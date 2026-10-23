"""Scoring of one investigation result against one answer-key incident (architecture §9).

`score(result, incident)` is pure: no file, model or data access. The runner (`eval/run_eval.py`)
adds `wrong_explanation_type` to each incident from `eval/wrong_explanation_types.json` before
calling it.

Checks for a determinable incident, each pass (True), fail (False) or n/a (None) with a reason:

- `cause_type`: the rank-1 cause's type is in the incident's `cause_types`; when the key lists more
  than one type, every listed type must appear among the causes.
- `segment`: `change.segment` (a free string) names the incident's segment value.
- `window`: the ISO dates in `change.window` (a free string) overlap `window_start`..`window_end`;
  both ends are treated as inclusive, so windows touching on one day overlap.
- `wrong_explanation`: the incident's wrong-explanation type appears in `ruled_out`; n/a when no
  cause type fits that explanation.

An incident is found when cause_type, segment and window pass. An undeterminable incident is found
when the result says `determinable: false` and asserts no cause. A `cache_miss` error (sample mode
with no recorded model replies) is `no_cache`; any other error is `error`.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date
from typing import Any

from app.schemas import HYPOTHESIS_FAMILIES, Result

CHECKS = ("cause_type", "segment", "window", "wrong_explanation")

# Brazilian state codes and names; a state segment matches either.
BRAZIL_STATES = {
    "AC": "Acre", "AL": "Alagoas", "AP": "Amapa", "AM": "Amazonas", "BA": "Bahia", "CE": "Ceara",
    "DF": "Distrito Federal", "ES": "Espirito Santo", "GO": "Goias", "MA": "Maranhao",
    "MT": "Mato Grosso", "MS": "Mato Grosso do Sul", "MG": "Minas Gerais", "PA": "Para",
    "PB": "Paraiba", "PR": "Parana", "PE": "Pernambuco", "PI": "Piaui", "RJ": "Rio de Janeiro",
    "RN": "Rio Grande do Norte", "RS": "Rio Grande do Sul", "RO": "Rondonia", "RR": "Roraima",
    "SC": "Santa Catarina", "SP": "Sao Paulo", "SE": "Sergipe", "TO": "Tocantins",
}

# Words that name the whole marketplace; a national segment matches any of them.
NATIONAL_ALIASES = (
    "all", "all sellers", "all segments", "all states", "all orders", "overall", "national",
    "nationwide", "marketplace", "marketplace-wide", "platform", "platform-wide", "brazil", "total",
    "whole", "entire", "every", "multiple states", "multiple sellers", "many states", "many sellers",
)

ISO_DATE_RE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")


def _fold(text: str) -> str:
    """Lower-case, accents removed, underscores as spaces, whitespace collapsed."""
    plain = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    return " ".join(plain.replace("_", " ").lower().split())


def _contains_term(text: str, term: str) -> bool:
    """True if `term` occurs in `text` as whole words (both already folded)."""
    return re.search(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])", text) is not None


def _check(passed: bool | None, reason: str) -> dict[str, Any]:
    return {"pass": passed, "reason": reason}


def parse_window(text: str) -> tuple[date, date] | None:
    """The first and last ISO date in `text` (a single date is a one-day window); None if none parse."""
    dates = []
    for match in ISO_DATE_RE.finditer(text or ""):
        try:
            dates.append(date(int(match[1]), int(match[2]), int(match[3])))
        except ValueError:
            return None
    if not dates:
        return None
    return dates[0], dates[-1]


def check_window(window_text: str | None, incident: dict[str, Any]) -> dict[str, Any]:
    """Does the result's window string overlap the incident window (inclusive ends)?"""
    parsed = parse_window(window_text or "")
    if parsed is None:
        return _check(False, f"unparseable window: {window_text!r} (no valid ISO date)")
    start, end = parsed
    if end < start:
        return _check(False, f"window {window_text!r} ends before it starts")
    key_start = date.fromisoformat(incident["window_start"])
    key_end = date.fromisoformat(incident["window_end"])
    span = f"{start}..{end} vs key {key_start}..{key_end}"
    if start <= key_end and key_start <= end:
        return _check(True, f"overlaps: {span}")
    return _check(False, f"no overlap: {span}")


def check_segment(segment_text: str | None, incident: dict[str, Any]) -> dict[str, Any]:
    """Does the result's segment string name the incident's segment (case-insensitive)?"""
    if not segment_text or not segment_text.strip():
        return _check(False, "result has no segment")
    kind = incident["segment"]["type"]
    value = str(incident["segment"]["value"])
    text = _fold(segment_text)
    shown = f"{segment_text!r} vs {kind} {value!r}"
    if kind == "state":
        code = value.upper()
        name = BRAZIL_STATES.get(code)
        if name is None:
            return _check(False, f"unknown state code {value!r} in the answer key")
        hit = _contains_term(text, code.lower()) or _contains_term(text, _fold(name))
    elif kind in ("seller", "category"):
        hit = _contains_term(text, _fold(value))
    elif kind == "national":
        hit = any(_contains_term(text, alias) for alias in NATIONAL_ALIASES)
    elif kind == "marketing_cohort":
        # "sellers closed via paid_search in 2018-03": the channel names the cohort.
        channel = re.search(r"via (\S+)", value)
        hit = channel is not None and _contains_term(text, _fold(channel[1]))
    else:
        return _check(False, f"segment type {kind!r} has no matching rule")
    return _check(hit, ("matches: " if hit else "no match: ") + shown)


def check_cause_type(result: Result, incident: dict[str, Any]) -> dict[str, Any]:
    """Rank-1 cause type in the key's types; with several key types, all must appear among causes."""
    expected = list(incident["cause_types"])
    missing_vocab = [t for t in expected if t not in HYPOTHESIS_FAMILIES]
    if not result.causes:
        reason = "result asserts no cause"
        if missing_vocab:
            reason += f"; cause_type_not_in_vocabulary: {', '.join(missing_vocab)}"
        return _check(False, reason)
    top = result.causes[0].type
    found = [cause.type for cause in result.causes]
    if missing_vocab:
        return _check(False, f"cause_type_not_in_vocabulary: {', '.join(missing_vocab)} (rank-1 {top})")
    if top not in expected:
        return _check(False, f"rank-1 cause {top} not in {expected}")
    absent = [t for t in expected if t not in found]
    if absent:
        return _check(False, f"rank-1 {top} ok but {absent} missing from causes {found}")
    return _check(True, f"rank-1 {top}; causes {found} cover {expected}")


def check_wrong_explanation(result: Result, incident: dict[str, Any]) -> dict[str, Any]:
    """Is the incident's wrong-explanation type among `ruled_out`? n/a when no type fits."""
    wrong = incident.get("wrong_explanation_type")
    if wrong is None:
        return _check(None, "n/a: no cause type fits this wrong explanation")
    ruled = [item.type for item in result.ruled_out]
    if wrong in ruled:
        return _check(True, f"{wrong} ruled out")
    return _check(False, f"{wrong} not in ruled_out {ruled}")


def vocabulary_gaps(incidents: list[dict[str, Any]]) -> dict[str, list[str]]:
    """Answer-key cause types of determinable incidents that the CauseType vocabulary lacks, per incident."""
    gaps = {}
    for incident in incidents:
        if not incident.get("determinable", True):
            continue
        missing = [t for t in incident["cause_types"] if t not in HYPOTHESIS_FAMILIES]
        if missing:
            gaps[incident["id"]] = missing
    return gaps


def score(result: Result, incident: dict[str, Any]) -> dict[str, Any]:
    """Score one result against one incident; returns status, found and the per-check verdicts."""
    checks: dict[str, dict[str, Any]] = {}
    out: dict[str, Any] = {"id": incident["id"], "status": "error", "found": False, "checks": checks,
                           "error": None}
    gaps = vocabulary_gaps([incident]).get(incident["id"])
    if gaps:
        out["cause_type_not_in_vocabulary"] = gaps

    if result.status != "success":
        error = result.error.model_dump() if result.error else {"code": "unknown", "message": ""}
        out["error"] = error
        out["status"] = "no_cache" if error["code"] == "cache_miss" else "error"
        return out

    if not incident["determinable"]:
        found = not result.determinable and not result.causes
        if found:
            reason = "determinable false, no cause asserted"
        else:
            reason = f"determinable {str(result.determinable).lower()}, {len(result.causes)} cause(s) asserted"
        checks["undeterminable"] = _check(found, reason)
        out["status"] = "found" if found else "not_found"
        out["found"] = found
        return out

    change = result.change
    checks["cause_type"] = check_cause_type(result, incident)
    checks["segment"] = check_segment(change.segment if change else None, incident)
    checks["window"] = (check_window(change.window, incident) if change
                        else _check(False, "result has no change (window)"))
    checks["wrong_explanation"] = check_wrong_explanation(result, incident)
    found = all(checks[name]["pass"] for name in ("cause_type", "segment", "window"))
    out["status"] = "found" if found else "not_found"
    out["found"] = found
    return out
