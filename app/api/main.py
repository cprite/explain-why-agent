"""FastAPI app: start a run, read back its result and trace (architecture §7 and §8).

    uvicorn app.api.main:app --host 0.0.0.0 --port 8000

- `POST /run` runs one investigation through `app.runner.execute_run`, the same code path as
  `run.py`, and answers with the result JSON.
- `GET /runs/{id}` returns `logs/result-<id>.json`; `GET /runs/{id}/trace` returns
  `logs/trace-<id>.jsonl` as NDJSON.
- `GET /health` answers without touching the model or the data.
- `GET /anomalies` returns the scanner's cards (overall top ten and the per-metric board), scanned
  on first use and cached; `?metric=KEY&limit=N` returns one metric's flagged episodes ranked within
  it. `POST /run` also takes `{"anomaly_id": ...}` and runs that card's pre-filled question.
- `GET /` serves the web page (`web/index.html`, `web/app.js`, `web/style.css`).

Every error has one shape: `{"error": {"code": ..., "message": ..., "run_id": ...}}`. One run at a
time per process: a second `POST /run` while one is running gets `busy` (429) at once, which also
keeps memory to one DuckDB instance; a scan for `GET /anomalies` takes the same lock. A run that passes `API_RUN_TIMEOUT_SECONDS` gets `timeout`
(504); it cannot be killed, so it finishes in the background, still holding the run lock, and its
result appears at `GET /runs/{id}` when it ends.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.anomalies import MAX_METRIC_LIMIT, Board, BoardCache, Busy
from app.config import Settings, get_settings, resolve_path
from app.runner import RUN_ID_RULE, execute_run, new_run_id, valid_run_id
from app.schemas import Result, validate_result_file

MAX_QUERY_CHARS = 1000
MAX_ANOMALY_ID_CHARS = 300
WEB_DIR = Path(__file__).resolve().parents[2] / "web"
RUN_TIMEOUT_META = '<meta name="run-timeout-seconds" content="600">'

log = logging.getLogger("app.api")
_RUN_LOCK = threading.Lock()
BOARD = BoardCache(_RUN_LOCK)


class RunInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(description="The question to investigate.")

    @field_validator("query")
    @classmethod
    def _query_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("query must not be empty")
        if len(value) > MAX_QUERY_CHARS:
            raise ValueError(f"query must be at most {MAX_QUERY_CHARS} characters (got {len(value)})")
        return value


class RunOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sample_mode: bool | None = Field(default=None, description="Default: SAMPLE_MODE from the environment.")


class RunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str | None = Field(default=None, description="Generated when absent.")
    input: RunInput | None = Field(default=None, description="A typed question; or give anomaly_id.")
    anomaly_id: str | None = Field(
        default=None, min_length=1, max_length=MAX_ANOMALY_ID_CHARS,
        description="Id of a card from GET /anomalies; its pre-filled question is run.",
    )
    options: RunOptions = Field(default_factory=RunOptions)

    @model_validator(mode="after")
    def _question_given(self) -> RunRequest:
        if self.input is None and self.anomaly_id is None:
            raise ValueError("input.query or anomaly_id is required")
        return self

    @field_validator("run_id")
    @classmethod
    def _safe_run_id(cls, value: str | None) -> str | None:
        if value is not None and not valid_run_id(value):
            raise ValueError(RUN_ID_RULE)
        return value


class ApiError(Exception):
    """An error answered in the shared shape."""

    def __init__(self, status: int, code: str, message: str, run_id: str | None = None) -> None:
        super().__init__(message)
        self.status, self.code, self.message, self.run_id = status, code, message, run_id


def error_response(status: int, code: str, message: str, run_id: str | None = None) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message, "run_id": run_id}})


app = FastAPI(
    title="explain-why-agent",
    description="Explain why a business metric changed: ranked causes with evidence.",
    version="0.13.0",
)


@app.exception_handler(ApiError)
async def _api_error(_: Request, exc: ApiError) -> JSONResponse:
    return error_response(exc.status, exc.code, exc.message, exc.run_id)


@app.exception_handler(RequestValidationError)
async def _invalid_input(_: Request, exc: RequestValidationError) -> JSONResponse:
    problems = []
    for item in exc.errors():
        loc = [str(part) for part in item.get("loc", ()) if part != "body"]
        message = str(item.get("msg", "invalid")).removeprefix("Value error, ")
        problems.append(f"{'.'.join(loc) or 'body'}: {message}")
    body = exc.body if isinstance(exc.body, dict) else {}
    run_id = body.get("run_id") if isinstance(body.get("run_id"), str) and valid_run_id(body["run_id"]) else None
    return error_response(422, "invalid_input", "; ".join(problems) or "invalid request", run_id)


@app.exception_handler(StarletteHTTPException)
async def _http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
    codes = {404: "not_found", 405: "method_not_allowed"}
    return error_response(exc.status_code, codes.get(exc.status_code, "http_error"), str(exc.detail))


@app.exception_handler(Exception)
async def _unexpected(_: Request, exc: Exception) -> JSONResponse:
    log.error("unexpected error in the API layer", exc_info=exc)
    return error_response(500, "run_failed", f"unexpected {type(exc).__name__} in the API; details are in the server log")


def _log_file(settings: Settings, run_id: str | None, kind: str, suffix: str) -> Path:
    """`<LOG_DIR>/<kind>-<run_id><suffix>`, only for a run id that passes the run-id rule."""
    if run_id is None or not valid_run_id(run_id):
        raise ApiError(400, "invalid_input", RUN_ID_RULE)
    log_dir = resolve_path(settings.log_dir).resolve()
    path = (log_dir / f"{kind}-{run_id}{suffix}").resolve()
    if path.parent != log_dir:  # belt and braces: the rule above already excludes separators
        raise ApiError(400, "invalid_input", RUN_ID_RULE)
    return path


@app.get("/health")
def health() -> dict[str, Any]:
    """Liveness; reads the settings only (no model, no data)."""
    return {"status": "ok", "sample_mode": get_settings().sample_mode}


@app.post("/run")
def post_run(body: RunRequest) -> JSONResponse:
    """Run one investigation and return its result (architecture §7)."""
    settings = get_settings()
    if body.options.sample_mode is not None:
        settings = settings.model_copy(update={"sample_mode": body.options.sample_mode})
    run_id = body.run_id or new_run_id()
    timeout = settings.api_run_timeout_seconds
    if body.input is not None and body.anomaly_id is not None:
        raise ApiError(400, "invalid_input", "give either input.query or anomaly_id, not both", run_id)
    if body.input is not None:
        question = body.input.query
    else:
        card = _board(run_id=run_id).by_id.get(body.anomaly_id or "")
        if card is None:
            raise ApiError(404, "not_found", f"no anomaly card with id {body.anomaly_id}", run_id)
        question = card.question

    if not _RUN_LOCK.acquire(blocking=False):
        raise ApiError(429, "busy", "a run is already in progress; try again when it has finished", run_id)
    outcome: dict[str, Any] = {}

    def work() -> None:
        try:
            outcome["result"] = execute_run(question, run_id=run_id, settings=settings)
        except Exception as exc:  # noqa: BLE001 - reported to the caller as run_failed
            outcome["error"] = exc
        finally:
            _RUN_LOCK.release()

    try:
        worker = threading.Thread(target=work, name=f"run-{run_id}", daemon=True)
        worker.start()
    except Exception:
        _RUN_LOCK.release()
        raise
    worker.join(timeout)
    if worker.is_alive():
        log.warning("run %s passed API_RUN_TIMEOUT_SECONDS=%s; it continues in the background", run_id, timeout)
        raise ApiError(
            504, "timeout",
            f"the run did not finish within API_RUN_TIMEOUT_SECONDS={timeout:g}; it finishes in the background "
            f"and its result will be at GET /runs/{run_id}",
            run_id,
        )
    if "error" in outcome:
        exc = outcome["error"]
        log.error("run %s raised", run_id, exc_info=exc)
        raise ApiError(500, "run_failed", f"the run failed with an unexpected {type(exc).__name__}", run_id)

    result: Result = outcome["result"]
    if result.status == "error" and result.error is not None:
        if result.error.code == "cache_miss":
            raise ApiError(409, "cache_miss", result.error.message, run_id)
        if result.error.code == "internal":
            raise ApiError(
                500, "run_failed",
                f"the run ended with an internal error; see GET /runs/{run_id}/trace", run_id,
            )
    return JSONResponse(result.model_dump(mode="json"))


@app.get("/runs/{run_id}")
def get_run(run_id: str) -> JSONResponse:
    """The stored result of a finished run."""
    path = _log_file(get_settings(), run_id, "result", ".json")
    if not path.is_file():
        raise ApiError(404, "not_found", f"no finished run with id {run_id}", run_id)
    try:
        result = validate_result_file(path)
    except ValueError as exc:
        log.error("stored result %s is invalid: %s", path.name, exc)
        raise ApiError(500, "run_failed", "the stored result does not validate", run_id) from None
    return JSONResponse(result.model_dump(mode="json"))


@app.get("/runs/{run_id}/trace")
def get_trace(run_id: str) -> Response:
    """The run's trace, one JSON object per line (also while the run is still going)."""
    path = _log_file(get_settings(), run_id, "trace", ".jsonl")
    if not path.is_file():
        raise ApiError(404, "not_found", f"no trace for run id {run_id}", run_id)
    return Response(content=path.read_bytes(), media_type="application/x-ndjson")


def _board(refresh: bool = False, run_id: str | None = None) -> Board:
    try:
        return BOARD.get(refresh=refresh)
    except Busy as exc:
        raise ApiError(429, "busy", str(exc), run_id) from None


@app.get("/anomalies")
def get_anomalies(
    refresh: bool = False,
    metric: str | None = Query(default=None, min_length=1, max_length=100),
    limit: int = Query(default=10, ge=1),
) -> JSONResponse:
    """The scanner's cards: overall top ten and per-metric board, or one metric's ranked list."""
    board = _board(refresh=refresh)
    if metric is None:
        report = board.report
        return JSONResponse({
            "generated_at": report.generated_at.isoformat(),
            "timed_out": report.timed_out,
            "episodes_found": report.episodes_found,
            "cards": [card.model_dump(mode="json") for card in report.cards],
            "by_metric": [b.model_dump(mode="json") for b in report.by_metric],
        })
    chosen = board.metric(metric, min(limit, MAX_METRIC_LIMIT))
    if chosen is None:
        raise ApiError(404, "not_found", f"no configured metric {metric}")
    return JSONResponse(chosen.model_dump(mode="json"))


@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    """The web page; the client-side wait is capped at API_RUN_TIMEOUT_SECONDS."""
    html = (WEB_DIR / "index.html").read_text(encoding="utf-8")
    timeout = get_settings().api_run_timeout_seconds
    html = html.replace(RUN_TIMEOUT_META, f'<meta name="run-timeout-seconds" content="{timeout:g}">')
    return HTMLResponse(html)


@app.get("/web/app.js")
def web_script() -> FileResponse:
    return FileResponse(WEB_DIR / "app.js", media_type="text/javascript")


@app.get("/web/style.css")
def web_style() -> FileResponse:
    return FileResponse(WEB_DIR / "style.css", media_type="text/css")
