"""The answer key is read only by the evaluation (architecture §9): nothing under app/ names it or
opens a path under eval/."""

from __future__ import annotations

import io
import re
import tokenize
from ast import literal_eval
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app"
# A path-like string (no spaces) that is eval/ or reaches into it: "eval", "eval/x", "../eval/x".
EVAL_PATH_RE = re.compile(r"^(?:\S*/)?eval(?:[/\\]\S*)?$")


def app_files() -> list[Path]:
    return [path for path in APP.rglob("*") if path.is_file() and "__pycache__" not in path.parts]


def eval_path_strings(source: str) -> list[str]:
    """String literals in Python source that look like a path under eval/."""
    found = []
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type != tokenize.STRING:
            continue
        try:
            value = literal_eval(token.string)
        except (ValueError, SyntaxError):
            continue  # f-strings and the like: checked by the plain-text scan below
        if isinstance(value, str) and EVAL_PATH_RE.match(value.strip()):
            found.append(value)
    return found


def test_detector_flags_eval_paths() -> None:
    assert eval_path_strings('open("eval/answer_key.json")') == ["eval/answer_key.json"]
    assert eval_path_strings('ROOT / "eval" / name') == ["eval"]
    assert eval_path_strings('x = "../eval/x.json"') == ["../eval/x.json"]
    assert eval_path_strings('"""The answer key in `eval/` is never loaded."""') == []
    assert eval_path_strings('ast.literal_eval(text)') == []


def test_app_never_names_the_answer_key_or_opens_eval() -> None:
    problems = []
    for path in app_files():
        text = path.read_text(encoding="utf-8", errors="ignore")
        name = path.relative_to(ROOT)
        if "answer_key" in text.lower():
            problems.append(f"{name}: mentions answer_key")
        if path.suffix == ".py":
            problems += [f"{name}: path under eval/: {value!r}" for value in eval_path_strings(text)]
            if re.search(r"""f["'][^"'\n]*\beval[/\\]""", text):
                problems.append(f"{name}: f-string path under eval/")
    assert not problems, problems


# --- Sprint 11d: no incident ids or question-to-value mappings in app/ -----------------------------

ANSWER_KEY = ROOT / "eval" / "answer_key.json"
# The names the 25 Oct real-run questions used for a segment, and the values stored for them. A
# mapping from one to the other in app/ would fix those incidents by hand instead of from the data.
QUESTION_NAMES = ("Minas Gerais", "Rio de Janeiro", "paid-search", "paid search")
# The files Sprint 11d added for grounding: they must not even name a stored segment value.
GROUNDING_FILES = (
    APP / "data" / "value_hints.py",
    APP / "agents" / "prompts" / "value_hints_note.md",
    APP / "agents" / "prompts" / "investigator_check_values.md",
    APP / "agents" / "prompts" / "investigator_rewrite_note.md",
)


def _incident_needles() -> list[tuple[str, re.Pattern[str]]]:
    import json

    needles = [("incident id", re.compile(r"\bincident[-_ ]?\d{1,2}\b", re.IGNORECASE))]
    for incident in json.loads(ANSWER_KEY.read_text()):
        value = str(incident["segment"]["value"])
        if incident["segment"]["type"] in ("seller", "category"):  # ids and stored category names
            needles.append((value, re.compile(re.escape(value), re.IGNORECASE)))
    needles += [(name, re.compile(re.escape(name), re.IGNORECASE)) for name in QUESTION_NAMES]
    return needles


def test_app_has_no_incident_ids_or_question_to_value_mappings() -> None:
    needles = _incident_needles()
    assert len(needles) > len(QUESTION_NAMES) + 1  # the answer key's seller and category values are in
    problems = []
    for path in app_files():
        text = path.read_text(encoding="utf-8", errors="ignore")
        problems += [f"{path.relative_to(ROOT)}: {label}" for label, pattern in needles if pattern.search(text)]
    assert not problems, problems


def test_grounding_code_and_prompts_name_no_stored_segment_value() -> None:
    import json

    stored = {"paid_search", "boleto"}
    for incident in json.loads(ANSWER_KEY.read_text()):
        if incident["segment"]["type"] == "state":
            stored.add(str(incident["segment"]["value"]))
    problems = []
    for path in GROUNDING_FILES:
        text = path.read_text(encoding="utf-8")
        problems += [f"{path.relative_to(ROOT)}: {value}" for value in sorted(stored)
                     if re.search(rf"(?<![A-Za-z_]){re.escape(value)}(?![A-Za-z_])", text)]
    assert not problems, problems
