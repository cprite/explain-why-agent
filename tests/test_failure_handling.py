"""Sprint 14: failure handling and sample mode (build-plan task 20, docs/sprints/14-failure-handling.md).

One section per acceptance criterion of issue #29: query repair, model retries and fallback with the
three-attempt cap, Zetaris fallback, sample mode with the network blocked, the Meterless token
aliases, the API carry-overs and the fixed caps. No test opens a network connection: model calls go
to an `httpx.MockTransport` or the committed per-call cache, Zetaris calls to a MockTransport.
"""

from __future__ import annotations

import ipaddress
import json
import socket
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from test_generator import (
    GOOD,
    MESSAGES,
    NVIDIA_KEY,
    TOKEN,
    Answer,
    Recorder,
    chat_reply,
    make_generator,
)

import app.api.main as api
import run as run_cli
from app.agents.investigator import MAX_SQL_REPAIRS
from app.config import Settings
from app.data.layer import DataLayer, QueryError, QueryOutcome, SourceInfo
from app.data.local import LocalDataLayer
from app.data.zetaris import FALLBACK_ADAPTER, ZetarisClient
from app.llm.generator import (
    CACHE_MISS_MESSAGE,
    MAX_MODEL_ATTEMPTS,
    METERLESS_TIMEOUT_SECONDS,
    RETRY_DELAYS_SECONDS,
    Generator,
)
from app.llm.stub import ScriptedModel
from app.loop import run_investigation
from app.schemas import Result, validate_result_file
from app.trace import TraceWriter

ROOT = Path(__file__).resolve().parents[1]
DAY1 = "Why did order volume spike on 24 November 2017?"
PLAN_CHECK_J = "Why did delivery lateness spike for deliveries completed the week of 28 May 2018?"
UNRECORDED = "Why did review scores fall in March 2018?"


def trace_of(log_dir: Path, run_id: str) -> list[dict[str, Any]]:
    return TraceWriter(log_dir, run_id).read()


@pytest.fixture
def clean_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """No settings variable set (an empty .env), sample mode on, logs under tmp_path."""
    for key in Settings.model_fields:
        monkeypatch.delenv(key.upper(), raising=False)
    monkeypatch.setenv("SAMPLE_MODE", "true")
    log_dir = tmp_path / "logs"
    monkeypatch.setenv("LOG_DIR", str(log_dir))
    return log_dir


@pytest.fixture
def no_network(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    """Make every socket connection to a non-loopback address raise; returns the attempts it blocked."""
    blocked: list[Any] = []
    real_connect = socket.socket.connect
    real_connect_ex = socket.socket.connect_ex
    real_getaddrinfo = socket.getaddrinfo

    def loopback(host: Any) -> bool:
        if host in ("localhost", "", None):
            return True
        try:
            return ipaddress.ip_address(str(host).split("%")[0]).is_loopback
        except ValueError:
            return False  # a host name: resolving it would already use the network

    def allowed(sock: socket.socket, address: Any) -> bool:
        return sock.family == getattr(socket, "AF_UNIX", object()) or (
            isinstance(address, tuple) and loopback(address[0])
        )

    def connect(sock: socket.socket, address: Any) -> None:
        if not allowed(sock, address):
            blocked.append(address)
            raise OSError(f"network blocked by the test: connect to {address!r}")
        return real_connect(sock, address)

    def connect_ex(sock: socket.socket, address: Any) -> int:
        if not allowed(sock, address):
            blocked.append(address)
            raise OSError(f"network blocked by the test: connect to {address!r}")
        return real_connect_ex(sock, address)

    def getaddrinfo(host: Any, *args: Any, **kwargs: Any) -> Any:
        if not loopback(host):
            blocked.append(host)
            raise OSError(f"network blocked by the test: resolve {host!r}")
        return real_getaddrinfo(host, *args, **kwargs)

    monkeypatch.setattr(socket.socket, "connect", connect)
    monkeypatch.setattr(socket.socket, "connect_ex", connect_ex)
    monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)
    return blocked


def test_the_network_guard_blocks_outside_addresses_and_allows_loopback(no_network: list[Any]) -> None:
    with pytest.raises(OSError, match="network blocked"):
        socket.create_connection(("192.0.2.1", 80), timeout=1)
    with pytest.raises(httpx.ConnectError, match="network blocked"):  # httpx wraps the OSError
        httpx.get("http://example.invalid/", timeout=1)
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    try:
        socket.create_connection(server.getsockname(), timeout=1).close()
    finally:
        server.close()
    assert len(no_network) == 2


# --- Criterion 1: query repair ------------------------------------------------------------------------


class FlakyData(DataLayer):
    """The local layer, except that the listed query numbers fail with a scripted error (logged as a failure)."""

    adapter_name = "local"

    def __init__(self, inner: LocalDataLayer, fail_on: set[int], code: str, message: str) -> None:
        self.inner, self.fail_on, self.code, self.message = inner, fail_on, code, message
        self.log = inner.log
        self.count = 0

    def list_sources(self) -> list[str]:
        return self.inner.list_sources()

    def describe(self, source: str) -> SourceInfo:
        return self.inner.describe(source)

    def query(self, source: str | None, sql: str, limit: int | None = None, timeout: float | None = None) -> QueryOutcome:
        self.count += 1
        if self.count in self.fail_on:
            failed = QueryError(query_id=f"fail-{self.count:03d}", source=source, sql=sql, adapter="local",
                                code=self.code, message=self.message)
            self.log.write(failed)
            return failed
        return self.inner.query(source, sql, limit, timeout)

    def close(self) -> None:
        self.inner.close()


QUERY_FAILURES = [
    ("failed", 'Parser Error: syntax error at or near "FORM"'),
    ("failed", 'Binder Error: Referenced column "order_dt" not found in FROM clause!'),
    ("timeout", "query exceeded QUERY_TIMEOUT_SECONDS=30"),
]


def run_flaky(tmp_path: Path, fail_on: set[int], code: str, message: str) -> tuple[Result, FlakyData]:
    settings = Settings(sample_mode=False, log_dir=str(tmp_path / "logs"), llm_cache_dir=str(tmp_path / "cache"),
                        max_agent_rounds=8, max_tool_calls=20, meterless_runtime_token="", nvidia_api_key="")
    inner = LocalDataLayer(run_id="flaky", log_dir=tmp_path / "logs", sources=("orders",), settings=settings)
    data = FlakyData(inner, fail_on, code, message)
    try:
        result = run_investigation(DAY1, run_id="flaky", generate=ScriptedModel(), data=data, settings=settings)
    finally:
        data.close()
    return result, data


@pytest.mark.parametrize(("code", "message"), QUERY_FAILURES)
def test_first_query_fails_second_is_accepted_after_exactly_one_repair(tmp_path: Path, code: str, message: str) -> None:
    result, data = run_flaky(tmp_path, {1}, code, message)
    trace = trace_of(tmp_path / "logs", "flaky")
    repairs = [line for line in trace if line["action"] == "repair_sql"]
    assert len(repairs) == 1
    assert repairs[0]["input_summary"] == "change_check" and repairs[0]["previous_error"] == message
    log = data.log.read()
    assert [line["status"] for line in log[:2]] == [code, "ok"]  # both attempts in the query log
    assert log[0]["error"] == message and log[0]["sql"] == log[1]["sql"]
    runs = [line for line in trace if line["action"] == "run_query"]
    assert [(line["status"], line["retry_count"]) for line in runs[:2]] == [(code, 0), ("ok", 1)]
    # The run went on: the change check produced an observation and the Reporter answered.
    assert result.status == "success" and result.change is not None and result.causes
    assert ("Reporter", "report") in {(line["agent"], line["action"]) for line in trace}


@pytest.mark.parametrize(("code", "message"), QUERY_FAILURES)
def test_query_failing_twice_is_an_outcome_and_the_run_still_returns_a_result(
    tmp_path: Path, code: str, message: str
) -> None:
    result, data = run_flaky(tmp_path, {1, 2}, code, message)
    trace = trace_of(tmp_path / "logs", "flaky")
    assert len([line for line in trace if line["action"] == "repair_sql"]) == MAX_SQL_REPAIRS == 1
    change_check = [line for line in trace if line["action"] == "run_query"][:2]
    assert [line["status"] for line in change_check] == [code, code]
    assert [line["status"] for line in data.log.read()].count(code) == 2  # no third attempt
    assert f"Change check failed: change_check: query failed after repair: {message}" in result.limitations
    assert result.status == "success" and result.change is None
    Result.model_validate(result.model_dump())


# --- Criterion 2: model retries, fallback and the three-attempt cap -----------------------------------


def provider_lines(tmp_path: Path) -> list[dict[str, Any]]:
    return [line for line in trace_of(tmp_path / "logs", "gen-test") if line["provider"] != "cache"]


def test_timeout_then_the_next_attempt_succeeds(tmp_path: Path) -> None:
    """A timed-out Meterless call is not repeated (its timeout is 180 s); the next attempt is the fallback."""
    rec = Recorder({
        "127.0.0.1": [httpx.ReadTimeout("read timed out")],
        "nvidia.test": [httpx.Response(200, json=chat_reply(GOOD, model="nvidia/test-model"))],
    })
    result = make_generator(tmp_path, rec)(MESSAGES, schema=Answer, role="planner")
    assert result.ok and result.provider == "nvidia" and result.parsed == {"answer": 5, "word": "five"}
    first, second = provider_lines(tmp_path)
    assert (first["provider"], first["status"], first["attempt"]) == ("meterless", "timeout", 1)
    assert (second["provider"], second["status"], second["attempt"]) == ("nvidia", "ok", 2)
    assert second["fallback_reason"].startswith("timeout: meterless timed out")


def test_5xx_then_retry_then_success_on_the_same_provider(tmp_path: Path) -> None:
    sleeps: list[float] = []
    rec = Recorder({"127.0.0.1": [httpx.Response(503), httpx.Response(200, json=chat_reply(GOOD))]})
    result = make_generator(tmp_path, rec, sleeps)(MESSAGES, schema=Answer, role="planner")
    assert result.ok and result.provider == "meterless" and result.retries == 1 and sleeps == [2.0]
    [line] = provider_lines(tmp_path)
    assert line["attempt"] == 2 and line["retry_count"] == 1 and "fallback_reason" not in line


def test_5xx_until_retries_are_exhausted_then_nvidia_with_fallback_reason(tmp_path: Path) -> None:
    sleeps: list[float] = []
    rec = Recorder({
        "127.0.0.1": [httpx.Response(502), httpx.Response(503)],
        "nvidia.test": [httpx.Response(200, json=chat_reply(GOOD, model="nvidia/test-model"))],
    })
    result = make_generator(tmp_path, rec, sleeps)(MESSAGES, schema=Answer, role="reporter")
    assert result.ok and result.provider == "nvidia" and len(rec.requests) == MAX_MODEL_ATTEMPTS
    meterless, nvidia = provider_lines(tmp_path)
    assert meterless["status"] == "retries_exhausted" and meterless["attempt"] == 2
    assert meterless["model"] == "meterless/deep" and "fallback_reason" not in meterless
    assert nvidia["provider"] == "nvidia" and nvidia["model"] == "nvidia/test-model" and nvidia["attempt"] == 3
    assert nvidia["fallback"] is True
    assert nvidia["fallback_reason"] == "retries_exhausted: meterless returned HTTP 503 after 1 retries"


def test_401_is_not_retried_and_not_bypassed(tmp_path: Path) -> None:
    """Main documents that an unauthorized Meterless token is reported, not silently bypassed."""
    sleeps: list[float] = []
    rec = Recorder({"127.0.0.1": [httpx.Response(401)]})
    result = make_generator(tmp_path, rec, sleeps)(MESSAGES, schema=Answer, role="planner")
    assert result.ok is False and result.error["code"] == "unauthorized"
    assert "rejected the token (HTTP 401)" in result.error["message"]
    assert len(rec.requests) == 1 and sleeps == []
    [line] = provider_lines(tmp_path)
    assert line["status"] == "unauthorized" and line["attempt"] == 1


def test_401_from_nvidia_as_primary_is_a_structured_error(tmp_path: Path) -> None:
    rec = Recorder({"nvidia.test": [httpx.Response(401)]})
    result = make_generator(tmp_path, rec, model_provider="nvidia")(MESSAGES, role="planner")
    assert result.ok is False and result.error["code"] == "unauthorized" and len(rec.requests) == 1


def test_fallback_not_configured_gives_a_structured_error(tmp_path: Path) -> None:
    sleeps: list[float] = []
    rec = Recorder({"127.0.0.1": [httpx.Response(503)] * 3})
    result = make_generator(tmp_path, rec, sleeps, nvidia_api_key="")(MESSAGES, schema=Answer, role="planner")
    assert result.ok is False
    assert result.error == {"code": "retries_exhausted", "message": "meterless returned HTTP 503 after 2 retries"}
    assert len(rec.requests) == MAX_MODEL_ATTEMPTS and sleeps == [2.0, 4.0]


def test_empty_reply_is_repaired_once_then_a_structured_error(tmp_path: Path) -> None:
    rec = Recorder({"127.0.0.1": [httpx.Response(200, json=chat_reply("")), httpx.Response(200, json=chat_reply(""))]})
    result = make_generator(tmp_path, rec)(MESSAGES, schema=Answer, role="planner")
    assert result.ok is False and result.error["code"] == "invalid_json" and result.repaired
    assert "no JSON object" in result.error["message"] and len(rec.requests) == 2


def ok_reply(content: str = GOOD) -> httpx.Response:
    return httpx.Response(200, json=chat_reply(content))


CAP_SCENARIOS = {
    "5xx everywhere": {"127.0.0.1": [httpx.Response(503)] * 4, "nvidia.test": [httpx.Response(503)] * 4},
    "429 everywhere, no fallback": {"127.0.0.1": [httpx.Response(429)] * 4},
    "offline, then fallback 5xx": {"127.0.0.1": [httpx.ConnectError("refused")],
                                   "nvidia.test": [httpx.Response(500)] * 4},
    "timeouts everywhere": {"127.0.0.1": [httpx.ReadTimeout("t")] * 4, "nvidia.test": [httpx.ReadTimeout("t")] * 4},
    "fallback answers invalid JSON twice": {"127.0.0.1": [httpx.Response(503)] * 4,
                                            "nvidia.test": [ok_reply("nope"), ok_reply("nope")]},
    "a retry, then a reply that needs the repair call": {"127.0.0.1": [httpx.Response(503), ok_reply("nope"),
                                                                       ok_reply(GOOD)]},
}
NO_FALLBACK = {"429 everywhere, no fallback", "a retry, then a reply that needs the repair call"}


@pytest.mark.parametrize("scenario", CAP_SCENARIOS)
@pytest.mark.parametrize("provider", ["meterless", "nvidia"])
def test_never_more_than_three_model_attempts_per_agent_step(tmp_path: Path, scenario: str, provider: str) -> None:
    script = {host: list(items) for host, items in CAP_SCENARIOS[scenario].items()}
    if provider == "nvidia":  # NVIDIA as the primary: the scripts above, sent to its host only
        script = {"nvidia.test": script.get("127.0.0.1", []) + script.get("nvidia.test", [])}
    rec = Recorder(script)
    overrides = {"nvidia_api_key": ""} if scenario in NO_FALLBACK and provider == "meterless" else {}
    result = make_generator(tmp_path, rec, model_provider=provider, **overrides)(MESSAGES, schema=Answer, role="planner")
    assert len(rec.requests) <= MAX_MODEL_ATTEMPTS == 3
    assert result.ok == (scenario == "a retry, then a reply that needs the repair call")
    assert result.ok or result.error["code"] != "internal"
    lines = provider_lines(tmp_path)
    assert lines and max(line["attempt"] for line in lines) == len(rec.requests)


def test_no_attempt_left_for_the_repair_call_is_a_structured_error(tmp_path: Path) -> None:
    rec = Recorder({"127.0.0.1": [httpx.Response(503), httpx.Response(503)], "nvidia.test": [ok_reply("nope")]})
    result = make_generator(tmp_path, rec)(MESSAGES, schema=Answer, role="planner")
    assert result.ok is False and result.error["code"] == "invalid_json"
    assert "no attempt left for a repair call (MAX_MODEL_ATTEMPTS=3 per step)" in result.error["message"]
    assert len(rec.requests) == 3


def test_every_generate_call_gets_its_own_three_attempts(tmp_path: Path) -> None:
    rec = Recorder({"127.0.0.1": [httpx.Response(503), httpx.Response(503), ok_reply(),
                                  httpx.Response(503), httpx.Response(503), ok_reply()]})
    gen = make_generator(tmp_path, rec, nvidia_api_key="")
    assert gen(MESSAGES, schema=Answer, role="planner").ok
    assert gen(MESSAGES, schema=Answer, role="planner").ok
    assert len(rec.requests) == 6


# --- Criterion 3: Zetaris down, the run completes on the local adapter ------------------------------


@pytest.mark.parametrize("loop", ["simple", "markovian"])
def test_zetaris_connect_error_run_completes_on_the_local_adapter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, no_network: list[Any], loop: str
) -> None:
    import app.llm.generator
    import app.runner

    zetaris_calls: list[httpx.Request] = []

    def refuse(request: httpx.Request) -> httpx.Response:
        zetaris_calls.append(request)
        raise httpx.ConnectError("connection refused", request=request)

    real_from_settings = ZetarisClient.from_settings
    monkeypatch.setattr(ZetarisClient, "from_settings",
                        classmethod(lambda cls, cfg, **kw: real_from_settings(cfg, transport=httpx.MockTransport(refuse))))
    monkeypatch.setattr(app.llm.generator, "Generator", lambda cfg: ScriptedModel())
    log_dir = tmp_path / "logs"
    settings = Settings(
        sample_mode=False, data_layer="zetaris", zetaris_url="http://zetaris.invalid:8888/api/v1.0",
        zetaris_api_key="zk-test", zetaris_org_id="1", zetaris_retry_delay_seconds=0.0, log_dir=str(log_dir),
        query_cache_dir=str(tmp_path / "qcache"), max_agent_rounds=8, world_db_path=str(tmp_path / "world.db"),
    )
    result = app.runner.execute_run(DAY1, run_id=f"zt-down-{loop}", settings=settings, loop=loop)

    assert result.status == "success", result.error
    assert zetaris_calls, "the Zetaris adapter must have been tried"
    queries = [json.loads(line) for line in (log_dir / f"queries-zt-down-{loop}.jsonl").read_text().splitlines()]
    assert queries and {q["adapter"] for q in queries} == {FALLBACK_ADAPTER}
    assert all(q["fallback_reason"] == "Zetaris unavailable after one retry: connection error (ConnectError)"
               for q in queries)
    fallback_lines = [line for line in trace_of(log_dir, f"zt-down-{loop}") if line["action"] == "data_fallback"]
    # One fallback line in the trace for each fallback line in the query log, and no other.
    assert sorted(line["query_id"] for line in fallback_lines) == sorted(q["query_id"] for q in queries)
    assert all(line["adapter"] == FALLBACK_ADAPTER and line["fallback_reason"] for line in fallback_lines)
    [note] = [item for item in result.limitations if item.startswith("Data adapter:")]
    assert FALLBACK_ADAPTER in note and "describe orders" in note
    assert validate_result_file(log_dir / f"result-zt-down-{loop}.json") == result  # the stored file says so too
    assert no_network == []


def test_no_fallback_note_when_zetaris_answers_or_in_sample_mode(clean_env: Path) -> None:
    assert run_cli.main([DAY1, "--loop", "simple", "--run-id", "no-note"]) == 0
    stored = validate_result_file(clean_env / "result-no-note.json")
    assert not any(item.startswith("Data adapter:") for item in stored.limitations)


# --- Criterion 4: sample mode end to end with the network blocked -----------------------------------


LIVE_LOOKING_ENV = {
    # Credentials and hosts that a live run would use; sample mode must not try any of them.
    "METERLESS_RUNTIME_TOKEN": "rt-would-be-live", "METERLESS_BASE_URL": "http://198.51.100.7:8088/v1",
    "NVIDIA_API_KEY": "nvapi-would-be-live", "NVIDIA_MODEL": "nvidia/x", "NVIDIA_BASE_URL": "https://nvidia.example/v1",
    "DATA_LAYER": "zetaris", "ZETARIS_URL": "http://zetaris.example:8888/api/v1.0", "ZETARIS_API_KEY": "zk",
    "ZETARIS_ORG_ID": "1",
}


@pytest.mark.parametrize("env", ["empty", "live credentials set"])
@pytest.mark.parametrize(("question", "args"), [(DAY1, ["--loop", "simple"]), (PLAN_CHECK_J, [])])
def test_sample_mode_runs_end_to_end_from_the_cache_without_network(
    clean_env: Path, no_network: list[Any], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
    env: str, question: str, args: list[str],
) -> None:
    if env != "empty":
        for key, value in LIVE_LOOKING_ENV.items():
            monkeypatch.setenv(key, value)
    assert run_cli.main([question, *args, "--run-id", "offline"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "success" and payload["sample_mode"] is True and payload["causes"]
    trace = trace_of(clean_env, "offline")
    assert trace[0]["action"] == "start" and trace[0]["sample_mode"] is True
    model_lines = [line for line in trace if line["action"] in ("model_call", "model_repair_call")]
    assert model_lines and {line["provider"] for line in model_lines} == {"cache"}
    assert {line["status"] for line in model_lines} == {"ok"}
    queries = [json.loads(line) for line in (clean_env / "queries-offline.jsonl").read_text().splitlines()]
    assert queries and {q["adapter"] for q in queries} == {"local"}
    assert no_network == []  # not even an attempt was blocked


@pytest.mark.parametrize("args", [["--loop", "simple"], []])
def test_sample_mode_cache_miss_is_the_structured_error(
    clean_env: Path, no_network: list[Any], capsys: pytest.CaptureFixture[str], args: list[str]
) -> None:
    assert run_cli.main([UNRECORDED, *args, "--run-id", "miss"]) == 1
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["status"] == "error" and payload["determinable"] is False and payload["causes"] == []
    assert payload["error"] == {"code": "cache_miss", "message": CACHE_MISS_MESSAGE}
    assert "needs a model key" in payload["error"]["message"] and payload["sample_mode"] is True
    assert "Traceback" not in captured.out + captured.err
    misses = [line for line in trace_of(clean_env, "miss") if line["status"] == "cache_miss"]
    assert misses and misses[0]["provider"] == "cache"
    assert no_network == []


def test_sample_mode_cache_miss_over_the_api(clean_env: Path, no_network: list[Any]) -> None:
    response = TestClient(api.app).post("/run", json={"input": {"query": UNRECORDED}, "run_id": "api-miss"})
    assert response.status_code == 409
    assert response.json() == {"error": {"code": "cache_miss", "message": CACHE_MISS_MESSAGE, "run_id": "api-miss"}}
    assert no_network == []


# --- Criterion 5: METERLESS_RUNTIME_TOKEN and the older METERLESS_API_KEY ---------------------------


@pytest.mark.parametrize(
    ("runtime_token", "api_key", "expected"),
    [("rt-runtime", None, "rt-runtime"), (None, "rt-older-name", "rt-older-name"),
     ("rt-runtime", "rt-older-name", "rt-runtime"), ("", "rt-older-name", "rt-older-name")],
)
def test_runtime_token_and_api_key_aliases(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, runtime_token: str | None, api_key: str | None, expected: str
) -> None:
    for key in Settings.model_fields:
        monkeypatch.delenv(key.upper(), raising=False)
    monkeypatch.setenv("SAMPLE_MODE", "false")
    monkeypatch.setenv("LOG_DIR", str(tmp_path))
    if runtime_token is not None:
        monkeypatch.setenv("METERLESS_RUNTIME_TOKEN", runtime_token)
    if api_key is not None:
        monkeypatch.setenv("METERLESS_API_KEY", api_key)
    settings = Settings()
    assert settings.meterless_token == expected
    rec = Recorder({"127.0.0.1": [ok_reply()]})
    result = Generator(settings, transport=httpx.MockTransport(rec))(MESSAGES, schema=Answer, role="planner")
    assert result.ok and result.provider == "meterless"
    assert rec.requests[0].headers["Authorization"] == f"Bearer {expected}"


def test_no_meterless_token_under_either_name_means_not_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in Settings.model_fields:
        monkeypatch.delenv(key.upper(), raising=False)
    settings = Settings()
    assert settings.meterless_token == ""
    assert not Generator(settings).meterless.configured
    assert not Generator(Settings(meterless_api_key="rt-local")).meterless.configured  # placeholder refused


# --- Criterion 6: carry-overs --------------------------------------------------------------------------


def test_post_run_with_a_used_run_id_is_409_and_keeps_the_earlier_logs(clean_env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOOP", "simple")
    client = TestClient(api.app)
    body = {"run_id": "used-once", "input": {"query": DAY1}}
    assert client.post("/run", json=body).status_code == 200
    files = {path.name: path.read_bytes() for path in clean_env.iterdir() if "used-once" in path.name}
    assert set(files) >= {"trace-used-once.jsonl", "result-used-once.json", "queries-used-once.jsonl"}

    again = client.post("/run", json={**body, "input": {"query": UNRECORDED}})
    assert again.status_code == 409
    error = again.json()["error"]
    assert set(again.json()) == {"error"} and set(error) == {"code", "message", "run_id"}
    assert error["code"] == "run_id_taken" and error["run_id"] == "used-once" and "already used" in error["message"]
    assert {path.name: path.read_bytes() for path in clean_env.iterdir() if "used-once" in path.name} == files
    assert not api._RUN_LOCK.locked()
    assert client.get("/runs/used-once").json()["question"] == DAY1


@pytest.mark.parametrize("kind", ["trace", "queries"])
def test_any_earlier_log_file_marks_the_run_id_as_used(clean_env: Path, kind: str) -> None:
    clean_env.mkdir(parents=True)
    suffix = ".jsonl"
    (clean_env / f"{kind}-half-run{suffix}").write_text("{}\n")
    response = TestClient(api.app).post("/run", json={"run_id": "half-run", "input": {"query": DAY1}})
    assert response.status_code == 409 and response.json()["error"]["code"] == "run_id_taken"


def test_bad_loop_setting_is_invalid_input_not_500(clean_env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOOP", "chunky")
    response = TestClient(api.app).post("/run", json={"run_id": "bad-loop", "input": {"query": DAY1}})
    assert response.status_code == 400
    error = response.json()["error"]
    assert error["code"] == "invalid_input" and "LOOP must be one of markovian, simple" in error["message"]
    assert "chunky" in error["message"] and error["run_id"] == "bad-loop"
    assert not (clean_env / "trace-bad-loop.jsonl").exists()
    assert not api._RUN_LOCK.locked()


def test_bad_loop_at_the_cli_is_a_structured_error(
    clean_env: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("LOOP", "chunky")
    assert run_cli.main([DAY1, "--run-id", "bad-loop-cli"]) == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "error" and payload["error"]["code"] == "bad_loop"
    assert "LOOP must be one of markovian, simple, got 'chunky'" == payload["error"]["message"]
    with pytest.raises(SystemExit) as exit_info:  # an unknown --loop value is refused by the parser
        run_cli.main([DAY1, "--loop", "chunky"])
    assert exit_info.value.code == 2
    assert "invalid choice: 'chunky'" in capsys.readouterr().err


def test_stray_root_files_are_gone_and_ignored() -> None:
    import subprocess

    for name in ("record.err", "result.json", "result-live.json"):
        tracked = subprocess.run(["git", "ls-files", "--error-unmatch", name], cwd=ROOT, capture_output=True, timeout=30, check=False)
        assert tracked.returncode != 0, f"{name} is still tracked"
        ignored = subprocess.run(["git", "check-ignore", "-q", name], cwd=ROOT, capture_output=True, timeout=30, check=False)
        assert ignored.returncode == 0, f"{name} is not covered by .gitignore"
    kept = subprocess.run(["git", "check-ignore", "-q", "output_examples/result.json"], cwd=ROOT,
                          capture_output=True, timeout=30, check=False)
    assert kept.returncode != 0, "the ignore rules must only cover the repository root"


# --- Criterion 7: every retry and fallback loop has a fixed cap, every external call a timeout -------


def test_retry_and_fallback_caps_are_fixed() -> None:
    assert MAX_MODEL_ATTEMPTS == 3
    assert RETRY_DELAYS_SECONDS == (2.0, 4.0, 8.0)
    assert MAX_SQL_REPAIRS == 1
    with pytest.raises(ValidationError):
        Settings(max_retries=4)
    with pytest.raises(ValidationError):
        Settings(zetaris_retry_delay_seconds=31)
    # The Zetaris adapter retries once (tests/test_data_zetaris.py::test_outage_retries_once_then_falls_back_to_local).
    import inspect

    from app.data.zetaris import ZetarisDataLayer

    assert inspect.getsource(ZetarisDataLayer._run_with_retry).count("self.client.run_sql(") == 2


def test_every_external_call_keeps_its_timeout(tmp_path: Path) -> None:
    settings = Settings(sample_mode=False, model_timeout_seconds=45, query_timeout_seconds=12,
                        nvidia_api_key=NVIDIA_KEY, nvidia_model="m", meterless_runtime_token=TOKEN)
    gen = Generator(settings)
    assert gen.meterless.client.timeout == httpx.Timeout(METERLESS_TIMEOUT_SECONDS) == httpx.Timeout(180.0)
    assert gen.nvidia.client.timeout == httpx.Timeout(45.0)
    zetaris = ZetarisClient(base_url="http://zetaris.invalid/api/v1.0", org_id="1", api_key="k", timeout=12.0)
    try:
        timeout = zetaris._timeout(None)
        assert timeout.read == 12.0 and timeout.connect is not None and timeout.connect <= 12.0
    finally:
        zetaris.close()
    script = (ROOT / "scripts" / "clean_clone_check.sh").read_text()
    calls = [line for line in script.splitlines() if "run.py" in line and not line.lstrip().startswith("#")]
    assert calls and all("with_timeout" in line for line in calls)
