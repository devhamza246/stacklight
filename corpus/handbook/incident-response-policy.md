# Incident Response Policy

Owner: Engineering
Last reviewed: 2026-10-20

## Severity levels
- **SEV1:** full outage or data loss/exposure affecting multiple customers.
- **SEV2:** significant degradation, such as run delays above 10 minutes or a failing core integration.
- **SEV3:** minor impact with a workaround.

## Roles
- The **Incident Commander (IC)** coordinates and makes decisions; the on-call engineer is IC by default for the first 15 minutes, then may hand over.
- The **Communications Lead** posts updates; the **Scribe** keeps the timeline.

## Timelines
- Page acknowledged within 5 minutes; an incident channel named `#inc-YYYYMMDD-short-name` is opened immediately.
- SEV1: first public status-page update within 15 minutes of declaration, then every 30 minutes until resolved. SEV2: first update within 30 minutes, then hourly.
- Customers affected by a suspected data exposure are notified within 72 hours of confirmation.
- A blameless postmortem is published within 5 business days of resolution for every SEV1 and SEV2.

The public status page is status.quillbase.example. Only the Communications Lead edits it.
