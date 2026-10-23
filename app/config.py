"""Application settings loaded from environment variables only."""

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration. Missing keys use safe defaults; never raise at import."""

    model_config = SettingsConfigDict(
        env_file=None,
        env_ignore_empty=True,
        extra="ignore",
    )

    sample_mode: bool = True
    meterless_base_url: str = "http://127.0.0.1:8088/v1"
    meterless_api_key: str = ""
    nvidia_api_key: str = ""
    nvidia_base_url: str = ""
    model_name: str = ""
    # Data layer (architecture §3): zetaris (default; local when ZETARIS_URL is empty) or local.
    # Sample mode always uses local.
    data_layer: str = "zetaris"
    zetaris_url: str = ""
    zetaris_api_key: str = ""
    zetaris_org_id: str = ""
    # Login fallback when no API key is set or the key is refused: GET /auth/login with Basic auth.
    zetaris_username: str = ""
    zetaris_password: str = ""
    # Pause before the one retry of a failed Zetaris call (connection error, timeout, 5xx).
    zetaris_retry_delay_seconds: float = Field(default=1.0, ge=0.0, le=30.0)
    max_query_rows: int = Field(default=5000, ge=1)
    query_timeout_seconds: int = Field(default=30, ge=1)
    # DuckDB resource caps. Without them DuckDB takes 80 % of RAM and every core, so one runaway
    # model-written query can push a small host into swap until it stops responding.
    duckdb_memory_limit: str = "2GB"
    # One thread by default: with several, rows that tie in an ORDER BY can come back in a different
    # order on each run, which changes the model's input and breaks sample-mode replay.
    duckdb_threads: int = Field(default=1, ge=1)
    # Database file and spill directory. On disk, not in /tmp: /tmp is often RAM-backed (tmpfs),
    # which would make spilling to "disk" use memory after all.
    duckdb_work_dir: str = ".cache/duckdb"
    model_timeout_seconds: int = Field(default=60, ge=1)
    log_dir: str = "logs"
    sample_data_dir: str = "data/sample"

    # Model generator (architecture §6). Primary provider: Meterless Runtime (Nightshift).
    model_provider: str = "meterless"
    meterless_runtime_token: str = ""
    meterless_model: str = ""
    meterless_model_planner: str = ""
    meterless_model_investigator: str = ""
    meterless_model_critic: str = ""
    meterless_model_reporter: str = ""
    nvidia_model: str = ""
    model_temperature: float = Field(default=0.2, ge=0.0, le=2.0)
    max_output_tokens: int = Field(default=4096, ge=1)
    max_retries: int = Field(default=3, ge=0, le=3)
    record_cache: bool = False
    llm_cache_dir: str = "data/sample/llm_cache"
    # Recorded query results for sample mode: written with RECORD_CACHE in a live run, served in
    # sample mode so the agents see identical rows on every machine (ties in ORDER BY ... LIMIT
    # otherwise pick different rows on different platforms and the model cache no longer matches).
    query_cache_dir: str = "data/sample/query_cache"

    # Investigation loop caps (architecture §7).
    max_agent_rounds: int = Field(default=6, ge=1)
    max_tool_calls: int = Field(default=20, ge=1)


REPO_ROOT = Path(__file__).resolve().parents[1]


def resolve_path(value: str) -> Path:
    """Resolve a configured path; relative paths are taken from the repository root."""
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def get_settings() -> Settings:
    """Build settings from the current process environment."""
    return Settings()
