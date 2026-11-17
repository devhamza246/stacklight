import { act, cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";
import { ThemeProvider } from "./state/ThemeProvider";
import { PREFILLED_QUESTION } from "./state/useDemo";
import { FakeEventSource } from "./test/fakeEventSource";
import { CHUNK, DOCS, REFUND_APPROVAL } from "./test/fixtures";

const STATUS = { status: "ok", spend_today_usd: 0.19, cap_usd: 2, cost_known: true, resets_at: "2026-11-18T00:00:00+00:00", pending_runs: 0, documents: 84, kb_ready: true, kb_error: null };

interface Route { status?: number; body: unknown; headers?: Record<string, string> }
function mockApi(routes: Record<string, Route | ((init?: RequestInit) => Route)>) {
  const calls: { url: string; init?: RequestInit }[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    calls.push({ url, init });
    const key = Object.keys(routes).filter((k) => url.startsWith(k)).sort((a, b) => b.length - a.length)[0];
    const r0 = key ? routes[key] : { status: 404, body: { detail: "nope" } };
    const r = typeof r0 === "function" ? r0(init) : r0;
    return new Response(JSON.stringify(r.body), { status: r.status ?? 200, headers: { "Content-Type": "application/json", ...r.headers } });
  }));
  return calls;
}

const base = {
  "/api/status": { body: STATUS },
  "/api/approvals": { body: [] },
  "/api/documents": { body: DOCS },
  "/api/chunks/5": { body: CHUNK },
};

const mount = () => render(<ThemeProvider><App /></ThemeProvider>);

beforeEach(() => FakeEventSource.install());
afterEach(() => vi.unstubAllGlobals());

describe("App", () => {
  it("a failed first-start seed shows a calm setup-failed state and keeps the composer disabled", async () => {
    mockApi({ ...base, "/api/status": { body: { ...STATUS, documents: 40, kb_ready: false, kb_error: "Knowledge base setup failed. Restart the app to retry." } } });
    mount();
    const box = await screen.findByPlaceholderText("Knowledge base setup failed — restart to retry");
    expect(box).toBeDisabled();
    expect(screen.getByRole("status", { name: "Demo status" })).toHaveTextContent("Knowledge base setup failed — restart to retry");
    expect(screen.queryByText("Preparing the knowledge base…")).not.toBeInTheDocument();
  });

  it("while the knowledge base is being prepared the composer is disabled with calm copy, then enables", async () => {
    let ready = false;
    mockApi({ ...base, "/api/status": () => ({ body: { ...STATUS, documents: 0, kb_ready: ready } }) });
    mount();
    const box = await screen.findByPlaceholderText("Preparing the knowledge base…");
    expect(box).toBeDisabled();
    expect(screen.getByRole("status", { name: "Demo status" })).toHaveTextContent("Preparing the knowledge base…");
    expect(screen.getByRole("button", { name: "Ask" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Audit the knowledge base" })).toBeDisabled();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    ready = true;
    cleanup();
    mockApi({ ...base, "/api/status": () => ({ body: { ...STATUS, kb_ready: true } }) });
    mount();
    await waitFor(() => expect(screen.getByLabelText("Your question")).toBeEnabled());
  });

  it("first load: tagline, prefilled question, suggestion chips, empty trace and queue", async () => {
    mockApi(base);
    mount();
    expect(screen.getAllByText("AI team that answers from your docs, and keeps them current.").length).toBeGreaterThan(0);
    expect(screen.getByLabelText("Your question")).toHaveValue(PREFILLED_QUESTION);
    for (const chip of ["What’s our uptime SLA for Enterprise?", "How many API requests per minute on the Team plan?", "Audit the knowledge base"]) {
      expect(screen.getByRole("button", { name: chip })).toBeInTheDocument();
    }
    expect(await screen.findByText("Nothing waiting for review")).toBeInTheDocument();
    expect(await screen.findByText(/\$0\.19 of \$2\.00/)).toBeInTheDocument();
    expect(screen.getByRole("navigation", { name: "Sections" })).toBeInTheDocument();
  });

  it("ask flow: spans light up, verified shows before text, tokens stream, chips open the drawer, totals appear", async () => {
    const calls = mockApi({ ...base, "/api/chat": { status: 202, body: { run_id: "r1" } } });
    mount();
    await userEvent.click(screen.getByRole("button", { name: "Ask" }));
    const post = calls.find((c) => c.url === "/api/chat")!;
    expect(JSON.parse(post.init!.body as string)).toMatchObject({ message: PREFILLED_QUESTION, mode: "ask" });
    await waitFor(() => expect(FakeEventSource.instances).toHaveLength(1));
    const es = FakeEventSource.last;
    const span = (agent: string, status: string, n: number) => ({ type: "span", run_id: "r1", span_id: `${agent}${n}`, parent_id: null, agent, name: `${agent}.x`, status, cost_usd: 0.001, latency_ms: status === "started" ? null : 400, cost_known: true, input_tokens: 1, output_tokens: 1 });
    const trace = screen.getByTestId("trace");
    const statusOf = (name: string) => trace.querySelector(`[data-agent="${name}"]`)!.getAttribute("data-status");

    act(() => es.emit("span", span("retriever", "started", 1), 1));
    expect(statusOf("Retriever")).toBe("active");
    expect(statusOf("Answerer")).toBe("pending");
    expect(screen.getByText("Verifying sources…", { selector: ".badge" })).toBeInTheDocument();
    act(() => {
      es.emit("span", span("retriever", "ok", 1), 2);
      es.emit("span", span("answerer", "started", 2), 3);
    });
    expect(statusOf("Retriever")).toBe("done");
    expect(statusOf("Answerer")).toBe("active");
    act(() => {
      es.emit("span", span("answerer", "ok", 2), 4);
      es.emit("span", span("factchecker", "started", 3), 5);
    });
    expect(statusOf("Fact-checker")).toBe("active");

    act(() => {
      es.emit("span", span("factchecker", "ok", 3), 6);
      es.emit("verified", { type: "verified", faithfulness: 1, claims_supported: 2, claims_total: 2 }, 7);
    });
    expect(screen.getByText("Fact-checked · 2/2 claims supported")).toBeInTheDocument();
    expect(screen.getByTestId("answer-body")).toHaveTextContent("");
    act(() => {
      es.emit("token", { type: "token", text: "A P1 incident gets " }, 8);
      es.emit("token", { type: "token", text: "1 hour, 24/7." }, 9);
    });
    expect(screen.getByTestId("answer-body")).toHaveTextContent("A P1 incident gets 1 hour, 24/7.");
    expect(screen.getByTestId("answer-body")).toHaveAttribute("aria-live", "polite");
    act(() => {
      es.emit("citation", { type: "citation", chunk_id: 5, quote: "1 hour, 24/7", title: "SLA and Support Tiers", source: "corpus/handbook/sla-and-support-tiers.md" }, 10);
      es.emit("totals", { type: "totals", cost_usd: 0.0041, latency_ms: 3140, cost_known: true }, 11);
      es.emit("done", { type: "done", run_id: "r1" }, 12);
    });
    expect(screen.getAllByText("$0.004 · 3.1 s").length).toBeGreaterThan(0);
    const chip = within(screen.getByTestId("answer-body")).getByRole("button", { name: "Source 1: SLA and Support Tiers" });
    await userEvent.click(chip);
    expect(await screen.findByRole("dialog")).toBeInTheDocument();
    await waitFor(() => expect(document.querySelector("mark")).toHaveTextContent("1 hour, 24/7"));
    await userEvent.keyboard("{Escape}");
    expect(chip).toHaveFocus();
  });

  it("abstain run shows the not-sure state and no answer card", async () => {
    mockApi({ ...base, "/api/chat": { status: 202, body: { run_id: "r2" } } });
    mount();
    await userEvent.click(screen.getByRole("button", { name: "Ask" }));
    await waitFor(() => expect(FakeEventSource.instances).toHaveLength(1));
    act(() => {
      FakeEventSource.last.emit("abstain", { type: "abstain", reason: "not_in_kb", closest: [{ chunk_id: 5, title: "SLA", source: "s.md" }] }, 1);
      FakeEventSource.last.emit("done", { type: "done", run_id: "r2" }, 2);
    });
    expect(screen.getByRole("heading", { name: "I’m not sure" })).toBeInTheDocument();
    expect(screen.queryByLabelText("Answer")).toBeNull();
  });

  it("failed run keeps the trace and offers a retry", async () => {
    mockApi({ ...base, "/api/chat": { status: 202, body: { run_id: "r3" } } });
    mount();
    await userEvent.click(screen.getByRole("button", { name: "Ask" }));
    await waitFor(() => expect(FakeEventSource.instances).toHaveLength(1));
    act(() => FakeEventSource.last.emit("failed", { type: "failed", code: "llm_unavailable", message: "x" }, 1));
    expect(screen.getByRole("heading", { name: "The answer service isn’t responding" })).toBeInTheDocument();
    expect(screen.getByTestId("trace")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
  });

  it("audit flow: curate run queues a card that appears in the approval queue", async () => {
    let approvals: unknown[] = [];
    const calls = mockApi({
      ...base,
      "/api/curate": { status: 202, body: { run_id: "c1" } },
      "/api/approvals?status=pending": () => ({ body: approvals }),
    });
    mount();
    await userEvent.click(screen.getByRole("button", { name: "Audit the knowledge base" }));
    await waitFor(() => expect(FakeEventSource.instances).toHaveLength(1));
    expect(calls.some((c) => c.url === "/api/curate")).toBe(true);
    approvals = [REFUND_APPROVAL];
    act(() => {
      FakeEventSource.last.emit("finding", { type: "finding", kind: "conflict", summary: "[conflict:1-2] Refund window conflict", document_ids: [1, 2], approval_id: 7, needs_human_choice: false }, 1);
      FakeEventSource.last.emit("approval_proposed", { type: "approval_proposed", approval_id: 7, kind: "kb_change" }, 2);
    });
    expect(await screen.findByRole("button", { name: /Approve change/ })).toBeInTheDocument();
    expect(screen.getByLabelText("Knowledge base audit")).toHaveTextContent("Refund window conflict");
  });

  it("needs_human_choice findings are informational with no Approve", async () => {
    mockApi({ ...base, "/api/curate": { status: 202, body: { run_id: "c2" } } });
    mount();
    await userEvent.click(screen.getByRole("button", { name: "Audit the knowledge base" }));
    await waitFor(() => expect(FakeEventSource.instances).toHaveLength(1));
    act(() => {
      FakeEventSource.last.emit("finding", { type: "finding", kind: "conflict", summary: "Two docs disagree. No automatic edit proposed: unclear.", document_ids: [1, 2], approval_id: null, needs_human_choice: true }, 1);
      FakeEventSource.last.emit("done", { type: "done", run_id: "c2" }, 2);
    });
    const queue = screen.getByTestId("queue");
    expect(await within(queue).findByText(/No automatic fix/)).toBeInTheDocument();
    expect(within(queue).queryByRole("button", { name: /Approve/ })).toBeNull();
  });

  it("429 disables the composer with a countdown from retry_after_s", async () => {
    mockApi({ ...base, "/api/chat": { status: 429, body: { error: "busy", retry_after_s: 8 }, headers: { "Retry-After": "8" } } });
    mount();
    await userEvent.click(screen.getByRole("button", { name: "Ask" }));
    expect(await screen.findByText("Busy right now, try again in a few seconds")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Try again in [78] s/ })).toBeDisabled();
    expect(screen.getByLabelText("Your question")).toBeDisabled();
    expect(FakeEventSource.instances).toHaveLength(0);
  });

  it("429 busy on the audit action shows the busy notice and a countdown", async () => {
    mockApi({ ...base, "/api/curate": { status: 429, body: { error: "busy", retry_after_s: 15 }, headers: { "Retry-After": "15" } } });
    mount();
    await userEvent.click(screen.getByRole("button", { name: "Audit the knowledge base" }));
    expect(await screen.findByText("Busy right now, try again in a few seconds")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Try again in 1[45] s/ })).toBeDisabled();
    expect(FakeEventSource.instances).toHaveLength(0);
  });

  it("draft composer tells visitors drafts are public", async () => {
    mockApi({ ...base });
    mount();
    expect(screen.queryByTestId("draft-visibility")).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Draft reply mode" }));
    expect(screen.getByTestId("draft-visibility")).toHaveTextContent("Drafts are visible to all visitors of this demo");
  });

  it("503 demo_paused shows the paused banner, disables the composer, keeps trace and queue", async () => {
    mockApi({ ...base, "/api/chat": { status: 503, body: { status: "demo_paused", reason: "daily_budget", resets_at: "2026-11-18T00:00:00+00:00" } } });
    mount();
    await userEvent.click(screen.getByRole("button", { name: "Ask" }));
    expect(await screen.findByText("Demo paused: daily budget reached")).toBeInTheDocument();
    expect(screen.getByLabelText("Your question")).toBeDisabled();
    expect(screen.getByTestId("trace")).toBeInTheDocument();
    expect(screen.getByTestId("queue")).toBeInTheDocument();
  });

  it("503 resetting shows the refreshing notice and retries by itself", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    let n = 0;
    mockApi({
      ...base,
      "/api/chat": () => (++n === 1 ? { status: 503, body: { status: "resetting" }, headers: { "Retry-After": "2" } } : { status: 202, body: { run_id: "r9" } }),
    });
    mount();
    await userEvent.click(screen.getByRole("button", { name: "Ask" }));
    expect(await screen.findByText("Refreshing the demo data…")).toBeInTheDocument();
    await act(async () => { await vi.advanceTimersByTimeAsync(2500); });
    await waitFor(() => expect(FakeEventSource.instances).toHaveLength(1));
    expect(FakeEventSource.last.url).toBe("/api/runs/r9/events");
    vi.useRealTimers();
  });

  it("draft mode sends the ticket text and tone to /api/chat with mode draft", async () => {
    const calls = mockApi({ ...base, "/api/chat": { status: 202, body: { run_id: "d1" } } });
    mount();
    await userEvent.click(screen.getByRole("button", { name: "Draft reply mode" }));
    await userEvent.type(screen.getByLabelText("Customer ticket text"), "Our API keeps returning 429");
    await userEvent.selectOptions(screen.getByLabelText("Tone"), "sales");
    await userEvent.click(screen.getByRole("button", { name: "Draft reply" }));
    const post = calls.find((c) => c.url === "/api/chat")!;
    expect(JSON.parse(post.init!.body as string)).toEqual({ message: "Our API keeps returning 429", mode: "draft", tone: "sales" });
  });
});
