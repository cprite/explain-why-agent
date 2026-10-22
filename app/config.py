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


REPO_ROOT = Path(__file__).resolve().parents[1]


def resolve_path(value: str) -> Path:
    """Resolve a configured path; relative paths are taken from the repository root."""
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def get_settings() -> Settings:
    """Build settings from the current process environment."""
    return Settings()
