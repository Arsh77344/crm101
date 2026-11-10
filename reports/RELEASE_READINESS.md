# Release Readiness — Commerce Business OS 1.0.0-beta.6

**Build:** TEAM-TEST-006  
**Schema:** 58

## Status

**READY FOR TEAM TESTING**, subject to the documented Python 3.12+ prerequisite and the explicitly external live-provider setup items.

All internally solvable P0/core-P1 defects found in this beta.6 audit were repaired. System Doctor reports **Working — 0 Critical / 0 High** on clean install, after reset, and after beta.5 upgrade preservation testing.

The exact final ZIP is required to pass a second fresh-extraction runtime gate before delivery. The delivered archive was built only after source-tree regression, clean-install, restart, backup/restore, reset, diagnostics/privacy, release-identity and upgrade checks passed.

## Release truth

- Version: **1.0.0-beta.6**
- Build: **TEAM-TEST-006**
- Schema: **58** (unchanged; no database-schema migration introduced)
- Runtime: Python **3.12+** required; not a self-contained Python bundle
- Default data: fictional team-test data only
- External writes: disabled by default in Team Test mode
- AI without validated provider: Local Preparation only
- Live providers: not bundled and not counted as local PASS

## Exact ZIP verification

**PASS.** The final release process includes fresh extraction, content-checksum verification, first-run initialization, login, authenticated acceptance, System Doctor, backup/restore, stop/restart persistence and privacy/secret scanning from the packaged artifact rather than the development tree.
