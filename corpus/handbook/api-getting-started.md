# API Getting Started

Owner: Developer Relations
Last reviewed: 2026-10-12

- Base URL: `https://api.quillbase.example/v2`. Version 1 was retired on 31 March 2026 and returns HTTP 410.
- Authenticate with a bearer token: `Authorization: Bearer qb_live_...`. Test-mode tokens begin with `qb_test_` and never trigger real integrations.
- Create tokens under Settings > Developers. Tokens are shown once. Each workspace can hold up to 25 tokens, and a token can be scoped to read-only.
- Tokens that have not been used for 180 days are revoked automatically.
- Lists use cursor pagination: pass `limit` (default 25, maximum 100) and `cursor`.
- Key endpoints: `GET /flows`, `POST /flows/{id}/runs`, `GET /runs/{id}`, `POST /webhooks`.
- Idempotency: send an `Idempotency-Key` header on POST requests; keys are remembered for 24 hours.
- Official SDKs exist for Python (`pip install quillbase`) and TypeScript (`npm install @quillbase/sdk`).
