# Integrations Overview

Owner: Product
Last reviewed: 2026-09-08

Quillbase ships with native integrations and a generic webhook/HTTP connector.

| Integration | Direction | Sync frequency | Plans |
|---|---|---|---|
| Slack | triggers and actions | real time | all |
| Salesforce | two-way | every 15 minutes | Team and above |
| HubSpot | two-way | every 10 minutes | Team and above |
| GitHub | triggers and actions | real time (webhooks) | all |
| Jira | triggers and actions | real time | Team and above |
| Zendesk | two-way | every 5 minutes | Team and above |
| Google Sheets | actions | on demand | all |
| Snowflake | export only | hourly | Business and above |

The Free plan allows 5 connected integrations in total. Connections are authenticated with OAuth wherever the vendor supports it; otherwise the API token is stored with envelope encryption. If a connection loses authorization, flows using it pause and the owner is emailed within 10 minutes.

Custom integrations can be built with the HTTP step (up to 6 MB response body) or the public API (see API Getting Started).
