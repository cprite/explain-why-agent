"""Regression tests for the Sprint 7 review items fixed in Sprint 8 (issue #21).

- Heuristic extraction (carryover step 3) files a rejection under the hypothesis it is about, and a
  negated, questioned or ambiguous rejection as an open question.
- A compression call that times out does not leave its worker thread running: the compressor gets a
  per-call deadline and no retries through `Generator.with_limits`.
- Fallback item ids are unique across a run.
- The ChunkManager takes the real ContextBuilder payload (a dict).

No network: the generator runs over an httpx MockTransport.
"""

from __future__ import annotations

import threading
import time
from typing import Any

import httpx

from app.config import Settings
from app.engines.markovian.carryover import (
    FallbackIds,
    RoundOutput,
    build_carryover,
    heuristic_items,
)
from app.engines.markovian.chunks import ChunkManager
from app.engines.markovian.config import MarkovianConfig
from app.engines.world_model.context import ContextBuilder, Intent
from app.engines.world_model.store import WorldStore
from app.llm.generator import Generator

TOKEN = "rt-test-secret-7f3a9c"
REVIEW_1 = "H4 is supported; H1 not supported by duplicates (0 rows)\nH2 has not been ruled out yet, needs a check"
REVIEW_2 = (
    "H3 cannot be ruled out yet; it is the leading cause\n1. H3 leading cause: mix shift +14%\n"
    "H4 is not supported? Unclear.\nWe have not excluded H5, still to test"
)


def ids(items: Any) -> list[str]:
    return [item.id for item in items]


# --- heuristic attribution and negation -------------------------------------------------------------


def test_rejection_is_filed_under_the_hypothesis_it_names_not_the_first_on_the_line() -> None:
    draft = heuristic_items(REVIEW_1)
    assert ids(draft.ruled_out) == ["H1"]
    assert ids(draft.ranking) == ["H4"]
    assert draft.open_questions == ["H2 has not been ruled out yet, needs a check"]


def test_negated_and_questioned_rejections_are_open_questions() -> None:
    draft = heuristic_items(REVIEW_2)
    assert draft.ruled_out == []
    assert ids(draft.ranking) == ["H3"]  # the leading hypothesis is kept, not ruled out
    assert draft.open_questions == [
        "H3 cannot be ruled out yet",
        "H4 is not supported? Unclear.",
        "We have not excluded H5, still to test",
    ]


def test_contrast_clauses_and_ambiguous_rejections() -> None:
    draft = heuristic_items(
        "H2 is supported, while H3 was ruled out by the seller split\n"
        "H5 and H6 were both rejected after the rerun\n"
        "Ruled out: H1 (data_artefact): Refuted by the data: 0 duplicate rows"
    )
    assert ids(draft.ranking) == ["H2"]
    assert ids(draft.ruled_out) == ["H3", "H1"]
    assert draft.open_questions == ["H5 and H6 were both rejected after the rerun"]


def test_negation_words_before_a_rejection_phrase() -> None:
    for line in ("H7 is not refuted by the price data", "H7 could not be excluded", "H7 is yet to be rejected",
                 "H7 has never been ruled out"):
        draft = heuristic_items(line)
        assert draft.ruled_out == [], line
        assert draft.open_questions == [line], line
    assert ids(heuristic_items("H7 was refuted: share flat at 1.0").ruled_out) == ["H7"]


# --- fallback ids -----------------------------------------------------------------------------------


def test_fallback_ids_do_not_collide_after_an_item_is_removed() -> None:
    text = "1. H1 leading: volume up\n2. sellers broadened\nH1 ruled out after all\n3. category mix moved"
    draft = heuristic_items(text)
    assert ids(draft.ruled_out) == ["H1"]
    assert len(draft.ranking) == 2 and len(set(ids(draft.ranking))) == 2  # both unlabelled lines kept


def test_fallback_ids_are_unique_across_a_run() -> None:
    shared = FallbackIds()
    config = MarkovianConfig(chunk_budget_chars=2000, carryover_budget_chars=600)
    text = "1. sellers broadened\n- duplicates ruled out (0 rows)"
    first = build_carryover(RoundOutput(text), config=config, rounds_left=3, fallback_ids=shared)
    second = build_carryover(RoundOutput(text), config=config, rounds_left=2, fallback_ids=shared)
    assert first.carryover_step == second.carryover_step == "heuristic_extraction"
    first_ids = ids(first.ranking) + ids(first.ruled_out)
    second_ids = ids(second.ranking) + ids(second.ruled_out)
    assert len(first_ids) == len(second_ids) == 2
    assert not set(first_ids) & set(second_ids)


# --- compressor deadline ----------------------------------------------------------------------------


def generator(handler: Any, **overrides: Any) -> Generator:
    values = {"sample_mode": False, "meterless_runtime_token": TOKEN, "nvidia_api_key": "", "max_retries": 3,
              "log_dir": "/tmp/unused-logs"}
    values.update(overrides)
    return Generator(Settings(**values), transport=httpx.MockTransport(handler), sleep=lambda _s: None)


def compress_threads() -> list[threading.Thread]:
    return [t for t in threading.enumerate() if t.name == "carryover-compress" and t.is_alive()]


def test_compression_timeout_leaves_no_thread_running() -> None:
    """The bounded compressor's HTTP call gives up before the cascade stops waiting."""
    seen: list[float] = []

    def slow_server(request: httpx.Request) -> httpx.Response:
        read_timeout = request.extensions["timeout"]["read"]
        seen.append(read_timeout)
        time.sleep(min(read_timeout, 5.0))  # a server that answers later than the client waits
        raise httpx.ReadTimeout("read timed out", request=request)

    config = MarkovianConfig(chunk_budget_chars=2000, carryover_budget_chars=600, chunk_timeout_seconds=5,
                             compression_timeout_seconds=0.5)
    started = time.monotonic()
    result = build_carryover(RoundOutput("1. H3 leading: mix shift +14%"), config=config, rounds_left=2,
                             generate=generator(slow_server))
    elapsed = time.monotonic() - started
    assert result.carryover_step == "heuristic_extraction"
    compression = result.attempts[1]
    assert compression.step == "model_compression" and compression.status == "failed"
    assert "timeout" in compression.detail
    assert len(seen) == 1 and seen[0] <= 0.45 + 1e-6  # one request, cut to the per-call deadline
    assert elapsed < 1.0
    assert compress_threads() == []


def test_bounded_generator_does_not_retry_or_fall_back() -> None:
    calls: list[str] = []

    def busy(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.host)
        return httpx.Response(503)

    bounded = generator(busy).with_limits(deadline_seconds=2.0)
    result = bounded([{"role": "user", "content": "hi"}], role="compressor")
    assert not result.ok and result.error is not None and result.error["code"] == "retries_exhausted"
    assert calls == ["127.0.0.1"]  # MAX_RETRIES=3 would have sent four


def test_unbounded_generator_still_retries() -> None:
    calls: list[str] = []

    def busy(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.host)
        return httpx.Response(503)

    generator(busy)([{"role": "user", "content": "hi"}], role="planner")
    assert len(calls) == 4


# --- the real ContextBuilder payload ----------------------------------------------------------------


def test_chunk_manager_takes_the_context_builder_dict_payload() -> None:
    with WorldStore(":memory:") as store:
        question = store.put_entity("question", {"text": "Why did orders rise?"}, agent="planner", run_id="r")
        store.put_entity("hypothesis", {"statement": "One seller.", "family": "single_seller", "question_id": question,
                                        "label": "H1", "priority": 1}, agent="planner", run_id="r")
        payload = ContextBuilder(store).build(Intent("plan", question_id=question), 4000)
    chunk = ChunkManager(MarkovianConfig()).start_chunk("Why did orders rise?", context=payload, label="plan")
    assert len(chunk.items_included) == 2
    assert '"family":"single_seller"' in chunk.text  # dict summaries as compact sorted-key JSON
    assert "selected because: the question being answered" in chunk.text
