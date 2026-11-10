# Changelog

## 1.0.0-beta.6 — TEAM-TEST-006
- Unified current release identity and documentation on beta.6 / TEAM-TEST-006 / schema 58.
- Preserved beta.5 tester work during sibling-release upgrade discovery.
- Reclassified normal owner `Needs attention` process work so it no longer creates a false High integrity finding.
- Added a cross-platform single-instance workspace lock so a second launch cannot start duplicate workers against the same SQLite database.
- Fixed RBAC permission implication so domain `manage` grants include domain `read` without granting unrelated administrator settings.
- Fixed clean-install isolation so previous-release discovery cannot import an unrelated historical workspace from a broad ancestor directory.
- Re-verified canonical activity identity, inventory/order/return truth, idempotency, backup/restore, reset, restart, Local Preparation and truthful disconnected-provider states.

## 1.0.0-beta.5 — TEAM-TEST-005
- Removed duplicate relationship-mirror activity rows that could display Contact IDs beside Task/Order actions.
- Contact timelines now resolve related canonical Task/Opportunity/Order events directly.
- Added Doctor checks for duplicate relationship events and action/entity semantic mismatches.
- Preserved beta.4 inventory, AI truth, connection-state, order-layout and recovery fixes.

## 1.0.0-beta.4 — TEAM-TEST-004

- **Problem:** Creative Studio showed `AI video generation / Ready` while the workspace AI status was disconnected. **Root cause:** local video mode was treated as AI provider readiness. **Fix:** separate Local video preparation from AI motion provider readiness. **Test:** disconnected provider renders Local Ready + AI Not connected.
- **Problem:** Product Preparation could still be visually ambiguous in no-AI mode. **Root cause:** a preparation select remained visible even when only local processing was possible. **Fix:** explicit Local Preparation control + hidden local engine + Prepare locally CTA. **Test:** authenticated route contains no legacy Standard preparation/Prepare these products wording.
- **Problem:** roadmap providers filled the owner Connections screen as Coming soon cards. **Root cause:** planning state was rendered like an operational provider state. **Fix:** canonical Planning only state and collapsed planned-provider section with no Connect action. **Test:** owner route contains no Coming soon provider cards.
- **Problem:** Advanced provider setup displayed bare Not configured status. **Root cause:** low-level provider state leaked directly into operator UX. **Fix:** Platform setup required with clearer setup explanation.
- **Problem:** Orders table header could cover the first transaction row. **Root cause:** conflicting compact-table sticky-header CSS. **Fix:** Orders-specific non-sticky header rule.
- **Problem:** beta upgrade discovery assumed immediately adjacent release folders. **Root cause:** path search did not account for tester wrapper folders. **Fix:** portable one-level wrapper discovery without hard-coded user paths.

## 1.0.0-beta.3 — TEAM-TEST-003

- **Problem:** current release evidence could be classified stale. **Root cause:** legacy Doctor evidence contract. **Fix:** semantic product/version/build/schema evidence validation. **Test:** current evidence accepted; stale evidence rejected.
- **Problem:** verified backup could remain not ready. **Root cause:** legacy `Ready` comparison. **Fix:** canonical backup-state consumer. **Test:** NOT_CREATED onboarding and VERIFIED recovery transitions.
- **Problem:** seeded order financial header did not expose its proven line discount. **Root cause:** incomplete historical projection. **Fix:** evidence-backed subtotal/discount/shipping reconstruction. **Test:** order header equals immutable line totals.
- **Problem:** shipped/returned order lines could still display stale fulfilment/return projections. **Root cause:** historical projection not reconciled from shipment/return evidence. **Fix:** idempotent projection repair. **Test:** shipment/return evidence matches line metadata.
- **Problem:** campaign business-context activity could appear as generic System. **Root cause:** audit-backed event classifier lacked domain prefixes. **Fix:** domain-aware classification. **Test:** campaign event classified Marketing.
- **Problem:** System Health crashed after contextual recovery refactor. **Root cause:** missing readiness-module import. **Fix:** explicit import. **Test:** authenticated System Health HTTP 200 in broad route sweep.
- **Problem:** manually/imported new contacts generated legacy `CON-...` IDs. **Root cause:** old UID prefix remained in contact creation service. **Fix:** new contacts now generate `CNT-...`; beta.2 `CON-...` remains valid legacy data. **Test:** real HTTP contact creation returns CNT and survives restart.

## 1.0.0-beta.2 — TEAM-TEST-002

Corrected canonical activity identity, introduced Team Test Warehouse/location inventory, contextual recovery actions, explicit Local Preparation Mode, pipeline scrolling guidance and first-backup onboarding.
- **Problem:** Reset Test Data could leave a verified backup archive in the active recovery set while replacing the database, causing the fresh workspace to appear `CREATED_NOT_VERIFIED` instead of `First backup required`. **Root cause:** reset archived the database but not workspace-bound full-backup artifacts. **Fix:** reset now moves prior full backups into a timestamped reset-history directory before creating the fresh workspace. **Test:** reset-after-backup returns current recovery state to NOT_CREATED while preserving prior artifact history.
