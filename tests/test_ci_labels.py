"""The plan check letters in .github/workflows/ci.yml are not reused (Sprint 10b).

The eval step (PR #20) and the Critic step (PR #28) were both "Plan check L"; the Critic step is N
now (M is PR #30's). Plan check D is the one known exception: Sprint 6b added "Plan check D (task 10)"
next to main's "Plan check D (task 7)" on purpose (docs/sprints/06b-zetaris-adapter.md), each with
its own task number.
"""

from __future__ import annotations

import re
from collections import Counter

from app.config import REPO_ROOT

CI = REPO_ROOT / ".github" / "workflows" / "ci.yml"
LABEL = re.compile(r'^\s*- name: "Plan check ([A-Z])\b([^"]*)"', re.MULTILINE)
KNOWN_SHARED = {"D": 2}
"""Letters used by more than one step on purpose, with how many steps use them."""


def labels() -> list[tuple[str, str]]:
    return LABEL.findall(CI.read_text(encoding="utf-8"))


def test_no_plan_check_letter_is_used_twice() -> None:
    counts = Counter(letter for letter, _ in labels())
    shared = {letter: n for letter, n in counts.items() if n > 1}
    assert shared == KNOWN_SHARED
    tasks = [rest for letter, rest in labels() if letter in KNOWN_SHARED]
    assert len(set(tasks)) == len(tasks)  # the D steps still differ by their task number


def test_eval_is_l_and_the_critic_step_is_n() -> None:
    by_letter: dict[str, list[str]] = {}
    for letter, rest in labels():
        by_letter.setdefault(letter, []).append(rest)
    assert by_letter["L"] == [
        ": evaluation against the answer key in sample mode (score gated on the committed after score)"]
    assert by_letter["N"] == [" (tasks 13+14): Critic verdicts and the three branches in sample mode"]
