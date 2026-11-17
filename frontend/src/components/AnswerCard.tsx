import type { RunState } from "../state/runReducer";
import { basename, formatCost, formatLatency } from "../lib/format";
import { CitationChip } from "./CitationChip";
import { Icon } from "./Icon";
import { VerifiedBadge } from "./VerifiedBadge";
import type { OpenSource } from "./SourceDrawer";

interface Props {
  run: RunState;
  openChunkId: number | null;
  onOpenSource: (source: OpenSource, trigger: HTMLElement) => void;
  onViewTrace: () => void;
}

/**
 * Real backend ordering: the answer is verified BEFORE any text streams. So the card shows a
 * skeleton ("Verifying sources…") until `verified` arrives, then the badge, then the text, then
 * the citation chips once the citation events land.
 */
export function AnswerCard({ run, openChunkId, onOpenSource, onViewTrace }: Props) {
  const running = run.phase === "running";
  const verifying = running && !run.verified;
  const streaming = running && !run.totals && run.citations.length === 0;
  // Defensive client gate for "answer only after verification": text is never shown before `verified`.
  const paragraphs = !run.verified ? [] : run.text.split(/\n{2,}/).filter((p) => p.trim().length > 0);
  const open = (i: number) => (el: HTMLElement) => {
    const c = run.citations[i];
    onOpenSource({ chunkId: c.chunk_id, title: c.title, source: c.source, quote: c.quote }, el);
  };

  return (
    <article className="answer-card" aria-label="Answer">
      <div className="answer-head">
        <span className="who">Answer</span>
        {run.verified || verifying ? <VerifiedBadge verified={run.verified} /> : (
          <span className="badge badge-neutral">Writing…</span>
        )}
      </div>
      <div className="answer-body" aria-live="polite" aria-busy={running} data-testid="answer-body">
        {verifying ? (
          <div className="skeleton" aria-hidden="true"><i /><i /><i style={{ width: "62%" }} /></div>
        ) : (
          paragraphs.map((p, i) => {
            const last = i === paragraphs.length - 1;
            return (
              <p key={i} className={i === 0 ? "answer-lead" : undefined}>
                {p}
                {last && streaming && <span className="caret" aria-hidden="true" />}
                {last && run.citations.map((c, k) => (
                  <CitationChip key={k} n={k + 1} title={c.title} expanded={openChunkId === c.chunk_id} onOpen={open(k)} />
                ))}
              </p>
            );
          })
        )}
        {verifying && <span className="sr-only">Verifying sources…</span>}
      </div>
      {run.citations.length > 0 && (
        <div className="answer-sources" role="group" aria-label="Sources">
          {run.citations.map((c, k) => (
            <button
              key={k}
              className="source-link"
              type="button"
              aria-haspopup="dialog"
              aria-expanded={openChunkId === c.chunk_id}
              onClick={(e) => open(k)(e.currentTarget)}
            >
              <Icon name="file" />
              <span><span className="mono">[{k + 1}]</span> {c.title} · <span className="mono">{basename(c.source)}</span></span>
            </button>
          ))}
        </div>
      )}
      {run.totals && (
        <div className="answer-foot">
          <span className="num"><strong>{formatCost(run.totals.cost_usd, run.totals.cost_known)}</strong> · {formatLatency(run.totals.latency_ms)}</span>
          <span className="sep" aria-hidden="true">|</span>
          <span>{run.citations.length} {run.citations.length === 1 ? "source" : "sources"}</span>
          <button className="link-btn trace-link" type="button" onClick={onViewTrace}>View trace</button>
        </div>
      )}
    </article>
  );
}
