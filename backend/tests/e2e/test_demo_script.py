"""The 30-second demo script, in a real browser against the real app (stubbed LLM).

Run with `make e2e` (excluded from the default suite).
"""
import re

import pytest

from .conftest import DESKTOP, MOBILE

pytestmark = pytest.mark.e2e

TAGLINE = "AI team that answers from your docs, and keeps them current."
QUESTION = "What first-response time do we promise for a P1 incident on the Business plan?"

# Records every transition of a trace node to "active", in order, as it happens in the page.
TRACE_RECORDER = """
window.__lit = [];
new MutationObserver((muts) => {
  for (const m of muts) {
    const el = m.target;
    if (el.dataset && el.dataset.agent && el.dataset.status === 'active') window.__lit.push(el.dataset.agent);
  }
}).observe(document, {subtree: true, attributes: true, attributeFilter: ['data-status']});
"""


def trace_status(page, agent):
    return page.locator(f'[data-testid="trace"] [data-agent="{agent}"]').get_attribute("data-status")


def test_demo_script_runs_end_to_end(server, make_page, shot):
    server.reset()
    page = make_page(DESKTOP, "light")
    page.add_init_script(TRACE_RECORDER)
    page.goto(server.url)

    # First load: tagline, the real question prefilled, chips, empty trace and queue.
    assert page.locator(".tagline").inner_text() == TAGLINE
    assert page.get_by_label("Your question").input_value() == QUESTION
    for chip in ("What’s our uptime SLA for Enterprise?", "How many API requests per minute on the Team plan?", "Audit the knowledge base"):
        assert page.get_by_role("button", name=chip).is_visible()
    assert page.get_by_text("Nothing waiting for review").is_visible()
    page.get_by_text(re.compile(r"\$\d+\.\d\d of \$1000\.00")).wait_for()
    assert trace_status(page, "Retriever") == "pending"
    shot(page, "desktop", "light", "idle")

    # Ask. The trace lights up Retriever -> Answerer -> Fact-checker.
    page.get_by_role("button", name="Ask", exact=True).click()
    badge = page.locator(".answer-head .badge")
    badge.get_by_text("Verifying sources…").wait_for()
    assert page.locator(".skeleton").is_visible()  # nothing streams before the check
    assert page.get_by_test_id("answer-body").inner_text().strip() == "Verifying sources…"

    # The Verified badge with real counts arrives BEFORE the text has finished streaming.
    page.get_by_text("Fact-checked · 2/2 claims supported").wait_for()
    early = page.get_by_test_id("answer-body").inner_text()
    assert "4 business hours." not in early, early

    page.locator("button.cite").first.wait_for()  # citations land after the text
    body = page.get_by_test_id("answer-body").inner_text()
    assert "1 hour, 24/7" in body and "4 business hours." in body

    lit = page.evaluate("window.__lit")
    wanted = [a for a in lit if a in ("Retriever", "Answerer", "Fact-checker")]
    assert wanted[:3] == ["Retriever", "Answerer", "Fact-checker"], lit
    for agent in ("Orchestrator", "Retriever", "Answerer", "Fact-checker"):
        assert trace_status(page, agent) == "done"

    # Totals chip shows cost and latency.
    page.get_by_test_id("totals").get_by_text(re.compile(r"^\$\d\.\d{3} · \d+\.\d s$")).wait_for()
    assert page.locator(".answer-foot").get_by_text(re.compile(r"^\$\d\.\d{3} · \d+\.\d s$")).is_visible()

    # Citation chip opens the drawer with the quoted sentence highlighted in the passage.
    chip = page.get_by_role("button", name=re.compile(r"^Source 1: SLA and Support Tiers"))
    chip.click()
    dialog = page.get_by_role("dialog")
    dialog.wait_for()
    assert dialog.get_attribute("aria-modal") == "true"
    mark = dialog.locator("mark")
    mark.first.wait_for()
    assert "1 hour, 24/7" in " ".join(mark.all_inner_texts())
    assert "Business" in dialog.locator("tr.cited").inner_text()
    assert "handbook/sla-and-support-tiers.md" in dialog.inner_text()
    shot(page, "desktop", "light", "answer-drawer")
    page.keyboard.press("Escape")
    dialog.wait_for(state="hidden")
    assert chip.evaluate("el => el === document.activeElement")
    shot(page, "desktop", "light", "answer")

    # Audit the knowledge base: the refund conflict arrives as a card with Approve.
    page.get_by_role("button", name="Run audit").click()
    queue = page.get_by_test_id("queue")
    card = queue.locator('article[data-kind="conflict"]')
    card.wait_for(timeout=30_000)
    assert "refund" in card.inner_text().lower()
    assert card.get_by_role("button", name="Approve change").is_visible()
    assert "replace_all" in card.inner_text()
    assert "**" not in card.locator(".fix").inner_text()  # bold rendered, not raw asterisks
    assert page.get_by_label("Knowledge base audit").is_visible()
    page.wait_for_selector('[data-testid="trace"] [data-agent="Curator"][data-status="done"]')
    shot(page, "desktop", "light", "approval-diff")

    # Approve applies it and the card resolves to a receipt.
    card.get_by_role("button", name="Approve change").click()
    receipt = queue.locator(".receipt")
    receipt.wait_for()
    assert "Approved" in receipt.inner_text() and "billing-faq.md" in receipt.inner_text()
    assert queue.locator('article[data-kind="conflict"]').count() == 0
    applied = server.get_json("/api/approvals?status=approved")
    assert len(applied) == 1 and applied[0]["applied_at"] is not None
    assert page.errors == []


def test_audit_chip_from_idle(server, make_page):
    server.reset()
    page = make_page(DESKTOP, "light")
    page.goto(server.url)
    page.get_by_role("button", name="Audit the knowledge base").click()
    queue = page.get_by_test_id("queue")
    queue.locator('article[data-kind="conflict"]').wait_for(timeout=30_000)
    queue.locator('article[data-kind="stale"]').wait_for()
    assert page.get_by_role("button", name="Approve archive").is_visible()
    assert page.errors == []


def test_abstain_scenario(server, make_page, shot):
    server.reset()
    page = make_page(DESKTOP, "light")
    page.goto(server.url)
    box = page.get_by_label("Your question")
    box.fill("What is our equity refresh policy for senior engineers?")
    page.get_by_role("button", name="Ask", exact=True).click()
    page.get_by_role("heading", name="I’m not sure").wait_for()
    assert page.get_by_text("Closest sources, none of them answer it").is_visible()
    assert page.get_by_text(re.compile("ask a human", re.I)).count() == 0
    assert page.get_by_label("Answer").count() == 0
    assert trace_status(page, "Answerer") == "warn"
    assert trace_status(page, "Fact-checker") == "skipped"
    shot(page, "desktop", "light", "abstain")
    assert page.errors == []


def test_failed_scenario(server, make_page, shot):
    server.reset()
    page = make_page(DESKTOP, "light")
    page.goto(server.url)
    page.get_by_label("Your question").fill("Tell me about the outage policy")
    page.get_by_role("button", name="Ask", exact=True).click()
    page.get_by_role("heading", name="The answer service isn’t responding").wait_for(timeout=30_000)
    assert page.get_by_role("button", name="Try again").is_visible()
    assert trace_status(page, "Retriever") == "done"  # trace kept
    assert trace_status(page, "Answerer") == "error"
    shot(page, "desktop", "light", "failed")


def test_paused_scenario(paused_server, make_page, shot):
    page = make_page(DESKTOP, "light")
    page.goto(paused_server.url)
    page.get_by_text("Demo paused: daily budget reached").wait_for()
    assert "Demo paused" in page.get_by_role("status", name="Demo status").inner_text()
    assert page.get_by_label("Your question").is_disabled()
    assert page.get_by_test_id("trace").is_visible() and page.get_by_test_id("queue").is_visible()
    shot(page, "desktop", "light", "paused")


def test_mobile_layout_and_tab_bar(server, make_page, shot):
    server.reset()
    page = make_page(MOBILE, "light")
    page.goto(server.url)
    nav = page.get_by_role("navigation", name="Sections")
    nav.wait_for()
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    for b in nav.get_by_role("button").all():
        assert b.bounding_box()["height"] >= 40
    shot(page, "mobile", "light", "idle")

    page.get_by_role("button", name="Ask", exact=True).click()
    page.get_by_role("button", name=re.compile(r"^Source 1")).first.wait_for(timeout=30_000)
    page.get_by_test_id("totals").wait_for(state="attached")
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    # The sticky composer never covers the last piece of content.
    last = page.locator(".answer-foot").bounding_box()
    dock = page.locator(".dock").bounding_box()
    assert last["y"] + last["height"] <= dock["y"] + 1
    assert dock["y"] + dock["height"] <= nav.bounding_box()["y"] + 1
    shot(page, "mobile", "light", "answer")

    # Tab bar: Trace and Queue replace the chat, and Chat brings it back.
    nav.get_by_role("button", name="Trace").click()
    assert page.get_by_test_id("trace").is_visible() and not page.locator("main").is_visible()
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    nav.get_by_role("button", name="Queue").click()
    assert page.get_by_test_id("queue").is_visible()
    nav.get_by_role("button", name="Chat").click()
    assert page.locator("main").is_visible()
    assert page.errors == []


def test_mobile_audit_queue_badge(server, make_page, shot):
    server.reset()
    page = make_page(MOBILE, "light")
    page.goto(server.url)
    page.get_by_role("button", name="Audit the knowledge base").click()
    page.locator(".tab .count").wait_for(timeout=30_000)
    nav = page.get_by_role("navigation", name="Sections")
    nav.get_by_role("button", name=re.compile("Queue")).click()
    card = page.locator('article[data-kind="conflict"]')
    card.wait_for()
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    assert card.get_by_role("button", name="Approve change").bounding_box()["height"] >= 40
    shot(page, "mobile", "light", "approval-diff")
    assert page.errors == []
