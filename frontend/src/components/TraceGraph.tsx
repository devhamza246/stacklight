import { liveTotals, nodeView, pipelineFor, type NodeView, type RunState } from "../state/runReducer";
import { Icon } from "./Icon";
import { TotalsChip } from "./TotalsChip";
import { TraceNode } from "./TraceNode";

const ABSTAIN_WHY = { not_in_kb: "Not in the knowledge base", no_sources: "Nothing retrieved", unverified: "Could not be verified" } as const;

function describe(agent: string, run: RunState, v: NodeView, base: string): { role: string; line?: string } {
  const s = v.status;
  switch (agent) {
    case "orchestrator":
      return { role: run.route ? `Routed to ${run.route.mode}` : base };
    case "retriever":
      if (s === "active") return { role: "Searching the knowledge base", line: "Running…" };
      if (run.retrieved) {
        const n = run.retrieved.hits.length;
        return { role: `${n} passage${n === 1 ? "" : "s"}${run.retrieved.degraded ? ", reranker unavailable" : ", hybrid + rerank"}` };
      }
      return { role: base };
    case "answerer":
      if (s === "active") return { role: "Writing the answer", line: "Running…" };
      if (s === "warn") return { role: "Chose not to answer", line: run.abstain ? ABSTAIN_WHY[run.abstain.reason] : undefined };
      if (s === "error") return { role: run.failed?.code === "llm_unavailable" ? "Language model unavailable" : "Stopped early", line: v.latencyMs != null ? `Failed after ${(v.latencyMs / 1000).toFixed(1)} s` : "Failed" };
      if (s === "done") return { role: `Cited ${run.citations.length} source${run.citations.length === 1 ? "" : "s"}` };
      return { role: base };
    case "factchecker":
      if (s === "active") return { role: "Checking claims", line: "Running…" };
      if (s === "skipped") return { role: run.abstain ? "Nothing to check" : "Not run" };
      if (s === "done" && run.verified) return { role: `${run.verified.claims_supported} of ${run.verified.claims_total} claims supported` };
      return { role: base };
    case "curator":
      if (s === "active") return { role: "Scanning for conflicts and stale pages", line: "Running…" };
      if (s === "done") return { role: `${run.findings.length} finding${run.findings.length === 1 ? "" : "s"}` };
      return { role: base };
    case "drafter":
      if (s === "active") return { role: "Writing the reply", line: "Running…" };
      if (s === "done") return { role: run.draft ? "Drafted a reply" : "Chose not to draft" };
      return { role: base };
    default:
      return { role: base };
  }
}

/** The agent team as a fixed pipeline. Plain CSS: vertical when narrow, a horizontal graph in wide containers. */
export function TraceGraph({ run }: { run: RunState }) {
  const started = run.phase !== "idle";
  const running = run.phase === "running";
  const totals = liveTotals(run);
  const pipeline = pipelineFor(run.mode);
  const views = pipeline.map((p) => nodeView(run, p.agent));

  return (
    <section className="panel trace" data-panel="trace" aria-labelledby="trace-h" data-testid="trace">
      <div className="panel-head">
        <h2 id="trace-h"><Icon name="activity" />Trace</h2>
        <TotalsChip running={running} started={started && Object.keys(run.spans).length > 0} cost={totals.cost} latencyMs={totals.latencyMs} known={totals.known} />
      </div>
      <ol className={`steps${started ? "" : " is-idle"}`} aria-label="Agent pipeline" style={{ ["--n" as string]: pipeline.length }}>
        {pipeline.map((p, i) => {
          const v = views[i];
          const d = describe(p.agent, run, v, p.role);
          return <TraceNode key={p.agent} name={p.name} role={d.role} status={v.status} statusLine={d.line} latencyMs={v.latencyMs} cost={v.cost} costKnown={v.costKnown} />;
        })}
      </ol>
      <div className="trace-foot">
        {!started && <span>Ask a question and the team shows its work here: every step, its cost and its latency.</span>}
        {started && run.route && <span><b>Route</b> {run.route.mode}</span>}
        {started && run.retrieved && <span><b>Retrieved</b> {run.retrieved.hits.length}{run.retrieved.degraded ? " (degraded)" : ""}</span>}
        {started && run.citations.length > 0 && <span><b>Cited</b> {run.citations.length}</span>}
        {run.abstain && <span><b>Outcome</b> abstained ({run.abstain.reason})</span>}
        {run.mode === "curate" && run.phase === "done" && <span><b>Findings</b> {run.findings.length}</span>}
        {run.failed && <><span className="warnline">Run failed: {run.failed.code}</span><span>Spans kept so you can see where it stopped.</span></>}
      </div>
    </section>
  );
}
