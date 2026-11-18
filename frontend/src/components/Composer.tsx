import { useId, type KeyboardEvent, type RefObject } from "react";
import type { Tone } from "../api/types";
import { Icon } from "./Icon";

export type ComposerMode = "ask" | "draft";

interface Props {
  mode: ComposerMode;
  onModeChange: (m: ComposerMode) => void;
  tone: Tone;
  onToneChange: (t: Tone) => void;
  value: string;
  onChange: (v: string) => void;
  onSubmit: () => void;
  /** Composer cannot send (demo paused, rate limited, resetting). The box stays visible. */
  disabled?: boolean;
  disabledPlaceholder?: string;
  /** A run is streaming; sending again waits for it to end. */
  running?: boolean;
  hero?: boolean;
  hint?: string;
  inputRef?: RefObject<HTMLTextAreaElement>;
}

export function Composer({
  mode, onModeChange, tone, onToneChange, value, onChange, onSubmit, disabled = false,
  disabledPlaceholder, running = false, hero = false, hint, inputRef,
}: Props) {
  const id = useId();
  const draft = mode === "draft";
  const blocked = disabled || running;
  const canSend = !blocked && value.trim().length > 0;
  const label = draft ? "Customer ticket text" : "Your question";
  const placeholder = disabled && disabledPlaceholder
    ? disabledPlaceholder
    : draft ? "Paste the customer’s message to draft a cited reply" : hero ? "Ask a question" : "Ask a follow-up";

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      if (canSend) onSubmit();
    }
  };

  return (
    <form className="composer" data-tour="composer" onSubmit={(e) => { e.preventDefault(); if (canSend) onSubmit(); }}>
      <div className={`composer-box${disabled ? " disabled-box" : ""}`}>
        <div className="composer-modes">
          <div role="group" aria-label="Mode" className="seg" data-tour="modes">
            <button type="button" aria-pressed={!draft} aria-label="Ask mode" onClick={() => onModeChange("ask")}>Ask</button>
            <button type="button" aria-pressed={draft} aria-label="Draft reply mode" onClick={() => onModeChange("draft")}>Draft reply</button>
          </div>
          {draft && (
            <label className="tone">
              <span className="sr-only">Tone</span>
              <select value={tone} onChange={(e) => onToneChange(e.target.value as Tone)} aria-label="Tone">
                <option value="support">Support tone</option>
                <option value="sales">Sales tone</option>
              </select>
            </label>
          )}
        </div>
        <label className="sr-only" htmlFor={id}>{label}</label>
        <div className="composer-row">
          <textarea
            id={id}
            ref={inputRef}
            rows={draft ? (hero ? 4 : 3) : hero ? 3 : 1}
            value={value}
            placeholder={placeholder}
            disabled={disabled}
            maxLength={4000}
            onChange={(e) => onChange(e.target.value)}
            onKeyDown={onKeyDown}
          />
          <button
            className="send"
            type="submit"
            aria-label={draft ? "Draft reply" : "Ask"}
            aria-disabled={!canSend}
            disabled={!canSend}
          >
            <Icon name="send" large />
          </button>
        </div>
      </div>
      <p className="composer-hint">
        {hint ?? (running ? "Answering…" : "Enter to send · Shift+Enter for a new line")}
      </p>
      {draft && <p className="composer-hint" data-testid="draft-visibility">Drafts are visible to all visitors of this demo.</p>}
    </form>
  );
}

export const SUGGESTIONS = [
  "What’s our uptime SLA for Enterprise?",
  "How many API requests per minute on the Team plan?",
];

export function SuggestionChips({ onPick, onAudit, disabled }: { onPick: (q: string) => void; onAudit: () => void; disabled?: boolean }) {
  return (
    <div className="chips" data-tour="chips" role="group" aria-label="Suggested questions">
      {SUGGESTIONS.map((q) => (
        <button key={q} className="chip" type="button" disabled={disabled} onClick={() => onPick(q)}>{q}</button>
      ))}
      <button className="chip chip-action" type="button" disabled={disabled} onClick={onAudit}>
        <Icon name="search" />Audit the knowledge base
      </button>
    </div>
  );
}
