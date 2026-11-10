from __future__ import annotations

"""V18 end-to-end business process orchestration and operations completion.

This module closes the handoffs between the existing product, campaign, CRM, order,
fulfilment, retention and analytics foundations. External-provider actions remain
truthful: they become Needs setup/Needs attention until a real provider confirms them.
"""

import datetime as dt
import hashlib
import json
import re
import secrets
from typing import Any

import marketing as m
import db_layer


def _emit_event_safe(event_type: str, entity_type: str, entity_id: str, payload: dict, *, dedupe_key: str, title: str) -> bool:
    """Emit downstream automation event without hiding a handoff failure."""
    try:
        import operating_core as oc
        oc.emit_event(event_type,entity_type,entity_id,payload,dedupe_key=dedupe_key)
        return True
    except Exception as exc:
        from operational_guard import record_side_effect_failure
        record_side_effect_failure('process_orchestrator',title,exc,
            recovery='The primary transaction was preserved. Open System health, fix the automation/event-stream issue, then retry the affected workflow.',
            entity_type=entity_type,entity_id=entity_id,severity='Error',action_url='/system-health')
        return False

SCHEMA = r'''
CREATE TABLE IF NOT EXISTS v17_processes(
 id TEXT PRIMARY KEY,
 process_type TEXT NOT NULL,
 object_type TEXT NOT NULL,
 object_id TEXT NOT NULL,
 contact_id TEXT DEFAULT '',
 campaign_id TEXT DEFAULT '',
 order_id TEXT DEFAULT '',
 product_id TEXT DEFAULT '',
 status TEXT NOT NULL DEFAULT 'Running',
 current_step TEXT DEFAULT '',
 automation_level INTEGER DEFAULT 2,
 correlation_id TEXT DEFAULT '',
 summary_json TEXT NOT NULL DEFAULT '{}',
 created_at TEXT DEFAULT CURRENT_TIMESTAMP,
 updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
 completed_at TEXT,
 UNIQUE(process_type,object_type,object_id)
);
CREATE INDEX IF NOT EXISTS v17_process_status ON v17_processes(status,updated_at);
CREATE TABLE IF NOT EXISTS v17_process_steps(
 id TEXT PRIMARY KEY,
 process_id TEXT NOT NULL,
 step_key TEXT NOT NULL,
 sequence_no INTEGER NOT NULL,
 label TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'Waiting',
 detail TEXT DEFAULT '',
 action_url TEXT DEFAULT '',
 evidence_json TEXT NOT NULL DEFAULT '{}',
 started_at TEXT,
 completed_at TEXT,
 updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
 UNIQUE(process_id,step_key)
);
CREATE INDEX IF NOT EXISTS v17_steps_process ON v17_process_steps(process_id,sequence_no);
CREATE TABLE IF NOT EXISTS v17_handoffs(
 id TEXT PRIMARY KEY,
 process_id TEXT NOT NULL,
 from_step TEXT DEFAULT '',
 to_step TEXT DEFAULT '',
 event_type TEXT NOT NULL,
 status TEXT NOT NULL,
 detail TEXT DEFAULT '',
 created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS v17_fulfilments(
 id TEXT PRIMARY KEY,
 order_id TEXT NOT NULL UNIQUE,
 contact_id TEXT DEFAULT '',
 status TEXT NOT NULL DEFAULT 'Preparing',
 inventory_status TEXT DEFAULT 'Not checked',
 carrier TEXT DEFAULT '',
 service TEXT DEFAULT '',
 tracking_number TEXT DEFAULT '',
 tracking_url TEXT DEFAULT '',
 label_url TEXT DEFAULT '',
 provider_connection_id TEXT DEFAULT '',
 provider_fulfilment_id TEXT DEFAULT '',
 packed_at TEXT,
 shipped_at TEXT,
 delivered_at TEXT,
 last_error TEXT DEFAULT '',
 created_at TEXT DEFAULT CURRENT_TIMESTAMP,
 updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS v17_inventory_movements(
 id TEXT PRIMARY KEY,
 product_id TEXT NOT NULL,
 location_id TEXT DEFAULT 'MAIN',
 movement_type TEXT NOT NULL,
 quantity INTEGER NOT NULL,
 reference_type TEXT DEFAULT '',
 reference_id TEXT DEFAULT '',
 note TEXT DEFAULT '',
 created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS v17_inventory_movements_product ON v17_inventory_movements(product_id,created_at);
CREATE TABLE IF NOT EXISTS v17_return_cases(
 id TEXT PRIMARY KEY,
 order_id TEXT NOT NULL,
 contact_id TEXT DEFAULT '',
 case_type TEXT NOT NULL DEFAULT 'Return',
 reason TEXT DEFAULT '',
 requested_resolution TEXT DEFAULT 'Refund',
 status TEXT NOT NULL DEFAULT 'Requested',
 refund_amount REAL DEFAULT 0,
 currency TEXT DEFAULT '',
 restock INTEGER DEFAULT 0,
 external_refund_id TEXT DEFAULT '',
 note TEXT DEFAULT '',
 requested_at TEXT DEFAULT CURRENT_TIMESTAMP,
 received_at TEXT,
 completed_at TEXT,
 updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS v17_returns_order ON v17_return_cases(order_id,status);
CREATE TABLE IF NOT EXISTS v17_social_posts(
 id TEXT PRIMARY KEY,
 campaign_id TEXT DEFAULT '',
 product_id TEXT DEFAULT '',
 channel TEXT NOT NULL,
 connection_id TEXT DEFAULT '',
 asset_url TEXT DEFAULT '',
 caption TEXT DEFAULT '',
 scheduled_at TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'Scheduled',
 provider_post_id TEXT DEFAULT '',
 last_error TEXT DEFAULT '',
 attempts INTEGER DEFAULT 0,
 created_at TEXT DEFAULT CURRENT_TIMESTAMP,
 updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS v17_social_due ON v17_social_posts(status,scheduled_at);
CREATE TABLE IF NOT EXISTS v17_conversations(
 id TEXT PRIMARY KEY,
 contact_id TEXT DEFAULT '',
 channel TEXT NOT NULL,
 subject TEXT DEFAULT '',
 status TEXT NOT NULL DEFAULT 'Open',
 owner TEXT DEFAULT '',
 unread_count INTEGER DEFAULT 0,
 last_message_at TEXT DEFAULT CURRENT_TIMESTAMP,
 created_at TEXT DEFAULT CURRENT_TIMESTAMP,
 updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS v17_conversations_contact ON v17_conversations(contact_id,last_message_at);
CREATE TABLE IF NOT EXISTS v17_messages(
 id TEXT PRIMARY KEY,
 conversation_id TEXT NOT NULL,
 source_type TEXT NOT NULL,
 source_id TEXT NOT NULL,
 direction TEXT DEFAULT '',
 sender TEXT DEFAULT '',
 recipient TEXT DEFAULT '',
 body TEXT DEFAULT '',
 delivery_status TEXT DEFAULT '',
 occurred_at TEXT DEFAULT CURRENT_TIMESTAMP,
 metadata_json TEXT NOT NULL DEFAULT '{}',
 UNIQUE(source_type,source_id)
);
CREATE TABLE IF NOT EXISTS v17_accounting_handoffs(
 id TEXT PRIMARY KEY,
 order_id TEXT NOT NULL,
 handoff_type TEXT NOT NULL,
 amount REAL DEFAULT 0,
 currency TEXT DEFAULT '',
 tax_amount REAL DEFAULT 0,
 status TEXT NOT NULL DEFAULT 'Prepared',
 external_id TEXT DEFAULT '',
 payload_json TEXT NOT NULL DEFAULT '{}',
 created_at TEXT DEFAULT CURRENT_TIMESTAMP,
 updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
 UNIQUE(order_id,handoff_type)
);
CREATE TABLE IF NOT EXISTS v17_profitability(
 id TEXT PRIMARY KEY,
 scope_type TEXT NOT NULL,
 scope_id TEXT NOT NULL,
 revenue REAL DEFAULT 0,
 cogs REAL DEFAULT 0,
 ad_spend REAL DEFAULT 0,
 gross_margin REAL DEFAULT 0,
 contribution REAL DEFAULT 0,
 currency TEXT DEFAULT '',
 evidence_json TEXT NOT NULL DEFAULT '{}',
 calculated_at TEXT DEFAULT CURRENT_TIMESTAMP,
 UNIQUE(scope_type,scope_id)
);
CREATE TABLE IF NOT EXISTS v17_retention_actions(
 id TEXT PRIMARY KEY,
 contact_id TEXT NOT NULL,
 order_id TEXT DEFAULT '',
 action_type TEXT NOT NULL,
 channel TEXT DEFAULT '',
 due_at TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'Planned',
 title TEXT NOT NULL,
 reason TEXT DEFAULT '',
 payload_json TEXT NOT NULL DEFAULT '{}',
 created_at TEXT DEFAULT CURRENT_TIMESTAMP,
 updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
 UNIQUE(contact_id,order_id,action_type)
);
CREATE INDEX IF NOT EXISTS v17_retention_due ON v17_retention_actions(status,due_at);
CREATE TABLE IF NOT EXISTS v17_next_actions(
 id TEXT PRIMARY KEY,
 entity_type TEXT NOT NULL,
 entity_id TEXT NOT NULL,
 action_type TEXT NOT NULL,
 title TEXT NOT NULL,
 reason TEXT NOT NULL,
 priority TEXT NOT NULL DEFAULT 'Medium',
 confidence TEXT NOT NULL DEFAULT 'Rule-based',
 status TEXT NOT NULL DEFAULT 'Open',
 action_url TEXT DEFAULT '',
 dedupe_key TEXT UNIQUE,
 created_at TEXT DEFAULT CURRENT_TIMESTAMP,
 updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS v17_next_actions_status ON v17_next_actions(status,priority,created_at);
CREATE TABLE IF NOT EXISTS v17_campaign_actions(
 id TEXT PRIMARY KEY,
 campaign_id TEXT NOT NULL,
 channel TEXT NOT NULL,
 action_type TEXT NOT NULL,
 connection_id TEXT DEFAULT '',
 status TEXT NOT NULL DEFAULT 'Prepared',
 detail TEXT DEFAULT '',
 action_url TEXT DEFAULT '',
 external_id TEXT DEFAULT '',
 payload_json TEXT NOT NULL DEFAULT '{}',
 created_at TEXT DEFAULT CURRENT_TIMESTAMP,
 updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
 UNIQUE(campaign_id,channel,action_type)
);
CREATE INDEX IF NOT EXISTS v17_campaign_actions_campaign ON v17_campaign_actions(campaign_id,status);
'''

PROCESS_DEFS = {
    'product_to_market': [
        ('product','Product record'),('source_qc','Source image & product truth QC'),('ai','AI product understanding'),
        ('content','Product copy & SEO'),('creative','Approved product imagery'),('video','Product video'),
        ('store','Store publication'),('campaign','Campaign plan'),('channels','Channel execution readiness'),('measure','Measurement ready'),
    ],
    'lead_to_sale': [
        ('identity','Customer identity'),('consent','Communication permission'),('score','Lead qualification'),
        ('followup','Follow-up'),('opportunity','Sales opportunity'),('purchase','Purchase/order'),
    ],
    'campaign_to_revenue': [
        ('plan','Campaign plan'),('products','Products selected'),('creative','Creative prepared'),('approval','Approval'),
        ('organic','Organic social'),('email','Email'),('whatsapp','WhatsApp'),('meta','Meta Ads'),('google','Google Ads'),
        ('metrics','Performance data'),('attribution','Revenue attribution'),
    ],
    'order_to_retention': [
        ('order','Order recorded'),('payment','Payment state'),('inventory','Inventory reservation'),('fulfilment','Fulfilment'),
        ('shipping','Shipment'),('delivery','Delivery'),('returns','Returns/refunds'),('accounting','Accounting handoff'),
        ('post_purchase','Post-purchase journey'),('attribution','Revenue attribution'),('retention','Retention plan'),('next_action','Next action'),
    ],
}


def uid(prefix: str) -> str:
    return prefix + '-' + secrets.token_hex(8).upper()


def _legacy_l267_initialise() -> None:
    with m.connect() as con:
        con.executescript(SCHEMA)


def _json(value: Any) -> str:
    return json.dumps(value or {}, ensure_ascii=False, default=str)


def _one(sql: str, args=()) -> dict:
    return m.one(sql,args) or {}


def _count(sql: str,args=()) -> int:
    return int((_one(sql,args).get('n') or 0))


def _automation_level() -> int:
    row=_one("SELECT setting_value FROM settings WHERE setting_key='v13_default_automation_level'")
    try:return max(1,min(4,int(row.get('setting_value') or 2)))
    except Exception:return 2


def ensure_process(process_type: str, object_type: str, object_id: str, **links) -> str:
    initialise()
    if process_type not in PROCESS_DEFS:raise ValueError('Unknown business process.')
    existing=_one('SELECT id FROM v17_processes WHERE process_type=? AND object_type=? AND object_id=?',(process_type,object_type,object_id))
    if existing:return existing['id']
    pid=uid('PROC17');corr=links.get('correlation_id') or pid
    with m.connect() as con:
        con.execute('''INSERT INTO v17_processes(id,process_type,object_type,object_id,contact_id,campaign_id,order_id,product_id,automation_level,correlation_id)
                       VALUES(?,?,?,?,?,?,?,?,?,?)''',(pid,process_type,object_type,object_id,str(links.get('contact_id') or ''),str(links.get('campaign_id') or ''),str(links.get('order_id') or ''),str(links.get('product_id') or ''),_automation_level(),corr))
        for n,(key,label) in enumerate(PROCESS_DEFS[process_type],1):
            con.execute('INSERT INTO v17_process_steps(id,process_id,step_key,sequence_no,label) VALUES(?,?,?,?,?)',(uid('STEP17'),pid,key,n,label))
    return pid


def _set_step(process_id: str, key: str, status: str, detail: str='', action_url: str='', evidence: dict|None=None) -> None:
    completed="CURRENT_TIMESTAMP" if status in {'Complete','Skipped'} else 'NULL'
    started="CURRENT_TIMESTAMP" if status not in {'Waiting','Blocked'} else 'started_at'
    with m.connect() as con:
        con.execute(f'''UPDATE v17_process_steps SET status=?,detail=?,action_url=?,evidence_json=?,started_at=coalesce(started_at,{started}),completed_at={completed},updated_at=CURRENT_TIMESTAMP
                        WHERE process_id=? AND step_key=?''',(status,detail[:4000],action_url[:1000],_json(evidence),process_id,key))


def _handoff(process_id: str, from_step: str, to_step: str, event_type: str, status: str, detail: str='') -> None:
    last=_one('SELECT to_step,status,detail FROM v17_handoffs WHERE process_id=? ORDER BY created_at DESC LIMIT 1',(process_id,))
    if last and last.get('to_step')==to_step and last.get('status')==status and last.get('detail')==detail[:4000]:return
    with m.connect() as con:
        con.execute('INSERT INTO v17_handoffs(id,process_id,from_step,to_step,event_type,status,detail) VALUES(?,?,?,?,?,?,?)',(uid('HAND17'),process_id,from_step,to_step,event_type,status,detail[:4000]))


def _finish_process(process_id: str) -> dict:
    steps=m.rows('SELECT * FROM v17_process_steps WHERE process_id=? ORDER BY sequence_no',(process_id,))
    rank={'Blocked':5,'Needs attention':4,'Needs setup':3,'Waiting':2,'Ready':1,'Running':1,'Complete':0,'Skipped':0}
    worst=max((rank.get(x['status'],4) for x in steps),default=0)
    if all(x['status'] in {'Complete','Skipped'} for x in steps):status='Complete'
    elif worst>=5:status='Blocked'
    elif worst>=4:status='Needs attention'
    elif worst>=3:status='Needs setup'
    else:status='Running'
    current=next((x['step_key'] for x in steps if x['status'] not in {'Complete','Skipped'}),'')
    counts={}
    for s in steps:counts[s['status']]=counts.get(s['status'],0)+1
    with m.connect() as con:
        con.execute("UPDATE v17_processes SET status=?,current_step=?,summary_json=?,updated_at=CURRENT_TIMESTAMP,completed_at=CASE WHEN ?='Complete' THEN CURRENT_TIMESTAMP ELSE completed_at END WHERE id=?",(status,current,_json({'counts':counts}),status,process_id))
    return {'id':process_id,'status':status,'current_step':current,'steps':steps,'counts':counts}


def process(process_id: str) -> dict:
    initialise();row=_one('SELECT * FROM v17_processes WHERE id=?',(process_id,))
    if not row:raise ValueError('Business process not found.')
    row['steps']=m.rows('SELECT * FROM v17_process_steps WHERE process_id=? ORDER BY sequence_no',(process_id,))
    row['handoffs']=m.rows('SELECT * FROM v17_handoffs WHERE process_id=? ORDER BY created_at DESC LIMIT 100',(process_id,))
    return row


def processes(limit: int=100) -> list[dict]:
    initialise();return m.rows('SELECT * FROM v17_processes ORDER BY updated_at DESC LIMIT ?',(max(1,min(limit,500)),))


def _approval_count(entity_type: str, entity_id: str) -> int:
    if not m.table_exists('v11_approvals'):return 0
    return _count("SELECT count(*) n FROM v11_approvals WHERE object_type=? AND object_id=? AND status IN ('Pending','Approved')",(entity_type,entity_id))


def refresh_product_process(process_id: str, product_id: str) -> dict:
    import integration_v14 as v14
    p=_one('SELECT * FROM products WHERE product_id=?',(product_id,))
    if not p:
        _set_step(process_id,'product','Blocked','Product no longer exists.','/products');return _finish_process(process_id)
    if p.get('status')=='Archived':
        _set_step(process_id,'product','Blocked','Product is archived and excluded from active launch workflows. Restore it before continuing.','/products/'+product_id,{'status':'Archived'})
        return _finish_process(process_id)
    _set_step(process_id,'product','Complete','Product record exists.','/products/'+product_id,{'status':p.get('status')})
    qc=_one("SELECT count(*) n,min(CASE WHEN confidence='Low' THEN 0 ELSE 1 END) safe FROM v13_quality_checks WHERE entity_type='product' AND entity_id=?",(product_id,)) if m.table_exists('v13_quality_checks') else {}
    if int(qc.get('n') or 0):
        st='Needs attention' if int(qc.get('safe') or 0)==0 else 'Complete';_set_step(process_id,'source_qc',st,'Product/source quality checks have been recorded.' if st=='Complete' else 'A low-confidence quality check requires review.','/quality-centre')
    else:_set_step(process_id,'source_qc','Ready','Run source-image and product-truth QC.','/product-workspace/'+product_id)
    ai_runs=_count("SELECT count(*) n FROM v13_ai_usage WHERE object_type='product' AND object_id=? AND task_key IN ('product_understanding','product_analysis') AND status='Completed'",(product_id,)) if m.table_exists('v13_ai_usage') else 0
    if ai_runs:_set_step(process_id,'ai','Complete','A successful AI product-analysis run is recorded.','/product-workspace/'+product_id)
    elif m.secret():_set_step(process_id,'ai','Ready','AI is configured; product understanding can run.','/product-workspace/'+product_id)
    else:_set_step(process_id,'ai','Needs setup','Connect the AI provider before automatic product understanding can run.','/settings#ai')
    content_ok=bool((p.get('public_product_name') or '').strip() and (p.get('description') or '').strip())
    if m.table_exists('m4_product_content'):
        c=_one('SELECT * FROM m4_product_content WHERE product_id=?',(product_id,));content_ok=content_ok or bool(c.get('b2c_description') or c.get('seo_title'))
    _set_step(process_id,'content','Complete' if content_ok else 'Ready','Product customer/SEO copy is present.' if content_ok else 'Generate or enter customer-facing product copy and SEO metadata.','/product-workspace/'+product_id)
    assets=_count("SELECT count(*) n FROM v7_creative_assets WHERE product_id=? AND status IN ('Approved','Completed','Ready')",(product_id,)) if m.table_exists('v7_creative_assets') else 0
    jobs=_count("SELECT count(*) n FROM v7_creative_jobs WHERE product_id=? AND status IN ('Completed','Approved')",(product_id,)) if m.table_exists('v7_creative_jobs') else 0
    if assets or jobs:_set_step(process_id,'creative','Complete',f'{assets+jobs} approved/completed creative record(s) exist.','/creative?product_id='+product_id)
    elif m.secret():_set_step(process_id,'creative','Ready','Creative generation can run, but final product fidelity still requires approval.','/creative?product_id='+product_id)
    else:_set_step(process_id,'creative','Needs setup','AI imagery requires the configured AI provider.','/settings#ai')
    video=_count("SELECT count(*) n FROM v8_video_jobs WHERE product_id=? AND status IN ('Completed','Approved','Rendered')",(product_id,)) if m.table_exists('v8_video_jobs') else 0
    if video:_set_step(process_id,'video','Complete',f'{video} completed/approved video job(s) exist.','/creative-studio')
    else:_set_step(process_id,'video','Ready','Video is optional for publication but can be prepared for campaign placements.','/creative-studio')
    store=v14.channel_readiness('Website')
    published=bool(p.get('published_at')) or str(p.get('status') or '').lower() in {'published','active'}
    if published:_set_step(process_id,'store','Complete','Product has a recorded publication state.','/products/'+product_id)
    elif store.get('status')=='Connected':_set_step(process_id,'store','Ready','Store is connected; publish only after product and creative review.','/integrations')
    else:_set_step(process_id,'store','Needs setup',store.get('reason') or 'Connect the store.','/integrations')
    campaigns=_count("SELECT count(*) n FROM v10_unified_campaigns WHERE product_ids_json LIKE ?",('%'+product_id+'%',)) if m.table_exists('v10_unified_campaigns') else 0
    _set_step(process_id,'campaign','Complete' if campaigns else 'Ready',f'{campaigns} campaign(s) reference this product.' if campaigns else 'Create a business-goal campaign for this product.','/campaign-builder')
    readiness=[v14.channel_readiness(x) for x in ['Instagram/Facebook','Email','WhatsApp','Meta Ads','Google Ads']]
    ready=sum(1 for r in readiness if r.get('status') in {'Connected','Ready'})
    if ready:_set_step(process_id,'channels','Ready' if ready<len(readiness) else 'Complete',f'{ready}/{len(readiness)} principal marketing channels are ready.','/integrations')
    else:_set_step(process_id,'channels','Needs setup','No principal external marketing channel is business-ready yet.','/integrations')
    metrics=_count('SELECT count(*) n FROM v10_channel_metrics') if m.table_exists('v10_channel_metrics') else 0
    _set_step(process_id,'measure','Complete' if metrics else 'Ready',f'{metrics} provider metric row(s) are available.' if metrics else 'Measurement will begin after connected channels return real performance data.','/marketing-performance')
    return _finish_process(process_id)


def refresh_lead_process(process_id: str, contact_id: str) -> dict:
    c=_one('SELECT * FROM contacts WHERE contact_id=?',(contact_id,))
    if not c:_set_step(process_id,'identity','Blocked','Contact no longer exists.','/contacts');return _finish_process(process_id)
    identity=bool(c.get('email') or c.get('phone_number') or c.get('username'))
    _set_step(process_id,'identity','Complete' if identity else 'Needs attention','At least one durable customer identifier is recorded.' if identity else 'Add an email, phone number or verified social identity.','/contacts/'+contact_id)
    perms=_count("SELECT count(*) n FROM marketing_permissions WHERE contact_id=? AND status IN ('Allowed','OptedIn')",(contact_id,))
    # Absence of positive marketing permission is a normal business boundary, not a
    # system incident. Keep the process waiting until an allowed route exists rather
    # than flooding Needs Attention for every imported prospect.
    _set_step(process_id,'consent','Complete' if perms else 'Waiting','A verified outbound permission exists.' if perms else 'No positive marketing permission is recorded. Marketing outreach stays blocked until a permitted route or verified permission exists.','/consent-centre')
    score=int(c.get('lead_score') or 0);qual=str(c.get('qualification_status') or '')
    _set_step(process_id,'score','Complete' if score or qual not in {'','Unreviewed'} else 'Ready',f'Lead score {score}; qualification {qual or "Unreviewed"}.','/contacts/'+contact_id)
    tasks=_count("SELECT count(*) n FROM m4_tasks WHERE contact_id=? AND status='Open'",(contact_id,)) if m.table_exists('m4_tasks') else 0
    _set_step(process_id,'followup','Complete' if tasks else 'Ready',f'{tasks} open follow-up task(s).' if tasks else 'Create or automate the next follow-up action.','/tasks')
    opp=_count("SELECT count(*) n FROM opportunities WHERE contact_id=? AND stage NOT IN ('Purchased','Lost','Closed Lost')",(contact_id,))
    _set_step(process_id,'opportunity','Complete' if opp else 'Ready',f'{opp} active opportunity/opportunities.' if opp else 'Create an opportunity when buying intent is confirmed.','/opportunities')
    orders=_count("SELECT count(*) n FROM orders WHERE contact_id=? AND order_status NOT IN ('Cancelled')",(contact_id,))
    _set_step(process_id,'purchase','Complete' if orders else 'Waiting',f'{orders} order(s) recorded.' if orders else 'Waiting for purchase/order confirmation.','/orders')
    return _finish_process(process_id)


def prepare_campaign_actions(campaign_id: str) -> list[dict]:
    """Translate a campaign plan into explicit, truthful channel handoffs.

    This function prepares work and approval records. It never publishes, sends,
    activates, or spends money by itself.
    """
    initialise()
    import integration_layer as il
    import integration_v14 as v14
    import platform_core as pc
    camp=il.campaign(campaign_id)
    selected=list(camp.get('channels') or [])
    existing_rows={r['channel']:r for r in m.rows('SELECT * FROM v10_campaign_channels WHERE campaign_id=?',(campaign_id,))} if m.table_exists('v10_campaign_channels') else {}
    results=[]
    for channel in selected:
        action_type='Prepare channel'; action_url='/campaign-builder/'+campaign_id
        connection_id=''; status='Prepared'; detail='Prepared for owner review.'; external_id=''; payload={}
        row=existing_rows.get(channel,{})
        provider_done=str(row.get('launch_status') or '').strip().lower() in {'launched','published','sent','active','completed','provider confirmed','submitted'} or bool(row.get('external_campaign_id'))
        if provider_done:
            status='Complete'; detail='Provider/execution evidence is already recorded.'; external_id=str(row.get('external_campaign_id') or '')
        elif channel=='Website':
            ready=v14.channel_readiness('Website'); conn=ready.get('connection'); connection_id=str((conn or {}).get('id') or '')
            action_type='Publish products'; action_url='/integrations'
            status='Ready' if ready.get('status') in {'Connected','Ready'} else 'Needs setup'
            detail='Store is ready for reviewed product publication.' if status=='Ready' else (ready.get('reason') or 'Connect the store first.')
        elif channel in {'Instagram','Facebook','Instagram/Facebook'}:
            ready=v14.channel_readiness('Instagram/Facebook'); conn=ready.get('connection'); connection_id=str((conn or {}).get('id') or '')
            action_type='Schedule/publish social'; action_url='/operations/social'
            status='Ready' if ready.get('status') in {'Connected','Ready'} else 'Needs setup'
            detail='Social account is ready; schedule reviewed creative with a public HTTPS asset.' if status=='Ready' else (ready.get('reason') or 'Connect Meta first.')
        elif channel=='Email':
            ready=v14.channel_readiness('Email'); conn=ready.get('connection'); connection_id=str((conn or {}).get('id') or '')
            action_type='Prepare/send email'; action_url='/campaign-builder/'+campaign_id
            status='Ready' if ready.get('status') in {'Connected','Ready'} else 'Needs setup'
            detail='Email transport is ready. Recipient eligibility and reviewed content are still required before send.' if status=='Ready' else (ready.get('reason') or 'Connect email first.')
        elif channel=='WhatsApp':
            ready=v14.channel_readiness('WhatsApp'); conn=ready.get('connection'); connection_id=str((conn or {}).get('id') or '')
            action_type='Prepare/send WhatsApp'; action_url='/campaign-builder/'+campaign_id
            status='Ready' if ready.get('status') in {'Connected','Ready'} else 'Needs setup'
            detail='WhatsApp is ready. Use an approved template and only opted-in eligible recipients.' if status=='Ready' else (ready.get('reason') or 'Connect WhatsApp first.')
        elif channel in {'Meta Ads','Google Ads'}:
            ready=v14.paid_write_readiness(channel); conn=ready.get('connection'); connection_id=str((conn or {}).get('id') or '')
            action_type='Create PAUSED campaign'; action_url='/campaign-builder/'+campaign_id
            if ready.get('status')=='Ready':
                status='Awaiting approval'; detail='Write prerequisites are ready. An approval is required before creating a provider-confirmed PAUSED campaign; activation is a separate unavailable step.'
                if m.table_exists('v11_approvals'):
                    pending=_one("SELECT id FROM v11_approvals WHERE object_type='campaign' AND object_id=? AND action_type=? AND status='Pending'",(campaign_id,'Paid campaign preparation · '+channel))
                    if not pending:
                        pc.approval('Paid campaign preparation · '+channel,'campaign',campaign_id,'Create a reviewed '+channel+' campaign in PAUSED state only. No spend/activation.',risk_level='High')
            else:
                status='Needs setup'; detail=ready.get('reason') or (channel+' needs additional provider setup.')
        else:
            # Internal content channels such as SEO/Blog do not require an external provider action.
            action_type='Prepare owned content'; action_url='/campaign-builder'; status='Ready'; detail='Internal/owned-channel content can be prepared without an external launch.'
        aid=uid('CACT17')
        with m.connect() as con:
            con.execute("""INSERT INTO v17_campaign_actions(id,campaign_id,channel,action_type,connection_id,status,detail,action_url,external_id,payload_json)
                           VALUES(?,?,?,?,?,?,?,?,?,?)
                           ON CONFLICT(campaign_id,channel,action_type) DO UPDATE SET
                             connection_id=excluded.connection_id,status=excluded.status,detail=excluded.detail,
                             action_url=excluded.action_url,external_id=excluded.external_id,payload_json=excluded.payload_json,
                             updated_at=CURRENT_TIMESTAMP""",
                        (aid,campaign_id,channel,action_type,connection_id,status,detail,action_url,external_id,_json(payload)))
        results.append({'campaign_id':campaign_id,'channel':channel,'action_type':action_type,'status':status,'detail':detail,'connection_id':connection_id,'external_id':external_id})
    return results


def refresh_campaign_process(process_id: str, campaign_id: str) -> dict:
    import integration_layer as il
    import integration_v14 as v14
    if not m.table_exists('v10_unified_campaigns'):
        _set_step(process_id,'plan','Blocked','Campaign tables are unavailable.','/campaign-builder');return _finish_process(process_id)
    try:camp=il.campaign(campaign_id)
    except Exception:
        _set_step(process_id,'plan','Blocked','Campaign no longer exists.','/campaign-builder');return _finish_process(process_id)
    _set_step(process_id,'plan','Complete','Campaign plan exists.','/campaign-builder/'+campaign_id)
    prepare_campaign_actions(campaign_id)
    _set_step(process_id,'products','Complete' if camp.get('product_ids') else 'Needs attention',f"{len(camp.get('product_ids') or [])} product(s) selected.",'/campaign-builder/'+campaign_id)
    creative=0;handoff_count=0
    if m.table_exists('v8_creative_campaign_assets'):
        if m.table_exists('v19_creative_quality'):
            creative=_count("SELECT count(*) n FROM v8_creative_campaign_assets a JOIN v19_creative_quality q ON q.asset_id=a.id WHERE a.campaign_id=? AND a.status='Approved' AND q.qc_status='Passed' AND a.placement_key NOT LIKE 'MASTER%'",(campaign_id,))
        else:
            creative=_count("SELECT count(*) n FROM v8_creative_campaign_assets WHERE campaign_id=? AND status='Approved' AND placement_key NOT LIKE 'MASTER%'",(campaign_id,))
    if m.table_exists('v8_publish_handoffs'):handoff_count=_count("SELECT count(*) n FROM v8_publish_handoffs WHERE campaign_id=?",(campaign_id,))
    cstatus='Complete' if handoff_count else ('Ready' if creative else 'Needs attention')
    detail=f'{handoff_count} approved channel handoff(s) prepared from {creative} QC-passed approved creative(s).' if handoff_count else (f'{creative} approved QC-passed creative(s); prepare channel handoffs.' if creative else 'Creative records may exist, but no QC-passed approved campaign creative is ready yet.')
    _set_step(process_id,'creative',cstatus,detail,'/creative-studio')
    approvals=_approval_count('campaign',campaign_id)
    _set_step(process_id,'approval','Complete' if approvals else 'Ready','Campaign approval evidence exists.' if approvals else 'Higher-risk external actions should be approved before execution.','/approvals')
    channel_map={'organic':'Instagram/Facebook','email':'Email','whatsapp':'WhatsApp','meta':'Meta Ads','google':'Google Ads'}
    rows={r['channel']:r for r in m.rows('SELECT * FROM v10_campaign_channels WHERE campaign_id=?',(campaign_id,))}
    for key,ch in channel_map.items():
        if ch not in (camp.get('channels') or []):
            _set_step(process_id,key,'Skipped',f'{ch} is not selected for this campaign.','/campaign-builder/'+campaign_id);continue
        rr=v14.channel_readiness(ch);row=rows.get(ch,{})
        launched=str(row.get('launch_status') or '').lower() in {'launched','published','sent','active','completed','provider confirmed'} or bool(row.get('external_campaign_id'))
        if launched:_set_step(process_id,key,'Complete',f'{ch} has provider/execution evidence recorded.','/campaign-builder/'+campaign_id)
        elif rr.get('status') in {'Connected','Ready'}:_set_step(process_id,key,'Ready',f'{ch} is connected and ready for its supported execution path.','/campaign-builder/'+campaign_id)
        else:_set_step(process_id,key,'Needs setup',rr.get('reason') or f'{ch} needs setup.','/integrations')
    metrics=_count('SELECT count(*) n FROM v10_channel_metrics') if m.table_exists('v10_channel_metrics') else 0
    _set_step(process_id,'metrics','Complete' if metrics else 'Waiting',f'{metrics} provider metric row(s) are available.' if metrics else 'Waiting for real provider performance data.','/marketing-performance')
    touches=_count("SELECT count(*) n FROM v9_attribution_touchpoints WHERE campaign_id=?",(campaign_id,)) if m.table_exists('v9_attribution_touchpoints') else 0
    _set_step(process_id,'attribution','Complete' if touches else 'Waiting',f'{touches} attributed touchpoint(s).' if touches else 'Attribution begins when customer/order events carry campaign identifiers.','/marketing-performance')
    return _finish_process(process_id)


def _order_info(order_id: str) -> dict:
    return _one('SELECT * FROM orders WHERE order_id=?',(order_id,))


def ensure_fulfilment(order_id: str) -> str:
    initialise();o=_order_info(order_id)
    if not o:raise ValueError('Order not found.')
    existing=_one('SELECT id FROM v17_fulfilments WHERE order_id=?',(order_id,))
    if existing:return existing['id']
    items=_count('SELECT count(*) n FROM order_items WHERE order_id=?',(order_id,)) if m.table_exists('order_items') else 0
    status='Ready to pack' if items else 'Needs item review'
    fid=uid('FUL17')
    with m.connect() as con:
        con.execute('INSERT INTO v17_fulfilments(id,order_id,contact_id,status,inventory_status) VALUES(?,?,?,?,?)',(fid,order_id,str(o.get('contact_id') or ''),status,'Pending'))
    reserve_order_inventory(order_id)
    return fid


def _legacy_l542_reserve_order_inventory(order_id: str, location_id: str='MAIN') -> dict:
    initialise();items=m.rows('SELECT product_id,quantity FROM order_items WHERE order_id=?',(order_id,)) if m.table_exists('order_items') else []
    if not items:return {'reserved':0,'shortages':[],'detail':'No order-item rows are available; inventory reservation needs item data.'}
    reserved=0;shortages=[]
    with m.connect() as con:
        for item in items:
            pid=item['product_id'];qty=max(0,int(item.get('quantity') or 0))
            inv=con.execute('SELECT on_hand,reserved FROM v9_inventory WHERE product_id=? AND location_id=?',(pid,location_id)).fetchone() if m.table_exists('v9_inventory') else None
            if inv:
                available=int(inv['on_hand'] or 0)-int(inv['reserved'] or 0)
                use=min(qty,max(0,available))
                if use:
                    con.execute('UPDATE v9_inventory SET reserved=reserved+?,updated_at=CURRENT_TIMESTAMP WHERE product_id=? AND location_id=?',(use,pid,location_id));reserved+=use
                    con.execute('INSERT INTO v17_inventory_movements(id,product_id,location_id,movement_type,quantity,reference_type,reference_id,note) VALUES(?,?,?,?,?,?,?,?)',(uid('MOV17'),pid,location_id,'Reserve',use,'order',order_id,'Reserved for order fulfilment'))
                if use<qty:shortages.append({'product_id':pid,'needed':qty,'available':available})
            else:shortages.append({'product_id':pid,'needed':qty,'available':None})
        con.execute('UPDATE v17_fulfilments SET inventory_status=?,updated_at=CURRENT_TIMESTAMP WHERE order_id=?',('Shortage' if shortages else 'Reserved',order_id))
    return {'reserved':reserved,'shortages':shortages,'detail':'Inventory reserved.' if not shortages else 'Inventory shortage/review required.'}


def _legacy_l562_release_order_reservations(order_id: str, location_id: str='MAIN') -> dict:
    """Release the local operational reservation once stock leaves fulfilment.

    This does not decrement provider-owned on_hand. The configured inventory authority
    remains responsible for authoritative stock quantities; the CRM only releases its local
    reservation and records the movement so repeated shipment callbacks are idempotent.
    """
    initialise();released=0
    reserves=m.rows("SELECT product_id,coalesce(sum(quantity),0) qty FROM v17_inventory_movements WHERE reference_type='order' AND reference_id=? AND movement_type='Reserve' GROUP BY product_id",(order_id,))
    with m.connect() as con:
        for r in reserves:
            pid=r['product_id'];reserved_qty=int(r.get('qty') or 0)
            already=con.execute("SELECT coalesce(sum(quantity),0) qty FROM v17_inventory_movements WHERE reference_type='order' AND reference_id=? AND product_id=? AND movement_type='Release reservation'",(order_id,pid)).fetchone()
            remaining=max(0,reserved_qty-int((already or {'qty':0})['qty'] or 0))
            if not remaining:continue
            inv=con.execute('SELECT reserved FROM v9_inventory WHERE product_id=? AND location_id=?',(pid,location_id)).fetchone() if m.table_exists('v9_inventory') else None
            if inv:
                use=min(remaining,max(0,int(inv['reserved'] or 0)))
                if use:con.execute('UPDATE v9_inventory SET reserved=?,updated_at=CURRENT_TIMESTAMP WHERE product_id=? AND location_id=?',(max(0,int(inv['reserved'] or 0)-use),pid,location_id))
            else:use=remaining
            con.execute('INSERT INTO v17_inventory_movements(id,product_id,location_id,movement_type,quantity,reference_type,reference_id,note) VALUES(?,?,?,?,?,?,?,?)',(uid('MOV17'),pid,location_id,'Release reservation',remaining,'order',order_id,'Reservation released when fulfilment left the local packing stage. Authoritative on-hand remains owned by the configured inventory source.'))
            released+=remaining
    return {'released':released}


def _legacy_l587_mark_packed(fulfilment_id: str) -> None:
    with m.connect() as con:con.execute("UPDATE v17_fulfilments SET status='Packed',packed_at=CURRENT_TIMESTAMP,updated_at=CURRENT_TIMESTAMP,last_error='' WHERE id=?",(fulfilment_id,))


def _legacy_l591_mark_shipped(fulfilment_id: str, carrier: str, tracking_number: str, tracking_url: str='') -> None:
    f=_one('SELECT * FROM v17_fulfilments WHERE id=?',(fulfilment_id,))
    if not f:raise ValueError('Fulfilment not found.')
    if not carrier.strip() or not tracking_number.strip():raise ValueError('Carrier and tracking number are required before marking shipped.')
    consume_order_reservations(f['order_id'])
    with m.connect() as con:con.execute("UPDATE v17_fulfilments SET status='Shipped',carrier=?,tracking_number=?,tracking_url=?,shipped_at=CURRENT_TIMESTAMP,updated_at=CURRENT_TIMESTAMP,last_error='' WHERE id=?",(carrier.strip()[:120],tracking_number.strip()[:200],tracking_url.strip()[:1000],fulfilment_id))
    _emit_event_safe('ORDER_SHIPPED','order',f['order_id'],{'fulfilment_id':fulfilment_id,'carrier':carrier,'tracking_number':tracking_number},dedupe_key='shipped:'+fulfilment_id,title='Shipment saved but ORDER_SHIPPED automation event failed')


def _legacy_l602_mark_delivered(fulfilment_id: str) -> None:
    f=_one('SELECT * FROM v17_fulfilments WHERE id=?',(fulfilment_id,))
    if not f:raise ValueError('Fulfilment not found.')
    # Reservation was consumed at shipment; delivery is status-only and idempotent.
    with m.connect() as con:con.execute("UPDATE v17_fulfilments SET status='Delivered',delivered_at=CURRENT_TIMESTAMP,updated_at=CURRENT_TIMESTAMP WHERE id=?",(fulfilment_id,))
    _emit_event_safe('ORDER_DELIVERED','order',f['order_id'],{'fulfilment_id':fulfilment_id},dedupe_key='delivered:'+fulfilment_id,title='Delivery saved but ORDER_DELIVERED automation event failed')
    plan_retention_for_order(f['order_id'])



def _return_location(order_id: str, product_id: str) -> str:
    """Prefer the location from which the product was dispatched."""
    if m.table_exists('v35_inventory_movements'):
        row=m.one("SELECT location_id FROM v35_inventory_movements WHERE reference_type='order' AND reference_id=? AND product_id=? AND movement_type='Dispatch' ORDER BY created_at DESC LIMIT 1",(order_id,product_id))
        if row and row.get('location_id'):return row['location_id']
    row=m.one("SELECT location_id FROM v9_inventory WHERE product_id=? ORDER BY CASE WHEN location_id='MAIN' THEN 0 ELSE 1 END,location_id LIMIT 1",(product_id,)) if m.table_exists('v9_inventory') else None
    return (row or {}).get('location_id') or 'MAIN'

def _legacy_l622_create_return(order_id: str, reason: str, requested_resolution: str='Refund', case_type: str='Return') -> str:
    o=_order_info(order_id)
    if not o:raise ValueError('Order not found.')
    if requested_resolution not in {'Refund','Exchange','Store credit','Repair/other'}:raise ValueError('Choose a supported return resolution.')
    rid=uid('RET17')
    with m.connect() as con:con.execute('INSERT INTO v17_return_cases(id,order_id,contact_id,case_type,reason,requested_resolution,currency) VALUES(?,?,?,?,?,?,?)',(rid,order_id,str(o.get('contact_id') or ''),case_type[:40],reason.strip()[:2000],requested_resolution,str(o.get('currency') or '')))
    _emit_event_safe('RETURN_REQUESTED','order',order_id,{'return_id':rid,'resolution':requested_resolution,'contact_id':o.get('contact_id')},dedupe_key='return:'+rid,title='Return saved but RETURN_REQUESTED automation event failed')
    return rid


def _legacy_l634_update_return(return_id: str, status: str, refund_amount: float|str=0, restock: bool=False, note: str='', external_refund_id: str='') -> None:
    allowed={'Requested','Approved','In transit','Received','Refund pending','Completed','Rejected','Cancelled'}
    if status not in allowed:raise ValueError('Choose a valid return status.')
    try:amount=max(0,float(refund_amount or 0))
    except Exception:raise ValueError('Enter a valid refund amount.') from None
    with m.connect() as con:
        con.execute("UPDATE v17_return_cases SET status=?,refund_amount=?,restock=?,note=?,external_refund_id=?,received_at=CASE WHEN ?='Received' AND received_at IS NULL THEN CURRENT_TIMESTAMP ELSE received_at END,completed_at=CASE WHEN ?='Completed' THEN CURRENT_TIMESTAMP ELSE completed_at END,updated_at=CURRENT_TIMESTAMP WHERE id=?",(status,amount,1 if restock else 0,note[:2000],external_refund_id[:200],status,status,return_id))
    if status=='Completed':
        r=_one('SELECT * FROM v17_return_cases WHERE id=?',(return_id,))
        if amount>0:
            with m.connect() as con:con.execute("INSERT INTO v17_accounting_handoffs(id,order_id,handoff_type,amount,currency,status,external_id,payload_json) VALUES(?,?,?,?,?,'Prepared',?,?) ON CONFLICT(order_id,handoff_type) DO UPDATE SET amount=excluded.amount,currency=excluded.currency,status='Prepared',external_id=excluded.external_id,payload_json=excluded.payload_json,updated_at=CURRENT_TIMESTAMP",(uid('ACC17'),r['order_id'],'Refund',-amount,r.get('currency') or '',external_refund_id,_json({'return_id':return_id,'note':note})))
        if restock:
            items=m.rows('SELECT product_id,quantity FROM order_items WHERE order_id=?',(r['order_id'],))
            with m.connect() as con:
                for item in items:
                    con.execute('INSERT INTO v17_inventory_movements(id,product_id,location_id,movement_type,quantity,reference_type,reference_id,note) VALUES(?,?,?,?,?,?,?,?)',(uid('MOV17'),item['product_id'],'MAIN','Return restock',int(item.get('quantity') or 0),'return',return_id,'Return completed; provider inventory writeback may still be required by source-of-truth policy.'))
        _emit_event_safe('ORDER_REFUNDED','order',r['order_id'],{'return_id':return_id,'refund_amount':amount,'external_refund_id':external_refund_id},dedupe_key='refund:'+return_id,title='Refund saved but ORDER_REFUNDED automation event failed')


def _legacy_l655_prepare_accounting_handoff(order_id: str) -> str:
    o=_order_info(order_id)
    if not o:raise ValueError('Order not found.')
    kind='Sale';existing=_one('SELECT id FROM v17_accounting_handoffs WHERE order_id=? AND handoff_type=?',(order_id,kind))
    if existing:return existing['id']
    aid=uid('ACC17')
    with m.connect() as con:con.execute('INSERT INTO v17_accounting_handoffs(id,order_id,handoff_type,amount,currency,status,payload_json) VALUES(?,?,?,?,?,?,?)',(aid,order_id,kind,float(o.get('total') or 0),str(o.get('currency') or ''),'Prepared',_json({'external_order_reference':o.get('external_order_reference'),'contact_id':o.get('contact_id')})))
    return aid


def _legacy_l665_accounting_export_rows(limit: int=5000) -> list[dict]:
    initialise();return m.rows('SELECT * FROM v17_accounting_handoffs ORDER BY created_at DESC LIMIT ?',(max(1,min(limit,20000)),))


def plan_retention_for_order(order_id: str) -> list[str]:
    initialise();o=_order_info(order_id);cid=str(o.get('contact_id') or '')
    if not o or not cid:return []
    now=dt.datetime.now(dt.timezone.utc);currency=str(o.get('currency') or '')
    actions=[
        ('thank_you','Thank customer after purchase','Transactional follow-up after a recorded purchase',0),
        ('review_request','Ask for a review','Give the customer time to receive/use the product first',14),
        ('cross_sell','Recommend a relevant follow-up product','Use verified order/product history; do not invent affinity',30),
        ('win_back','Consider a repeat-purchase campaign','Customer has had time since the purchase',90),
    ]
    ids=[]
    with m.connect() as con:
        for typ,title,reason,days in actions:
            due=(now+dt.timedelta(days=days)).replace(microsecond=0).strftime('%Y-%m-%d %H:%M:%S')
            rid=uid('RETENTION17')
            con.execute('''INSERT INTO v17_retention_actions(id,contact_id,order_id,action_type,due_at,title,reason,payload_json)
                           VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(contact_id,order_id,action_type) DO NOTHING''',(rid,cid,order_id,typ,due,title,reason,_json({'order_total':o.get('total'),'currency':currency})))
            row=con.execute('SELECT id FROM v17_retention_actions WHERE contact_id=? AND order_id=? AND action_type=?',(cid,order_id,typ)).fetchone();ids.append(row['id'])
    return ids


def _legacy_l690_process_due_retention(limit: int=100) -> dict:
    """Turn due retention plans into explicit work without sending unreviewed content."""
    initialise();rows=m.rows("SELECT * FROM v17_retention_actions WHERE status='Planned' AND due_at<=CURRENT_TIMESTAMP ORDER BY due_at LIMIT ?",(limit,));prepared=0
    for r in rows:
        cid=r['contact_id'];channel=''
        perms=m.rows("SELECT channel,status FROM marketing_permissions WHERE contact_id=? AND status IN ('Allowed','OptedIn') ORDER BY CASE channel WHEN 'Email' THEN 0 WHEN 'WhatsApp' THEN 1 ELSE 2 END",(cid,))
        if perms:channel=perms[0]['channel']
        # Retention content is intentionally prepared as a task/next action until a
        # reviewed journey template exists. This prevents unreviewed marketing sends.
        title=r['title'];task_id=''
        if m.table_exists('m4_tasks'):
            existing=_one("SELECT id FROM m4_tasks WHERE contact_id=? AND status='Open' AND title=? ORDER BY created_at DESC LIMIT 1",(cid,title))
            if existing:task_id=existing['id']
            else:
                task_id=m.uid('TASK')
                with m.connect() as con:con.execute("INSERT INTO m4_tasks(id,title,contact_id,due_date,status) VALUES(?,?,?,?,?)",(task_id,title,cid,dt.date.today().isoformat(),'Open'))
        with m.connect() as con:con.execute("UPDATE v17_retention_actions SET status='Ready',channel=?,payload_json=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",(channel,_json({'task_id':task_id,'requires_reviewed_content':True}),r['id']))
        prepared+=1
    return {'checked':len(rows),'prepared':prepared}


def _legacy_l711_next_action(entity_type: str, entity_id: str, action_type: str, title: str, reason: str, priority: str='Medium', action_url: str='', dedupe_key: str='') -> str:
    dedupe_key=dedupe_key or f'{entity_type}:{entity_id}:{action_type}'
    existing=_one("SELECT id FROM v17_next_actions WHERE dedupe_key=? AND status='Open'",(dedupe_key,))
    if existing:return existing['id']
    nid=uid('NEXT17')
    with m.connect() as con:con.execute('INSERT INTO v17_next_actions(id,entity_type,entity_id,action_type,title,reason,priority,action_url,dedupe_key) VALUES(?,?,?,?,?,?,?,?,?)',(nid,entity_type,entity_id,action_type,title[:300],reason[:3000],priority,action_url[:1000],dedupe_key))
    return nid


def generate_next_actions() -> int:
    initialise();before=_count("SELECT count(*) n FROM v17_next_actions WHERE status='Open'")
    # Leads that need attention.
    for c in m.rows("SELECT contact_id,coalesce(full_name,username,email,phone_number,contact_id) name,lead_score FROM contacts WHERE coalesce(lead_score,0)>=70 AND coalesce(lifecycle_stage,'') NOT IN ('Purchased','Lost','Customer') LIMIT 200"):
        next_action('contact',c['contact_id'],'follow_up',f"Follow up with {c['name']}",f"Recorded lead score is {int(c.get('lead_score') or 0)}. Review recent activity before contacting them.",'High','/contacts/'+c['contact_id'])
    # Orders needing fulfilment.
    if m.table_exists('orders'):
        for o in m.rows("SELECT order_id,order_status FROM orders WHERE order_status IN ('Paid','Pending','Fulfilled') LIMIT 500"):
            f=_one('SELECT * FROM v17_fulfilments WHERE order_id=?',(o['order_id'],))
            if not f or f.get('status') not in {'Delivered','Cancelled'}:
                next_action('order',o['order_id'],'fulfilment','Complete fulfilment for '+o['order_id'],'A paid/active order does not yet have confirmed delivery.','High','/operations/orders/'+o['order_id'])
    # Due retention actions.
    for r in m.rows("SELECT * FROM v17_retention_actions WHERE status='Planned' AND due_at<=CURRENT_TIMESTAMP ORDER BY due_at LIMIT 200"):
        next_action('contact',r['contact_id'],r['action_type'],r['title'],r['reason'],'Medium','/contacts/'+r['contact_id'],dedupe_key='retention:'+r['id'])
    # Process blockers.
    for p in m.rows("SELECT * FROM v17_processes WHERE status IN ('Blocked','Needs attention','Needs setup') ORDER BY updated_at DESC LIMIT 200"):
        step=_one("SELECT * FROM v17_process_steps WHERE process_id=? AND status NOT IN ('Complete','Skipped') ORDER BY sequence_no LIMIT 1",(p['id'],))
        if step:next_action(p['object_type'],p['object_id'],'process_blocker',f"Continue {p['process_type'].replace('_',' ')}",step.get('detail') or 'The business process needs attention.','High' if p['status'] in {'Blocked','Needs attention'} else 'Medium','/operations/process/'+p['id'],dedupe_key='process:'+p['id']+':'+step['step_key'])
    after=_count("SELECT count(*) n FROM v17_next_actions WHERE status='Open'");return max(0,after-before)


def calculate_profitability(scope_type: str='business', scope_id: str='default') -> dict:
    # V50 canonical recognized profitability. Recorded operational orders are not
    # automatically revenue; Refunded requires canonical refund evidence.
    initialise()
    import v50_reliability as v50
    breakdown=[]; mixed_currency=False; cost_complete=True; missing_cost_products=[]
    if scope_type=='order':
        row=v50.recognized_order_financials(scope_id)
        currency=str(row.get('currency') or '')
        revenue=float(row.get('net_revenue') or 0); cogs=float(row.get('cogs') or 0); ad=0.0
        gross=float(row.get('gross_profit') or (revenue-cogs)); contribution=gross
        cost_complete=bool(row.get('cost_complete')); missing_cost_products=list(row.get('missing_cost_products') or [])
        evidence={'recognized':bool(row.get('recognized')),'incomplete':bool(row.get('incomplete')),'reason':row.get('reason',''),
                  'revenue_source':'recognized order total less canonical refunds','cogs_source':'immutable sale-time cost snapshots less restocked reversals',
                  'ad_spend_source':'not directly allocated','refunds':float(row.get('refunds') or 0),'gross_order_value':float(row.get('gross_order_value') or 0),
                  'cost_complete':cost_complete,'missing_cost_products':missing_cost_products}
    else:
        summary=v50.financial_summary(); incomplete=list(summary.get('incomplete_orders') or [])
        for b in summary.get('currency_breakdown') or []:
            curr=str(b.get('currency') or 'Unspecified')
            curr_ad=float((_one("SELECT coalesce(sum(spend),0) v FROM v10_channel_metrics WHERE coalesce(nullif(currency,''),?)=?",(curr,curr)).get('v') or 0)) if m.table_exists('v10_channel_metrics') else 0.0
            missing_ids=list(b.get('missing_cost_products') or [])
            for x in missing_ids:
                if x not in missing_cost_products: missing_cost_products.append(x)
            breakdown.append({'currency':curr,'recognized_orders':int(b.get('recognized_orders') or 0),'gross_revenue':float(b.get('gross_order_value') or 0),
                              'refunds':float(b.get('refunds') or 0),'net_revenue':float(b.get('net_revenue') or 0),'cogs':float(b.get('cogs') or 0),
                              'cogs_reversal':0.0,'ad_spend':curr_ad,'gross_profit':float(b.get('gross_profit') or 0),
                              'contribution':float(b.get('gross_profit') or 0)-curr_ad,'cost_complete':bool(b.get('cost_complete')),'missing_cost_products':missing_ids})
        if not breakdown:
            default_currency=str(m.settings().get('default_currency','') or 'Unspecified')
            breakdown=[{'currency':default_currency,'recognized_orders':0,'gross_revenue':0.0,'refunds':0.0,'net_revenue':0.0,'cogs':0.0,'cogs_reversal':0.0,'ad_spend':0.0,'gross_profit':0.0,'contribution':0.0,'cost_complete':True,'missing_cost_products':[]}]
        cost_complete=all(x['cost_complete'] for x in breakdown) and not incomplete
        active=[x for x in breakdown if x['gross_revenue'] or x['refunds'] or x['cogs'] or x['ad_spend']]
        mixed_currency=len(active)>1; active=active or breakdown
        if len(active)==1:
            b=active[0]; currency=b['currency']; revenue=b['net_revenue']; cogs=b['cogs']; ad=b['ad_spend']; gross=b['gross_profit']; contribution=b['contribution']
        else:
            currency='MULTI'; revenue=cogs=ad=gross=contribution=None
        evidence={'revenue_source':'Canonical recognized order truth; Draft/Pending/Cancelled excluded; Refunded requires evidence',
                  'cogs_source':'immutable order-line cost snapshots for recognized orders only','ad_spend_source':'provider channel metrics grouped by currency',
                  'mixed_currency':mixed_currency,'currency_breakdown':breakdown,'cost_complete':cost_complete,'missing_cost_products':missing_cost_products,
                  'incomplete_refund_orders':[x.get('order_id') for x in incomplete],'metric_dictionary':summary.get('metric_dictionary',{})}
    pid=uid('PROFIT50')
    with m.connect() as con:
        con.execute('INSERT INTO v17_profitability(id,scope_type,scope_id,revenue,cogs,ad_spend,gross_margin,contribution,currency,evidence_json) VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(scope_type,scope_id) DO UPDATE SET revenue=excluded.revenue,cogs=excluded.cogs,ad_spend=excluded.ad_spend,gross_margin=excluded.gross_margin,contribution=excluded.contribution,currency=excluded.currency,evidence_json=excluded.evidence_json,calculated_at=CURRENT_TIMESTAMP',(pid,scope_type,scope_id,revenue,cogs,ad,gross,contribution,currency,_json(evidence)))
    return {'scope_type':scope_type,'scope_id':scope_id,'revenue':revenue,'cogs':cogs,'ad_spend':ad,'gross_margin':gross,'contribution':contribution,'currency':currency,'evidence':evidence,'cost_complete':cost_complete,'missing_cost_products':missing_cost_products,'mixed_currency':mixed_currency,'currency_breakdown':breakdown}

def refresh_order_process(process_id: str, order_id: str) -> dict:
    o=_order_info(order_id)
    if not o:_set_step(process_id,'order','Blocked','Order no longer exists.','/orders');return _finish_process(process_id)
    _set_step(process_id,'order','Complete','Order record exists.','/orders')
    st=str(o.get('order_status') or '')
    payment_ok=st in {'Paid','Fulfilled','Refunded'}
    _set_step(process_id,'payment','Complete' if payment_ok else 'Waiting',f'Order status: {st or "Unknown"}.','/orders')
    f=_one('SELECT * FROM v17_fulfilments WHERE order_id=?',(order_id,))
    if payment_ok and not f:
        try:ensure_fulfilment(order_id);f=_one('SELECT * FROM v17_fulfilments WHERE order_id=?',(order_id,))
        except Exception as exc:
            from operational_guard import record_side_effect_failure
            record_side_effect_failure('order_process','Paid order could not prepare fulfilment',exc,recovery='Open the order, resolve inventory/reservation issues, then retry fulfilment preparation.',entity_type='order',entity_id=order_id,severity='Error',action_url='/operations/orders/'+order_id)
    if f:
        inv=f.get('inventory_status') or 'Not checked';_set_step(process_id,'inventory','Complete' if inv=='Reserved' else 'Needs attention' if inv=='Shortage' else 'Ready',f'Inventory reservation: {inv}.','/operations/orders/'+order_id)
        _set_step(process_id,'fulfilment','Complete' if f.get('status') in {'Packed','Shipped','Delivered'} else 'Ready',f"Fulfilment status: {f.get('status')}",'/operations/orders/'+order_id)
        _set_step(process_id,'shipping','Complete' if f.get('status') in {'Shipped','Delivered'} else 'Ready',f"Shipment status: {f.get('status')}",'/operations/orders/'+order_id)
        _set_step(process_id,'delivery','Complete' if f.get('status')=='Delivered' else 'Waiting','Delivery is confirmed.' if f.get('status')=='Delivered' else 'Waiting for a real delivery confirmation.','/operations/orders/'+order_id)
    else:
        _set_step(process_id,'inventory','Waiting','Inventory reservation starts after payment/order readiness.','/orders')
        _set_step(process_id,'fulfilment','Waiting','Fulfilment starts after payment/order readiness.','/orders')
        _set_step(process_id,'shipping','Waiting','Shipment has not been prepared.','/orders')
        _set_step(process_id,'delivery','Waiting','No shipment is in transit.','/orders')
    returns=_count("SELECT count(*) n FROM v17_return_cases WHERE order_id=? AND status NOT IN ('Cancelled','Rejected')",(order_id,))
    _set_step(process_id,'returns','Complete' if returns else 'Ready',f'{returns} return/refund case(s) recorded.' if returns else 'Return/refund workflow is available if the customer needs it.','/operations/orders/'+order_id)
    acc=_count('SELECT count(*) n FROM v17_accounting_handoffs WHERE order_id=?',(order_id,))
    if not acc:
        try:prepare_accounting_handoff(order_id);acc=1
        except Exception as exc:
            from operational_guard import record_side_effect_failure
            record_side_effect_failure('order_process','Order accounting handoff could not be prepared',exc,recovery='Review the order financial data and retry the accounting handoff.',entity_type='order',entity_id=order_id,severity='Error',action_url='/operations/accounting')
    _set_step(process_id,'accounting','Complete' if acc else 'Needs attention','Accounting handoff record prepared for export/provider sync.' if acc else 'Could not prepare accounting handoff.','/operations/accounting')
    retention=_count('SELECT count(*) n FROM v17_retention_actions WHERE order_id=?',(order_id,))
    if payment_ok and not retention:
        try:plan_retention_for_order(order_id);retention=_count('SELECT count(*) n FROM v17_retention_actions WHERE order_id=?',(order_id,))
        except Exception as exc:
            from operational_guard import record_side_effect_failure
            record_side_effect_failure('order_process','Paid order could not prepare retention actions',exc,recovery='Review Customer 360 and the order, then retry the retention plan.',entity_type='order',entity_id=order_id,severity='Error',action_url='/operations/retention')
    _set_step(process_id,'post_purchase','Complete' if retention else 'Waiting',f'{retention} post-purchase/retention action(s) planned.' if retention else 'Post-purchase actions start after a verified purchase.','/operations/retention')
    touches=_count("SELECT count(*) n FROM v9_attribution_touchpoints WHERE contact_id=? AND event_type LIKE '%order%'",(str(o.get('contact_id') or ''),)) if m.table_exists('v9_attribution_touchpoints') and o.get('contact_id') else 0
    if o.get('contact_id') and not touches:
        try:
            import business_os as bos;bos.record_touchpoint(str(o.get('contact_id')),'order_purchase','commerce','CRM','order',value=float(o.get('total') or 0),currency=str(o.get('currency') or ''),metadata={'order_id':order_id});touches=1
        except Exception as exc:
            from operational_guard import record_side_effect_failure
            record_side_effect_failure('order_process','Order purchase touchpoint could not be recorded',exc,recovery='Review Customer 360 identity and attribution, then refresh the order process.',entity_type='order',entity_id=order_id,severity='Error',action_url='/marketing-performance')
    _set_step(process_id,'attribution','Complete' if touches else 'Needs attention',f'{touches} purchase attribution touchpoint(s).' if touches else 'Order has no customer/campaign attribution evidence yet.','/marketing-performance')
    _set_step(process_id,'retention','Complete' if retention else 'Waiting',f'{retention} retention action(s) planned.' if retention else 'Retention plan is waiting for purchase evidence.','/operations/retention')
    next_count=_count("SELECT count(*) n FROM v17_next_actions WHERE entity_type='order' AND entity_id=? AND status='Open'",(order_id,))
    if not next_count:
        if f and f.get('status')!='Delivered':next_action('order',order_id,'fulfilment','Complete order fulfilment','The order is not yet delivered.','High','/operations/orders/'+order_id)
        else:next_action('order',order_id,'review_retention','Review post-purchase journey','The order has moved into the retention stage.','Medium','/operations/retention')
        next_count=1
    _set_step(process_id,'next_action','Complete',f'{next_count} next-action record(s) are open.','/operations/actions')
    calculate_profitability('order',order_id)
    return _finish_process(process_id)


def refresh_process(process_id: str) -> dict:
    p=_one('SELECT * FROM v17_processes WHERE id=?',(process_id,))
    if not p:raise ValueError('Business process not found.')
    typ=p['process_type']
    if typ=='product_to_market':return refresh_product_process(process_id,p.get('product_id') or p['object_id'])
    if typ=='lead_to_sale':return refresh_lead_process(process_id,p.get('contact_id') or p['object_id'])
    if typ=='campaign_to_revenue':return refresh_campaign_process(process_id,p.get('campaign_id') or p['object_id'])
    if typ=='order_to_retention':return refresh_order_process(process_id,p.get('order_id') or p['object_id'])
    raise ValueError('Unsupported business process.')


def bootstrap_processes(limit: int=500) -> dict:
    initialise();created=0
    if m.table_exists('products'):
        for p in m.rows("SELECT product_id FROM products WHERE coalesce(status,'Draft')<>'Archived' ORDER BY created_at DESC LIMIT ?",(limit,)):
            before=_count("SELECT count(*) n FROM v17_processes WHERE process_type='product_to_market' AND object_id=?",(p['product_id'],));ensure_process('product_to_market','product',p['product_id'],product_id=p['product_id']);created+=0 if before else 1
    if m.table_exists('contacts'):
        for c in m.rows("SELECT contact_id FROM contacts WHERE coalesce(lead_score,0)>0 OR coalesce(qualification_status,'Unreviewed')<>'Unreviewed' ORDER BY created_at DESC LIMIT ?",(limit,)):
            before=_count("SELECT count(*) n FROM v17_processes WHERE process_type='lead_to_sale' AND object_id=?",(c['contact_id'],));ensure_process('lead_to_sale','contact',c['contact_id'],contact_id=c['contact_id']);created+=0 if before else 1
    if m.table_exists('v10_unified_campaigns'):
        for c in m.rows('SELECT id FROM v10_unified_campaigns ORDER BY created_at DESC LIMIT ?',(limit,)):
            before=_count("SELECT count(*) n FROM v17_processes WHERE process_type='campaign_to_revenue' AND object_id=?",(c['id'],));ensure_process('campaign_to_revenue','campaign',c['id'],campaign_id=c['id']);created+=0 if before else 1
    if m.table_exists('orders'):
        for o in m.rows('SELECT order_id,contact_id FROM orders ORDER BY ordered_at DESC LIMIT ?',(limit,)):
            before=_count("SELECT count(*) n FROM v17_processes WHERE process_type='order_to_retention' AND object_id=?",(o['order_id'],));ensure_process('order_to_retention','order',o['order_id'],order_id=o['order_id'],contact_id=o.get('contact_id') or '');created+=0 if before else 1
    return {'created':created,'total':_count('SELECT count(*) n FROM v17_processes')}


def refresh_all(limit: int=250) -> dict:
    initialise();bootstrap_processes(limit);rows=m.rows('SELECT id FROM v17_processes ORDER BY updated_at ASC LIMIT ?',(limit,));done=failed=0
    for r in rows:
        try:refresh_process(r['id']);done+=1
        except Exception as exc:
            failed+=1
            with m.connect() as con:con.execute("UPDATE v17_processes SET status='Needs attention',summary_json=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",(_json({'error':str(exc)}),r['id']))
    reconcile_inbox();process_due_social_posts(20);process_due_retention(100);generate_next_actions();calculate_profitability()
    return {'refreshed':done,'failed':failed,'total':len(rows)}


def start_for_event(event_type: str, entity_type: str, entity_id: str, payload: dict|None=None) -> list[str]:
    initialise();payload=payload or {};ids=[];event_type=event_type.upper()
    if entity_type=='product' or event_type in {'PRODUCT_CREATED','PRODUCT_UPDATED'}:
        ids.append(ensure_process('product_to_market','product',entity_id,product_id=entity_id))
    if entity_type=='contact' or event_type in {'LEAD_CREATED','MESSAGE_RECEIVED'}:
        cid=entity_id if entity_type=='contact' else str(payload.get('contact_id') or '')
        if cid:ids.append(ensure_process('lead_to_sale','contact',cid,contact_id=cid))
    if entity_type=='campaign' or event_type in {'CAMPAIGN_CREATED','CAMPAIGN_APPROVED'}:
        cid=entity_id if entity_type=='campaign' else str(payload.get('campaign_id') or '')
        if cid:ids.append(ensure_process('campaign_to_revenue','campaign',cid,campaign_id=cid))
    if entity_type=='order' or event_type in {'ORDER_PLACED','ORDER_SHIPPED','ORDER_DELIVERED','ORDER_REFUNDED'}:
        oid=entity_id if entity_type=='order' else str(payload.get('order_id') or '')
        if oid:
            o=_order_info(oid);ids.append(ensure_process('order_to_retention','order',oid,order_id=oid,contact_id=str(o.get('contact_id') or '')))
    for pid in ids:
        try:
            import durable_worker as dw
            dw.enqueue('v17.process.advance',{'process_id':pid},priority=45,idempotency_key='v17-process:'+pid+':'+event_type+':'+entity_id)
        except Exception as exc:
            # Process creation succeeded, but the durable handoff did not. Persist
            # the recovery state instead of silently returning a success-looking ID.
            with m.connect() as con:
                con.execute("UPDATE v17_processes SET status='Needs attention',summary_json=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                            (_json({'error':'Background process could not be queued','detail':str(exc)[:1000],'event_type':event_type}),pid))
            try:
                import operating_core as oc
                oc.incident('process','Error','Business process could not start',str(exc),
                            'Open Needs Attention or the process record, restore worker health, then retry. The canonical business record was preserved.',
                            entity_type,entity_id)
            except Exception:
                pass
    return ids


def schedule_social_post(campaign_id: str, channel: str, asset_url: str, caption: str, scheduled_at: str, product_id: str='') -> str:
    initialise()
    if channel not in {'Instagram','Facebook'}:raise ValueError('Choose Instagram or Facebook.')
    if not asset_url.startswith('https://'):raise ValueError('Social publishing requires a public HTTPS asset URL.')
    try:
        parsed=dt.datetime.fromisoformat(scheduled_at.replace('Z','+00:00'))
        if parsed.tzinfo is None:parsed=parsed.replace(tzinfo=dt.timezone.utc)
    except Exception:raise ValueError('Enter a valid scheduled date/time.') from None
    import integration_v14 as v14
    rr=v14.resolve_channel_connection('Instagram/Facebook')
    if rr.get('ambiguous'):raise ValueError('Choose the default Meta account before scheduling social posts.')
    conn=rr.get('connection');cid=conn['id'] if conn else ''
    sid=uid('SOC17')
    with m.connect() as con:con.execute('INSERT INTO v17_social_posts(id,campaign_id,product_id,channel,connection_id,asset_url,caption,scheduled_at,status) VALUES(?,?,?,?,?,?,?,?,?)',(sid,campaign_id,product_id,channel,cid,asset_url,caption[:4000],parsed.astimezone(dt.timezone.utc).replace(tzinfo=None).strftime('%Y-%m-%d %H:%M:%S'),'Scheduled' if cid else 'Needs setup'))
    return sid


def _legacy_l915_process_due_social_posts(limit: int=20) -> dict:
    initialise();rows=m.rows("SELECT * FROM v17_social_posts WHERE status IN ('Scheduled','Retry') AND scheduled_at<=CURRENT_TIMESTAMP ORDER BY scheduled_at LIMIT ?",(limit,));published=failed=0
    if not rows:return {'published':0,'failed':0,'checked':0}
    import integration_layer as il
    for post in rows:
        cid=post.get('connection_id') or ''
        if not cid:
            with m.connect() as con:con.execute("UPDATE v17_social_posts SET status='Needs setup',last_error='No default Meta social connection is configured.',updated_at=CURRENT_TIMESTAMP WHERE id=?",(post['id'],));failed+=1;continue
        try:
            if post['channel']=='Instagram':out=il.publish_instagram_image(cid,post['asset_url'],post.get('caption') or '')
            else:out=il.publish_facebook_page_image(cid,post['asset_url'],post.get('caption') or '')
            provider=str(out.get('id') or out.get('post_id') or out.get('creation_id') or '')
            with m.connect() as con:con.execute("UPDATE v17_social_posts SET status='Published',provider_post_id=?,last_error='',attempts=attempts+1,updated_at=CURRENT_TIMESTAMP WHERE id=?",(provider,post['id']));published+=1
        except Exception as exc:
            with m.connect() as con:con.execute("UPDATE v17_social_posts SET status=CASE WHEN attempts>=2 THEN 'Needs attention' ELSE 'Retry' END,last_error=?,attempts=attempts+1,updated_at=CURRENT_TIMESTAMP WHERE id=?",(str(exc)[:1200],post['id']));failed+=1
    return {'published':published,'failed':failed,'checked':len(rows)}


def _conversation(contact_id: str, channel: str, subject: str='') -> str:
    row=_one("SELECT id FROM v17_conversations WHERE contact_id=? AND channel=? AND status='Open' ORDER BY last_message_at DESC LIMIT 1",(contact_id,channel))
    if row:return row['id']
    cid=uid('CONV17')
    with m.connect() as con:con.execute('INSERT INTO v17_conversations(id,contact_id,channel,subject) VALUES(?,?,?,?)',(cid,contact_id,channel,subject[:300]))
    return cid


def reconcile_inbox(limit: int=1000) -> dict:
    initialise();added=0
    if m.table_exists('interactions'):
        rows=m.rows('SELECT * FROM interactions ORDER BY occurred_at DESC LIMIT ?',(limit,))
        for x in rows:
            source_id=str(x.get('interaction_id') or '')
            if not source_id or _one("SELECT id FROM v17_messages WHERE source_type='interaction' AND source_id=?",(source_id,)):continue
            channel=str(x.get('channel') or 'Other');contact=str(x.get('contact_id') or '');conv=_conversation(contact,channel,str(x.get('subject_or_summary') or ''))
            direction=str(x.get('direction') or '');body=str(x.get('subject_or_summary') or '')
            with m.connect() as con:
                con.execute('INSERT INTO v17_messages(id,conversation_id,source_type,source_id,direction,body,delivery_status,occurred_at,metadata_json) VALUES(?,?,?,?,?,?,?,?,?)',(uid('MSG17'),conv,'interaction',source_id,direction,body,'Recorded',x.get('occurred_at') or None,_json({'campaign_id':x.get('campaign_id')})))
                con.execute('UPDATE v17_conversations SET unread_count=unread_count+?,last_message_at=coalesce(?,CURRENT_TIMESTAMP),updated_at=CURRENT_TIMESTAMP WHERE id=?',(1 if direction.lower()=='inbound' else 0,x.get('occurred_at'),conv));added+=1
    if m.table_exists('v9_delivery_events'):
        rows=m.rows('SELECT * FROM v9_delivery_events ORDER BY occurred_at DESC LIMIT ?',(limit,))
        for x in rows:
            source_id=str(x.get('id') or '')
            if _one("SELECT id FROM v17_messages WHERE source_type='delivery' AND source_id=?",(source_id,)):continue
            contact=str(x.get('contact_id') or '');channel=str(x.get('channel') or 'Other');conv=_conversation(contact,channel,str(x.get('event_type') or ''))
            with m.connect() as con:
                con.execute('INSERT INTO v17_messages(id,conversation_id,source_type,source_id,direction,body,delivery_status,occurred_at,metadata_json) VALUES(?,?,?,?,?,?,?,?,?)',(uid('MSG17'),conv,'delivery',source_id,'System',str(x.get('event_type') or ''),str(x.get('event_type') or ''),x.get('occurred_at') or None,x.get('payload_json') or '{}'))
                con.execute('UPDATE v17_conversations SET last_message_at=coalesce(?,CURRENT_TIMESTAMP),updated_at=CURRENT_TIMESTAMP WHERE id=?',(x.get('occurred_at'),conv));added+=1
    return {'added':added,'conversations':_count('SELECT count(*) n FROM v17_conversations'),'messages':_count('SELECT count(*) n FROM v17_messages')}


def dashboard() -> dict:
    # Read-only snapshot. Process reconciliation belongs to the worker or the explicit
    # Refresh processes POST action; simply viewing a dashboard must not reserve stock,
    # create tasks, or otherwise mutate business state.
    initialise()
    profit=_one("SELECT * FROM v17_profitability WHERE scope_type='business' AND scope_id='default' ORDER BY calculated_at DESC LIMIT 1")
    if not profit:profit={'revenue':0.0,'cogs':0.0,'ad_spend':0.0,'gross_margin':0.0,'contribution':0.0,'currency':''}
    return {
        'process_counts':m.rows('SELECT status,count(*) n FROM v17_processes GROUP BY status ORDER BY status'),
        'open_actions':m.rows("SELECT * FROM v17_next_actions WHERE status='Open' ORDER BY CASE priority WHEN 'High' THEN 0 WHEN 'Medium' THEN 1 ELSE 2 END,created_at DESC LIMIT 20"),
        'fulfilments':m.rows("SELECT f.*,o.total,o.currency FROM v17_fulfilments f LEFT JOIN orders o USING(order_id) WHERE f.status<>'Delivered' ORDER BY f.created_at DESC LIMIT 20"),
        'returns':m.rows("SELECT * FROM v17_return_cases WHERE status NOT IN ('Completed','Rejected','Cancelled') ORDER BY requested_at DESC LIMIT 20"),
        'retention_due':m.rows("SELECT * FROM v17_retention_actions WHERE status='Planned' AND due_at<=CURRENT_TIMESTAMP ORDER BY due_at LIMIT 20"),
        'social_due':m.rows("SELECT * FROM v17_social_posts WHERE status IN ('Scheduled','Retry','Needs attention','Needs setup') ORDER BY scheduled_at LIMIT 20"),
        'profitability':profit,
        'inbox':{'open':_count("SELECT count(*) n FROM v17_conversations WHERE status='Open'"),'unread':int((_one('SELECT coalesce(sum(unread_count),0) n FROM v17_conversations').get('n') or 0))},
    }

# ---------------------------------------------------------------------------
# V18 Operations Completion layer
# ---------------------------------------------------------------------------

V18_SCHEMA = r'''
CREATE TABLE IF NOT EXISTS v18_return_items(
 return_id TEXT NOT NULL,
 order_item_id TEXT NOT NULL,
 product_id TEXT NOT NULL,
 quantity INTEGER NOT NULL,
 unit_price REAL NOT NULL DEFAULT 0,
 restocked_quantity INTEGER NOT NULL DEFAULT 0,
 created_at TEXT DEFAULT CURRENT_TIMESTAMP,
 PRIMARY KEY(return_id,order_item_id)
);
CREATE INDEX IF NOT EXISTS v18_return_items_product ON v18_return_items(product_id,created_at);
CREATE TABLE IF NOT EXISTS v18_accounting_entries(
 id TEXT PRIMARY KEY,
 order_id TEXT NOT NULL,
 source_type TEXT NOT NULL,
 source_id TEXT NOT NULL,
 entry_type TEXT NOT NULL,
 amount REAL DEFAULT 0,
 currency TEXT DEFAULT '',
 tax_amount REAL DEFAULT 0,
 status TEXT NOT NULL DEFAULT 'Prepared',
 external_id TEXT DEFAULT '',
 payload_json TEXT NOT NULL DEFAULT '{}',
 created_at TEXT DEFAULT CURRENT_TIMESTAMP,
 updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
 UNIQUE(source_type,source_id,entry_type)
);
CREATE INDEX IF NOT EXISTS v18_accounting_order ON v18_accounting_entries(order_id,created_at);
CREATE INDEX IF NOT EXISTS v18_accounting_status ON v18_accounting_entries(status,created_at);
CREATE TABLE IF NOT EXISTS v18_action_state(
 action_id TEXT PRIMARY KEY,
 snoozed_until TEXT,
 resolution_note TEXT DEFAULT '',
 resolved_at TEXT,
 updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS v18_operation_events(
 id TEXT PRIMARY KEY,
 object_type TEXT NOT NULL,
 object_id TEXT NOT NULL,
 event_type TEXT NOT NULL,
 detail TEXT DEFAULT '',
 actor TEXT DEFAULT '',
 payload_json TEXT NOT NULL DEFAULT '{}',
 created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS v18_operation_events_object ON v18_operation_events(object_type,object_id,created_at);
'''

_v17_initialise = _legacy_l267_initialise


def _v18_log(object_type: str, object_id: str, event_type: str, detail: str='', payload: dict|None=None, actor: str='system') -> str:
    eid=uid('OPE18')
    with m.connect() as con:
        con.execute('INSERT INTO v18_operation_events(id,object_type,object_id,event_type,detail,actor,payload_json) VALUES(?,?,?,?,?,?,?)',
                    (eid,object_type,object_id,event_type,detail[:3000],actor[:120],_json(payload)))
    return eid


def _legacy_l1048_initialise() -> None:
    """Initialise V17 compatibility schema plus V18 operational-integrity tables."""
    _v17_initialise()
    with m.connect() as con:
        con.executescript(V18_SCHEMA)
    # Carry forward the old single-row accounting handoffs so V18 starts with a
    # complete finance queue without changing the previous database in place.
    if m.table_exists('v17_accounting_handoffs'):
        for row in m.rows('SELECT * FROM v17_accounting_handoffs ORDER BY created_at'):
            payload={}
            try:payload=json.loads(row.get('payload_json') or '{}')
            except Exception:pass
            is_refund=str(row.get('handoff_type') or '').lower()=='refund'
            if is_refund and payload.get('aggregate'):
                continue
            source_type='return' if is_refund else 'order'
            source_id=str(payload.get('return_id') or row.get('id') or row.get('order_id'))
            with m.connect() as con:
                con.execute('''INSERT INTO v18_accounting_entries(id,order_id,source_type,source_id,entry_type,amount,currency,tax_amount,status,external_id,payload_json,created_at,updated_at)
                               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(source_type,source_id,entry_type) DO NOTHING''',
                            (uid('ACC18'),row.get('order_id') or '',source_type,source_id,row.get('handoff_type') or 'Sale',float(row.get('amount') or 0),row.get('currency') or '',float(row.get('tax_amount') or 0),row.get('status') or 'Prepared',row.get('external_id') or '',row.get('payload_json') or '{}',row.get('created_at'),row.get('updated_at')))


def operation_events(object_type: str, object_id: str, limit: int=100) -> list[dict]:
    initialise()
    return m.rows('SELECT * FROM v18_operation_events WHERE object_type=? AND object_id=? ORDER BY created_at DESC LIMIT ?',
                  (object_type,object_id,max(1,min(int(limit),500))))


def _legacy_l1077_order_returnable_items(order_id: str) -> list[dict]:
    """Return order lines and the quantity still eligible for a new return case."""
    initialise()
    if not m.table_exists('order_items'):return []
    rows=m.rows('''SELECT oi.order_item_id,oi.product_id,oi.quantity,oi.unit_price,
                          coalesce(p.public_product_name,p.product_code,p.internal_sku,oi.product_id) product_name
                   FROM order_items oi LEFT JOIN products p ON p.product_id=oi.product_id
                   WHERE oi.order_id=? ORDER BY oi.order_item_id''',(order_id,))
    out=[]
    for row in rows:
        claimed=_one('''SELECT coalesce(sum(ri.quantity),0) qty
                        FROM v18_return_items ri JOIN v17_return_cases r ON r.id=ri.return_id
                        WHERE r.order_id=? AND ri.order_item_id=? AND r.status NOT IN ('Rejected','Cancelled')''',(order_id,row['order_item_id'])).get('qty') or 0
        item=dict(row);item['claimed_quantity']=int(claimed);item['returnable_quantity']=max(0,int(row.get('quantity') or 0)-int(claimed));out.append(item)
    return out


def return_items(return_id: str) -> list[dict]:
    initialise()
    return m.rows('''SELECT ri.*,coalesce(p.public_product_name,p.product_code,p.internal_sku,ri.product_id) product_name
                     FROM v18_return_items ri LEFT JOIN products p ON p.product_id=ri.product_id
                     WHERE ri.return_id=? ORDER BY ri.order_item_id''',(return_id,))


def _active_reserved_for_order_product(order_id: str, product_id: str, location_id: str='MAIN') -> int:
    reserve=int((_one("SELECT coalesce(sum(quantity),0) qty FROM v17_inventory_movements WHERE reference_type='order' AND reference_id=? AND product_id=? AND location_id=? AND movement_type='Reserve'",(order_id,product_id,location_id)).get('qty') or 0))
    release=int((_one("SELECT coalesce(sum(quantity),0) qty FROM v17_inventory_movements WHERE reference_type='order' AND reference_id=? AND product_id=? AND location_id=? AND movement_type IN ('Release reservation','Consume reservation')",(order_id,product_id,location_id)).get('qty') or 0))
    return max(0,reserve-release)

def _reservation_locations(order_id: str, product_id: str) -> list[dict]:
    """Return active reservations by actual stock location."""
    rows=m.rows("""SELECT location_id,
        coalesce(sum(CASE WHEN movement_type='Reserve' THEN quantity ELSE 0 END),0)-
        coalesce(sum(CASE WHEN movement_type IN ('Release reservation','Consume reservation') THEN quantity ELSE 0 END),0) active
        FROM v17_inventory_movements
        WHERE reference_type='order' AND reference_id=? AND product_id=?
        GROUP BY location_id
        HAVING active>0 ORDER BY location_id""",(order_id,product_id))
    return [dict(x,active=max(0,int(x.get('active') or 0))) for x in rows]

def _choose_reservation_location(product_id: str, qty: int, preferred: str='') -> str|None:
    args=[product_id];where='product_id=?'
    if preferred:
        row=m.one('SELECT location_id,on_hand,reserved FROM v9_inventory WHERE product_id=? AND location_id=?',(product_id,preferred))
        if row and int(row.get('on_hand') or 0)-int(row.get('reserved') or 0)>=qty:return preferred
    rows=m.rows('SELECT location_id,on_hand,reserved FROM v9_inventory WHERE product_id=? ORDER BY (on_hand-reserved) DESC,location_id',(product_id,))
    for row in rows:
        if int(row.get('on_hand') or 0)-int(row.get('reserved') or 0)>=qty:return row['location_id']
    return rows[0]['location_id'] if rows else None


def _legacy_l1128_reserve_order_inventory(order_id: str, location_id: str='') -> dict:
    """Idempotently reserve order quantities against real stock locations.

    V36 no longer assumes MAIN. Existing reservations remain at their original
    locations; new quantities use the preferred location when possible, otherwise
    the location with the most available stock.
    """
    initialise();items=m.rows('SELECT product_id,quantity FROM order_items WHERE order_id=?',(order_id,)) if m.table_exists('order_items') else []
    if not items:return {'reserved':0,'released':0,'shortages':[],'detail':'No order-item rows are available; inventory reservation needs item data.'}
    newly_reserved=0;released=0;shortages=[]
    for item in items:
        pid=item['product_id'];needed=max(0,int(item.get('quantity') or 0))
        existing=_reservation_locations(order_id,pid);active=sum(x['active'] for x in existing)
        if active>needed:
            excess=active-needed
            for loc in reversed(existing):
                use=min(excess,loc['active'])
                if not use:continue
                with m.connect() as con:
                    con.execute('UPDATE v9_inventory SET reserved=max(0,reserved-?),updated_at=CURRENT_TIMESTAMP WHERE product_id=? AND location_id=?',(use,pid,loc['location_id']))
                    con.execute('INSERT INTO v17_inventory_movements(id,product_id,location_id,movement_type,quantity,reference_type,reference_id,note) VALUES(?,?,?,?,?,?,?,?)',(uid('MOV36'),pid,loc['location_id'],'Release reservation',use,'order',order_id,'Released excess reservation after order quantity changed.'))
                released+=use;excess-=use
                if excess<=0:break
            active=needed
        remaining=max(0,needed-active)
        while remaining>0:
            loc=_choose_reservation_location(pid,remaining,location_id)
            if not loc:
                shortages.append({'product_id':pid,'needed':remaining,'available':0});break
            inv=_one('SELECT on_hand,reserved FROM v9_inventory WHERE product_id=? AND location_id=?',(pid,loc))
            available=max(0,int(inv.get('on_hand') or 0)-int(inv.get('reserved') or 0));use=min(remaining,available)
            if use<=0:
                shortages.append({'product_id':pid,'needed':remaining,'available':available});break
            with m.connect() as con:
                con.execute('UPDATE v9_inventory SET reserved=reserved+?,updated_at=CURRENT_TIMESTAMP WHERE product_id=? AND location_id=?',(use,pid,loc))
                con.execute('INSERT INTO v17_inventory_movements(id,product_id,location_id,movement_type,quantity,reference_type,reference_id,note) VALUES(?,?,?,?,?,?,?,?)',(uid('MOV36'),pid,loc,'Reserve',use,'order',order_id,'Canonical reservation.'))
            newly_reserved+=use;remaining-=use
    with m.connect() as con:con.execute('UPDATE v17_fulfilments SET inventory_status=?,updated_at=CURRENT_TIMESTAMP WHERE order_id=?',('Shortage' if shortages else 'Reserved',order_id))
    _v18_log('order',order_id,'inventory.reservation','Inventory reservation reconciled.',{'reserved':newly_reserved,'released':released,'shortages':shortages})
    return {'reserved':newly_reserved,'released':released,'shortages':shortages,'detail':'Inventory reservation reconciled.' if not shortages else 'Inventory shortage/review required.'}

def _legacy_l1169_release_order_reservations(order_id: str, location_id: str='') -> dict:
    """Release every active reservation for an order at its actual location."""
    initialise();released=0
    products=m.rows("SELECT DISTINCT product_id FROM v17_inventory_movements WHERE reference_type='order' AND reference_id=?",(order_id,))
    for r in products:
        for loc in _reservation_locations(order_id,r['product_id']):
            qty=loc['active']
            if qty<=0:continue
            with m.connect() as con:
                con.execute('UPDATE v9_inventory SET reserved=max(0,reserved-?),updated_at=CURRENT_TIMESTAMP WHERE product_id=? AND location_id=?',(qty,r['product_id'],loc['location_id']))
                con.execute('INSERT INTO v17_inventory_movements(id,product_id,location_id,movement_type,quantity,reference_type,reference_id,note) VALUES(?,?,?,?,?,?,?,?)',(uid('MOV36'),r['product_id'],loc['location_id'],'Release reservation',qty,'order',order_id,'Reservation release.'))
            released+=qty
    return {'released':released}

def consume_order_reservations(order_id: str) -> dict:
    """Atomically consume active reservations and decrement canonical on-hand."""
    import v35_truth as truth
    initialise();consumed=0
    products=m.rows("SELECT DISTINCT product_id FROM v17_inventory_movements WHERE reference_type='order' AND reference_id=?",(order_id,))
    for r in products:
        pid=r['product_id']
        for loc in _reservation_locations(order_id,pid):
            qty=loc['active']
            if qty<=0:continue
            inv=truth.canonical_inventory(pid,loc['location_id'])
            if int(inv['on_hand'])<qty:raise ValueError(f'Inventory for {pid} at {loc["location_id"]} is below its reserved quantity. Reconcile stock before shipping.')
            with m.connect() as con:
                con.execute('UPDATE v9_inventory SET reserved=max(0,reserved-?),updated_at=CURRENT_TIMESTAMP WHERE product_id=? AND location_id=?',(qty,pid,loc['location_id']))
                con.execute('INSERT INTO v17_inventory_movements(id,product_id,location_id,movement_type,quantity,reference_type,reference_id,note) VALUES(?,?,?,?,?,?,?,?)',(uid('MOV36'),pid,loc['location_id'],'Consume reservation',qty,'order',order_id,'Reservation consumed by dispatch.'))
            truth.adjust_stock_delta(pid,loc['location_id'],-qty,'Dispatch','Order shipped',reference_type='order',reference_id=order_id)
            consumed+=qty
    return {'consumed':consumed}


def mark_packed(fulfilment_id: str) -> None:
    initialise();f=_one('SELECT * FROM v17_fulfilments WHERE id=?',(fulfilment_id,))
    if not f:raise ValueError('Fulfilment not found.')
    if f.get('status') in {'Shipped','Delivered'}:raise ValueError('This fulfilment has already left the packing stage.')
    if f.get('inventory_status')=='Shortage':raise ValueError('Resolve the inventory shortage before marking this order packed.')
    if f.get('status')=='Needs item review':raise ValueError('Add/review order items before packing this order.')
    with m.connect() as con:con.execute("UPDATE v17_fulfilments SET status='Packed',packed_at=coalesce(packed_at,CURRENT_TIMESTAMP),updated_at=CURRENT_TIMESTAMP,last_error='' WHERE id=?",(fulfilment_id,))
    _v18_log('order',f['order_id'],'fulfilment.packed','Order marked packed.',{'fulfilment_id':fulfilment_id})


def _legacy_l1213_mark_shipped(fulfilment_id: str, carrier: str, tracking_number: str, tracking_url: str='') -> None:
    initialise();f=_one('SELECT * FROM v17_fulfilments WHERE id=?',(fulfilment_id,))
    if not f:raise ValueError('Fulfilment not found.')
    if f.get('status')=='Delivered':raise ValueError('A delivered fulfilment cannot be shipped again.')
    if f.get('status')!='Packed':raise ValueError('Mark the order packed before confirming shipment.')
    carrier=carrier.strip();tracking_number=tracking_number.strip();tracking_url=tracking_url.strip()
    if not carrier or not tracking_number:raise ValueError('Carrier and tracking number are required before marking shipped.')
    if tracking_url and not tracking_url.startswith('https://'):raise ValueError('Tracking URL must use HTTPS.')
    consume_order_reservations(f['order_id'])
    with m.connect() as con:con.execute("UPDATE v17_fulfilments SET status='Shipped',carrier=?,tracking_number=?,tracking_url=?,shipped_at=coalesce(shipped_at,CURRENT_TIMESTAMP),updated_at=CURRENT_TIMESTAMP,last_error='' WHERE id=?",(carrier[:120],tracking_number[:200],tracking_url[:1000],fulfilment_id))
    _v18_log('order',f['order_id'],'fulfilment.shipped',f'Shipped with {carrier}.',{'tracking_number':tracking_number,'tracking_url':tracking_url})
    _emit_event_safe('ORDER_SHIPPED','order',f['order_id'],{'fulfilment_id':fulfilment_id,'carrier':carrier,'tracking_number':tracking_number},dedupe_key='shipped:'+fulfilment_id,title='Shipment saved but ORDER_SHIPPED automation event failed')


def _legacy_l1229_mark_delivered(fulfilment_id: str) -> None:
    initialise();f=_one('SELECT * FROM v17_fulfilments WHERE id=?',(fulfilment_id,))
    if not f:raise ValueError('Fulfilment not found.')
    if f.get('status')=='Delivered':return
    if f.get('status')!='Shipped':raise ValueError('Confirm shipment before confirming delivery.')
    with m.connect() as con:con.execute("UPDATE v17_fulfilments SET status='Delivered',delivered_at=CURRENT_TIMESTAMP,updated_at=CURRENT_TIMESTAMP,last_error='' WHERE id=?",(fulfilment_id,))
    _v18_log('order',f['order_id'],'fulfilment.delivered','Delivery confirmed.',{'fulfilment_id':fulfilment_id})
    _emit_event_safe('ORDER_DELIVERED','order',f['order_id'],{'fulfilment_id':fulfilment_id},dedupe_key='delivered:'+fulfilment_id,title='Delivery saved but ORDER_DELIVERED automation event failed')
    plan_retention_for_order(f['order_id'])


def create_return(order_id: str, reason: str, requested_resolution: str='Refund', case_type: str='Return', item_quantities: dict[str,int]|None=None) -> str:
    initialise();o=_order_info(order_id)
    if not o:raise ValueError('Order not found.')
    fulfil=_one('SELECT status FROM v17_fulfilments WHERE order_id=?',(order_id,))
    if str(o.get('order_status') or '') not in {'Fulfilled','Refunded'} and str(fulfil.get('status') or '') not in {'Partially shipped','Shipped','Delivered'}:
        raise ValueError('A return can only be opened after the order has been shipped or fulfilled.')
    if requested_resolution not in {'Refund','Exchange','Store credit','Repair/other'}:raise ValueError('Choose a supported return resolution.')
    if case_type not in {'Return','Exchange','Refund request'}:raise ValueError('Choose a supported case type.')
    if not reason.strip():raise ValueError('Add the customer reason before opening the case.')
    available=order_returnable_items(order_id);chosen=[]
    if available:
        if item_quantities is None:
            # Backward-compatible programmatic behaviour: return all currently
            # returnable quantities. The V18 UI always sends explicit quantities.
            item_quantities={x['order_item_id']:x['returnable_quantity'] for x in available if x['returnable_quantity']>0}
        for item in available:
            qty=int((item_quantities or {}).get(item['order_item_id'],0) or 0)
            if qty<0:raise ValueError('Return quantities cannot be negative.')
            if qty>int(item['returnable_quantity']):raise ValueError(f"Return quantity for {item['product_name']} exceeds the quantity still eligible for return.")
            if qty:chosen.append((item,qty))
        if not chosen:raise ValueError('Choose at least one order item and quantity for this return/exchange.')
    rid=uid('RET18')
    with m.connect() as con:
        con.execute('INSERT INTO v17_return_cases(id,order_id,contact_id,case_type,reason,requested_resolution,currency) VALUES(?,?,?,?,?,?,?)',(rid,order_id,str(o.get('contact_id') or ''),case_type,reason.strip()[:2000],requested_resolution,str(o.get('currency') or '')))
        for item,qty in chosen:
            con.execute('INSERT INTO v18_return_items(return_id,order_item_id,product_id,quantity,unit_price) VALUES(?,?,?,?,?)',(rid,item['order_item_id'],item['product_id'],qty,float(item.get('unit_price') or 0)))
    _v18_log('return',rid,'return.opened',f'{case_type} opened for order {order_id}.',{'resolution':requested_resolution,'items':[{'order_item_id':x[0]['order_item_id'],'quantity':x[1]} for x in chosen]})
    _emit_event_safe('RETURN_REQUESTED','order',order_id,{'return_id':rid,'resolution':requested_resolution,'contact_id':o.get('contact_id')},dedupe_key='return:'+rid,title='Return saved but RETURN_REQUESTED automation event failed')
    return rid


_RETURN_TRANSITIONS={
    'Requested':{'Approved','Rejected','Cancelled'},
    'Approved':{'In transit','Received','Cancelled'},
    'In transit':{'Received'},
    'Received':{'Refund pending','Completed'},
    'Refund pending':{'Completed'},
    'Completed':set(),'Rejected':set(),'Cancelled':set(),
}


def _legacy_l1285__return_value(return_id: str) -> float:
    items=return_items(return_id)
    if items:return round(sum(int(x.get('quantity') or 0)*float(x.get('unit_price') or 0) for x in items),2)
    r=_one('SELECT order_id FROM v17_return_cases WHERE id=?',(return_id,));o=_order_info(r.get('order_id') or '')
    return round(float(o.get('total') or 0),2) if o else 0.0


def _prepare_refund_accounting(return_id: str, amount: float, external_refund_id: str='', note: str='') -> str:
    r=_one('SELECT * FROM v17_return_cases WHERE id=?',(return_id,))
    if not r:raise ValueError('Return case not found.')
    aid=uid('ACC18')
    payload={'return_id':return_id,'note':note}
    with m.connect() as con:
        con.execute('''INSERT INTO v18_accounting_entries(id,order_id,source_type,source_id,entry_type,amount,currency,status,external_id,payload_json)
                       VALUES(?,?,?,?,?,?,?,?,?,?)
                       ON CONFLICT(source_type,source_id,entry_type) DO UPDATE SET amount=excluded.amount,currency=excluded.currency,status='Prepared',external_id=excluded.external_id,payload_json=excluded.payload_json,updated_at=CURRENT_TIMESTAMP''',
                    (aid,r['order_id'],'return',return_id,'Refund',-abs(float(amount)),r.get('currency') or '','Prepared',external_refund_id[:200],_json(payload)))
        # Preserve the legacy aggregate row for older reporting code, but make it
        # an aggregate of completed V18 refunds rather than overwriting arbitrarily.
        total=float((_one("SELECT coalesce(sum(refund_amount),0) v FROM v17_return_cases WHERE order_id=? AND status='Completed'",(r['order_id'],)).get('v') or 0))
        con.execute("""INSERT INTO v17_accounting_handoffs(id,order_id,handoff_type,amount,currency,status,external_id,payload_json)
                       VALUES(?,?,?,?,?,'Prepared',?,?)
                       ON CONFLICT(order_id,handoff_type) DO UPDATE SET amount=excluded.amount,currency=excluded.currency,status='Prepared',external_id=excluded.external_id,payload_json=excluded.payload_json,updated_at=CURRENT_TIMESTAMP""",
                    (uid('ACC17'),r['order_id'],'Refund',-abs(total),r.get('currency') or '',external_refund_id[:200],_json({'latest_return_id':return_id,'aggregate':True})))
    return aid


def _legacy_l1312_update_return(return_id: str, status: str, refund_amount: float|str=0, restock: bool=False, note: str='', external_refund_id: str='') -> None:
    initialise();r=_one('SELECT * FROM v17_return_cases WHERE id=?',(return_id,))
    if not r:raise ValueError('Return case not found.')
    if status not in _RETURN_TRANSITIONS:raise ValueError('Choose a valid return status.')
    current=str(r.get('status') or 'Requested')
    if status!=current and status not in _RETURN_TRANSITIONS.get(current,set()):raise ValueError(f'Cannot move a return from {current} directly to {status}. Use the next operational stage.')
    try:amount=max(0,float(refund_amount or 0))
    except Exception:raise ValueError('Enter a valid refund amount.') from None
    max_value=_return_value(return_id)
    if amount>max_value+0.001:raise ValueError(f'Refund amount cannot exceed the returned-item value ({r.get("currency") or ""} {max_value:.2f}).')
    if status=='Completed' and r.get('requested_resolution')=='Refund' and amount>0 and not external_refund_id.strip():
        raise ValueError('Record the payment-provider or manual refund reference before marking a monetary refund completed.')
    with m.connect() as con:
        con.execute("UPDATE v17_return_cases SET status=?,refund_amount=?,restock=?,note=?,external_refund_id=?,received_at=CASE WHEN ?='Received' AND received_at IS NULL THEN CURRENT_TIMESTAMP ELSE received_at END,completed_at=CASE WHEN ?='Completed' AND completed_at IS NULL THEN CURRENT_TIMESTAMP ELSE completed_at END,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (status,amount,1 if restock else 0,note[:2000],external_refund_id[:200],status,status,return_id))
    _v18_log('return',return_id,'return.status',f'{current} → {status}.',{'refund_amount':amount,'restock':bool(restock),'external_refund_id':external_refund_id})
    if status=='Completed':
        if amount>0:_prepare_refund_accounting(return_id,amount,external_refund_id,note)
        if restock:
            explicit_items=return_items(return_id)
            items=explicit_items
            if not items:
                items=[dict(x,restocked_quantity=0) for x in m.rows('SELECT order_item_id,product_id,quantity,unit_price FROM order_items WHERE order_id=?',(r['order_id'],))]
            pending=[]
            for item in items:
                qty=max(0,int(item.get('quantity') or 0)-int(item.get('restocked_quantity') or 0))
                if qty:pending.append((item,qty))
            with m.connect() as con:
                for item,qty in pending:
                    loc=_return_location(r['order_id'],item['product_id'])
                    con.execute('INSERT INTO v17_inventory_movements(id,product_id,location_id,movement_type,quantity,reference_type,reference_id,note) VALUES(?,?,?,?,?,?,?,?)',(uid('MOV36'),item['product_id'],loc,'Return restock',qty,'return',return_id,'Returned quantity received and posted to canonical inventory.'))
                    if explicit_items:con.execute('UPDATE v18_return_items SET restocked_quantity=restocked_quantity+? WHERE return_id=? AND order_item_id=?',(qty,return_id,item['order_item_id']))
            import v35_truth as truth
            for item,qty in pending:
                truth.adjust_stock_delta(item['product_id'],_return_location(r['order_id'],item['product_id']),qty,'Customer return','Completed return restock',reference_type='return',reference_id=return_id,order_item_id=item.get('order_item_id') or '')
        _emit_event_safe('ORDER_REFUNDED','order',r['order_id'],{'return_id':return_id,'refund_amount':amount,'external_refund_id':external_refund_id},dedupe_key='refund:'+return_id,title='Refund saved but ORDER_REFUNDED automation event failed')


def prepare_accounting_handoff(order_id: str) -> str:
    initialise();o=_order_info(order_id)
    if not o:raise ValueError('Order not found.')
    kind='Sale';aid=uid('ACC18');payload={'external_order_reference':o.get('external_order_reference'),'contact_id':o.get('contact_id')}
    with m.connect() as con:
        con.execute('''INSERT INTO v18_accounting_entries(id,order_id,source_type,source_id,entry_type,amount,currency,status,payload_json)
                       VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(source_type,source_id,entry_type) DO UPDATE SET amount=excluded.amount,currency=excluded.currency,payload_json=excluded.payload_json,updated_at=CURRENT_TIMESTAMP''',
                    (aid,order_id,'order',order_id,kind,float(o.get('total') or 0),str(o.get('currency') or ''),'Prepared',_json(payload)))
        # Compatibility row used by older process/report code.
        con.execute('''INSERT INTO v17_accounting_handoffs(id,order_id,handoff_type,amount,currency,status,payload_json)
                       VALUES(?,?,?,?,?,?,?) ON CONFLICT(order_id,handoff_type) DO UPDATE SET amount=excluded.amount,currency=excluded.currency,payload_json=excluded.payload_json,updated_at=CURRENT_TIMESTAMP''',
                    (uid('ACC17'),order_id,kind,float(o.get('total') or 0),str(o.get('currency') or ''),'Prepared',_json(payload)))
    return (_one("SELECT id FROM v18_accounting_entries WHERE source_type='order' AND source_id=? AND entry_type='Sale'",(order_id,)).get('id') or aid)


def accounting_export_rows(limit: int=5000) -> list[dict]:
    initialise();return m.rows('SELECT * FROM v18_accounting_entries ORDER BY created_at DESC LIMIT ?',(max(1,min(int(limit),20000)),))


def update_accounting_entry(entry_id: str, status: str, external_id: str='', note: str='') -> None:
    initialise();allowed={'Prepared','Exported','Posted','Rejected'}
    if status not in allowed:raise ValueError('Choose a valid accounting status.')
    if status=='Posted' and not external_id.strip():raise ValueError('Record the accounting/provider posting reference before marking this entry Posted.')
    row=_one('SELECT * FROM v18_accounting_entries WHERE id=?',(entry_id,))
    if not row:raise ValueError('Accounting entry not found.')
    payload={}
    try:payload=json.loads(row.get('payload_json') or '{}')
    except Exception:pass
    if note:payload['note']=note[:2000]
    with m.connect() as con:con.execute('UPDATE v18_accounting_entries SET status=?,external_id=?,payload_json=?,updated_at=CURRENT_TIMESTAMP WHERE id=?',(status,external_id[:200],_json(payload),entry_id))
    _v18_log('order',row['order_id'],'accounting.status',f"{row['entry_type']} handoff → {status}.",{'entry_id':entry_id,'external_id':external_id})


def next_action(entity_type: str, entity_id: str, action_type: str, title: str, reason: str, priority: str='Medium', action_url: str='', dedupe_key: str='') -> str:
    """Upsert a next action without violating the unique dedupe key after resolution."""
    initialise();dedupe_key=dedupe_key or f'{entity_type}:{entity_id}:{action_type}'
    existing=_one('SELECT * FROM v17_next_actions WHERE dedupe_key=?',(dedupe_key,))
    if existing:
        state=_one('SELECT * FROM v18_action_state WHERE action_id=?',(existing['id'],))
        snoozed=(state.get('snoozed_until') or '') if state else ''
        if snoozed:
            try:
                until=dt.datetime.fromisoformat(str(snoozed).replace('Z','+00:00'))
                if until.tzinfo is None:until=until.replace(tzinfo=dt.timezone.utc)
                if until>dt.datetime.now(dt.timezone.utc):return existing['id']
            except Exception:pass
        with m.connect() as con:
            con.execute("UPDATE v17_next_actions SET entity_type=?,entity_id=?,action_type=?,title=?,reason=?,priority=?,action_url=?,status='Open',updated_at=CURRENT_TIMESTAMP WHERE id=?",
                        (entity_type,entity_id,action_type,title[:300],reason[:3000],priority,action_url[:1000],existing['id']))
            con.execute('INSERT INTO v18_action_state(action_id,snoozed_until,resolution_note,resolved_at) VALUES(?,?,?,?) ON CONFLICT(action_id) DO UPDATE SET snoozed_until=NULL,resolution_note=\'\',resolved_at=NULL,updated_at=CURRENT_TIMESTAMP',(existing['id'],None,'',None))
        return existing['id']
    nid=uid('NEXT18')
    with m.connect() as con:con.execute('INSERT INTO v17_next_actions(id,entity_type,entity_id,action_type,title,reason,priority,action_url,dedupe_key) VALUES(?,?,?,?,?,?,?,?,?)',(nid,entity_type,entity_id,action_type,title[:300],reason[:3000],priority,action_url[:1000],dedupe_key))
    return nid


def resolve_next_action(action_id: str, note: str='') -> None:
    initialise();row=_one('SELECT * FROM v17_next_actions WHERE id=?',(action_id,))
    if not row:raise ValueError('Next action not found.')
    with m.connect() as con:
        con.execute("UPDATE v17_next_actions SET status='Done',updated_at=CURRENT_TIMESTAMP WHERE id=?",(action_id,))
        con.execute("INSERT INTO v18_action_state(action_id,resolution_note,resolved_at) VALUES(?,?,CURRENT_TIMESTAMP) ON CONFLICT(action_id) DO UPDATE SET resolution_note=excluded.resolution_note,resolved_at=CURRENT_TIMESTAMP,snoozed_until=NULL,updated_at=CURRENT_TIMESTAMP",(action_id,note[:1000]))
    _v18_log(row['entity_type'],row['entity_id'],'next_action.resolved',row['title'],{'action_id':action_id,'note':note})


def snooze_next_action(action_id: str, days: int=1) -> None:
    initialise();row=_one('SELECT * FROM v17_next_actions WHERE id=?',(action_id,))
    if not row:raise ValueError('Next action not found.')
    days=max(1,min(int(days),90));until=(dt.datetime.now(dt.timezone.utc)+dt.timedelta(days=days)).replace(microsecond=0).strftime('%Y-%m-%d %H:%M:%S')
    with m.connect() as con:
        con.execute("UPDATE v17_next_actions SET status='Snoozed',updated_at=CURRENT_TIMESTAMP WHERE id=?",(action_id,))
        con.execute("INSERT INTO v18_action_state(action_id,snoozed_until) VALUES(?,?) ON CONFLICT(action_id) DO UPDATE SET snoozed_until=excluded.snoozed_until,updated_at=CURRENT_TIMESTAMP",(action_id,until))
    _v18_log(row['entity_type'],row['entity_id'],'next_action.snoozed',f'Snoozed until {until}.',{'action_id':action_id})


def process_due_retention(limit: int=100) -> dict:
    """Prepare due retention work and expose it as an actionable Operations item."""
    initialise();rows=m.rows("SELECT * FROM v17_retention_actions WHERE status='Planned' AND due_at<=CURRENT_TIMESTAMP ORDER BY due_at LIMIT ?",(limit,));prepared=0
    for r in rows:
        cid=r['contact_id'];channel=''
        perms=m.rows("SELECT channel,status FROM marketing_permissions WHERE contact_id=? AND status IN ('Allowed','OptedIn') ORDER BY CASE channel WHEN 'Email' THEN 0 WHEN 'WhatsApp' THEN 1 ELSE 2 END",(cid,))
        if perms:channel=perms[0]['channel']
        title=r['title'];task_id=''
        if m.table_exists('m4_tasks'):
            existing=_one("SELECT id FROM m4_tasks WHERE contact_id=? AND status='Open' AND title=? ORDER BY created_at DESC LIMIT 1",(cid,title))
            if existing:task_id=existing['id']
            else:
                task_id=m.uid('TASK')
                with m.connect() as con:con.execute("INSERT INTO m4_tasks(id,title,contact_id,due_date,status) VALUES(?,?,?,?,?)",(task_id,title,cid,dt.date.today().isoformat(),'Open'))
        with m.connect() as con:con.execute("UPDATE v17_retention_actions SET status='Ready',channel=?,payload_json=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",(channel,_json({'task_id':task_id,'requires_reviewed_content':True}),r['id']))
        next_action('contact',cid,r['action_type'],title,r['reason'],'Medium','/operations/retention',dedupe_key='retention:'+r['id'])
        prepared+=1
    return {'checked':len(rows),'prepared':prepared}


def update_retention_action(action_id: str, action: str, days: int=7) -> None:
    initialise();r=_one('SELECT * FROM v17_retention_actions WHERE id=?',(action_id,))
    if not r:raise ValueError('Retention action not found.')
    if action=='complete':
        with m.connect() as con:con.execute("UPDATE v17_retention_actions SET status='Completed',updated_at=CURRENT_TIMESTAMP WHERE id=?",(action_id,))
        existing=_one("SELECT id FROM v17_next_actions WHERE dedupe_key=?",('retention:'+action_id,))
        if existing:resolve_next_action(existing['id'],'Retention action completed.')
    elif action=='cancel':
        with m.connect() as con:con.execute("UPDATE v17_retention_actions SET status='Cancelled',updated_at=CURRENT_TIMESTAMP WHERE id=?",(action_id,))
        existing=_one("SELECT id FROM v17_next_actions WHERE dedupe_key=?",('retention:'+action_id,))
        if existing:resolve_next_action(existing['id'],'Retention action cancelled.')
    elif action=='snooze':
        days=max(1,min(int(days),90));due=(dt.datetime.now(dt.timezone.utc)+dt.timedelta(days=days)).replace(microsecond=0).strftime('%Y-%m-%d %H:%M:%S')
        with m.connect() as con:con.execute("UPDATE v17_retention_actions SET status='Planned',due_at=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",(due,action_id))
        existing=_one("SELECT id FROM v17_next_actions WHERE dedupe_key=?",('retention:'+action_id,))
        if existing:snooze_next_action(existing['id'],days)
    else:raise ValueError('Choose complete, snooze or cancel.')
    _v18_log('contact',r['contact_id'],'retention.'+action,r['title'],{'retention_action_id':action_id,'days':days})


def assign_conversation(conversation_id: str, owner: str) -> None:
    initialise();c=_one('SELECT * FROM v17_conversations WHERE id=?',(conversation_id,))
    if not c:raise ValueError('Conversation not found.')
    with m.connect() as con:con.execute('UPDATE v17_conversations SET owner=?,updated_at=CURRENT_TIMESTAMP WHERE id=?',(owner.strip()[:120],conversation_id))
    _v18_log('conversation',conversation_id,'conversation.assigned',f'Assigned to {owner.strip() or "Unassigned"}.')


def set_conversation_status(conversation_id: str, status: str) -> None:
    initialise();status=status.title()
    if status not in {'Open','Closed'}:raise ValueError('Conversation status must be Open or Closed.')
    c=_one('SELECT * FROM v17_conversations WHERE id=?',(conversation_id,))
    if not c:raise ValueError('Conversation not found.')
    with m.connect() as con:con.execute('UPDATE v17_conversations SET status=?,updated_at=CURRENT_TIMESTAMP WHERE id=?',(status,conversation_id))
    _v18_log('conversation',conversation_id,'conversation.status',f'Conversation {status.lower()}.')


def create_conversation_task(conversation_id: str, title: str='Reply to customer') -> str:
    initialise();c=_one('SELECT * FROM v17_conversations WHERE id=?',(conversation_id,))
    if not c:raise ValueError('Conversation not found.')
    if not c.get('contact_id'):raise ValueError('Match this conversation to a CRM contact before creating a follow-up task.')
    if not m.table_exists('m4_tasks'):raise ValueError('Task storage is unavailable.')
    tid=m.uid('TASK');due=dt.date.today().isoformat()
    with m.connect() as con:con.execute("INSERT INTO m4_tasks(id,title,contact_id,due_date,status) VALUES(?,?,?,?,?)",(tid,(title.strip() or 'Reply to customer')[:300],c['contact_id'],due,'Open'))
    _v18_log('conversation',conversation_id,'conversation.task','Follow-up task created.',{'task_id':tid})
    return tid


def send_conversation_email(conversation_id: str, subject: str, body: str, confirm: str='') -> dict:
    """Send a real one-to-one email using an authenticated mailbox when possible.

    This is intentionally Email-only. WhatsApp free-form replies have separate 24-hour
    session rules; V18 does not bypass them with a misleading generic Send button.
    """
    initialise()
    if confirm!='SEND':raise ValueError('Type SEND to confirm a real customer email.')
    c=_one('SELECT * FROM v17_conversations WHERE id=?',(conversation_id,))
    if not c:raise ValueError('Conversation not found.')
    if str(c.get('channel') or '').lower()!='email':raise ValueError('Direct reply is currently supported only for Email conversations. Use the connected channel tools for other channels.')
    contact=_one('SELECT * FROM contacts WHERE contact_id=?',(c.get('contact_id') or '',))
    to_email=str(contact.get('email') or '').strip() if contact else ''
    if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',to_email):raise ValueError('This contact does not have a valid email address.')
    if not subject.strip() or not body.strip():raise ValueError('Subject and message are required.')
    import legacy
    import integration_v14 as v14
    import integration_layer as il
    provider='';provider_id=''
    mailbox=v14.resolve_channel_connection('Business Email')
    selected_mailbox=mailbox.get('connection')
    if mailbox.get('ambiguous'):
        raise ValueError('More than one Microsoft mailbox can send mail. Choose the default Business Email account in Business Connections first.')
    if selected_mailbox and 'mail_send' in (selected_mailbox.get('config',{}).get('services') or []):
        out=v14.microsoft_send_mail(selected_mailbox['id'],to_email,subject.strip(),body.strip());provider='Microsoft 365';provider_id=str(out.get('id') or '') if isinstance(out,dict) else ''
    else:
        ready=v14.channel_readiness('Email');conn=ready.get('connection')
        if ready.get('status')!='Connected' or not conn:raise ValueError('Connect and validate an email provider before replying from the unified inbox.')
        from_email=str(m.settings().get('business_email') or '').strip()
        if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',from_email):raise ValueError('Set your verified business sender email in Settings before replying.')
        text=body.strip();html='<p>'+text.replace('&','&amp;').replace('<','&lt;').replace('>','&gt;').replace('\n','<br>')+'</p>'
        out=il.resend_send_email(conn['id'],from_email,to_email,subject.strip(),html,text,'inbox-'+conversation_id+'-'+hashlib.sha256((subject+body).encode()).hexdigest()[:32])
        provider='Resend';provider_id=str(out.get('id') or '') if isinstance(out,dict) else ''
    iid=m.uid('INT')
    if m.table_exists('interactions'):
        with m.connect() as con:con.execute('INSERT INTO interactions(interaction_id,contact_id,channel,interaction_type,direction,subject_or_summary,occurred_at,metadata_json) VALUES(?,?,?,?,?,?,CURRENT_TIMESTAMP,?)',(iid,c['contact_id'],'Email','Sent','Outbound',subject.strip()[:500],_json({'provider':provider,'provider_id':provider_id,'conversation_id':conversation_id,'body':body[:5000]})))
    with m.connect() as con:
        con.execute('INSERT INTO v17_messages(id,conversation_id,source_type,source_id,direction,body,delivery_status,occurred_at,metadata_json) VALUES(?,?,?,?,?,?,?,?,?)',(uid('MSG18'),conversation_id,'operations_email',iid,'Outbound',body[:10000],'Submitted',dt.datetime.now(dt.timezone.utc).replace(microsecond=0).strftime('%Y-%m-%d %H:%M:%S'),_json({'subject':subject,'provider':provider,'provider_id':provider_id})))
        con.execute('UPDATE v17_conversations SET last_message_at=CURRENT_TIMESTAMP,updated_at=CURRENT_TIMESTAMP WHERE id=?',(conversation_id,))
    _v18_log('conversation',conversation_id,'conversation.email_sent',f'Email submitted via {provider}.',{'provider_id':provider_id,'to':to_email})
    return {'submitted':True,'provider':provider,'provider_id':provider_id}


def _legacy_l1537_social_post_action(post_id: str, action: str) -> None:
    initialise();p=_one('SELECT * FROM v17_social_posts WHERE id=?',(post_id,))
    if not p:raise ValueError('Social post not found.')
    if action=='cancel':
        if p.get('status')=='Published':raise ValueError('A provider-confirmed published post cannot be cancelled from the scheduler.')
        with m.connect() as con:con.execute("UPDATE v17_social_posts SET status='Cancelled',updated_at=CURRENT_TIMESTAMP WHERE id=?",(post_id,))
    elif action in {'retry','publish_now'}:
        if p.get('status')=='Published':return
        with m.connect() as con:con.execute("UPDATE v17_social_posts SET status='Scheduled',scheduled_at=CURRENT_TIMESTAMP,last_error='',updated_at=CURRENT_TIMESTAMP WHERE id=?",(post_id,))
        process_due_social_posts(1)
    else:raise ValueError('Choose retry, publish_now or cancel.')
    _v18_log('social_post',post_id,'social.'+action,f'Social post action: {action}.')


def _legacy_l1551_process_due_social_posts(limit: int=20) -> dict:
    initialise();rows=m.rows("SELECT * FROM v17_social_posts WHERE status IN ('Scheduled','Retry') AND scheduled_at<=CURRENT_TIMESTAMP ORDER BY scheduled_at LIMIT ?",(limit,));published=failed=0
    if not rows:return {'published':0,'failed':0,'checked':0}
    import integration_layer as il
    for post in rows:
        cid=post.get('connection_id') or ''
        if not cid:
            with m.connect() as con:con.execute("UPDATE v17_social_posts SET status='Needs setup',last_error='No default Meta social connection is configured.',updated_at=CURRENT_TIMESTAMP WHERE id=?",(post['id'],));failed+=1;continue
        try:
            if post['channel']=='Instagram':out=il.publish_instagram_image(cid,post['asset_url'],post.get('caption') or '')
            else:out=il.publish_facebook_page_image(cid,post['asset_url'],post.get('caption') or '')
            provider=str(out.get('id') or out.get('post_id') or out.get('creation_id') or '')
            with m.connect() as con:
                con.execute("UPDATE v17_social_posts SET status='Published',provider_post_id=?,last_error='',attempts=attempts+1,updated_at=CURRENT_TIMESTAMP WHERE id=?",(provider,post['id']))
                if post.get('campaign_id') and m.table_exists('v10_campaign_channels'):
                    # Organic execution evidence should advance the campaign process.
                    con.execute("UPDATE v10_campaign_channels SET launch_status='Published',external_campaign_id=CASE WHEN coalesce(external_campaign_id,'')='' THEN ? ELSE external_campaign_id END,updated_at=CURRENT_TIMESTAMP WHERE campaign_id=? AND channel IN (?, 'Instagram/Facebook')",(provider,post['campaign_id'],post['channel']))
            published+=1;_v18_log('social_post',post['id'],'social.published','Provider confirmed social publication.',{'provider_post_id':provider})
        except Exception as exc:
            with m.connect() as con:con.execute("UPDATE v17_social_posts SET status=CASE WHEN attempts>=2 THEN 'Needs attention' ELSE 'Retry' END,last_error=?,attempts=attempts+1,updated_at=CURRENT_TIMESTAMP WHERE id=?",(str(exc)[:1200],post['id']));failed+=1
    return {'published':published,'failed':failed,'checked':len(rows)}


def _legacy_l1574_publishable_campaign_assets(limit: int=200) -> list[dict]:
    """List assets that can resolve to a public HTTPS URL for social publishing."""
    initialise();out=[]
    try:import media_store
    except Exception:return []
    candidates=[]
    if m.table_exists('v8_creative_campaign_assets'):
        candidates += [dict(x,source='Campaign creative') for x in m.rows('SELECT id,campaign_id,product_id,placement_key,relative_path FROM v8_creative_campaign_assets ORDER BY created_at DESC LIMIT ?',(limit,))]
    if m.table_exists('v7_creative_assets'):
        candidates += [dict(x,campaign_id='',placement_key=x.get('asset_kind') or '',source='Product creative') for x in m.rows('SELECT id,product_id,asset_kind,relative_path FROM v7_creative_assets ORDER BY created_at DESC LIMIT ?',(limit,))]
    seen=set()
    for x in candidates:
        rel=str(x.get('relative_path') or '')
        if not rel or rel in seen:continue
        seen.add(rel)
        try:url=media_store.public_url(rel,upload_if_needed=False)
        except Exception:url=''
        if url.startswith('https://'):
            out.append({'id':x.get('id'),'campaign_id':x.get('campaign_id') or '','product_id':x.get('product_id') or '','label':str(x.get('placement_key') or x.get('source') or x.get('id')),'relative_path':rel,'url':url})
        if len(out)>=limit:break
    return out

# V18 refinements: process exactly the requested social post and keep GET asset
# discovery read-only. Cloud upload happens only after an explicit schedule action.
def _publish_social_post(post: dict) -> bool:
    import integration_layer as il
    cid=post.get('connection_id') or ''
    if not cid:
        with m.connect() as con:con.execute("UPDATE v17_social_posts SET status='Needs setup',last_error='No default Meta social connection is configured.',updated_at=CURRENT_TIMESTAMP WHERE id=?",(post['id'],))
        return False
    try:
        if post['channel']=='Instagram':out=il.publish_instagram_image(cid,post['asset_url'],post.get('caption') or '')
        else:out=il.publish_facebook_page_image(cid,post['asset_url'],post.get('caption') or '')
        provider=str(out.get('id') or out.get('post_id') or out.get('creation_id') or '')
        with m.connect() as con:
            con.execute("UPDATE v17_social_posts SET status='Published',provider_post_id=?,last_error='',attempts=attempts+1,updated_at=CURRENT_TIMESTAMP WHERE id=?",(provider,post['id']))
            if post.get('campaign_id') and m.table_exists('v10_campaign_channels'):
                con.execute("UPDATE v10_campaign_channels SET launch_status='Published',external_campaign_id=CASE WHEN coalesce(external_campaign_id,'')='' THEN ? ELSE external_campaign_id END,updated_at=CURRENT_TIMESTAMP WHERE campaign_id=? AND channel IN (?, 'Instagram/Facebook')",(provider,post['campaign_id'],post['channel']))
        _v18_log('social_post',post['id'],'social.published','Provider confirmed social publication.',{'provider_post_id':provider})
        return True
    except Exception as exc:
        with m.connect() as con:con.execute("UPDATE v17_social_posts SET status=CASE WHEN attempts>=2 THEN 'Needs attention' ELSE 'Retry' END,last_error=?,attempts=attempts+1,updated_at=CURRENT_TIMESTAMP WHERE id=?",(str(exc)[:1200],post['id']))
        return False


def social_post_action(post_id: str, action: str) -> None:
    initialise();p=_one('SELECT * FROM v17_social_posts WHERE id=?',(post_id,))
    if not p:raise ValueError('Social post not found.')
    if action=='cancel':
        if p.get('status')=='Published':raise ValueError('A provider-confirmed published post cannot be cancelled from the scheduler.')
        with m.connect() as con:con.execute("UPDATE v17_social_posts SET status='Cancelled',updated_at=CURRENT_TIMESTAMP WHERE id=?",(post_id,))
    elif action in {'retry','publish_now'}:
        if p.get('status')=='Published':return
        with m.connect() as con:con.execute("UPDATE v17_social_posts SET status='Scheduled',scheduled_at=CURRENT_TIMESTAMP,last_error='',updated_at=CURRENT_TIMESTAMP WHERE id=?",(post_id,))
        p=_one('SELECT * FROM v17_social_posts WHERE id=?',(post_id,));_publish_social_post(p)
    else:raise ValueError('Choose retry, publish_now or cancel.')
    _v18_log('social_post',post_id,'social.'+action,f'Social post action: {action}.')


def process_due_social_posts(limit: int=20) -> dict:
    initialise();rows=m.rows("SELECT * FROM v17_social_posts WHERE status IN ('Scheduled','Retry') AND scheduled_at<=CURRENT_TIMESTAMP ORDER BY scheduled_at LIMIT ?",(limit,));published=failed=0
    for post in rows:
        if _publish_social_post(post):published+=1
        else:failed+=1
    return {'published':published,'failed':failed,'checked':len(rows)}


def publishable_campaign_assets(limit: int=200) -> list[dict]:
    """List approved/recent creative assets without uploading them as a GET side effect."""
    initialise();out=[];candidates=[]
    if m.table_exists('v8_creative_campaign_assets'):
        candidates += [dict(x,source='Campaign creative') for x in m.rows('SELECT id,campaign_id,product_id,placement_key,relative_path,status FROM v8_creative_campaign_assets ORDER BY created_at DESC LIMIT ?',(limit,))]
    if m.table_exists('v7_creative_assets'):
        candidates += [dict(x,campaign_id='',placement_key=x.get('asset_kind') or '',source='Product creative') for x in m.rows('SELECT id,product_id,asset_kind,relative_path,status FROM v7_creative_assets ORDER BY created_at DESC LIMIT ?',(limit,))]
    seen=set()
    for x in candidates:
        rel=str(x.get('relative_path') or '')
        if not rel or rel in seen:continue
        seen.add(rel)
        status=str(x.get('status') or '')
        if status and status.lower() in {'rejected','failed'}:continue
        out.append({'id':x.get('id'),'campaign_id':x.get('campaign_id') or '','product_id':x.get('product_id') or '','label':str(x.get('placement_key') or x.get('source') or x.get('id')),'relative_path':rel,'status':status})
        if len(out)>=limit:break
    return out


def resolve_campaign_asset_url(asset_id: str) -> str:
    initialise();asset=next((x for x in publishable_campaign_assets(500) if str(x.get('id'))==str(asset_id)),None)
    if not asset:raise ValueError('Choose a creative asset that still exists in the CRM.')
    import media_store
    url=media_store.public_url(asset['relative_path'],upload_if_needed=True)
    if not url.startswith('https://'):raise ValueError('This CRM asset is not publicly publishable yet. Configure public HTTPS/cloud media or provide an external HTTPS image URL.')
    return url

# ---------------------------------------------------------------------------
# V37 business-acceptance hardening: line-level partial fulfilment.
# ---------------------------------------------------------------------------
import v35_truth as truth
V37_SCHEMA = r'''
CREATE TABLE IF NOT EXISTS v37_shipments(
 id TEXT PRIMARY KEY,
 fulfilment_id TEXT NOT NULL,
 order_id TEXT NOT NULL,
 carrier TEXT NOT NULL,
 tracking_number TEXT NOT NULL,
 tracking_url TEXT DEFAULT '',
 status TEXT NOT NULL DEFAULT 'Shipped',
 idempotency_key TEXT DEFAULT '',
 shipped_at TEXT DEFAULT CURRENT_TIMESTAMP,
 delivered_at TEXT,
 created_at TEXT DEFAULT CURRENT_TIMESTAMP,
 updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
 UNIQUE(idempotency_key)
);
CREATE INDEX IF NOT EXISTS v37_shipments_order ON v37_shipments(order_id,created_at);
CREATE TABLE IF NOT EXISTS v37_shipment_items(
 shipment_id TEXT NOT NULL,
 order_item_id TEXT NOT NULL,
 product_id TEXT NOT NULL,
 location_id TEXT NOT NULL,
 quantity INTEGER NOT NULL,
 created_at TEXT DEFAULT CURRENT_TIMESTAMP,
 PRIMARY KEY(shipment_id,order_item_id,location_id)
);
CREATE INDEX IF NOT EXISTS v37_shipment_items_order_item ON v37_shipment_items(order_item_id);
'''

_v36_initialise_for_v37 = _legacy_l1048_initialise

def initialise() -> None:
    _v36_initialise_for_v37()
    with m.connect() as con:
        con.executescript(V37_SCHEMA)


def shipment_rows(order_id: str) -> list[dict]:
    initialise()
    rows=m.rows('''SELECT s.*,coalesce(sum(si.quantity),0) item_quantity
                   FROM v37_shipments s LEFT JOIN v37_shipment_items si ON si.shipment_id=s.id
                   WHERE s.order_id=? GROUP BY s.id ORDER BY s.created_at''',(order_id,))
    return rows


def fulfilment_line_progress(order_id: str) -> list[dict]:
    """Ordered, shipped and remaining quantity for every immutable order line."""
    initialise()
    rows=m.rows('''SELECT oi.order_item_id,oi.product_id,oi.quantity ordered_quantity,oi.unit_price,
                          coalesce(p.public_product_name,p.product_code,p.internal_sku,oi.product_id) product_name
                   FROM order_items oi LEFT JOIN products p ON p.product_id=oi.product_id
                   WHERE oi.order_id=? ORDER BY oi.order_item_id''',(order_id,)) if m.table_exists('order_items') else []
    out=[]
    for row in rows:
        shipped=int((_one('''SELECT coalesce(sum(si.quantity),0) qty FROM v37_shipment_items si
                              JOIN v37_shipments s ON s.id=si.shipment_id
                              WHERE si.order_item_id=? AND s.status NOT IN ('Cancelled')''',(row['order_item_id'],)).get('qty') or 0))
        ordered=max(0,int(row.get('ordered_quantity') or 0))
        item=dict(row);item['shipped_quantity']=min(ordered,shipped);item['remaining_quantity']=max(0,ordered-shipped);out.append(item)
    return out


def _shipment_plan(order_id: str, requested: dict[str,int]) -> list[dict]:
    lines={x['order_item_id']:x for x in fulfilment_line_progress(order_id)}
    availability={}
    plan=[]
    for item_id,raw_qty in requested.items():
        qty=max(0,int(raw_qty or 0))
        if not qty:continue
        line=lines.get(item_id)
        if not line:raise ValueError('One selected order line no longer exists. Refresh before shipping.')
        if qty>int(line['remaining_quantity']):raise ValueError(f"Shipment quantity for {line['product_name']} exceeds the {line['remaining_quantity']} unit(s) still unshipped.")
        pid=line['product_id']
        if pid not in availability:
            availability[pid]={x['location_id']:int(x['active']) for x in _reservation_locations(order_id,pid)}
        need=qty
        for loc,active in sorted(availability[pid].items()):
            use=min(need,active)
            if use<=0:continue
            inv=truth.canonical_inventory(pid,loc)
            if int(inv['on_hand'])<use:raise ValueError(f'Inventory for {pid} at {loc} is below the quantity reserved for dispatch. Reconcile stock first.')
            plan.append({'order_item_id':item_id,'product_id':pid,'location_id':loc,'quantity':use})
            availability[pid][loc]-=use;need-=use
            if need<=0:break
        if need>0:raise ValueError(f"Only {qty-need} of {qty} requested unit(s) for {line['product_name']} remain reserved. Recheck inventory before shipping.")
    if not plan:raise ValueError('Choose at least one unshipped item and quantity.')
    return plan


def _legacy_l1761_create_partial_shipment(fulfilment_id: str, item_quantities: dict[str,int], carrier: str, tracking_number: str,
                            tracking_url: str='', idempotency_key: str='') -> str:
    """Create one shipment for selected order-line quantities and consume only those reservations."""
    initialise();f=_one('SELECT * FROM v17_fulfilments WHERE id=?',(fulfilment_id,))
    if not f:raise ValueError('Fulfilment not found.')
    if f.get('status')=='Delivered':raise ValueError('A delivered fulfilment cannot be shipped again.')
    if f.get('status') not in {'Packed','Partially shipped'}:raise ValueError('Mark the order packed before confirming a shipment.')
    carrier=str(carrier or '').strip();tracking_number=str(tracking_number or '').strip();tracking_url=str(tracking_url or '').strip();idempotency_key=str(idempotency_key or '').strip()
    if not carrier or not tracking_number:raise ValueError('Carrier and tracking number are required before shipping.')
    if tracking_url and not tracking_url.startswith('https://'):raise ValueError('Tracking URL must use HTTPS.')
    if idempotency_key:
        existing=_one('SELECT id FROM v37_shipments WHERE idempotency_key=?',(idempotency_key,))
        if existing:return existing['id']
    order_id=f['order_id'];plan=_shipment_plan(order_id,item_quantities);sid=uid('SHP37')
    with m.connect() as con:
        con.execute('INSERT INTO v37_shipments(id,fulfilment_id,order_id,carrier,tracking_number,tracking_url,idempotency_key) VALUES(?,?,?,?,?,?,?)',
                    (sid,fulfilment_id,order_id,carrier[:120],tracking_number[:200],tracking_url[:1000],idempotency_key[:180]))
        for p in plan:
            con.execute('UPDATE v9_inventory SET reserved=max(0,reserved-?),updated_at=CURRENT_TIMESTAMP WHERE product_id=? AND location_id=?',
                        (p['quantity'],p['product_id'],p['location_id']))
            con.execute('INSERT INTO v17_inventory_movements(id,product_id,location_id,movement_type,quantity,reference_type,reference_id,note) VALUES(?,?,?,?,?,?,?,?)',
                        (uid('MOV37'),p['product_id'],p['location_id'],'Consume reservation',p['quantity'],'order',order_id,'Reservation consumed by shipment '+sid+'.'))
            con.execute('INSERT INTO v37_shipment_items(shipment_id,order_item_id,product_id,location_id,quantity) VALUES(?,?,?,?,?)',
                        (sid,p['order_item_id'],p['product_id'],p['location_id'],p['quantity']))
    # Canonical stock movements are deliberately separate records with shipment identity.
    for p in plan:
        truth.adjust_stock_delta(p['product_id'],p['location_id'],-p['quantity'],'Dispatch','Partial/order shipment dispatched; shipment '+sid,reference_type='order',reference_id=order_id,order_item_id=p['order_item_id'])
    remaining=sum(x['remaining_quantity'] for x in fulfilment_line_progress(order_id))
    new_status='Partially shipped' if remaining else 'Shipped'
    with m.connect() as con:
        con.execute("UPDATE v17_fulfilments SET status=?,carrier=?,tracking_number=?,tracking_url=?,shipped_at=coalesce(shipped_at,CURRENT_TIMESTAMP),updated_at=CURRENT_TIMESTAMP,last_error='' WHERE id=?",
                    (new_status,carrier[:120],tracking_number[:200],tracking_url[:1000],fulfilment_id))
    _v18_log('order',order_id,'fulfilment.shipment',f'{sum(p["quantity"] for p in plan)} unit(s) shipped with {carrier}.',{'shipment_id':sid,'tracking_number':tracking_number,'remaining_units':remaining})
    _emit_event_safe('ORDER_SHIPPED','order',order_id,{'fulfilment_id':fulfilment_id,'shipment_id':sid,'carrier':carrier,'tracking_number':tracking_number,'remaining_units':remaining},dedupe_key='shipment:'+sid,title='Shipment saved but ORDER_SHIPPED automation event failed')
    return sid


def ship_all_remaining(fulfilment_id: str, carrier: str, tracking_number: str, tracking_url: str='') -> str:
    f=_one('SELECT order_id FROM v17_fulfilments WHERE id=?',(fulfilment_id,))
    if not f:raise ValueError('Fulfilment not found.')
    requested={x['order_item_id']:x['remaining_quantity'] for x in fulfilment_line_progress(f['order_id']) if x['remaining_quantity']>0}
    return create_partial_shipment(fulfilment_id,requested,carrier,tracking_number,tracking_url,'full:'+fulfilment_id+':'+tracking_number)


def _legacy_l1807_mark_shipment_delivered(shipment_id: str) -> None:
    initialise();s=_one('SELECT * FROM v37_shipments WHERE id=?',(shipment_id,))
    if not s:raise ValueError('Shipment not found.')
    if s.get('status')=='Delivered':return
    with m.connect() as con:con.execute("UPDATE v37_shipments SET status='Delivered',delivered_at=CURRENT_TIMESTAMP,updated_at=CURRENT_TIMESTAMP WHERE id=?",(shipment_id,))
    pending=int((_one("SELECT count(*) n FROM v37_shipments WHERE order_id=? AND status<>'Delivered'",(s['order_id'],)).get('n') or 0))
    remaining=sum(x['remaining_quantity'] for x in fulfilment_line_progress(s['order_id']))
    if pending==0 and remaining==0:
        with m.connect() as con:con.execute("UPDATE v17_fulfilments SET status='Delivered',delivered_at=CURRENT_TIMESTAMP,updated_at=CURRENT_TIMESTAMP WHERE id=?",(s['fulfilment_id'],))
        plan_retention_for_order(s['order_id'])
    _v18_log('order',s['order_id'],'shipment.delivered','Shipment delivery confirmed.',{'shipment_id':shipment_id,'remaining_unshipped':remaining})


# Override V36 all-or-nothing dispatch while preserving the public API.
def mark_shipped(fulfilment_id: str, carrier: str, tracking_number: str, tracking_url: str='') -> None:
    ship_all_remaining(fulfilment_id,carrier,tracking_number,tracking_url)


def mark_delivered(fulfilment_id: str) -> None:
    initialise();f=_one('SELECT * FROM v17_fulfilments WHERE id=?',(fulfilment_id,))
    if not f:raise ValueError('Fulfilment not found.')
    shipments=shipment_rows(f['order_id'])
    if shipments:
        if sum(x['remaining_quantity'] for x in fulfilment_line_progress(f['order_id']))>0:raise ValueError('Ship all remaining order quantities before confirming the whole order delivered.')
        for s in shipments:
            mark_shipment_delivered(s['id'])
        return
    # Legacy V36 shipment fallback for workspaces that shipped before V37 existed.
    if f.get('status')=='Delivered':return
    if f.get('status')!='Shipped':raise ValueError('Confirm shipment before confirming delivery.')
    with m.connect() as con:con.execute("UPDATE v17_fulfilments SET status='Delivered',delivered_at=CURRENT_TIMESTAMP,updated_at=CURRENT_TIMESTAMP,last_error='' WHERE id=?",(fulfilment_id,))
    _v18_log('order',f['order_id'],'fulfilment.delivered','Delivery confirmed.',{'fulfilment_id':fulfilment_id,'legacy':True})
    plan_retention_for_order(f['order_id'])


# Return eligibility becomes shipped-quantity aware once V37 shipment evidence exists.
def order_returnable_items(order_id: str) -> list[dict]:
    initialise()
    if not m.table_exists('order_items'):return []
    rows=m.rows('''SELECT oi.order_item_id,oi.product_id,oi.quantity,oi.unit_price,
                          coalesce(p.public_product_name,p.product_code,p.internal_sku,oi.product_id) product_name
                   FROM order_items oi LEFT JOIN products p ON p.product_id=oi.product_id
                   WHERE oi.order_id=? ORDER BY oi.order_item_id''',(order_id,))
    has_v37=bool(_one('SELECT id FROM v37_shipments WHERE order_id=? LIMIT 1',(order_id,)).get('id'))
    legacy_f=_one('SELECT status FROM v17_fulfilments WHERE order_id=?',(order_id,))
    out=[]
    for row in rows:
        claimed=int((_one('''SELECT coalesce(sum(ri.quantity),0) qty FROM v18_return_items ri JOIN v17_return_cases r ON r.id=ri.return_id
                              WHERE r.order_id=? AND ri.order_item_id=? AND r.status NOT IN ('Rejected','Cancelled')''',(order_id,row['order_item_id'])).get('qty') or 0))
        if has_v37:
            shipped=int((_one('''SELECT coalesce(sum(si.quantity),0) qty FROM v37_shipment_items si JOIN v37_shipments s ON s.id=si.shipment_id
                                  WHERE si.order_item_id=? AND s.status NOT IN ('Cancelled')''',(row['order_item_id'],)).get('qty') or 0))
        else:
            shipped=int(row.get('quantity') or 0) if str(legacy_f.get('status') or '') in {'Shipped','Delivered'} else 0
        item=dict(row);item['shipped_quantity']=shipped;item['claimed_quantity']=claimed;item['returnable_quantity']=max(0,shipped-claimed);out.append(item)
    return out

# ---------------------------------------------------------------------------
# V38 atomic transaction cutover
# ---------------------------------------------------------------------------

def _v38_sync_stock_cache_in_tx(con, product_id: str) -> None:
    """Keep the legacy products.stock_qty compatibility cache aligned atomically."""
    row=con.execute('SELECT coalesce(sum(on_hand),0) total FROM v9_inventory WHERE product_id=?',(product_id,)).fetchone()
    total=int(row[0] if row else 0)
    con.execute('UPDATE products SET stock_qty=? WHERE product_id=?',(total,product_id))


def _v38_insert_stock_movement(con, product_id: str, location_id: str, delta: int, movement_type: str,
                               reason: str, reference_type: str='', reference_id: str='', order_item_id: str='') -> None:
    # Ensure the canonical ledger exists even for legacy/imported workspaces that
    # have not yet visited a V35+ truth screen. This is safe inside the same shipment transaction.
    con.execute("""CREATE TABLE IF NOT EXISTS v35_inventory_movements(
      id TEXT PRIMARY KEY, product_id TEXT NOT NULL, location_id TEXT NOT NULL DEFAULT 'MAIN',
      movement_type TEXT NOT NULL, direction TEXT NOT NULL, quantity INTEGER NOT NULL,
      reason TEXT NOT NULL DEFAULT '', actor_user_id TEXT DEFAULT '', reference_type TEXT DEFAULT '',
      reference_id TEXT DEFAULT '', order_item_id TEXT DEFAULT '', before_on_hand INTEGER NOT NULL DEFAULT 0,
      after_on_hand INTEGER NOT NULL DEFAULT 0, created_at TEXT DEFAULT CURRENT_TIMESTAMP)""")
    row=con.execute('SELECT on_hand FROM v9_inventory WHERE product_id=? AND location_id=?',(product_id,location_id)).fetchone()
    before=int(row[0] if row else 0);after=before+int(delta)
    if after<0:raise ValueError(f'Not enough on-hand stock for {product_id} at {location_id}.')
    con.execute('UPDATE v9_inventory SET on_hand=?,updated_at=CURRENT_TIMESTAMP WHERE product_id=? AND location_id=?',(after,product_id,location_id))
    con.execute('''INSERT INTO v35_inventory_movements(id,product_id,location_id,movement_type,direction,quantity,reason,actor_user_id,reference_type,reference_id,order_item_id,before_on_hand,after_on_hand)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                (uid('MOV38'),product_id,location_id,movement_type,'In' if delta>=0 else 'Out',abs(int(delta)),reason[:1000],'',reference_type[:60],reference_id[:180],order_item_id[:180],before,after))
    _v38_sync_stock_cache_in_tx(con,product_id)


def create_partial_shipment(fulfilment_id: str, item_quantities: dict[str,int], carrier: str, tracking_number: str,
                            tracking_url: str='', idempotency_key: str='') -> str:
    """V38: persist shipment, consume reservations and decrement on-hand in one DB transaction."""
    initialise();f=_one('SELECT * FROM v17_fulfilments WHERE id=?',(fulfilment_id,))
    if not f:raise ValueError('Fulfilment not found.')
    if f.get('status')=='Delivered':raise ValueError('A delivered fulfilment cannot be shipped again.')
    if f.get('status') not in {'Packed','Partially shipped'}:raise ValueError('Mark the order packed before confirming a shipment.')
    carrier=str(carrier or '').strip();tracking_number=str(tracking_number or '').strip();tracking_url=str(tracking_url or '').strip();idempotency_key=str(idempotency_key or '').strip()
    if not carrier or not tracking_number:raise ValueError('Carrier and tracking number are required before shipping.')
    if tracking_url and not tracking_url.startswith('https://'):raise ValueError('Tracking URL must use HTTPS.')
    if idempotency_key:
        existing=_one('SELECT id FROM v37_shipments WHERE idempotency_key=?',(idempotency_key,))
        if existing:return existing['id']
    order_id=f['order_id'];plan=_shipment_plan(order_id,item_quantities);sid=uid('SHP38')
    if idempotency_key:
        effective_key=idempotency_key[:180]
    else:
        # A deterministic fallback makes browser/provider retries safe even when the caller
        # does not explicitly supply an idempotency key. Tracking + exact line quantities
        # identify the same physical dispatch attempt.
        import hashlib, json
        payload={'fulfilment_id':fulfilment_id,'carrier':carrier,'tracking_number':tracking_number,
                 'items':sorted((str(k),int(v or 0)) for k,v in item_quantities.items() if int(v or 0)>0)}
        effective_key=('auto:'+hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(',',':')).encode()).hexdigest())[:180]
    with m.connect() as con:
        con.execute('BEGIN IMMEDIATE')
        # Re-check fulfilment and line/reservation state while holding the write lock.
        live=con.execute('SELECT status FROM v17_fulfilments WHERE id=?',(fulfilment_id,)).fetchone()
        if not live or live[0] not in {'Packed','Partially shipped'}:raise ValueError('Fulfilment changed while this shipment was being prepared. Refresh and try again.')
        replay=con.execute('SELECT id FROM v37_shipments WHERE idempotency_key=?',(effective_key,)).fetchone()
        if replay:return replay[0]
        con.execute('INSERT INTO v37_shipments(id,fulfilment_id,order_id,carrier,tracking_number,tracking_url,idempotency_key) VALUES(?,?,?,?,?,?,?)',
                    (sid,fulfilment_id,order_id,carrier[:120],tracking_number[:200],tracking_url[:1000],effective_key))
        touched=set()
        for p in plan:
            # Re-check active reservation and physical stock in the same transaction.
            reserve=con.execute("SELECT coalesce(sum(CASE WHEN movement_type='Reserve' THEN quantity WHEN movement_type IN ('Release reservation','Consume reservation') THEN -quantity ELSE 0 END),0) FROM v17_inventory_movements WHERE reference_type='order' AND reference_id=? AND product_id=? AND location_id=?",
                                (order_id,p['product_id'],p['location_id'])).fetchone()[0]
            inv=con.execute('SELECT on_hand,reserved FROM v9_inventory WHERE product_id=? AND location_id=?',(p['product_id'],p['location_id'])).fetchone()
            if not inv or int(reserve)<p['quantity'] or int(inv[1])<p['quantity']:
                raise ValueError(f"Reservation for {p['product_id']} at {p['location_id']} changed before dispatch. Refresh and reconcile inventory.")
            if int(inv[0])<p['quantity']:
                raise ValueError(f"Inventory for {p['product_id']} at {p['location_id']} fell below the reserved quantity. Reconcile stock first.")
            con.execute('UPDATE v9_inventory SET reserved=reserved-?,updated_at=CURRENT_TIMESTAMP WHERE product_id=? AND location_id=?',
                        (p['quantity'],p['product_id'],p['location_id']))
            con.execute('INSERT INTO v17_inventory_movements(id,product_id,location_id,movement_type,quantity,reference_type,reference_id,note) VALUES(?,?,?,?,?,?,?,?)',
                        (uid('MOV38R'),p['product_id'],p['location_id'],'Consume reservation',p['quantity'],'order',order_id,'Reservation consumed atomically by shipment '+sid+'.'))
            _v38_insert_stock_movement(con,p['product_id'],p['location_id'],-p['quantity'],'Dispatch','Shipment dispatched atomically; shipment '+sid,'order',order_id,p['order_item_id'])
            con.execute('INSERT INTO v37_shipment_items(shipment_id,order_item_id,product_id,location_id,quantity) VALUES(?,?,?,?,?)',
                        (sid,p['order_item_id'],p['product_id'],p['location_id'],p['quantity']))
            touched.add(p['product_id'])
        # Derive remaining quantity without opening a second connection.
        rem=con.execute('''SELECT coalesce(sum(max(0,oi.quantity-coalesce(sq.shipped,0))),0)
                           FROM order_items oi LEFT JOIN (
                             SELECT si.order_item_id,sum(si.quantity) shipped FROM v37_shipment_items si
                             JOIN v37_shipments s ON s.id=si.shipment_id WHERE s.order_id=? AND s.status<>'Cancelled' GROUP BY si.order_item_id
                           ) sq ON sq.order_item_id=oi.order_item_id WHERE oi.order_id=?''',(order_id,order_id)).fetchone()[0]
        remaining=int(rem or 0);new_status='Partially shipped' if remaining else 'Shipped'
        con.execute("UPDATE v17_fulfilments SET status=?,carrier=?,tracking_number=?,tracking_url=?,shipped_at=coalesce(shipped_at,CURRENT_TIMESTAMP),updated_at=CURRENT_TIMESTAMP,last_error='' WHERE id=?",
                    (new_status,carrier[:120],tracking_number[:200],tracking_url[:1000],fulfilment_id))
    _v18_log('order',order_id,'fulfilment.shipment',f'{sum(p["quantity"] for p in plan)} unit(s) shipped with {carrier}.',{'shipment_id':sid,'tracking_number':tracking_number,'remaining_units':remaining,'atomic':True})
    _emit_event_safe('ORDER_SHIPPED','order',order_id,{'fulfilment_id':fulfilment_id,'shipment_id':sid,'carrier':carrier,'tracking_number':tracking_number,'remaining_units':remaining},dedupe_key='shipment:'+sid,title='Shipment saved but ORDER_SHIPPED automation event failed')
    return sid


def _return_value(return_id: str) -> float:
    """V38: refundable value uses the actual discounted/taxed line total, not list price."""
    items=return_items(return_id)
    if items:
        total=0.0
        for item in items:
            meta=_one('''SELECT oi.quantity ordered_quantity,oi.unit_price,lm.line_total
                         FROM order_items oi LEFT JOIN v35_order_line_meta lm ON lm.order_item_id=oi.order_item_id
                         WHERE oi.order_item_id=?''',(item['order_item_id'],))
            ordered=max(1,int((meta or {}).get('ordered_quantity') or item.get('quantity') or 1))
            line_total=(meta or {}).get('line_total')
            if line_total is None:line_total=float((meta or {}).get('unit_price') or item.get('unit_price') or 0)*ordered
            total+=float(line_total)/ordered*int(item.get('quantity') or 0)
        return round(total,2)
    r=_one('SELECT order_id FROM v17_return_cases WHERE id=?',(return_id,));o=_order_info((r or {}).get('order_id') or '')
    return round(float((o or {}).get('total') or 0),2)


def update_return(return_id: str, status: str, refund_amount: float|str=0, restock: bool=False, note: str='', external_refund_id: str='') -> None:
    """V38: completion, refund accounting and restock are transactionally consistent."""
    initialise();r=_one('SELECT * FROM v17_return_cases WHERE id=?',(return_id,))
    if not r:raise ValueError('Return case not found.')
    if status not in _RETURN_TRANSITIONS:raise ValueError('Choose a valid return status.')
    current=str(r.get('status') or 'Requested')
    if status!=current and status not in _RETURN_TRANSITIONS.get(current,set()):raise ValueError(f'Cannot move a return from {current} directly to {status}. Use the next operational stage.')
    try:amount=max(0,float(refund_amount or 0))
    except Exception:raise ValueError('Enter a valid refund amount.') from None
    max_value=_return_value(return_id)
    if amount>max_value+0.001:raise ValueError(f'Refund amount cannot exceed the returned-item value ({r.get("currency") or ""} {max_value:.2f}).')
    if status=='Completed' and r.get('requested_resolution')=='Refund' and amount>0 and not str(external_refund_id or '').strip():
        raise ValueError('Record the payment-provider or manual refund reference before marking a monetary refund completed.')
    pending=[]
    if status=='Completed' and restock:
        explicit=return_items(return_id)
        items=explicit or [dict(x,restocked_quantity=0) for x in m.rows('SELECT order_item_id,product_id,quantity,unit_price FROM order_items WHERE order_id=?',(r['order_id'],))]
        for item in items:
            qty=max(0,int(item.get('quantity') or 0)-int(item.get('restocked_quantity') or 0))
            if qty:pending.append((item,qty,_return_location(r['order_id'],item['product_id']),bool(explicit)))
    with m.connect() as con:
        con.execute('BEGIN IMMEDIATE')
        live=con.execute('SELECT status FROM v17_return_cases WHERE id=?',(return_id,)).fetchone()
        live_status=str(live[0] if live else '')
        if live_status!=current:raise ValueError('This return changed while you were reviewing it. Refresh before saving.')
        # Apply stock and accounting before marking the return complete, all in one commit.
        if status=='Completed':
            for item,qty,loc,is_explicit in pending:
                inv=con.execute('SELECT on_hand FROM v9_inventory WHERE product_id=? AND location_id=?',(item['product_id'],loc)).fetchone()
                if not inv:
                    con.execute('INSERT INTO v9_inventory(product_id,location_id,on_hand,reserved,reorder_point) VALUES(?,?,?,?,?)',(item['product_id'],loc,0,0,0))
                con.execute('INSERT INTO v17_inventory_movements(id,product_id,location_id,movement_type,quantity,reference_type,reference_id,note) VALUES(?,?,?,?,?,?,?,?)',
                            (uid('MOV38'),item['product_id'],loc,'Return restock',qty,'return',return_id,'Returned quantity posted atomically to canonical inventory.'))
                _v38_insert_stock_movement(con,item['product_id'],loc,qty,'Customer return','Completed return restock', 'return',return_id,item.get('order_item_id') or '')
                if is_explicit:
                    con.execute('UPDATE v18_return_items SET restocked_quantity=restocked_quantity+? WHERE return_id=? AND order_item_id=?',(qty,return_id,item['order_item_id']))
            if amount>0:
                aid=uid('ACC38');payload=_json({'return_id':return_id,'note':note})
                con.execute('''INSERT INTO v18_accounting_entries(id,order_id,source_type,source_id,entry_type,amount,currency,status,external_id,payload_json)
                               VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(source_type,source_id,entry_type) DO UPDATE SET amount=excluded.amount,currency=excluded.currency,status='Prepared',external_id=excluded.external_id,payload_json=excluded.payload_json,updated_at=CURRENT_TIMESTAMP''',
                            (aid,r['order_id'],'return',return_id,'Refund',-abs(amount),r.get('currency') or '','Prepared',str(external_refund_id or '')[:200],payload))
        con.execute("UPDATE v17_return_cases SET status=?,refund_amount=?,restock=?,note=?,external_refund_id=?,received_at=CASE WHEN ?='Received' AND received_at IS NULL THEN CURRENT_TIMESTAMP ELSE received_at END,completed_at=CASE WHEN ?='Completed' AND completed_at IS NULL THEN CURRENT_TIMESTAMP ELSE completed_at END,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (status,amount,1 if restock else 0,note[:2000],str(external_refund_id or '')[:200],status,status,return_id))
        if status=='Completed' and amount>0:
            total=float(con.execute("SELECT coalesce(sum(refund_amount),0) FROM v17_return_cases WHERE order_id=? AND status='Completed'",(r['order_id'],)).fetchone()[0] or 0)
            con.execute('''INSERT INTO v17_accounting_handoffs(id,order_id,handoff_type,amount,currency,status,external_id,payload_json)
                           VALUES(?,?,?,?,?,'Prepared',?,?) ON CONFLICT(order_id,handoff_type) DO UPDATE SET amount=excluded.amount,currency=excluded.currency,status='Prepared',external_id=excluded.external_id,payload_json=excluded.payload_json,updated_at=CURRENT_TIMESTAMP''',
                        (uid('ACC38'),r['order_id'],'Refund',-abs(total),r.get('currency') or '',str(external_refund_id or '')[:200],_json({'latest_return_id':return_id,'aggregate':True})))
            order_total=float(con.execute('SELECT coalesce(total,0) FROM orders WHERE order_id=?',(r['order_id'],)).fetchone()[0] or 0)
            if order_total>0 and total>=order_total-0.001:
                con.execute("UPDATE orders SET order_status='Refunded' WHERE order_id=?",(r['order_id'],))
    _v18_log('return',return_id,'return.status',f'{current} → {status}.',{'refund_amount':amount,'restock':bool(restock),'external_refund_id':external_refund_id,'atomic':True})
    if status=='Completed':
        _emit_event_safe('ORDER_REFUNDED','order',r['order_id'],{'return_id':return_id,'refund_amount':amount,'external_refund_id':external_refund_id},dedupe_key='refund:'+return_id,title='Refund saved but ORDER_REFUNDED automation event failed')


def mark_shipment_delivered(shipment_id: str) -> None:
    """V38: delivery of the final shipment closes both fulfilment and order state."""
    initialise();s=_one('SELECT * FROM v37_shipments WHERE id=?',(shipment_id,))
    if not s:raise ValueError('Shipment not found.')
    if s.get('status')!='Delivered':
        with m.connect() as con:con.execute("UPDATE v37_shipments SET status='Delivered',delivered_at=coalesce(delivered_at,CURRENT_TIMESTAMP),updated_at=CURRENT_TIMESTAMP WHERE id=?",(shipment_id,))
    pending=int((_one("SELECT count(*) n FROM v37_shipments WHERE order_id=? AND status<>'Delivered'",(s['order_id'],)).get('n') or 0))
    remaining=sum(x['remaining_quantity'] for x in fulfilment_line_progress(s['order_id']))
    if pending==0 and remaining==0:
        with m.connect() as con:
            con.execute("UPDATE v17_fulfilments SET status='Delivered',delivered_at=coalesce(delivered_at,CURRENT_TIMESTAMP),updated_at=CURRENT_TIMESTAMP WHERE id=?",(s['fulfilment_id'],))
            con.execute("UPDATE orders SET order_status='Fulfilled' WHERE order_id=? AND order_status='Paid'",(s['order_id'],))
        plan_retention_for_order(s['order_id'])
    _v18_log('order',s['order_id'],'shipment.delivered','Shipment delivery confirmed.',{'shipment_id':shipment_id,'remaining_unshipped':remaining,'order_closed':pending==0 and remaining==0})


def reserve_order_inventory_in_tx(con, order_id: str, location_id: str='') -> dict:
    """V39 reservation reconciliation inside the caller transaction.

    This is the canonical helper used when a Paid order is created/edited so the
    order header, lines, fulfilment row and stock reservations either all commit
    together or all roll back together.
    """
    newly_reserved=0;released=0;shortages=[]
    items=con.execute('SELECT product_id,sum(quantity) needed FROM order_items WHERE order_id=? GROUP BY product_id',(order_id,)).fetchall() if m.table_exists('order_items') else []
    if not items:return {'reserved':0,'released':0,'shortages':[],'detail':'No order-item rows are available; inventory reservation needs item data.'}
    for item in items:
        pid=item['product_id'];needed=max(0,int(item['needed'] or 0))
        existing=con.execute("""SELECT location_id,
            coalesce(sum(CASE WHEN movement_type='Reserve' THEN quantity ELSE 0 END),0)-
            coalesce(sum(CASE WHEN movement_type IN ('Release reservation','Consume reservation') THEN quantity ELSE 0 END),0) active
            FROM v17_inventory_movements WHERE reference_type='order' AND reference_id=? AND product_id=?
            GROUP BY location_id HAVING active>0 ORDER BY location_id""",(order_id,pid)).fetchall()
        active=sum(max(0,int(x['active'] or 0)) for x in existing)
        if active>needed:
            excess=active-needed
            for row in reversed(existing):
                use=min(excess,max(0,int(row['active'] or 0)))
                if use<=0:continue
                inv=con.execute('SELECT reserved FROM v9_inventory WHERE product_id=? AND location_id=?',(pid,row['location_id'])).fetchone()
                if not inv or int(inv['reserved'] or 0)<use:raise ValueError(f'Reserved inventory for {pid} at {row["location_id"]} is inconsistent.')
                con.execute('UPDATE v9_inventory SET reserved=reserved-?,updated_at=CURRENT_TIMESTAMP WHERE product_id=? AND location_id=?',(use,pid,row['location_id']))
                con.execute('INSERT INTO v17_inventory_movements(id,product_id,location_id,movement_type,quantity,reference_type,reference_id,note) VALUES(?,?,?,?,?,?,?,?)',(uid('MOV39R'),pid,row['location_id'],'Release reservation',use,'order',order_id,'Released excess reservation after order quantity changed.'))
                released+=use;excess-=use
                if excess<=0:break
            active=needed
        remaining=max(0,needed-active)
        if remaining:
            inv_rows=con.execute('SELECT location_id,on_hand,reserved FROM v9_inventory WHERE product_id=? ORDER BY (on_hand-reserved) DESC,location_id',(pid,)).fetchall()
            if location_id:
                inv_rows=sorted(inv_rows,key=lambda r:(0 if r['location_id']==location_id else 1,-(int(r['on_hand'] or 0)-int(r['reserved'] or 0)),r['location_id']))
            available_total=sum(max(0,int(r['on_hand'] or 0)-int(r['reserved'] or 0)) for r in inv_rows)
            if available_total<remaining:
                shortages.append({'product_id':pid,'needed':remaining,'available':available_total})
            else:
                for inv in inv_rows:
                    available=max(0,int(inv['on_hand'] or 0)-int(inv['reserved'] or 0));use=min(remaining,available)
                    if use<=0:continue
                    con.execute('UPDATE v9_inventory SET reserved=reserved+?,updated_at=CURRENT_TIMESTAMP WHERE product_id=? AND location_id=?',(use,pid,inv['location_id']))
                    con.execute('INSERT INTO v17_inventory_movements(id,product_id,location_id,movement_type,quantity,reference_type,reference_id,note) VALUES(?,?,?,?,?,?,?,?)',(uid('MOV39R'),pid,inv['location_id'],'Reserve',use,'order',order_id,'Canonical reservation.'))
                    newly_reserved+=use;remaining-=use
                    if remaining<=0:break
    con.execute('UPDATE v17_fulfilments SET inventory_status=?,updated_at=CURRENT_TIMESTAMP WHERE order_id=?',('Shortage' if shortages else 'Reserved',order_id))
    return {'reserved':newly_reserved,'released':released,'shortages':shortages,'detail':'Inventory reservation reconciled.' if not shortages else 'Inventory shortage/review required.'}


def ensure_fulfilment_and_reserve_in_tx(con, order_id: str) -> dict:
    row=con.execute('SELECT order_id,contact_id FROM orders WHERE order_id=?',(order_id,)).fetchone()
    if not row:raise ValueError('Order not found.')
    fulfil=con.execute('SELECT id FROM v17_fulfilments WHERE order_id=?',(order_id,)).fetchone()
    if not fulfil:
        items=con.execute('SELECT count(*) n FROM order_items WHERE order_id=?',(order_id,)).fetchone()
        fid=uid('FUL39');status='Ready to pack' if int(items['n'] or 0) else 'Needs item review'
        con.execute('INSERT INTO v17_fulfilments(id,order_id,contact_id,status,inventory_status) VALUES(?,?,?,?,?)',(fid,order_id,str(row['contact_id'] or ''),status,'Pending'))
    return reserve_order_inventory_in_tx(con,order_id)


def reserve_order_inventory(order_id: str, location_id: str='') -> dict:
    """V39: atomically reconcile order reservations across real locations."""
    initialise()
    with m.connect() as con:
        con.execute('BEGIN IMMEDIATE')
        result=reserve_order_inventory_in_tx(con,order_id,location_id)
    _v18_log('order',order_id,'inventory.reservation','Inventory reservation reconciled atomically.',{'reserved':result['reserved'],'released':result['released'],'shortages':result['shortages']})
    return result

def release_order_reservations(order_id: str, location_id: str='') -> dict:
    """V38: release every active order reservation in one transaction."""
    initialise();released=0
    with m.connect() as con:
        con.execute('BEGIN IMMEDIATE')
        rows=con.execute("""SELECT product_id,location_id,
            coalesce(sum(CASE WHEN movement_type='Reserve' THEN quantity ELSE 0 END),0)-
            coalesce(sum(CASE WHEN movement_type IN ('Release reservation','Consume reservation') THEN quantity ELSE 0 END),0) active
            FROM v17_inventory_movements WHERE reference_type='order' AND reference_id=?
            GROUP BY product_id,location_id HAVING active>0""",(order_id,)).fetchall()
        for row in rows:
            qty=max(0,int(row['active'] or 0));pid=row['product_id'];loc=row['location_id']
            if qty<=0:continue
            inv=con.execute('SELECT reserved FROM v9_inventory WHERE product_id=? AND location_id=?',(pid,loc)).fetchone()
            if not inv or int(inv['reserved'] or 0)<qty:raise ValueError(f'Reserved inventory for {pid} at {loc} is inconsistent. Reconcile inventory first.')
            con.execute('UPDATE v9_inventory SET reserved=reserved-?,updated_at=CURRENT_TIMESTAMP WHERE product_id=? AND location_id=?',(qty,pid,loc))
            con.execute('INSERT INTO v17_inventory_movements(id,product_id,location_id,movement_type,quantity,reference_type,reference_id,note) VALUES(?,?,?,?,?,?,?,?)',(uid('MOV38R'),pid,loc,'Release reservation',qty,'order',order_id,'Atomic reservation release.'))
            released+=qty
    return {'released':released}
