# Salesforce Integration Guide

Owner: Solutions Engineering
Last reviewed: 2026-07-07

Requires Team plan or above and a Salesforce edition with API access (Professional with API add-on, Enterprise, Unlimited).

- Quillbase polls Salesforce every 15 minutes for changes to objects you select. Maximum 10 synced objects per workspace.
- Connect with the "Quillbase for Salesforce" connected app using OAuth; the connecting user needs the "API Enabled" permission.
- Field mapping is configured per object. Custom fields ending in `__c` are supported; formula fields are read-only.
- Each sync consumes Salesforce API calls from your org. A typical workspace uses about 2,000 calls per day, so watch your org limit on Professional edition (15,000 calls per 24 hours by default).
- Deleted Salesforce records are soft-deleted in Quillbase for 30 days.
- Known limit: Quillbase cannot sync more than 200,000 records per object in the first import. Contact support for a staged import.
