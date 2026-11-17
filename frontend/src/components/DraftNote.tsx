import type { RunState } from "../state/runReducer";
import { Icon } from "./Icon";

/** Thread card for a drafted reply: a preview here, the full card with Approve lives in the queue. */
export function DraftNote({ run, onReview }: { run: RunState; onReview: () => void }) {
  const running = run.phase === "running";
  const d = run.draft;
  return (
    <article className="answer-card" aria-label="Drafted reply">
      <div className="answer-head">
        <span className="who">Draft reply</span>
        {running && !d ? <span className="badge badge-neutral" role="status"><Icon name="clock" />Drafting…</span>
          : d ? <span className="badge badge-ok"><Icon name="mail" />Waiting for approval</span> : null}
      </div>
      <div className="answer-body" aria-live="polite" aria-busy={running}>
        {running && !d && <div className="skeleton" aria-hidden="true"><i /><i /><i style={{ width: "62%" }} /></div>}
        {d && (
          <>
            {d.subject && <p className="answer-lead"><strong>{d.subject}</strong></p>}
            <p className="draft-body">{d.body}</p>
          </>
        )}
      </div>
      {d && (
        <div className="answer-foot">
          <span><Icon name="plane" /> Simulated send. Nothing leaves the system.</span>
          <button className="link-btn queue-link" type="button" onClick={onReview}>Review in queue</button>
        </div>
      )}
    </article>
  );
}
