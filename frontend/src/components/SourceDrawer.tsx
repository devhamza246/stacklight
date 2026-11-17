import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import { api } from "../api/client";
import type { Chunk } from "../api/types";
import { Icon } from "./Icon";
import { displayPath } from "../lib/format";
import { PassageView, quoteFound } from "./PassageView";

export interface OpenSource {
  chunkId: number;
  title: string;
  source: string;
  /** The cited sentence to highlight; absent when opened from a "closest sources" list. */
  quote?: string;
}

interface Props {
  source: OpenSource | null;
  /** Element to give focus back to on close (the chip that opened the drawer). */
  returnFocusTo: HTMLElement | null;
  onClose: () => void;
  fetchChunk?: (id: number) => Promise<Chunk>;
}

type Load = { state: "loading" } | { state: "ready"; chunk: Chunk } | { state: "error" };

const FOCUSABLE = 'a[href], button:not([disabled]), textarea, input, select, [tabindex]:not([tabindex="-1"])';

/** Modal dialog: bottom sheet below 1024 px, right-hand drawer above. Focus is trapped and restored. */
export function SourceDrawer({ source, returnFocusTo, onClose, fetchChunk = api.chunk }: Props) {
  const [load, setLoad] = useState<Load>({ state: "loading" });
  const dialogRef = useRef<HTMLDivElement>(null);
  const headingRef = useRef<HTMLHeadingElement>(null);
  const closeRef = useRef(onClose);
  closeRef.current = onClose;
  const open = source !== null;
  const chunkId = source?.chunkId;

  useEffect(() => {
    if (chunkId === undefined) return;
    let live = true;
    setLoad({ state: "loading" });
    fetchChunk(chunkId).then(
      (chunk) => live && setLoad({ state: "ready", chunk }),
      () => live && setLoad({ state: "error" }),
    );
    return () => { live = false; };
  }, [chunkId, fetchChunk]);

  // Focus in on open; back to the trigger on close. Escape closes from anywhere.
  useEffect(() => {
    if (!open) return;
    const trigger = returnFocusTo;
    headingRef.current?.focus();
    const onKey = (e: globalThis.KeyboardEvent) => {
      if (e.key === "Escape") { e.stopPropagation(); closeRef.current(); }
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      if (trigger && trigger.isConnected) trigger.focus();
    };
  }, [open, returnFocusTo, chunkId]);

  if (!source) return null;

  const trap = (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.key !== "Tab") return;
    const items = Array.from(dialogRef.current?.querySelectorAll<HTMLElement>(FOCUSABLE) ?? []);
    if (!items.length) return;
    const first = items[0];
    const last = items[items.length - 1];
    const active = document.activeElement;
    if (e.shiftKey && (active === first || active === headingRef.current)) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && active === last) { e.preventDefault(); first.focus(); }
  };

  const title = load.state === "ready" ? load.chunk.title : source.title;
  const path = load.state === "ready" ? load.chunk.source : source.source;

  return (
    <>
      <div className="scrim" onClick={onClose} aria-hidden="true" />
      <div
        ref={dialogRef}
        className="drawer"
        id="source-drawer"
        role="dialog"
        aria-modal="true"
        aria-labelledby="drawer-title"
        onKeyDown={trap}
      >
        <div className="drawer-head">
          <div style={{ flex: 1, minWidth: 0 }}>
            <div className="eyebrow">Source</div>
            <h2 id="drawer-title" tabIndex={-1} ref={headingRef}>{title}</h2>
            <div className="drawer-path"><Icon name="file" /><span className="mono">{displayPath(path)}</span></div>
          </div>
          <button className="icon-btn" type="button" aria-label="Close source" onClick={onClose}>
            <Icon name="x" large />
          </button>
        </div>
        <div className="drawer-body">
          {load.state === "loading" && <p className="drawer-note" role="status">Loading the passage…</p>}
          {load.state === "error" && (
            <>
              <p className="drawer-note" role="alert">Couldn’t load the full passage. It may have changed since this answer.</p>
              {source.quote && <blockquote className="quote">{source.quote}</blockquote>}
            </>
          )}
          {load.state === "ready" && (
            <>
              <h3>{source.quote ? "Cited passage" : "Passage"}</h3>
              <PassageView text={load.chunk.text} quote={source.quote} />
              {quoteFound(load.chunk.text, source.quote) && (
                <p className="legend"><i aria-hidden="true" />Highlighted: the text the answer cites</p>
              )}
            </>
          )}
        </div>
        <div className="drawer-foot">
          <span>{load.state === "ready" ? `Passage ${load.chunk.ord + 1} of this document` : "Knowledge base"}</span>
          <span className="mono">chunk {source.chunkId}</span>
        </div>
      </div>
    </>
  );
}
