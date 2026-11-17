import { useMemo } from "react";
import type { Approval, FindingEvent, KbChangePayload } from "../api/types";
import { basename, stripFindingKey } from "../lib/format";
import type { ApprovalsState, Receipt } from "../state/useApprovals";
import { docLabel, useDocs } from "../state/useDocs";
import { ApprovalCard } from "./ApprovalCard";
import { EmptyState } from "./EmptyState";
import { Icon } from "./Icon";
import type { OpenSource } from "./SourceDrawer";

interface Props {
  approvals: ApprovalsState;
  /** Approval ids the current run just proposed: slide in and get a "New" marker. */
  newIds: Set<number>;
  /** Findings the Curator could not turn into an edit (needs_human_choice). Informational only. */
  needsHuman: FindingEvent[];
  onOpenSource: (source: OpenSource, trigger: HTMLElement) => void;
  /** Starts a Curator audit (also reachable from the idle chips). Omitted: no button. */
  onAudit?: () => void;
  auditDisabled?: boolean;
}

function kbPayload(a: Approval): KbChangePayload | null {
  const p = a.payload as Partial<KbChangePayload>;
  return a.kind === "kb_change" && typeof p.document_id === "number" && p.change ? (a.payload as KbChangePayload) : null;
}

function receiptText(r: Receipt, docs: ReturnType<typeof useDocs>): { head: string; sub: string } {
  const p = kbPayload(r.approval);
  const file = p ? basename(docLabel(docs, p.document_id).source) : null;
  const was = r.alreadyDecided ? " (it was already decided)" : "";
  if (!r.approved) return { head: `Rejected${was}. Nothing was changed.`, sub: "The proposal is closed and the audit entry is saved." };
  if (r.approval.kind === "reply") return { head: `Approved${was}. Reply recorded as sent.`, sub: "Simulated send: nothing left the system. Audit entry saved." };
  if (p?.change.type === "replace_text") return { head: `Approved${was}. ${file} was updated.`, sub: "1 edit applied, audit entry saved. New questions use the new wording." };
  if (p?.change.type === "archive") return { head: `Approved${was}. ${file} was archived.`, sub: "It no longer appears in answers. Audit entry saved." };
  if (p?.change.type === "supersede") return { head: `Approved${was}. ${file} was marked superseded.`, sub: "It no longer appears in answers. Audit entry saved." };
  return { head: `Approved${was}.`, sub: "Audit entry saved." };
}

export function ApprovalQueue({ approvals, newIds, needsHuman, onOpenSource, onAudit, auditDisabled }: Props) {
  const { pending, receipts, loaded, loadError } = approvals;
  const ids = useMemo(
    () => [...pending, ...receipts.map((r) => r.approval)].flatMap((a) => {
      const p = kbPayload(a);
      return p ? [p.document_id, ...p.source_document_ids, ...(p.change.type === "supersede" ? [p.change.superseded_by_document_id] : [])] : [];
    }),
    [pending, receipts],
  );
  const docs = useDocs(ids);
  const empty = loaded && pending.length === 0 && needsHuman.length === 0;

  return (
    <section className="panel queue" data-panel="queue" aria-labelledby="queue-h" data-testid="queue">
      <div className="panel-head">
        <h2 id="queue-h">
          <Icon name="inbox" />Approval queue
          {pending.length > 0 && <span className="count-badge" aria-label={`${pending.length} pending`}>{pending.length}</span>}
        </h2>
        {onAudit && (
          <button className="btn btn-sm" type="button" onClick={onAudit} disabled={auditDisabled}>
            <Icon name="search" />Run audit
          </button>
        )}
      </div>
      <p className="panel-sub">Agents propose. You decide. Nothing changes until you approve.</p>
      {loadError && <p className="q-error" role="alert" style={{ margin: "0 16px 12px" }}>Couldn’t load the queue. It will refresh after the next run.</p>}
      <div className="queue-list" aria-live="polite">
        {receipts.map((r) => {
          const t = receiptText(r, docs);
          return (
            <div key={`r${r.approval.id}`} className="receipt" role="status">
              <Icon name="check" />
              <div><b>{t.head}</b><span>{t.sub}</span></div>
            </div>
          );
        })}
        {pending.map((a) => (
          <ApprovalCard
            key={a.id} approval={a} docs={docs} ui={approvals.ui(a.id)} isNew={newIds.has(a.id)}
            onDecide={approvals.decide} onOpenSource={onOpenSource}
          />
        ))}
        {needsHuman.map((f, i) => (
          <article key={`h${i}`} className="q-card" aria-labelledby={`nh-${i}`}>
            <div className="q-head">
              <span className={`q-kind ${f.kind}`}><Icon name={f.kind === "conflict" ? "swap" : "clock"} /></span>
              <div style={{ minWidth: 0 }}>
                <div className="q-meta"><span>{f.kind === "conflict" ? "Conflict" : "Stale"}</span><span>· Needs a human choice</span></div>
                <h3 className="q-title" id={`nh-${i}`}>No automatic fix: a person has to decide</h3>
                <p className="q-sub">{stripFindingKey(f.summary)}</p>
              </div>
            </div>
            <div className="q-gate"><Icon name="lock" /><span><b>Nothing to approve.</b> The Curator couldn’t tell which side is right, so it proposed no edit. Edit the documents yourself, then run the audit again.</span></div>
            <div style={{ height: 14 }} />
          </article>
        ))}
      </div>
      {empty && receipts.length === 0 && (
        <EmptyState title="Nothing waiting for review">
          Run an audit and the Curator will flag conflicts and stale pages here. It never changes a document on its own.
        </EmptyState>
      )}
      {empty && receipts.length > 0 && <p className="panel-sub" style={{ paddingBottom: 16 }}>Nothing else is waiting for review.</p>}
    </section>
  );
}
