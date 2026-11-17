import type { ReactNode } from "react";
import { Icon, type IconName } from "./Icon";

export type CardKind = "conflict" | "stale" | "reply" | "generic";
const KIND_ICON: Record<CardKind, IconName> = { conflict: "swap", stale: "clock", reply: "mail", generic: "file" };

interface Props {
  kind: CardKind;
  meta: string[];
  title: ReactNode;
  titleId: string;
  sub?: ReactNode;
  isNew?: boolean;
  children?: ReactNode;
  gate?: string;
  actions?: ReactNode;
  error?: string | null;
}

/** Shared frame for every approval card: header, body, the approval-gate line, actions, inline error. */
export function QueueCard({ kind, meta, title, titleId, sub, isNew, children, gate, actions, error }: Props) {
  return (
    <article className={`q-card${isNew ? " is-new" : ""}`} aria-labelledby={titleId} data-kind={kind}>
      <div className="q-head">
        <span className={`q-kind ${kind}`}><Icon name={KIND_ICON[kind]} /></span>
        <div style={{ minWidth: 0 }}>
          <div className="q-meta">{meta.map((m, i) => <span key={i}>{i > 0 && "· "}{m}</span>)}</div>
          <h3 className="q-title" id={titleId}>{title}</h3>
          {sub && <p className="q-sub">{sub}</p>}
        </div>
      </div>
      {children && <div className="q-body">{children}</div>}
      {gate && <div className="q-gate"><Icon name="lock" /><span><b>Needs your approval.</b> {gate}</span></div>}
      {error && <p className="q-error" role="alert">{error}</p>}
      {actions && <div className="q-actions">{actions}</div>}
    </article>
  );
}
