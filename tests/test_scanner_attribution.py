"""Adtributor attribution tests on synthetic cubes (acceptance criterion 3)."""

from __future__ import annotations

import pytest

from app.scanner.attribution import SliceValues, attribute

STATES = {"SP": 500.0, "RJ": 200.0, "MG": 150.0, "RS": 100.0, "BA": 50.0}
CATEGORIES = {"beleza": 0.30, "esporte": 0.25, "casa": 0.25, "relogios": 0.20}


def _additive_cube(rj_extra: float) -> dict[str, dict[str, SliceValues]]:
    """Orders by state and by category; RJ gains `rj_extra` orders spread evenly over categories."""
    states = {k: SliceValues(forecast=v, actual=v + (rj_extra if k == "RJ" else 0.0)) for k, v in STATES.items()}
    total_f = sum(STATES.values())
    total_a = total_f + rj_extra
    categories = {k: SliceValues(forecast=total_f * share, actual=total_a * share) for k, share in CATEGORIES.items()}
    return {"category": categories, "state": states}


def test_known_slice_ranks_first_and_its_dimension_ranks_first() -> None:
    result = attribute(_additive_cube(rj_extra=300.0))
    assert result[0].dimension == "state"
    assert result[0].slices[0].value == "RJ"
    assert result[0].slices[0].explanatory_power == pytest.approx(1.0)
    assert result[0].explained >= 0.67
    # The category split did not move: no slice there is surprising.
    other = [r for r in result if r.dimension == "category"]
    assert not other or other[0].surprise < result[0].surprise


def test_explanatory_powers_in_a_dimension_sum_to_one() -> None:
    cube = _additive_cube(rj_extra=300.0)
    cube["state"]["SP"] = SliceValues(forecast=500.0, actual=560.0)
    cube["state"]["BA"] = SliceValues(forecast=50.0, actual=20.0)
    for dimension in attribute(cube, explains_threshold=0.0, slice_threshold=-1.0, top_dimensions=5):
        assert sum(dimension.explanatory_powers.values()) == pytest.approx(1.0)


def test_smallest_set_reaching_threshold_is_listed_by_surprise() -> None:
    # Change of +100: SP +40 (large slice, small share shift), BA +40 (small slice, big shift), RJ +20.
    states = {
        "SP": SliceValues(500.0, 540.0),
        "BA": SliceValues(50.0, 90.0),
        "RJ": SliceValues(200.0, 220.0),
        "MG": SliceValues(150.0, 150.0),
    }
    (result,) = attribute({"state": states})
    assert {s.value for s in result.slices} == {"SP", "BA"}  # 80% with two slices
    assert [s.value for s in result.slices] == ["BA", "SP"]  # BA is the bigger surprise
    assert result.explained == pytest.approx(0.8)


def test_dimension_without_a_concentrated_cause_is_dropped() -> None:
    # Twenty equal slices each grow 10%: each explains 5% of the change, below the 10% slice
    # threshold, so the dimension has no explaining set.
    flat = {f"s{i}": SliceValues(10.0, 11.0) for i in range(20)}
    assert attribute({"seller": flat}) == []


def test_ratio_metric_attributes_through_numerator_and_denominator() -> None:
    # Average review score = sum(score) / count(reviews). Category relogios: same review count,
    # scores collapse from 4.0 to 2.0 on average (a numerator move).
    def cube(relogios_avg: float, relogios_count: float) -> dict[str, dict[str, SliceValues]]:
        cats = {}
        for name, count in {"beleza": 300.0, "esporte": 250.0, "casa": 250.0}.items():
            cats[name] = SliceValues(forecast=4.0 * count, actual=4.0 * count, forecast_den=count, actual_den=count)
        cats["relogios"] = SliceValues(
            forecast=4.0 * 200.0, actual=relogios_avg * relogios_count, forecast_den=200.0, actual_den=relogios_count
        )
        return {"category": cats}

    (numerator_case,) = attribute(cube(relogios_avg=2.0, relogios_count=200.0), ratio=True)
    assert numerator_case.slices[0].value == "relogios"
    assert numerator_case.slices[0].explanatory_power == pytest.approx(1.0)
    assert numerator_case.slices[0].forecast == pytest.approx(4.0)
    assert numerator_case.slices[0].actual == pytest.approx(2.0)
    assert sum(numerator_case.explanatory_powers.values()) == pytest.approx(1.0)

    # Mix shift through the denominator: a low-scoring category (avg 2.0 throughout) gains
    # volume, so the overall average falls although no category's own average moved.
    cats = {
        "beleza": SliceValues(4.0 * 400, 4.0 * 400, 400.0, 400.0),
        "esporte": SliceValues(4.0 * 400, 4.0 * 400, 400.0, 400.0),
        "relogios": SliceValues(2.0 * 100, 2.0 * 500, 100.0, 500.0),
    }
    (mix_case,) = attribute({"category": cats}, ratio=True)
    assert mix_case.slices[0].value == "relogios"
    assert mix_case.slices[0].forecast == pytest.approx(mix_case.slices[0].actual)  # its own ratio is flat
    assert sum(mix_case.explanatory_powers.values()) == pytest.approx(1.0)
    assert mix_case.explained >= 0.67


def test_ratio_surprise_adds_numerator_and_denominator_terms() -> None:
    cats = {
        "a": SliceValues(400.0, 400.0, 100.0, 100.0),
        "b": SliceValues(400.0, 100.0, 100.0, 100.0),
    }
    ratio = attribute({"c": cats}, ratio=True, explains_threshold=0.0, slice_threshold=-1.0)[0]
    num_only = attribute(
        {"c": {k: SliceValues(v.forecast, v.actual) for k, v in cats.items()}},
        explains_threshold=0.0,
        slice_threshold=-1.0,
    )[0]
    # Denominator shares did not move, so the ratio surprise equals the numerator surprise.
    by_value = {s.value: s.surprise for s in ratio.slices}
    assert by_value["b"] == pytest.approx({s.value: s.surprise for s in num_only.slices}["b"])


def test_no_change_returns_nothing() -> None:
    same = {"x": SliceValues(10.0, 10.0), "y": SliceValues(5.0, 5.0)}
    assert attribute({"d": same}) == []
    assert attribute({"d": {"x": SliceValues(1.0, 1.0, 1.0, 1.0)}}, ratio=True) == []
