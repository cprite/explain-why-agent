"""Anomaly card and scan report models (the scanner's own output; not the investigation result)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field


class Segment(BaseModel):
    type: str  # segment type key from config.yaml (all, state, category, ...)
    value: str  # slice value; "all" for the whole shop
    label: str  # readable, e.g. "state RJ"


class Period(BaseModel):
    start: date
    end: date  # last day covered (inclusive)
    grain: Literal["day", "week"]
    periods: int = Field(ge=1)


class SliceAttribution(BaseModel):
    value: str
    explanatory_power: float
    surprise: float
    baseline: float
    observed: float


class DimensionAttribution(BaseModel):
    dimension: str
    explained: float
    surprise: float
    slices: list[SliceAttribution]


class AnomalyCard(BaseModel):
    id: str
    rank: int = Field(ge=1)  # position in the list the card is in (overall top ten, or within its metric)
    overall_rank: int | None = Field(default=None, ge=1)  # position among all flagged episodes
    metric: str  # metric key, e.g. avg_freight or payment_share:boleto
    metric_label: str
    segment: Segment
    period: Period
    baseline: float  # expected value per period
    observed: float  # observed value per period
    change: float  # observed - baseline
    change_pct: float | None  # None when the baseline is zero
    direction: Literal["rise", "fall"]
    z_score: float
    volume: int  # orders behind the peak period
    score: float  # |z| x ln(volume)
    method: str  # "stl" or "trailing_median"
    top_attribution: str | None  # e.g. "driven by state RJ: 72% of the change"
    attribution: list[DimensionAttribution]
    merged: list[str] = Field(default_factory=list)  # child cards folded into this one
    question: str


class MetricBoard(BaseModel):
    """The top flagged episodes of one configured metric, ranked by score within that metric."""

    metric: str  # configured metric key; variant metrics (payment_share:boleto, ...) are grouped
    metric_label: str
    episodes_found: int  # flagged episodes of this metric after the parent/child merge
    cards: list[AnomalyCard]  # overall top ten
    by_metric: list[MetricBoard] = Field(default_factory=list)  # per-metric view, config order


class ScanReport(BaseModel):
    generated_at: datetime
    data_source: str
    elapsed_seconds: float
    timed_out: bool
    queries: int
    series_scanned: int
    episodes_found: int
    thresholds: dict[str, float]
    cards: list[AnomalyCard]  # overall top ten
    by_metric: list[MetricBoard] = Field(default_factory=list)  # per-metric view, config order
