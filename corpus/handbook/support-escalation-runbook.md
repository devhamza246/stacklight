# Support Escalation Runbook

Owner: Customer Support
Last reviewed: 2026-08-04

Internal runbook for support agents.

## Tiers
- **L1:** frontline agents. Resolve from documentation; target 80% of tickets closed at L1.
- **L2:** senior support engineers. Take tickets L1 cannot resolve within 4 business hours.
- **L3:** the engineering on-call. L2 hands off with reproduction steps, workspace ID and run IDs.

## Escalation rules
- Any P1 is paged to L2 immediately and to engineering on-call if not mitigated within 30 minutes.
- A P2 ticket unresolved after 8 business hours moves up one tier.
- Tickets from Enterprise customers are tagged `ENT` and are visible to the account's CSM.
- Customers who ask to speak with a manager are routed to the Support Manager on duty within one business day.

## Money and exceptions
- Agents may approve refunds and credits up to $500.
- Support managers approve $500.01 to $5,000.
- Refunds above $5,000 need written sign-off from the Finance lead.
- Never promise a feature date; refer roadmap questions to the account's CSM or sales rep.
- Data deletion requests go to privacy@quillbase.example and are not handled in tickets.
