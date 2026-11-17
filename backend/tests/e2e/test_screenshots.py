"""Captures the real app into docs/ui/screens/ (desktop/mobile x light/dark). Only with E2E_SCREENSHOTS=1
(`make e2e-screens`); otherwise skipped so normal runs never rewrite tracked images."""
import os
import re

import pytest

from .conftest import DESKTOP, MOBILE

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(os.environ.get("E2E_SCREENSHOTS") != "1", reason="set E2E_SCREENSHOTS=1 (make e2e-screens)"),
]

VARIANTS = [("desktop", DESKTOP, "light"), ("desktop", DESKTOP, "dark"), ("mobile", MOBILE, "light"), ("mobile", MOBILE, "dark")]


def ask(page, text, wait_for):
    page.get_by_label("Your question").fill(text)
    page.get_by_role("button", name="Ask", exact=True).click()
    wait_for()


@pytest.mark.parametrize("device,viewport,theme", VARIANTS, ids=[f"{d}-{t}" for d, _, t in VARIANTS])
def test_capture_screens(server, paused_server, make_page, shot, device, viewport, theme):
    mobile = device == "mobile"
    server.reset()
    page = make_page(viewport, theme, reduced_motion="reduce")

    def tab(name):
        if mobile:
            page.get_by_role("navigation", name="Sections").get_by_role("button", name=re.compile(name)).click()

    # idle
    page.goto(server.url)
    page.get_by_text(re.compile(r"of \$1000\.00")).wait_for()
    page.get_by_text("Nothing waiting for review").wait_for(state="attached")
    shot(page, device, theme, "idle")
    if mobile:
        tab("Trace")
        shot(page, device, theme, "m-trace")
        tab("Chat")

    # answer, then the drawer
    ask(page, "What first-response time do we promise for a P1 incident on the Business plan?",
        lambda: page.locator(".answer-foot").wait_for(timeout=30_000))
    page.locator("button.cite").first.wait_for()
    shot(page, device, theme, "answer")
    page.get_by_role("button", name=re.compile(r"^Source 1")).first.click()
    page.get_by_role("dialog").locator("mark").first.wait_for()
    shot(page, device, theme, "answer-drawer")
    page.keyboard.press("Escape")
    if mobile:
        tab("Trace")
        shot(page, device, theme, "trace-done")
        tab("Chat")

    # audit -> approval diff -> resolved
    if mobile:
        tab("Queue")
    page.get_by_role("button", name="Run audit").click()
    card = page.locator('article[data-kind="conflict"]')
    card.wait_for(timeout=30_000)
    page.get_by_test_id("queue").locator('article[data-kind="stale"]').wait_for()
    page.wait_for_timeout(300)
    page.get_by_test_id("queue").evaluate("el => el.scrollIntoView({block: 'start'})")
    shot(page, device, theme, "approval-diff")
    card.get_by_role("button", name="Approve change").click()
    page.get_by_test_id("queue").locator(".receipt").wait_for()
    shot(page, device, theme, "approval-resolved")

    # abstain
    server.reset()
    page.goto(server.url)
    ask(page, "What is our equity refresh policy for senior engineers?",
        lambda: page.get_by_role("heading", name="I’m not sure").wait_for())
    shot(page, device, theme, "abstain")

    # failed (trace kept)
    server.reset()
    page.goto(server.url)
    ask(page, "Tell me about the outage policy",
        lambda: page.get_by_role("heading", name="The answer service isn’t responding").wait_for(timeout=30_000))
    shot(page, device, theme, "failed")

    # paused
    page.goto(paused_server.url)
    page.get_by_text("Demo paused: daily budget reached").wait_for()
    shot(page, device, theme, "paused")
