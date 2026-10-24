"""Streamed Meterless replies and record-only-missing (Sprint 8b, issue #25).

Most tests use a mocked SSE transport; the two timeout tests run a local HTTP server on 127.0.0.1
that stops sending chunks, so httpx's real read timeout and the per-call deadline are exercised.
"""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable, Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx
import pytest

from app.llm.generator import (
    CallLimits,
    MeterlessProvider,
    ProviderError,
    ResponseCache,
)
from app.trace import TraceWriter
from tests.test_generator import (
    GOOD,
    MESSAGES,
    TOKEN,
    Answer,
    Recorder,
    chat_reply,
    make_generator,
)

ROUTED = "nvidia/nemotron-3.5-super-vl-120b-a12b"


def chunk(content: str | None = None, *, model: str = "meterless/deep", **extra: object) -> dict:
    delta: dict = {} if content is None else {"content": content}
    return {"id": "chatcmpl-s", "object": "chat.completion.chunk", "model": model,
            "choices": [{"index": 0, "delta": delta, "finish_reason": None}], **extra}


USAGE_CHUNK = {"id": "chatcmpl-s", "model": "meterless/deep", "choices": [],
               "usage": {"prompt_tokens": 40, "completion_tokens": 9, "total_tokens": 49}}


def sse_bytes(*events: dict | str, done: bool = True) -> bytes:
    lines = [f"data: {e if isinstance(e, str) else json.dumps(e)}\n\n" for e in events]
    if done:
        lines.append("data: [DONE]\n\n")
    return "".join(lines).encode()


def sse(*events: dict | str, done: bool = True, headers: dict[str, str] | None = None) -> httpx.Response:
    return httpx.Response(
        200, headers={"content-type": "text/event-stream", **(headers or {})}, content=sse_bytes(*events, done=done)
    )


def good_stream(**meterless: str) -> httpx.Response:
    return sse(
        chunk("", meterless={"routed_model": ROUTED}),
        {"choices": [{"index": 0, "delta": {"reasoning_content": "think: 2+3 is 5"}}]},
        chunk('{"answer": 5,'),
        {"choices": [{"index": 0, "delta": {"reasoning": "more thinking"}}]},
        chunk(' "word": "five"}'),
        {**USAGE_CHUNK, "meterless": {"receipt_id": "rcpt_stream_1", **meterless}},
    )


# --- streaming -----------------------------------------------------------------------------------


def test_stream_joins_content_and_captures_usage_routed_model_and_receipt(tmp_path: Path) -> None:
    rec = Recorder({"127.0.0.1": [good_stream()]})
    result = make_generator(tmp_path, rec)(MESSAGES, schema=Answer, role="reporter")
    assert result.ok, result.error
    assert result.content == '{"answer": 5, "word": "five"}'  # reasoning deltas are not in the reply
    assert result.parsed == {"answer": 5, "word": "five"}
    assert result.model_routed == ROUTED
    assert result.receipt_id == "rcpt_stream_1"
    assert result.usage == {"prompt_tokens": 40, "completion_tokens": 9, "total_tokens": 49}
    body = rec.bodies()[0]
    assert body["stream"] is True and body["stream_options"] == {"include_usage": True}
    assert body["model"] == "meterless/deep"
    request = rec.requests[0]
    assert request.headers["meterless-app"] == "explain-why" and request.headers["meterless-scope"] == "user"
    line = TraceWriter(tmp_path / "logs", "gen-test").read()[0]
    assert line["provider"] == "meterless" and line["status"] == "ok"
    assert line["model_routed"] == ROUTED and line["receipt_id"] == "rcpt_stream_1"
    assert line["tokens"]["total_tokens"] == 49


def test_stream_receipt_from_response_header_and_model_from_chunks(tmp_path: Path) -> None:
    stream = sse(chunk(GOOD, model="nvidia/routed-x"), USAGE_CHUNK, headers={"meterless-receipt": "rcpt_hdr"})
    result = make_generator(tmp_path, Recorder({"127.0.0.1": [stream]}))(MESSAGES, schema=Answer)
    assert result.ok and result.receipt_id == "rcpt_hdr"
    assert result.model_routed == "meterless/deep"  # last chunk's model; no meterless block sent


def test_stream_handles_multiline_data_comments_and_crlf(tmp_path: Path) -> None:
    raw = (
        b": keep-alive\r\n\r\n"
        b'data: {"model": "m", "choices": [{"index": 0,\r\n'
        b'data: "delta": {"content": "{\\"answer\\": 5, \\"word\\": \\"five\\"}"}}]}\r\n\r\n'
        b"data: [DONE]\r\n\r\n"
    )
    stream = httpx.Response(200, headers={"content-type": "text/event-stream; charset=utf-8"}, content=raw)
    result = make_generator(tmp_path, Recorder({"127.0.0.1": [stream]}))(MESSAGES, schema=Answer)
    assert result.ok, result.error
    assert result.parsed == {"answer": 5, "word": "five"}
    assert result.usage is None


def test_provider_deadline_502_then_stream_retries_and_succeeds(tmp_path: Path) -> None:
    sleeps: list[float] = []
    deadline = httpx.Response(502, json={"code": "provider_error", "meterless_detail": "provider_deadline"})
    rec = Recorder({"127.0.0.1": [deadline, good_stream()]})
    result = make_generator(tmp_path, rec, sleeps)(MESSAGES, schema=Answer, role="reporter")
    assert result.ok and result.provider == "meterless"
    assert result.parsed["word"] == "five"
    assert sleeps == [2.0] and result.retries == 1
    assert len(rec.requests) == 2
    assert all(json.loads(r.content)["stream"] is True for r in rec.requests)


def test_error_event_in_stream_is_retried_like_a_5xx(tmp_path: Path) -> None:
    sleeps: list[float] = []
    failed = sse(chunk('{"answer"'), {"error": {"code": "provider_error", "meterless_detail": "provider_deadline"}},
                 done=False)
    rec = Recorder({"127.0.0.1": [failed, good_stream()]})
    result = make_generator(tmp_path, rec, sleeps)(MESSAGES, schema=Answer)
    assert result.ok and result.parsed == {"answer": 5, "word": "five"}
    assert sleeps == [2.0] and result.retries == 1


def test_error_events_exhaust_retries_then_fall_back_to_buffered_nvidia(tmp_path: Path) -> None:
    sleeps: list[float] = []
    failing = [sse({"error": {"message": "upstream", "status": 503}}, done=False) for _ in range(4)]
    nvidia = httpx.Response(200, json=chat_reply(GOOD, model="nvidia/test-model"))
    rec = Recorder({"127.0.0.1": failing, "nvidia.test": [nvidia]})
    result = make_generator(tmp_path, rec, sleeps)(MESSAGES, schema=Answer)
    assert sleeps == [2.0]  # Meterless keeps the third of MAX_MODEL_ATTEMPTS=3 for the fallback
    assert result.ok and result.provider == "nvidia"
    assert result.attempts[0]["status"] == "retries_exhausted"
    assert len(rec.requests) == 3
    assert result.attempts[-1]["attempt"] == 3 and result.attempts[-1]["fallback_reason"].startswith("retries_exhausted")
    nvidia_body = json.loads(rec.requests[-1].content)
    assert "stream" not in nvidia_body and "stream_options" not in nvidia_body  # the fallback stays buffered


def test_unauthorized_error_event_is_not_retried(tmp_path: Path) -> None:
    sleeps: list[float] = []
    rec = Recorder({"127.0.0.1": [sse({"error": {"message": "bad token", "code": "401"}}, done=False)]})
    result = make_generator(tmp_path, rec, sleeps)(MESSAGES)
    assert result.ok is False and result.error["code"] == "unauthorized"
    assert sleeps == []


def test_unreadable_stream_is_bad_response(tmp_path: Path) -> None:
    rec = Recorder({"127.0.0.1": [sse("{not json"), sse({"meterless": {"receipt_id": "r"}})]})
    gen = make_generator(tmp_path, rec)
    assert gen(MESSAGES).error["code"] == "bad_response"
    assert gen(MESSAGES).error["code"] == "bad_response"  # a stream with no choices at all


def test_model_stream_false_sends_the_buffered_request(tmp_path: Path) -> None:
    reply = chat_reply(GOOD, meterless={"routed_model": ROUTED, "receipt_id": "rcpt_buf"})
    rec = Recorder({"127.0.0.1": [httpx.Response(200, json=reply)]})
    gen = make_generator(tmp_path, rec, model_stream=False)
    assert gen.meterless.stream is False
    result = gen(MESSAGES, schema=Answer, role="planner")
    assert result.ok and result.parsed["answer"] == 5
    assert result.model_routed == ROUTED and result.receipt_id == "rcpt_buf"
    body = rec.bodies()[0]
    assert set(body) == {"model", "messages", "temperature", "max_tokens"}


def test_stream_request_answered_with_plain_json_is_still_read(tmp_path: Path) -> None:
    rec = Recorder({"127.0.0.1": [httpx.Response(200, json=chat_reply(GOOD, meterless={"receipt_id": "r9"}))]})
    gen = make_generator(tmp_path, rec)
    assert gen.meterless.stream is True
    result = gen(MESSAGES, schema=Answer)
    assert result.ok and result.receipt_id == "r9" and result.usage["total_tokens"] == 18


# --- timeouts against a real local server --------------------------------------------------------


class _Server:
    """A local HTTP server whose chat endpoint writes the SSE byte chunks `script()` yields."""

    def __init__(self, script: Callable[[], Iterator[bytes]]) -> None:
        outer = self
        self.stop = threading.Event()

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                self.rfile.read(int(self.headers.get("content-length", 0)))
                self.send_response(200)
                self.send_header("content-type", "text/event-stream")
                self.end_headers()
                try:
                    for piece in script():
                        if outer.stop.is_set():
                            return
                        self.wfile.write(piece)
                        self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError):
                    return

            def log_message(self, *args: object) -> None:
                return

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.httpd.daemon_threads = True
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    def __enter__(self) -> str:
        self.thread.start()
        return f"http://127.0.0.1:{self.httpd.server_address[1]}/v1"

    def __exit__(self, *exc: object) -> None:
        self.stop.set()
        self.httpd.shutdown()
        self.httpd.server_close()


def _chat(provider: MeterlessProvider, limits: CallLimits | None = None) -> None:
    provider.chat(MESSAGES, model="meterless/deep", temperature=0.2, max_tokens=64, limits=limits)


def test_stream_that_stops_sending_chunks_past_the_read_timeout_is_a_timeout() -> None:
    def stalls() -> Iterator[bytes]:
        yield sse_bytes(chunk('{"answer": 5'), done=False)
        time.sleep(3.0)  # longer than the 0.5 s read timeout below
        yield sse_bytes(chunk("}"))

    with _Server(stalls) as url:
        provider = MeterlessProvider(base_url=url, token=TOKEN, timeout=0.5, sleep=lambda _s: None)
        assert provider.stream is False  # the provider default; the generator passes MODEL_STREAM
        provider.stream = True
        started = time.monotonic()
        with pytest.raises(ProviderError) as info:
            _chat(provider)
        elapsed = time.monotonic() - started
    assert info.value.code == "timeout"
    assert elapsed < 2.5


def test_per_call_deadline_applies_to_the_whole_stream() -> None:
    def trickles() -> Iterator[bytes]:
        for _ in range(60):  # a chunk every 0.1 s for 6 s: never a read timeout
            yield sse_bytes(chunk("x"), done=False)
            time.sleep(0.1)
        yield b"data: [DONE]\n\n"

    with _Server(trickles) as url:
        provider = MeterlessProvider(base_url=url, token=TOKEN, timeout=5.0, sleep=lambda _s: None, stream=True)
        started = time.monotonic()
        with pytest.raises(ProviderError) as info:
            _chat(provider, CallLimits(time.monotonic() + 0.6, 0))
        elapsed = time.monotonic() - started
    assert info.value.code == "timeout"
    assert "during the stream" in info.value.message
    assert elapsed < 2.0


# --- RECORD_REUSE_EXISTING -----------------------------------------------------------------------


def _seed(tmp_path: Path, recorded_with: str, reply: str = GOOD) -> Path:
    key = ResponseCache.key(MESSAGES, "Answer", "planner")
    return ResponseCache(tmp_path / "cache").put(
        key,
        {"role": "planner", "schema": "Answer", "messages": MESSAGES, "reply": reply, "provider": recorded_with,
         "model_requested": "meterless/deep", "model_routed": f"{recorded_with}-model", "receipt_id": "rcpt_old",
         "usage": None, "recorded_with": recorded_with, "recorded_at": "2026-10-23T10:00:00+00:00"},
    )


def test_recording_replays_an_existing_meterless_entry_without_a_call(tmp_path: Path) -> None:
    path = _seed(tmp_path, "meterless")
    before = path.read_text()
    rec = Recorder({})  # any HTTP request fails the test
    result = make_generator(tmp_path, rec, record_cache=True)(MESSAGES, schema=Answer, role="planner")
    assert result.ok, result.error
    assert result.from_cache and result.provider == "cache"
    assert result.parsed == {"answer": 5, "word": "five"} and result.receipt_id == "rcpt_old"
    assert rec.requests == []
    assert path.read_text() == before
    line = TraceWriter(tmp_path / "logs", "gen-test").read()[0]
    assert line["provider"] == "cache" and line["recorded_with"] == "meterless"


def test_recording_calls_again_and_overwrites_a_stub_entry(tmp_path: Path) -> None:
    path = _seed(tmp_path, "stub", reply='{"answer": 0, "word": "zero"}')
    rec = Recorder({"127.0.0.1": [good_stream()]})
    result = make_generator(tmp_path, rec, record_cache=True)(MESSAGES, schema=Answer, role="planner")
    assert result.ok and result.provider == "meterless" and result.parsed["answer"] == 5
    assert len(rec.requests) == 1
    entry = json.loads(path.read_text())
    assert entry["recorded_with"] == "meterless" and entry["reply"] == GOOD
    assert entry["receipt_id"] == "rcpt_stream_1" and entry["model_routed"] == ROUTED


def test_recording_a_miss_calls_the_model_and_writes_it(tmp_path: Path) -> None:
    rec = Recorder({"127.0.0.1": [good_stream()]})
    gen = make_generator(tmp_path, rec, record_cache=True)
    assert gen(MESSAGES, schema=Answer, role="planner").provider == "meterless"
    assert gen(MESSAGES, schema=Answer, role="planner").provider == "cache"  # the second time it is reused
    assert len(rec.requests) == 1


def test_reuse_disabled_sends_every_call_to_the_model(tmp_path: Path) -> None:
    path = _seed(tmp_path, "meterless", reply='{"answer": 0, "word": "zero"}')
    rec = Recorder({"127.0.0.1": [good_stream(), good_stream()]})
    gen = make_generator(tmp_path, rec, record_cache=True, record_reuse_existing=False)
    assert gen(MESSAGES, schema=Answer, role="planner").provider == "meterless"
    assert gen(MESSAGES, schema=Answer, role="planner").provider == "meterless"
    assert len(rec.requests) == 2
    assert json.loads(path.read_text())["reply"] == GOOD


def test_live_without_record_cache_never_reads_the_cache(tmp_path: Path) -> None:
    _seed(tmp_path, "meterless")
    rec = Recorder({"127.0.0.1": [good_stream()]})
    result = make_generator(tmp_path, rec)(MESSAGES, schema=Answer, role="planner")
    assert result.provider == "meterless" and len(rec.requests) == 1


def test_sample_mode_still_replays_stub_entries_without_network(tmp_path: Path) -> None:
    _seed(tmp_path, "stub", reply='{"answer": 0, "word": "zero"}')
    rec = Recorder({})
    result = make_generator(tmp_path, rec, sample_mode=True)(MESSAGES, schema=Answer, role="planner")
    assert result.ok and result.from_cache and result.parsed["word"] == "zero"
    assert rec.requests == []


def test_bounded_streamed_calls_keep_the_attempt_cap_and_trace_fields(tmp_path: Path) -> None:
    """Through `with_limits` (the run_by_deadline worker) a streamed step still sends at most 3 requests,
    and the trace lines carry provider, model, attempt and, on the fallback, fallback_reason."""
    failing = [sse({"error": {"message": "upstream", "status": 503}}, done=False) for _ in range(4)]
    nvidia = httpx.Response(200, json=chat_reply(GOOD, model="nvidia/test-model"))
    rec = Recorder({"127.0.0.1": failing, "nvidia.test": [nvidia]})
    generator = make_generator(tmp_path, rec)
    result = generator.with_limits(deadline_seconds=30, max_retries=3)(MESSAGES, schema=Answer, run_id="gen-test")
    assert result.ok and result.provider == "nvidia"
    assert len(rec.requests) == 3
    assert json.loads(rec.requests[0].content)["stream"] is True
    lines = [json.loads(line) for line in (tmp_path / "logs" / "trace-gen-test.jsonl").read_text().splitlines()]
    calls = [line for line in lines if line.get("provider") in ("meterless", "nvidia")]
    assert [(c["provider"], c["attempt"]) for c in calls] == [("meterless", 2), ("nvidia", 3)]
    assert all(c.get("model") for c in calls)
    assert "fallback_reason" not in calls[0] and calls[1]["fallback_reason"].startswith("retries_exhausted")
