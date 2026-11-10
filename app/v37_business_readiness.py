"""V37 business-acceptance diagnostics and exception-first operating model."""
from __future__ import annotations
import datetime as dt
import re
from pathlib import Path

import db_layer
import marketing as m
import v35_truth as truth
import v40_integrity
import v50_reliability as v50


def initialise() -> None:
    truth.initialise()


def incident_action_url(entity_type: str, entity_id: str='') -> str:
    """Return the closest owner recovery screen for a canonical incident."""
    typ=str(entity_type or '').strip().lower();oid=str(entity_id or '').strip()
    if typ=='product' and oid:return '/products/'+oid
    if typ in {'contact','customer','lead'} and oid:return '/contacts/'+oid+'/review'
    if typ=='order' and oid:return '/operations/orders/'+oid
    if typ=='campaign' and oid:return '/campaign-builder/'+oid
    if typ in {'integration','connection','oauth','mcp'}:return '/integration-health'
    if typ in {'job','automation'}:return '/event-stream'
    return '/system-health'



def recovery_action(kind: str, title: str, url: str, object_type: str='', object_id: str='') -> tuple[str,str]:
    k=str(kind or '').lower(); t=str(title or '').lower(); typ=str(object_type or '').lower()
    if 'backup' in t or k in {'recovery','onboarding'}:
        return ('Create backup' if 'first backup' in t or 'required' in t else 'Verify backup', '/system-health')
    if k=='sales' or typ=='task': return ('Open task', '/tasks/'+str(object_id)+'/edit' if object_id else (url or '/tasks'))
    if k=='campaign' or typ=='campaign' or 'campaign' in t:
        return ('Review creative' if 'creative' in t else 'Open campaign', url or '/marketing')
    if k=='integration' or typ in {'integration','connection','oauth','mcp'}: return ('Reconnect', url or '/integration-health')
    if k=='product' or typ=='product': return ('Review product', url or '/products')
    if k=='inventory' or typ=='inventory' or 'stock' in t: return ('Review stock', url or '/locations')
    if k=='ai' or typ=='ai': return ('Configure AI', url or '/settings#ai')
    if typ=='order' or 'order' in t or 'fulfil' in t: return ('Open order', url or '/orders')
    if typ in {'contact','customer','lead'}: return ('Open customer', url or '/contacts')
    if k=='automation' or typ=='job': return ('Retry / inspect', url or '/event-stream')
    return ('Open recovery', url or '/system-health')

def crm_health() -> dict:
    initialise()
    total=int((m.one('SELECT count(*) n FROM contacts') or {'n':0})['n']) if m.table_exists('contacts') else 0
    missing_name=int((m.one("SELECT count(*) n FROM contacts WHERE coalesce(trim(full_name),'')='' AND coalesce(trim(username),'')='' ") or {'n':0})['n']) if total else 0
    missing_source=int((m.one("SELECT count(*) n FROM contacts WHERE coalesce(trim(source_name),'')='' ") or {'n':0})['n']) if total else 0
    invalid_email=0;invalid_phone=0
    if total:
        for r in m.rows('SELECT email,phone_number FROM contacts'):
            email=str(r.get('email') or '').strip();phone=str(r.get('phone_number') or '').strip()
            if email and not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',email):invalid_email+=1
            digits=re.sub(r'\D','',phone)
            if phone and (len(digits)<7 or len(digits)>15):invalid_phone+=1
    dup_email=int((m.one("SELECT coalesce(sum(n-1),0) n FROM (SELECT lower(trim(email)) e,count(*) n FROM contacts WHERE coalesce(trim(email),'')<>'' GROUP BY lower(trim(email)) HAVING count(*)>1) x") or {'n':0})['n']) if total else 0
    dup_phone=int((m.one("SELECT coalesce(sum(n-1),0) n FROM (SELECT replace(replace(replace(replace(replace(phone_number,' ',''),'-',''),'(',''),')',''),'+','') p,count(*) n FROM contacts WHERE coalesce(trim(phone_number),'')<>'' GROUP BY p HAVING count(*)>1) x") or {'n':0})['n']) if total else 0
    quality_issues=missing_name+missing_source+invalid_email+invalid_phone+dup_email+dup_phone
    clean=max(0,total-quality_issues)
    pct=round(clean/total*100,1) if total else 100.0
    return {'total':total,'quality_percent':pct,'missing_name':missing_name,'missing_source':missing_source,'invalid_email':invalid_email,'invalid_phone':invalid_phone,'duplicate_email_rows':dup_email,'duplicate_phone_rows':dup_phone}


def product_quality() -> dict:
    initialise();rows=m.rows("SELECT product_id FROM products WHERE coalesce(status,'Draft')<>'Archived'") if m.table_exists('products') else []
    missing_cost=missing_price=missing_inventory=not_store_ready=0
    for r in rows:
        ready=truth.product_readiness(r['product_id']);blockers=ready.get('blockers',[])
        missing_cost+=int('Missing cost data' in blockers);missing_price+=int('Missing price' in blockers);missing_inventory+=int('Missing inventory' in blockers);not_store_ready+=int(not ready.get('ready_for_store'))
    return {'total':len(rows),'missing_cost':missing_cost,'missing_price':missing_price,'missing_inventory':missing_inventory,'not_store_ready':not_store_ready}


def business_exceptions(limit: int=250) -> list[dict]:
    """Return evidence-backed exceptions with direct corrective actions."""
    initialise()
    try:
        import operating_core as _oc
        _oc.reconcile_incidents()
        import business_os as _bos
        _bos.dedupe_open_recommendations()
    except Exception:
        pass
    items=[]
    def add(priority,kind,title,detail,url,object_type='',object_id=''):
        label,action_url=recovery_action(kind,title,url,object_type,object_id)
        items.append({'priority':priority,'kind':kind,'title':title,'detail':detail,'url':action_url,'action_label':label,'object_type':object_type,'object_id':str(object_id or '')})
    gate=v40_integrity.integrity_gate(False)
    for f in gate.get('findings',[]):
        url='/system-health'
        if f.get('object_type')=='order':url='/operations/orders/'+str(f.get('object_id') or '')
        elif f.get('object_type')=='product':url='/products/'+str(f.get('object_id') or '')
        add('Critical' if f.get('severity')=='Critical' else 'High','Data integrity',f.get('check_key','Integrity issue').replace('_',' ').title(),f.get('detail',''),url,f.get('object_type',''),f.get('object_id',''))
    if m.table_exists('v12_worker_jobs'):
        for j in m.rows("SELECT id,job_type,status,last_error,updated_at FROM v12_worker_jobs WHERE status IN ('DeadLetter','Retry') ORDER BY CASE status WHEN 'DeadLetter' THEN 0 ELSE 1 END,updated_at DESC LIMIT 50"):
            add('Critical' if j['status']=='DeadLetter' else 'High','Automation','Background work failed: '+str(j['job_type']),j.get('last_error') or 'The system will retry according to its recovery policy.','/event-stream','job',j['id'])
    if m.table_exists('v13_incidents'):
        priority_map={'Critical':'Critical','Error':'High','Warning':'Medium','Info':'Info','High':'High','Medium':'Medium'}
        for x in m.rows("SELECT * FROM v13_incidents WHERE status='Open' ORDER BY CASE severity WHEN 'Critical' THEN 0 WHEN 'Error' THEN 1 WHEN 'High' THEN 1 WHEN 'Warning' THEN 2 WHEN 'Medium' THEN 2 ELSE 3 END,coalesce(last_seen,created_at) DESC LIMIT 50"):
            count=int(x.get('occurrence_count') or 1)
            recovery=str(x.get('recovery') or '').strip()
            detail=recovery or 'This workflow needs review before the system can continue safely.'
            if count>1: detail=f'{count} occurrences grouped · '+detail
            target=incident_action_url(x.get('entity_type') or '',x.get('entity_id') or '')
            label,target=recovery_action('Incident',x.get('title') or 'Operational incident',target,x.get('entity_type') or 'incident',x.get('entity_id') or '')
            item={'priority':priority_map.get(x.get('severity'),'High'),'kind':'Incident','title':x.get('title') or 'Operational incident','detail':detail,
                  'technical_detail':x.get('latest_error') or x.get('detail') or '',
                  'url':target,'action_label':label,'object_type':x.get('entity_type') or 'incident','object_id':str(x.get('entity_id') or x['id'])}
            items.append(item)
    if m.table_exists('v10_connections'):
        for c in m.rows("SELECT id,label,status,last_error,last_success_at FROM v10_connections WHERE status NOT IN ('Connected','Available to connect','Disconnected') OR coalesce(last_error,'')<>'' ORDER BY updated_at DESC LIMIT 50"):
            add('High','Integration',str(c.get('label') or 'Connection')+' needs attention',c.get('last_error') or ('Current status: '+str(c.get('status') or 'Unknown')),'/integration-health','integration',c['id'])
    if m.table_exists('products'):
        for p in m.rows("SELECT product_id,coalesce(public_product_name,product_code,internal_sku,product_id) name FROM products WHERE coalesce(status,'Draft')<>'Archived' ORDER BY created_at DESC LIMIT 200"):
            ready=truth.product_readiness(p['product_id'])
            if not ready.get('ready_to_sell'):
                add('High','Product','Product cannot be sold yet: '+str(p['name']),'; '.join(ready.get('blockers',[])[:5]),'/products/'+p['product_id'],'product',p['product_id'])
    if m.table_exists('m4_tasks'):
        for t in m.rows("SELECT id,title,contact_id,due_date,owner FROM m4_tasks WHERE status='Open' AND due_date<CURRENT_TIMESTAMP ORDER BY due_date LIMIT 50"):
            url='/contacts/'+t['contact_id']+'/review' if t.get('contact_id') else '/tasks'
            add('High','Sales','Overdue follow-up: '+str(t.get('title') or 'Task'),f"Due {t.get('due_date') or ''}"+((' · owner '+str(t.get('owner'))) if t.get('owner') else ''),url,'task',t['id'])
    if m.table_exists('v17_conversations'):
        for c in m.rows("SELECT id,contact_id,unread_count,last_message_at FROM v17_conversations WHERE status='Open' AND coalesce(unread_count,0)>0 ORDER BY last_message_at LIMIT 50"):
            add('High','Customer','Customer is waiting for a reply',f"{int(c.get('unread_count') or 0)} unread message(s); last activity {c.get('last_message_at') or ''}",'/operations/inbox','conversation',c['id'])
    # V46: AI failures are operational exceptions, not specialist-ledger trivia.
    # Group identical failures so a broken model/credential does not flood the owner.
    try:
        import ai_router
        ai_router.initialise()
        if m.table_exists('v42_ai_failure_groups'):
            rows=m.rows("""SELECT g.signature,g.task_key,g.provider,g.model,g.error_category,g.failure_count,g.latest_usage_id,
                     coalesce(u.error,'') error,coalesce(u.related_url,'') related_url,u.object_type,u.object_id
              FROM v42_ai_failure_groups g LEFT JOIN v13_ai_usage u ON u.id=g.latest_usage_id
              WHERE coalesce(g.resolved,0)=0 ORDER BY g.last_seen_at DESC LIMIT 30""")
            for x in rows:
                count=int(x.get('failure_count') or 1)
                task=str(x.get('task_key') or 'AI job').replace('_',' ')
                detail=(x.get('error') or x.get('error_category') or 'AI provider request failed.')
                if count>1: detail=f'{count} equivalent failures were grouped. '+detail
                url=x.get('related_url') or '/settings#ai'
                add('High','AI',f'AI {task} needs attention',detail[:1200],url,x.get('object_type') or 'ai',x.get('object_id') or x.get('latest_usage_id') or x.get('signature'))
    except Exception:
        pass
    # Campaign planning can succeed while one connected delivery channel fails.
    # Surface the channel error directly rather than leaving it buried in the builder.
    if m.table_exists('v10_campaign_channels'):
        for ch in m.rows("""SELECT cc.id,cc.campaign_id,cc.channel,cc.launch_status,cc.last_error,coalesce(c.name,cc.campaign_id) campaign_name
              FROM v10_campaign_channels cc LEFT JOIN v10_unified_campaigns c ON c.id=cc.campaign_id
              WHERE cc.launch_status IN ('Failed','Rejected','Needs attention') OR coalesce(cc.last_error,'')<>''
              ORDER BY cc.updated_at DESC LIMIT 50"""):
            detail=ch.get('last_error') or ('Channel status: '+str(ch.get('launch_status') or 'Needs attention'))
            add('High','Campaign',f"{ch.get('channel') or 'Campaign channel'} failed for {ch.get('campaign_name') or ch['campaign_id']}",detail,
                '/campaign-builder/'+str(ch['campaign_id']),'campaign',ch['campaign_id'])
    # Canonical cross-module processes that are blocked must be visible to the owner.
    if m.table_exists('v17_processes'):
        for pr in m.rows("SELECT id,process_type,object_type,object_id,status,current_step,summary_json FROM v17_processes WHERE status IN ('Blocked','Needs attention') ORDER BY updated_at DESC LIMIT 50"):
            step=m.one('SELECT label,detail,action_url,status FROM v17_process_steps WHERE process_id=? AND step_key=?',(pr['id'],pr.get('current_step') or '')) if m.table_exists('v17_process_steps') else None
            detail=(step or {}).get('detail') or 'The canonical business process stopped and needs an owner action or retry.'
            title=f"Continue {str(pr.get('process_type') or 'business process').replace('_',' ')}"
            if pr.get('process_type')=='lead_to_sale' and pr.get('object_id'):
                c=m.one('SELECT coalesce(nullif(full_name,''),nullif(username,''),nullif(email,''),contact_id) name FROM contacts WHERE contact_id=?',(pr['object_id'],)) if m.table_exists('contacts') else None
                title='Continue sale follow-up for '+str((c or {}).get('name') or pr['object_id'])
            if step and step.get('label'): title+=' · '+str(step['label'])
            url=(step or {}).get('action_url') or '/operations/process/'+str(pr['id'])
            add('High','Process',title,detail,url,pr.get('object_type') or 'process',pr.get('object_id') or pr['id'])
    # V47: a compatibility/unified lifecycle mismatch can bypass an owner lock.
    # Surface the exact campaign so the owner can inspect/repair it rather than
    # requiring them to discover the inconsistency only through System Doctor.
    if m.table_exists('campaigns') and m.table_exists('v10_unified_campaigns'):
        for row in m.rows("""SELECT c.campaign_id,c.campaign_name,c.status legacy_status,u.status unified_status
              FROM campaigns c JOIN v10_unified_campaigns u ON u.id=c.campaign_id
              WHERE (coalesce(c.status,'Draft') IN ('Archived','Paused') OR coalesce(u.status,'Draft') IN ('Archived','Paused'))
                AND coalesce(c.status,'Draft')<>coalesce(u.status,'Draft')
              ORDER BY c.created_at DESC LIMIT 50"""):
            detail=f"Campaign lifecycle disagrees: owner campaign status is {row.get('legacy_status') or 'Draft'} while unified execution status is {row.get('unified_status') or 'Draft'}. Do not execute until they agree."
            add('High','Campaign','Campaign lifecycle needs repair: '+str(row.get('campaign_name') or row['campaign_id']),detail,
                '/campaigns/'+str(row['campaign_id']),'campaign',row['campaign_id'])
    # V50 recovery truth: a backup file is not recovery evidence until the exact
    # latest archive has passed an isolated restore drill.
    try:
        root=Path(__file__).resolve().parent
        backup=v50.backup_readiness(root)
        if backup.get('status')!='VERIFIED':
            if backup.get('status')=='NOT_CREATED':
                add('Medium','Onboarding','First backup required','Create and verify your first backup to complete recovery setup.','/system-health','backup','')
            else:
                add('High','Recovery','Backup verification required',backup.get('detail') or 'Verify the latest full backup.','/system-health','backup',backup.get('latest') or '')
    except Exception:
        pass
    # V50 financial truth: a Refunded label without canonical refund evidence is
    # not allowed to silently alter revenue/profit reporting.
    try:
        for row in v50.financial_summary().get('incomplete_orders') or []:
            oid=str(row.get('order_id') or '')
            add('Critical','Financial truth','Refund evidence is incomplete for order '+oid,row.get('reason') or 'Refund evidence is incomplete.',('/operations/orders/'+oid) if oid else '/orders','order',oid)
    except Exception:
        pass
    # V53: canonicalise owner cards. The same underlying object/stage appears once.
    grouped={}
    for item in items:
        key=(item.get('kind'),item.get('object_type'),item.get('object_id'),item.get('title'))
        if key not in grouped:
            item=dict(item);item['occurrence_count']=1;grouped[key]=item
        else:
            grouped[key]['occurrence_count']=int(grouped[key].get('occurrence_count') or 1)+1
    items=list(grouped.values())
    for item in items:
        if int(item.get('occurrence_count') or 1)>1:
            item['detail']=f"{item['occurrence_count']} equivalent items grouped. "+str(item.get('detail') or '')
    rank={'Critical':0,'High':1,'Medium':2,'Info':3}
    items.sort(key=lambda x:(rank.get(x['priority'],9),x['kind'],x['title']))
    return items[:limit]


def backup_status(root: Path) -> dict:
    return v50.backup_readiness(Path(root))


def readiness_scorecard(root: Path) -> list[dict]:
    initialise();exc=business_exceptions();critical=sum(1 for x in exc if x['priority']=='Critical');pq=product_quality();crm=crm_health();backup=backup_status(root)
    ai=m.ai_health();ai_ready=ai.get('status')=='Connected'
    connected=int((m.one("SELECT count(*) n FROM v10_connections WHERE status='Connected'") or {'n':0})['n']) if m.table_exists('v10_connections') else 0
    cards=[]
    def add(domain,status,why,url):cards.append({'domain':domain,'status':status,'why':why,'url':url})
    add('Core application','READY' if not critical else 'NOT READY','No critical integrity findings.' if not critical else f'{critical} critical integrity finding(s) require repair.','/system-health')
    add('Products','READY WITH CONDITIONS' if pq['not_store_ready'] else 'READY',f"{pq['total']} product(s); {pq['not_store_ready']} not store-ready.",'/products')
    add('AI','READY WITH CONDITIONS' if ai_ready else 'NOT READY','Live AI status: '+str(ai.get('status') or 'Unknown')+'.','/settings#ai')
    add('Inventory','NOT READY' if any(x.get('priority')=='Critical' and 'inventory' in (x.get('title') or '').lower() for x in exc) else ('READY WITH CONDITIONS' if pq['missing_inventory'] else 'READY'),f"Canonical stock checks are active; {pq['missing_inventory']} product(s) still have no canonical inventory row.",'/locations')
    add('CRM','READY WITH CONDITIONS' if (crm['quality_percent']<100 or crm['duplicate_email_rows'] or crm['duplicate_phone_rows'] or crm['invalid_email'] or crm['invalid_phone']) else 'READY',f"CRM health {crm['quality_percent']}%; review duplicates, invalid details and missing sources.",'/contacts')
    add('Sales','READY WITH CONDITIONS','Priority scoring, opportunities and tasks work; mature per-user work queues still need live multi-user acceptance.','/opportunities')
    add('Orders','READY','Order lines, idempotency, immutable cost snapshots and state protection are active.','/orders')
    add('Fulfilment','READY WITH CONDITIONS','Line-level partial/multiple shipments are transactionally hardened; carrier automation remains external.','/operations/fulfilments')
    add('Returns','READY WITH CONDITIONS','Returns are line/quantity based and now limited to shipped quantities; payment-provider refunds remain external.','/operations/returns')
    add('Marketing','READY WITH CONDITIONS','Campaign planning works; live execution depends on connected channels.','/marketing')
    add('Integrations','READY WITH CONDITIONS' if connected else 'NOT READY',f'{connected} live connection(s) currently report Connected.','/integrations')
    add('Automation','READY WITH CONDITIONS','Durable jobs, retries and dead-letter handling exist; review open exceptions.','/event-stream')
    add('Analytics','READY WITH CONDITIONS','Core order/profitability facts exist; live channel metrics and advanced cohort/CAC/CLV remain conditional.','/marketing-performance')
    add('Security','READY WITH CONDITIONS','Local mode is single-user friendly; production still requires HTTPS, MFA and live role acceptance.','/access-control')
    add('Reliability','READY WITH CONDITIONS','Integrity checks and retries are active; external outage recovery requires provider acceptance.','/system-health')
    add('UX','READY WITH CONDITIONS','Primary business navigation is simplified; advanced tools remain available under More tools & settings.','/today')
    add('Backup / recovery','READY' if backup['status']=='VERIFIED' else 'READY WITH CONDITIONS' if backup['status']=='NOT_CREATED' else 'NOT READY',backup['detail'],'/system-health')
    return cards


def doctor_findings(root: Path) -> list[dict]:
    """Business-readiness checks suitable for the System Doctor."""
    out=[]
    pq=product_quality();crm=crm_health();backup=backup_status(root)
    if pq['missing_cost']:out.append({'check_key':'missing_product_cost','severity':'High','object_type':'product','object_id':'','detail':f"{pq['missing_cost']} product(s) have no cost, so profitability is incomplete."})
    if pq['missing_inventory']:out.append({'check_key':'missing_product_inventory','severity':'High','object_type':'product','object_id':'','detail':f"{pq['missing_inventory']} product(s) have no canonical inventory row."})
    if crm['duplicate_email_rows'] or crm['duplicate_phone_rows']:out.append({'check_key':'crm_possible_duplicates','severity':'High','object_type':'contact','object_id':'','detail':f"Possible duplicate contact rows: email {crm['duplicate_email_rows']}, phone {crm['duplicate_phone_rows']}."})
    if backup['status'] in {'CREATED_NOT_VERIFIED','FAILED','RESTORE_FAILED'}:out.append({'check_key':'backup_readiness','severity':'High','object_type':'backup','object_id':'','detail':backup['detail']})
    if m.table_exists('v12_worker_jobs'):
        n=int((m.one("SELECT count(*) n FROM v12_worker_jobs WHERE status='DeadLetter'") or {'n':0})['n'])
        if n:out.append({'check_key':'dead_letter_jobs','severity':'Critical','object_type':'job','object_id':'','detail':f'{n} background job(s) are in DeadLetter and need recovery.'})
    # V46 doctor coverage for operational failures that previously lived only in specialist screens.
    try:
        import ai_router
        ai_router.initialise()
        if m.table_exists('v42_ai_failure_groups'):
            n=int((m.one("SELECT coalesce(sum(failure_count),0) n FROM v42_ai_failure_groups WHERE coalesce(resolved,0)=0") or {'n':0})['n'])
            if n:out.append({'check_key':'open_ai_failures','severity':'High','object_type':'ai','object_id':'','detail':f'{n} unresolved AI failure occurrence(s) are grouped in Needs Attention.'})
    except Exception as exc:
        out.append({'check_key':'ai_failure_health_check_failed','severity':'High','object_type':'ai','object_id':'','detail':'AI failure-health check could not complete: '+str(exc)[:500]})
    if m.table_exists('v10_campaign_channels'):
        n=int((m.one("SELECT count(*) n FROM v10_campaign_channels WHERE launch_status IN ('Failed','Rejected','Needs attention') OR coalesce(last_error,'')<>''") or {'n':0})['n'])
        if n:out.append({'check_key':'failed_campaign_channels','severity':'High','object_type':'campaign','object_id':'','detail':f'{n} campaign channel(s) have failed/rejected execution or an unresolved provider error.'})
    if m.table_exists('v17_processes'):
        # A process in "Needs attention" is normal owner work (for example creative
        # review) and belongs on the Needs Attention workspace, not in the integrity
        # gate. Only a genuinely Blocked process is a High Doctor finding.
        n=int((m.one("SELECT count(*) n FROM v17_processes WHERE status='Blocked'") or {'n':0})['n'])
        if n:out.append({'check_key':'blocked_business_processes','severity':'High','object_type':'process','object_id':'','detail':f'{n} canonical business process(es) are blocked and require recovery.'})
    # V53 operational-truth reconciliation checks.
    try:
        import business_os as bos
        import v24_ops
        health=bos.canonical_operational_health();home=v24_ops.daily_summary()
        if int(home.get('system_alerts') or 0)!=int(health.get('unresolved') or 0):
            out.append({'check_key':'home_system_health_mismatch','severity':'Critical','object_type':'system','object_id':'','detail':f"Home reports {home.get('system_alerts')} system alert(s) but canonical operational health reports {health.get('unresolved')}."})
        if m.table_exists('v9_recommendations'):
            dup=int((m.one("SELECT count(*) n FROM (SELECT dedupe_key,count(*) c FROM v9_recommendations WHERE status='Open' AND coalesce(dedupe_key,'')<>'' GROUP BY dedupe_key HAVING count(*)>1) x") or {'n':0})['n'])
            if dup:out.append({'check_key':'duplicate_open_recommendations','severity':'Critical','object_type':'recommendation','object_id':'','detail':f'{dup} duplicate open recommendation identity/identities exist.'})
            leak=int((m.one("SELECT count(*) n FROM v9_recommendations r JOIN products p ON (r.dedupe_key='product-ready:'||p.product_id OR r.dedupe_key='product-launch:'||p.product_id OR r.action_url='/products/'||p.product_id) WHERE r.status='Open' AND p.status='Archived'") or {'n':0})['n'])
            if leak:out.append({'check_key':'archived_product_recommendation_leak','severity':'High','object_type':'product','object_id':'','detail':f'{leak} open recommendation(s) still target archived products.'})
    except Exception as exc:
        out.append({'check_key':'operational_truth_reconciliation_failed','severity':'High','object_type':'system','object_id':'','detail':'Operational truth reconciliation could not complete: '+str(exc)[:500]})
    # V47: compatibility campaign tables must agree on lifecycle locks. A mismatch
    # could otherwise let one service treat an owner-archived/paused campaign as mutable.
    if m.table_exists('campaigns') and m.table_exists('v10_unified_campaigns'):
        n=int((m.one("""SELECT count(*) n FROM campaigns c JOIN v10_unified_campaigns u ON u.id=c.campaign_id
          WHERE (coalesce(c.status,'Draft') IN ('Archived','Paused') OR coalesce(u.status,'Draft') IN ('Archived','Paused'))
            AND coalesce(c.status,'Draft')<>coalesce(u.status,'Draft')""") or {'n':0})['n'])
        if n:out.append({'check_key':'campaign_lifecycle_divergence','severity':'High','object_type':'campaign','object_id':'','detail':f'{n} campaign(s) disagree between compatibility and unified lifecycle status. Repair before campaign execution.'})
    # V50 verified-recovery and recognized-financial checks.
    try:
        fin=v50.financial_summary()
        if fin.get('incomplete_orders'):
            out.append({'check_key':'incomplete_refund_evidence','severity':'Critical','object_type':'order','object_id':'','detail':f"{len(fin['incomplete_orders'])} Refunded order(s) have no canonical refund evidence and are excluded from recognized revenue until repaired."})
    except Exception as exc:
        out.append({'check_key':'financial_truth_check_failed','severity':'High','object_type':'reporting','object_id':'','detail':'Financial truth check could not complete: '+str(exc)[:500]})
    # V50 Wix connection/mapping truth. A saved connection is never enough.
    try:
        import json as _json
        import integration_v14 as _v14
        if m.table_exists('v10_connections'):
            wix=m.rows("SELECT id,status,config_json,label,last_error FROM v10_connections WHERE connector_key='wix'")
            app_cfg=_v14.provider_app('wix') if hasattr(_v14,'provider_app') else {}
            for c in wix:
                cfg=_json.loads(c.get('config_json') or '{}')
                if not (app_cfg.get('client_id') and _v14.provider_secret('wix','client_secret')):
                    out.append({'check_key':'wix_platform_setup','severity':'High','object_type':'integration','object_id':c['id'],'detail':'Wix connection exists but the platform Wix App ID/secret is not configured.'})
                if c.get('status')=='Connected' and not (cfg.get('instance_id') and cfg.get('signed_instance_verified')):
                    out.append({'check_key':'wix_false_connected_state','severity':'Critical','object_type':'integration','object_id':c['id'],'detail':'Wix is marked Connected without a verified Wix app instance. Reconnect Wix.'})
                if c.get('status')=='Connected' and c.get('last_error'):
                    out.append({'check_key':'wix_connection_error','severity':'High','object_type':'integration','object_id':c['id'],'detail':str(c.get('last_error'))[:800]})
            if m.table_exists('v10_external_objects'):
                checks=[('product','products','product_id'),('contact','contacts','contact_id'),('order','orders','order_id')]
                for obj,table,key in checks:
                    rows=m.rows("SELECT x.connection_id,x.external_id,x.local_id FROM v10_external_objects x JOIN v10_connections c ON c.id=x.connection_id WHERE c.connector_key='wix' AND x.object_type=? AND coalesce(x.local_id,'')<>''",(obj,))
                    for x in rows:
                        exists=m.one(f'SELECT 1 ok FROM {table} WHERE {key}=?',(x['local_id'],)) if m.table_exists(table) else None
                        if not exists:
                            out.append({'check_key':'wix_broken_'+obj+'_mapping','severity':'Critical','object_type':'integration','object_id':x['connection_id'],'detail':f"Wix {obj} {x['external_id']} maps to missing canonical {obj} {x['local_id']}."})
            auth=m.one("SELECT authority_connection_id FROM v14_data_authority WHERE entity_type='inventory' LIMIT 1") if m.table_exists('v14_data_authority') else None
            cid=str((auth or {}).get('authority_connection_id') or '')
            if cid and cid!='INTERNAL':
                c=m.one("SELECT connector_key,status FROM v10_connections WHERE id=?",(cid,))
                if c and c.get('connector_key')=='wix' and c.get('status')!='Connected':
                    out.append({'check_key':'wix_inventory_authority_unhealthy','severity':'Critical','object_type':'integration','object_id':cid,'detail':'Wix is selected as inventory authority but the selected Wix connection is not Connected.'})
    except Exception as exc:
        out.append({'check_key':'wix_doctor_check_failed','severity':'High','object_type':'integration','object_id':'','detail':'Wix Doctor checks could not complete: '+str(exc)[:500]})

    # V51 release evidence: a green-looking release must be backed by a verification
    # report for this exact release. Old/stale evidence is never treated as current.
    try:
        import json as _json
        import release_info as _ri
        evidence_path=root/'release_verification.json'
        if not evidence_path.exists():
            out.append({'check_key':'release_verification_missing','severity':'High','object_type':'release','object_id':'','detail':'No release_verification.json exists for the current release. Run verify_release.py before certifying this build.'})
        else:
            payload=_json.loads(evidence_path.read_text())
            semantic=bool(payload.get('product') or payload.get('build'))
            label=payload.get('build') if semantic else payload.get('release')
            product_ok=(not semantic) or payload.get('product')==_ri.PRODUCT_NAME
            schema_ok=(not semantic) or str(payload.get('schema') or '')==str(_ri.SCHEMA_VERSION)
            if label!=getattr(_ri,'RELEASE_VERIFICATION_LABEL',_ri.RELEASE_LABEL) or payload.get('version')!=_ri.APP_VERSION or not product_ok or not schema_ok:
                out.append({'check_key':'release_verification_stale','severity':'High','object_type':'release','object_id':'','detail':f"Verification evidence belongs to {payload.get('product') or payload.get('release') or 'unknown'} {payload.get('version') or ''} ({label or 'unknown build'}), not {_ri.PRODUCT_NAME} {_ri.APP_VERSION} ({_ri.BUILD_ID})."})
            elif semantic:
                if not payload.get('complete') or not payload.get('ok'):
                    out.append({'check_key':'release_verification_failed','severity':'Critical','object_type':'release','object_id':'','detail':'Semantic team-release verification evidence is not complete and green.'})
            else:
                expected={'core','platform','journeys','operations','owner_marketing','integrity','resilience','current'}
                present={str(x.get('group') or '') for x in payload.get('groups',[])}
                missing=sorted(expected-present)
                failed=[x.get('group') for x in payload.get('groups',[]) if not x.get('ok')]
                if missing:
                    out.append({'check_key':'release_verification_incomplete','severity':'High','object_type':'release','object_id':'','detail':'Release verification is incomplete; missing groups: '+', '.join(missing)})
                if failed or not payload.get('ok'):
                    out.append({'check_key':'release_verification_failed','severity':'Critical','object_type':'release','object_id':'','detail':'Release verification has failing groups: '+(', '.join(x for x in failed if x) or 'unknown')[:500]})
    except Exception as exc:
        out.append({'check_key':'release_verification_unreadable','severity':'High','object_type':'release','object_id':'','detail':'Release verification evidence could not be read: '+str(exc)[:500]})
    return out
