from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import os
import re
import secrets
from pathlib import Path
from typing import Any

import marketing as m
import db_layer
import runtime_config as rc
import v35_truth as truth

ROOT = Path(__file__).resolve().parent

SCHEMA = r'''
CREATE TABLE IF NOT EXISTS v13_workspaces(
 id TEXT PRIMARY KEY,
 name TEXT NOT NULL,
 default_currency TEXT DEFAULT 'INR',
 default_language TEXT DEFAULT 'English',
 status TEXT DEFAULT 'Active',
 created_at TEXT DEFAULT CURRENT_TIMESTAMP,
 updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS v13_entity_workspace(
 entity_type TEXT NOT NULL,
 entity_id TEXT NOT NULL,
 workspace_id TEXT NOT NULL,
 PRIMARY KEY(entity_type,entity_id)
);
CREATE TABLE IF NOT EXISTS v13_events(
 id TEXT PRIMARY KEY,
 event_type TEXT NOT NULL,
 entity_type TEXT,
 entity_id TEXT,
 payload_json TEXT DEFAULT '{}',
 dedupe_key TEXT UNIQUE,
 correlation_id TEXT,
 causation_id TEXT,
 status TEXT DEFAULT 'Pending',
 error TEXT DEFAULT '',
 occurred_at TEXT DEFAULT CURRENT_TIMESTAMP,
 processed_at TEXT
);
CREATE INDEX IF NOT EXISTS v13_events_status ON v13_events(status,occurred_at);
CREATE INDEX IF NOT EXISTS v13_events_entity ON v13_events(entity_type,entity_id,occurred_at);
CREATE TABLE IF NOT EXISTS v13_automation_rules(
 id TEXT PRIMARY KEY,
 name TEXT NOT NULL,
 trigger_event TEXT NOT NULL,
 condition_json TEXT DEFAULT '{}',
 action_type TEXT NOT NULL,
 action_json TEXT DEFAULT '{}',
 delay_seconds INTEGER DEFAULT 0,
 measurement_key TEXT DEFAULT '',
 automation_level INTEGER DEFAULT 2,
 enabled INTEGER DEFAULT 1,
 created_at TEXT DEFAULT CURRENT_TIMESTAMP,
 updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS v13_rules_trigger ON v13_automation_rules(trigger_event,enabled);
CREATE TABLE IF NOT EXISTS v13_rule_runs(
 id TEXT PRIMARY KEY,
 rule_id TEXT NOT NULL,
 event_id TEXT NOT NULL,
 outcome TEXT NOT NULL,
 detail TEXT,
 created_at TEXT DEFAULT CURRENT_TIMESTAMP,
 UNIQUE(rule_id,event_id)
);
CREATE TABLE IF NOT EXISTS v13_pipeline_runs(
 id TEXT PRIMARY KEY,
 product_id TEXT NOT NULL,
 status TEXT DEFAULT 'Running',
 automation_level INTEGER DEFAULT 2,
 target_channels_json TEXT DEFAULT '[]',
 started_at TEXT DEFAULT CURRENT_TIMESTAMP,
 finished_at TEXT,
 summary_json TEXT DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS v13_pipeline_product ON v13_pipeline_runs(product_id,started_at);
CREATE TABLE IF NOT EXISTS v13_pipeline_steps(
 id TEXT PRIMARY KEY,
 run_id TEXT NOT NULL,
 step_no INTEGER NOT NULL,
 step_key TEXT NOT NULL,
 label TEXT NOT NULL,
 status TEXT NOT NULL,
 detail TEXT,
 action_url TEXT,
 created_at TEXT DEFAULT CURRENT_TIMESTAMP,
 UNIQUE(run_id,step_key)
);
CREATE TABLE IF NOT EXISTS v13_quality_checks(
 id TEXT PRIMARY KEY,
 entity_type TEXT NOT NULL,
 entity_id TEXT NOT NULL,
 check_type TEXT NOT NULL,
 score REAL,
 confidence TEXT NOT NULL,
 status TEXT NOT NULL,
 issues_json TEXT DEFAULT '[]',
 evidence_json TEXT DEFAULT '{}',
 created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS v13_quality_entity ON v13_quality_checks(entity_type,entity_id,created_at);
CREATE TABLE IF NOT EXISTS v13_ai_usage(
 id TEXT PRIMARY KEY,
 task_key TEXT NOT NULL,
 provider TEXT NOT NULL,
 model TEXT,
 object_type TEXT,
 object_id TEXT,
 status TEXT NOT NULL,
 input_units INTEGER DEFAULT 0,
 output_units INTEGER DEFAULT 0,
 image_count INTEGER DEFAULT 0,
 video_seconds REAL DEFAULT 0,
 estimated_cost REAL DEFAULT 0,
 currency TEXT DEFAULT 'USD',
 error TEXT DEFAULT '',
 created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS v13_ai_usage_date ON v13_ai_usage(created_at,task_key,status);
CREATE TABLE IF NOT EXISTS v13_ai_budgets(
 scope TEXT PRIMARY KEY,
 max_calls INTEGER DEFAULT 0,
 max_estimated_cost REAL DEFAULT 0,
 currency TEXT DEFAULT 'USD',
 warn_percent INTEGER DEFAULT 80,
 updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS v13_consent_events(
 id TEXT PRIMARY KEY,
 contact_id TEXT NOT NULL,
 channel TEXT NOT NULL,
 state TEXT NOT NULL,
 source TEXT,
 evidence TEXT,
 jurisdiction TEXT,
 occurred_at TEXT DEFAULT CURRENT_TIMESTAMP,
 recorded_by TEXT,
 created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS v13_consent_contact ON v13_consent_events(contact_id,channel,occurred_at);
CREATE TABLE IF NOT EXISTS v13_incidents(
 id TEXT PRIMARY KEY,
 source TEXT NOT NULL,
 severity TEXT NOT NULL,
 title TEXT NOT NULL,
 detail TEXT,
 recovery TEXT,
 status TEXT DEFAULT 'Open',
 entity_type TEXT,
 entity_id TEXT,
 created_at TEXT DEFAULT CURRENT_TIMESTAMP,
 resolved_at TEXT, dedupe_key TEXT UNIQUE, first_seen TEXT DEFAULT CURRENT_TIMESTAMP, last_seen TEXT DEFAULT CURRENT_TIMESTAMP, occurrence_count INTEGER DEFAULT 1, latest_error TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS v13_incidents_status ON v13_incidents(status,severity,created_at);
CREATE TABLE IF NOT EXISTS v13_capability_checks(
 capability_key TEXT PRIMARY KEY,
 label TEXT NOT NULL,
 status TEXT NOT NULL,
 detail TEXT,
 action_url TEXT,
 checked_at TEXT DEFAULT CURRENT_TIMESTAMP
);
'''

DEFAULT_RULES = [
    ('RULE-PRODUCT-PIPELINE','New product → prepare launch','PRODUCT_CREATED','RUN_PRODUCT_PIPELINE',2),
    ('RULE-ORDER-RETENTION','Paid order → retention plan','ORDER_PLACED','POST_PURCHASE_RECOMMENDATION',2),
    ('RULE-INVENTORY-LOW','Low inventory → owner exception','INVENTORY_LOW','OWNER_RECOMMENDATION',1),
    ('RULE-MESSAGE-INBOUND','Inbound message → human follow-up','MESSAGE_RECEIVED','CREATE_TASK',2),
    ('RULE-QC-LOW','Low-confidence AI/QC → approval','QUALITY_REVIEW_REQUIRED','CREATE_APPROVAL',2),
]

UNVERIFIED_CLAIMS = [
    r'\bpure\s+silk\b', r'\b100\s*%\s*silk\b', r'\bhandloom\b', r'\bhand[- ]?woven\b',
    r'\bgi[- ]?certified\b', r'\bgeographical indication\b', r'\breal\s+gold\b', r'\breal\s+silver\b',
    r'\bauthentic\b', r'\bgenuine\b', r'\bcertified\b', r'\bmade\s+in\s+banaras\b', r'\bmade\s+in\s+varanasi\b'
]


def uid(prefix: str) -> str:
    return prefix + '-' + secrets.token_hex(8).upper()


def initialise() -> None:
    with m.connect() as con:
        con.executescript(SCHEMA)
        cols={r['name'] for r in con.execute('PRAGMA table_info(v13_automation_rules)').fetchall()}
        if 'delay_seconds' not in cols:con.execute('ALTER TABLE v13_automation_rules ADD COLUMN delay_seconds INTEGER DEFAULT 0')
        if 'measurement_key' not in cols:con.execute("ALTER TABLE v13_automation_rules ADD COLUMN measurement_key TEXT DEFAULT ''")
        con.execute("INSERT OR IGNORE INTO v13_workspaces(id,name,default_currency,default_language) VALUES('WS-DEFAULT','Primary business',?,?)",
                    ((m.settings().get('default_currency') or 'INR'), 'English'))
        for rid,name,trigger,action,level in DEFAULT_RULES:
            con.execute('''INSERT OR IGNORE INTO v13_automation_rules(id,name,trigger_event,action_type,automation_level,enabled)
                           VALUES(?,?,?,?,?,1)''',(rid,name,trigger,action,level))
        defaults=[('daily',50,0.0),('monthly',1000,0.0),('daily_image',10,0.0),('daily_video',3,0.0)]
        for scope,calls,cost in defaults:
            con.execute('INSERT OR IGNORE INTO v13_ai_budgets(scope,max_calls,max_estimated_cost,currency,warn_percent) VALUES(?,?,?,?,80)',(scope,calls,cost,'USD'))
        for k,v in {
            'v13_default_automation_level':'2',
            'v13_default_channels':'Website,Instagram,Facebook,Meta Ads,Google Ads,Email,WhatsApp',
            'v13_default_market':'United Kingdom',
            'v13_default_language':'English',
            'v13_auto_product_qc':'1',
            'v13_auto_local_assets':'1',
            'v13_auto_creative_plan':'1',
            'v13_auto_paid_ai':'0',
            'v13_require_low_confidence_approval':'1',
        }.items():
            con.execute('INSERT OR IGNORE INTO settings(setting_key,setting_value) VALUES(?,?)',(k,v))
    # Existing V52/V53 workspaces need additive columns before any later
    # readiness/repair code orders or updates incidents by last_seen.
    _ensure_v53_incident_columns()


def setting(key: str, default: str='') -> str:
    row=m.one('SELECT setting_value FROM settings WHERE setting_key=?',(key,))
    return (row or {}).get('setting_value') or default


def save_settings(values: dict[str,Any]) -> None:
    level=int(values.get('automation_level') or setting('v13_default_automation_level','2'))
    if level not in {1,2,3,4}: raise ValueError('Automation level must be 1, 2, 3 or 4.')
    channels=','.join(dict.fromkeys(x.strip() for x in str(values.get('default_channels') or '').split(',') if x.strip()))[:1000]
    with m.connect() as con:
        pairs={
            'v13_default_automation_level':str(level),
            'v13_default_channels':channels or setting('v13_default_channels'),
            'v13_default_market':str(values.get('default_market') or setting('v13_default_market','United Kingdom'))[:160],
            'v13_default_language':str(values.get('default_language') or setting('v13_default_language','English'))[:80],
            'v13_auto_product_qc':'1' if str(values.get('auto_product_qc','1'))=='1' else '0',
            'v13_auto_local_assets':'1' if str(values.get('auto_local_assets','1'))=='1' else '0',
            'v13_auto_creative_plan':'1' if str(values.get('auto_creative_plan','1'))=='1' else '0',
            'v13_auto_paid_ai':'1' if str(values.get('auto_paid_ai','0'))=='1' else '0',
            'v13_require_low_confidence_approval':'1' if str(values.get('require_low_confidence_approval','1'))=='1' else '0',
        }
        for k,v in pairs.items():con.execute('INSERT OR REPLACE INTO settings VALUES(?,?)',(k,v))


def workspace_id() -> str:
    initialise();return 'WS-DEFAULT'


def assign_entity(entity_type: str, entity_id: str, ws: str='WS-DEFAULT') -> None:
    initialise()
    if not entity_type or not entity_id:return
    with m.connect() as con:
        con.execute('''INSERT INTO v13_entity_workspace(entity_type,entity_id,workspace_id) VALUES(?,?,?)
                       ON CONFLICT(entity_type,entity_id) DO UPDATE SET workspace_id=excluded.workspace_id''',(entity_type,entity_id,ws))


def emit_event(event_type: str, entity_type: str='', entity_id: str='', payload: dict|None=None,
               dedupe_key: str='', correlation_id: str='', causation_id: str='') -> str:
    initialise();eid=uid('EV13');corr=correlation_id or eid
    try:
        with m.connect() as con:
            con.execute('''INSERT INTO v13_events(id,event_type,entity_type,entity_id,payload_json,dedupe_key,correlation_id,causation_id)
                           VALUES(?,?,?,?,?,?,?,?)''',(eid,event_type,entity_type,entity_id,json.dumps(payload or {},ensure_ascii=False),dedupe_key or None,corr,causation_id))
    except Exception:
        if dedupe_key:
            row=m.one('SELECT id FROM v13_events WHERE dedupe_key=?',(dedupe_key,))
            if row:return row['id']
        raise
    try:
        import durable_worker as dw
        dw.enqueue('v13.event.dispatch',{'event_id':eid},priority=50,idempotency_key='event:'+eid)
    except Exception as exc:
        try:
            incident('automation','Warning','Event queued without worker dispatch',str(exc),'The event remains Pending and will be picked up by maintenance. Check worker health if this repeats.',entity_type,entity_id)
        except Exception:
            pass
        try:
            import observability
            observability.log('event.enqueue_failed',event_id=eid,event_type=event_type,error=str(exc))
        except Exception:
            pass
    return eid


def _event(event_id: str) -> dict:
    row=m.one('SELECT * FROM v13_events WHERE id=?',(event_id,))
    if not row:raise ValueError('Event not found.')
    return row


def _ensure_v53_incident_columns() -> None:
    """Upgrade pre-V53 incident tables safely, including populated SQLite tables.

    SQLite rejects ``ALTER TABLE .. ADD COLUMN .. DEFAULT CURRENT_TIMESTAMP``
    when the table already contains rows. Earlier migrations swallowed that error,
    leaving ``first_seen``/``last_seen`` absent. Add timestamp columns without a
    non-constant default, then backfill them from existing history. Fresh databases
    still receive the defaults from ``SCHEMA`` above.
    """
    if not m.table_exists('v13_incidents'):
        return
    if db_layer.USING_POSTGRES:
        existing={str(r.get('column_name')) for r in m.rows("SELECT column_name FROM information_schema.columns WHERE table_name='v13_incidents'")}
    else:
        existing={str(r.get('name')) for r in m.rows('PRAGMA table_info(v13_incidents)')}
    # Use migration-safe definitions. Application writes explicitly set the
    # timestamps; the CREATE TABLE schema retains defaults for fresh databases.
    cols=[('dedupe_key','TEXT'),('first_seen','TEXT'),('last_seen','TEXT'),('occurrence_count','INTEGER DEFAULT 1'),('latest_error',"TEXT DEFAULT ''")]
    with m.connect() as con:
        for col,typ in cols:
            if col not in existing:
                con.execute(f'ALTER TABLE v13_incidents ADD COLUMN {col} {typ}')
        # Preserve historical time as closely as possible and make the migrated
        # rows immediately safe for ORDER BY/coalesce queries.
        con.execute("UPDATE v13_incidents SET first_seen=coalesce(first_seen,created_at,CURRENT_TIMESTAMP)")
        con.execute("UPDATE v13_incidents SET last_seen=coalesce(last_seen,resolved_at,created_at,first_seen,CURRENT_TIMESTAMP)")
        con.execute("UPDATE v13_incidents SET occurrence_count=coalesce(occurrence_count,1), latest_error=coalesce(nullif(latest_error,''),detail,'')")
        con.execute('CREATE UNIQUE INDEX IF NOT EXISTS v13_incidents_dedupe ON v13_incidents(dedupe_key)')


def incident(source: str, severity: str, title: str, detail: str='', recovery: str='', entity_type: str='', entity_id: str='', dedupe_key: str='') -> str:
    """Canonical operational incident. Replay updates one card instead of flooding Needs Attention."""
    initialise();_ensure_v53_incident_columns();sev=severity if severity in {'Info','Warning','Error','Critical'} else 'Error'
    stable=dedupe_key or hashlib.sha256((source+'|'+entity_type+'|'+entity_id+'|'+title).encode()).hexdigest()
    iid=uid('INC')
    with m.connect() as con:
        con.execute('''INSERT INTO v13_incidents(id,source,severity,title,detail,recovery,status,entity_type,entity_id,dedupe_key,first_seen,last_seen,occurrence_count,latest_error)
                       VALUES(?,?,?,?,?,?,'Open',?,?,?,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP,1,?)
                       ON CONFLICT(dedupe_key) DO UPDATE SET source=excluded.source,severity=excluded.severity,title=excluded.title,detail=excluded.detail,recovery=excluded.recovery,status='Open',entity_type=excluded.entity_type,entity_id=excluded.entity_id,resolved_at=NULL,last_seen=CURRENT_TIMESTAMP,occurrence_count=coalesce(v13_incidents.occurrence_count,1)+1,latest_error=excluded.latest_error''',
                    (iid,source[:100],sev,title[:240],detail[:4000],recovery[:2000],entity_type[:80],entity_id[:160],stable,detail[:4000]))
        row=con.execute('SELECT id FROM v13_incidents WHERE dedupe_key=?',(stable,)).fetchone()
        return row['id']



def reconcile_incidents() -> dict:
    """Collapse historical duplicate open incidents into one canonical row per business fault."""
    initialise();_ensure_v53_incident_columns()
    rows=m.rows("SELECT * FROM v13_incidents WHERE status='Open' ORDER BY created_at,id")
    groups={}
    for row in rows:
        stable=row.get('dedupe_key') or hashlib.sha256((str(row.get('source') or '')+'|'+str(row.get('entity_type') or '')+'|'+str(row.get('entity_id') or '')+'|'+str(row.get('title') or '')).encode()).hexdigest()
        groups.setdefault(stable,[]).append(row)
    collapsed=0
    with m.connect() as con:
        for stable,grp in groups.items():
            keep=grp[-1];count=sum(int(x.get('occurrence_count') or 1) for x in grp)
            try:
                con.execute("UPDATE v13_incidents SET dedupe_key=?,occurrence_count=?,first_seen=?,last_seen=?,latest_error=? WHERE id=?",
                            (stable,count,grp[0].get('created_at') or None,keep.get('last_seen') or keep.get('created_at') or None,keep.get('latest_error') or keep.get('detail') or '',keep['id']))
            except Exception:
                # A canonical row may already own this dedupe key; use it as keeper.
                owner=con.execute('SELECT id,occurrence_count FROM v13_incidents WHERE dedupe_key=?',(stable,)).fetchone()
                if owner:
                    keep_id=owner['id'];con.execute('UPDATE v13_incidents SET occurrence_count=coalesce(occurrence_count,1)+?,last_seen=CURRENT_TIMESTAMP WHERE id=?',(count,keep_id));keep=dict(keep);keep['id']=keep_id
            for old in grp:
                if old['id']==keep['id']:continue
                con.execute("UPDATE v13_incidents SET status='Resolved',resolved_at=CURRENT_TIMESTAMP WHERE id=? AND status='Open'",(old['id'],));collapsed+=1
    return {'open_groups':len(groups),'collapsed':collapsed}

def resolve_incident(iid: str) -> None:
    with m.connect() as con:con.execute("UPDATE v13_incidents SET status='Resolved',resolved_at=CURRENT_TIMESTAMP WHERE id=?",(iid,))



def _conditions_match(rule: dict, event: dict) -> tuple[bool,str]:
    """Evaluate a small auditable condition language; unknown keys fail closed."""
    try:cond=json.loads(rule.get('condition_json') or '{}')
    except Exception:return False,'Invalid condition JSON.'
    if not cond:return True,'No conditions.'
    allowed={'entity_type','entity_id','payload_equals','payload_in'}
    unknown=set(cond)-allowed
    if unknown:return False,'Unsupported condition key(s): '+', '.join(sorted(unknown))
    if cond.get('entity_type') and str(event.get('entity_type') or '')!=str(cond['entity_type']):return False,'Entity type does not match.'
    if cond.get('entity_id') and str(event.get('entity_id') or '')!=str(cond['entity_id']):return False,'Entity ID does not match.'
    try:payload=json.loads(event.get('payload_json') or '{}')
    except Exception:payload={}
    for key,want in (cond.get('payload_equals') or {}).items():
        if payload.get(key)!=want:return False,f'Payload condition {key} does not match.'
    for key,values in (cond.get('payload_in') or {}).items():
        if payload.get(key) not in (values if isinstance(values,list) else [values]):return False,f'Payload value {key} is not in the allowed set.'
    return True,'Conditions matched.'


def save_rule(data: dict, rule_id: str='') -> str:
    initialise();name=str(data.get('name') or '').strip();trigger=str(data.get('trigger_event') or '').strip().upper();action=str(data.get('action_type') or '').strip().upper()
    if not name or not trigger or not action:raise ValueError('Rule name, trigger and action are required.')
    allowed_actions={'RUN_PRODUCT_PIPELINE','POST_PURCHASE_RECOMMENDATION','OWNER_RECOMMENDATION','CREATE_TASK','CREATE_APPROVAL'}
    if action not in allowed_actions:raise ValueError('Choose a supported automation action.')
    level=max(1,min(4,int(data.get('automation_level') or 2)));delay=max(0,min(30*24*3600,int(data.get('delay_seconds') or 0)))
    cond=data.get('condition_json') or '{}'
    if isinstance(cond,dict):cond=json.dumps(cond)
    try:json.loads(cond)
    except Exception:raise ValueError('Conditions must be valid JSON.') from None
    rid=rule_id or uid('RULE')
    with m.connect() as con:
        con.execute('''INSERT INTO v13_automation_rules(id,name,trigger_event,condition_json,action_type,action_json,delay_seconds,measurement_key,automation_level,enabled)
                       VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name,trigger_event=excluded.trigger_event,condition_json=excluded.condition_json,
                       action_type=excluded.action_type,action_json=excluded.action_json,delay_seconds=excluded.delay_seconds,measurement_key=excluded.measurement_key,
                       automation_level=excluded.automation_level,enabled=excluded.enabled,updated_at=CURRENT_TIMESTAMP''',
                    (rid,name[:200],trigger[:100],cond,action,'{}',delay,str(data.get('measurement_key') or '')[:120],level,1 if str(data.get('enabled','1'))!='0' else 0))
    return rid


def execute_delayed_rule(rule_id: str,event_id: str) -> str:
    rule=m.one('SELECT * FROM v13_automation_rules WHERE id=?',(rule_id,));event=_event(event_id)
    if not rule or not rule.get('enabled'):return 'Skipped: rule no longer enabled.'
    matched,why=_conditions_match(rule,event)
    if not matched:detail='Skipped: '+why;outcome='Skipped'
    else:
        try:detail=_run_rule(rule,event);outcome='Completed'
        except Exception as exc:
            detail=str(exc);outcome='Failed';incident('automation','Error','Delayed automation rule failed',f"{rule['name']}: {exc}",'Review the event and retry the rule.',event.get('entity_type') or '',event.get('entity_id') or '',dedupe_key='delayed-rule:'+str(rule_id)+':'+str(event.get('entity_type') or '')+':'+str(event.get('entity_id') or ''))
    with m.connect() as con:
        existing=con.execute('SELECT id FROM v13_rule_runs WHERE rule_id=? AND event_id=?',(rule_id,event_id)).fetchone()
        if existing:con.execute('UPDATE v13_rule_runs SET outcome=?,detail=? WHERE id=?',(outcome,detail[:3000],existing[0]))
        else:con.execute('INSERT INTO v13_rule_runs(id,rule_id,event_id,outcome,detail) VALUES(?,?,?,?,?)',(uid('RR'),rule_id,event_id,outcome,detail[:3000]))
    return detail

def _run_rule(rule: dict, event: dict) -> str:
    action=rule['action_type'];entity_type=event.get('entity_type') or '';entity_id=event.get('entity_id') or ''
    payload=json.loads(event.get('payload_json') or '{}')
    if action=='RUN_PRODUCT_PIPELINE':
        if entity_type!='product' or not entity_id:return 'Skipped: event is not a product.'
        level=int(rule.get('automation_level') or 2)
        # Level 1 is recommend only; levels 2-4 can prepare the pipeline.
        if level<=1:
            import business_os as bos
            bos.recommendation('Product','Prepare '+product_label(entity_id),'A new product is ready for the automated launch-preparation workflow.','High','/product-workspace/'+entity_id,dedupe_key='v13-new-product:'+entity_id)
            return 'Recommendation created.'
        launch_product_pipeline(entity_id,automation_level=level)
        return 'Product launch-preparation pipeline started.'
    if action=='POST_PURCHASE_RECOMMENDATION':
        import business_os as bos
        bos.recommendation('Retention','Prepare post-purchase journey','A completed purchase can trigger confirmation, review, care guidance, cross-sell and repeat-purchase planning.','Medium','/orders',dedupe_key='v13-postpurchase:'+entity_id)
        return 'Retention recommendation created.'
    if action=='OWNER_RECOMMENDATION':
        import business_os as bos
        bos.recommendation('Inventory','Review low stock','Available inventory has reached the configured reorder point.','High','/locations',dedupe_key='v13-low-stock:'+entity_id)
        return 'Inventory exception created.'
    if action=='CREATE_TASK':
        cid=entity_id if entity_type=='contact' else str(payload.get('contact_id') or '')
        if not cid:return 'Skipped: no contact.'
        existing=m.one("SELECT id FROM m4_tasks WHERE contact_id=? AND status='Open' AND title='Respond to inbound customer message' ORDER BY created_at DESC LIMIT 1",(cid,))
        if not existing:
            with m.connect() as con:
                con.execute("INSERT INTO m4_tasks(id,title,contact_id,due_date,status) VALUES(?,?,?,date('now'),'Open')",(m.uid('TASK'),'Respond to inbound customer message',cid))
        return 'Follow-up task exists.'
    if action=='CREATE_APPROVAL':
        import platform_core as pc
        pc.approval('Quality review',entity_type,entity_id,'Low-confidence output requires owner review.','High','System')
        return 'Approval requested.'
    return 'Skipped: unsupported action '+action


def dispatch_event(event_id: str) -> dict:
    initialise();event=_event(event_id)
    if event['status']=='Processed':return {'processed':0,'skipped':1}
    rules=m.rows('SELECT * FROM v13_automation_rules WHERE trigger_event=? AND enabled=1 ORDER BY automation_level,id',(event['event_type'],))
    processed=failed=0
    for rule in rules:
        if m.one('SELECT id FROM v13_rule_runs WHERE rule_id=? AND event_id=?',(rule['id'],event_id)):continue
        matched,why=_conditions_match(rule,event)
        if not matched:
            detail='Skipped: '+why;outcome='Skipped'
            with m.connect() as con:con.execute('INSERT INTO v13_rule_runs(id,rule_id,event_id,outcome,detail) VALUES(?,?,?,?,?)',(uid('RR'),rule['id'],event_id,outcome,detail[:3000]))
            continue
        delay=int(rule.get('delay_seconds') or 0)
        if delay>0:
            try:
                import durable_worker as dw
                dw.enqueue('v13.rule.action',{'rule_id':rule['id'],'event_id':event_id},priority=60,idempotency_key='rule:'+rule['id']+':'+event_id,delay_seconds=delay)
                detail=f'Scheduled after {delay} second(s).';outcome='Scheduled';processed+=1
            except Exception as exc:
                detail=str(exc);outcome='Failed';failed+=1
                incident('automation','Error','Automation scheduling failed',f"{rule['name']}: {exc}",'Review the worker and retry the event.',event.get('entity_type') or '',event.get('entity_id') or '',dedupe_key='automation-schedule:'+str(rule['id'])+':'+str(event.get('entity_type') or '')+':'+str(event.get('entity_id') or ''))
            with m.connect() as con:con.execute('INSERT INTO v13_rule_runs(id,rule_id,event_id,outcome,detail) VALUES(?,?,?,?,?)',(uid('RR'),rule['id'],event_id,outcome,detail[:3000]))
            continue
        try:
            detail=_run_rule(rule,event);outcome='Completed';processed+=1
        except Exception as exc:
            detail=str(exc);outcome='Failed';failed+=1
            incident('automation','Error','Automation rule failed',f"{rule['name']}: {exc}",'Review the event, data and connector, then retry the event.',event.get('entity_type') or '',event.get('entity_id') or '',dedupe_key='automation-rule:'+str(rule['id'])+':'+str(event.get('entity_type') or '')+':'+str(event.get('entity_id') or ''))
        with m.connect() as con:
            con.execute('INSERT INTO v13_rule_runs(id,rule_id,event_id,outcome,detail) VALUES(?,?,?,?,?)',(uid('RR'),rule['id'],event_id,outcome,detail[:3000]))
    with m.connect() as con:
        con.execute("UPDATE v13_events SET status=?,error=?,processed_at=CURRENT_TIMESTAMP WHERE id=?",('Failed' if failed else 'Processed',f'{failed} rule(s) failed' if failed else '',event_id))
    # V18 continues turning business events into durable end-to-end process instances. This is
    # deliberately after the V13 rule transaction so process orchestration cannot
    # lock or corrupt the event dispatcher if a downstream module needs attention.
    try:
        import process_orchestrator as po
        po.start_for_event(event.get('event_type') or '',event.get('entity_type') or '',event.get('entity_id') or '',json.loads(event.get('payload_json') or '{}'))
    except Exception as exc:
        try:
            incident('process_orchestrator','Warning','Process orchestration handoff failed',str(exc),'The business event was processed, but the end-to-end process instance needs review or retry.',event.get('entity_type') or '',event.get('entity_id') or '',dedupe_key='process-handoff:'+str(event.get('event_type') or '')+':'+str(event.get('entity_type') or '')+':'+str(event.get('entity_id') or ''))
        except Exception:
            pass
        try:
            import observability
            observability.log('process.handoff_failed',event_id=event_id,error=str(exc))
        except Exception:
            pass
    return {'processed':processed,'failed':failed}


def process_pending_events(limit: int=50) -> dict:
    rows=m.rows("SELECT id FROM v13_events WHERE status IN ('Pending','Retry') ORDER BY occurred_at LIMIT ?",(limit,))
    done=failed=0
    for r in rows:
        result=dispatch_event(r['id']);done+=result.get('processed',0);failed+=result.get('failed',0)
    return {'processed':done,'failed':failed,'events':len(rows)}


def product_label(product_id: str) -> str:
    p=m.one('SELECT public_product_name,internal_sku FROM products WHERE product_id=?',(product_id,)) or {}
    return p.get('public_product_name') or p.get('internal_sku') or product_id


def _confidence(score: float) -> str:
    if score>=85:return 'High'
    if score>=65:return 'Medium'
    return 'Low'


def _save_quality(entity_type: str, entity_id: str, check_type: str, score: float, issues: list[str], evidence: dict|None=None) -> dict:
    score=max(0.0,min(100.0,float(score)));conf=_confidence(score);status='Pass' if conf=='High' else ('Review recommended' if conf=='Medium' else 'Approval required')
    qid=uid('QC')
    with m.connect() as con:
        con.execute('INSERT INTO v13_quality_checks(id,entity_type,entity_id,check_type,score,confidence,status,issues_json,evidence_json) VALUES(?,?,?,?,?,?,?,?,?)',
                    (qid,entity_type,entity_id,check_type,score,conf,status,json.dumps(issues,ensure_ascii=False),json.dumps(evidence or {},ensure_ascii=False)))
    if conf=='Low' and setting('v13_require_low_confidence_approval','1')=='1':
        emit_event('QUALITY_REVIEW_REQUIRED',entity_type,entity_id,{'check_id':qid,'check_type':check_type,'score':score},'quality-review:'+qid)
    return {'id':qid,'score':score,'confidence':conf,'status':status,'issues':issues,'evidence':evidence or {}}


def assess_source_images(product_id: str) -> dict:
    initialise()
    rows=m.rows('SELECT * FROM product_images WHERE product_id=? ORDER BY is_primary DESC,image_role',(product_id,))
    if not rows:return _save_quality('product',product_id,'source_images',0,['No product source images are stored.'],{'image_count':0})
    issues=[];scores=[];hashes={};ahashes={};evidence=[]
    try:
        from PIL import Image,ImageOps,ImageStat
    except Exception:
        return _save_quality('product',product_id,'source_images',55,['Pillow is unavailable, so source images could not be fully validated.'],{'image_count':len(rows)})
    for row in rows:
        path=ROOT/str(row.get('relative_path') or '')
        item={'image_id':row['image_id'],'filename':row.get('original_filename'),'role':row.get('image_role')}
        score=100.0
        if not path.is_file():
            issues.append(f"Missing file: {row.get('original_filename') or row['image_id']}");scores.append(0);item['missing']=True;evidence.append(item);continue
        raw=path.read_bytes();sha=hashlib.sha256(raw).hexdigest();item['sha256']=sha[:16]
        hashes.setdefault(sha,[]).append(row['image_id'])
        try:
            with Image.open(path) as im:
                im.verify()
            with Image.open(path) as im:
                im=ImageOps.exif_transpose(im).convert('RGB');w,h=im.size;item['width']=w;item['height']=h
                short=min(w,h);long=max(w,h)
                if short<700:score-=35;issues.append(f"{row.get('original_filename')}: low resolution ({w}×{h}).")
                elif short<1000:score-=18;issues.append(f"{row.get('original_filename')}: modest resolution ({w}×{h}).")
                if long/max(1,short)>4.0:score-=8
                tiny=ImageOps.fit(im,(64,64));stat=ImageStat.Stat(tiny);brightness=sum(stat.mean)/3;item['brightness']=round(brightness,1)
                if brightness<35:score-=20;issues.append(f"{row.get('original_filename')}: very dark exposure.")
                elif brightness>225:score-=20;issues.append(f"{row.get('original_filename')}: very bright exposure.")
                g=ImageOps.grayscale(im).resize((8,8));pix=list(g.get_flattened_data() if hasattr(g,'get_flattened_data') else g.getdata());avg=sum(pix)/64;bits=''.join('1' if x>=avg else '0' for x in pix);ahashes[row['image_id']]=bits
        except Exception:
            score=0;issues.append(f"{row.get('original_filename')}: file is not a valid supported image.")
        scores.append(max(0,score));item['score']=round(max(0,score),1);evidence.append(item)
    for sha,ids in hashes.items():
        if len(ids)>1:issues.append(f'Exact duplicate source images detected ({len(ids)} files).')
    ids=list(ahashes)
    near=[]
    for i in range(len(ids)):
        for j in range(i+1,len(ids)):
            a,b=ahashes[ids[i]],ahashes[ids[j]];distance=sum(x!=y for x,y in zip(a,b))
            if distance<=3 and hashes.get(next((k for k,v in hashes.items() if ids[i] in v),''),[])!=hashes.get(next((k for k,v in hashes.items() if ids[j] in v),''),[]):
                near.append((ids[i],ids[j],distance))
    if near:issues.append(f'{len(near)} visually similar source-image pair(s) detected; review before assuming they are distinct views.')
    score=sum(scores)/len(scores) if scores else 0
    if len(rows)<3:score-=10;issues.append('Fewer than three source views are available; model/mannequin fidelity may be harder to validate.')
    return _save_quality('product',product_id,'source_images',score,issues,{'image_count':len(rows),'images':evidence,'near_duplicates':near[:20]})


def assess_product_copy(product_id: str) -> dict:
    initialise();p=m.one('SELECT * FROM products WHERE product_id=?',(product_id,))
    if not p:return _save_quality('product',product_id,'product_truth',0,['Product record is missing.'])
    try:
        import product_engine as pe
        c=pe.content(product_id)
        fields=pe.fields(product_id)
    except Exception:
        c={};fields=[]
    text=' '.join(str(x or '') for x in [p.get('public_product_name'),p.get('description'),c.get('b2c_description'),c.get('b2b_description'),c.get('seo_title'),c.get('meta_description')])
    issues=[];score=100.0
    for pat in UNVERIFIED_CLAIMS:
        if re.search(pat,text,re.I):
            issues.append('Potentially factual marketing claim requires evidence: '+re.search(pat,text,re.I).group(0));score-=15
    verified={(r.get('field_name'),str(r.get('field_value') or '').lower()) for r in fields if str(r.get('verification_status') or '').lower() in {'verified','source supplied'}}
    if p.get('fabric') and ('fabric',str(p['fabric']).lower()) not in verified:
        issues.append('Fabric label is not independently verified.');score-=8
    if not p.get('retail_price'):issues.append('Retail price is missing.');score-=10
    has_inventory=bool(m.one('SELECT 1 ok FROM v9_inventory WHERE product_id=? LIMIT 1',(product_id,))) if m.table_exists('v9_inventory') else False
    if not has_inventory:issues.append('Canonical inventory is missing.');score-=10
    elif truth.product_available(product_id)<=0:issues.append('No available stock.');score-=10
    if not c.get('seo_title'):issues.append('SEO title is missing.');score-=7
    elif len(str(c.get('seo_title'))) > 65:issues.append('SEO title is longer than the usual concise search-result range.');score-=3
    if not c.get('meta_description'):issues.append('Meta description is missing.');score-=7
    if not (c.get('b2c_description') or p.get('description')):issues.append('Customer-facing description is missing.');score-=12
    return _save_quality('product',product_id,'product_truth',score,issues,{'verified_field_count':len(verified)})



def assess_commercial_readiness(product_id: str, channels: list[str]|None=None) -> dict:
    """Check sale-critical fields separately from image/copy confidence.

    Asset preparation is allowed to continue, but live store/publishing readiness must
    never look green when price, stock, currency or owner fact review is missing.
    """
    initialise();p=m.one('SELECT * FROM products WHERE product_id=?',(product_id,))
    if not p:return _save_quality('product',product_id,'commercial_readiness',0,['Product record is missing.'])
    issues=[];score=100.0;channels=set(channels or [])
    if not (p.get('public_product_name') or '').strip():issues.append('Customer-facing title is missing.');score-=20
    if not (p.get('category') or '').strip():issues.append('Product category is missing.');score-=10
    if not (p.get('currency') or '').strip():issues.append('Currency is missing.');score-=15
    if p.get('retail_price') in (None,''):
        issues.append('Retail price is missing.');score-=25
    elif float(p.get('retail_price') or 0)<=0:
        issues.append('Retail price must be greater than zero before live retail publishing.');score-=20
    import v35_truth as truth
    available_stock=truth.product_available(product_id)
    if not m.table_exists('v9_inventory') or not m.one('SELECT 1 ok FROM v9_inventory WHERE product_id=?',(product_id,)):
        issues.append('Canonical inventory is missing.');score-=25
    elif available_stock<=0:
        issues.append('No available stock is currently sellable.');score-=25
    if ('Website' in channels or 'Shopify' in channels) and str(p.get('status') or 'Draft') not in {'Active','Draft','Sold Out'}:
        issues.append('Product status is not publishable.');score-=10
    review=m.one('SELECT confirmed,evidence FROM m4_product_review WHERE product_id=?',(product_id,)) or {}
    if not review.get('confirmed'):
        issues.append('Owner/supplier fact review has not been completed.');score-=30
    img=(m.one('SELECT count(*) n FROM product_images WHERE product_id=?',(product_id,)) or {'n':0})['n']
    if not int(img or 0):issues.append('No source product image is stored.');score-=30
    return _save_quality('product',product_id,'commercial_readiness',score,issues,{'channels':sorted(channels),'image_count':int(img or 0),'fact_reviewed':bool(review.get('confirmed')),'available_stock':available_stock})

def quality_summary(product_id: str) -> dict:
    rows=m.rows('SELECT * FROM v13_quality_checks WHERE entity_type=\'product\' AND entity_id=? ORDER BY created_at DESC',(product_id,))
    latest={}
    for r in rows:
        latest.setdefault(r['check_type'],r)
    values=list(latest.values());score=sum(float(x.get('score') or 0) for x in values)/len(values) if values else 0
    # Overall confidence is constrained by the weakest latest gate rather than
    # being promoted by averaging unrelated checks.  A strong image score must
    # not hide a medium/low product-truth or commercial-readiness result.
    levels={str(x.get('confidence') or '') for x in values}
    confidence='Low' if 'Low' in levels else ('Medium' if 'Medium' in levels else ('High' if values else 'Low'))
    return {'score':round(score,1),'confidence':confidence,'checks':values}


def _step(run_id: str, no: int, key: str, label: str, status: str, detail: str='', action_url: str='') -> None:
    with m.connect() as con:
        con.execute('INSERT INTO v13_pipeline_steps(id,run_id,step_no,step_key,label,status,detail,action_url) VALUES(?,?,?,?,?,?,?,?)',
                    (uid('PSTEP'),run_id,no,key,label,status,detail[:3000],action_url[:1000]))


def launch_product_pipeline(product_id: str, channels: list[str]|None=None, automation_level: int|None=None) -> str:
    initialise();import record_lifecycle as lifecycle;p=lifecycle.require_operationally_active_product(product_id)
    channels=channels or [x.strip() for x in setting('v13_default_channels','Website,Instagram,Facebook,Meta Ads,Google Ads,Email,WhatsApp').split(',') if x.strip()]
    level=int(automation_level or setting('v13_default_automation_level','2'));level=max(1,min(4,level))
    run_id=uid('PIPE');assign_entity('product',product_id)
    with m.connect() as con:con.execute('INSERT INTO v13_pipeline_runs(id,product_id,automation_level,target_channels_json) VALUES(?,?,?,?)',(run_id,product_id,level,json.dumps(channels)))
    blocked=False;summary={'channels':channels,'automation_level':level}
    try:
        qc1=assess_source_images(product_id);_step(run_id,1,'source_qc','Source image quality',qc1['status'],f"{qc1['score']:.0f}/100 · {len(qc1['issues'])} issue(s)",'/product-workspace/'+product_id)
        qc2=assess_product_copy(product_id);qcc=assess_commercial_readiness(product_id,channels)
        truth_status='Approval required' if 'Low' in {qc2['confidence'],qcc['confidence']} else ('Review recommended' if 'Medium' in {qc2['confidence'],qcc['confidence']} else 'Pass')
        _step(run_id,2,'truth_qc','Product truth, copy & commerce',truth_status,f"Copy {qc2['score']:.0f}/100 · commerce {qcc['score']:.0f}/100 · {len(qc2['issues'])+len(qcc['issues'])} issue(s)",'/product-workspace/'+product_id)
        if qc1['confidence']=='Low' or qc2['confidence']=='Low' or qcc['confidence']=='Low':blocked=True
        if setting('v13_auto_local_assets','1')=='1':
            try:
                import product_engine as pe
                made=pe.prepare_assets(product_id)
                ready=int((m.one("SELECT count(*) n FROM v6_product_assets WHERE product_id=? AND status='Ready'",(product_id,)) or {'n':0})['n'])
                if ready:
                    _step(run_id,3,'local_assets','E-commerce derivatives','Completed',f'{ready} derivative(s) ready; {made} newly generated in this run.','/product-engine')
                else:
                    _step(run_id,3,'local_assets','E-commerce derivatives','Needs attention','No usable local derivatives were produced. Check that the stored source-image files still exist, then retry.','/product-engine');blocked=True
            except Exception as exc:_step(run_id,3,'local_assets','E-commerce derivatives','Failed',str(exc),'/product-engine');blocked=True
        else:_step(run_id,3,'local_assets','E-commerce derivatives','Skipped','Automatic local derivatives are disabled.','/product-engine')
        # AI masters are expensive and fidelity-sensitive. Queue/approval is automatic; generation is gated unless the owner explicitly enables paid AI.
        try:
            import creative_engine as ce
            jobs=ce.queue_default_pack(product_id,'V13 product operating pipeline')
            if m.secret() and setting('v13_auto_paid_ai','0')=='1' and level>=3 and not blocked:
                import durable_worker as dw
                dw.enqueue('creative.queue',{'product_id':product_id},priority=70,idempotency_key='v13-creative:'+product_id)
                detail=f'{len(jobs)} AI master job(s) queued for background generation within AI budget controls.';status='Queued'
            else:
                detail=f'{len(jobs)} AI master job(s) prepared. Paid generation requires explicit AI connection/automation approval.';status='Prepared'
            _step(run_id,4,'ai_masters','Product / mannequin / model masters',status,detail,'/creative?product_id='+product_id)
        except Exception as exc:_step(run_id,4,'ai_masters','Product / mannequin / model masters','Failed',str(exc),'/creative');blocked=True
        # Build a channel campaign that can immediately create source-based creatives without waiting for generative AI.
        campaign_id=''
        if setting('v13_auto_creative_plan','1')=='1':
            try:
                import creative_studio as cs
                placement_map={
                    'Instagram':['ig_feed_portrait','ig_story','ig_reel_video'],
                    'Facebook':['fb_feed_portrait','fb_story','fb_reel_video'],
                    'Meta Ads':['meta_feed_portrait','meta_feed_square','meta_story','meta_reel_video'],
                    'Google Ads':['google_search_square','google_search_landscape','google_pmax_square','google_pmax_landscape','google_pmax_portrait','youtube_vertical'],
                }
                placements=[]
                for ch in channels:placements+=placement_map.get(ch,[])
                placements=list(dict.fromkeys(placements))
                if placements:
                    campaign_id=cs.create_campaign({'name':'Auto launch · '+product_label(product_id),'campaign_type':'Product spotlight','target_market':setting('v13_default_market','United Kingdom'),'language':setting('v13_default_language','English'),'visual_style':'Product-first performance ad','background_style':'Warm neutral','subject_mode':'Product only','text_mode':'Marketing text','cta':'Explore the collection','variations':'1'},[product_id],placements)
                    result=cs.generate_all_images(campaign_id)
                    _step(run_id,5,'channel_creatives','Social & advertising creatives','Completed',f"Prepared {result['placement_assets']} placement asset(s) and {result['detail_assets']} detail asset(s) from product-safe sources.",'/creative-studio/campaigns/'+campaign_id)
                else:_step(run_id,5,'channel_creatives','Social & advertising creatives','Not required','No image/video advertising channels selected.','/creative-studio')
            except Exception as exc:_step(run_id,5,'channel_creatives','Social & advertising creatives','Failed',str(exc),'/creative-studio');blocked=True
        else:_step(run_id,5,'channel_creatives','Social & advertising creatives','Skipped','Automatic creative planning is disabled.','/creative-studio')
        # Video: create local storyboard/video jobs only when campaign and video placements exist. Does not incur generative video cost.
        try:
            video_jobs=0
            if campaign_id:
                import creative_studio as cs
                for pl in cs.campaign_placements(campaign_id):
                    key=pl['placement_key']
                    if key in cs.VIDEO_PLACEMENTS:
                        cs.create_video_job(campaign_id,product_id,key,{'duration':'15','provider':'local','video_style':'Product showcase','transition_style':'Slow zoom','captions_mode':'on'});video_jobs+=1
            _step(run_id,6,'video_plan','Video / Reels','Prepared' if video_jobs else 'Not required',f'{video_jobs} placement-aware local video job(s) prepared. Generative motion remains separately review-gated.','/creative-studio/campaigns/'+campaign_id if campaign_id else '/creative-studio')
        except Exception as exc:_step(run_id,6,'video_plan','Video / Reels','Failed',str(exc),'/creative-studio')
        # Store and communication readiness are truthful connector checks.
        try:
            import integration_layer as il
            readiness=[]
            for ch in channels:
                r=il.channel_readiness('Instagram/Facebook' if ch in {'Facebook','Instagram'} else ch)
                readiness.append({'channel':ch,'status':r['status'],'reason':r.get('reason','')})
            store=il.channel_readiness('Website')
            if qcc['confidence']=='Low':
                store_status='Blocked';store_detail='Commercial data is incomplete: '+'; '.join(qcc['issues'][:4])
            else:
                store_status='Ready' if store['status']=='Connected' else 'Needs connection';store_detail=store.get('reason','')
            _step(run_id,7,'store','Store publishing readiness',store_status,store_detail,'/products/'+product_id if store_status=='Blocked' else '/integrations')
            ready=sum(1 for x in readiness if x['status']=='Connected');_step(run_id,8,'channels','Marketing channel readiness','Ready' if ready==len(readiness) and readiness else 'Needs setup',f'{ready}/{len(readiness)} selected channel(s) have a verified connection.','/integration-health')
        except Exception as exc:_step(run_id,7,'store','Store publishing readiness','Needs setup',str(exc),'/integrations');_step(run_id,8,'channels','Marketing channel readiness','Needs setup',str(exc),'/integrations')
        # Human approval boundary.
        q=quality_summary(product_id)
        if q['confidence']=='Low' or blocked:
            _step(run_id,9,'approval','Owner approval','Required','At least one product/creative quality check is low confidence or a preparation step failed.','/product-workspace/'+product_id)
        else:
            _step(run_id,9,'approval','Owner approval','Recommended' if level<4 else 'Policy controlled','Commercial facts, paid media budgets and product-preserving AI outputs remain subject to configured approval policy.','/approvals')
        try:
            import business_os as bos
            bos.recommendation('Growth','Review launch plan for '+product_label(product_id),'Product assets, QC and channel readiness have been prepared in one workflow.','High','/product-workspace/'+product_id,dedupe_key='v13-pipeline-review:'+product_id)
        except Exception:pass
        _step(run_id,10,'next_action','Next business action','Prepared','Open the product workspace to resolve only the remaining exceptions and approve downstream actions.','/product-workspace/'+product_id)
        status='Needs attention' if blocked else 'Prepared'
        with m.connect() as con:con.execute('UPDATE v13_pipeline_runs SET status=?,finished_at=CURRENT_TIMESTAMP,summary_json=? WHERE id=?',(status,json.dumps(summary),run_id))
    except Exception as exc:
        with m.connect() as con:con.execute("UPDATE v13_pipeline_runs SET status='Failed',finished_at=CURRENT_TIMESTAMP,summary_json=? WHERE id=?",(json.dumps({'error':str(exc)}),run_id))
        incident('product_pipeline','Error','Product launch pipeline failed',str(exc),'Open the product workspace and retry the failed stage.', 'product',product_id)
        raise
    return run_id


def latest_pipeline(product_id: str) -> dict|None:
    row=m.one('SELECT * FROM v13_pipeline_runs WHERE product_id=? ORDER BY started_at DESC LIMIT 1',(product_id,))
    if row:row['steps']=m.rows('SELECT * FROM v13_pipeline_steps WHERE run_id=? ORDER BY step_no',(row['id'],))
    return row


def record_ai_usage(task_key: str, provider: str, model: str='', status: str='Completed', object_type: str='', object_id: str='', input_units: int=0, output_units: int=0, image_count: int=0, video_seconds: float=0.0, estimated_cost: float=0.0, error: str='', *, error_category: str='', retryable: bool=False, attempts: int=1, provider_request_id: str='', duration_ms: int=0, related_url: str='', failure_signature: str='') -> str:
    initialise();aid=uid('AIU')
    with m.connect() as con:
        try:
            con.execute('''INSERT INTO v13_ai_usage(id,task_key,provider,model,object_type,object_id,status,input_units,output_units,image_count,video_seconds,estimated_cost,error,error_category,retryable,attempts,provider_request_id,duration_ms,related_url,failure_signature)
                           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',(aid,task_key,provider[:80],model[:160],object_type[:80],object_id[:160],status,int(input_units or 0),int(output_units or 0),int(image_count or 0),float(video_seconds or 0),float(estimated_cost or 0),str(error)[:4000],str(error_category)[:80],1 if retryable else 0,max(1,int(attempts or 1)),str(provider_request_id)[:200],max(0,int(duration_ms or 0)),str(related_url)[:500],str(failure_signature)[:100]))
        except Exception:
            # Backward-compatible fallback for a database that has not yet run
            # the V42 additive migration. No AI call is lost because of telemetry.
            con.execute('''INSERT INTO v13_ai_usage(id,task_key,provider,model,object_type,object_id,status,input_units,output_units,image_count,video_seconds,estimated_cost,error)
                           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)''',(aid,task_key,provider[:80],model[:160],object_type[:80],object_id[:160],status,int(input_units or 0),int(output_units or 0),int(image_count or 0),float(video_seconds or 0),float(estimated_cost or 0),str(error)[:2000]))
    return aid


def _scope_usage(scope: str) -> dict:
    if scope.startswith('daily'):
        where="date(created_at)=date('now')"
    else:
        where="substr(created_at,1,7)=substr(CURRENT_TIMESTAMP,1,7)" if not db_layer.USING_POSTGRES else "date_trunc('month',created_at)=date_trunc('month',CURRENT_TIMESTAMP)"
    # Call limits protect the business from repeated provider attempts, including
    # quota/network/model failures. Counting only Completed rows allowed a broken
    # provider to be hammered indefinitely while the UI still displayed 0/50.
    if scope=='daily_image':
        extra=" AND (image_count>0 OR lower(task_key) LIKE '%image%' OR lower(task_key) LIKE 'creative_%')"
    elif scope=='daily_video':
        extra=" AND (video_seconds>0 OR lower(task_key) LIKE '%video%')"
    else: extra=''
    row=m.one(f"""SELECT count(*) calls,coalesce(sum(estimated_cost),0) cost,
                         coalesce(sum(CASE WHEN status='Completed' THEN 1 ELSE 0 END),0) completed,
                         coalesce(sum(CASE WHEN status<>'Completed' THEN 1 ELSE 0 END),0) failed
                  FROM v13_ai_usage WHERE {where}{extra}""") or {'calls':0,'cost':0,'completed':0,'failed':0}
    return {'calls':int(row['calls'] or 0),'cost':float(row['cost'] or 0),
            'completed':int(row.get('completed') or 0),'failed':int(row.get('failed') or 0)}


def ai_budget_status() -> list[dict]:
    initialise();out=[]
    for b in m.rows('SELECT * FROM v13_ai_budgets ORDER BY scope'):
        used=_scope_usage(b['scope']);mc=int(b['max_calls'] or 0);cost=float(b['max_estimated_cost'] or 0);pct_calls=(100*used['calls']/mc) if mc else 0;pct_cost=(100*used['cost']/cost) if cost else 0
        out.append(dict(b)|used|{'percent':round(max(pct_calls,pct_cost),1),'blocked':bool((mc and used['calls']>=mc) or (cost and used['cost']>=cost))})
    return out


def guard_ai_call(kind: str='general', provider: str='OpenAI') -> None:
    # Fail fast only when a cached health result proves this provider cannot
    # succeed. Untested keys are allowed to make their first real request, and
    # non-OpenAI providers (for example Veo/Gemini) must not be blocked by an
    # unrelated OpenAI billing state. Explicit Test connection bypasses this guard.
    if str(provider or 'OpenAI').lower()=='openai':
        try:
            health=m.ai_health(False)
        except Exception:
            health={}
        state=str(health.get('status') or '')
        hard={
            'Billing / quota issue':'AI is paused because the provider account has no available billing or quota capacity. Resolve billing/quota, then run Test connection.',
            'Model unavailable':'The configured AI model is unavailable to this API account. Choose an available model and run Test connection.'
        }
        if state in hard:
            raise ValueError(hard[state])
    statuses={x['scope']:x for x in ai_budget_status()}
    for scope in ['daily','monthly']+(['daily_image'] if kind=='image' else [])+(['daily_video'] if kind=='video' else []):
        if statuses.get(scope,{}).get('blocked'):raise ValueError('AI usage budget/limit reached for '+scope.replace('_',' ')+'. Review AI Governance before starting more paid generation.')


def save_ai_budget(scope: str, max_calls: int, max_cost: float, warn_percent: int=80) -> None:
    if scope not in {'daily','monthly','daily_image','daily_video'}:raise ValueError('Unknown AI budget scope.')
    if not 0<=int(warn_percent)<=100:raise ValueError('Warning percentage must be between 0 and 100.')
    with m.connect() as con:
        con.execute('''INSERT INTO v13_ai_budgets(scope,max_calls,max_estimated_cost,currency,warn_percent) VALUES(?,?,?,?,?)
                       ON CONFLICT(scope) DO UPDATE SET max_calls=excluded.max_calls,max_estimated_cost=excluded.max_estimated_cost,warn_percent=excluded.warn_percent,updated_at=CURRENT_TIMESTAMP''',(scope,max(0,int(max_calls)),max(0,float(max_cost)),'USD',int(warn_percent)))


def record_consent(contact_id: str, channel: str, state: str, source: str='', evidence: str='', jurisdiction: str='', recorded_by: str='') -> str:
    initialise();allowed_channels={'Email','WhatsApp','SMS','Phone','Other'};allowed_states={'Unknown','Allowed','OptedIn','OptedOut','Suppressed','DoNotContact'}
    if channel not in allowed_channels:raise ValueError('Choose a supported communication channel.')
    if state not in allowed_states:raise ValueError('Choose a valid consent/permission state.')
    if not m.one('SELECT contact_id FROM contacts WHERE contact_id=?',(contact_id,)):raise ValueError('Contact not found.')
    eid=uid('CONS')
    with m.connect() as con:
        con.execute('INSERT INTO v13_consent_events(id,contact_id,channel,state,source,evidence,jurisdiction,recorded_by) VALUES(?,?,?,?,?,?,?,?)',(eid,contact_id,channel,state,source[:200],evidence[:1000],jurisdiction[:120],recorded_by[:120]))
        con.execute('DELETE FROM marketing_permissions WHERE contact_id=? AND channel=?',(contact_id,channel))
        con.execute('INSERT INTO marketing_permissions(permission_id,contact_id,channel,status,lawful_basis_or_reason,evidence_reference,jurisdiction) VALUES(?,?,?,?,?,?,?)',(m.uid('PER'),contact_id,channel,state,source[:500],evidence[:1000],jurisdiction[:120]))
    return eid


def consent_history(contact_id: str) -> list[dict]:
    return m.rows('SELECT * FROM v13_consent_events WHERE contact_id=? ORDER BY occurred_at DESC,created_at DESC',(contact_id,))


def scan_inventory_events() -> int:
    initialise();
    if not m.table_exists('v9_inventory'):return 0
    rows=m.rows('''SELECT i.product_id,i.location_id,i.on_hand,i.reserved,i.reorder_point FROM v9_inventory i
                   WHERE (i.on_hand-i.reserved)<=i.reorder_point''')
    n=0;day=dt.datetime.now(dt.UTC).date().isoformat()
    for r in rows:
        emit_event('INVENTORY_LOW','product',r['product_id'],r,f"inventory-low:{r['product_id']}:{r['location_id']}:{day}");n+=1
    return n


def capability_matrix() -> list[dict]:
    initialise()
    out=[]
    def add(key,label,status,detail,url=''):
        out.append({'key':key,'label':label,'status':status,'detail':detail,'action_url':url})
    ai=bool(m.secret())
    add('product_intake','Raw product intake','Fully functional','Multi-image/ZIP intake, filename parsing, grouping, provenance and safe local derivatives are implemented.','/product-engine')
    add('product_qc','Product source & truth QC','Fully functional','Local image validation, duplicate checks, unverified-claim checks and confidence gates are implemented.','/quality-centre')
    add('ai_product','AI product understanding','Partially functional' if ai else 'Requires setup','Multimodal AI analysis exists; it requires a configured AI account and remains reviewable.','/settings#ai')
    add('ai_images','Model/mannequin/studio AI imagery','Partially functional' if ai else 'Requires setup','Reference-image generation and fidelity review exist. Production acceptance still requires representative garment validation.','/creative-studio')
    try:
        import creative_studio as cs
        video_ai=bool(cs.video_secret())
    except Exception:video_ai=False
    add('video_local','Product-safe local video','Fully functional','Placement-aware slideshow/motion video jobs use approved/source imagery and FFmpeg when available.','/creative-studio')
    add('video_ai','Generative fashion video','Partially functional' if video_ai else 'Requires setup','Reference-image AI motion is provider-gated and must remain product-fidelity reviewed.','/creative-studio')
    add('crm','Unified CRM core','Partially functional','Contacts, identity resolution, activities, orders, campaigns and permissions are linked; some external conversation/behavior sources still depend on connectors.','/contacts')
    add('automation','Central automation/event layer','Partially functional','Durable jobs, event dispatch, safe conditions, delays, retries, approvals and exception records are implemented; the action library and measurement loop are still being expanded.','/automation-engine')
    add('consent','Consent ledger','Fully functional','Append-only permission history synchronises the effective CRM permission used by channel eligibility.','/consent-centre')
    add('ai_cost','AI cost governance','Partially functional','Call budgets, usage ledger and paid-generation preflight controls are implemented. Exact cost is only recorded when known/configured, so provider-billing reconciliation is still incomplete.','/ai-governance')
    try:
        import integration_layer as il
        il.initialise()
        checks={r['connector_key']:r for r in il.connections()}
        def conn(keys):return any(checks.get(k,{}).get('status')=='Connected' for k in keys)
        add('shopify','Store sync / Shopify','Partially functional' if conn(['shopify']) else 'Requires setup','Real account validation, product/customer/order sync and draft product creation exist; carts, returns, fulfilment and full inventory webhooks remain incomplete.','/integrations')
        add('email','Marketing email','Partially functional' if conn(['resend']) else 'Requires setup','Domain, send, events and suppression work for the implemented provider; advanced scheduling, deliverability controls and full shared-inbox operation remain incomplete.','/integrations')
        add('whatsapp','WhatsApp Business','Partially functional' if conn(['whatsapp_cloud']) else 'Requires setup','Template send and inbound/status ingestion exist; shared-inbox UX and richer media flows remain incomplete.','/integrations')
        add('social','Facebook / Instagram organic','Partially functional' if conn(['meta_social']) else 'Requires setup','Image publishing and account discovery exist; complete scheduling/comments/inbox/reels workflow is incomplete.','/integrations')
        add('meta_ads','Meta Ads','Partially functional' if conn(['meta_ads']) else 'Requires setup','Read/performance sync exists. Paid mutation stays intentionally gated until budget/conversion/approval controls are validated.','/integrations')
        add('google_ads','Google Ads','Partially functional' if conn(['google_ads']) else 'Requires setup','Read/performance sync exists. Paid mutation remains gated.','/integrations')
    except Exception:
        add('integrations','External integrations','Requires setup','Open Integration Centre to configure verified provider connections.','/integrations')
    add('multi_business','Multi-brand / multi-business tenancy','Prototype','Workspace/entity ownership foundations exist, but the current UI and core records are still primarily single-business.','/architecture-readiness')
    add('attribution','Closed-loop attribution','Partially functional','Touchpoints, campaign/order links and provider metrics exist; robust cross-device/multi-touch attribution still depends on connected identifiers and website events.','/marketing-performance')
    add('payments','Payment operations','Prototype','Payment reconciliation foundation exists for Stripe; charging/refunds/checkout are not a general commerce workflow yet.','/integrations')
    add('shipping','Shipping / fulfilment','Not implemented','Carrier labels, tracking and delivery events still need a provider connector.','/integrations')
    add('accounting','Accounting sync','Not implemented','Accounting connector remains roadmap work.','/integrations')
    add('manufacturing','Manufacturing / QC / MRP','Not implemented','Weaver/vendor/raw-material/production-batch operations remain roadmap work.','/architecture-readiness')
    add('production_runtime','Production cloud foundation','Partially functional' if rc.IS_PRODUCTION and not rc.production_gaps() else 'Requires setup','PostgreSQL, object media, HTTPS, workers, metrics, MFA and backup tooling exist; real deployment, monitoring destinations and disaster-recovery drills must still be validated.','/architecture-readiness')
    with m.connect() as con:
        for x in out:
            con.execute('''INSERT INTO v13_capability_checks(capability_key,label,status,detail,action_url,checked_at) VALUES(?,?,?,?,?,CURRENT_TIMESTAMP)
                           ON CONFLICT(capability_key) DO UPDATE SET label=excluded.label,status=excluded.status,detail=excluded.detail,action_url=excluded.action_url,checked_at=CURRENT_TIMESTAMP''',(x['key'],x['label'],x['status'],x['detail'],x['action_url']))
    return out


def readiness_snapshot() -> dict:
    caps=capability_matrix();counts={}
    for c in caps:counts[c['status']]=counts.get(c['status'],0)+1
    incidents=m.one("SELECT count(*) n FROM v13_incidents WHERE status='Open'") or {'n':0}
    budgets=ai_budget_status()
    return {'capabilities':caps,'counts':counts,'open_incidents':int(incidents['n'] or 0),'ai_budgets':budgets,'production_gaps':rc.production_gaps()}


def run_end_to_end_audit() -> dict:
    initialise();steps=[]
    def add(no,label,status,detail,url=''):
        steps.append({'no':no,'label':label,'status':status,'detail':detail,'action_url':url})
    products=int((m.one('SELECT count(*) n FROM products') or {'n':0})['n']);images=int((m.one('SELECT count(*) n FROM product_images') or {'n':0})['n'])
    add(1,'Upload','Pass' if images else 'Needs setup',f'{images} stored source product image(s).','/product-engine')
    add(2,'Product recognition','Pass' if m.table_exists('v6_product_fields') else 'Blocked','Filename/AI provenance fields are available.','/product-engine')
    add(3,'Product creation','Pass' if products else 'Needs setup',f'{products} product record(s).','/products')
    add(4,'Image enhancement','Pass' if m.table_exists('v6_product_assets') else 'Blocked','Product-safe local derivatives are supported.','/product-engine')
    ai=bool(m.secret());add(5,'Mannequin/model generation','Partial' if ai and m.table_exists('v7_creative_jobs') else 'Needs setup','Reference-edit generation exists; AI connection and fidelity review are required.','/creative')
    add(6,'Video generation','Pass' if m.table_exists('v8_video_jobs') else 'Blocked','Product-safe local video workflow exists; generative motion is optional/provider-gated.','/creative-studio')
    add(7,'Product copy','Pass' if m.table_exists('v6_product_content') else 'Blocked','B2C/B2B copy and provenance are stored.','/product-engine')
    add(8,'SEO','Pass' if m.table_exists('v6_product_content') else 'Blocked','Product SEO metadata and blog studio exist.','/blogs')
    try:
        import integration_layer as il
        website=il.channel_readiness('Website');social=il.channel_readiness('Instagram/Facebook');email=il.channel_readiness('Email');wa=il.channel_readiness('WhatsApp');meta=il.channel_readiness('Meta Ads');google=il.channel_readiness('Google Ads')
    except Exception:
        website=social=email=wa=meta=google={'status':'Not connected','reason':'Integration layer unavailable.'}
    add(9,'Website/store publishing','Partial' if website['status']=='Connected' else 'Needs setup',(website.get('reason','')+' Draft product write/sync exists; full commerce lifecycle is not complete.' if website['status']=='Connected' else website.get('reason','')),'/integrations')
    add(10,'Social asset creation','Pass' if m.table_exists('v8_creative_campaign_assets') else 'Blocked','Placement-aware social image composition exists.','/creative-studio')
    add(11,'Campaign creation','Pass' if m.table_exists('v10_unified_campaigns') else 'Blocked','Unified campaign planning exists.','/campaign-builder')
    add(12,'Audience selection','Pass' if m.table_exists('contacts') else 'Blocked','CRM segmentation and natural-language audience builder exist.','/audience-builder')
    add(13,'Email campaign','Partial' if email['status']=='Connected' else 'Needs setup',(email.get('reason','')+' Reviewed sending/events work; advanced lifecycle scheduling and mailbox operations remain partial.' if email['status']=='Connected' else email.get('reason','')),'/integrations')
    add(14,'WhatsApp campaign','Partial' if wa['status']=='Connected' else 'Needs setup',(wa.get('reason','')+' Template send/inbound status work; full shared conversation operations remain partial.' if wa['status']=='Connected' else wa.get('reason','')),'/integrations')
    add(15,'Meta campaign','Partial' if meta['status']=='Connected' else 'Needs setup','Performance sync exists; paid write/activation remains intentionally gated.','/integrations')
    add(16,'Google campaign','Partial' if google['status']=='Connected' else 'Needs setup','Performance sync exists; paid write/activation remains intentionally gated.','/integrations')
    add(17,'Lead capture','Partial' if m.table_exists('contacts') else 'Blocked','CRM capture and inbound connector mapping are available; completeness depends on connected forms/ad/social sources.','/contacts')
    add(18,'CRM entry','Pass' if m.table_exists('interactions') else 'Blocked','Customer activities/interactions are recorded.','/contacts')
    add(19,'Automated follow-up','Pass' if m.table_exists('v13_automation_rules') else 'Blocked','Central event rules can create tasks/recommendations.','/automation-engine')
    orders=int((m.one('SELECT count(*) n FROM orders') or {'n':0})['n']);add(20,'Customer purchase','Pass' if m.table_exists('orders') else 'Blocked',f'{orders} recorded order(s).','/orders')
    add(21,'Order tracking','Partial','Order state is stored; carrier shipment tracking still requires a logistics connector.','/orders')
    add(22,'Revenue attribution','Partial' if m.table_exists('v9_attribution_touchpoints') else 'Blocked','Attribution touchpoints exist; closed-loop accuracy depends on connected identifiers/events.','/marketing-performance')
    add(23,'Customer retention','Partial' if m.table_exists('v13_automation_rules') else 'Blocked','Purchase events can create post-purchase recommendations/workflows; full automated cross-channel journeys depend on live sending connectors and rules.','/automation-engine')
    add(24,'Analytics update','Partial','CRM and provider metrics exist; full warehouse/cohort/profit analytics remains incomplete.','/marketing-performance')
    add(25,'AI next action','Pass' if m.table_exists('v9_recommendations') else 'Blocked','Action Centre surfaces deterministic and AI-assisted recommendations.','/')
    order={'Pass':0,'Partial':1,'Needs setup':2,'Blocked':3};overall=max(steps,key=lambda x:order.get(x['status'],3))['status'] if steps else 'Blocked'
    return {'status':overall,'steps':steps,'summary':{'products':products,'images':images}}
