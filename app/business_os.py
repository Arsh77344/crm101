from __future__ import annotations
import datetime as dt
import hashlib
import json
import re
import sqlite3
import uuid
import os
import zipfile
from pathlib import Path
from typing import Any

import marketing as m
import db_layer
import v35_truth as truth

SCHEMA = r'''
CREATE TABLE IF NOT EXISTS v9_model_routes(
 task_key TEXT PRIMARY KEY, label TEXT NOT NULL, provider TEXT NOT NULL DEFAULT 'OpenAI',
 model TEXT NOT NULL, reasoning TEXT DEFAULT '', fallback_model TEXT DEFAULT '', enabled INTEGER DEFAULT 1,
 notes TEXT DEFAULT '', updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS v9_connectors(
 connector_key TEXT PRIMARY KEY, label TEXT NOT NULL, category TEXT NOT NULL,
 provider TEXT DEFAULT '', status TEXT NOT NULL DEFAULT 'Not connected',
 capabilities_json TEXT NOT NULL DEFAULT '[]', config_json TEXT NOT NULL DEFAULT '{}',
 last_checked_at TEXT, last_error TEXT DEFAULT '', updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS v9_email_domains(
 id TEXT PRIMARY KEY, domain TEXT NOT NULL UNIQUE, provider TEXT DEFAULT '', sender_name TEXT DEFAULT '',
 sender_email TEXT DEFAULT '', spf_status TEXT DEFAULT 'Unknown', dkim_status TEXT DEFAULT 'Unknown',
 dmarc_status TEXT DEFAULT 'Unknown', domain_status TEXT DEFAULT 'Setup required', reputation_status TEXT DEFAULT 'Unknown',
 daily_limit INTEGER DEFAULT 100, bounce_rate REAL DEFAULT 0, complaint_rate REAL DEFAULT 0,
 verified_at TEXT, updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS v9_events(
 id TEXT PRIMARY KEY, event_type TEXT NOT NULL, object_type TEXT NOT NULL DEFAULT '', object_id TEXT NOT NULL DEFAULT '',
 payload_json TEXT NOT NULL DEFAULT '{}', status TEXT NOT NULL DEFAULT 'New', dedupe_key TEXT UNIQUE,
 created_at TEXT DEFAULT CURRENT_TIMESTAMP, processed_at TEXT
);
CREATE TABLE IF NOT EXISTS v9_jobs(
 id TEXT PRIMARY KEY, event_id TEXT, job_type TEXT NOT NULL, object_type TEXT DEFAULT '', object_id TEXT DEFAULT '',
 status TEXT NOT NULL DEFAULT 'Queued', attempts INTEGER DEFAULT 0, max_attempts INTEGER DEFAULT 3,
 next_run_at TEXT DEFAULT CURRENT_TIMESTAMP, payload_json TEXT NOT NULL DEFAULT '{}', last_error TEXT DEFAULT '',
 created_at TEXT DEFAULT CURRENT_TIMESTAMP, updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
 FOREIGN KEY(event_id) REFERENCES v9_events(id)
);
CREATE TABLE IF NOT EXISTS v9_recommendations(
 id TEXT PRIMARY KEY, kind TEXT NOT NULL, title TEXT NOT NULL, reason TEXT NOT NULL,
 priority TEXT NOT NULL DEFAULT 'Medium', status TEXT NOT NULL DEFAULT 'Open', action_url TEXT DEFAULT '',
 payload_json TEXT NOT NULL DEFAULT '{}', dedupe_key TEXT UNIQUE, created_at TEXT DEFAULT CURRENT_TIMESTAMP,
 resolved_at TEXT, updated_at TEXT DEFAULT CURRENT_TIMESTAMP, occurrence_count INTEGER DEFAULT 1
);
CREATE TABLE IF NOT EXISTS v9_failures(
 id TEXT PRIMARY KEY, source TEXT NOT NULL, object_type TEXT DEFAULT '', object_id TEXT DEFAULT '',
 severity TEXT NOT NULL DEFAULT 'Error', message TEXT NOT NULL, recovery_hint TEXT DEFAULT '',
 resolved INTEGER DEFAULT 0, created_at TEXT DEFAULT CURRENT_TIMESTAMP, resolved_at TEXT, dedupe_key TEXT UNIQUE, first_seen TEXT DEFAULT CURRENT_TIMESTAMP, last_seen TEXT DEFAULT CURRENT_TIMESTAMP, occurrence_count INTEGER DEFAULT 1, latest_error TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS v9_identities(
 contact_id TEXT NOT NULL, identity_type TEXT NOT NULL, normalized_value TEXT NOT NULL,
 original_value TEXT DEFAULT '', confidence TEXT DEFAULT 'Imported', created_at TEXT DEFAULT CURRENT_TIMESTAMP,
 PRIMARY KEY(identity_type, normalized_value)
);
CREATE TABLE IF NOT EXISTS v9_brands(
 id TEXT PRIMARY KEY, name TEXT NOT NULL, default_currency TEXT DEFAULT 'INR', default_language TEXT DEFAULT 'English',
 status TEXT DEFAULT 'Active', created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS v9_locations(
 id TEXT PRIMARY KEY, brand_id TEXT, name TEXT NOT NULL, location_type TEXT NOT NULL DEFAULT 'Warehouse',
 country TEXT DEFAULT '', city TEXT DEFAULT '', address TEXT DEFAULT '', timezone TEXT DEFAULT '', status TEXT DEFAULT 'Active'
);
CREATE TABLE IF NOT EXISTS v9_inventory(
 product_id TEXT NOT NULL, location_id TEXT NOT NULL, on_hand INTEGER DEFAULT 0, reserved INTEGER DEFAULT 0,
 reorder_point INTEGER DEFAULT 0, updated_at TEXT DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY(product_id, location_id)
);
CREATE TABLE IF NOT EXISTS v9_security_settings(
 setting_key TEXT PRIMARY KEY, setting_value TEXT NOT NULL DEFAULT '', updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS v9_delivery_events(
 id TEXT PRIMARY KEY, connector_key TEXT NOT NULL, external_id TEXT DEFAULT '', contact_id TEXT, campaign_id TEXT,
 channel TEXT NOT NULL, event_type TEXT NOT NULL, endpoint TEXT DEFAULT '', payload_json TEXT NOT NULL DEFAULT '{}',
 occurred_at TEXT DEFAULT CURRENT_TIMESTAMP, UNIQUE(connector_key,external_id,event_type)
);
CREATE TABLE IF NOT EXISTS v9_attribution_touchpoints(
 id TEXT PRIMARY KEY, contact_id TEXT, anonymous_id TEXT DEFAULT '', session_id TEXT DEFAULT '', channel TEXT DEFAULT '',
 source TEXT DEFAULT '', medium TEXT DEFAULT '', campaign_id TEXT, product_id TEXT, event_type TEXT NOT NULL,
 value REAL, currency TEXT DEFAULT '', occurred_at TEXT DEFAULT CURRENT_TIMESTAMP, metadata_json TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS v9_webhook_receipts(
 id TEXT PRIMARY KEY, connector_key TEXT NOT NULL, external_event_id TEXT DEFAULT '', signature_valid INTEGER DEFAULT 0,
 event_type TEXT DEFAULT '', status TEXT DEFAULT 'Received', payload_hash TEXT NOT NULL, received_at TEXT DEFAULT CURRENT_TIMESTAMP,
 UNIQUE(connector_key,external_event_id)
);
CREATE INDEX IF NOT EXISTS v9_delivery_contact_time ON v9_delivery_events(contact_id,occurred_at);
CREATE INDEX IF NOT EXISTS v9_attribution_contact_time ON v9_attribution_touchpoints(contact_id,occurred_at);

CREATE INDEX IF NOT EXISTS v9_jobs_status_next ON v9_jobs(status,next_run_at);
CREATE INDEX IF NOT EXISTS v9_events_type_created ON v9_events(event_type,created_at);
CREATE INDEX IF NOT EXISTS v9_recs_status_priority ON v9_recommendations(status,priority);
CREATE INDEX IF NOT EXISTS v9_failures_open ON v9_failures(resolved,severity);
CREATE INDEX IF NOT EXISTS v9_inventory_product ON v9_inventory(product_id);
CREATE INDEX IF NOT EXISTS idx_contacts_email_v9 ON contacts(email);
CREATE INDEX IF NOT EXISTS idx_contacts_phone_v9 ON contacts(phone_number);
CREATE INDEX IF NOT EXISTS idx_contacts_lifecycle_v9 ON contacts(lifecycle_stage);
CREATE INDEX IF NOT EXISTS idx_products_status_v9 ON products(status);
CREATE INDEX IF NOT EXISTS idx_orders_contact_v9 ON orders(contact_id);
CREATE INDEX IF NOT EXISTS idx_interactions_contact_time_v9 ON interactions(contact_id,occurred_at);
'''

MODEL_DEFAULTS = [
 ('product_understanding','Product understanding / multimodal extraction','OpenAI','gpt-6-sol','medium','gpt-6-astra','Vision + structured extraction; balance fidelity and cost.'),
 ('product_copy','Product descriptions / metadata','OpenAI','gpt-6-luna','none','gpt-6-sol','High-volume structured copy with escalation for ambiguous facts.'),
 ('seo_strategy','SEO research / content strategy','OpenAI','gpt-6-sol','medium','gpt-6-luna','Reasoning and web-backed strategy when research is enabled.'),
 ('marketing_copy','Marketing copy / personalisation','OpenAI','gpt-6-luna','low','gpt-6-sol','High-volume copy; use verified CRM and product context only.'),
 ('crm_intelligence','CRM intelligence / next best action','OpenAI','gpt-6-sol','medium','gpt-6-astra','Cross-record reasoning and prioritisation.'),
 ('business_analytics','Business analysis / growth recommendations','OpenAI','gpt-6-sol','high','gpt-6-astra','Deeper reasoning over sales, inventory, campaigns and margin.'),
 ('customer_service','Customer service assistant','OpenAI','gpt-6-luna','low','gpt-6-sol','Fast grounded answers; escalate when facts are missing.'),
 ('translation','Translation / localisation','OpenAI','gpt-6-luna','none','gpt-6-sol','High-volume localisation with glossary context.'),
 ('image_preserve','Product-preserving image edit','OpenAI','gpt-image-2.5-sunburst','','gpt-image-2.5-flare','Precision-first reference editing for textile fidelity.'),
 ('image_fast','Fast creative generation','OpenAI','gpt-image-2.5-flare','','gpt-image-2.5-sunburst','Fast high-quality variations where exact edits are less critical.'),
 ('voiceover','Voice-over','OpenAI','gpt-4o-mini-tts','','','Speech generation; disclose AI-generated voice.'),
 ('video','Generative video','Pluggable','provider-configured','','local-compositor','Provider adapter; always fidelity-review product video.'),
]

CONNECTORS = [
 ('commerce','E-commerce / website','Commerce','Shopify',['products','inventory','orders','customers','carts','webhooks']),
 ('email_marketing','Marketing email','Messaging','Provider adapter',['send','templates','webhooks','bounce','complaint','unsubscribe','tracking']),
 ('email_transactional','Transactional email','Messaging','Provider adapter',['order_email','service_email','webhooks']),
 ('whatsapp','WhatsApp Business','Messaging','Meta WhatsApp',['templates','send','inbox','delivery','opt_out']),
 ('sms','SMS','Messaging','Provider adapter',['send','delivery','opt_out']),
 ('meta_ads','Meta Ads','Advertising','Meta',['campaigns','adsets','ads','creative','pixel','catalog','reporting']),
 ('social_meta','Instagram / Facebook','Social','Meta',['publish','schedule','comments','insights']),
 ('pinterest','Pinterest','Social','Pinterest',['publish','catalog','insights']),
 ('google_ads','Google Ads','Advertising','Google',['campaigns','assets','audiences','conversions','reporting']),
 ('merchant_center','Google Merchant Center','Commerce','Google',['product_feed','diagnostics']),
 ('ga4','Google Analytics 4','Analytics','Google',['events','attribution','audiences']),
 ('search_console','Search Console','SEO','Google',['queries','pages','coverage']),
 ('payments','Payments','Payments','Provider adapter',['payments','refunds','webhooks']),
 ('shipping','Shipping / fulfilment','Operations','Provider adapter',['rates','labels','tracking','delivery']),
 ('accounting','Accounting','Finance','Provider adapter',['orders','invoices','payments','tax']),
 ('calendar','Calendar / appointments','Sales','Google/Microsoft',['availability','appointments','reminders']),
 ('video_meetings','Video meetings','Sales','Zoom/Meet',['meetings','recording','transcript']),
 ('cloud_storage','Cloud asset storage','Infrastructure','Object storage',['media','backups','signed_urls']),
]

def uid(prefix:str)->str:
    return prefix+'-'+uuid.uuid4().hex[:16].upper()

def initialise() -> None:
    with m.connect() as con:
        con.executescript(SCHEMA)
        for task,label,provider,model,reasoning,fallback,notes in MODEL_DEFAULTS:
            con.execute('''INSERT OR IGNORE INTO v9_model_routes(task_key,label,provider,model,reasoning,fallback_model,notes)
                           VALUES(?,?,?,?,?,?,?)''',(task,label,provider,model,reasoning,fallback,notes))
        # Migrate only model IDs shipped by earlier prototypes; preserve deliberate owner overrides.
        current={row[0]:(row[3],row[5]) for row in MODEL_DEFAULTS}
        for task,(model,fallback) in current.items():
            row=con.execute('SELECT model,fallback_model FROM v9_model_routes WHERE task_key=?',(task,)).fetchone()
            if not row: continue
            old_model=str(row[0] or '');old_fallback=str(row[1] or '')
            if old_model in {'gpt-5.5','gpt-5.6-sol','gpt-5.6-luna','gpt-5.6-terra'}:
                con.execute('UPDATE v9_model_routes SET model=?,fallback_model=?,updated_at=CURRENT_TIMESTAMP WHERE task_key=?',(model,fallback,task))
        for key,label,cat,provider,caps in CONNECTORS:
            con.execute('''INSERT OR IGNORE INTO v9_connectors(connector_key,label,category,provider,capabilities_json)
                           VALUES(?,?,?,?,?)''',(key,label,cat,provider,json.dumps(caps)))
        con.execute("INSERT OR IGNORE INTO v9_security_settings VALUES('session_mode','local-single-user',CURRENT_TIMESTAMP)")
        con.execute("INSERT OR IGNORE INTO v9_security_settings VALUES('secrets_storage','local-file-0600',CURRENT_TIMESTAMP)")
    _ensure_v53_columns()
    rebuild_identity_index()


def rebuild_identity_index(limit:int|None=None)->dict:
    created=conflicts=0
    sql='SELECT contact_id,email,phone_number,username FROM contacts ORDER BY contact_id'+(' LIMIT ?' if limit else '')
    args=(limit,) if limit else ()
    with m.connect() as con:
        if not limit: con.execute('DELETE FROM v9_identities')
        rows=con.execute(sql,args).fetchall()
        for r in rows:
            vals=[('email',(r['email'] or '').strip().lower()),('phone',re.sub(r'\D','',r['phone_number'] or '')),('social',(r['username'] or '').strip().lstrip('@').lower())]
            for typ,val in vals:
                if not val: continue
                try:
                    con.execute('INSERT OR IGNORE INTO v9_identities(contact_id,identity_type,normalized_value,original_value) VALUES(?,?,?,?)',(r['contact_id'],typ,val,val));created+=1
                except sqlite3.IntegrityError: conflicts+=1
    return {'created':created,'conflicts':conflicts}


def model_route(task_key:str)->dict|None:
    return m.one('SELECT * FROM v9_model_routes WHERE task_key=? AND enabled=1',(task_key,))


def save_model_route(data:dict)->None:
    key=str(data.get('task_key','')).strip()
    if not key or not m.one('SELECT 1 ok FROM v9_model_routes WHERE task_key=?',(key,)): raise ValueError('Choose a known AI task route.')
    model=str(data.get('model','')).strip();fallback=str(data.get('fallback_model','')).strip();reasoning=str(data.get('reasoning','')).strip()
    if not model: raise ValueError('Model ID cannot be empty.')
    if reasoning not in {'','none','low','medium','high','xhigh','max'}: raise ValueError('Choose a supported reasoning setting.')
    with m.connect() as con:
        con.execute('UPDATE v9_model_routes SET provider=?,model=?,reasoning=?,fallback_model=?,enabled=?,updated_at=CURRENT_TIMESTAMP WHERE task_key=?',
                    (str(data.get('provider','OpenAI'))[:80],model[:120],reasoning,fallback[:120],1 if str(data.get('enabled','1'))=='1' else 0,key))
    m.audit('v9.model_route.updated',key,model)


def emit(event_type:str,object_type:str='',object_id:str='',payload:dict|None=None,dedupe_key:str='')->str:
    payload=payload or {}; dedupe_key=dedupe_key or hashlib.sha256((event_type+'|'+object_type+'|'+object_id+'|'+json.dumps(payload,sort_keys=True)).encode()).hexdigest()
    with m.connect() as con:
        existing=con.execute('SELECT id FROM v9_events WHERE dedupe_key=?',(dedupe_key,)).fetchone()
        if existing:return existing['id']
        eid=uid('EVT');con.execute('INSERT INTO v9_events(id,event_type,object_type,object_id,payload_json,dedupe_key) VALUES(?,?,?,?,?,?)',(eid,event_type,object_type,object_id,json.dumps(payload),dedupe_key));return eid


def enqueue(job_type:str,object_type:str='',object_id:str='',payload:dict|None=None,event_id:str|None=None,max_attempts:int=3)->str:
    jid=uid('JOB')
    with m.connect() as con: con.execute('INSERT INTO v9_jobs(id,event_id,job_type,object_type,object_id,max_attempts,payload_json) VALUES(?,?,?,?,?,?,?)',(jid,event_id,job_type,object_type,object_id,max_attempts,json.dumps(payload or {})))
    return jid


def _ensure_v53_columns() -> None:
    """Idempotent schema hardening for owner-facing recommendations/failures.

    Timestamp columns are added without ``DEFAULT CURRENT_TIMESTAMP`` during
    upgrades because populated SQLite tables reject that ALTER TABLE form.
    Values are then backfilled from existing history.
    """
    alters={
      'v9_recommendations':[('updated_at','TEXT'),('occurrence_count','INTEGER DEFAULT 1')],
      'v9_failures':[('dedupe_key','TEXT'),('first_seen','TEXT'),('last_seen','TEXT'),('occurrence_count','INTEGER DEFAULT 1'),('latest_error',"TEXT DEFAULT ''")],
    }
    for table,cols in alters.items():
        if not m.table_exists(table):
            continue
        existing={str(r.get('name')) for r in m.rows(f'PRAGMA table_info({table})')} if not db_layer.USING_POSTGRES else {str(r.get('column_name')) for r in m.rows("SELECT column_name FROM information_schema.columns WHERE table_name=?",(table,))}
        with m.connect() as con:
            for col,typ in cols:
                if col not in existing:
                    con.execute(f'ALTER TABLE {table} ADD COLUMN {col} {typ}')
            if table=='v9_recommendations':
                con.execute("UPDATE v9_recommendations SET updated_at=coalesce(updated_at,created_at,CURRENT_TIMESTAMP), occurrence_count=coalesce(occurrence_count,1)")
            elif table=='v9_failures':
                con.execute("UPDATE v9_failures SET first_seen=coalesce(first_seen,created_at,CURRENT_TIMESTAMP)")
                con.execute("UPDATE v9_failures SET last_seen=coalesce(last_seen,resolved_at,created_at,first_seen,CURRENT_TIMESTAMP)")
                con.execute("UPDATE v9_failures SET occurrence_count=coalesce(occurrence_count,1), latest_error=coalesce(nullif(latest_error,''),message,'')")
                con.execute('CREATE UNIQUE INDEX IF NOT EXISTS v9_failures_dedupe ON v9_failures(dedupe_key)')


def recommendation(kind:str,title:str,reason:str,priority='Medium',action_url='',payload:dict|None=None,dedupe_key='')->str:
    """Atomic idempotent owner recommendation upsert. Replays refresh one canonical row."""
    _ensure_v53_columns()
    dedupe_key=dedupe_key or hashlib.sha256((kind+'|'+title+'|'+action_url).encode()).hexdigest()
    rid=uid('REC');payload_json=json.dumps(payload or {})
    with m.connect() as con:
        con.execute('''INSERT INTO v9_recommendations(id,kind,title,reason,priority,status,action_url,payload_json,dedupe_key,occurrence_count,updated_at)
                       VALUES(?,?,?,?,?,'Open',?,?,?,1,CURRENT_TIMESTAMP)
                       ON CONFLICT(dedupe_key) DO UPDATE SET kind=excluded.kind,title=excluded.title,reason=excluded.reason,priority=excluded.priority,status='Open',action_url=excluded.action_url,payload_json=excluded.payload_json,resolved_at=NULL,occurrence_count=coalesce(v9_recommendations.occurrence_count,1)+1,updated_at=CURRENT_TIMESTAMP''',
                    (rid,kind,title,reason,priority,action_url,payload_json,dedupe_key))
        row=con.execute('SELECT id FROM v9_recommendations WHERE dedupe_key=?',(dedupe_key,)).fetchone()
        return row['id']


def failure(source:str,message:str,recovery_hint:str='',object_type='',object_id='',severity='Error',dedupe_key:str='')->str:
    """Canonical failure upsert; repeated identical faults update one incident row."""
    _ensure_v53_columns()
    stable=dedupe_key or hashlib.sha256((str(source)+'|'+str(object_type)+'|'+str(object_id)+'|'+str(message)[:500]).encode()).hexdigest()
    fid=uid('ERR')
    with m.connect() as con:
        con.execute('''INSERT INTO v9_failures(id,source,object_type,object_id,severity,message,recovery_hint,resolved,dedupe_key,first_seen,last_seen,occurrence_count,latest_error)
                       VALUES(?,?,?,?,?,?,?,0,?,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP,1,?)
                       ON CONFLICT(dedupe_key) DO UPDATE SET source=excluded.source,object_type=excluded.object_type,object_id=excluded.object_id,severity=excluded.severity,message=excluded.message,recovery_hint=excluded.recovery_hint,resolved=0,resolved_at=NULL,last_seen=CURRENT_TIMESTAMP,occurrence_count=coalesce(v9_failures.occurrence_count,1)+1,latest_error=excluded.latest_error''',
                    (fid,source[:120],object_type[:80],object_id[:160],severity,message[:4000],recovery_hint[:2000],stable,message[:4000]))
        row=con.execute('SELECT id FROM v9_failures WHERE dedupe_key=?',(stable,)).fetchone()
        return row['id']


def bootstrap_events()->int:
    made=0
    # Product state enters the event stream without changing the existing product engine.
    for r in m.rows("SELECT product_id,status,retail_price,wholesale_price FROM products WHERE coalesce(status,'Draft')<>'Archived'"):
        eid=emit('product.discovered','product',r['product_id'],{'status':r['status']},'product.discovered:'+r['product_id'])
        with m.connect() as con:
            exists=con.execute("SELECT 1 FROM v9_jobs WHERE event_id=? AND job_type='product.readiness'",(eid,)).fetchone()
        if not exists:enqueue('product.readiness','product',r['product_id'],event_id=eid);made+=1
    return made


def process_job(job:dict)->None:
    typ=job['job_type'];oid=job.get('object_id') or ''
    if typ=='product.readiness':
        p=m.one('SELECT * FROM products WHERE product_id=?',(oid,))
        if not p or p.get('status')=='Archived':return
        missing=[]
        if p.get('retail_price') in (None,''):missing.append('retail price')
        inv=m.one('SELECT 1 ok FROM v9_inventory WHERE product_id=? LIMIT 1',(oid,)) if m.table_exists('v9_inventory') else None
        if not inv:missing.append('inventory record')
        elif truth.product_available(oid)<=0:missing.append('available stock')
        if not p.get('description'):missing.append('description')
        if missing:recommendation('Product','Complete '+(p.get('public_product_name') or p.get('internal_sku') or 'product'),'Missing '+', '.join(missing)+' before fully automated selling.','High','/products/'+oid,dedupe_key='product-ready:'+oid)
        else:recommendation('Growth','Prepare a launch for '+(p.get('public_product_name') or p.get('internal_sku') or 'this product'),'Core product data is present. Build creative, audience and channel plan.','Medium','/creative-studio/new?product_id='+oid,dedupe_key='product-launch:'+oid)
    elif typ=='lead.followup':
        recommendation('Sales','Review a lead that needs follow-up','The workflow engine identified a lead with a due next action.','High','/contacts/'+oid,dedupe_key='lead-followup:'+oid)
    elif typ=='order.postpurchase':
        recommendation('Retention','Prepare post-purchase journey','Order event can trigger confirmation, review, cross-sell and repeat-purchase planning.','Medium','/orders',dedupe_key='postpurchase:'+oid)


def run_jobs(limit:int=50)->dict:
    done=failed=0
    with m.connect() as con:
        jobs=[dict(r) for r in con.execute("SELECT * FROM v9_jobs WHERE status IN ('Queued','Retry') AND datetime(next_run_at)<=datetime('now') ORDER BY created_at LIMIT ?",(limit,))]
    for j in jobs:
        try:
            with m.connect() as con: con.execute("UPDATE v9_jobs SET status='Running',attempts=attempts+1,updated_at=CURRENT_TIMESTAMP WHERE id=?",(j['id'],))
            process_job(j)
            with m.connect() as con:
                con.execute("UPDATE v9_jobs SET status='Completed',last_error='',updated_at=CURRENT_TIMESTAMP WHERE id=?",(j['id'],))
                if j.get('event_id'):con.execute("UPDATE v9_events SET status='Processed',processed_at=CURRENT_TIMESTAMP WHERE id=?",(j['event_id'],))
            done+=1
        except Exception as exc:
            attempts=int(j.get('attempts') or 0)+1;status='Dead letter' if attempts>=int(j.get('max_attempts') or 3) else 'Retry';delay=min(60,2**attempts)
            with m.connect() as con:con.execute("UPDATE v9_jobs SET status=?,last_error=?,next_run_at=datetime('now',?),updated_at=CURRENT_TIMESTAMP WHERE id=?",(status,str(exc)[:2000],f'+{delay} minutes',j['id']))
            failure('automation',str(exc),'Retry the job after fixing the underlying data or connector.',j.get('object_type',''),j.get('object_id',''));failed+=1
    return {'completed':done,'failed':failed}


def dedupe_open_recommendations() -> int:
    """Supersede exact duplicate open owner actions while retaining audit history."""
    rows=m.rows("SELECT id,title,reason,action_url,created_at FROM v9_recommendations WHERE status='Open' ORDER BY created_at DESC,id DESC")
    seen=set();dupes=[]
    for row in rows:
        key=(' '.join(str(row.get('title') or '').lower().split()),
             ' '.join(str(row.get('reason') or '').lower().split()),
             str(row.get('action_url') or '').strip().lower())
        if key in seen:dupes.append(row['id'])
        else:seen.add(key)
    if dupes:
        with m.connect() as con:
            for rid in dupes:
                con.execute("UPDATE v9_recommendations SET status='Superseded',resolved_at=CURRENT_TIMESTAMP WHERE id=? AND status='Open'",(rid,))
        m.audit('recommendation.deduplicated','',f'{len(dupes)} duplicate open recommendation(s) superseded; history preserved.')
    return len(dupes)


def generate_recommendations()->int:
    before=m.one("SELECT count(*) n FROM v9_recommendations WHERE status='Open'")['n']
    # Data quality / identity
    bad=m.one("SELECT count(*) n FROM contacts WHERE coalesce(data_quality,'') LIKE 'Needs Review%' OR (coalesce(email,'')='' AND coalesce(phone_number,'')='')")['n']
    if bad:recommendation('Data quality',f'Review {bad:,} contacts with incomplete contact data','Fixing invalid or missing addresses reduces wasted outreach and fragmented profiles.','High','/contacts?view=needs-review',dedupe_key='contacts-quality')
    unknown=m.one("SELECT count(*) n FROM marketing_permissions WHERE status='Unknown'")['n'] if m.table_exists('marketing_permissions') else 0
    if unknown:recommendation('Compliance',f'{unknown:,} channel permissions still need review','Publicly available contact data is not treated as permission. Review before automated outreach.','High','/contacts',dedupe_key='permissions-unknown')
    # Due tasks
    due=m.one("SELECT count(*) n FROM m4_tasks WHERE status='Open' AND date(due_date)<=date('now')")['n']
    if due:recommendation('Sales',f'{due:,} tasks are due','Clear due follow-ups before starting additional acquisition work.','High','/tasks',dedupe_key='tasks-due')
    # Integration readiness
    
    try:
        import integration_layer as il
        has_v10=m.table_exists('v10_connections')
        if has_v10:
            implemented=[k for k,v in il.CONNECTOR_CATALOG.items() if v.get('implemented')]
            connected={r['connector_key'] for r in il.connections() if r['status']=='Connected'}
            notconn=sum(1 for k in implemented if k not in connected)
        else:
            notconn=m.one("SELECT count(*) n FROM v9_connectors WHERE status<>'Connected'")['n']
    except Exception:
        notconn=m.one("SELECT count(*) n FROM v9_connectors WHERE status<>'Connected'")['n'] if m.table_exists('v9_connectors') else 0
    if notconn:recommendation('Platform',f'{notconn} integrations still need a verified connection','Automated sync and launch remain limited until the relevant provider connection passes a real backend test.','Medium','/integrations',dedupe_key='connectors-missing')
    # Email domain
    domains=m.one('SELECT count(*) n FROM v9_email_domains')['n']
    if not domains:recommendation('Email','Set up a verified sending domain','Marketing and transactional email should use an authenticated domain with SPF, DKIM, DMARC, suppression and bounce handling.','High','/email-infrastructure',dedupe_key='email-domain')
    # Failures
    errs=m.one('SELECT count(*) n FROM v9_failures WHERE resolved=0')['n']
    if errs:recommendation('System',f'{errs} unresolved automation/system issues','Nothing should fail silently. Review failures and recovery steps.','High','/system-health',dedupe_key='open-failures')
    bootstrap_events();run_jobs(100);dedupe_open_recommendations()
    after=m.one("SELECT count(*) n FROM v9_recommendations WHERE status='Open'")['n']
    return max(0,after-before)


def connector_rows()->list[dict]:return m.rows('SELECT * FROM v9_connectors ORDER BY category,label')

def update_connector(key:str,status:str,provider:str='',note:str='')->None:
    if status not in {'Not connected','Needs setup','Connected','Error','Expired'}:raise ValueError('Choose a valid connector status.')
    with m.connect() as con:
        if not con.execute('SELECT 1 FROM v9_connectors WHERE connector_key=?',(key,)).fetchone():raise ValueError('Unknown integration.')
        con.execute('UPDATE v9_connectors SET status=?,provider=?,last_checked_at=CURRENT_TIMESTAMP,last_error=?,updated_at=CURRENT_TIMESTAMP WHERE connector_key=?',(status,provider[:100],note[:1000] if status in {'Error','Expired'} else '',key))


def save_email_domain(data:dict)->str:
    domain=str(data.get('domain','')).strip().lower().lstrip('@')
    if not re.fullmatch(r'[a-z0-9.-]+\.[a-z]{2,}',domain):raise ValueError('Enter a valid sending domain, for example example.com.')
    sender=str(data.get('sender_email','')).strip().lower()
    if sender and not sender.endswith('@'+domain):raise ValueError('Sender email should use the sending domain.')
    did=str(data.get('id','')).strip() or uid('DOM')
    statuses={k:str(data.get(k,'Unknown')) for k in ['spf_status','dkim_status','dmarc_status']}
    allowed={'Unknown','Missing','Pending','Verified','Fail'}
    if any(v not in allowed for v in statuses.values()):raise ValueError('Choose valid DNS verification states.')
    ready=all(v=='Verified' for v in statuses.values())
    with m.connect() as con:
        con.execute('''INSERT INTO v9_email_domains(id,domain,provider,sender_name,sender_email,spf_status,dkim_status,dmarc_status,domain_status,daily_limit,verified_at)
        VALUES(?,?,?,?,?,?,?,?,?,?,CASE WHEN ? THEN CURRENT_TIMESTAMP ELSE NULL END)
        ON CONFLICT(domain) DO UPDATE SET provider=excluded.provider,sender_name=excluded.sender_name,sender_email=excluded.sender_email,
        spf_status=excluded.spf_status,dkim_status=excluded.dkim_status,dmarc_status=excluded.dmarc_status,domain_status=excluded.domain_status,daily_limit=excluded.daily_limit,verified_at=excluded.verified_at,updated_at=CURRENT_TIMESTAMP''',
        (did,domain,str(data.get('provider',''))[:100],str(data.get('sender_name',''))[:120],sender,statuses['spf_status'],statuses['dkim_status'],statuses['dmarc_status'],'Verified' if ready else 'Setup required',max(1,min(100000,int(data.get('daily_limit') or 100))),1 if ready else 0))
    return did


def customer_360(contact_id:str)->dict:
    # Customer 360 depends on the canonical campaign metadata introduced in V35.
    # Initialise it defensively so imported/legacy workspaces cannot crash this owner view.
    import v35_truth as truth
    truth.initialise()
    c=m.one('SELECT * FROM contacts WHERE contact_id=?',(contact_id,))
    if not c:raise ValueError('Contact not found.')
    campaign_ids=set()
    if m.table_exists('campaign_members'):
        campaign_ids.update(r['campaign_id'] for r in m.rows('SELECT DISTINCT campaign_id FROM campaign_members WHERE contact_id=?',(contact_id,)) if r.get('campaign_id'))
    if m.table_exists('v10_campaign_sends'):
        campaign_ids.update(r['campaign_id'] for r in m.rows('SELECT DISTINCT campaign_id FROM v10_campaign_sends WHERE contact_id=?',(contact_id,)) if r.get('campaign_id'))
    if m.table_exists('m42_deal_meta') and m.table_exists('opportunities'):
        campaign_ids.update((r.get('canonical_campaign_id') or r.get('campaign_id')) for r in m.rows('''SELECT dm.canonical_campaign_id,dm.campaign_id FROM m42_deal_meta dm JOIN opportunities o ON o.opportunity_id=dm.deal_id WHERE o.contact_id=?''',(contact_id,)) if (r.get('canonical_campaign_id') or r.get('campaign_id')))
    if m.table_exists('m42_order_meta') and m.table_exists('orders'):
        campaign_ids.update((r.get('canonical_campaign_id') or r.get('campaign_id')) for r in m.rows('''SELECT om.canonical_campaign_id,om.campaign_id FROM m42_order_meta om JOIN orders oo ON oo.order_id=om.order_id WHERE oo.contact_id=?''',(contact_id,)) if (r.get('canonical_campaign_id') or r.get('campaign_id')))
    campaigns=[]
    if campaign_ids and m.table_exists('v10_unified_campaigns'):
        ids=sorted(campaign_ids); placeholders=','.join('?'*len(ids))
        campaigns=m.rows(f'SELECT * FROM v10_unified_campaigns WHERE id IN ({placeholders}) ORDER BY created_at DESC',tuple(ids))
    def optional_rows(table,sql,args):
        return m.rows(sql,args) if m.table_exists(table) else []
    return {
      'contact':c,
      'activities':optional_rows('activities','SELECT * FROM activities WHERE contact_id=? ORDER BY created_at DESC LIMIT 50',(contact_id,)),
      'interactions':optional_rows('interactions','SELECT * FROM interactions WHERE contact_id=? ORDER BY occurred_at DESC LIMIT 50',(contact_id,)),
      'tasks':optional_rows('m4_tasks','SELECT * FROM m4_tasks WHERE contact_id=? ORDER BY due_date DESC LIMIT 30',(contact_id,)),
      'deals':optional_rows('opportunities','SELECT * FROM opportunities WHERE contact_id=? ORDER BY created_at DESC',(contact_id,)),
      'orders':optional_rows('orders','SELECT * FROM orders WHERE contact_id=? ORDER BY ordered_at DESC',(contact_id,)),
      'campaigns':campaigns,
      'permissions':optional_rows('marketing_permissions','SELECT * FROM marketing_permissions WHERE contact_id=? ORDER BY updated_at DESC',(contact_id,)),
      'delivery':optional_rows('v9_delivery_events','SELECT * FROM v9_delivery_events WHERE contact_id=? ORDER BY occurred_at DESC LIMIT 100',(contact_id,)),
      'touchpoints':optional_rows('v9_attribution_touchpoints','SELECT * FROM v9_attribution_touchpoints WHERE contact_id=? ORDER BY occurred_at DESC LIMIT 100',(contact_id,)),
    }


def canonical_operational_health() -> dict:
    """One operational-failure/readiness read model shared by Home and System Health."""
    _ensure_v53_columns()
    try:
        import operating_core as _oc
        _oc.reconcile_incidents()
    except Exception:
        pass
    try:
        dedupe_open_recommendations()
    except Exception:
        pass
    if m.table_exists('products') and m.table_exists('v9_recommendations'):
        with m.connect() as con:
            con.execute("""UPDATE v9_recommendations SET status='Superseded',resolved_at=CURRENT_TIMESTAMP
                         WHERE status='Open' AND EXISTS (SELECT 1 FROM products p WHERE p.status='Archived' AND
                           (v9_recommendations.dedupe_key='product-ready:'||p.product_id OR v9_recommendations.dedupe_key='product-launch:'||p.product_id OR v9_recommendations.action_url='/products/'||p.product_id))""")
    counts={'v9_failures':0,'v13_incidents':0,'dead_jobs':0,'blocked_processes':0}
    if m.table_exists('v9_failures'): counts['v9_failures']=int((m.one("SELECT count(*) n FROM v9_failures WHERE coalesce(resolved,0)=0") or {'n':0})['n'])
    if m.table_exists('v13_incidents'): counts['v13_incidents']=int((m.one("SELECT count(*) n FROM v13_incidents WHERE status='Open' AND severity IN ('Error','Critical')") or {'n':0})['n'])
    if m.table_exists('v9_jobs'): counts['dead_jobs']+=int((m.one("SELECT count(*) n FROM v9_jobs WHERE status IN ('Failed','Dead letter','DeadLetter')") or {'n':0})['n'])
    if m.table_exists('v12_worker_jobs'): counts['dead_jobs']+=int((m.one("SELECT count(*) n FROM v12_worker_jobs WHERE status IN ('Failed','Dead','DeadLetter')") or {'n':0})['n'])
    if m.table_exists('v17_processes'): counts['blocked_processes']=int((m.one("SELECT count(*) n FROM v17_processes WHERE status IN ('Blocked','Needs attention')") or {'n':0})['n'])
    counts['unresolved']=sum(counts.values())
    try:
        import integration_v14 as v14
        catalog=v14.business_catalog()
        supported=len(catalog)
        connected=0;degraded=0
        for key in catalog:
            rows=[r for r in __import__('integration_layer').connections(key)]
            if any(r.get('status')=='Connected' for r in rows): connected+=1
            elif any(r.get('status') in {'Needs Attention','Connection error','Reconnect required'} for r in rows): degraded+=1
        counts.update({'connectors_supported':supported,'connectors_connected':connected,'connectors_degraded':degraded})
    except Exception:
        counts.update({'connectors_supported':0,'connectors_connected':0,'connectors_degraded':0})
    return counts


def system_health()->dict:
    ok,detail=db_layer.database_ready()
    operational=canonical_operational_health()
    if db_layer.USING_POSTGRES:
        tables=(m.one("SELECT count(*) n FROM information_schema.tables WHERE table_schema='public'") or {'n':0})['n']
        quick='ok' if ok else detail
    else:
        tables=m.one("SELECT count(*) n FROM sqlite_master WHERE type='table'")['n']
        q=m.one('PRAGMA quick_check');quick=(q.get('quick_check','unknown') if q else 'unknown')
    has_conn=m.table_exists('v10_connections')
    return {
      'db_quick_check':quick,'database_backend':db_layer.backend_name(),
      'tables':tables,
      'queued_jobs':m.one("SELECT count(*) n FROM v9_jobs WHERE status IN ('Queued','Retry','Running')")['n'],
      'dead_jobs':operational['dead_jobs'],
      'open_failures':operational['unresolved'],
      'connected':operational['connectors_connected'],
      'connectors':operational['connectors_supported'],
      'connector_degraded':operational['connectors_degraded'],
      'contacts':m.one('SELECT count(*) n FROM contacts')['n'],
      'products':m.one('SELECT count(*) n FROM products')['n'],
    }


def create_full_backup(root:Path)->Path:
    """Create a portable backup; PostgreSQL uses pg_dump, local mode uses SQLite backup."""
    root=Path(root).resolve()
    if db_layer.USING_POSTGRES:
        folder=root/'backups';folder.mkdir(parents=True,exist_ok=True)
        import subprocess,sys
        proc=subprocess.run([sys.executable,str(root/'backup_production.py')],capture_output=True,text=True)
        if proc.returncode:raise ValueError((proc.stderr or proc.stdout or 'Production backup failed.').strip())
        path=Path(proc.stdout.strip().splitlines()[-1])
        if not path.is_file():raise ValueError('Production backup command completed but no archive was found.')
        return path
    # V50: a backup is created atomically from a stable SQLite snapshot.
    # Recovery readiness is tracked separately and becomes Ready only after
    # the exact archive has passed an isolated restore drill.
    import v50_reliability as v50
    return v50.create_local_full_backup(root)

def record_delivery(connector_key:str,external_id:str,contact_id:str,channel:str,event_type:str,endpoint:str='',campaign_id:str='',payload:dict|None=None)->str:
    did=uid('DLV')
    with m.connect() as con:
        con.execute('INSERT OR IGNORE INTO v9_delivery_events(id,connector_key,external_id,contact_id,campaign_id,channel,event_type,endpoint,payload_json) VALUES(?,?,?,?,?,?,?,?,?)',(did,connector_key,external_id,contact_id or None,campaign_id or None,channel,event_type,endpoint,json.dumps(payload or {})))
    return did

def record_touchpoint(contact_id:str,event_type:str,channel:str='',source:str='',medium:str='',campaign_id:str='',product_id:str='',value:float|None=None,currency:str='',metadata:dict|None=None)->str:
    tid=uid('TCH')
    with m.connect() as con:
        con.execute('INSERT INTO v9_attribution_touchpoints(id,contact_id,channel,source,medium,campaign_id,product_id,event_type,value,currency,metadata_json) VALUES(?,?,?,?,?,?,?,?,?,?,?)',(tid,contact_id or None,channel,source,medium,campaign_id or None,product_id or None,event_type,value,currency,json.dumps(metadata or {})))
    return tid
