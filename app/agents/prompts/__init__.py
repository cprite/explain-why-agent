"""Prompt templates for the agents, kept as Markdown files next to this module.

Prompts are generic: they describe the method, never a particular incident, date, segment or answer.
"""

from __future__ import annotations

from functools import cache
from pathlib import Path

PROMPT_DIR = Path(__file__).resolve().parent


@cache
def load_prompt(name: str) -> str:
    """Return the text of `<name>.md` from the prompts directory."""
    return (PROMPT_DIR / f"{name}.md").read_text(encoding="utf-8").strip()
