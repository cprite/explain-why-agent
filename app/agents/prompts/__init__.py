"""Prompt templates for the agents, kept as Markdown files next to this module.

Prompts are generic: they describe the method, never a particular incident, date, segment or answer.
Each file starts with a short header for readers, an HTML comment saying what the agent does and what
it must not do; `load_prompt` drops it, so the model sees (and the sample-mode cache key hashes) only
the text after it.
"""

from __future__ import annotations

import re
from functools import cache
from pathlib import Path

PROMPT_DIR = Path(__file__).resolve().parent
HEADER_RE = re.compile(r"\A\s*<!--.*?-->", re.DOTALL)


@cache
def load_prompt(name: str) -> str:
    """Return the text of `<name>.md` from the prompts directory, without its header comment."""
    return HEADER_RE.sub("", (PROMPT_DIR / f"{name}.md").read_text(encoding="utf-8"), count=1).strip()
