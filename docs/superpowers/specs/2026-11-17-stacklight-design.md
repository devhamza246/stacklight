# Stacklight: a multi-agent knowledge ops team (Design)

Status: draft for approval. Size: project. Date: 2026-11-17.

> **Historical design record.** This is the original brief, kept as written. The Langfuse optional profile and React
> Flow did NOT ship: tracing is OpenTelemetry-style spans in Postgres and the trace graph is CSS/SVG. The audience and
> sales framing below is the original brief, not a description of the shipped README.

## Intent and why

Stacklight is a public portfolio project proving multi-agent orchestration, RAG, and AI knowledge management. Audience: Western startup founders, CTOs, Upwork buyers. It is used in proposal openers: one line with a measured eval number, then a live demo link, a 2-minute video, and a README with metrics.

The thought to land in the first 30 seconds of the demo:

> "This person can ship an AI system I'd trust with real work, and it tells me when it's unsure."

### The 30-second demo script (the design's acceptance test)

| Time | What the viewer sees |
|------|----------------------|
| 0-5s | A real question already in the chat box. Tagline on screen: "Stacklight: AI team that answers from your docs, and keeps them current." |
| 5-15s | A cited answer streams in. Each citation links to the source passage. |
| 15-22s | Trace panel shows Orchestrator routing to Retriever, Answerer, Fact-checker. Cost and latency visible (e.g. "$0.004, 3.1s"). |
| 22-30s | Curator flags "two docs conflict on the refund policy" and queues a proposed fix. An Approve button sits next to it. |

Avoid in the first 30s: architecture diagrams, framework names, setup or login screens, a content-free "hello" chat.

What the founder should take away: cited answers (no hallucination worry); a visible team of agents with traces (engineering, not a prompt wrapper); cost per query on screen; the Curator and approval gate (it catches problems and does nothing risky alone).

## Goals

- One knowledge base; a team of agents answers, curates, and drafts replies from it.
- Agents (seven LangGraph nodes):
  - **Orchestrator**: routes each request, owns state and retries.
  - **Ingestion**: parses, chunks, embeds, stores documents.
  - **Retriever**: hybrid search (vector + keyword) then rerank.
  - **Answerer**: cited answers from retrieved passages only.
  - **Fact-checker** (added from the demo script): checks each claim against its cited passage, outputs a faithfulness score, and triggers abstention.
  - **Curator**: flags stale or conflicting docs, proposes updates.
  - **Drafter**: support and sales replies from KB content.
- **Abstention**: when retrieval confidence or faithfulness is low, the system says it is not sure and shows the closest sources instead of guessing.
- Human approval gate on every outbound reply and every KB change. No agent writes to the KB or sends a reply without a recorded human approval.
- Measurable proof: eval harness (retrieval hit rate, answer faithfulness, citation rate, abstention behavior), cost and latency per run, trace viewer.
- Provider-agnostic model layer (swap LLM via config).
- Reproducible: `docker compose up` runs everything; one command reproduces the eval table.

## Non-goals

- No separate frontend server, SSR framework (no Next.js), or UI state-management sprawl: one React SPA, built statically, served by FastAPI. (Revised 2026-11-17: the original "thin UI, no polish, no JS framework" stance was dropped at the author's request.)
- No auth, multi-tenant, billing.
- No fine-tuning.
- No real customer data.

## Anti-goals (failure even if it "works")

- Reads as a generic chatbot or toy demo.
- A UI that looks like a default admin template, or is beautiful but hides the traces, costs and citations that prove the engineering.
- No eval numbers, or numbers that cannot be reproduced. Any figure in the README or a proposal opener must come from the harness output; example figures such as "62% to 84%" are illustrations, never copied in.
- Un-cited answers.
- Agents that act without approval.

## Constraints

- Stack: Python, FastAPI, LangGraph, Postgres + pgvector, Celery + Redis, Docker; OpenTelemetry for tracing; Ragas-style evals; React + TypeScript + Vite frontend.
- Host: a self-hosted Ubuntu server, 4 cores, no GPU, with limited free RAM. It already runs other containers (including a Cloudflare tunnel); check ports and container names before deploying.
- Demo corpus must be synthetic or public/open-licensed.

## Approaches considered

1. **LangGraph + pgvector + FastAPI (chosen by author).** Built-in state, retries, human-in-the-loop; one datastore; matches author's stack; most-listed framework in job posts. Trade-off: framework learning curve.
2. Custom orchestrator, no framework. Shows internals but reinvents state, retries, tracing; may read as non-standard.
3. Claude/OpenAI Agents SDK + Qdrant. Fastest polish; vendor-tied, second datastore.

Sub-choices (author picked option A for both):

- **Tracing: OpenTelemetry spans stored in Stacklight's own Postgres, with an in-app trace viewer page.** Light on RAM, no extra containers, puts cost and latency on the demo screen. Rejected as default: self-hosted Langfuse (needs ClickHouse, MinIO, extra Redis; heavy for about 7 GB free; trace UI would sit outside the 30-second screen). Langfuse stays available as an optional compose profile.
- **Reranker: small CPU cross-encoder (MiniLM-class), run locally.** Free and reproducible; adds roughly 100-300 ms. Rejected as default: hosted reranker API (faster, but a paid key and harder to reproduce).

## Decided by the author

- Mixed concept: KB answering + curation + support/sales drafting.
- Approach 1 (LangGraph).
- OpenTelemetry-in-Postgres tracing and CPU reranker.
- The demo script above.

## Design calls (author asked to check; my proposals)

- **Demo corpus:** synthetic company handbook + support tickets generated with a cheap model, plus one open-source project's public docs for realism (license recorded in the repo). The handbook must contain two docs that genuinely disagree on the refund policy, plus at least one clearly stale doc, so the Curator demo is real.
- **UI (revised: beautiful, per author):** a polished single-page app served by FastAPI. The author has never shipped frontend, so the how is my call:
  - **Tech (author chose React + Vite on 2026-11-17):** React + TypeScript built with Vite. A multi-stage Dockerfile builds the static bundle and FastAPI serves it, so `docker compose up` still runs one app with no separate frontend server. Server-Sent Events stream answers and live trace updates. React Flow draws the animated agent graph; a diff component renders conflicting docs. Styling via CSS variables as design tokens (builder may add Tailwind or a component kit such as shadcn/ui). Fonts are self-hosted in the repo, no CDN dependency. Rejected: htmx + vanilla JS (no build step, but the live graph and diff views would need custom code).
  - **Look:** modern product-grade, not an admin template. Light and dark themes (follows system), generous spacing, one accent color, a clear type scale, subtle motion only where it explains something (answer streaming in, the trace lighting up agent by agent, a new item sliding into the approval queue). Responsive down to phone width, since buyers open links on phones.
  - **Layout:** chat with streaming answer and inline citation chips that open a source-passage drawer; a trace panel showing the agent graph with the active node highlighted, plus cost and latency; a Curator/approval queue with side-by-side diff of conflicting docs and Approve/Reject; abstention shown as a distinct "not sure" state with closest sources.
  - **The 30-second script is the visual spec.** The first screen load must already show a real question and the tagline, and every beat in the script must be reachable without clicking through setup.
  - **Backend contract:** the API and SSE event shapes (answer tokens, trace events, approval items) are defined in phases 1-3 so the UI can be built against them in phase 4.
  - **Process:** design first (static mockups of the three panels reviewed by the author before implementation), then build. Screenshot-based checks at desktop and phone widths are part of done.
  - Panels: chat, trace, approval queue (replies and KB changes).
- **Hosting:** Stacklight gets its own compose network and publishes one host port (proposed 8780, verify free before deploy). Public exposure via a new hostname on the existing Cloudflare tunnel setup, or a small VPS if uptime matters. Builder confirms.
- **Evals:** about 50 hand-checked Q&A pairs, including some unanswerable ones to test abstention. README table compares naive vector RAG vs hybrid + rerank on retrieval hit rate, faithfulness, citation rate. Eval runs pin one model and version.
- **Default LLM:** cheap hosted model for the live demo, swappable via config; embeddings model also configurable.
- **Memory budget:** the whole compose stack should fit in roughly 3-4 GB so it coexists with existing services.

- **Public demo safety (found in builder read-through):** with no auth, anyone can click Approve. So "send" is simulated (the approved reply is logged, nothing leaves the system), KB changes apply to a demo KB that resets on a schedule, and the public instance has per-IP rate limits plus a daily spend cap that makes it fall back to a "demo paused" notice. Approval records are still stored, to prove the gate.

## Left to the builder

Chunking strategy, schema, prompts, repo layout, CI, exact embedding and reranker model, abstention thresholds, trace schema details.

## Models per phase

- Architecture + eval design: Opus
- Implementation: Sonnet
- Synthetic docs / test questions: Haiku
- Demo script and README drafting: Sonnet (Opus only if the eval story is reworked)

## Phases

1. Repo skeleton, compose, schema, ingestion.
2. Retriever + Answerer + Fact-checker + evals baseline.
3. Orchestrator + Curator + Drafter + approval gates.
4. Tracing, cost tracking, UI design (mockups, then build).
5. UI polish pass, eval table, README, demo video, deploy.

Scope guard: the agents, evals and approval gates ship first. UI polish may not delay phases 1-3 or the eval table, because the eval numbers are what proves the project is not a toy.

## Definition of done

- `docker compose up` on a clean machine yields a working demo with the corpus loaded.
- The 30-second script runs end to end on the live demo.
- The UI passes a screenshot review at desktop and phone widths in light and dark themes.
- A single command regenerates the eval table; README numbers match its output.
- No code path sends a reply or changes the KB without a stored approval record.
- Every answer shown has citations or an explicit abstention.
