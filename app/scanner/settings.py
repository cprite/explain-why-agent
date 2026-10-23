"""Load and validate app/scanner/config.yaml."""

from __future__ import annotations

import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field

CONFIG_PATH = Path(__file__).with_name("config.yaml")
DEFAULT_TIMEOUT_S = 300.0

Grain = Literal["day", "week"]
SampleDesign = Literal["stratified", "full"]
Normalise = Literal["period_share", "per_order"]


class DetectionConfig(BaseModel):
    z_threshold: float = Field(gt=0)
    volume_floor: int = Field(ge=0)
    windows: dict[str, int]
    cycle: dict[str, int] = Field(default_factory=dict)
    min_cycles: int = Field(ge=1)
    stl_seasonal: int = Field(ge=7)
    min_history: dict[str, int]
    merge_gap: int = Field(ge=0)
    z_cap: float = Field(gt=0)
    mad_floor: float = Field(default=0.0, ge=0)  # spread floor, as a share of |trailing median|


class AttributionConfig(BaseModel):
    explains_threshold: float = Field(gt=0, le=1)
    slice_threshold: float = Field(ge=0, le=1)
    top_dimensions: int = Field(ge=1)


class RankingConfig(BaseModel):
    max_cards: int = Field(ge=1)
    attribute_top: int = Field(ge=0)
    per_metric_top: int = Field(default=3, ge=0)  # episodes per metric on the per-metric board


class LimitsConfig(BaseModel):
    max_queries: int = Field(ge=1)
    max_series: int = Field(ge=1)
    max_episodes_per_series: int = Field(ge=1)


class SegmentType(BaseModel):
    label: str
    column: str | None = None
    min_total_volume: int = 0


class Metric(BaseModel):
    """One metric as configured; `variant` is set on the expanded copies of a variant metric."""

    key: str
    label: str
    fact: str
    time: str
    grain: Grain
    numerator: str
    denominator: str | None = None
    volume: str
    filter: str | None = None
    segments: list[str]
    variants: list[str] = Field(default_factory=list)
    variant: str | None = None
    # Sampling-robust form used when sample_design is "stratified": a count becomes the segment's
    # share of the period's orders ("period_share"), a sum becomes a per-order mean ("per_order").
    normalise: Normalise | None = None
    normalised_label: str | None = None
    share_of_period: bool = False  # set on the stratified copy of a period_share metric

    @property
    def is_ratio(self) -> bool:
        return self.denominator is not None

    def for_design(self, design: SampleDesign) -> Metric:
        """The metric as scanned under `design`: unchanged for a full extract; for a stratified
        sample, counts and sums are turned into shares and per-order means."""
        if design == "full" or self.normalise is None:
            return self
        update: dict = {"label": self.normalised_label or self.label, "denominator": self.volume}
        if self.normalise == "period_share":
            # The whole shop's share of its own orders is 1 by definition: nothing to scan.
            update["share_of_period"] = True
            update["segments"] = [s for s in self.segments if s != "all"]
        return self.model_copy(update=update)


class ScannerConfig(BaseModel):
    sample_design: SampleDesign = "stratified"
    detection: DetectionConfig
    attribution: AttributionConfig
    ranking: RankingConfig
    limits: LimitsConfig
    grains: dict[str, str]
    facts: dict[str, str]
    segments: dict[str, SegmentType]
    metrics: list[Metric]

    def segment(self, key: str) -> SegmentType:
        return self.segments[key]

    def fact_sql(self, name: str, _depth: int = 0) -> str:
        """Fact SQL with nested {fact.<name>} references expanded (depth capped)."""
        if _depth > 3:
            raise ValueError(f"fact nesting too deep at {name!r}")
        sql = self.facts[name]
        return re.sub(
            r"\{fact\.(\w+)\}",
            lambda m: self.fact_sql(m.group(1), _depth + 1).strip(),
            sql,
        )

    def expanded_metrics(self) -> list[Metric]:
        """Metrics as scanned: one copy per variant (e.g. payment share per payment type), each in
        the form the sample design calls for (see Metric.for_design)."""
        out: list[Metric] = []
        for metric in self.metrics:
            metric = metric.for_design(self.sample_design)
            if not metric.variants:
                out.append(metric)
                continue
            for variant in metric.variants:
                out.append(
                    metric.model_copy(
                        update={
                            "key": f"{metric.key}:{variant}",
                            "label": metric.label.replace("{variant}", variant),
                            "numerator": metric.numerator.replace("{variant}", variant),
                            "variants": [],
                            "variant": variant,
                        }
                    )
                )
        return out


def parse_config(raw: dict) -> ScannerConfig:
    data = dict(raw)
    data["metrics"] = [{"key": key, **body} for key, body in raw["metrics"].items()]
    config = ScannerConfig.model_validate(data)
    for metric in config.metrics:
        unknown = [s for s in metric.segments if s not in config.segments]
        if unknown:
            raise ValueError(f"metric {metric.key}: unknown segment types {unknown}")
        if metric.fact not in config.facts:
            raise ValueError(f"metric {metric.key}: unknown fact {metric.fact!r}")
        if metric.grain not in config.detection.windows:
            raise ValueError(f"metric {metric.key}: no window for grain {metric.grain!r}")
        if metric.normalise and metric.denominator:
            raise ValueError(f"metric {metric.key}: normalise applies to counts and sums, not ratios")
    return config


@lru_cache(maxsize=1)
def load_config(path: str | None = None) -> ScannerConfig:
    config_path = Path(path) if path else CONFIG_PATH
    with config_path.open(encoding="utf-8") as handle:
        return parse_config(yaml.safe_load(handle))


def timeout_seconds() -> float:
    """SCANNER_TIMEOUT_S from the environment (default 300 s); invalid or empty values use the default."""
    raw = os.environ.get("SCANNER_TIMEOUT_S", "").strip()
    try:
        value = float(raw) if raw else DEFAULT_TIMEOUT_S
    except ValueError:
        return DEFAULT_TIMEOUT_S
    return value if value > 0 else DEFAULT_TIMEOUT_S
