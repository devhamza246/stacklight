import { formatTotals, formatCost } from "../lib/format";

interface Props { running: boolean; started: boolean; cost: number; latencyMs: number | null; known: boolean }

/** "Ready" before a run, a live cost while it runs, "$0.004 · 3.1 s" once the backend's totals land. */
export function TotalsChip({ running, started, cost, latencyMs, known }: Props) {
  if (!started) return <span className="totals">Ready</span>;
  const text = latencyMs != null ? formatTotals(cost, latencyMs, known) : `${formatCost(cost, known)} so far`;
  return <span className={`totals${running ? " is-live" : ""}`} aria-live="off" data-testid="totals">{text}</span>;
}
