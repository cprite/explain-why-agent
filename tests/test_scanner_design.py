"""Sample-design switch and sampling-robust metric forms (config.yaml `sample_design`, `normalise`)."""

from __future__ import annotations

import pytest
import yaml

from app.scanner.attribution import SliceValues, attribute
from app.scanner.scan import Scanner
from app.scanner.settings import CONFIG_PATH, load_config, parse_config


def _raw() -> dict:
    return yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))


def _metrics(design: str) -> dict:
    raw = _raw()
    raw["sample_design"] = design
    return {m.key: m for m in parse_config(raw).expanded_metrics()}


def test_repository_sample_uses_the_stratified_design() -> None:
    assert load_config().sample_design == "stratified"


def test_every_count_and_sum_metric_has_a_sampling_robust_form() -> None:
    for key, body in _raw()["metrics"].items():
        if "denominator" not in body:
            assert body.get("normalise") in {"period_share", "per_order"}, key


def test_stratified_count_becomes_share_of_the_periods_orders() -> None:
    m = _metrics("stratified")["daily_orders"]
    assert m.share_of_period and m.is_ratio
    assert m.denominator == m.volume
    assert "all" not in m.segments  # the whole shop's share is 1 by definition
    assert m.label == "share of the day's orders"


def test_stratified_sums_become_per_order_means() -> None:
    metrics = _metrics("stratified")
    for key in ("revenue", "channel_revenue"):
        m = metrics[key]
        assert m.is_ratio and not m.share_of_period
        assert m.denominator == "COUNT(DISTINCT order_id)"
        assert "per" in m.label and "order" in m.label
    assert "all" in metrics["revenue"].segments


def test_full_design_keeps_raw_totals() -> None:
    stratified, full = _metrics("stratified"), _metrics("full")
    for key in ("daily_orders", "revenue", "channel_revenue"):
        assert not full[key].is_ratio and not full[key].share_of_period
        assert full[key].numerator == stratified[key].numerator
    assert "all" in full["daily_orders"].segments
    # Ratio metrics are the same under both designs.
    for key in ("avg_order_value", "avg_freight", "payment_share:boleto"):
        assert full[key] == stratified[key]


def test_unknown_design_and_normalised_ratio_are_rejected() -> None:
    raw = _raw()
    raw["sample_design"] = "weighted"
    with pytest.raises(ValueError):
        parse_config(raw)
    raw = _raw()
    raw["metrics"]["avg_freight"]["normalise"] = "per_order"
    with pytest.raises(ValueError, match="normalise applies to counts and sums"):
        parse_config(raw)


def test_share_sql_divides_by_the_period_total_of_all_segments() -> None:
    m = _metrics("stratified")["daily_orders"]
    sql = Scanner(config=load_config(), run_sql=lambda _sql: []).series_sql(m, "state")
    assert "JOIN (SELECT CAST(purchase_ts AS DATE) AS period, COUNT(DISTINCT order_id) AS den" in sql
    assert "GROUP BY CAST(purchase_ts AS DATE)) t ON t.period = s.period" in sql


def test_share_attribution_explanatory_powers_sum_to_one() -> None:
    # RJ's share of all orders, attributed over categories: numerator = RJ orders in the category,
    # denominator = all orders in the category, so the denominators add up to the period total.
    cube = {"category": {
        "beleza": SliceValues(forecast=10, actual=40, forecast_den=100, actual_den=130),
        "esporte": SliceValues(forecast=10, actual=11, forecast_den=100, actual_den=100),
        "casa": SliceValues(forecast=10, actual=9, forecast_den=100, actual_den=100),
    }}
    result = attribute(cube, ratio=True)
    assert result and result[0].slices[0].value == "beleza"
    assert sum(result[0].explanatory_powers.values()) == pytest.approx(1.0)
