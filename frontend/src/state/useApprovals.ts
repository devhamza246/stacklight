import { useCallback, useEffect, useRef, useState } from "react";
import { api as realApi, ApiError, type Api } from "../api/client";
import type { Approval } from "../api/types";

export interface Receipt {
  approval: Approval;
  approved: boolean;
  /** The server said it had already been decided (409): shown as a calm success, not an error. */
  alreadyDecided: boolean;
}

export interface CardUi { busy: boolean; error: string | null; blockedUntil: number | null }
const IDLE: CardUi = { busy: false, error: null, blockedUntil: null };

export interface ApprovalsState {
  pending: Approval[];
  receipts: Receipt[];
  loaded: boolean;
  loadError: boolean;
  ui: (id: number) => CardUi;
  decide: (id: number, approve: boolean) => Promise<void>;
  refresh: () => Promise<void>;
}

type Client = Pick<Api, "approvals" | "decide">;

/** Conflicts (an exact edit to review) first, then other KB changes, then drafted replies; newest first within each. */
function priority(a: Approval): number {
  if (a.kind === "reply") return 2;
  const change = (a.payload as { change?: { type?: string } }).change;
  return change?.type === "replace_text" ? 0 : 1;
}

/**
 * The pending queue plus per-card decision state. A decision is guarded synchronously
 * (a double click sends exactly one request), and a repeated decision (409) is treated as success.
 */
export function useApprovals(client: Client = realApi): ApprovalsState {
  const [pending, setPending] = useState<Approval[]>([]);
  const [receipts, setReceipts] = useState<Receipt[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [loadError, setLoadError] = useState(false);
  const [uis, setUis] = useState<Record<number, CardUi>>({});
  const inflight = useRef(new Set<number>());
  const alive = useRef(true);
  const clientRef = useRef(client);
  clientRef.current = client;

  useEffect(() => {
    alive.current = true;
    return () => { alive.current = false; };
  }, []);

  const patch = useCallback((id: number, next: Partial<CardUi>) => {
    if (alive.current) setUis((u) => ({ ...u, [id]: { ...(u[id] ?? IDLE), ...next } }));
  }, []);

  const refresh = useCallback(async () => {
    try {
      const list = await clientRef.current.approvals("pending");
      if (!alive.current) return;
      setPending([...list].sort((a, b) => priority(a) - priority(b) || b.id - a.id));
      setLoaded(true);
      setLoadError(false);
    } catch {
      if (alive.current) { setLoaded(true); setLoadError(true); }
    }
  }, []);

  useEffect(() => { void refresh(); }, [refresh]);

  const resolve = useCallback((approval: Approval, approved: boolean, alreadyDecided: boolean) => {
    if (!alive.current) return;
    setPending((p) => p.filter((a) => a.id !== approval.id));
    setReceipts((r) => [{ approval, approved, alreadyDecided }, ...r.filter((x) => x.approval.id !== approval.id)]);
  }, []);

  const decide = useCallback(async (id: number, approve: boolean) => {
    if (inflight.current.has(id)) return; // double click: one request only
    inflight.current.add(id);
    patch(id, { busy: true, error: null });
    try {
      const done = await clientRef.current.decide(id, approve);
      resolve(done, done.status === "approved", false);
    } catch (e) {
      if (!(e instanceof ApiError)) {
        patch(id, { error: "Something went wrong. Please try again." });
      } else if (e.kind === "conflict") {
        // Someone (or an earlier click) already decided it: converge on the server's answer.
        try {
          const all = await clientRef.current.approvals("all");
          const found = all.find((a) => a.id === id);
          if (found && found.status !== "pending") resolve(found, found.status === "approved", true);
          else await refresh();
        } catch {
          await refresh();
        }
      } else if (e.kind === "not_found") {
        patch(id, { error: "This proposal no longer exists (the demo data may have been refreshed)." });
        await refresh();
      } else if (e.kind === "unprocessable") {
        patch(id, { error: `The approved change could not be applied, so nothing was changed. ${e.message}` });
      } else if (e.kind === "rate_limited" || e.kind === "busy") {
        const wait = e.retryAfterS ?? 10;
        patch(id, { error: `Too many actions in a short time. Try again in ${wait} s.`, blockedUntil: Date.now() + wait * 1000 });
        setTimeout(() => patch(id, { blockedUntil: null }), wait * 1000);
      } else if (e.kind === "resetting") {
        const wait = e.retryAfterS ?? 5;
        patch(id, { error: `The demo is refreshing its data. Try again in ${wait} s.`, blockedUntil: Date.now() + wait * 1000 });
        setTimeout(() => patch(id, { blockedUntil: null }), wait * 1000);
      } else if (e.kind === "network") {
        patch(id, { error: "Couldn’t reach the server. Check your connection and try again." });
      } else {
        patch(id, { error: "Something went wrong. Please try again." });
      }
    } finally {
      inflight.current.delete(id);
      patch(id, { busy: false });
    }
  }, [patch, refresh, resolve]);

  return { pending, receipts, loaded, loadError, ui: (id) => uis[id] ?? IDLE, decide, refresh };
}
