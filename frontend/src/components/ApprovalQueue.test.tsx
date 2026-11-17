import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ApprovalQueue } from "./ApprovalQueue";
import { ApiError } from "../api/client";
import type { Approval } from "../api/types";
import { useApprovals } from "../state/useApprovals";
import { DOCS, REFUND_APPROVAL, REPLY_APPROVAL, STALE_APPROVAL } from "../test/fixtures";

vi.mock("../state/useDocs", async (orig) => {
  const mod = await orig<typeof import("../state/useDocs")>();
  return { ...mod, useDocs: (ids: number[]) => mod.useDocs(ids, async () => DOCS) };
});

type Client = Parameters<typeof useApprovals>[0];
function Harness({ client }: { client: Client }) {
  const approvals = useApprovals(client);
  return <ApprovalQueue approvals={approvals} newIds={new Set()} needsHuman={[]} onOpenSource={() => {}} />;
}
const clientWith = (list: Approval[], decide = vi.fn()) =>
  ({ approvals: vi.fn().mockResolvedValue(list), decide }) as unknown as Client & { decide: ReturnType<typeof vi.fn> };

describe("ApprovalQueue cards", () => {
  it("renders a conflict as a diff with bold runs, the gate line and scope", async () => {
    render(<Harness client={clientWith([REFUND_APPROVAL])} />);
    expect(await screen.findByText(/Two documents disagree/)).toBeInTheDocument();
    const fix = await screen.findByRole("group", { name: /Proposed fix in billing-faq.md/ });
    expect(within(fix).getAllByText("Refund window:").every((n) => n.tagName === "STRONG")).toBe(true);
    expect(fix.textContent).not.toContain("**");
    expect(screen.getByText(/Needs your approval/)).toBeInTheDocument();
    expect(screen.getByText(/replace_all/)).toHaveTextContent("replace_all");
    expect(screen.getByRole("button", { name: /Approve change/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Reject" })).toBeInTheDocument();
  });

  it("makes replace_all=true visible", async () => {
    const a = structuredClone(REFUND_APPROVAL);
    (a.payload as { change: { replace_all: boolean } }).change.replace_all = true;
    render(<Harness client={clientWith([a])} />);
    expect(await screen.findByText(/replace_all ON/)).toBeInTheDocument();
  });

  it("renders archive and supersede variants", async () => {
    const sup = structuredClone(STALE_APPROVAL);
    sup.id = 10;
    (sup.payload as { change: unknown }).change = { type: "supersede", superseded_by_document_id: 1 };
    render(<Harness client={clientWith([STALE_APPROVAL, sup])} />);
    expect(await screen.findByRole("button", { name: "Approve archive" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Approve supersede" })).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "Keep it" })).toHaveLength(2);
  });

  it("renders a reply draft with the simulated-send line", async () => {
    render(<Harness client={clientWith([REPLY_APPROVAL])} />);
    expect(await screen.findByText(/Simulated send. Nothing leaves the system/)).toBeInTheDocument();
    expect(screen.getByText(/300 requests per minute\./)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Approve and mark sent/ })).toBeInTheDocument();
  });

  it("falls back to a generic card for unknown kinds", async () => {
    const odd: Approval = { ...REFUND_APPROVAL, id: 11, kind: "mystery", payload: { a: 1 } };
    render(<Harness client={clientWith([odd])} />);
    expect(await screen.findByText("Proposal #11")).toBeInTheDocument();
  });

  it("shows the empty state when nothing is pending", async () => {
    render(<Harness client={clientWith([])} />);
    expect(await screen.findByText("Nothing waiting for review")).toBeInTheDocument();
  });

  it("renders LLM-authored text as literal text, never as HTML", async () => {
    const evil = "<img src=x onerror=alert(1)> and <script>alert(2)</script>";
    const a = structuredClone(REFUND_APPROVAL);
    Object.assign(a.payload, { finding_summary: `[conflict:1-2] ${evil}` });
    (a.payload as { change: { find: string; replace: string } }).change.find = evil;
    const r = structuredClone(REPLY_APPROVAL);
    Object.assign(r.payload, { body: evil, subject: evil });
    const { container } = render(<Harness client={clientWith([a, r])} />);
    await screen.findByText(/Simulated send/);
    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector("script")).toBeNull();
    expect(container.textContent).toContain("<img src=x onerror=alert(1)>");
  });
});

describe("approval decisions", () => {
  it("sends one request on a double click and disables the buttons while in flight", async () => {
    let finish!: (a: Approval) => void;
    const decide = vi.fn().mockReturnValue(new Promise<Approval>((res) => { finish = res; }));
    render(<Harness client={clientWith([REFUND_APPROVAL], decide)} />);
    const approve = await screen.findByRole("button", { name: /Approve change/ });
    await userEvent.dblClick(approve);
    expect(decide).toHaveBeenCalledTimes(1);
    expect(decide).toHaveBeenCalledWith(7, true);
    expect(screen.getByRole("button", { name: /Applying/ })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Reject" })).toBeDisabled();
    finish({ ...REFUND_APPROVAL, status: "approved" });
    expect(await screen.findByText(/Approved\. billing-faq\.md was updated/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Approve change/ })).toBeNull();
  });

  it("rejects with the reject button", async () => {
    const decide = vi.fn().mockResolvedValue({ ...REFUND_APPROVAL, status: "rejected" });
    render(<Harness client={clientWith([REFUND_APPROVAL], decide)} />);
    await userEvent.click(await screen.findByRole("button", { name: "Reject" }));
    expect(decide).toHaveBeenCalledWith(7, false);
    expect(await screen.findByText(/Rejected\. Nothing was changed/)).toBeInTheDocument();
  });

  it("treats 409 (already decided) as an idempotent success", async () => {
    const decide = vi.fn().mockRejectedValue(new ApiError("conflict", 409, "already approved"));
    const client = clientWith([REFUND_APPROVAL], decide);
    (client.approvals as ReturnType<typeof vi.fn>).mockImplementation(async (s: string) =>
      s === "all" ? [{ ...REFUND_APPROVAL, status: "approved" }] : [REFUND_APPROVAL]);
    render(<Harness client={client} />);
    await userEvent.click(await screen.findByRole("button", { name: /Approve change/ }));
    expect(await screen.findByText(/already decided/)).toBeInTheDocument();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("shows an inline message on 404, 422 and 429 and keeps the card", async () => {
    const decide = vi.fn()
      .mockRejectedValueOnce(new ApiError("not_found", 404, "unknown approval"))
      .mockRejectedValueOnce(new ApiError("unprocessable", 422, "text not found"))
      .mockRejectedValueOnce(new ApiError("rate_limited", 429, "slow down", 30));
    render(<Harness client={clientWith([REFUND_APPROVAL], decide)} />);
    const approve = await screen.findByRole("button", { name: /Approve change/ });
    await userEvent.click(approve);
    expect(await screen.findByRole("alert")).toHaveTextContent(/no longer exists/);
    await userEvent.click(screen.getByRole("button", { name: /Approve change/ }));
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent(/could not be applied/));
    await userEvent.click(screen.getByRole("button", { name: /Approve change/ }));
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent(/Try again in 30 s/));
    expect(screen.getByRole("button", { name: /Approve change/ })).toBeDisabled();
  });

  it("treats 503 resetting as a calm retryable state and keeps the card", async () => {
    const decide = vi.fn().mockRejectedValueOnce(new ApiError("resetting", 503, "Resetting", 5));
    render(<Harness client={clientWith([REFUND_APPROVAL], decide)} />);
    await userEvent.click(await screen.findByRole("button", { name: /Approve change/ }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/refreshing its data. Try again in 5 s/);
    expect(screen.getByRole("button", { name: /Approve change/ })).toBeDisabled();
  });
});
