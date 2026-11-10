from __future__ import annotations

import datetime as dt
import json
from typing import Any

import marketing as m
import db_layer
import v50_reliability as v50
import integration_layer as il
import owner_experience as ox

CTA_GOALS = {
    'buy_online': ('Buy online', 'Shop now'),
    'message_us': ('Message us', 'Message us'),
    'visit_showroom': ('Visit showroom', 'Visit showroom'),
    'book_call': ('Book video call', 'Book a call'),
    'view_collection': ('View collection', 'View collection'),
}

JOURNEY_PRESETS = [
    {
        'key':'welcome','title':'Welcome new leads','trigger':'A new lead enters the CRM','outcome':'Introduce the brand, relevant products and a clear next step.','goal':'sales',
        'audience':'New leads who have not purchased yet','action':'/campaign-builder?goal=sales&journey=welcome'
    },
    {
        'key':'cart','title':'Recover abandoned carts','trigger':'A connected store reports an abandoned cart','outcome':'Prepare a reminder and optional follow-up without inventing an offer.','goal':'sales',
        'audience':'Customers with a verified abandoned-cart event','action':'/integrations'
    },
    {
        'key':'post_purchase','title':'Post-purchase care','trigger':'An order is completed','outcome':'Prepare thank-you, care, review and relevant cross-sell follow-up.','goal':'returning',
        'audience':'Customers with a verified completed purchase','action':'/operations/retention'
    },
    {
        'key':'winback','title':'Win back inactive customers','trigger':'A previous customer has not purchased recently','outcome':'Recommend relevant products and prepare a reviewed re-engagement campaign.','goal':'returning',
        'audience':'Previous customers with no recent recorded purchase','action':'/campaign-builder?goal=returning&journey=winback'
    },
    {
        'key':'vip','title':'Reward high-value customers','trigger':'Customer value meets your reviewed VIP rule','outcome':'Prepare early-access or personalised outreach for review.','goal':'returning',
        'audience':'High-value customers based on recorded order history','action':'/audience-builder?q=customers%20with%20average%20order%20value%20over%20500'
    },
]


def _columns(table: str) -> set[str]:
    if not m.table_exists(table):
        return set()
    with m.connect() as con:
        return {str(r['name']) for r in con.execute('PRAGMA table_info('+table+')').fetchall()}


def initialise() -> None:
    il.initialise()
    cols=_columns('v10_unified_campaigns')
    wanted={
        'cta_goal':"TEXT DEFAULT 'view_collection'",
        'start_date':'TEXT',
        'end_date':'TEXT',
        'owner_note':"TEXT DEFAULT ''",
    }
    with m.connect() as con:
        for col,ddl in wanted.items():
            if col not in cols:
                con.execute('ALTER TABLE v10_unified_campaigns ADD COLUMN '+col+' '+ddl)
    sync_legacy_campaigns()


def _normalise_legacy_channel(value: str) -> str:
    raw=str(value or '').strip().lower()
    mapping={
        'email':'Email','whatsapp':'WhatsApp','whats app':'WhatsApp',
        'instagram':'Instagram/Facebook','facebook':'Instagram/Facebook','instagram/facebook':'Instagram/Facebook',
        'meta ads':'Meta Ads','facebook ads':'Meta Ads','google ads':'Google Ads',
        'website':'Website','web':'Website','pinterest':'Pinterest','seo':'SEO/Blog','blog':'SEO/Blog','seo/blog':'SEO/Blog',
    }
    return mapping.get(raw,'')


def sync_legacy_campaigns() -> int:
    """Mirror historical campaign-studio records into the unified campaign index.

    V31 still exposed two campaign stores: Home counted ``campaigns`` while the
    owner campaign builder/calendar read ``v10_unified_campaigns``. That made the
    UI show draft campaigns that did not exist on the calendar. V32 keeps the
    legacy tables intact for their audience/draft history, but creates one
    idempotent unified index row for every historical campaign so owner-facing
    counts, lists and calendars use a single source of truth.
    """
    if not m.table_exists('campaigns') or not m.table_exists('v10_unified_campaigns'):
        return 0
    extra={}
    if m.table_exists('m4_campaigns'):
        for r in m.rows('SELECT campaign_id,goal,brief,product_ids_json FROM m4_campaigns'):
            extra[str(r['campaign_id'])]=r
    imported=0
    rows=m.rows("SELECT campaign_id,campaign_name,audience_type,channel,status,created_at FROM campaigns ORDER BY created_at")
    for r in rows:
        cid=str(r.get('campaign_id') or '')
        if not cid or m.one('SELECT 1 ok FROM v10_unified_campaigns WHERE id=?',(cid,)):
            continue
        meta=extra.get(cid,{})
        try:
            product_ids=json.loads(meta.get('product_ids_json') or '[]')
            if not isinstance(product_ids,list):product_ids=[]
        except Exception:
            product_ids=[]
        channel=_normalise_legacy_channel(r.get('channel') or '')
        channels=[channel] if channel else []
        objective=str(meta.get('goal') or meta.get('brief') or 'Historical campaign plan').strip()[:2000] or 'Historical campaign plan'
        audience=str(r.get('audience_type') or '').strip()
        audience_query=(audience+' audience imported from the earlier campaign studio').strip()[:2000]
        status=str(r.get('status') or 'Draft').strip() or 'Draft'
        created=str(r.get('created_at') or '') or None
        note='Imported from the earlier campaign studio. Existing audience membership, drafts and history remain preserved in the legacy campaign records.'
        with m.connect() as con:
            con.execute('''INSERT OR IGNORE INTO v10_unified_campaigns(id,name,objective,audience_query,product_ids_json,channels_json,region,language,budget,currency,status,owner_note,created_at,updated_at)
                           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,coalesce(?,CURRENT_TIMESTAMP),coalesce(?,CURRENT_TIMESTAMP))''',
                        (cid,str(r.get('campaign_name') or 'Historical campaign')[:180],objective,audience_query,json.dumps(product_ids),json.dumps(channels),'',str(m.settings().get('default_language') or 'English')[:80],None,str(m.settings().get('default_currency') or 'INR'),status,note,created,created))
        if channel:
            ready=il.channel_readiness(channel)
            conn=(ready.get('connection') or {}).get('id')
            with m.connect() as con:
                con.execute('INSERT OR IGNORE INTO v10_campaign_channels(id,campaign_id,channel,connection_id,readiness) VALUES(?,?,?,?,?)',(il.uid('UCH'),cid,channel,conn,ready.get('status') or 'Not connected'))
        imported+=1
    if imported:
        m.audit('campaign.unified_index', '', f'{imported} historical campaign(s) added to the unified campaign index; legacy records preserved.')
    return imported


def _date(value: str, label: str, required: bool=False) -> str:
    value=str(value or '').strip()
    if not value:
        if required:
            raise ValueError('Choose '+label.lower()+'.')
        return ''
    try:
        return dt.date.fromisoformat(value).isoformat()
    except ValueError:
        raise ValueError('Choose a valid '+label.lower()+'.') from None


def save_campaign_context(cid: str, data: dict[str,Any]) -> None:
    initialise()
    if not m.one('SELECT 1 ok FROM v10_unified_campaigns WHERE id=?',(cid,)):
        raise ValueError('Campaign not found.')
    cta=str(data.get('cta_goal') or 'view_collection').strip()
    if cta not in CTA_GOALS:
        raise ValueError('Choose what you want customers to do from the options shown.')
    start=_date(str(data.get('start_date') or ''),'Start date')
    end=_date(str(data.get('end_date') or ''),'End date')
    if start and end and end < start:
        raise ValueError('End date cannot be earlier than the start date.')
    note=str(data.get('owner_note') or '').strip()[:1000]
    with m.connect() as con:
        con.execute('UPDATE v10_unified_campaigns SET cta_goal=?,start_date=?,end_date=?,owner_note=?,updated_at=CURRENT_TIMESTAMP WHERE id=?',
                    (cta,start or None,end or None,note,cid))
    m.audit('campaign.business_context',cid,'Business CTA and campaign timing updated.')


def create_owner_campaign(data: dict[str,Any]) -> str:
    initialise()
    cid=ox.create_business_campaign(data)
    save_campaign_context(cid,data)
    return cid


def channel_pack(cid: str) -> list[dict[str,Any]]:
    """Return channel-specific, product-grounded draft directions.

    This is a local preparation layer. It does not claim a provider has published
    anything and never invents discounts, stock urgency or unsupported claims.
    """
    initialise();c=il.campaign(cid)
    goal=CTA_GOALS.get(str(c.get('cta_goal') or 'view_collection'),CTA_GOALS['view_collection'])
    product_names=[]
    for pid in c.get('product_ids') or []:
        row=m.one("SELECT public_product_name,status FROM products WHERE product_id=?",(pid,))
        if row and row.get('status')!='Archived':
            product_names.append(str(row.get('public_product_name') or '').strip())
    products=', '.join([x for x in product_names if x][:3]) or 'the selected collection'
    objective=str(c.get('objective') or '').strip()
    region=str(c.get('region') or '').strip()
    cta=goal[1]
    packs=[]
    for ch in c.get('channels') or []:
        if ch=='Instagram/Facebook':
            draft=f'{products}. {objective} {cta}.'.strip()
            fields={'Suggested format':'Feed post + Story/Reel adaptation','Caption draft':draft,'CTA':cta}
        elif ch=='Meta Ads':
            fields={'Primary text':f'Discover {products}. {objective}'.strip(),'Headline':cta,'CTA':cta,'Format':'Image/video variants for review'}
        elif ch=='Google Ads':
            fields={'Headline 1':str(products)[:30],'Headline 2':cta[:30],'Description':objective[:90] or ('Explore '+products)[:90],'Landing action':cta}
        elif ch=='Email':
            fields={'Subject':('Explore '+products)[:80],'Preview text':objective[:120],'Body direction':f'Introduce {products}, explain why it is relevant, then invite the reader to {cta.lower()}.','CTA':cta}
        elif ch=='WhatsApp':
            fields={'Message draft':f'Hello {{first_name}}, here is {products}. {objective} {cta}.'.strip(),'CTA':cta,'Eligibility':'Send only with documented WhatsApp eligibility/approved template where required'}
        elif ch=='Website':
            fields={'Hero/collection message':objective or ('Explore '+products),'Primary CTA':cta,'Destination':'Connected product/collection page'}
        elif ch=='SEO/Blog':
            fields={'Content topic':f'{products} for {region}' if region else products,'Search intent':'Product/collection discovery','CTA':cta,'Next step':'Create reviewed SEO article or collection content'}
        elif ch=='Pinterest':
            fields={'Pin title':str(products)[:100],'Description':(objective+' '+cta).strip()[:500],'Destination':'Product or collection page'}
        else:
            fields={'Draft direction':objective,'CTA':cta}
        packs.append({'channel':ch,'fields':fields})
    return packs




def _dedupe_recommendations(rows: list[dict[str,Any]]) -> list[dict[str,Any]]:
    """Collapse semantically identical open recommendations for owner views.

    Older releases could leave several open rows for the same product action under
    different historical dedupe keys. The audit trail stays intact; this function
    only prevents the owner from seeing the same action repeatedly.
    """
    out=[];seen=set()
    for row in rows:
        title=' '.join(str(row.get('title') or '').lower().split())
        reason=' '.join(str(row.get('reason') or row.get('detail') or '').lower().split())
        action=str(row.get('action_url') or '').strip().lower()
        key=(title,reason,action)
        if key in seen:continue
        seen.add(key);out.append(row)
    return out

def overview(days: int=30) -> dict[str,Any]:
    initialise();days=max(1,min(int(days),365));since=(dt.date.today()-dt.timedelta(days=days)).isoformat()
    def count(sql,args=()):
        return int((m.one(sql,args) or {'n':0}).get('n') or 0)
    campaigns=count("SELECT count(*) n FROM v10_unified_campaigns WHERE coalesce(status,'Draft')<>'Archived'")
    scheduled=count("SELECT count(*) n FROM v10_unified_campaigns WHERE start_date IS NOT NULL AND start_date<>'' AND coalesce(status,'Draft')<>'Archived'")
    leads=count("SELECT count(*) n FROM contacts WHERE date(created_at)>=date(?)",(since,))
    crm_total=count("SELECT count(*) n FROM contacts")
    fin=v50.financial_summary(since,dt.date.today().isoformat())
    orders=int(fin['recorded_orders'])
    order_revenue_by_currency={str(r['currency']):float(r['net_revenue'] or 0) for r in fin['currency_breakdown']}
    revenue=(next(iter(order_revenue_by_currency.values())) if len(order_revenue_by_currency)==1 else None)
    perf=il.performance_summary(days)
    spend_by_currency={}
    provider_revenue_by_currency={}
    for x in perf.get('rows') or []:
        cur=str(x.get('currency') or 'Unspecified')
        spend_by_currency[cur]=spend_by_currency.get(cur,0.0)+float(x.get('spend') or 0)
        provider_revenue_by_currency[cur]=provider_revenue_by_currency.get(cur,0.0)+float(x.get('revenue') or 0)
    spend=(next(iter(spend_by_currency.values())) if len(spend_by_currency)==1 else None)
    provider_revenue=(next(iter(provider_revenue_by_currency.values())) if len(provider_revenue_by_currency)==1 else None)
    conversions=sum(float(x.get('conversions') or 0) for x in perf.get('rows') or [])
    readiness=ox.channel_statuses() + [
        {'channel':'Google Shopping','status':'Partial capability','reason':'Merchant Center account discovery and product reads exist through the Google connection; feed writes, diagnostics remediation and Shopping launch are not complete.','ready':False},
        {'channel':'YouTube','status':'Planning only','reason':'YouTube channel discovery exists through Google. Production video publishing and YouTube advertising execution are not implemented yet.','ready':False},
        {'channel':'Pinterest','status':'Planning only','reason':'Pinterest-specific content can be prepared/exported, but provider publishing is not connected yet.','ready':False},
    ]
    recs=[]
    if m.table_exists('v9_recommendations'):
        recs=_dedupe_recommendations(m.rows("SELECT * FROM v9_recommendations WHERE status='Open' AND kind IN ('Growth','Retention','Inventory','Product') ORDER BY CASE priority WHEN 'High' THEN 0 WHEN 'Medium' THEN 1 ELSE 2 END,created_at DESC LIMIT 50"))[:8]
    if not recs:
        for x in perf.get('recommendations') or []:
            recs.append({'title':x['channel']+' needs review' if x.get('severity')=='Review' else x['channel']+' opportunity','reason':x.get('message',''),'action_url':'/marketing-performance?days='+str(days),'priority':'High' if x.get('severity')=='Review' else 'Medium'})
    upcoming=m.rows("SELECT id,name,status,start_date,end_date,cta_goal,owner_note,created_at FROM v10_unified_campaigns WHERE coalesce(status,'Draft')<>'Archived' ORDER BY CASE WHEN start_date IS NULL OR start_date='' THEN 1 ELSE 0 END,start_date,created_at DESC LIMIT 12")
    social=m.rows("SELECT * FROM v17_social_posts ORDER BY scheduled_at DESC LIMIT 12") if m.table_exists('v17_social_posts') else []
    return {'days':days,'campaigns':campaigns,'scheduled':scheduled,'leads':leads,'crm_total':crm_total,'orders':orders,'order_revenue':revenue,'order_revenue_by_currency':order_revenue_by_currency,'mixed_order_currency':len(order_revenue_by_currency)>1,'spend':spend,'spend_by_currency':spend_by_currency,'provider_revenue':provider_revenue,'provider_revenue_by_currency':provider_revenue_by_currency,'mixed_provider_currency':len(set(spend_by_currency)|set(provider_revenue_by_currency))>1,'conversions':conversions,'readiness':readiness,'recommendations':recs,'upcoming':upcoming,'social':social,'performance':perf}


def journey_readiness() -> list[dict[str,Any]]:
    initialise();out=[]
    store=il.channel_readiness('Website')['status']=='Connected'
    email=il.channel_readiness('Email')['status']=='Connected'
    wa=il.channel_readiness('WhatsApp')['status']=='Connected'
    retention_ready=m.table_exists('v17_retention_actions')
    for item in JOURNEY_PRESETS:
        x=dict(item)
        if x['key']=='cart':
            x['status']='Needs store connection' if not store else 'Ready for verified cart events'
        elif x['key']=='post_purchase':
            x['status']='Ready for review' if retention_ready else 'Needs setup'
        else:
            x['status']='Ready to plan' if (email or wa) else 'Planning only — connect Email or WhatsApp'
        out.append(x)
    return out
