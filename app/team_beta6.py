from __future__ import annotations
from pathlib import Path
import sqlite3
import team_beta5
import team_release_checks

SCHEMA_VERSION='58'
APP_VERSION='1.0.0-beta.6'
BUILD_ID='TEAM-TEST-006'


def upgrade_workspace(db_path: Path|str) -> dict:
    # beta.6 introduces no schema migration. Re-run the idempotent beta.5 repair,
    # then update only release metadata so legitimate tester data is preserved.
    changed={'beta5':team_beta5.upgrade_workspace(db_path),'release_marker':0}
    with sqlite3.connect(Path(db_path)) as con:
        for key,val in (
            ('team_release_schema',SCHEMA_VERSION),
            ('team_release_version',APP_VERSION),
            ('team_release_build',BUILD_ID),
        ):
            con.execute("INSERT OR REPLACE INTO settings(setting_key,setting_value) VALUES(?,?)",(key,val))
        con.commit()
    changed['release_marker']=1
    return changed


def initialise():
    import os
    path=os.environ.get('CRM_DB_PATH')
    return upgrade_workspace(path) if path else {}


def doctor_findings(connect):
    base=list(team_beta5.doctor_findings(connect))
    # beta.5 correctly owns schema/activity checks, but its release-marker expectation
    # is historical now. beta.6 replaces only those release-marker findings.
    findings=[x for x in base if x.get('check_key') not in {
        'team_release_schema_mismatch','team_release_marker_mismatch','team_release_marker_unreadable'
    }]
    try:
        with connect() as con:
            vals={r[0]:r[1] for r in con.execute("SELECT setting_key,setting_value FROM settings WHERE setting_key IN ('team_release_version','team_release_build','team_release_schema')")}
        expected={'team_release_version':APP_VERSION,'team_release_build':BUILD_ID,'team_release_schema':SCHEMA_VERSION}
        for key,want in expected.items():
            if str(vals.get(key) or '')!=want:
                findings.append({'check_key':'team_release_marker_mismatch','severity':'High','object_type':'release','object_id':key,'detail':f'{key} is {vals.get(key)!r}; expected {want}.'})
    except Exception as exc:
        findings.append({'check_key':'team_release_marker_unreadable','severity':'High','object_type':'release','object_id':'','detail':str(exc)[:500]})
    identity=team_release_checks.verify_release_identity()
    for item in identity['findings']:
        findings.append({'check_key':'release_identity_documentation_drift','severity':'High','object_type':'release','object_id':item.get('file',''),'detail':str(item)[:800]})
    # Regression check for the beta.6 RBAC repair: a role granted *.manage must
    # retain read access to that same business domain while admin-only routes stay
    # governed by their separate settings/integration permissions.
    try:
        import platform_core as pc
        for role,permission in (
            ('Sales','contacts.read'),('Sales','sales.read'),
            ('Administrator','contacts.read'),('Administrator','orders.read'),
        ):
            if not pc.can({'role':role},permission):
                findings.append({'check_key':'role_manage_read_implication_broken','severity':'High','object_type':'role','object_id':role,'detail':f'{role} cannot read {permission} even though the role has the corresponding manage capability.'})
    except Exception as exc:
        findings.append({'check_key':'role_permission_check_failed','severity':'High','object_type':'role','object_id':'','detail':str(exc)[:500]})
    return findings
