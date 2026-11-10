from __future__ import annotations
from pathlib import Path
import sqlite3
import team_beta4

SCHEMA_VERSION='58'
APP_VERSION='1.0.0-beta.5'
BUILD_ID='TEAM-TEST-005'

MIRROR_ACTION_PREFIXES=('Task ','Bulk task ','Deal ','Order ','External order ')

def upgrade_workspace(db_path: Path|str) -> dict:
    changed={'beta4':team_beta4.upgrade_workspace(db_path),'relationship_mirrors_removed':0,'release_marker':0}
    with sqlite3.connect(Path(db_path)) as con:
        tables={r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if 'm42_changes' in tables:
            # beta.2 introduced Contact mirror rows for relationship visibility. They
            # duplicate canonical Task/Opportunity/Order events and can render misleading
            # entity/action pairs in Change History. Contact timelines now resolve the
            # canonical event through related_object_type/related_object_id instead.
            cur=con.execute("DELETE FROM m42_changes WHERE coalesce(event_scope,'business')='relationship'")
            changed['relationship_mirrors_removed']=cur.rowcount
        for key,val in (
            ('team_release_schema',SCHEMA_VERSION),
            ('team_release_version',APP_VERSION),
            ('team_release_build',BUILD_ID),
        ):
            con.execute("INSERT OR REPLACE INTO settings(setting_key,setting_value) VALUES(?,?)",(key,val))
        changed['release_marker']=1
        con.commit()
    return changed

def initialise():
    import os
    path=os.environ.get('CRM_DB_PATH')
    return upgrade_workspace(path) if path else {}

def doctor_findings(connect):
    base=list(team_beta4.doctor_findings(connect))
    findings=[x for x in base if x.get('check_key') not in {'team_release_schema_mismatch','team_release_marker_mismatch','team_release_marker_unreadable'}]
    try:
        with connect() as con:
            tables={r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if 'm42_changes' in tables:
                mirrors=con.execute("SELECT count(*) FROM m42_changes WHERE coalesce(event_scope,'business')='relationship'").fetchone()[0]
                if mirrors:
                    findings.append({'check_key':'duplicate_relationship_activity','severity':'Critical','object_type':'activity','object_id':'','detail':f'{mirrors} relationship mirror activity row(s) duplicate canonical business events.'})
                # Event semantics: action labels that describe a Task/Order/Opportunity
                # must use that business object as the event entity.
                semantic=con.execute("""SELECT id,object_type,object_id,action FROM m42_changes
                    WHERE coalesce(event_scope,'business')='business' AND (
                      (action LIKE 'Order %' AND object_type<>'Order') OR
                      (action LIKE 'Task %' AND object_type<>'Task') OR
                      ((action LIKE 'Deal %' OR action LIKE 'Stage changed%') AND object_type NOT IN ('Deal','Opportunity'))
                    ) LIMIT 25""").fetchall()
                for event_id,typ,ident,action in semantic:
                    findings.append({'check_key':'activity_action_entity_mismatch','severity':'Critical','object_type':'activity','object_id':event_id,'detail':f'{action} is attached to {typ} {ident}; event entity must be the object the action is about.'})
            vals={r[0]:r[1] for r in con.execute("SELECT setting_key,setting_value FROM settings WHERE setting_key IN ('team_release_version','team_release_build','team_release_schema')")}
        expected={'team_release_version':APP_VERSION,'team_release_build':BUILD_ID,'team_release_schema':SCHEMA_VERSION}
        for key,want in expected.items():
            if str(vals.get(key) or '')!=want:
                findings.append({'check_key':'team_release_marker_mismatch','severity':'High','object_type':'release','object_id':key,'detail':f'{key} is {vals.get(key)!r}; expected {want}.'})
    except Exception as exc:
        findings.append({'check_key':'team_release_marker_unreadable','severity':'High','object_type':'release','object_id':'','detail':str(exc)[:500]})
    return findings
