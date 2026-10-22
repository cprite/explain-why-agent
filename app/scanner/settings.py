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


class AttributionConfig(BaseModel):
    explains_threshold: float = Field(gt=0, le=1)
    slice_threshold: float = Field(ge=0, le=1)
    top_dimensions: int = Field(ge=1)


class RankingConfig(BaseModel):
    max_cards: int = Field(ge=1)
    attribute_top: int = Field(ge=0)


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

    @property
    def is_ratio(self) -> bool:
        return self.denominator is not None


class ScannerConfig(BaseModel):
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
        """Metrics with one copy per variant (e.g. payment share per payment type)."""
        out: list[Metric] = []
        for metric in self.metrics:
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
