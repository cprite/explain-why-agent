"""Placeholder CLI entry point. Replaced by the investigation loop in a later sprint."""

from __future__ import annotations

import argparse
import json
import sys

from app.config import get_settings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Explain-why agent (skeleton)")
    parser.add_argument("question", help="Question to investigate")
    args = parser.parse_args(argv)

    settings = get_settings()
    payload = {
        "status": "not_implemented",
        "sample_mode": settings.sample_mode,
        "question": args.question,
    }
    print(json.dumps(payload))
    return 0


if __name__ == "__main__":
    sys.exit(main())
