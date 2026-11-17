# Webhooks Guide

Owner: Developer Relations
Last reviewed: 2026-08-19

Quillbase can send webhooks to your endpoint and receive them to trigger flows.

## Outgoing webhooks
- Events: `run.succeeded`, `run.failed`, `flow.paused`, `workspace.quota_reached`.
- Payloads are JSON, signed with HMAC-SHA256 in the `X-Quillbase-Signature` header using your endpoint secret.
- Your endpoint must reply with a 2xx status within 10 seconds.
- Failed deliveries are retried 5 times with exponential backoff (1 minute, 5 minutes, 30 minutes, 2 hours, 12 hours), then marked failed. Events can be replayed manually for 7 days.
- Endpoint limits per plan: Free 2, Team 20, Business 100, Enterprise 500.

## Incoming webhooks
Each flow with a webhook trigger gets a unique URL of the form `https://hooks.quillbase.example/t/<token>`. Maximum body size is 6 MB (25 MB on Enterprise). Requests above 100 per second per workspace get HTTP 429.
