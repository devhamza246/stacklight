# Stacklight UI design

Static HTML/CSS mockups that the React build (Task 15) follows. No framework, no CDN, no fonts fetched: open `index.html` in a browser.
All figures in the mockups ($0.004, 3.1 s, $0.19 of $2.00) are **illustrative**. The UI itself never says so.

| File | What it is |
|---|---|
| `tokens.css` | Design tokens: type scale, spacing, radius, motion, light and dark colors |
| `base.css` | Component styles built only on the tokens |
| `chat.html` | Full screen: chat + Trace + Approval queue. States below. Mobile has a Chat / Trace / Queue tab bar |
| `trace.html` | Trace panel specimen (wide layout shows the agent graph horizontally, plus the span table) |
| `approvals.html` | Approval queue specimen: conflict diff, stale page, drafted reply, resolved, empty |
| `mock.js` | Mockup-only switching (`?state=`, `?theme=`, `?tab=`, `?drawer=`). Not product code |
| `screens/` | `{desktop,mobile}-{light,dark}-{state}.png`, 1440x900 and 390x844 |

URL switches: `?state=idle|streaming|answer|abstain|paused|busy|resetting|failed` on `chat.html`; `&drawer=1|2` on `state=answer`; `&tab=trace|queue` below 1024 px; `&theme=light|dark`. Without `?theme` it follows the OS, and the header toggle overrides it.

## Design rationale

- **The first 30 seconds do the selling.** The first screen has a real question already in the box (answerable from the corpus), the tagline, and three suggestions, one of which runs the Curator. After the answer, the Trace and the Approval queue sit in the same view, so cited answer, team trace with cost and latency, and the Approve button are visible without scrolling at 1440x900.
- **Uncertainty is a first-class state, not an error.** "I'm not sure" uses amber, a question-mark icon, a reason, the closest sources (labelled "none of them answer it") and two next steps. It is deliberately not red and not a chat bubble.
- **Proof is always one click away.** Every `[n]` chip opens a source drawer with the document title, file path and the cited row or sentence highlighted. The Fact-checker result is a badge on the answer, and the footer shows cost and latency.
- **Agents propose, humans decide.** Every queue card says "Needs your approval. Nothing changes until you approve", shows the exact edit as a diff, and states the scope (`replace_all` off, one file). Drafted replies are labelled "Simulated send. Nothing leaves the system."
- **Calm and warm.** Warm-neutral surfaces, one teal accent, borders instead of shadows (shadow only on the drawer), generous spacing on an 8 px grid, 12 px radius. Inter-style type: `font-family: Inter, system-ui, ...`; the React build self-hosts Inter (the screenshots were taken without Inter installed, so they use the fallback sans, which is slightly wider).
- **Motion only explains.** A blinking caret while text streams; trace nodes light up in order and the connector fills; the active node pulses; a new queue card slides in; the drawer slides in. Everything is CSS and is removed under `prefers-reduced-motion`.
- **Never colour alone.** Every status has an icon and a word (check / dot / cross / dash / warning triangle plus Done / Running / Failed / Not run / Declined).
- **LLM text is plain text.** Answer text, finding summaries, draft bodies and diff lines come from a model or the corpus: render with text nodes (no `innerHTML`, no raw HTML). Bold and `[n]` chips are produced by the app from structured data (citation events), not parsed from model markup. The drawer's table is the corpus chunk rendered by a safe markdown subset with no raw HTML.

## Tokens

| Token | Light | Dark | Use |
|---|---|---|---|
| `--bg` | #faf8f5 | #12100e | Page |
| `--surface` | #ffffff | #1a1815 | Cards, panels |
| `--surface-2` | #f5f2ed | #221f1b | Inset areas, user message, footers |
| `--text` / `--text-2` / `--text-3` | #1c1917 / #55504a / #6b655e | #f4f0ea / #bbb3a8 / #9d958a | Primary / secondary / hints |
| `--accent` | #0d9488 | #2dd4bf | Fills and graphics: node rings, caret, connectors |
| `--accent-text` | #0f766e | #5eead4 | Accent text and links (AA) |
| `--btn-bg` / `--btn-fg` | #0f766e / #ffffff | #2dd4bf / #052e2a | Primary button |
| `--accent-soft`, `--highlight` | #e5f4f1, #e0f5f1 | #11302d, #16443f | Badges, citation chips, cited passage |
| `--warn-*` | #7a3e07 on #fff6e3 | #fbbf24 on #261f0e | Abstain, paused, conflict |
| `--danger-*` | #9a2b17 on #fdf0ec | #f6a998 on #2b1814 | Failed run |
| `--del-*` / `--add-*` | red / green tints | red / green tints | Diff lines (with `-` and `+` glyphs) |
| `--control-border` | #8a8276 | #6b645a | Composer border (3:1) |

Why two teals in light mode: #0d9488 on white is only 3.7:1, fine for graphics, not for text. Text and button fills use #0f766e (5.5:1). The brand teal is therefore still the one accent, used at two strengths.

Type scale (px): 12, 13, 15 (body), 17 (answer), 20 (card titles), 28, 36. Spacing: 4, 8, 12, 16, 24, 32, 48, 64. Radius: 8, 12, 16, pill. Mono for file paths and span names.

## Contrast (WCAG 2.x, computed from the token values)

| Pair | Light | Dark | Need |
|---|---|---|---|
| Body text on surface | 17.49 | 15.61 | 4.5 |
| Body text on page | 16.50 | 16.72 | 4.5 |
| Secondary text on surface | 7.98 | 8.54 | 4.5 |
| Secondary text on page | 7.52 | 9.15 | 4.5 |
| Secondary text on inset surface | 7.14 | 7.91 | 4.5 |
| Tertiary text on page (hints, placeholders) | 5.43 | 6.42 | 4.5 |
| Tertiary text on inset surface | 5.15 | 5.55 | 4.5 |
| Accent text on surface | 5.47 | 11.98 | 4.5 |
| Accent text on accent-soft (badges, citation chips) | 4.83 | 9.56 | 4.5 |
| Accent text on highlight | 4.82 | 7.34 | 4.5 |
| Primary button label on button | 5.47 | 7.89 | 4.5 |
| Warning text on warning surface | 7.76 | 9.79 | 4.5 |
| Danger text on danger surface | 6.90 | 8.88 | 4.5 |
| Removed-line text | 7.50 | 8.59 | 4.5 |
| Added-line text | 7.04 | 9.88 | 4.5 |
| Accent graphic on surface | 3.74 | 9.52 | 3 |
| Warning icon on warning surface | 4.67 | 9.79 | 3 |
| Composer border on page | 3.58 | 3.25 | 3 |

Also: visible focus ring (2 px `--focus-ring`, offset 2 px) on every control; buttons and chips are at least 40 px tall below 1024 px; landmarks `header`, `main`, `aside`, `nav`; the answer body is `aria-live="polite"` with `aria-busy` while streaming; the status pill is `role="status"`; citation chips carry `aria-label="Source 1: <title>"` and `aria-expanded`; skip link; `prefers-reduced-motion` honoured; no horizontal page scroll at 390 px (the span table scrolls inside its own box).

## States

Each state is a `data-s` section in `chat.html` (or `trace.html` / `approvals.html`) and has screenshots in `screens/`.

| # | State | URL | Screenshot name |
|---|---|---|---|
| 1 | Idle / first load | `chat.html?state=idle` | `idle` |
| 2 | Mid-stream (caret, Answerer active) | `chat.html?state=streaming` | `streaming` |
| 3 | Completed answer with citations | `chat.html?state=answer` | `answer` |
| 3b | Source drawer open | `chat.html?state=answer&drawer=1` | `answer-drawer` |
| 4 | Abstention "I'm not sure" | `chat.html?state=abstain` | `abstain` |
| 5 | Curator finding + approval queue (conflict diff, stale, draft) | `approvals.html?state=pending` | `approval-diff` |
| 5b | After approving | `approvals.html?state=resolved` | `approval-resolved` |
| 6 | Demo paused, daily budget | `chat.html?state=paused` | `paused` |
| 6b | Busy, try again (429) | `chat.html?state=busy` | `busy` |
| 6c | Resetting (503) | `chat.html?state=resetting` | `resetting` |
| 7 | Failed run, trace kept | `chat.html?state=failed` | `failed` |
| 8 | Empty approval queue | `approvals.html?state=empty` | `approval-empty` |
| T | Trace panel: complete / running / abstained / failed | `trace.html?state=done\|streaming\|abstain\|failed` | `trace-done`, `trace-streaming`, `trace-abstain`, `trace-failed` |
| M | Mobile tabs | `chat.html?state=answer&tab=trace\|queue` | `m-trace`, `m-queue`, `m-queue-empty`, `m-trace-streaming`, `m-trace-failed` |

Screenshot file names are `{desktop|mobile}-{light|dark}-{name}.png`.

Corpus facts used (all verified in `corpus/`): Business P1 first response 1 hour, 24/7 and Enterprise 15 minutes (`sla-and-support-tiers.md`, reviewed 2026-09-22); Enterprise uptime 99.95%; Team API limit 300 requests/min (`plan-limits-reference.md`); refund window 30 days (`refund-policy.md`, reviewed 2026-08-02) vs 14 days (`billing-faq.md`, reviewed 2026-07-21); `legacy-onboarding-checklist-2024.md` last reviewed 2024-08-12; ticket T-1025. The abstention question (equity refresh policy) matches nothing in the corpus.

## UI <-> API mapping

| UI element | Driven by |
|---|---|
| Status pill ("Live demo, $0.19 of $2.00 today") | `GET /api/status`: `spend_today_usd`, `cap_usd`, `status`, `pending_runs`, `documents`, `kb_ready`, `kb_error` (poll, e.g. every 30 s and after each run; every 5 s while `kb_ready` is false: "Preparing the knowledge base…") |
| "Demo paused" banner, disabled composer | `status: "demo_paused"` from `/api/status`, or `503 {status:"demo_paused", reason:"daily_budget", resets_at}` on POST; show reset time from `resets_at` (UTC) |
| "Refreshing the demo data" notice | `503 {status:"resetting"}` + `Retry-After` |
| "Busy, try again" notice | `429 {error:"busy", retry_after_s}` or `rate_limited`; enable the button after `retry_after_s` |
| Send / Stop | `POST /api/chat {question}` -> `202 {run_id}`, then `GET /api/runs/{id}/events` (SSE); Stop closes the stream (the run keeps going server-side) |
| Trace node status | `span` events (`agent`, `status` started/ok/error, `cost_usd`, `latency_ms`, `cost_known`); node lights on `started`, finishes on `ok`, goes red on `error` |
| Retriever caption ("5 passages") and "degraded" hint | `retrieved` (`hits`, `degraded`) |
| Route caption ("Routed to ask") | `route` (`mode`, `reason`). Note `route` is not the first event |
| Streaming text and caret | `token` (`text`) |
| `[n]` chips, source drawer, sources row | `citation` (`chunk_id`, `quote`, `title`, `source`); the drawer fetches `GET /api/chunks/{id}` for the full passage and highlights `quote` |
| Fact-checked badge | Absence of `abstain` plus a verified run (the Fact-checker span `ok`). Claim counts (5/5) need the verdict in the run record; see concern in the task report |
| "I'm not sure" card, closest sources | `abstain` (`reason`: no_sources / not_in_kb / unverified, `closest[]`) |
| Totals chip and answer footer ($0.004, 3.1 s) | `totals` (`cost_usd`, `latency_ms`, `cost_known`); show "cost unknown" when `cost_known` is false |
| Run finished | `done`; `failed` (`code`, generic `message`) |
| Failed card copy | `llm_unavailable`: "The answer service isn't responding"; `timeout`: "This took too long, so I stopped it"; `internal`: "Something went wrong on our side". Always "Nothing was changed" and keep the trace |
| Approval queue cards | `finding` (`kind` conflict/stale, `summary`, `document_ids`, `approval_id`, `needs_human_choice`), `approval_proposed` (`approval_id`, `kind` reply/kb_change); on load `GET /api/findings` (pending kb_change) |
| Draft reply card | `draft` (`subject`, `body` already redacted, `citations[]`); started by `POST /api/draft {ticket_text, tone}` |
| "Audit the knowledge base" chip | `POST /api/curate` then the same SSE stream |
| `needs_human_choice: true` | Replace the single Approve with "Keep refund-policy.md" / "Keep billing-faq.md" choices (not mocked) |
| Approve / Reject | Approval endpoints from the approvals task; the UI shows the audit receipt after success |

## Components for the React build

`ThemeProvider` (data-theme + localStorage + system default), `AppShell` (header, two-column layout, mobile `TabBar`), `StatusPill`, `ChatPanel` (thread, `Composer`, `SuggestionChips`), `UserMessage`, `AnswerCard` (`StreamingText`, `CitationChip`, `VerifiedBadge`, `AnswerFooter`), `SourceDrawer` (dialog on desktop, bottom sheet on mobile, `PassageView`), `NotSureState`, `FailedState`, `NoticeBanner` (paused / busy / resetting), `TracePanel` (`TraceGraph`, `TraceNode`, `TotalsChip`, `SpanTable`), `ApprovalQueue` (`QueueCard`, `ConflictCard`, `StaleCard`, `DraftCard`, `DocDiff`, `ApprovalGate` line, `EmptyQueue`, `ApprovalReceipt`), `useRunStream` (SSE reducer for the events above), `useStatus`.

## Notes for the build

- `TraceGraph` is vertical in narrow containers and a horizontal graph when its container is at least 620 px wide (container query). Use one component; do not duplicate.
- With the current backend, `token` events replay an already verified answer, so the Fact-checker finishes before text streams. The mid-stream mockup shows the Answerer active (as designed). In the build, either show "Writing" while tokens replay with all nodes done, or add a "Checking claims" phase before the first token. Decide before building `useRunStream`.
- The mockups use a simple `[hidden]` toggle for states; the build should derive them from stream state.

## Build notes (where the React app intentionally differs)

The built UI follows these mockups; real screenshots are in `docs/ui/screens/` (`make e2e-screens`). Intentional differences:

- **Ordering**: real backend order, so the answer card shows a "Verifying sources…" skeleton, then the Fact-checked badge with real counts, then streamed text, then the `[n]` chips and sources row (answer text carries no inline markers, so chips follow the text).
- **Composer**: an Ask / Draft reply toggle (with a tone select) sits inside the box; a "Run audit" button sits in the queue header so an audit can be started after the first answer. No Stop button (a run cannot be cancelled server-side). The box is cleared after sending; "Rephrase the question" puts the last question back.
- **"I'm not sure"**: no "Ask a human" action (not an API feature); it keeps "Rephrase the question" and lists the 3 closest sources as buttons that open the drawer.
- **Source drawer**: shows one passage (the cited one) rather than tabs, with a small safe renderer (headings, pipe tables, paragraphs; no HTML) and the quote highlighted by text match.
- **Approval cards**: titles come from the payload and `GET /api/documents` (a small read-only addition); cards are shown expanded, conflicts first. `replace_all` on is shown as a warning badge. Findings with `needs_human_choice` are informational cards with no Approve.
- **Trace**: the pipeline follows the run mode (Orchestrator, Retriever, Answerer, Fact-checker for ask; Orchestrator, Curator for an audit; Orchestrator, Drafter for a draft). No sequential light-up delay in real time (nodes light as spans arrive).
- **Tokens**: `--highlight` light value is now `#e0f5f1` (was `#d3efe9`) so accent text on it is 4.82:1; the contrast table above is updated. Idle trace nodes carry a faint teal tint, and the idle hero is top-biased.
- **Layout**: the tab bar applies below 1024 px (as in the mockups; phones are the 390 px case).
