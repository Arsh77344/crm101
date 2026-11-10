# Commerce Business OS 1.0.0-beta.6 — Team Test

**Build:** TEAM-TEST-006  
**Schema:** 58  
**Package:** `Commerce_Business_OS_Updated_2026-11-01.zip`

This is the internal team-test build. It uses fictional sample data, creates local test credentials on first launch, and keeps external providers disconnected until a real account is configured and validated.

## Start

- macOS: double-click `START_APP.command`
- Windows: run `START_APP.bat`
- Linux: run `START_APP.sh`

Python **3.12 or newer** is an explicit prerequisite for this release. This package is not described as a self-contained bundled Python runtime.

On first launch, read `data/FIRST_RUN_CREDENTIALS.txt` and sign in with the generated **Owner** credentials. The credential file is created locally after extraction; it is not included in the shared ZIP.

Start with `docs/QUICK_START.md`, then use `docs/TESTER_GUIDE.md` and `docs/TEST_CHECKLIST.md` for structured testing.
