# Designed facts (used by tests and evals)

The corpus is for the fictional company "Quillbase". These are the deliberately seeded properties; every other document is meant to be consistent with the rest.

refund_conflict: refund-policy.md (30 days, full refund, no usage condition) vs billing-faq.md (14 days, annual plans only under 1,000 runs, 10 business days). Both state `**Refund window:** N days`; no other handbook doc does.

stale_doc: legacy-onboarding-checklist-2024.md (Last reviewed: 2024-08-12; outdated Team price $19, API v1, 14-day log retention, manual API keys, HIPAA/ISO claims). It intentionally disagrees with the current docs; it is stale, not a second conflict seed.

## Canonical current facts (for eval questions)
- Plans: Free $0, Team $29 ($24 annual), Business $79 ($66 annual), Enterprise custom; annual discount 17%.
- Uptime SLA: Business 99.9%, Enterprise 99.95%. P1 first response: Business 1 hour, Enterprise 15 minutes.
- API: base `https://api.quillbase.example/v2`, rate limits 60 / 300 / 1,200 / 6,000 requests per minute.
