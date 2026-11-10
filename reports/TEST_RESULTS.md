# Test Results — Commerce Business OS 1.0.0-beta.6

**Build:** TEAM-TEST-006  
**Schema:** 58

## Result

- Local verification assertions executed: **149**
- Passed: **149**
- Failed: **0**
- External live-provider acceptance groups skipped: **9**

The 149 local assertions comprise the 113 grouped beta.6 repair/regression checks recorded in `app/release_verification.json` plus a 36-check clean-install acceptance gate covering login, authenticated core routes, release truth, inventory authority, Local Preparation, Creative Studio local-vs-AI truth, Connections truth and real backup/restore UI flow.

## Verified locally

- compile/import sanity;
- release identity and documentation consistency;
- first-run initialization and locally generated fictional credentials;
- login/session;
- authenticated core routes including Home, Needs Attention, Recent Activity, Search, Products, Product Preparation, Creative Studio, Inventory, CRM, Tasks, Sales Pipeline, Orders, Fulfilments, Returns, Marketing, Campaigns, Connections, Data Ownership, Access Control, Reporting, System Health and Change History;
- canonical Contact/Task/Opportunity/Order/Product activity semantics and no relationship-mirror duplicates;
- Team Test Warehouse and product/location stock reconciliation;
- product archive/restore and inventory/order integrity;
- paid-order total reconciliation, reservation, fulfilment, return/refund and replay safety;
- invalid-state rejection for tested order/fulfilment/return paths;
- opportunity stage movement to Negotiation and persistence;
- Local Preparation Mode and `Prepare locally` when AI is not connected;
- Local video preparation separated from AI motion generation;
- roadmap integrations shown as Planning only with no fake Connect path;
- supported/unconfigured integrations shown as Setup Required;
- single-instance protection and restart persistence;
- real backup creation and isolated restore verification through authenticated controls;
- Reset Test Data and fresh fictional credentials;
- diagnostics export without passwords/tokens/private contact data;
- beta.5 → beta.6 tester-data preservation without schema increment;
- System Doctor: **Working — 0 Critical / 0 High**.

## External live acceptance not executed

No real credentials are bundled. Live acceptance remains **EXTERNAL SETUP REQUIRED** for Wix, Shopify, Meta/Facebook/Instagram, Google services/Google Ads, Microsoft 365/Outlook, WhatsApp Business, Stripe, external AI providers and MCP connectors.

Windows launcher logic was statically reviewed in this Linux verification environment; native Windows execution remains a platform acceptance item.

## Exact ZIP gate

The release ZIP was extracted into a separate verification directory and tested without using the development tree. Content checksums passed, first-run initialization and login succeeded, the 36-check exact-ZIP acceptance gate passed, System Doctor reported **0 Critical / 0 High**, backup + isolated restore verified, and stop/restart retained the workspace and verified-backup state.
