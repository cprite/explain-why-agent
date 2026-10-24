"""The web page (Sprint 13b): served at /, no other host, data inserted as text only.

The render rules themselves (undeterminable result, markup as text, card fields) are checked in
node by tests/web/render_check.js, which this module runs; the browser check in CI
(eval/browser_check.py) drives the same page in headless Chromium.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from html.parser import HTMLParser
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.api.main as api
from app.config import Settings

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
URL_RE = re.compile(r"https?://", re.IGNORECASE)


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    for key in Settings.model_fields:
        monkeypatch.delenv(key.upper(), raising=False)
    monkeypatch.setenv("LOG_DIR", str(tmp_path / "logs"))
    return TestClient(api.app)


class _Refs(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.refs: list[str] = []
        self.inline_scripts = 0
        self._in_script = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        for name, value in attrs:
            if name in {"src", "href", "action", "srcset", "poster", "data"} and value is not None:
                self.refs.append(value)
            assert not name.startswith("on"), f"inline event handler {name} on <{tag}>"
        self._in_script = tag == "script"

    def handle_data(self, data: str) -> None:
        if self._in_script and data.strip():
            self.inline_scripts += 1

    def handle_endtag(self, tag: str) -> None:
        self._in_script = False


def test_get_root_serves_the_page_and_its_assets(client: TestClient) -> None:
    page = client.get("/")
    assert page.status_code == 200
    assert page.headers["content-type"].startswith("text/html")
    for marker in ('id="top-cards"', 'id="tiles"', 'id="question"', 'id="ask"', 'id="result"',
                   'src="/web/app.js"', 'href="/web/style.css"'):
        assert marker in page.text
    script = client.get("/web/app.js")
    assert script.status_code == 200 and "javascript" in script.headers["content-type"]
    assert script.text == (WEB / "app.js").read_text(encoding="utf-8")
    style = client.get("/web/style.css")
    assert style.status_code == 200 and style.headers["content-type"].startswith("text/css")


def test_page_carries_the_api_run_timeout(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    assert '<meta name="run-timeout-seconds" content="600">' in client.get("/").text
    monkeypatch.setenv("API_RUN_TIMEOUT_SECONDS", "42.5")
    assert '<meta name="run-timeout-seconds" content="42.5">' in client.get("/").text


def test_web_folder_holds_only_the_three_files() -> None:
    assert sorted(p.name for p in WEB.iterdir() if p.name != ".gitkeep") == ["app.js", "index.html", "style.css"]


@pytest.mark.parametrize("name", ["index.html", "app.js", "style.css"])
def test_no_other_host_is_referenced(name: str) -> None:
    text = (WEB / name).read_text(encoding="utf-8")
    assert not URL_RE.search(text), f"{name} references another host: {URL_RE.search(text)}"
    assert "@import" not in text and "url(" not in text


def test_html_references_are_same_origin_paths() -> None:
    parser = _Refs()
    parser.feed((WEB / "index.html").read_text(encoding="utf-8"))
    assert parser.refs == ["/web/style.css", "/web/app.js"]
    assert all(ref.startswith("/") and not ref.startswith("//") for ref in parser.refs)
    assert parser.inline_scripts == 0


def test_js_fetches_only_same_origin_paths() -> None:
    script = (WEB / "app.js").read_text(encoding="utf-8")
    targets = re.findall(r"requestJson\(\s*([`'\"][^`'\"]*)", script)
    assert targets, "expected requestJson calls"
    assert all(t[1:].startswith("/") and not t[1:].startswith("//") for t in targets), targets
    assert "fetch(url" in script and script.count("fetch(") == 1, "all requests go through requestJson"


def test_js_never_builds_markup_from_strings() -> None:
    script = (WEB / "app.js").read_text(encoding="utf-8")
    for banned in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", "new Function"):
        assert banned not in script, banned


def test_render_rules_in_node() -> None:
    node = shutil.which("node")
    if node is None:
        if os.environ.get("CI"):
            pytest.fail("node is required in CI for the render checks")
        pytest.skip("node is not installed; CI runs this check")
    done = subprocess.run([node, str(ROOT / "tests" / "web" / "render_check.js")], capture_output=True,
                          text=True, timeout=60, check=False)
    print(done.stdout)
    assert done.returncode == 0, done.stdout + done.stderr
    assert "PASS undeterminable result says so and shows no cause" in done.stdout
    assert "PASS markup in result fields is inserted as text" in done.stdout
    assert "ALL RENDER CHECKS PASSED" in done.stdout
