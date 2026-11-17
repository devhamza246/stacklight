# Plan Limits Reference

Owner: Product
Last reviewed: 2026-09-14

This is the authoritative table of hard limits per plan.

| Limit | Free | Team | Business | Enterprise |
|---|---|---|---|---|
| Steps per flow | 10 | 50 | 50 | 50 |
| Active flows | 5 | 100 | unlimited | unlimited |
| Run timeout | 2 minutes | 5 minutes | 5 minutes | 15 minutes |
| Max payload size per run | 1 MB | 6 MB | 6 MB | 25 MB |
| Run log retention | 7 days | 30 days | 365 days | 7 years (optional audit add-on) |
| Connected integrations | 5 | unlimited | unlimited | unlimited |
| API rate limit | 60 requests/min | 300 requests/min | 1,200 requests/min | 6,000 requests/min (default) |
| Webhook endpoints | 2 | 20 | 100 | 500 |
| Workspaces per account | 1 | 3 | 10 | unlimited |

When a workspace exceeds its included runs on Free, flows pause until the next calendar month; Free never incurs overage charges. A paused flow shows the banner "Run quota reached" and resumes automatically on the 1st of the month at 00:00 UTC.
