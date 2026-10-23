"""`python -m app.api`: serve the API on `API_HOST`:`API_PORT` (defaults 0.0.0.0:8000)."""

from __future__ import annotations

import uvicorn

from app.config import get_settings


def main() -> None:
    """Start uvicorn with the bind address and port from the environment."""
    settings = get_settings()
    uvicorn.run("app.api.main:app", host=settings.api_host, port=settings.api_port)


if __name__ == "__main__":
    main()
