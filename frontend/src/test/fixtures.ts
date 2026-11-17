import type { Approval, Chunk, KbChangePayload, ReplyPayload } from "../api/types";

export const REFUND_APPROVAL: Approval = {
  id: 7, kind: "kb_change", status: "pending", created_at: "2026-11-17T10:00:00Z", decided_at: null,
  decided_by: null, reason: null, applied_at: null, result: null,
  payload: {
    document_id: 2,
    source_document_ids: [1, 2],
    finding_summary: "[conflict:1-2] 'Refund Policy' and 'Billing FAQ' conflict: 30 days vs 14 days.",
    change: {
      type: "replace_text",
      find: "**Refund window:** 14 days from the date of the charge",
      replace: "**Refund window:** 30 days from the date of your first purchase",
      replace_all: false,
    },
  } satisfies KbChangePayload,
};

export const STALE_APPROVAL: Approval = {
  ...REFUND_APPROVAL, id: 8,
  payload: {
    document_id: 3, source_document_ids: [3],
    finding_summary: "[stale:3] 'Legacy Onboarding' (last reviewed 2024-08-12) is stale: points to API v1.",
    change: { type: "archive" },
  } satisfies KbChangePayload,
};

export const REPLY_APPROVAL: Approval = {
  ...REFUND_APPROVAL, id: 9, kind: "reply",
  payload: {
    ticket_text: "Our integration keeps getting 429 errors", subject: "Rate limits on Team",
    body: "Hi, the Team plan allows 300 requests per minute.", tone: "support",
    citations: [{ chunk_id: 5, quote: "300 requests per minute" }],
  } satisfies ReplyPayload,
};

export const DOCS = [
  { id: 1, title: "Refund Policy", source: "corpus/handbook/refund-policy.md" },
  { id: 2, title: "Billing FAQ", source: "corpus/handbook/billing-faq.md" },
  { id: 3, title: "Legacy Onboarding", source: "corpus/handbook/legacy-onboarding-checklist-2024.md" },
];

export const CHUNK: Chunk = {
  chunk_id: 5, document_id: 1, title: "SLA and Support Tiers", source: "corpus/handbook/sla-and-support-tiers.md", ord: 0,
  text: "## Support channels\n\n| Plan | P1 |\n|---|---|\n| Team | 8 business hours |\n| Business | 1 hour, 24/7 |\n\nBusiness hours are 08:00 to 18:00 UTC.",
};
