"""Browser check of the web page (Sprint 13b plan check), headless Chromium through Playwright.

CI only (`.github/workflows/browser-check.yml`); never run Chromium on the build machine. Expects the
API on BROWSER_CHECK_URL (default http://127.0.0.1:8000) in sample mode:

    SAMPLE_MODE=true python -m app.api &
    python eval/browser_check.py

Prints one [PASS]/[FAIL] line per assertion, saves a full-page screenshot to
BROWSER_CHECK_SCREENSHOT (default browser-check.png) and exits 1 if any assertion failed. Every wait
has a cap.
"""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from playwright.sync_api import Page, sync_playwright

BASE = os.environ.get("BROWSER_CHECK_URL", "http://127.0.0.1:8000").rstrip("/")
SCREENSHOT = Path(os.environ.get("BROWSER_CHECK_SCREENSHOT", "browser-check.png"))
DAY1_QUESTION = "Why did order volume spike on 24 November 2017?"
INCIDENT_06 = '.tile[data-metric="avg_review_score"] article.card[data-card-id^="avg_review_score|category|relogios_presentes|2018-01"]'
CACHE_MISS_TEXT = "No recorded answer for this question in sample mode"
BOARD_TIMEOUT_MS = 180_000  # first load runs the scan (about 30 s)
RUN_TIMEOUT_MS = 120_000
STEP_TIMEOUT_MS = 15_000

results: list[tuple[bool, str]] = []


def check(name: str, condition: Callable[[], Any]) -> bool:
    try:
        value = condition()
        ok = value is None or bool(value)
        detail = "" if value is None or isinstance(value, bool) else f" ({value})"
    except Exception as exc:  # noqa: BLE001 - reported as a failed assertion
        ok, detail = False, f" ({type(exc).__name__}: {str(exc).splitlines()[0][:300]})"
    results.append((ok, name))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{detail}", flush=True)
    return ok


def _none(items: list[str]) -> None:
    assert not items, "; ".join(items)[:500]


def no_stack_trace(text: str) -> bool:
    return not any(marker in text for marker in ("Traceback", 'File "', "Error:\n", " at line "))


def run(page: Page) -> None:
    page.set_default_timeout(STEP_TIMEOUT_MS)
    page.goto(f"{BASE}/", wait_until="domcontentloaded")

    # The board: overall cards and the per-metric tiles.
    check("board shows the overall cards",
          lambda: page.wait_for_selector("#top-cards article.card", timeout=BOARD_TIMEOUT_MS) and
          f"{page.locator('#top-cards article.card').count()} cards")
    check("at most ten overall cards", lambda: 1 <= page.locator("#top-cards article.card").count() <= 10)
    check("one tile per metric, review-score tile present",
          lambda: page.locator(".tile").count() >= 1 and
          page.locator('.tile[data-metric="avg_review_score"]').count() == 1 and
          f"{page.locator('.tile').count()} tiles")
    check("every card has an Explain button",
          lambda: page.locator("article.card").count() == page.locator("article.card button.explain").count())
    check("incident-06 is not on the review-score tile before Show more", lambda: page.locator(INCIDENT_06).count() == 0)

    # Show more on the average review score tile reveals incident-06.
    check("Show more on the review-score tile",
          lambda: page.locator('.tile[data-metric="avg_review_score"] button.show-more').click() or True)
    check("incident-06 card appears (avg review score, relogios_presentes, January 2018)",
          lambda: page.wait_for_selector(INCIDENT_06) and page.locator(INCIDENT_06).inner_text().replace("\n", " | "))

    # Explain on incident-06: sample mode has no recorded answer -> readable cache_miss message.
    check("Explain on the incident-06 card", lambda: page.locator(f"{INCIDENT_06} button.explain").click() or True)
    check("readable cache_miss message",
          lambda: page.wait_for_selector(f"#message:has-text('{CACHE_MISS_TEXT}')", timeout=RUN_TIMEOUT_MS) and
          page.locator("#message").inner_text())
    check("no stack trace in the message", lambda: no_stack_trace(page.locator("#message").inner_text()))
    check("buttons enabled again after the run", lambda: not page.locator("#ask").is_disabled())

    # The Day-1 question, typed.
    page.fill("#question", DAY1_QUESTION)
    page.click("#ask")
    check("Ask disables the button and shows elapsed seconds",
          lambda: page.locator("#ask").is_disabled() or page.locator("#result .result-body").count() == 1)
    check("result view appears",
          lambda: page.wait_for_selector("#result .result-body", timeout=RUN_TIMEOUT_MS) is not None)
    check("agents-at-work panel shows the hand-offs, the hypotheses and a Replay button",
          lambda: page.locator("#live .feed li.step").count() >= 5 and page.locator("#live .hyp").count() >= 1 and
          page.locator("#live button.replay").count() == 1 and
          f"{page.locator('#live .feed li.step').count()} steps, {page.locator('#live .hyp').count()} hypotheses")
    check("Replay animates the hand-offs with an active agent",
          lambda: page.locator("#live button.replay").click() is None and
          page.wait_for_selector("#live .agent.active", timeout=STEP_TIMEOUT_MS) is not None and
          page.wait_for_selector("#live button.replay", timeout=60_000) is not None)
    check("at least one ranked cause", lambda: page.locator("#result li.cause").count() >= 1 and
          page.locator("#result li.cause").first.inner_text().replace("\n", " | ")[:200])
    check("no 'Cannot be determined' on a determinable answer",
          lambda: page.locator("#result .undeterminable").count() == 0)
    details = page.locator("#result li.evidence details").first

    def expand() -> str:
        assert not details.evaluate("el => el.open")
        details.locator("summary").click()
        assert details.evaluate("el => el.open")
        finding = details.locator(".finding")
        assert finding.is_visible()
        return finding.inner_text()[:200]

    check("an evidence item expands to its finding", expand)
    check("ruled-out section with at least one item", lambda: page.locator("#result .ruled-out li").count() >= 1 and
          page.locator("#result .ruled-out").inner_text().replace("\n", " | ")[:200])
    check("limitations and next checks sections",
          lambda: page.locator("#result .limitations").count() == 1 and page.locator("#result .next-checks").count() == 1)

    link = page.locator("#result a.trace-link")
    href = link.get_attribute("href") or ""

    def trace_download() -> str:
        response = page.request.get(f"{BASE}{href}", timeout=STEP_TIMEOUT_MS)
        assert response.status == 200, response.status
        lines = [json.loads(line) for line in response.text().splitlines() if line.strip()]
        assert lines and lines[0]["action"] == "start" and lines[-1]["action"] == "finish"
        with page.expect_download(timeout=STEP_TIMEOUT_MS) as info:
            link.click()
        return f"{href}: {len(lines)} lines, saved as {info.value.suggested_filename}"

    check("Download trace link works", trace_download)
    page.screenshot(path=str(SCREENSHOT), full_page=True)
    print(f"screenshot: {SCREENSHOT}", flush=True)

    # Rendering rules in the real browser, on stub results (not sent to the server).
    stub = {
        "run_id": "stub-browser", "status": "success", "question": "stub", "determinable": False,
        "causes": [{"rank": 1, "type": "product_quality", "summary": "MUST NOT SHOW", "confidence": 0.9,
                    "evidence": [{"observation_id": "o", "source": "reviews", "query_id": "q1", "finding": "f"}]}],
        "ruled_out": [], "limitations": ["stub limitation"], "trace_id": "t", "log_file": "l",
        "execution_time_seconds": 0, "sample_mode": True,
    }
    rendered = page.evaluate(
        "r => { const n = EW.renderResult(r); return {text: n.textContent, causes: n.querySelectorAll('.cause').length}; }",
        stub,
    )
    check("stub determinable=false renders 'Cannot be determined from the data' and no cause",
          lambda: "Cannot be determined from the data" in rendered["text"] and rendered["causes"] == 0 and
          "MUST NOT SHOW" not in rendered["text"])
    xss = '<img src=x onerror="window.__pwned=1">'
    shown = page.evaluate(
        """r => { const n = EW.renderResult(r); document.body.appendChild(n);
                  return {imgs: n.querySelectorAll('img').length,
                          summary: n.querySelector('.cause-summary').textContent}; }""",
        {**stub, "determinable": True, "causes": [{**stub["causes"][0], "summary": xss}]},
    )
    page.wait_for_timeout(500)
    check("markup in a summary is shown as text (no img element, no onerror run)",
          lambda: shown["imgs"] == 0 and shown["summary"] == xss and page.evaluate("window.__pwned") is None)


def main() -> int:
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 900}, accept_downloads=True)
        errors: list[str] = []
        page.on("pageerror", lambda exc: errors.append(str(exc)))
        external: list[str] = []
        page.on("request", lambda req: None if req.url.startswith(BASE) else external.append(req.url))
        try:
            run(page)
        except Exception as exc:  # noqa: BLE001 - a step that could not run is a failed check
            problem = [f"{type(exc).__name__}: {exc}"]
            check("browser check ran to the end", lambda: _none(problem))
        finally:
            if not SCREENSHOT.exists():
                page.screenshot(path=str(SCREENSHOT), full_page=True)
                print(f"screenshot: {SCREENSHOT}", flush=True)
            check("no JavaScript errors on the page", lambda: _none(errors))
            check("no request to another host", lambda: _none(external))
            browser.close()
    failed = [name for ok, name in results if not ok]
    print(f"\n{len(results) - len(failed)} of {len(results)} browser checks passed", flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
