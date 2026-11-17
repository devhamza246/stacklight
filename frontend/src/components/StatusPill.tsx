import type { StatusInfo } from "../api/types";
import { Icon } from "./Icon";

const usd = (n: number, known: boolean) => `$${n.toFixed(2)}${known ? "" : "+"}`;

export function StatusPill({ info, error }: { info: StatusInfo | null; error: boolean }) {
  let pill;
  if (info?.status === "demo_paused") {
    pill = (
      <span className="status-pill is-paused">
        <Icon name="pause" />
        <strong>Demo paused</strong>
        <span className="hide-sm">· {usd(info.spend_today_usd, info.cost_known)} of {usd(info.cap_usd, true)} today</span>
      </span>
    );
  } else if (info && info.kb_error) {
    pill = (
      <span className="status-pill is-paused">
        <Icon name="pause" />
        <span>Knowledge base setup failed — restart to retry</span>
      </span>
    );
  } else if (info && !info.kb_ready) {
    pill = (
      <span className="status-pill">
        <span className="dot" aria-hidden="true" />
        <span>Preparing the knowledge base…</span>
      </span>
    );
  } else if (info) {
    pill = (
      <span className="status-pill">
        <span className="dot" aria-hidden="true" />
        <strong className="hide-sm">Live demo</strong>
        <span><span className="hide-sm">· </span>{usd(info.spend_today_usd, info.cost_known)} of {usd(info.cap_usd, true)}<span className="hide-sm"> today</span></span>
      </span>
    );
  } else {
    pill = (
      <span className="status-pill">
        <span className="dot" aria-hidden="true" />
        <span>{error ? "Status unavailable" : "Connecting…"}</span>
      </span>
    );
  }
  return <div className="status" role="status" aria-label="Demo status">{pill}</div>;
}
