# Team Test Checklist — Commerce Business OS 1.0.0-beta.6

**Build:** TEAM-TEST-006  
**Schema:** 58

For each test record **Expected / Actual / Pass-Fail / Severity / Steps / Screenshot / Comments**.

- [ ] Fresh extraction starts through the supported launcher
- [ ] First-run credentials are generated locally and login succeeds
- [ ] Home metrics and their destinations agree
- [ ] Needs Attention classifies onboarding, owner work and system incidents correctly
- [ ] Recent Activity uses the correct canonical entity type and ID
- [ ] Contact history shows related Task/Opportunity/Order events without changing their identity
- [ ] Search returns the correct entity and destination
- [ ] Product Preparation shows Local Preparation Mode when AI is disconnected
- [ ] Product Preparation primary action says Prepare locally
- [ ] Creative Studio separates Local video preparation from AI motion generation
- [ ] Product create/edit/archive/restore persists after refresh/restart
- [ ] Team Test Warehouse exists and product/location inventory reconcile
- [ ] Inventory reservation/fulfilment movements reconcile where exercised
- [ ] Contact create/edit/search/sort/filter works
- [ ] Contact/Task/Opportunity/Order identities remain distinct
- [ ] Sales Pipeline stage movement persists after refresh/restart
- [ ] Order totals reconcile with lines and invalid states are rejected
- [ ] Return/refund state does not create impossible inventory/financial outcomes
- [ ] Marketing planning stops truthfully at Setup Required when providers are disconnected
- [ ] Planned providers expose no fake Connect action
- [ ] Supported unconfigured providers show Setup Required / Platform setup required
- [ ] First backup required → Create backup → Verify restore → Recovery verified
- [ ] System Health agrees with canonical incidents and backup state
- [ ] Run System Doctor; no unresolved P0/P1 integrity defect is reported
- [ ] Stop and restart; created/edited test records persist
- [ ] Reset Test Data recreates the fictional workspace and First backup required state
- [ ] Export Diagnostics creates a useful non-secret support bundle
