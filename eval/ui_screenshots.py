"""Screenshots of the web page for review (headless Chromium through Playwright).

Expects the API on UI_SHOTS_URL (default http://127.0.0.1:8001) in sample mode with the Nemotron
recordings (`LLM_CACHE_DIR=data/recorded/nemotron/llm_cache`). Saves ui-*.png in the working
directory (or UI_SHOTS_DIR): the board, the "Agents at work" panel half-way through a replay, and the answer, in the
light and the dark theme. Not a check: it exits 0 unless the page could not be driven at all.
"""

from __future__ import annotations

import os
import sys

from playwright.sync_api import Page, sync_playwright

BASE = os.environ.get("UI_SHOTS_URL", "http://127.0.0.1:8001").rstrip("/")
OUT = os.environ.get("UI_SHOTS_DIR", ".")
QUESTION = "Why did delivery lateness spike for deliveries completed the week of 28 May 2018?"


def shoot(page: Page, theme: str) -> None:
    page.goto(f"{BASE}/", wait_until="domcontentloaded")
    page.wait_for_selector("#top-cards article.card", timeout=180_000)
    page.screenshot(path=f"{OUT}/ui-{theme}-1-board.png")
    page.fill("#question", QUESTION)
    page.click("#ask")
    page.wait_for_selector("#live button.replay", timeout=120_000)
    page.click("#live button.replay")
    page.wait_for_timeout(9_000)  # about twenty hand-offs into the replay
    page.locator("#live").scroll_into_view_if_needed()
    page.locator("#live").screenshot(path=f"{OUT}/ui-{theme}-2-live.png")
    page.wait_for_selector("#live button.replay", timeout=120_000)
    page.locator("#live").screenshot(path=f"{OUT}/ui-{theme}-3-live-done.png")
    page.locator("#result").screenshot(path=f"{OUT}/ui-{theme}-4-answer.png")
    print(f"{theme}: saved", flush=True)


def main() -> int:
    with sync_playwright() as pw:
        exe = os.environ.get("UI_SHOTS_CHROMIUM") or None  # a system Chromium instead of Playwright's
        browser = pw.chromium.launch(headless=True, executable_path=exe)
        for theme in ("light", "dark"):
            page = browser.new_page(viewport={"width": 1280, "height": 900}, color_scheme=theme)
            shoot(page, theme)
            page.close()
        browser.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
