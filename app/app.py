#!/usr/bin/env python3
"""Commerce Business OS 1.0.0-beta.6 TEAM-TEST-006 release."""
from __future__ import annotations
import datetime as dt
import html
import hashlib
import hmac
import io
import json
import mimetypes
import os
import re
import secrets
import socket
import sqlite3
import threading
import urllib.parse
import webbrowser
from http.server import ThreadingHTTPServer
from pathlib import Path

import legacy
import runtime_config as rc
import db_layer
import media_store
import observability
import marketing as m
import contact_tools as ct
import outreach as o
from growth_ui import ContactPages, personalisation_fields
from workspace_ui import WorkspacePages
from v5_features import FeaturePages
import v5_features as v5
from product_engine_ui import ProductEnginePages
import product_engine as pe
from creative_ui import CreativePages
import creative_engine as ce
from creative_studio_ui import CreativeStudioPages
import creative_studio as cs
import business_os as bos
from business_os_ui import BusinessOSPages
import integration_layer as integ
from integration_ui import IntegrationPages
import integration_v14 as int14
from integration_v14_ui import IntegrationV14Pages
import platform_core as pc
from platform_ui import PlatformPages, login_document
import operating_core as oc
from operating_ui import OperatingPages
import handover_core as hc
from handover_ui import HandoverPages
from owner_experience_ui import OwnerExperiencePages
import process_orchestrator as po
from process_orchestrator_ui import ProcessOrchestratorPages
import record_lifecycle as lifecycle
import v24_ops as v24
from release_info import APP_VERSION, BUILD_ID, SCHEMA_VERSION, PRODUCT_NAME, RELEASE_LABEL, RELEASE_NAME
import v27_marketing as v27m
import v35_truth as truth
from v27_marketing_ui import V27MarketingPages
from v37_ui import V37BusinessPages
import v37_business_readiness as v37br
import ai_router
import connection_service
import v54_repair
import team_beta2
import team_beta6
import launch_studio
from launch_ui import LaunchPages

ROOT=Path(__file__).resolve().parent
legacy.DB=m.DB
legacy.STATIC=rc.STATIC_ROOT
TOKEN=secrets.token_urlsafe(32)
old_layout=legacy.layout


def current_table_exists(name: str) -> bool:
    """Check schema against the same database connection used by owner workflows.

    Avoid mixing db_layer's process-global workspace with marketing's active/test
    workspace; that mismatch can make a page believe a table exists and then query
    a different database.
    """
    try:
        with m.connect() as con:
            try:
                row=con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(name,)).fetchone()
                return row is not None
            except Exception:
                row=con.execute("SELECT count(*) n FROM information_schema.tables WHERE table_schema='public' AND table_name=?",(name,)).fetchone()
                return bool(row and int(row['n'])>0)
    except Exception:
        return False


_LOOPBACK_HOSTS={"localhost","127.0.0.1","::1"}

def _canonical_origin(value: str):
    """Return (scheme, normalized_host, effective_port) for origin comparisons.

    Browsers omit default ports from Origin (for example http://127.0.0.1
    instead of http://127.0.0.1:80). Loopback aliases are normalized so
    localhost, 127.0.0.1 and ::1 are treated as the same local machine.
    """
    raw=str(value or '').strip().rstrip('/')
    if not raw:
        return None
    try:
        parsed=urllib.parse.urlparse(raw)
        scheme=(parsed.scheme or '').lower()
        host=(parsed.hostname or '').lower().rstrip('.')
        if not scheme or not host:
            return None
        if host in _LOOPBACK_HOSTS:
            host='loopback'
        port=parsed.port
        if port is None:
            if scheme=='http':
                port=80
            elif scheme=='https':
                port=443
        return (scheme,host,port)
    except (ValueError,TypeError):
        return None

def _canonical_host(value: str, scheme: str='http'):
    raw=str(value or '').strip()
    if not raw:
        return None
    return _canonical_origin(f'{scheme}://{raw}')

def _origin_is_allowed(origin: str, host_header: str, server_port: int, public_base_url: str='', local_mode: bool=True) -> bool:
    """Validate browser Origin using canonical scheme/host/port semantics.

    Local mode deliberately treats loopback aliases/ports as one trusted local
    browser boundary; the per-form CSRF token is still required. Production
    mode remains exact-origin only.
    """
    if not str(origin or '').strip():
        return True
    origin_key=_canonical_origin(origin)
    if not origin_key:
        return False
    host_key=_canonical_host(host_header,'http')
    if host_key:
        # In local single-user mode, browsers/proxies can serialize the same
        # loopback CRM with different aliases or omit/default the port. Treat
        # those as the same local boundary, then rely on the mandatory CSRF
        # token for request authenticity. External origins are still rejected.
        if local_mode and origin_key[1]=='loopback' and host_key[1]=='loopback':
            return True
        if local_mode and origin_key==host_key:
            return True
    public_key=_canonical_origin(public_base_url) if public_base_url else None
    return bool(public_key and origin_key==public_key)

def csrf_token_for_cookie(cookie_header: str='') -> str:
    """Return a CSRF token bound to this authenticated browser session."""
    session=''
    for part in str(cookie_header or '').split(';'):
        key,sep,value=part.strip().partition('=')
        if sep and key=='crm_session':
            session=value
            break
    # Local/no-auth mode keeps the historical process token so existing local
    # workflows and tests remain compatible. Authenticated browser sessions
    # receive a distinct HMAC-bound token, preventing one signed-in user from
    # reusing another user's CSRF token.
    if not session:
        return TOKEN
    return hmac.new(TOKEN.encode('utf-8'),session.encode('utf-8'),hashlib.sha256).hexdigest()

H=html.escape

def e(value):
    return H('' if value is None else str(value),quote=True)

def query(value):
    return urllib.parse.quote(str(value))

def options(values, chosen='', empty=None):
    result=f'<option value="">{e(empty)}</option>' if empty is not None else ''
    for value in values:
        v,label=value if isinstance(value,tuple) else (value,value)
        result+=f'<option value="{e(v)}" {"selected" if str(v)==str(chosen) else ""}>{e(label)}</option>'
    return result

def button(label,href,kind=''):
    return f'<a class="btn {kind}" href="{e(href)}">{label}</a>'

def notice(text,kind='info'):
    return f'<div class="note {kind}">{e(text)}</div>'

def pagehead(title,subtitle,actions=''):
    return f'<div class="top"><div><h1>{e(title)}</h1><div class="sub">{e(subtitle)}</div></div><div class="actions">{actions}</div></div>'

def field(label, control, hint=''):
    return f'<label class="field">{e(label)}{control}{"<small>"+e(hint)+"</small>" if hint else ""}</label>'

def source_choices():
    return [(r['source_name'],r['source_name']) for r in m.rows("SELECT source_name FROM contacts WHERE source_name IS NOT NULL AND source_name<>'' UNION SELECT source AS source_name FROM m41_sources ORDER BY 1")]

def layout(title,body,active='dashboard'):
    css=re.search(r'<style>(.*?)</style>',old_layout(title,'',active),re.S).group(1)
    groups=[
        ('HOME',[
            ('today','/today','Home','&#8962;'),
            ('exceptions','/business-exceptions','Needs attention','&#9888;'),
            ('activity','/activity','Recent activity','&#9719;')]),
        ('SELL',[
            ('launch','/launch','Launch a product','&#10024;'),
            ('products','/products','Products','&#9635;'),
            ('orders','/orders','Orders','&#9776;'),
            ('locations','/locations','Stock & locations','&#9638;'),
            ('showrooms','/showrooms','Customer selections','&#9671;')]),
        ('CUSTOMERS',[
            ('contacts','/contacts','Customers & leads','&#9678;'),
            ('opportunities','/opportunities','Sales pipeline','&#9672;'),
            ('tasks','/tasks','Tasks','&#9719;')]),
        ('MARKETING',[
            ('marketing','/marketing','Marketing home','&#10022;'),
            ('campaign_builder','/campaign-builder','Create campaign','&#10022;'),
            ('marketing_calendar','/marketing-calendar','Calendar','&#9719;'),
            ('performance','/marketing-performance','Results','&#9636;')]),
        ('AI & AUTOMATION',[
            ('product_engine','/product-workspace','Prepare products','&#9633;'),
            ('creative_studio','/creative-studio','AI image & video studio','&#10024;'),
            ('automation','/event-stream','Automations','&#8644;')]),
        ('CONNECTIONS',[
            ('integrations','/integrations','Connected apps','&#9901;'),
            ('integration_health','/integration-health','Connection health','&#9829;')])]
    advanced=[
        ('action','/','Business overview','&#8962;'),
        ('approvals','/approvals','Approvals','&#10003;'),
        ('journeys','/customer-journeys','Customer journeys','&#8644;'),
        ('operations','/operations','Operations centre','&#8644;'),
        ('quality','/quality-centre','Quality centre','&#10003;'),
        ('growth','/growth','Growth opportunities','&#10022;'),
        ('campaigns','/campaigns','Advanced campaign studio','&#10022;'),
        ('privacy','/consent-centre','Consent & privacy','&#128274;'),
        ('owner_automation','/owner-automation','Automation level','&#8644;'),
        ('setup','/setup','Business setup','&#10003;'),
        ('handover','/handover','System handover','&#9654;'),
        ('readiness','/business-readiness','Business readiness','&#9636;'),
        ('capability','/capability-audit','Capability audit','&#9636;'),
        ('crm_health','/crm-health','CRM health','&#9829;'),
        ('e2e','/v17-e2e','End-to-end test','&#10003;'),
        ('external','/external-requirements','External requirements','&#9432;'),
        ('health','/system-health','System health','&#9888;'),
        ('access','/access-control','Users & roles','&#128274;'),
        ('settings','/settings','Settings','&#9881;'),
        ('backups','/backups','Backups','&#8634;')]
    nav=''
    for group,items in groups:
        nav+=f'<div class="nav-group">{group}</div>'
        nav+=''.join(f'<a class="nav {"active" if key==active else ""}" href="{url}"><span aria-hidden="true">{icon}</span>{e(label)}</a>' for key,url,label,icon in items)
    advanced_open=' open' if active in {x[0] for x in advanced} else ''
    nav+=f'<details class="nav-more"{advanced_open}><summary>More tools &amp; settings</summary>'
    nav+=''.join(f'<a class="nav {"active" if key==active else ""}" href="{url}"><span aria-hidden="true">{icon}</span>{e(label)}</a>' for key,url,label,icon in advanced)
    nav+='</details>'
    ai_state=m.ai_health()
    ai={'Connected':'AI ready','Untested':'AI needs a quick test','Rate limited':'AI temporarily limited','Billing / quota issue':'AI needs attention','Model unavailable':'AI model unavailable','Needs attention':'AI needs attention','Provider unavailable':'AI provider unavailable'}.get(ai_state.get('status'),'AI not connected')
    summary={'degraded':True}
    try:
        summary=v24.daily_summary();attention=v24.attention_total(summary)
    except Exception as exc:
        attention=0
        observability.log('workspace_bar.summary_failed',error=str(exc))
    attention_label='Today'+((' · '+str(attention)) if attention else (' · check' if summary.get('degraded') else ''))
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{e(title)} | {e(PRODUCT_NAME)}</title><style>{css}</style><link rel="stylesheet" href="/ui/studio.css"><link rel="stylesheet" href="/ui/workspace.css"><link rel="stylesheet" href="/ui/v25.css?v=34"><link rel="stylesheet" href="/ui/v28.css?v=34"><link rel="stylesheet" href="/ui/v29.css?v=34"><link rel="stylesheet" href="/ui/v30.css?v=34"><link rel="stylesheet" href="/ui/v32.css?v=34"><link rel="stylesheet" href="/ui/v33.css?v=34"><link rel="stylesheet" href="/ui/v34.css?v=34"><link rel="stylesheet" href="/ui/v45.css?v=45"><script defer src="/ui/studio.js"></script><script defer src="/ui/workspace.js"></script></head><body>
<a class="skip" href="#main">Skip to content</a><div class="shell"><aside id="primary-navigation" aria-label="Main navigation"><div class="brand"><span class="brand-mark">c.</span><div>{e(PRODUCT_NAME)}<small>Team test workspace</small></div></div>{nav}<div class="aside-foot"><span class="mode-dot"></span>{"Production" if rc.IS_PRODUCTION else "Team Test Mode"} &middot; {APP_VERSION}<br>{BUILD_ID} &middot; Schema {SCHEMA_VERSION}</div></aside><button class="nav-backdrop" type="button" data-menu-close aria-label="Close navigation" tabindex="-1"></button>
<div class="workarea"><header class="workspace-bar"><button type="button" class="mobile-nav" data-menu aria-label="Open navigation" aria-controls="primary-navigation" aria-expanded="false">&#9776;</button><form action="/search" method="get"><div class="search-shell"><span class="muted" aria-hidden="true">&#8981;</span><label class="visually-hidden" for="global-search">Search workspace</label><input class="global-search" id="global-search" name="q" autocomplete="off" placeholder="Search anything..."><span class="search-hint">⌘ K</span></div></form><div class="workspace-controls"><a class="top-link {'attention-link' if attention or summary.get('degraded') else ''}" href="/today">{e(attention_label)}</a><a class="top-link ai-status" href="/settings#ai">{e(ai)}</a><a class="quick-new" href="/new" aria-label="Create something new">+ New</a><div class="avatar" aria-label="Workspace user">T</div></div></header><main id="main">{body}</main></div></div></body></html>'''

legacy.layout=layout


def safe_suggestions():
    # Keyword prioritisation is not AI, consent, residency or purchase probability.
    count=0
    with m.connect() as con:
        for row in con.execute('SELECT * FROM contacts').fetchall():
            r=dict(row); text=' '.join(r[k] or '' for k in ['username','full_name','biography'])
            words=[term for term in ['saree','sarees','sari','silk','boutique','handloom','textile','bridal','retailer','fashion','designer'] if re.search(r'\b'+term+r'\b',text,re.I)]
            score=min(100,len(words)*14+20) if words else 20
            reason='Rule-based terms: '+', '.join(words) if words else 'Limited profile evidence; do not infer consumer intent.'
            con.execute('UPDATE contacts SET lead_score=?,relevance_reason=?,data_quality=? WHERE contact_id=?',
                        (score,reason,legacy.data_quality(r['email'],r['phone_number'],r['website']),r['contact_id']))
            count+=1
    m.audit('audience.suggestions','',f'{count} priority hints refreshed. Qualification, type, country and permissions unchanged.')
    return count
legacy.run_enrichment=safe_suggestions


def health_payload():
    email_ready=integ.channel_readiness('Email')['status']=='Connected'
    wa_ready=integ.channel_readiness('WhatsApp')['status']=='Connected'
    shop_ready=integ.channel_readiness('Website')['status']=='Connected'
    db_ok,db_detail=db_layer.database_ready();gaps=rc.production_gaps();store=media_store.status()
    pending_events=(m.one("SELECT count(*) n FROM v13_events WHERE status IN ('Pending','Retry')") or {'n':0})['n'] if m.table_exists('v13_events') else 0
    open_incidents=(m.one("SELECT count(*) n FROM v13_incidents WHERE status='Open'") or {'n':0})['n'] if m.table_exists('v13_incidents') else 0
    return {'product':PRODUCT_NAME,'version':APP_VERSION,'build':BUILD_ID,'schema':SCHEMA_VERSION,'team_test_mode':rc.TEAM_TEST_MODE,'external_writes_enabled':rc.ALLOW_EXTERNAL_WRITES,'mode':'production' if rc.IS_PRODUCTION else 'local','database':db_layer.backend_name(),'database_ready':db_ok,'database_detail':db_detail,
        'media':store,'production_configuration_gaps':gaps,'ai_optional':True,'product_engine':True,'creative_engine':True,'creative_studio':True,'ai_video_optional':True,
        'operating_loop':True,'pending_business_events':int(pending_events or 0),'open_incidents':int(open_incidents or 0),'durable_worker_required_in_production':bool(rc.IS_PRODUCTION),
        'real_email_transport_connected':email_ready,'real_whatsapp_transport_connected':wa_ready,'reviewed_provider_submission_available':bool(email_ready or wa_ready),
        'shopify_sync_connected':shop_ready,'shopify_draft_write_available':shop_ready,'automatic_bulk_launch':False,'public_webhooks_ready':bool(integ._public_base_url())}

def prometheus_metrics():
    h=bos.system_health()
    vals={
      'commerce_crm_contacts':h.get('contacts',0),
      'commerce_crm_open_failures':h.get('open_failures',0),
      'commerce_crm_connected_integrations':h.get('connected',0),
      'commerce_crm_worker_jobs_queued':(m.one("SELECT count(*) n FROM v12_worker_jobs WHERE status IN ('Queued','Retry','Running')") or {'n':0})['n'] if m.table_exists('v12_worker_jobs') else 0,
      'commerce_crm_worker_jobs_dead_letter':(m.one("SELECT count(*) n FROM v12_worker_jobs WHERE status='DeadLetter'") or {'n':0})['n'] if m.table_exists('v12_worker_jobs') else 0,
      'commerce_crm_products':(m.one('SELECT count(*) n FROM products') or {'n':0})['n'],
      'commerce_crm_v13_events_pending':(m.one("SELECT count(*) n FROM v13_events WHERE status IN ('Pending','Retry')") or {'n':0})['n'] if m.table_exists('v13_events') else 0,
      'commerce_crm_v13_open_incidents':(m.one("SELECT count(*) n FROM v13_incidents WHERE status='Open'") or {'n':0})['n'] if m.table_exists('v13_incidents') else 0,
      'commerce_crm_v13_low_confidence_checks':(m.one("SELECT count(*) n FROM v13_quality_checks WHERE confidence='Low'") or {'n':0})['n'] if m.table_exists('v13_quality_checks') else 0,
      'commerce_crm_v13_ai_calls_today':(m.one("SELECT count(*) n FROM v13_ai_usage WHERE date(created_at)=date('now')") or {'n':0})['n'] if current_table_exists('v13_ai_usage') else 0,
    }
    return ''.join(f'{k} {int(v or 0)}\n' for k,v in vals.items())

class App(LaunchPages,V37BusinessPages,V27MarketingPages,ProcessOrchestratorPages,OwnerExperiencePages,HandoverPages,IntegrationV14Pages,OperatingPages,PlatformPages,IntegrationPages,BusinessOSPages,CreativeStudioPages,CreativePages,ProductEnginePages,FeaturePages,WorkspacePages,ContactPages,legacy.App):
    server_version='CommerceBusinessOS/'+APP_VERSION
    sys_version=''
    current_user=None

    def require_auth(self):
        if pc.auth_enabled():
            user=pc.session_user(self.headers.get('Cookie',''))
            if user:
                self.current_user=user;return True
            if self.command=='GET':
                self.redirect('/login');return False
            self.send_response(401);self.end_headers();return False
        self.current_user=None
        return super().require_auth()

    def authorised_for(self,path,method='GET'):
        if not pc.auth_enabled():return True
        return pc.can(self.current_user,pc.permission_for_path(path,method))

    def end_headers(self):
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('X-Frame-Options','DENY')
        self.send_header('Referrer-Policy','no-referrer')
        self.send_header('Cache-Control','no-store')
        self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self' https://connect.facebook.net; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob: https:; connect-src 'self' https://graph.facebook.com https://www.facebook.com https://web.facebook.com; frame-src 'self' https://www.facebook.com https://web.facebook.com; object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'")
        self.send_header('Permissions-Policy','camera=(), microphone=(), geolocation=(), payment=()')
        if rc.IS_PRODUCTION:self.send_header('Strict-Transport-Security','max-age=31536000; includeSubDomains')
        super().end_headers()

    def allowed_host(self):
        port=int(self.server.server_address[1])
        host_header=(self.headers.get('Host','') or '').strip()
        host_key=_canonical_host(host_header,'http')
        local_ok=bool((not rc.IS_PRODUCTION) and host_key and host_key[1]=='loopback')
        public=(rc.PUBLIC_BASE_URL or str(m.settings().get('public_base_url','') or '')).strip()
        public_key=_canonical_origin(public) if public else None
        public_host_ok=False
        if public_key:
            try:
                raw=urllib.parse.urlparse('http://'+host_header)
                host=(raw.hostname or '').lower().rstrip('.')
                hport=raw.port
                if hport is None:hport=443 if public_key[0]=='https' else 80
                public_host_ok=(host==public_key[1] and hport==public_key[2])
            except (ValueError,TypeError):
                public_host_ok=False
        if not (local_ok or public_host_ok):
            self.send_error(403,'Use the local address printed by this app or the configured public HTTPS host.');return False
        return True

    def send_html(self,s,code=200):
        csrf=csrf_token_for_cookie(self.headers.get('Cookie',''))
        s=re.sub(r'(<form\b[^>]*method=["\x27]post["\x27][^>]*>)',lambda match:match.group(1)+f'<input type="hidden" name="_csrf" value="{csrf}">',s,flags=re.I)
        super().send_html(s,code)

    def json_response(self,payload,code=200,attachment=''):
        raw=json.dumps(payload,ensure_ascii=False,indent=2).encode()
        self.send_response(code);self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Content-Length',str(len(raw)))
        if attachment:self.send_header('Content-Disposition',f'attachment; filename="{attachment}"')
        self.end_headers();self.wfile.write(raw)

    def error_page(self,text,code=400):
        path=urllib.parse.urlparse(self.path).path
        if path.startswith('/product-engine') or path.startswith('/product-workspace'):
            return_label,return_url,nav='Return to product workflow','/product-engine','product_engine'
        elif path.startswith('/campaign') or path.startswith('/creative') or path.startswith('/marketing') or path.startswith('/customer-journeys'):
            return_label,return_url,nav='Return to create marketing','/campaign-builder','campaigns'
        elif path.startswith('/operations'):
            return_label,return_url,nav='Return to operations centre','/operations','operations'
        elif path.startswith('/integrations') or path.startswith('/oauth'):
            return_label,return_url,nav='Return to business connections','/integrations','integrations'
        else:
            return_label,return_url,nav='Return to business control centre','/','dashboard'
        body=pagehead('Let\'s fix one thing','Your existing records have not been replaced.')+notice(text,'error')+f'<div class="section">{button(return_label,return_url,"secondary")} {button("Open settings","/settings","secondary")}</div>'
        return self.send_html(layout('Action needs attention',body,nav),code)

    def send_file(self,raw,filename,content_type='text/csv; charset=utf-8'):
        self.send_response(200); self.send_header('Content-Type',content_type)
        self.send_header('Content-Disposition','attachment; filename="'+filename+'"')
        self.send_header('Content-Length',str(len(raw))); self.end_headers(); self.wfile.write(raw)

    def form(self):
        if hasattr(self,'_parsed_form'):return self._parsed_form
        n=int(self.headers.get('Content-Length','0')); typ=self.headers.get('Content-Type','')
        limit=(520*1024*1024 if self.path in {'/product-engine/upload','/product-engine/upload-images'} else 32*1024*1024 if self.path=='/creative-studio/music' else 6*1024*1024 if self.path=='/creative/brand-logo' else ct.MAX_BYTES+65536 if self.path=='/imports/upload' else 13*1024*1024 if self.path=='/products/create' else 9*1024*1024 if self.path=='/products/import/preview' else 160000)
        if self.path in {'/launch/upload','/launch/photos'}:limit=80*1024*1024+65536
        if n>limit or n<0:raise ValueError('This upload or form exceeds its size limit.')
        raw=self.rfile.read(n)
        if typ.lower().startswith('multipart/form-data'):
            allowed={'/imports/upload':'contact_file','/products/create':'product_image','/products/import/preview':'product_csv','/product-engine/upload':'product_archives','/product-engine/upload-images':'product_images','/creative/brand-logo':'brand_logo','/creative-studio/music':'music_file'}
            allowed.update({'/launch/upload':'product_images','/launch/photos':'product_images'})
            if self.path not in allowed:raise ValueError('File upload is not supported on this form.')
            from email.parser import BytesParser
            from email import policy
            message=BytesParser(policy=policy.default).parsebytes(('Content-Type: '+typ+'\r\nMIME-Version: 1.0\r\n\r\n').encode()+raw)
            if not message.is_multipart():raise ValueError('Could not read this upload. Choose the file again.')
            result={}; upload=None; uploads=[]; expected=allowed[self.path]
            for part in message.iter_parts():
                name=part.get_param('name',header='content-disposition'); filename=part.get_filename()
                data=part.get_payload(decode=True) or b''
                if filename is not None and filename:
                    if name!=expected:raise ValueError('Unexpected file field in this form.')
                    if self.path in {'/product-engine/upload','/product-engine/upload-images','/launch/upload','/launch/photos'}:uploads.append((data,filename))
                    else:
                        if upload is not None:raise ValueError('Upload one file at a time.')
                        upload=(data,filename)
                elif name: result.setdefault(name,[]).append(data.decode('utf-8'))
            if self.path=='/imports/upload':self._contact_upload=upload
            elif self.path=='/products/create':self._product_upload=upload
            elif self.path=='/products/import/preview':self._product_csv_upload=upload
            elif self.path=='/product-engine/upload':self._product_archives=uploads
            elif self.path=='/product-engine/upload-images':self._product_images=uploads
            elif self.path=='/creative/brand-logo':self._brand_logo_upload=upload
            elif self.path=='/creative-studio/music':self._creative_music_upload=upload
            elif self.path in {'/launch/upload','/launch/photos'}:self._launch_images=uploads
            self._parsed_form=result
        else:
            self._parsed_form=urllib.parse.parse_qs(raw.decode('utf-8'),keep_blank_values=True)
        return self._parsed_form

    def do_GET(self):
        # Hosting platforms probe /health with an internal Host header; it returns no private data.
        if urllib.parse.urlparse(self.path).path!='/health' and not self.allowed_host():return
        p=urllib.parse.urlparse(self.path);q=urllib.parse.parse_qs(p.query);self.q=q
        if re.fullmatch(r'/webhooks/meta/[^/]+',p.path):
            try:
                cid=p.path.split('/')[-1];challenge=integ.verify_meta_webhook_challenge(cid,q.get('hub.mode',[''])[0],q.get('hub.verify_token',[''])[0],q.get('hub.challenge',[''])[0])
                raw=str(challenge).encode();self.send_response(200);self.send_header('Content-Type','text/plain; charset=utf-8');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw);return
            except ValueError as err:return self.json_response({'ok':False,'error':str(err)},403)
        if p.path=='/login':
            if not pc.auth_enabled():return self.redirect('/')
            return self.send_html(login_document(q.get('error',[''])[0]))
        if p.path=='/logout':
            pc.logout_cookie(self.headers.get('Cookie',''));self.send_response(303);self.send_header('Set-Cookie','crm_session=; Path=/; Max-Age=0; HttpOnly; SameSite=Strict');self.send_header('Location','/login');self.end_headers();return
        if p.path in {'/health','/ready'}:
            payload=health_payload();code=200 if p.path=='/health' or (payload['database_ready'] and not payload['production_configuration_gaps']) else 503
            return self.json_response(payload,code)
        if p.path=='/metrics':
            if rc.IS_PRODUCTION:
                supplied=self.headers.get('Authorization','')
                if not rc.MONITORING_TOKEN or supplied!='Bearer '+rc.MONITORING_TOKEN:return self.json_response({'error':'Monitoring token required.'},403)
            raw=prometheus_metrics().encode();self.send_response(200);self.send_header('Content-Type','text/plain; version=0.0.4; charset=utf-8');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw);return
        if not self.require_auth():return
        if not self.authorised_for(p.path,'GET'):return self.send_html(layout('Access denied',pagehead('Access denied','Your role does not have permission to open this area.')+notice('Ask an Owner or Administrator to change your role or perform this action.','warn'),'dashboard'),403)
        try:
            if p.path=='/new':
                recommended='<a class="create-primary" href="/launch"><span class="create-primary-icon">&#10024;</span><span><span class="create-kicker">Recommended starting point</span><strong>Launch a product from photos</strong><small>Prepare a listing, colours and sizes, studio photos and social posts in one guided workspace.</small></span><span class="create-arrow">&#8594;</span></a>'
                actions=''.join([
                    '<a class="create-card" href="/contacts/new"><span class="create-icon">&#9678;</span><strong>Add customer or lead</strong><small>Save a customer and create follow-up work.</small></a>',
                    '<a class="create-card" href="/campaign-builder"><span class="create-icon">&#10022;</span><strong>Create marketing campaign</strong><small>Choose the outcome and let the system prepare channel-specific content.</small></a>',
                    '<a class="create-card" href="/opportunities/new"><span class="create-icon">&#9672;</span><strong>Add sales opportunity</strong><small>Track a potential B2B or B2C sale.</small></a>',
                    '<a class="create-card" href="/tasks/new"><span class="create-icon">&#9719;</span><strong>Add task</strong><small>Record a follow-up or action for yourself or the team.</small></a>',
                    '<a class="create-card" href="/orders/new"><span class="create-icon">&#9776;</span><strong>Record order</strong><small>Add a real transaction or provider-confirmed order.</small></a>',
                    '<a class="create-card" href="/showrooms/new"><span class="create-icon">&#9671;</span><strong>Create customer selection</strong><small>Build a shareable product selection for a customer or prospect.</small></a>',
                    '<a class="create-card" href="/products/new"><span class="create-icon">&#9633;</span><strong>Enter product details manually</strong><small>Use this only when you already know the product facts.</small></a>'
                ])
                body=pagehead('What would you like to do?','Choose one action. The system will guide you through the rest.')+recommended+'<div class="create-section-head"><h2>Other common actions</h2><p>Everything else can be reached from the left navigation.</p></div><div class="create-grid">'+actions+'</div>'
                return self.send_html(layout('Create something',body,'today'))
            if self.launch_get(p.path,q):return
            if self.v37_get(p.path,q):return
            if self.v27_get(p.path,q):return
            if self.v17_get(p.path,q):return
            if self.v16_get(p.path,q):return
            if self.v15_get(p.path,q):return
            if self.v14_get(p.path,q):return
            if self.v13_get(p.path,q):return
            if self.v11_get(p.path,q):return
            if self.v10_get(p.path,q):return
            if self.v9_get(p.path,q):return
            if self.v8_get(p.path,q):return
            if self.v7_get(p.path,q):return
            if self.v6_get(p.path,q):return
            if self.v5_get(p.path,q):return
            if self.workspace_get(p.path,q):return
            if p.path=='/product-workflow':return self.redirect('/products')
            if p.path=='/audiences':return self.redirect('/audience-builder')
            if p.path=='/contacts/new':return self.contact_form()
            if re.fullmatch(r'/contacts/[^/]+/edit',p.path):return self.contact_form(p.path.split('/')[2])
            if p.path=='/imports':return self.imports_home()
            if p.path=='/imports/template.csv':return self.send_file(ct.csv_bytes([list(ct.FIELDS)]),'contact_import_template.csv')
            if p.path=='/imports/template.xlsx':return self.send_file((ROOT/'templates'/'contact_import.xlsx').read_bytes(),'contact_import_template.xlsx','application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
            if re.fullmatch(r'/imports/[^/]+/(report|rejected).csv',p.path):
                j=ct.job(p.path.split('/')[2]);r=json.loads(j['report'] or '{}')
                if not r:raise ValueError('Preview the import before downloading a report.')
                if p.path.endswith('/rejected.csv'):
                    headers=r.get('headers',[])
                    data=[headers+['Import row','Import issue']]
                    data += [(x.get('raw_cells',[])+['']*len(headers))[:len(headers)]+[x['row'],x['reason']] for x in r['rows'] if x['action'] in {'Invalid','Conflict'}]
                    return self.send_file(ct.csv_bytes(data),'rejected_contact_rows.csv')
                return self.send_file(ct.csv_bytes([['Row','Contact','Decision','Reason']]+[[x['row'],x['name'],x['action'],x['reason']] for x in r['rows']]),'contact_import_report.csv')
            if re.fullmatch(r'/imports/[^/]+',p.path):return self.import_detail(p.path.split('/')[2],q)
            if p.path=='/outreach':return self.outreach_library()
            if p.path=='/templates':return self.templates(q)
            if p.path.startswith('/templates/'):return self.templates(q,p.path.split('/')[2])
            if p.path=='/segments':return self.segments()
            if re.fullmatch(r'/campaigns/[^/]+/personalise',p.path):return self.campaign_personalise(p.path.split('/')[2])
            if p.path.startswith('/ui/'):
                name=p.path[len('/ui/'):]
                if name not in {'launch.css','launch.js','studio.css','studio.js','workspace.css','workspace.js','integrations_v14.js','v25.css','v28.css','v29.css','v30.css','v32.css','v33.css','v34.css','v45.css'}:return self.send_error(404)
                raw=(ROOT/'ui'/name).read_bytes();self.send_response(200);self.send_header('Content-Type','text/css' if name.endswith('.css') else 'application/javascript');self.send_header('Content-Length',str(len(raw)));self.send_header('Cache-Control','no-cache, max-age=0');self.end_headers();self.wfile.write(raw);return
            if p.path=='/api/audience':
                a=m.audience_preview({k:v[0] for k,v in q.items()})
                return self.json_response({k:a[k] for k in ['matching','eligible','suppressed','duplicates']} | {'selected':[{'name':ct.clean_display_name(c['full_name']) or c['username'],'type':c['contact_type'],'eligible':c['eligible'],'reason':c['eligibility_reason']} for c in a['selected']]})
            if p.path=='/knowledge':return self.knowledge(q)
            if p.path=='/tasks':return self.tasks(q)
            if p.path=='/campaigns/new':return self.new_campaign(q)
            if p.path.startswith('/campaigns/') and p.path.endswith('/export'):
                camid=p.path.split('/')[2];lifecycle.require_active_campaign(camid);drafts=m.rows('SELECT * FROM m4_drafts WHERE campaign_id=?',(camid,))
                allowed=[d for d in drafts if not m.draft_gate(d)]
                if not allowed:raise ValueError('No approved, currently eligible drafts to export. Preview drafts remain in your workspace.')
                return self.json_response({'warning':'Manual review handoff only. Nothing has been sent. Recheck opt-outs in your sending platform.',
                    'campaign':m.campaign(camid)['campaign_name'],'messages':[{'contact_id':d['contact_id'],'channel':d['channel'],'subject':d['subject'],'body':d['body'],'step':d['step'],'suggested_day':d['day_offset']} for d in allowed]},attachment='reviewed_campaign_drafts.json')
            return super().do_GET()
        except ValueError as err:
            if p.path=='/api/audience':return self.json_response({'error':str(err)},400)
            return self.error_page(str(err))
        except ModuleNotFoundError as err:
            if getattr(err,'name','') in {'PIL','cryptography'} or str(getattr(err,'name','')).startswith(('PIL.','cryptography.')):
                return self.error_page('This optional image or secure-connector capability needs the full local runtime. Run PREPARE_FULL_RUNTIME.command while online, then retry. Your existing records were not changed.',503)
            raise
        except Exception as err:
            if db_layer.is_database_error(err):return self.error_page('A database operation could not finish. Your existing records have not been replaced. Keep this window open and report which button you clicked.',500)
            raise

    def do_POST(self):
        p=urllib.parse.urlparse(self.path)
        if p.path=='/login':
            if not self.allowed_host():return
            f=self.form();v=lambda k,default='':f.get(k,[default])[0]
            try:
                _,token=pc.authenticate(v('email'),v('password'),self.client_address[0] if self.client_address else 'local',v('otp'));self.send_response(303);cookie='crm_session='+token+'; Path=/; HttpOnly; SameSite=Lax; Max-Age=43200';
                if rc.COOKIE_SECURE or (m.settings().get('public_base_url') or '').startswith('https://'):cookie+='; Secure'
                self.send_header('Set-Cookie',cookie);self.send_header('Location','/');self.end_headers();return
            except ValueError as err:return self.send_html(login_document(str(err)),401)
        # Provider webhooks are intentionally outside browser auth/CSRF, but only cryptographically verified handlers accept them.
        if re.fullmatch(r'/webhooks/(resend|meta|shopify)/[^/]+',p.path):
            if not self.allowed_host():return
            try:
                n=int(self.headers.get('Content-Length','0'))
                if n<1 or n>4*1024*1024:raise ValueError('Webhook body size is invalid.')
                raw=self.rfile.read(n);parts=p.path.split('/');provider=parts[2];cid=parts[3];headers={k:v for k,v in self.headers.items()}
                if provider=='resend':out=integ.handle_resend_webhook(cid,raw,headers)
                elif provider=='meta':out=integ.handle_whatsapp_webhook(cid,raw,headers)
                else:out=integ.handle_shopify_webhook(cid,raw,headers)
                return self.json_response(out,200)
            except ValueError as err:return self.json_response({'ok':False,'error':str(err)},400)
            except Exception:return self.json_response({'ok':False,'error':'Webhook processing failed safely.'},500)
        if not self.allowed_host():return
        if not self.require_auth():return
        if not self.authorised_for(p.path,'POST'):return self.send_html(layout('Access denied',pagehead('Access denied','Your role cannot perform this action.')+notice('Ask an Owner or Administrator for the required permission.','warn'),'dashboard'),403)
        try:
            f=self.form();v=lambda k,default='':f.get(k,[default])[0]
            origin=(self.headers.get('Origin') or '').strip()
            host=(self.headers.get('Host','') or '').strip()
            public=(rc.PUBLIC_BASE_URL or m.settings().get('public_base_url') or '').strip()
            port=int(self.server.server_address[1])
            # V19: validate the per-form CSRF secret first. In local single-user
            # mode the server is bound to loopback and allowed_host() has already
            # verified the request Host. Browser extensions/privacy tooling can
            # rewrite or suppress Origin, so Origin is advisory for loopback POSTs.
            # Production remains strict: the browser Origin must exactly match the
            # configured public HTTPS origin.
            if not secrets.compare_digest(v('_csrf'),csrf_token_for_cookie(self.headers.get('Cookie',''))):
                raise ValueError('This form expired or belongs to another signed-in session. Refresh the page and try again.')
            host_key=_canonical_host(host,'http')
            local_loopback=bool((not rc.IS_PRODUCTION) and host_key and host_key[1]=='loopback')
            # Local mode trust boundary = loopback Host + unguessable per-process/session
            # CSRF token. We intentionally do not reject a valid local POST because a
            # browser extension/privacy feature rewrote, suppressed or made Origin
            # opaque. Production keeps exact public-origin enforcement.
            if local_loopback:
                # Preserve defence-in-depth against a normal external web origin,
                # while tolerating opaque/extension Origin values produced by local
                # browser privacy tooling. The CSRF token above remains mandatory.
                origin_key=_canonical_origin(origin) if origin else None
                if origin_key and origin_key[0] in {'http','https'} and origin_key[1] != 'loopback':
                    print(f'[security] blocked external browser origin={origin!r} host={host!r}',flush=True)
                    raise ValueError('Cross-site request blocked. Refresh the CRM at the address opened by this release and try again.')
            elif not _origin_is_allowed(origin,host,port,public,local_mode=False):
                print(f'[security] blocked browser origin={origin!r} host={host!r} port={port} public={public!r}',flush=True)
                raise ValueError('Cross-site request blocked. Refresh the CRM at the address opened by this release and try again.')
            if self.launch_post(p.path,f):return
            if self.v27_post(p.path,f):return
            if self.v17_post(p.path,f):return
            if self.v16_post(p.path,f):return
            if self.v15_post(p.path,f):return
            if self.v14_post(p.path,f):return
            if self.v13_post(p.path,f):return
            if self.v11_post(p.path,f):return
            if self.v10_post(p.path,f):return
            if self.v9_post(p.path,f):return
            if self.v8_post(p.path,f):return
            if self.v7_post(p.path,f):return
            if self.v6_post(p.path,f):return
            if self.v5_post(p.path,f):return
            if self.workspace_post(p.path,f):return
            if p.path=='/campaigns/bulk/archive':
                selected=f.get('campaign_ids',[])
                count=lifecycle.bulk_archive_campaigns(selected)
                return self.redirect('/campaigns?view=active&bulk_archived='+str(count))
            if p.path=='/campaigns/bulk/restore':
                selected=f.get('campaign_ids',[])
                count=lifecycle.bulk_restore_campaigns(selected)
                return self.redirect('/campaigns?view=archived&bulk_restored='+str(count))
            if re.fullmatch(r'/campaigns/[^/]+/duplicate',p.path):
                camid=p.path.split('/')[2];new_id=m.duplicate_campaign(camid)
                return self.redirect('/campaigns/'+new_id+'?duplicated=1')
            if re.fullmatch(r'/campaigns/[^/]+/pause',p.path):
                camid=p.path.split('/')[2];lifecycle.pause_campaign(camid)
                return self.redirect('/campaigns/'+camid+'?paused=1')
            if re.fullmatch(r'/campaigns/[^/]+/resume',p.path):
                camid=p.path.split('/')[2];lifecycle.resume_campaign(camid)
                return self.redirect('/campaigns/'+camid+'?resumed=1')
            if re.fullmatch(r'/campaigns/[^/]+/archive',p.path):
                camid=p.path.split('/')[2];lifecycle.archive_campaign(camid)
                return self.redirect('/campaigns?view=active&archived=1')
            if re.fullmatch(r'/campaigns/[^/]+/restore',p.path):
                camid=p.path.split('/')[2];lifecycle.restore_campaign(camid)
                return self.redirect('/campaigns/'+camid+'?restored=1')
            if p.path=='/products/bulk/archive':
                selected=f.get('product_ids',[])
                if not selected:return self.redirect('/products?view=active&bulk_error=select')
                count=v24.archive_products(selected)
                return self.redirect('/products?view=active&bulk_archived='+str(count))
            if p.path=='/products/bulk/category':
                selected=f.get('product_ids',[])
                if not selected:return self.redirect('/products?view=active&bulk_error=select')
                count=pe.bulk_set_category(selected,v('category'))
                return self.redirect('/products?view=active&bulk_category='+str(count)+'&category_name='+query(v('category')))
            if p.path=='/products/bulk/collection':
                selected=f.get('product_ids',[])
                if not selected:return self.redirect('/products?view=active&bulk_error=select')
                result=truth.assign_products_to_collection(selected,v('collection_name'))
                return self.redirect('/products?view=active&bulk_collection='+str(result['count'])+'&collection_name='+query(result['name']))
            if p.path=='/products/bulk/restore':
                selected=f.get('product_ids',[])
                if not selected:return self.redirect('/products?view=archived&bulk_error=select')
                count=lifecycle.bulk_restore_products(selected)
                return self.redirect('/products?view=archived&bulk_restored='+str(count))
            if p.path=='/products/bulk/delete':
                selected=f.get('product_ids',[])
                if not selected:return self.redirect('/products?view=archived&bulk_error=select')
                if v('confirm_delete')!='DELETE':raise ValueError('Type DELETE before permanently deleting unused archived products.')
                result=lifecycle.bulk_delete_products(selected)
                return self.redirect('/products?view=archived&bulk_deleted='+str(result['deleted'])+'&bulk_blocked='+str(len(result['blocked'])))
            if re.fullmatch(r'/products/[^/]+/duplicate',p.path):
                pid=p.path.split('/')[2];new_id=v24.duplicate_product(pid)
                return self.redirect('/products/'+new_id+'?duplicated=1')
            if re.fullmatch(r'/products/[^/]+/archive',p.path):
                pid=p.path.split('/')[2];lifecycle.archive_product(pid)
                return self.redirect('/products?view=active&archived=1')
            if re.fullmatch(r'/products/[^/]+/restore',p.path):
                pid=p.path.split('/')[2];lifecycle.restore_product(pid)
                return self.redirect('/products/'+pid+'?restored=1')
            if re.fullmatch(r'/products/[^/]+/delete',p.path):
                pid=p.path.split('/')[2]
                if v('confirm_delete')!='DELETE':raise ValueError('Type DELETE before permanently deleting this unused archived product.')
                lifecycle.delete_product(pid)
                return self.redirect('/products?view=archived&deleted=1')
            if re.fullmatch(r'/showrooms/[^/]+/archive',p.path):
                sid=p.path.split('/')[2];lifecycle.archive_showroom(sid)
                return self.redirect('/showrooms?view=active&archived=1')
            if re.fullmatch(r'/showrooms/[^/]+/restore',p.path):
                sid=p.path.split('/')[2];lifecycle.restore_showroom(sid)
                return self.redirect('/showrooms/'+sid+'?restored=1')
            if re.fullmatch(r'/showrooms/[^/]+/delete',p.path):
                sid=p.path.split('/')[2]
                if v('confirm_delete')!='DELETE':raise ValueError('Type DELETE in the confirmation field before permanently removing this unused showroom.')
                lifecycle.delete_showroom(sid)
                return self.redirect('/showrooms?deleted=1')
            if re.fullmatch(r'/showrooms/[^/]+/details',p.path):
                sid=p.path.split('/')[2];v24.save_showroom_details(sid,{k:x[0] for k,x in f.items()})
                return self.redirect('/showrooms/'+sid+'?operations_saved=1')
            if re.fullmatch(r'/showrooms/[^/]+/(activate|deactivate)',p.path):
                sid=p.path.split('/')[2];v24.set_showroom_active(sid,p.path.endswith('/activate'))
                return self.redirect('/showrooms/'+sid+'?state_saved=1')
            if re.fullmatch(r'/showrooms/[^/]+/update',p.path):
                sid=p.path.split('/')[2];current=lifecycle.showroom(sid)
                if current.get('status')=='Archived':raise ValueError('Restore this showroom before editing it.')
                cid=v('contact_id');ids=list(dict.fromkeys(f.get('product_ids',[])))
                valid={x['product_id'] for x in m.products()}
                if not ids or any(x not in valid for x in ids):raise ValueError('Choose at least one active product for the showroom.')
                if cid:m.contact(cid)
                pricing=v('pricing_mode','Hidden')
                if pricing not in {'Hidden','Retail','Wholesale'}:raise ValueError('Choose a pricing mode.')
                title=v('title').strip()
                if not title:raise ValueError('Give the showroom a title.')
                with m.connect() as con:
                    con.execute('''UPDATE showrooms SET contact_id=?,title=?,pricing_mode=?,intro_text=?,cta_text=? WHERE showroom_id=?''',
                                (cid or None,title[:180],pricing,v('intro_text')[:2000],v('cta_text','Ask about this piece')[:100],sid))
                    con.execute('DELETE FROM showroom_products WHERE showroom_id=?',(sid,))
                    con.executemany('INSERT INTO showroom_products(showroom_id,product_id,sort_order) VALUES(?,?,?)',[(sid,pid,i) for i,pid in enumerate(ids)])
                m.audit('showroom.updated',sid,'Owner changed showroom details/product selection.')
                return self.redirect('/showrooms/'+sid+'?saved=1')
            if p.path=='/contacts/save':
                cid=ct.save_contact({k:x[0] for k,x in f.items()},v('contact_id') or None)
                return self.redirect('/contacts/'+cid+'?saved=1')
            if p.path=='/imports/upload':
                upload=getattr(self,'_contact_upload',None)
                if not upload:raise ValueError('Choose a CSV, TSV or XLSX contact file.')
                jid=ct.stage_import(*upload);return self.redirect('/imports/'+jid)
            if re.fullmatch(r'/imports/[^/]+/preview',p.path):
                jid=p.path.split('/')[2]
                mapping={k[4:]:x[0] for k,x in f.items() if k.startswith('map_') and k[4:].isdigit() and x[0]}
                ct.prepare(jid,mapping,{k:v(k) for k in ['source','tags','default_type','policy']})
                return self.redirect('/imports/'+jid)
            if re.fullmatch(r'/imports/[^/]+/commit',p.path):
                if v('confirm')!='1':raise ValueError('Review and confirm the import first.')
                jid=p.path.split('/')[2];ct.apply_import(jid);return self.redirect('/imports/'+jid)
            if re.fullmatch(r'/imports/[^/]+/cancel',p.path):
                ct.cancel_import(p.path.split('/')[2]);return self.redirect('/imports')
            if p.path=='/templates/save':
                tid=o.save_template({k:x[0] for k,x in f.items()});return self.redirect('/templates/'+tid)
            if p.path=='/segments/preview':
                filt=m.normal_filters({k:x[0] for k,x in f.items()})
                return self.segments(preview={'filters':filt,'result':m.audience_preview(filt)})
            if p.path=='/segments/save':
                name=v('name').strip()
                if not name:raise ValueError('Give this audience a name.')
                filt=m.normal_filters({k:x[0] for k,x in f.items()})
                with m.connect() as con:con.execute('INSERT INTO m41_segments(id,name,filters) VALUES(?,?,?)',(m.uid('SEG'),name[:180],json.dumps(filt)))
                return self.redirect('/segments')
            if re.fullmatch(r'/campaigns/[^/]+/personalise',p.path):
                camid=p.path.split('/')[2];cam=lifecycle.require_active_campaign(camid)
                with m.connect() as con:o.store(con,camid,{k:x[0] for k,x in f.items()},cam['audience_type'],cam['channel'])
                m.audit('campaign.personalisation',camid,'Old drafts retained; regeneration and reapproval needed')
                return self.redirect('/campaigns/'+camid)
            if p.path=='/campaigns/create':
                camid=m.create_campaign({k:x[0] for k,x in f.items()},f.get('product_ids',[]));return self.redirect('/campaigns/'+camid)
            if p.path.startswith('/campaigns/') and p.path.endswith('/generate'):
                camid=p.path.split('/')[2];cid=v('contact_id')
                m.generate(camid,cid,v('engine','local'),v('ai_consent')=='1',v('replace')=='1')
                return self.redirect('/campaigns/'+camid+'?contact='+query(cid)+'&generated=1')
            if p.path.startswith('/campaigns/') and p.path.endswith('/batch-local'):
                camid=p.path.split('/')[2]
                # At most ten selected recipients; never replace existing drafts silently.
                made=0
                for c in m.rows('SELECT contact_id FROM campaign_members WHERE campaign_id=? ORDER BY added_at,contact_id LIMIT 10',(camid,)):
                    if not m.one('SELECT id FROM m4_drafts WHERE campaign_id=? AND contact_id=?',(camid,c['contact_id'])):
                        try:made+=m.generate(camid,c['contact_id'],'local')
                        except ValueError:pass
                return self.redirect('/campaigns/'+camid+'?batch='+str(made))
            if p.path.startswith('/campaigns/') and p.path.endswith('/populate'):
                raise ValueError('V3 bulk population is replaced by the guided campaign builder. Create a new campaign to review audience and permissions first.')
            if p.path.startswith('/drafts/') and p.path.endswith('/save'):
                did=p.path.split('/')[2];d=m.one('SELECT * FROM m4_drafts WHERE id=?',(did,))
                if not d:raise ValueError('Draft not found.')
                m.update_draft(did,v('subject'),v('body'),v('action')=='approve',v('confirmed')=='1')
                return self.redirect('/campaigns/'+d['campaign_id']+'?contact='+query(d['contact_id'])+'&saved=1')
            if p.path.startswith('/drafts/') and p.path.endswith('/handoff'):
                did=p.path.split('/')[2];d=m.one('SELECT * FROM m4_drafts WHERE id=?',(did,))
                if not d:raise ValueError('Draft not found.')
                issues=m.draft_gate(d)
                if issues:raise ValueError('Handoff blocked: '+ '; '.join(issues))
                c=m.contact(d['contact_id'])
                if d['channel']=='Email':
                    url='mailto:'+query(c['email'])+'?'+urllib.parse.urlencode({'subject':d['subject'],'body':d['body']})
                    label='Open in your email app'
                elif d['channel']=='WhatsApp':
                    url='https://wa.me/'+m.endpoint(c,'WhatsApp')+'?'+urllib.parse.urlencode({'text':d['body']})
                    label='Open in WhatsApp'
                else:
                    raise ValueError('SMS and phone scripts are planning-only. No SMS sender or dialler is connected; no message or call was made.')
                m.audit('draft.handoff_prepared',did,'Not sent; delivery has not been verified')
                body=pagehead('Your reviewed draft is ready','This opens a draft, not an automatically sent message.')
                body+=notice('Double-check the recipient and your sending account in the external app. The CRM cannot observe delivery or replies from this handoff. Log actual activity separately.')
                body+='<div class="card section"><h2>'+e(ct.clean_display_name(c['full_name']) or c['username'])+'</h2><p class="helper">'+e(m.endpoint(c,d['channel']))+'</p><pre class="kb-text">'+e(d['body'])+'</pre><a class="btn" target="_blank" rel="noopener noreferrer" href="'+e(url)+'">'+label+'</a></div><div class="section">'+button('Back to campaign','/campaigns/'+d['campaign_id']+'?contact='+query(d['contact_id']),'secondary')+'</div>'
                return self.send_html(layout('Draft handoff',body,'campaigns'))
            if p.path=='/knowledge/save':
                title=v('title').strip();content=v('content').strip();source=v('source').strip();status='Approved' if v('approved')=='1' else 'Draft'
                if not title or not content:raise ValueError('Knowledge needs a title and content.')
                if len(content)>12000 or len(source)>1000:raise ValueError('Keep each knowledge note under 12,000 characters.')
                if status=='Approved' and not source:raise ValueError('Add the source or internal evidence before approving facts.')
                audience=v('audience','Both')
                if audience not in {'Both','B2B','B2C'}:raise ValueError('Choose a valid audience.')
                kid=v('id') or m.uid('KNOW')
                with m.connect() as con:
                    con.execute('''INSERT INTO m4_knowledge(id,title,category,audience,content,source,status) VALUES(?,?,?,?,?,?,?)
                    ON CONFLICT(id) DO UPDATE SET title=excluded.title,category=excluded.category,audience=excluded.audience,
                    content=excluded.content,source=excluded.source,status=excluded.status,updated_at=CURRENT_TIMESTAMP''',
                    (kid,title[:180],v('category')[:100],audience,content,source,status))
                m.audit('knowledge.saved',kid,status);return self.redirect('/knowledge?saved=1')
            if p.path=='/knowledge/archive':
                with m.connect() as con:con.execute("UPDATE m4_knowledge SET status='Archived',updated_at=CURRENT_TIMESTAMP WHERE id=?",(v('id'),))
                m.audit('knowledge.archived',v('id'));return self.redirect('/knowledge')
            if p.path=='/preferences/save':
                cid=v('contact_id');m.contact(cid)
                if (v('verified')=='1' or v('country_verified')=='1') and not v('evidence').strip():raise ValueError('Add where this preference came from before marking it confirmed.')
                with m.connect() as con:
                    con.execute('''INSERT INTO m4_preferences(contact_id,preferences,evidence,verified,country_verified) VALUES(?,?,?,?,?)
                    ON CONFLICT(contact_id) DO UPDATE SET preferences=excluded.preferences,evidence=excluded.evidence,
                    verified=excluded.verified,country_verified=excluded.country_verified,updated_at=CURRENT_TIMESTAMP''',
                    (cid,v('preferences')[:1500],v('evidence')[:500],int(v('verified')=='1'),int(v('country_verified')=='1')))
                return self.redirect('/contacts/'+cid)
            if p.path=='/products/review':
                pid=v('product_id')
                if not m.one('SELECT product_id FROM products WHERE product_id=?',(pid,)):raise ValueError('Product not found.')
                confirmed=int(v('confirmed')=='1')
                if confirmed and not v('evidence').strip():raise ValueError('Record your source for these product facts.')
                with m.connect() as con:
                    con.execute('''INSERT INTO m4_product_review(product_id,confirmed,evidence) VALUES(?,?,?)
                    ON CONFLICT(product_id) DO UPDATE SET confirmed=excluded.confirmed,evidence=excluded.evidence,updated_at=CURRENT_TIMESTAMP''',(pid,confirmed,v('evidence')[:1000]))
                m.audit('product.reviewed',pid,'Confirmed' if confirmed else 'Needs review');return self.redirect('/products/'+pid)
            if p.path=='/ai/save':
                model=v('model',m.settings().get('ai_model','gpt-6-luna')).strip()
                if v('api_key').strip():m.save_secret(v('api_key').strip())
                m.configure_marketing_model(model)
                m.audit('ai.configuration','','Key not logged; connection must be tested before AI generation');return self.redirect('/settings?ai_saved=1#ai')
            if p.path=='/ai/test':
                result=m.test_ai_connection()
                m.audit('ai.connection_test','',result.get('status',''))
                return self.redirect('/settings?ai_test='+query(result.get('status',''))+'#ai')
            if p.path=='/ai/test-all':
                matrix=ai_router.capability_matrix(force=True)
                ready=sum(1 for x in matrix if x.get('ready'))
                m.audit('ai.capability_test','',f'{ready}/{len(matrix)} capabilities ready')
                return self.redirect('/settings?ai_matrix='+query(str(ready))+'&ai_total='+query(str(len(matrix)))+'#ai')
            if p.path=='/ai/disconnect':
                if m.SECRET_PATH.exists():m.SECRET_PATH.unlink()
                try:
                    if os.environ.get('OPENAI_API_KEY','').strip():
                        m.set_ai_health('Untested','The app-stored key was removed, but an OPENAI_API_KEY environment variable is still available. Test the connection before AI generation.')
                    else:
                        m.set_ai_health('Not connected','No API key is stored.')
                except Exception:pass
                return self.redirect('/settings#ai')
            if p.path=='/permissions/update':
                cid=v('contact_id');m.contact(cid);channel=v('channel');status=v('status')
                if channel not in {'Email','WhatsApp','Phone','SMS','Other'} or status not in {'Unknown','Allowed','OptedIn','OptedOut','Suppressed','DoNotContact'}:raise ValueError('Choose a supported channel and status.')
                if status in {'Allowed','OptedIn'} and not all(v(x).strip() for x in ['reason','evidence','jurisdiction']):raise ValueError('Document the basis, evidence and jurisdiction. A public profile is not proof of permission.')
                with m.connect() as con:
                    old=[dict(r) for r in con.execute('SELECT * FROM marketing_permissions WHERE contact_id=? AND channel=?',(cid,channel))]
                    con.execute('INSERT INTO m4_audit(id,action,object_id,detail) VALUES(?,?,?,?)',(m.uid('AUD'),'permission.previous_version',cid,json.dumps(old)))
                    con.execute('DELETE FROM marketing_permissions WHERE contact_id=? AND channel=?',(cid,channel))
                    con.execute('''INSERT INTO marketing_permissions(permission_id,contact_id,channel,status,lawful_basis_or_reason,evidence_reference,jurisdiction)
                    VALUES(?,?,?,?,?,?,?)''',(m.uid('PER'),cid,channel,status,v('reason')[:1000],v('evidence')[:1000],v('jurisdiction')[:100]))
                    import crm_workspace
                    crm_workspace.history(con,'Contact',cid,'Channel permission reviewed',{'channel':channel,'previous':old},{'channel':channel,'status':status,'evidence':v('evidence')[:1000]})
                return self.redirect('/contacts/'+cid)
            if p.path=='/tasks/create':
                title=v('title').strip();due=v('due_date')
                if not title:raise ValueError('Give the task a name.')
                try:dt.date.fromisoformat(due)
                except ValueError:raise ValueError('Choose a valid date for the task.')
                with m.connect() as con:con.execute('INSERT INTO m4_tasks(id,title,contact_id,campaign_id,due_date) VALUES(?,?,?,?,?)',
                    (m.uid('TASK'),title[:200],v('contact_id') or None,v('campaign_id') or None,due))
                return self.redirect('/tasks')
            if p.path=='/tasks/complete':
                with m.connect() as con:con.execute("UPDATE m4_tasks SET status='Done' WHERE id=?",(v('id'),))
                return self.redirect('/tasks')
            if p.path.startswith('/contacts/') and p.path.endswith('/create-company'):
                cid=p.path.split('/')[2]
                if m.one('SELECT company_id FROM contact_companies WHERE contact_id=?',(cid,)):return self.redirect('/companies')
                c=ct.profile(cid)
                if c['contact_type'] not in {'B2B','Both'}:raise ValueError('Choose B2B or Both for a business account.')
                name=c.get('company_name') or ct.clean_display_name(c['full_name']) or c['username']
                company_id=m.uid('CMP')
                with m.connect() as con:
                    con.execute('INSERT INTO companies(company_id,company_name,website,country,company_type) VALUES(?,?,?,?,?)',(company_id,name,c['website'],c['country'],c['business_category'] or 'Unreviewed'))
                    con.execute('INSERT INTO contact_companies(contact_id,company_id,role_title,is_primary) VALUES(?,?,?,1)',(cid,company_id,c.get('role_title') or 'Primary contact'))
                return self.redirect('/companies')
            if p.path.startswith('/products/') and p.path.endswith('/cost'):
                pid=p.path.split('/')[2]
                current=lifecycle.product(pid)
                raw=v('cost_price').strip()
                currency=v('cost_currency',current.get('cost_currency') or current.get('currency') or m.settings().get('default_currency','INR')).strip()
                if currency not in {'INR','GBP','USD','EUR'}:raise ValueError('Choose INR, GBP, USD or EUR for product cost.')
                if raw:
                    try: cost=float(raw)
                    except ValueError: raise ValueError('Enter a valid product cost.') from None
                    if cost<0 or cost>1e9:raise ValueError('Use a non-negative, reasonable product cost.')
                else:
                    cost=None
                before=truth.product_cost(pid)
                truth.set_product_cost(pid,cost,currency,'Owner entry',note='Updated from Product review')
                after=truth.product_cost(pid)
                with m.connect() as con:
                    import crm_workspace as cw
                    cw.history(con,'Product',pid,'Product cost updated',before,after)
                return self.redirect('/products/'+pid+'?cost_saved=1')
            if p.path.startswith('/products/') and p.path.endswith('/update'):
                pid=p.path.split('/')[2];current=lifecycle.product(pid)
                if current.get('status')=='Archived' and v('status')!='Archived':raise ValueError('Restore this product before changing its active status.')
                if current.get('status')!='Archived' and v('status') not in {'Draft','Active','Sold Out'}:raise ValueError('Choose Draft, Active or Sold Out. Use Archive product to remove it from active workflows.')
                for k in ['retail_price','wholesale_price','moq']:
                    if v(k):
                        try:value=float(v(k))
                        except ValueError:raise ValueError('Price, stock and minimum quantity must be numbers.')
                        if value<0 or value>1e9:raise ValueError('Use a non-negative, reasonable price or quantity.')
                        if k=='moq' and not value.is_integer():raise ValueError('Minimum quantity must be a whole number.')
                title=v('public_product_name').strip()
                if not title:raise ValueError('Enter a customer-facing product title.')
                def optional_number(key):
                    raw=v(key).strip()
                    return None if raw=='' else float(raw)
                before=dict(current)
                with m.connect() as con:
                    con.execute('''UPDATE products SET public_product_name=?,product_code=?,colour=?,fabric=?,weave_or_motif=?,category=?,
                                   retail_price=?,wholesale_price=?,currency=?,moq=?,status=?,description=?,tags=? WHERE product_id=?''',
                                (title,v('product_code').strip()[:80],v('colour').strip()[:100],v('fabric').strip()[:180],v('weave_or_motif').strip()[:180],
                                 v('category').strip()[:120],optional_number('retail_price'),optional_number('wholesale_price'),v('currency','INR'),
                                 int(float(v('moq'))) if v('moq') else None,v('status'),v('description')[:5000],v('tags')[:1000],pid))
                    con.execute('UPDATE m4_product_review SET confirmed=0 WHERE product_id=?',(pid,))
                    import crm_workspace as cw
                    after=dict(con.execute('SELECT * FROM products WHERE product_id=?',(pid,)).fetchone())
                    cw.history(con,'Product',pid,'Product details updated',before,after)
                # Stock is intentionally absent from this mutation. It can only be
                # changed through canonical Stock & Locations workflows.
                return self.redirect('/products/'+pid+'?saved=1')
            if p.path.startswith('/contacts/') and p.path.endswith('/update'):
                if v('contact_type') not in {'B2B','B2C','Both','Unknown'}:raise ValueError('Choose a contact type.')
                if v('qualification_status') not in {'Unreviewed','Qualified','Needs Review','Irrelevant','Do Not Contact'}:raise ValueError('Choose a qualification status.')
            if p.path=='/settings/update':
                if v('public_base_url') and not m.valid_https(v('public_base_url')):raise ValueError('Public URL must be a real HTTPS address, or leave it blank. This does not deploy your app.')
                if v('booking_url') and not m.valid_https(v('booking_url')):raise ValueError('Booking link must use HTTPS, or leave it blank.')
            if p.path=='/showrooms/create':
                # Strong random URL identifier instead of the old six-character suffix; local only regardless.
                cid=v('contact_id');ids=list(dict.fromkeys(f.get('product_ids',[])))
                valid={x['product_id'] for x in m.products()}
                if not ids or any(x not in valid for x in ids):raise ValueError('Choose existing products for the showroom.')
                if cid:m.contact(cid)
                pricing=v('pricing_mode','Hidden')
                if pricing not in {'Hidden','Retail','Wholesale'}:raise ValueError('Choose a pricing mode.')
                sid=m.uid('SHR');slug=secrets.token_urlsafe(24)
                with m.connect() as con:
                    con.execute('''INSERT INTO showrooms(showroom_id,contact_id,slug,title,pricing_mode,status,intro_text,cta_text,public_enabled)
                    VALUES(?,?,?,?,?,'Active',?,?,1)''',(sid,cid or None,slug,v('title','A collection selected for you')[:180],pricing,v('intro_text')[:2000],v('cta_text','Ask about this piece')[:100]))
                    con.executemany('INSERT INTO showroom_products(showroom_id,product_id,sort_order) VALUES(?,?,?)',[(sid,pid,i) for i,pid in enumerate(ids)])
                return self.redirect('/showrooms/'+sid)
            return super().do_POST()
        except (ValueError,UnicodeError) as err:return self.error_page(str(err))
        except ModuleNotFoundError as err:
            if getattr(err,'name','') in {'PIL','cryptography'} or str(getattr(err,'name','')).startswith(('PIL.','cryptography.')):
                return self.error_page('This optional image or secure-connector capability needs the full local runtime. Run PREPARE_FULL_RUNTIME.command while online, then retry. Your existing records were not changed.',503)
            raise
        except Exception as err:
            if db_layer.is_database_error(err):return self.error_page('That change could not be saved. Check that all selected contacts and products still exist, then refresh and retry.',500)
            raise

    def classic_dashboard(self):
        stats=m.one('''SELECT count(*) contacts, coalesce(sum(CASE WHEN contact_type='B2B' THEN 1 ELSE 0 END),0) b2b, coalesce(sum(CASE WHEN contact_type='B2C' THEN 1 ELSE 0 END),0) b2c, coalesce(sum(CASE WHEN contact_type='Both' THEN 1 ELSE 0 END),0) both, coalesce(sum(CASE WHEN contact_type='Unknown' OR contact_type IS NULL THEN 1 ELSE 0 END),0) unknown FROM contacts''')
        drafts=m.one('SELECT count(*) n FROM m4_drafts')['n'];campaigns=m.one("SELECT count(*) n FROM campaigns WHERE coalesce(status,'Draft')<>'Archived'")['n']
        knowledge=m.one("SELECT count(*) n FROM m4_knowledge WHERE status='Approved'")['n']
        confirmed=sum(bool(p['confirmed']) for p in m.products());ss=m.settings()
        pr=m.products();images=''.join(f'<img class="mini-product" alt="Sample saree" src="/{e(p["img"])}">' for p in [pr[0],pr[1],pr[-1]] if p.get('img')) if pr else ''
        body=pagehead('A clearer day. A better campaign.','Your products, audiences and next actions, in one place.',button('Add contact','/contacts/new','secondary')+button('Import contacts','/imports','secondary')+button('Create campaign &rarr;','/campaigns/new'))
        body+=f'''<div class="hero-panel"><div class="hero-copy"><div class="eyebrow">Made for your saree business</div><h2>From beautiful pieces<br>to personal conversations.</h2><p>Choose who you want to reach. Build from the facts you trust. Review every message before it leaves your workspace.</p><div class="actions">{button('Build my first campaign &rarr;','/campaigns/new','light')}{button('Add brand knowledge','/knowledge','ghost')}</div><span class="hero-chip">B2B + B2C journeys &nbsp; / &nbsp; No automatic sending</span></div><div class="hero-visual">{images}</div></div>'''
        body+='<div class="grid">'
        for label,value,hint,symbol in [('Your contacts',f'{stats["contacts"]:,}',f'{stats["b2b"]:,} B2B / {stats["b2c"]:,} B2C / {stats["both"]:,} Both / {stats["unknown"]:,} Unknown','&#9678;'),('Campaign plans',campaigns,'Draft planning, not sent campaigns','&#10022;'),('Personalised drafts',drafts,'Local or AI generated; review required','&#9998;'),('Approved knowledge',knowledge,f'{confirmed} of {len(pr)} products fact-checked','&#9636;')]:
            body+=f'<div class="card stat"><div class="stat-top"><div class="label">{label}</div><span class="stat-symbol">{symbol}</span></div><div class="value">{value}</div><div class="hint">{hint}</div></div>'
        body+='</div><div class="two section"><div><div class="section-head"><h2>Choose your next conversation</h2><a href="/campaigns">Campaign studio &rarr;</a></div><div class="campaign-grid">'
        for aud,title,desc,goal in [('B2B','Meet your next stockist','A sourcing conversation for boutiques and retailers.','Catalogue discovery'),('B2C','Help someone find their saree','A friendly discovery journey, without assumptions.','New collection')]:
            body+=f'<a class="card recipe" href="/campaigns/new?audience={aud}&goal={query(goal)}"><span class="pill {aud.lower()}">{aud} JOURNEY</span><h3>{title}</h3><p>{desc}</p><span class="arrow">Use this starting point &rarr;</span></a>'
        body+='</div><div class="section"><div class="section-head"><h2>Coming up</h2><a href="/tasks">View tasks &rarr;</a></div><div class="card">'
        tasks=m.rows("SELECT * FROM m4_tasks WHERE status='Open' ORDER BY due_date LIMIT 4")
        body+=''.join(f'<div class="task-row"><span class="round-number">&#9719;</span><div class="row-main"><strong>{e(t["title"])}</strong><div class="tiny muted">{e(t["due_date"])}</div></div></div>' for t in tasks) or '<div class="helper">No tasks yet. Plan follow-ups after reviewing your first campaign. Tasks are reminders inside this app, not automatic messages.</div>'
        body+='</div></div></div><div><div class="section-head"><h2>Your launch checklist</h2><span class="pill purple">One step at a time</span></div><div class="card">'
        checks=[('Business identity',bool(ss.get('brand_name') and ss['brand_name']!='Brand name pending'),'Use your chosen brand, not source filenames.','/settings'),('Knowledge library',knowledge>0,'Add your tone, terms and policies with sources.','/knowledge'),('Product facts',confirmed>0,'Confirm fabric, prices and availability.','/products'),('Draft a campaign',campaigns>0,'Start with a small B2B or B2C audience.','/campaigns/new')]
        for i,(label,done,desc,href) in enumerate(checks,1):
            body+=f'<div class="readiness-row"><span class="round-number">{"&#10003;" if done else i}</span><div class="row-main"><strong>{label}</strong><small>{desc}</small></div><a class="link tiny" href="{href}">{"Review" if done else "Set up"}</a></div>'
        body+='</div><div class="section">'+notice('A high profile score is not consent or a probability of buying. Preview audiences can include unreviewed records; the review gate blocks handoff until permissions are documented.')+'</div></div></div>'
        return self.send_html(layout('Today',body))

    def campaigns(self):
        q=urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query);view=(q.get('view') or ['active'])[0];archived=view=='archived'
        op='=' if archived else '<>'
        campaigns=m.rows("""SELECT c.*, (SELECT count(*) FROM campaign_members cm WHERE cm.campaign_id=c.campaign_id) members,
        (SELECT count(*) FROM m4_drafts d WHERE d.campaign_id=c.campaign_id) drafts FROM campaigns c
        WHERE coalesce(c.status,'Draft') """+op+" 'Archived' ORDER BY created_at DESC")
        active_count=(m.one("SELECT count(*) n FROM campaigns WHERE coalesce(status,'Draft')<>'Archived'") or {'n':0})['n']
        archived_count=(m.one("SELECT count(*) n FROM campaigns WHERE status='Archived'") or {'n':0})['n']
        actions=button(f'Active plans ({active_count})','/campaigns?view=active','' if not archived else 'secondary')+button(f'Archived ({archived_count})','/campaigns?view=archived','' if archived else 'secondary')+button('Outreach playbooks','/outreach','secondary')
        if not archived:actions+=button('New campaign &rarr;','/campaigns/new')
        body=pagehead('Archived campaigns' if archived else 'Campaign studio','Archived campaigns retain members, drafts and attribution but cannot generate, export or send until restored.' if archived else 'Make the right conversation easier to start.',actions)
        if q.get('archived'):body+='<div class="status-banner">'+notice('Campaign archived. Drafts, members and attribution were preserved; generation and handoff actions are blocked until restore.','success')+'</div>'
        if q.get('bulk_archived'):body+='<div class="status-banner">'+notice(q['bulk_archived'][0]+' selected campaign(s) archived. Drafts, audience history and attribution were preserved.','success')+'</div>'
        if q.get('bulk_restored'):body+='<div class="status-banner">'+notice(q['bulk_restored'][0]+' selected campaign(s) restored to Draft for review.','success')+'</div>'
        if not archived:
            body+='<div class="three">'
            for aud,title,desc,goal in [('B2B','Stockist discovery','Introduce a selected collection. Ask about styles, quantities and sourcing needs.','Catalogue discovery'),('B2C','Collection discovery','Invite people to explore colours and preferences without inventing purchase intent.','New collection'),('B2C','Reconnect with customers','Plan a reorder conversation with your existing customer segment.','Reorder conversation')]:
                extra='&lifecycle=Customer' if goal=='Reorder conversation' else ''
                body+=f'<a class="card recipe" href="/campaigns/new?audience={aud}&goal={query(goal)}{extra}"><div class="recipe-icon">&#10022;</div><span class="pill {aud.lower()}" style="float:right">{aud}</span><h3>{title}</h3><p>{desc}</p><span class="arrow">Start from this journey &rarr;</span></a>'
            body+='</div>'
        body+='<div class="section"><div class="section-head"><h2>'+('Campaign history' if archived else 'Your campaign plans')+'</h2><span class="tiny muted">'+('Read-only until restored' if archived else 'No delivery provider connected')+'</span></div>'
        if not campaigns:body+='<div class="card empty">'+('No archived campaigns.' if archived else 'Your first campaign starts with a goal, an audience and a collection.<br>No need to build a list or write every message from scratch.')+'</div>'
        else:
            bulk_action='/campaigns/bulk/restore' if archived else '/campaigns/bulk/archive'
            bulk_label='Restore selected' if archived else 'Archive selected'
            bulk_confirm='Restore selected campaigns to Draft for review?' if archived else 'Archive selected campaigns? Members, drafts and attribution will be preserved.'
            body+=f'<form id="campaign-bulk-form" method="post" action="{bulk_action}" class="card section"><div class="form-foot"><button type="button" class="btn secondary" data-select-form="campaign-bulk-form">Select visible</button><button class="btn secondary" data-confirm="{e(bulk_confirm)}">{e(bulk_label)}</button></div><p class="helper">Bulk lifecycle changes affect only the selected campaign plans. Historical drafts, audiences, sends and attribution are retained.</p></form>'
            body+='<div class="campaign-grid">'
            for c in campaigns:
                cls='warn' if archived else ('warn' if c['status']=='Paused' else 'purple')
                choose=f'<label class="check compact-check" title="Select campaign for bulk action"><input type="checkbox" name="campaign_ids" value="{e(c["campaign_id"])}" form="campaign-bulk-form"><span class="visually-hidden">Select {e(c["campaign_name"])}</span></label>'
                body+=f'<div class="card campaign-tile"><div class="meta">{choose}<span class="pill {str(c["audience_type"]).lower()}">{e(c["audience_type"])}</span><span class="pill">{e(c["channel"])}</span><span class="pill {cls}">{e(c["status"])}</span></div><h3><a class="link" href="/campaigns/{e(c["campaign_id"])}">{e(c["campaign_name"])}</a></h3><div class="divider"></div><div class="toolbar"><span class="campaign-count">{c["members"]}</span><span class="tiny muted">planned contacts</span><span class="campaign-count">{c["drafts"]}</span><span class="tiny muted">draft messages</span></div></div>'
            body+='</div>'
        body+='</div>'
        self.send_html(layout('Campaign studio',body,'campaigns'))

    def new_campaign(self,q):
        val=lambda k,d='':q.get(k,[d])[0]
        aud=val('audience','B2B');goal=val('goal','Catalogue discovery');sources=source_choices()
        countries=[r['country'] for r in m.rows("SELECT DISTINCT country FROM contacts WHERE coalesce(country,'')<>'' ORDER BY 1")]
        body=pagehead('Create a campaign','Three simple steps. Start with a small audience and review before sending.',button('All campaigns','/campaigns','secondary'))
        body+='''<ol class="steps"><li class="current"><span>1</span>Goal &amp; audience</li><li><span>2</span>Collection &amp; brief</li><li><span>3</span>Preview &amp; create</li></ol><form method="post" action="/campaigns/create" data-wizard>'''
        body+='<input type="hidden" name="idempotency_key" value="'+e(m.uid('REQ50'))+'">'
        body+='<input type="hidden" name="contact_id" value="'+e(val('contact_id'))+'">'
        body+='<section class="wizard-step"><div class="two"><div class="card"><h2>Who are we talking to?</h2><div class="formgrid">'
        body+=field('Campaign name','<input name="name" required maxlength="180" placeholder="Example: Boutique discovery - September">')
        body+=field('Customer journey','<select name="audience">'+options([('B2B','B2B / Businesses'),('B2C','B2C / Individual buyers'),('Both','Both / Separate messaging per person')],aud)+'</select>')
        body+=field('Campaign goal','<select name="goal">'+options(o.GOALS,goal)+'</select>')
        body+=field('Channel','<select name="channel">'+options([('Email','Email'),('WhatsApp','WhatsApp'),('Social DM','Instagram / LinkedIn DM script'),('SMS','SMS / script only'),('Phone','Phone / call script only')],val('channel','Email'))+'</select>','Email/WhatsApp support reviewed manual handoff. SMS and phone are scripts only; no sender or dialler is connected.')
        body+=field('Source list','<select name="source">'+options(sources,val('source'),empty='All sources')+'</select>','Your imported source names stay separate from your business brand.')
        body+=field('Customer stage','<select name="lifecycle">'+options(['New','Contacted','Engaged','Qualified','Customer','Repeat Customer','Inactive'],val('lifecycle'),empty='All stages')+'</select>')
        body+=field('Country / phone-region hint','<select name="country">'+options(countries,val('country'),empty='Any country / region')+'</select>','Imported or inferred; not verified residence or legal jurisdiction.')
        body+=field('Company or category keywords','<input name="search" value="'+e(val('search'))+'" placeholder="Optional: boutique, textile...">')
        body+=field('Contact tag','<select name="tag">'+options([x['tag'] for x in m.rows('SELECT DISTINCT tag FROM m41_tags ORDER BY tag')],val('tag'),empty='Any tag')+'</select>')
        body+=field('Profile-priority filter','<select name="min_score">'+options([('0','No score filter (recommended for B2C)'),('45','45+ profile priority'),('75','75+ profile priority')], val('min_score','0'))+'</select>','Keyword score, not AI confidence. No score does not mean no consumer interest.')
        body+=field('First planning audience','<select name="limit">'+options([('5','5 contacts'),('10','10 contacts'),('25','25 contacts'),('50','50 contacts'),('100','100 contacts')],val('limit','10'))+'</select>')
        body+='</div></div><div class="card"><h2>Preview first. Send later.</h2><p class="helper">B2B drafts focus on buying requirements, order quantities and a collection review. B2C drafts focus on choice, preferences and helpful guidance.</p>'
        body+=field('Audience permission mode','<select name="scope">'+options([('Preview','Preview / include permission-unknown contacts'),('Eligible','Documented-permission contacts only')],val('scope','Preview'))+'</select>','Opt-outs and suppressed addresses are excluded in both modes.')
        body+='<div class="section">'+notice('Preview mode lets you design the campaign without pretending that scraped contact details are permission to contact anyone.')+'</div></div></div><div class="form-foot"><button class="btn" type="button" data-next>Choose collection &rarr;</button></div></section>'
        body+='<section class="wizard-step" hidden><div class="two"><div class="card"><h2>Build from your products</h2><p class="helper">Choose the pieces for this campaign. Imported fabric and weave descriptions need human confirmation before campaign approval.</p><div class="checkgrid">'
        for p in m.products():
            checked=" checked" if p["product_id"]==val("product_id") else ""
            fact_status="Facts confirmed" if p["confirmed"] else "Facts need review"
            duplicate_badge='<span class="pill warn">Possible duplicate</span>' if p["duplicate_group"] else ""
            body+=f'<label class="check"><input type="checkbox" name="product_ids" value="{e(p["product_id"])}"{checked}><img src="/{e(p["img"] or "")}" alt="{e(p["colour"])} saree"><span class="row-main"><strong>{e(p["public_product_name"])}</strong><small>{e(p["product_code"])} &middot; {fact_status}</small>{duplicate_badge}</span></label>'
        body+='</div></div><div class="card"><h2>Give the copy a direction</h2>'
        body+=field('Tone','<select name="tone">'+options(['Warm and professional','Elegant and understated','Friendly and conversational','Direct and practical'])+'</select>')
        body+='<div class="section">'+field('What should this campaign achieve?','<textarea name="brief" maxlength="2000" placeholder="Example: Introduce a selected collection and ask what the boutique is sourcing. Avoid hard selling.">'+e(val('brief'))+'</textarea>','A brief is a direction, not proof of discounts, stock, delivery promises or certifications.')+'</div>'
        body+='<div class="section">'+personalisation_fields({k:x[0] for k,x in q.items()},aud)+'</div>'
        body+='<div class="section">'+notice('Only approved knowledge enters the AI context. No product photo, email, phone, username or scraped biography is sent to the AI provider by this app.')+'</div></div></div><div class="form-foot"><button class="btn secondary" type="button" data-back>&larr; Back</button><button class="btn" type="button" data-next>Review audience &rarr;</button></div></section>'
        body+='<section class="wizard-step" hidden><div class="two"><div class="card" id="audience-preview" aria-live="polite">Checking audience...</div><div class="card"><h2>You are creating a plan</h2><p class="helper">This step creates a draft campaign and a reviewed-size contact list. Nothing is sent, no AI call is made, and no contact is automatically marked as contacted.</p><p class="helper">Next you will preview messages, see what informed them, and choose local templates or a connected AI model.</p>'+notice('Some records may be planning-only until permission, brand details and product facts are verified.')+'</div></div><div class="form-foot"><button class="btn secondary" type="button" data-back>&larr; Back</button><button class="btn" type="submit">Create draft campaign</button></div></section></form>'
        self.send_html(layout('Create campaign',body,'campaigns'))

    def campaign(self,camid):
        cam=m.campaign(camid);q=getattr(self,'q',{});status=str(cam.get('status') or 'Draft');archived=status=='Archived';paused=status=='Paused';locked=archived or paused
        if not cam['goal']:
            body=pagehead(cam['campaign_name'],'Your older campaign is preserved.')+notice('This older campaign predates the current guided brief. Use the guided builder for knowledge-grounded personalised drafts; the old records remain unchanged.')+'<div class="section">'+button('Create a guided campaign','/campaigns/new')+'</div>'
            return self.send_html(layout('Campaign',body,'campaigns'))
        members=m.rows('''SELECT c.* FROM campaign_members cm JOIN contacts c USING(contact_id)
        WHERE cm.campaign_id=? ORDER BY c.lead_score DESC,c.contact_id''',(camid,))
        if not members:raise ValueError('This campaign has no audience.')
        cid=q.get('contact',[members[0]['contact_id']])[0]
        if cid not in {c['contact_id'] for c in members}:raise ValueError('Choose a contact from this campaign.')
        person=next(c for c in members if c['contact_id']==cid)
        drafts=m.rows('SELECT * FROM m4_drafts WHERE campaign_id=? AND contact_id=? ORDER BY step',(camid,cid))
        total=m.one('SELECT count(*) n FROM m4_drafts WHERE campaign_id=?',(camid,))['n']
        ctx=m.context(camid,cid);ok,reason=m.eligibility(person,cam['channel']);ai_state=m.ai_health()
        if archived:
            life=f'<form method="post" action="/campaigns/{e(camid)}/restore" data-confirm="Restore this campaign to Draft for review?"><button class="btn">Restore campaign</button></form>'
        elif paused:
            life=f'<form method="post" action="/campaigns/{e(camid)}/resume"><button class="btn">Resume campaign</button></form><form method="post" action="/campaigns/{e(camid)}/archive" data-confirm="Archive this paused campaign? Drafts, members and attribution will remain in history."><button class="btn secondary">Archive campaign</button></form>'
        else:
            life=f'<form method="post" action="/campaigns/{e(camid)}/pause" data-confirm="Pause this campaign? New draft generation, handoff and provider submissions will be blocked until you resume it. Existing provider activity is not changed automatically."><button class="btn secondary">Pause campaign</button></form><form method="post" action="/campaigns/{e(camid)}/archive" data-confirm="Archive this campaign? Drafts, members and attribution will remain in history."><button class="btn secondary">Archive campaign</button></form>'
        duplicate='' if archived else f'<form method="post" action="/campaigns/{e(camid)}/duplicate" data-confirm="Create a new Draft using this campaign plan and the current audience/permission state? Draft messages and send history will not be copied."><button class="btn secondary">Duplicate campaign</button></form>'
        detail_actions=button('All campaigns','/campaigns','secondary')+duplicate+life
        if not locked:detail_actions=button('Personalisation choices','/campaigns/'+camid+'/personalise','secondary')+detail_actions
        body=pagehead(cam['campaign_name'],f'{cam["audience_type"]} / {cam["channel"]} / {len(members)} planned contacts / {total} saved drafts',detail_actions)
        if archived:body+=notice('This campaign is archived and read-only. Restore it before generating drafts, changing personalisation or exporting handoffs.','warn')
        elif paused:body+=notice('This campaign is paused. Existing history stays visible, but new draft generation, manual handoff and provider submissions are blocked until you resume it. Pausing here does not claim that an already-running external provider campaign was paused.','warn')
        if q.get('paused'):body+=notice('Campaign paused. No new CRM handoff or provider submission is allowed until it is resumed.','success')
        if q.get('resumed'):body+=notice('Campaign resumed as Draft. Review the audience, permissions and channel readiness before continuing.','success')
        if q.get('duplicated'):body+=notice('Campaign duplicated as a fresh Draft using the current audience and permission state. Draft messages and prior sends were not copied.','success')
        if q.get('generated') or q.get('saved'):body+='<div class="status-banner">'+notice('Drafts saved locally. No messages were sent.','success')+'</div>'
        if q.get('batch'):body+='<div class="status-banner">'+notice(f'{q["batch"][0]} local-template drafts created. Existing drafts were not overwritten.','success')+'</div>'
        batch_action='' if locked else f'<form method="post" action="/campaigns/{e(camid)}/batch-local" data-busy="Building local drafts..."><button class="btn secondary small">Draft first 10 locally</button></form>'
        body+=f'''<div class="card toolbar" style="margin-bottom:20px"><span class="pill {cam['audience_type'].lower()}">{e(cam['audience_type'])}</span><span class="pill purple">{e(cam['goal'])}</span><span class="pill">{e(cam['tone'])}</span><span class="row-main"></span>{batch_action}</div>'''
        body+='<div class="two"><div><div class="card"><h2>Preview the right message</h2><form method="get" class="filters">'
        body+=field('Recipient','<select name="contact">'+options([(c['contact_id'],(ct.clean_display_name(c['full_name']) or c['username'])+' / '+c['contact_type']) for c in members],cid)+'</select>')+'<button class="btn secondary">View messages</button></form>'
        body+=f'<div class="toolbar"><span class="pill {"good" if ok else "warn"}">{e(reason)}</span><a class="link tiny" href="/contacts/{e(cid)}">Contact &amp; permissions &rarr;</a></div></div>'
        if not drafts:
            body+='<div class="card empty section"><h2>Your drafts will appear here</h2>Choose <strong>Build local drafts</strong> for an immediate template-based preview,<br>or connect AI and review the exact payload before generating.</div>'
        for d in drafts:
            issues=m.draft_gate(d)
            source=json.loads(d['source_json'])
            used=source.get('used',[])
            body+=f'''<div class="card message-card section"><div class="message-top"><div><span class="day-badge">Step {d['step']+1} / proposed day {d['day_offset']}</span><div class="sub">{e(d['engine'])}</div></div><span class="pill {"good" if d['status']=='Approved' else 'purple'}">{e(d['status'])} / not sent</span></div>
            <form method="post" action="/drafts/{e(d['id'])}/save">'''
            if d['channel']=='Email':
                body+=field('Subject','<input class="message-subject" name="subject" value="'+e(d['subject'])+'" maxlength="250" '+('disabled' if locked else '')+'>')
                body+=f'<p class="tiny muted">Alternative subject idea: {e(d["alternative_subject"])}<br>Suggestion only; no A/B test has been run.</p>'
            else:body+='<input type="hidden" name="subject" value="">'
            body+=f'<label class="visually-hidden" for="body-{e(d["id"])}">Message body</label><textarea class="message-text" name="body" id="body-{e(d["id"])}" maxlength="7000" {"disabled" if locked else ""}>{e(d["body"])}</textarea>'
            body+=f'<details class="source-box"><summary>Why this message / sources</summary><p>{e(d["why"])}</p><p>Referenced source IDs: {e(", ".join(used) or "Journey template only; no verified product claims")}</p><p>All generated claims still require your review. Approval does not certify legal compliance.</p></details>'
            hard_issues=[x for x in issues if x!='Human draft approval required']
            if hard_issues:body+='<div class="section">'+notice('Blocked from handoff: '+'; '.join(hard_issues),'warn')+'</div>'
            elif d['status']!='Approved':body+='<div class="section">'+notice('Ready for your review. Approval records that you checked the content; it does not send anything.','info')+'</div>'
            body+='<div class="section"><label class="checkline"><input type="checkbox" name="confirmed" value="1" '+('disabled' if hard_issues else '')+'>I reviewed the facts, sender identity, audience basis and opt-out wording.</label></div>'
            controls=f'<button class="btn secondary" type="button" data-copy="body-{e(d["id"])}">Copy preview</button>'
            if locked:
                controls+='<span class="pill warn">Read-only while '+('archived' if archived else 'paused')+'</span>'
            else:
                controls+='<button class="btn secondary" name="action" value="save">Save draft</button>'
                if d['status']=='Approved':
                    controls+='<span class="pill good">Approved for handoff</span>'
                elif hard_issues:
                    controls+='<button class="btn" type="button" disabled title="Resolve the blockers shown above before approval">Approval blocked</button>'
                else:
                    controls+='<button class="btn" name="action" value="approve">Approve for handoff</button>'
            body+=f'<div class="form-foot">{controls}</div></form></div>'
            if not locked and d['status']=='Approved' and d['channel'] in {'Email','WhatsApp'}:
                body+=f'<form method="post" action="/drafts/{e(d["id"])}/handoff"><button class="btn secondary">Prepare manual {e(d["channel"])} handoff</button></form>'
        body+='</div><div class="sticky-panel"><div class="card"><div class="eyebrow">Copy assistant</div><h2>Make it personal. Keep it true.</h2><p class="helper">Local drafts use your playbook or reusable sequence, tone, greeting, confirmed preferences and proposed timing. AI uses approved knowledge and your brief. Custom sequences are local-only; no AI call is needed.</p>'
        replace='<label class="checkline"><input type="checkbox" name="replace" value="1" required>Replace this person\'s saved drafts. Previous text is retained in the audit history; approvals will reset.</label>' if drafts else ''
        if locked:body+='<div class="section">'+notice('Resume or restore this campaign before generating or replacing drafts.','warn')+'</div><div class="divider"></div>'
        else:body+=f'<form method="post" action="/campaigns/{e(camid)}/generate" data-busy="Building local drafts..."><input type="hidden" name="contact_id" value="{e(cid)}"><input type="hidden" name="engine" value="local">{replace}<button class="btn ghost" style="width:100%;margin-top:12px">Build local drafts / no AI cost</button></form><div class="divider"></div>'
        body+=f'<details><summary class="helper"><strong>Review exact AI payload</strong></summary><pre class="modal-json">{e(json.dumps(ctx,ensure_ascii=False,indent=2))}</pre></details>'
        body+='<p class="tiny muted">Structured email, phone, name, username and biography fields are excluded. Review free-text notes for personal information before sharing. API billing is separate; one click makes one paid request. No automatic retry.</p>'
        if not locked and ai_state['status']=='Connected':
            body+=f'<form method="post" action="/campaigns/{e(camid)}/generate" data-busy="Generating 3 AI drafts..."><input type="hidden" name="contact_id" value="{e(cid)}"><input type="hidden" name="engine" value="ai">{replace}<label class="checkline"><input type="checkbox" name="ai_consent" value="1" required>I approve sending this payload to OpenAI and the API charge.</label><button class="btn" style="width:100%;margin-top:12px">Generate 3 AI drafts</button></form>'
        elif m.secret():
            body+=notice('AI is not ready: '+ai_state['status']+'. '+ai_state['detail'],'warn')+button('Test / fix AI connection','/settings#ai','secondary')
        else:body+=button('Connect AI in settings &rarr;','/settings#ai','secondary')+'<p class="tiny muted">AI generation is not active yet. Local templates are not labelled as AI.</p>'
        brief_text=cam['brief'] or ('Use the campaign goal “'+str(cam['goal'] or 'Catalogue discovery')+'” as the direction. Use only verified product facts; do not invent offers, pricing, stock or delivery promises.')
        body+='</div><div class="card section"><h2>Campaign brief</h2><p class="helper">'+e(brief_text)+'</p>'+('' if cam['brief'] else notice('No custom brief was entered, so the CRM is using a safe goal-based default. Add a custom brief if you want more specific copy.','info'))+'<h3>Follow-up plan</h3><p class="helper">Proposed timing only. Nothing is scheduled to send. Stop follow-ups after a reply, purchase or opt-out; check this manually until a sending integration is connected.</p>'
        handoff_action='' if locked else button('Export reviewed draft JSON','/campaigns/'+camid+'/export','secondary')
        body+=button('Add a review task','/tasks?campaign='+query(camid)+'&contact='+query(cid),'secondary')+'</div><div class="card section"><h2>Handoff, not auto-send</h2><p class="helper">Approved drafts can be opened manually in your email app or WhatsApp, after a fresh permission check. Delivery and replies are not tracked automatically. The JSON export omits addresses. Connect a sending provider separately for automated delivery.</p>'+handoff_action+'</div></div></div>'
        self.send_html(layout('Campaign review',body,'campaigns'))

    def classic_contacts(self,q):
        val=lambda k,d='':q.get(k,[d])[0]
        search=val('search',val('q'));aud=val('type');country=val('country');source=val('source');scope=val('scope');page=max(1,min(500,int(val('page','1') or '1')))
        clauses=[];args=[]
        if search:clauses.append('(full_name LIKE ? OR username LIKE ? OR email LIKE ? OR business_category LIKE ?)');args.extend(['%'+search+'%']*4)
        if aud in {'B2B','B2C'}:clauses.append("contact_type IN (?,'Both')");args.append(aud)
        elif aud:clauses.append('contact_type=?');args.append(aud)
        if source:clauses.append('(source_name=? OR EXISTS (SELECT 1 FROM m41_sources s WHERE s.contact_id=contacts.contact_id AND s.source=?))');args.extend([source,source])
        tag=val('tag')
        if tag:clauses.append('EXISTS (SELECT 1 FROM m41_tags t WHERE t.contact_id=contacts.contact_id AND t.tag=?)');args.append(tag)
        for col,value in [('country',country)]:
            if value:clauses.append(col+'=?');args.append(value)
        base='SELECT * FROM contacts'+(' WHERE '+' AND '.join(clauses) if clauses else '')+' ORDER BY lead_score DESC,full_name'
        allrows=m.rows(base,args);pm=m.permissions_map();channel=val('channel','Email')
        if channel not in {'Email','WhatsApp','SMS','Phone'}:channel='Email'
        if scope=='Eligible':allrows=[c for c in allrows if m.eligibility(c,channel,pm)[0]]
        elif scope=='Unknown':allrows=[c for c in allrows if m.eligibility(c,channel,pm)[1]=='Permission unknown']
        total=len(allrows);shown=allrows[(page-1)*40:page*40]
        countries=[r['country'] for r in m.rows("SELECT DISTINCT country FROM contacts WHERE coalesce(country,'')<>'' ORDER BY 1")]
        body=pagehead('Audiences',f'{total:,} matching records. Stored contacts are not automatically marketing subscribers.',button('Saved audiences','/segments','secondary')+button('Import contacts','/imports','secondary')+button('Add contact','/contacts/new'))
        body+='<form method="get" class="filters">'+field('Find a contact','<input name="search" value="'+e(search)+'" placeholder="Name, email, category...">')
        body+=field('Journey','<select name="type">'+options(['B2B','B2C','Both','Unknown'],aud,empty='All types')+'</select>')
        body+=field('Source list','<select name="source">'+options(source_choices(),source,empty='All sources')+'</select>')
        body+=field('Tag','<select name="tag">'+options([x['tag'] for x in m.rows('SELECT DISTINCT tag FROM m41_tags ORDER BY tag')],val('tag'),empty='All tags')+'</select>')
        body+=field('Country / region hint','<select name="country">'+options(countries,country,empty='All regions')+'</select>')
        body+=field('Permission channel','<select name="channel">'+options(['Email','WhatsApp','SMS','Phone'],channel)+'</select>')
        body+=field('Permission review','<select name="scope">'+options([('Eligible','Documented permission'),('Unknown','Permission unknown')],scope,empty='All records')+'</select>')
        body+='<button class="btn">Apply filters</button>'+button('Reset','/contacts','secondary')+'</form>'
        body+='<div class="table-wrap"><table><tr><th>Contact</th><th>Journey</th><th>Profile category</th><th>Priority hint</th><th>Channel permission</th><th>Customer stage</th></tr>'
        for c in shown:
            ok,reason=m.eligibility(c,channel,pm)
            body+=f'<tr><td><a class="contact-name" href="/contacts/{e(c["contact_id"])}">{e(ct.clean_display_name(c["full_name"]) or c["username"])}</a><span class="tiny muted">@{e(c["username"])}<br>{e(c["source_name"])}</span></td><td><span class="pill {str(c["contact_type"]).lower()}">{e(c["contact_type"])}</span></td><td>{e(c["business_category"] or "Unreviewed")}</td><td>{int(c["lead_score"] or 0)} <span class="tiny muted">/ 100</span><div class="tiny muted">Keyword hint</div></td><td><span class="pill {"good" if ok else "warn"}">{e(reason)}</span></td><td>{e(c["lifecycle_stage"])}</td></tr>'
        if not shown:body+='<tr><td colspan="6" class="empty">No matching records. Adjust the filters.</td></tr>'
        body+='</table></div><div class="form-foot">'
        clean={k:v[0] for k,v in q.items() if k!='page'}
        if page>1:body+=button('&larr; Previous','/contacts?'+urllib.parse.urlencode(clean|{'page':page-1}),'secondary')
        body+=f'<span class="tiny muted">Page {page} / {max(1,(total+39)//40)}</span>'
        if page*40<total:body+=button('Next &rarr;','/contacts?'+urllib.parse.urlencode(clean|{'page':page+1}),'secondary')
        body+='</div><div class="section"><form method="post" action="/enrich" data-confirm="Refresh local keyword priority hints? This will not change qualification, customer types, country or permissions."><button class="btn secondary small">Refresh rule-based suggestions</button></form><p class="tiny muted">Keyword scores are not AI predictions, verified business categories or probabilities of buying. Imported country values may come from telephone prefixes, not residence.</p></div>'
        self.send_html(layout('Audiences',body,'contacts'))

    def classic_contact(self,cid):
        c=m.contact(cid);pref=m.one('SELECT * FROM m4_preferences WHERE contact_id=?',(cid,)) or {}
        perms=m.rows('SELECT * FROM marketing_permissions WHERE contact_id=? ORDER BY channel',(cid,))
        accounts=m.rows('SELECT cp.company_id,co.company_name FROM contact_companies cp JOIN companies co USING(company_id) WHERE cp.contact_id=?',(cid,))
        body=pagehead(ct.clean_display_name(c['full_name']) or c['username'],f'@{c["username"]} / {c["source_name"]}',button('Edit contact','/contacts/'+cid+'/edit','secondary')+button('Build a campaign','/campaigns/new?audience='+('B2C' if c['contact_type']=='B2C' else 'B2B')+'&contact_id='+query(cid))+button('Back to audiences','/contacts','secondary'))
        prof=ct.profile(cid)
        body+='<div class="two"><div class="card"><h2>Contact context</h2><div class="kv">'
        for key,label in [('first_name','First name'),('last_name','Last name'),('company_name','Company for personalisation'),('role_title','Role'),('tags','Tags')]:
            body+='<div>'+label+'</div><div>'+e(prof.get(key) or 'Not recorded')+'</div>'
        for label,value in [('Journey',c['contact_type']),('Email',c['email']),('Telephone',c['phone_number']),('Website',c['website']),('Country / region',str(c['country'] or 'Unknown')+(' / manually confirmed' if pref.get('country_verified') else ' / unverified hint')),('Category',c['business_category']),('Priority hint',str(c['lead_score'])+' / 100 (keyword-based, not purchase probability)'),('Profile evidence',c['biography']),('Next follow-up',c['next_follow_up'])]:
            body+=f'<div>{label}</div><div>{e(value or "Not recorded")}</div>'
        body+='</div><div class="divider"></div><h3>B2B account</h3>'
        if accounts:body+=''.join(f'<span class="pill b2b">{e(a["company_name"])}</span>' for a in accounts)
        elif c['contact_type'] in {'B2B','Both'}:body+=f'<form method="post" action="/contacts/{e(cid)}/create-company"><button class="btn secondary">Create account from contact</button></form>'
        else:body+='<p class="helper">Individual customer. No company is required.</p>'
        body+='</div><div class="card"><h2>Your review</h2><form method="post" action="/contacts/'+e(cid)+'/update"><div class="formgrid">'
        for label,key,values in [('Contact type','contact_type',['B2B','B2C','Both','Unknown']),('Qualification','qualification_status',['Unreviewed','Qualified','Needs Review','Irrelevant','Do Not Contact']),('Customer stage','lifecycle_stage',['New','Contacted','Engaged','Qualified','Customer','Repeat Customer','Inactive'])]:
            body+=field(label,'<select name="'+key+'">'+options(values,c[key])+'</select>')
        for label,key in [('Country','country'),('Language','language'),('Niche','niche'),('Business category','business_category')]:body+=field(label,f'<input name="{key}" value="{e(c[key])}">')
        body+='</div><p class="helper">A suggested B2B category does not prove the business is a corporate subscriber. Qualification is separate from channel permission.</p><button class="btn">Save review</button></form></div></div>'
        body+='<div class="two section"><div class="card"><h2>Confirmed customer preferences</h2><p class="helper">Add preferences the person explicitly gave you, such as colours, budget or sourcing needs. Do not infer sensitive traits from names, photos or follows.</p><form method="post" action="/preferences/save">'
        body+=f'<input type="hidden" name="contact_id" value="{e(cid)}">'+field('Preference notes',f'<textarea name="preferences" maxlength="1500">{e(pref.get("preferences",""))}</textarea>')
        body+=field('Where was this confirmed?',f'<input name="evidence" value="{e(pref.get("evidence",""))}" placeholder="Example: customer enquiry dated...">')
        body+=f'<p><label class="checkline"><input name="verified" value="1" type="checkbox" {"checked" if pref.get("verified") else ""}>These preferences are confirmed and can inform campaign drafts.</label></p><p><label class="checkline"><input name="country_verified" value="1" type="checkbox" {"checked" if pref.get("country_verified") else ""}>I independently verified the contact\'s country.</label></p><button class="btn secondary">Save preferences</button></form></div>'
        body+='<div class="card"><h2>Add a note or follow-up</h2><form method="post" action="/activities/create">'+f'<input type="hidden" name="contact_id" value="{e(cid)}">'
        body+='<div class="formgrid">'+field('Activity type','<select name="activity_type">'+options(['Note','Email','WhatsApp','Call','Meeting','Follow-up'])+'</select>')+field('Channel','<select name="channel">'+options(['Other','Email','WhatsApp','Social DM','Phone','Website'])+'</select>')+field('Direction','<select name="direction">'+options(['Internal','Inbound','Outbound'])+'</select>')+field('Next follow-up','<input type="datetime-local" name="follow_up_at">')+'</div>'+field('What happened?','<textarea name="summary" required placeholder="Log actual activity, not an assumed customer response."></textarea>')+'<button class="btn secondary">Save activity</button></form></div></div>'
        body+='<div class="section"><div class="section-head"><h2>Channel permissions</h2><span class="pill warn">No automatic consent</span></div><div class="table-wrap"><table><tr><th>Channel</th><th>Status</th><th>Basis</th><th>Evidence</th><th>Jurisdiction</th></tr>'
        for p in perms:body+=f'<tr><td>{e(p["channel"])}</td><td><span class="pill">{e(p["status"])}</span></td><td>{e(p["lawful_basis_or_reason"] or "Not recorded")}</td><td>{e(p["evidence_reference"] or "Not recorded")}</td><td>{e(p["jurisdiction"] or "Not reviewed")}</td></tr>'
        body+='</table></div><div class="card section"><h3>Record evidence, not just a green status</h3><form method="post" action="/permissions/update">'+f'<input type="hidden" name="contact_id" value="{e(cid)}"><div class="formgrid">'
        body+=field('Channel','<select name="channel">'+options(['Email','WhatsApp','Phone','SMS','Other'])+'</select>')+field('Status','<select name="status">'+options(['Unknown','Allowed','OptedIn','OptedOut','Suppressed','DoNotContact'])+'</select>')
        body+=field('Basis / reason','<input name="reason" placeholder="What permits this marketing?">')+field('Evidence reference','<input name="evidence" placeholder="Opt-in record, form or reviewed assessment">')+field('Reviewed jurisdiction','<input name="jurisdiction" placeholder="Where do the relevant rules apply?">')
        body+='</div><p class="helper">Allowed is not a universal legal exemption. WhatsApp drafts require documented opt-in. Unknown or opted-out contacts remain blocked for handoff.</p><button class="btn">Save permission record</button></form></div></div>'
        acts=m.rows('SELECT * FROM activities WHERE contact_id=? ORDER BY created_at DESC LIMIT 30',(cid,))
        body+='<div class="card section"><h2>Activity timeline</h2>'
        for a in acts:body+=f'<div class="readiness-row"><span class="pill">{e(a["activity_type"])}</span><div class="row-main"><strong class="tiny">{e(a["summary"])}</strong><small class="muted">{e(a["created_at"])} / {e(a["direction"])}</small></div></div>'
        if not acts:body+='<p class="helper">No activity recorded yet. Generating a draft never marks a person as contacted.</p>'
        body+='</div>'
        self.send_html(layout('Contact',body,'contacts'))

    def knowledge(self,q):
        notes=m.rows("SELECT * FROM m4_knowledge WHERE status<>'Archived' ORDER BY updated_at DESC")
        edit=m.one('SELECT * FROM m4_knowledge WHERE id=?',(q.get('edit',[''])[0],)) or {}
        body=pagehead('Knowledge library','Give your copy assistant approved facts, not guesses.',button('Campaign studio','/campaigns','secondary'))
        if q.get('saved'):body+='<div class="status-banner">'+notice('Knowledge saved. Only approved notes will be used by connected AI.','success')+'</div>'
        body+='<div class="two"><div><div class="card"><h2>What belongs here?</h2><p class="helper">Start with your brand voice, verified product story, wholesale terms, shipping and returns, and frequently asked questions. Every factual note should have a source you trust.</p><div class="toolbar"><span class="tag">Brand voice</span><span class="tag">Wholesale terms</span><span class="tag">Product evidence</span><span class="tag">Shipping &amp; returns</span><span class="tag">FAQ</span></div></div>'
        for n in notes:
            body+=f'<div class="card section"><div class="message-top"><h3>{e(n["title"])}</h3><span class="pill {"good" if n["status"]=="Approved" else "warn"}">{e(n["status"])}</span></div><div class="toolbar"><span class="tag">{e(n["category"])}</span><span class="tag">{e(n["audience"])}</span></div><p class="kb-text">{e(n["content"])}</p><p class="tiny muted">Evidence: {e(n["source"] or "Not recorded")}<br>Source ID: {e(n["id"])}</p><div class="toolbar">{button("Edit","/knowledge?edit="+query(n["id"]),"secondary small")}<form method="post" action="/knowledge/archive" data-confirm="Archive this knowledge note? Future AI drafts will not use it; existing drafts will require review."><input type="hidden" name="id" value="{e(n["id"])}"><button class="btn secondary small">Archive</button></form></div></div>'
        if not notes:body+='<div class="card empty section">No approved knowledge yet.<br>Add your first note using the form. Your source filenames are not your brand and do not prove fabric composition.</div>'
        body+='</div><div class="card sticky-panel"><h2>'+('Edit knowledge' if edit else 'Add knowledge')+'</h2><form method="post" action="/knowledge/save">'
        body+=f'<input type="hidden" name="id" value="{e(edit.get("id",""))}">'
        body+=field('Title',f'<input name="title" required maxlength="180" value="{e(edit.get("title",""))}" placeholder="Example: B2B minimum order policy">')+'<div class="formgrid section">'
        body+=field('Category','<select name="category">'+options(['Brand voice','Wholesale terms','Product facts','Shipping and returns','FAQ','Offer terms'],edit.get('category','Brand voice'))+'</select>')+field('Audience','<select name="audience">'+options(['Both','B2B','B2C'],edit.get('audience','Both'))+'</select>')+'</div><div class="section">'
        body+=field('Facts or guidance',f'<textarea name="content" required maxlength="12000" style="min-height:180px">{e(edit.get("content",""))}</textarea>','Do not include contact lists or sensitive customer information.')+'</div><div class="section">'
        body+=field('Source / evidence',f'<input name="source" value="{e(edit.get("source",""))}" placeholder="Supplier confirmation, policy document or owner-approved guidance">')+'</div>'
        body+=f'<p><label class="checkline"><input type="checkbox" name="approved" value="1" {"checked" if edit.get("status")=="Approved" else ""}>I have reviewed this content. It is approved for campaign drafting.</label></p><button class="btn" style="width:100%">Save knowledge</button></form></div></div>'
        self.send_html(layout('Knowledge library',body,'knowledge'))

    def products(self):
        q=urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        val=lambda k,d='':(q.get(k) or [d])[0]
        view=val('view','active');archived=view=='archived';search=val('search').strip();category=val('category').strip();sort=val('sort','newest')
        duplicates_only=(val('duplicates')=='1' and not archived)
        if sort not in {'newest','oldest','name','name_desc','stock_low','stock_high'}:sort='newest'
        # Recompute candidate groups before rendering. V33 preserves the V32 active-only duplicate logic and excludes archived items
        # and clears stale group labels left by earlier incremental updates.
        try:pe.refresh_duplicate_groups()
        except Exception as exc:observability.log('products.duplicate_refresh_failed',error=str(exc))
        all_products=m.products(include_archived=True)
        inv_map={r['product_id']:max(0,int(r.get('available') or 0)) for r in m.rows('SELECT product_id,coalesce(sum(on_hand-reserved),0) available FROM v9_inventory GROUP BY product_id')} if m.table_exists('v9_inventory') else {}
        for p in all_products:p['_available_stock']=inv_map.get(p['product_id'])
        pr=[p for p in all_products if (p.get('status')=='Archived')==archived]
        if duplicates_only:pr=[p for p in pr if p.get('duplicate_group')]
        if search:
            needle=search.casefold()
            pr=[p for p in pr if needle in ' '.join(str(p.get(k) or '') for k in ['public_product_name','product_code','internal_sku','colour','category','tags']).casefold()]
        if category:pr=[p for p in pr if str(p.get('category') or '')==category]
        sorters={
          'newest':lambda p:str(p.get('created_at') or ''),
          'oldest':lambda p:str(p.get('created_at') or ''),
          'name':lambda p:(str(p.get('public_product_name') or '').casefold(),str(p.get('product_id'))),
          'name_desc':lambda p:(str(p.get('public_product_name') or '').casefold(),str(p.get('product_id'))),
          'stock_low':lambda p:(10**12 if p.get('_available_stock') is None else int(p.get('_available_stock') or 0),str(p.get('public_product_name') or '').casefold()),
          'stock_high':lambda p:(-1 if p.get('_available_stock') is None else int(p.get('_available_stock') or 0),str(p.get('public_product_name') or '').casefold()),
        }
        reverse=sort in {'newest','name_desc','stock_high'}
        pr=sorted(pr,key=sorters[sort],reverse=reverse)
        archived_count=sum(1 for p in all_products if p.get('status')=='Archived');active_count=len(all_products)-archived_count
        duplicate_count=sum(1 for p in all_products if p.get('status')!='Archived' and p.get('duplicate_group'))
        categories=sorted({str(p.get('category') or '') for p in all_products if p.get('category')})
        actions=button(f'Active products ({active_count})','/products?view=active','' if not archived and not duplicates_only else 'secondary')+button(f'Archived ({archived_count})','/products?view=archived','' if archived else 'secondary')
        if not archived:actions+=button('Add product','/products/new')+button('Import products','/products/import','secondary')
        title='Archived products' if archived else ('Review duplicate candidates' if duplicates_only else 'Your product collection')
        subtitle='Archived products stay in history but are excluded from new customer selections, campaigns, creative work and publishing.' if archived else ('Compare only active products currently flagged as possible duplicates. Archived products are ignored.' if duplicates_only else 'Search, sort, review, archive and operate the catalogue from one place.')
        body=pagehead(title,subtitle,actions)
        if q.get('archived'):body+='<div class="status-banner">'+notice('Product archived. Historical references were preserved, but it is no longer offered in active workflow selectors.','success')+'</div>'
        if q.get('bulk_archived'):body+='<div class="status-banner">'+notice(q['bulk_archived'][0]+' selected product(s) archived. Historical references were preserved.','success')+'</div>'
        if q.get('bulk_restored'):body+='<div class="status-banner">'+notice(q['bulk_restored'][0]+' selected product(s) restored to Draft.','success')+'</div>'
        if q.get('bulk_deleted'):body+='<div class="status-banner">'+notice(q['bulk_deleted'][0]+' unused archived product(s) permanently deleted; '+q.get('bulk_blocked',['0'])[0]+' blocked by business history.','success' if q.get('bulk_blocked',['0'])[0]=='0' else 'warn')+'</div>'
        if q.get('bulk_category'):body+='<div class="status-banner">'+notice(q['bulk_category'][0]+' selected product(s) updated to category '+q.get('category_name',[''])[0]+'.','success')+'</div>'
        if q.get('bulk_collection'):body+='<div class="status-banner">'+notice(q['bulk_collection'][0]+' selected product(s) added to merchandise collection '+q.get('collection_name',[''])[0]+'.','success')+'</div>'
        if q.get('bulk_error'):body+='<div class="status-banner">'+notice('Select at least one product before running a bulk action. Nothing was changed.','warn')+'</div>'
        hidden_dupes='<input type="hidden" name="duplicates" value="1">' if duplicates_only else ''
        body+='<form method="get" class="card compact-filter"><input type="hidden" name="view" value="'+e(view)+'">'+hidden_dupes+'<div class="filter-grid">'+field('Search','<input name="search" value="'+e(search)+'" placeholder="Product title, SKU, colour, tag...">')+field('Category','<select name="category">'+options(categories,category,empty='All categories')+'</select>')+field('Sort','<select name="sort">'+options([('newest','Newest'),('oldest','Oldest'),('name','Name A–Z'),('name_desc','Name Z–A'),('stock_low','Lowest stock'),('stock_high','Highest stock')],sort)+'</select>')+'</div><div class="form-foot"><button class="btn">Apply</button>'+button('Clear','/products?view='+view+('&duplicates=1' if duplicates_only else ''),'secondary')+'</div></form>'
        if duplicate_count and not archived and not duplicates_only:
            body+='<div class="status-banner">'+notice(str(duplicate_count)+' active product records are possible duplicates. Archived records no longer trigger duplicate warnings.')+button('Review duplicate candidates','/products?view=active&duplicates=1','secondary small')+'</div>'
        if archived:
            body+='<form id="product-bulk-form" method="post" action="/products/bulk/restore" class="selection-bar"><strong>Archived product actions</strong><span class="helper">Restore returns products to Draft. Permanent delete is allowed only when no business history exists.</span><button class="btn secondary small">Restore selected</button><input name="confirm_delete" placeholder="Type DELETE for permanent delete"><button class="btn secondary small" formaction="/products/bulk/delete" data-confirm="Permanently delete only the selected unused archived products? Products with business history will be blocked.">Delete selected if safe</button></form><div class="card table-wrap archived-product-list"><table><thead><tr><th>Select</th><th>Product</th><th>SKU</th><th>Fact status</th><th>Price / stock</th><th>Actions</th></tr></thead><tbody>'
            for p in pr:
                img=('/'+e(p['img'])) if p.get('img') else ''
                thumb=(f'<img class="archived-product-thumb" src="{img}" alt="">' if img else '<span class="archived-product-thumb placeholder"></span>')
                restore=f'<form method="post" action="/products/{e(p["product_id"])}/restore" data-confirm="Restore this product to Draft for review?"><button class="btn secondary small">Restore product</button></form>'
                price=legacy.money(p['retail_price'],p['currency'] or 'INR')
                stock=e(p.get('_available_stock') if p.get('_available_stock') is not None else 'Not set')
                select=f'<input type="checkbox" form="product-bulk-form" name="product_ids" value="{e(p["product_id"])}" aria-label="Select {e(p["public_product_name"])}">'
                body+=f'<tr><td>{select}</td><td><div class="archived-product-cell">{thumb}<div><strong>{e(p["public_product_name"])}</strong><small>{e(p["colour"] or "Colour not set")}</small></div></div></td><td>{e(p["product_code"] or p.get("internal_sku") or p["product_id"])}</td><td><span class="pill {"good" if p["confirmed"] else "warn"}">{"Facts confirmed" if p["confirmed"] else "Facts need review"}</span></td><td>{price}<br><span class="tiny muted">Stock: {stock}</span></td><td><div class="toolbar">{button("View product","/products/"+p["product_id"],"secondary small")}{restore}</div></td></tr>'
            if not pr:body+='<tr><td colspan="6"><div class="empty">No archived products.</div></td></tr>'
            body+='</tbody></table></div>'
        else:
            body+='<form id="product-bulk-form" method="post" action="/products/bulk/archive" class="selection-bar"><strong>Bulk catalogue actions</strong><span class="helper">Select up to 100 products. Actions validate the full selection before changing data.</span><button class="btn secondary small" data-confirm="Archive the selected products? Existing orders, assets and history will be kept.">Archive selected</button><input name="category" placeholder="Category"><button class="btn secondary small" formaction="/products/bulk/category">Set category</button><input name="collection_name" placeholder="Merchandise collection"><button class="btn secondary small" formaction="/products/bulk/collection">Add to collection</button></form><div class="product-grid">'
            for p in pr:
                check='<input type="checkbox" form="product-bulk-form" name="product_ids" value="'+e(p['product_id'])+'" aria-label="Select '+e(p['public_product_name'])+'">'
                duplicate_badge='<span class="pill warn">Possible duplicate</span>' if p['duplicate_group'] else ''
                body+=f'<article class="product"><div class="message-top">{check}<span class="product-code-strong">{e(p["product_code"] or p.get("internal_sku") or p["product_id"])}</span>{duplicate_badge}</div><a href="/products/{e(p["product_id"])}"><img src="/{e(p["img"] or "")}" alt="{e(p["colour"])} product sample"></a><div class="pbody"><h3>{e(p["public_product_name"])}</h3><p>{e(p["colour"])} / {e(p["status"])}</p><div class="meta"><span class="pill {"good" if p["confirmed"] else "warn"}">{"Facts confirmed" if p["confirmed"] else "Facts need review"}</span>'
                lifecycle_form=f'<form method="post" action="/products/{e(p["product_id"])}/archive" data-confirm="Archive this product? It will be removed from active selectors while historical records stay intact."><button class="btn secondary small">Archive</button></form>'
                duplicate=f'<form method="post" action="/products/{e(p["product_id"])}/duplicate" data-confirm="Create a Draft copy of this product for review?"><button class="btn secondary small">Duplicate</button></form>'
                body+=f'</div><div class="divider"></div><div class="tiny muted">Retail: {legacy.money(p["retail_price"],p["currency"] or "INR")} / Available stock: {e(p.get("_available_stock") if p.get("_available_stock") is not None else "Not set")}</div><div class="toolbar section">{button("View product","/products/"+p["product_id"],"small")}<details class="row-actions"><summary>More actions</summary><div class="row-actions-menu">{duplicate}{lifecycle_form}</div></details></div></div></article>'
            if not pr:body+='<div class="card empty">'+('No possible duplicate candidates remain.' if duplicates_only else 'No products match these filters. Clear filters or add a new product.')+'</div>'
            body+='</div>'
        self.send_html(layout('Products',body,'products'))

    def product(self,pid):
        p=lifecycle.product(pid);archived=p.get('status')=='Archived'
        imgs=m.rows('SELECT * FROM product_images WHERE product_id=? ORDER BY is_primary DESC,image_role',(pid,))
        lifecycle_form=(f'<form method="post" action="/products/{e(pid)}/restore" data-confirm="Restore this product to Draft for review?"><button class="btn">Restore product</button></form>' if archived else f'<form method="post" action="/products/{e(pid)}/archive" data-confirm="Archive this product? It will be removed from active selectors while historical records stay intact."><button class="btn secondary">Archive</button></form>')
        contextual='' if archived else (f'<form method="post" action="/products/{e(pid)}/duplicate" data-confirm="Create a Draft copy of this product for review?"><button class="btn secondary">Duplicate</button></form>'+button('Generate assets','/creative-studio?product_id='+query(pid),'secondary')+button('Promote product','/campaign-builder?product='+query(pid),'secondary'))
        body=pagehead(p['public_product_name'],p['product_code'] or p['internal_sku'],button('Add product','/products/new','')+button('All products','/products','secondary')+contextual+lifecycle_form)
        if pid.startswith('PRD-LAUNCH-'):
            launch=next((json.loads(r['document']) for r in m.rows('SELECT document FROM launch_drafts WHERE document LIKE ?',('%'+pid+'%',)) if json.loads(r['document']).get('product_id')==pid),None)
            if launch:
                body+=notice('Saved from your product launch. Manage colours, sizes, listing photos and social posts there. Opening stock is applied after you review and approve the listing.')+button('Continue preparing product','/launch/'+launch['id'],'secondary')
        if archived:
            blockers=lifecycle.product_delete_blockers(pid)
            body+=notice('This product is archived. It is retained for business history but excluded from new customer selections, campaigns, creative generation and publishing. Restore it before returning it to active use.','warn')
            if blockers:body+=notice('Permanent deletion is blocked because this product is referenced by: '+', '.join(blockers)+'. Keep it archived to preserve history.','info')
            else:body+=f'<div class="card section"><h2>Permanent deletion</h2><p class="helper">This archived product has no protected business-history dependency. Type DELETE to remove it permanently.</p><form method="post" action="/products/{e(pid)}/delete" data-confirm="Permanently delete this unused archived product?"><input name="confirm_delete" placeholder="Type DELETE" required><button class="btn secondary">Permanently delete</button></form></div>'
        body+='<div class="two"><div><div class="gallery">'
        for image in imgs:body+=f'<figure style="margin:0"><img src="/{e(image["relative_path"])}" alt="{e(image["image_role"])}"><figcaption class="tiny muted">{e(image["image_role"])}</figcaption></figure>'
        body+='</div><div class="card section"><h2>Fact-check for campaigns</h2><p class="helper">Saving product changes resets its fact-check flag. Review the details above and cite supplier evidence before approving them for campaign use. A filename or an AI interpretation is not verification.</p><form method="post" action="/products/review">'
        body+=f'<input type="hidden" name="product_id" value="{e(pid)}">'+field('Evidence / verification note',f'<input name="evidence" value="{e(p["evidence"] or "")}" placeholder="Supplier specification or owner verification dated...">')
        body+=f'<p><label class="checkline"><input type="checkbox" name="confirmed" value="1" {"checked" if p["confirmed"] else ""}>I checked the product description, composition, prices and any claims. They are accurate for campaign drafting.</label></p><button class="btn">Save fact review</button></form></div>'
        pcost=truth.product_cost(pid)
        body+=f'<div class="card section"><h2>Product cost / COGS</h2><p class="helper">This is the current unit cost used for future profitability snapshots. Changing it never rewrites the cost already captured on historical orders.</p><form method="post" action="/products/{e(pid)}/cost"><div class="formgrid">'
        body+=field('Unit cost',f'<input name="cost_price" type="number" min="0" step="0.01" value="{e(pcost.get("cost_price") if pcost.get("cost_price") is not None else "")}" placeholder="Required before reliable margin reporting">')
        body+=field('Cost currency','<select name="cost_currency">'+options(['INR','GBP','USD','EUR'],pcost.get('currency') or p.get('currency') or 'INR')+'</select>')
        body+='</div><div class="form-foot"><button class="btn secondary">Save product cost</button></div></form></div></div><div class="card"><h2>Edit product details</h2><form method="post" action="/products/'+e(pid)+'/update"><div class="formgrid">'
        textfields=[('Customer-facing title','public_product_name'),('Product code / SKU','product_code'),('Colour','colour'),('Fabric / composition','fabric'),('Weave / motif','weave_or_motif'),('Category','category')]
        for label,key in textfields:body+=field(label,f'<input name="{key}" value="{e(p.get(key) or "")}">')
        for label,key in [('Retail price','retail_price'),('Wholesale price','wholesale_price'),('Minimum order quantity','moq')]:
            step='0.01' if 'price' in key else '1'
            body+=field(label,f'<input name="{key}" type="number" min="0" step="{step}" value="{e(p.get(key) if p.get(key) is not None else "")}">')
        body+=field('Currency','<select name="currency">'+options(['INR','GBP','USD','EUR'],p['currency'] or 'INR')+'</select>')
        if archived:body+=field('Status','<span class="pill warn">Archived</span><input type="hidden" name="status" value="Archived">','Restore the product before changing its active status.')
        else:body+=field('Status','<select name="status">'+options(['Draft','Active','Sold Out'],p['status'])+'</select>')
        body+='</div><div class="section">'+field('Description',f'<textarea name="description">{e(p["description"] or "")}</textarea>')+'</div>'+field('Tags',f'<input name="tags" value="{e(p["tags"] or "")}">')+'<p class="helper">Inventory is changed only from Stock & Locations so editing product copy cannot silently change stock.</p><div class="form-foot"><button class="btn">Save product details</button></div></form></div></div>'
        self.send_html(layout('Product review',body,'products'))

    def classic_tasks(self,q):
        ts=m.rows('SELECT t.*,c.full_name FROM m4_tasks t LEFT JOIN contacts c USING(contact_id) ORDER BY t.status DESC,t.due_date')
        camid=q.get('campaign',[''])[0];cid=q.get('contact',[''])[0]
        body=pagehead('Tasks & calendar','A simple date-ordered worklist. These are local reminders, not automatic sends.')
        body+='<div class="two"><div class="card"><h2>Your upcoming work</h2>'
        for t in ts:
            overdue=t['status']=='Open' and t['due_date']<dt.date.today().isoformat()
            body+=f'<div class="task-row"><span class="pill {"warn" if overdue else "good" if t["status"]=="Done" else "purple"}">{e(t["due_date"])}</span><div class="row-main"><strong>{e(t["title"])}</strong><div class="tiny muted">{e(ct.clean_display_name(t["full_name"]) or "Workspace task")} / {e(t["status"])}</div></div>'
            if t['status']!='Done':body+=f'<form method="post" action="/tasks/complete"><input type="hidden" name="id" value="{e(t["id"])}"><button class="btn secondary small">Done</button></form>'
            body+='</div>'
        if not ts:body+='<p class="helper">Nothing scheduled yet. Add a review task or follow-up date here. The app does not run when your Mac is off.</p>'
        body+='</div><div class="card"><h2>Add a task</h2><form method="post" action="/tasks/create">'+field('Task','<input name="title" required placeholder="Review first campaign drafts">')+'<div class="section">'+field('Due date','<input type="date" name="due_date" required>')+'</div>'
        body+=f'<input type="hidden" name="campaign_id" value="{e(camid)}"><input type="hidden" name="contact_id" value="{e(cid)}"><div class="form-foot"><button class="btn">Save task</button></div></form></div></div>'
        self.send_html(layout('Tasks',body,'tasks'))

    def settings(self,q):
        # Settings reads the enriched AI ledger; make its migration idempotently
        # available even when this page is reached from a partially initialised
        # workspace/test fixture. Never assume another route ran migrations first.
        ai_router.initialise()
        s=m.settings()
        body=pagehead('Settings & AI','Your real business identity, drafting preferences and private local AI connection.')
        if q.get('saved'):body+='<div class="status-banner">'+notice('Business settings saved. Existing drafts may need regeneration if sender details changed.','success')+'</div>'
        if q.get('ai_saved'):body+='<div class="status-banner">'+notice('AI configuration saved locally. Run Test connection before AI generation is enabled.','success')+'</div>'
        body+='<div class="two"><div class="card"><h2>Business identity</h2><form method="post" action="/settings/update"><div class="formgrid">'
        for label,key,hint in [('Actual brand name','brand_name','Keep Brand name pending until you choose your brand.'),('Your business WhatsApp number','business_whatsapp','Your number, including country code; never a prospect\'s number.'),('Your business email','business_email','Used for the sender-readiness check.'),('Booking URL','booking_url','Optional HTTPS appointment link.'),('Public Base URL','public_base_url','Leave blank while testing locally. This field does not deploy the CRM.')]:
            body+=field(label,f'<input name="{key}" value="{e(s.get(key,""))}">',hint)
        body+=field('Default currency','<select name="default_currency">'+options(['INR','GBP','USD','EUR'],s.get('default_currency','INR'))+'</select>')+'</div><div class="form-foot"><button class="btn">Save business settings</button></div></form></div><div class="card"><h2>Local by design</h2><p class="helper">This team-testing release runs locally. External provider writes are blocked by default, sample contacts use non-deliverable addresses, and real provider actions require explicit administrator opt-in.</p>'+notice('Do not open a tunnel, forward a router port or expose this local Python server publicly. Production hosting needs a separate security-reviewed deployment.')+f'<div class="section"><h3>Your saved data</h3><p class="helper">The team launcher uses the isolated test database in this release data folder. Test data persists across restarts and never imports your private development workspace.</p></div></div></div>'
        ai_state=m.ai_health();ai_good=ai_state.get('status')=='Connected';ai_status=ai_state.get('status','Not connected')
        if q.get('ai_test'):body+='<div class="status-banner">'+notice('AI connection test: '+q['ai_test'][0], 'success' if q['ai_test'][0]=='Connected' else 'warn')+'</div>'
        owner_message=ai_state.get('detail','')
        if ai_status=='Billing / quota issue':owner_message='AI is paused because the OpenAI API account has no available billing or quota capacity. Resolve that in the API account, then test the connection again.'
        elif ai_status in {'Provider unavailable','Rate limited'}:owner_message='AI is temporarily unavailable. Your CRM data is safe; try the connection test again later.'
        elif ai_status=='Model unavailable':owner_message='The configured AI model is not currently available to this API account. Open Advanced AI settings if you need to change it.'
        elif ai_status=='Connected':owner_message='AI access has been verified. Product and marketing AI features can run when their workflow allows it.'
        body+='<section class="card section" id="ai"><div class="message-top"><div><div class="eyebrow">AI ASSISTANT</div><h2>AI connection</h2><p class="helper">'+e(owner_message)+'</p></div><span class="pill '+('good' if ai_good else 'warn')+'">'+e(ai_status)+'</span></div>'
        if ai_state.get('checked_at'):body+='<p class="tiny muted">Last provider check: '+e(ai_state['checked_at'])+(' · '+e(ai_state.get('model','')) if ai_state.get('model') else '')+'</p>'
        body+='<details class="manual-entry brand-details section"><summary>Advanced AI provider setup</summary><div class="manual-body"><p class="helper"><strong>Advanced AI model setting:</strong> Provider credentials and raw model routing are administrator settings. Saved secret values are never displayed.</p><form method="post" action="/ai/save"><div class="section">'+field('OpenAI API key','<input type="password" name="api_key" autocomplete="new-password" placeholder="Leave empty to keep the existing key">','Saved privately on this machine; never enter customer data or API keys into chat.')+'</div><div class="section">'+field('Marketing-copy model',f'<input name="model" value="{e(s.get("ai_model","gpt-6-luna"))}">','Only change this if you know which model your API account should use. Other AI tasks can be configured under Advanced AI routing.')+'</div><div class="form-foot"><button class="btn">Save provider setup</button></div></form></div></details>'
        if m.secret():body+='<div class="ai-status-panel section"><div><h3>Check whether AI is ready</h3><p>Test every configured business AI capability before relying on generation. A model is not marked Ready unless this API account can actually use it.</p></div><div class="ai-actions"><form method="post" action="/ai/test-all"><button class="btn">Test AI configuration</button></form><a class="btn secondary" href="/ai-governance">Advanced AI settings</a></div></div><form method="post" action="/ai/disconnect" class="section" data-confirm="Remove the key stored by this app? An environment-provided key is not removed."><button class="btn secondary small">Remove stored key</button></form>'
        matrix=ai_router.capability_matrix(force=False) if m.secret() else []
        if q.get('ai_matrix'):body+='<div class="status-banner">'+notice('AI capability test completed: '+e(q['ai_matrix'][0])+' of '+e(q.get('ai_total',['0'])[0])+' validated as Ready.','success' if q['ai_matrix'][0]==q.get('ai_total',[''])[0] else 'warn')+'</div>'
        if matrix:
            body+='<div class="table-wrap section"><table><tr><th>Capability</th><th>Provider</th><th>Model</th><th>Status</th><th>Fallback</th></tr>'
            for row in matrix:
                status=row.get('status','Configuration required');cls='good' if status=='Ready' else 'warn'
                body+=f'<tr><td>{e(row.get("route_key"))}</td><td>{e(row.get("provider"))}</td><td>{e(row.get("model") or "Not configured")}</td><td><span class="pill {cls}">{e(status)}</span><div class="tiny muted">{e(row.get("detail"))}</div></td><td>{e(row.get("fallback_model") or "None")}</td></tr>'
            body+='</table></div>'
        body+='</section><details class="manual-entry section"><summary>Privacy: what information can be sent to AI?</summary><div class="manual-body"><p class="helper section">Campaign drafting can use your business journey, campaign goal, tone, brief, confirmed preferences, verified product facts and approved knowledge. Structured customer names, email addresses, phone numbers, usernames, scraped biographies, images and your full contact database are excluded.</p><p class="helper">Free-text notes may still contain personal information, so review them before using AI. API usage and billing are separate from ChatGPT.</p>'+notice('AI generation remains disabled for protected workflows until the connection test confirms the saved key and configured model.')+'</div></details>'
        uses=m.rows('''SELECT task_key,provider,model,status,input_units,output_units,estimated_cost,error,error_category,retryable,attempts,provider_request_id,duration_ms,object_type,object_id,created_at FROM v13_ai_usage ORDER BY created_at DESC LIMIT 50''') if current_table_exists('v13_ai_usage') else []
        groups=m.rows('SELECT task_key,model,error_category,failure_count,last_seen_at,resolved FROM v42_ai_failure_groups WHERE resolved=0 ORDER BY last_seen_at DESC LIMIT 12') if current_table_exists('v42_ai_failure_groups') else []
        body+='<div class="card section"><div class="message-top"><div><h2>AI usage & failures</h2><p class="helper">Repeated identical failures are grouped. Missing credentials, invalid models and invalid requests stop immediately instead of entering retry loops.</p></div></div>'
        if groups:
            body+='<h3>Repeated failures needing attention</h3><div class="table-wrap"><table><tr><th>Task</th><th>Model</th><th>Reason</th><th>Count</th><th>Latest</th></tr>'
            for g in groups:body+=f'<tr><td>{e(g["task_key"])}</td><td>{e(g["model"])}</td><td>{e(g["error_category"])}</td><td>{e(g["failure_count"])}</td><td>{e(g["last_seen_at"])}</td></tr>'
            body+='</table></div>'
        if uses:
            body+='<h3 class="section">Recent requests</h3><div class="table-wrap"><table><tr><th>When</th><th>Task</th><th>Provider / model</th><th>Result</th><th>Attempts</th><th>Usage</th><th>Details</th></tr>'
            for u in uses:
                detail=(u.get('error_category') or '')+((': '+u.get('error','')) if u.get('error') else '')
                related=(u.get('object_type') or '')+(' '+u.get('object_id','') if u.get('object_id') else '')
                related_html=('<br><span class="tiny muted">'+e(related)+'</span>') if related.strip() else ''
                body+=f'<tr><td>{e(u["created_at"])}</td><td>{e(u["task_key"])}</td><td>{e(u["provider"])}<br><span class="tiny muted">{e(u["model"])}</span></td><td>{e(u["status"])}</td><td>{e(u.get("attempts") or 1)}</td><td>{e(u.get("input_units") or 0)} in / {e(u.get("output_units") or 0)} out<br><span class="tiny muted">{e(u.get("duration_ms") or 0)} ms</span></td><td>{e(detail or "Completed")}{related_html}</td></tr>'
            body+='</table></div>'
        else:body+='<p class="helper">No AI requests have been made from this workspace.</p>'
        body+='</div>'
        self.send_html(layout('Settings & AI',body,'settings'))

    def showrooms(self):
        q=urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query);val=lambda k,d='':(q.get(k) or [d])[0]
        view=val('view','active');archived=view=='archived';search=val('search').strip();state=val('state');sort=val('sort','newest')
        if sort not in {'newest','oldest','name','name_desc','views'}:sort='newest'
        where=["coalesce(s.status,'Draft') "+('=' if archived else '<>')+" 'Archived'"];args=[]
        if search:where.append('(s.title LIKE ? OR c.full_name LIKE ? OR c.username LIKE ?)');args.extend(['%'+search+'%']*3)
        if state in {'Draft','Inactive'} and not archived:where.append("coalesce(s.status,'Draft')=?");args.append(state)
        order={'newest':'s.created_at DESC','oldest':'s.created_at','name':'s.title COLLATE NOCASE','name_desc':'s.title COLLATE NOCASE DESC','views':'legacy_views DESC,s.created_at DESC'}[sort]
        shows=m.rows("""SELECT s.*,c.full_name,c.username,
        (SELECT count(*) FROM showroom_products p WHERE p.showroom_id=s.showroom_id) products,
        (SELECT count(*) FROM showroom_views v WHERE v.showroom_id=s.showroom_id) legacy_views
        FROM showrooms s LEFT JOIN contacts c USING(contact_id) WHERE """+' AND '.join(where)+' ORDER BY '+order,args)
        active_count=(m.one("SELECT count(*) n FROM showrooms WHERE coalesce(status,'Draft')<>'Archived'") or {'n':0})['n'];archived_count=(m.one("SELECT count(*) n FROM showrooms WHERE status='Archived'") or {'n':0})['n']
        actions=button(f'Active ({active_count})','/showrooms?view=active','' if not archived else 'secondary')+button(f'Archived ({archived_count})','/showrooms?view=archived','' if archived else 'secondary')
        if not archived:actions+=button('Create selection','/showrooms/new')
        body=pagehead('Archived customer selections' if archived else 'Customer selections','Archived customer selections stay in history but cannot be opened.' if archived else 'Create a curated digital product selection for a customer or prospect. Physical stock locations are managed under Stock & locations.',actions)
        body+='<form method="get" class="card compact-filter"><input type="hidden" name="view" value="'+e(view)+'"><div class="filter-grid">'+field('Search','<input name="search" value="'+e(search)+'" placeholder="Collection title or contact...">')
        if not archived:body+=field('State','<select name="state">'+options([('Draft','Active preview'),('Inactive','Inactive / preview off')],state,empty='All states')+'</select>')
        body+=field('Sort','<select name="sort">'+options([('newest','Newest'),('oldest','Oldest'),('name','Name A–Z'),('name_desc','Name Z–A'),('views','Most legacy views')],sort)+'</select>')+'</div><div class="form-foot"><button class="btn">Apply</button>'+button('Clear','/showrooms?view='+view,'secondary')+'</div></form>'
        if q.get('deleted'):body+='<div class="status-banner">'+notice('Unused archived customer selection permanently deleted.','success')+'</div>'
        if q.get('archived'):body+='<div class="status-banner">'+notice('Customer selection archived and its preview disabled.','success')+'</div>'
        body+='<div class="status-banner">'+notice('Preview counts can include your own testing. They are shown only as legacy page loads, not verified customer visits.')+'</div><div class="campaign-grid">'
        for s in shows:
            status=s.get('status') or 'Draft'
            if archived:
                lifecycle_action=f'<form method="post" action="/showrooms/{e(s["showroom_id"])}/restore" data-confirm="Restore this customer selection as an inactive local preview?"><button class="btn small">Restore selection</button></form>'
                state_action=''
            else:
                lifecycle_action=f'<form method="post" action="/showrooms/{e(s["showroom_id"])}/archive" data-confirm="Archive this customer selection? Its preview will be disabled and history will be preserved."><button class="btn secondary small">Archive selection</button></form>'
                if status=='Inactive':state_action=f'<form method="post" action="/showrooms/{e(s["showroom_id"])}/activate"><button class="btn secondary small">Activate preview</button></form>'
                else:state_action=f'<form method="post" action="/showrooms/{e(s["showroom_id"])}/deactivate" data-confirm="Turn off this collection preview without archiving it?"><button class="btn secondary small">Set inactive</button></form>'
            body+=f'<div class="card"><span class="pill {"warn" if archived or status=="Inactive" else "purple"}">{"Archived" if archived else "Inactive" if status=="Inactive" else "Active preview"}</span><h3>{e(s["title"])}</h3><p class="helper">For {e(ct.clean_display_name(s["full_name"]) or s["username"] or "a general audience")}<br>{s["products"]} products / {e(s["pricing_mode"])} pricing<br>{s["legacy_views"]} legacy page loads</p><div class="toolbar section">{button("Manage selection","/showrooms/"+s["showroom_id"],"secondary small")}{state_action}{lifecycle_action}</div></div>'
        if not shows:body+='<div class="card empty">'+('No archived customer selections.' if archived else 'No customer selections match these filters. Clear filters or create a selection.')+'</div>'
        body+='</div>'
        self.send_html(layout('Customer selections',body,'showrooms'))

    def showroom(self,sid):
        q=getattr(self,'q',{})
        s=m.one('''SELECT s.*,c.full_name FROM showrooms s LEFT JOIN contacts c USING(contact_id) WHERE showroom_id=?''',(sid,))
        if not s:raise ValueError('Customer selection not found.')
        archived=s.get('status')=='Archived';blockers=lifecycle.showroom_delete_blockers(sid) if archived else []
        lifecycle_form=(f'<form method="post" action="/showrooms/{e(sid)}/restore" data-confirm="Restore this customer selection as an inactive local preview?"><button class="btn">Restore selection</button></form>' if archived else f'<form method="post" action="/showrooms/{e(sid)}/archive" data-confirm="Archive this customer selection? Its preview link will stop working but history will be preserved."><button class="btn secondary">Archive selection</button></form>')
        preview='' if archived else button('Open collection preview','/s/'+s['slug'])
        body=pagehead(s['title'],f'For {ct.clean_display_name(s["full_name"]) or "a general audience"} / {"archived" if archived else "local preview"}',preview+button('Create selection','/showrooms/new','')+button('All selections','/showrooms','secondary')+lifecycle_form)
        if archived:body+=notice('This customer selection is archived. Its preview is disabled and it is excluded from new deal selection. Restore it before using it again.','warn')
        if q.get('operations_saved'):body+='<div class="status-banner">'+notice('Collection contact details saved.','success')+'</div>'
        if q.get('state_saved'):body+='<div class="status-banner">'+notice('Selection availability updated.','success')+'</div>'
        body+=notice('The word personalised is not an access-control guarantee. Keep this local prototype off the public internet. No test preview is treated as recipient engagement.')
        details=v24.showroom_details(sid)
        if not archived:
            current_state=s.get('status') or 'Draft'
            state_action=(f'<form method="post" action="/showrooms/{e(sid)}/activate"><button class="btn secondary">Activate preview</button></form>' if current_state=='Inactive' else f'<form method="post" action="/showrooms/{e(sid)}/deactivate" data-confirm="Turn off the collection preview without archiving it?"><button class="btn secondary">Set inactive</button></form>')
            body+='<div class="card section"><div class="message-top"><div><h2>Selection availability</h2><p class="helper">Turn the customer preview on or off without deleting its history.</p></div>'+state_action+'</div><details class="manual-entry brand-details"><summary>Optional contact or visit information</summary><div class="manual-body"><p class="helper section">Only add these details if they are useful for this customer selection. Physical stock locations are managed separately.</p><form method="post" action="/showrooms/'+e(sid)+'/details"><div class="formgrid">'+field('Address','<textarea name="address">'+e(details.get('address') or '')+'</textarea>')+field('Contact email','<input name="contact_email" value="'+e(details.get('contact_email') or '')+'">')+field('Contact phone','<input name="contact_phone" value="'+e(details.get('contact_phone') or '')+'">')+field('Opening hours','<textarea name="opening_hours" placeholder="Mon–Sat 10:00–18:00">'+e(details.get('opening_hours') or '')+'</textarea>')+'</div>'+field('Notes','<textarea name="staff_notes">'+e(details.get('staff_notes') or '')+'</textarea>')+'<div class="form-foot"><button class="btn secondary">Save optional details</button></div></form></div></details></div>'
        selected={r['product_id'] for r in m.rows('SELECT product_id FROM showroom_products WHERE showroom_id=?',(sid,))}
        if not archived:
            contacts=m.rows("SELECT contact_id,full_name,username,contact_type FROM contacts WHERE qualification_status NOT IN ('Irrelevant','Do Not Contact') ORDER BY full_name LIMIT 750")
            body+='<div class="card section"><h2>Edit customer selection</h2><form method="post" action="/showrooms/'+e(sid)+'/update"><div class="formgrid">'
            body+=field('Contact','<select name="contact_id">'+options([(c['contact_id'],(ct.clean_display_name(c['full_name']) or c['username'])+' / '+c['contact_type']) for c in contacts],s.get('contact_id') or '',empty='Generic collection / no contact')+'</select>')+field('Collection title',f'<input name="title" value="{e(s["title"])}" required>')
            body+=field('Pricing mode','<select name="pricing_mode">'+options(['Hidden','Wholesale','Retail'],s['pricing_mode'])+'</select>')+field('Button label',f'<input name="cta_text" value="{e(s.get("cta_text") or "Ask about this piece")}">')+'</div><div class="section">'+field('Personal introduction',f'<textarea name="intro_text">{e(s.get("intro_text") or "")}</textarea>')+'</div><h3 class="section">Products</h3><div class="checkgrid">'
            for p in m.products():
                duplicate='<span class="pill warn">Possible duplicate</span>' if p.get('duplicate_group') else ''
                body+=f'<label class="check"><input name="product_ids" type="checkbox" value="{e(p["product_id"])}" {"checked" if p["product_id"] in selected else ""}><img src="/{e(p["img"] or "")}" alt="{e(p["colour"])} saree"><div class="row-main"><strong>{e(p["public_product_name"])}</strong><div class="product-choice-meta"><span class="product-code-strong">{e(p["product_code"] or p.get("internal_sku") or p["product_id"])}</span>{duplicate}<span class="tiny muted">{"Facts confirmed" if p["confirmed"] else "Review needed"}</span></div></div></label>'
            body+='</div><div class="form-foot"><button class="btn">Save selection</button></div></form></div>'
        body+='<div class="product-grid section">'
        for p in m.products(include_archived=True):
            if p['product_id'] in selected:body+=f'<div class="product"><img src="/{e(p["img"] or "")}" alt="{e(p["colour"])} saree"><div class="pbody"><h3>{e(p["public_product_name"])}</h3><span class="pill {"warn" if p.get("status")=="Archived" else "good" if p["confirmed"] else "warn"}">{"Product archived" if p.get("status")=="Archived" else "Facts confirmed" if p["confirmed"] else "Facts need review"}</span></div></div>'
        body+='</div>'
        if archived:
            body+='<div class="card section"><h2>Permanent removal</h2>'
            if blockers:body+=notice('Permanent deletion is blocked because this customer selection has business history: '+', '.join(blockers)+'. Keep it archived instead.','warn')
            else:body+='<p class="helper">This archived customer selection has no linked deals or recorded engagement. Type DELETE to permanently remove the collection and its product selections.</p><form method="post" action="/showrooms/'+e(sid)+'/delete" data-confirm="Permanently delete this unused customer selection? This cannot be undone.">'+field('Confirmation','<input name="confirm_delete" autocomplete="off" placeholder="DELETE">')+'<button class="btn secondary section">Delete selection permanently</button></form>'
            body+='</div>'
        self.send_html(layout('Customer selection',body,'showrooms'))

    def new_showroom(self,q):
        cid=q.get('contact_id',[''])[0]
        search=q.get('search',[''])[0]
        contacts=m.rows("SELECT c.contact_id,c.full_name,c.username,c.contact_type FROM contacts c LEFT JOIN m42_contact_meta cm USING(contact_id) WHERE cm.archived_at IS NULL AND (c.full_name LIKE ? OR c.username LIKE ?) ORDER BY c.full_name LIMIT 60",('%'+search+'%','%'+search+'%')) if search else []
        if cid and cid not in {c['contact_id'] for c in contacts}:contacts.insert(0,m.contact(cid))
        body=pagehead('Create a customer selection','Choose products for a customer or prospect. This creates a curated digital preview, not a physical showroom or stock location.',button('All selections','/showrooms','secondary'))
        body+='<form class="filters" method="get">'+field('Find a contact','<input name="search" value="'+e(search)+'" placeholder="Example: LemonChiffon">')+'<button class="btn secondary">Search</button></form>'
        body+='<form method="post" action="/showrooms/create"><div class="card"><div class="formgrid">'
        body+=field('Contact','<select name="contact_id">'+options([(c['contact_id'],(ct.clean_display_name(c['full_name']) or c['username'])+' / '+c['contact_type']) for c in contacts],cid,empty='Generic collection / no contact')+'</select>')+field('Collection title','<input name="title" value="A collection selected for you" required>')
        body+=field('Pricing mode','<select name="pricing_mode">'+options(['Hidden','Wholesale','Retail'])+'</select>')+field('Button label','<input name="cta_text" value="Ask about this piece">')+'</div><div class="section">'+field('Personal introduction','<textarea name="intro_text" placeholder="A selected collection for your review."></textarea>')+'</div></div><div class="card section"><h2>Select products</h2><div class="checkgrid">'
        for p in m.products():
            duplicate='<span class="pill warn">Possible duplicate</span>' if p.get('duplicate_group') else ''
            body+=f'<label class="check"><input name="product_ids" type="checkbox" value="{e(p["product_id"])}"><img src="/{e(p["img"] or "")}" alt="{e(p["colour"])} saree"><div class="row-main"><strong>{e(p["public_product_name"])}</strong><div class="product-choice-meta"><span class="product-code-strong">{e(p["product_code"] or p.get("internal_sku") or p["product_id"])}</span>{duplicate}<span class="tiny muted">{"Facts confirmed" if p["confirmed"] else "Review needed"}</span></div></div></label>'
        body+='</div><div class="form-foot"><button class="btn">Create selection preview</button></div></div></form>'
        self.send_html(layout('Create selection',body,'showrooms'))

    def public_showroom(self,slug):
        s=m.one("SELECT s.*,c.full_name FROM showrooms s LEFT JOIN contacts c USING(contact_id) WHERE slug=? AND coalesce(s.status,'Draft') NOT IN ('Archived','Inactive') AND coalesce(s.public_enabled,1)=1",(slug,))
        if not s:raise ValueError('Customer selection not found.')
        ids={p['product_id'] for p in m.rows('SELECT product_id FROM showroom_products WHERE showroom_id=?',(s['showroom_id'],))}
        st=m.settings();brand=st.get('brand_name','Brand name pending')
        body=f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{e(s['title'])}</title><style>{re.search(r'<style>(.*?)</style>',old_layout('',''),re.S).group(1)}</style><link rel="stylesheet" href="/ui/studio.css"></head><body><div class="showroom-public"><div class="public-header"><strong>{e(brand)}</strong><a class="link tiny" href="/showrooms/{e(s['showroom_id'])}">Back to workspace &rarr;</a></div><div class="section">{notice('Local preview only. Your visit is not logged as a customer visit. Product enquiry buttons are test-only in this release.')}</div><div class="eyebrow section">A personal collection {('for '+e(ct.clean_display_name(s['full_name']))) if ct.clean_display_name(s['full_name']) else ''}</div><h1 class="hero-title">{e(s['title'])}</h1><p class="helper">{e(s['intro_text'] or 'A selection of pieces to explore at your own pace.')}</p><div class="product-grid">'''
        for p in m.products():
            if p['product_id'] not in ids:continue
            price=''
            if s['pricing_mode'] in {'Retail','Wholesale'}:
                amount=p['retail_price'] if s['pricing_mode']=='Retail' else p['wholesale_price']
                price=legacy.money(amount,p['currency'] or 'INR') if amount is not None and p['confirmed'] else 'Price on enquiry / details to be confirmed'
            body+=f'<article class="product"><img src="/{e(p["img"] or "")}" alt="{e(p["colour"])} saree"><div class="pbody"><span class="tiny muted">{e(p["product_code"])}</span><h3>{e(p["public_product_name"])}</h3><p>{e(p["colour"])} / {"Verified details" if p["confirmed"] else "Imported description - not verified"}</p><p class="section"><strong>{e(price)}</strong></p><details class="source-box"><summary>View product details</summary><p>{e(p["description"] or "Detailed information has not been supplied yet.")}</p></details><div class="section">{button(e(s["cta_text"] or "Ask about this piece"),"/interest/"+slug+"/"+p["product_id"],"secondary")}</div></div></article>'
        body+='</div></div></body></html>'
        self.send_html(body)

    def showroom_interest(self,slug,pid):
        match=m.one('''SELECT s.showroom_id FROM showrooms s JOIN showroom_products sp USING(showroom_id) JOIN products p ON p.product_id=sp.product_id
          WHERE s.slug=? AND sp.product_id=? AND coalesce(s.status,'Draft') NOT IN ('Archived','Inactive') AND coalesce(s.public_enabled,1)=1 AND coalesce(p.status,'Draft')<>'Archived' ''',(slug,pid))
        if not match:raise ValueError('This product does not belong to that showroom.')
        body=pagehead('Enquiry preview','Nothing has been sent to the prospect or your business.')+notice('This is a local interface test. It is not stored as customer interest and does not open WhatsApp automatically.')+'<div class="section">'+button('Return to the collection','/s/'+slug)+'</div>'
        self.send_html(layout('Enquiry preview',body,'showrooms'))


def initialise():
    if not db_layer.USING_POSTGRES and not m.DB.is_file():raise RuntimeError('No database workspace is available yet. Start the application with the included Team Test launcher.')
    if db_layer.USING_POSTGRES:db_layer.bootstrap_base_schema()
    legacy.ensure_schema();m.initialise();v5.initialise();pe.initialise();ce.initialise();cs.initialise();bos.initialise();integ.initialise();pc.initialise();oc.initialise();int14.initialise();int14.patch_legacy();ai_router.initialise();connection_service.initialise();hc.initialise();po.initialise();v24.initialise();v27m.initialise();truth.initialise();v37br.initialise();v54_repair.initialise();team_beta2.initialise();team_beta6.initialise();po.bootstrap_processes(500);bos.bootstrap_events();bos.generate_recommendations()
    import durable_worker;durable_worker.initialise()
    launch_studio.initialise()
    if rc.IS_PRODUCTION:
        gaps=rc.production_gaps()
        if gaps:raise RuntimeError('Production configuration is incomplete: '+' '.join(gaps))
        if not pc.auth_enabled():raise RuntimeError('Production mode requires database sign-in. Enable authentication locally before deploying, or migrate an authenticated workspace.')
        if not pc.users():raise RuntimeError('Production mode requires at least one active user account.')
        if not pc.production_mfa_ready():raise RuntimeError('Production mode requires MFA on at least one active Owner account. Configure MFA locally before deployment.')


def run(open_browser=False):
    initialise()
    port=rc.PORT
    try:server=ThreadingHTTPServer((rc.BIND_HOST,port),App)
    except OSError as err:
        if err.errno in {48,98}:raise RuntimeError('Port 8765 is already in use. In the Terminal running the older CRM, press Control+C, then run this command again. Do not run two versions at once.') from None
        raise
    server.daemon_threads=True
    inbox_stop=threading.Event()
    if not rc.IS_PRODUCTION:
        # The local launcher permits one process. Production uses leased durable jobs.
        with m.connect() as con:
            con.execute("UPDATE launch_jobs SET status='Failed',message='Preparation was interrupted by a restart. Review the draft and retry the action.',finished_at=CURRENT_TIMESTAMP WHERE status='Running'")
        threading.Thread(target=launch_studio.worker,args=(inbox_stop,),daemon=True,name='product-launch-worker').start()
        threading.Thread(target=pe.watch_inbox_loop,args=(inbox_stop,60),daemon=True,name='product-inbox-watcher').start()
        threading.Thread(target=ce.watch_creative_loop,args=(inbox_stop,75),daemon=True,name='creative-job-watcher').start()
        pc.start_scheduler()
        import durable_worker
        threading.Thread(target=durable_worker.run_local,args=(inbox_stop,2.0),daemon=True,name='durable-local-worker').start()
    display_url=rc.PUBLIC_BASE_URL if rc.IS_PRODUCTION and rc.PUBLIC_BASE_URL else f'http://127.0.0.1:{port}'
    print(f'\n{PRODUCT_NAME} {APP_VERSION} ({BUILD_ID}) is running at {display_url}',flush=True)
    if rc.IS_PRODUCTION:
        print('Production mode: PostgreSQL/object storage/public HTTPS are required. Run durable_worker.py as a separate worker service.\n',flush=True)
    else:
        print('Local mode: existing SQLite/media remain supported. Cloud-ready PostgreSQL, object storage, health/readiness endpoints and separate durable worker support are included. Keep Terminal open. Control+C stops the app.\n',flush=True)
    if open_browser and not rc.IS_PRODUCTION:threading.Timer(1.0,lambda:webbrowser.open(f'http://127.0.0.1:{port}/')).start()
    try:server.serve_forever()
    except KeyboardInterrupt:print('\nCRM stopped. Team test data remains in the release data folder.')
    finally:
        inbox_stop.set();server.server_close()

if __name__=='__main__':
    try:run()
    except Exception as err:
        if isinstance(err,RuntimeError) or db_layer.is_database_error(err):print('\nCould not start: '+str(err));raise SystemExit(1)
        raise
