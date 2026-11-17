/** Mirrors backend/app/tracing/cost.py `format_cost`: unknown prices are a lower bound ("$0.004+") or "n/a". */
export function formatCost(usd: number, known = true): string {
  if (known) return `$${usd.toFixed(3)}`;
  return usd > 0 ? `$${usd.toFixed(3)}+` : "n/a";
}

/** Span-level cost needs more precision ($0.0003). */
export function formatCostFine(usd: number, known = true): string {
  if (!known && usd <= 0) return "n/a";
  return `$${usd.toFixed(4)}${known ? "" : "+"}`;
}

export function formatLatency(ms: number | null | undefined): string {
  if (ms == null) return "–";
  return `${(ms / 1000).toFixed(1)} s`;
}

export function formatTotals(cost: number, ms: number, known: boolean): string {
  return `${formatCost(cost, known)} · ${formatLatency(ms)}`;
}

/** "refund-policy.md" from "corpus/handbook/refund-policy.md". */
export function basename(path: string): string {
  const i = path.lastIndexOf("/");
  return i >= 0 ? path.slice(i + 1) : path;
}

/** Curator summaries are prefixed with an internal dedupe key like "[conflict:3-7] ". */
export function stripFindingKey(summary: string): string {
  return summary.replace(/^\[[^\]]+\]\s*/, "");
}

/**
 * Corpus sources are stored relative ("corpus/handbook/sla-and-support-tiers.md"). Older
 * databases may still hold absolute server paths; those are shortened to the relative form.
 * Anything else is shown as given.
 */
export function displayPath(source: string): string {
  const i = source.lastIndexOf("/corpus/");
  return i >= 0 ? source.slice(i + 1) : source;
}
