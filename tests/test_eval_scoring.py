"""Tests for eval/scoring.py: `score(result, incident)` on hand-made results, and the edge cases of
window overlap, segment matching and the cause vocabulary."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

from app.schemas import HYPOTHESIS_FAMILIES, Result

ROOT = Path(__file__).resolve().parents[1]
# eval/ is not a package: its directory goes on the path before importing from it.
sys.path.insert(0, str(ROOT / "eval"))

import scoring
from scoring import check_segment, check_window, parse_window, score, vocabulary_gaps

ANSWER_KEY = json.loads((ROOT / "eval" / "answer_key.json").read_text(encoding="utf-8"))
WRONG_TYPES = json.loads((ROOT / "eval" / "wrong_explanation_types.json").read_text(encoding="utf-8"))


def incident(incident_id: str) -> dict[str, Any]:
    found = next(item for item in ANSWER_KEY if item["id"] == incident_id)
    return {**found, "wrong_explanation_type": WRONG_TYPES[incident_id]["type"]}


def cause(rank: int, kind: str) -> dict[str, Any]:
    return {"rank": rank, "type": kind, "summary": f"{kind} cause", "confidence": 0.8,
            "evidence": [{"observation_id": "obs-1", "source": "orders", "query_id": "q001", "finding": "x"}]}


def make_result(
    *,
    causes: list[str] = (),
    segment: str = "all",
    window: str = "2017-11-24 to 2017-11-25",
    ruled_out: list[str] = (),
    determinable: bool = True,
    status: str = "success",
    error: dict[str, str] | None = None,
    change: bool = True,
) -> Result:
    return Result.model_validate({
        "run_id": "t", "status": status, "question": "q", "determinable": determinable,
        "change": {"metric": "m", "segment": segment, "window": window} if change else None,
        "causes": [cause(i, kind) for i, kind in enumerate(causes, 1)],
        "ruled_out": [{"type": kind, "why": "no"} for kind in ruled_out],
        "trace_id": "t", "log_file": "logs/trace-t.jsonl", "execution_time_seconds": 0.1,
        "error": error,
    })


# --- score(): the acceptance-criteria cases -----------------------------------------------------


def test_correct_cause_is_found() -> None:
    row = score(make_result(causes=["volume"], ruled_out=["data_artefact"]), incident("incident-01"))
    assert row["status"] == "found" and row["found"] is True
    assert {name: check["pass"] for name, check in row["checks"].items()} == {
        "cause_type": True, "segment": True, "window": True, "wrong_explanation": True}


def test_wrong_cause_type_is_not_found() -> None:
    row = score(make_result(causes=["mix_shift", "volume"]), incident("incident-01"))
    assert row["status"] == "not_found"
    assert row["checks"]["cause_type"]["pass"] is False
    assert "mix_shift" in row["checks"]["cause_type"]["reason"]


def test_two_cause_incident_answered_with_one_cause_is_not_found() -> None:
    key = incident("incident-08")
    one = make_result(causes=["volume"], segment="RJ", window="2018-06-12 to 2018-06-30")
    row = score(one, key)
    assert row["status"] == "not_found"
    assert row["checks"]["cause_type"]["pass"] is False
    assert "price_discount" in row["checks"]["cause_type"]["reason"]
    both = make_result(causes=["price_discount", "volume"], segment="RJ", window="2018-06-12 to 2018-06-30",
                       ruled_out=["single_seller"])
    assert score(both, key)["status"] == "found"


def test_wrong_segment_is_not_found() -> None:
    result = make_result(causes=["single_seller"], segment="seller 0000aaaa",
                         window="2018-01-08 to 2018-01-21")
    row = score(result, incident("incident-03"))
    assert row["status"] == "not_found"
    assert row["checks"]["segment"]["pass"] is False
    assert row["checks"]["cause_type"]["pass"] is True


def test_window_outside_is_not_found() -> None:
    row = score(make_result(causes=["volume"], window="2017-12-01 to 2017-12-02"), incident("incident-01"))
    assert row["status"] == "not_found"
    assert row["checks"]["window"]["pass"] is False
    assert "no overlap" in row["checks"]["window"]["reason"]


def test_wrong_explanation_missing_from_ruled_out_fails_check_d_only() -> None:
    row = score(make_result(causes=["volume"], ruled_out=["price_discount"]), incident("incident-01"))
    assert row["checks"]["wrong_explanation"]["pass"] is False
    assert "data_artefact" in row["checks"]["wrong_explanation"]["reason"]
    assert row["status"] == "found"  # (d) is reported but not part of "found"


def test_undeterminable_answered_with_a_cause_is_not_found() -> None:
    result = make_result(causes=["product_quality"], window="2017-12-01 to 2017-12-15")
    row = score(result, incident("incident-09"))
    assert row["status"] == "not_found"
    assert row["checks"]["undeterminable"]["pass"] is False


def test_undeterminable_answered_not_determinable_is_found() -> None:
    result = make_result(determinable=False, window="2017-12-01 to 2017-12-15")
    for incident_id in ("incident-09", "incident-10"):
        row = score(result, incident(incident_id))
        assert row["status"] == "found" and row["found"] is True
        assert row["checks"] == {"undeterminable": {"pass": True, "reason": "determinable false, no cause asserted"}}


def test_undeterminable_answered_determinable_without_cause_is_not_found() -> None:
    row = score(make_result(determinable=True), incident("incident-10"))
    assert row["status"] == "not_found"


def test_cache_miss_is_no_cache_not_not_found() -> None:
    result = make_result(status="error", determinable=False, change=False,
                         error={"code": "cache_miss", "message": "this question needs a model key"})
    for incident_id in ("incident-02", "incident-09"):
        row = score(result, incident(incident_id))
        assert row["status"] == "no_cache"
        assert row["found"] is False
        assert row["error"]["code"] == "cache_miss"


def test_other_error_is_error() -> None:
    result = make_result(status="error", determinable=False, change=False,
                         error={"code": "max_agent_rounds", "message": "stopped"})
    row = score(result, incident("incident-01"))
    assert row["status"] == "error" and row["found"] is False


def test_result_without_change_fails_segment_and_window() -> None:
    row = score(make_result(causes=["volume"], change=False), incident("incident-01"))
    assert row["checks"]["segment"]["pass"] is False
    assert row["checks"]["window"]["pass"] is False
    assert row["status"] == "not_found"


def test_wrong_explanation_without_a_fitting_type_is_n_a() -> None:
    key = {**incident("incident-01"), "wrong_explanation_type": None}
    row = score(make_result(causes=["volume"]), key)
    assert row["checks"]["wrong_explanation"]["pass"] is None
    assert row["status"] == "found"


# --- window overlap at the edges ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("window", "passed"),
    [
        ("2018-07-25 to 2018-08-01", True),   # ends on the key's first day
        ("2018-08-31 to 2018-09-07", True),   # starts on the key's last day
        ("2018-07-01 to 2018-07-31", False),  # ends the day before
        ("2018-09-01 to 2018-09-30", False),  # starts the day after
        ("2018-08-15", True),                 # a single date inside
        ("from 2018-06-01 through 2018-12-31 (whole H2)", True),  # contains the key window
    ],
)
def test_window_edges(window: str, passed: bool) -> None:
    assert check_window(window, incident("incident-04"))["pass"] is passed


@pytest.mark.parametrize("window", ["August 2018", "", "2018-08", "2018-02-30 to 2018-03-01", "24/11/2017"])
def test_unparseable_window_fails_with_reason(window: str) -> None:
    check = check_window(window, incident("incident-04"))
    assert check["pass"] is False
    assert "unparseable window" in check["reason"]


def test_parse_window_takes_first_and_last_date() -> None:
    assert str(parse_window("2018-08-01 to 2018-08-31")) == "(datetime.date(2018, 8, 1), datetime.date(2018, 8, 31))"


# --- segment matching ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "segment",
    ["RJ", "rj", "customer_state = 'RJ'", "Rio de Janeiro", "RIO DE JANEIRO", "orders shipped to rio de janeiro"],
)
def test_state_segment_accepts_code_and_name_case_insensitively(segment: str) -> None:
    assert check_segment(segment, incident("incident-04"))["pass"] is True


@pytest.mark.parametrize("segment", ["SP", "Sao Paulo", "all", "BRJ orders", ""])
def test_state_segment_rejects_other_states(segment: str) -> None:
    assert check_segment(segment, incident("incident-04"))["pass"] is False


def test_state_names_with_accents_match() -> None:
    key = {**incident("incident-04"), "segment": {"type": "state", "value": "SP"}}
    assert check_segment("São Paulo", key)["pass"] is True


def test_seller_segment_is_case_insensitive() -> None:
    key = incident("incident-03")
    assert check_segment("seller_id F8DB351D8C4C4C22C6835C19A46F01B0", key)["pass"] is True
    assert check_segment("seller f8db351d8c4c4c22c6835c19a46f01b1", key)["pass"] is False


def test_category_segment_accepts_underscores_or_spaces() -> None:
    key = incident("incident-06")
    assert check_segment("product_category_name = 'RELOGIOS_PRESENTES'", key)["pass"] is True
    assert check_segment("relogios presentes", key)["pass"] is True
    assert check_segment("beleza_saude", key)["pass"] is False


def test_national_and_cohort_segments() -> None:
    assert check_segment("all", incident("incident-01"))["pass"] is True
    assert check_segment("Marketplace-wide", incident("incident-02"))["pass"] is True
    assert check_segment("seller 1234", incident("incident-01"))["pass"] is False
    assert check_segment("sellers closed via paid_search, 2018-03 cohort", incident("incident-07"))["pass"] is True
    assert check_segment("organic_search cohort", incident("incident-07"))["pass"] is False


# --- vocabulary gap -----------------------------------------------------------------------------


def test_answer_key_cause_types_missing_from_vocabulary_are_reported() -> None:
    """Documents the gap between the answer key and CauseType; does not fail on it.

    Today the gap is `freight_cost` (incident-04). The test lists whatever is missing and checks the
    eval reports exactly that, so closing the gap later keeps it green.
    """
    missing = {item["id"]: [t for t in item["cause_types"] if t not in HYPOTHESIS_FAMILIES]
               for item in ANSWER_KEY if item["determinable"]}
    missing = {key: value for key, value in missing.items() if value}
    print(f"answer-key cause types missing from CauseType: {missing}")
    assert vocabulary_gaps(ANSWER_KEY) == missing
    for incident_id, types in missing.items():
        row = score(make_result(causes=["volume"]), incident(incident_id))
        assert row["cause_type_not_in_vocabulary"] == types
        assert row["checks"]["cause_type"]["pass"] is False
        assert "cause_type_not_in_vocabulary: " + ", ".join(types) in row["checks"]["cause_type"]["reason"]


def test_wrong_explanation_mapping_covers_every_incident_with_valid_types() -> None:
    assert set(WRONG_TYPES) == {item["id"] for item in ANSWER_KEY}
    for incident_id, entry in WRONG_TYPES.items():
        assert entry["type"] is None or entry["type"] in HYPOTHESIS_FAMILIES, incident_id
        assert entry["reason"].strip(), incident_id


def test_scoring_module_reads_no_files() -> None:
    source = Path(scoring.__file__).read_text(encoding="utf-8")
    assert "open(" not in source and "read_text" not in source and "answer_key" not in source
