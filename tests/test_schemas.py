"""Tests for the result schemas (app/schemas.py) and the example result."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.schemas import (
    ALL_MODELS,
    CauseDraft,
    HYPOTHESIS_FAMILIES,
    Plan,
    Result,
    Statement,
    json_schemas,
    validate_result_file,
)

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "output_examples" / "example-result.json"


def test_example_result_validates() -> None:
    result = validate_result_file(EXAMPLE)
    assert result.status == "success"
    assert result.causes and result.causes[0].evidence
    kinds = {s.kind for s in result.causes[0].statements}
    assert kinds == {"measured", "inferred"}


def test_result_has_every_architecture_field() -> None:
    fields = set(Result.model_fields)
    for name in (
        "status", "question", "change", "determinable", "causes", "ruled_out", "limitations",
        "agents", "trace_id", "log_file", "token_report", "execution_time_seconds",
    ):
        assert name in fields


def test_malformed_result_fails_with_readable_error(tmp_path: Path) -> None:
    payload = json.loads(EXAMPLE.read_text())
    payload["status"] = "maybe"
    del payload["causes"][0]["evidence"]
    payload["causes"][0]["confidence"] = 3
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps(payload))
    with pytest.raises(ValueError) as info:
        validate_result_file(bad)
    message = str(info.value)
    assert "status" in message
    assert "causes.0.evidence: Field required" in message
    assert "causes.0.confidence" in message


def test_measured_statement_needs_query_id() -> None:
    with pytest.raises(ValidationError, match="measured statement"):
        Statement(text="Orders rose 400%", kind="measured")
    assert Statement(text="So it was a promotion", kind="inferred").query_ids == []


def test_undeterminable_result_cannot_assert_causes() -> None:
    payload = json.loads(EXAMPLE.read_text())
    payload["determinable"] = False
    with pytest.raises(ValidationError, match="undeterminable"):
        Result.model_validate(payload)


def test_error_result_needs_error() -> None:
    payload = json.loads(EXAMPLE.read_text())
    payload.update(status="error", causes=[])
    with pytest.raises(ValidationError, match="error result"):
        Result.model_validate(payload)


def test_json_schema_export_for_every_model() -> None:
    schemas = json_schemas()
    assert set(schemas) == {"Question", "Plan", "Hypothesis", "Observation", "Verdict", "Result"}
    assert len(ALL_MODELS) == 6
    for name, schema in schemas.items():
        assert schema["type"] == "object", name
        assert schema["properties"], name
        json.dumps(schema)
    families = schemas["Hypothesis"]["properties"]["family"]["enum"]
    assert tuple(families) == HYPOTHESIS_FAMILIES


def test_plan_requires_two_to_four_hypotheses() -> None:
    hyp = {"id": "H1", "family": "volume", "statement": "s", "priority": 1, "test": {"description": "d"}}
    base = {
        "question": "q", "metric": "m", "segment": "all",
        "window": {"start": "2020-01-02", "end": "2020-01-03"},
        "baseline_window": {"start": "2019-12-26", "end": "2020-01-02"},
        "change_check": {"description": "d"},
    }
    Plan.model_validate({**base, "hypotheses": [hyp, {**hyp, "id": "H2"}]})
    with pytest.raises(ValidationError):
        Plan.model_validate({**base, "hypotheses": [hyp]})
    with pytest.raises(ValidationError):
        Plan.model_validate({**base, "hypotheses": [hyp] * 5})


def test_schemas_cli_validates_example() -> None:
    out = subprocess.run(
        [sys.executable, "-m", "app.schemas"], cwd=ROOT, capture_output=True, text=True, check=False
    )
    assert out.returncode == 0, out.stdout + out.stderr
    assert out.stdout.startswith("[PASS] example-result.json: valid Result")


def test_cause_draft_takes_ids_from_statements() -> None:
    cause = {
        "hypothesis_id": "H3", "type": "mix_shift", "summary": "s", "confidence": 0.8,
        "statements": [
            {"text": "a", "kind": "measured", "observation_ids": ["obs-0"]},
            {"text": "b", "kind": "inferred", "observation_ids": ["obs-5", "obs-0"]},
        ],
    }
    assert CauseDraft.model_validate(cause).observation_ids == ["obs-0", "obs-5"]
    assert CauseDraft.model_validate({**cause, "observation_ids": ["obs-9"]}).observation_ids == ["obs-9"]
    with pytest.raises(ValidationError):
        CauseDraft.model_validate({**cause, "statements": []})
