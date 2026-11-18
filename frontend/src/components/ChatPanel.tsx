import { useEffect, useRef, type RefObject } from "react";
import type { Tone } from "../api/types";
import type { RunState } from "../state/runReducer";
import { formatCost, formatLatency } from "../lib/format";
import { AnswerCard } from "./AnswerCard";
import { AuditCard } from "./AuditCard";
import { Banner, type Notice } from "./Banner";
import { Composer, SuggestionChips, type ComposerMode } from "./Composer";
import { DraftNote } from "./DraftNote";
import { NotSureState } from "./NotSureState";
import type { OpenSource } from "./SourceDrawer";

export interface ComposerState {
  mode: ComposerMode; setMode: (m: ComposerMode) => void;
  tone: Tone; setTone: (t: Tone) => void;
  askText: string; setAskText: (v: string) => void;
  draftText: string; setDraftText: (v: string) => void;
}

interface Props {
  run: RunState;
  /** What the visitor last sent (also set when the request was refused, so the thread keeps it). */
  submitted: string | null;
  notice: Notice | null;
  composer: ComposerState;
  composerDisabled: boolean;
  disabledPlaceholder?: string;
  /** The first-start seed is still running (`kb_ready: false`). */
  preparing?: boolean;
  sending: boolean;
  onSubmit: () => void;
  onPick: (q: string) => void;
  onAudit: () => void;
  onRetry: () => void;
  onRephrase: () => void;
  onTour: (e: { currentTarget: HTMLElement }) => void;
  onViewTrace: () => void;
  onViewQueue: () => void;
  openChunkId: number | null;
  onOpenSource: (source: OpenSource, trigger: HTMLElement) => void;
  inputRef: RefObject<HTMLTextAreaElement>;
}

export function ChatPanel(p: Props) {
  const { run, submitted, notice, composer: c } = p;
  const threadRef = useRef<HTMLDivElement>(null);
  const idle = submitted === null && run.phase === "idle";
  const running = run.phase === "running" || p.sending;
  const text = c.mode === "draft" ? c.draftText : c.askText;
  const setText = c.mode === "draft" ? c.setDraftText : c.setAskText;

  // Keep the newest content in view while text streams, unless the reader scrolled up.
  useEffect(() => {
    const el = threadRef.current;
    if (!el) return;
    if (el.scrollHeight - el.scrollTop - el.clientHeight < 160) {
      const reduce = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
      el.scrollTo?.({ top: el.scrollHeight, behavior: reduce ? "auto" : "smooth" });
    }
  }, [run.text, run.citations.length, run.phase, run.findings.length, notice]);

  const composerEl = (hero: boolean) => (
    <Composer
      mode={c.mode} onModeChange={c.setMode} tone={c.tone} onToneChange={c.setTone}
      value={text} onChange={setText} onSubmit={p.onSubmit}
      disabled={p.composerDisabled} disabledPlaceholder={p.disabledPlaceholder} running={running}
      hero={hero} inputRef={p.inputRef}
      hint={p.preparing ? "Loading the sample docs. This takes a few minutes on first start." : p.composerDisabled && notice?.kind === "paused" ? "Resets at 00:00 UTC" : undefined}
    />
  );

  const banner = notice && notice.kind !== "failed" ? <Banner notice={notice} onRetry={p.onRetry} /> : null;

  if (idle) {
    return (
      <main id="main" className="col-chat" data-panel="chat" aria-label="Chat">
        <div className="thread is-centered">
          <div className="thread-inner">
            {banner}
            <div className="intro">
              <p className="eyebrow">AI team that answers from your docs, and keeps them current.</p>
              <h1>Ask anything the docs can answer.</h1>
              <p>Every answer cites its sources. If the docs don’t say, Stacklight tells you instead of guessing.</p>
              <p className="intro-tour">New here? <button type="button" className="link-btn" onClick={p.onTour}>Take the 30-second tour</button> or just try a sample question below.</p>
            </div>
            {composerEl(true)}
            <SuggestionChips onPick={p.onPick} onAudit={p.onAudit} disabled={p.composerDisabled || running} />
          </div>
        </div>
      </main>
    );
  }

  const totals = run.totals ? { cost: run.totals.cost_usd, latencyMs: run.totals.latency_ms, known: run.totals.cost_known } : null;
  const failedFooter = totals ? `${formatCost(totals.cost, totals.known)} · ${formatLatency(totals.latencyMs)}` : undefined;
  const failedNotice: Notice | null = run.failed ? { kind: "failed", code: run.failed.code } : notice?.kind === "failed" ? notice : null;

  let body = null;
  if (run.phase === "failed" || failedNotice) {
    body = failedNotice && <Banner notice={failedNotice} onRetry={p.onRetry} onViewTrace={p.onViewTrace} footer={failedFooter} />;
  } else if (run.abstain) {
    body = (
      <NotSureState
        abstain={run.abstain} hits={run.retrieved?.hits} footer={totals}
        onRephrase={() => {
          p.onRephrase();
          setTimeout(() => { p.inputRef.current?.focus(); p.inputRef.current?.select(); }, 0);
        }}
        onOpenSource={p.onOpenSource} onViewTrace={p.onViewTrace}
      />
    );
  } else if (run.mode === "curate" && run.phase !== "idle") {
    body = <AuditCard run={run} onReview={p.onViewQueue} />;
  } else if (run.mode === "draft" && run.phase !== "idle") {
    body = <DraftNote run={run} onReview={p.onViewQueue} />;
  } else if (run.phase !== "idle") {
    body = <AnswerCard run={run} openChunkId={p.openChunkId} onOpenSource={p.onOpenSource} onViewTrace={p.onViewTrace} />;
  }

  return (
    <main id="main" className="col-chat" data-panel="chat" aria-label="Chat">
      <div className="thread" ref={threadRef}>
        <div className="thread-inner">
          {submitted && (
            <div className="msg-user"><p><span className="sr-only">You asked: </span>{submitted}</p></div>
          )}
          {banner}
          {body}
        </div>
      </div>
      <div className="dock">{composerEl(false)}</div>
    </main>
  );
}
