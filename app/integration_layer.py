from __future__ import annotations

import base64
import datetime as dt
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any

# Team Test compatibility: secure credential features require cryptography, but
# the offline CRM can still start without optional third-party packages.
try:
    from cryptography.fernet import Fernet, InvalidToken
    CRYPTOGRAPHY_AVAILABLE=True
except ImportError:
    CRYPTOGRAPHY_AVAILABLE=False
    class InvalidToken(Exception):
        pass
    class Fernet:
        def __init__(self,*args,**kwargs):
            raise RuntimeError('Secure credential/MFA support requires the optional full runtime. Run PREPARE_FULL_RUNTIME.command while online, then restart the CRM.')
        @staticmethod
        def generate_key():
            raise RuntimeError('Secure credential/MFA support requires the optional full runtime. Run PREPARE_FULL_RUNTIME.command while online, then restart the CRM.')

import marketing as m
import runtime_config as rc
import db_layer
import media_store
import v35_truth as truth

ROOT = Path(__file__).resolve().parent
VAULT_KEY_PATH = Path(os.environ.get('CRM_INTEGRATION_KEY_PATH', str(Path.home()/'.config'/'commerce-crm'/'integration-vault.key')))

SCHEMA = r'''
CREATE TABLE IF NOT EXISTS v10_connections(
 id TEXT PRIMARY KEY,
 connector_key TEXT NOT NULL,
 provider TEXT NOT NULL,
 label TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'Available to connect',
 auth_type TEXT NOT NULL DEFAULT 'token',
 account_name TEXT DEFAULT '',
 external_account_id TEXT DEFAULT '',
 scopes_json TEXT NOT NULL DEFAULT '[]',
 config_json TEXT NOT NULL DEFAULT '{}',
 capabilities_json TEXT NOT NULL DEFAULT '[]',
 last_tested_at TEXT,
 last_sync_at TEXT,
 last_success_at TEXT,
 last_error TEXT DEFAULT '',
 created_at TEXT DEFAULT CURRENT_TIMESTAMP,
 updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS v10_connections_key ON v10_connections(connector_key,status);
CREATE TABLE IF NOT EXISTS v10_connection_secrets(
 connection_id TEXT NOT NULL,
 secret_key TEXT NOT NULL,
 encrypted_value BLOB NOT NULL,
 hint TEXT DEFAULT '',
 updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
 PRIMARY KEY(connection_id,secret_key),
 FOREIGN KEY(connection_id) REFERENCES v10_connections(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS v10_api_logs(
 id TEXT PRIMARY KEY,
 connection_id TEXT,
 operation TEXT NOT NULL,
 method TEXT NOT NULL,
 endpoint TEXT NOT NULL,
 status_code INTEGER,
 success INTEGER NOT NULL DEFAULT 0,
 duration_ms INTEGER,
 error_class TEXT DEFAULT '',
 error_message TEXT DEFAULT '',
 created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS v10_api_logs_connection ON v10_api_logs(connection_id,created_at);
CREATE TABLE IF NOT EXISTS v10_sync_runs(
 id TEXT PRIMARY KEY,
 connection_id TEXT NOT NULL,
 sync_type TEXT NOT NULL,
 direction TEXT NOT NULL DEFAULT 'pull',
 status TEXT NOT NULL DEFAULT 'Running',
 records_seen INTEGER DEFAULT 0,
 records_created INTEGER DEFAULT 0,
 records_updated INTEGER DEFAULT 0,
 records_skipped INTEGER DEFAULT 0,
 errors INTEGER DEFAULT 0,
 summary_json TEXT NOT NULL DEFAULT '{}',
 started_at TEXT DEFAULT CURRENT_TIMESTAMP,
 finished_at TEXT,
 FOREIGN KEY(connection_id) REFERENCES v10_connections(id)
);
CREATE INDEX IF NOT EXISTS v10_sync_runs_connection ON v10_sync_runs(connection_id,started_at);
CREATE TABLE IF NOT EXISTS v10_external_objects(
 connection_id TEXT NOT NULL,
 object_type TEXT NOT NULL,
 external_id TEXT NOT NULL,
 local_type TEXT DEFAULT '',
 local_id TEXT DEFAULT '',
 external_updated_at TEXT DEFAULT '',
 payload_json TEXT NOT NULL DEFAULT '{}',
 synced_at TEXT DEFAULT CURRENT_TIMESTAMP,
 PRIMARY KEY(connection_id,object_type,external_id)
);
CREATE INDEX IF NOT EXISTS v10_external_objects_local ON v10_external_objects(local_type,local_id);
CREATE TABLE IF NOT EXISTS v10_channel_metrics(
 id TEXT PRIMARY KEY,
 connection_id TEXT NOT NULL,
 channel TEXT NOT NULL,
 metric_date TEXT NOT NULL,
 campaign_external_id TEXT DEFAULT '',
 campaign_name TEXT DEFAULT '',
 spend REAL DEFAULT 0,
 impressions INTEGER DEFAULT 0,
 clicks INTEGER DEFAULT 0,
 conversions REAL DEFAULT 0,
 revenue REAL DEFAULT 0,
 currency TEXT DEFAULT '',
 source_json TEXT NOT NULL DEFAULT '{}',
 UNIQUE(connection_id,channel,metric_date,campaign_external_id)
);
CREATE INDEX IF NOT EXISTS v10_channel_metrics_date ON v10_channel_metrics(channel,metric_date);
CREATE TABLE IF NOT EXISTS v10_oauth_states(
 state TEXT PRIMARY KEY,
 provider TEXT NOT NULL,
 connection_id TEXT NOT NULL,
 redirect_uri TEXT NOT NULL,
 scopes_json TEXT NOT NULL DEFAULT '[]',
 created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS v10_unified_campaigns(
 id TEXT PRIMARY KEY,
 name TEXT NOT NULL,
 objective TEXT NOT NULL,
 audience_query TEXT DEFAULT '',
 product_ids_json TEXT NOT NULL DEFAULT '[]',
 channels_json TEXT NOT NULL DEFAULT '[]',
 region TEXT DEFAULT '',
 language TEXT DEFAULT 'English',
 budget REAL,
 currency TEXT DEFAULT '',
 status TEXT NOT NULL DEFAULT 'Draft',
 ai_plan_json TEXT NOT NULL DEFAULT '{}',
 created_at TEXT DEFAULT CURRENT_TIMESTAMP,
 updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS v10_campaign_channels(
 id TEXT PRIMARY KEY,
 campaign_id TEXT NOT NULL,
 channel TEXT NOT NULL,
 connection_id TEXT,
 readiness TEXT NOT NULL DEFAULT 'Not connected',
 external_campaign_id TEXT DEFAULT '',
 launch_status TEXT NOT NULL DEFAULT 'Draft',
 payload_json TEXT NOT NULL DEFAULT '{}',
 last_error TEXT DEFAULT '',
 updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
 UNIQUE(campaign_id,channel)
);
CREATE TABLE IF NOT EXISTS v10_campaign_sends(
 id TEXT PRIMARY KEY,
 campaign_id TEXT NOT NULL,
 channel TEXT NOT NULL,
 connection_id TEXT NOT NULL,
 contact_id TEXT NOT NULL,
 endpoint TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'Submitted',
 provider_message_id TEXT DEFAULT '',
 subject TEXT DEFAULT '',
 payload_json TEXT NOT NULL DEFAULT '{}',
 error TEXT DEFAULT '',
 send_key TEXT DEFAULT '',
 created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS v10_campaign_sends_campaign ON v10_campaign_sends(campaign_id,channel,created_at);
CREATE INDEX IF NOT EXISTS v10_campaign_sends_contact ON v10_campaign_sends(contact_id,created_at);
CREATE TABLE IF NOT EXISTS v10_webhook_events(
 id TEXT PRIMARY KEY,
 connection_id TEXT NOT NULL,
 provider TEXT NOT NULL,
 external_event_id TEXT DEFAULT '',
 event_type TEXT NOT NULL,
 signature_valid INTEGER NOT NULL DEFAULT 0,
 payload_json TEXT NOT NULL DEFAULT '{}',
 received_at TEXT DEFAULT CURRENT_TIMESTAMP,
 UNIQUE(connection_id,provider,external_event_id)
);
CREATE TABLE IF NOT EXISTS v10_setup_progress(
 step_key TEXT PRIMARY KEY,
 status TEXT NOT NULL DEFAULT 'Not started',
 detail TEXT DEFAULT '',
 updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);
'''

# Only list a connector as implemented when a genuine backend flow exists in this release.
# Other requested integrations remain visible as planned / blocked, with no fake action button.
CONNECTOR_CATALOG: dict[str, dict[str, Any]] = {
    'shopify': {
        'label':'Shopify', 'category':'Commerce', 'provider':'Shopify', 'auth':'access_token',
        'implemented':True, 'capabilities':['test','sync_products','sync_customers','sync_orders','push_product_draft','register_webhooks','receive_webhooks'],
        'help':'Connect a Shopify Admin API token with read_products/read_customers/read_orders; write_products is required to publish drafts.'
    },
    'resend': {
        'label':'Email / Resend', 'category':'Communication', 'provider':'Resend', 'auth':'api_key',
        'implemented':True, 'capabilities':['test','sync_domains','domain_create','domain_verify','send_email','register_webhook','receive_webhook'],
        'help':'Use a Resend API key. Domain verification, sending and signed webhook registration/ingestion are real API operations when a public HTTPS URL is configured.'
    },
    'whatsapp_cloud': {
        'label':'WhatsApp Business Cloud API', 'category':'Communication', 'provider':'Meta', 'auth':'access_token',
        'implemented':True, 'capabilities':['test','sync_templates','send_template','receive_messages','receive_status_webhooks'],
        'help':'Requires a Meta system-user access token, WhatsApp phone-number ID and WABA ID.'
    },
    'meta_ads': {
        'label':'Meta Ads', 'category':'Social & Advertising', 'provider':'Meta', 'auth':'access_token',
        'implemented':True, 'capabilities':['test','sync_campaigns','sync_insights'],
        'help':'Read/sync account campaigns and insights now. Ad creation stays unavailable until write permissions and production tracking are configured.'
    },
    'google_ads': {
        'label':'Google Ads', 'category':'Google ecosystem', 'provider':'Google', 'auth':'oauth_refresh_token',
        'implemented':True, 'capabilities':['test','sync_campaigns','sync_insights'],
        'help':'Requires OAuth client ID/secret, refresh token, developer token and Google Ads customer ID. Read/sync only in this release.'
    },
    'google_business': {
        'label':'Google Business connection', 'category':'Google ecosystem', 'provider':'Google', 'auth':'oauth_refresh_token',
        'implemented':True, 'capabilities':['test','sync_ga4','sync_search_console','sync_merchant','sync_gmail','sync_calendar'],
        'help':'One Google OAuth connection can be granted only the services you select: Analytics, Search Console, Merchant Center, Gmail mailbox and Calendar. Each service still needs its own account/property ID where applicable.'
    },
    'merchant_center': {
        'label':'Google Merchant Center', 'category':'Google ecosystem', 'provider':'Google', 'auth':'shared_google',
        'implemented':False, 'capabilities':[],
        'help':'Use the implemented Google Business connection for Merchant Center sync. A separate Merchant connection is not exposed to avoid duplicate Google authorisation.'
    },
    'ga4': {'label':'Google Analytics 4','category':'Google ecosystem','provider':'Google','auth':'shared_google','implemented':False,'capabilities':[],'help':'Use the implemented Google Business connection and select Analytics; this separate card remains informational only.'},
    'search_console': {'label':'Google Search Console','category':'Google ecosystem','provider':'Google','auth':'shared_google','implemented':False,'capabilities':[],'help':'Use the implemented Google Business connection and select Search Console; this separate card remains informational only.'},
    'youtube': {'label':'YouTube','category':'Google ecosystem','provider':'Google','auth':'shared_google','implemented':False,'capabilities':[],'help':'YouTube publishing is still planned. The Google Business connector does not expose a fake publishing control.'},
    'meta_social': {'label':'Instagram & Facebook organic', 'category':'Social & Advertising','provider':'Meta','auth':'oauth',
        'implemented':True,'capabilities':['test','sync_pages','sync_social_accounts','publish_instagram_image','publish_facebook_image'],
        'help':'Connect a Meta app/user, select a Facebook Page and Instagram Professional account. Publishing requires a real public HTTPS media URL and the necessary Meta permissions.'},
    'instagram_facebook': {'label':'Instagram & Facebook organic (legacy card)','category':'Social & Advertising','provider':'Meta','auth':'oauth','implemented':False,'capabilities':[],'help':'Use the implemented Instagram & Facebook organic connector above.'},
    'pinterest': {'label':'Pinterest','category':'Social & Advertising','provider':'Pinterest','auth':'oauth','implemented':False,'capabilities':[],'help':'Planned; generated Pinterest assets can be exported but publishing is not connected.'},
    'sms': {'label':'SMS provider','category':'Communication','provider':'Provider adapter','auth':'api_key','implemented':False,'capabilities':[],'help':'Planned; no SMS transport is currently enabled.'},
    'stripe': {'label':'Stripe','category':'Payments','provider':'Stripe','auth':'api_key','implemented':True,'capabilities':['test','sync_payments'], 'help':'Connect a restricted/test Stripe secret key. V11 can validate the account and sync recent PaymentIntents for reporting. It does not create or refund charges.'},
    'razorpay': {'label':'Razorpay','category':'Payments','provider':'Razorpay','auth':'api_key','implemented':False,'capabilities':[],'help':'Planned.'},
    'shipping': {'label':'Shipping / courier','category':'Logistics','provider':'Provider adapter','auth':'api_key','implemented':False,'capabilities':[],'help':'Planned.'},
    'accounting': {'label':'Accounting','category':'Business operations','provider':'Provider adapter','auth':'oauth','implemented':False,'capabilities':[],'help':'Planned.'},
    'calendar': {'label':'Calendar & appointments','category':'Business operations','provider':'Google/Microsoft','auth':'oauth','implemented':False,'capabilities':[],'help':'Planned; CRM tasks remain local.'},
    'video_meetings': {'label':'Video meetings','category':'Business operations','provider':'Zoom/Meet','auth':'oauth','implemented':False,'capabilities':[],'help':'Planned.'},
    'cloud_storage': {'label':'Cloud asset storage','category':'Business operations','provider':'Object storage','auth':'api_key','implemented':False,'capabilities':[],'help':'Required before public social publishing. Local media remains the source in this testing build.'},
}

VALID_STATES = {'Available to connect','Connected','Connection requires setup','Permission required','Syncing','Connection error','Reconnect required','Unsupported / planned'}


def uid(prefix: str) -> str:
    return prefix + '-' + uuid.uuid4().hex[:16].upper()


def initialise() -> None:
    with m.connect() as con:
        con.executescript(SCHEMA)
        try:
            cols={r['name'] for r in con.execute('PRAGMA table_info(v10_campaign_sends)').fetchall()}
            if 'send_key' not in cols:con.execute("ALTER TABLE v10_campaign_sends ADD COLUMN send_key TEXT DEFAULT ''")
        except Exception:
            pass
        try:con.execute("CREATE UNIQUE INDEX IF NOT EXISTS v39_campaign_send_key ON v10_campaign_sends(send_key) WHERE send_key<>''")
        except Exception:pass
    try:
        import v35_truth as _truth
        _truth._add_column('interactions','canonical_campaign_id',"TEXT DEFAULT ''")
    except Exception:pass
    # Seed explicit setup progress without pretending completion.
    for key in ['store','email','meta','google','whatsapp','customers','tracking','campaign']:
        with m.connect() as con:
            con.execute('INSERT OR IGNORE INTO v10_setup_progress(step_key) VALUES(?)',(key,))


def _vault() -> Fernet:
    # Production never creates a credential-encryption key on the application filesystem.
    # Supply CRM_VAULT_MASTER_KEY through the deployment secret manager.
    env_key=os.environ.get('CRM_VAULT_MASTER_KEY','').strip().encode()
    if env_key:
        try:return Fernet(env_key)
        except Exception:raise RuntimeError('CRM_VAULT_MASTER_KEY is not a valid Fernet key.') from None
    if rc.IS_PRODUCTION:
        raise RuntimeError('CRM_VAULT_MASTER_KEY is required in production and must be supplied through the deployment secret manager.')
    VAULT_KEY_PATH.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
    if not VAULT_KEY_PATH.exists():
        fd=os.open(VAULT_KEY_PATH,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'wb') as f:f.write(Fernet.generate_key())
    os.chmod(VAULT_KEY_PATH,0o600)
    key=VAULT_KEY_PATH.read_bytes().strip()
    return Fernet(key)


def store_secret(connection_id:str,key:str,value:str) -> None:
    if not value:return
    enc=_vault().encrypt(value.encode())
    hint=('…'+value[-4:]) if len(value)>=4 else 'saved'
    with m.connect() as con:
        con.execute('''INSERT INTO v10_connection_secrets(connection_id,secret_key,encrypted_value,hint) VALUES(?,?,?,?)
        ON CONFLICT(connection_id,secret_key) DO UPDATE SET encrypted_value=excluded.encrypted_value,hint=excluded.hint,updated_at=CURRENT_TIMESTAMP''',(connection_id,key,enc,hint))


def load_secret(connection_id:str,key:str) -> str:
    row=m.one('SELECT encrypted_value FROM v10_connection_secrets WHERE connection_id=? AND secret_key=?',(connection_id,key))
    if not row:return ''
    try:return _vault().decrypt(row['encrypted_value']).decode()
    except (InvalidToken,ValueError,TypeError):raise ValueError('Saved credentials cannot be decrypted. Reconnect this account.') from None


def secret_hints(connection_id:str)->dict[str,str]:
    return {r['secret_key']:r['hint'] for r in m.rows('SELECT secret_key,hint FROM v10_connection_secrets WHERE connection_id=?',(connection_id,))}


def connection(connection_id:str)->dict:
    row=m.one('SELECT * FROM v10_connections WHERE id=?',(connection_id,))
    if not row:raise ValueError('Connection not found.')
    row['config']=json.loads(row.get('config_json') or '{}');row['scopes']=json.loads(row.get('scopes_json') or '[]');row['capabilities']=json.loads(row.get('capabilities_json') or '[]')
    return row


def connections(connector_key:str|None=None)->list[dict]:
    sql='SELECT * FROM v10_connections';args=()
    if connector_key:sql+=' WHERE connector_key=?';args=(connector_key,)
    sql+=' ORDER BY category COLLATE NOCASE, label COLLATE NOCASE, created_at DESC'
    # category is derived from catalog for backwards compatibility.
    rows=m.rows(sql.replace('category COLLATE NOCASE, ',''),args)
    for r in rows:
        meta=CONNECTOR_CATALOG.get(r['connector_key'],{});r['category']=meta.get('category','Other');r['config']=json.loads(r.get('config_json') or '{}');r['capabilities']=json.loads(r.get('capabilities_json') or '[]')
    return rows


def upsert_connection(connector_key:str,label:str='',config:dict|None=None,secrets_map:dict|None=None,connection_id:str='')->str:
    meta=CONNECTOR_CATALOG.get(connector_key)
    if not meta:raise ValueError('Unknown integration.')
    if not meta.get('implemented'):raise ValueError('This integration is planned but not implemented yet. No credentials were saved.')
    config=config or {};secrets_map=secrets_map or {}
    cid=connection_id or uid('CONN')
    safe_config={k:v for k,v in config.items() if v not in (None,'')}
    with m.connect() as con:
        if connection_id:
            if not con.execute('SELECT 1 FROM v10_connections WHERE id=?',(cid,)).fetchone():raise ValueError('Connection not found.')
            con.execute('''UPDATE v10_connections SET connector_key=?,provider=?,label=?,status='Connection requires setup',auth_type=?,config_json=?,capabilities_json=?,last_error='',updated_at=CURRENT_TIMESTAMP WHERE id=?''',
                        (connector_key,meta['provider'],label or meta['label'],meta['auth'],json.dumps(safe_config),json.dumps(meta.get('capabilities',[])),cid))
        else:
            con.execute('''INSERT INTO v10_connections(id,connector_key,provider,label,status,auth_type,config_json,capabilities_json) VALUES(?,?,?,?,?,?,?,?)''',
                        (cid,connector_key,meta['provider'],label or meta['label'],'Connection requires setup',meta['auth'],json.dumps(safe_config),json.dumps(meta.get('capabilities',[]))))
    for k,v in secrets_map.items():
        if str(v).strip():store_secret(cid,k,str(v).strip())
    m.audit('integration.configured',cid,connector_key)
    return cid


def disconnect(connection_id:str)->None:
    c=connection(connection_id)
    with m.connect() as con:
        con.execute('DELETE FROM v10_connection_secrets WHERE connection_id=?',(connection_id,))
        con.execute("UPDATE v10_connections SET status='Available to connect',account_name='',external_account_id='',scopes_json='[]',last_error='',updated_at=CURRENT_TIMESTAMP WHERE id=?",(connection_id,))
    m.audit('integration.disconnected',connection_id,c['connector_key'])


def _api_log(connection_id:str,operation:str,method:str,endpoint:str,status_code:int|None,success:bool,duration_ms:int,error_class:str='',error_message:str='')->None:
    # Endpoint intentionally excludes query-string secrets and credentials.
    clean=endpoint.split('?',1)[0][:500]
    with m.connect() as con:
        con.execute('INSERT INTO v10_api_logs(id,connection_id,operation,method,endpoint,status_code,success,duration_ms,error_class,error_message) VALUES(?,?,?,?,?,?,?,?,?,?)',
                    (uid('API'),connection_id,operation,method,clean,status_code,1 if success else 0,duration_ms,error_class[:120],error_message[:1000]))


def api_json(connection_id:str,operation:str,url:str,method:str='GET',headers:dict|None=None,payload:Any=None,timeout:int=30,retries:int=2)->Any:
    body=None
    if payload is not None:body=json.dumps(payload).encode()
    hdr={'Accept':'application/json','User-Agent':'CommerceCRM-V11/1.0'}
    if payload is not None:hdr['Content-Type']='application/json'
    hdr.update(headers or {})
    last=None
    for attempt in range(retries+1):
        started=time.monotonic();code=None
        try:
            req=urllib.request.Request(url,data=body,headers=hdr,method=method)
            with urllib.request.urlopen(req,timeout=timeout) as resp:
                code=resp.status;raw=resp.read();duration=int((time.monotonic()-started)*1000)
                _api_log(connection_id,operation,method,url,code,True,duration)
                if not raw:return {}
                return json.loads(raw.decode())
        except urllib.error.HTTPError as exc:
            code=exc.code;duration=int((time.monotonic()-started)*1000)
            try:raw=exc.read(8000).decode('utf-8','replace')
            except Exception:raw=''
            # Never include response headers; redact token-like patterns from body.
            redacted=re.sub(r'(?i)(access[_-]?token|refresh[_-]?token|client[_-]?secret|api[_-]?key|authorization(?:[_-]?code)?)["\':= ]+["\']?[^,}"\'\s]+',r'\1=[redacted]',raw)
            _api_log(connection_id,operation,method,url,code,False,duration,'HTTPError',redacted[:900])
            last=ValueError(f'{operation} returned HTTP {code}.')
            if code in {429,500,502,503,504} and attempt<retries:
                time.sleep(min(4,2**attempt));continue
            raise last from None
        except (urllib.error.URLError,TimeoutError,OSError,ValueError) as exc:
            duration=int((time.monotonic()-started)*1000);_api_log(connection_id,operation,method,url,code,False,duration,type(exc).__name__,str(exc)[:900]);last=ValueError(f'{operation} could not reach the provider.')
            if attempt<retries:time.sleep(min(4,2**attempt));continue
            raise last from None
    raise last or ValueError(operation+' failed.')


def _shopify_graphql(c:dict,query:str,variables:dict|None=None,operation='Shopify API')->dict:
    shop=re.sub(r'^https?://','',c['config'].get('store_domain','').strip()).strip('/')
    token=load_secret(c['id'],'access_token')
    if not shop or not token:raise ValueError('Add the Shopify store domain and Admin API access token.')
    if not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9-]*\.myshopify\.com',shop):raise ValueError('Use the permanent *.myshopify.com store domain.')
    ver=c['config'].get('api_version') or '2026-07'
    data=api_json(c['id'],operation,f'https://{shop}/admin/api/{ver}/graphql.json','POST',{'X-Shopify-Access-Token':token},{'query':query,'variables':variables or {}})
    if data.get('errors'):raise ValueError(operation+' returned GraphQL errors: '+ '; '.join(str(x.get('message','error')) for x in data['errors'][:3]))
    return data.get('data') or {}


def _resend(c:dict,path:str,method='GET',payload=None,operation='Resend API')->Any:
    key=load_secret(c['id'],'api_key')
    if not key:raise ValueError('Add a Resend API key.')
    return api_json(c['id'],operation,'https://api.resend.com'+path,method,{'Authorization':'Bearer '+key},payload)


def _meta(c:dict,path:str,params:dict|None=None,method='GET',payload=None,operation='Meta API')->Any:
    token=load_secret(c['id'],'access_token');version=c['config'].get('graph_version') or 'v26.0'
    if not token:raise ValueError('Add a Meta access token.')
    url=f'https://graph.facebook.com/{version}/'+path.lstrip('/')
    if params:url+='?'+urllib.parse.urlencode(params)
    headers={'Authorization':'Bearer '+token}
    return api_json(c['id'],operation,url,method,headers,payload)


def _google_access_token(c:dict)->str:
    cid=c['config'].get('client_id','');secret=load_secret(c['id'],'client_secret');refresh=load_secret(c['id'],'refresh_token')
    if not cid or not secret or not refresh:raise ValueError('Google OAuth client ID, client secret and refresh token are required.')
    data=urllib.parse.urlencode({'grant_type':'refresh_token','client_id':cid,'client_secret':secret,'refresh_token':refresh}).encode()
    started=time.monotonic();url='https://oauth2.googleapis.com/token'
    try:
        req=urllib.request.Request(url,data=data,headers={'Content-Type':'application/x-www-form-urlencoded'},method='POST')
        with urllib.request.urlopen(req,timeout=30) as resp:
            out=json.load(resp);_api_log(c['id'],'Google OAuth refresh','POST',url,resp.status,True,int((time.monotonic()-started)*1000))
            return out['access_token']
    except urllib.error.HTTPError as exc:
        _api_log(c['id'],'Google OAuth refresh','POST',url,exc.code,False,int((time.monotonic()-started)*1000),'HTTPError','OAuth token refresh failed')
        raise ValueError('Google OAuth token refresh failed. Reconnect the Google account.') from None


def test_connection(connection_id:str)->dict:
    c=connection(connection_id);kind=c['connector_key'];account='';external='';scopes=[]
    try:
        if kind=='shopify':
            d=_shopify_graphql(c,'query { shop { name email primaryDomain { url } currencyCode } }',operation='Test Shopify connection')['shop']
            account=d.get('name') or c['config'].get('store_domain','');external=d.get('primaryDomain',{}).get('url','');scopes=c.get('capabilities',[])
        elif kind=='resend':
            d=_resend(c,'/domains?limit=1',operation='Test Resend connection');account='Resend email account';external=str((d.get('data') or [{}])[0].get('id','')) if isinstance(d,dict) else '' ;scopes=c.get('capabilities',[])
        elif kind=='whatsapp_cloud':
            phone=c['config'].get('phone_number_id','')
            if not phone:raise ValueError('Add the WhatsApp phone-number ID.')
            d=_meta(c,phone,{'fields':'display_phone_number,verified_name,quality_rating'},operation='Test WhatsApp connection');account=d.get('verified_name') or d.get('display_phone_number') or 'WhatsApp Business';external=d.get('id') or phone;scopes=['whatsapp_business_messaging']
        elif kind=='meta_ads':
            aid=str(c['config'].get('ad_account_id','')).removeprefix('act_')
            if not aid:raise ValueError('Add the Meta ad account ID.')
            d=_meta(c,'act_'+aid,{'fields':'id,name,account_status,currency,timezone_name'},operation='Test Meta Ads connection');account=d.get('name') or ('act_'+aid);external=d.get('id') or ('act_'+aid);scopes=['ads_read']
        elif kind=='google_ads':
            token=_google_access_token(c);dev=load_secret(c['id'],'developer_token')
            if not dev:raise ValueError('Add the Google Ads developer token.')
            d=api_json(c['id'],'Test Google Ads connection','https://googleads.googleapis.com/v25/customers:listAccessibleCustomers','GET',{'Authorization':'Bearer '+token,'developer-token':dev});ids=d.get('resourceNames') or []
            customer=re.sub(r'\D','',c['config'].get('customer_id',''))
            if customer and ('customers/'+customer) not in ids:raise ValueError('The configured Google Ads customer is not accessible to this OAuth user.')
            account=('Google Ads '+customer) if customer else (ids[0] if ids else 'Google Ads');external=customer or (ids[0].split('/')[-1] if ids else '');scopes=['adwords']
        elif kind=='google_business':
            token=_google_access_token(c)
            d=api_json(c['id'],'Test Google business OAuth','https://www.googleapis.com/oauth2/v2/userinfo','GET',{'Authorization':'Bearer '+token})
            services=c['config'].get('services') or []
            if isinstance(services,str):services=[x for x in services.split(',') if x]
            if not services:raise ValueError('Choose at least one Google business service.')
            account=d.get('email') or d.get('name') or 'Google account';external=d.get('id') or account;scopes=[GOOGLE_SERVICE_SCOPES[x] for x in services if x in GOOGLE_SERVICE_SCOPES]
        elif kind=='meta_social':
            d=_meta(c,'me',{'fields':'id,name'},operation='Test Meta social connection')
            page_id=str(c['config'].get('page_id') or '').strip();ig_id=str(c['config'].get('instagram_user_id') or '').strip()
            if page_id:
                page=_meta(c,page_id,{'fields':'id,name'},operation='Validate Facebook Page');account=page.get('name') or d.get('name') or 'Meta account';external=page.get('id') or page_id
            else:account=d.get('name') or 'Meta account';external=d.get('id') or ''
            if ig_id:_meta(c,ig_id,{'fields':'id,username'},operation='Validate Instagram account')
            scopes=META_SOCIAL_SCOPES
        elif kind=='stripe':
            key=load_secret(c['id'],'api_key')
            if not key:raise ValueError('Add the Stripe restricted/test secret key.')
            d=api_json(c['id'],'Test Stripe connection','https://api.stripe.com/v1/balance','GET',{'Authorization':'Bearer '+key})
            account='Stripe account';external='';scopes=['balance','payment_intents.read']
        else:raise ValueError('This connector does not have a live test implementation.')
        with m.connect() as con:
            con.execute("UPDATE v10_connections SET status='Connected',account_name=?,external_account_id=?,scopes_json=?,last_tested_at=CURRENT_TIMESTAMP,last_success_at=CURRENT_TIMESTAMP,last_error='',updated_at=CURRENT_TIMESTAMP WHERE id=?",(account,external,json.dumps(scopes),connection_id))
        m.audit('integration.connected',connection_id,kind+' '+account)
        try:
            import platform_core as pc
            pc.ensure_connection_schedule(connection_id,60)
        except Exception:
            pass
        return {'ok':True,'account_name':account,'external_account_id':external}
    except ValueError as exc:
        msg=str(exc)
        state='Permission required' if re.search(r'permission|scope|accessible|403',msg,re.I) else 'Reconnect required' if re.search(r'oauth|token|401|expired|reconnect',msg,re.I) else 'Connection error'
        with m.connect() as con:con.execute('UPDATE v10_connections SET status=?,last_tested_at=CURRENT_TIMESTAMP,last_error=?,updated_at=CURRENT_TIMESTAMP WHERE id=?',(state,msg[:1200],connection_id))
        raise


def begin_sync(connection_id:str,sync_type:str,direction='pull')->str:
    rid=uid('SYNC')
    with m.connect() as con:
        con.execute('INSERT INTO v10_sync_runs(id,connection_id,sync_type,direction) VALUES(?,?,?,?)',(rid,connection_id,sync_type,direction))
        con.execute("UPDATE v10_connections SET status='Syncing',updated_at=CURRENT_TIMESTAMP WHERE id=?",(connection_id,))
    return rid


def finish_sync(run_id:str,summary:dict,error:str='')->dict:
    status='Failed' if error else 'Completed';cid=m.one('SELECT connection_id FROM v10_sync_runs WHERE id=?',(run_id,))['connection_id']
    vals={k:int(summary.get(k,0)) for k in ['records_seen','records_created','records_updated','records_skipped','errors']}
    with m.connect() as con:
        con.execute('''UPDATE v10_sync_runs SET status=?,records_seen=?,records_created=?,records_updated=?,records_skipped=?,errors=?,summary_json=?,finished_at=CURRENT_TIMESTAMP WHERE id=?''',
                    (status,vals['records_seen'],vals['records_created'],vals['records_updated'],vals['records_skipped'],vals['errors'],json.dumps(summary),run_id))
        con.execute("UPDATE v10_connections SET status=?,last_sync_at=CURRENT_TIMESTAMP,last_success_at=CASE WHEN ?='' THEN CURRENT_TIMESTAMP ELSE last_success_at END,last_error=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",('Connection error' if error else 'Connected',error,error[:1200],cid))
    return summary


def _external_upsert(connection_id:str,object_type:str,external_id:str,payload:dict,local_type='',local_id='')->None:
    with m.connect() as con:
        con.execute('''INSERT INTO v10_external_objects(connection_id,object_type,external_id,local_type,local_id,payload_json)
        VALUES(?,?,?,?,?,?) ON CONFLICT(connection_id,object_type,external_id) DO UPDATE SET local_type=excluded.local_type,local_id=excluded.local_id,payload_json=excluded.payload_json,synced_at=CURRENT_TIMESTAMP''',
        (connection_id,object_type,external_id,local_type,local_id,json.dumps(payload,ensure_ascii=False)))


def _match_contact(email:str='',phone:str='')->str:
    email=(email or '').strip().lower();digits=re.sub(r'\D','',phone or '')
    has_idx=m.table_exists('v9_identities')
    if email:
        r=m.one("SELECT contact_id FROM v9_identities WHERE identity_type='email' AND normalized_value=?",(email,)) if has_idx else m.one("SELECT contact_id FROM contacts WHERE lower(trim(email))=? LIMIT 1",(email,))
        if r:return r['contact_id']
    if digits:
        r=m.one("SELECT contact_id FROM v9_identities WHERE identity_type='phone' AND normalized_value=?",(digits,)) if has_idx else None
        if r:return r['contact_id']
        for row in m.rows("SELECT contact_id,phone_number FROM contacts WHERE phone_number IS NOT NULL AND phone_number<>''"):
            if re.sub(r'\D','',row.get('phone_number') or '')==digits:return row['contact_id']
    return ''


def _shopify_order_lines(connection_id:str, order:dict)->list[dict]:
    """Resolve Shopify line items to canonical local products.

    SKU is preferred because it is merchant-controlled.  If SKU is missing or
    no longer matches, fall back to the product identity mapping established by
    the catalogue sync.  Unresolved lines are deliberately returned with an
    empty product_id so the canonical order sync can surface a mapping exception
    instead of inventing a product or silently dropping the line.
    """
    out=[]
    for line in (order.get('lineItems') or {}).get('nodes',[]) or []:
        sku=str(line.get('sku') or '').strip();pid=''
        if sku:
            r=m.one('SELECT product_id FROM products WHERE internal_sku=? OR product_code=? LIMIT 1',(sku,sku))
            pid=(r or {}).get('product_id','')
        ext_product=str((line.get('product') or {}).get('id') or '')
        if not pid and ext_product:
            r=m.one("SELECT local_id FROM v10_external_objects WHERE connection_id=? AND object_type='product' AND external_id=? LIMIT 1",(connection_id,ext_product))
            pid=(r or {}).get('local_id','')
        money=(line.get('originalUnitPriceSet') or {}).get('shopMoney') or {}
        try:unit=float(money.get('amount') or 0)
        except (TypeError,ValueError):unit=0.0
        out.append({'product_id':pid,'sku':sku,'external_product_id':ext_product,
                    'quantity':int(line.get('quantity') or 0),'unit_price':unit})
    if (order.get('lineItems') or {}).get('pageInfo',{}).get('hasNextPage'):
        # This should be rare after requesting 250 lines, but never pretend an
        # incomplete provider payload is a complete order.
        out.append({'product_id':'','sku':'','external_product_id':'__MORE_LINES__','quantity':0,'unit_price':0})
    return out


def sync_shopify(connection_id:str)->dict:
    import platform_core as pc
    import integration_v14 as v14
    pc._ensure_stock_location_schema()
    truth.initialise()
    c=connection(connection_id);run=begin_sync(connection_id,'shopify_full');summary={'records_seen':0,'records_created':0,'records_updated':0,'records_skipped':0,'errors':0,'warnings':0,'authority_blocked':0,'products':0,'customers':0,'orders':0}
    try:
        # Keep local test sync deliberately bounded. Production worker should paginate continuously.
        q='''query { products(first:100) { nodes { id title handle productType tags status updatedAt variants(first:20) { nodes { id sku price inventoryQuantity } } } } customers(first:100) { nodes { id displayName firstName lastName defaultEmailAddress { emailAddress marketingState } defaultPhoneNumber { phoneNumber marketingState } tags updatedAt } } orders(first:100, sortKey:CREATED_AT, reverse:true) { nodes { id name createdAt updatedAt displayFinancialStatus displayFulfillmentStatus currentTotalPriceSet { shopMoney { amount currencyCode } } totalRefundedSet { shopMoney { amount currencyCode } } customer { id defaultEmailAddress { emailAddress } defaultPhoneNumber { phoneNumber } } lineItems(first:250) { pageInfo { hasNextPage } nodes { quantity sku originalUnitPriceSet { shopMoney { amount currencyCode } } product { id } } } } } }'''
        d=_shopify_graphql(c,q,operation='Sync Shopify catalog/customers/orders')
        for p in d.get('products',{}).get('nodes',[]):
            summary['records_seen']+=1;summary['products']+=1;ext=p['id'];sku=''
            variants=p.get('variants',{}).get('nodes',[]);sku=(variants[0].get('sku') or '') if variants else ''
            local=''
            if sku:
                r=m.one('SELECT product_id FROM products WHERE internal_sku=? OR product_code=?',(sku,sku));local=(r or {}).get('product_id','')
            _external_upsert(connection_id,'product',ext,p,'product',local)
            if local:
                import record_lifecycle as lifecycle
                if not lifecycle.is_operationally_active_product(local):
                    # Keep the external identity mapping/history, but archived products do not
                    # re-enter active commercial state through provider reconciliation.
                    summary['records_skipped']+=1
                    continue
                # Product content and retail pricing are CRM-mastered. A Shopify
                # catalogue sync records the provider payload/mapping but never overwrites
                # CRM price/content. Inventory mutates only when this exact connection is
                # the explicitly selected inventory authority.
                qty=(variants[0].get('inventoryQuantity') if variants else None)
                if qty is not None:
                    dec=v14.authority_decision('inventory','Shopify',connection_id,'stock_qty',local)
                    if dec['allowed']:
                        reconciled=truth.reconcile_provider_aggregate_stock(local,int(qty),'Shopify',str(ext))
                        if not reconciled.get('applied'):
                            summary['authority_blocked']+=1
                    else:
                        summary['authority_blocked']+=1
                summary['records_updated']+=1
            else:summary['records_skipped']+=1
        for x in d.get('customers',{}).get('nodes',[]):
            summary['records_seen']+=1;summary['customers']+=1
            email=((x.get('defaultEmailAddress') or {}).get('emailAddress') or '').strip();phone=((x.get('defaultPhoneNumber') or {}).get('phoneNumber') or '').strip();cid=_match_contact(email,phone)
            if not cid:
                import contact_tools as ct
                raw={'full_name':x.get('displayName') or (' '.join(filter(None,[x.get('firstName'),x.get('lastName')]))),'first_name':x.get('firstName') or '','contact_type':'B2C','email':email,'phone_number':phone,'source_name':'Shopify','source_reference':x['id'],'country':'','language':'','username':'','website':'','business_category':'Customer','tags':','.join(x.get('tags') or [])}
                try:cid=ct.save_contact(raw);summary['records_created']+=1
                except ValueError:cid=_match_contact(email,phone);summary['records_skipped']+=1
            else:summary['records_updated']+=1
            _external_upsert(connection_id,'customer',x['id'],x,'contact',cid)
        for x in d.get('orders',{}).get('nodes',[]):
            summary['records_seen']+=1;summary['orders']+=1
            order_auth=v14.authority_decision('online_order','Shopify',connection_id,'order',str(x.get('id') or ''))
            if not order_auth.get('allowed'):
                summary['authority_blocked']+=1
                continue
            cust=x.get('customer') or {};email=((cust.get('defaultEmailAddress') or {}).get('emailAddress') or '');phone=((cust.get('defaultPhoneNumber') or {}).get('phoneNumber') or '');cid=_match_contact(email,phone)
            money=(x.get('currentTotalPriceSet') or {}).get('shopMoney') or {};total=float(money.get('amount') or 0);currency=money.get('currencyCode') or '';refund_money=(x.get('totalRefundedSet') or {}).get('shopMoney') or {};refund_total=float(refund_money.get('amount') or 0);refund_currency=refund_money.get('currencyCode') or currency
            import crm_workspace as cw
            synced=cw.sync_external_order('Shopify',connection_id,x['id'],contact_id=cid,total=total,currency=currency,
                    financial_status=x.get('displayFinancialStatus') or '',fulfilment_status=x.get('displayFulfillmentStatus') or '',
                    ordered_at=x.get('createdAt') or '',lines=_shopify_order_lines(connection_id,x),provider_refund_total=refund_total,provider_refund_currency=refund_currency)
            oid=synced['order_id']
            summary['records_created' if synced['created'] else 'records_updated']+=1
            if synced.get('unmapped_lines'):summary['records_skipped']+=int(synced['unmapped_lines'])
            _external_upsert(connection_id,'order',x['id'],x,'order',oid)
            if cid:
                try:
                    import business_os as bos
                    bos.record_touchpoint(cid,'order.synced','Website','Shopify','commerce',value=total,currency=currency,metadata={'external_order_id':x['id']})
                except Exception as exc:
                    summary['warnings']+=1
                    from operational_guard import record_side_effect_failure
                    record_side_effect_failure('shopify_sync','Shopify order synced but Customer 360 touchpoint failed',exc,recovery='Retry the Shopify sync after reviewing System health. The canonical order was preserved.',entity_type='contact',entity_id=cid,severity='Error')
            if str(x.get('displayFinancialStatus') or '').upper() in {'PAID','PARTIALLY_PAID','PARTIALLY_REFUNDED'}:
                try:
                    import operating_core as oc
                    oc.emit_event('ORDER_PLACED','order',oid,{'contact_id':cid,'source':'Shopify','external_order_id':x['id'],'status':x.get('displayFinancialStatus'),'total':total,'currency':currency},dedupe_key='shopify-order:'+str(x['id'])+':'+str(x.get('displayFinancialStatus') or ''))
                except Exception as exc:
                    summary['warnings']+=1
                    from operational_guard import record_side_effect_failure
                    record_side_effect_failure('shopify_sync','Shopify order synced but automation event failed',exc,recovery='Retry the Shopify sync after reviewing System health. The canonical order was preserved.',entity_type='order',entity_id=oid,severity='Error')
        try:
            import business_os as bos
            bos.rebuild_identity_index()
        except Exception as exc:
            summary['warnings']+=1
            from operational_guard import record_side_effect_failure
            record_side_effect_failure('shopify_sync','Shopify sync completed but identity index rebuild failed',exc,recovery='Open System health and retry the Shopify sync. Canonical records were preserved; identity matching needs repair.',severity='Error')
        return finish_sync(run,summary)
    except Exception as exc:
        summary['errors']+=1;finish_sync(run,summary,str(exc));raise


def publish_product_to_shopify(connection_id:str,product_id:str)->dict:
    rc.require_external_write_allowed('publish a Shopify product draft')
    """Create a reviewable Shopify DRAFT and configure its initial variant.

    Product identity, copy, SEO, SKU and retail price are transferred. Media is only
    safe to add once the application has public HTTPS asset URLs; inventory is
    location-specific and is not guessed by this write path.
    """
    c=connection(connection_id);import record_lifecycle as lifecycle;p=lifecycle.require_operationally_active_product(product_id)
    title=p.get('public_product_name') or p.get('source_product_name') or p.get('internal_sku')
    if not title:raise ValueError('Product needs a customer-facing title before Shopify publishing.')
    price=p.get('retail_price')
    if price in (None,''):raise ValueError('Product needs a retail price before Shopify publishing.')
    try:content=m.one('SELECT * FROM v6_product_content WHERE product_id=?',(product_id,)) or {}
    except sqlite3.OperationalError:content={}
    st=m.settings();vendor=(st.get('brand_name') or '').strip()
    if vendor.lower() in {'','brand name pending','pending'}:vendor=''
    description=p.get('description') or content.get('b2c_description') or content.get('short_description') or ''
    esc=lambda x:str(x or '').replace('&','&amp;').replace('<','&lt;').replace('>','&gt;')
    tags=[x.strip() for x in (p.get('tags') or '').split(',') if x.strip()]
    try:
        content_tags=json.loads(content.get('tags_json') or '[]')
        if isinstance(content_tags,list):tags=list(dict.fromkeys(tags+[str(x).strip() for x in content_tags if str(x).strip()]))
    except Exception:pass
    payload={'title':title,'descriptionHtml':'<p>'+esc(description)+'</p>','productType':p.get('category') or 'Saree','status':'DRAFT','tags':tags}
    if vendor:payload['vendor']=vendor
    seo_title=(content.get('seo_title') or '').strip();seo_desc=(content.get('meta_description') or '').strip()
    if seo_title or seo_desc:payload['seo']={'title':seo_title or title,'description':seo_desc}
    media=[]
    primary=m.one('SELECT relative_path,original_filename FROM product_images WHERE product_id=? ORDER BY is_primary DESC, image_id LIMIT 1',(product_id,))
    if primary and primary.get('relative_path'):
        try:
            media_url=media_store.public_url(primary['relative_path'],upload_if_needed=True)
            if media_url:
                alt=(content.get('alt_text') or title)[:500]
                media=[{'originalSource':media_url,'alt':alt,'mediaContentType':'IMAGE'}]
        except Exception as exc:
            m.audit('shopify.media_prepare_failed',product_id,str(exc)[:1000])
    q='''mutation CreateCRMProduct($product: ProductCreateInput!, $media: [CreateMediaInput!]) { productCreate(product:$product, media:$media) { product { id title handle status seo { title description } media(first:10) { nodes { alt mediaContentType status } } variants(first:1) { nodes { id price } } } userErrors { field message } } }'''
    d=_shopify_graphql(c,q,{'product':payload,'media':media},operation='Create Shopify product draft').get('productCreate') or {}
    if d.get('userErrors'):raise ValueError('Shopify rejected the draft: '+ '; '.join(x.get('message','') for x in d['userErrors']))
    prod=d.get('product') or {};ext=prod.get('id','')
    if not ext:raise ValueError('Shopify did not return a product ID.')
    variants=((prod.get('variants') or {}).get('nodes') or [])
    variant_id=(variants[0] or {}).get('id') if variants else ''
    variant_configured=False
    if variant_id:
        vq='''mutation UpdateInitialVariant($productId: ID!, $variants: [ProductVariantsBulkInput!]!) { productVariantsBulkUpdate(productId:$productId, variants:$variants) { productVariants { id price } userErrors { field message } } }'''
        variant={'id':variant_id,'price':str(price)}
        sku=(p.get('internal_sku') or p.get('product_code') or '').strip()
        if sku:variant['inventoryItem']={'sku':sku,'tracked':True}
        vd=_shopify_graphql(c,vq,{'productId':ext,'variants':[variant]},operation='Configure Shopify initial variant').get('productVariantsBulkUpdate') or {}
        if vd.get('userErrors'):raise ValueError('Shopify created the draft but rejected its price/SKU: '+ '; '.join(x.get('message','') for x in vd['userErrors']))
        variant_configured=True
    result=dict(prod);result['variant_configured']=variant_configured;result['media_status']='Attached to draft' if media else 'No publishable HTTPS asset URL was available; draft created without media.'
    _external_upsert(connection_id,'product',ext,result,'product',product_id)
    return result

def sync_resend(connection_id:str)->dict:
    c=connection(connection_id);run=begin_sync(connection_id,'resend_domains');summary={'records_seen':0,'records_created':0,'records_updated':0,'records_skipped':0,'errors':0}
    try:
        d=_resend(c,'/domains?limit=100',operation='Sync Resend domains')
        for dom in (d.get('data') or []):
            summary['records_seen']+=1
            detail=dom
            if dom.get('id'):
                try:detail=_resend(c,'/domains/'+urllib.parse.quote(str(dom['id'])),operation='Get Resend domain')
                except ValueError:detail=dom
            _external_upsert(connection_id,'email_domain',dom.get('id',''),detail);summary['records_updated']+=1
        return finish_sync(run,summary)
    except Exception as exc:summary['errors']+=1;finish_sync(run,summary,str(exc));raise


def resend_create_domain(connection_id:str,domain:str)->dict:
    rc.require_external_write_allowed('create an email-sending domain')
    c=connection(connection_id);domain=domain.strip().lower().lstrip('@')
    if not re.fullmatch(r'[a-z0-9.-]+\.[a-z]{2,}',domain):raise ValueError('Enter a valid domain.')
    out=_resend(c,'/domains','POST',{'name':domain},'Create Resend domain');_external_upsert(connection_id,'email_domain',out.get('id',''),out);return out


def resend_verify_domain(connection_id:str,domain_id:str)->dict:
    rc.require_external_write_allowed('verify an email-sending domain')
    c=connection(connection_id);out=_resend(c,f'/domains/{urllib.parse.quote(domain_id)}/verify','POST',{},'Verify Resend domain');return out


def resend_send_email(connection_id:str,from_email:str,to_email:str,subject:str,html:str,text:str='',idempotency_key:str='')->dict:
    rc.require_external_write_allowed('send email')
    c=connection(connection_id)
    key=load_secret(c['id'],'api_key')
    if not all([from_email,to_email,subject,html or text]):raise ValueError('From, to, subject and message are required.')
    headers={'Authorization':'Bearer '+key}
    if idempotency_key:headers['Idempotency-Key']=idempotency_key[:256]
    payload={'from':from_email,'to':[to_email],'subject':subject}
    if html:payload['html']=html
    if text:payload['text']=text
    return api_json(c['id'],'Send email','https://api.resend.com/emails','POST',headers,payload)


def sync_whatsapp_templates(connection_id:str)->dict:
    c=connection(connection_id);waba=c['config'].get('waba_id','')
    if not waba:raise ValueError('Add the WhatsApp Business Account ID.')
    run=begin_sync(connection_id,'whatsapp_templates');summary={'records_seen':0,'records_created':0,'records_updated':0,'records_skipped':0,'errors':0}
    try:
        d=_meta(c,waba+'/message_templates',{'fields':'id,name,status,category,language,components','limit':'100'},operation='Sync WhatsApp templates')
        for x in d.get('data',[]):summary['records_seen']+=1;summary['records_updated']+=1;_external_upsert(connection_id,'whatsapp_template',x.get('id') or x.get('name',''),x)
        return finish_sync(run,summary)
    except Exception as exc:summary['errors']+=1;finish_sync(run,summary,str(exc));raise



RESEND_WEBHOOK_EVENTS = [
    'email.sent','email.delivered','email.delivery_delayed','email.bounced','email.complained',
    'email.opened','email.clicked','email.failed','email.suppressed','email.received','contact.unsubscribed'
]


def _public_base_url() -> str:
    url=(rc.PUBLIC_BASE_URL or str(m.settings().get('public_base_url','') or '')).strip().rstrip('/')
    if not url:
        return ''
    try:
        parsed=urllib.parse.urlparse(url)
    except Exception:
        return ''
    host=(parsed.hostname or '').lower()
    if parsed.scheme!='https' or not host or host in {'localhost','127.0.0.1','::1'}:
        return ''
    return url


def resend_register_webhook(connection_id:str)->dict:
    rc.require_external_write_allowed('register an external webhook')
    """Register the real Resend webhook endpoint. Requires a public HTTPS base URL."""
    c=connection(connection_id)
    if c.get('connector_key')!='resend':raise ValueError('This action is only available for Resend connections.')
    if c.get('status')!='Connected':raise ValueError('Test the Resend connection successfully first.')
    base=_public_base_url()
    if not base:raise ValueError('Configure a real public HTTPS Base URL in Settings before registering provider webhooks. Localhost cannot receive Resend callbacks.')
    endpoint=f'{base}/webhooks/resend/{connection_id}'
    out=_resend(c,'/webhooks','POST',{'endpoint':endpoint,'events':RESEND_WEBHOOK_EVENTS},'Register Resend webhook')
    obj=(out.get('data') if isinstance(out,dict) and isinstance(out.get('data'),dict) else out) or {}
    wid=str(obj.get('id','')); secret=str(obj.get('signing_secret',''))
    if not wid:raise ValueError('Resend did not return a webhook ID.')
    if not secret:raise ValueError('Resend did not return a signing secret. The webhook was not marked ready.')
    store_secret(connection_id,'webhook_secret',secret)
    _external_upsert(connection_id,'resend_webhook',wid,{'id':wid,'endpoint':endpoint,'events':RESEND_WEBHOOK_EVENTS})
    m.audit('integration.resend_webhook_registered',connection_id,f'Webhook {wid} registered for the configured public HTTPS endpoint. Secret stored encrypted.')
    return {'id':wid,'endpoint':endpoint,'events':RESEND_WEBHOOK_EVENTS}


def _webhook_secret_bytes(secret:str)->bytes:
    raw=secret.strip()
    if raw.startswith('whsec_'):raw=raw[6:]
    try:return base64.b64decode(raw+'='*((4-len(raw)%4)%4),validate=True)
    except Exception:raise ValueError('Webhook signing secret is not valid.') from None


def verify_resend_webhook(connection_id:str,raw_body:bytes,headers:dict[str,str],tolerance_seconds:int=300)->str:
    """Verify Resend/Svix Standard Webhooks HMAC using the exact raw request body."""
    secret=load_secret(connection_id,'webhook_secret')
    if not secret:raise ValueError('No webhook signing secret is stored for this email connection.')
    hid=(headers.get('svix-id') or headers.get('webhook-id') or '').strip()
    hts=(headers.get('svix-timestamp') or headers.get('webhook-timestamp') or '').strip()
    hsig=(headers.get('svix-signature') or headers.get('webhook-signature') or '').strip()
    if not hid or not hts or not hsig:raise ValueError('Webhook signature headers are missing.')
    try:ts=int(hts)
    except ValueError:raise ValueError('Webhook timestamp is invalid.') from None
    if abs(int(time.time())-ts)>int(tolerance_seconds):raise ValueError('Webhook timestamp is outside the accepted replay window.')
    signed=hid.encode()+b'.'+hts.encode()+b'.'+raw_body
    expected=base64.b64encode(hmac.new(_webhook_secret_bytes(secret),signed,hashlib.sha256).digest()).decode()
    candidates=[]
    for token in re.split(r'[ ,]+',hsig):
        token=token.strip()
        if not token:continue
        if token.startswith('v1,'):candidates.append(token[3:])
        elif token.startswith('v1='):candidates.append(token[3:])
        elif token!='v1':candidates.append(token)
    if not any(secrets.compare_digest(expected,x) for x in candidates):raise ValueError('Webhook signature is invalid.')
    return hid


def _resend_event_contact(data:dict)->tuple[str,str]:
    email=''; tos=data.get('to') or []
    if isinstance(tos,str):tos=[tos]
    if tos:email=str(tos[0]).strip().lower()
    if not email and data.get('email'):email=str(data.get('email')).strip().lower()
    contact_id=''
    if email:
        row=m.one('SELECT contact_id FROM contacts WHERE lower(email)=lower(?) LIMIT 1',(email,))
        if row:contact_id=row.get('contact_id') or ''
    return contact_id,email


def handle_resend_webhook(connection_id:str,raw_body:bytes,headers:dict[str,str])->dict:
    """Verify, deduplicate and ingest a real Resend webhook event."""
    c=connection(connection_id)
    if c.get('connector_key')!='resend':raise ValueError('Webhook connection is not a Resend connector.')
    event_id=verify_resend_webhook(connection_id,raw_body,{str(k).lower():str(v) for k,v in headers.items()})
    try:event=json.loads(raw_body.decode('utf-8'))
    except Exception:raise ValueError('Webhook body is not valid JSON.') from None
    event_type=str(event.get('type') or event.get('event_type') or '').strip()
    if not event_type:raise ValueError('Webhook event type is missing.')
    existing=m.one('SELECT id FROM v10_webhook_events WHERE connection_id=? AND provider=? AND external_event_id=?',(connection_id,'Resend',event_id))
    if existing:return {'ok':True,'duplicate':True,'event_id':event_id,'event_type':event_type}
    data=event.get('data') if isinstance(event.get('data'),dict) else {}
    provider_message_id=str(data.get('email_id') or data.get('id') or '')
    contact_id,email=_resend_event_contact(data)
    if event_type=='email.received':
        sender=str(data.get('from') or '').strip()
        mm=re.search(r'<([^>]+@[^>]+)>',sender);sender_email=(mm.group(1) if mm else sender).strip().lower()
        if '@' in sender_email:
            email=sender_email
            rr=m.one('SELECT contact_id FROM contacts WHERE lower(email)=lower(?) LIMIT 1',(sender_email,))
            contact_id=(rr or {}).get('contact_id','')
    with m.connect() as con:
        con.execute('INSERT INTO v10_webhook_events(id,connection_id,provider,external_event_id,event_type,signature_valid,payload_json) VALUES(?,?,?,?,?,?,?)',
                    (uid('WH'),connection_id,'Resend',event_id,event_type,1,json.dumps(event,ensure_ascii=False)))
        if provider_message_id:
            mapstatus={'email.sent':'Sent','email.delivered':'Delivered','email.delivery_delayed':'Delayed','email.bounced':'Bounced','email.complained':'Complained','email.opened':'Opened','email.clicked':'Clicked','email.failed':'Failed','email.suppressed':'Suppressed'}
            if event_type in mapstatus:
                con.execute('UPDATE v10_campaign_sends SET status=? WHERE connection_id=? AND provider_message_id=?',(mapstatus[event_type],connection_id,provider_message_id))
    try:
        import business_os as bos
        if contact_id:bos.record_delivery('resend',provider_message_id or event_id,contact_id,'Email',event_type,email,'',event)
    except Exception as exc:
        if contact_id:
            from operational_guard import record_side_effect_failure
            record_side_effect_failure('resend_webhook','Email event received but Customer 360 delivery history failed',exc,recovery='The provider event was preserved. Review the customer and retry event reconciliation.',entity_type='contact',entity_id=contact_id,severity='Error')
    if event_type=='email.received' and contact_id:
        subject=str(data.get('subject') or 'Inbound email')[:500]
        with m.connect() as con:
            con.execute('INSERT INTO interactions(interaction_id,contact_id,channel,interaction_type,direction,subject_or_summary,occurred_at,metadata_json) VALUES(?,?,?,?,?,?,?,?)',
                        (uid('INT'),contact_id,'Email','Received','Inbound',subject,dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat().replace('+00:00','Z'),json.dumps({'provider':'Resend','event_id':event_id,'email_id':provider_message_id})))
        try:
            import operating_core as oc
            oc.emit_event('MESSAGE_RECEIVED','contact',contact_id,{'channel':'Email','message_id':provider_message_id or event_id,'subject':subject},dedupe_key='resend-inbound:'+event_id)
        except Exception as exc:
            from operational_guard import record_side_effect_failure
            record_side_effect_failure('resend_webhook','Inbound email saved but sales follow-up event failed',exc,recovery='The inbound message is safe. Open the customer and retry the follow-up workflow.',entity_type='contact',entity_id=contact_id,severity='Error')
    if event_type in {'email.bounced','email.complained','email.suppressed','contact.unsubscribed'} and email:
        reason='Provider event: '+event_type
        with m.connect() as con:
            con.execute('INSERT OR REPLACE INTO m41_suppressed_endpoints(channel,endpoint,reason) VALUES(?,?,?)',('Email',email,reason))
            if contact_id:
                con.execute("DELETE FROM marketing_permissions WHERE contact_id=? AND channel='Email'",(contact_id,))
                con.execute('INSERT INTO marketing_permissions(permission_id,contact_id,channel,status,lawful_basis_or_reason,evidence_reference,jurisdiction) VALUES(?,?,?,?,?,?,?)',
                            (uid('PER'),contact_id,'Email','Suppressed',reason,'Verified Resend webhook '+event_id,'Provider suppression'))
        if contact_id:
            try:
                import operating_core as oc
                oc.record_consent(contact_id,'Email','Suppressed',reason,'Verified Resend webhook '+event_id,'Provider suppression','system')
            except Exception as exc:
                from operational_guard import record_side_effect_failure
                record_side_effect_failure('resend_webhook','Email suppression applied but consent history failed',exc,recovery='Marketing remains suppressed. Repair the customer consent ledger from System health.',entity_type='contact',entity_id=contact_id,severity='Error')
    m.audit('integration.resend_webhook',connection_id,f'{event_type}; event={event_id}; contact={contact_id or "unmatched"}')
    return {'ok':True,'duplicate':False,'event_id':event_id,'event_type':event_type,'contact_id':contact_id,'message_id':provider_message_id}


def resend_webhook_status(connection_id:str)->dict:
    ext=m.one("SELECT external_id,payload_json,synced_at FROM v10_external_objects WHERE connection_id=? AND object_type='resend_webhook' ORDER BY synced_at DESC LIMIT 1",(connection_id,))
    return {'registered':bool(ext and load_secret(connection_id,'webhook_secret')),'external':ext,'public_base_url':_public_base_url()}

def whatsapp_send_template(connection_id:str,to_phone:str,template_name:str,language='en_US')->dict:
    rc.require_external_write_allowed('send a WhatsApp template')
    c=connection(connection_id);phone_id=c['config'].get('phone_number_id','')
    if not phone_id:raise ValueError('WhatsApp phone-number ID is missing.')
    digits=re.sub(r'\D','',to_phone or '')
    if len(digits)<8:raise ValueError('Enter a recipient number including country code.')
    payload={'messaging_product':'whatsapp','to':digits,'type':'template','template':{'name':template_name,'language':{'code':language}}}
    return _meta(c,phone_id+'/messages',method='POST',payload=payload,operation='Send WhatsApp template')


def sync_meta_ads(connection_id:str)->dict:
    c=connection(connection_id);aid=str(c['config'].get('ad_account_id','')).removeprefix('act_')
    if not aid:raise ValueError('Meta ad account ID is missing.')
    run=begin_sync(connection_id,'meta_ads');summary={'records_seen':0,'records_created':0,'records_updated':0,'records_skipped':0,'errors':0}
    try:
        campaigns=_meta(c,'act_'+aid+'/campaigns',{'fields':'id,name,status,effective_status,objective,updated_time','limit':'100'},operation='Sync Meta campaigns')
        for x in campaigns.get('data',[]):summary['records_seen']+=1;summary['records_updated']+=1;_external_upsert(connection_id,'meta_campaign',x['id'],x)
        ins=_meta(c,'act_'+aid+'/insights',{'fields':'campaign_id,campaign_name,impressions,clicks,spend,actions,action_values,account_currency','level':'campaign','date_preset':'last_30d','time_increment':'1','limit':'500'},operation='Sync Meta insights')
        for x in ins.get('data',[]):
            conv=0.0;revenue=0.0
            for a in x.get('actions') or []:
                if a.get('action_type') in {'purchase','omni_purchase'}:
                    try:conv+=float(a.get('value') or 0)
                    except:pass
            for a in x.get('action_values') or []:
                if a.get('action_type') in {'purchase','omni_purchase'}:
                    try:revenue+=float(a.get('value') or 0)
                    except:pass
            day=x.get('date_start') or dt.date.today().isoformat();cid=x.get('campaign_id','')
            with m.connect() as con:con.execute('''INSERT INTO v10_channel_metrics(id,connection_id,channel,metric_date,campaign_external_id,campaign_name,spend,impressions,clicks,conversions,revenue,currency,source_json)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(connection_id,channel,metric_date,campaign_external_id) DO UPDATE SET campaign_name=excluded.campaign_name,spend=excluded.spend,impressions=excluded.impressions,clicks=excluded.clicks,conversions=excluded.conversions,revenue=excluded.revenue,currency=excluded.currency,source_json=excluded.source_json''',
            (uid('MET'),connection_id,'Meta Ads',day,cid,x.get('campaign_name',''),float(x.get('spend') or 0),int(x.get('impressions') or 0),int(x.get('clicks') or 0),conv,revenue,x.get('account_currency',''),json.dumps(x)))
        summary['records_seen']+=len(ins.get('data',[]));summary['records_updated']+=len(ins.get('data',[]))
        return finish_sync(run,summary)
    except Exception as exc:summary['errors']+=1;finish_sync(run,summary,str(exc));raise


def sync_google_ads(connection_id:str)->dict:
    c=connection(connection_id);token=_google_access_token(c);dev=load_secret(c['id'],'developer_token');customer=re.sub(r'\D','',c['config'].get('customer_id',''))
    if not dev or not customer:raise ValueError('Google Ads developer token and customer ID are required.')
    run=begin_sync(connection_id,'google_ads');summary={'records_seen':0,'records_created':0,'records_updated':0,'records_skipped':0,'errors':0}
    try:
        gaql='''SELECT campaign.id, campaign.name, campaign.status, metrics.impressions, metrics.clicks, metrics.cost_micros, metrics.conversions, metrics.conversions_value, customer.currency_code, segments.date FROM campaign WHERE segments.date DURING LAST_30_DAYS'''
        headers={'Authorization':'Bearer '+token,'developer-token':dev}
        login=re.sub(r'\D','',c['config'].get('login_customer_id',''))
        if login:headers['login-customer-id']=login
        d=api_json(c['id'],'Sync Google Ads','https://googleads.googleapis.com/v25/customers/'+customer+'/googleAds:search','POST',headers,{'query':gaql,'pageSize':10000})
        for row in d.get('results',[]):
            camp=row.get('campaign') or {};met=row.get('metrics') or {};seg=row.get('segments') or {};cust=row.get('customer') or {};ext=str(camp.get('id',''));day=seg.get('date') or dt.date.today().isoformat();summary['records_seen']+=1;summary['records_updated']+=1
            _external_upsert(connection_id,'google_campaign',ext,camp)
            with m.connect() as con:con.execute('''INSERT INTO v10_channel_metrics(id,connection_id,channel,metric_date,campaign_external_id,campaign_name,spend,impressions,clicks,conversions,revenue,currency,source_json)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(connection_id,channel,metric_date,campaign_external_id) DO UPDATE SET campaign_name=excluded.campaign_name,spend=excluded.spend,impressions=excluded.impressions,clicks=excluded.clicks,conversions=excluded.conversions,revenue=excluded.revenue,currency=excluded.currency,source_json=excluded.source_json''',
            (uid('MET'),connection_id,'Google Ads',day,ext,camp.get('name',''),float(met.get('costMicros') or 0)/1_000_000,int(met.get('impressions') or 0),int(met.get('clicks') or 0),float(met.get('conversions') or 0),float(met.get('conversionsValue') or 0),cust.get('currencyCode',''),json.dumps(row)))
        return finish_sync(run,summary)
    except Exception as exc:summary['errors']+=1;finish_sync(run,summary,str(exc));raise



def sync_google_business(connection_id:str)->dict:
    c=connection(connection_id);token=_google_access_token(c);services=c['config'].get('services') or []
    if isinstance(services,str):services=[x for x in services.split(',') if x]
    run=begin_sync(connection_id,'google_business');summary={'records_seen':0,'records_created':0,'records_updated':0,'records_skipped':0,'errors':0,'services':services}
    try:
        headers={'Authorization':'Bearer '+token}
        if 'analytics' in services:
            prop=re.sub(r'\D','',str(c['config'].get('ga4_property_id') or ''))
            if not prop:raise ValueError('Analytics is selected but GA4 property ID is missing.')
            payload={'dateRanges':[{'startDate':'30daysAgo','endDate':'today'}],'dimensions':[{'name':'date'}],'metrics':[{'name':'sessions'},{'name':'transactions'},{'name':'totalRevenue'}],'limit':'1000'}
            d=api_json(c['id'],'Sync GA4','https://analyticsdata.googleapis.com/v1beta/properties/'+prop+':runReport','POST',headers,payload)
            for row in d.get('rows',[]):
                day=(row.get('dimensionValues') or [{}])[0].get('value') or dt.date.today().strftime('%Y%m%d')
                if len(day)==8:day=day[:4]+'-'+day[4:6]+'-'+day[6:]
                vals=[x.get('value','0') for x in row.get('metricValues',[])]
                sessions=int(float(vals[0] or 0)) if len(vals)>0 else 0;trans=float(vals[1] or 0) if len(vals)>1 else 0;rev=float(vals[2] or 0) if len(vals)>2 else 0
                summary['records_seen']+=1;summary['records_updated']+=1
                with m.connect() as con:
                    con.execute("""INSERT INTO v10_channel_metrics(id,connection_id,channel,metric_date,campaign_external_id,campaign_name,spend,impressions,clicks,conversions,revenue,currency,source_json)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(connection_id,channel,metric_date,campaign_external_id) DO UPDATE SET impressions=excluded.impressions,conversions=excluded.conversions,revenue=excluded.revenue,source_json=excluded.source_json""",
                    (uid('MET'),connection_id,'Website / GA4',day,'website','Website',0,sessions,0,trans,rev,m.settings().get('default_currency',''),json.dumps(row)))
        if 'search_console' in services:
            site=str(c['config'].get('search_console_site') or '').strip()
            if not site:raise ValueError('Search Console is selected but the site property is missing.')
            end=dt.date.today();start=end-dt.timedelta(days=30)
            url='https://www.googleapis.com/webmasters/v3/sites/'+urllib.parse.quote(site,safe='')+'/searchAnalytics/query'
            d=api_json(c['id'],'Sync Search Console',url,'POST',headers,{'startDate':start.isoformat(),'endDate':end.isoformat(),'dimensions':['date'],'rowLimit':1000})
            for row in d.get('rows',[]):
                day=(row.get('keys') or [end.isoformat()])[0];summary['records_seen']+=1;summary['records_updated']+=1
                with m.connect() as con:
                    con.execute("""INSERT INTO v10_channel_metrics(id,connection_id,channel,metric_date,campaign_external_id,campaign_name,spend,impressions,clicks,conversions,revenue,currency,source_json)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(connection_id,channel,metric_date,campaign_external_id) DO UPDATE SET impressions=excluded.impressions,clicks=excluded.clicks,source_json=excluded.source_json""",
                    (uid('MET'),connection_id,'Organic Search',day,'search-console','Search Console',0,int(row.get('impressions') or 0),int(row.get('clicks') or 0),0,0,'',json.dumps(row)))
        if 'merchant' in services:
            account=re.sub(r'\D','',str(c['config'].get('merchant_account_id') or ''))
            if not account:raise ValueError('Merchant Center is selected but the account ID is missing.')
            d=api_json(c['id'],'Sync Merchant products',f'https://merchantapi.googleapis.com/products/v1/accounts/{account}/products?pageSize=250','GET',headers)
            for prod in d.get('products',[]) or []:
                ext=prod.get('name') or prod.get('offerId') or uid('MRC');_external_upsert(connection_id,'merchant_product',ext,prod);summary['records_seen']+=1;summary['records_updated']+=1
        if 'gmail' in services:
            d=api_json(c['id'],'Sync Gmail message list','https://gmail.googleapis.com/gmail/v1/users/me/messages?maxResults=25','GET',headers)
            for item in d.get('messages',[]) or []:
                mid=item.get('id')
                if not mid:continue
                url='https://gmail.googleapis.com/gmail/v1/users/me/messages/'+urllib.parse.quote(mid)+'?format=metadata&metadataHeaders=From&metadataHeaders=To&metadataHeaders=Subject&metadataHeaders=Date'
                msg=api_json(c['id'],'Sync Gmail message metadata',url,'GET',headers)
                _external_upsert(connection_id,'gmail_message',mid,msg);summary['records_seen']+=1;summary['records_updated']+=1
                headers_list=((msg.get('payload') or {}).get('headers') or []);hm={x.get('name','').lower():x.get('value','') for x in headers_list}
                candidates=re.findall(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}',hm.get('from','')+' '+hm.get('to',''))
                cid=''
                for em in candidates:
                    cid=_match_contact(em,'')
                    if cid:break
                if cid and not m.one("SELECT 1 FROM interactions WHERE contact_id=? AND metadata_json LIKE ? LIMIT 1",(cid,'%'+mid+'%')):
                    direction='Inbound' if candidates and _match_contact(candidates[0],'')==cid else 'Unknown'
                    with m.connect() as con:
                        con.execute("""INSERT INTO interactions(interaction_id,contact_id,channel,interaction_type,direction,subject_or_summary,occurred_at,metadata_json)
                        VALUES(?,?,?,?,?,?,CURRENT_TIMESTAMP,?)""",(uid('INT'),cid,'Email','Mailbox sync',direction,(hm.get('subject') or 'Email')[:500],json.dumps({'gmail_message_id':mid,'thread_id':msg.get('threadId','')})))
        if 'calendar' in services:
            cal=urllib.parse.quote(str(c['config'].get('calendar_id') or 'primary'),safe='')
            time_min=urllib.parse.quote(dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat().replace('+00:00','Z'),safe=':TZ-')
            d=api_json(c['id'],'Sync Google Calendar',f'https://www.googleapis.com/calendar/v3/calendars/{cal}/events?singleEvents=true&orderBy=startTime&maxResults=100&timeMin={time_min}','GET',headers)
            for ev in d.get('items',[]) or []:
                _external_upsert(connection_id,'calendar_event',ev.get('id') or uid('CAL'),ev);summary['records_seen']+=1;summary['records_updated']+=1
        return finish_sync(run,summary)
    except Exception as exc:
        summary['errors']+=1;finish_sync(run,summary,str(exc));raise


def sync_meta_social(connection_id:str)->dict:
    c=connection(connection_id);run=begin_sync(connection_id,'meta_social');summary={'records_seen':0,'records_created':0,'records_updated':0,'records_skipped':0,'errors':0}
    try:
        d=_meta(c,'me/accounts',{'fields':'id,name,instagram_business_account{id,username}'},operation='Sync Meta Pages')
        for page in d.get('data',[]) or []:
            clean={k:v for k,v in page.items() if k!='access_token'};_external_upsert(connection_id,'facebook_page',str(page.get('id') or ''),clean);summary['records_seen']+=1;summary['records_updated']+=1
            ig=page.get('instagram_business_account') or {}
            if ig:_external_upsert(connection_id,'instagram_account',str(ig.get('id') or ''),ig);summary['records_seen']+=1;summary['records_updated']+=1
        return finish_sync(run,summary)
    except Exception as exc:
        summary['errors']+=1;finish_sync(run,summary,str(exc));raise


def publish_instagram_image(connection_id:str,image_url:str,caption:str)->dict:
    rc.require_external_write_allowed('publish to Instagram')
    c=connection(connection_id)
    if image_url and not re.match(r'^https://',image_url,re.I):
        image_url=media_store.public_url(image_url,upload_if_needed=True)
    if c['connector_key']!='meta_social' or c['status']!='Connected':raise ValueError('Connect and test Instagram/Facebook first.')
    ig=str(c['config'].get('instagram_user_id') or '').strip()
    if not ig:raise ValueError('Select/configure the Instagram Professional account ID first.')
    if not re.match(r'^https://',image_url or '',re.I):raise ValueError('Instagram publishing requires a publicly reachable HTTPS image URL.')
    created=_meta(c,ig+'/media',method='POST',payload={'image_url':image_url,'caption':caption or ''},operation='Create Instagram media container')
    creation_id=created.get('id')
    if not creation_id:raise ValueError('Meta did not return an Instagram media container ID.')
    return _meta(c,ig+'/media_publish',method='POST',payload={'creation_id':creation_id},operation='Publish Instagram image')


def select_meta_social_accounts(connection_id:str,page_id:str='',instagram_user_id:str='')->None:
    c=connection(connection_id)
    if c['connector_key']!='meta_social':raise ValueError('This is not an Instagram/Facebook connection.')
    pages=m.rows("SELECT external_id,payload_json FROM v10_external_objects WHERE connection_id=? AND object_type='facebook_page'",(connection_id,))
    page_ids={str(x['external_id']) for x in pages}
    igs=m.rows("SELECT external_id,payload_json FROM v10_external_objects WHERE connection_id=? AND object_type='instagram_account'",(connection_id,))
    ig_ids={str(x['external_id']) for x in igs}
    page_id=str(page_id or '').strip();instagram_user_id=str(instagram_user_id or '').strip()
    if page_id and page_id not in page_ids:raise ValueError('Sync the Meta connection and choose a Facebook Page returned by the connected account.')
    if instagram_user_id and instagram_user_id not in ig_ids:raise ValueError('Sync the Meta connection and choose an Instagram Professional account returned by the connected account.')
    cfg=dict(c['config']);cfg['page_id']=page_id;cfg['instagram_user_id']=instagram_user_id
    with m.connect() as con:con.execute('UPDATE v10_connections SET config_json=?,updated_at=CURRENT_TIMESTAMP WHERE id=?',(json.dumps(cfg),connection_id))


def _meta_page_token(c:dict,page_id:str)->str:
    d=_meta(c,'me/accounts',{'fields':'id,name,access_token','limit':'200'},operation='Get Facebook Page access token')
    for page in d.get('data',[]) or []:
        if str(page.get('id'))==str(page_id) and page.get('access_token'):return str(page['access_token'])
    raise ValueError('The selected Facebook Page is not available to this authorised Meta account, or the required Page permission is missing.')


def publish_facebook_page_image(connection_id:str,image_url:str,caption:str)->dict:
    rc.require_external_write_allowed('publish to Facebook')
    c=connection(connection_id)
    if image_url and not re.match(r'^https://',image_url,re.I):
        image_url=media_store.public_url(image_url,upload_if_needed=True)
    if c['connector_key']!='meta_social' or c['status']!='Connected':raise ValueError('Connect and test Instagram/Facebook first.')
    page_id=str(c['config'].get('page_id') or '').strip()
    if not page_id:raise ValueError('Select a Facebook Page from the synced Meta accounts first.')
    if not re.match(r'^https://',image_url or '',re.I):raise ValueError('Facebook publishing requires a publicly reachable HTTPS image URL.')
    page_token=_meta_page_token(c,page_id);version=c['config'].get('graph_version') or 'v26.0'
    url=f'https://graph.facebook.com/{version}/{page_id}/photos'
    return api_json(c['id'],'Publish Facebook Page photo',url,'POST',{'Authorization':'Bearer '+page_token},{'url':image_url,'caption':caption or '','published':True})


def sync_stripe(connection_id:str)->dict:
    c=connection(connection_id);key=load_secret(c['id'],'api_key')
    if not key:raise ValueError('Add the Stripe secret key.')
    run=begin_sync(connection_id,'stripe_payments');summary={'records_seen':0,'records_created':0,'records_updated':0,'records_skipped':0,'errors':0}
    try:
        d=api_json(c['id'],'Sync Stripe PaymentIntents','https://api.stripe.com/v1/payment_intents?limit=100','GET',{'Authorization':'Bearer '+key})
        for pi in d.get('data',[]) or []:
            _external_upsert(connection_id,'stripe_payment_intent',pi.get('id') or uid('PI'),pi);summary['records_seen']+=1;summary['records_updated']+=1
        return finish_sync(run,summary)
    except Exception as exc:
        summary['errors']+=1;finish_sync(run,summary,str(exc));raise

def sync_connection(connection_id:str)->dict:
    c=connection(connection_id)
    if c['status']!='Connected':test_connection(connection_id);c=connection(connection_id)
    return {
        'shopify':sync_shopify,'resend':sync_resend,'whatsapp_cloud':sync_whatsapp_templates,
        'meta_ads':sync_meta_ads,'google_ads':sync_google_ads,'google_business':sync_google_business,
        'meta_social':sync_meta_social,'stripe':sync_stripe
    }.get(c['connector_key'],lambda _cid: (_ for _ in ()).throw(ValueError('This connector does not have a live sync implementation.')))(connection_id)


def channel_readiness(channel:str)->dict:
    mapping={'Email':'resend','WhatsApp':'whatsapp_cloud','Meta Ads':'meta_ads','Google Ads':'google_ads','Website':'shopify','Instagram/Facebook':'meta_social'}
    key=mapping.get(channel)
    if not key:return {'status':'Unsupported / planned','connection':None,'reason':'No launch connector is implemented for this channel yet.'}
    conns=[x for x in connections(key) if x['status']=='Connected']
    if not conns:return {'status':'Not connected','connection':None,'reason':CONNECTOR_CATALOG[key]['help']}
    return {'status':'Connected','connection':conns[0],'reason':'Ready for supported operations.'}


def create_unified_campaign(data:dict)->str:
    import v50_reliability as v50
    v50.initialise()
    replay_key=v50.request_key(data.get('idempotency_key'))
    existing=v50.existing_campaign_for_request(replay_key)
    if existing:
        return existing
    name=str(data.get('name') or '').strip();objective=str(data.get('objective') or '').strip();channels=data.get('channels') or []
    if isinstance(channels,str):channels=[channels]
    if not name or not objective:raise ValueError('Campaign name and objective are required.')
    if not channels:raise ValueError('Choose at least one channel.')
    valid={'Email','WhatsApp','Meta Ads','Google Ads','Website','Instagram/Facebook','Pinterest','SEO/Blog'}
    if any(x not in valid for x in channels):raise ValueError('Unknown campaign channel.')
    # Resolve integrations before opening the write transaction. V14 routing may
    # initialise/migrate its own tables, which must never happen through a nested
    # SQLite writer while this campaign transaction is open.
    channel_states=[]
    for ch in channels:
        ready=channel_readiness(ch);channel_states.append((ch,ready,(ready.get('connection') or {}).get('id')))
    cid=uid('UCAM')
    product_ids=data.get('product_ids') or []
    with m.connect() as con:
        con.execute('''INSERT INTO v10_unified_campaigns(id,name,objective,audience_query,product_ids_json,channels_json,region,language,budget,currency) VALUES(?,?,?,?,?,?,?,?,?,?)''',
                    (cid,name,objective,str(data.get('audience_query') or '')[:2000],json.dumps(product_ids),json.dumps(channels),str(data.get('region') or '')[:120],str(data.get('language') or 'English')[:80],float(data['budget']) if data.get('budget') else None,str(data.get('currency') or m.settings().get('default_currency','INR'))))
        for ch,ready,conn in channel_states:
            con.execute('INSERT INTO v10_campaign_channels(id,campaign_id,channel,connection_id,readiness) VALUES(?,?,?,?,?)',(uid('UCH'),cid,ch,conn,ready['status']))
        v50.remember_campaign_request(con,replay_key,cid,'unified')
    try:
        import process_orchestrator as po
        pid=po.ensure_process('campaign_to_revenue','campaign',cid,campaign_id=cid)
        import durable_worker as dw
        dw.enqueue('v17.process.advance',{'process_id':pid},priority=55,idempotency_key='v17-campaign:'+cid)
    except Exception as exc:
        # The campaign itself is safely persisted, but an automation handoff that
        # failed to enter the durable worker must never look like a complete success.
        # Mark the canonical process for owner recovery and create an incident that
        # appears in Needs Attention. The campaign remains a valid Draft.
        try:
            if 'pid' in locals():
                with m.connect() as con:
                    con.execute("UPDATE v17_processes SET status='Needs attention',summary_json=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                                (json.dumps({'error':'Campaign automation could not be queued','detail':str(exc)[:1000]}),pid))
            import operating_core as oc
            oc.incident('campaign','Error','Campaign automation could not start',str(exc),
                        'Open the campaign, check System health, then retry the campaign process. The campaign draft itself is safe.',
                        'campaign',cid)
        except Exception:
            pass
    return cid


def campaign(cid:str)->dict:
    c=m.one('SELECT * FROM v10_unified_campaigns WHERE id=?',(cid,))
    if not c:raise ValueError('Unified campaign not found.')
    c['product_ids']=json.loads(c.get('product_ids_json') or '[]');c['channels']=json.loads(c.get('channels_json') or '[]');c['channel_rows']=m.rows('SELECT * FROM v10_campaign_channels WHERE campaign_id=? ORDER BY channel',(cid,));return c


def require_campaign_executable(cid:str)->dict:
    """Fail closed when an owner has archived or paused a campaign.

    Provider execution must honour the same lifecycle state as the planning UI;
    stored credentials or a direct service call may never bypass that boundary.
    """
    c=campaign(cid)
    status=str(c.get('status') or 'Draft')
    if status in {'Archived','Paused'}:
        raise ValueError('This campaign is '+status.lower()+'. Restore or resume it before sending or creating provider campaigns.')
    return c


def audience_preview_nl(query:str,limit=100)->dict:
    """Deterministic natural-language audience parser over explicit CRM/order facts only.
    Supports journey, B2B/B2C, location, inactivity windows, purchase history and minimum AOV.
    It never infers protected traits.
    """
    q=(query or '').strip();low=q.lower();where=['1=1'];args=[];notes=[]
    if re.search(r'\bb2b\b|boutique|retailer|wholesale|business',low):where.append("c.contact_type IN ('B2B','Both')");notes.append('B2B/Both')
    elif re.search(r'\bb2c\b|consumer',low):where.append("c.contact_type IN ('B2C','Both')");notes.append('B2C/Both')
    locmatch=re.search(r'\bin\s+([A-Za-z][A-Za-z .-]{2,40}?)(?=\s+(?:who|that|with|and|but|customers?|leads?)\b|$)',q,re.I)
    if locmatch:
        loc=locmatch.group(1).strip();where.append('lower(c.country)=lower(?)');args.append(loc);notes.append('country='+loc)
    customer_words=bool(re.search(r'\bcustomer(?:s)?\b|bought|purchased|purchase history|previous buyers?',low))
    lead_words=bool(re.search(r'\blead(?:s)?\b|prospects?',low))
    if customer_words and not lead_words:where.append("c.lifecycle_stage IN ('Customer','Repeat Customer')");notes.append('customer lifecycle')
    if lead_words:where.append("c.lifecycle_stage NOT IN ('Customer','Repeat Customer','Inactive')");notes.append('lead lifecycle')
    months=None
    mm=re.search(r"(?:haven['’]?t|have not|no)\s+(?:bought|purchased|ordered|purchase)\D{0,35}(\d{1,3})\s+months?",low)
    if not mm:mm=re.search(r'(\d{1,3})\s+months?\s+(?:since|without)\s+(?:a\s+)?(?:purchase|order)',low)
    if mm:months=max(1,min(int(mm.group(1)),120))
    if months:
        where.append("EXISTS (SELECT 1 FROM orders ox WHERE ox.contact_id=c.contact_id)")
        where.append("date((SELECT max(ordered_at) FROM orders ol WHERE ol.contact_id=c.contact_id)) <= date('now', ?)")
        args.append(f'-{months} months');notes.append(f'no recorded purchase in {months} months')
    elif re.search(r'\b(?:bought|purchased|ordered)\s+(?:before|previously)|previous customers?|past customers?',low):
        where.append("EXISTS (SELECT 1 FROM orders ox WHERE ox.contact_id=c.contact_id)");notes.append('has recorded order')
    aov=re.search(r'(?:average order value|aov)\s*(?:over|above|>|at least)\s*[£$€₹]?\s*([0-9][0-9,]*(?:\.[0-9]+)?)',low)
    if aov:
        val=float(aov.group(1).replace(',',''));where.append("(SELECT avg(total) FROM orders oa WHERE oa.contact_id=c.contact_id AND oa.total IS NOT NULL) >= ?");args.append(val);notes.append(f'AOV >= {val:g}')
    if 'repeat customer' in low:where.append("c.lifecycle_stage='Repeat Customer'");notes.append('Repeat Customer')
    if re.search(r'\bengaged\b',low):where.append("c.lifecycle_stage='Engaged'");notes.append('Engaged lifecycle')
    if re.search(r'\bqualified\b',low):where.append("c.qualification_status='Qualified'");notes.append('Qualified')
    base=' FROM contacts c WHERE '+' AND '.join(where)
    cols='c.contact_id,c.full_name,c.username,c.email,c.phone_number,c.country,c.contact_type,c.lifecycle_stage'
    rows=m.rows('SELECT '+cols+base+" ORDER BY coalesce(nullif(c.full_name,''),nullif(c.username,''),c.email,c.phone_number) COLLATE NOCASE LIMIT ?",tuple(args+[limit]))
    count=m.one('SELECT count(*) n'+base,tuple(args))['n']
    return {'query':q,'recognized':notes,'unparsed':q if not notes else '', 'contacts':rows,'count':count}


def generate_ai_campaign_plan(cid:str)->dict:
    """Generate a strategy plan from aggregate/verified business context only. Recipient PII is not sent."""
    camp=campaign(cid);key=m.secret()
    if not key:raise ValueError('Connect the OpenAI API key in Settings & AI before generating an AI campaign plan.')
    try:
        import operating_core as oc
        oc.guard_ai_call('general')
    except ImportError:oc=None
    aud=audience_preview_nl(camp.get('audience_query',''),limit=1)
    prod=[]
    for pid in camp['product_ids'][:50]:
        p=m.one('''SELECT p.product_id,p.public_product_name,p.colour,p.category,p.retail_price,p.wholesale_price,p.currency,p.moq,p.status,
                   coalesce(r.confirmed,0) verified FROM products p LEFT JOIN m4_product_review r USING(product_id) WHERE p.product_id=?''',(pid,))
        if p and p.get('status')!='Archived':
            # Unverified fabric/provenance claims are intentionally excluded.
            item={k:p.get(k) for k in ['product_id','public_product_name','colour','category','retail_price','wholesale_price','currency','moq','verified']}
            item['available_stock']=truth.product_available(pid)
            prod.append(item)
    metrics=performance_summary(90)['rows']
    channels=[]
    for ch in camp['channels']:
        rr=channel_readiness(ch);channels.append({'channel':ch,'connection_status':rr['status'],'reason':rr['reason']})
    data={'campaign':{'name':camp['name'],'objective':camp['objective'],'region':camp.get('region',''),'language':camp.get('language','English'),'budget':camp.get('budget'),'currency':camp.get('currency','')},
          'audience':{'query':camp.get('audience_query',''),'recognized_rules':aud['recognized'],'matching_contacts':aud['count']},
          'channels':channels,'products':prod,'synced_channel_metrics_90d':metrics}
    schema={'type':'object','properties':{
      'summary':{'type':'string'},'audience_strategy':{'type':'string'},'product_strategy':{'type':'string'},
      'channel_recommendations':{'type':'array','items':{'type':'object','properties':{'channel':{'type':'string'},'priority':{'type':'string'},'role':{'type':'string'},'reason':{'type':'string'},'budget_percent':{'type':['number','null']}},'required':['channel','priority','role','reason','budget_percent'],'additionalProperties':False}},
      'content_angles':{'type':'array','items':{'type':'string'}},'experiments':{'type':'array','items':{'type':'string'}},'kpis':{'type':'array','items':{'type':'string'}},'risks':{'type':'array','items':{'type':'string'}},'next_actions':{'type':'array','items':{'type':'string'}}
    },'required':['summary','audience_strategy','product_strategy','channel_recommendations','content_angles','experiments','kpis','risks','next_actions'],'additionalProperties':False}
    sys='''You are a cautious growth strategist for a saree/suit commerce business. Use only the supplied aggregate business data. Do not infer recipient traits or invent product facts, offers, discounts, margins, stock urgency, campaign results or conversion probabilities. Treat provider metrics as historical observations, not guarantees. Recommend only channels listed in the input. A channel that is not connected may be recommended for future setup but must not be described as launch-ready. Explain each recommendation in plain language for a non-technical business owner. Budget percentages are suggestions only and must sum to no more than 100 when provided. Return the schema only.'''
    import ai_router
    state=ai_router.preflight('business_analytics',object_type='campaign',object_id=cid,default_model=m.routed_model('business_analytics','gpt-6-sol'))
    body={'model':state['model'],'store':False,'max_output_tokens':2600,'input':[{'role':'system','content':sys},{'role':'user','content':json.dumps(data,ensure_ascii=False)}],
          'text':{'format':{'type':'json_schema','name':'campaign_plan','strict':True,'schema':schema}}}
    out,attempts,duration_ms=ai_router.request_json('business_analytics',body,timeout=60,object_type='campaign',object_id=cid,max_attempts=3)
    usage=out.get('usage') or {}
    ai_router.record_success('business_analytics','OpenAI',state['model'],object_type='campaign',object_id=cid,input_units=int(usage.get('input_tokens') or 0),output_units=int(usage.get('output_tokens') or 0),duration_ms=duration_ms,provider_request_id=str(out.get('id') or ''),attempts=attempts,related_url='/campaigns/'+cid)
    texts=[part.get('text','') for item in out.get('output',[]) if item.get('type')=='message' for part in item.get('content',[]) if part.get('type')=='output_text']
    try:plan=json.loads(''.join(texts))
    except Exception:raise ValueError('AI did not return a usable campaign plan. No campaign was launched or changed.') from None
    with m.connect() as con:con.execute('UPDATE v10_unified_campaigns SET ai_plan_json=?,updated_at=CURRENT_TIMESTAMP WHERE id=?',(json.dumps(plan,ensure_ascii=False),cid))
    m.audit('unified_campaign.ai_plan',cid,'AI strategy plan generated from aggregate/verified data; no recipient PII sent.')
    return plan


def campaign_plan(cid:str)->dict:
    row=m.one('SELECT ai_plan_json FROM v10_unified_campaigns WHERE id=?',(cid,)) or {}
    try:return json.loads(row.get('ai_plan_json') or '{}')
    except Exception:return {}

def _campaign_contacts(cid:str, channel:str, limit:int=5000)->dict:
    """Resolve a unified campaign audience and apply conservative channel eligibility."""
    c=campaign(cid)
    preview=audience_preview_nl(c.get('audience_query',''),limit=max(1,min(int(limit),5000)))
    eligible=[]; blocked=[]; seen=set(); pm=m.permissions_map()
    for row in preview['contacts']:
        full=m.contact(row['contact_id'])
        ok,reason=m.eligibility(full,channel,pm)
        ep=m.endpoint(full,channel)
        if ep and ep in seen:
            blocked.append({'contact':full,'reason':'Duplicate endpoint','endpoint':ep});continue
        if ep:seen.add(ep)
        (eligible if ok else blocked).append({'contact':full,'reason':reason,'endpoint':ep})
    return {'eligible':eligible,'blocked':blocked,'preview':preview}


def campaign_send_readiness(cid:str,channel:str,limit:int=5000)->dict:
    ready=channel_readiness(channel);aud=_campaign_contacts(cid,channel,limit)
    return {
        'channel':channel,'connection':ready.get('connection'),'connection_status':ready['status'],
        'reason':ready['reason'],'eligible_count':len(aud['eligible']),'blocked_count':len(aud['blocked']),
        'sample_eligible':aud['eligible'][:20],'sample_blocked':aud['blocked'][:20],
        'total_matches':aud['preview']['count']
    }


def _personalize(text:str,contact:dict,camp:dict)->str:
    name=(contact.get('first_name') or '').strip()
    if not name:
        full=(contact.get('full_name') or '').strip();name=full.split()[0] if full else ''
    company=''
    co=m.one("""SELECT co.company_name FROM contact_companies cc JOIN companies co ON co.company_id=cc.company_id
                WHERE cc.contact_id=? ORDER BY cc.is_primary DESC,co.company_name LIMIT 1""",(contact['contact_id'],))
    if co:company=co.get('company_name') or ''
    brand=m.settings().get('brand_name','') or '[Your brand]'
    values={'first_name':name or 'there','full_name':contact.get('full_name') or name or 'there','company_name':company,
            'brand':brand,'objective':camp.get('objective','')}
    out=str(text or '')
    for k,v in values.items():out=out.replace('{{'+k+'}}',str(v))
    if re.search(r'\{\{[^}]+\}\}',out):raise ValueError('Message contains an unsupported or unresolved merge field.')
    return out


def _record_campaign_send(cid:str,channel:str,connection_id:str,contact:dict,endpoint:str,status:str,provider_id:str='',subject:str='',payload:dict|None=None,error:str='',send_key:str='')->str:
    sid=uid('SEND')
    with m.connect() as con:
        con.execute("""INSERT INTO v10_campaign_sends(id,campaign_id,channel,connection_id,contact_id,endpoint,status,provider_message_id,subject,payload_json,error,send_key)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",(sid,cid,channel,connection_id,contact['contact_id'],endpoint,status,provider_id,subject,json.dumps(payload or {}),str(error)[:1200],send_key))
        if status=='Submitted':
            
            cols={r['name'] for r in con.execute('PRAGMA table_info(interactions)').fetchall()}
            if 'canonical_campaign_id' in cols:
                con.execute("""INSERT INTO interactions(interaction_id,contact_id,campaign_id,canonical_campaign_id,channel,interaction_type,direction,subject_or_summary,occurred_at,metadata_json)
                           VALUES(?,?,?,?,?,?,?,?,?,?)""",(uid('INT'),contact['contact_id'],None,cid,channel,'Submitted','Outbound',subject or ('Campaign '+channel),dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat().replace('+00:00','Z'),json.dumps({'unified_campaign_id':cid,'provider_message_id':provider_id})))
            else:
                con.execute("""INSERT INTO interactions(interaction_id,contact_id,campaign_id,channel,interaction_type,direction,subject_or_summary,occurred_at,metadata_json)
                           VALUES(?,?,?,?,?,?,?,?,?)""",(uid('INT'),contact['contact_id'],None,channel,'Submitted','Outbound',subject or ('Campaign '+channel),dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat().replace('+00:00','Z'),json.dumps({'unified_campaign_id':cid,'provider_message_id':provider_id})))
    try:
        import business_os as bos
        if status=='Submitted':bos.record_delivery(channel.lower().replace(' ','_'),provider_id or sid,contact['contact_id'],channel,'submitted',endpoint,cid,payload or {})
    except Exception as exc:
        if status=='Submitted':
            from operational_guard import record_side_effect_failure
            record_side_effect_failure('campaign_delivery','Campaign send succeeded but Customer 360 delivery history failed',exc,recovery='The provider submission is preserved. Open the campaign/customer and reconcile delivery history; do not resend blindly.',entity_type='campaign',entity_id=cid,severity='Error')
    return sid


def send_email_campaign(cid:str,from_email:str,subject:str,body_text:str,max_recipients:int=50)->dict:
    rc.require_external_write_allowed('send a real email campaign')
    """Submit a reviewed campaign via Resend only to contacts that pass the CRM Email eligibility gate."""
    camp=require_campaign_executable(cid);ready=channel_readiness('Email')
    if ready['status']!='Connected' or not ready.get('connection'):raise ValueError('Connect and test an email provider first.')
    if not from_email or '@' not in from_email:raise ValueError('Enter the verified sender email address.')
    if not subject.strip() or not body_text.strip():raise ValueError('Subject and message are required.')
    limit=max(1,min(int(max_recipients or 50),100))
    aud=_campaign_contacts(cid,'Email',5000);selected=aud['eligible'][:limit]
    if not selected:raise ValueError('No recipients have a valid email address and documented eligible Email permission.')
    connection_id=ready['connection']['id'];submitted=failed=0;ids=[]
    for item in selected:
        contact=item['contact'];endpoint=item['endpoint']
        try:
            sub=_personalize(subject,contact,camp);txt=_personalize(body_text,contact,camp)
            html='<p>'+txt.replace('&','&amp;').replace('<','&lt;').replace('>','&gt;').replace('\n','<br>')+'</p>'
            idem='crm-'+hashlib.sha256((cid+'|Email|'+contact['contact_id']+'|'+sub+'|'+txt).encode()).hexdigest()[:48]
            prior=m.one("SELECT provider_message_id FROM v10_campaign_sends WHERE send_key=? AND status='Submitted'",(idem,))
            if prior:
                submitted+=1
                if prior.get('provider_message_id'):ids.append(prior['provider_message_id'])
                continue
            out=resend_send_email(connection_id,from_email,endpoint,sub,html,txt,idem)
            pid=str(out.get('id','')) if isinstance(out,dict) else ''
            _record_campaign_send(cid,'Email',connection_id,contact,endpoint,'Submitted',pid,sub,{'provider':'Resend'},send_key=idem)
            submitted+=1;ids.append(pid)
        except Exception as exc:
            _record_campaign_send(cid,'Email',connection_id,contact,endpoint,'Failed','',subject,{},str(exc));failed+=1
    m.audit('unified_campaign.email_submitted',cid,f'{submitted} submitted; {failed} failed; {len(aud["blocked"])} blocked by eligibility/data-quality gate.')
    return {'submitted':submitted,'failed':failed,'blocked':len(aud['blocked']),'eligible_total':len(aud['eligible']),'provider_ids':[x for x in ids if x]}


def send_whatsapp_campaign(cid:str,template_name:str,language='en_US',max_recipients:int=50)->dict:
    rc.require_external_write_allowed('send a real WhatsApp campaign')
    """Submit an approved parameter-free WhatsApp template only to contacts that pass the opt-in/evidence gate."""
    require_campaign_executable(cid)
    ready=channel_readiness('WhatsApp')
    if ready['status']!='Connected' or not ready.get('connection'):raise ValueError('Connect and test WhatsApp Business Cloud API first.')
    if not template_name.strip():raise ValueError('Choose an approved WhatsApp template.')
    connection_id=ready['connection']['id']
    tpl=m.one("SELECT payload_json FROM v10_external_objects WHERE connection_id=? AND object_type='whatsapp_template' AND json_extract(payload_json,'$.name')=?",(connection_id,template_name))
    if not tpl:raise ValueError('Sync WhatsApp templates and choose one returned by the connected business account.')
    try:payload=json.loads(tpl['payload_json'])
    except:payload={}
    if str(payload.get('status','')).upper()!='APPROVED':raise ValueError('The selected WhatsApp template is not approved.')
    raw=json.dumps(payload.get('components') or [])
    if re.search(r'\{\{\s*\d+\s*\}\}',raw):raise ValueError('This template contains variables. V10 will not guess template values; use a parameter-free approved template for this test release.')
    limit=max(1,min(int(max_recipients or 50),100));aud=_campaign_contacts(cid,'WhatsApp',5000);selected=aud['eligible'][:limit]
    if not selected:raise ValueError('No recipients have documented WhatsApp opt-in/evidence and a valid number.')
    submitted=failed=0
    for item in selected:
        contact=item['contact'];endpoint=item['endpoint']
        try:
            send_key='crm-'+hashlib.sha256((cid+'|WhatsApp|'+contact['contact_id']+'|'+template_name+'|'+language).encode()).hexdigest()[:48]
            prior=m.one("SELECT provider_message_id FROM v10_campaign_sends WHERE send_key=? AND status='Submitted'",(send_key,))
            if prior:
                submitted+=1;continue
            out=whatsapp_send_template(connection_id,endpoint,template_name,language)
            msgs=(out.get('messages') or []) if isinstance(out,dict) else [];pid=str((msgs[0] if msgs else {}).get('id',''))
            _record_campaign_send(cid,'WhatsApp',connection_id,contact,endpoint,'Submitted',pid,'',{'template':template_name,'language':language},send_key=send_key)
            submitted+=1
        except Exception as exc:
            _record_campaign_send(cid,'WhatsApp',connection_id,contact,endpoint,'Failed','', '',{'template':template_name},str(exc));failed+=1
    m.audit('unified_campaign.whatsapp_submitted',cid,f'{submitted} submitted; {failed} failed; {len(aud["blocked"])} blocked by eligibility/data-quality gate.')
    return {'submitted':submitted,'failed':failed,'blocked':len(aud['blocked']),'eligible_total':len(aud['eligible'])}


def campaign_sends(cid:str,limit=250)->list[dict]:
    return m.rows("""SELECT s.*,coalesce(c.full_name,c.username,c.email,c.phone_number) contact_name
                     FROM v10_campaign_sends s LEFT JOIN contacts c ON c.contact_id=s.contact_id
                     WHERE s.campaign_id=? ORDER BY s.created_at DESC LIMIT ?""",(cid,int(limit)))

def performance_summary(days=30)->dict:
    rows=m.rows('''SELECT channel,currency,sum(spend) spend,sum(impressions) impressions,sum(clicks) clicks,sum(conversions) conversions,sum(revenue) revenue
                   FROM v10_channel_metrics WHERE date(metric_date)>=date('now',?) GROUP BY channel,currency ORDER BY channel,currency''',(f'-{int(days)} days',))
    out=[];recommendations=[]
    for r in rows:
        r=dict(r);r['roas']=(r['revenue']/r['spend']) if r['spend'] else None;r['ctr']=(r['clicks']/r['impressions']*100) if r['impressions'] else None;r['cpa']=(r['spend']/r['conversions']) if r['conversions'] else None;out.append(r)
        if r['spend'] and not r['conversions']:
            recommendations.append({'severity':'Review','channel':r['channel'],'message':f"{r['channel']} recorded spend but no provider-reported conversions in this window. Review targeting, creative and tracking before increasing budget."})
        if r['impressions'] and r['clicks']==0:
            recommendations.append({'severity':'Review','channel':r['channel'],'message':f"{r['channel']} recorded impressions but no clicks. Review creative and placement fit."})
    valid=[x for x in out if x['roas'] is not None and x['spend']>0]
    if len(valid)>=2:
        best=max(valid,key=lambda x:x['roas']);recommendations.append({'severity':'Opportunity','channel':best['channel'],'message':f"{best['channel']} has the highest provider-reported ROAS in this window ({best['roas']:.2f}x). Treat this as a signal for testing, not an automatic budget decision."})
    return {'rows':out,'days':days,'recommendations':recommendations}


def setup_status()->list[dict]:
    """Ten-step non-technical onboarding. A step is complete only when real data/configuration supports it."""
    st=m.settings();contacts=m.one('SELECT count(*) n FROM contacts')['n'];products=m.one('SELECT count(*) n FROM products')['n'];campaigns=m.one('SELECT count(*) n FROM v10_unified_campaigns')['n']
    def conn(keys):
        if isinstance(keys,str):keys=[keys]
        for key in keys:
            c=next((x for x in connections(key) if x['status']=='Connected'),None)
            if c:return c
        return None
    brand=bool((st.get('brand_name') or '').strip() and (st.get('brand_name') or '').strip().lower() not in {'brand name pending','pending'})
    store=conn('shopify');email=conn('resend');meta=conn(['meta_social','meta_ads']);google=conn(['google_business','google_ads']);wa=conn('whatsapp_cloud')
    ai=bool(m.secret())
    return [
      {'key':'profile','label':'Create business profile','status':'Complete' if brand else 'Needs setup','detail':(st.get('brand_name') or 'Add the real business name, currency and contact details.'),'url':'/settings'},
      {'key':'store','label':'Connect website / store','status':'Complete' if store else 'Needs setup','detail':(store or {}).get('account_name','') or 'Shopify is the first live commerce connector.','url':'/integrations/'+store['id'] if store else '/integrations/connect/shopify'},
      {'key':'email','label':'Connect email and sending domain','status':'Complete' if email else 'Needs setup','detail':(email or {}).get('account_name','') or 'Connect Resend, then verify your sending domain and delivery webhook after deployment.','url':'/integrations/'+email['id'] if email else '/integrations/connect/resend'},
      {'key':'meta','label':'Connect Meta / Instagram / Facebook','status':'Complete' if meta else 'Needs setup','detail':(meta or {}).get('account_name','') or 'Connect organic social and/or Meta Ads with the required business permissions.','url':'/integrations/'+meta['id'] if meta else '/integrations/connect/meta_social'},
      {'key':'google','label':'Connect Google services','status':'Complete' if google else 'Needs setup','detail':(google or {}).get('account_name','') or 'One Google Business OAuth connection can cover Analytics, Search Console, Merchant, Gmail and Calendar; Google Ads remains separate because it also needs a developer token.','url':'/integrations/'+google['id'] if google else '/integrations/connect/google_business'},
      {'key':'whatsapp','label':'Connect WhatsApp Business','status':'Complete' if wa else 'Needs setup','detail':(wa or {}).get('account_name','') or 'Connect Cloud API, sync approved templates, then configure signed webhooks after deployment.','url':'/integrations/'+wa['id'] if wa else '/integrations/connect/whatsapp_cloud'},
      {'key':'customers','label':'Import or synchronise customers','status':'Complete' if contacts else 'Needs setup','detail':f'{contacts:,} CRM contacts available.','url':'/contacts'},
      {'key':'brand','label':'Configure AI and brand knowledge','status':'Complete' if ai and brand else 'Needs setup','detail':('AI and brand identity configured.' if ai and brand else 'Add brand settings, approved knowledge and an AI connection for higher automation.'),'url':'/settings'},
      {'key':'products','label':'Upload first products','status':'Complete' if products else 'Needs setup','detail':f'{products:,} product records available.','url':'/product-engine'},
      {'key':'campaign','label':'Create first AI campaign','status':'Complete' if campaigns else 'Needs setup','detail':'Build one objective, audience and product selection, then adapt it to connected channels.','url':'/campaign-builder'},
    ]


def connection_audit(connection_id:str,limit=100)->list[dict]:
    return m.rows('SELECT * FROM v10_api_logs WHERE connection_id=? ORDER BY created_at DESC LIMIT ?',(connection_id,limit))


def recent_syncs(connection_id:str='',limit=100)->list[dict]:
    if connection_id:return m.rows('SELECT * FROM v10_sync_runs WHERE connection_id=? ORDER BY started_at DESC LIMIT ?',(connection_id,limit))
    return m.rows('SELECT * FROM v10_sync_runs ORDER BY started_at DESC LIMIT ?',(limit,))

GOOGLE_ADS_SCOPE='https://www.googleapis.com/auth/adwords'
GOOGLE_SERVICE_SCOPES={
    'analytics':'https://www.googleapis.com/auth/analytics.readonly',
    'search_console':'https://www.googleapis.com/auth/webmasters.readonly',
    'merchant':'https://www.googleapis.com/auth/content',
    'gmail':'https://www.googleapis.com/auth/gmail.readonly',
    'calendar':'https://www.googleapis.com/auth/calendar.readonly',
}
META_ADS_SCOPES=['ads_read','business_management']
META_SOCIAL_SCOPES=['pages_show_list','pages_read_engagement','pages_manage_posts','instagram_basic','instagram_content_publish','business_management']


def begin_oauth(connection_id:str,provider:str,redirect_uri:str)->str:
    c=connection(connection_id);state=secrets.token_urlsafe(32)
    if provider=='google':
        client_id=c['config'].get('client_id','')
        if not client_id or not load_secret(connection_id,'client_secret'):raise ValueError('Save the Google OAuth client ID and client secret first.')
        if c['connector_key']=='google_business':
            services=c['config'].get('services') or []
            if isinstance(services,str):services=[x for x in services.split(',') if x]
            scopes=['openid','email','https://www.googleapis.com/auth/userinfo.email']+[GOOGLE_SERVICE_SCOPES[x] for x in services if x in GOOGLE_SERVICE_SCOPES]
            if len(scopes)<=3:raise ValueError('Choose at least one Google business service before starting OAuth.')
        else:
            scopes=[GOOGLE_ADS_SCOPE]
        params={'client_id':client_id,'redirect_uri':redirect_uri,'response_type':'code','scope':' '.join(dict.fromkeys(scopes)),'access_type':'offline','include_granted_scopes':'true','prompt':'consent','state':state}
        url='https://accounts.google.com/o/oauth2/v2/auth?'+urllib.parse.urlencode(params)
    elif provider=='meta':
        app_id=c['config'].get('app_id','')
        if not app_id or not load_secret(connection_id,'app_secret'):raise ValueError('Save the Meta app ID and app secret first.')
        scopes=META_SOCIAL_SCOPES if c['connector_key']=='meta_social' else META_ADS_SCOPES
        version=c['config'].get('graph_version') or 'v26.0'
        params={'client_id':app_id,'redirect_uri':redirect_uri,'state':state,'response_type':'code','scope':','.join(scopes)}
        url=f'https://www.facebook.com/{version}/dialog/oauth?'+urllib.parse.urlencode(params)
    else:raise ValueError('OAuth provider not supported.')
    with m.connect() as con:
        con.execute('INSERT INTO v10_oauth_states(state,provider,connection_id,redirect_uri,scopes_json) VALUES(?,?,?,?,?)',(state,provider,connection_id,redirect_uri,json.dumps(scopes)))
    return url


def complete_oauth(provider:str,state:str,code:str)->str:
    row=m.one("SELECT * FROM v10_oauth_states WHERE state=? AND provider=? AND datetime(created_at)>=datetime('now','-15 minutes')",(state,provider))
    if not row:raise ValueError('OAuth session expired or state check failed. Start the connection again.')
    c=connection(row['connection_id']);redirect=row['redirect_uri']
    if provider=='google':
        payload=urllib.parse.urlencode({'code':code,'client_id':c['config'].get('client_id',''),'client_secret':load_secret(c['id'],'client_secret'),'redirect_uri':redirect,'grant_type':'authorization_code'}).encode()
        req=urllib.request.Request('https://oauth2.googleapis.com/token',data=payload,headers={'Content-Type':'application/x-www-form-urlencoded'},method='POST')
        try:
            with urllib.request.urlopen(req,timeout=30) as resp:out=json.load(resp)
        except urllib.error.HTTPError:raise ValueError('Google OAuth code exchange failed. Check the configured redirect URI and OAuth client.') from None
        if out.get('refresh_token'):store_secret(c['id'],'refresh_token',out['refresh_token'])
        if out.get('access_token'):store_secret(c['id'],'access_token',out['access_token'])
    elif provider=='meta':
        version=c['config'].get('graph_version') or 'v26.0'
        params={'client_id':c['config'].get('app_id',''),'client_secret':load_secret(c['id'],'app_secret'),'redirect_uri':redirect,'code':code}
        url=f'https://graph.facebook.com/{version}/oauth/access_token?'+urllib.parse.urlencode(params)
        try:
            with urllib.request.urlopen(url,timeout=30) as resp:out=json.load(resp)
        except urllib.error.HTTPError:raise ValueError('Meta OAuth code exchange failed. Check the app settings and valid OAuth redirect URI.') from None
        if not out.get('access_token'):raise ValueError('Meta did not return an access token.')
        store_secret(c['id'],'access_token',out['access_token'])
    else:raise ValueError('OAuth provider not supported.')
    with m.connect() as con:con.execute('DELETE FROM v10_oauth_states WHERE state=?',(state,))
    return c['id']

# --- V11 webhook helpers ----------------------------------------------------
def _record_webhook_receipt_once(connector_key:str,external_event_id:str,event_type:str,payload_hash:str,status:str='Processed')->str:
    existing=m.one('SELECT id FROM v9_webhook_receipts WHERE connector_key=? AND external_event_id=?',(connector_key,external_event_id))
    if existing:return ''
    rid=uid('WHR')
    try:
        with m.connect() as con:con.execute('INSERT INTO v9_webhook_receipts(id,connector_key,external_event_id,signature_valid,event_type,status,payload_hash) VALUES(?,?,?,?,?,?,?)',(rid,connector_key,external_event_id,1,event_type,status,payload_hash))
        return rid
    except Exception:
        # SQLite and PostgreSQL raise different uniqueness exception classes.
        existing=m.one('SELECT id FROM v9_webhook_receipts WHERE connector_key=? AND external_event_id=?',(connector_key,external_event_id))
        if existing:return ''
        raise

def verify_meta_webhook_challenge(connection_id:str,mode:str,verify_token:str,challenge:str)->str:
    c=connection(connection_id)
    expected=str(c.get('config',{}).get('verify_token') or '')
    if c['connector_key']!='whatsapp_cloud':raise ValueError('This webhook endpoint is not a WhatsApp connection.')
    if mode!='subscribe' or not expected or not secrets.compare_digest(expected,verify_token or ''):raise ValueError('Webhook verification token did not match.')
    return challenge


def _meta_signing_secret(connection_id:str)->str:
    """Return the platform Meta app secret, with legacy per-connection fallback."""
    try:
        import integration_v14 as v14
        secret=v14.provider_secret('meta','client_secret')
        if secret:return secret
    except Exception:
        pass
    return load_secret(connection_id,'app_secret')


def _verify_meta_signature(connection_id:str,raw_body:bytes,signature:str)->None:
    secret=_meta_signing_secret(connection_id)
    if not secret:raise ValueError('The platform Meta App Secret is required before receiving signed webhooks.')
    if not signature or not signature.startswith('sha256='):raise ValueError('Missing Meta webhook signature.')
    expected=hmac.new(secret.encode(),raw_body,hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected,signature.split('=',1)[1]):raise ValueError('Meta webhook signature validation failed.')


def handle_whatsapp_webhook(connection_id:str,raw_body:bytes,headers:dict[str,str])->dict:
    c=connection(connection_id)
    if c['connector_key']!='whatsapp_cloud':raise ValueError('This is not a WhatsApp connection.')
    sig=headers.get('X-Hub-Signature-256') or headers.get('x-hub-signature-256') or ''
    _verify_meta_signature(connection_id,raw_body,sig)
    try:payload=json.loads(raw_body.decode('utf-8'))
    except Exception:raise ValueError('Webhook body is not valid JSON.') from None
    handled=duplicates=status_count=message_count=0
    import business_os as bos
    import contact_tools as ct
    for entry in payload.get('entry',[]) or []:
        for change in entry.get('changes',[]) or []:
            value=change.get('value') or {}
            for st in value.get('statuses',[]) or []:
                mid=str(st.get('id') or '');event=str(st.get('status') or 'status')
                if not mid:continue
                rid='wa:'+mid+':'+event
                if not _record_webhook_receipt_once('whatsapp',rid,event,hashlib.sha256(raw_body).hexdigest(),'Processed'):
                    duplicates+=1;continue
                phone=str(st.get('recipient_id') or '');cid=_match_contact('',phone)
                bos.record_delivery('whatsapp',mid,cid,'WhatsApp',event,phone,'',st)
                with m.connect() as con:con.execute("UPDATE v10_campaign_sends SET status=?,updated_at=CURRENT_TIMESTAMP WHERE provider_message_id=?",(event.title(),mid))
                handled+=1;status_count+=1
            for msg in value.get('messages',[]) or []:
                mid=str(msg.get('id') or '');phone=str(msg.get('from') or '')
                if not mid:continue
                rid='wa:'+mid+':inbound'
                if not _record_webhook_receipt_once('whatsapp',rid,'message',hashlib.sha256(raw_body).hexdigest(),'Processed'):
                    duplicates+=1;continue
                cid=_match_contact('',phone)
                if not cid:
                    try:cid=ct.save_contact({'full_name':'','first_name':'','contact_type':'Unknown','email':'','phone_number':'+'+re.sub(r'\D','',phone),'source_name':'WhatsApp inbound','source_reference':mid,'country':'','language':'','username':'','website':'','business_category':'','tags':'Inbound'})
                    except ValueError:cid=_match_contact('',phone)
                body=((msg.get('text') or {}).get('body') or ('WhatsApp '+str(msg.get('type') or 'message')))[:4000]
                if cid:
                    with m.connect() as con:con.execute('''INSERT INTO interactions(interaction_id,contact_id,channel,interaction_type,direction,subject_or_summary,occurred_at,metadata_json)
                    VALUES(?,?,?,?,?,?,CURRENT_TIMESTAMP,?)''',(uid('INT'),cid,'WhatsApp','Message','Inbound',body,json.dumps({'provider_message_id':mid,'raw_type':msg.get('type')})))
                    bos.record_delivery('whatsapp',mid,cid,'WhatsApp','received',phone,'',msg)
                    try:bos.emit('contact.message_received','contact',cid,{'channel':'WhatsApp','message_id':mid},'wa-inbound-'+mid)
                    except Exception as exc:
                        from operational_guard import record_side_effect_failure
                        record_side_effect_failure('whatsapp_webhook','WhatsApp message saved but compatibility event failed',exc,recovery='The message is safe. Use the customer timeline while the compatibility event is repaired.',entity_type='contact',entity_id=cid,severity='Warning')
                    try:
                        import operating_core as oc
                        oc.emit_event('MESSAGE_RECEIVED','contact',cid,{'channel':'WhatsApp','message_id':mid,'summary':body[:500]},dedupe_key='wa-inbound:'+mid)
                    except Exception as exc:
                        from operational_guard import record_side_effect_failure
                        record_side_effect_failure('whatsapp_webhook','WhatsApp message saved but sales follow-up event failed',exc,recovery='The inbound message is safe. Open the customer and retry the follow-up workflow.',entity_type='contact',entity_id=cid,severity='Error')
                handled+=1;message_count+=1
    return {'ok':True,'handled':handled,'statuses':status_count,'messages':message_count,'duplicates':duplicates}


def _shopify_signing_secret(connection_id:str)->str:
    """Return the Shopify app signing secret without making a business owner store it.

    V14 keeps provider/developer credentials in the platform provider-app store. Older
    V10-V13 workspaces may still have an app_secret on the individual connection, so
    retain that as a backwards-compatible fallback.
    """
    try:
        import integration_v14 as v14
        secret=v14.provider_secret('shopify','client_secret')
        if secret:return secret
    except Exception:
        pass
    return load_secret(connection_id,'app_secret')


def shopify_register_webhooks(connection_id:str)->dict:
    rc.require_external_write_allowed('register Shopify webhooks')
    c=connection(connection_id)
    if c['connector_key']!='shopify' or c['status']!='Connected':raise ValueError('Connect and test Shopify first.')
    if not _shopify_signing_secret(connection_id):raise ValueError('The platform Shopify app secret is not configured. Ask an administrator to complete Advanced platform integrations.')
    base=_public_base_url()
    if not base:raise ValueError('Configure a real public HTTPS Base URL before registering Shopify webhooks.')
    uri=base.rstrip('/')+'/webhooks/shopify/'+connection_id
    topics=['ORDERS_CREATE','ORDERS_UPDATED','CUSTOMERS_CREATE','CUSTOMERS_UPDATE','PRODUCTS_UPDATE']
    mutation='''mutation Hook($topic: WebhookSubscriptionTopic!, $webhook: WebhookSubscriptionInput!) { webhookSubscriptionCreate(topic:$topic, webhookSubscription:$webhook) { webhookSubscription { id topic uri } userErrors { field message } } }'''
    made=[];errors=[]
    for topic in topics:
        try:
            d=_shopify_graphql(c,mutation,{'topic':topic,'webhook':{'uri':uri,'format':'JSON'}},operation='Register Shopify webhook').get('webhookSubscriptionCreate') or {}
            if d.get('userErrors'):errors.extend([x.get('message','') for x in d['userErrors']]);continue
            hook=d.get('webhookSubscription') or {};made.append(hook);_external_upsert(connection_id,'shopify_webhook',str(hook.get('id') or topic),hook)
        except Exception as exc:errors.append(str(exc))
    if not made and errors:raise ValueError('Shopify webhook registration failed: '+ '; '.join(errors[:3]))
    return {'registered':len(made),'errors':errors,'endpoint':uri}


def handle_shopify_webhook(connection_id:str,raw_body:bytes,headers:dict[str,str])->dict:
    c=connection(connection_id)
    if c['connector_key']!='shopify':raise ValueError('This is not a Shopify connection.')
    secret=_shopify_signing_secret(connection_id)
    if not secret:raise ValueError('The platform Shopify app secret is required for signed webhook validation.')
    got=headers.get('X-Shopify-Hmac-Sha256') or headers.get('x-shopify-hmac-sha256') or ''
    expected=base64.b64encode(hmac.new(secret.encode(),raw_body,hashlib.sha256).digest()).decode()
    if not got or not hmac.compare_digest(expected,got):raise ValueError('Shopify webhook signature validation failed.')
    topic=headers.get('X-Shopify-Topic') or headers.get('x-shopify-topic') or 'unknown'
    event_id=headers.get('X-Shopify-Webhook-Id') or headers.get('x-shopify-webhook-id') or hashlib.sha256(raw_body).hexdigest()
    try:payload=json.loads(raw_body.decode('utf-8'))
    except Exception:raise ValueError('Shopify webhook body is not valid JSON.') from None
    receipt_id=_record_webhook_receipt_once('shopify',event_id,topic,hashlib.sha256(raw_body).hexdigest(),'Queued')
    if not receipt_id:return {'ok':True,'duplicate':True,'topic':topic}
    try:
        with m.connect() as con:con.execute('''INSERT INTO v10_webhook_events(id,connection_id,provider,external_event_id,event_type,signature_valid,payload_json)
                                               VALUES(?,?,?,?,?,?,?) ON CONFLICT(connection_id,provider,external_event_id) DO NOTHING''',(uid('WHE'),connection_id,'shopify',event_id,topic,1,json.dumps(payload,ensure_ascii=False)))
        import durable_worker as dw
        dw.enqueue('integration.webhook.sync',{'connection_id':connection_id,'receipt_id':receipt_id,'event_id':event_id},priority=30,max_attempts=6,idempotency_key='shopify-webhook:'+connection_id+':'+event_id)
        # Keep the periodic reconciliation schedule enabled as a safety net. The
        # durable webhook job handles the immediate event; the schedule catches any
        # provider event that was delayed, dropped upstream or could not be queued.
        try:
            import platform_core as pc
            pc.ensure_connection_schedule(connection_id,60)
        except Exception:pass
    except Exception:
        with m.connect() as con:con.execute("UPDATE v9_webhook_receipts SET status='FailedToQueue' WHERE id=?",(receipt_id,))
        raise
    try:
        import business_os as bos
        bos.emit('shopify.'+topic.replace('/','.'),'integration',connection_id,{'external_id':payload.get('id'),'topic':topic},'shopify-'+event_id)
    except Exception as exc:
        from operational_guard import record_side_effect_failure
        record_side_effect_failure('shopify_webhook','Shopify webhook queued but compatibility event handoff failed',exc,recovery='The durable provider webhook remains queued. Review integration health; do not replay the provider transaction manually.',entity_type='integration',entity_id=connection_id,severity='Warning')
    return {'ok':True,'duplicate':False,'topic':topic,'queued':True}
