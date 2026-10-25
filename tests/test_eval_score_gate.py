"""The CI gate on the evaluation score (scripts/check_eval_score.py, Sprint 11c criterion 7)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from scripts.check_eval_score import check, committed_after, parse_score

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = "incident-01  found\n\nScore: 5/10 (answered 5, no_cache 5, errors 0)\n"


def after_report(logs: Path, stamp: str, line: str) -> None:
    logs.mkdir(parents=True, exist_ok=True)
    (logs / f"eval-after-{stamp}.json").write_text(json.dumps({"score_line": line}), encoding="utf-8")


def test_parse_score() -> None:
    assert parse_score("Score: 5/10 (answered 5, no_cache 5, errors 0)") == (5, 10)
    assert parse_score("Score: 5/10") is None and parse_score("") is None


def test_missing_score_line_fails(tmp_path: Path) -> None:
    code, message = check("incident-01  found\n", tmp_path)
    assert code == 1 and "does not end with" in message
    assert check("", tmp_path)[0] == 1


def test_without_an_after_report_the_score_is_reported(tmp_path: Path) -> None:
    code, message = check(OUTPUT, tmp_path)
    assert code == 0 and message.startswith("[REPORT] sample-mode score 5/10")


def test_equal_after_score_passes_and_a_different_one_fails(tmp_path: Path) -> None:
    after_report(tmp_path, "20261026T090000Z", "Score: 4/10 (answered 9, no_cache 0, errors 1)")
    after_report(tmp_path, "20261026T100000Z", "Score: 5/10 (answered 10, no_cache 0, errors 0)")
    assert committed_after(tmp_path).name == "eval-after-20261026T100000Z.json"  # the newest
    code, message = check(OUTPUT, tmp_path)
    assert code == 0 and message.startswith("[PASS]")
    after_report(tmp_path, "20261026T110000Z", "Score: 6/10 (answered 10, no_cache 0, errors 0)")
    code, message = check(OUTPUT, tmp_path)
    assert code == 1 and "differs from the committed after score 6/10" in message


def test_before_reports_are_not_the_reference(tmp_path: Path) -> None:
    (tmp_path / "eval-before-20261026T100000Z.json").write_text(json.dumps({"score_line": "Score: 1/10 (answered "
                                                                           "10, no_cache 0, errors 0)"}))
    assert check(OUTPUT, tmp_path)[0] == 0 and committed_after(tmp_path) is None


def test_cli(tmp_path: Path) -> None:
    out = tmp_path / "eval.txt"
    out.write_text(OUTPUT, encoding="utf-8")
    proc = subprocess.run([sys.executable, str(ROOT / "scripts" / "check_eval_score.py"), str(out), "--logs",
                           str(tmp_path / "logs")], capture_output=True, text=True, check=False, timeout=60)
    assert proc.returncode == 0 and "[REPORT]" in proc.stdout


def test_after_reports_can_be_committed() -> None:
    """logs/ is ignored except .gitkeep and the before/after evaluation reports (criterion 2)."""
    ignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "!logs/eval-before-*.json" in ignore and "!logs/eval-after-*.json" in ignore
