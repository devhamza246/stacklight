import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, ApiError } from "../api/client";
import type { FindingEvent, Tone } from "../api/types";
import { useRunStream } from "../api/useRunStream";
import type { Notice } from "../components/Banner";
import type { ComposerMode } from "../components/Composer";
import { useApprovals } from "./useApprovals";
import { useCountdown } from "./useCountdown";
import { useStatus } from "./useStatus";

export const PREFILLED_QUESTION = "What first-response time do we promise for a P1 incident on the Business plan?";
const MAX_RESET_RETRIES = 6;

type Request = { kind: "ask" | "draft" | "audit"; text: string; tone: Tone };

/** Everything the screen needs: composer state, the run stream, notices (paused/busy/...), the queue and status. */
export function useDemo() {
  const status = useStatus();
  const approvals = useApprovals();
  const [mode, setMode] = useState<ComposerMode>("ask");
  const [tone, setTone] = useState<Tone>("support");
  const [askText, setAskText] = useState(PREFILLED_QUESTION);
  const [draftText, setDraftText] = useState("");
  const [runId, setRunId] = useState<string | null>(null);
  const [meta, setMeta] = useState<{ question: string; mode: "ask" | "draft" | "curate" }>({ question: "", mode: "ask" });
  const [request, setRequest] = useState<Request | null>(null);
  const [sending, setSending] = useState(false);
  const [refusal, setRefusal] = useState<Notice | null>(null);
  const [deadline, setDeadline] = useState<number | null>(null);
  const [needsHuman, setNeedsHuman] = useState<FindingEvent[]>([]);
  const [newIds, setNewIds] = useState<Set<number>>(new Set());
  const run = useRunStream(runId, meta);
  const secondsLeft = useCountdown(deadline);
  const sendingRef = useRef(false);
  const resetTries = useRef(0);

  const refreshStatus = status.refresh;
  const send = useCallback(async (req: Request) => {
    if (sendingRef.current) return;
    sendingRef.current = true;
    setSending(true);
    setRequest(req);
    try {
      const { run_id } = req.kind === "audit" ? await api.startAudit() : await api.startRun(req.text, req.kind, req.tone);
      resetTries.current = 0;
      setRefusal(null);
      setDeadline(null);
      setNewIds(new Set());
      if (req.kind === "ask") setAskText("");
      if (req.kind === "draft") setDraftText("");
      setMeta({ question: req.kind === "audit" ? "Audit the knowledge base" : req.text, mode: req.kind === "audit" ? "curate" : req.kind });
      setRunId(run_id);
    } catch (e) {
      if (e instanceof ApiError && (e.kind === "busy" || e.kind === "rate_limited" || e.kind === "too_many_streams")) {
        setRefusal({ kind: e.kind === "busy" ? "busy" : "rate_limited", secondsLeft: e.retryAfterS ?? 10 });
        setDeadline(Date.now() + (e.retryAfterS ?? 10) * 1000);
      } else if (e instanceof ApiError && e.kind === "demo_paused") {
        setRefusal({ kind: "paused", resetsAt: e.resetsAt });
        refreshStatus();
      } else if (e instanceof ApiError && e.kind === "resetting") {
        setRefusal({ kind: "resetting" });
        setDeadline(Date.now() + (e.retryAfterS ?? 5) * 1000);
      } else {
        const offline = e instanceof ApiError && e.kind === "network";
        setRefusal({
          kind: "failed", code: "internal",
          title: offline ? "Can’t reach the server" : undefined,
          detail: offline ? "Check your connection. Nothing was sent and nothing was changed." : undefined,
        });
      }
    } finally {
      sendingRef.current = false;
      setSending(false);
    }
  }, [refreshStatus]);

  const submit = useCallback(() => {
    const text = (mode === "draft" ? draftText : askText).trim();
    if (text) void send({ kind: mode, text, tone });
  }, [mode, draftText, askText, tone, send]);
  const pick = useCallback((q: string) => { setMode("ask"); setAskText(q); void send({ kind: "ask", text: q, tone }); }, [send, tone]);
  const audit = useCallback(() => void send({ kind: "audit", text: "", tone }), [send, tone]);
  /** "Rephrase the question": put the last question back in the box to edit. */
  const restoreQuestion = useCallback(() => {
    if (request?.kind === "ask") { setMode("ask"); setAskText(request.text); }
    else if (request?.kind === "draft") { setMode("draft"); setDraftText(request.text); }
  }, [request]);
  const retry = useCallback(() => { if (request) void send(request); }, [request, send]);

  // The demo refreshing itself: try again by itself a few times.
  useEffect(() => {
    if (refusal?.kind !== "resetting" || deadline === null || secondsLeft > 0) return;
    if (resetTries.current >= MAX_RESET_RETRIES) return;
    resetTries.current += 1;
    retry();
  }, [refusal, deadline, secondsLeft, retry]);

  // After a run ends: refresh the spend pill and the queue.
  const settled = run.phase === "done" || run.phase === "failed";
  useEffect(() => {
    if (!settled) return;
    refreshStatus();
    void approvals.refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [settled, run.runId]);

  // Proposed approvals appear in the queue as they are created.
  const proposedKey = run.proposed.map((p) => p.approval_id).join(",");
  useEffect(() => {
    if (!proposedKey) return;
    void approvals.refresh();
    setNewIds((s) => new Set([...s, ...run.proposed.map((p) => p.approval_id), ...run.findings.flatMap((f) => (f.approval_id ? [f.approval_id] : []))]));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [proposedKey]);

  useEffect(() => {
    if (run.mode === "curate") setNeedsHuman(run.findings.filter((f) => f.approval_id === null));
  }, [run.mode, run.findings]);

  const pausedFromStatus = status.info?.status === "demo_paused";
  const notice: Notice | null = useMemo(() => {
    if (refusal?.kind === "busy" || refusal?.kind === "rate_limited") return { ...refusal, secondsLeft };
    if (pausedFromStatus && refusal?.kind !== "failed") return { kind: "paused", resetsAt: status.info?.resets_at };
    return refusal;
  }, [refusal, secondsLeft, pausedFromStatus, status.info?.resets_at]);

  const kbFailed = !!status.info?.kb_error;
  const preparing = status.info?.kb_ready === false && !kbFailed;
  const composerDisabled = preparing || kbFailed || notice?.kind === "paused" || notice?.kind === "resetting" || secondsLeft > 0;
  return {
    status, approvals, run, notice, needsHuman, newIds, sending, composerDisabled,
    submitted: request ? (request.kind === "audit" ? "Audit the knowledge base" : request.text) : null,
    composer: { mode, setMode, tone, setTone, askText, setAskText, draftText, setDraftText },
    submit, pick, audit, retry, restoreQuestion,
    preparing,
    disabledPlaceholder: kbFailed ? "Knowledge base setup failed — restart to retry" : preparing ? "Preparing the knowledge base…" : notice?.kind === "paused" ? "Questions are paused until midnight UTC" : "Please wait a moment",
  };
}
