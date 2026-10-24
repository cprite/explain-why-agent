"""Markovian engine configuration (architecture §5.2), read from `MARKOVIAN_*` environment variables.

    config = MarkovianConfig.from_env()

Sizes are in characters, not tokens: the engine budgets what it builds, and the token report
converts with the guide's `ceil(chars / 4)` estimate. Invalid values raise `MarkovianConfigError`
naming the variable, the value and the allowed range.
"""

from __future__ import annotations

import os
from collections.abc import Mapping

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

ENV_PREFIX = "MARKOVIAN_"


class MarkovianConfigError(ValueError):
    """A `MARKOVIAN_*` variable holds a value the engine cannot run with."""


class MarkovianConfig(BaseModel):
    """Caps and budgets for one Markovian run."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    # Chain depth cap: chunk 0 (plan) plus about seven hypothesis rounds keeps a run inside 10 minutes.
    max_chunks: int = Field(default=8, ge=1, le=50)
    # Hard ceiling on the input the chunk manager builds for one chunk (goal + carryover + evidence).
    chunk_budget_chars: int = Field(default=12000, ge=1000, le=200000)
    # Ceiling on the rendered carryover state passed from one chunk to the next.
    carryover_budget_chars: int = Field(default=1200, ge=200, le=100000)
    # Wall-clock limit for one chunk (one investigate-and-critique round), enforced by the orchestrator.
    chunk_timeout_seconds: float = Field(default=180.0, gt=0, le=3600)
    # Wall-clock limit for the single model-compression call in the carryover cascade (step 2).
    compression_timeout_seconds: float = Field(default=30.0, gt=0, le=600)
    # Wall-clock limit for a whole orchestrated run (MARKOVIAN_RUN_TIMEOUT_S): the run stops with
    # stop_reason "timeout" when it is reached. 540 s keeps a run inside the 10-minute demo limit.
    run_timeout_s: float = Field(default=540.0, gt=0, le=3600)

    @model_validator(mode="after")
    def _check_relations(self) -> MarkovianConfig:
        if self.carryover_budget_chars * 2 > self.chunk_budget_chars:
            raise ValueError(
                f"MARKOVIAN_CARRYOVER_BUDGET_CHARS ({self.carryover_budget_chars}) must be at most half of "
                f"MARKOVIAN_CHUNK_BUDGET_CHARS ({self.chunk_budget_chars}), so evidence still fits in a chunk"
            )
        if self.compression_timeout_seconds > self.chunk_timeout_seconds:
            raise ValueError(
                f"MARKOVIAN_COMPRESSION_TIMEOUT_SECONDS ({self.compression_timeout_seconds:g}) must not exceed "
                f"MARKOVIAN_CHUNK_TIMEOUT_SECONDS ({self.chunk_timeout_seconds:g})"
            )
        return self

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> MarkovianConfig:
        """Build the config from `environ` (default: the process environment).

        Unset or blank variables take the default. Raises `MarkovianConfigError` listing every
        invalid variable.
        """
        env = os.environ if environ is None else environ
        values = {
            name: env[f"{ENV_PREFIX}{name.upper()}"].strip()
            for name in cls.model_fields
            if env.get(f"{ENV_PREFIX}{name.upper()}", "").strip()
        }
        try:
            return cls.model_validate(values)
        except ValidationError as exc:
            raise MarkovianConfigError(_describe(exc, values)) from None


def _describe(exc: ValidationError, values: Mapping[str, str]) -> str:
    lines = []
    for error in exc.errors():
        loc = error.get("loc") or ()
        if loc:
            field = str(loc[0])
            var = f"{ENV_PREFIX}{field.upper()}"
            lines.append(f"{var}={values.get(field, error.get('input'))!r}: {error['msg']}")
        else:
            lines.append(str(error["msg"]).removeprefix("Value error, "))
    return "invalid Markovian configuration: " + "; ".join(lines)
