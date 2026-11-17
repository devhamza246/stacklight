# Data Residency and Retention

Owner: Security and Legal
Last reviewed: 2026-09-02

- Quillbase hosts customer data in two regions: US-East (Virginia) and EU-Frankfurt. The region is chosen when a workspace is created and cannot be changed afterwards; migrating requires creating a new workspace and exporting flows.
- Run logs are kept for the retention period of the plan (Free 7 days, Team 30 days, Business 365 days, Enterprise up to 7 years).
- When a workspace is deleted its data enters a 30-day grace period during which an owner can restore it. After 30 days it is purged from production, and from backups within a further 35 days.
- Individual data subject requests (access or deletion) are answered within 30 days; send them to privacy@quillbase.example.
- Customers can export all flows and run history as JSON or CSV from Settings > Data > Export. Exports are generated within 24 hours and download links expire after 7 days.
- Sub-processors are listed at quillbase.example/subprocessors; customers on Business and above are notified 30 days before a new sub-processor is added.
