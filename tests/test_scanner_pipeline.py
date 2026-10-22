"""End-to-end scanner tests on synthetic CSVs: SQL, ranking, attribution, parent/child merge."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
import yaml

from app.scanner.db import SampleDatabase
from app.scanner.models import ScanReport
from app.scanner.scan import Scanner, ScanTimeout
from app.scanner.settings import CONFIG_PATH, parse_config
from tests.scanner_fixtures import write_sample

SPIKE_DAY = 90


def _config(metrics: list[str], segments: list[str]):
    raw = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    raw["metrics"] = {k: {**raw["metrics"][k], "segments": segments} for k in metrics}
    return parse_config(raw)


@pytest.fixture
def rj_spike_db(tmp_path: Path) -> Iterator[SampleDatabase]:
    data = write_sample(tmp_path / "data", extra={(SPIKE_DAY, "RJ"): 150})
    database = SampleDatabase(data_dir=data, cache_dir=tmp_path / "cache")
    yield database
    database.close()


def test_whole_shop_move_caused_by_one_state_yields_one_card_naming_it(rj_spike_db: SampleDatabase) -> None:
    config = _config(["daily_orders"], ["all", "state", "category"])
    result = Scanner(config=config, run_sql=rj_spike_db.run_sql, timeout_s=120).scan()
    report = result.report
    assert not report.timed_out

    on_spike = [c for c in report.cards if c.period.start <= _day(SPIKE_DAY) <= c.period.end]
    assert len(on_spike) == 1, [c.id for c in on_spike]
    card = on_spike[0]
    assert card.segment.type == "all"
    assert card.direction == "rise"
    assert card.top_attribution is not None and card.top_attribution.startswith("driven by state RJ:")
    assert card.attribution[0].dimension == "state"
    assert card.attribution[0].slices[0].value == "RJ"
    assert any(m.startswith("state RJ") for m in card.merged)
    assert card.rank == 1
    assert "whole shop" in card.question and card.question.startswith("Why did daily orders")
    # Category moved in proportion, so state carries more surprise.
    assert card.attribution[0].surprise > max((d.surprise for d in card.attribution[1:]), default=0.0)

    # The JSON round-trips through the card model.
    assert ScanReport.model_validate_json(report.model_dump_json()) == report


def test_two_separate_state_moves_give_two_whole_shop_cards(tmp_path: Path) -> None:
    # Two states spike on different days: each whole-shop card names its own state.
    data = write_sample(tmp_path / "data", extra={(SPIKE_DAY, "RJ"): 150, (60, "MG"): 150})
    database = SampleDatabase(data_dir=data, cache_dir=tmp_path / "cache")
    try:
        config = _config(["daily_orders"], ["all", "state"])
        report = Scanner(config=config, run_sql=database.run_sql, timeout_s=120).scan().report
    finally:
        database.close()
    def on(day: int):
        return [c for c in report.cards if c.period.start <= _day(day) <= c.period.end]

    for day, state in ((SPIKE_DAY, "RJ"), (60, "MG")):
        cards = on(day)
        assert [c.segment.type for c in cards] == ["all"], [c.id for c in cards]
        assert cards[0].top_attribution.startswith(f"driven by state {state}:")


def test_scan_stops_at_the_query_cap(rj_spike_db: SampleDatabase) -> None:
    raw = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    raw["limits"]["max_queries"] = 2
    raw["metrics"] = {"daily_orders": raw["metrics"]["daily_orders"]}
    report = Scanner(config=parse_config(raw), run_sql=rj_spike_db.run_sql, timeout_s=120).scan().report
    assert report.timed_out
    assert report.queries == 2


def test_scan_stops_at_the_time_cap(rj_spike_db: SampleDatabase) -> None:
    scanner = Scanner(config=_config(["daily_orders"], ["all"]), run_sql=rj_spike_db.run_sql, timeout_s=120)
    scanner.budget.deadline = 0.0  # already past
    report = scanner.scan().report
    assert report.timed_out
    assert report.cards == []
    with pytest.raises(ScanTimeout):
        scanner.budget.check()


def _day(offset: int):
    from datetime import timedelta

    from tests.scanner_fixtures import START

    return START + timedelta(days=offset)
