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
    zetaris_url: str = ""
    zetaris_api_key: str = ""
    max_query_rows: int = Field(default=5000, ge=1)
    query_timeout_seconds: int = Field(default=30, ge=1)
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
    max_output_tokens: int = Field(default=2048, ge=1)
    max_retries: int = Field(default=3, ge=0, le=3)
    record_cache: bool = False
    llm_cache_dir: str = "data/sample/llm_cache"

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
