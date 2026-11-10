from __future__ import annotations
from pathlib import Path
import sqlite3
import team_beta3

SCHEMA_VERSION='57'
APP_VERSION='1.0.0-beta.4'
BUILD_ID='TEAM-TEST-004'

def upgrade_workspace(db_path: Path|str) -> dict:
    changed={'beta3': team_beta3.upgrade_workspace(db_path), 'release_marker':0}
    with sqlite3.connect(Path(db_path)) as con:
        con.execute("INSERT OR REPLACE INTO settings(setting_key,setting_value) VALUES('team_release_schema',?)",(SCHEMA_VERSION,))
        con.execute("INSERT OR REPLACE INTO settings(setting_key,setting_value) VALUES('team_release_version',?)",(APP_VERSION,))
        con.execute("INSERT OR REPLACE INTO settings(setting_key,setting_value) VALUES('team_release_build',?)",(BUILD_ID,))
        changed['release_marker']=1
        con.commit()
    return changed

def initialise():
    import os
    path=os.environ.get('CRM_DB_PATH')
    return upgrade_workspace(path) if path else {}

def doctor_findings(connect):
    findings=list(team_beta3.doctor_findings(connect))
    try:
        with connect() as con:
            vals={r[0]:r[1] for r in con.execute("SELECT setting_key,setting_value FROM settings WHERE setting_key IN ('team_release_version','team_release_build','team_release_schema')")}
        expected={'team_release_version':APP_VERSION,'team_release_build':BUILD_ID,'team_release_schema':SCHEMA_VERSION}
        for key,want in expected.items():
            if str(vals.get(key) or '')!=want:
                findings.append({'check_key':'team_release_marker_mismatch','severity':'High','object_type':'release','object_id':key,'detail':f'{key} is {vals.get(key)!r}; expected {want}.'})
    except Exception as exc:
        findings.append({'check_key':'team_release_marker_unreadable','severity':'High','object_type':'release','object_id':'','detail':str(exc)[:500]})
    return findings
