# On-Call Handbook

Owner: Engineering
Last reviewed: 2026-07-30

- The primary on-call rotation is weekly and hands off every Monday at 10:00 UTC. A secondary engineer is paged after 10 minutes without acknowledgment.
- Pages are delivered through the paging tool to phone, SMS and push. Acknowledge within 5 minutes.
- On-call engineers receive a $400 stipend per week on call plus a day of comp time after any week with two or more night pages.
- Rotation swaps must be posted in `#oncall-swaps` at least 48 hours ahead.
- Before handing off, write the handoff note covering open incidents, flaky alerts and risky deploys.
- Do not deploy on Fridays after 14:00 UTC unless fixing an incident.
- Runbooks live in the `runbooks/` repository; every alert must link to a runbook entry.
- The team targets fewer than 5 pages per on-call week; sustained higher numbers trigger an alert-cleanup sprint.
