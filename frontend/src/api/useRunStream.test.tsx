import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useRunStream } from "./useRunStream";
import { FakeEventSource } from "../test/fakeEventSource";

const meta = { question: "q", mode: "ask" as const };

beforeEach(() => {
  vi.useFakeTimers();
  FakeEventSource.install();
});
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("useRunStream", () => {
  it("opens nothing without a run id", () => {
    const { result } = renderHook(() => useRunStream(null, meta));
    expect(FakeEventSource.instances).toHaveLength(0);
    expect(result.current.phase).toBe("idle");
  });

  it("subscribes, reduces events in order and closes on done", () => {
    const { result } = renderHook(() => useRunStream("run-1", meta));
    const es = FakeEventSource.last;
    expect(es.url).toBe("/api/runs/run-1/events");
    act(() => {
      es.emit("verified", { type: "verified", faithfulness: 1, claims_supported: 2, claims_total: 3 }, 1);
      es.emit("token", { type: "token", text: "Hi " }, 2);
      es.emit("token", { type: "token", text: "there" }, 3);
    });
    expect(result.current.verified?.claims_supported).toBe(2);
    expect(result.current.text).toBe("Hi there");
    expect(es.closed).toBe(false);
    act(() => es.emit("done", { type: "done", run_id: "run-1" }, 4));
    expect(result.current.phase).toBe("done");
    expect(es.closed).toBe(true);
  });

  it("surfaces failed codes and closes the stream", () => {
    const { result } = renderHook(() => useRunStream("r", meta));
    act(() => FakeEventSource.last.emit("failed", { type: "failed", code: "timeout", message: "x" }, 1));
    expect(result.current.failed?.code).toBe("timeout");
    expect(FakeEventSource.last.closed).toBe(true);
  });

  it("lets the browser retry transient errors without opening a second stream", () => {
    renderHook(() => useRunStream("r", meta));
    act(() => FakeEventSource.last.fail(false));
    act(() => { vi.advanceTimersByTime(5000); });
    expect(FakeEventSource.instances).toHaveLength(1);
  });

  it("reconnects after a fatal error and ignores replayed events (resume)", () => {
    const { result } = renderHook(() => useRunStream("r", meta));
    const first = FakeEventSource.last;
    act(() => {
      first.emit("token", { type: "token", text: "a" }, 1);
      first.emit("token", { type: "token", text: "b" }, 2);
      first.fail(true);
    });
    act(() => { vi.advanceTimersByTime(1000); });
    expect(FakeEventSource.instances).toHaveLength(2);
    const second = FakeEventSource.last;
    act(() => {
      second.emit("token", { type: "token", text: "a" }, 1); // replay
      second.emit("token", { type: "token", text: "b" }, 2); // replay
      second.emit("token", { type: "token", text: "c" }, 3);
    });
    expect(result.current.text).toBe("abc");
    expect(result.current.lastEventId).toBe(3);
  });

  it("gives up after repeated fatal errors with a connection-lost failure", () => {
    const { result } = renderHook(() => useRunStream("r", meta));
    for (let i = 0; i < 4; i++) {
      act(() => FakeEventSource.last.fail(true));
      act(() => { vi.advanceTimersByTime(5000); });
    }
    expect(result.current.phase).toBe("failed");
    expect(result.current.failed?.code).toBe("internal");
  });

  it("closes the stream on unmount and does not reconnect", () => {
    const { unmount } = renderHook(() => useRunStream("r", meta));
    const es = FakeEventSource.last;
    unmount();
    expect(es.closed).toBe(true);
    act(() => { vi.advanceTimersByTime(10_000); });
    expect(FakeEventSource.instances).toHaveLength(1);
  });

  it("switches streams when the run id changes", () => {
    const { rerender } = renderHook(({ id }) => useRunStream(id, meta), { initialProps: { id: "a" as string | null } });
    const a = FakeEventSource.last;
    rerender({ id: "b" });
    expect(a.closed).toBe(true);
    expect(FakeEventSource.last.url).toBe("/api/runs/b/events");
  });
});
