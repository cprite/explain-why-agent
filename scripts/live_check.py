"""Live check of the model generator: one real call that must return schema-valid JSON.

Not run in CI (it needs credentials). Run it on the build machine:

    METERLESS_RUNTIME_TOKEN=... python scripts/live_check.py              # through Meterless Runtime
    NVIDIA_API_KEY=... NVIDIA_MODEL=... python scripts/live_check.py --provider nvidia

Prints the provider status, the provider that answered, the model the runtime routed to, the
receipt id and the parsed JSON. Skips cleanly (exit 0) when the needed variables are missing.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from pydantic import BaseModel, Field

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings
from app.llm.generator import Generator, meterless_token_usable


class LiveCheckReply(BaseModel):
    """The small object the model is asked for."""

    sum: int = Field(description="The sum of the two numbers.")
    word: str = Field(description="The sum written as an English word.")


MESSAGES = [
    {"role": "system", "content": "You are a careful assistant that answers in JSON."},
    {"role": "user", "content": "Add 2 and 3. Give the sum as a number and as an English word."},
]


def main(argv: list[str] | None = None) -> int:
    """Run the live check; return the process exit code."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--provider", choices=("meterless", "nvidia"), default="meterless")
    args = parser.parse_args(argv)

    settings = get_settings()
    if args.provider == "meterless" and not meterless_token_usable(settings.meterless_token):
        print("SKIP: METERLESS_RUNTIME_TOKEN is not set (or is the rt-local placeholder); no call made.")
        return 0
    if args.provider == "nvidia" and not (settings.nvidia_api_key and settings.nvidia_model):
        print("SKIP: NVIDIA_API_KEY and NVIDIA_MODEL must both be set for --provider nvidia; no call made.")
        return 0

    settings = settings.model_copy(
        update={"sample_mode": False, "record_cache": False, "model_provider": args.provider}
    )
    generator = Generator(settings)
    if args.provider == "meterless":
        status = generator.meterless.status()
        print(f"meterless status: {status.state} ({status.reason}); base URL {generator.meterless.base_url}")
        print(f"routing modes: {', '.join(status.models) or '-'}")
    result = generator(MESSAGES, schema=LiveCheckReply, role="investigator", run_id="live-check")
    print(f"provider: {result.provider}")
    print(f"model requested: {result.model_requested}")
    print(f"model routed: {result.model_routed}")
    print(f"receipt id: {result.receipt_id}")
    print(f"retries: {result.retries}, repaired: {result.repaired}, {result.duration_ms:.0f} ms")
    if not result.ok:
        print(f"FAIL: {result.error['code']}: {result.error['message']}")
        return 1
    print(f"parsed JSON: {json.dumps(result.parsed)}")
    print("PASS: one live call returned schema-valid JSON")
    return 0


if __name__ == "__main__":
    sys.exit(main())
