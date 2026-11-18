import { useCallback, useEffect, useLayoutEffect, useRef, useState, type KeyboardEvent } from "react";
import { Icon, type IconName } from "./Icon";
import type { Tab } from "./TabBar";

type Side = "top" | "bottom" | "left" | "right";
interface Step {
  icon: IconName;
  title: string;
  body: string;
  /** CSS selector of the element to spotlight. No target = centered welcome card. */
  target?: string;
  /** Preferred popover sides, tried in order. */
  sides?: Side[];
  /** Phone layout shows one panel at a time; switch to it first. */
  tab?: Tab;
}

export const TOUR_STEPS: Step[] = [
  {
    icon: "shield",
    title: "A team of AI agents that works from your documents",
    body: "Stacklight answers questions from a company’s own docs, spots pages that are out of date or contradict each other, and drafts customer replies. This demo runs on a made-up company, Quillbase. Nothing risky happens without a person approving it.",
  },
  {
    icon: "chat",
    title: "Ask in plain English",
    body: "Answers stream in with numbered citations. Click one to open the exact passage, with the quoted sentence highlighted. If the docs don’t cover the question, Stacklight says it isn’t sure and shows the closest sources instead of guessing.",
    target: '[data-tour="composer"]', sides: ["bottom", "top", "right", "left"], tab: "chat",
  },
  {
    icon: "mail",
    title: "Answer questions or draft replies",
    body: "Switch to “Draft reply”, paste a customer’s message, and the Drafter writes a cited support or sales response from the docs. It goes to the approval queue; nothing is sent.",
    target: '[data-tour="modes"]', sides: ["bottom", "top", "right"], tab: "chat",
  },
  {
    icon: "search",
    title: "Not sure what to ask? Start here",
    body: "Pick a sample question, or run “Audit the knowledge base”. The Curator reads the docs, finds contradictions and stale pages, such as two refund policies that disagree, and proposes fixes.",
    target: '[data-tour="chips"]', sides: ["top", "bottom"], tab: "chat",
  },
  {
    icon: "activity",
    title: "Watch the team work",
    body: "Each agent lights up in turn: route the request, retrieve passages, write the answer, fact-check every claim. You also see what the question cost and how long it took.",
    target: '[data-panel="trace"]', sides: ["left", "bottom", "top"], tab: "trace",
  },
  {
    icon: "inbox",
    title: "You approve, or nothing happens",
    body: "Proposed doc fixes show up here as a before-and-after diff, and drafted replies as text. Nothing changes until you press Approve. In this demo sending is simulated and the sample docs reset every few hours, so click freely.",
    target: '[data-panel="queue"]', sides: ["left", "top", "bottom"], tab: "queue",
  },
];

const FOCUSABLE = 'button:not([disabled]), [href], [tabindex]:not([tabindex="-1"])';
const GAP = 14;
const MARGIN = 12;
const PAD = 6;

interface Placement { rect: DOMRect | null; left: number; top: number; side: Side | "center"; arrow: number }

function place(target: Element | null, pop: { w: number; h: number }, sides: Side[]): Placement {
  const vw = window.innerWidth;
  const vh = window.innerHeight;
  const raw = target?.getBoundingClientRect();
  if (!raw || raw.width === 0 || raw.height === 0) {
    return { rect: null, left: Math.max(MARGIN, (vw - pop.w) / 2), top: Math.max(MARGIN, (vh - pop.h) / 2), side: "center", arrow: 0 };
  }
  // Clip to the viewport so a tall panel is spotlit only where it is visible.
  const top = Math.max(raw.top, 0);
  const bottom = Math.min(raw.bottom, vh);
  const rect = new DOMRect(raw.left, top, raw.width, Math.max(bottom - top, 0));
  const clampX = (x: number) => Math.min(Math.max(x, MARGIN), vw - pop.w - MARGIN);
  const clampY = (y: number) => Math.min(Math.max(y, MARGIN), vh - pop.h - MARGIN);
  const cx = rect.left + rect.width / 2;
  const cy = rect.top + rect.height / 2;
  for (const s of sides) {
    let l = 0; let t = 0; let fits = false;
    if (s === "bottom") { t = rect.bottom + PAD + GAP; l = clampX(cx - pop.w / 2); fits = t + pop.h <= vh - MARGIN; }
    if (s === "top") { t = rect.top - PAD - GAP - pop.h; l = clampX(cx - pop.w / 2); fits = t >= MARGIN; }
    if (s === "right") { l = rect.right + PAD + GAP; t = clampY(cy - pop.h / 2); fits = l + pop.w <= vw - MARGIN; }
    if (s === "left") { l = rect.left - PAD - GAP - pop.w; t = clampY(cy - pop.h / 2); fits = l >= MARGIN; }
    if (fits) {
      const arrow = s === "top" || s === "bottom" ? cx - l : cy - t;
      return { rect, left: l, top: t, side: s, arrow: Math.min(Math.max(arrow, 22), (s === "top" || s === "bottom" ? pop.w : pop.h) - 22) };
    }
  }
  // Nothing fits beside it (small screens, tall targets): dock the card at the bottom, keep the spotlight.
  return { rect, left: clampX((vw - pop.w) / 2), top: clampY(vh - pop.h - MARGIN), side: "center", arrow: 0 };
}

/** Guided tour: a popover anchored to the real UI element it explains, with that element spotlit. */
export function TourDialog({ open, onClose, returnFocusTo, onTab }: {
  open: boolean; onClose: () => void; returnFocusTo: HTMLElement | null; onTab?: (t: Tab) => void;
}) {
  const [steps, setSteps] = useState<Step[]>(TOUR_STEPS);
  const [i, setI] = useState(0);
  const [pl, setPl] = useState<Placement | null>(null);
  const popRef = useRef<HTMLDivElement>(null);
  const headingRef = useRef<HTMLHeadingElement>(null);
  const closeRef = useRef(onClose);
  closeRef.current = onClose;
  const tabRef = useRef(onTab);
  tabRef.current = onTab;

  // Only walk through parts of the screen that exist right now (e.g. the sample chips vanish after a question).
  useEffect(() => {
    if (!open) return;
    setSteps(TOUR_STEPS.filter((s) => !s.target || document.querySelector(s.target)));
    setI(0);
    const trigger = returnFocusTo;
    const onKey = (e: globalThis.KeyboardEvent) => { if (e.key === "Escape") { e.stopPropagation(); closeRef.current(); } };
    document.addEventListener("keydown", onKey);
    return () => { document.removeEventListener("keydown", onKey); setPl(null); if (trigger?.isConnected) trigger.focus(); };
  }, [open, returnFocusTo]);

  const step = steps[Math.min(i, steps.length - 1)];

  const measure = useCallback(() => {
    const el = popRef.current;
    if (!el || !step) return;
    const target = step.target ? document.querySelector(step.target) : null;
    setPl(place(target, { w: el.offsetWidth, h: el.offsetHeight }, step.sides ?? ["bottom", "top"]));
  }, [step]);

  // Switch phone tab, bring the target into view, then measure as layout settles. Timers back up
  // requestAnimationFrame, which browsers pause in background tabs. Measuring is idempotent.
  useLayoutEffect(() => {
    if (!open || !step) return;
    if (step.tab) tabRef.current?.(step.tab);
    const run = () => {
      const target = step.target ? document.querySelector(step.target) : null;
      target?.scrollIntoView?.({ block: "nearest", inline: "nearest" });
      measure();
    };
    const raf = requestAnimationFrame(() => { run(); headingRef.current?.focus({ preventScroll: true }); });
    const timers = [40, 160, 400].map((ms) => window.setTimeout(run, ms));
    return () => { cancelAnimationFrame(raf); timers.forEach(clearTimeout); };
  }, [open, step, measure]);

  useEffect(() => {
    if (!open) return;
    window.addEventListener("resize", measure);
    window.addEventListener("scroll", measure, true);
    return () => { window.removeEventListener("resize", measure); window.removeEventListener("scroll", measure, true); };
  }, [open, measure]);

  if (!open || !step) return null;
  const last = i === steps.length - 1;

  const trap = (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.key !== "Tab") return;
    const items = Array.from(popRef.current?.querySelectorAll<HTMLElement>(FOCUSABLE) ?? []);
    if (!items.length) return;
    const first = items[0];
    const end = items[items.length - 1];
    const active = document.activeElement;
    if (e.shiftKey && (active === first || active === headingRef.current)) { e.preventDefault(); end.focus(); }
    else if (!e.shiftKey && active === end) { e.preventDefault(); first.focus(); }
  };

  const r = pl?.rect;
  return (
    <>
      <div className="tour-shield" aria-hidden="true" />
      {r ? (
        <div className="tour-spot" aria-hidden="true" style={{ left: r.left - PAD, top: r.top - PAD, width: r.width + PAD * 2, height: r.height + PAD * 2 }} />
      ) : (
        <div className="scrim" aria-hidden="true" />
      )}
      <div
        ref={popRef}
        className={`tour tour-${pl?.side ?? "center"}`}
        role="dialog" aria-modal="true" aria-labelledby="tour-title" onKeyDown={trap}
        style={{ left: pl?.left ?? -9999, top: pl?.top ?? -9999, ["--arrow" as string]: `${pl?.arrow ?? 0}px`, visibility: pl ? "visible" : "hidden" }}
      >
        <div className="tour-top">
          <span className="tour-count" aria-live="polite">Step {i + 1} of {steps.length}</span>
          <button className="icon-btn" type="button" aria-label="Close the tour" onClick={onClose}><Icon name="x" large /></button>
        </div>
        <h2 id="tour-title" tabIndex={-1} ref={headingRef}>{step.title}</h2>
        <p>{step.body}</p>
        <div className="tour-actions">
          <div className="tour-dots" aria-hidden="true">{steps.map((_, n) => <i key={n} className={n === i ? "on" : ""} />)}</div>
          <span style={{ flex: 1 }} />
          {!last && <button className="btn btn-quiet btn-sm" type="button" onClick={onClose}>Skip</button>}
          {i > 0 && <button className="btn btn-sm" type="button" onClick={() => setI(i - 1)}>Back</button>}
          <button className="btn btn-primary btn-sm" type="button" onClick={() => (last ? onClose() : setI(i + 1))}>
            {last ? "Start exploring" : "Next"}
          </button>
        </div>
      </div>
    </>
  );
}
