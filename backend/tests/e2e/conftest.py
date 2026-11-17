"""Fixtures for the browser end-to-end tests (Playwright + Chromium, real app, stubbed LLM).

Servers are real subprocesses of tests/e2e/server.py, each with its own throwaway database.
Needs the built frontend (`make web-build`) and the dev Postgres (`make dev-db`).
Set E2E_SCREENSHOTS=1 to (re)write docs/ui/screens/*.png from the screenshot test.
"""
import os
import socket
import subprocess
import sys
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path

import pytest

playwright_sync = pytest.importorskip("playwright.sync_api", reason="pip install playwright && playwright install chromium")

BACKEND = Path(__file__).resolve().parents[2]
ROOT = BACKEND.parent
DIST = ROOT / "frontend" / "dist"
SCREENS = ROOT / "docs" / "ui" / "screens"

DESKTOP = {"width": 1440, "height": 900}
MOBILE = {"width": 390, "height": 844}


@dataclass
class Server:
    url: str
    proc: subprocess.Popen

    def reset(self) -> None:
        req = urllib.request.Request(f"{self.url}/__e2e/reset", method="POST")
        urllib.request.urlopen(req, timeout=60).read()

    def get_json(self, path: str):
        import json

        return json.load(urllib.request.urlopen(f"{self.url}{path}", timeout=10))


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _start(db: str, **env) -> Server:
    if not (DIST / "index.html").exists():
        pytest.fail("frontend/dist is missing: run `make web-build` (or `make e2e`)")
    port = _free_port()
    # tests/conftest.py exports a huge DAILY_SPEND_CAP_USD for the unit suite; the e2e server sets its own.
    full_env = {**os.environ, "DAILY_SPEND_CAP_USD": "1000", "E2E_PORT": str(port), "E2E_DB": db,
                "PYTHONPATH": str(BACKEND), **{k: str(v) for k, v in env.items()}}
    proc = subprocess.Popen([sys.executable, "-m", "tests.e2e.server"], cwd=BACKEND, env=full_env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    url = f"http://127.0.0.1:{port}"
    deadline = time.time() + 120
    while time.time() < deadline:
        if proc.poll() is not None:
            pytest.fail(f"e2e server exited early:\n{proc.stdout.read()}")
        try:
            urllib.request.urlopen(f"{url}/health", timeout=1)
            return Server(url, proc)
        except OSError:
            time.sleep(0.5)
    proc.kill()
    pytest.fail("e2e server did not start in 120 s")


@pytest.fixture(scope="session")
def server():
    s = _start("stacklight_e2e_main")
    yield s
    s.proc.terminate()
    s.proc.wait(timeout=20)


@pytest.fixture(scope="session")
def paused_server():
    """Daily spend cap of $0: the demo is paused from the first request."""
    s = _start("stacklight_e2e_paused", DAILY_SPEND_CAP_USD="0")
    yield s
    s.proc.terminate()
    s.proc.wait(timeout=20)


@pytest.fixture(scope="session")
def browser():
    with playwright_sync.sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


@pytest.fixture
def make_page(browser):
    contexts = []

    def make(viewport=DESKTOP, scheme="light", reduced_motion="no-preference"):
        ctx = browser.new_context(viewport=viewport, color_scheme=scheme, reduced_motion=reduced_motion,
                                  is_mobile=viewport["width"] < 700, has_touch=viewport["width"] < 700,
                                  device_scale_factor=1)
        contexts.append(ctx)
        page = ctx.new_page()
        page.set_default_timeout(15_000)
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        page.errors = errors  # type: ignore[attr-defined]
        return page

    yield make
    for c in contexts:
        c.close()


@pytest.fixture
def shot():
    """shot(page, device, theme, name): writes docs/ui/screens/{device}-{theme}-{name}.png when E2E_SCREENSHOTS=1."""

    def take(page, device, theme, name):
        if os.environ.get("E2E_SCREENSHOTS") != "1":
            return
        SCREENS.mkdir(parents=True, exist_ok=True)
        page.wait_for_timeout(450)  # let slide-in / sheet animations settle
        page.screenshot(path=str(SCREENS / f"{device}-{theme}-{name}.png"))

    return take
