# Demo script and video script

Everything here is a plan for recording. No timing or cost in this file is a measurement: with a real
model, latency and cost depend on the model you configure. Read them off the screen on the day.

Source of truth for the beats: the design spec (`docs/superpowers/specs/2026-11-17-stacklight-design.md`). The same
beats are exercised by the browser test `backend/tests/e2e/test_demo_script.py` (`make e2e`) against a stubbed model,
so the UI states below are verified; real-model behaviour is whatever your model does.

## 1. The 30-second beat sheet

The thought to land: "this system answers from its documents, shows its sources, and says when it is unsure."

Question already in the box on first load: **"What first-response time do we promise for a P1 incident on the Business plan?"**
(corpus answer: 1 hour, 24/7, from `handbook/sla-and-support-tiers.md`; the standard 4 business hours is the contrast).

| Time | Spec beat | Concrete action | What appears on screen |
|---|---|---|---|
| 0-5 s | Real question in the box, tagline on screen | Do nothing. Let the page sit. | Header tagline "AI team that answers from your docs, and keeps them current.", status pill (spend of cap today), the prefilled question, three suggestion chips (the third is "Audit the knowledge base"), an empty trace and an empty approval queue. |
| 5-15 s | Cited answer streams in; citations link to the passage | Click **Ask**. When the text finishes, click the `[1]` chip. | With the real backend the order is: trace nodes light up one by one, the answer card shows "Verifying sources..." with a skeleton, the badge turns to "Fact-checked - n/m claims supported", then the verified text streams in word by word, then the `[n]` chips and the sources row appear. The chip opens the source drawer on the cited passage, highlighted. |
| 15-22 s | Trace shows Orchestrator routing to Retriever, Answerer, Fact-checker; cost and latency visible | Close the drawer; point at the Trace panel (on mobile: the Trace tab, or "View trace"). | Orchestrator, Retriever ("n passages, hybrid + rerank"), Answerer, Fact-checker all done, each with its own time and cost, plus the total chip and the answer footer (cost, latency, number of sources). Real values for your model. |
| 22-30 s | Curator flags a conflict and queues a fix; Approve sits next to it | Click **Audit the knowledge base** (or **Run audit** in the queue header). Scroll the queue to the conflict card. Hover Approve; do not click it unless you want the receipt on camera. | A "Knowledge base audit" card with a Conflict finding (refund window 30 days in `refund-policy.md` vs 14 days in `billing-faq.md`) and a Stale finding (`legacy-onboarding-checklist-2024.md`). The queue shows a side-by-side diff, the exact proposed edit, the scope line, "Needs your approval. Nothing changes until you approve." and Approve / Reject. |

Why "verified before it streams": the app never shows unverified text. The Fact-checker runs first and the verified
answer is then replayed to the browser, which is why the badge comes before the words. Say so on camera; it reads as
a feature, because it is one.

Not in the first 30 s: architecture, framework names, setup or login, a "hello" chat.

## 2. The 2-minute video (screen recording)

Record 1440x900, light theme, one continuous take or three short takes. Voiceover in plain language; no framework names
until the last 20 seconds.

| Time | Shot | Voiceover |
|---|---|---|
| 0:00-0:10 | Page loads with the question prefilled. Hold, then click Ask. | "This is Stacklight: a small team of AI agents that answers from your documents and keeps them current. I'll ask it something real." |
| 0:10-0:35 | Trace nodes light up; skeleton "Verifying sources..."; badge; text streams; `[1]` chip. | "It retrieves, drafts an answer from only those passages, then a second agent checks every claim against its source. Only after that check does any text reach the screen. Here: n of n claims supported." |
| 0:35-0:50 | Click `[1]`; drawer shows the highlighted row of the SLA table. | "Every answer links to the exact passage it came from. This is the row it used." |
| 0:50-1:05 | Close drawer; Trace panel, then totals and footer. | "Each agent's time and cost is on screen, per run. [Read the real total off the screen.]" |
| 1:05-1:25 | Ask the unanswerable question: "What is our equity refresh policy for senior engineers?" Abstain card with closest sources. | "When the documents don't contain the answer, it says so and shows the closest sources instead of guessing. That is a result, not an error." |
| 1:25-1:50 | Click Audit the knowledge base; conflict card with the diff; point at the approval line; click Approve; show the receipt. | "A Curator agent audits the knowledge base. It found two pages that disagree about the refund window and proposes one exact edit. Nothing changes until a person approves, and every approval is recorded. Outbound replies work the same way: simulated send, human approval first." |
| 1:50-2:00 | Cut to the README evidence table, then the repo. | "The README has the retrieval numbers and the one command that reproduces them, and says what has not been measured yet. Link below." |

Only say the answer-level numbers aloud (faithfulness, cost per query) after you have run `make eval` and put them in
the README. Until then, the evidence shot shows the retrieval table and nothing more.

## 3. Recording checklist

Setup
- [ ] `.env`: provider key set, `LLM_MODEL` set to a cheap priced model, `DAILY_SPEND_CAP_USD` high enough for several takes (the status pill shows `spend of cap`; a tripped cap pauses the demo mid-take).
- [ ] Start from a **fresh reset** so the queue is empty and the corpus is pristine: `docker compose exec app python -m app.cli reset-demo` (needs no runs in flight). Confirm `/api/status` shows `kb_ready: true` and `documents: 81`.
- [ ] Warm the models: ask one throwaway question first (the first retrieval loads the reranker and is slower), then reset again if you do not want it in the history.
- [ ] Run the audit once beforehand if it is slow with your model (it judges document pairs one at a time). Pending proposals survive until the next reset (`GET /api/findings` lists them), so the queue will already hold the conflict and stale cards when you start recording. In that case do not run the audit again on camera (it may propose the same fixes again); narrate from the queue instead, or record the audit separately and cut it in.
- [ ] Do not approve the refund fix before the audit beat unless you want the receipt in the shot; after approving, a reset restores the original corpus.

Screen
- [ ] Light theme, 1440x900 window, browser zoom 100 % (110 % if text is too small on the final export).
- [ ] Hide bookmarks bar, extensions, other tabs; use a clean profile or private window; turn off notifications.
- [ ] Mouse pointer visible, moving slowly; no keyboard shortcuts on screen.
- [ ] Queue and chat empty at the start of the take (see reset above); question prefilled and untouched.
- [ ] One mobile shot (390x844) of the answer for the end of the video, optional.

After
- [ ] Read the real cost and latency numbers off the screen before writing them anywhere. Do not reuse figures from the design mockups (`$0.004`, `3.1 s`, `$0.19 of $2.00`): those are illustrative.
- [ ] Reset the demo again so the public instance is clean.
