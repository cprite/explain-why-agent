"""Stubbed-transport tests for the model generator (app/llm/generator.py). No network is used."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest
from pydantic import BaseModel

from app.config import Settings
from app.llm.generator import (
    CACHE_MISS_MESSAGE,
    METERLESS_TIMEOUT_SECONDS,
    Generator,
    MeterlessProvider,
    ResponseCache,
    normalise_base_url,
)
from app.trace import TraceWriter

TOKEN = "rt-test-secret-7f3a9c"
NVIDIA_KEY = "nvapi-test-secret-55d1"
METERLESS = "http://127.0.0.1:8088/v1"
NVIDIA = "https://nvidia.test/v1"


class Answer(BaseModel):
    answer: int
    word: str


Handler = Callable[[httpx.Request], httpx.Response]


def chat_reply(content: str, *, model: str = "meterless/auto", meterless: dict | None = None) -> dict:
    body: dict = {
        "id": "chatcmpl-1",
        "model": model,
        "choices": [{"index": 0, "message": {"role": "assistant", "content": content}}],
        "usage": {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18},
    }
    if meterless is not None:
        body["meterless"] = meterless
    return body


class Recorder:
    """A MockTransport handler that replays scripted responses per host and records requests."""

    def __init__(self, script: dict[str, list[httpx.Response | Exception]]) -> None:
        self.script = {host: list(items) for host, items in script.items()}
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        queue = self.script.get(request.url.host, [])
        if not queue:
            raise AssertionError(f"unexpected request {request.method} {request.url}")
        item = queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def bodies(self, host: str = "127.0.0.1") -> list[dict]:
        return [json.loads(r.content) for r in self.requests if r.url.host == host and r.method == "POST"]


def make_settings(tmp_path: Path, **overrides: object) -> Settings:
    values: dict[str, object] = {
        "sample_mode": False,
        "meterless_base_url": METERLESS,
        "meterless_runtime_token": TOKEN,
        "nvidia_api_key": NVIDIA_KEY,
        "nvidia_base_url": NVIDIA,
        "nvidia_model": "nvidia/test-model",
        "log_dir": str(tmp_path / "logs"),
        "llm_cache_dir": str(tmp_path / "cache"),
        "model_provider": "meterless",
        "meterless_model": "",
        "meterless_model_planner": "",
        "meterless_model_investigator": "",
        "meterless_model_critic": "",
        "meterless_model_reporter": "",
        "model_temperature": 0.2,
        "max_output_tokens": 512,
        "max_retries": 3,
        "record_cache": False,
    }
    values.update(overrides)
    return Settings(**values)


def make_generator(
    tmp_path: Path, recorder: Recorder, sleeps: list[float] | None = None, **overrides: object
) -> Generator:
    sleeps = sleeps if sleeps is not None else []
    return Generator(
        make_settings(tmp_path, **overrides),
        transport=httpx.MockTransport(recorder),
        sleep=sleeps.append,
        trace=TraceWriter(tmp_path / "logs", "gen-test"),
    )


MESSAGES = [{"role": "system", "content": "You answer arithmetic."}, {"role": "user", "content": "2+3?"}]
GOOD = '{"answer": 5, "word": "five"}'


# --- base URL normalisation -------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw",
    [
        "http://127.0.0.1:8088/v1",
        "http://127.0.0.1:8088/v1/",
        "http://127.0.0.1:8088",
        "http://127.0.0.1:8088/",
        "127.0.0.1:8088",
        "127.0.0.1:8088/v1",
        "http://127.0.0.1:8088/v1/chat/completions",
        "http://127.0.0.1:8088/v1/models",
        "http://127.0.0.1:8088/healthz",
        "127.0.0.1:8088/healthz",
        "http://127.0.0.1:8088/v1/v1",
        "HTTP://127.0.0.1:8088/v1/chat/completions/",
        "  http://127.0.0.1:8088/v1  ",
    ],
)
def test_normalise_base_url_every_form(raw: str) -> None:
    assert normalise_base_url(raw) == "http://127.0.0.1:8088/v1"


def test_normalise_keeps_https_and_host() -> None:
    assert normalise_base_url("https://box.example:9000/v1/models") == "https://box.example:9000/v1"
    assert normalise_base_url("") == "http://127.0.0.1:8088/v1"
    assert "/v1/v1" not in normalise_base_url("localhost:8090/v1/v1/chat/completions")


# --- status, headers, timeout -----------------------------------------------------------------


def models_response(*ids: str) -> httpx.Response:
    return httpx.Response(200, json={"object": "list", "data": [{"id": i, "object": "model"} for i in ids]})


def make_meterless(handler: Handler, token: str = TOKEN) -> MeterlessProvider:
    return MeterlessProvider(base_url="127.0.0.1:8088/healthz", token=token, transport=httpx.MockTransport(handler))


def test_status_online_from_models_keeps_unknown_meterless_ids() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return models_response("meterless/auto", "meterless/deep", "meterless/text.fusion-x", "gpt-other")

    status = make_meterless(handler).status()
    assert status.state == "online"
    assert status.models == ["meterless/auto", "meterless/deep", "meterless/text.fusion-x"]
    assert [r.url.path for r in seen] == ["/v1/models"]


@pytest.mark.parametrize("code", [401, 403])
def test_status_unauthorized(code: int) -> None:
    status = make_meterless(lambda r: httpx.Response(code, json={"error": "bad token"})).status()
    assert status.state == "unauthorized"


def test_status_offline_on_connection_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    assert make_meterless(handler).status().state == "offline"


def test_status_offline_on_other_answers() -> None:
    assert make_meterless(lambda r: httpx.Response(500)).status().state == "offline"
    assert make_meterless(lambda r: models_response("not-meterless")).status().state == "offline"


def test_headers_sent_as_specified(tmp_path: Path) -> None:
    rec = Recorder({"127.0.0.1": [models_response("meterless/auto"), httpx.Response(200, json=chat_reply(GOOD))]})
    gen = make_generator(tmp_path, rec)
    assert gen.meterless.status().state == "online"
    result = gen(MESSAGES, schema=Answer, role="planner")
    assert result.ok
    models_req, chat_req = rec.requests
    for request in (models_req, chat_req):
        assert request.headers["Authorization"] == f"Bearer {TOKEN}"
        assert request.headers["meterless-app"] == "explain-why"
    assert "meterless-scope" not in models_req.headers
    assert chat_req.headers["meterless-scope"] == "user"
    assert chat_req.url.path == "/v1/chat/completions"


def test_meterless_timeout_is_180_seconds(tmp_path: Path) -> None:
    gen = make_generator(tmp_path, Recorder({}))
    timeout = gen.meterless.client.timeout
    assert METERLESS_TIMEOUT_SECONDS == 180.0
    assert timeout.connect == timeout.read == timeout.write == timeout.pool == 180.0


def test_placeholder_token_is_rejected_without_a_call(tmp_path: Path) -> None:
    rec = Recorder({})
    gen = make_generator(tmp_path, rec, meterless_runtime_token="rt-local", nvidia_api_key="")
    assert gen.meterless.configured is False
    result = gen(MESSAGES, schema=Answer, role="planner")
    assert not result.ok
    assert result.error["code"] == "not_configured"
    assert rec.requests == []


def test_role_models_and_request_settings(tmp_path: Path) -> None:
    rec = Recorder({"127.0.0.1": [httpx.Response(200, json=chat_reply(GOOD))] * 3})
    gen = make_generator(tmp_path, rec, model_temperature=0.0, max_output_tokens=99, meterless_model_critic="meterless/judge.deep")
    gen(MESSAGES, role="planner")
    gen(MESSAGES, role="investigator")
    gen(MESSAGES, role="critic")
    bodies = rec.bodies()
    assert [b["model"] for b in bodies] == ["meterless/deep", "meterless/fast", "meterless/judge.deep"]
    assert all(b["temperature"] == 0.0 and b["max_tokens"] == 99 for b in bodies)
    assert make_generator(tmp_path, rec, meterless_model="meterless/auto").model_for("planner") == "meterless/auto"


# --- JSON mode ----------------------------------------------------------------------------------


def test_valid_json_reply_passes(tmp_path: Path) -> None:
    rec = Recorder({"127.0.0.1": [httpx.Response(200, json=chat_reply("```json\n" + GOOD + "\n```"))]})
    result = make_generator(tmp_path, rec)(MESSAGES, schema=Answer, role="investigator")
    assert result.ok and result.parsed == {"answer": 5, "word": "five"}
    assert result.repaired is False
    assert len(rec.requests) == 1
    system = rec.bodies()[0]["messages"][0]["content"]
    assert "JSON Schema for Answer" in system and "You answer arithmetic." in system


def test_invalid_json_triggers_exactly_one_repair(tmp_path: Path) -> None:
    rec = Recorder(
        {
            "127.0.0.1": [
                httpx.Response(200, json=chat_reply('{"answer": "five"}')),
                httpx.Response(200, json=chat_reply(GOOD)),
            ]
        }
    )
    result = make_generator(tmp_path, rec)(MESSAGES, schema=Answer, role="investigator")
    assert result.ok and result.repaired and result.parsed["answer"] == 5
    assert len(rec.requests) == 2
    repair_turn = rec.bodies()[1]["messages"][-1]
    assert repair_turn["role"] == "user"
    assert "answer" in repair_turn["content"] and "word" in repair_turn["content"]


def test_second_invalid_reply_returns_structured_error(tmp_path: Path) -> None:
    rec = Recorder(
        {"127.0.0.1": [httpx.Response(200, json=chat_reply("not json")), httpx.Response(200, json=chat_reply("{bad"))]}
    )
    result = make_generator(tmp_path, rec)(MESSAGES, schema=Answer, role="investigator")
    assert result.ok is False
    assert result.error["code"] == "invalid_json"
    assert "Answer" in result.error["message"]
    assert len(rec.requests) == 2


# --- retries and fallback ------------------------------------------------------------------------


def test_429_retry_sequence_then_success(tmp_path: Path) -> None:
    # No fallback configured, so Meterless may use all MAX_MODEL_ATTEMPTS=3 requests (two retries).
    sleeps: list[float] = []
    rec = Recorder(
        {"127.0.0.1": [httpx.Response(429), httpx.Response(503), httpx.Response(200, json=chat_reply(GOOD))]}
    )
    result = make_generator(tmp_path, rec, sleeps, nvidia_api_key="")(MESSAGES, schema=Answer, role="planner")
    assert result.ok and result.provider == "meterless"
    assert sleeps == [2.0, 4.0]
    assert result.retries == 2


def test_retries_exhausted_falls_back_to_nvidia(tmp_path: Path) -> None:
    sleeps: list[float] = []
    rec = Recorder(
        {
            "127.0.0.1": [httpx.Response(429)] * 2,
            "nvidia.test": [httpx.Response(200, json=chat_reply(GOOD, model="nvidia/test-model"))],
        }
    )
    result = make_generator(tmp_path, rec, sleeps)(MESSAGES, schema=Answer, role="planner")
    assert sleeps == [2.0]  # Meterless keeps the third of MAX_MODEL_ATTEMPTS=3 for the fallback
    assert result.ok and result.provider == "nvidia"
    assert [a["provider"] for a in result.attempts] == ["meterless", "nvidia"]
    assert result.attempts[0]["status"] == "retries_exhausted"


def test_meterless_offline_falls_back_to_nvidia(tmp_path: Path) -> None:
    rec = Recorder(
        {
            "127.0.0.1": [httpx.ConnectError("refused")],
            "nvidia.test": [httpx.Response(200, json=chat_reply(GOOD, model="nvidia/test-model"))],
        }
    )
    result = make_generator(tmp_path, rec)(MESSAGES, schema=Answer, role="planner")
    assert result.ok
    assert result.provider == "nvidia"
    assert result.model_routed == "nvidia/test-model"
    assert result.attempts[0]["status"] == "offline"
    nvidia_request = rec.requests[-1]
    assert nvidia_request.headers["Authorization"] == f"Bearer {NVIDIA_KEY}"
    assert "meterless-app" not in nvidia_request.headers
    assert json.loads(nvidia_request.content)["model"] == "nvidia/test-model"
    trace = TraceWriter(tmp_path / "logs", "gen-test").read()
    assert [line["provider"] for line in trace] == ["meterless", "nvidia"]
    assert trace[1]["fallback"] is True


def test_unauthorized_meterless_does_not_fall_back(tmp_path: Path) -> None:
    rec = Recorder({"127.0.0.1": [httpx.Response(401)]})
    result = make_generator(tmp_path, rec)(MESSAGES, role="planner")
    assert result.ok is False and result.error["code"] == "unauthorized"
    assert all(r.url.host == "127.0.0.1" for r in rec.requests)


def test_no_fallback_configured_returns_structured_error(tmp_path: Path) -> None:
    rec = Recorder({"127.0.0.1": [httpx.ConnectError("refused")]})
    result = make_generator(tmp_path, rec, nvidia_api_key="")(MESSAGES, role="planner")
    assert result.ok is False and result.error["code"] == "offline"


def test_routed_model_and_receipt_captured(tmp_path: Path) -> None:
    reply = chat_reply(
        GOOD,
        model="meterless/deep",
        meterless={"routed_model": "nvidia/nemotron-3.5-super-vl-120b-a12b", "receipt_id": "rcpt_123"},
    )
    rec = Recorder({"127.0.0.1": [httpx.Response(200, json=reply)]})
    result = make_generator(tmp_path, rec)(MESSAGES, schema=Answer, role="planner")
    assert result.model_requested == "meterless/deep"
    assert result.model_routed == "nvidia/nemotron-3.5-super-vl-120b-a12b"
    assert result.receipt_id == "rcpt_123"
    assert result.usage["total_tokens"] == 18
    line = TraceWriter(tmp_path / "logs", "gen-test").read()[0]
    assert line["model_routed"] == "nvidia/nemotron-3.5-super-vl-120b-a12b"
    assert line["receipt_id"] == "rcpt_123"
    assert line["tokens"]["total_tokens"] == 18
    for key in ("timestamp", "agent", "action", "provider", "model_requested", "duration_ms", "status", "retry_count"):
        assert key in line


def test_receipt_in_nested_block_or_header(tmp_path: Path) -> None:
    nested = chat_reply(GOOD, meterless={"routed_model": "m", "receipt": {"id": "rcpt_nested"}})
    rec = Recorder(
        {
            "127.0.0.1": [
                httpx.Response(200, json=nested),
                httpx.Response(200, json=chat_reply(GOOD), headers={"meterless-receipt": "rcpt_hdr"}),
            ]
        }
    )
    gen = make_generator(tmp_path, rec)
    assert gen(MESSAGES).receipt_id == "rcpt_nested"
    assert gen(MESSAGES).receipt_id == "rcpt_hdr"


# --- sample-mode cache ---------------------------------------------------------------------------

FIXTURE_CACHE = Path(__file__).parent / "fixtures" / "llm_cache"


def test_cache_hit_returns_reply_without_network(tmp_path: Path) -> None:
    rec = Recorder({})
    gen = make_generator(tmp_path, rec, sample_mode=True, llm_cache_dir=str(FIXTURE_CACHE))
    result = gen(MESSAGES, schema=Answer, role="investigator")
    assert result.ok, result.error
    assert result.from_cache and result.provider == "cache"
    assert result.parsed == {"answer": 5, "word": "five"}
    assert result.model_routed == "fixture-model"
    assert rec.requests == []


def test_cache_key_ignores_whitespace_but_not_role_or_schema() -> None:
    base = ResponseCache.key(MESSAGES, "Answer", "investigator")
    spaced = [{"role": m["role"], "content": "  " + m["content"].replace(" ", "   ") + "\n"} for m in MESSAGES]
    assert ResponseCache.key(spaced, "Answer", "investigator") == base
    assert ResponseCache.key(MESSAGES, "Answer", "planner") != base
    assert ResponseCache.key(MESSAGES, None, "investigator") != base


def test_cache_miss_returns_structured_error(tmp_path: Path) -> None:
    rec = Recorder({})
    gen = make_generator(tmp_path, rec, sample_mode=True, llm_cache_dir=str(FIXTURE_CACHE))
    result = gen([{"role": "user", "content": "a question nobody recorded"}], schema=Answer, role="planner")
    assert result.ok is False
    assert result.error == {"code": "cache_miss", "message": CACHE_MISS_MESSAGE}
    assert "needs a model key" in result.error["message"]
    assert rec.requests == []


def test_recorder_writes_entries_that_sample_mode_replays(tmp_path: Path) -> None:
    reply = chat_reply(GOOD, meterless={"routed_model": "nemotron-x", "receipt_id": "r1"})
    rec = Recorder({"127.0.0.1": [httpx.Response(200, json=reply)]})
    live = make_generator(tmp_path, rec, record_cache=True)
    assert live(MESSAGES, schema=Answer, role="planner").ok
    files = list((tmp_path / "cache").glob("*.json"))
    assert len(files) == 1
    entry = json.loads(files[0].read_text())
    assert entry["recorded_with"] == "meterless" and entry["model_routed"] == "nemotron-x"

    replay = make_generator(tmp_path, Recorder({}), sample_mode=True)
    result = replay(MESSAGES, schema=Answer, role="planner")
    assert result.ok and result.from_cache and result.parsed["word"] == "five"


# --- secrets ------------------------------------------------------------------------------------


def test_no_secret_in_trace_or_cache(tmp_path: Path) -> None:
    rec = Recorder(
        {
            "127.0.0.1": [httpx.Response(200, json=chat_reply("nope")), httpx.Response(401), httpx.ConnectError("x")],
            "nvidia.test": [httpx.Response(200, json=chat_reply(GOOD))],
        }
    )
    gen = make_generator(tmp_path, rec, record_cache=True)
    assert gen(MESSAGES, schema=Answer, role="planner").error["code"] == "unauthorized"  # repair hits 401
    assert gen(MESSAGES, schema=Answer, role="reporter").provider == "nvidia"  # offline -> fallback
    written = (tmp_path / "logs" / "trace-gen-test.jsonl").read_text()
    written += "".join(p.read_text() for p in (tmp_path / "cache").glob("*.json"))
    assert written
    assert TOKEN not in written
    assert NVIDIA_KEY not in written


def test_generate_never_raises(tmp_path: Path) -> None:
    def explode(request: httpx.Request) -> httpx.Response:
        raise RuntimeError("transport bug")

    gen = Generator(make_settings(tmp_path), transport=httpx.MockTransport(explode), sleep=lambda s: None)
    result = gen(MESSAGES, schema=Answer, role="planner", run_id="boom")
    assert result.ok is False
    assert result.error["code"] == "internal"


def test_live_check_skips_without_credentials() -> None:
    import os
    import subprocess
    import sys

    root = Path(__file__).resolve().parents[1]
    env = {k: v for k, v in os.environ.items() if not k.startswith(("METERLESS_", "NVIDIA_"))}
    for args, needle in (([], "METERLESS_RUNTIME_TOKEN"), (["--provider", "nvidia"], "NVIDIA_API_KEY")):
        out = subprocess.run(
            [sys.executable, "scripts/live_check.py", *args], cwd=root, env=env, capture_output=True, text=True, check=False
        )
        assert out.returncode == 0, out.stderr
        assert out.stdout.startswith("SKIP:") and needle in out.stdout
