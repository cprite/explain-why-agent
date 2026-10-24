"""GET /anomalies and POST /run {"anomaly_id"} (Sprint 13b), with the FastAPI TestClient.

One real scan of the committed sample runs once per module (about 25 s, no network); the other
tests swap in a stub board or a stub `execute_run`.
"""

from __future__ import annotations

import socket
import threading
from pathlib import Path
from typing import Any

import pytest
import yaml
from fastapi.testclient import TestClient

import app.api.main as api
from app.api.anomalies import MAX_METRIC_LIMIT, Board, BoardCache, run_scan
from app.config import Settings
from app.scanner import db
from app.scanner.models import AnomalyCard, MetricBoard, ScanReport
from app.schemas import Result

CONFIG_YAML = Path(__file__).resolve().parents[1] / "app" / "scanner" / "config.yaml"
INCIDENT_06 = ("avg_review_score", "relogios_presentes", "2018-01")


def is_incident_06(card: dict[str, Any] | AnomalyCard) -> bool:
    c = card if isinstance(card, AnomalyCard) else AnomalyCard.model_validate(card)
    return (c.metric, c.segment.value, c.period.start.isoformat()[:7]) == INCIDENT_06


@pytest.fixture(scope="module")
def real_board() -> Board:
    """One scan of the committed sample with an empty environment and no network."""
    with pytest.MonkeyPatch.context() as mp:
        for key in Settings.model_fields:
            mp.delenv(key.upper(), raising=False)
        mp.setenv("SAMPLE_MODE", "true")

        def no_network(*args: Any, **kwargs: Any) -> None:
            raise AssertionError("the scan must not open a network connection")

        mp.setattr(socket.socket, "connect", no_network)
        return run_scan()


@pytest.fixture
def logs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
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


@pytest.fixture
def served(real_board: Board, monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """Serve the module's real board; returns the list of scans the cache asked for."""
    calls: list[int] = []

    def compute() -> Board:
        calls.append(1)
        return real_board

    monkeypatch.setattr(api, "BOARD", BoardCache(api._RUN_LOCK, compute))
    return calls


def assert_error(response: Any, status: int, code: str) -> dict[str, Any]:
    assert response.status_code == status, response.text
    body = response.json()
    assert set(body) == {"error"} and set(body["error"]) == {"code", "message", "run_id"}
    assert body["error"]["code"] == code and body["error"]["message"]
    return body["error"]


def stub_result(question: str, run_id: str) -> Result:
    return Result(run_id=run_id, status="success", question=question, determinable=False, trace_id=run_id,
                  log_file=f"logs/trace-{run_id}.jsonl", execution_time_seconds=0.0, sample_mode=True)


def incident_06_card(client: TestClient) -> dict[str, Any]:
    cards = client.get("/anomalies?metric=avg_review_score&limit=10").json()["cards"]
    return next(c for c in cards if is_incident_06(c))


# --- Criterion 1: GET /anomalies --------------------------------------------------------------------


def test_real_scan_closes_the_scanner_connection(real_board: Board) -> None:
    assert db.default_database()._conn is None
    assert not real_board.report.timed_out


def test_get_anomalies_returns_top_ten_and_per_metric_board(client: TestClient, served: list[int]) -> None:
    response = client.get("/anomalies")
    assert response.status_code == 200, response.text
    body = response.json()
    assert {"cards", "by_metric"} <= set(body)
    assert 1 <= len(body["cards"]) <= 10
    cards = [AnomalyCard.model_validate(c) for c in body["cards"]]
    assert [c.rank for c in cards] == list(range(1, len(cards) + 1))
    boards = [MetricBoard.model_validate(b) for b in body["by_metric"]]
    assert [b.metric for b in boards] == list(yaml.safe_load(CONFIG_YAML.read_text())["metrics"])
    assert all(len(b.cards) <= 3 for b in boards)
    ScanReport.model_validate({**served_report_fields(body), "cards": body["cards"], "by_metric": body["by_metric"]})
    # Incident-06 is flagged but neither in the top ten nor in its metric's default top 3.
    assert not any(is_incident_06(c) for c in cards)
    review = next(b for b in boards if b.metric == "avg_review_score")
    assert not any(is_incident_06(c) for c in review.cards)
    assert review.episodes_found > 3


def served_report_fields(body: dict[str, Any]) -> dict[str, Any]:
    return {"generated_at": body["generated_at"], "data_source": "x", "elapsed_seconds": 0, "timed_out": body["timed_out"],
            "queries": 0, "series_scanned": 0, "episodes_found": body["episodes_found"], "thresholds": {}}


def test_metric_list_includes_incident_06(client: TestClient, served: list[int]) -> None:
    response = client.get("/anomalies?metric=avg_review_score&limit=10")
    assert response.status_code == 200, response.text
    board = MetricBoard.model_validate(response.json())
    assert board.metric == "avg_review_score" and len(board.cards) == 10
    assert [c.rank for c in board.cards] == list(range(1, 11))
    overall = [c.overall_rank for c in board.cards]
    assert overall == sorted(overall)
    matches = [c for c in board.cards if is_incident_06(c)]
    assert len(matches) == 1
    card = matches[0]
    assert card.metric_label.lower().startswith("average review score")
    assert card.segment.label == "product category relogios_presentes"
    assert card.direction == "fall" and card.z_score < -3.5
    assert "relogios_presentes" in card.question


def test_metric_list_starts_with_the_board_cards(client: TestClient, served: list[int]) -> None:
    body = client.get("/anomalies").json()
    for board in body["by_metric"]:
        expanded = client.get(f"/anomalies?metric={board['metric']}&limit=25").json()
        assert expanded["episodes_found"] == board["episodes_found"]
        assert len(expanded["cards"]) == min(board["episodes_found"], MAX_METRIC_LIMIT)
        assert expanded["cards"][: len(board["cards"])] == board["cards"]


def test_metric_limit_is_capped_and_checked(client: TestClient, served: list[int]) -> None:
    capped = client.get("/anomalies?metric=payment_share&limit=500").json()
    assert len(capped["cards"]) == MAX_METRIC_LIMIT
    assert len(client.get("/anomalies?metric=avg_review_score&limit=2").json()["cards"]) == 2
    assert_error(client.get("/anomalies?metric=avg_review_score&limit=0"), 422, "invalid_input")
    assert_error(client.get("/anomalies?metric=avg_review_score&limit=abc"), 422, "invalid_input")
    assert_error(client.get("/anomalies?metric=no_such_metric"), 404, "not_found")
    assert served == [1], "every call is answered from the one cached scan"


def test_scanner_settings_are_unchanged() -> None:
    config = yaml.safe_load(CONFIG_YAML.read_text())
    assert config["sample_design"] == "stratified"
    detection = config["detection"]
    assert (detection["z_threshold"], detection["volume_floor"], detection["mad_floor"]) == (3.5, 30, 0.01)
    assert detection["windows"] == {"day": 28, "week": 12}
    assert detection["min_history"] == {"day": 14, "week": 6}
    assert config["attribution"] == {"explains_threshold": 0.67, "slice_threshold": 0.10, "top_dimensions": 3}
    assert config["ranking"] == {"max_cards": 10, "attribute_top": 40, "per_metric_top": 3}


# --- Cache and lock -----------------------------------------------------------------------------------


def test_scan_is_cached_until_refresh(client: TestClient, served: list[int]) -> None:
    assert client.get("/anomalies").status_code == 200
    assert client.get("/anomalies").status_code == 200
    assert served == [1]
    assert client.get("/anomalies?refresh=true").status_code == 200
    assert served == [1, 1]


def test_scan_takes_the_run_lock(client: TestClient, real_board: Board, monkeypatch: pytest.MonkeyPatch) -> None:
    held: list[bool] = []

    def compute() -> Board:
        held.append(api._RUN_LOCK.locked())
        return real_board

    monkeypatch.setattr(api, "BOARD", BoardCache(api._RUN_LOCK, compute))
    assert client.get("/anomalies").status_code == 200
    assert held == [True]
    assert not api._RUN_LOCK.locked()


def test_refresh_during_a_run_is_busy(client: TestClient, served: list[int]) -> None:
    assert client.get("/anomalies").status_code == 200
    assert api._RUN_LOCK.acquire(blocking=False)
    try:
        assert_error(client.get("/anomalies?refresh=true"), 429, "busy")
        # The cached board is still served while the run goes on.
        assert client.get("/anomalies").status_code == 200
        assert client.get("/anomalies?metric=avg_review_score&limit=10").status_code == 200
    finally:
        api._RUN_LOCK.release()
    assert served == [1]


def test_first_scan_during_a_run_is_busy(client: TestClient, served: list[int]) -> None:
    assert api._RUN_LOCK.acquire(blocking=False)
    try:
        assert_error(client.get("/anomalies"), 429, "busy")
    finally:
        api._RUN_LOCK.release()
    assert served == []


def test_timed_out_scan_is_served_but_not_cached(client: TestClient, real_board: Board,
                                                monkeypatch: pytest.MonkeyPatch) -> None:
    partial = Board(real_board.report.model_copy(update={"timed_out": True}), real_board.expanded)
    boards = [partial, real_board]
    calls: list[bool] = []

    def compute() -> Board:
        calls.append(partial is boards[0])
        return boards.pop(0)

    monkeypatch.setattr(api, "BOARD", BoardCache(api._RUN_LOCK, compute))
    first = client.get("/anomalies")
    assert first.status_code == 200 and first.json()["timed_out"] is True
    # The next call scans again; the complete board is then cached.
    assert client.get("/anomalies").json()["timed_out"] is False
    assert client.get("/anomalies").json()["timed_out"] is False
    assert calls == [True, False]


def test_failed_scan_releases_the_lock_and_is_not_cached(logs: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def broken() -> Board:
        raise RuntimeError("scanner exploded at /secret/path")

    monkeypatch.setattr(api, "BOARD", BoardCache(api._RUN_LOCK, broken))
    error = assert_error(TestClient(api.app, raise_server_exceptions=False).get("/anomalies"), 500, "run_failed")
    assert "/secret/path" not in error["message"]
    assert not api._RUN_LOCK.locked()


# --- Criterion 2: POST /run {"anomaly_id"} -----------------------------------------------------------


def test_anomaly_id_runs_the_cards_question_through_execute_run(
    client: TestClient, served: list[int], monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[tuple[str, str, bool]] = []

    def record(question: str, *, run_id: str, settings: Settings) -> Result:
        seen.append((question, run_id, settings.sample_mode))
        return stub_result(question, run_id)

    monkeypatch.setattr(api, "execute_run", record)
    top = client.get("/anomalies").json()["cards"][0]
    target = incident_06_card(client)  # only in the expanded list
    for card, run_id in ((top, "an-top"), (target, "an-06")):
        response = client.post("/run", json={"run_id": run_id, "anomaly_id": card["id"],
                                             "options": {"sample_mode": True}})
        assert response.status_code == 200, response.text
        assert response.json()["question"] == card["question"]
    assert seen == [(top["question"], "an-top", True), (target["question"], "an-06", True)]
    assert served == [1]


def test_anomaly_id_before_any_board_load_scans_first(
    client: TestClient, served: list[int], real_board: Board, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(api, "execute_run", lambda q, *, run_id, settings: stub_result(q, run_id))
    card_id = real_board.report.cards[0].id
    response = client.post("/run", json={"anomaly_id": card_id})
    assert response.status_code == 200, response.text
    assert served == [1]


def test_incident_06_in_sample_mode_is_a_structured_cache_miss(client: TestClient, served: list[int], logs: Path) -> None:
    card = incident_06_card(client)
    response = client.post("/run", json={"run_id": "an-miss", "anomaly_id": card["id"], "options": {"sample_mode": True}})
    error = assert_error(response, 409, "cache_miss")
    assert error["run_id"] == "an-miss"
    stored = client.get("/runs/an-miss").json()
    assert stored["question"] == card["question"]
    assert stored["error"]["code"] == "cache_miss"


def test_unknown_anomaly_id_is_not_found(client: TestClient, served: list[int], logs: Path,
                                         monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(api, "execute_run", lambda *a, **k: pytest.fail("no run for an unknown card"))
    error = assert_error(client.post("/run", json={"run_id": "an-x", "anomaly_id": "nope|all|all|2017-01-01"}),
                         404, "not_found")
    assert error["run_id"] == "an-x"
    assert not logs.exists()


@pytest.mark.parametrize(
    ("body", "status"),
    [
        ({"anomaly_id": "a", "input": {"query": "Why did order volume spike on 24 November 2017?"}}, 400),
        ({}, 422),
        ({"options": {"sample_mode": True}}, 422),
        ({"anomaly_id": ""}, 422),
        ({"anomaly_id": 7}, 422),
        ({"anomaly_id": "x" * 301}, 422),
    ],
    ids=["both", "neither", "options-only", "empty-id", "not-a-string", "too-long"],
)
def test_anomaly_id_input_errors(client: TestClient, body: dict[str, Any], status: int, logs: Path,
                                 monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(api, "execute_run", lambda *a, **k: pytest.fail("an invalid request must not run"))
    monkeypatch.setattr(api, "BOARD", BoardCache(api._RUN_LOCK, lambda: pytest.fail("no scan for an invalid request")))
    assert_error(client.post("/run", json=body), status, "invalid_input")
    assert not logs.exists()


def test_anomaly_run_while_another_run_holds_the_lock_is_busy(
    client: TestClient, served: list[int], monkeypatch: pytest.MonkeyPatch
) -> None:
    card_id = client.get("/anomalies").json()["cards"][0]["id"]
    started, release = threading.Event(), threading.Event()

    def slow(question: str, *, run_id: str, settings: Settings) -> Result:
        started.set()
        release.wait(10)
        return stub_result(question, run_id)

    monkeypatch.setattr(api, "execute_run", slow)
    first: dict[str, Any] = {}
    thread = threading.Thread(target=lambda: first.update(r=client.post("/run", json={"anomaly_id": card_id})))
    thread.start()
    try:
        assert started.wait(10)
        assert_error(client.post("/run", json={"anomaly_id": card_id}), 429, "busy")
        assert_error(client.get("/anomalies?refresh=true"), 429, "busy")
    finally:
        release.set()
        thread.join(10)
    assert first["r"].status_code == 200
