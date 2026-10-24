# Sprint 8b — Stream Meterless replies, record only missing cache entries

Issue #25. Two changes to `app/llm/generator.py`. Meterless replies are now streamed, so a long
reply no longer hits Nightshift's 45 s provider deadline. A recording run now replays the entries it
already has and calls the model only for the missing ones.

## Finding: the 45 s provider deadline

The Meterless Nightshift runtime bounds its cloud provider call with
`CLOUD_FETCH_DEADLINE_MS = 45_000` (`providers.js`). The deadline covers the time until the
upstream response headers arrive. A non-streamed request gets no headers until the whole reply has
been generated. So any call longer than 45 s returns:

```
HTTP 502  {"code":"provider_error","meterless_detail":"provider_deadline"}
```

Observed on 24 Oct while recording the Markovian cache: the Day 1 Reporter call
(`meterless/deep`, `ReportDraft`) failed in 3 runs in a row, each attempt about 45 s long. A plain
curl reproduces it with a long essay prompt and `max_tokens: 16384`:

- without streaming: HTTP 502 after 45 s;
- with `"stream": true, "stream_options": {"include_usage": true}`: HTTP 200 after 52 s. The
  stream still carries `meterless.routed_model`, `receipt_id` and the final `usage` chunk.

The same failure would hit the live demo on any Planner or Reporter call longer than 45 s.

## What changed

- **Streaming** (`OpenAICompatibleProvider`, `stream=` flag; the generator passes
  `MODEL_STREAM` to `MeterlessProvider`, default `true`):
  - the request body gets `stream: true` and `stream_options: {include_usage: true}` and is sent
    with `httpx.Client.stream`;
  - the reply is parsed as server-sent events: `data:` lines (multi-line data joined, `:` comment
    lines skipped, `[DONE]` ends it). The reply text is the `choices[0].delta.content` pieces
    joined. Reasoning deltas (`reasoning_content`, `reasoning`) are dropped;
  - `usage` comes from the last chunk that has one (the include-usage chunk). `meterless` blocks
    are merged from every chunk where one appears. Then the same `_reply_metadata` as the buffered
    path reads `routed_model` and the receipt (block `receipt_id`, `receipt.id`, or the
    `meterless-receipt` response header);
  - errors are mapped as before. An HTTP error status (checked before the body is read) goes through
    the existing branch: 429 and 5xx are retried after 2/4/8 s, so a 502 `provider_deadline` is a
    retryable 5xx; 401/403 is `unauthorized`; any other 4xx is `http_error`. An `error` event
    inside a 200 stream is mapped to the status it names (`status`, `status_code` or a numeric
    `code`), else to 502, and then takes the same branch. A stream that is not valid JSON, or that
    has no `choices` chunk at all, is `bad_response`;
  - if the server ignores `stream` and answers `application/json`, the whole completion is read as
    before. Because of that, the existing JSON-mocked tests run unchanged with streaming on;
  - timeouts: the client timeout is httpx's read timeout, i.e. the longest gap allowed between two
    chunks. A stall past it is the existing `timeout` error. With a per-call deadline
    (`generator.with_limits`), the request timeout is still cut to the time left. The deadline is
    now also checked after every event, so a stream that keeps trickling ends at the deadline with
    `timeout` ("per-call deadline reached during the stream");
  - `MODEL_STREAM=false` sends the old buffered request: same body, no `stream` keys. The NVIDIA
    direct fallback is always buffered.
- **Record only what's missing** (`RECORD_REUSE_EXISTING`, default `true`): with
  `RECORD_CACHE=true` in live mode, `_complete` looks the key up first. An entry with
  `recorded_with == "meterless"` is replayed through the existing cache branch (provider `cache`,
  no HTTP call, the file is not rewritten). An entry recorded with anything else (`stub`) is called
  again and overwritten. A miss is called and written as before. With `false`, every call goes to
  the model, as before this sprint. Sample mode is unchanged.
- `.env.example` documents both settings. No other default changed.

## How it was tested

- `tests/test_generator_streaming.py` (18 tests):
  - mocked SSE transport: content joined with reasoning deltas dropped; usage, routed model and
    receipt captured (from chunks and from the header); multi-line data, comments and CRLF;
    HTTP 502 `provider_deadline` then a 200 stream retries once (sleep 2 s) and succeeds; an
    error event is retried like a 5xx; four error events exhaust the retries and fall back to
    buffered NVIDIA; a 401 error event is not retried; unreadable streams give `bad_response`;
    `MODEL_STREAM=false` sends exactly `model, messages, temperature, max_tokens`; a JSON answer
    to a stream request is still read;
  - real local HTTP server on 127.0.0.1: a stream that stops sending chunks for longer than the
    read timeout (0.5 s) becomes `timeout` in under 2.5 s; a stream that sends a chunk every 0.1 s
    for 6 s ends at a 0.6 s per-call deadline with `timeout`;
  - `RECORD_REUSE_EXISTING`: an existing meterless entry is replayed with no HTTP request and the
    file is unchanged; a stub entry is called again and overwritten with the meterless reply; a
    miss is called once and reused on the second call; with `false` both calls go to the model;
    live mode without `RECORD_CACHE` never reads the cache; sample mode still replays a stub
    entry with no network.
- Full suite `pytest -q`, `ruff check .`, plan check B (`python -m app.llm.check`), and plan
  check C (sample-mode `run.py` on the Day 1 question, `scripts/check_result.py` PASS).
- Not tested live: the build sandbox has no Nightshift token. The coordinator records through
  Nightshift on top of this branch after review.

## Known limits

- The deadline is checked between events. One read that blocks in a stall can run past the
  deadline, by at most that request's read timeout: the smaller of the provider timeout and the
  time left when the request started.
- The Meterless read timeout is the provider-contract `METERLESS_TIMEOUT_SECONDS` (180 s), as
  before. `MODEL_TIMEOUT_SECONDS` (60 s) is still the NVIDIA timeout. The issue text says
  `MODEL_TIMEOUT_SECONDS`, but this sprint changes no defaults, so the Meterless value stays 180 s.
- If the connection drops in the middle of a stream, httpx raises a protocol error. That is
  reported as `offline` and goes to the NVIDIA fallback, the same as any other connection error.
- Reuse trusts only `recorded_with == "meterless"`. Entries recorded through the NVIDIA fallback
  are called again.
- The query-result cache (`data/sample/query_cache`) is still rewritten on every recording run,
  as before. On one machine with `DUCKDB_THREADS=1` the rows are the same.
