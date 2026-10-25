"""Prompts stay readable (Sprint 11c, criterion 5): every prompt file has a short header saying what the
agent does and what it must not do, and no prompt's model text grows by more than half of its size on
main before Sprint 11c (0ae9313).

The header is an HTML comment that `load_prompt` drops, so it is not sent to the model and does not
change the sample-mode cache key of a prompt whose text is unchanged; the growth limit is measured on
the text the model sees.
"""

from __future__ import annotations

import re

import pytest

from app.agents.prompts import HEADER_RE, PROMPT_DIR, load_prompt

# Characters of model text per prompt on main at 0ae9313, before Sprint 11c.
SIZE_BEFORE = {
    "change_check_note": 535,
    "chunk_note": 488,
    "critic": 2573,
    "investigator_observe": 668,
    "investigator_sql": 1020,
    "planner": 1595,
    "reporter": 1238,
}
# Prompts added after 0ae9313 (Sprint 11d): their size when they were added.
SIZE_BEFORE |= {
    "investigator_check_values": 846,
    "investigator_rewrite_note": 442,
    "value_hints_note": 655,
}
MAX_GROWTH = 1.5
MAX_HEADER_LINES = 4


def prompt_names() -> list[str]:
    return sorted(path.stem for path in PROMPT_DIR.glob("*.md"))


def test_every_prompt_has_a_known_size_before() -> None:
    assert prompt_names() == sorted(SIZE_BEFORE)


@pytest.mark.parametrize("name", sorted(SIZE_BEFORE))
def test_prompt_has_a_short_header_with_does_and_must_not(name: str) -> None:
    text = (PROMPT_DIR / f"{name}.md").read_text(encoding="utf-8")
    header = HEADER_RE.match(text)
    assert header, f"{name}.md starts without a header comment"
    body = header.group(0)
    assert re.search(r"\bDoes:", body) and re.search(r"\bMust not:", body), body
    assert body.count("\n") + 1 <= MAX_HEADER_LINES


@pytest.mark.parametrize("name", sorted(SIZE_BEFORE))
def test_prompt_model_text_grows_by_at_most_half(name: str) -> None:
    text = load_prompt(name)
    assert not text.startswith("<!--") and "Must not:" not in text  # the header never reaches the model
    assert len(text) <= SIZE_BEFORE[name] * MAX_GROWTH, (name, len(text), SIZE_BEFORE[name])


def test_load_prompt_drops_only_a_leading_header() -> None:
    assert HEADER_RE.sub("", "<!-- a\nb -->\nText <!-- kept -->", count=1).strip() == "Text <!-- kept -->"
    assert HEADER_RE.sub("", "Text first <!-- kept -->", count=1) == "Text first <!-- kept -->"
