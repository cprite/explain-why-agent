"""No file under app/ (prompts included) carries incident-specific knowledge (Sprint 11c, criterion 4).

The terms are read from eval/answer_key.json at test time, so the check stays in step with the key:
every incident id, the key's file name, every seller or product id in it (and its first eight
characters, the usual short form), plus a fixed list of incident words. `RJ` is checked only in the
prompts, where it would be a segment literal; state codes are legitimate elsewhere (the scanner's
labels, the World Model's sample question for its own CI step).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app"
PROMPTS = APP / "agents" / "prompts"
KEY = ROOT / "eval" / "answer_key.json"

FIXED_TERMS = ("watches", "relogios", "rio de janeiro", "truck strike", "greve", "black friday")
PROMPT_ONLY_TERMS = ("rj",)


def key_terms(key_path: Path = KEY) -> list[str]:
    """The incident-specific terms taken from the answer key."""
    text = key_path.read_text(encoding="utf-8")
    incidents = json.loads(text)
    terms = {incident["id"] for incident in incidents}
    terms |= {key_path.stem, key_path.name}
    for identifier in set(re.findall(r"\b[0-9a-f]{32}\b", text)):  # seller and product ids
        terms |= {identifier, identifier[:8]}
    for incident in incidents:
        segment = incident.get("segment") or {}
        if segment.get("type") in ("seller", "product"):
            terms.add(str(segment["value"]))
    return sorted(terms | set(FIXED_TERMS))


def find_terms(text: str, terms: list[str] | tuple[str, ...]) -> list[str]:
    """Terms that occur in `text` as whole words, case-insensitively."""
    return [term for term in terms if re.search(rf"(?<![0-9a-z]){re.escape(term)}(?![0-9a-z])", text, re.IGNORECASE)]


def app_files() -> list[Path]:
    return sorted(p for p in APP.rglob("*") if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc")


def test_terms_come_from_the_answer_key() -> None:
    terms = key_terms()
    incidents = json.loads(KEY.read_text(encoding="utf-8"))
    assert {incident["id"] for incident in incidents} <= set(terms)
    assert "answer_key" in terms and "answer_key.json" in terms
    sellers = [i["segment"]["value"] for i in incidents if i["segment"]["type"] == "seller"]
    assert sellers and all(s in terms and s[:8] in terms for s in sellers)
    assert set(FIXED_TERMS) <= set(terms)


def test_detector_finds_whole_words_in_any_case() -> None:
    terms = key_terms()
    assert find_terms("Planned around BLACK FRIDAY.", terms) == ["black friday"]
    assert find_terms("see incident-03 for details", terms) == ["incident-03"]
    assert find_terms("WHERE seller_id = 'f8db351d8c4c4c22c6835c19a46f01b0'", terms) != []
    assert find_terms("the watches category", terms) == ["watches"]
    assert find_terms("segment = 'RJ'", PROMPT_ONLY_TERMS) == ["rj"]
    assert find_terms("stopwatchesx, regreved, incident-030", terms) == []
    assert find_terms("a projection of the trajectory", PROMPT_ONLY_TERMS) == []


def test_temporary_file_with_a_term_is_caught(tmp_path: Path) -> None:
    planted = tmp_path / "planted.md"
    planted.write_text("Check the truck strike first.", encoding="utf-8")
    assert find_terms(planted.read_text(encoding="utf-8"), key_terms()) == ["truck strike"]


def test_no_app_file_names_an_incident_term() -> None:
    terms = key_terms()
    problems = []
    for path in app_files():
        text = path.read_text(encoding="utf-8", errors="ignore")
        found = find_terms(text, terms)
        if path.is_relative_to(PROMPTS):
            found += find_terms(text, PROMPT_ONLY_TERMS)
        problems += [f"{path.relative_to(ROOT)}: {term}" for term in found]
    assert problems == []
