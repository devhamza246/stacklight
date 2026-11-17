import type { ReactNode } from "react";
import type { FailCode } from "../api/types";
import { Icon, type IconName } from "./Icon";

export type Notice =
  | { kind: "paused"; resetsAt?: string }
  | { kind: "busy" | "rate_limited"; secondsLeft: number }
  | { kind: "resetting" }
  | { kind: "failed"; code: FailCode; title?: string; detail?: string };

export const FAIL_COPY: Record<FailCode, { title: string; body: string }> = {
  llm_unavailable: {
    title: "The answer service isn’t responding",
    body: "I couldn’t reach the language model, so there is no answer yet. Nothing was changed. The steps that did run are kept in the trace.",
  },
  timeout: {
    title: "This took too long, so I stopped it",
    body: "The run hit its time limit. Nothing was changed. The steps that did run are kept in the trace.",
  },
  internal: {
    title: "Something went wrong on our side",
    body: "The run ended unexpectedly. Nothing was changed. The steps that did run are kept in the trace.",
  },
};

function resetTime(resetsAt?: string): { clock: string; inHours: string } {
  const t = resetsAt ? Date.parse(resetsAt) : NaN;
  if (Number.isNaN(t)) return { clock: "00:00 UTC", inHours: "" };
  const d = new Date(t);
  const clock = `${String(d.getUTCHours()).padStart(2, "0")}:${String(d.getUTCMinutes()).padStart(2, "0")} UTC`;
  const mins = Math.max(0, Math.round((t - Date.now()) / 60000));
  const inHours = mins >= 90 ? `in about ${Math.round(mins / 60)} hours` : mins >= 2 ? `in about ${mins} minutes` : "in a moment";
  return { clock, inHours };
}

function InfoBanner({ icon, title, tone = "info", children }: { icon: IconName; title: string; tone?: "info" | "warn"; children: ReactNode }) {
  return (
    <div className={`banner${tone === "info" ? " is-info" : ""}`} role="status">
      <Icon name={icon} large />
      <div>
        <strong>{title}</strong>
        {children}
      </div>
    </div>
  );
}

interface Props {
  notice: Notice;
  onRetry?: () => void;
  onViewTrace?: () => void;
  /** Failed notices show the run's cost and latency, e.g. "$0.0003 · 9.2 s". */
  footer?: string;
}

/** One component for every calm "something is not normal" state: paused, busy, rate-limited, resetting, failed. */
export function Banner({ notice, onRetry, onViewTrace, footer }: Props) {
  switch (notice.kind) {
    case "paused": {
      const { clock, inHours } = resetTime(notice.resetsAt);
      return (
        <InfoBanner icon="pause" title="Demo paused: daily budget reached" tone="warn">
          <p>
            The demo covers its own model costs and has used today’s budget. It comes back at midnight UTC ({clock}
            {inHours ? `, ${inHours}` : ""}). Nothing is broken. You can still read the trace and approval examples.
          </p>
        </InfoBanner>
      );
    }
    case "busy":
    case "rate_limited": {
      const waiting = notice.secondsLeft > 0;
      const busy = notice.kind === "busy";
      return (
        <InfoBanner
          icon="clock"
          title={busy ? "Busy right now, try again in a few seconds" : "You’re going a little fast"}
        >
          <p>
            {busy ? "Several people are using the demo." : "The demo limits how often one visitor can ask."} Your question is kept
            and nothing was charged.{waiting ? ` You can try again in ${notice.secondsLeft} s.` : ""}
          </p>
          {onRetry && (
            <p style={{ marginTop: 12 }}>
              <button className="btn btn-primary" type="button" onClick={onRetry} aria-disabled={waiting} disabled={waiting}>
                <Icon name="refresh" />
                {waiting ? `Try again in ${notice.secondsLeft} s` : "Try again"}
              </button>
            </p>
          )}
        </InfoBanner>
      );
    }
    case "resetting":
      return (
        <InfoBanner icon="refresh" title="Refreshing the demo data…">
          <p>The demo resets itself every few hours to a clean copy of the sample docs. Trying again automatically in a few seconds.</p>
        </InfoBanner>
      );
    case "failed": {
      const copy = FAIL_COPY[notice.code];
      return (
        <article className="callout callout-danger" aria-labelledby="fail-h">
          <div className="callout-head">
            <span className="callout-icon"><Icon name="power" large /></span>
            <div>
              <h2 id="fail-h">{notice.title ?? copy.title}</h2>
              <p>{notice.detail ?? copy.body}</p>
            </div>
          </div>
          <div className="callout-actions">
            {onRetry && (
              <button className="btn btn-primary" type="button" onClick={onRetry}>
                <Icon name="refresh" />Try again
              </button>
            )}
            {onViewTrace && <button className="btn trace-link" type="button" onClick={onViewTrace}>View trace</button>}
          </div>
          <div className="callout-foot num">
            Run failed · <span className="mono">{notice.code}</span>{footer ? ` · ${footer}` : ""}
          </div>
        </article>
      );
    }
  }
}
