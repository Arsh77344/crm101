# Tester Guide — Commerce Business OS 1.0.0-beta.6

**Build:** TEAM-TEST-006  
**Schema:** 58

This build is for structured internal testing with fictional data. It is not a production deployment.

## What to test

Work through the application as a business user rather than only checking that pages open:

- Home and Needs Attention
- Recent Activity and Change History
- Products and Product Preparation
- Creative Studio
- Stock & Locations / Team Test Warehouse
- Contacts, Tasks and Customer history
- Sales Pipeline / Opportunities
- Orders, fulfilment and returns
- Marketing and Campaigns
- Business Connections
- System Health and System Doctor
- Backup/restore, restart and Reset Test Data

## Business-truth checks

When you create related records, their identities must remain separate:

- Contact → `CNT-...`
- Task → `TASK-...`
- Opportunity → its own opportunity/deal ID
- Order → `ORD-...`
- Product → `PRD-...`

A task related to a contact must still appear as a **Task** event, with the contact treated only as the related object.

Product-level stock must reconcile with canonical location stock. Seeded stock belongs to **Team Test Warehouse**.

## AI and local-mode truth

When the main AI provider is not validated, Product Preparation must show **Local Preparation Mode** and **Prepare locally**. Creative Studio must show local video preparation separately from optional AI motion. Local processing must never be presented as proof that an external AI provider is connected.

## Connections truth

Only implemented providers should expose actionable setup/connect flows. Roadmap-only providers belong under **Planning only**. A provider is **Connected** only after real validation; saved configuration alone is not a successful connection.

No live provider credentials are bundled with the team-test ZIP.

## Needs Attention versus system integrity

Needs Attention can contain normal business work such as an overdue follow-up, creative review, first-backup onboarding or a disconnected integration. System Doctor is reserved for integrity/reliability findings and should not classify ordinary owner work as a High database/system defect.

## Reporting a defect

For each issue record:

- page / object ID
- steps to reproduce
- expected result
- actual result
- Pass/Fail
- severity
- whether it persists after refresh
- whether it persists after restart
- screenshot if useful
- comments
