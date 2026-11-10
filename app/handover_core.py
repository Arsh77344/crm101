from __future__ import annotations

import datetime as dt
import json
import os
import shutil
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

import marketing as m
from release_info import APP_VERSION
import db_layer
import runtime_config as rc
import media_store
import platform_core as pc
import operating_core as oc
import integration_layer as legacy
import integration_v14 as v14
import creative_studio as cs

SCHEMA = r'''
CREATE TABLE IF NOT EXISTS v15_acceptance_evidence(
 id TEXT PRIMARY KEY,
 check_key TEXT NOT NULL,
 status TEXT NOT NULL,
 detail TEXT DEFAULT '',
 source TEXT DEFAULT 'system',
 checked_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS v15_acceptance_key_time ON v15_acceptance_evidence(check_key,checked_at);
'''

STATUSES = {
    'full':'Fully Working',
    'partial':'Partially Working',
    'ui':'UI Only',
    'mock':'Mock / Placeholder',
    'config':'Configuration Required',
    'broken':'Broken',
    'missing':'Not Implemented',
}


def uid(prefix: str) -> str:
    import uuid
    return prefix+'-'+uuid.uuid4().hex[:16].upper()


def initialise() -> None:
    with m.connect() as con:
        con.executescript(SCHEMA)


def _count(sql: str, args=()) -> int:
    try:
        return int((m.one(sql,args) or {'n':0})['n'] or 0)
    except Exception as exc:
        if db_layer.is_database_error(exc): return 0
        raise


def _setting(key: str, default: str='') -> str:
    try:
        row=m.one('SELECT setting_value FROM settings WHERE setting_key=?',(key,))
        return str((row or {}).get('setting_value') or default)
    except Exception:
        return default


def _save_setting(key: str, value: str) -> None:
    with m.connect() as con:
        con.execute('''INSERT INTO settings(setting_key,setting_value) VALUES(?,?)
                       ON CONFLICT(setting_key) DO UPDATE SET setting_value=excluded.setting_value''',(key,value))


def _record(check_key: str, status: str, detail: str, source='system') -> None:
    initialise()
    with m.connect() as con:
        con.execute('INSERT INTO v15_acceptance_evidence(id,check_key,status,detail,source) VALUES(?,?,?,?,?)',
                    (uid('ACC'),check_key,status,detail[:4000],source[:80]))


def latest_evidence(check_key: str) -> dict|None:
    initialise()
    return m.one('SELECT * FROM v15_acceptance_evidence WHERE check_key=? ORDER BY checked_at DESC LIMIT 1',(check_key,))


def _connected(key: str) -> list[dict]:
    try:
        return [c for c in legacy.connections(key) if c.get('status')=='Connected']
    except Exception:
        return []


def _any_success(task_keys: tuple[str,...]) -> bool:
    if not m.table_exists('v13_ai_usage'): return False
    placeholders=','.join('?' for _ in task_keys)
    return _count(f"SELECT count(*) n FROM v13_ai_usage WHERE task_key IN ({placeholders}) AND status='Completed'",task_keys)>0


def _last_openai_verified() -> str:
    return _setting('v15_openai_verified_at','')


def verify_openai_connection() -> dict:
    """User-triggered, non-generative OpenAI credential/model check."""
    key=m.secret()
    if not key:
        raise ValueError('OpenAI is not configured. Add the API key in Settings & AI first.')
    model=m.routed_model('product_understanding','gpt-6-sol')
    url='https://api.openai.com/v1/models/'+urllib.parse.quote(model,safe='')
    req=urllib.request.Request(url,headers={'Authorization':'Bearer '+key})
    try:
        with urllib.request.urlopen(req,timeout=20) as res:
            payload=json.load(res)
    except urllib.error.HTTPError as ex:
        detail=''
        try: detail=ex.read().decode('utf-8','replace')[:600]
        except Exception: pass
        _record('openai_live','Broken',f'HTTP {ex.code}: {detail}','provider')
        raise ValueError(f'OpenAI rejected the connection (HTTP {ex.code}). Check API access, billing and the configured model.') from None
    except OSError:
        _record('openai_live','Broken','Network request failed.','provider')
        raise ValueError('OpenAI could not be reached. Check the internet connection and try again.') from None
    now=dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat().replace('+00:00','Z')
    _save_setting('v15_openai_verified_at',now)
    _save_setting('v15_openai_verified_model',str(payload.get('id') or model))
    _record('openai_live','Fully Working',f'Model access confirmed for {payload.get("id") or model}.','provider')
    return {'ok':True,'model':payload.get('id') or model,'verified_at':now}


def runtime_checks() -> list[dict[str,Any]]:
    initialise();out=[]
    def add(key,label,status,detail,action=''):
        out.append({'key':key,'label':label,'status':status,'detail':detail,'action_url':action})
    db_ok,db_detail=db_layer.database_ready()
    add('database','Database','Ready' if db_ok else 'Broken',db_detail or db_layer.backend_name(),'/system-health')
    media=media_store.status();media_ok=bool(media.get('ready',media.get('backend')=='local'))
    add('media','Media storage','Ready' if media_ok else 'Needs setup',json.dumps(media,default=str),'/system-health')
    ffmpeg=shutil.which('ffmpeg')
    add('ffmpeg','Local video renderer','Ready' if ffmpeg else 'Needs setup',ffmpeg or 'FFmpeg is not installed; local MP4 rendering will fall back or be unavailable.','/creative-studio')
    ai_state=m.ai_health()
    ai_status=ai_state.get('status','Not connected')
    add('openai','OpenAI','Ready' if ai_status=='Connected' else ('Needs setup' if ai_status=='Not connected' else 'Needs attention'),
        str(ai_state.get('detail') or 'AI status has not been checked.'),'/settings#ai')
    try: video_key=bool(cs.video_secret())
    except Exception: video_key=False
    add('video_ai','Generative video provider','Configured, not verified' if video_key else 'Optional / not configured',
        'Google Veo is optional; product-safe local video remains separate.','/creative-studio')
    gaps=rc.production_gaps()
    add('production','Production deployment','Ready' if rc.IS_PRODUCTION and not gaps else ('Needs setup' if rc.IS_PRODUCTION else 'Not deployed'),
        'Production prerequisites satisfied.' if rc.IS_PRODUCTION and not gaps else (' '.join(gaps) if gaps else 'Running in local workspace mode.'),'/architecture-readiness')
    if rc.IS_PRODUCTION:
        auth_ok=pc.auth_enabled() and bool(pc.users()) and pc.production_mfa_ready()
        add('auth','Production sign-in & MFA','Ready' if auth_ok else 'Broken','Production requires database sign-in plus MFA on at least one active Owner.','/access-control')
    else:
        add('auth','User sign-in & roles','Ready' if pc.auth_enabled() else 'Optional locally','Local single-user mode is permitted; enable sign-in before public deployment.','/access-control')
    return out


def external_requirements() -> list[dict[str,str]]:
    initialise();requirements=[]
    def add(key,item,why,where_get,where_go,when,status):
        requirements.append({'key':key,'item':item,'why':why,'where_get':where_get,'where_go':where_go,'when':when,'status':status})
    base=(rc.PUBLIC_BASE_URL or _setting('public_base_url')).strip()
    add('https','Public HTTPS domain','OAuth callbacks and provider webhooks must reach the CRM from the internet.',
        'Your hosting/domain provider.','Production PUBLIC_BASE_URL and provider callback/webhook consoles.','Before live integrations',
        'Ready' if rc.valid_public_https(base) else 'Required')
    ai_state=m.ai_health();ai_status=ai_state.get('status','Not connected')
    add('openai','OpenAI API account/key','Used for product understanding, copy, image generation and voice where enabled.',
        'OpenAI Platform project/API keys.','Settings → AI. The secret is stored outside the contact database.','Before paid AI generation',
        'Ready' if ai_status=='Connected' else ('Required for AI' if ai_status=='Not connected' else ai_status))
    try: veo=bool(cs.video_secret())
    except Exception: veo=False
    add('veo','Google Gemini/Veo API key','Only needed for optional generative fashion motion; local product video does not require it.',
        'Google AI/Gemini developer console with Veo access.','Creative Studio → video provider settings.','Later / optional',
        'Configured, live test needed' if veo else 'Optional')
    for provider,label,why,when in [
        ('shopify','Shopify developer application','Enables owner login, store selection, sync, webhooks and draft publication.','Before live store connection'),
        ('meta','Meta developer application','Enables Facebook/Instagram login and WhatsApp Embedded Signup.','Before Meta/WhatsApp connection'),
        ('google','Google OAuth application','Enables Google Ads, Analytics, Merchant, Search Console, Gmail and Calendar login.','Before Google connection'),
        ('microsoft','Microsoft Entra application','Enables Outlook/business mailbox login.','Before Microsoft mailbox connection')]:
        try: configured=v14.provider_app(provider).get('configured',False)
        except Exception: configured=False
        add(provider,label,why,'The provider developer/admin console.','Advanced platform integrations (Owner/Administrator only).',when,'Configured' if configured else 'Required')
    try:
        google_dev=bool(v14.provider_secret('google','developer_token'))
    except Exception:google_dev=False
    add('google_ads_dev','Google Ads developer token','Google Ads API read/write calls require developer access in addition to normal Google login.',
        'Google Ads API Center in the manager account.','Advanced platform integrations → Google.','Before Google Ads sync/write','Configured' if google_dev else 'Required for Google Ads')
    try:
        meta=v14.provider_app('meta');wa_cfg=bool((meta.get('config') or {}).get('whatsapp_config_id'))
    except Exception:wa_cfg=False
    add('whatsapp_signup','WhatsApp Embedded Signup configuration','Lets the owner connect the WABA/phone without pasting system-user tokens.',
        'Meta App Dashboard / WhatsApp Embedded Signup configuration.','Advanced platform integrations → Meta.','Before WhatsApp connection','Configured' if wa_cfg else 'Required for WhatsApp')
    resend=_connected('resend')
    domain_verified=False
    if m.table_exists('v9_email_domains'):
        domain_verified=_count("SELECT count(*) n FROM v9_email_domains WHERE lower(domain_status) IN ('verified','active','ready')")>0
    add('email_transport','Marketing email sending account + verified domain','Required to deliver marketing/transactional email with DNS authentication and event webhooks.',
        'Resend account and your DNS provider.','Integration Centre + Email infrastructure.','Before sending live email',
        'Ready' if resend and domain_verified else ('Connected; verify domain' if resend else 'Required'))
    add('ad_billing','Advertising billing & conversion setup','Meta/Google cannot safely spend until the ad accounts have billing and conversion destinations configured.',
        'Meta Ads Manager and Google Ads.','Provider accounts; CRM only creates controlled PAUSED structures until reviewed.','Before activating paid campaigns','External review required')
    return requirements


def strict_capability_matrix() -> list[dict[str,str]]:
    """Evidence-led V18 capability inventory.

    This deliberately does not treat a route, table, button or stored token as proof that
    a business outcome works. Provider-backed features remain Configuration Required until
    a validated connection exists, and partial workflows stay Partially Working even when
    their first API call is implemented.
    """
    initialise();out=[]
    def add(key,label,status,detail,action=''):
        out.append({'key':key,'label':label,'status':status,'detail':detail,'action_url':action})
    def ready(channel):
        try:
            r=v14.channel_readiness(channel)
            return r.get('status')=='Connected', str(r.get('reason') or '')
        except Exception:
            return False,'Integration readiness could not be verified.'

    db_ok,db_detail=db_layer.database_ready()
    add('frontend','Frontend / navigation',STATUSES['full'],'Server-rendered business screens, navigation, validation and error pages are covered by regression tests. The owner dashboard and exception-first workspace are the default operating entry points.','/handover')
    add('backend','Backend / application services',STATUSES['full'] if db_ok else STATUSES['broken'],db_detail or 'Core application services initialise against the configured database.','/system-health')
    add('database','Database / persistence',STATUSES['partial'] if db_ok else STATUSES['broken'],'SQLite works for local use and PostgreSQL support/migration exists for production. Real production PostgreSQL scale/load acceptance still requires deployment.','/architecture-readiness')

    products=_count('SELECT count(*) n FROM products');images=_count('SELECT count(*) n FROM product_images')
    intakes=_count('SELECT count(*) n FROM v6_product_intakes') if m.table_exists('v6_product_intakes') else 0
    add('product_management','Product management',STATUSES['full'],f'Create/import/edit/review product records, pricing, stock and evidence are implemented. Workspace currently has {products} product(s).','/products')
    add('product_intake','Raw product image intake',STATUSES['full'],f'Multi-image/ZIP intake, validation, grouping, provenance and safe derivatives are implemented and tested. Current workspace: {intakes} intake(s), {images} image record(s).','/product-engine')
    add('product_qc','Image and product-truth QC',STATUSES['full'],'Image validation, duplicate/near-duplicate checks, unsupported-claim detection and confidence gates are implemented locally.','/quality-centre')

    ai=bool(m.secret());ai_verified=bool(_last_openai_verified());ai_success=_any_success(('product_understanding','product_copy'))
    add('ai_product','AI product understanding / copy',STATUSES['config'] if not ai else (STATUSES['full'] if ai_verified and ai_success else STATUSES['partial']),
        'OpenAI multimodal product analysis and structured content generation are wired. A stored key alone is not proof: V18 requires live model verification and a successful recorded run before calling this fully working.','/settings#ai')
    image_success=_any_success(('creative_master','image_generation'))
    add('ai_images','AI product / model / mannequin imagery',STATUSES['config'] if not ai else STATUSES['partial'],
        ('Successful provider image usage is recorded, but textile/garment fidelity remains approval-gated.' if image_success else 'Reference-image generation is implemented, but no successful provider generation is recorded in this workspace. Fidelity review remains mandatory.'),'/creative-studio')
    add('asset_management','Asset management',STATUSES['partial'],'Source/generated assets, variants, approval state, provenance and cloud-media abstraction exist. A richer owner editor and enterprise DAM workflow remain incomplete.','/creative-studio')

    ffmpeg=bool(shutil.which('ffmpeg'))
    local_video_count=_count("SELECT count(*) n FROM v8_video_jobs WHERE status IN ('Generated','Rendered','Completed','Approved')") if m.table_exists('v8_video_jobs') else 0
    add('video_local','Product-safe local video',STATUSES['full'] if ffmpeg else STATUSES['config'],f'Placement-aware local video rendering is implemented; FFmpeg {"is available" if ffmpeg else "is not installed"}. {local_video_count} rendered/completed job(s) are recorded.','/creative-studio')
    try:video_key=bool(cs.video_secret())
    except Exception:video_key=False
    video_success=_any_success(('video_generation',))
    add('video_ai','Generative fashion video',STATUSES['config'] if not video_key else STATUSES['partial'],'Veo integration exists. '+('Successful provider use is recorded, but fidelity approval is still required.' if video_success else 'Provider access has not yet been proven by a successful recorded generation here.'),'/creative-studio')

    add('crm','CRM / customer 360',STATUSES['partial'],'Contacts, leads/lifecycle, identity resolution, companies, activities, orders, permissions and timeline foundations work. A truly complete cross-channel behavioural history depends on live connectors and website events.','/contacts')
    add('sales_pipeline','Sales pipeline / opportunities / tasks',STATUSES['full'],'Opportunities, stages, owners, tasks, follow-ups, companies and showroom-linked sales records are implemented locally.','/opportunities')
    add('segmentation','Segmentation / audiences',STATUSES['partial'],'Rule/natural-language audience foundations exist, but behavioural segments only become complete when live web/cart/ad/social events are feeding the CRM.','/audiences')
    add('clv','Customer lifetime value / profitability',STATUSES['partial'],'Order/revenue records exist, but complete CLV, contribution margin, cohort and product-profitability analytics remain incomplete.','/marketing-performance')

    add('automation','Event automation / background jobs',STATUSES['partial'],'Persistent events, conditions, delayed jobs, retries, idempotency, approvals, exceptions and dead-letter handling are implemented. The action library does not yet cover every business process.','/event-stream')
    add('consent','Consent / outbound eligibility',STATUSES['full'],'Append-only permission history and effective channel eligibility checks are implemented and used by outbound workflows.','/consent-centre')
    add('identity','Duplicate / identity resolution',STATUSES['partial'],'Email/phone/provider identities and merge foundations exist. Cross-channel identity accuracy still depends on verified identifiers from connected systems.','/contacts')

    store,store_reason=ready('Website')
    social,social_reason=ready('Instagram/Facebook')
    wa,wa_reason=ready('WhatsApp')
    meta,meta_reason=ready('Meta Ads')
    gads,gads_reason=ready('Google Ads')
    add('shopify','Shopify commerce',STATUSES['partial'] if store else STATUSES['config'],(store_reason+' ' if store_reason else '')+'Login-first connection, product/customer/order sync, webhooks, authority controls and reviewed draft publication exist. Carts, checkout lifecycle, fulfilments and returns/refunds are not complete.','/integrations')
    add('inventory','Inventory',STATUSES['partial'],'Canonical location stock, reservations, available-to-promise, audited movements, dispatch, cancellation release, returns and provider reconciliation are implemented. Incoming purchase-order stock and advanced replenishment forecasting remain incomplete.','/data-ownership')
    add('returns','Returns / exchanges / refunds',STATUSES['partial'],'Line-item/quantity return cases, shipped-quantity eligibility, controlled state transitions, refund-value validation, partial-refund accounting, restock-by-returned-quantity and audit history are implemented. Automatic payment-provider refunds and a customer self-service portal still require provider work.','/operations/returns')
    add('shipping','Shipping / fulfilment',STATUSES['partial'],'The current release supports idempotent reservation plus line-level partial/multiple shipments, pack→ship→deliver transitions, tracking validation, canonical stock consumption and an operational audit trail. Automatic carrier rates/labels/tracking webhooks still require a selected carrier connector.','/operations')
    add('payments','Payments',STATUSES['partial'] if _connected('stripe') else STATUSES['config'],'Stripe validation/reconciliation foundations exist. General checkout creation, capture, payment-failure recovery and refunds are not a complete workflow.','/integrations')

    add('social','Facebook / Instagram organic',STATUSES['partial'] if social else STATUSES['config'],(social_reason+' ' if social_reason else '')+'Provider-confirmed single-image publishing and account discovery exist. Scheduling, reels/carousels, comments and complete inbox management remain incomplete.','/integrations')
    add('social_scheduler','Social scheduling',STATUSES['partial'],'V18 adds durable provider-backed Facebook/Instagram image scheduling, explicit retry/publish-now/cancel controls, CRM creative selection and campaign handoff completion from provider evidence. Reels/carousels/stories remain incomplete.','/operations/social')
    add('meta_ads','Meta Ads',STATUSES['partial'] if meta else STATUSES['config'],(meta_reason+' ' if meta_reason else '')+'Reporting plus reviewed provider-confirmed PAUSED campaign/ad-set creation exist. Creative/ad objects, conversion configuration and activation remain intentionally blocked/incomplete.','/integrations')
    add('google_ads','Google Ads',STATUSES['partial'] if gads else STATUSES['config'],(gads_reason+' ' if gads_reason else '')+'Reporting plus reviewed provider-confirmed PAUSED campaign creation exist. Ad groups/assets/conversions/locations and activation remain incomplete.','/integrations')

    email=_connected('resend')
    add('email_marketing','Marketing email',STATUSES['partial'] if email else STATUSES['config'],'Real transport, domain/event/suppression handling and consent checks exist for the implemented provider. Advanced lifecycle scheduling, A/B testing and deliverability operations remain incomplete.','/integrations')
    ms=_connected('microsoft_mailbox');google=_connected('google_account')
    add('business_mailbox','Gmail / Microsoft business mailbox',STATUSES['partial'] if (ms or google) else STATUSES['config'],'Login-first mailbox connections, Gmail metadata sync and Microsoft read/send foundations exist. Full shared inbox, threading, assignment and reply workflow remain incomplete.','/integrations')
    add('whatsapp','WhatsApp Business',STATUSES['partial'] if wa else STATUSES['config'],(wa_reason+' ' if wa_reason else '')+'Embedded Signup, phone registration/WABA subscription, template sending and inbound/status ingestion exist. Rich shared-inbox/media/customer-service operation remains incomplete.','/integrations')

    google_conn=bool(google)
    add('ga4','Google Analytics 4',STATUSES['partial'] if google_conn else STATUSES['config'],'GA4 resource discovery and data-sync foundation exist through the shared Google login. Complete ecommerce funnel/cohort analysis is incomplete.','/integrations')
    add('search_console','Search Console / SEO feedback',STATUSES['partial'] if google_conn else STATUSES['config'],'Search Console read/sync foundation and SEO content tools exist. Automated ranking monitoring, internal-link optimisation and continuous content-refresh loop remain incomplete.','/integrations')
    add('merchant','Merchant Center / Shopping',STATUSES['partial'] if google_conn else STATUSES['config'],'Merchant account discovery and product reads exist. Feed writes, diagnostics remediation, price/inventory writeback and complete Shopping execution are incomplete.','/integrations')
    add('youtube','YouTube publishing / ads',STATUSES['missing'],'YouTube channel discovery exists through Google, but production video publishing and YouTube advertising execution are not implemented.','/integrations')
    add('business_profile','Google Business Profile',STATUSES['partial'] if google_conn else STATUSES['config'],'Business Profile account discovery exists; full location/profile/post/review management is incomplete.','/integrations')

    add('campaigns','Campaign planning / orchestration',STATUSES['partial'],'Unified campaign planning, channel readiness, product/creative association and approvals exist. One-click full multi-channel execution is not complete because several channel write paths remain partial.','/campaign-builder')
    add('analytics','Analytics / reporting',STATUSES['partial'],'CRM, orders, provider metrics and marketing performance foundations exist. Advanced cohorts, CAC/CLV, contribution margin, profit and complete funnels remain incomplete.','/marketing-performance')
    add('attribution','Revenue attribution',STATUSES['partial'],'Touchpoints and campaign/order links exist, but robust multi-touch/cross-device attribution requires consistent live website, ad and order identifiers.','/marketing-performance')
    add('growth_agent','AI growth recommendations',STATUSES['partial'],'Action Centre and AI/deterministic recommendation foundations exist. Continuous autonomous optimisation is not reliable until live revenue, inventory and advertising data are complete.','/')
    add('customer_service_ai','AI customer service agent',STATUSES['partial'],'AI routing/model foundations and inbound events exist, but there is no complete autonomous website + WhatsApp + email support agent grounded across policies/orders/products.','/event-stream')

    add('wholesale','B2B / wholesale',STATUSES['partial'],'Companies, wholesale tiers/prices, opportunities, MOQ and showroom concepts exist. Quotes, negotiated pricing, buyer portal, credit terms and repeat ordering are incomplete.','/companies')
    add('showroom','Physical showroom / offline sales',STATUSES['partial'],'Showroom/location and assisted CRM foundations exist. POS and complete online-to-offline attribution are not implemented.','/showrooms')
    add('manufacturing','Manufacturing / sourcing / MRP',STATUSES['missing'],'Weaver/vendor/raw-material/batch/QC/costing and production-planning workflows are not implemented.','/architecture-readiness')
    add('accounting','Accounting',STATUSES['partial'],'V18 records separate auditable sale and partial-refund finance entries with Prepared/Exported/Posted/Rejected states, external IDs and CSV export. Direct Xero/QuickBooks/general-ledger sync still requires a chosen accounting provider connector.','/operations/accounting')
    add('tax','Tax / invoicing rules',STATUSES['partial'],'Commerce data carries currencies/prices, but complete VAT/GST regional rules and statutory invoice handling are not implemented.','/architecture-readiness')
    add('localisation','Localisation / multicurrency',STATUSES['partial'],'Default language/currency and translation-model routing exist; full regional catalogues, market pricing and translation workflow are incomplete.','/settings')

    auth_ok=pc.auth_enabled()
    add('security','Security / authentication',STATUSES['partial'],'CSRF, roles, encrypted secrets, OAuth state/PKCE, provider validation and MFA foundations exist. Production security is not complete until deployed with HTTPS, managed secrets, MFA and real provider acceptance.','/access-control')
    add('roles','Users / roles / approvals',STATUSES['full'] if auth_ok or not rc.IS_PRODUCTION else STATUSES['config'],'Role permissions and approval gates are implemented; public production requires authentication and MFA.','/access-control')
    add('privacy','Privacy / GDPR operations',STATUSES['partial'],'Consent, privacy-request/anonymisation foundations exist. Full retention, DSAR export/deletion automation and policy operations remain incomplete.','/privacy')
    add('error_handling','Errors / retries / recovery',STATUSES['partial'],'Business-language integration errors, retries, dead-letter jobs and recovery hints exist. Not every legacy workflow has the same polished loading/retry UX.','/system-health')
    add('monitoring','Monitoring / alerts',STATUSES['partial'],'Health/readiness/metrics and integration health checks exist. Real uptime/error destinations and alert delivery require production configuration.','/system-health')
    add('backups','Backups / disaster recovery',STATUSES['partial'],'Encrypted PostgreSQL backup/restore tooling exists. Off-site schedules and restore drills must be proven in the deployed environment.','/architecture-readiness')
    prod_ready=rc.IS_PRODUCTION and not rc.production_gaps() and pc.auth_enabled() and pc.production_mfa_ready()
    add('deployment','Production deployment',STATUSES['partial'] if prod_ready else STATUSES['config'],'Docker/PostgreSQL/object storage/worker/HTTPS/metrics/backup architecture exists. It is not a verified live deployment until the real cloud environment passes acceptance.','/architecture-readiness')
    add('scale','Scalability',STATUSES['partial'],'PostgreSQL and durable-worker foundations remove key localhost bottlenecks, but 100k+ contact/catalogue load tests and concurrent-worker/provider-rate-limit testing are still required.','/architecture-readiness')
    add('multi_business','Multi-business tenancy',STATUSES['mock'],'Brand/location/workspace ownership foundations exist, but full tenant isolation is not complete and must not be sold as true multi-tenant SaaS.','/architecture-readiness')
    add('owner_experience','Owner experience / handover',STATUSES['partial'],'The current release provides a single Needs Attention queue and factual Business Readiness view on top of fulfilment, returns, inbox, retention, social, finance and next-action work queues. Specialist provider configuration still needs an administrator until live accounts are onboarded.','/handover')
    add('process_orchestration','End-to-end process orchestration',STATUSES['full'],'V18 persists product-to-market, lead-to-sale, campaign-to-revenue and order-to-retention processes with evidence-based step states and blockers.','/operations')
    add('unified_inbox','Unified conversation view',STATUSES['partial'],'V18 adds conversation ownership, close/reopen, follow-up task creation and safe one-to-one Email sending on top of the unified activity view. Native replies for every provider remain connector-dependent.','/operations/inbox')
    add('profitability','Contribution / profitability bridge',STATUSES['partial'],'V18 calculates evidence-based revenue, recorded COGS and synced ad-spend contribution views. Complete tax, returns cost, fulfilment cost and accounting-provider reconciliation remain incomplete.','/operations')
    return out

def journey_audit() -> dict:
    """Strict non-destructive business journey. No provider writes, sends or spend."""
    initialise();steps=[]
    def add(no,label,status,detail,action=''):
        steps.append({'no':no,'label':label,'status':status,'detail':detail,'action_url':action})
    products=_count('SELECT count(*) n FROM products');images=_count('SELECT count(*) n FROM product_images')
    content=_count('SELECT count(*) n FROM v6_product_content') if m.table_exists('v6_product_content') else 0
    add(1,'Business account & settings','Working' if (_setting('brand_name').strip() and _setting('brand_name').strip().lower()!='brand name pending') else 'Requires setup','Business settings exist; enter the real brand/business details before live use.','/settings')
    add(2,'Connect business accounts','Partial' if any(c.get('status')=='Connected' for c in legacy.connections()) else 'Requires setup','Login-first connections are implemented for the main providers, but live accounts must be connected and validated.','/integrations')
    add(3,'Upload raw product images','Working' if images else 'Ready','The intake engine is implemented and tested; this workspace currently has %d image record(s).'%images,'/product-engine')
    add(4,'Create product record','Working' if products else 'Ready','The product intake pipeline creates reviewable product records; %d product(s) currently exist.'%products,'/product-engine')
    ai=bool(m.secret());verified=bool(_last_openai_verified())
    add(5,'AI product understanding','Working' if ai and verified and _any_success(('product_understanding',)) else ('Requires setup' if not ai else 'Partial'),'A key is not enough for Pass; live model verification and successful recorded analysis are required.','/settings#ai')
    add(6,'Product copy & SEO','Working' if content and _any_success(('product_understanding','product_copy')) else ('Partial' if content else 'Ready'),'Product content storage exists; successful generation plus human review is the evidence gate.','/product-engine')
    img_success=_any_success(('creative_master','image_generation'))
    add(7,'Professional AI product imagery','Partial' if img_success else ('Requires setup' if not ai else 'Ready'),'Reference-image generation exists. Even after successful generation, textile fidelity remains approval-gated.','/creative-studio')
    ffmpeg=bool(shutil.which('ffmpeg'))
    add(8,'Product video','Working' if ffmpeg else 'Requires setup','Local product-safe video needs FFmpeg. Generative motion is optional and always review-gated.','/creative-studio')
    try:store=v14.channel_readiness('Website')
    except Exception:store={'status':'Not connected','reason':'Integration layer unavailable.'}
    add(9,'Store publication','Partial' if store.get('status')=='Connected' else 'Requires setup',(store.get('reason') or '')+' Shopify draft publishing exists; full checkout/fulfilment/returns lifecycle is not complete.','/integrations')
    add(10,'Create cross-channel campaign','Working' if m.table_exists('v10_unified_campaigns') else 'Broken','Unified campaign planning and channel readiness are implemented.','/campaign-builder')
    try:social=v14.channel_readiness('Instagram/Facebook')
    except Exception:social={'status':'Not connected','reason':''}
    add(11,'Instagram/Facebook publishing','Partial' if social.get('status')=='Connected' else 'Requires setup','Supported image publishing exists after provider validation; scheduling/reels/comments/inbox are incomplete.','/integrations')
    add(12,'Marketing email','Partial' if _connected('resend') else 'Requires setup','Sending/events/suppression are real for the implemented transport; richer lifecycle orchestration remains partial.','/integrations')
    try:wa=v14.channel_readiness('WhatsApp')
    except Exception:wa={'status':'Not connected'}
    add(13,'WhatsApp','Partial' if wa.get('status')=='Connected' else 'Requires setup','Embedded Signup, templates and inbound/status events exist; richer two-way agent/inbox operation is incomplete.','/integrations')
    try:meta=v14.channel_readiness('Meta Ads');google=v14.channel_readiness('Google Ads')
    except Exception:meta=google={'status':'Not connected'}
    add(14,'Meta advertising','Partial' if meta.get('status')=='Connected' else 'Requires setup','Provider-confirmed PAUSED campaign/ad-set creation exists. Activation and complete ad/creative/conversion setup remain blocked.','/integrations')
    add(15,'Google advertising','Partial' if google.get('status')=='Connected' else 'Requires setup','Provider-confirmed PAUSED campaign creation exists. Ad groups/assets/conversions and activation remain blocked.','/integrations')
    contacts=_count('SELECT count(*) n FROM contacts')
    add(16,'Lead/customer enters CRM','Working' if contacts else 'Ready','CRM creation/import/identity-resolution works; completeness depends on live forms, ads, messages and commerce sources.','/contacts')
    add(17,'Follow-up automation','Working' if m.table_exists('v13_automation_rules') else 'Broken','Event rules, durable delayed jobs, retries and human approvals are implemented.','/event-stream')
    orders=_count('SELECT count(*) n FROM orders')
    add(18,'Purchase & order sync','Working' if orders else ('Partial' if store.get('status')=='Connected' else 'Requires setup'),f'{orders} order(s) recorded. Shopify orders can sync when connected; other commerce/payment sources are incomplete.','/orders')
    add(19,'Shipping & delivery','Partial','The current release provides a fulfilment queue, idempotent reservations, partial/multiple shipments, pack→ship→deliver controls and tracking validation. Automatic carrier labels/rates/webhooks still require a carrier connector.','/operations')
    add(20,'Revenue attribution','Partial','Touchpoints exist, but robust multi-touch/cross-device attribution still needs live website and provider identifiers.','/marketing-performance')
    add(21,'Post-purchase & retention','Partial','V18 creates actionable thank-you, review, cross-sell and win-back work with complete/snooze/cancel controls. Live sending still obeys consent and connected transport readiness.','/operations/retention')
    add(22,'Analytics','Partial','CRM and provider metrics exist; cohorts, CLV, contribution margin and complete profit/funnel analytics remain incomplete.','/marketing-performance')
    add(23,'AI next action','Partial','Action Centre has deterministic/AI-assisted recommendations; continuous autonomous optimisation depends on complete live revenue/stock/ad data.','/')
    add(24,'Accounting / finance handoff','Partial','V18 prepares separate sale/refund accounting entries with export/posting status and external references. Direct posting to an accounting provider is still not configured.','/operations/accounting')
    add(25,'Production reliability','Working' if rc.IS_PRODUCTION and not rc.production_gaps() else 'Requires setup','Cloud architecture exists in code; production deployment, alert delivery, restore drills and provider staging acceptance still need the real environment.','/architecture-readiness')
    severity={'Working':0,'Ready':1,'Partial':2,'Requires setup':3,'Not implemented':4,'Broken':5}
    worst=max(steps,key=lambda x:severity.get(x['status'],5))['status'] if steps else 'Broken'
    return {'status':worst,'steps':steps,'counts':{s:sum(1 for x in steps if x['status']==s) for s in severity}}


def beginner_flow() -> list[dict[str,str]]:
    return [
        {'step':'1','title':'Set up the business','what':'Enter real business/brand details, market, currency and operating defaults.','automatic':'The CRM stores one source of business settings.','owner':'Confirm the facts and create users/MFA before public deployment.'},
        {'step':'2','title':'Connect channels','what':'Click Connect, sign in to Shopify/Meta/Google/Microsoft, approve permissions and choose the correct account.','automatic':'OAuth tokens, refresh, resource discovery and routing are handled behind the scenes.','owner':'Developer app configuration is an administrator/deployment task, not a daily task.'},
        {'step':'3','title':'Upload raw product photos','what':'Upload a few saree/suit photos or an intake archive.','automatic':'The system validates files, groups them, stores provenance and prepares safe derivatives.','owner':'Resolve missing/duplicate/poor-quality photos if flagged.'},
        {'step':'4','title':'Understand and describe the product','what':'AI analyses visible product details and drafts names, descriptions, tags and SEO metadata.','automatic':'AI is constrained not to invent silk purity, handloom/GI/authenticity, price, stock or similar unverifiable facts.','owner':'Review uncertain facts and approve evidence.'},
        {'step':'5','title':'Create imagery and video','what':'Prepare ecommerce images, model/mannequin/studio variants, social assets and product video.','automatic':'Local composition and optional provider AI generate assets into a review queue.','owner':'Approve garment fidelity, especially generative model/video output.'},
        {'step':'6','title':'Prepare the store listing','what':'Send the reviewed product to the selected commerce account.','automatic':'Connection routing and provider response determine status.','owner':'Confirm price, stock and publication approval.'},
        {'step':'7','title':'Create marketing','what':'Build one campaign plan for social, email, WhatsApp and paid media.','automatic':'The system prepares channel-specific assets/audiences and checks permissions/readiness.','owner':'Approve messaging, budget, targeting and high-risk external actions.'},
        {'step':'8','title':'Capture responses and sales','what':'Inbound messages, delivery events and store orders feed customer records where connectors support them.','automatic':'Identity resolution, consent, activities, events and tasks update the CRM.','owner':'Resolve duplicate identities/exceptions.'},
        {'step':'9','title':'Retain customers','what':'Purchases can trigger post-purchase tasks/recommendations and future campaigns.','automatic':'Durable rules can schedule follow-up work.','owner':'Choose automation level and approve customer-facing actions where required.'},
        {'step':'10','title':'Measure and improve','what':'Provider metrics, CRM activity, orders and touchpoints feed reporting/recommendations.','automatic':'The Action Centre surfaces issues/opportunities.','owner':'Use recommendations as decision support; incomplete attribution is clearly labelled.'},
    ]


def v43_operational_truth() -> dict:
    """Local truth checks that do not pretend external providers were reached."""
    from pathlib import Path
    import release_info
    root=Path(__file__).resolve().parent
    bypasses=[]
    for path in root.glob('*.py'):
        if path.name=='ai_router.py':
            continue
        try:
            text=path.read_text(errors='ignore')
        except Exception:
            continue
        if ('api.openai.com'+'/v1/responses') in text:
            bypasses.append(path.name)
    validations=m.rows("SELECT task_key,status,detail,checked_at FROM v42_ai_validation ORDER BY task_key") if m.table_exists('v42_ai_validation') else []
    failures=m.rows("SELECT task_key,error_category,failure_count,last_seen_at FROM v42_ai_failure_groups WHERE resolved=0 ORDER BY last_seen_at DESC") if m.table_exists('v42_ai_failure_groups') else []
    mcps=m.rows("SELECT id,label,status,last_success_at,last_error FROM v42_mcp_connectors ORDER BY label") if m.table_exists('v42_mcp_connectors') else []
    authority=m.one("SELECT authority_connection_id FROM v14_data_authority WHERE entity_type='inventory'") if m.table_exists('v14_data_authority') else {}
    connected_stores=int((m.one("SELECT count(*) n FROM v10_connections WHERE connector_key='shopify' AND status='Connected'") or {'n':0})['n']) if m.table_exists('v10_connections') else 0
    dupes=int((m.one("SELECT count(*) n FROM products WHERE coalesce(duplicate_group,'')<>'' AND status<>'Archived'") or {'n':0})['n']) if m.table_exists('products') else 0
    stuck=int((m.one("SELECT count(*) n FROM v9_jobs WHERE status IN ('Running','Retry')") or {'n':0})['n']) if m.table_exists('v9_jobs') else 0
    return {
        'release_identity':{'product':release_info.PRODUCT_NAME,'label':release_info.RELEASE_LABEL,'version':release_info.APP_VERSION,'build':release_info.BUILD_ID,'schema':release_info.SCHEMA_VERSION,'consistent':release_info.identity_consistent()},
        'responses_api_bypasses':bypasses,
        'ai_validation':validations,
        'ai_open_failure_groups':failures,
        'mcp_connectors':mcps,
        'inventory_authority':{'connected_stores':connected_stores,'selected_connection_id':str((authority or {}).get('authority_connection_id') or ''),'needs_selection':bool(connected_stores and not (authority or {}).get('authority_connection_id'))},
        'duplicate_active_products':dupes,
        'stuck_or_retry_jobs':stuck,
    }



def v44_operational_truth() -> dict:
    """V44 checks for owner-workflow/runtime truth defects discovered in this cycle."""
    import release_info
    base=v43_operational_truth()
    required={'error_category','retryable','attempts','provider_request_id','duration_ms','related_url','failure_signature'}
    cols=set()
    if m.table_exists('v13_ai_usage'):
        try:
            with m.connect() as con:
                try:
                    cols={r['name'] for r in con.execute('PRAGMA table_info(v13_ai_usage)')}
                except Exception:
                    cols={r['column_name'] for r in con.execute("SELECT column_name FROM information_schema.columns WHERE table_name='v13_ai_usage'")}
        except Exception:
            cols=set()
    missing=sorted(required-cols) if cols else ([] if not m.table_exists('v13_ai_usage') else sorted(required))
    groups=m.rows("SELECT task_key,error_category,failure_count,last_seen_at FROM v42_ai_failure_groups WHERE resolved=0 ORDER BY last_seen_at DESC") if m.table_exists('v42_ai_failure_groups') else []
    provider_wide={'authentication':'Needs attention','quota':'Billing / quota issue','rate_limit':'Rate limited','provider_unavailable':'Provider unavailable','timeout':'Provider unavailable','network':'Needs attention','missing_credentials':'Not connected'}
    health=m.ai_health()
    inconsistent=[]
    for g in groups:
        expected=provider_wide.get(g.get('error_category'))
        if expected and health.get('status') in {'Connected','Untested'}:
            inconsistent.append({'task_key':g.get('task_key'),'error_category':g.get('error_category'),'expected_status':expected,'actual_status':health.get('status')})
    return {**base,
        'release_identity':{'product':release_info.PRODUCT_NAME,'label':release_info.RELEASE_LABEL,'version':release_info.APP_VERSION,'build':release_info.BUILD_ID,'schema':release_info.SCHEMA_VERSION,'consistent':release_info.identity_consistent()},
        'ai_ledger_schema':{'ready':not missing,'missing_columns':missing},
        'shared_ai_health':{'status':health.get('status'),'consistent_with_open_provider_failures':not inconsistent,'mismatches':inconsistent},
        'settings_ai_schema_guard':'Settings calls ai_router.initialise() before querying enriched AI ledger columns.',
    }

def doctor_report() -> dict:
    import release_info
    import v40_integrity
    import v37_business_readiness as br
    from pathlib import Path
    journey=journey_audit();integrity=v40_integrity.integrity_gate(record=False)
    # Merge business-readiness checks into the Doctor integrity surface so a green
    # transaction ledger cannot hide missing backups, dead-letter jobs or data-quality blockers.
    extra=br.doctor_findings(Path(__file__).resolve().parent)
    try:
        import team_beta6
        extra=list(extra)+team_beta6.doctor_findings(m.connect)
    except Exception as exc:
        extra=list(extra)+[{'check_key':'team_release_truth_check_failed','severity':'High','object_type':'system','object_id':'','detail':'Team-release truth checks could not complete: '+str(exc)[:500]}]
    if extra:
        findings=list(integrity.get('findings',[]))+extra
        critical=sum(1 for x in findings if x.get('severity')=='Critical');high=sum(1 for x in findings if x.get('severity')=='High')
        integrity={**integrity,'findings':findings,'critical':critical,'high':high,'status':'Broken' if critical else ('Needs attention' if high else 'Working')}
    if integrity['status']=='Broken':journey={**journey,'status':'Broken'}
    return {
        'product':release_info.PRODUCT_NAME if 'release_info' in globals() else 'Commerce Business OS','version':APP_VERSION,'build':__import__('release_info').BUILD_ID,'schema':__import__('release_info').SCHEMA_VERSION,
        'runtime':runtime_checks(),
        'external_requirements':external_requirements(),
        'capabilities':strict_capability_matrix(),
        'journey':journey,
        'integrity':integrity,
        'business_readiness':br.readiness_scorecard(Path(__file__).resolve().parent),
        'crm_health':br.crm_health(),
        'v42_operational_truth':{
            'ai_capability_validation':m.rows('SELECT task_key,provider,model,status,detail,checked_at FROM v42_ai_validation ORDER BY task_key') if m.table_exists('v42_ai_validation') else [],
            'ai_open_failure_groups':m.rows('SELECT task_key,provider,model,error_category,failure_count,last_seen_at FROM v42_ai_failure_groups WHERE resolved=0 ORDER BY last_seen_at DESC') if m.table_exists('v42_ai_failure_groups') else [],
            'mcp_connectors':m.rows('SELECT id,provider_key,label,status,last_success_at,last_error FROM v42_mcp_connectors ORDER BY label') if m.table_exists('v42_mcp_connectors') else [],
            'lifecycle_policy':'Dependency-aware destructive deletion is enforced by record_lifecycle.py; integration removal means disconnect, not history deletion.'
        },
        'v44_operational_truth':v44_operational_truth(),
    }
