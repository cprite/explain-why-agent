"""Pick the data layer from the configuration: `DATA_LAYER=zetaris|local`; sample mode is always local."""

from __future__ import annotations

import sys
from pathlib import Path

from app.config import Settings, get_settings
from app.data.layer import DataLayer
from app.data.local import LocalDataLayer

DATA_LAYERS = ("zetaris", "local")


def make_data_layer(
    run_id: str = "adhoc",
    *,
    settings: Settings | None = None,
    log_dir: Path | str | None = None,
) -> DataLayer:
    """Return the configured data layer (use it as a context manager, it holds a database or client).

    - `SAMPLE_MODE=true`: always `LocalDataLayer`; nothing touches the network.
    - `DATA_LAYER=local`: `LocalDataLayer`.
    - `DATA_LAYER=zetaris` (default): `ZetarisDataLayer`, falling back to local per query. With
      `ZETARIS_URL` empty it uses `LocalDataLayer` and says so on stderr; with the URL set but the
      organisation id or credentials missing it raises `ValueError`.
    """
    settings = settings or get_settings()
    choice = settings.data_layer.strip().lower()
    if choice not in DATA_LAYERS:
        raise ValueError(f"DATA_LAYER must be one of {', '.join(DATA_LAYERS)}, got {settings.data_layer!r}")
    if settings.sample_mode or choice == "local":
        return LocalDataLayer(run_id=run_id, log_dir=log_dir, settings=settings)
    if not settings.zetaris_url:
        print("DATA_LAYER=zetaris but ZETARIS_URL is empty; using the local adapter", file=sys.stderr)
        return LocalDataLayer(run_id=run_id, log_dir=log_dir, settings=settings)
    from app.data.zetaris import ZetarisDataLayer

    return ZetarisDataLayer(run_id=run_id, log_dir=log_dir, settings=settings)
