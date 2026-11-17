import type { RunState } from "../state/runReducer";
import { stripFindingKey } from "../lib/format";
import { Icon } from "./Icon";

/** Thread card for a Curator audit: findings as they stream in, then a summary and a way to the queue. */
export function AuditCard({ run, onReview }: { run: RunState; onReview: () => void }) {
  const running = run.phase === "running";
  const queued = run.findings.filter((f) => f.approval_id !== null).length;
  const human = run.findings.length - queued;
  return (
    <article className="answer-card" aria-label="Knowledge base audit">
      <div className="answer-head">
        <span className="who">Knowledge base audit</span>
        {running
          ? <span className="badge badge-neutral" role="status"><Icon name="clock" />Scanning…</span>
          : <span className={`badge ${run.findings.length ? "badge-warn" : "badge-ok"}`}>
              <Icon name={run.findings.length ? "warn" : "check"} />
              {run.findings.length ? `${run.findings.length} finding${run.findings.length === 1 ? "" : "s"}` : "Nothing new to fix"}
            </span>}
      </div>
      <div className="answer-body audit-body" aria-live="polite" aria-busy={running}>
        {running && run.findings.length === 0 && (
          <p>The Curator is comparing documents and checking review dates. With a real model this can take a little while.</p>
        )}
        {run.findings.length > 0 && (
          <ul className="finding-list">
            {run.findings.map((f, i) => (
              <li key={i}>
                <span className={`badge ${f.kind === "conflict" ? "badge-warn" : "badge-neutral"}`}>{f.kind === "conflict" ? "Conflict" : "Stale"}</span>
                <span>{stripFindingKey(f.summary)}</span>
              </li>
            ))}
          </ul>
        )}
        {!running && run.phase === "done" && run.findings.length === 0 && (
          <p>No new conflicts or stale pages. Anything already waiting for review is in the queue.</p>
        )}
        {!running && run.findings.length > 0 && (
          <p className="audit-sum">
            {queued > 0 && <>{queued} proposed {queued === 1 ? "fix is" : "fixes are"} waiting for your approval. Nothing changes until you approve. </>}
            {human > 0 && <>{human} need{human === 1 ? "s" : ""} a human decision and {human === 1 ? "has" : "have"} no automatic edit.</>}
          </p>
        )}
      </div>
      {!running && queued > 0 && (
        <div className="answer-foot">
          <span>{queued} in the approval queue</span>
          <button className="link-btn queue-link" type="button" onClick={onReview}>Review in queue</button>
        </div>
      )}
    </article>
  );
}
