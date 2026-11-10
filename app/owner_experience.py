from __future__ import annotations

"""V18 owner-first business experience helpers.

This layer intentionally translates the underlying CRM/integration/automation machinery
into business-language decisions. It does not weaken provider validation or bypass
consent/approval gates.
"""

import json
from typing import Any

import marketing as m
import db_layer
import integration_layer as il
import integration_v14 as v14
import operating_core as oc
import observability
import v35_truth as truth

AUTOMATION_MODES = {
    '1': {
        'name': 'Assist Me',
        'summary': 'AI recommends actions, but you approve important work before it happens.',
        'automatic': 'Analysis, suggestions and draft preparation.',
        'approval': 'Publishing, sending, paid media and important customer actions.',
    },
    '2': {
        'name': 'Work With Me',
        'summary': 'The system prepares routine work and asks before actions with business impact.',
        'automatic': 'Product QC, draft content, creative preparation and low-risk workflow preparation.',
        'approval': 'External publishing, campaigns, messages and higher-risk changes.',
    },
    '3': {
        'name': 'Automate Routine Work',
        'summary': 'Routine approved workflows run automatically; exceptions and risk stay with you.',
        'automatic': 'Configured low-risk automations, syncs, routine follow-ups and preparation tasks.',
        'approval': 'Exceptions, low-confidence AI, unusual spend and irreversible actions.',
    },
    '4': {
        'name': 'Advanced Automation',
        'summary': 'Approved rules can execute more work automatically within explicit permissions and budgets.',
        'automatic': 'Approved event-driven rules inside configured limits.',
        'approval': 'Anything outside policy, budget, consent, confidence or provider permission boundaries.',
    },
}

GOAL_PRESETS = {
    'sales': {
        'label': 'Get more sales',
        'objective': 'Drive qualified product purchases using the strongest connected sales and marketing channels.',
        'audience': 'Customers and prospects most relevant to the selected products',
        'channels': ['Website','Instagram/Facebook','Meta Ads','Google Ads','Email','WhatsApp','SEO/Blog'],
    },
    'collection': {
        'label': 'Promote a new collection',
        'objective': 'Launch the selected collection, build awareness and turn interest into qualified enquiries and purchases.',
        'audience': 'Customers and prospects likely to be interested in this collection',
        'channels': ['Website','Instagram/Facebook','Meta Ads','Google Ads','Email','WhatsApp','SEO/Blog'],
    },
    'returning': {
        'label': 'Bring customers back',
        'objective': 'Re-engage previous customers with relevant products and encourage a repeat purchase.',
        'audience': 'Previous customers who have not purchased recently',
        'channels': ['Email','WhatsApp','Instagram/Facebook'],
    },
    'whatsapp': {
        'label': 'Get more WhatsApp enquiries',
        'objective': 'Generate qualified WhatsApp enquiries for the selected products and make follow-up easy for the sales team.',
        'audience': 'Relevant prospects in the selected market who are suitable for WhatsApp follow-up',
        'channels': ['Instagram/Facebook','Meta Ads','Google Ads','WhatsApp'],
    },
    'showroom': {
        'label': 'Increase showroom visits',
        'objective': 'Increase qualified visits and appointments for the selected showroom or location.',
        'audience': 'Relevant customers and prospects within practical travelling distance',
        'channels': ['Google Ads','Instagram/Facebook','Meta Ads','Email','WhatsApp'],
    },
    'clear_stock': {
        'label': 'Clear excess stock',
        'objective': 'Move selected excess inventory efficiently without losing control of price, margin or customer permissions.',
        'audience': 'Customers and prospects relevant to the selected products and offer',
        'channels': ['Website','Email','WhatsApp','Instagram/Facebook','Meta Ads'],
    },
}

def initialise() -> None:
    # Owner routes can be opened before the full app bootstrap (tests/recovery).
    # Initialise support tables idempotently so business-facing pages fail safe.
    il.initialise();v14.initialise();oc.initialise()


OWNER_GROUPS = [
    ('Sell', ['shopify','woocommerce','wix']),
    ('Market', ['meta_business']),
    ('Communicate', ['whatsapp_cloud','microsoft_mailbox','resend','sms']),
    ('Measure', ['google_account']),
    ('Operate', ['stripe','shipping','accounting','razorpay','paypal']),
]


def _table(name: str) -> bool:
    try:
        return m.table_exists(name)
    except Exception:
        return False


def _setting(key: str, default: str='') -> str:
    try:
        row=m.one('SELECT setting_value FROM settings WHERE setting_key=?',(key,))
        return str((row or {}).get('setting_value') or default)
    except Exception:
        return default


def automation_mode() -> dict:
    initialise()
    key=_setting('v13_default_automation_level','2')
    if key not in AUTOMATION_MODES:key='2'
    return {'key':key, **AUTOMATION_MODES[key]}


def automation_readiness() -> dict:
    """Explain the difference between the selected policy and what can execute today."""
    initialise();mode=automation_mode();level=int(mode['key'])
    try:rules=int((m.one("SELECT count(*) n FROM v13_automation_rules WHERE enabled=1") or {'n':0})['n']) if _table('v13_automation_rules') else 0
    except Exception:rules=0
    try:connected=sum(1 for c in il.connections() if str(c.get('status') or '')=='Connected')
    except Exception:connected=0
    try:ai=m.ai_health()
    except Exception:ai={'status':'Unknown','detail':'AI readiness could not be checked.'}
    blockers=[]
    if level>=2 and ai.get('status')!='Connected':blockers.append('AI-assisted work is limited until the AI connection is healthy.')
    if level>=3 and rules==0:blockers.append('No enabled event automation rules are configured yet.')
    if level>=3 and connected==0:blockers.append('No external business account is connected, so provider actions cannot execute.')
    if level==1:effective='Recommendations and drafts only'
    elif level==2:effective='Local preparation with approval gates'
    elif rules and connected:effective='Configured rules can run within connected-provider limits'
    elif rules:effective='Local configured rules can run; external actions remain blocked'
    else:effective='Preparation only until rules/providers are configured'
    return {'selected':mode,'effective':effective,'enabled_rules':rules,'connected_accounts':connected,'ai_status':ai.get('status') or 'Unknown','ai_detail':ai.get('detail') or '', 'blockers':blockers}


def set_automation_mode(key: str) -> dict:
    initialise()
    key=str(key or '')
    if key not in AUTOMATION_MODES:raise ValueError('Choose one of the four automation levels shown on this page.')
    oc.save_settings({'automation_level':key})
    try:
        import platform_core as pc
        pc.set_sec('automation_mode',{'1':'Manual','2':'Assisted','3':'Automated','4':'Automated'}[key])
    except Exception:
        pass
    return automation_mode()


def email_setup_progress() -> dict:
    initialise()
    conns=[c for c in il.connections('resend') if c.get('status')=='Connected']
    if not conns:
        return {'status':'Needs setup','percent':0,'detail':'Connect the marketing-email provider, then verify your sending domain.'}
    c=conns[0]
    domains=m.rows("SELECT payload_json FROM v10_external_objects WHERE connection_id=? AND object_type='email_domain'",(c['id'],))
    verified=False;dns_attention=False
    for row in domains:
        try: payload=json.loads(row.get('payload_json') or '{}')
        except Exception: payload={}
        status=str(payload.get('status') or '').lower()
        if status in {'verified','active'}:verified=True
        records=payload.get('records') or []
        if records and not verified:dns_attention=True
    webhook=bool(m.one("SELECT 1 ok FROM v10_external_objects WHERE connection_id=? AND object_type='resend_webhook' LIMIT 1",(c['id'],)))
    if verified and webhook:return {'status':'Complete','percent':100,'detail':'Sending domain is verified and delivery-event webhook is registered.'}
    if verified:return {'status':'In progress','percent':85,'detail':'Sending domain is verified. Register the delivery-event webhook so bounces and delivery events return to the CRM.'}
    if domains:return {'status':'In progress','percent':60,'detail':'Email provider is connected, but the sending domain still needs DNS verification'+(' (DKIM/SPF records require attention).' if dns_attention else '.') }
    return {'status':'In progress','percent':35,'detail':'Email provider is connected. Add and verify the business sending domain next.'}


def owner_setup_steps() -> list[dict[str,Any]]:
    initialise()
    """A short, resumable business setup path based on real evidence."""
    raw=v14.setup_status()
    by={x['label']:x for x in raw}
    email=email_setup_progress()
    by['Marketing email']={'label':'Marketing email','status':email['status'],'detail':email['detail'],'url':'/integrations'}
    def take(label, title=None, why=''):
        x=dict(by.get(label) or {'status':'Needs setup','detail':'This setup step has not been completed.','url':'/setup'})
        return {'key':label.lower().replace(' ','_').replace('/','_'), 'title':title or label, 'status':x['status'], 'detail':x['detail'], 'url':x['url'], 'why':why}
    return [
        take('Business profile','Tell us about your business','Used for branding, currency, language and sensible defaults.'),
        take('Store','Connect your store','Lets products, customers, orders and inventory work with the CRM.'),
        take('Meta / Instagram / Facebook','Connect Facebook & Instagram','Lets the platform publish supported content, read performance and prepare Meta advertising.'),
        take('Google','Connect Google','One login can enable the Google services you actually use.'),
        take('WhatsApp Business','Connect WhatsApp','Lets opted-in conversations and approved messaging feed the CRM.'),
        take('Marketing email','Set up email','Lets reviewed campaigns send from a verified business domain.'),
        take('Customers','Bring in customers','Imports/syncs customer records so campaigns and follow-up use one CRM.'),
        take('Products','Upload your first products','Starts the AI product, creative and campaign preparation workflow.'),
        take('First connected campaign','Create your first campaign','Turns a business goal into a channel-ready campaign workspace.'),
    ]


def setup_progress() -> dict:
    initialise()
    steps=owner_setup_steps();complete=sum(1 for x in steps if x['status']=='Complete')
    next_step=next((x for x in steps if x['status'] not in {'Complete','Optional'}),None)
    return {'steps':steps,'complete':complete,'total':len(steps),'percent':round((complete/len(steps))*100) if steps else 100,'next':next_step}


def integration_groups() -> list[dict[str,Any]]:
    initialise()
    catalog=v14.business_catalog();connections=il.connections();bykey={}
    for c in connections:bykey.setdefault(c['connector_key'],[]).append(c)
    out=[]
    for group,keys in OWNER_GROUPS:
        cards=[]
        for key in keys:
            meta=catalog.get(key)
            if not meta:continue
            rows=bykey.get(key,[]);connected=[c for c in rows if c.get('status')=='Connected']
            c=connected[0] if connected else (rows[0] if rows else None)
            if c:
                health=v14.connection_health(c['id'],persist=False)
                if c.get('status')=='Connected' and health['healthy']:status='Connected'
                elif c.get('status')=='Connected':status='Needs attention'
                else:status=c.get('status') or 'Needs setup'
                account=c.get('account_name') or c.get('label') or ''
                last=c.get('last_sync_at') or c.get('last_success_at') or ''
                action='/integrations/v14/'+c['id'] if key in catalog and key in v14.V14_BUSINESS_CONNECTORS else '/integrations/'+c['id']
                if key=='resend':
                    ep=email_setup_progress()
                    status='Connected' if ep['status']=='Complete' else 'Needs attention'
                    meta=dict(meta);meta['help']=ep['detail']+f" Email setup: {ep['percent']}% complete."
            elif not meta.get('implemented'):
                status='Planning only';account='';last='';action=''
            elif meta.get('login_first'):
                prov=v14.provider_app(meta['provider_key'])
                status='Ready to connect' if prov.get('configured') else 'Setup Required'
                account='';last='';action='/integrations/v14/connect/'+key if prov.get('configured') else '/developer/integrations/'+meta['provider_key']
            else:
                status='Advanced setup';account='';last='';action='/developer/integrations'
            cards.append({'key':key,'label':meta['label'],'status':status,'account':account,'last_activity':last,'action_url':action,'implemented':bool(meta.get('implemented')),'login_first':bool(meta.get('login_first')),'help':meta.get('help','')})
        if cards:out.append({'group':group,'cards':cards})
    return out


def channel_statuses() -> list[dict]:
    initialise()
    channels=['Website','Instagram/Facebook','Meta Ads','Google Ads','Email','WhatsApp','SEO/Blog']
    out=[]
    for ch in channels:
        if ch=='SEO/Blog':
            # The packaged OS can always prepare local SEO/blog drafts.  A CMS or
            # website connection is required only for external publication.  Do not
            # confuse lazy table initialisation with channel readiness.
            out.append({'channel':ch,'status':'Ready for drafting','reason':'Local SEO/blog drafting and review are available; external publication still depends on the connected website/CMS path.','ready':True})
            continue
        r=v14.channel_readiness(ch)
        ready=r.get('status') in {'Connected','Ready'}
        out.append({'channel':ch,'status':'Ready' if ready else r.get('status','Needs setup'),'reason':r.get('reason',''),'ready':ready})
    return out


def recommended_channels(goal_key: str) -> list[dict]:
    initialise()
    preset=GOAL_PRESETS.get(goal_key) or GOAL_PRESETS['sales']
    statuses={x['channel']:x for x in channel_statuses()}
    result=[]
    for ch in preset['channels']:
        s=statuses.get(ch) or {'channel':ch,'status':'Unsupported / planned','reason':'This channel is not available yet.','ready':False}
        result.append({**s,'recommended':True,'selected':bool(s['ready'])})
    return result




def currency_for_region(region: str, fallback: str = 'GBP') -> str:
    """Return a sensible campaign currency from the owner's market text.

    This is only a UI default; the owner can still override it.
    """
    r=(region or '').strip().lower()
    if any(x in r for x in ['united kingdom','uk','england','scotland','wales','london']): return 'GBP'
    if any(x in r for x in ['india','delhi','mumbai','varanasi','benaras','banaras']): return 'INR'
    if any(x in r for x in ['united states','usa','u.s.','new york','california']): return 'USD'
    if any(x in r for x in ['france','germany','italy','spain','ireland','netherlands','belgium','europe']): return 'EUR'
    return fallback if fallback in {'GBP','EUR','USD','INR'} else 'GBP'

def campaign_defaults(goal_key: str) -> dict:
    initialise()
    preset=GOAL_PRESETS.get(goal_key) or GOAL_PRESETS['sales']
    st=m.settings();region=_setting('v13_default_market',str(st.get('default_country') or 'United Kingdom'))
    language=_setting('v13_default_language',str(st.get('default_language') or 'English'))
    currency=currency_for_region(region,str(st.get('default_currency') or 'GBP'))
    return {'goal_key':goal_key if goal_key in GOAL_PRESETS else 'sales','goal':preset['label'],'objective':preset['objective'],'audience':preset['audience'],'region':region,'language':language,'currency':currency,'channels':recommended_channels(goal_key)}


def create_business_campaign(data: dict) -> str:
    initialise()
    goal_key=str(data.get('goal_key') or 'sales')
    preset=GOAL_PRESETS.get(goal_key)
    if not preset:raise ValueError('Choose a business goal from the options shown.')
    product_ids=list(data.get('product_ids') or [])
    if not product_ids:raise ValueError('Choose at least one product so the campaign has something real to promote.')
    channels=list(data.get('channels') or [])
    if not channels:raise ValueError('Choose at least one ready channel. Recommended connected channels are selected for you by default.')
    name=str(data.get('name') or '').strip() or preset['label']
    region=str(data.get('region') or campaign_defaults(goal_key)['region']).strip()
    language=str(data.get('language') or campaign_defaults(goal_key)['language']).strip()
    audience=str(data.get('audience_query') or preset['audience']).strip()
    objective=str(data.get('objective') or preset['objective']).strip()
    raw={
        'name':name,'objective':objective,'audience_query':audience,'region':region,'language':language,
        'budget':data.get('budget') or '', 'currency':data.get('currency') or m.settings().get('default_currency','GBP'),
        'channels':channels,'product_ids':product_ids,
        'idempotency_key':str(data.get('idempotency_key') or '').strip(),
    }
    return il.create_unified_campaign(raw)


def auto_select_unambiguous_resources(connection_id: str) -> dict:
    initialise()
    return v14.auto_select_unambiguous_resources(connection_id)


def beginner_e2e() -> dict:
    initialise()
    """Twenty-step non-technical owner scenario using evidence, not UI presence."""
    steps=[]
    def add(no,label,status,detail,url=''):
        steps.append({'no':no,'label':label,'status':status,'detail':detail,'url':url})
    setup={x['title']:x for x in owner_setup_steps()}
    def conn(ch):
        try:return v14.channel_readiness(ch)
        except Exception:return {'status':'Not connected','reason':'Connection status unavailable.'}
    product_count=int((m.one('SELECT count(*) n FROM products') or {'n':0})['n']) if _table('products') else 0
    image_count=int((m.one('SELECT count(*) n FROM product_images') or {'n':0})['n']) if _table('product_images') else 0
    ai_key=bool(m.secret())
    add(1,'Create/configure business','Working' if setup['Tell us about your business']['status']=='Complete' else 'Needs setup',setup['Tell us about your business']['detail'],'/settings')
    r=conn('Website');add(2,'Connect store by login','Working' if r['status']=='Connected' else 'Needs setup',r['reason'],'/integrations')
    meta=next((c for c in il.connections('meta_business') if c.get('status')=='Connected'),None);add(3,'Connect Meta by login','Working' if meta else 'Needs setup','Meta login is provider-validated when Connected; resource choices are auto-selected only when unambiguous.','/integrations')
    google=next((c for c in il.connections('google_account') if c.get('status')=='Connected'),None);add(4,'Connect Google by login','Working' if google else 'Needs setup','One Google login can authorize the selected business services.','/integrations')
    mail=next((c for c in il.connections('microsoft_mailbox') if c.get('status')=='Connected'),None) or (google if google and 'gmail' in ((google.get('config') or {}).get('services') or []) else None);add(5,'Connect business mailbox','Working' if mail else 'Needs setup','Gmail or Microsoft 365 can provide the business mailbox connection.','/integrations')
    wa=conn('WhatsApp');add(6,'Connect WhatsApp','Working' if wa['status']=='Connected' else 'Needs setup',wa['reason'],'/integrations')
    add(7,'Upload raw saree images','Working' if image_count else 'Needs setup',f'{image_count} source image(s) are stored.','/product-workspace')
    add(8,'AI creates/prepares product','Partial' if product_count else 'Needs setup',f'{product_count} product record(s) exist. Product understanding can use AI when configured, but high-risk product facts still require review.','/product-workspace')
    add(9,'Review generated imagery','Partial' if _table('v7_creative_jobs') else 'Not implemented','Creative jobs and fidelity review exist; provider-backed generation still depends on configured AI services.','/creative')
    add(10,'Review videos','Partial' if _table('v8_video_jobs') else 'Not implemented','Local/storyboard video workflow exists; full generative video remains provider-gated.','/creative-studio')
    add(11,'Publish products','Partial' if r['status']=='Connected' else 'Needs setup','Reviewed Shopify draft publishing exists; full commerce lifecycle remains incomplete.','/integrations')
    add(12,'Ask AI to promote products','Working' if _table('v10_unified_campaigns') else 'Broken','Business-goal campaign builder is available; AI strategy generation requires AI configuration.','/campaign-builder')
    add(13,'Review suggested campaign','Working','V18 starts from a business goal, recommends ready channels and keeps advanced platform settings optional.','/campaign-builder')
    add(14,'Approve campaign actions','Working' if _table('v11_approvals') else 'Broken','Approval infrastructure exists for higher-risk external actions.','/approvals')
    ready=[x for x in channel_statuses() if x['ready'] and x['channel']!='SEO/Blog'];add(15,'Use connected channels','Partial' if ready else 'Needs setup',f'{len(ready)} external channel(s) are currently business-ready.','/integrations')
    add(16,'Receive leads automatically','Partial','Inbound connectors can create/update CRM activity where implemented; complete website/lead-form coverage still depends on live providers and webhooks.','/contacts')
    add(17,'See leads in CRM','Working' if _table('contacts') else 'Broken','Contacts, activities, opportunities and order links are stored centrally.','/contacts')
    add(18,'Receive follow-up recommendations','Working' if _table('v9_recommendations') else 'Partial','Action Centre and owner attention signals can surface recorded follow-up opportunities.','/')
    add(19,'Record sales automatically','Partial' if _table('orders') else 'Broken','Orders can sync from implemented commerce connectors, but shipping/returns/payment mutation are not yet complete.','/orders')
    add(20,'See performance in one dashboard','Partial' if _table('v10_channel_metrics') else 'Broken','Provider metrics, CRM activity and order data exist; deeper profitability and cross-device attribution remain incomplete.','/marketing-performance')
    rank={'Working':0,'Partial':1,'Needs setup':2,'Not implemented':3,'Broken':4}
    worst=max((rank.get(x['status'],4) for x in steps),default=4)
    overall=next(k for k,v in rank.items() if v==worst)
    return {'status':overall,'steps':steps,'counts':{k:sum(1 for x in steps if x['status']==k) for k in rank}}


def attention_summary() -> list[dict]:
    initialise()
    """Surface business attention items from recorded facts only."""
    items=[];check_errors=[]
    def failed(check,exc):
        check_errors.append(check)
        observability.log('owner_attention.check_failed',check=check,error=str(exc))
    try:
        truth.refresh_sales_priorities()
        if _table('v35_sales_priority'):
            n=int((m.one("SELECT count(*) n FROM v35_sales_priority sp JOIN contacts c ON c.contact_id=sp.contact_id WHERE sp.priority_score>=60 AND coalesce(c.lifecycle_stage,'') NOT IN ('Purchased','Lost','Customer')") or {'n':0})['n'])
            if n:items.append({'priority':'High','title':f'{n} high-priority lead(s) need follow-up','detail':'Priority uses fit, recent buying intent and urgency; open each contact to see why action is needed now.','url':'/contacts?sort=priority'})
        else:
            n=int((m.one("SELECT count(*) n FROM contacts WHERE coalesce(lead_score,0)>=70 AND coalesce(lifecycle_stage,'') NOT IN ('Purchased','Lost','Customer')") or {'n':0})['n'])
            if n:items.append({'priority':'High','title':f'{n} high-priority lead(s) need follow-up','detail':'These contacts have a recorded lead score of 70 or more and are not marked purchased/lost.','url':'/contacts?sort=priority'})
    except Exception as exc:failed('lead follow-up',exc)
    try:
        if _table('v11_approvals'):
            n=int((m.one("SELECT count(*) n FROM v11_approvals WHERE status='Pending'") or {'n':0})['n'])
            if n:items.append({'priority':'High','title':f'{n} approval(s) are waiting','detail':'The system is intentionally waiting for a human decision before higher-risk work continues.','url':'/approvals'})
    except Exception as exc:failed('approvals',exc)
    try:
        bad=[c for c in il.connections() if c.get('status') not in {'Connected','Available to connect'}]
        if bad:items.append({'priority':'High','title':f'{len(bad)} connection(s) need attention','detail':'Reconnect or finish setup so automations can use the affected channels.','url':'/integration-health'})
    except Exception as exc:failed('connections',exc)
    try:
        if _table('v13_incidents'):
            n=int((m.one("SELECT count(*) n FROM v13_incidents WHERE status='Open'") or {'n':0})['n'])
            if n:items.append({'priority':'Medium','title':f'{n} automation exception(s) need review','detail':'Routine work stopped safely and needs a decision or retry.','url':'/control-centre'})
    except Exception as exc:failed('automation incidents',exc)
    try:
        # A conservative repeat-purchase signal: at least one order, no purchase in 90 days.
        if _table('orders'):
            n=int((m.one("""SELECT count(*) n FROM (SELECT contact_id,max(date(coalesce(ordered_at,''))) last_order FROM orders WHERE contact_id IS NOT NULL AND contact_id<>'' GROUP BY contact_id HAVING last_order<>'' AND last_order<=date('now','-90 days')) x""") or {'n':0})['n'])
            if n:items.append({'priority':'Opportunity','title':f'{n} past customer(s) may be ready for re-engagement','detail':'Their last recorded order was at least 90 days ago. Review relevance and consent before outreach.','url':'/campaign-builder?goal=returning'})
    except Exception as exc:failed('repeat-purchase opportunity',exc)
    if check_errors:
        items.insert(0,{'priority':'High','title':'Some owner checks could not be verified','detail':'Open System health before assuming there is nothing to do. Failed checks: '+', '.join(sorted(set(check_errors)))+'.','url':'/system-health'})
    if not items:
        items.append({'priority':'Good','title':'No urgent owner actions found','detail':'The system checked recorded approvals, connections and follow-ups and found nothing requiring immediate attention.','url':'/control-centre'})
    return items[:8]


def system_activity() -> list[dict]:
    initialise()
    rows=[]
    try:
        if _table('v12_worker_jobs'):
            q=m.rows("SELECT job_type,status,created_at FROM v12_worker_jobs WHERE status IN ('Queued','Retry','Running') ORDER BY created_at DESC LIMIT 8")
            rows.extend({'label':str(x.get('job_type') or 'Background job'),'status':x.get('status') or 'Queued','time':x.get('created_at') or ''} for x in q)
    except Exception:pass
    try:
        if _table('v13_events'):
            q=m.rows("SELECT event_type,status,occurred_at FROM v13_events WHERE status IN ('Pending','Retry') ORDER BY occurred_at DESC LIMIT 8")
            rows.extend({'label':str(x.get('event_type') or 'Business event'),'status':x.get('status') or 'Pending','time':x.get('occurred_at') or ''} for x in q)
    except Exception:pass
    return rows[:8]
