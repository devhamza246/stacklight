import type { Approval, DocRef, KbChangePayload, ReplyPayload } from "../api/types";
import { basename, stripFindingKey } from "../lib/format";
import { docLabel } from "../state/useDocs";
import type { CardUi } from "../state/useApprovals";
import { DocDiff } from "./DocDiff";
import { Icon } from "./Icon";
import { QueueCard } from "./QueueCard";
import type { OpenSource } from "./SourceDrawer";

interface Props {
  approval: Approval;
  docs: Record<number, DocRef>;
  ui: CardUi;
  isNew?: boolean;
  onDecide: (id: number, approve: boolean) => void;
  onOpenSource: (source: OpenSource, trigger: HTMLElement) => void;
}

function Actions({ ui, approveLabel, rejectLabel, onApprove, onReject }: {
  ui: CardUi; approveLabel: string; rejectLabel: string; onApprove: () => void; onReject: () => void;
}) {
  const blocked = ui.busy || (ui.blockedUntil !== null && ui.blockedUntil > Date.now());
  return (
    <>
      <button className="btn btn-primary" type="button" disabled={blocked} aria-disabled={blocked} onClick={onApprove}>
        <Icon name={ui.busy ? "refresh" : "check"} />{ui.busy ? "Applying…" : approveLabel}
      </button>
      <button className="btn" type="button" disabled={blocked} aria-disabled={blocked} onClick={onReject}>{rejectLabel}</button>
    </>
  );
}

function ConflictBody({ p, docs }: { p: KbChangePayload; docs: Record<number, DocRef> }) {
  if (p.change.type !== "replace_text") return null;
  const target = docLabel(docs, p.document_id);
  const otherId = p.source_document_ids.find((id) => id !== p.document_id);
  const support = otherId !== undefined ? docLabel(docs, otherId) : undefined;
  return <DocDiff target={target} find={p.change.find} replace={p.change.replace} replaceAll={p.change.replace_all} support={support} />;
}

function KbChangeCard({ a, p, docs, ui, isNew, onDecide }: { a: Approval; p: KbChangePayload } & Omit<Props, "approval" | "onOpenSource">) {
  const id = `ap-${a.id}`;
  const target = docLabel(docs, p.document_id);
  const summary = stripFindingKey(p.finding_summary);
  const act = (approve: boolean) => () => onDecide(a.id, approve);

  if (p.change.type === "replace_text") {
    const other = p.source_document_ids.find((d) => d !== p.document_id);
    return (
      <QueueCard
        kind="conflict" meta={["Conflict", "Found by Curator"]} isNew={isNew} titleId={id}
        title={other !== undefined ? <>Two documents disagree: <span className="mono">{basename(docLabel(docs, other).source)}</span> and <span className="mono">{basename(target.source)}</span></> : "Two documents disagree"}
        sub={summary}
        gate="Nothing changes until you approve." error={ui.error}
        actions={<Actions ui={ui} approveLabel="Approve change" rejectLabel="Reject" onApprove={act(true)} onReject={act(false)} />}
      >
        <ConflictBody p={p} docs={docs} />
      </QueueCard>
    );
  }
  const superseded = p.change.type === "supersede" ? docLabel(docs, p.change.superseded_by_document_id) : null;
  return (
    <QueueCard
      kind="stale" meta={["Stale", "Found by Curator"]} isNew={isNew} titleId={id}
      title={<><span className="mono">{basename(target.source)}</span> looks out of date</>}
      sub={summary}
      gate="Nothing changes until you approve." error={ui.error}
      actions={<Actions ui={ui} approveLabel={superseded ? "Approve supersede" : "Approve archive"} rejectLabel="Keep it" onApprove={act(true)} onReject={act(false)} />}
    >
      <p className="why">
        <b>Proposed:</b>{" "}
        {superseded
          ? <>mark it as superseded by <span className="mono">{basename(superseded.source)}</span> so it stops appearing in answers.</>
          : "archive the document so it stops appearing in answers."}
      </p>
    </QueueCard>
  );
}

function ReplyCard({ a, p, ui, isNew, onDecide, onOpenSource }: { a: Approval; p: ReplyPayload } & Omit<Props, "approval" | "docs">) {
  const id = `ap-${a.id}`;
  const act = (approve: boolean) => () => onDecide(a.id, approve);
  const cites = p.citations.filter((c): c is { chunk_id: number; quote?: string } => typeof c.chunk_id === "number");
  return (
    <QueueCard
      kind="reply" meta={["Draft reply", p.tone]} isNew={isNew} titleId={id}
      title={p.subject ? `Reply: ${p.subject}` : "Drafted reply"}
      sub={p.ticket_text ? clip(p.ticket_text, 140) : undefined}
      gate="Nothing is sent until you approve." error={ui.error}
      actions={<Actions ui={ui} approveLabel="Approve and mark sent" rejectLabel="Discard" onApprove={act(true)} onReject={act(false)} />}
    >
      <div className="draft">
        {p.subject && <div className="subj">{p.subject}</div>}
        <p className="draft-body">{p.body}</p>
        {cites.length > 0 && (
          <p className="draft-cites">
            Sources{" "}
            {cites.map((c, i) => (
              <button
                key={i} type="button" className="cite" aria-haspopup="dialog" aria-label={`Source ${i + 1}: ${c.quote ? clip(c.quote, 60) : `passage ${c.chunk_id}`}`}
                onClick={(e) => onOpenSource({ chunkId: c.chunk_id, title: "Cited passage", source: "knowledge base", quote: c.quote }, e.currentTarget)}
              >[{i + 1}]</button>
            ))}
          </p>
        )}
        <p className="sim"><Icon name="plane" />Simulated send. Nothing leaves the system.</p>
      </div>
    </QueueCard>
  );
}

function GenericCard({ a, ui, isNew, onDecide }: { a: Approval } & Omit<Props, "approval" | "docs" | "onOpenSource">) {
  const act = (approve: boolean) => () => onDecide(a.id, approve);
  return (
    <QueueCard
      kind="generic" meta={[a.kind]} isNew={isNew} titleId={`ap-${a.id}`} title={`Proposal #${a.id}`}
      gate="Nothing changes until you approve." error={ui.error}
      actions={<Actions ui={ui} approveLabel="Approve" rejectLabel="Reject" onApprove={act(true)} onReject={act(false)} />}
    >
      <pre className="generic-payload">{JSON.stringify(a.payload, null, 2)}</pre>
    </QueueCard>
  );
}

const clip = (s: string, n: number) => (s.length > n ? `${s.slice(0, n - 1)}…` : s);

/** Picks the right card for an approval from its kind and payload shape. */
export function ApprovalCard({ approval: a, docs, ui, isNew, onDecide, onOpenSource }: Props) {
  const p = a.payload as Record<string, unknown>;
  if (a.kind === "kb_change" && p && typeof p === "object" && "change" in p && typeof p.document_id === "number") {
    return <KbChangeCard a={a} p={a.payload as KbChangePayload} docs={docs} ui={ui} isNew={isNew} onDecide={onDecide} />;
  }
  if (a.kind === "reply" && typeof p?.body === "string") {
    return <ReplyCard a={a} p={a.payload as ReplyPayload} ui={ui} isNew={isNew} onDecide={onDecide} onOpenSource={onOpenSource} />;
  }
  return <GenericCard a={a} ui={ui} isNew={isNew} onDecide={onDecide} />;
}
