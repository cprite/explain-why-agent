"""Model generator: one OpenAI-compatible function used by every agent (architecture §6).

    generate(messages, *, schema=None, role="planner", run_id="r1") -> GenerationResult

- Primary provider: Meterless Runtime (Nightshift), implemented to the official provider contract
  (`docs/research/meterless-power-prompts-2026-10-19.md`): base URL normalised to `<host>/v1`,
  `Authorization: Bearer <runtime token>` on every call (the placeholder `rt-local` is refused),
  `meterless-app: explain-why` on every request, `meterless-scope: user` on chat, routing-mode
  model ids (`meterless/auto`, `meterless/deep`, ...) read from `GET /v1/models`, status decided by
  `GET /v1/models`, 180 s timeout. The reply's `meterless.routed_model` and receipt id are recorded.
- Fallback provider: NVIDIA's hosted API directly, used only when Meterless is offline (connection
  error or timeout) or its retries are exhausted. An unauthorized Meterless token is reported, not
  silently bypassed.
- Retries: 429 and 5xx are retried after 2 s, 4 s and 8 s (capped by `MAX_RETRIES`).
- JSON mode: with `schema` (a pydantic model class) the reply is parsed and validated; on failure
  one repair call sends the validation error back; a second failure is a structured error.
- Sample mode: replies come from a per-call cache under `data/sample/llm_cache/`, keyed by a hash of
  the normalised request (messages, schema name, role); a miss is a structured error. With
  `RECORD_CACHE=true` in live mode every reply is written to that cache.
- Every provider call (and every cache lookup) is one line in `logs/trace-<run_id>.jsonl`.

No exception escapes `generate`: every failure comes back as `GenerationResult(ok=False, error=...)`.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, Protocol
from urllib.parse import urlsplit, urlunsplit

import httpx
from pydantic import BaseModel, ValidationError

from app.config import Settings, get_settings, resolve_path
from app.schemas import validation_summary
from app.trace import TraceWriter, summarise

METERLESS_PROVIDER_ID = "meterless"
METERLESS_DEFAULT_BASE_URL = "http://127.0.0.1:8088/v1"
METERLESS_APP_ID = "explain-why"
METERLESS_TIMEOUT_SECONDS = 180.0
PLACEHOLDER_TOKENS = frozenset({"rt-local"})
NVIDIA_PROVIDER_ID = "nvidia"
NVIDIA_DEFAULT_BASE_URL = "https://integrate.api.nvidia.com/v1"
RETRY_DELAYS_SECONDS: tuple[float, ...] = (2.0, 4.0, 8.0)
DEFAULT_MODEL = "meterless/auto"
ROLE_DEFAULT_MODELS: dict[str, str] = {
    "planner": "meterless/deep",
    "reporter": "meterless/deep",
    "investigator": "meterless/fast",
    "critic": "meterless/fast",
}
CACHE_MISS_MESSAGE = (
    "this question needs a model key: no recorded reply for this request in the sample-mode cache. "
    "Set SAMPLE_MODE=false with METERLESS_RUNTIME_TOKEN (or NVIDIA_API_KEY) to run it live."
)
FALLBACK_CODES = frozenset({"offline", "timeout", "retries_exhausted"})

Message = dict[str, Any]
ProviderState = Literal["online", "unauthorized", "offline"]


def normalise_base_url(url: str | None) -> str:
    """Normalise a pasted Meterless URL to `<scheme>://<host>/v1`.

    Accepts the URL with or without a scheme, and with `/v1`, `/v1/chat/completions`, `/v1/models`
    or `/healthz` on the end. Never produces `/v1/v1`.
    """
    text = (url or "").strip() or METERLESS_DEFAULT_BASE_URL
    if "://" not in text:
        text = "http://" + text.lstrip("/")
    parts = urlsplit(text)
    path = parts.path.rstrip("/")
    changed = True
    while changed:
        changed = False
        for suffix in ("/chat/completions", "/models", "/healthz", "/v1"):
            if path.lower().endswith(suffix):
                path = path[: -len(suffix)].rstrip("/")
                changed = True
    return urlunsplit((parts.scheme.lower(), parts.netloc, path + "/v1", "", ""))


def meterless_token_usable(token: str | None) -> bool:
    """True when a runtime token is set and is not the placeholder the runtime rejects."""
    value = (token or "").strip()
    return bool(value) and value not in PLACEHOLDER_TOKENS


@dataclass
class ProviderStatus:
    """Meterless status as decided by `GET /v1/models`."""

    state: ProviderState
    models: list[str] = field(default_factory=list)
    reason: str = ""


@dataclass
class GenerationResult:
    """What a `generate` call returns. `error` is `{code, message}` when `ok` is false."""

    ok: bool
    content: str | None = None
    parsed: dict[str, Any] | None = None
    provider: str | None = None
    model_requested: str | None = None
    model_routed: str | None = None
    receipt_id: str | None = None
    usage: dict[str, Any] | None = None
    retries: int = 0
    repaired: bool = False
    from_cache: bool = False
    duration_ms: float = 0.0
    attempts: list[dict[str, Any]] = field(default_factory=list)
    error: dict[str, str] | None = None

    def to_dict(self) -> dict[str, Any]:
        """Plain-dict form."""
        return asdict(self)


class GenerateFn(Protocol):
    """The injected generator signature every agent takes."""

    def __call__(
        self,
        messages: list[Message],
        *,
        schema: type[BaseModel] | None = None,
        role: str = "default",
        run_id: str | None = None,
    ) -> GenerationResult: ...


class ProviderError(Exception):
    """A provider call failed. `code` decides whether the generator falls back."""

    def __init__(self, code: str, message: str, retries: int = 0, status_code: int | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.retries = retries
        self.status_code = status_code


@dataclass
class ProviderReply:
    """A successful chat completion."""

    content: str
    model_routed: str | None
    receipt_id: str | None
    usage: dict[str, Any] | None
    retries: int


def _content_text(message: dict[str, Any]) -> str:
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") in ("text", None)]
        return "".join(part for part in parts if isinstance(part, str))
    return ""


class OpenAICompatibleProvider:
    """A chat-completions provider over httpx with the shared retry policy."""

    name = "openai-compatible"

    def __init__(
        self,
        *,
        base_url: str,
        token: str,
        timeout: float,
        transport: httpx.BaseTransport | None = None,
        max_retries: int = 3,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._token = token
        self.timeout = timeout
        self.max_retries = max(0, min(max_retries, len(RETRY_DELAYS_SECONDS)))
        self._sleep = sleep
        self.client = httpx.Client(timeout=httpx.Timeout(timeout), transport=transport)

    @property
    def configured(self) -> bool:
        """Whether the provider has what it needs to make a call."""
        return bool(self._token)

    def headers(self, *, chat: bool) -> dict[str, str]:
        """Headers for one request (the token is only ever placed here)."""
        return {"Authorization": f"Bearer {self._token}", "Content-Type": "application/json"}

    def _reply_metadata(self, data: dict[str, Any], response: httpx.Response) -> tuple[str | None, str | None]:
        model = data.get("model")
        return (model if isinstance(model, str) else None), None

    def chat(
        self, messages: list[Message], *, model: str, temperature: float, max_tokens: int
    ) -> ProviderReply:
        """POST /chat/completions with retries on 429/5xx; raises `ProviderError` on failure."""
        if not self.configured:
            raise ProviderError("not_configured", f"{self.name} is not configured")
        body = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        retries = 0
        while True:
            try:
                response = self.client.post(
                    f"{self.base_url}/chat/completions", json=body, headers=self.headers(chat=True)
                )
            except httpx.TimeoutException as exc:
                raise ProviderError("timeout", f"{self.name} timed out: {type(exc).__name__}", retries) from exc
            except httpx.HTTPError as exc:
                raise ProviderError("offline", f"{self.name} unreachable: {type(exc).__name__}", retries) from exc

            status = response.status_code
            if status == 429 or status >= 500:
                if retries < self.max_retries:
                    self._sleep(RETRY_DELAYS_SECONDS[retries])
                    retries += 1
                    continue
                raise ProviderError(
                    "retries_exhausted",
                    f"{self.name} returned HTTP {status} after {retries} retries",
                    retries,
                    status,
                )
            if status in (401, 403):
                raise ProviderError("unauthorized", f"{self.name} rejected the token (HTTP {status})", retries, status)
            if status >= 400:
                raise ProviderError("http_error", f"{self.name} returned HTTP {status}", retries, status)
            try:
                data = response.json()
                message = data["choices"][0]["message"]
            except (ValueError, KeyError, IndexError, TypeError) as exc:
                raise ProviderError("bad_response", f"{self.name} sent an unreadable reply", retries) from exc
            routed, receipt = self._reply_metadata(data, response)
            usage = data.get("usage") if isinstance(data.get("usage"), dict) else None
            return ProviderReply(_content_text(message), routed, receipt, usage, retries)


class MeterlessProvider(OpenAICompatibleProvider):
    """Meterless Runtime (Nightshift), provider id `meterless`."""

    name = METERLESS_PROVIDER_ID

    def __init__(self, *, base_url: str, token: str, **kwargs: Any) -> None:
        kwargs.setdefault("timeout", METERLESS_TIMEOUT_SECONDS)
        super().__init__(base_url=normalise_base_url(base_url), token=token.strip(), **kwargs)

    @property
    def configured(self) -> bool:
        return meterless_token_usable(self._token)

    def headers(self, *, chat: bool) -> dict[str, str]:
        headers = super().headers(chat=chat)
        headers["meterless-app"] = METERLESS_APP_ID
        if chat:
            headers["meterless-scope"] = "user"
        return headers

    def _reply_metadata(self, data: dict[str, Any], response: httpx.Response) -> tuple[str | None, str | None]:
        block = data.get("meterless") if isinstance(data.get("meterless"), dict) else {}
        routed = block.get("routed_model") or data.get("model")
        receipt = block.get("receipt_id")
        if receipt is None:
            raw = block.get("receipt")
            receipt = raw.get("id") if isinstance(raw, dict) else raw
        if receipt is None:
            receipt = response.headers.get("meterless-receipt") or response.headers.get("x-meterless-receipt")
        return (str(routed) if routed else None), (str(receipt) if receipt else None)

    def status(self) -> ProviderStatus:
        """Decide online / unauthorized / offline from `GET /v1/models` (never `/healthz`)."""
        try:
            response = self.client.get(f"{self.base_url}/models", headers=self.headers(chat=False))
        except httpx.HTTPError as exc:
            return ProviderStatus("offline", reason=f"unreachable: {type(exc).__name__}")
        if response.status_code in (401, 403):
            return ProviderStatus("unauthorized", reason=f"HTTP {response.status_code}: paste a runtime token")
        if response.status_code != 200:
            return ProviderStatus("offline", reason=f"HTTP {response.status_code}")
        try:
            rows = response.json().get("data", [])
        except (ValueError, AttributeError):
            return ProviderStatus("offline", reason="unreadable /v1/models reply")
        models = [
            row.get("id") for row in rows if isinstance(row, dict) and str(row.get("id", "")).startswith("meterless/")
        ]
        if not models:
            return ProviderStatus("offline", reason="no meterless/* models listed")
        return ProviderStatus("online", models=models, reason="ok")

    def list_models(self) -> list[str]:
        """Routing-mode model ids from `GET /v1/models`, unknown `meterless/*` ids kept."""
        return self.status().models


class NvidiaProvider(OpenAICompatibleProvider):
    """NVIDIA's hosted OpenAI-compatible API, used directly as the fallback."""

    name = NVIDIA_PROVIDER_ID

    def __init__(self, *, model: str, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.model = model

    @property
    def configured(self) -> bool:
        return bool(self._token) and bool(self.model)


class ResponseCache:
    """Per-call model reply cache for sample mode (architecture §10)."""

    def __init__(self, directory: Path | str) -> None:
        self.directory = Path(directory)

    @staticmethod
    def key(messages: list[Message], schema_name: str | None, role: str) -> str:
        """Provider-independent hash of the normalised request."""
        normalised = {
            "messages": [
                {"role": str(m.get("role", "")), "content": " ".join(str(m.get("content", "")).split())}
                for m in messages
            ],
            "schema": schema_name,
            "role": role,
        }
        payload = json.dumps(normalised, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def path(self, key: str) -> Path:
        """File holding one entry."""
        return self.directory / f"{key}.json"

    def get(self, key: str) -> dict[str, Any] | None:
        """Return the cached entry or None."""
        path = self.path(key)
        if not path.is_file():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def put(self, key: str, entry: dict[str, Any]) -> Path:
        """Write one entry (used by the recorder)."""
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self.path(key)
        path.write_text(json.dumps({"key": key, **entry}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return path


def _json_instruction(schema: type[BaseModel]) -> str:
    return (
        "Reply with exactly one JSON object and nothing else (no prose, no code fences). "
        f"It must validate against this JSON Schema for {schema.__name__}:\n"
        + json.dumps(schema.model_json_schema(), separators=(",", ":"))
    )


def _with_json_instruction(messages: list[Message], schema: type[BaseModel]) -> list[Message]:
    instruction = _json_instruction(schema)
    out = [dict(m) for m in messages]
    if out and out[0].get("role") == "system":
        out[0]["content"] = f"{out[0].get('content', '')}\n\n{instruction}"
    else:
        out.insert(0, {"role": "system", "content": instruction})
    return out


_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)


def parse_json_reply(content: str, schema: type[BaseModel]) -> tuple[dict[str, Any] | None, str | None]:
    """Parse and validate a reply; return `(parsed, None)` or `(None, readable error)`."""
    text = _FENCE_RE.sub("", (content or "").strip()).strip()
    if not text.startswith("{"):
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            return None, "the reply contains no JSON object"
        text = text[start : end + 1]
    try:
        obj = json.loads(text)
    except json.JSONDecodeError as exc:
        return None, f"invalid JSON: {exc.msg} at line {exc.lineno} column {exc.colno}"
    try:
        model = schema.model_validate(obj)
    except ValidationError as exc:
        return None, f"does not match {schema.__name__}: {validation_summary(exc)}"
    return model.model_dump(mode="json"), None


class Generator:
    """The injected generator. Call it like a function: `generator(messages, schema=..., role=...)`."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        trace: TraceWriter | None = None,
        cache: ResponseCache | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        s = self.settings
        self.sample_mode = s.sample_mode
        self.record_cache = s.record_cache and not s.sample_mode
        self.cache = cache or ResponseCache(resolve_path(s.llm_cache_dir))
        self._trace = trace
        self._traces: dict[str, TraceWriter] = {}
        self.meterless = MeterlessProvider(
            base_url=s.meterless_base_url,
            token=s.meterless_runtime_token,
            transport=transport,
            max_retries=s.max_retries,
            sleep=sleep,
        )
        self.nvidia = NvidiaProvider(
            base_url=s.nvidia_base_url or NVIDIA_DEFAULT_BASE_URL,
            token=s.nvidia_api_key,
            model=s.nvidia_model,
            timeout=float(s.model_timeout_seconds),
            transport=transport,
            max_retries=s.max_retries,
            sleep=sleep,
        )

    def model_for(self, role: str) -> str:
        """Meterless routing mode for a role: per-role override, then METERLESS_MODEL, then the role default."""
        override = getattr(self.settings, f"meterless_model_{role}", "") if role else ""
        return override or self.settings.meterless_model or ROLE_DEFAULT_MODELS.get(role, DEFAULT_MODEL)

    def _trace_for(self, run_id: str | None) -> TraceWriter | None:
        if self._trace is not None:
            return self._trace
        if not run_id:
            return None
        if run_id not in self._traces:
            self._traces[run_id] = TraceWriter(resolve_path(self.settings.log_dir), run_id)
        return self._traces[run_id]

    def __call__(
        self,
        messages: list[Message],
        *,
        schema: type[BaseModel] | None = None,
        role: str = "default",
        run_id: str | None = None,
    ) -> GenerationResult:
        """Generate one reply; see the module docstring. Never raises."""
        started = time.perf_counter()
        trace = self._trace_for(run_id)
        try:
            first = self._complete(messages, schema=schema, role=role, trace=trace, repair=False)
            if not first.ok or schema is None:
                return self._finish(first, started)
            parsed, problem = parse_json_reply(first.content or "", schema)
            if parsed is not None:
                first.parsed = parsed
                return self._finish(first, started)
            repair_messages = [
                *messages,
                {"role": "assistant", "content": first.content or ""},
                {
                    "role": "user",
                    "content": f"Your reply was rejected: {problem}. "
                    "Send the corrected reply as one JSON object only.",
                },
            ]
            second = self._complete(repair_messages, schema=schema, role=role, trace=trace, repair=True)
            second.repaired = True
            second.retries += first.retries
            second.attempts = first.attempts + second.attempts
            if not second.ok:
                return self._finish(second, started)
            parsed, problem2 = parse_json_reply(second.content or "", schema)
            if parsed is None:
                second.ok = False
                second.error = {
                    "code": "invalid_json",
                    "message": f"reply failed {schema.__name__} validation twice: {problem2}",
                }
                return self._finish(second, started)
            second.parsed = parsed
            return self._finish(second, started)
        except Exception as exc:  # noqa: BLE001 - the contract is that nothing escapes to agents
            result = GenerationResult(ok=False, error={"code": "internal", "message": f"{type(exc).__name__}: {exc}"})
            return self._finish(result, started)

    generate = __call__

    @staticmethod
    def _finish(result: GenerationResult, started: float) -> GenerationResult:
        result.duration_ms = (time.perf_counter() - started) * 1000.0
        return result

    def _complete(
        self,
        messages: list[Message],
        *,
        schema: type[BaseModel] | None,
        role: str,
        trace: TraceWriter | None,
        repair: bool,
    ) -> GenerationResult:
        """One logical model call: cache in sample mode, otherwise provider chain with fallback."""
        schema_name = schema.__name__ if schema else None
        key = ResponseCache.key(messages, schema_name, role)
        model = self.model_for(role)
        last_user = next((m.get("content") for m in reversed(messages) if m.get("role") == "user"), "")

        def log(provider: str, status: str, **fields: Any) -> dict[str, Any]:
            record = {
                "provider": provider,
                "model_requested": fields.pop("model_requested", model),
                "status": status,
                **fields,
            }
            if trace is not None:
                trace.write(
                    agent=role,
                    action="model_repair_call" if repair else "model_call",
                    target=None,
                    input_summary=last_user,
                    output_summary=fields.get("content_summary"),
                    status=status,
                    retry_count=fields.get("retries", 0),
                    schema=schema_name,
                    cache_key=key,
                    **{k: v for k, v in record.items() if k not in ("status", "content_summary")},
                )
            return record

        if self.sample_mode:
            entry = self.cache.get(key)
            if entry is None:
                attempt = log("cache", "cache_miss", model_routed=None, duration_ms=0.0, tokens=None, retries=0)
                return GenerationResult(
                    ok=False,
                    provider="cache",
                    model_requested=model,
                    from_cache=True,
                    attempts=[attempt],
                    error={"code": "cache_miss", "message": CACHE_MISS_MESSAGE},
                )
            content = str(entry.get("reply", ""))
            attempt = log(
                "cache",
                "ok",
                model_routed=entry.get("model_routed"),
                receipt_id=entry.get("receipt_id"),
                recorded_with=entry.get("recorded_with"),
                duration_ms=0.0,
                tokens=entry.get("usage"),
                retries=0,
                content_summary=summarise(content),
            )
            return GenerationResult(
                ok=True,
                content=content,
                provider="cache",
                model_requested=model,
                model_routed=entry.get("model_routed"),
                receipt_id=entry.get("receipt_id"),
                usage=entry.get("usage"),
                from_cache=True,
                attempts=[attempt],
            )

        prepared = _with_json_instruction(messages, schema) if schema else [dict(m) for m in messages]
        chain: list[tuple[OpenAICompatibleProvider, str]] = []
        if self.settings.model_provider == NVIDIA_PROVIDER_ID:
            chain.append((self.nvidia, self.nvidia.model))
        else:
            chain.append((self.meterless, model))
            chain.append((self.nvidia, self.nvidia.model))

        attempts: list[dict[str, Any]] = []
        total_retries = 0
        last_error: ProviderError | None = None
        for index, (provider, provider_model) in enumerate(chain):
            # Fallback only when the primary is offline or its retries are exhausted.
            if index > 0 and (
                last_error is None or last_error.code not in FALLBACK_CODES or not provider.configured
            ):
                break
            call_started = time.perf_counter()
            try:
                reply = provider.chat(
                    prepared,
                    model=provider_model,
                    temperature=self.settings.model_temperature,
                    max_tokens=self.settings.max_output_tokens,
                )
            except ProviderError as exc:
                last_error = exc
                total_retries += exc.retries
                attempts.append(
                    log(
                        provider.name,
                        exc.code,
                        model_requested=provider_model,
                        model_routed=None,
                        duration_ms=round((time.perf_counter() - call_started) * 1000.0, 1),
                        tokens=None,
                        retries=exc.retries,
                        error=exc.message,
                    )
                )
                continue
            total_retries += reply.retries
            attempts.append(
                log(
                    provider.name,
                    "ok",
                    model_requested=provider_model,
                    model_routed=reply.model_routed,
                    receipt_id=reply.receipt_id,
                    duration_ms=round((time.perf_counter() - call_started) * 1000.0, 1),
                    tokens=reply.usage,
                    retries=reply.retries,
                    fallback=index > 0,
                    content_summary=summarise(reply.content),
                )
            )
            if self.record_cache:
                self.cache.put(
                    key,
                    {
                        "role": role,
                        "schema": schema_name,
                        "messages": messages,
                        "reply": reply.content,
                        "provider": provider.name,
                        "model_requested": provider_model,
                        "model_routed": reply.model_routed,
                        "receipt_id": reply.receipt_id,
                        "usage": reply.usage,
                        "recorded_with": provider.name,
                        "recorded_at": datetime.now(UTC).isoformat(),
                    },
                )
            return GenerationResult(
                ok=True,
                content=reply.content,
                provider=provider.name,
                model_requested=provider_model,
                model_routed=reply.model_routed,
                receipt_id=reply.receipt_id,
                usage=reply.usage,
                retries=total_retries,
                attempts=attempts,
            )

        error = last_error or ProviderError("not_configured", "no model provider is configured")
        return GenerationResult(
            ok=False,
            provider=attempts[-1]["provider"] if attempts else None,
            model_requested=model,
            retries=total_retries,
            attempts=attempts,
            error={"code": error.code, "message": error.message},
        )


def build_generator(settings: Settings | None = None, **kwargs: Any) -> Generator:
    """Construct the default generator from the environment."""
    return Generator(settings, **kwargs)
