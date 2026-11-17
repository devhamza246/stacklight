import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { Banner } from "./Banner";

describe("Banner", () => {
  it("paused: calm copy with the reset time", () => {
    render(<Banner notice={{ kind: "paused", resetsAt: "2026-11-18T00:00:00+00:00" }} />);
    expect(screen.getByRole("status")).toHaveTextContent("Demo paused: daily budget reached");
    expect(screen.getByRole("status")).toHaveTextContent(/midnight UTC \(00:00 UTC/);
    expect(screen.getByRole("status")).toHaveTextContent("Nothing is broken");
  });

  it("busy: retry is disabled with a countdown, then enabled", () => {
    const { rerender } = render(<Banner notice={{ kind: "busy", secondsLeft: 7 }} onRetry={() => {}} />);
    expect(screen.getByRole("button", { name: "Try again in 7 s" })).toBeDisabled();
    rerender(<Banner notice={{ kind: "busy", secondsLeft: 0 }} onRetry={() => {}} />);
    expect(screen.getByRole("button", { name: "Try again" })).toBeEnabled();
  });

  it("rate limited: distinct copy", () => {
    render(<Banner notice={{ kind: "rate_limited", secondsLeft: 12 }} onRetry={() => {}} />);
    expect(screen.getByText("You’re going a little fast")).toBeInTheDocument();
  });

  it("resetting: refreshing notice", () => {
    render(<Banner notice={{ kind: "resetting" }} />);
    expect(screen.getByText("Refreshing the demo data…")).toBeInTheDocument();
  });

  it.each([
    ["llm_unavailable", "The answer service isn’t responding"],
    ["timeout", "This took too long, so I stopped it"],
    ["internal", "Something went wrong on our side"],
  ] as const)("failed %s has code-specific copy, a retry and a trace link", async (code, title) => {
    const onRetry = vi.fn();
    const onViewTrace = vi.fn();
    render(<Banner notice={{ kind: "failed", code }} onRetry={onRetry} onViewTrace={onViewTrace} footer="$0.0003 · 9.2 s" />);
    expect(screen.getByRole("heading", { name: title })).toBeInTheDocument();
    expect(screen.getByText(/Nothing was changed/)).toBeInTheDocument();
    expect(screen.getByText(code)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    await userEvent.click(screen.getByRole("button", { name: "View trace" }));
    expect(onRetry).toHaveBeenCalled();
    expect(onViewTrace).toHaveBeenCalled();
  });
});
