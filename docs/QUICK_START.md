# Quick Start — Commerce Business OS 1.0.0-beta.6

**Build:** TEAM-TEST-006  
**Schema:** 58  
**ZIP:** `Commerce_Business_OS_1.0.0-beta.6_TEAM_TEST.zip`  
**Folder after extraction:** `Commerce_Business_OS_1.0.0-beta.6`

## Before you start

Install Python **3.12 or newer** if it is not already available. This team-test package uses the tester machine's Python runtime; it does not claim to bundle a verified self-contained macOS/Windows runtime.

## Start the CRM

1. Extract `Commerce_Business_OS_1.0.0-beta.6_TEAM_TEST.zip`.
2. Open the single `Commerce_Business_OS_1.0.0-beta.6` folder.
3. macOS: double-click `START_APP.command`. Windows: run `START_APP.bat`. Linux: run `START_APP.sh`.
4. Keep the launcher window open while testing.
5. On first launch, open `data/FIRST_RUN_CREDENTIALS.txt`.
6. Sign in with the generated **Owner** email and password.
7. Stop the CRM with Control+C in the launcher window.
8. Start it again with the same launcher. Your team-test data should persist.

## Expected offline/local states

- **Product Preparation:** when AI is not validated, the page must show **Local Preparation Mode** and a **Prepare locally** action.
- **Creative Studio:** local video preparation and optional AI motion are separate capabilities. Local video may be Ready while AI motion remains Not connected.
- **Business Connections:** roadmap-only providers are **Planning only** and must not expose fake Connect actions.
- **Supported but unconfigured connections:** show **Setup Required** or **Platform setup required** until real validation succeeds.
- **Inventory:** `Team Test Warehouse` is the fictional canonical location for seeded stock.
- **Backup:** a fresh workspace starts at **First backup required** until a backup is created and an isolated restore verification succeeds.

## System Doctor

Run `RUN_SYSTEM_DOCTOR.command` with the CRM closed. Doctor checks application/data integrity. Normal owner work such as creative review may appear in **Needs Attention**, but it should not be misreported as a High integrity failure merely because an owner action is pending.

## Reset fictional test data

Close the CRM and run `RESET_TEST_DATA.command`. Type `RESET` when prompted. The reset archives the previous local test database, recreates the fictional workspace, generates new local sign-in credentials, and returns backup readiness to **First backup required**.

## Diagnostics

Run `EXPORT_DIAGNOSTICS.command` with the CRM closed to create a support bundle. The bundle is intended to contain release/health information without secrets or customer-private data.
