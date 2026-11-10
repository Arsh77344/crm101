# Release Notes — Commerce Business OS 1.0.0-beta.6

**Build:** TEAM-TEST-006  
**Schema:** 58

This release is a reliability/documentation repair cycle for team testing rather than a feature expansion.

## Repairs
- **Clean-install isolation:** previous-release discovery is now limited to the extraction neighbourhood (and a parent only for an obvious Team Test wrapper), preventing unrelated historical/audit workspaces elsewhere in the directory tree from being imported into a fresh install.

- **Single-instance reliability:** a second launcher invocation against the same workspace is rejected rather than starting a second server/worker on another port; OS-held locking releases automatically after a crash.
- **Role access:** `*.manage` permissions now correctly include the corresponding `*.read` capability, so Sales/Administrator roles can open the domains they manage without receiving unrelated Settings or Users & Roles access.


- **Release identity:** current tester documentation, application metadata and launcher wording now use one beta.6 / TEAM-TEST-006 identity with schema 58.
- **Upgrade preservation:** the launcher now discovers the immediately previous team-test workspace and can preserve tester-created beta data instead of skipping the latest prior release.
- **System Doctor classification:** ordinary business-owner work in a `Needs attention` process is no longer promoted to a High integrity defect solely because an action is pending. A genuinely `Blocked` process still triggers a High Doctor finding.
- **Release verification:** beta.6 adds an automated current-release identity/documentation check used by System Doctor and release verification.
- **Reset consistency:** Reset Test Data now applies the beta.6 release marker while retaining the same schema because no database-schema migration was introduced.

## Preserved behavior

Canonical activity identity, Team Test Warehouse inventory authority, truthful Local Preparation/AI states, connection-state truth, backup/restore safeguards and replay-safety foundations remain in place.
