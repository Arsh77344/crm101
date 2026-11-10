"""V4.2 CRM services. Local transactions; no outbound transports or background jobs."""
from __future__ import annotations
import datetime as dt
import hashlib
import json
import re
import secrets
import sqlite3
from decimal import Decimal, InvalidOperation
from pathlib import Path
import marketing as m
import contact_tools as ct
import db_layer
import v35_truth as truth

STAGES={
 'B2B':['New','Qualified','Showroom Sent','Quote Sent','Negotiation','Won','Lost'],
 'B2C':['New','Enquiry','Selection Confirmed','Payment Pending','Won','Lost'],
 'Unassigned':['New','Qualified','Showroom Sent','Negotiation','Won','Lost']}
LIFECYCLES=['New','Contacted','Engaged','Qualified','Customer','Repeat Customer','Inactive']
CURRENCIES=['INR','GBP','USD','EUR']
KINDS=['Review','Call','Email','WhatsApp','Meeting','Other']
PRIORITIES=['Low','Normal','High']
SCHEMA='''
CREATE TABLE IF NOT EXISTS m42_contact_meta(contact_id TEXT PRIMARY KEY, owner TEXT DEFAULT '', archived_at TEXT, updated_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS m42_properties(id TEXT PRIMARY KEY, label TEXT NOT NULL UNIQUE COLLATE NOCASE, kind TEXT NOT NULL, options_json TEXT DEFAULT '[]', created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS m42_values(contact_id TEXT NOT NULL, property_id TEXT NOT NULL, value TEXT, updated_at TEXT DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY(contact_id,property_id));
CREATE TABLE IF NOT EXISTS m42_views(id TEXT PRIMARY KEY, name TEXT NOT NULL, filters_json TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS m42_deal_meta(deal_id TEXT PRIMARY KEY, pipeline TEXT DEFAULT 'Unassigned', owner TEXT DEFAULT '', campaign_id TEXT, version INTEGER DEFAULT 1, stage_changed_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS m42_order_meta(order_id TEXT PRIMARY KEY, deal_id TEXT, campaign_id TEXT, attribution_note TEXT, version INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS v40_external_order_meta(order_id TEXT PRIMARY KEY, provider TEXT NOT NULL, connection_id TEXT DEFAULT '', external_status TEXT DEFAULT '', external_fulfilment_status TEXT DEFAULT '', sync_state TEXT DEFAULT 'Synced', unmapped_line_count INTEGER DEFAULT 0, unmapped_lines_json TEXT DEFAULT '[]', provider_refund_total REAL DEFAULT 0, provider_refund_currency TEXT DEFAULT '', updated_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS m42_changes(id TEXT PRIMARY KEY, object_type TEXT, object_id TEXT, action TEXT, before_json TEXT, after_json TEXT, related_object_type TEXT, related_object_id TEXT, event_scope TEXT DEFAULT 'business', created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE INDEX IF NOT EXISTS m42_history_lookup ON m42_changes(object_type,object_id,created_at);
CREATE TABLE IF NOT EXISTS m42_plans(id TEXT PRIMARY KEY, kind TEXT NOT NULL, payload TEXT NOT NULL, status TEXT DEFAULT 'Preview', created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS m42_rules(id TEXT PRIMARY KEY, name TEXT NOT NULL, conditions TEXT NOT NULL, action TEXT NOT NULL, config TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS m42_enrolments(rule_id TEXT NOT NULL, contact_id TEXT NOT NULL, plan_id TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY(rule_id,contact_id));
CREATE INDEX IF NOT EXISTS m42_tasks_contact ON m4_tasks(contact_id,status);
CREATE INDEX IF NOT EXISTS m42_activity_contact ON activities(contact_id,created_at);
'''

def initial_schema():
    with m.connect() as con:
        con.executescript(SCHEMA)
        for table,cols in {
          'm4_tasks':{'owner':"TEXT DEFAULT ''",'priority':"TEXT DEFAULT 'Normal'",'kind':"TEXT DEFAULT 'Review'",'opportunity_id':'TEXT','company_id':'TEXT','notes':"TEXT DEFAULT ''",'updated_at':'TEXT'},
          'm42_contact_meta':{'archived_at':'TEXT'},
          'activities':{'campaign_id':'TEXT'},
          'companies':{'status':"TEXT DEFAULT 'Active'"},
          'v40_external_order_meta':{'unmapped_lines_json':"TEXT DEFAULT '[]'",'provider_refund_total':'REAL DEFAULT 0','provider_refund_currency':"TEXT DEFAULT ''"},
          'm42_changes':{'related_object_type':'TEXT','related_object_id':'TEXT','event_scope':"TEXT DEFAULT 'business'"}
        }.items():
            existing={r['name'] for r in con.execute('PRAGMA table_info('+table+')')}
            for col,definition in cols.items():
                if col not in existing:con.execute('ALTER TABLE '+table+' ADD COLUMN '+col+' '+definition)
        con.execute("""INSERT OR IGNORE INTO m42_deal_meta(deal_id,pipeline)
          SELECT o.opportunity_id,CASE WHEN c.contact_type='B2C' THEN 'B2C' WHEN c.contact_type IN ('B2B','Both') THEN 'B2B' ELSE 'Unassigned' END
          FROM opportunities o LEFT JOIN contacts c ON c.contact_id=o.contact_id""")
        con.execute("INSERT OR IGNORE INTO m42_order_meta(order_id) SELECT order_id FROM orders")
        con.execute("INSERT OR REPLACE INTO m4_meta(key,value) VALUES('version','4.2.0')")
    # Current CRM operations depend on canonical assignment/campaign metadata.
    # Make schema initialisation self-contained for imported and legacy workspaces.
    import v35_truth as _truth
    _truth.initialise()

def text(v,limit=200):
    v=str(v or '').strip()
    if len(v)>limit:raise ValueError('This field is too long (maximum '+str(limit)+' characters).')
    return v

def required(v,label,limit=200):
    v=text(v,limit)
    if not v:raise ValueError('Enter '+label+'.')
    return v

def choice(v,choices,label):
    if v not in choices:raise ValueError('Choose a valid '+label+'.')
    return v

def date(v,optional=True):
    v=text(v,30)
    if not v and optional:return None
    try:return dt.date.fromisoformat(v).isoformat()
    except ValueError:raise ValueError('Choose a valid date.') from None

def amount(v):
    if v is None or str(v).strip()=='':return None
    try:
        n=Decimal(str(v))
        if not n.is_finite() or n<0 or n>Decimal('1000000000'):raise ValueError()
        rounded=n.quantize(Decimal('0.01'))
        if rounded!=n:raise ValueError()
        return float(rounded)
    except (InvalidOperation,ValueError):raise ValueError('Enter a non-negative amount below 1,000,000,000 with at most two decimal places.') from None

def ref(con,table,column,ident):
    if not ident:return None
    if not con.execute('SELECT 1 FROM '+table+' WHERE '+column+'=?',(ident,)).fetchone():raise ValueError('A selected record no longer exists. Refresh and select it again.')
    return ident

def contact_archived(con,cid):
    if not cid:return False
    row=con.execute('SELECT archived_at FROM m42_contact_meta WHERE contact_id=?',(cid,)).fetchone()
    return bool(row and row[0])

def history(con,typ,ident,action,before=None,after=None,related_object_type=None,related_object_id=None,event_scope='business'):
    payload=after if isinstance(after,dict) else {}
    rel_type=related_object_type; rel_id=related_object_id; scope=event_scope or 'business'
    # Canonical event identity: store one event for the object the action is about.
    # Related entities are links, never duplicate mirror events. Legacy Contact mirror
    # rows are removed by team_beta5 and contact timelines query related-object links.
    if typ=='Task' and payload.get('contact_id'):
        rel_type,rel_id='Contact',str(payload['contact_id'])
    elif typ in {'Deal','Opportunity'} and payload.get('contact_id'):
        rel_type,rel_id='Contact',str(payload['contact_id'])
    elif typ=='Order' and payload.get('contact_id'):
        rel_type,rel_id='Contact',str(payload['contact_id'])
    con.execute('''INSERT INTO m42_changes(id,object_type,object_id,action,before_json,after_json,related_object_type,related_object_id,event_scope)
                   VALUES(?,?,?,?,?,?,?,?,?)''',
                (m.uid('CHG'),typ,ident,action,json.dumps(before,ensure_ascii=False),json.dumps(after,ensure_ascii=False),rel_type,rel_id,scope))

def primary_company(con,cid):
    r=con.execute("""SELECT cp.company_id FROM contact_companies cp JOIN companies co ON co.company_id=cp.company_id
      WHERE cp.contact_id=? AND coalesce(co.status,'Active')<>'Archived'
      ORDER BY cp.is_primary DESC,cp.company_id LIMIT 1""",(cid,)).fetchone()
    return r[0] if r else None

def field_def(raw):
    label=required(raw.get('label'),'a property label',100)
    kind=choice(raw.get('kind'),['Text','Number','Date','Dropdown'],'property type')
    values=list(dict.fromkeys(x.strip() for x in str(raw.get('options','')).splitlines() if x.strip()))
    if kind=='Dropdown' and not 2<=len(values)<=40:raise ValueError('Add 2 to 40 dropdown choices, one per line.')
    if any(len(x)>100 for x in values):raise ValueError('Each dropdown choice must be under 100 characters.')
    pid=m.uid('PROP')
    with m.connect() as con:
        if con.execute('SELECT 1 FROM m42_properties WHERE label=?',(label,)).fetchone():raise ValueError('A property with that label already exists.')
        con.execute('INSERT INTO m42_properties(id,label,kind,options_json) VALUES(?,?,?,?)',(pid,label,kind,json.dumps(values if kind=='Dropdown' else [])))
        history(con,'Property',pid,'Created',None,{'label':label,'kind':kind})
    return pid

def clean_property(prop,value):
    value=text(value,2000)
    if not value:return ''
    if prop['kind']=='Dropdown':choice(value,json.loads(prop['options_json']),'property option')
    elif prop['kind']=='Date':value=date(value,False)
    elif prop['kind']=='Number':
        try:
            n=Decimal(value)
            if not n.is_finite() or abs(n)>Decimal('1e12'):raise ValueError()
            value=str(n.normalize())
        except (ValueError,InvalidOperation):raise ValueError('Enter a finite number for '+prop['label']+'.') from None
    return value

def save_properties(cid,raw):
    with m.connect() as con:
        ref(con,'contacts','contact_id',cid)
        old={r['property_id']:r['value'] for r in con.execute('SELECT * FROM m42_values WHERE contact_id=?',(cid,))}
        vals={p['id']:clean_property(dict(p),raw.get(p['id'],'')) for p in con.execute('SELECT * FROM m42_properties')}
        for pid,v in vals.items():con.execute('INSERT INTO m42_values(contact_id,property_id,value) VALUES(?,?,?) ON CONFLICT(contact_id,property_id) DO UPDATE SET value=excluded.value,updated_at=CURRENT_TIMESTAMP',(cid,pid,v))
        history(con,'Contact',cid,'Custom properties updated',old,vals)

def set_owner(cid,owner_user_id='',owner_label=''):
    """Assign a contact to a real active user; keep a legacy label only for unresolved history."""
    uidv=truth.resolve_user(owner_user_id) if owner_user_id else ''
    owner=truth.user_label(uidv,'') if uidv else text(owner_label,100)
    with m.connect() as con:
        ref(con,'contacts','contact_id',cid)
        old=con.execute('SELECT owner,owner_user_id FROM m42_contact_meta WHERE contact_id=?',(cid,)).fetchone()
        con.execute("""INSERT INTO m42_contact_meta(contact_id,owner,owner_user_id) VALUES(?,?,?)
                       ON CONFLICT(contact_id) DO UPDATE SET owner=excluded.owner,owner_user_id=excluded.owner_user_id,updated_at=CURRENT_TIMESTAMP""",(cid,owner,uidv))
        history(con,'Contact',cid,'Owner updated',{'owner':old['owner'] if old else '','owner_user_id':old['owner_user_id'] if old else ''},{'owner':owner,'owner_user_id':uidv})

def filter_contacts(raw):
    keys=['search','type','source','tag','country','owner','stage','channel','scope','sort','property','property_value','record_state','task']
    f={k:text(raw.get(k),200) for k in keys}
    f['channel']=f['channel'] or 'Email'
    f['record_state']=f['record_state'] or 'active'
    choice(f['record_state'],['active','archived','all'],'record state')
    choice(f['channel'],['Email','WhatsApp','Social DM','SMS','Phone'],'channel')
    if f['type']:choice(f['type'],['B2B','B2C','Both','Unknown'],'journey')
    if f['stage']:choice(f['stage'],LIFECYCLES,'customer stage')
    choice(f['scope'],['','Eligible','Unknown','Blocked'],'permission filter')
    choice(f['task'],['','missing','open'],'task filter')
    priority_expr="coalesce((SELECT sp.priority_score FROM v35_sales_priority sp WHERE sp.contact_id=c.contact_id),c.lead_score,0) DESC,c.full_name,c.contact_id" if m.table_exists('v35_sales_priority') else 'c.lead_score DESC,c.full_name,c.contact_id'
    sort={'name':"coalesce(nullif(trim(c.full_name),''),nullif(trim(c.username),''),'') COLLATE NOCASE,c.contact_id",'name_desc':"coalesce(nullif(trim(c.full_name),''),nullif(trim(c.username),''),'') COLLATE NOCASE DESC,c.contact_id",'recent':'c.created_at DESC,c.contact_id','oldest':'c.created_at,c.contact_id','priority':priority_expr}
    f['sort']=f['sort'] or 'name';choice(f['sort'],sort,'sort order')
    where=[];params=[]
    if f['record_state']=='active':where.append('cm.archived_at IS NULL')
    elif f['record_state']=='archived':where.append('cm.archived_at IS NOT NULL')
    if f['search']:
        where.append('(c.full_name LIKE ? OR c.username LIKE ? OR c.email LIKE ? OR c.phone_number LIKE ? OR c.business_category LIKE ? OR p.company_name LIKE ?)')
        params+=['%'+f['search']+'%']*6
    if f['type'] in {'B2B','B2C'}:where.append("c.contact_type IN (?,'Both')");params.append(f['type'])
    elif f['type']:where.append('c.contact_type=?');params.append(f['type'])
    for key,col in [('country','c.country'),('stage','c.lifecycle_stage')]:
        if f[key]:where.append(col+'=?');params.append(f[key])
    if f['owner']=='__unassigned':where.append("coalesce(cm.owner,'')=''")
    elif f['owner']:where.append('cm.owner=?');params.append(f['owner'])
    if f['task']=='missing':where.append("NOT EXISTS(SELECT 1 FROM m4_tasks tx WHERE tx.contact_id=c.contact_id AND tx.status='Open')")
    elif f['task']=='open':where.append("EXISTS(SELECT 1 FROM m4_tasks tx WHERE tx.contact_id=c.contact_id AND tx.status='Open')")
    if f['tag']:where.append('EXISTS(SELECT 1 FROM m41_tags t WHERE t.contact_id=c.contact_id AND t.tag=?)');params.append(f['tag'])
    if f['source']:where.append('(c.source_name=? OR EXISTS(SELECT 1 FROM m41_sources s WHERE s.contact_id=c.contact_id AND s.source=?))');params.extend([f['source']]*2)
    if f['property']:
        if not m.one('SELECT 1 FROM m42_properties WHERE id=?',(f['property'],)):raise ValueError('Select an existing custom property.')
        where.append('EXISTS(SELECT 1 FROM m42_values pv WHERE pv.contact_id=c.contact_id AND pv.property_id=? AND pv.value=?)');params.extend([f['property'],f['property_value']])
    sql="""SELECT c.*,coalesce(cm.owner,'') owner,p.company_name,
       (SELECT min(due_date) FROM m4_tasks t WHERE t.contact_id=c.contact_id AND t.status='Open') task_due
       FROM contacts c LEFT JOIN m42_contact_meta cm USING(contact_id) LEFT JOIN m41_profile p USING(contact_id)"""
    if where:sql+=' WHERE '+' AND '.join(where)
    records=m.rows(sql+' ORDER BY '+(('c.contact_id' if f['sort'] in {'name','name_desc'} else sort[f['sort']])),params)
    pm=m.permissions_map();blocked=m.blocked_endpoints(pm,f['channel']);result=[]
    for c in records:
        ok,reason=m.eligibility(c,f['channel'],pm)
        if m.endpoint(c,f['channel']) in blocked:ok,reason=False,'Opted out / suppressed (including matching address)'
        c['eligible']=ok;c['permission_reason']=reason
        if f['scope']=='Eligible' and not ok:continue
        if f['scope']=='Unknown' and reason!='Permission unknown':continue
        if f['scope']=='Blocked' and (ok or reason=='Permission unknown'):continue
        result.append(c)
    if f['sort'] in {'name','name_desc'}:
        def name_key(c):
            raw=(c.get('full_name') or c.get('username') or '').strip()
            clean=re.sub(r'^[^A-Za-z0-9]+','',raw).strip()
            if not clean:clean=raw
            first=clean[:1]
            # A-Z means alphabetic names first and ignores decorative leading quotes/#/@.
            bucket=0 if first.isalpha() else 1
            return (bucket,clean.casefold(),str(c.get('contact_id') or ''))
        result.sort(key=name_key,reverse=f['sort']=='name_desc')
    return f,result

def save_view(raw):
    name=required(raw.get('name'),'a view name',80);f,_=filter_contacts(raw)
    ident=m.uid('VIEW')
    with m.connect() as con:con.execute('INSERT INTO m42_views(id,name,filters_json) VALUES(?,?,?)',(ident,name,json.dumps(f)))
    return ident

def task_save(raw,tid=None,con=None):
    if con is None:
        with m.connect() as con:return task_save(raw,tid,con)
    title=required(raw.get('title'),'a task title')
    due=date(raw.get('due_date'),False)
    priority=choice(raw.get('priority') or 'Normal',PRIORITIES,'priority')
    kind=choice(raw.get('kind') or 'Review',KINDS,'task type')
    owner_user_id=truth.resolve_user(raw.get('owner_user_id')) if raw.get('owner_user_id') else ''
    owner=truth.user_label(owner_user_id,'') if owner_user_id else text(raw.get('owner'),100)
    notes=text(raw.get('notes'),2000)
    status=choice(raw.get('status') or 'Open',['Open','Done','Cancelled'],'task status')
    cid=ref(con,'contacts','contact_id',raw.get('contact_id') or None)
    if cid and contact_archived(con,cid):raise ValueError('That contact is archived. Restore it before creating or changing linked work.')
    did=ref(con,'opportunities','opportunity_id',raw.get('opportunity_id') or None)
    cam=truth.canonical_campaign_id(raw.get('campaign_id')) if raw.get('campaign_id') else None
    if did:
        deal=con.execute('SELECT contact_id FROM opportunities WHERE opportunity_id=?',(did,)).fetchone()
        if cid and deal['contact_id'] and cid!=deal['contact_id']:raise ValueError('The selected deal belongs to another contact.')
        cid=cid or deal['contact_id']
    account=primary_company(con,cid) if cid else None
    old=con.execute('SELECT * FROM m4_tasks WHERE id=?',(tid,)).fetchone() if tid else None
    if tid and not old:raise ValueError('Task not found.')
    tid=tid or m.uid('TASK')
    con.execute("""INSERT INTO m4_tasks(id,title,contact_id,campaign_id,due_date,status,owner,owner_user_id,priority,kind,opportunity_id,company_id,notes,updated_at)
      VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP) ON CONFLICT(id) DO UPDATE SET title=excluded.title,contact_id=excluded.contact_id,campaign_id=excluded.campaign_id,
      due_date=excluded.due_date,status=excluded.status,owner=excluded.owner,owner_user_id=excluded.owner_user_id,priority=excluded.priority,kind=excluded.kind,opportunity_id=excluded.opportunity_id,
      company_id=excluded.company_id,notes=excluded.notes,updated_at=CURRENT_TIMESTAMP""",
      (tid,title,cid,cam,due,status,owner,owner_user_id,priority,kind,did,account,notes))
    history(con,'Task',tid,'Task saved',dict(old) if old else None,{'title':title,'due_date':due,'status':status,'contact_id':cid,'owner':owner,'owner_user_id':owner_user_id})
    return tid

def task_status(tid,status):
    choice(status,['Open','Done','Cancelled'],'task status')
    with m.connect() as con:
        old=con.execute('SELECT * FROM m4_tasks WHERE id=?',(tid,)).fetchone()
        if not old:raise ValueError('Task not found.')
        con.execute('UPDATE m4_tasks SET status=?,updated_at=CURRENT_TIMESTAMP WHERE id=?',(status,tid))
        history(con,'Task',tid,'Task '+status,{'status':old['status']},{'status':status})

def bulk_tasks(task_ids, action: str, owner_user_id: str='') -> int:
    """Apply one safe task action atomically to the selected visible work items."""
    ids=list(dict.fromkeys(str(x or '').strip() for x in (task_ids or []) if str(x or '').strip()))
    if not ids:raise ValueError('Select at least one task.')
    if len(ids)>100:raise ValueError('Select no more than 100 tasks at a time.')
    action=choice(action,['complete','reopen','cancel','assign'],'bulk task action')
    resolved_user=''
    resolved_label=''
    if action=='assign':
        if not owner_user_id:raise ValueError('Choose an owner before assigning selected tasks.')
        resolved_user=truth.resolve_user(owner_user_id)
        resolved_label=truth.user_label(resolved_user,'')
    with m.connect() as con:
        marks=','.join('?' for _ in ids)
        rows=con.execute('SELECT * FROM m4_tasks WHERE id IN ('+marks+')',ids).fetchall()
        found={r['id']:r for r in rows}
        missing=[x for x in ids if x not in found]
        if missing:raise ValueError('One or more selected tasks no longer exist. Refresh the list and try again.')
        for tid in ids:
            old=found[tid]
            if action=='assign':
                con.execute('UPDATE m4_tasks SET owner=?,owner_user_id=?,updated_at=CURRENT_TIMESTAMP WHERE id=?',(resolved_label,resolved_user,tid))
                history(con,'Task',tid,'Task reassigned',{'owner':old['owner'],'owner_user_id':old['owner_user_id']},{'owner':resolved_label,'owner_user_id':resolved_user})
            else:
                status={'complete':'Done','reopen':'Open','cancel':'Cancelled'}[action]
                con.execute('UPDATE m4_tasks SET status=?,updated_at=CURRENT_TIMESTAMP WHERE id=?',(status,tid))
                history(con,'Task',tid,'Task '+status,{'status':old['status']},{'status':status})
    return len(ids)

def log_activity(raw):
    with m.connect() as con:
        cid=ref(con,'contacts','contact_id',required(raw.get('contact_id'),'a contact'))
        if contact_archived(con,cid):raise ValueError('That contact is archived. Restore it before logging new activity.')
        did=ref(con,'opportunities','opportunity_id',raw.get('opportunity_id'))
        cam=truth.canonical_campaign_id(raw.get('campaign_id')) if raw.get('campaign_id') else None
        if did:
            dc=con.execute('SELECT contact_id FROM opportunities WHERE opportunity_id=?',(did,)).fetchone()[0]
            if dc and dc!=cid:raise ValueError('The deal belongs to a different contact.')
        kind=choice(raw.get('activity_type') or 'Note',['Note','Email','WhatsApp','Call','Meeting','Follow-up'],'activity type')
        channel=choice(raw.get('channel') or 'Other',['Other','Email','WhatsApp','Social DM','Phone','Website','SMS'],'channel')
        direction=choice(raw.get('direction') or 'Internal',['Internal','Inbound','Outbound'],'activity direction')
        summary=required(raw.get('summary'),'what happened',4000)
        due=date(raw.get('due_date'))
        aid=m.uid('ACT');account=primary_company(con,cid)
        con.execute("""INSERT INTO activities(activity_id,contact_id,company_id,opportunity_id,campaign_id,canonical_campaign_id,activity_type,channel,direction,summary,follow_up_at)
          VALUES(?,?,?,?,?,?,?,?,?,?,?)""",(aid,cid,account,did,cam,cam,kind,channel,direction,summary,due))
        if due:task_save({'title':'Follow up: '+summary[:150],'due_date':due,'contact_id':cid,'opportunity_id':did,'campaign_id':cam,'kind':'Review'},con=con)
        history(con,'Contact',cid,'Activity logged',None,{'id':aid,'type':kind,'direction':direction,'campaign_id':cam,'manually_logged':True})
    try:truth.contact_priority(cid)
    except Exception:pass
    return aid

def deal_save(raw,did=None):
    name=required(raw.get('name'),'a deal name');pipeline=choice(raw.get('pipeline') or 'B2B',STAGES,'pipeline')
    stage=choice(raw.get('stage') or 'New',STAGES[pipeline],'stage for this pipeline')
    value=amount(raw.get('estimated_value'));currency=choice(raw.get('currency') or 'INR',CURRENCIES,'currency')
    due=date(raw.get('expected_close_date'));notes=text(raw.get('notes'),4000)
    owner_user_id=truth.resolve_user(raw.get('owner_user_id')) if raw.get('owner_user_id') else ''
    owner=truth.user_label(owner_user_id,'') if owner_user_id else text(raw.get('owner'),100)
    with m.connect() as con:
        con.execute('BEGIN IMMEDIATE')
        cid=ref(con,'contacts','contact_id',raw.get('contact_id'))
        if cid and contact_archived(con,cid):raise ValueError('That contact is archived. Restore it before creating or changing a deal.')
        cam=truth.canonical_campaign_id(raw.get('campaign_id')) if raw.get('campaign_id') else None
        sid=ref(con,'showrooms','showroom_id',raw.get('showroom_id'))
        if sid:
            sr=con.execute('SELECT contact_id,status FROM showrooms WHERE showroom_id=?',(sid,)).fetchone()
            if (sr['status'] or 'Draft') in {'Archived','Inactive'}:raise ValueError('That showroom is not active. Restore or activate it before linking it to a deal.')
            sc=sr['contact_id']
            if sc and cid!=sc:raise ValueError('Select a showroom belonging to this contact, or a generic showroom.')
        old=con.execute('SELECT o.*,d.pipeline,d.owner,d.owner_user_id,d.campaign_id,d.canonical_campaign_id,d.version FROM opportunities o JOIN m42_deal_meta d ON d.deal_id=o.opportunity_id WHERE o.opportunity_id=?',(did,)).fetchone() if did else None
        if did:
            if not old:raise ValueError('Deal not found.')
            if str(old['version'])!=str(raw.get('version')):raise ValueError('This deal changed in another tab. Refresh before saving.')
        did=did or m.uid('OPP');account=primary_company(con,cid) if cid else None
        con.execute("""INSERT INTO opportunities(opportunity_id,contact_id,company_id,name,stage,estimated_value,currency,expected_close_date,notes,showroom_id)
          VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(opportunity_id) DO UPDATE SET contact_id=excluded.contact_id,company_id=excluded.company_id,name=excluded.name,
          stage=excluded.stage,estimated_value=excluded.estimated_value,currency=excluded.currency,expected_close_date=excluded.expected_close_date,notes=excluded.notes,showroom_id=excluded.showroom_id""",
          (did,cid,account,name,stage,value,currency,due,notes,sid))
        con.execute("""INSERT INTO m42_deal_meta(deal_id,pipeline,owner,owner_user_id,campaign_id,canonical_campaign_id) VALUES(?,?,?,?,?,?) ON CONFLICT(deal_id) DO UPDATE SET
          pipeline=excluded.pipeline,owner=excluded.owner,owner_user_id=excluded.owner_user_id,campaign_id=excluded.campaign_id,canonical_campaign_id=excluded.canonical_campaign_id,version=m42_deal_meta.version+1,
          stage_changed_at=CASE WHEN ? THEN CURRENT_TIMESTAMP ELSE stage_changed_at END""",
          (did,pipeline,owner,owner_user_id,cam,cam,not old or old['stage']!=stage or old['pipeline']!=pipeline))
        after={'name':name,'stage':stage,'value':value,'currency':currency,'pipeline':pipeline,'owner':owner,'owner_user_id':owner_user_id,'contact_id':cid,'campaign_id':cam}
        history(con,'Deal',did,'Deal updated' if old else 'Deal created',dict(old) if old else None,after)
    if cid:
        try:truth.contact_priority(cid)
        except Exception:pass
    return did

def move_deal(did,stage,version):
    with m.connect() as con:
        con.execute('BEGIN IMMEDIATE')
        r=con.execute('SELECT o.*,d.pipeline,d.version FROM opportunities o JOIN m42_deal_meta d ON d.deal_id=o.opportunity_id WHERE o.opportunity_id=?',(did,)).fetchone()
        if not r:raise ValueError('Deal not found.')
        choice(stage,STAGES[r['pipeline']],'stage')
        if str(version)!=str(r['version']):raise ValueError('The deal changed in another tab. Refresh this board before moving it.')
        if r['stage']==stage:return
        con.execute('UPDATE opportunities SET stage=? WHERE opportunity_id=?',(stage,did))
        con.execute('UPDATE m42_deal_meta SET version=version+1,stage_changed_at=CURRENT_TIMESTAMP WHERE deal_id=?',(did,))
        history(con,'Deal',did,'Stage changed',{'stage':r['stage']},{'stage':stage})
    # A won deal is not a payment and never creates an order automatically.

def company_save(raw,company_id=None):
    name=required(raw.get('company_name'),'an account name')
    website=text(raw.get('website'),1000)
    if website and not re.fullmatch(r'https?://[^\s]+',website):raise ValueError('Account website must begin with http:// or https://.')
    payload={k:text(raw.get(k),4000 if k=='notes' else 200) for k in ['country','company_type','wholesale_tier','notes']}
    with m.connect() as con:
        old=con.execute('SELECT * FROM companies WHERE company_id=?',(company_id,)).fetchone() if company_id else None
        if company_id and not old:raise ValueError('Account not found.')
        if old and (old['status'] or 'Active')=='Archived':raise ValueError('Restore this account before editing it.')
        company_id=company_id or m.uid('CMP')
        con.execute('''INSERT INTO companies(company_id,company_name,website,country,company_type,wholesale_tier,notes) VALUES(?,?,?,?,?,?,?)
         ON CONFLICT(company_id) DO UPDATE SET company_name=excluded.company_name,website=excluded.website,country=excluded.country,
         company_type=excluded.company_type,wholesale_tier=excluded.wholesale_tier,notes=excluded.notes''',
         (company_id,name,website,payload['country'],payload['company_type'],payload['wholesale_tier'],payload['notes']))
        history(con,'Account',company_id,'Account saved',dict(old) if old else None,{'company_name':name,**payload})
    return company_id

def link_account(cid,account,role,primary=False):
    with m.connect() as con:
        ref(con,'contacts','contact_id',cid);ref(con,'companies','company_id',account)
        if not cid or not account:raise ValueError('Choose a contact and account.')
        state=con.execute("SELECT coalesce(status,'Active') FROM companies WHERE company_id=?",(account,)).fetchone()[0]
        if state=='Archived':raise ValueError('That account is archived. Restore it before linking new contacts.')
        role=text(role,200)
        if primary:con.execute('UPDATE contact_companies SET is_primary=0 WHERE contact_id=?',(cid,))
        con.execute('INSERT INTO contact_companies(contact_id,company_id,role_title,is_primary) VALUES(?,?,?,?) ON CONFLICT(contact_id,company_id) DO UPDATE SET role_title=excluded.role_title,is_primary=excluded.is_primary',(cid,account,role,int(primary)))
        # Explicit primary association synchronises the reusable company/role fields.
        if primary:
            name=con.execute('SELECT company_name FROM companies WHERE company_id=?',(account,)).fetchone()[0]
            con.execute('INSERT INTO m41_profile(contact_id,company_name,role_title) VALUES(?,?,?) ON CONFLICT(contact_id) DO UPDATE SET company_name=excluded.company_name,role_title=excluded.role_title',(cid,name,role))
        history(con,'Contact',cid,'Account linked',None,{'account_id':account,'role':role,'primary':primary})

def _v38_release_reservations_in_tx(con, order_id: str) -> int:
    """Release every active reservation for an order inside the caller transaction."""
    if not m.table_exists('v17_inventory_movements') or not m.table_exists('v9_inventory'):return 0
    rows=con.execute("""SELECT product_id,location_id,
        coalesce(sum(CASE WHEN movement_type='Reserve' THEN quantity ELSE 0 END),0)-
        coalesce(sum(CASE WHEN movement_type IN ('Release reservation','Consume reservation') THEN quantity ELSE 0 END),0) active
        FROM v17_inventory_movements WHERE reference_type='order' AND reference_id=?
        GROUP BY product_id,location_id HAVING active>0""",(order_id,)).fetchall()
    released=0
    for row in rows:
        pid=row['product_id'];loc=row['location_id'];qty=max(0,int(row['active'] or 0))
        if not qty:continue
        inv=con.execute('SELECT reserved FROM v9_inventory WHERE product_id=? AND location_id=?',(pid,loc)).fetchone()
        if not inv or int(inv['reserved'] or 0)<qty:
            raise ValueError(f'Reserved inventory for {pid} at {loc} is inconsistent. Reconcile inventory before cancelling this order.')
        con.execute('UPDATE v9_inventory SET reserved=reserved-?,updated_at=CURRENT_TIMESTAMP WHERE product_id=? AND location_id=?',(qty,pid,loc))
        con.execute('INSERT INTO v17_inventory_movements(id,product_id,location_id,movement_type,quantity,reference_type,reference_id,note) VALUES(?,?,?,?,?,?,?,?)',
                    (m.uid('MOV38C'),pid,loc,'Release reservation',qty,'order',order_id,'Reservation released atomically by order cancellation.'))
        released+=qty
    return released


def _v38_cancel_order(oid: str, raw: dict) -> str:
    """Cancel an existing order without rewriting its immutable commercial lines."""
    with m.connect() as con:
        con.execute('BEGIN IMMEDIATE')
        old=con.execute('SELECT o.*,x.version FROM orders o LEFT JOIN m42_order_meta x USING(order_id) WHERE order_id=?',(oid,)).fetchone()
        if not old:raise ValueError('Order not found.')
        if str(old['version'])!=str(raw.get('version')):raise ValueError('Order changed or missing. Refresh before saving.')
        prior=str(old['order_status'] or 'Draft')
        if prior=='Cancelled':return oid
        if prior in {'Fulfilled','Refunded'}:raise ValueError('A fulfilled/refunded order cannot be cancelled. Use the return/refund workflow.')
        fulfil=con.execute('SELECT status FROM v17_fulfilments WHERE order_id=?',(oid,)).fetchone() if m.table_exists('v17_fulfilments') else None
        fstatus=str(fulfil[0] if fulfil else '')
        if fstatus in {'Packed','Partially shipped','Shipped','Delivered'}:
            raise ValueError('This order has entered fulfilment and cannot be cancelled from the order editor. Use the fulfilment/return workflow.')
        released=_v38_release_reservations_in_tx(con,oid) if prior=='Paid' else 0
        con.execute("UPDATE orders SET order_status='Cancelled' WHERE order_id=?",(oid,))
        con.execute('UPDATE m42_order_meta SET version=version+1 WHERE order_id=?',(oid,))
        if m.table_exists('v17_fulfilments'):
            con.execute("UPDATE v17_fulfilments SET status='Cancelled',inventory_status='Released',updated_at=CURRENT_TIMESTAMP WHERE order_id=? AND status NOT IN ('Shipped','Delivered')",(oid,))
        history(con,'Order',oid,'Order cancelled',dict(old),{'status':'Cancelled','released_reservations':released})
    try:
        import business_os as bos;bos.emit('order.updated','order',oid,{'status':'Cancelled','contact_id':old['contact_id']},'order.cancelled:'+oid)
    except Exception:pass
    return oid


def order_save(raw,oid=None,lines=None):
    """Save a real order header and its physical transaction lines as one business transaction."""
    currency=choice(raw.get('currency') or 'INR',CURRENCIES,'currency')
    status=choice(raw.get('order_status') or 'Draft',['Draft','Pending','Paid','Fulfilled','Cancelled','Refunded'],'order status')
    typ=choice(raw.get('order_type') or 'B2C',['B2B','B2C'],'order type')
    if oid and status=='Cancelled':return _v38_cancel_order(oid,raw)
    lines=lines or []
    clean_lines=[]
    for idx,line in enumerate(lines,1):
        pid=text(line.get('product_id'),200)
        if not pid:continue
        try:qty=int(str(line.get('quantity') or '0'))
        except Exception:raise ValueError(f'Enter a whole-number quantity for order line {idx}.') from None
        if qty<=0:raise ValueError(f'Quantity on order line {idx} must be at least 1.')
        unit=amount(line.get('unit_price'));discount=amount(line.get('discount')) or 0;tax=amount(line.get('tax')) or 0
        if unit is None:raise ValueError(f'Enter a unit price for order line {idx}.')
        base=round(float(unit)*qty,2)
        if float(discount)>base:raise ValueError(f'Discount on order line {idx} cannot exceed the merchandise value.')
        line_total=round(base-float(discount)+float(tax),2)
        clean_lines.append({'product_id':pid,'quantity':qty,'unit_price':float(unit),'discount':float(discount),'tax':float(tax),'line_total':line_total})
    if status in {'Paid','Fulfilled'} and not clean_lines:
        raise ValueError('A physical-product order needs at least one product line before it can be marked paid or fulfilled.')
    if status=='Fulfilled':
        if not oid:raise ValueError('Save the order first, then complete fulfilment from the fulfilment workflow.')
        f=m.one("SELECT status FROM v17_fulfilments WHERE order_id=?",(oid,)) if m.table_exists('v17_fulfilments') else None
        if not f or f.get('status')!='Delivered':raise ValueError('Confirm packing, shipping and delivery before an order can become fulfilled.')
    total=round(sum(x['line_total'] for x in clean_lines),2) if clean_lines else amount(raw.get('total'))
    if status in {'Paid','Fulfilled'} and total is None:raise ValueError('The order total cannot be calculated without product lines.')
    if status=='Paid':
        requested={}
        for line in clean_lines:requested[line['product_id']]=requested.get(line['product_id'],0)+int(line['quantity'])
        for pid,qty in requested.items():
            available=truth.product_available(pid);already=0
            if oid and m.table_exists('v17_inventory_movements'):
                already=int((m.one("SELECT coalesce(sum(CASE WHEN movement_type='Reserve' THEN quantity WHEN movement_type IN ('Release reservation','Consume reservation') THEN -quantity ELSE 0 END),0) n FROM v17_inventory_movements WHERE reference_type='order' AND reference_id=? AND product_id=?",(oid,pid)) or {'n':0}).get('n') or 0)
            prod=m.one('SELECT status FROM products WHERE product_id=?',(pid,))
            if not prod:raise ValueError(f'Product {pid} no longer exists.')
            if str(prod.get('status') or 'Draft')!='Active':
                raise ValueError(f'Product {pid} is not Active and cannot be added to a paid order. Restore/activate it or choose another product.')
            if available+max(0,already)<qty:
                raise ValueError(f"Not enough available stock for {pid}. Available: {available}. Adjust stock or reduce the combined order quantity.")
    with m.connect() as con:
        con.execute('BEGIN IMMEDIATE')
        con.execute("CREATE TABLE IF NOT EXISTS v36_order_requests(idempotency_key TEXT PRIMARY KEY, order_id TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP)")
        request_key=text(raw.get('idempotency_key'),120)
        if not oid and request_key:
            replay=con.execute('SELECT order_id FROM v36_order_requests WHERE idempotency_key=?',(request_key,)).fetchone()
            if replay:return replay[0]
        cid=ref(con,'contacts','contact_id',raw.get('contact_id'))
        did=ref(con,'opportunities','opportunity_id',raw.get('deal_id'))
        cam=truth.canonical_campaign_id(raw.get('campaign_id')) if raw.get('campaign_id') else None
        if did:
            dr=con.execute('SELECT contact_id FROM opportunities WHERE opportunity_id=?',(did,)).fetchone()
            if cid and dr[0] and dr[0]!=cid:raise ValueError('The order and deal must refer to the same contact.')
            cid=cid or dr[0]
        old=con.execute('SELECT o.*,x.version FROM orders o LEFT JOIN m42_order_meta x USING(order_id) WHERE order_id=?',(oid,)).fetchone() if oid else None
        if oid and (not old or str(old['version'])!=str(raw.get('version'))):raise ValueError('Order changed or missing. Refresh before saving.')
        ext_ref=text(raw.get('external_order_reference'),250)
        if not oid and ext_ref:
            duplicate=con.execute('SELECT order_id FROM orders WHERE external_order_reference=? LIMIT 1',(ext_ref,)).fetchone()
            if duplicate:raise ValueError('An order with this external/reference ID already exists. Open the existing order instead of creating a duplicate.')
        if old:
            prior=str(old['order_status'] or 'Draft')
            fulfil=con.execute('SELECT status FROM v17_fulfilments WHERE order_id=?',(oid,)).fetchone() if m.table_exists('v17_fulfilments') else None
            fstatus=str(fulfil[0] if fulfil else '')
            if prior in {'Fulfilled','Refunded','Cancelled'} or fstatus in {'Packed','Partially shipped','Shipped','Delivered'}:
                raise ValueError('This order is locked because fulfilment or a terminal order state has been reached. Use the return/refund workflow for corrections.')
            allowed={'Draft':{'Draft','Pending','Paid','Cancelled'},'Pending':{'Pending','Paid','Cancelled'},'Paid':{'Paid','Cancelled'}}
            if status not in allowed.get(prior,{prior}):raise ValueError(f'Cannot move an order from {prior} directly to {status}. Use the operational workflow for the next state.')
        oid=oid or m.uid('ORD');account=primary_company(con,cid) if cid else None
        if not old and request_key:
            con.execute('INSERT INTO v36_order_requests(idempotency_key,order_id) VALUES(?,?)',(request_key,oid))
        con.execute("""INSERT INTO orders(order_id,contact_id,company_id,order_type,order_status,total,currency,external_order_reference,ordered_at)
          VALUES(?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP) ON CONFLICT(order_id) DO UPDATE SET contact_id=excluded.contact_id,company_id=excluded.company_id,
          order_type=excluded.order_type,order_status=excluded.order_status,total=excluded.total,currency=excluded.currency,external_order_reference=excluded.external_order_reference""",
          (oid,cid,account,typ,status,total,currency,ext_ref))
        con.execute("""INSERT INTO m42_order_meta(order_id,deal_id,campaign_id,canonical_campaign_id,attribution_note) VALUES(?,?,?,?,?) ON CONFLICT(order_id) DO UPDATE SET
          deal_id=excluded.deal_id,campaign_id=excluded.campaign_id,canonical_campaign_id=excluded.canonical_campaign_id,attribution_note=excluded.attribution_note,version=version+1""",
          (oid,did,cam,cam,text(raw.get('attribution_note'),1000)))
        if clean_lines:
            old_ids=[r['order_item_id'] for r in con.execute('SELECT order_item_id FROM order_items WHERE order_id=?',(oid,))]
            con.execute('DELETE FROM order_items WHERE order_id=?',(oid,))
            for old_id in old_ids:con.execute('DELETE FROM v35_order_line_meta WHERE order_item_id=?',(old_id,))
            for line in clean_lines:
                ref(con,'products','product_id',line['product_id'])
                item_id=m.uid('ITEM')
                con.execute('INSERT INTO order_items(order_item_id,order_id,product_id,quantity,unit_price) VALUES(?,?,?,?,?)',(item_id,oid,line['product_id'],line['quantity'],line['unit_price']))
                p=con.execute('SELECT internal_sku,product_code,cost_price,cost_currency,currency,cost_source FROM products WHERE product_id=?',(line['product_id'],)).fetchone()
                con.execute("""INSERT INTO v35_order_line_meta(order_item_id,sku_snapshot,unit_discount,tax_amount,line_total,unit_cost_snapshot,cost_currency,cost_source) VALUES(?,?,?,?,?,?,?,?)""",
                            (item_id,p['internal_sku'] or p['product_code'] or '',line['discount'],line['tax'],line['line_total'],p['cost_price'],p['cost_currency'] or p['currency'] or '',p['cost_source'] or ''))
        history(con,'Order',oid,'Order saved',dict(old) if old else None,{'status':status,'total':total,'currency':currency,'campaign_id':cam,'contact_id':cid,'line_count':len(clean_lines)})
        if status=='Paid':
            import process_orchestrator as po
            result=po.ensure_fulfilment_and_reserve_in_tx(con,oid)
            if result.get('shortages'):
                raise ValueError('Not enough stock to reserve this paid order: '+', '.join(x.get('product_id','') for x in result['shortages']))
    try:
        import business_os as bos
        eid=bos.emit('order.updated' if old else 'order.created','order',oid,{'status':status,'contact_id':cid,'campaign_id':cam},('order.updated:' if old else 'order.created:')+oid+':'+str(raw.get('version','0')))
        if status in {'Paid','Fulfilled'}:bos.enqueue('order.postpurchase','order',oid,{'contact_id':cid,'status':status},eid)
    except Exception as exc:
        try:bos.failure('order.event_handoff',str(exc),'The order is saved safely. Open Needs attention and retry the downstream automation.','order',oid,'Error')
        except Exception:m.audit('order.event_handoff_failed',oid,str(exc))
    if status in {'Paid','Fulfilled'}:
        try:
            import operating_core as oc
            oc.emit_event('ORDER_PLACED','order',oid,{'contact_id':cid,'campaign_id':cam,'status':status,'total':total,'currency':currency},dedupe_key=f'order:{oid}:{status}')
        except Exception as exc:
            try:
                import business_os as bos2;bos2.failure('order.operating_event',str(exc),'The order is saved safely. Retry the order workflow from Needs attention.','order',oid,'Error')
            except Exception:m.audit('order.operating_event_failed',oid,str(exc))
    if cid:
        try:truth.contact_priority(cid)
        except Exception:pass
    return oid


def _external_status(financial_status: str, fulfilment_status: str='') -> str:
    # Map provider states into the small canonical order lifecycle without inventing success.
    fin=str(financial_status or '').strip().upper().replace(' ','_')
    fulf=str(fulfilment_status or '').strip().upper().replace(' ','_')
    if fin in {'REFUNDED','FULLY_REFUNDED'}: return 'Refunded'
    if fin in {'VOIDED','CANCELLED','CANCELED'}: return 'Cancelled'
    if fin in {'PAID','PARTIALLY_REFUNDED'}:
        return 'Fulfilled' if fulf in {'FULFILLED','DELIVERED'} else 'Paid'
    return 'Pending'


def sync_external_order(provider: str, connection_id: str, external_id: str, *, contact_id: str='', total=0,
                        currency: str='', financial_status: str='', fulfilment_status: str='', ordered_at: str='',
                        lines: list[dict]|None=None, provider_refund_total=0, provider_refund_currency: str='') -> dict:
    # Persist externally confirmed commerce truth without bypassing canonical order lines/snapshots.
    # Provider inventory reconciliation already reflects the external order, so this path records a
    # provider-managed fulfilment and does not create a second local reservation.
    initial_schema()
    provider=text(provider,80) or 'External provider';connection_id=text(connection_id,160);external_id=required(external_id,'external order ID',250)
    currency=text(currency,10) or str(m.settings().get('default_currency') or 'INR')
    try: total=float(total or 0)
    except Exception: raise ValueError('External order total is not numeric.') from None
    try: provider_refund_total=max(0.0,float(provider_refund_total or 0))
    except Exception: raise ValueError('External refund total is not numeric.') from None
    provider_refund_currency=text(provider_refund_currency,10) or currency
    lines=list(lines or [])
    mapped=[];unmapped=[]
    for raw in lines:
        pid=text(raw.get('product_id'),160)
        try: qty=int(raw.get('quantity') or 0)
        except Exception: qty=0
        try: unit=float(raw.get('unit_price') or 0)
        except Exception: unit=0.0
        if not pid or qty<=0:
            unmapped.append(raw);continue
        mapped.append({'product_id':pid,'quantity':qty,'unit_price':unit,'sku':text(raw.get('sku'),160)})
    status=_external_status(financial_status,fulfilment_status)
    # Initialise fulfilment schema before opening the order transaction. Opening a
    # second schema-writing SQLite connection from inside this transaction can
    # deadlock/lock a valid provider sync on older or partially initialised workspaces.
    import process_orchestrator as po
    po.initialise()
    with m.connect() as con:
        existing=con.execute('SELECT order_id FROM orders WHERE external_order_reference=? LIMIT 1',(external_id,)).fetchone()
        oid=existing[0] if existing else m.uid('ORD')
        cid=ref(con,'contacts','contact_id',contact_id) if contact_id else None
        account=primary_company(con,cid) if cid else None
        con.execute('''INSERT INTO orders(order_id,contact_id,company_id,order_type,order_status,total,currency,external_order_reference,ordered_at)
                       VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(order_id) DO UPDATE SET
                       contact_id=coalesce(excluded.contact_id,orders.contact_id),company_id=coalesce(excluded.company_id,orders.company_id),
                       order_status=excluded.order_status,total=excluded.total,currency=excluded.currency,ordered_at=coalesce(excluded.ordered_at,orders.ordered_at)''',
                    (oid,cid,account,'B2C',status,total,currency,external_id,ordered_at or dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()))
        con.execute('''INSERT INTO m42_order_meta(order_id,attribution_note) VALUES(?,?)
                       ON CONFLICT(order_id) DO UPDATE SET attribution_note=excluded.attribution_note,version=version+1''',
                    (oid,f'{provider} order synced from provider evidence.'))
        old_ids=[r['order_item_id'] for r in con.execute('SELECT order_item_id FROM order_items WHERE order_id=?',(oid,))]
        for old_id in old_ids: con.execute('DELETE FROM v35_order_line_meta WHERE order_item_id=?',(old_id,))
        con.execute('DELETE FROM order_items WHERE order_id=?',(oid,))
        actually_mapped=[]
        for line in mapped:
            prow=con.execute('SELECT internal_sku,product_code,cost_price,cost_currency,currency,cost_source FROM products WHERE product_id=?',(line['product_id'],)).fetchone()
            if not prow:
                unmapped.append(line);continue
            actually_mapped.append(line)
            item_id=m.uid('ITEM');line_total=round(line['quantity']*line['unit_price'],2)
            con.execute('INSERT INTO order_items(order_item_id,order_id,product_id,quantity,unit_price) VALUES(?,?,?,?,?)',(item_id,oid,line['product_id'],line['quantity'],line['unit_price']))
            con.execute('''INSERT INTO v35_order_line_meta(order_item_id,sku_snapshot,unit_discount,tax_amount,line_total,unit_cost_snapshot,cost_currency,cost_source)
                           VALUES(?,?,?,?,?,?,?,?)''',(item_id,line.get('sku') or prow['internal_sku'] or prow['product_code'] or '',0,0,line_total,prow['cost_price'],prow['cost_currency'] or prow['currency'] or currency,prow['cost_source'] or ''))
        sync_state='Needs product mapping' if unmapped else 'Synced'
        safe_unmapped=[{'sku':text(x.get('sku'),160),'external_product_id':text(x.get('external_product_id'),250),'quantity':int(x.get('quantity') or 0)} for x in unmapped]
        con.execute('''INSERT INTO v40_external_order_meta(order_id,provider,connection_id,external_status,external_fulfilment_status,sync_state,unmapped_line_count,unmapped_lines_json,provider_refund_total,provider_refund_currency)
                       VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(order_id) DO UPDATE SET provider=excluded.provider,connection_id=excluded.connection_id,
                       external_status=excluded.external_status,external_fulfilment_status=excluded.external_fulfilment_status,sync_state=excluded.sync_state,
                       unmapped_line_count=excluded.unmapped_line_count,unmapped_lines_json=excluded.unmapped_lines_json,provider_refund_total=excluded.provider_refund_total,
                       provider_refund_currency=excluded.provider_refund_currency,updated_at=CURRENT_TIMESTAMP''',
                    (oid,provider,connection_id,text(financial_status,80),text(fulfilment_status,80),sync_state,len(unmapped),json.dumps(safe_unmapped),provider_refund_total,provider_refund_currency))
        f=con.execute('SELECT id FROM v17_fulfilments WHERE order_id=?',(oid,)).fetchone()
        fid=f[0] if f else m.uid('FUL40')
        fulf_upper=str(fulfilment_status or '').upper()
        fstatus='Delivered' if status=='Fulfilled' or fulf_upper in {'FULFILLED','DELIVERED'} else ('Needs item review' if unmapped else 'Provider managed')
        delivered=dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat() if fstatus=='Delivered' else None
        con.execute('''INSERT INTO v17_fulfilments(id,order_id,contact_id,status,inventory_status,provider_connection_id,provider_fulfilment_id,delivered_at)
                       VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(order_id) DO UPDATE SET contact_id=excluded.contact_id,status=excluded.status,
                       inventory_status=excluded.inventory_status,provider_connection_id=excluded.provider_connection_id,
                       provider_fulfilment_id=excluded.provider_fulfilment_id,delivered_at=coalesce(v17_fulfilments.delivered_at,excluded.delivered_at),updated_at=CURRENT_TIMESTAMP''',
                    (fid,oid,cid or '',fstatus,'Provider reconciled' if not unmapped else 'Needs mapping',connection_id,external_id,delivered))
        history(con,'Order',oid,'External order synced',None,{'provider':provider,'external_id':external_id,'status':status,'mapped_lines':len(actually_mapped),'unmapped_lines':len(unmapped),'total':total,'currency':currency})
    return {'order_id':oid,'created':not bool(existing),'status':status,'mapped_lines':len(actually_mapped),'unmapped_lines':len(unmapped),'sync_state':sync_state}

def fingerprint(con,cid):
    c=con.execute('SELECT * FROM contacts WHERE contact_id=?',(cid,)).fetchone()
    if not c:raise ValueError('A selected contact no longer exists.')
    owner=con.execute('SELECT owner FROM m42_contact_meta WHERE contact_id=?',(cid,)).fetchone()
    tags=[r[0] for r in con.execute('SELECT tag FROM m41_tags WHERE contact_id=? ORDER BY tag',(cid,))]
    profile=con.execute('SELECT * FROM m41_profile WHERE contact_id=?',(cid,)).fetchone()
    perms=[list(r) for r in con.execute('SELECT * FROM marketing_permissions WHERE contact_id=? ORDER BY channel,permission_id',(cid,))]
    props=[list(r) for r in con.execute('SELECT property_id,value FROM m42_values WHERE contact_id=? ORDER BY property_id',(cid,))]
    return hashlib.sha256(json.dumps([list(c),owner[0] if owner else '',tags,list(profile) if profile else [],perms,props]).encode()).hexdigest()

def action_config(raw):
    action=choice(raw.get('action'),['owner','tag','task','stage','archive'],'internal action')
    if action=='owner':
        uidv=truth.resolve_user(raw.get('owner_user_id'));config={'owner_user_id':uidv,'owner':truth.user_label(uidv,'')}
    elif action=='tag':
        tag=ct.tags(required(raw.get('tag'),'a tag',100))
        if len(tag)!=1:raise ValueError('Add one tag per action.')
        config={'tag':tag[0]}
    elif action=='stage':
        config={'stage':choice(raw.get('stage'),LIFECYCLES,'customer stage')}
    elif action=='archive':
        config={}
    else:
        title=required(raw.get('title'),'a task title')
        try:days=int(raw.get('days') or 0)
        except (ValueError,TypeError):raise ValueError('Use a whole number of days.') from None
        if not 0<=days<=365:raise ValueError('Task timing must be between 0 and 365 days.')
        uidv=truth.resolve_user(raw.get('owner_user_id')) if raw.get('owner_user_id') else ''
        config={'title':title,'days':days,'owner_user_id':uidv,'owner':truth.user_label(uidv,'') if uidv else text(raw.get('owner'),100),'kind':choice(raw.get('kind') or 'Review',KINDS,'task type')}
    return action,config

def plan_action(ids,raw,rule_id=None):
    ids=list(dict.fromkeys(ids))
    if not 1<=len(ids)<=100:raise ValueError('Select between 1 and 100 contacts for this reviewed action.')
    action,config=action_config(raw);ident=m.uid('PLAN')
    with m.connect() as con:
        targets=[]
        for cid in ids:
            if contact_archived(con,cid):raise ValueError('Archived contacts cannot be included in new bulk actions. Restore them first.')
            stamp=fingerprint(con,cid)
            if rule_id:
                if con.execute('SELECT 1 FROM m42_enrolments WHERE rule_id=? AND contact_id=?',(rule_id,cid)).fetchone():continue
                if con.execute('SELECT qualification_status FROM contacts WHERE contact_id=?',(cid,)).fetchone()[0]=='Do Not Contact':continue
            name=con.execute('SELECT full_name,username FROM contacts WHERE contact_id=?',(cid,)).fetchone()
            targets.append({'id':cid,'name':name[0] or name[1] or cid,'stamp':stamp})
        if not targets:raise ValueError('No new matching records remain for this internal workflow.')
        payload={'action':action,'config':config,'contacts':targets,'rule_id':rule_id,'date':dt.date.today().isoformat()}
        con.execute('INSERT INTO m42_plans(id,kind,payload) VALUES(?,?,?)',(ident,'Workflow' if rule_id else 'Bulk',json.dumps(payload)))
    return ident

def apply_plan(ident):
    with m.connect() as con:
        con.execute('BEGIN IMMEDIATE')
        row=con.execute('SELECT *,julianday("now")-julianday(created_at) age FROM m42_plans WHERE id=?',(ident,)).fetchone()
        if not row:raise ValueError('Preview not found.')
        if row['status']=='Applied':return 0
        if row['age']>1/48:raise ValueError('This preview expired. Create a new preview before applying.')
        p=json.loads(row['payload']);rule=p.get('rule_id')
        for c in p['contacts']:
            if fingerprint(con,c['id'])!=c['stamp']:raise ValueError('A selected contact changed since preview. Create a new preview; nothing was applied.')
            if rule and con.execute('SELECT 1 FROM m42_enrolments WHERE rule_id=? AND contact_id=?',(rule,c['id'])).fetchone():raise ValueError('A record already ran through this workflow. Preview again; nothing was applied.')
        for c in p['contacts']:
            cfg=p['config'];cid=c['id'];before={}
            if p['action']=='owner':
                old=con.execute('SELECT owner,owner_user_id FROM m42_contact_meta WHERE contact_id=?',(cid,)).fetchone();before={'owner':old['owner'] if old else '','owner_user_id':old['owner_user_id'] if old else ''}
                con.execute('INSERT INTO m42_contact_meta(contact_id,owner,owner_user_id) VALUES(?,?,?) ON CONFLICT(contact_id) DO UPDATE SET owner=excluded.owner,owner_user_id=excluded.owner_user_id,updated_at=CURRENT_TIMESTAMP',(cid,cfg['owner'],cfg['owner_user_id']))
            elif p['action']=='tag':
                before={'tags':[r[0] for r in con.execute('SELECT tag FROM m41_tags WHERE contact_id=?',(cid,))]}
                con.execute('INSERT OR IGNORE INTO m41_tags(contact_id,tag) VALUES(?,?)',(cid,cfg['tag']))
            elif p['action']=='stage':
                old=con.execute('SELECT lifecycle_stage FROM contacts WHERE contact_id=?',(cid,)).fetchone();before={'lifecycle_stage':old[0] if old else ''}
                con.execute('UPDATE contacts SET lifecycle_stage=? WHERE contact_id=?',(cfg['stage'],cid))
            elif p['action']=='archive':
                old=con.execute('SELECT archived_at FROM m42_contact_meta WHERE contact_id=?',(cid,)).fetchone();before={'archived_at':old[0] if old else None}
                con.execute('INSERT INTO m42_contact_meta(contact_id,archived_at) VALUES(?,CURRENT_TIMESTAMP) ON CONFLICT(contact_id) DO UPDATE SET archived_at=CURRENT_TIMESTAMP,updated_at=CURRENT_TIMESTAMP',(cid,))
            else:
                due=(dt.date.fromisoformat(p['date'])+dt.timedelta(days=cfg['days'])).isoformat()
                task_save({'title':cfg['title'],'contact_id':cid,'due_date':due,'owner':cfg['owner'],'owner_user_id':cfg.get('owner_user_id',''),'kind':cfg['kind']},con=con)
            history(con,'Contact',cid,('Workflow: ' if rule else 'Bulk: ')+p['action'],before,{'plan_id':ident,**cfg})
            if rule:con.execute('INSERT INTO m42_enrolments(rule_id,contact_id,plan_id) VALUES(?,?,?)',(rule,cid,ident))
        con.execute("UPDATE m42_plans SET status='Applied' WHERE id=?",(ident,))
    return len(p['contacts'])

def rule_save(raw):
    name=required(raw.get('name'),'a workflow name')
    conditions={k:text(raw.get(k),100) for k in ['type','stage','tag_filter']}
    if conditions['type']:choice(conditions['type'],['B2B','B2C','Both','Unknown'],'journey')
    if conditions['stage']:choice(conditions['stage'],LIFECYCLES,'stage')
    if not any(conditions.values()):raise ValueError('Add at least one condition so the workflow has a specific audience.')
    action,config=action_config(raw);rid=m.uid('RULE')
    with m.connect() as con:con.execute('INSERT INTO m42_rules(id,name,conditions,action,config) VALUES(?,?,?,?,?)',(rid,name,json.dumps(conditions),action,json.dumps(config)))
    return rid

def rule_preview(rid):
    r=m.one('SELECT * FROM m42_rules WHERE id=?',(rid,))
    if not r:raise ValueError('Workflow not found.')
    conditions=json.loads(r['conditions']);_,records=filter_contacts({'type':conditions['type'],'stage':conditions['stage'],'tag':conditions['tag_filter']})
    seen={x['contact_id'] for x in m.rows('SELECT contact_id FROM m42_enrolments WHERE rule_id=?',(rid,))}
    ids=[c['contact_id'] for c in records if c['contact_id'] not in seen and c['qualification_status']!='Do Not Contact'][:100]
    if not ids:raise ValueError('No new matching contacts. Each contact is processed at most once per workflow.')
    return plan_action(ids,{'action':r['action'],**json.loads(r['config'])},rid)

def search(term):
    term=text(term,200)
    if len(term)<2:return []
    v='%'+term+'%';result=[]
    configs=[('Contact',"SELECT c.contact_id id,coalesce(c.full_name,c.username) label,c.email detail FROM contacts c LEFT JOIN m42_contact_meta cm USING(contact_id) WHERE cm.archived_at IS NULL AND (c.full_name LIKE ? OR c.username LIKE ? OR c.email LIKE ? OR c.phone_number LIKE ?) ORDER BY c.full_name LIMIT 12",(v,v,v,v),'/contacts/'),
      ('Account',"SELECT company_id id,company_name label,company_type detail FROM companies WHERE company_name LIKE ? AND coalesce(status,'Active')<>'Archived' ORDER BY company_name LIMIT 8",(v,),'/companies/'),
      ('Deal','SELECT opportunity_id id,name label,stage detail FROM opportunities WHERE name LIKE ? ORDER BY created_at DESC LIMIT 8',(v,),'/opportunities/'),
      ('Product',"SELECT product_id id,public_product_name label,coalesce(product_code,internal_sku,'') detail FROM products WHERE coalesce(status,'Draft')<>'Archived' AND (public_product_name LIKE ? OR product_code LIKE ? OR internal_sku LIKE ? OR colour LIKE ?) ORDER BY created_at DESC LIMIT 10",(v,v,v,v),'/products/'),
      ('Order',"SELECT order_id id,order_id label,coalesce(external_order_reference,order_status) detail FROM orders WHERE order_id LIKE ? OR external_order_reference LIKE ? ORDER BY ordered_at DESC LIMIT 8",(v,v),'/orders/'),
      ('Customer selection',"SELECT showroom_id id,title label,coalesce(status,'Draft') detail FROM showrooms WHERE coalesce(status,'Draft') NOT IN ('Archived','Inactive') AND title LIKE ? ORDER BY created_at DESC LIMIT 8",(v,),'/showrooms/'),
      ('Task',"SELECT id,title label,coalesce(due_date,status) detail FROM m4_tasks WHERE title LIKE ? ORDER BY due_date DESC LIMIT 8",(v,),'/tasks/')]
    for typ,sql,args,prefix in configs:
        for r in m.rows(sql,args):
            url=prefix+r['id']+('/edit' if typ=='Task' else '')
            result.append({'type':typ,**r,'url':url})
    for r in truth.campaign_search(term,8):
        result.append({'type':'Campaign','id':r['id'],'label':r['name'],'detail':r.get('channels') or r.get('status') or '','url':'/campaign-builder/'+r['id']})
    return result

def reports():
    totals={k:0 for k in ['B2B','B2C','Both','Unknown']}
    for r in m.rows('SELECT contact_type k,count(*) n FROM contacts GROUP BY contact_type'):totals[r['k'] or 'Unknown']=totals.get(r['k'] or 'Unknown',0)+r['n']
    pipeline=m.rows("SELECT coalesce(currency,'Unspecified') currency,stage,count(*) n,coalesce(sum(estimated_value),0) amount FROM opportunities GROUP BY currency,stage")
    orders=m.rows("SELECT coalesce(currency,'Unspecified') currency,order_status,count(*) n,coalesce(sum(total),0) amount FROM orders GROUP BY currency,order_status")
    if m.table_exists('v10_unified_campaigns'):
        campaign=m.rows("""SELECT ca.id campaign_id,ca.name campaign_name,ca.channels_json channel,
          (SELECT count(*) FROM campaign_members cm WHERE cm.campaign_id=ca.id) audience,
          (SELECT count(*) FROM m4_drafts d WHERE d.campaign_id=ca.id) drafts,
          (SELECT count(*) FROM m4_drafts d WHERE d.campaign_id=ca.id AND d.status='Approved') approved
          FROM v10_unified_campaigns ca ORDER BY ca.created_at DESC""")
    else:
        campaign=m.rows("""SELECT campaign_id,campaign_name,coalesce(channel,'') channel,
          (SELECT count(*) FROM campaign_members cm WHERE cm.campaign_id=campaigns.campaign_id) audience,
          (SELECT count(*) FROM m4_drafts d WHERE d.campaign_id=campaigns.campaign_id) drafts,
          (SELECT count(*) FROM m4_drafts d WHERE d.campaign_id=campaigns.campaign_id AND d.status='Approved') approved
          FROM campaigns ORDER BY created_at DESC""") if m.table_exists('campaigns') else []
    meta_cols={r['name'] for r in m.rows("PRAGMA table_info(m42_order_meta)")} if m.table_exists('m42_order_meta') and not db_layer.USING_POSTGRES else set()
    campaign_ref="coalesce(nullif(x.canonical_campaign_id,''),x.campaign_id)" if 'canonical_campaign_id' in meta_cols else 'x.campaign_id'
    attribution=m.rows(f"""SELECT ca.name campaign_name,coalesce(o.currency,'Unspecified') currency,o.order_status,count(*) orders,coalesce(sum(o.total),0) amount
      FROM orders o JOIN m42_order_meta x USING(order_id) JOIN v10_unified_campaigns ca ON ca.id={campaign_ref}
      GROUP BY ca.id,o.currency,o.order_status""") if m.table_exists('v10_unified_campaigns') and m.table_exists('m42_order_meta') else []
    return {'contacts':totals,'pipeline':pipeline,'orders':orders,'campaigns':campaign,'attribution':attribution}

def backup():
    if db_layer.USING_POSTGRES:
        raise ValueError('Browser SQLite snapshots are disabled in PostgreSQL mode. Use System health → full backup for the production database.')
    folder=m.DB.parent/'backups';folder.mkdir(exist_ok=True)
    name='workspace_'+dt.datetime.now(dt.timezone.utc).strftime('%Y%m%d_%H%M%S')+'_'+secrets.token_hex(3)+'.sqlite'
    path=folder/name
    with sqlite3.connect(m.DB) as src,sqlite3.connect(path) as dst:
        src.backup(dst)
        if dst.execute('PRAGMA quick_check').fetchone()[0]!='ok':raise ValueError('Backup integrity check failed. Your working database was not changed.')
    path.chmod(0o600)
    m.audit('backup.created','',name+'; database only, excludes image files and separate API key')
    return name
