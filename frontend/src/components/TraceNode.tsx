import type { NodeStatus } from "../state/runReducer";
import { formatCostFine, formatLatency } from "../lib/format";
import { Icon, type IconName } from "./Icon";

const ICON: Record<NodeStatus, IconName> = {
  pending: "dot", active: "dot", done: "check", error: "x", warn: "warn", skipped: "dash",
};
const WORD: Record<NodeStatus, string> = {
  pending: "Waiting", active: "Running", done: "Done", error: "Failed", warn: "Declined", skipped: "Not run",
};

interface Props {
  name: string;
  role: string;
  status: NodeStatus;
  statusLine?: string;
  latencyMs: number | null;
  cost: number;
  costKnown: boolean;
}

/** One agent in the pipeline. Status is always an icon AND a word, never colour alone. */
export function TraceNode({ name, role, status, statusLine, latencyMs, cost, costKnown }: Props) {
  const hasMetrics = status === "done" || status === "warn" || status === "error" || status === "active";
  return (
    <li className={`step is-${status}`} style={{ ["--i" as string]: 0 }} data-agent={name} data-status={status}>
      <span className="node">
        <Icon name={ICON[status]} />
        <span className="sr-only">{WORD[status]}</span>
      </span>
      <div>
        <div className="step-name">{name}</div>
        <div className="step-role">{role}</div>
        {statusLine && <span className="step-status">{statusLine}</span>}
      </div>
      <div className="step-metrics">
        {hasMetrics ? (
          <>
            <b>{latencyMs != null ? formatLatency(latencyMs) : "…"}</b>
            {formatCostFine(cost, costKnown)}
          </>
        ) : status === "skipped" ? null : (
          <span aria-label="no data yet">–</span>
        )}
      </div>
    </li>
  );
}
