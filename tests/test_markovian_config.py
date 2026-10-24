"""Tests for the Markovian engine configuration (app/engines/markovian/config.py)."""

from __future__ import annotations

import pytest

from app.engines.markovian.config import MarkovianConfig, MarkovianConfigError

ENV_KEYS = (
    "MARKOVIAN_MAX_CHUNKS",
    "MARKOVIAN_CHUNK_BUDGET_CHARS",
    "MARKOVIAN_CARRYOVER_BUDGET_CHARS",
    "MARKOVIAN_CHUNK_TIMEOUT_SECONDS",
    "MARKOVIAN_COMPRESSION_TIMEOUT_SECONDS",
)


@pytest.fixture(autouse=True)
def clear_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


def test_defaults_with_empty_environment() -> None:
    config = MarkovianConfig.from_env()
    assert config.max_chunks == 8
    assert config.chunk_budget_chars == 12000
    assert config.carryover_budget_chars == 1200
    assert config.chunk_timeout_seconds == 180.0
    assert config.compression_timeout_seconds == 30.0


def test_process_environment_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MARKOVIAN_MAX_CHUNKS", "5")
    monkeypatch.setenv("MARKOVIAN_CHUNK_BUDGET_CHARS", "6000")
    monkeypatch.setenv("MARKOVIAN_CARRYOVER_BUDGET_CHARS", " 800 ")
    monkeypatch.setenv("MARKOVIAN_CHUNK_TIMEOUT_SECONDS", "90")
    monkeypatch.setenv("MARKOVIAN_COMPRESSION_TIMEOUT_SECONDS", "12.5")
    config = MarkovianConfig.from_env()
    assert (config.max_chunks, config.chunk_budget_chars, config.carryover_budget_chars) == (5, 6000, 800)
    assert (config.chunk_timeout_seconds, config.compression_timeout_seconds) == (90.0, 12.5)


def test_explicit_mapping_and_blank_values_take_defaults() -> None:
    config = MarkovianConfig.from_env({"MARKOVIAN_MAX_CHUNKS": "3", "MARKOVIAN_CHUNK_BUDGET_CHARS": "  "})
    assert config.max_chunks == 3
    assert config.chunk_budget_chars == 12000


@pytest.mark.parametrize(
    ("env", "fragment"),
    [
        ({"MARKOVIAN_MAX_CHUNKS": "0"}, "MARKOVIAN_MAX_CHUNKS='0'"),
        ({"MARKOVIAN_MAX_CHUNKS": "51"}, "MARKOVIAN_MAX_CHUNKS='51'"),
        ({"MARKOVIAN_MAX_CHUNKS": "eight"}, "MARKOVIAN_MAX_CHUNKS='eight'"),
        ({"MARKOVIAN_MAX_CHUNKS": "2.5"}, "MARKOVIAN_MAX_CHUNKS='2.5'"),
        ({"MARKOVIAN_CHUNK_BUDGET_CHARS": "999"}, "MARKOVIAN_CHUNK_BUDGET_CHARS='999'"),
        ({"MARKOVIAN_CARRYOVER_BUDGET_CHARS": "-1"}, "MARKOVIAN_CARRYOVER_BUDGET_CHARS='-1'"),
        ({"MARKOVIAN_CHUNK_TIMEOUT_SECONDS": "0"}, "MARKOVIAN_CHUNK_TIMEOUT_SECONDS='0'"),
        ({"MARKOVIAN_CHUNK_TIMEOUT_SECONDS": "nan"}, "MARKOVIAN_CHUNK_TIMEOUT_SECONDS='nan'"),
        ({"MARKOVIAN_COMPRESSION_TIMEOUT_SECONDS": "soon"}, "MARKOVIAN_COMPRESSION_TIMEOUT_SECONDS='soon'"),
        (
            {"MARKOVIAN_CHUNK_BUDGET_CHARS": "2000", "MARKOVIAN_CARRYOVER_BUDGET_CHARS": "1500"},
            "must be at most half of MARKOVIAN_CHUNK_BUDGET_CHARS",
        ),
        (
            {"MARKOVIAN_CHUNK_TIMEOUT_SECONDS": "10", "MARKOVIAN_COMPRESSION_TIMEOUT_SECONDS": "20"},
            "must not exceed MARKOVIAN_CHUNK_TIMEOUT_SECONDS",
        ),
    ],
)
def test_invalid_values_are_rejected_with_the_variable_named(env: dict[str, str], fragment: str) -> None:
    with pytest.raises(MarkovianConfigError) as info:
        MarkovianConfig.from_env(env)
    message = str(info.value)
    assert message.startswith("invalid Markovian configuration: ")
    assert fragment in message


def test_every_invalid_variable_is_listed_at_once() -> None:
    with pytest.raises(MarkovianConfigError) as info:
        MarkovianConfig.from_env({"MARKOVIAN_MAX_CHUNKS": "x", "MARKOVIAN_CHUNK_BUDGET_CHARS": "1"})
    assert "MARKOVIAN_MAX_CHUNKS" in str(info.value)
    assert "MARKOVIAN_CHUNK_BUDGET_CHARS" in str(info.value)


def test_invalid_process_environment_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MARKOVIAN_MAX_CHUNKS", "-3")
    with pytest.raises(MarkovianConfigError, match="MARKOVIAN_MAX_CHUNKS"):
        MarkovianConfig.from_env()


def test_config_is_frozen() -> None:
    config = MarkovianConfig.from_env({})
    with pytest.raises(ValueError):
        config.max_chunks = 99  # type: ignore[misc]


def test_every_variable_is_documented_in_env_example() -> None:
    from app.config import REPO_ROOT

    example = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")
    for key in ENV_KEYS:
        assert f"\n{key}=" in example
