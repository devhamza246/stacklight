import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import type { StatusInfo } from "../api/types";

export const STATUS_POLL_MS = 30_000;
/** Faster polling while the knowledge base is still being prepared. */
export const STATUS_PREPARING_POLL_MS = 5_000;

export interface StatusState { info: StatusInfo | null; error: boolean; refresh: () => void }

/**
 * Demo status for the header pill. Polled gently: once on load, then every 30 s while the tab is
 * visible (never in a loop that outruns the timer), plus `refresh()` for "after a run ends".
 * Polling pauses while the tab is hidden and catches up once when it becomes visible again.
 */
export function useStatus(fetchStatus: () => Promise<StatusInfo> = api.status): StatusState {
  const [info, setInfo] = useState<StatusInfo | null>(null);
  const [error, setError] = useState(false);
  const fetchRef = useRef(fetchStatus);
  fetchRef.current = fetchStatus;
  const inflight = useRef(false);
  const alive = useRef(true);
  const timer = useRef<ReturnType<typeof setTimeout>>();
  const preparing = useRef(false);

  const load = useCallback(async () => {
    if (inflight.current) return;
    inflight.current = true;
    try {
      const next = await fetchRef.current();
      if (alive.current) { preparing.current = next.kb_ready === false; setInfo(next); setError(false); }
    } catch {
      if (alive.current) setError(true);
    } finally {
      inflight.current = false;
    }
  }, []);

  useEffect(() => {
    alive.current = true;
    const schedule = () => {
      clearTimeout(timer.current);
      if (document.hidden) return;
      timer.current = setTimeout(async () => {
        await load();
        schedule();
      }, preparing.current ? STATUS_PREPARING_POLL_MS : STATUS_POLL_MS);
    };
    const onVisibility = () => {
      if (document.hidden) clearTimeout(timer.current);
      else { void load(); schedule(); }
    };
    void load().finally(schedule); // schedule after the first response: it decides the interval
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      alive.current = false;
      clearTimeout(timer.current);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [load]);

  const refresh = useCallback(() => void load(), [load]);
  return { info, error, refresh };
}
