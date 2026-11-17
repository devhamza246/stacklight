# Postmortem Template and Process

Owner: Engineering
Last reviewed: 2026-09-09

Postmortems are blameless: we examine systems and decisions, not individuals.

## Process
1. The Incident Commander assigns an author within 1 business day.
2. A draft is ready by business day 3 and a review meeting held by business day 4.
3. The final postmortem is published internally by business day 5. For SEV1 incidents a customer-facing summary is published on the status page within 10 business days.

## Template sections
Summary, Impact (customers affected, duration, runs lost), Timeline (UTC), Root cause, What went well, What went poorly, and Action items with an owner and due date.

Action items are tracked in the `POSTMORTEM` Jira project. Items marked P0 must be completed within 30 days; the Engineering Director reviews overdue items monthly.
