import type { AbstainEvent, HitRef } from "../api/types";
import { displayPath, formatTotals } from "../lib/format";
import { Icon } from "./Icon";
import type { OpenSource } from "./SourceDrawer";

const REASON: Record<AbstainEvent["reason"], string> = {
  not_in_kb: "I couldn’t find this in the knowledge base, so I won’t guess.",
  no_sources: "Nothing in the knowledge base matched this question, so I won’t guess.",
  unverified: "I found related pages but couldn’t check an answer against them, so I won’t guess.",
};

interface Props {
  abstain: AbstainEvent;
  /** Retrieval hits, used only to order and label the closest sources. */
  hits?: HitRef[];
  footer?: { cost: number; latencyMs: number; known: boolean } | null;
  onRephrase: () => void;
  onOpenSource: (source: OpenSource, trigger: HTMLElement) => void;
  onViewTrace?: () => void;
}

/** Abstention is a calm, first-class outcome (amber), not an error and not a chat bubble. */
export function NotSureState({ abstain, hits = [], footer, onRephrase, onOpenSource, onViewTrace }: Props) {
  const rank = (id: number) => {
    const i = hits.findIndex((h) => h.chunk_id === id);
    return i < 0 ? Number.MAX_SAFE_INTEGER : i;
  };
  const closest = [...abstain.closest].sort((a, b) => rank(a.chunk_id) - rank(b.chunk_id)).slice(0, 3);
  return (
    <article className="callout callout-warn" aria-labelledby="abs-h">
      <div className="callout-head">
        <span className="callout-icon"><Icon name="help" large /></span>
        <div>
          <h2 id="abs-h">I’m not sure</h2>
          <p>{REASON[abstain.reason]}</p>
          <p className="hint">Try rephrasing, or ask about something the docs cover. Mention the plan, feature or policy by name.</p>
        </div>
      </div>
      <div className="callout-actions" style={{ paddingTop: 8 }}>
        <button className="btn" type="button" onClick={onRephrase}>Rephrase the question</button>
      </div>
      {closest.length > 0 && (
        <div className="closest">
          <h3>Closest sources, none of them answer it</h3>
          <ul>
            {closest.map((c, i) => (
              <li key={c.chunk_id}>
                <button
                  className="closest-btn"
                  type="button"
                  aria-haspopup="dialog"
                  onClick={(e) => onOpenSource({ chunkId: c.chunk_id, title: c.title, source: c.source }, e.currentTarget)}
                >
                  <Icon name="file" />
                  <span>
                    <span className="t">{c.title}</span>
                    <span className="p mono">{displayPath(c.source)}</span>
                  </span>
                  <span className="tag">{i === 0 ? "Closest match" : "Also retrieved"}</span>
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
      <div className="callout-foot num">
        Abstained, no answer shown{footer ? ` · ${formatTotals(footer.cost, footer.latencyMs, footer.known)}` : ""}
        {onViewTrace && <> · <button className="link-btn trace-link" type="button" style={{ marginLeft: 0 }} onClick={onViewTrace}>View trace</button></>}
      </div>
    </article>
  );
}

