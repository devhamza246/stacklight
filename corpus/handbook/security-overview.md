# Security Overview

Owner: Security
Last reviewed: 2026-10-05

## Compliance
- SOC 2 Type II: the most recent report covers the period 1 January 2026 to 30 June 2026 and is available under NDA.
- ISO 27001 certification is planned for 2027; it is not yet held.
- Quillbase does not currently offer HIPAA Business Associate Agreements.

## Encryption
- Data in transit uses TLS 1.2 or higher; TLS 1.0 and 1.1 are rejected.
- Data at rest is encrypted with AES-256. Customer secrets stored in connections (API tokens for integrations) use envelope encryption with per-workspace keys managed in a cloud KMS and rotated every 90 days.

## Backups
Databases are backed up every 6 hours and backups are retained for 35 days. Restore drills run quarterly.

## Access controls
- Employees authenticate with SSO plus a hardware security key; passwords must be at least 14 characters.
- Production access is just-in-time, approved by a second engineer and expires after 4 hours.
- Customer data access by staff is logged and reviewed monthly.

## Testing
A third-party penetration test runs once a year (the latest was completed in March 2026); critical findings are fixed within 7 days and high findings within 30 days.
