"""Tests for the HTTP API (app/api/main.py) with the FastAPI TestClient.

Runs use sample mode: model replies from the committed per-call cache, data from the local DuckDB
sample. No test opens a network connection; error cases that need a slow or failing run replace
`app.api.main.execute_run` with a stub.
"""

from __future__ import annotations

import json
import socket
import threading
import time
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

import app.api.main as api
import app.runner
import run as run_cli
from app.config import Settings
from app.schemas import Result, ResultError, validate_result_file

QUESTION = "Why did order volume spike on 24 November 2017?"
DAY1_BODY = {"input": {"query": QUESTION}, "options": {"sample_mode": True}}
# Fields that differ between two runs of the same question by design.
PER_RUN_FIELDS = ("run_id", "trace_id", "log_file", "query_log", "execution_time_seconds")


@pytest.fixture
def logs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Clear every settings variable, run in sample mode, write logs under tmp_path."""
    for key in Settings.model_fields:
        monkeypatch.delenv(key.upper(), raising=False)
    monkeypatch.setenv("SAMPLE_MODE", "true")
    log_dir = tmp_path / "logs"
    monkeypatch.setenv("LOG_DIR", str(log_dir))
    return log_dir


@pytest.fixture
def client(logs: Path) -> TestClient:
    yield TestClient(api.app)
    assert not api._RUN_LOCK.locked(), "a test left the run lock held"


def stub_result(question: str, run_id: str, **fields: Any) -> Result:
    values: dict[str, Any] = {
        "run_id": run_id, "status": "success", "question": question, "determinable": False,
        "trace_id": run_id, "log_file": f"logs/trace-{run_id}.jsonl", "execution_time_seconds": 0.0,
        "sample_mode": True,
    }
    values.update(fields)
    return Result(**values)


def assert_error(response: Any, status: int, code: str) -> dict[str, Any]:
    assert response.status_code == status, response.text
    body = response.json()
    assert set(body) == {"error"}
    assert set(body["error"]) == {"code", "message", "run_id"}
    assert body["error"]["code"] == code
    assert body["error"]["message"]
    return body["error"]


# --- Criterion 1 and 2: a real sample-mode run, stored and read back ----------------------------


def test_post_run_day1_sample_mode_returns_valid_result_and_writes_files(client: TestClient, logs: Path) -> None:
    response = client.post("/run", json=DAY1_BODY)
    assert response.status_code == 200, response.text
    body = response.json()
    result = Result.model_validate(body)
    assert result.status == "success" and result.sample_mode is True
    assert result.causes and result.causes[0].evidence
    run_id = body["run_id"]
    assert app.runner.valid_run_id(run_id)
    assert (logs / f"trace-{run_id}.jsonl").is_file()
    stored = logs / f"result-{run_id}.json"
    assert stored.is_file()
    assert validate_result_file(stored).model_dump(mode="json") == body

    again = client.get(f"/runs/{run_id}")
    assert again.status_code == 200
    assert again.json() == body

    trace = client.get(f"/runs/{run_id}/trace")
    assert trace.status_code == 200
    assert trace.headers["content-type"].startswith("application/x-ndjson")
    lines = [json.loads(line) for line in trace.text.splitlines()]
    assert lines == [json.loads(line) for line in (logs / f"trace-{run_id}.jsonl").read_text().splitlines()]
    assert lines[0]["action"] == "start" and lines[-1]["action"] == "finish"
    assert {line["run_id"] for line in lines} == {run_id}


def test_post_run_uses_the_given_run_id(client: TestClient, logs: Path) -> None:
    response = client.post("/run", json={**DAY1_BODY, "run_id": "api-given.1"})
    assert response.status_code == 200, response.text
    assert response.json()["run_id"] == "api-given.1"
    assert (logs / "result-api-given.1.json").is_file()


def test_get_unknown_run_is_not_found(client: TestClient) -> None:
    error = assert_error(client.get("/runs/no-such-run"), 404, "not_found")
    assert error["run_id"] == "no-such-run"
    assert_error(client.get("/runs/no-such-run/trace"), 404, "not_found")


# "/runs/.." is sent as "/" by the client (dot-segment removal), which is now the web page; the
# encoded form "/runs/%2E%2E" reaches the run route with the id "..".
@pytest.mark.parametrize(
    "path",
    ["/runs/../etc", "/runs/a/b", "/runs/a%2Fb", "/runs/..%2Fetc", "/runs/..%2F..%2Fetc%2Fpasswd/trace",
     "/runs/a..b", "/runs/%2E%2E", "/runs/.hidden", "/runs/%2Fetc%2Fpasswd", "/runs/a%5Cb", "/runs/" + "x" * 65],
)
def test_traversal_ids_are_rejected_without_opening_files(
    client: TestClient, path: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    opened: list[str] = []
    real_is_file, real_read_bytes = Path.is_file, Path.read_bytes

    def spy_is_file(self: Path) -> bool:
        opened.append(str(self))
        return real_is_file(self)

    def spy_read_bytes(self: Path) -> bytes:
        opened.append(str(self))
        return real_read_bytes(self)

    monkeypatch.setattr(Path, "is_file", spy_is_file)
    monkeypatch.setattr(Path, "read_bytes", spy_read_bytes)
    response = client.get(path)
    assert response.status_code in (400, 404), response.text
    code = "invalid_input" if response.status_code == 400 else "not_found"
    assert_error(response, response.status_code, code)
    assert opened == []


def test_run_id_check_runs_before_any_path_is_built(client: TestClient, logs: Path) -> None:
    # A file that a traversal id would reach if the id were used unchecked.
    logs.mkdir(parents=True)
    (logs.parent / "result-x.json").write_text("{}")
    assert_error(client.get("/runs/..%2Fresult-x"), 404, "not_found")
    assert_error(client.get("/runs/a..b"), 400, "invalid_input")


# --- Criterion 3: error cases ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "body",
    [
        {"input": {"query": ""}},
        {"input": {"query": "   "}},
        {"input": {}},
        {},
        {"input": {"query": "x" * 1001}},
        {"input": {"query": 42}},
        {"input": {"anomaly_id": "a-1"}},
        {"input": {"query": QUESTION}, "options": {"sample_mode": "maybe"}},
    ],
    ids=["empty", "blank", "missing-query", "missing-input", "too-long", "not-a-string", "anomaly-id",
         "bad-option"],
)
def test_invalid_input(client: TestClient, body: dict[str, Any], logs: Path) -> None:
    assert_error(client.post("/run", json=body), 422, "invalid_input")
    assert not logs.exists() or not any(logs.iterdir()), "an invalid request must not start a run"


def test_query_of_exactly_1000_characters_is_accepted(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(api, "execute_run", lambda q, *, run_id, settings: stub_result(q, run_id))
    response = client.post("/run", json={"input": {"query": "x" * 1000}})
    assert response.status_code == 200, response.text


def test_malformed_json_is_invalid_input(client: TestClient) -> None:
    response = client.post("/run", content=b"{not json", headers={"Content-Type": "application/json"})
    assert_error(response, 422, "invalid_input")


@pytest.mark.parametrize("run_id", ["../etc", "a/b", "a..b", ".x", "-x", "", "x" * 65, "a b", "é"])
def test_invalid_run_id(client: TestClient, run_id: str, logs: Path) -> None:
    error = assert_error(client.post("/run", json={**DAY1_BODY, "run_id": run_id}), 422, "invalid_input")
    assert error["message"].startswith("run_id:")
    assert error["run_id"] is None
    assert not logs.exists()


def test_run_that_raises_is_run_failed_without_details(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(question: str, *, run_id: str, settings: Settings) -> Result:
        raise RuntimeError("connect failed for https://user:hunter2@example.invalid token=sk-secret")

    monkeypatch.setattr(api, "execute_run", boom)
    response = client.post("/run", json={**DAY1_BODY, "run_id": "boom-1"})
    error = assert_error(response, 500, "run_failed")
    assert error["run_id"] == "boom-1"
    for leaked in ("hunter2", "sk-secret", "Traceback", "File \"", "example.invalid"):
        assert leaked not in response.text
    assert "RuntimeError" in error["message"]


def test_internal_error_result_is_run_failed(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    def internal(question: str, *, run_id: str, settings: Settings) -> Result:
        return stub_result(question, run_id, status="error",
                           error=ResultError(code="internal", message="KeyError: 'secret'"))

    monkeypatch.setattr(api, "execute_run", internal)
    response = client.post("/run", json=DAY1_BODY)
    error = assert_error(response, 500, "run_failed")
    assert "secret" not in response.text and error["run_id"]


def test_unexpected_api_layer_error_is_run_failed(logs: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def broken() -> Settings:
        raise RuntimeError("password=hunter2")

    monkeypatch.setattr(api, "get_settings", broken)
    response = TestClient(api.app, raise_server_exceptions=False).post("/run", json=DAY1_BODY)
    assert_error(response, 500, "run_failed")
    assert "hunter2" not in response.text and "Traceback" not in response.text


def test_sample_mode_cache_miss_is_409(client: TestClient, logs: Path) -> None:
    # Only the Day-1 question has recorded model replies; any other question misses the cache.
    response = client.post("/run", json={"run_id": "miss-1", "input": {"query": "Why did reviews drop in March 2018?"},
                                         "options": {"sample_mode": True}})
    error = assert_error(response, 409, "cache_miss")
    assert error["run_id"] == "miss-1"
    # The run itself ended normally: its structured result is stored and readable.
    stored = client.get("/runs/miss-1").json()
    assert stored["status"] == "error" and stored["error"]["code"] == "cache_miss"


def test_second_run_while_one_holds_the_lock_is_busy(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    started, release = threading.Event(), threading.Event()

    def slow(question: str, *, run_id: str, settings: Settings) -> Result:
        started.set()
        release.wait(10)
        return stub_result(question, run_id)

    monkeypatch.setattr(api, "execute_run", slow)
    first: dict[str, Any] = {}
    thread = threading.Thread(target=lambda: first.update(r=client.post("/run", json={**DAY1_BODY, "run_id": "one"})))
    thread.start()
    try:
        assert started.wait(10), "the first run never started"
        t0 = time.monotonic()
        error = assert_error(client.post("/run", json={**DAY1_BODY, "run_id": "two"}), 429, "busy")
        assert time.monotonic() - t0 < 2, "busy must be answered at once, not queued"
        assert error["run_id"] == "two"
        assert client.get("/health").status_code == 200  # reads still work during a run
    finally:
        release.set()
        thread.join(10)
    assert first["r"].status_code == 200 and first["r"].json()["run_id"] == "one"
    # The lock is free again.
    assert client.post("/run", json={**DAY1_BODY, "run_id": "three"}).status_code == 200


def test_run_past_the_timeout_is_504(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("API_RUN_TIMEOUT_SECONDS", "0.2")
    release, finished = threading.Event(), threading.Event()

    def stuck(question: str, *, run_id: str, settings: Settings) -> Result:
        try:
            release.wait(10)
            return stub_result(question, run_id)
        finally:
            finished.set()

    monkeypatch.setattr(api, "execute_run", stuck)
    t0 = time.monotonic()
    error = assert_error(client.post("/run", json={**DAY1_BODY, "run_id": "slow-1"}), 504, "timeout")
    assert time.monotonic() - t0 < 5
    assert error["run_id"] == "slow-1"
    assert "API_RUN_TIMEOUT_SECONDS=0.2" in error["message"]
    # The timed-out run still holds the lock until it really ends.
    assert_error(client.post("/run", json={**DAY1_BODY, "run_id": "slow-2"}), 429, "busy")
    release.set()
    assert finished.wait(10)
    for _ in range(100):
        if not api._RUN_LOCK.locked():
            break
        time.sleep(0.02)
    assert not api._RUN_LOCK.locked()


def test_unknown_route_uses_the_error_shape(client: TestClient) -> None:
    assert_error(client.get("/nope"), 404, "not_found")
    assert_error(client.get("/run"), 405, "method_not_allowed")


# --- Criterion 4: one code path for run.py and the API -------------------------------------------


def test_run_py_and_post_run_give_the_same_result(
    client: TestClient, logs: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    calls: list[str] = []
    real = app.runner.execute_run

    def spy(question: str, *, run_id: str, settings: Settings) -> Result:
        calls.append(run_id)
        return real(question, run_id=run_id, settings=settings)

    assert run_cli.execute_run is app.runner.execute_run
    assert api.execute_run is app.runner.execute_run
    monkeypatch.setattr(api, "execute_run", spy)

    assert run_cli.main([QUESTION, "--sample", "--run-id", "same-cli"]) == 0
    cli = json.loads(capsys.readouterr().out)
    response = client.post("/run", json={**DAY1_BODY, "run_id": "same-api"})
    assert response.status_code == 200, response.text
    served = response.json()
    assert calls == ["same-api"]

    def comparable(payload: dict[str, Any]) -> dict[str, Any]:
        return {key: value for key, value in payload.items() if key not in PER_RUN_FIELDS}

    assert comparable(served) == comparable(cli)
    assert served["causes"], "the comparison must cover a real answer"
    # run.py goes through the same helper, so it stores its result too.
    assert validate_result_file(logs / "result-same-cli.json").model_dump(mode="json") == cli


# --- Criterion 5: health --------------------------------------------------------------------------


def test_health_with_empty_environment_and_no_network(logs: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for key in ("SAMPLE_MODE", "LOG_DIR"):
        monkeypatch.delenv(key, raising=False)

    def no_network(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("health must not open a connection")

    monkeypatch.setattr(socket.socket, "connect", no_network)
    monkeypatch.setattr(api, "execute_run", no_network)
    response = TestClient(api.app).get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "sample_mode": True}


def test_health_reports_live_mode(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SAMPLE_MODE", "false")
    assert client.get("/health").json() == {"status": "ok", "sample_mode": False}


def test_sample_mode_option_overrides_the_environment(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[bool] = []

    def record(question: str, *, run_id: str, settings: Settings) -> Result:
        seen.append(settings.sample_mode)
        return stub_result(question, run_id)

    monkeypatch.setattr(api, "execute_run", record)
    monkeypatch.setenv("SAMPLE_MODE", "false")
    client.post("/run", json={"input": {"query": QUESTION}, "options": {"sample_mode": True}})
    client.post("/run", json={"input": {"query": QUESTION}})
    monkeypatch.setenv("SAMPLE_MODE", "true")
    client.post("/run", json={"input": {"query": QUESTION}, "options": {"sample_mode": False}})
    assert seen == [True, False, False]


def test_python_dash_m_app_api_binds_from_environment(logs: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import uvicorn

    import app.api.__main__ as entry

    captured: dict[str, Any] = {}
    monkeypatch.setattr(uvicorn, "run", lambda target, **kwargs: captured.update(target=target, **kwargs))
    entry.main()
    assert captured == {"target": "app.api.main:app", "host": "0.0.0.0", "port": 8000}
    monkeypatch.setenv("API_HOST", "127.0.0.1")
    monkeypatch.setenv("API_PORT", "8123")
    entry.main()
    assert captured == {"target": "app.api.main:app", "host": "127.0.0.1", "port": 8123}


def test_api_settings_defaults(logs: Path) -> None:
    settings = Settings()
    assert (settings.api_host, settings.api_port, settings.api_run_timeout_seconds) == ("0.0.0.0", 8000, 600)
