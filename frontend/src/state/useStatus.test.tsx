import { act, render, renderHook, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { STATUS_POLL_MS, STATUS_PREPARING_POLL_MS, useStatus } from "./useStatus";
import { StatusPill } from "../components/StatusPill";
import type { StatusInfo } from "../api/types";

const info: StatusInfo = { status: "ok", spend_today_usd: 0.19, cap_usd: 2, cost_known: true, resets_at: "2026-11-18T00:00:00+00:00", pending_runs: 0, documents: 84, kb_ready: true, kb_error: null };

function setHidden(hidden: boolean) {
  Object.defineProperty(document, "hidden", { configurable: true, get: () => hidden });
  document.dispatchEvent(new Event("visibilitychange"));
}

beforeEach(() => vi.useFakeTimers());
afterEach(() => { vi.useRealTimers(); setHidden(false); });

describe("useStatus polling", () => {
  it("fetches once on load, then once per 30 s, never in a tight loop", async () => {
    const fetchStatus = vi.fn().mockResolvedValue(info);
    renderHook(() => useStatus(fetchStatus));
    await act(async () => { await vi.advanceTimersByTimeAsync(0); });
    expect(fetchStatus).toHaveBeenCalledTimes(1);
    await act(async () => { await vi.advanceTimersByTimeAsync(STATUS_POLL_MS - 1000); });
    expect(fetchStatus).toHaveBeenCalledTimes(1);
    await act(async () => { await vi.advanceTimersByTimeAsync(1000); });
    expect(fetchStatus).toHaveBeenCalledTimes(2);
    await act(async () => { await vi.advanceTimersByTimeAsync(STATUS_POLL_MS * 2); });
    expect(fetchStatus).toHaveBeenCalledTimes(4);
  });

  it("does not poll while the tab is hidden and catches up when it is visible again", async () => {
    const fetchStatus = vi.fn().mockResolvedValue(info);
    renderHook(() => useStatus(fetchStatus));
    await act(async () => { await vi.advanceTimersByTimeAsync(0); });
    act(() => setHidden(true));
    await act(async () => { await vi.advanceTimersByTimeAsync(STATUS_POLL_MS * 5); });
    expect(fetchStatus).toHaveBeenCalledTimes(1);
    await act(async () => { setHidden(false); await vi.advanceTimersByTimeAsync(0); });
    expect(fetchStatus).toHaveBeenCalledTimes(2);
  });

  it("polls every few seconds while the knowledge base is preparing, then returns to 30 s", async () => {
    const fetchStatus = vi.fn()
      .mockResolvedValueOnce({ ...info, kb_ready: false })
      .mockResolvedValue(info);
    renderHook(() => useStatus(fetchStatus));
    await act(async () => { await vi.advanceTimersByTimeAsync(0); });
    await act(async () => { await vi.advanceTimersByTimeAsync(STATUS_PREPARING_POLL_MS); });
    expect(fetchStatus).toHaveBeenCalledTimes(2);
    await act(async () => { await vi.advanceTimersByTimeAsync(STATUS_PREPARING_POLL_MS * 2); });
    expect(fetchStatus).toHaveBeenCalledTimes(2);
  });

  it("refresh() fetches on demand and overlapping refreshes collapse into one request", async () => {
    let resolve!: (i: StatusInfo) => void;
    const fetchStatus = vi.fn()
      .mockResolvedValueOnce(info)
      .mockReturnValueOnce(new Promise<StatusInfo>((r) => { resolve = r; }));
    const { result } = renderHook(() => useStatus(fetchStatus));
    await act(async () => { await vi.advanceTimersByTimeAsync(0); });
    act(() => { result.current.refresh(); result.current.refresh(); });
    expect(fetchStatus).toHaveBeenCalledTimes(2);
    await act(async () => { resolve(info); });
  });

  it("stops polling on unmount", async () => {
    const fetchStatus = vi.fn().mockResolvedValue(info);
    const { unmount } = renderHook(() => useStatus(fetchStatus));
    await act(async () => { await vi.advanceTimersByTimeAsync(0); });
    unmount();
    await act(async () => { await vi.advanceTimersByTimeAsync(STATUS_POLL_MS * 3); });
    expect(fetchStatus).toHaveBeenCalledTimes(1);
  });
});

describe("StatusPill", () => {
  it("shows live spend, the paused state, and an unavailable fallback", () => {
    const { rerender } = render(<StatusPill info={info} error={false} />);
    expect(screen.getByRole("status")).toHaveTextContent("Live demo");
    expect(screen.getByRole("status")).toHaveTextContent("$0.19 of $2.00");
    rerender(<StatusPill info={{ ...info, status: "demo_paused", spend_today_usd: 2 }} error={false} />);
    expect(screen.getByRole("status")).toHaveTextContent("Demo paused");
    rerender(<StatusPill info={null} error />);
    expect(screen.getByRole("status")).toHaveTextContent("Status unavailable");
  });
});
