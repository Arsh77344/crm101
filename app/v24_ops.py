"""V25 daily-operations helpers (module name retained for upgrade compatibility).

Adds owner-facing operating data that is deliberately separate from historical
business records: showroom operational details, product duplication, bulk
product archival, and an exception/activity summary used by the dashboard.
"""
from __future__ import annotations
import datetime as dt
import json
import re

import marketing as m
import db_layer
import observability

SCHEMA = r'''
CREATE TABLE IF NOT EXISTS m24_showroom_details(
  showroom_id TEXT PRIMARY KEY,
  address TEXT DEFAULT '',
  contact_email TEXT DEFAULT '',
  contact_phone TEXT DEFAULT '',
  opening_hours TEXT DEFAULT '',
  staff_notes TEXT DEFAULT '',
  updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS m24_notifications(
  id TEXT PRIMARY KEY,
  kind TEXT NOT NULL,
  title TEXT NOT NULL,
  detail TEXT DEFAULT '',
  action_url TEXT DEFAULT '',
  severity TEXT DEFAULT 'info',
  dedupe_key TEXT UNIQUE,
  read_at TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
'''

def initialise():
    with m.connect() as con:
        if db_layer.USING_POSTGRES:
            for stmt in [x.strip() for x in SCHEMA.split(';') if x.strip()]:
                con.execute(stmt)
        else:
            con.executescript(SCHEMA)
        # V26 standardises showroom lifecycle language. Historical Draft rows
        # represented an enabled local preview, so migrate them to Active.
        if m.table_exists('showrooms'):
            con.execute("UPDATE showrooms SET status='Active' WHERE coalesce(status,'Draft')='Draft' AND coalesce(public_enabled,1)=1")
            con.execute("UPDATE showrooms SET status='Inactive' WHERE coalesce(status,'Draft')='Draft' AND coalesce(public_enabled,1)=0")


def showroom_details(showroom_id: str) -> dict:
    if not m.table_exists('m24_showroom_details'): initialise()
    row=m.one('SELECT * FROM m24_showroom_details WHERE showroom_id=?',(showroom_id,))
    return row or {'showroom_id':showroom_id,'address':'','contact_email':'','contact_phone':'','opening_hours':'','staff_notes':'','updated_at':''}


def save_showroom_details(showroom_id: str, raw: dict) -> None:
    if not m.table_exists('m24_showroom_details'): initialise()
    if not m.one('SELECT showroom_id FROM showrooms WHERE showroom_id=?',(showroom_id,)):
        raise ValueError('Showroom not found.')
    def clean(k,n): return str(raw.get(k) or '').strip()[:n]
    email=clean('contact_email',250)
    if email and not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',email):
        raise ValueError('Enter a valid showroom email address or leave it blank.')
    phone=clean('contact_phone',80)
    payload=(clean('address',1200),email,phone,clean('opening_hours',1200),clean('staff_notes',3000),showroom_id)
    with m.connect() as con:
        con.execute('''INSERT INTO m24_showroom_details(address,contact_email,contact_phone,opening_hours,staff_notes,showroom_id)
          VALUES(?,?,?,?,?,?) ON CONFLICT(showroom_id) DO UPDATE SET address=excluded.address,contact_email=excluded.contact_email,
          contact_phone=excluded.contact_phone,opening_hours=excluded.opening_hours,staff_notes=excluded.staff_notes,updated_at=CURRENT_TIMESTAMP''',payload)
    m.audit('showroom.operations.updated',showroom_id,'Address, contact, opening-hours or staff notes updated.')


def set_showroom_active(showroom_id: str, active: bool) -> None:
    row=m.one('SELECT * FROM showrooms WHERE showroom_id=?',(showroom_id,))
    if not row: raise ValueError('Showroom not found.')
    if row.get('status')=='Archived': raise ValueError('Restore this showroom before changing its active state.')
    with m.connect() as con:
        con.execute('UPDATE showrooms SET status=?,public_enabled=? WHERE showroom_id=?',('Active' if active else 'Inactive',1 if active else 0,showroom_id))
    m.audit('showroom.activated' if active else 'showroom.deactivated',showroom_id,'Showroom activated.' if active else 'Showroom deactivated without archiving history.')


def duplicate_product(product_id: str) -> str:
    old=m.one('SELECT * FROM products WHERE product_id=?',(product_id,))
    if not old: raise ValueError('Product not found.')
    if old.get('status')=='Archived': raise ValueError('Restore the product before duplicating it.')
    with m.connect() as con:
        cols=[r['name'] if isinstance(r,dict) else r[1] for r in con.execute('PRAGMA table_info(products)').fetchall()]
        if not cols:
            # PostgreSQL path: use information_schema through the db abstraction if needed.
            cols=[k for k in old.keys()]
        new_id=m.uid('PRD')
        row=dict(old)
        row['product_id']=new_id
        sku=(old.get('internal_sku') or old.get('product_code') or 'SKU')
        base=re.sub(r'[^A-Za-z0-9_-]+','-',sku).strip('-')[:40] or 'SKU'
        row['internal_sku']=f'{base}-COPY-{new_id[-5:]}'
        if 'product_code' in row: row['product_code']=row['internal_sku']
        row['public_product_name']=(old.get('public_product_name') or 'Product')+' (Copy)'
        row['status']='Draft'
        if 'published_at' in row: row['published_at']=None
        if 'duplicate_group' in row: row['duplicate_group']=old.get('duplicate_group') or old['product_id']
        if 'created_at' in row: row.pop('created_at',None)
        write=[c for c in cols if c in row and c!='created_at']
        con.execute('INSERT INTO products('+','.join(write)+') VALUES('+','.join('?'*len(write))+')',tuple(row[c] for c in write))
        # Copy source image associations as references to the same immutable media.
        imgs=con.execute('SELECT * FROM product_images WHERE product_id=?',(product_id,)).fetchall()
        for img in imgs:
            d=dict(img); d['image_id']=m.uid('IMG'); d['product_id']=new_id
            keys=list(d)
            con.execute('INSERT INTO product_images('+','.join(keys)+') VALUES('+','.join('?'*len(keys))+')',tuple(d[k] for k in keys))
    m.audit('product.duplicated',new_id,'Created from '+product_id+' as Draft; source media references were retained for review.')
    return new_id


def archive_products(ids: list[str]) -> int:
    ids=list(dict.fromkeys(str(x) for x in ids if x))
    if not 1 <= len(ids) <= 100:
        raise ValueError('Select between 1 and 100 products for a bulk archive.')
    count=0
    for pid in ids:
        row=m.one('SELECT status FROM products WHERE product_id=?',(pid,))
        if not row: raise ValueError('A selected product no longer exists. Refresh and try again.')
        if row.get('status')!='Archived':
            with m.connect() as con:
                con.execute("UPDATE products SET status='Archived' WHERE product_id=?",(pid,))
                if m.table_exists('v9_recommendations'):
                    con.execute("UPDATE v9_recommendations SET status='Superseded',resolved_at=CURRENT_TIMESTAMP WHERE status='Open' AND (dedupe_key IN (?,?) OR action_url=?)",(f'product-ready:{pid}',f'product-launch:{pid}',f'/products/{pid}'))
                if m.table_exists('v17_processes'):
                    con.execute("UPDATE v17_processes SET status='Archived',updated_at=CURRENT_TIMESTAMP WHERE process_type='product_to_market' AND object_id=?",(pid,))
            m.audit('product.archived',pid,'Bulk archive from Products & catalogue; historical references preserved.')
            count+=1
    return count


def _count(sql,args=(),*,errors=None,label='metric'):
    try:
        return int((m.one(sql,args) or {'n':0}).get('n') or 0)
    except Exception as exc:
        observability.log('owner_dashboard.metric_failed',metric=label,error=str(exc))
        if errors is not None: errors.append(label)
        return 0


def daily_summary() -> dict:
    # Close interrupted synchronous product intakes before counting alerts.
    try:
        import product_engine as pe
        pe.reconcile_stale_intakes()
    except Exception as exc:
        observability.log('owner_dashboard.intake_reconcile_failed',error=str(exc))
    # A zero is useful only when the query actually ran. V26 returns a degraded
    # flag whenever a required dashboard metric could not be verified.
    today=dt.date.today().isoformat();errors=[]
    c=lambda label,sql,args=():_count(sql,args,errors=errors,label=label)
    out={
      'tasks_due':c('tasks_due',"SELECT count(*) n FROM m4_tasks WHERE status='Open' AND due_date<=?",(today,)),
      'product_review':c('product_review',"SELECT count(*) n FROM products p LEFT JOIN m4_product_review r USING(product_id) WHERE coalesce(p.status,'Draft')<>'Archived' AND coalesce(r.confirmed,0)=0"),
      'draft_campaigns':c('draft_campaigns',"SELECT count(*) n FROM v10_unified_campaigns WHERE status='Draft'") if m.table_exists('v10_unified_campaigns') else c('draft_campaigns',"SELECT count(*) n FROM campaigns WHERE status='Draft'"),
      'open_deals':c('open_deals',"SELECT count(*) n FROM opportunities WHERE stage NOT IN ('Won','Lost')"),
      'pending_orders':c('pending_orders',"SELECT count(*) n FROM orders WHERE order_status IN ('Draft','Pending')"),
      'low_stock':c('low_stock',"SELECT count(*) n FROM (SELECT p.product_id FROM products p JOIN v9_inventory i ON i.product_id=p.product_id WHERE coalesce(p.status,'Draft')<>'Archived' GROUP BY p.product_id HAVING coalesce(sum(i.on_hand-i.reserved),0)<=2)") if m.table_exists('v9_inventory') else 0,
      'failed_image_jobs':c('failed_image_jobs',"SELECT count(*) n FROM v7_creative_jobs WHERE status='Failed'") if m.table_exists('v7_creative_jobs') else 0,
      'failed_video_jobs':c('failed_video_jobs',"SELECT count(*) n FROM v8_video_jobs WHERE status='Failed'") if m.table_exists('v8_video_jobs') else 0,
      'failed_worker_jobs':c('failed_worker_jobs',"SELECT count(*) n FROM v12_worker_jobs WHERE status IN ('Failed','Dead','DeadLetter')") if m.table_exists('v12_worker_jobs') else 0,
      'failed_business_jobs':c('failed_business_jobs',"SELECT count(*) n FROM v9_jobs WHERE status IN ('Failed','Dead letter','DeadLetter')") if m.table_exists('v9_jobs') else 0,
      'failed_intakes':c('failed_intakes',"SELECT count(*) n FROM v6_product_intakes WHERE status='Failed'") if m.table_exists('v6_product_intakes') else 0,
      'open_failures':c('open_failures',"SELECT count(*) n FROM v9_failures WHERE coalesce(resolved,0)=0") if m.table_exists('v9_failures') else 0,
      'open_incidents':c('open_incidents',"SELECT count(*) n FROM v13_incidents WHERE status='Open' AND severity IN ('Error','Critical')") if m.table_exists('v13_incidents') else 0,
    }
    out['failed_jobs']=out['failed_image_jobs']+out['failed_video_jobs']+out['failed_worker_jobs']+out['failed_business_jobs']
    # V53: one canonical operational-health read model. Home and System Health must not disagree.
    try:
        import business_os as _bos
        canonical=_bos.canonical_operational_health()
        out['system_alerts']=int(canonical.get('unresolved') or 0)
        out['canonical_operational_health']=canonical
    except Exception as exc:
        observability.log('owner_dashboard.canonical_health_failed',error=str(exc))
        out['system_alerts']=out['failed_jobs']+out['failed_intakes']+out['open_failures']+out['open_incidents']
        errors.append('canonical_operational_health')
    out['metric_errors']=sorted(set(errors))
    out['degraded']=bool(errors)
    return out


def attention_total(summary: dict) -> int:
    """Return one owner-facing attention count used consistently across the shell and Home."""
    keys=('tasks_due','product_review','draft_campaigns','pending_orders','low_stock','system_alerts')
    return sum(int(summary.get(k,0) or 0) for k in keys)


def _friendly_audit_detail(detail: str, object_id: str='') -> str:
    """Turn machine payloads into short owner-readable activity text.

    Raw JSON/version snapshots remain available in Change history, not on Home.
    """
    text=str(detail or '').strip()
    if not text:
        return str(object_id or 'Recorded successfully.')
    if text[:1] in {'{','['}:
        try:
            obj=json.loads(text)
            if isinstance(obj,dict):
                status=str(obj.get('status') or '').strip()
                name=str(obj.get('name') or obj.get('title') or obj.get('campaign_name') or '').strip()
                ident=str(obj.get('id') or object_id or '').strip()
                bits=[x for x in [name, status, ident] if x]
                return ' · '.join(bits[:3]) or 'A stored record version was updated.'
            if isinstance(obj,list):
                return f'{len(obj)} stored item(s) updated.'
        except Exception:
            return 'A stored record version was updated.'
    return text[:500]


def recent_business_activity(limit: int=8) -> list[dict]:
    """Owner Home feed: business changes only, excluding migration/maintenance plumbing."""
    rows=recent_activity(max(40,int(limit or 8)*6))
    allowed={'Products','Product','Customers','Customer','Contacts','Contact','Marketing','Campaign','Campaigns','Orders','Order','Sales','Opportunity','Tasks','Task','Stock','Customer Selections','Customer selections'}
    out=[]
    for row in rows:
        kind=str(row.get('kind') or '')
        title=str(row.get('title') or '').lower()
        if kind not in allowed:
            continue
        if any(token in title for token in ('unified index','legacy approval reset','connection test','migration','backfill','previous version')):
            continue
        out.append(row)
        if len(out)>=limit:break
    return out


def recent_activity(limit: int=30) -> list[dict]:
    """Return an owner-facing activity feed rather than raw audit plumbing.

    The raw audit trail remains available under Change history/System health. This
    feed intentionally hides no-op scheduler heartbeats and converts machine event
    names/JSON payloads into business language.
    """
    events=[];errors=[]
    # Scan substantially more raw audit rows than the requested visible limit.
    # No-op scheduler heartbeats are filtered below; using only limit*2/limit*3
    # could therefore make Home look empty while the full Activity page had data.
    scan_limit=max(250,min(2000,int(limit or 30)*25))

    def human_action(action: str, detail: str, object_id: str=''):
        action=str(action or '').strip();raw_detail=str(detail or '').strip()
        if action.startswith('draft.') or 'previous_version' in action or 'previous-version' in action:
            return None
        # Repeating scheduler heartbeats with no completed/failed work add noise but
        # no owner value. Keep failures/completions when something actually happened.
        if action=='schedule.completed':
            try:
                payload=json.loads(raw_detail) if raw_detail.startswith('{') else {}
            except Exception:
                payload={}
            completed=int(payload.get('completed') or 0);failed=int(payload.get('failed') or 0)
            checked=int(payload.get('checked') or 0);attention=int(payload.get('attention') or 0)
            if completed==0 and failed==0 and checked==0 and attention==0:
                return None
            if failed:
                return ('Automation','Scheduled work needs attention',f'{failed} scheduled action(s) failed; {completed} completed.')
            if completed:
                return ('Automation','Scheduled work completed',f'{completed} background action(s) completed.')
            if checked:
                return ('Connections','Connection health checked',f'{checked} connection(s) checked; {attention} need attention.')
        detail=_friendly_audit_detail(raw_detail,object_id)
        if action in {'recommendations.refreshed','recommendation.refreshed'}:
            m1=re.search(r'(\d+)\s+recommendation',detail,re.I)
            if m1 and int(m1.group(1))==0:return None
            return ('AI & automation','Recommendations refreshed',detail or 'Business recommendations were refreshed.')
        mapping={
            'product.archived':('Products','Product archived'),
            'product.restored':('Products','Product restored'),
            'product.duplicated':('Products','Product duplicated'),
            'product.created':('Products','Product created'),
            'campaign.created':('Marketing','Campaign created'),
            'campaign.archived':('Marketing','Campaign archived'),
            'showroom.created':('Customer selections','Customer selection created'),
            'showroom.archived':('Customer selections','Customer selection archived'),
            'showroom.restored':('Customer selections','Customer selection restored'),
            'location.saved':('Stock','Stock location saved'),
            'inventory.location_updated':('Stock','Stock updated'),
            'contact.archived':('Customers','Customer archived'),
            'contact.restored':('Customers','Customer restored'),
        }
        if action in mapping:
            kind,title=mapping[action]
            return kind,title,(detail or object_id or 'Recorded successfully.')
        # Preserve business semantics for audit-backed events not yet promoted to
        # the canonical change table. This prevents campaign/product/contact actions
        # from being mislabeled as generic System activity.
        prefix_map={
            'campaign.':('Marketing','Campaign updated'),
            'unified_campaign.':('Marketing','Campaign updated'),
            'product.':('Products','Product updated'),
            'contact.':('Customers','Customer updated'),
            'showroom.':('Customer selections','Customer selection updated'),
            'inventory.':('Stock','Stock updated'),
            'location.':('Stock','Stock location updated'),
        }
        for prefix,(kind,title) in prefix_map.items():
            if action.startswith(prefix):
                return kind,title,(detail or object_id or 'Recorded successfully.')
        # Fall back to a readable title; raw action name remains available in Change history.
        title=re.sub(r'[._-]+',' ',action).strip().capitalize() or 'System activity'
        return ('System',title,detail or object_id or 'Recorded successfully.')

    try:
        for r in m.rows("SELECT created_at,object_type,object_id,action,after_json,coalesce(event_scope,'business') event_scope,related_object_type,related_object_id FROM m42_changes ORDER BY created_at DESC LIMIT ?", (scan_limit,)):
            if str(r.get('event_scope') or 'business')=='relationship':
                continue
            label=re.sub(r'[._-]+',' ',str(r['action'] or '')).strip().capitalize() or 'Record updated'
            obj_type=str(r['object_type'] or 'Record')
            kind=('Opportunity' if obj_type=='Deal' else obj_type.replace('_',' ').title())
            detail=str(r['object_id'] or '')
            oid=str(r['object_id'] or '')
            # Owner activity should open the canonical business record whenever
            # that record has a stable owner-facing URL. Fall back to history
            # only for low-level/system object types.
            target={
                'Contact':'/contacts/'+oid,
                'Deal':'/opportunities/'+oid,
                'Task':'/tasks/'+oid+'/edit',
                'Order':'/orders/'+oid,
                'Account':'/companies/'+oid,
                'Product':'/products/'+oid,
                'Opportunity':'/opportunities/'+oid,
                'Campaign':'/campaign-builder/'+oid,
            }.get(obj_type,'/history') if oid else '/history'
            events.append({'time':r['created_at'],'kind':kind,'title':label,'detail':detail,'url':target})
    except Exception as exc:
        errors.append('change history');observability.log('activity_feed.load_failed',source='m42_changes',error=str(exc))
    try:
        for r in m.rows('SELECT created_at,action,object_id,detail FROM m4_audit ORDER BY created_at DESC LIMIT ?', (scan_limit,)):
            human=human_action(r['action'],r.get('detail') or '',r.get('object_id') or '')
            if not human:continue
            kind,title,detail=human
            oid=str(r.get('object_id') or '')
            action=str(r.get('action') or '')
            url='/history'
            if oid:
                if action.startswith('product.'): url='/products/'+oid
                elif action.startswith('contact.'): url='/contacts/'+oid
                elif action.startswith('showroom.'): url='/showrooms/'+oid
                elif action.startswith('campaign.'): url='/campaign-builder/'+oid
                elif action.startswith('location.') or action.startswith('inventory.'): url='/locations'
            events.append({'time':r['created_at'],'kind':kind,'title':title,'detail':detail,'url':url})
    except Exception as exc:
        errors.append('audit log');observability.log('activity_feed.load_failed',source='m4_audit',error=str(exc))
    if errors:
        events.append({'time':dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat(),
                       'kind':'System warning','title':'Some recent activity could not be loaded',
                       'detail':'Open System health before relying on an empty activity feed.','url':'/system-health'})
    events.sort(key=lambda x:str(x.get('time') or ''),reverse=True)

    # Compact immediately repeated audit records (for example a bulk product archive)
    # so the owner sees one meaningful action rather than many near-identical rows.
    compact=[]
    def parse_time(value):
        try:return dt.datetime.fromisoformat(str(value).replace('Z','+00:00'))
        except Exception:return None
    for ev in events:
        key=(ev.get('kind'),ev.get('title'),ev.get('detail'))
        if compact and compact[-1].get('_key')==key:
            a=parse_time(compact[-1].get('time'));b=parse_time(ev.get('time'))
            if not a or not b or abs((a-b).total_seconds())<=90:
                compact[-1]['count']=compact[-1].get('count',1)+1
                continue
        row=dict(ev);row['_key']=key;row['count']=1;compact.append(row)
    for row in compact:
        row.pop('_key',None)
        if row.get('count',1)>1:
            row['title']=f"{row['title']} · {row['count']} records"
    return compact[:limit]
