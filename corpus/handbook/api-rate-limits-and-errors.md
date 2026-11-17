# API Rate Limits and Errors

Owner: Developer Relations
Last reviewed: 2026-10-12

## Rate limits (requests per minute, per workspace)
Free 60, Team 300, Business 1,200, Enterprise 6,000 by default (higher on request). Responses include `X-RateLimit-Limit`, `X-RateLimit-Remaining` and `X-RateLimit-Reset` headers.

When you exceed the limit the API returns HTTP 429 with a `Retry-After` header in seconds. Back off exponentially and retry.

## Error codes
| Status | Meaning |
|---|---|
| 400 | Invalid request body or parameter |
| 401 | Missing, expired or revoked token |
| 403 | Token lacks the required scope or the plan does not include the feature |
| 404 | Resource not found |
| 409 | Idempotency key reused with a different body |
| 422 | Flow definition failed validation (for example more than the plan's step limit) |
| 429 | Rate limit exceeded |
| 500 and 503 | Server error; safe to retry with the same idempotency key |

Starting a run via `POST /flows/{id}/runs` is also limited to 20 concurrent runs per flow on Team, 100 on Business and 500 on Enterprise.
