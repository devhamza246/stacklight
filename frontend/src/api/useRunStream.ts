import { useEffect, useReducer, useRef } from "react";
import { EVENT_TYPES, type Mode, type RunEvent } from "./types";
import { initialRun, runReducer, type RunState } from "../state/runReducer";

const MAX_RECONNECTS = 3;
const RECONNECT_DELAY_MS = 800;

export interface RunMeta { question: string; mode: Mode }

/**
 * Subscribe to a run's SSE stream and reduce its events into typed state.
 *
 * - The browser reconnects a dropped stream by itself and sends `Last-Event-ID`, so the server
 *   resumes after the last event we saw. If the browser gives up (readyState CLOSED) we open a
 *   fresh EventSource a few times; the reducer ignores replayed ids, so resume stays idempotent.
 * - The stream is closed on terminal events and on unmount.
 */
export function useRunStream(runId: string | null, meta: RunMeta): RunState {
  const [state, dispatch] = useReducer(runReducer, initialRun);
  const metaRef = useRef(meta);
  metaRef.current = meta;

  useEffect(() => {
    if (!runId) {
      dispatch({ type: "reset" });
      return;
    }
    dispatch({ type: "start", runId, question: metaRef.current.question, mode: metaRef.current.mode });

    let source: EventSource | null = null;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let attempts = 0;
    let finished = false;

    const finish = () => {
      finished = true;
      source?.close();
    };

    const open = () => {
      const es = new EventSource(`/api/runs/${encodeURIComponent(runId)}/events`);
      source = es;
      for (const type of EVENT_TYPES) {
        es.addEventListener(type, (raw) => {
          const msg = raw as MessageEvent<string>;
          let event: RunEvent;
          try { event = JSON.parse(msg.data) as RunEvent; } catch { return; }
          const id = Number(msg.lastEventId);
          attempts = 0;
          dispatch({ type: "event", event, id: Number.isFinite(id) && id > 0 ? id : undefined });
          if (event.type === "done" || event.type === "failed") finish();
        });
      }
      es.onerror = () => {
        if (finished) return;
        if (es.readyState !== EventSource.CLOSED) return; // browser is retrying with Last-Event-ID
        es.close();
        if (attempts >= MAX_RECONNECTS) {
          finished = true;
          dispatch({ type: "connection_lost" });
          return;
        }
        attempts += 1;
        timer = setTimeout(open, RECONNECT_DELAY_MS * attempts);
      };
    };
    open();

    return () => {
      finished = true;
      clearTimeout(timer);
      source?.close();
    };
  }, [runId]);

  return state;
}
