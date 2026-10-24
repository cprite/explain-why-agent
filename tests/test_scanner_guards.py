"""Scanner guards: DuckDB settings, read-only access, timeouts, honesty rules, CLI on the sample."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import duckdb
import pytest

from app.scanner import db
from app.scanner.db import QueryTimeout, SampleDatabase
from app.scanner.models import ScanReport
from app.scanner.settings import DEFAULT_TIMEOUT_S, timeout_seconds
from tests.scanner_fixtures import write_sample

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app"


@pytest.fixture
def small_db(tmp_path: Path) -> Iterator[SampleDatabase]:
    database = SampleDatabase(data_dir=write_sample(tmp_path / "data"), cache_dir=tmp_path / "cache")
    yield database
    database.close()


def test_duckdb_memory_threads_and_on_disk_temp_directory(small_db: SampleDatabase) -> None:
    (row,) = small_db.run_sql(
        "SELECT current_setting('memory_limit') AS mem, current_setting('threads') AS threads, "
        "current_setting('temp_directory') AS temp, current_setting('enable_external_access') AS ext"
    )
    assert row["mem"] in {"953.6 MiB", "1.0 GB"}  # DuckDB prints 1GB (10^9 bytes) in MiB
    assert int(row["threads"]) == 2
    assert Path(row["temp"]) == small_db.cache_dir / "tmp"
    assert row["ext"] is False or str(row["ext"]).lower() == "false"


def test_default_database_spills_under_repo_cache_not_tmp() -> None:
    assert db.MEMORY_LIMIT == "1GB"
    assert db.THREADS == 2
    assert db.CACHE_DIR == ROOT / ".cache" / "duckdb"
    temp = Path(db.duckdb_config(db.CACHE_DIR)["temp_directory"])
    assert temp.is_relative_to(ROOT / ".cache" / "duckdb")
    assert not temp.is_relative_to(Path("/tmp"))


def test_connection_is_read_only_without_external_access(small_db: SampleDatabase) -> None:
    assert small_db.run_sql("SELECT COUNT(*) AS n FROM orders")[0]["n"] > 0
    with pytest.raises(duckdb.Error):
        small_db.run_sql("CREATE TABLE x AS SELECT 1 AS a")
    with pytest.raises(duckdb.Error):
        small_db.run_sql(f"SELECT * FROM read_csv('{small_db.data_dir / 'orders' / 'orders.csv'}')")


def test_query_timeout_interrupts_and_connection_stays_usable(small_db: SampleDatabase) -> None:
    with pytest.raises(QueryTimeout):
        small_db.run_sql("SELECT COUNT(*) FROM range(1000000000) a, range(1000) b", timeout_s=0.2)
    assert small_db.run_sql("SELECT 1 AS one") == [{"one": 1}]


def test_scanner_timeout_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SCANNER_TIMEOUT_S", raising=False)
    assert timeout_seconds() == DEFAULT_TIMEOUT_S == 300
    monkeypatch.setenv("SCANNER_TIMEOUT_S", "42")
    assert timeout_seconds() == 42
    for bad in ("", "abc", "-5"):
        monkeypatch.setenv("SCANNER_TIMEOUT_S", bad)
        assert timeout_seconds() == 300


EVAL_PATH = re.compile(r"""["'/\\]eval[/\\]|/\s*["']eval["']|["']eval["']\s*[,)]""")


def test_nothing_under_app_mentions_answer_key_or_opens_eval_paths() -> None:
    offenders: list[str] = []
    files = [p for p in APP.rglob("*") if p.is_file() and "__pycache__" not in p.parts]
    assert files
    for path in files:
        text = path.read_text(encoding="utf-8", errors="ignore")
        if "answer_key" in text:
            offenders.append(f"{path.relative_to(ROOT)}: answer_key")
        if EVAL_PATH.search(text):
            offenders.append(f"{path.relative_to(ROOT)}: eval path")
    assert offenders == []


def test_guard_pattern_catches_eval_paths() -> None:
    for sample in ('open("eval/answer.json")', "ROOT / 'eval' / 'x'", 'Path("eval", "x")'):
        assert EVAL_PATH.search(sample), sample
    assert not EVAL_PATH.search("score_series(values)")


def test_cli_runs_on_committed_sample_and_writes_json(tmp_path: Path) -> None:
    out = tmp_path / "anomalies.json"
    env = {**os.environ, "SCANNER_TIMEOUT_S": "300"}
    result = subprocess.run(
        [sys.executable, "-m", "app.scanner", "--json", str(out)],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "metric" in result.stdout and "driven by" in result.stdout
    report = ScanReport.model_validate(json.loads(out.read_text(encoding="utf-8")))
    assert not report.timed_out
    assert 1 <= len(report.cards) <= 10
    assert [c.rank for c in report.cards] == list(range(1, len(report.cards) + 1))
    assert all(c.question.startswith("Why did") for c in report.cards)
