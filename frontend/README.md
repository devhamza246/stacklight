# Stacklight frontend

React 18 + TypeScript + Vite. Hand-written CSS driven by the design tokens in `src/styles/tokens.css`
(copied from `docs/design/`, which stays the reference). Inter is self-hosted via `@fontsource-variable/inter`.
No CDN, no UI kit, no icon font; icons are inline SVG (`components/Icon.tsx`).

Node is **not** installed on the host. Every Node command runs in the official `node:22-slim` image through `make`:

| Command | What it does |
|---|---|
| `make web-install` | `npm ci` from the lockfile (exact pinned versions) |
| `make web-lock` | regenerate `package-lock.json` after editing `package.json` |
| `make web-test` | Vitest + React Testing Library (jsdom) |
| `make web-typecheck` | `tsc --noEmit` |
| `make web-build` | typecheck + production build into `frontend/dist` |
| `make web-dev` | Vite dev server on http://127.0.0.1:5173 with HMR, `/api` proxied to the API (see below) |
| `make e2e` | builds, then runs the Playwright browser tests in `backend/tests/e2e/` |
| `make e2e-screens` | same, and rewrites `docs/ui/screens/*.png` |

`make web-dev` uses host networking and proxies `/api` and `/health` to `API_TARGET` (default `http://127.0.0.1:8000`).
Start the API first: `cd backend && .venv/bin/uvicorn app.api.main:app --port 8000` (needs `make dev-db`).
In production the same FastAPI process serves `frontend/dist` (copied to `/srv/static` in the image) at `/`.

## Structure

```
src/
  api/        types.ts (SSE + REST contract, mirrors backend/app/api/events.py), client.ts (typed REST, ApiError kinds),
              useRunStream.ts (EventSource hook: reconnect, idempotent resume, cleanup)
  state/      runReducer.ts (events -> typed run state, derived node views), useDemo.ts (the screen's controller),
              useApprovals.ts (queue + decisions), useStatus.ts (gentle polling), ThemeProvider.tsx, useDocs.ts
  components/ ChatPanel, Composer, AnswerCard, CitationChip, SourceDrawer, PassageView, VerifiedBadge, NotSureState,
              Banner, TraceGraph/TraceNode/TotalsChip, ApprovalQueue/ApprovalCard/QueueCard/DocDiff, StatusPill, TabBar ...
  lib/        format (cost/latency like backend format_cost), quote (find the cited sentence), passage, boldSplit
  styles/     tokens.css, base.css (component styles from the mockups), app.css (additions)
```

## Behaviour worth knowing

- **Event order is the backend's**: spans light the trace nodes as they arrive; the answer card shows a "Verifying sources…"
  skeleton until `verified` (badge with real counts), then `token`s stream, then `citation`s become `[n]` chips.
- **All model/corpus text is plain text** (React text nodes). The only markup derived from text is `**bold**` in diffs
  (`lib/boldSplit.tsx`), built from split strings, never HTML. There is a test with an `<img onerror>` payload.
- **Status polling**: on load, every 30 s while the tab is visible, after each run, never overlapping; paused while hidden.
- **Errors**: 429 disables the composer with a countdown from `retry_after_s`; 503 `demo_paused` shows the calm paused
  banner (composer off, trace and queue still work); 503 `resetting` auto-retries; failed runs keep the trace.

## Tests

Unit/component tests live next to the code (`*.test.ts(x)`); `src/test/fakeEventSource.ts` is a controllable EventSource.

### End-to-end (Python, Playwright)

`backend/tests/e2e/` runs the **real FastAPI app and the built frontend** in Chromium. `server.py` starts the app with
deterministic stubs installed **at the module boundary only** (production modules contain no test code):

- `app.llm.client.complete/embed` (and the two modules that imported `embed`) are replaced: hashed bag-of-words embeddings,
  an answerer that cites a real retrieved passage with a verbatim quote, an all-supported fact-checker, and a curator judge
  that reports the refund-window conflict and the outdated onboarding checklist. Each call sleeps ~350 ms and reports a
  small cost/latency, so the trace shows numbers and lights up step by step.
- The cross-encoder download is replaced by a word-overlap scorer.
- A throwaway Postgres database is created per server on the dev instance (`127.0.0.1:15432`, e.g. `stacklight_e2e_main`),
  the real corpus is ingested through the real pipeline, and `POST /__e2e/reset` (defined in the test server only) calls the
  real `reset_demo_kb` between tests.
- Magic questions: one mentioning "equity" is unanswerable (abstain path), one mentioning "outage" makes the stub LLM fail
  (failed run). The paused scenario starts a second server with `DAILY_SPEND_CAP_USD=0`.

Needs `pip install playwright` (optional extra `e2e`) and `playwright install chromium` in `backend/.venv`, plus `make dev-db`.
E2E tests are marked `e2e` and excluded from the default `pytest` run.
