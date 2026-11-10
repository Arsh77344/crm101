from __future__ import annotations

"""V14 login-first integration operating layer.

This module deliberately separates platform/operator credentials from merchant/business
connections. A normal business user connects an account with provider login. Provider
client IDs/secrets live in environment-managed secrets in production (or the encrypted
local vault during development) and are never requested in the normal connection UI.
"""

import base64
import datetime as dt
import hashlib
import hmac
import json
import os
import re
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

import marketing as m
import runtime_config as rc
import integration_layer as legacy
import db_layer
import v35_truth as truth

V14_SCHEMA = r'''
CREATE TABLE IF NOT EXISTS v14_provider_apps(
  provider_key TEXT PRIMARY KEY,
  display_name TEXT NOT NULL,
  client_id TEXT DEFAULT '',
  config_json TEXT NOT NULL DEFAULT '{}',
  status TEXT NOT NULL DEFAULT 'Not configured',
  updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS v14_provider_secrets(
  provider_key TEXT NOT NULL,
  secret_key TEXT NOT NULL,
  encrypted_value BLOB NOT NULL,
  hint TEXT DEFAULT '',
  updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY(provider_key,secret_key)
);
CREATE TABLE IF NOT EXISTS v14_oauth_sessions(
  state TEXT PRIMARY KEY,
  provider_key TEXT NOT NULL,
  connector_key TEXT NOT NULL,
  connection_id TEXT NOT NULL,
  redirect_uri TEXT NOT NULL,
  requested_scopes_json TEXT NOT NULL DEFAULT '[]',
  context_json TEXT NOT NULL DEFAULT '{}',
  verifier_encrypted BLOB,
  initiated_user_id TEXT DEFAULT '',
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS v14_token_metadata(
  connection_id TEXT PRIMARY KEY,
  token_type TEXT DEFAULT 'Bearer',
  expires_at TEXT,
  refresh_expires_at TEXT,
  granted_scopes_json TEXT NOT NULL DEFAULT '[]',
  last_refresh_at TEXT,
  last_refresh_error TEXT DEFAULT '',
  updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS v14_connection_resources(
  id TEXT PRIMARY KEY,
  connection_id TEXT NOT NULL,
  resource_type TEXT NOT NULL,
  external_id TEXT NOT NULL,
  display_name TEXT NOT NULL DEFAULT '',
  parent_external_id TEXT DEFAULT '',
  selected INTEGER NOT NULL DEFAULT 0,
  is_default INTEGER NOT NULL DEFAULT 0,
  metadata_json TEXT NOT NULL DEFAULT '{}',
  synced_at TEXT DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(connection_id,resource_type,external_id)
);
CREATE INDEX IF NOT EXISTS v14_resources_connection ON v14_connection_resources(connection_id,resource_type,selected);
CREATE TABLE IF NOT EXISTS v14_sync_cursors(
  connection_id TEXT NOT NULL,
  object_type TEXT NOT NULL,
  cursor_value TEXT DEFAULT '',
  watermark TEXT DEFAULT '',
  updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY(connection_id,object_type)
);
CREATE TABLE IF NOT EXISTS v14_data_authority(
  entity_type TEXT PRIMARY KEY,
  authority TEXT NOT NULL,
  conflict_policy TEXT NOT NULL,
  explanation TEXT NOT NULL DEFAULT '',
  updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS v14_connection_health(
  id TEXT PRIMARY KEY,
  connection_id TEXT NOT NULL,
  severity TEXT NOT NULL DEFAULT 'Info',
  code TEXT NOT NULL,
  summary TEXT NOT NULL,
  owner_action TEXT DEFAULT '',
  technical_detail TEXT DEFAULT '',
  status TEXT NOT NULL DEFAULT 'Open',
  checked_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS v14_health_connection ON v14_connection_health(connection_id,status,checked_at);
CREATE TABLE IF NOT EXISTS v14_connection_routes(
  scope_type TEXT NOT NULL DEFAULT 'workspace',
  scope_key TEXT NOT NULL DEFAULT 'default',
  channel TEXT NOT NULL,
  connection_id TEXT NOT NULL,
  resource_type TEXT DEFAULT '',
  resource_external_id TEXT DEFAULT '',
  updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY(scope_type,scope_key,channel)
);
CREATE INDEX IF NOT EXISTS v14_routes_connection ON v14_connection_routes(connection_id,channel);
CREATE TABLE IF NOT EXISTS v14_authority_decisions(
  id TEXT PRIMARY KEY,
  entity_type TEXT NOT NULL,
  field_name TEXT DEFAULT '',
  provider TEXT DEFAULT '',
  connection_id TEXT DEFAULT '',
  allowed INTEGER NOT NULL DEFAULT 0,
  reason TEXT NOT NULL,
  object_id TEXT DEFAULT '',
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS v14_authority_decisions_entity ON v14_authority_decisions(entity_type,created_at);
CREATE TABLE IF NOT EXISTS v14_paid_campaigns(
  id TEXT PRIMARY KEY,
  unified_campaign_id TEXT NOT NULL,
  channel TEXT NOT NULL,
  connection_id TEXT NOT NULL,
  provider TEXT NOT NULL,
  name TEXT NOT NULL,
  objective TEXT NOT NULL DEFAULT '',
  daily_budget REAL NOT NULL,
  currency TEXT NOT NULL,
  countries_json TEXT NOT NULL DEFAULT '[]',
  provider_campaign_id TEXT DEFAULT '',
  provider_budget_id TEXT DEFAULT '',
  provider_adset_id TEXT DEFAULT '',
  provider_status TEXT NOT NULL DEFAULT 'Draft',
  targeting_status TEXT NOT NULL DEFAULT 'Recorded for review',
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS v14_paid_campaigns_unified ON v14_paid_campaigns(unified_campaign_id,channel,created_at);
'''

# The application/operator creates these provider apps once. Business users never need
# to know the fields below. Environment variables override local encrypted settings.
PROVIDER_SPECS: dict[str, dict[str, Any]] = {
    'google': {
        'label': 'Google',
        'client_id_env': 'CRM_GOOGLE_OAUTH_CLIENT_ID',
        'client_secret_env': 'CRM_GOOGLE_OAUTH_CLIENT_SECRET',
        'extra_secret_envs': {'developer_token': 'CRM_GOOGLE_ADS_DEVELOPER_TOKEN'},
        'extra_config_envs': {},
    },
    'meta': {
        'label': 'Meta',
        'client_id_env': 'CRM_META_APP_ID',
        'client_secret_env': 'CRM_META_APP_SECRET',
        'extra_secret_envs': {},
        'extra_config_envs': {
            'graph_version': 'CRM_META_GRAPH_VERSION',
            'login_config_id': 'CRM_META_LOGIN_CONFIG_ID',
            'whatsapp_config_id': 'CRM_WHATSAPP_EMBEDDED_SIGNUP_CONFIG_ID',
        },
    },
    'shopify': {
        'label': 'Shopify app',
        'client_id_env': 'CRM_SHOPIFY_CLIENT_ID',
        'client_secret_env': 'CRM_SHOPIFY_CLIENT_SECRET',
        'extra_secret_envs': {},
        'extra_config_envs': {'scopes': 'CRM_SHOPIFY_SCOPES'},
    },
    'wix': {
        'label': 'Wix app',
        'client_id_env': 'CRM_WIX_APP_ID',
        'client_secret_env': 'CRM_WIX_APP_SECRET',
        'extra_secret_envs': {},
        'extra_config_envs': {'install_url': 'CRM_WIX_INSTALL_URL'},
    },
    'microsoft': {
        'label': 'Microsoft 365',
        'client_id_env': 'CRM_MICROSOFT_CLIENT_ID',
        'client_secret_env': 'CRM_MICROSOFT_CLIENT_SECRET',
        'extra_secret_envs': {},
        'extra_config_envs': {'tenant': 'CRM_MICROSOFT_TENANT'},
    },
}

GOOGLE_SERVICE_SCOPES = {
    'ads': 'https://www.googleapis.com/auth/adwords',
    'analytics': 'https://www.googleapis.com/auth/analytics.readonly',
    'search_console': 'https://www.googleapis.com/auth/webmasters.readonly',
    'merchant': 'https://www.googleapis.com/auth/content',
    'youtube': 'https://www.googleapis.com/auth/youtube.readonly',
    'gmail': 'https://www.googleapis.com/auth/gmail.readonly',
    'calendar': 'https://www.googleapis.com/auth/calendar.readonly',
    'business_profile': 'https://www.googleapis.com/auth/business.manage',
}
GOOGLE_SERVICE_LABELS = {
    'ads': 'Google Ads', 'analytics': 'Google Analytics 4', 'search_console': 'Search Console',
    'merchant': 'Merchant Center', 'youtube': 'YouTube', 'gmail': 'Gmail mailbox',
    'calendar': 'Google Calendar', 'business_profile': 'Google Business Profile',
}
META_SERVICE_SCOPES = {
    'social': ['pages_show_list','pages_read_engagement','pages_manage_posts','instagram_basic','instagram_content_publish'],
    # ads_management is required for reviewed write operations. Read-only reporting
    # continues to work when Meta grants only ads_read, but the UI will not expose a
    # create control until the granted scope set contains ads_management.
    'ads': ['ads_read','ads_management','business_management'],
    'leads': ['leads_retrieval','pages_show_list'],
}
MICROSOFT_SERVICE_SCOPES = {
    'mail_read': 'Mail.Read',
    'mail_send': 'Mail.Send',
}

V14_BUSINESS_CONNECTORS = {
    'shopify': {
        'label': 'Shopify', 'category': 'Commerce', 'provider': 'Shopify', 'provider_key': 'shopify',
        'auth': 'oauth', 'implemented': True, 'login_first': True,
        'help': 'Connect your Shopify store by signing in and approving access. No Admin API token is requested from the business owner.',
        'capabilities': ['test','sync_products','sync_customers','sync_orders','push_product_draft','register_webhooks','receive_webhooks'],
    },
    'wix': {
        'label': 'Wix', 'category': 'Commerce', 'provider': 'Wix', 'provider_key': 'wix',
        'auth': 'oauth_app_instance', 'implemented': True, 'login_first': True,
        'help': 'Install and authorise the Commerce Business OS Wix app. The owner never pastes Wix access tokens; Wix returns a signed app instance which the OS verifies before syncing.',
        'capabilities': ['test','sync_products','sync_customers','sync_orders','sync_inventory','push_product_draft'],
    },
    'meta_business': {
        'label': 'Facebook, Instagram & Meta Ads', 'category': 'Social & Advertising', 'provider': 'Meta', 'provider_key': 'meta',
        'auth': 'oauth', 'implemented': True, 'login_first': True,
        'help': 'Sign in with Meta, then choose the Business Portfolio, Facebook Page, Instagram Professional account and ad account you want this workspace to use.',
        'capabilities': ['test','sync_pages','sync_social_accounts','sync_campaigns','sync_insights','publish_instagram_image','publish_facebook_image','create_paid_campaign_paused'],
    },
    'google_account': {
        'label': 'Google', 'category': 'Google ecosystem', 'provider': 'Google', 'provider_key': 'google',
        'auth': 'oauth', 'implemented': True, 'login_first': True,
        'help': 'Sign in with Google once and choose only the services you need: Ads, Analytics, Merchant Center, Search Console, YouTube, Gmail, Calendar or Business Profile.',
        'capabilities': ['test','sync_google_resources','sync_ads','sync_ga4','sync_search_console','sync_merchant','sync_youtube','sync_gmail','sync_calendar','sync_business_profile','create_paid_campaign_paused'],
    },
    'microsoft_mailbox': {
        'label': 'Microsoft 365 / Outlook mailbox', 'category': 'Communication', 'provider': 'Microsoft', 'provider_key': 'microsoft',
        'auth': 'oauth', 'implemented': True, 'login_first': True,
        'help': 'Sign in with Microsoft to connect a business mailbox. Mailbox access is separate from marketing-email sending infrastructure.',
        'capabilities': ['test','sync_mailbox','send_mail'],
    },
    'whatsapp_cloud': {
        'label': 'WhatsApp Business', 'category': 'Communication', 'provider': 'Meta', 'provider_key': 'meta',
        'auth': 'embedded_signup', 'implemented': True, 'login_first': True,
        'help': 'Connect through Meta Embedded Signup where the platform app is approved. The owner should not paste a system-user token.',
        'capabilities': ['test','sync_templates','send_template','receive_messages','receive_status_webhooks'],
    },
    'resend': {
        'label': 'Marketing email / Resend', 'category': 'Communication', 'provider': 'Resend', 'provider_key': '',
        'auth': 'api_key', 'implemented': True, 'login_first': False,
        'help': 'Marketing email transport. Resend currently requires provider/API configuration; keep this in Advanced setup rather than asking ordinary staff for OAuth credentials.',
        'capabilities': ['test','sync_domains','domain_create','domain_verify','send_email','register_webhook','receive_webhook'],
    },
    'stripe': {
        'label': 'Stripe', 'category': 'Payments', 'provider': 'Stripe', 'provider_key': '',
        'auth': 'api_key', 'implemented': True, 'login_first': False,
        'help': 'Payment reconciliation is available with a restricted key. Full payment/refund operations remain deliberately disabled.',
        'capabilities': ['test','sync_payments'],
    },
}

# Informational entries are shown only as planned; no fake connect action is rendered.
V14_PLANNED = {
    'woocommerce': ('WooCommerce','Commerce'),
    'pinterest': ('Pinterest','Social & Advertising'),
    'tiktok': ('TikTok','Social & Advertising'),
    'sms': ('SMS','Communication'),
    'razorpay': ('Razorpay','Payments'),
    'paypal': ('PayPal','Payments'),
    'shipping': ('Shipping / courier','Logistics'),
    'accounting': ('Accounting','Business operations'),
    'cloud_storage': ('Cloud storage','Business operations'),
}

DATA_AUTHORITY_DEFAULTS = {
    'customer': ('Commerce Business OS', 'Identity-resolution merge; never overwrite explicit opt-outs.', 'The CRM is the unified customer intelligence record.'),
    'online_order': ('Connected commerce store', 'Provider order IDs are immutable; provider status wins for the provider-owned order.', 'Shopify/other store is authoritative for orders it creates.'),
    'product_content': ('Commerce Business OS', 'Generated/reviewed product copy and creative are mastered here until explicitly published.', 'The AI product engine owns generated content.'),
    'ad_performance': ('Advertising provider', 'Provider metrics are append/sync only; never fabricate missing spend or conversion values.', 'Meta/Google remain authoritative for their reporting.'),
    'marketing_permission': ('Commerce Business OS', 'Most restrictive verified permission wins on identity merge.', 'Consent and suppression must be enforced centrally.'),
    'inventory': ('Commerce Business OS', 'One inventory master at a time; external stock can take authority only after an explicit validated cutover.', 'Commerce Business OS is the safe default inventory authority until the owner selects a validated commerce store.'),
}


def uid(prefix: str) -> str:
    return prefix + '-' + secrets.token_hex(8).upper()


def _utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _iso_after(seconds: int | float | None) -> str | None:
    if not seconds:
        return None
    try:
        sec=max(1,int(seconds))
    except (TypeError,ValueError):
        return None
    return (_utc_now()+dt.timedelta(seconds=sec)).replace(microsecond=0).isoformat().replace('+00:00','Z')


def initialise() -> None:
    # V14 can be opened from retained/redirected routes before the full app bootstrap in
    # tests or recovery mode, so ensure the shared integration schema exists first.
    legacy.initialise()
    with m.connect() as con:
        con.executescript(V14_SCHEMA)
        for key,spec in PROVIDER_SPECS.items():
            con.execute('INSERT OR IGNORE INTO v14_provider_apps(provider_key,display_name) VALUES(?,?)',(key,spec['label']))
        # Bind OAuth state to the signed-in business user that initiated the flow.
        # This column is added defensively for early V14 workspaces created before the
        # user-binding hardening landed.
        if db_layer.USING_POSTGRES:
            cols={r['column_name'] for r in con.execute("SELECT column_name FROM information_schema.columns WHERE table_schema='public' AND table_name='v14_oauth_sessions'").fetchall()}
        else:
            cols={r['name'] for r in con.execute('PRAGMA table_info(v14_oauth_sessions)').fetchall()}
        if 'initiated_user_id' not in cols:
            con.execute("ALTER TABLE v14_oauth_sessions ADD COLUMN initiated_user_id TEXT DEFAULT ''")
        if db_layer.USING_POSTGRES:
            authority_cols={r['column_name'] for r in con.execute("SELECT column_name FROM information_schema.columns WHERE table_schema='public' AND table_name='v14_data_authority'").fetchall()}
        else:
            authority_cols={r['name'] for r in con.execute('PRAGMA table_info(v14_data_authority)').fetchall()}
        if 'authority_connection_id' not in authority_cols:
            con.execute("ALTER TABLE v14_data_authority ADD COLUMN authority_connection_id TEXT DEFAULT ''")
        for entity,(authority,policy,explanation) in DATA_AUTHORITY_DEFAULTS.items():
            con.execute('''INSERT INTO v14_data_authority(entity_type,authority,conflict_policy,explanation)
                           VALUES(?,?,?,?) ON CONFLICT(entity_type) DO NOTHING''',(entity,authority,policy,explanation))
        # V44: an installation without a selected store must still have one usable
        # inventory master. Empty legacy authority selections migrate to the internal CRM.
        con.execute("UPDATE v14_data_authority SET authority='Commerce Business OS',authority_connection_id='INTERNAL',conflict_policy=?,explanation=?,updated_at=CURRENT_TIMESTAMP WHERE entity_type='inventory' AND coalesce(authority_connection_id,'')=''",
                    (DATA_AUTHORITY_DEFAULTS['inventory'][1],DATA_AUTHORITY_DEFAULTS['inventory'][2]))
    patch_legacy_catalog()


def patch_legacy_catalog() -> None:
    # New login-first cards are first-class in V14. Legacy API-token connectors remain
    # readable for old workspaces but are hidden from the default business UX.
    for key,meta in V14_BUSINESS_CONNECTORS.items():
        legacy.CONNECTOR_CATALOG[key]=dict(meta)
    for key in ('meta_ads','meta_social','google_ads','google_business'):
        if key in legacy.CONNECTOR_CATALOG:
            legacy.CONNECTOR_CATALOG[key]['legacy']=True
            legacy.CONNECTOR_CATALOG[key]['help']='Legacy technical connection from an older workspace. Reconnect through the V14 login-first '+('Meta' if key.startswith('meta') else 'Google')+' connection when practical.'


def business_catalog() -> dict[str,dict[str,Any]]:
    out={k:dict(v) for k,v in V14_BUSINESS_CONNECTORS.items()}
    for key,(label,category) in V14_PLANNED.items():
        out[key]={'label':label,'category':category,'provider':label,'provider_key':'','auth':'planned','implemented':False,'login_first':False,'capabilities':[],'help':'Planned. No connection action is shown until a functional backend exists.'}
    return out


def _encrypt(value: str) -> bytes:
    return legacy._vault().encrypt(value.encode('utf-8'))


def _decrypt(value: bytes) -> str:
    try:return legacy._vault().decrypt(value).decode('utf-8')
    except Exception:raise ValueError('Saved platform credentials cannot be decrypted. Reconfigure the provider app.') from None


def _provider_secret_db(provider_key: str, secret_key: str) -> str:
    row=m.one('SELECT encrypted_value FROM v14_provider_secrets WHERE provider_key=? AND secret_key=?',(provider_key,secret_key))
    return _decrypt(row['encrypted_value']) if row else ''


def provider_secret(provider_key: str, secret_key: str) -> str:
    spec=PROVIDER_SPECS.get(provider_key) or {}
    if secret_key=='client_secret':
        env=spec.get('client_secret_env','')
    else:
        env=(spec.get('extra_secret_envs') or {}).get(secret_key,'')
    if env and os.environ.get(env,'').strip():return os.environ[env].strip()
    return _provider_secret_db(provider_key,secret_key)


def provider_app(provider_key: str) -> dict:
    spec=PROVIDER_SPECS.get(provider_key)
    if not spec:raise ValueError('Unknown provider application.')
    row=m.one('SELECT * FROM v14_provider_apps WHERE provider_key=?',(provider_key,)) or {'client_id':'','config_json':'{}','status':'Not configured'}
    cfg=json.loads(row.get('config_json') or '{}')
    env_client=os.environ.get(spec.get('client_id_env',''),'').strip()
    client_id=env_client or (row.get('client_id') or '')
    for key,env in (spec.get('extra_config_envs') or {}).items():
        if os.environ.get(env,'').strip():cfg[key]=os.environ[env].strip()
    if provider_key=='meta':cfg.setdefault('graph_version','v26.0')
    if provider_key=='microsoft':cfg.setdefault('tenant','common')
    if provider_key=='shopify':cfg.setdefault('scopes','read_products,write_products,read_customers,read_orders,read_inventory')
    if provider_key=='wix':cfg.setdefault('install_url','')
    secret=provider_secret(provider_key,'client_secret')
    missing=[]
    if not client_id:missing.append('client ID')
    if not secret:missing.append('client secret')
    return {'provider_key':provider_key,'label':spec['label'],'client_id':client_id,'config':cfg,'configured':not missing,'missing':missing,'source':'environment' if env_client or (spec.get('client_secret_env') and os.environ.get(spec['client_secret_env'],'').strip()) else 'encrypted local setup','status':'Configured' if not missing else 'Not configured'}


def configure_provider_app(provider_key: str, client_id: str, client_secret: str='', config: dict|None=None, extra_secrets: dict|None=None) -> None:
    if provider_key not in PROVIDER_SPECS:raise ValueError('Unknown provider application.')
    config=config or {};extra_secrets=extra_secrets or {}
    if rc.IS_PRODUCTION and (client_secret.strip() or any(str(v).strip() for v in extra_secrets.values())):
        raise ValueError('In production, provider client secrets must be supplied through the deployment secret manager/environment, not a browser form.')
    with m.connect() as con:
        con.execute('''INSERT INTO v14_provider_apps(provider_key,display_name,client_id,config_json,status)
                       VALUES(?,?,?,?,?) ON CONFLICT(provider_key) DO UPDATE SET client_id=excluded.client_id,config_json=excluded.config_json,status=excluded.status,updated_at=CURRENT_TIMESTAMP''',
                    (provider_key,PROVIDER_SPECS[provider_key]['label'],client_id.strip(),json.dumps(config),'Configured' if client_id.strip() else 'Not configured'))
    payload={'client_secret':client_secret}|extra_secrets
    for k,v in payload.items():
        if not str(v or '').strip():continue
        raw=str(v).strip();hint='…'+raw[-4:] if len(raw)>=4 else 'saved'
        with m.connect() as con:
            con.execute('''INSERT INTO v14_provider_secrets(provider_key,secret_key,encrypted_value,hint)
                           VALUES(?,?,?,?) ON CONFLICT(provider_key,secret_key) DO UPDATE SET encrypted_value=excluded.encrypted_value,hint=excluded.hint,updated_at=CURRENT_TIMESTAMP''',
                        (provider_key,k,_encrypt(raw),hint))
    m.audit('integration.provider_app_configured',provider_key,'Platform/operator provider application updated.')


def provider_hints(provider_key: str) -> dict[str,str]:
    return {r['secret_key']:r['hint'] for r in m.rows('SELECT secret_key,hint FROM v14_provider_secrets WHERE provider_key=?',(provider_key,))}


def provider_callback_urls(base_url: str) -> dict[str,str]:
    base=base_url.rstrip('/')
    return {
        'google': base+'/oauth/v14/google/callback',
        'meta': base+'/oauth/v14/meta/callback',
        'shopify': base+'/oauth/v14/shopify/callback',
        'wix': base+'/oauth/v14/wix/callback',
        'microsoft': base+'/oauth/v14/microsoft/callback',
        'whatsapp': base+'/integrations/v14/whatsapp/embedded/complete',
    }


def _pkce_pair() -> tuple[str,str]:
    verifier=secrets.token_urlsafe(64)
    challenge=base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
    return verifier,challenge


def _save_oauth_session(state: str, provider: str, connector: str, cid: str, redirect_uri: str, scopes: list[str], context: dict, verifier: str='', initiated_user_id: str='') -> None:
    enc=_encrypt(verifier) if verifier else None
    with m.connect() as con:
        con.execute('INSERT INTO v14_oauth_sessions(state,provider_key,connector_key,connection_id,redirect_uri,requested_scopes_json,context_json,verifier_encrypted,initiated_user_id) VALUES(?,?,?,?,?,?,?,?,?)',
                    (state,provider,connector,cid,redirect_uri,json.dumps(scopes),json.dumps(context),enc,str(initiated_user_id or '')))


def _oauth_session(provider: str, state: str, current_user_id: str='') -> dict:
    row=m.one("SELECT * FROM v14_oauth_sessions WHERE state=? AND provider_key=? AND datetime(created_at)>=datetime('now','-20 minutes')",(state,provider))
    if not row:raise ValueError('This connection session expired or failed its security state check. Start Connect again.')
    initiator=str(row.get('initiated_user_id') or '')
    current=str(current_user_id or '')
    if initiator and current!=initiator:
        raise ValueError('This connection was started by a different signed-in user. Start Connect again from your own session.')
    row['scopes']=json.loads(row.get('requested_scopes_json') or '[]');row['context']=json.loads(row.get('context_json') or '{}')
    if row.get('verifier_encrypted'):row['verifier']=_decrypt(row['verifier_encrypted'])
    else:row['verifier']=''
    return row


def _new_connection(connector_key: str, label: str='', config: dict|None=None, cid: str='') -> str:
    meta=legacy.CONNECTOR_CATALOG.get(connector_key) or V14_BUSINESS_CONNECTORS.get(connector_key)
    if not meta or not meta.get('implemented'):raise ValueError('This integration does not have a working connection flow yet.')
    config=config or {}
    cid=cid or legacy.uid('CONN')
    with m.connect() as con:
        if con.execute('SELECT 1 FROM v10_connections WHERE id=?',(cid,)).fetchone():
            con.execute("UPDATE v10_connections SET connector_key=?,provider=?,label=?,status='Connection requires setup',auth_type=?,config_json=?,capabilities_json=?,last_error='',updated_at=CURRENT_TIMESTAMP WHERE id=?",
                        (connector_key,meta.get('provider',''),label or meta['label'],meta.get('auth','oauth'),json.dumps(config),json.dumps(meta.get('capabilities',[])),cid))
        else:
            con.execute('INSERT INTO v10_connections(id,connector_key,provider,label,status,auth_type,config_json,capabilities_json) VALUES(?,?,?,?,?,?,?,?)',
                        (cid,connector_key,meta.get('provider',''),label or meta['label'],'Connection requires setup',meta.get('auth','oauth'),json.dumps(config),json.dumps(meta.get('capabilities',[]))))
    return cid


def _google_scopes(services: list[str]) -> list[str]:
    scopes=['openid','email','profile']
    for service in services:
        scope=GOOGLE_SERVICE_SCOPES.get(service)
        if scope:scopes.append(scope)
    return list(dict.fromkeys(scopes))


def _meta_scopes(services: list[str]) -> list[str]:
    scopes=[]
    for service in services:
        scopes.extend(META_SERVICE_SCOPES.get(service,[]))
    return list(dict.fromkeys(scopes or META_SERVICE_SCOPES['social']))


def _microsoft_scopes(services: list[str]) -> list[str]:
    scopes=['openid','profile','offline_access','User.Read']
    for service in services:
        scope=MICROSOFT_SERVICE_SCOPES.get(service)
        if scope:scopes.append(scope)
    return list(dict.fromkeys(scopes))


def begin_oauth(connector_key: str, redirect_uri: str, options: dict|None=None, connection_id: str='') -> dict:
    initialise();options=options or {};initiated_user_id=str(options.get('_initiated_user_id') or '')
    if connector_key=='shopify':
        provider='shopify';app=provider_app(provider)
        if not app['configured']:raise ValueError('Shopify account login is not enabled yet. An administrator must configure the platform Shopify app once.')
        shop=re.sub(r'^https?://','',str(options.get('store_domain') or '').strip().lower()).strip('/')
        if not re.fullmatch(r'[a-z0-9][a-z0-9-]*\.myshopify\.com',shop):raise ValueError('Enter the permanent Shopify store address ending in .myshopify.com.')
        scopes=[x.strip() for x in str(app['config'].get('scopes') or '').split(',') if x.strip()]
        cid=_new_connection('shopify',options.get('label') or 'Shopify',{'store_domain':shop,'api_version':options.get('api_version') or '2026-07'},connection_id)
        state=secrets.token_urlsafe(32);_save_oauth_session(state,provider,'shopify',cid,redirect_uri,scopes,{'shop':shop},initiated_user_id=initiated_user_id)
        params={'client_id':app['client_id'],'scope':','.join(scopes),'redirect_uri':redirect_uri,'state':state}
        return {'connection_id':cid,'url':f'https://{shop}/admin/oauth/authorize?'+urllib.parse.urlencode(params),'state':state}
    if connector_key=='google_account':
        provider='google';app=provider_app(provider)
        if not app['configured']:raise ValueError('Google account login is not enabled yet. An administrator must configure the platform Google OAuth app once.')
        services=[x for x in (options.get('services') or []) if x in GOOGLE_SERVICE_SCOPES]
        if not services:raise ValueError('Choose at least one Google service.')
        scopes=_google_scopes(services);cid=_new_connection('google_account',options.get('label') or 'Google',{'services':services},connection_id)
        state=secrets.token_urlsafe(32);verifier,challenge=_pkce_pair();_save_oauth_session(state,provider,'google_account',cid,redirect_uri,scopes,{'services':services},verifier,initiated_user_id)
        params={'client_id':app['client_id'],'redirect_uri':redirect_uri,'response_type':'code','scope':' '.join(scopes),'access_type':'offline','include_granted_scopes':'true','prompt':'consent','state':state,'code_challenge':challenge,'code_challenge_method':'S256'}
        return {'connection_id':cid,'url':'https://accounts.google.com/o/oauth2/v2/auth?'+urllib.parse.urlencode(params),'state':state}
    if connector_key=='meta_business':
        provider='meta';app=provider_app(provider)
        if not app['configured']:raise ValueError('Meta account login is not enabled yet. An administrator must configure the platform Meta app once.')
        services=[x for x in (options.get('services') or ['social','ads']) if x in META_SERVICE_SCOPES]
        if not services:services=['social']
        scopes=_meta_scopes(services);cfg={'services':services,'graph_version':app['config'].get('graph_version') or 'v26.0'}
        cid=_new_connection('meta_business',options.get('label') or 'Meta',cfg,connection_id)
        state=secrets.token_urlsafe(32);_save_oauth_session(state,provider,'meta_business',cid,redirect_uri,scopes,{'services':services},initiated_user_id=initiated_user_id)
        version=cfg['graph_version'];params={'client_id':app['client_id'],'redirect_uri':redirect_uri,'state':state,'response_type':'code','scope':','.join(scopes)}
        if app['config'].get('login_config_id'):params['config_id']=app['config']['login_config_id']
        return {'connection_id':cid,'url':f'https://www.facebook.com/{version}/dialog/oauth?'+urllib.parse.urlencode(params),'state':state}
    if connector_key=='microsoft_mailbox':
        provider='microsoft';app=provider_app(provider)
        if not app['configured']:raise ValueError('Microsoft account login is not enabled yet. An administrator must configure the platform Microsoft app once.')
        services=[x for x in (options.get('services') or ['mail_read']) if x in MICROSOFT_SERVICE_SCOPES]
        scopes=_microsoft_scopes(services);cid=_new_connection('microsoft_mailbox',options.get('label') or 'Microsoft 365 mailbox',{'services':services},connection_id)
        state=secrets.token_urlsafe(32);verifier,challenge=_pkce_pair();_save_oauth_session(state,provider,'microsoft_mailbox',cid,redirect_uri,scopes,{'services':services},verifier,initiated_user_id)
        tenant=app['config'].get('tenant') or 'common';params={'client_id':app['client_id'],'response_type':'code','redirect_uri':redirect_uri,'response_mode':'query','scope':' '.join(scopes),'state':state,'code_challenge':challenge,'code_challenge_method':'S256'}
        return {'connection_id':cid,'url':f'https://login.microsoftonline.com/{urllib.parse.quote(tenant)}/oauth2/v2.0/authorize?'+urllib.parse.urlencode(params),'state':state}
    raise ValueError('This integration does not use the shared login flow.')


def _form_json(connection_id: str, operation: str, url: str, data: dict[str,Any], headers: dict|None=None) -> dict:
    raw=urllib.parse.urlencode({k:v for k,v in data.items() if v is not None}).encode()
    hdr={'Accept':'application/json','Content-Type':'application/x-www-form-urlencoded','User-Agent':'CommerceCRM-V14.1/1.0'};hdr.update(headers or {})
    started=time.monotonic()
    try:
        req=urllib.request.Request(url,data=raw,headers=hdr,method='POST')
        with urllib.request.urlopen(req,timeout=30) as resp:
            body=resp.read();legacy._api_log(connection_id,operation,'POST',url,resp.status,True,int((time.monotonic()-started)*1000))
            return json.loads(body.decode()) if body else {}
    except urllib.error.HTTPError as exc:
        try:detail=exc.read(4000).decode('utf-8','replace')
        except Exception:detail=''
        detail=re.sub(r'(?i)(access[_-]?token|refresh[_-]?token|client[_-]?secret|api[_-]?key|authorization(?:[_-]?code)?)["\':= ]+["\']?[^,}"\'\s]+',r'\1=[redacted]',detail)
        legacy._api_log(connection_id,operation,'POST',url,exc.code,False,int((time.monotonic()-started)*1000),'HTTPError',detail[:900])
        raise ValueError(f'{operation} was rejected by the provider. Reconnect the account or review the platform app setup.') from None
    except (urllib.error.URLError,TimeoutError,OSError) as exc:
        legacy._api_log(connection_id,operation,'POST',url,None,False,int((time.monotonic()-started)*1000),type(exc).__name__,str(exc)[:900])
        raise ValueError(f'{operation} could not reach the provider. Try again shortly.') from None


def _set_token_meta(connection_id: str, out: dict, scopes: list[str]|str|None=None) -> None:
    granted=scopes
    if granted is None:granted=out.get('scope') or out.get('scopes') or []
    if isinstance(granted,str):granted=[x for x in re.split(r'[ ,]+',granted) if x]
    expires=_iso_after(out.get('expires_in'))
    refresh_exp=_iso_after(out.get('refresh_token_expires_in'))
    with m.connect() as con:
        con.execute('''INSERT INTO v14_token_metadata(connection_id,token_type,expires_at,refresh_expires_at,granted_scopes_json,last_refresh_at,last_refresh_error)
                       VALUES(?,?,?,?,?,CURRENT_TIMESTAMP,'') ON CONFLICT(connection_id) DO UPDATE SET token_type=excluded.token_type,expires_at=excluded.expires_at,refresh_expires_at=excluded.refresh_expires_at,granted_scopes_json=excluded.granted_scopes_json,last_refresh_at=CURRENT_TIMESTAMP,last_refresh_error='',updated_at=CURRENT_TIMESTAMP''',
                    (connection_id,str(out.get('token_type') or 'Bearer'),expires,refresh_exp,json.dumps(list(granted or []))))


def token_metadata(connection_id: str) -> dict:
    row=m.one('SELECT * FROM v14_token_metadata WHERE connection_id=?',(connection_id,)) or {}
    if row:row['granted_scopes']=json.loads(row.get('granted_scopes_json') or '[]')
    return row


def _expires_soon(value: str|None, seconds: int=180) -> bool:
    if not value:return False
    try:
        parsed=dt.datetime.fromisoformat(value.replace('Z','+00:00'))
        if parsed.tzinfo is None:parsed=parsed.replace(tzinfo=dt.timezone.utc)
        return parsed <= _utc_now()+dt.timedelta(seconds=seconds)
    except Exception:return False


def _store_access_tokens(connection_id: str, out: dict, scopes: list[str]|str|None=None) -> None:
    if out.get('access_token'):legacy.store_secret(connection_id,'access_token',str(out['access_token']))
    if out.get('refresh_token'):legacy.store_secret(connection_id,'refresh_token',str(out['refresh_token']))
    _set_token_meta(connection_id,out,scopes)


def _shopify_hmac_valid(raw_query: str, secret: str) -> bool:
    pairs=urllib.parse.parse_qsl(raw_query,keep_blank_values=True)
    provided='';clean=[]
    for k,v in pairs:
        if k=='hmac':provided=v
        elif k!='signature':clean.append((k,v))
    if not provided:return False
    message='&'.join(f'{k}={v}' for k,v in sorted(clean))
    digest=hmac.new(secret.encode(),message.encode(),hashlib.sha256).hexdigest()
    return hmac.compare_digest(digest,provided)


def complete_oauth(provider: str, state: str, code: str, raw_query: str='', current_user_id: str='') -> str:
    session=_oauth_session(provider,state,current_user_id);cid=session['connection_id'];app=provider_app(provider);secret=provider_secret(provider,'client_secret')
    # OAuth state is single-use. Consume it before token exchange so a failed/replayed
    # callback cannot reuse the same browser authorization session.
    with m.connect() as con:con.execute('DELETE FROM v14_oauth_sessions WHERE state=?',(state,))
    if not app['configured']:raise ValueError('The platform provider app is no longer configured. Ask an administrator to restore it.')
    if provider=='google':
        out=_form_json(cid,'Google OAuth code exchange','https://oauth2.googleapis.com/token',{'code':code,'client_id':app['client_id'],'client_secret':secret,'redirect_uri':session['redirect_uri'],'grant_type':'authorization_code','code_verifier':session.get('verifier') or None})
        _store_access_tokens(cid,out,session['scopes']);discover_google_resources(cid);auto_select_unambiguous_resources(cid)
    elif provider=='meta':
        c=legacy.connection(cid);version=c['config'].get('graph_version') or app['config'].get('graph_version') or 'v26.0'
        url=f'https://graph.facebook.com/{version}/oauth/access_token?'+urllib.parse.urlencode({'client_id':app['client_id'],'client_secret':secret,'redirect_uri':session['redirect_uri'],'code':code})
        try:
            out=legacy.api_json(cid,'Meta OAuth code exchange',url,'GET')
        except ValueError:raise ValueError('Meta did not complete the login. Check the platform app redirect URI and permissions, then reconnect.') from None
        if not out.get('access_token'):raise ValueError('Meta did not return an access token.')
        # Where supported, exchange for a longer-lived user token. If Meta rejects the
        # exchange, retain the valid short-lived token and surface expiry in health.
        token=str(out['access_token'])
        try:
            long_url=f'https://graph.facebook.com/{version}/oauth/access_token?'+urllib.parse.urlencode({'grant_type':'fb_exchange_token','client_id':app['client_id'],'client_secret':secret,'fb_exchange_token':token})
            long=legacy.api_json(cid,'Meta long-lived token exchange',long_url,'GET',retries=0)
            if long.get('access_token'):out=long;token=str(long['access_token'])
        except ValueError:pass
        out['access_token']=token;_store_access_tokens(cid,out,session['scopes']);discover_meta_resources(cid);auto_select_unambiguous_resources(cid)
    elif provider=='microsoft':
        tenant=app['config'].get('tenant') or 'common'
        out=_form_json(cid,'Microsoft OAuth code exchange',f'https://login.microsoftonline.com/{urllib.parse.quote(tenant)}/oauth2/v2.0/token',{'client_id':app['client_id'],'client_secret':secret,'code':code,'redirect_uri':session['redirect_uri'],'grant_type':'authorization_code','scope':' '.join(session['scopes']),'code_verifier':session.get('verifier') or None})
        _store_access_tokens(cid,out,session['scopes']);discover_microsoft_resources(cid);auto_select_unambiguous_resources(cid)
    elif provider=='shopify':
        if not raw_query:raise ValueError('Shopify callback query is missing.')
        if not _shopify_hmac_valid(raw_query,secret):raise ValueError('Shopify callback signature did not verify. Start Connect Shopify again.')
        shop=(session['context'].get('shop') or '').lower();pairs=dict(urllib.parse.parse_qsl(raw_query,keep_blank_values=True));returned=(pairs.get('shop') or '').lower()
        if shop!=returned:raise ValueError('Shopify returned a different store than the one that started this connection.')
        out=_form_json(cid,'Shopify OAuth code exchange',f'https://{shop}/admin/oauth/access_token',{'client_id':app['client_id'],'client_secret':secret,'code':code,'expiring':'1'})
        if not out.get('access_token'):raise ValueError('Shopify did not return an access token.')
        _store_access_tokens(cid,out,out.get('scope') or session['scopes'])
    else:raise ValueError('Unsupported OAuth provider.')
    test_connection(cid)
    return cid


def _resource_upsert(connection_id: str, resource_type: str, external_id: str, display_name: str='', parent: str='', metadata: dict|None=None) -> None:
    if not external_id:return
    rid=hashlib.sha256(f'{connection_id}|{resource_type}|{external_id}'.encode()).hexdigest()[:24]
    with m.connect() as con:
        con.execute('''INSERT INTO v14_connection_resources(id,connection_id,resource_type,external_id,display_name,parent_external_id,metadata_json)
                       VALUES(?,?,?,?,?,?,?) ON CONFLICT(connection_id,resource_type,external_id) DO UPDATE SET display_name=excluded.display_name,parent_external_id=excluded.parent_external_id,metadata_json=excluded.metadata_json,synced_at=CURRENT_TIMESTAMP''',
                    ('RES-'+rid.upper(),connection_id,resource_type,str(external_id),str(display_name or external_id)[:300],str(parent or '')[:200],json.dumps(metadata or {},ensure_ascii=False)))


def resources(connection_id: str, resource_type: str='') -> list[dict]:
    sql='SELECT * FROM v14_connection_resources WHERE connection_id=?';args=[connection_id]
    if resource_type:sql+=' AND resource_type=?';args.append(resource_type)
    sql+=' ORDER BY resource_type,selected DESC,display_name COLLATE NOCASE'
    out=m.rows(sql,tuple(args))
    for r in out:r['metadata']=json.loads(r.get('metadata_json') or '{}')
    return out


def select_resources(connection_id: str, selections: dict[str,str|list[str]]) -> None:
    c=legacy.connection(connection_id);available=resources(connection_id)
    valid={(r['resource_type'],r['external_id']) for r in available}
    with m.connect() as con:
        for typ,val in selections.items():
            values=[val] if isinstance(val,str) else list(val or [])
            values=[str(x) for x in values if str(x)]
            for ext in values:
                if (typ,ext) not in valid:raise ValueError('Choose only an account returned by the connected provider.')
            con.execute('UPDATE v14_connection_resources SET selected=0,is_default=0 WHERE connection_id=? AND resource_type=?',(connection_id,typ))
            for i,ext in enumerate(values):con.execute('UPDATE v14_connection_resources SET selected=1,is_default=? WHERE connection_id=? AND resource_type=? AND external_id=?',(1 if i==0 else 0,connection_id,typ,ext))
    cfg=c['config']
    mapping={'facebook_page':'page_id','instagram_account':'instagram_user_id','meta_ad_account':'ad_account_id','meta_business':'business_id','google_ads_customer':'customer_id','ga4_property':'ga4_property_id','search_console_site':'search_console_site','merchant_account':'merchant_account_id','youtube_channel':'youtube_channel_id','calendar':'calendar_id','business_profile_account':'business_profile_account_id'}
    for typ,key in mapping.items():
        vals=[r['external_id'] for r in resources(connection_id,typ) if r['selected']]
        if vals:cfg[key]=vals[0]
        else:cfg.pop(key,None)
    with m.connect() as con:con.execute('UPDATE v10_connections SET config_json=?,updated_at=CURRENT_TIMESTAMP WHERE id=?',(json.dumps(cfg),connection_id))
    m.audit('integration.resources_selected',connection_id,json.dumps({k:v for k,v in selections.items()}))


def auto_select_unambiguous_resources(connection_id: str) -> dict:
    """Select a provider resource only when there is exactly one valid choice.

    This removes unnecessary setup clicks without guessing when multiple stores/pages/accounts
    exist. Existing selections are preserved.
    """
    chosen=[];selections={}
    for req in account_selection_requirements(connection_id):
        if req.get('selected'):
            continue
        rows=req.get('resources') or []
        if len(rows)==1:
            selections[req['resource_type']]=rows[0]['external_id']
            chosen.append({'resource_type':req['resource_type'],'external_id':rows[0]['external_id'],'display_name':rows[0]['display_name']})
    if selections:
        select_resources(connection_id,selections)
        m.audit('integration.resources_auto_selected',connection_id,json.dumps(chosen,ensure_ascii=False))
    return {'count':len(chosen),'selected':chosen}


def _bearer(connection_id: str, token: str) -> dict[str,str]:
    return {'Authorization':'Bearer '+token}


def access_token(connection_id: str, provider: str) -> str:
    c=legacy.connection(connection_id);meta=token_metadata(connection_id);current=legacy.load_secret(connection_id,'access_token')
    if current and not _expires_soon(meta.get('expires_at'),180):return current
    refresh=legacy.load_secret(connection_id,'refresh_token')
    if not refresh:
        if current and not meta.get('expires_at'):return current
        with m.connect() as con:con.execute("UPDATE v10_connections SET status='Reconnect required',last_error='The account session expired. Reconnect the provider.',updated_at=CURRENT_TIMESTAMP WHERE id=?",(connection_id,))
        raise ValueError('Your '+provider.title()+' connection has expired. Reconnect the account.')
    app=provider_app(provider);secret=provider_secret(provider,'client_secret')
    try:
        if provider=='google':
            out=_form_json(connection_id,'Google OAuth refresh','https://oauth2.googleapis.com/token',{'grant_type':'refresh_token','client_id':app['client_id'],'client_secret':secret,'refresh_token':refresh})
        elif provider=='microsoft':
            tenant=app['config'].get('tenant') or 'common';scopes=meta.get('granted_scopes') or _microsoft_scopes(c['config'].get('services') or ['mail_read'])
            out=_form_json(connection_id,'Microsoft OAuth refresh',f'https://login.microsoftonline.com/{urllib.parse.quote(tenant)}/oauth2/v2.0/token',{'client_id':app['client_id'],'client_secret':secret,'grant_type':'refresh_token','refresh_token':refresh,'scope':' '.join(scopes)})
        elif provider=='shopify':
            shop=c['config'].get('store_domain','');out=_form_json(connection_id,'Shopify OAuth refresh',f'https://{shop}/admin/oauth/access_token',{'client_id':app['client_id'],'client_secret':secret,'grant_type':'refresh_token','refresh_token':refresh})
        else:raise ValueError('This provider requires interactive reconnection when its token expires.')
        _store_access_tokens(connection_id,out,meta.get('granted_scopes') or [])
        return str(out.get('access_token') or legacy.load_secret(connection_id,'access_token'))
    except ValueError as exc:
        with m.connect() as con:
            con.execute("UPDATE v14_token_metadata SET last_refresh_error=?,updated_at=CURRENT_TIMESTAMP WHERE connection_id=?",(str(exc)[:1000],connection_id))
            con.execute("UPDATE v10_connections SET status='Reconnect required',last_error=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",(friendly_error(str(exc),provider),connection_id))
        raise ValueError(friendly_error(str(exc),provider)) from None


def google_access_token(c: dict) -> str:
    # Login-first V14 connection. Legacy Google connections continue to use their
    # own credentials so old workspaces remain recoverable.
    if c.get('connector_key')=='google_account':return access_token(c['id'],'google')
    return _legacy_google_access_token(c)


def shopify_graphql(c: dict, query: str, variables: dict|None=None, operation='Shopify API') -> dict:
    shop=re.sub(r'^https?://','',str(c['config'].get('store_domain','')).strip()).strip('/')
    if not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9-]*\.myshopify\.com',shop):raise ValueError('Reconnect Shopify and choose a valid store.')
    token=access_token(c['id'],'shopify') if c.get('connector_key')=='shopify' and m.one('SELECT 1 FROM v14_token_metadata WHERE connection_id=?',(c['id'],)) else legacy.load_secret(c['id'],'access_token')
    if not token:raise ValueError('Shopify is not authorised. Reconnect the store.')
    ver=c['config'].get('api_version') or '2026-07'
    data=legacy.api_json(c['id'],operation,f'https://{shop}/admin/api/{ver}/graphql.json','POST',{'X-Shopify-Access-Token':token},{'query':query,'variables':variables or {}})
    if data.get('errors'):raise ValueError(operation+' returned GraphQL errors: '+'; '.join(str(x.get('message','error')) for x in data['errors'][:3]))
    return data.get('data') or {}


def _google_request(c: dict, operation: str, url: str, method='GET', payload=None, headers: dict|None=None) -> Any:
    token=access_token(c['id'],'google');hdr={'Authorization':'Bearer '+token};hdr.update(headers or {})
    return legacy.api_json(c['id'],operation,url,method,hdr,payload)


def discover_google_resources(connection_id: str) -> dict:
    c=legacy.connection(connection_id);token=access_token(connection_id,'google');hdr={'Authorization':'Bearer '+token};services=c['config'].get('services') or []
    if isinstance(services,str):services=[x for x in services.split(',') if x]
    out={'warnings':[],'count':0}
    user=legacy.api_json(c['id'],'Read Google account identity','https://www.googleapis.com/oauth2/v2/userinfo','GET',hdr)
    _resource_upsert(connection_id,'google_identity',str(user.get('id') or user.get('email') or 'me'),user.get('email') or user.get('name') or 'Google account',metadata={k:user.get(k) for k in ['email','name','picture']})
    if 'ads' in services:
        dev=provider_secret('google','developer_token')
        if not dev:out['warnings'].append('Google Ads is selected, but the platform operator still needs to configure the Google Ads developer token.')
        else:
            try:
                d=legacy.api_json(c['id'],'Discover Google Ads accounts','https://googleads.googleapis.com/v25/customers:listAccessibleCustomers','GET',{'Authorization':'Bearer '+token,'developer-token':dev})
                for name in d.get('resourceNames') or []:
                    ext=name.split('/')[-1];_resource_upsert(connection_id,'google_ads_customer',ext,'Google Ads '+ext,metadata={'resource_name':name});out['count']+=1
            except ValueError as exc:out['warnings'].append(f'Google Ads account discovery: {exc}')
    if 'analytics' in services:
        try:
            page='';seen=0
            while seen<1000:
                url='https://analyticsadmin.googleapis.com/v1beta/accountSummaries?pageSize=200'+('&pageToken='+urllib.parse.quote(page) if page else '')
                d=legacy.api_json(c['id'],'Discover GA4 properties',url,'GET',hdr)
                for account in d.get('accountSummaries') or []:
                    for prop in account.get('propertySummaries') or []:
                        ext=str(prop.get('property') or '').split('/')[-1];_resource_upsert(connection_id,'ga4_property',ext,prop.get('displayName') or ext,parent=str(account.get('account') or ''),metadata={'account_name':account.get('displayName'),'property':prop});out['count']+=1
                page=str(d.get('nextPageToken') or '');seen+=200
                if not page:break
        except ValueError as exc:out['warnings'].append(f'Google Analytics discovery: {exc}')
    if 'search_console' in services:
        try:
            d=legacy.api_json(c['id'],'Discover Search Console properties','https://www.googleapis.com/webmasters/v3/sites','GET',hdr)
            for site in d.get('siteEntry') or []:_resource_upsert(connection_id,'search_console_site',site.get('siteUrl',''),site.get('siteUrl',''),metadata=site);out['count']+=1
        except ValueError as exc:out['warnings'].append(f'Search Console discovery: {exc}')
    if 'merchant' in services:
        try:
            page='';seen=0
            while seen<1000:
                url='https://merchantapi.googleapis.com/accounts/v1/accounts?pageSize=250'+('&pageToken='+urllib.parse.quote(page) if page else '')
                d=legacy.api_json(c['id'],'Discover Merchant Center accounts',url,'GET',hdr)
                for acct in d.get('accounts') or []:
                    name=str(acct.get('name') or '');ext=name.split('/')[-1];_resource_upsert(connection_id,'merchant_account',ext,acct.get('accountName') or acct.get('displayName') or ext,metadata=acct);out['count']+=1
                page=str(d.get('nextPageToken') or '');seen+=250
                if not page:break
        except ValueError as exc:out['warnings'].append(f'Merchant Center discovery: {exc}')
    if 'youtube' in services:
        try:
            d=legacy.api_json(c['id'],'Discover YouTube channels','https://www.googleapis.com/youtube/v3/channels?part=snippet&mine=true&maxResults=50','GET',hdr)
            for ch in d.get('items') or []:_resource_upsert(connection_id,'youtube_channel',ch.get('id',''),(ch.get('snippet') or {}).get('title') or ch.get('id',''),metadata=ch);out['count']+=1
        except ValueError as exc:out['warnings'].append(f'YouTube discovery: {exc}')
    if 'calendar' in services:
        try:
            d=legacy.api_json(c['id'],'Discover Google calendars','https://www.googleapis.com/calendar/v3/users/me/calendarList?maxResults=250','GET',hdr)
            for cal in d.get('items') or []:_resource_upsert(connection_id,'calendar',cal.get('id',''),cal.get('summary') or cal.get('id',''),metadata=cal);out['count']+=1
        except ValueError as exc:out['warnings'].append(f'Calendar discovery: {exc}')
    if 'business_profile' in services:
        try:
            d=legacy.api_json(c['id'],'Discover Business Profile accounts','https://mybusinessaccountmanagement.googleapis.com/v1/accounts','GET',hdr)
            for acct in d.get('accounts') or []:
                name=str(acct.get('name') or '');ext=name.split('/')[-1];_resource_upsert(connection_id,'business_profile_account',ext,acct.get('accountName') or ext,metadata=acct);out['count']+=1
        except ValueError as exc:out['warnings'].append(f'Business Profile discovery: {exc}')
    return {'identity':user,'services':services}|out


def discover_meta_resources(connection_id: str) -> dict:
    c=legacy.connection(connection_id);token=access_token(connection_id,'meta');version=c['config'].get('graph_version') or provider_app('meta')['config'].get('graph_version') or 'v26.0';hdr={'Authorization':'Bearer '+token};out={'warnings':[],'count':0}
    def get(path,fields,operation):
        sep='&' if '?' in path else '?';return legacy.api_json(c['id'],operation,f'https://graph.facebook.com/{version}/'+path+sep+urllib.parse.urlencode({'fields':fields,'limit':'200'}),'GET',hdr)
    user=get('me','id,name','Read Meta identity');_resource_upsert(connection_id,'meta_identity',user.get('id','me'),user.get('name') or 'Meta account',metadata=user)
    try:
        d=get('me/businesses','id,name,verification_status','Discover Meta Business portfolios')
        for b in d.get('data') or []:_resource_upsert(connection_id,'meta_business',b.get('id',''),b.get('name') or b.get('id',''),metadata=b);out['count']+=1
    except ValueError as exc:out['warnings'].append(f'Business Portfolio discovery: {exc}')
    try:
        d=get('me/accounts','id,name,instagram_business_account{id,username}','Discover Facebook Pages')
        for page in d.get('data') or []:
            clean={k:v for k,v in page.items() if k!='access_token'};_resource_upsert(connection_id,'facebook_page',page.get('id',''),page.get('name') or page.get('id',''),metadata=clean);out['count']+=1
            ig=page.get('instagram_business_account') or {}
            if ig:_resource_upsert(connection_id,'instagram_account',ig.get('id',''),('@'+str(ig.get('username'))) if ig.get('username') else ig.get('id',''),parent=page.get('id',''),metadata=ig);out['count']+=1
    except ValueError as exc:out['warnings'].append(f'Facebook / Instagram discovery: {exc}')
    try:
        d=get('me/adaccounts','id,name,account_status,currency,timezone_name','Discover Meta ad accounts')
        for a in d.get('data') or []:_resource_upsert(connection_id,'meta_ad_account',str(a.get('id') or '').removeprefix('act_'),a.get('name') or a.get('id',''),metadata=a);out['count']+=1
    except ValueError as exc:out['warnings'].append(f'Meta Ads discovery: {exc}')
    try:
        perm=legacy.api_json(c['id'],'Read Meta granted permissions',f'https://graph.facebook.com/{version}/me/permissions','GET',hdr)
        granted=[x.get('permission') for x in perm.get('data') or [] if x.get('status')=='granted']
        with m.connect() as con:con.execute('UPDATE v10_connections SET scopes_json=? WHERE id=?',(json.dumps(granted),connection_id))
    except ValueError as exc:out['warnings'].append(f'Permission inspection: {exc}')
    return {'identity':user}|out


def discover_microsoft_resources(connection_id: str) -> dict:
    c=legacy.connection(connection_id);token=access_token(connection_id,'microsoft');user=legacy.api_json(c['id'],'Read Microsoft mailbox identity','https://graph.microsoft.com/v1.0/me?$select=id,displayName,mail,userPrincipalName','GET',{'Authorization':'Bearer '+token})
    email=user.get('mail') or user.get('userPrincipalName') or '';_resource_upsert(connection_id,'microsoft_mailbox',user.get('id') or email,email or user.get('displayName') or 'Microsoft mailbox',metadata=user)
    return {'identity':user,'count':1}


def _connection_identity_name(c: dict) -> tuple[str,str]:
    rows=resources(c['id'])
    for typ in ('google_identity','meta_identity','microsoft_mailbox'):
        r=next((x for x in rows if x['resource_type']==typ),None)
        if r:return r['display_name'],r['external_id']
    return c.get('label',''),c.get('external_account_id','')


def _waba_subscribed_app_ids(payload: dict) -> set[str]:
    ids=set()
    for item in (payload or {}).get('data') or []:
        if not isinstance(item,dict):continue
        direct=item.get('id')
        nested=(item.get('whatsapp_business_api_data') or {}).get('id') if isinstance(item.get('whatsapp_business_api_data'),dict) else None
        if direct:ids.add(str(direct))
        if nested:ids.add(str(nested))
    return ids


def begin_wix_install(redirect_uri: str, label: str='Wix', connection_id: str='', initiated_user_id: str='') -> dict:
    """Create a pending Wix business connection and return the configured install URL.

    Wix app credentials/install URL are operator configuration. The owner only clicks
    Connect. Wix must be configured to return to provider_callback_urls()['wix'] with
    a signedInstance query parameter.
    """
    initialise();app=provider_app('wix')
    if not app['configured']:raise ValueError('Wix login is not enabled yet. An administrator must configure the Wix app once.')
    install_url=str(app['config'].get('install_url') or '').strip()
    if not install_url.startswith('https://'):raise ValueError('Wix needs a valid HTTPS app install URL in Advanced Platform Setup.')
    cid=_new_connection('wix',label or 'Wix',{'install_callback':redirect_uri,'initiated_user_id':str(initiated_user_id or '')},connection_id)
    # Never call this connected before the signed instance and a live token validation.
    with m.connect() as con:con.execute("UPDATE v10_connections SET status='Connection requires setup',last_error='' WHERE id=?",(cid,))
    return {'connection_id':cid,'url':install_url}


def complete_wix_install(signed_instance: str, connection_id: str='', current_user_id: str='') -> str:
    initialise();app=provider_app('wix');secret=provider_secret('wix','client_secret')
    if not app['configured']:raise ValueError('Wix platform setup is incomplete.')
    import wix_v50 as wix
    payload=wix.decode_signed_instance(signed_instance,secret);instance_id=str(payload['instanceId'])
    # Prefer the explicit pending row. Otherwise reuse an existing instance mapping or
    # the single pending Wix connection. Reject ambiguity rather than attaching a site
    # to an arbitrary business account.
    candidates=legacy.connections('wix')
    cid=str(connection_id or '')
    if not cid:
        for c in candidates:
            if str((c.get('config') or {}).get('instance_id') or '')==instance_id:cid=c['id'];break
    if not cid:
        pending=[c for c in candidates if c.get('status')!='Connected' and not (c.get('config') or {}).get('instance_id')]
        if len(pending)==1:cid=pending[0]['id']
        elif len(pending)>1:raise ValueError('More than one Wix connection is awaiting installation. Open the intended Wix connection and reconnect it.')
        else:cid=_new_connection('wix','Wix',{})
    c=legacy.connection(cid);cfg=dict(c.get('config') or {})
    initiated=str(cfg.get('initiated_user_id') or '')
    if initiated and current_user_id and initiated!=str(current_user_id):raise ValueError('This Wix connection was started by another signed-in user. Start Connect Wix again.')
    cfg.update({'instance_id':instance_id,'site_owner_id':str(payload.get('siteOwnerId') or ''),'wix_user_id':str(payload.get('uid') or ''),'signed_instance_verified':True})
    with m.connect() as con:con.execute("UPDATE v10_connections SET config_json=?,status='Connection requires setup',updated_at=CURRENT_TIMESTAMP WHERE id=?",(json.dumps(cfg),cid))
    test_connection(cid)
    try:sync_connection(cid)
    except Exception as exc:
        # Auth is proven but sync isn't. Do not pretend the connection is healthy.
        with m.connect() as con:con.execute("UPDATE v10_connections SET status='Needs Attention',last_error=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",(friendly_error(str(exc),'Wix')[:1200],cid))
    return cid

def test_connection(connection_id: str) -> dict:
    c=legacy.connection(connection_id);kind=c['connector_key']
    try:
        if kind=='wix':
            import wix_v50 as wix
            app=provider_app('wix');secret=provider_secret('wix','client_secret');d=wix.token_info(connection_id,app,secret)
            if not bool(d.get('active',True)):raise ValueError('Wix returned an inactive access token. Reconnect Wix.')
            cfg=c.get('config') or {};instance=str(d.get('instanceId') or d.get('instance_id') or cfg.get('instance_id') or '')
            if cfg.get('instance_id') and instance and str(cfg.get('instance_id'))!=instance:raise ValueError('Wix validated a different app instance. Reconnect the intended site.')
            account='Wix site '+str(d.get('siteId') or d.get('site_id') or instance)
            external=str(d.get('siteId') or d.get('site_id') or instance);scopes=c.get('capabilities',[])
            cfg.update({'instance_id':instance or cfg.get('instance_id',''),'site_id':str(d.get('siteId') or d.get('site_id') or ''),'signed_instance_verified':bool(cfg.get('signed_instance_verified'))})
            with m.connect() as con:con.execute('UPDATE v10_connections SET config_json=? WHERE id=?',(json.dumps(cfg),connection_id))
        elif kind=='shopify':
            d=shopify_graphql(c,'query { shop { name email primaryDomain { url } currencyCode } }',operation='Test Shopify connection')['shop'];account=d.get('name') or c['config'].get('store_domain','');external=d.get('primaryDomain',{}).get('url','');scopes=token_metadata(connection_id).get('granted_scopes') or c.get('capabilities',[])
        elif kind=='google_account':
            token=access_token(connection_id,'google');d=legacy.api_json(c['id'],'Test Google login','https://www.googleapis.com/oauth2/v2/userinfo','GET',{'Authorization':'Bearer '+token});account=d.get('email') or d.get('name') or 'Google account';external=str(d.get('id') or account);scopes=token_metadata(connection_id).get('granted_scopes') or []
        elif kind=='meta_business':
            token=access_token(connection_id,'meta');ver=c['config'].get('graph_version') or 'v26.0';d=legacy.api_json(c['id'],'Test Meta login',f'https://graph.facebook.com/{ver}/me?fields=id,name','GET',{'Authorization':'Bearer '+token});account=d.get('name') or 'Meta account';external=d.get('id') or '';scopes=c.get('scopes') or token_metadata(connection_id).get('granted_scopes') or []
        elif kind=='microsoft_mailbox':
            token=access_token(connection_id,'microsoft');d=legacy.api_json(c['id'],'Test Microsoft login','https://graph.microsoft.com/v1.0/me?$select=id,displayName,mail,userPrincipalName','GET',{'Authorization':'Bearer '+token});account=d.get('mail') or d.get('userPrincipalName') or d.get('displayName') or 'Microsoft mailbox';external=d.get('id') or account;scopes=token_metadata(connection_id).get('granted_scopes') or []
        elif kind=='whatsapp_cloud':
            cfg=c['config'];phone=str(cfg.get('phone_number_id') or '');waba=str(cfg.get('waba_id') or '')
            if not phone or not waba:raise ValueError('WhatsApp onboarding is incomplete. Reconnect through Embedded Signup.')
            token=legacy.load_secret(connection_id,'access_token')
            if not token:raise ValueError('WhatsApp authorization is missing. Reconnect through Embedded Signup.')
            ver=cfg.get('graph_version') or 'v26.0';hdr={'Authorization':'Bearer '+token}
            d=legacy.api_json(c['id'],'Test WhatsApp phone',f'https://graph.facebook.com/{ver}/{phone}?fields=id,display_phone_number,verified_name,quality_rating','GET',hdr)
            subs=legacy.api_json(c['id'],'Verify WhatsApp WABA subscription',f'https://graph.facebook.com/{ver}/{waba}/subscribed_apps','GET',hdr)
            app_id=str(provider_app('meta').get('client_id') or '')
            subscribed=(app_id in _waba_subscribed_app_ids(subs)) if app_id else bool(_waba_subscribed_app_ids(subs))
            if not cfg.get('phone_registered'):raise ValueError('WhatsApp phone registration has not been confirmed. Complete WhatsApp setup again.')
            if not subscribed:raise ValueError('WhatsApp webhook subscription is not active for this business account. Complete WhatsApp setup again.')
            if not legacy._public_base_url():raise ValueError('WhatsApp needs a public HTTPS Base URL before it can be marked Connected, so inbound webhooks can reach the CRM.')
            account=d.get('verified_name') or d.get('display_phone_number') or 'WhatsApp Business';external=d.get('id') or phone;scopes=['whatsapp_business_messaging','whatsapp_business_management']
            cfg['webhook_subscribed']=True;cfg['webhook_endpoint']=legacy._public_base_url().rstrip('/')+'/webhooks/meta/'+connection_id
            with m.connect() as con:con.execute('UPDATE v10_connections SET config_json=? WHERE id=?',(json.dumps(cfg),connection_id))
        else:
            return _legacy_test_connection(connection_id)
        with m.connect() as con:
            con.execute("UPDATE v10_connections SET status='Connected',account_name=?,external_account_id=?,scopes_json=?,last_tested_at=CURRENT_TIMESTAMP,last_success_at=CURRENT_TIMESTAMP,last_error='',updated_at=CURRENT_TIMESTAMP WHERE id=?",(account,external,json.dumps(scopes),connection_id))
        try:
            import platform_core as pc;pc.ensure_connection_schedule(connection_id,60)
        except Exception:pass
        m.audit('integration.connected',connection_id,f'{kind} {account}')
        return {'ok':True,'account_name':account,'external_account_id':external}
    except ValueError as exc:
        msg=friendly_error(str(exc),c.get('provider') or kind);state='Permission required' if re.search(r'permission|scope|access denied|403',str(exc),re.I) else 'Reconnect required' if re.search(r'oauth|token|401|expired|reconnect|authori',str(exc),re.I) else 'Connection error'
        with m.connect() as con:con.execute('UPDATE v10_connections SET status=?,last_tested_at=CURRENT_TIMESTAMP,last_error=?,updated_at=CURRENT_TIMESTAMP WHERE id=?',(state,msg[:1200],connection_id))
        raise ValueError(msg) from None


def sync_google_account(connection_id: str) -> dict:
    c=legacy.connection(connection_id);services=c['config'].get('services') or []
    if isinstance(services,str):services=[x for x in services.split(',') if x]
    run=legacy.begin_sync(connection_id,'google_account');summary={'records_seen':0,'records_created':0,'records_updated':0,'records_skipped':0,'errors':0,'services':services,'warnings':[]}
    try:
        # Refresh resource discovery so newly granted accounts appear.
        disc=discover_google_resources(connection_id);auto_select_unambiguous_resources(connection_id);summary['warnings'].extend(disc.get('warnings') or [])
        if 'ads' in services:
            customer=c['config'].get('customer_id') or ''
            if customer:
                part=_sync_google_ads_v14(connection_id);summary['records_seen']+=part.get('records_seen',0);summary['records_updated']+=part.get('records_updated',0)
            else:summary['warnings'].append('Choose a Google Ads account before syncing campaign performance.')
        # Reuse the existing service sync for the services it already handles. It sees
        # the V14-selected IDs stored in the same config names.
        legacy_services=[x for x in services if x in {'analytics','search_console','merchant','gmail','calendar'}]
        if legacy_services:
            cfg=c['config'].copy();cfg['services']=legacy_services
            with m.connect() as con:con.execute('UPDATE v10_connections SET config_json=? WHERE id=?',(json.dumps(cfg),connection_id))
            try:
                part=_legacy_sync_google_business(connection_id);summary['records_seen']+=part.get('records_seen',0);summary['records_updated']+=part.get('records_updated',0);summary['records_created']+=part.get('records_created',0);summary['records_skipped']+=part.get('records_skipped',0)
            finally:
                with m.connect() as con:con.execute('UPDATE v10_connections SET config_json=? WHERE id=?',(json.dumps(c['config']),connection_id))
        if 'youtube' in services:
            # Account metadata is useful for campaign readiness. Publishing is not yet exposed.
            for r in resources(connection_id,'youtube_channel'):_external_resource_copy(connection_id,'youtube_channel',r)
        if 'business_profile' in services:
            for r in resources(connection_id,'business_profile_account'):_external_resource_copy(connection_id,'business_profile_account',r)
        return legacy.finish_sync(run,summary)
    except Exception as exc:
        summary['errors']+=1;legacy.finish_sync(run,summary,str(exc));raise


def _external_resource_copy(connection_id: str, object_type: str, r: dict) -> None:
    legacy._external_upsert(connection_id,object_type,r['external_id'],{'display_name':r['display_name'],'metadata':r.get('metadata',{})})


def _sync_google_ads_v14(connection_id: str) -> dict:
    c=legacy.connection(connection_id);token=access_token(connection_id,'google');dev=provider_secret('google','developer_token');customer=re.sub(r'\D','',c['config'].get('customer_id',''))
    if not dev:raise ValueError('Google Ads requires the platform Google Ads developer token. The business owner does not need to enter it.')
    if not customer:raise ValueError('Choose a Google Ads account.')
    run=legacy.begin_sync(connection_id,'google_ads');summary={'records_seen':0,'records_created':0,'records_updated':0,'records_skipped':0,'errors':0,'pages':0,'authority_blocked':0}
    try:
        decision=authority_decision('ad_performance','Google Ads',connection_id,'metrics',customer)
        if not decision['allowed']:
            summary['authority_blocked']+=1
            raise ValueError('Google Ads performance sync was blocked by the configured source-of-truth policy.')
        gaql='SELECT campaign.id, campaign.name, campaign.status, metrics.impressions, metrics.clicks, metrics.cost_micros, metrics.conversions, metrics.conversions_value, customer.currency_code, segments.date FROM campaign WHERE segments.date DURING LAST_30_DAYS'
        headers={'Authorization':'Bearer '+token,'developer-token':dev};login=re.sub(r'\D','',c['config'].get('login_customer_id',''))
        if login:headers['login-customer-id']=login
        state=sync_cursor(connection_id,'google_ads:metrics');page_token=state.get('cursor_value') or '';pages=0
        while pages<100:
            payload={'query':gaql,'pageSize':10000}
            if page_token:payload['pageToken']=page_token
            d=legacy.api_json(c['id'],'Sync Google Ads','https://googleads.googleapis.com/v25/customers/'+customer+'/googleAds:search','POST',headers,payload)
            pages+=1;summary['pages']+=1
            for row in d.get('results',[]):
                camp=row.get('campaign') or {};met=row.get('metrics') or {};seg=row.get('segments') or {};cust=row.get('customer') or {};ext=str(camp.get('id',''));day=seg.get('date') or dt.date.today().isoformat();summary['records_seen']+=1;summary['records_updated']+=1
                legacy._external_upsert(connection_id,'google_campaign',ext,camp)
                with m.connect() as con:con.execute('''INSERT INTO v10_channel_metrics(id,connection_id,channel,metric_date,campaign_external_id,campaign_name,spend,impressions,clicks,conversions,revenue,currency,source_json)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(connection_id,channel,metric_date,campaign_external_id) DO UPDATE SET campaign_name=excluded.campaign_name,spend=excluded.spend,impressions=excluded.impressions,clicks=excluded.clicks,conversions=excluded.conversions,revenue=excluded.revenue,currency=excluded.currency,source_json=excluded.source_json''',
                (legacy.uid('MET'),connection_id,'Google Ads',day,ext,camp.get('name',''),float(met.get('costMicros') or 0)/1_000_000,int(met.get('impressions') or 0),int(met.get('clicks') or 0),float(met.get('conversions') or 0),float(met.get('conversionsValue') or 0),cust.get('currencyCode',''),json.dumps(row)))
            page_token=str(d.get('nextPageToken') or '')
            set_sync_cursor(connection_id,'google_ads:metrics',page_token,_utc_now().replace(microsecond=0).isoformat().replace('+00:00','Z'))
            if not page_token:break
        if page_token:summary.setdefault('warnings',[]).append('Google Ads pagination paused after 100 pages; the saved cursor will resume on the next sync.')
        return legacy.finish_sync(run,summary)
    except Exception as exc:summary['errors']+=1;legacy.finish_sync(run,summary,str(exc));raise


def _sync_meta_ads_v14(connection_id: str) -> dict:
    c=legacy.connection(connection_id);aid=str(c['config'].get('ad_account_id') or '').removeprefix('act_')
    if not aid:raise ValueError('Choose a Meta ad account.')
    run=legacy.begin_sync(connection_id,'meta_ads');summary={'records_seen':0,'records_created':0,'records_updated':0,'records_skipped':0,'errors':0,'pages':0,'authority_blocked':0,'warnings':[]}
    try:
        decision=authority_decision('ad_performance','Meta',connection_id,'metrics',aid)
        if not decision['allowed']:
            summary['authority_blocked']+=1
            raise ValueError('Meta Ads performance sync was blocked by the configured source-of-truth policy.')
        for object_type,path,params in [
            ('campaigns','act_'+aid+'/campaigns',{'fields':'id,name,status,effective_status,objective,updated_time','limit':'100'}),
            ('insights','act_'+aid+'/insights',{'fields':'campaign_id,campaign_name,impressions,clicks,spend,actions,action_values,account_currency,date_start','level':'campaign','date_preset':'last_30d','time_increment':'1','limit':'500'})
        ]:
            state=sync_cursor(connection_id,'meta_ads:'+object_type);after=state.get('cursor_value') or '';pages=0
            while pages<100:
                req=dict(params)
                if after:req['after']=after
                d=_meta_business_request(c,path,req,operation='Sync Meta '+object_type.title())
                pages+=1;summary['pages']+=1
                for x in d.get('data') or []:
                    summary['records_seen']+=1;summary['records_updated']+=1
                    if object_type=='campaigns':
                        legacy._external_upsert(connection_id,'meta_campaign',str(x.get('id') or ''),x)
                        continue
                    conv=0.0;revenue=0.0
                    for a in x.get('actions') or []:
                        if a.get('action_type') in {'purchase','omni_purchase'}:
                            try:conv+=float(a.get('value') or 0)
                            except (TypeError,ValueError):pass
                    for a in x.get('action_values') or []:
                        if a.get('action_type') in {'purchase','omni_purchase'}:
                            try:revenue+=float(a.get('value') or 0)
                            except (TypeError,ValueError):pass
                    day=x.get('date_start') or dt.date.today().isoformat();camp_id=str(x.get('campaign_id') or '')
                    with m.connect() as con:con.execute('''INSERT INTO v10_channel_metrics(id,connection_id,channel,metric_date,campaign_external_id,campaign_name,spend,impressions,clicks,conversions,revenue,currency,source_json)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(connection_id,channel,metric_date,campaign_external_id) DO UPDATE SET campaign_name=excluded.campaign_name,spend=excluded.spend,impressions=excluded.impressions,clicks=excluded.clicks,conversions=excluded.conversions,revenue=excluded.revenue,currency=excluded.currency,source_json=excluded.source_json''',
                    (legacy.uid('MET'),connection_id,'Meta Ads',day,camp_id,x.get('campaign_name',''),float(x.get('spend') or 0),int(x.get('impressions') or 0),int(x.get('clicks') or 0),conv,revenue,x.get('account_currency',''),json.dumps(x)))
                paging=d.get('paging') or {};after=str(((paging.get('cursors') or {}).get('after')) or '') if paging.get('next') else ''
                set_sync_cursor(connection_id,'meta_ads:'+object_type,after,_utc_now().replace(microsecond=0).isoformat().replace('+00:00','Z'))
                if not after:break
            if after:summary['warnings'].append('Meta '+object_type+' pagination paused after 100 pages; the saved cursor will resume on the next sync.')
        return legacy.finish_sync(run,summary)
    except Exception as exc:summary['errors']+=1;legacy.finish_sync(run,summary,str(exc));raise


def sync_meta_business(connection_id: str) -> dict:
    c=legacy.connection(connection_id);run=legacy.begin_sync(connection_id,'meta_business');summary={'records_seen':0,'records_created':0,'records_updated':0,'records_skipped':0,'errors':0,'warnings':[]}
    try:
        disc=discover_meta_resources(connection_id);auto_select_unambiguous_resources(connection_id);summary['warnings'].extend(disc.get('warnings') or []);summary['records_seen']+=disc.get('count',0);summary['records_updated']+=disc.get('count',0)
        aid=str(c['config'].get('ad_account_id') or '').removeprefix('act_')
        if aid:
            part=_sync_meta_ads_v14(connection_id);summary['records_seen']+=part.get('records_seen',0);summary['records_updated']+=part.get('records_updated',0);summary['records_skipped']+=part.get('records_skipped',0)
            summary['warnings'].extend(part.get('warnings') or [])
        return legacy.finish_sync(run,summary)
    except Exception as exc:summary['errors']+=1;legacy.finish_sync(run,summary,str(exc));raise

def sync_microsoft_mailbox(connection_id: str) -> dict:
    c=legacy.connection(connection_id);token=access_token(connection_id,'microsoft');run=legacy.begin_sync(connection_id,'microsoft_mailbox');summary={'records_seen':0,'records_created':0,'records_updated':0,'records_skipped':0,'errors':0}
    try:
        url='https://graph.microsoft.com/v1.0/me/mailFolders/inbox/messages?$top=50&$select=id,subject,from,toRecipients,receivedDateTime,isRead,conversationId'
        d=legacy.api_json(c['id'],'Sync Microsoft mailbox',url,'GET',{'Authorization':'Bearer '+token})
        for msg in d.get('value') or []:
            summary['records_seen']+=1;email=((((msg.get('from') or {}).get('emailAddress') or {}).get('address')) or '').strip().lower();cid=legacy._match_contact(email,'') if email else ''
            legacy._external_upsert(connection_id,'microsoft_message',msg.get('id') or legacy.uid('MSG'),msg,'contact',cid)
            if cid and not m.one("SELECT 1 FROM interactions WHERE contact_id=? AND metadata_json LIKE ? LIMIT 1",(cid,'%'+str(msg.get('id'))+'%')):
                with m.connect() as con:con.execute('INSERT INTO interactions(interaction_id,contact_id,channel,interaction_type,direction,subject_or_summary,occurred_at,metadata_json) VALUES(?,?,?,?,?,?,?,?)',(legacy.uid('INT'),cid,'Email','Received','Inbound',str(msg.get('subject') or 'Microsoft mailbox message')[:500],msg.get('receivedDateTime') or _utc_now().isoformat(),json.dumps({'provider':'Microsoft Graph','message_id':msg.get('id'),'conversation_id':msg.get('conversationId')})))
                summary['records_created']+=1
            else:summary['records_updated']+=1
        return legacy.finish_sync(run,summary)
    except Exception as exc:summary['errors']+=1;legacy.finish_sync(run,summary,str(exc));raise


def microsoft_send_mail(connection_id: str, to_email: str, subject: str, text: str) -> dict:
    rc.require_external_write_allowed('send Microsoft 365 email')
    c=legacy.connection(connection_id);services=c['config'].get('services') or []
    if 'mail_send' not in services:raise ValueError('Reconnect Microsoft and enable Send mail before using this action.')
    if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',to_email or ''):raise ValueError('Enter a valid recipient email address.')
    token=access_token(connection_id,'microsoft');payload={'message':{'subject':subject[:300],'body':{'contentType':'Text','content':text[:20000]},'toRecipients':[{'emailAddress':{'address':to_email}}]},'saveToSentItems':True}
    legacy.api_json(c['id'],'Send Microsoft email','https://graph.microsoft.com/v1.0/me/sendMail','POST',{'Authorization':'Bearer '+token},payload)
    return {'submitted':True}



def _meta_business_request(c: dict, path: str, params: dict|None=None, method: str='GET', payload=None, operation='Meta API') -> Any:
    token=access_token(c['id'],'meta');version=c['config'].get('graph_version') or provider_app('meta')['config'].get('graph_version') or 'v26.0'
    url=f'https://graph.facebook.com/{version}/'+path.lstrip('/')
    if params:url+='?'+urllib.parse.urlencode(params)
    return legacy.api_json(c['id'],operation,url,method,{'Authorization':'Bearer '+token},payload)


def publish_instagram_image(connection_id: str, image_url: str, caption: str) -> dict:
    rc.require_external_write_allowed('publish to Instagram')
    c=legacy.connection(connection_id)
    if c['connector_key']!='meta_business':return _legacy_publish_instagram_image(connection_id,image_url,caption)
    if c['status']!='Connected':raise ValueError('Connect and test Meta first.')
    ig=str(c['config'].get('instagram_user_id') or '').strip()
    if not ig:raise ValueError('Choose an Instagram Professional account first.')
    if image_url and not re.match(r'^https://',image_url,re.I):
        import media_store
        image_url=media_store.public_url(image_url,upload_if_needed=True)
    if not re.match(r'^https://',image_url or '',re.I):raise ValueError('Instagram publishing requires a publicly reachable HTTPS image URL.')
    created=_meta_business_request(c,ig+'/media',method='POST',payload={'image_url':image_url,'caption':caption or ''},operation='Create Instagram media container')
    creation_id=created.get('id')
    if not creation_id:raise ValueError('Meta did not confirm creation of the Instagram media container.')
    out=_meta_business_request(c,ig+'/media_publish',method='POST',payload={'creation_id':creation_id},operation='Publish Instagram image')
    if not out.get('id'):raise ValueError('Meta did not confirm Instagram publication. The CRM has not marked this as published.')
    return out


def publish_facebook_page_image(connection_id: str, image_url: str, caption: str) -> dict:
    rc.require_external_write_allowed('publish to Facebook')
    c=legacy.connection(connection_id)
    if c['connector_key']!='meta_business':return _legacy_publish_facebook_page_image(connection_id,image_url,caption)
    if c['status']!='Connected':raise ValueError('Connect and test Meta first.')
    page_id=str(c['config'].get('page_id') or '').strip()
    if not page_id:raise ValueError('Choose a Facebook Page first.')
    if image_url and not re.match(r'^https://',image_url,re.I):
        import media_store
        image_url=media_store.public_url(image_url,upload_if_needed=True)
    if not re.match(r'^https://',image_url or '',re.I):raise ValueError('Facebook publishing requires a publicly reachable HTTPS image URL.')
    pages=_meta_business_request(c,'me/accounts',{'fields':'id,name,access_token','limit':'200'},operation='Get Facebook Page access token')
    page_token=''
    for page in pages.get('data') or []:
        if str(page.get('id'))==page_id:page_token=str(page.get('access_token') or '');break
    if not page_token:raise ValueError('The selected Facebook Page is no longer available to this Meta account. Reconnect or choose another Page.')
    version=c['config'].get('graph_version') or 'v26.0';url=f'https://graph.facebook.com/{version}/{page_id}/photos'
    out=legacy.api_json(c['id'],'Publish Facebook Page image',url,'POST',{'Authorization':'Bearer '+page_token},{'url':image_url,'caption':caption or '','published':True})
    if not (out.get('post_id') or out.get('id')):raise ValueError('Meta did not confirm Facebook publication. The CRM has not marked this as published.')
    return out

def _shopify_updated_query(watermark: str) -> str|None:
    if not watermark:return None
    # Shopify search syntax accepts ISO timestamps in a quoted updated_at filter.
    safe=str(watermark).replace("'",'')
    return f"updated_at:>='{safe}'"


def _shopify_page(c: dict, root: str, selection: str, cursor: str='', watermark: str='') -> dict:
    q=f'''query V14ShopifySync($cursor: String, $search: String) {{ {root}(first: 100, after: $cursor, sortKey: UPDATED_AT, query: $search) {{ nodes {{ {selection} }} pageInfo {{ hasNextPage endCursor }} }} }}'''
    return shopify_graphql(c,q,{'cursor':cursor or None,'search':_shopify_updated_query(watermark)},operation='Incremental Shopify '+root).get(root) or {}


def sync_shopify_v14(connection_id: str) -> dict:
    import platform_core as pc
    pc._ensure_stock_location_schema()
    truth.initialise()
    # Resumable Shopify sync with runtime source-of-truth enforcement.
    c=legacy.connection(connection_id);run=legacy.begin_sync(connection_id,'shopify_incremental');summary={'records_seen':0,'records_created':0,'records_updated':0,'records_skipped':0,'errors':0,'products':0,'customers':0,'orders':0,'authority_blocked':0,'pages':0}
    anchor=_utc_now().replace(microsecond=0).isoformat().replace('+00:00','Z')
    try:
        import contact_tools as ct
        specs={
          'products':('product','id title handle productType tags status updatedAt variants(first:20) { nodes { id sku price inventoryQuantity } }'),
          'customers':('customer','id displayName firstName lastName defaultEmailAddress { emailAddress marketingState } defaultPhoneNumber { phoneNumber marketingState } tags updatedAt'),
          'orders':('order','id name createdAt updatedAt displayFinancialStatus displayFulfillmentStatus currentTotalPriceSet { shopMoney { amount currencyCode } } totalRefundedSet { shopMoney { amount currencyCode } } customer { id defaultEmailAddress { emailAddress } defaultPhoneNumber { phoneNumber } } lineItems(first:250) { pageInfo { hasNextPage } nodes { quantity sku originalUnitPriceSet { shopMoney { amount currencyCode } } product { id } } }'),
        }
        for root,(otype,selection) in specs.items():
            state=sync_cursor(connection_id,'shopify:'+root);cursor=state.get('cursor_value') or '';watermark=state.get('watermark') or '';pages=0
            while pages<200:
                block=_shopify_page(c,root,selection,cursor,watermark);nodes=block.get('nodes') or [];pi=block.get('pageInfo') or {};summary['pages']+=1;pages+=1
                for x in nodes:
                    summary['records_seen']+=1
                    if root=='products':
                        summary['products']+=1;ext=x.get('id') or '';variants=(x.get('variants') or {}).get('nodes') or [];sku=(variants[0].get('sku') or '') if variants else '';local=''
                        if sku:
                            r=m.one('SELECT product_id FROM products WHERE internal_sku=? OR product_code=?',(sku,sku));local=(r or {}).get('product_id','')
                        legacy._external_upsert(connection_id,'product',ext,x,'product',local)
                        if local and variants:
                            import record_lifecycle as lifecycle
                            if not lifecycle.is_operationally_active_product(local):
                                summary['records_skipped']+=1
                                continue
                            updates=[];args=[];price=variants[0].get('price');qty=variants[0].get('inventoryQuantity')
                            price_auth=authority_decision('product_content','Shopify',connection_id,'retail_price',local)
                            if price_auth['allowed'] and price not in (None,''):
                                try:updates.append('retail_price=?');args.append(float(price))
                                except (TypeError,ValueError):pass
                            elif price not in (None,''):summary['authority_blocked']+=1
                            inv_auth=authority_decision('inventory','Shopify',connection_id,'stock_qty',local)
                            if inv_auth['allowed'] and qty is not None:
                                reconciled=truth.reconcile_provider_aggregate_stock(local,int(qty),'Shopify',str(ext))
                                if not reconciled.get('applied'):
                                    summary['authority_blocked']+=1
                            elif qty is not None:summary['authority_blocked']+=1
                            if updates:
                                args.append(local)
                                with m.connect() as con:con.execute('UPDATE products SET '+','.join(updates)+' WHERE product_id=?',tuple(args))
                                summary['records_updated']+=1
                            else:summary['records_skipped']+=1
                        else:summary['records_skipped']+=1
                    elif root=='customers':
                        summary['customers']+=1;email=((x.get('defaultEmailAddress') or {}).get('emailAddress') or '').strip();phone=((x.get('defaultPhoneNumber') or {}).get('phoneNumber') or '').strip();cid=legacy._match_contact(email,phone)
                        if not cid:
                            dec=authority_decision('customer','Shopify',connection_id,'identity',x.get('id',''),mutation='create')
                            if dec['allowed']:
                                raw={'full_name':x.get('displayName') or (' '.join(filter(None,[x.get('firstName'),x.get('lastName')]))),'first_name':x.get('firstName') or '','contact_type':'B2C','email':email,'phone_number':phone,'source_name':'Shopify','source_reference':x.get('id') or '','country':'','language':'','username':'','website':'','business_category':'Customer','tags':','.join(x.get('tags') or [])}
                                try:cid=ct.save_contact(raw);summary['records_created']+=1
                                except ValueError:cid=legacy._match_contact(email,phone);summary['records_skipped']+=1
                            else:summary['authority_blocked']+=1;summary['records_skipped']+=1
                        else:
                            authority_decision('customer','Shopify',connection_id,'identity',cid,mutation='update');summary['authority_blocked']+=1;summary['records_skipped']+=1
                        legacy._external_upsert(connection_id,'customer',x.get('id') or '',x,'contact',cid or '')
                    else:
                        summary['orders']+=1;ext=x.get('id') or '';dec=authority_decision('online_order','Shopify',connection_id,'order',ext)
                        cust=x.get('customer') or {};email=((cust.get('defaultEmailAddress') or {}).get('emailAddress') or '');phone=((cust.get('defaultPhoneNumber') or {}).get('phoneNumber') or '');cid=legacy._match_contact(email,phone);money=(x.get('currentTotalPriceSet') or {}).get('shopMoney') or {};total=float(money.get('amount') or 0);currency=money.get('currencyCode') or '';refund_money=(x.get('totalRefundedSet') or {}).get('shopMoney') or {};refund_total=float(refund_money.get('amount') or 0);refund_currency=refund_money.get('currencyCode') or currency
                        if dec['allowed']:
                            import crm_workspace as cw
                            synced=cw.sync_external_order('Shopify',connection_id,ext,contact_id=cid,total=total,currency=currency,
                                financial_status=x.get('displayFinancialStatus') or '',fulfilment_status=x.get('displayFulfillmentStatus') or '',
                                ordered_at=x.get('createdAt') or '',lines=legacy._shopify_order_lines(connection_id,x),provider_refund_total=refund_total,provider_refund_currency=refund_currency)
                            oid=synced['order_id'];summary['records_created' if synced['created'] else 'records_updated']+=1
                            if synced.get('unmapped_lines'):summary['records_skipped']+=int(synced['unmapped_lines'])
                        else:summary['authority_blocked']+=1;summary['records_skipped']+=1
                        legacy._external_upsert(connection_id,'order',ext,x,'order',oid if dec['allowed'] else '')
                        if dec['allowed'] and cid:
                            try:
                                import business_os as bos;bos.record_touchpoint(cid,'order.synced','Website','Shopify','commerce',value=total,currency=currency,metadata={'external_order_id':ext})
                            except Exception as exc:
                                summary.setdefault('warnings',[]).append('Customer 360 touchpoint failed for Shopify order '+str(ext))
                                from operational_guard import record_side_effect_failure
                                record_side_effect_failure('shopify_sync','Shopify order synced but Customer 360 touchpoint failed',exc,recovery='Retry the Shopify sync after reviewing System health. The canonical order was preserved.',entity_type='contact',entity_id=cid,severity='Error')
                        if dec['allowed'] and str(x.get('displayFinancialStatus') or '').upper() in {'PAID','PARTIALLY_PAID','PARTIALLY_REFUNDED'}:
                            try:
                                import operating_core as oc;oc.emit_event('ORDER_PLACED','order',oid,{'contact_id':cid,'source':'Shopify','external_order_id':ext,'status':x.get('displayFinancialStatus'),'total':total,'currency':currency},dedupe_key='shopify-order:'+str(ext)+':'+str(x.get('displayFinancialStatus') or ''))
                            except Exception as exc:
                                summary.setdefault('warnings',[]).append('Automation event failed for Shopify order '+str(ext))
                                from operational_guard import record_side_effect_failure
                                record_side_effect_failure('shopify_sync','Shopify order synced but automation event failed',exc,recovery='Retry the Shopify sync after reviewing System health. The canonical order was preserved.',entity_type='order',entity_id=oid,severity='Error')
                cursor=str(pi.get('endCursor') or '') if pi.get('hasNextPage') else ''
                set_sync_cursor(connection_id,'shopify:'+root,cursor,watermark)
                if not pi.get('hasNextPage'):
                    set_sync_cursor(connection_id,'shopify:'+root,'',anchor);break
            if pages>=200 and cursor:summary.setdefault('warnings',[]).append(root+' pagination paused after 200 pages; the saved cursor will resume on the next run.')
        try:
            import business_os as bos;bos.rebuild_identity_index()
        except Exception as exc:
            summary.setdefault('warnings',[]).append('Identity index rebuild failed after Shopify sync')
            from operational_guard import record_side_effect_failure
            record_side_effect_failure('shopify_sync','Shopify sync completed but identity index rebuild failed',exc,recovery='Open System health and retry the Shopify sync. Canonical records were preserved; identity matching needs repair.',severity='Error')
        return legacy.finish_sync(run,summary)
    except Exception as exc:
        summary['errors']+=1;legacy.finish_sync(run,summary,str(exc));raise


def sync_connection(connection_id: str) -> dict:
    c=legacy.connection(connection_id)
    if c['status']!='Connected':test_connection(connection_id);c=legacy.connection(connection_id)
    if c['connector_key']=='wix':
        import wix_v50 as wix;app=provider_app('wix');return wix.sync_all(connection_id,app,provider_secret('wix','client_secret'))
    if c['connector_key']=='shopify':return sync_shopify_v14(connection_id)
    if c['connector_key']=='google_account':return sync_google_account(connection_id)
    if c['connector_key']=='meta_business':return sync_meta_business(connection_id)
    if c['connector_key']=='microsoft_mailbox':return sync_microsoft_mailbox(connection_id)
    return _legacy_sync_connection(connection_id)


def _candidate_connections_for_channel(channel: str) -> list[dict]:
    keymap={
        'Email':['resend'], 'WhatsApp':['whatsapp_cloud'], 'Website':['shopify','wix'], 'Inventory':['shopify','wix'],
        'Meta Ads':['meta_business','meta_ads'], 'Instagram/Facebook':['meta_business','meta_social'],
        'Google Ads':['google_account','google_ads'], 'Business Email':['microsoft_mailbox'],
    }
    keys=keymap.get(channel,[]);out=[]
    for key in keys:
        for c in legacy.connections(key):
            if c['status']=='Connected':out.append(c)
    return out


def connection_routes(scope_type: str='workspace', scope_key: str='default') -> list[dict]:
    initialise();return m.rows('SELECT * FROM v14_connection_routes WHERE scope_type=? AND scope_key=? ORDER BY channel',(scope_type,scope_key))


def set_connection_route(channel: str, connection_id: str, scope_type: str='workspace', scope_key: str='default', resource_type: str='', resource_external_id: str='') -> None:
    initialise();c=legacy.connection(connection_id);candidates=_candidate_connections_for_channel(channel)
    if c['id'] not in {x['id'] for x in candidates}:raise ValueError('Choose a connected account that supports this business channel.')
    with m.connect() as con:
        con.execute('''INSERT INTO v14_connection_routes(scope_type,scope_key,channel,connection_id,resource_type,resource_external_id)
                       VALUES(?,?,?,?,?,?) ON CONFLICT(scope_type,scope_key,channel) DO UPDATE SET connection_id=excluded.connection_id,resource_type=excluded.resource_type,resource_external_id=excluded.resource_external_id,updated_at=CURRENT_TIMESTAMP''',
                    (scope_type,scope_key,channel,connection_id,resource_type,resource_external_id))
    if channel=='Inventory':
        with m.connect() as con:con.execute("UPDATE v14_data_authority SET authority='Connected commerce store',authority_connection_id=?,updated_at=CURRENT_TIMESTAMP WHERE entity_type='inventory'",(connection_id,))
    m.audit('integration.route_set',connection_id,f'{scope_type}:{scope_key}:{channel}')


def resolve_channel_connection(channel: str, scope_type: str='workspace', scope_key: str='default') -> dict:
    initialise();candidates=_candidate_connections_for_channel(channel)
    route=m.one('SELECT * FROM v14_connection_routes WHERE scope_type=? AND scope_key=? AND channel=?',(scope_type,scope_key,channel))
    if route:
        selected=next((x for x in candidates if x['id']==route['connection_id']),None)
        if selected:return {'connection':selected,'routed':True,'ambiguous':False}
    if len(candidates)==1:return {'connection':candidates[0],'routed':False,'ambiguous':False}
    if len(candidates)>1:return {'connection':None,'routed':False,'ambiguous':True,'candidates':candidates}
    return {'connection':None,'routed':False,'ambiguous':False,'candidates':[]}


def route_channels_for_connection(connection_id: str) -> list[str]:
    c=legacy.connection(connection_id);kind=c['connector_key']
    return {
        'shopify':['Website','Inventory'], 'resend':['Email'], 'whatsapp_cloud':['WhatsApp'],
        'meta_business':['Meta Ads','Instagram/Facebook'], 'meta_ads':['Meta Ads'], 'meta_social':['Instagram/Facebook'],
        'google_account':['Google Ads'], 'google_ads':['Google Ads'], 'microsoft_mailbox':['Business Email'],
    }.get(kind,[])


def channel_readiness(channel: str) -> dict:
    if channel=='SEO/Blog':return {'status':'Ready','connection':None,'reason':'SEO/blog preparation is an internal content workflow and does not require an external account connection.'}
    supported={'Email','WhatsApp','Website','Inventory','Meta Ads','Instagram/Facebook','Google Ads'}
    if channel not in supported:return {'status':'Unsupported / planned','connection':None,'reason':'No launch connector is implemented for this channel yet.'}
    resolved=resolve_channel_connection(channel)
    if resolved.get('ambiguous'):
        return {'status':'Requires account choice','connection':None,'reason':'More than one connected account can serve this channel. Choose the default account in Integration Centre before automation can use it.'}
    c=resolved.get('connection')
    if not c:
        return {'status':'Not connected','connection':None,'reason':'Connect a supported account for this channel.' if channel in {'Email','WhatsApp','Website','Inventory','Meta Ads','Instagram/Facebook','Google Ads'} else 'No launch connector is implemented for this channel yet.'}
    cfg=c.get('config') or {};kind=c['connector_key']
    if channel=='Inventory':
        route=m.one("SELECT connection_id FROM v14_connection_routes WHERE scope_type='workspace' AND scope_key='default' AND channel='Inventory'")
        if not route or route.get('connection_id')!=c['id']:return {'status':'Requires setup','connection':c,'reason':'Choose this store explicitly as the inventory authority before stock can overwrite CRM inventory.'}
        return {'status':'Connected','connection':c,'reason':'This store is the configured inventory authority.'}
    if channel=='WhatsApp':
        is_v14=bool(m.one('SELECT 1 ok FROM v14_token_metadata WHERE connection_id=?',(c['id'],)))
        if not is_v14:return {'status':'Connected','connection':c,'reason':'Legacy WhatsApp connection remains available; reconnect through Embedded Signup to gain V14 operational validation.'}
        if not (cfg.get('phone_registered') and cfg.get('webhook_subscribed')):return {'status':'Requires setup','connection':c,'reason':'WhatsApp is authorised but phone registration/webhook subscription is incomplete.'}
        if not legacy._public_base_url():return {'status':'Requires setup','connection':c,'reason':'Configure a public HTTPS Base URL so WhatsApp webhooks can reach the CRM.'}
        return {'status':'Connected','connection':c,'reason':'WhatsApp phone and WABA webhook subscription are validated.'}
    if channel=='Meta Ads' and kind=='meta_business':
        if 'ads' not in (cfg.get('services') or []):return {'status':'Requires setup','connection':c,'reason':'Reconnect Meta and enable Ads access.'}
        if not cfg.get('ad_account_id'):return {'status':'Requires setup','connection':c,'reason':'Meta is connected. Choose an ad account.'}
        return {'status':'Connected','connection':c,'reason':'Selected Meta ad account is connected for supported reporting/sync.'}
    if channel=='Instagram/Facebook' and kind=='meta_business':
        if 'social' not in (cfg.get('services') or []):return {'status':'Requires setup','connection':c,'reason':'Reconnect Meta and enable Facebook/Instagram access.'}
        if not (cfg.get('page_id') or cfg.get('instagram_user_id')):return {'status':'Requires setup','connection':c,'reason':'Choose a Facebook Page and/or Instagram account.'}
        return {'status':'Connected','connection':c,'reason':'Selected Facebook/Instagram resources are ready for supported publishing/reporting.'}
    if channel=='Google Ads' and kind=='google_account':
        if 'ads' not in (cfg.get('services') or []):return {'status':'Requires setup','connection':c,'reason':'Reconnect Google and enable Google Ads.'}
        if not cfg.get('customer_id'):return {'status':'Requires setup','connection':c,'reason':'Google is connected. Choose a Google Ads account.'}
        if not provider_secret('google','developer_token'):return {'status':'Requires platform setup','connection':c,'reason':'Google Ads developer token must be configured once by the platform administrator.'}
        return {'status':'Connected','connection':c,'reason':'Selected Google Ads account is connected for supported operations.'}
    return {'status':'Connected','connection':c,'reason':'Default connected account selected for this channel.' if resolved.get('routed') else 'Only one connected account is available for this channel.'}



def paid_write_readiness(channel: str) -> dict:
    """Return write readiness separately from read/reporting readiness.

    A provider can be healthy for reporting while still lacking a permission needed to
    create campaigns. Keeping this separate prevents a green reporting connection from
    being mistaken for paid-media write authority.
    """
    if channel not in {'Meta Ads','Google Ads'}:
        return {'status':'Unsupported','connection':None,'reason':'Only Meta Ads and Google Ads reviewed PAUSED creation is implemented.'}
    base=channel_readiness(channel)
    if base.get('status')!='Connected' or not base.get('connection'):
        return base
    c=base['connection'];kind=c['connector_key']
    if channel=='Meta Ads':
        if kind!='meta_business':return {'status':'Requires reconnect','connection':c,'reason':'Reconnect through the V14 Meta login before using paid-media write actions.'}
        granted=set(token_metadata(c['id']).get('granted_scopes') or [])
        if 'ads_management' not in granted:
            return {'status':'Requires permission','connection':c,'reason':'Reconnect Meta and approve ads_management before creating a campaign.'}
    if channel=='Google Ads' and kind!='google_account':
        return {'status':'Requires reconnect','connection':c,'reason':'Reconnect through the V14 Google login before using paid-media write actions.'}
    return {'status':'Ready','connection':c,'reason':'Provider write prerequisites are present. Creation is restricted to PAUSED campaigns.'}


def _record_paid_campaign(unified_campaign_id: str, channel: str, connection_id: str, provider: str, name: str,
                          objective: str, daily_budget: float, currency: str, countries: list[str],
                          provider_campaign_id: str='', provider_budget_id: str='', provider_adset_id: str='',
                          provider_status: str='PAUSED', targeting_status: str='Recorded for review') -> str:
    rid=uid('PAID')
    with m.connect() as con:
        con.execute('''INSERT INTO v14_paid_campaigns(id,unified_campaign_id,channel,connection_id,provider,name,objective,daily_budget,currency,countries_json,provider_campaign_id,provider_budget_id,provider_adset_id,provider_status,targeting_status)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                    (rid,unified_campaign_id,channel,connection_id,provider,name,objective,daily_budget,currency,json.dumps(countries),provider_campaign_id,provider_budget_id,provider_adset_id,provider_status,targeting_status))
    return rid


def paid_campaigns(unified_campaign_id: str) -> list[dict]:
    initialise();rows=m.rows('SELECT * FROM v14_paid_campaigns WHERE unified_campaign_id=? ORDER BY created_at DESC',(unified_campaign_id,))
    for row in rows:row['countries']=json.loads(row.get('countries_json') or '[]')
    return rows


def create_reviewed_paid_campaign(unified_campaign_id: str, channel: str, daily_budget: float|str,
                                  countries: list[str]|str, confirm: str,
                                  eu_political_status: str='DOES_NOT_CONTAIN_EU_POLITICAL_ADVERTISING') -> dict:
    """Create a provider-confirmed PAUSED campaign shell, never an active campaign.

    This intentionally does not create ads/creatives or enable delivery. It gives the
    owner a real provider object to review while keeping spend impossible until a later,
    separately reviewed activation workflow is implemented.
    """
    rc.require_external_write_allowed('create a real paid-media campaign')
    initialise()
    if confirm!='PAUSED':raise ValueError('Type PAUSED exactly. This action never creates an active campaign.')
    if channel not in {'Meta Ads','Google Ads'}:raise ValueError('Choose Meta Ads or Google Ads.')
    try:budget=round(float(daily_budget),2)
    except (TypeError,ValueError):raise ValueError('Enter a valid daily budget.') from None
    if budget<=0 or budget>1_000_000:raise ValueError('Daily budget must be greater than zero and within the platform safety limit.')
    if isinstance(countries,str):countries=[x.strip().upper() for x in re.split(r'[,\s]+',countries) if x.strip()]
    else:countries=[str(x).strip().upper() for x in (countries or []) if str(x).strip()]
    countries=list(dict.fromkeys(countries))
    if not countries or any(not re.fullmatch(r'[A-Z]{2}',x) for x in countries):raise ValueError('Enter at least one ISO two-letter country code, for example GB.')
    campaign=legacy.require_campaign_executable(unified_campaign_id)
    if channel not in campaign.get('channels',[]):raise ValueError('Add this channel to the campaign before creating a provider campaign.')
    readiness=paid_write_readiness(channel)
    if readiness.get('status')!='Ready' or not readiness.get('connection'):raise ValueError(readiness.get('reason') or 'Paid-media account is not ready for writes.')
    c=readiness['connection'];currency=str(campaign.get('currency') or m.settings().get('default_currency','GBP')).upper()
    if currency not in {'GBP','USD','EUR','INR'}:raise ValueError('Reviewed paid creation currently supports GBP, USD, EUR or INR so budget minor-unit conversion is unambiguous.')
    base_name=re.sub(r'\s+',' ',str(campaign.get('name') or 'Commerce Business OS campaign')).strip()[:180]
    stamp=_utc_now().strftime('%Y%m%d-%H%M%S');name=(base_name+' · '+stamp)[:220]
    if eu_political_status not in {'DOES_NOT_CONTAIN_EU_POLITICAL_ADVERTISING','CONTAINS_EU_POLITICAL_ADVERTISING'}:
        raise ValueError('Choose a valid EU political advertising declaration for Google Ads.')

    if channel=='Meta Ads':
        aid=str(c['config'].get('ad_account_id') or '').removeprefix('act_')
        if not aid:raise ValueError('Choose a Meta ad account first.')
        campaign_id=''
        try:
            created=_meta_business_request(c,'act_'+aid+'/campaigns',{
                'name':name,'objective':'OUTCOME_TRAFFIC','special_ad_categories':'[]','status':'PAUSED',
                'buying_type':'AUCTION','is_adset_budget_sharing_enabled':'false'
            },method='POST',operation='Create PAUSED Meta campaign')
            campaign_id=str(created.get('id') or '')
            if not campaign_id:raise ValueError('Meta did not return a campaign ID. Nothing was marked created.')
            minor=int(round(budget*100))
            targeting=json.dumps({'geo_locations':{'countries':countries,'location_types':['home','recent']}},separators=(',',':'))
            adset=_meta_business_request(c,'act_'+aid+'/adsets',{
                'name':(name+' · Ad set')[:220],'campaign_id':campaign_id,'optimization_goal':'LINK_CLICKS',
                'billing_event':'IMPRESSIONS','status':'PAUSED','daily_budget':str(minor),
                'bid_strategy':'LOWEST_COST_WITHOUT_CAP','targeting':targeting
            },method='POST',operation='Create PAUSED Meta ad set')
            adset_id=str(adset.get('id') or '')
            if not adset_id:raise ValueError('Meta did not return an ad-set ID. The campaign remains PAUSED and requires cleanup/review in Meta.')
            rid=_record_paid_campaign(unified_campaign_id,channel,c['id'],'Meta',name,'OUTCOME_TRAFFIC',budget,currency,countries,campaign_id,'',adset_id,'PAUSED','Applied to Meta ad set')
            m.audit('paid_campaign.created_paused',rid,f'Meta campaign {campaign_id} and ad set {adset_id} confirmed PAUSED; no ad creative was created.')
            return {'id':rid,'provider':'Meta','campaign_id':campaign_id,'adset_id':adset_id,'status':'PAUSED','daily_budget':budget,'currency':currency,'countries':countries,'targeting_status':'Applied'}
        except Exception:
            # A partially-created Meta campaign is still safe because it was created PAUSED.
            # Do not try to enable, and do not hide the partial provider object.
            if campaign_id:m.audit('paid_campaign.partial_paused',unified_campaign_id,f'Meta campaign {campaign_id} exists PAUSED but ad-set creation did not complete.')
            raise

    customer=re.sub(r'\D','',str(c['config'].get('customer_id') or ''))
    if not customer:raise ValueError('Choose a Google Ads customer account first.')
    token=access_token(c['id'],'google');dev=provider_secret('google','developer_token')
    if not dev:raise ValueError('Google Ads developer access is not configured by the platform administrator.')
    headers={'Authorization':'Bearer '+token,'developer-token':dev}
    login=re.sub(r'\D','',str(c['config'].get('login_customer_id') or ''))
    if login:headers['login-customer-id']=login
    budget_resource=''
    budget_response=legacy.api_json(c['id'],'Create Google Ads campaign budget',f'https://googleads.googleapis.com/v25/customers/{customer}/campaignBudgets:mutate','POST',headers,{
        'operations':[{'create':{'name':(name+' · Budget')[:220],'deliveryMethod':'STANDARD','amountMicros':int(round(budget*1_000_000))}}]
    })
    results=budget_response.get('results') or [];budget_resource=str((results[0] if results else {}).get('resourceName') or '')
    if not budget_resource:raise ValueError('Google Ads did not confirm the campaign budget. No campaign was marked created.')
    campaign_response=legacy.api_json(c['id'],'Create PAUSED Google Ads campaign',f'https://googleads.googleapis.com/v25/customers/{customer}/campaigns:mutate','POST',headers,{
        'operations':[{'create':{
            'name':name,'advertisingChannelType':'SEARCH','status':'PAUSED','manualCpc':{},'campaignBudget':budget_resource,
            'networkSettings':{'targetGoogleSearch':True,'targetSearchNetwork':True,'targetContentNetwork':False,'targetPartnerSearchNetwork':False},
            'containsEuPoliticalAdvertising':eu_political_status
        }}]
    })
    cres=campaign_response.get('results') or [];campaign_resource=str((cres[0] if cres else {}).get('resourceName') or '')
    if not campaign_resource:raise ValueError('Google Ads did not confirm the PAUSED campaign. The budget exists but the campaign was not marked created.')
    rid=_record_paid_campaign(unified_campaign_id,channel,c['id'],'Google Ads',name,'SEARCH',budget,currency,countries,campaign_resource,budget_resource,'','PAUSED','Countries recorded; Google location criteria require a later reviewed targeting step')
    m.audit('paid_campaign.created_paused',rid,f'Google Ads campaign {campaign_resource} confirmed PAUSED; no ad groups, ads or live country criteria were created.')
    return {'id':rid,'provider':'Google Ads','campaign_id':campaign_resource,'budget_id':budget_resource,'status':'PAUSED','daily_budget':budget,'currency':currency,'countries':countries,'targeting_status':'Recorded for review'}

def friendly_error(message: str, provider: str='integration') -> str:
    low=(message or '').lower();name=str(provider or 'account')
    if any(x in low for x in ['invalid_grant','expired','token','401','reauthor']):return f'Your {name} connection has expired or was revoked. Reconnect the account to continue.'
    if any(x in low for x in ['permission','scope','access denied','403']):return f'{name} is connected, but a required permission is missing. Reconnect and approve the requested business permission.'
    if '429' in low or 'rate limit' in low or 'quota' in low:return f'{name} is temporarily rate-limited. The system will retry; no business data was discarded.'
    if any(x in low for x in ['timeout','could not reach','unavailable','503','502','500']):return f'{name} is temporarily unavailable. Retry shortly; the failed action has been recorded.'
    if 'redirect' in low:return f'{name} login could not return to this application. An administrator should verify the registered callback URL.'
    return message or f'{name} connection needs attention.'


def connection_health(connection_id: str, persist: bool=True, active: bool=False) -> dict:
    c=legacy.connection(connection_id);issues=[];meta=token_metadata(connection_id);active_ok=None
    if active and c['status']=='Connected':
        try:test_connection(connection_id);active_ok=True;c=legacy.connection(connection_id)
        except ValueError as exc:
            active_ok=False;c=legacy.connection(connection_id);issues.append(('High','active_provider_check',friendly_error(str(exc),c.get('provider') or c['connector_key']),'Reconnect or correct the provider setup, then run Test connection.'))
    if c['status']!='Connected':issues.append(('High','not_connected',c.get('last_error') or f'{c["label"]} is not connected.','Reconnect or test the connection.'))
    if meta.get('expires_at') and _expires_soon(meta.get('expires_at'),3600):issues.append(('Medium','token_expiring','The account token expires within an hour.','The system will refresh it automatically when supported; otherwise reconnect.'))
    if meta.get('refresh_expires_at') and _expires_soon(meta.get('refresh_expires_at'),7*86400):issues.append(('Medium','refresh_expiring','The long-lived account session is nearing expiry.','Reconnect the account before the refresh token expires.'))
    if c['status']=='Connected' and c.get('last_sync_at'):
        try:
            parsed=dt.datetime.fromisoformat(str(c['last_sync_at']).replace('Z','+00:00'));parsed=parsed.replace(tzinfo=parsed.tzinfo or dt.timezone.utc)
            if _utc_now()-parsed>dt.timedelta(hours=25):issues.append(('Medium','sync_stale','This connection has not synchronised successfully for more than 24 hours.','Run Sync now or review the worker/scheduler.'))
        except Exception:pass
    readiness_channels=route_channels_for_connection(connection_id)
    for ch in readiness_channels:
        rr=channel_readiness(ch)
        if rr.get('connection') and rr['connection']['id']==connection_id and rr['status'] not in {'Connected','Ready'}:
            issues.append(('Low','channel_setup_'+re.sub(r'[^a-z0-9]+','_',ch.lower()),rr['reason'],'Finish the required account/resource setup.'))
    if persist:
        with m.connect() as con:
            con.execute("UPDATE v14_connection_health SET status='Resolved' WHERE connection_id=? AND status='Open'",(connection_id,))
            seen=set()
            for severity,code,summary,owner_action in issues:
                if code in seen:continue
                seen.add(code);con.execute('INSERT INTO v14_connection_health(id,connection_id,severity,code,summary,owner_action,technical_detail) VALUES(?,?,?,?,?,?,?)',(uid('HLT'),connection_id,severity,code,summary,owner_action,c.get('last_error') or ''))
    return {'connection':c,'issues':[{'severity':a,'code':b,'summary':cc,'owner_action':d} for a,b,cc,d in issues],'healthy':not issues,'active_checked':active,'active_ok':active_ok}


def run_health_checks(active: bool=True) -> dict:
    initialise();rows=legacy.connections();healthy=0;attention=0
    for c in rows:
        if c['connector_key'] not in business_catalog() and not legacy.CONNECTOR_CATALOG.get(c['connector_key'],{}).get('legacy'):continue
        result=connection_health(c['id'],active=active);healthy+=1 if result['healthy'] else 0;attention+=0 if result['healthy'] else 1
    return {'checked':healthy+attention,'healthy':healthy,'attention':attention,'active':active}


def sync_cursor(connection_id: str, object_type: str) -> dict:
    initialise();return m.one('SELECT * FROM v14_sync_cursors WHERE connection_id=? AND object_type=?',(connection_id,object_type)) or {'connection_id':connection_id,'object_type':object_type,'cursor_value':'','watermark':''}


def set_sync_cursor(connection_id: str, object_type: str, cursor_value: str='', watermark: str='') -> None:
    initialise()
    with m.connect() as con:
        con.execute('''INSERT INTO v14_sync_cursors(connection_id,object_type,cursor_value,watermark) VALUES(?,?,?,?)
                       ON CONFLICT(connection_id,object_type) DO UPDATE SET cursor_value=excluded.cursor_value,watermark=excluded.watermark,updated_at=CURRENT_TIMESTAMP''',(connection_id,object_type,str(cursor_value or ''),str(watermark or '')))


def data_authority() -> list[dict]:
    return m.rows('SELECT * FROM v14_data_authority ORDER BY entity_type')


def update_data_authority(entity_type: str, authority: str, conflict_policy: str, explanation: str='', authority_connection_id: str='') -> None:
    if entity_type not in DATA_AUTHORITY_DEFAULTS:raise ValueError('Choose a supported source-of-truth entity.')
    # Runtime authority rules are code-enforced. Free-form text must never imply that
    # changing a label changes the safety boundary. V20 therefore keeps every
    # non-inventory rule pinned to its audited default. Inventory exposes only the
    # actual connected-store selector that the runtime enforces.
    default_authority,default_policy,default_explanation=DATA_AUTHORITY_DEFAULTS[entity_type]
    if entity_type!='inventory':
        authority,conflict_policy,explanation,authority_connection_id=default_authority,default_policy,default_explanation,''
    else:
        authority,conflict_policy,explanation=default_authority,default_policy,default_explanation
        authority_connection_id=(authority_connection_id or 'INTERNAL').strip()
        if authority_connection_id=='INTERNAL':
            authority='Commerce Business OS'
        else:
            c=legacy.connection(authority_connection_id)
            if c['status']!='Connected':raise ValueError('The selected authority account must be connected and validated.')
            if c.get('connector_key') not in {'shopify','wix'}:raise ValueError('Choose a connected commerce store as the inventory authority.')
            authority='Connected commerce store'
    with m.connect() as con:
        con.execute('UPDATE v14_data_authority SET authority=?,conflict_policy=?,explanation=?,authority_connection_id=?,updated_at=CURRENT_TIMESTAMP WHERE entity_type=?',(authority[:120],conflict_policy[:1000],explanation[:1000],authority_connection_id,entity_type))
    if entity_type=='inventory':
        if authority_connection_id and authority_connection_id!='INTERNAL':set_connection_route('Inventory',authority_connection_id)
        else:
            with m.connect() as con:con.execute("DELETE FROM v14_connection_routes WHERE scope_type='workspace' AND scope_key='default' AND channel='Inventory'")


def authority_decision(entity_type: str, provider: str, connection_id: str='', field_name: str='', object_id: str='', mutation: str='update', persist: bool=True) -> dict:
    initialise();row=m.one('SELECT * FROM v14_data_authority WHERE entity_type=?',(entity_type,))
    if not row:return {'allowed':False,'reason':'No source-of-truth policy exists for this entity type.'}
    authority=str(row.get('authority') or '').strip().lower();provider_low=str(provider or '').strip().lower();configured=str(row.get('authority_connection_id') or '')
    allowed=False;reason=''
    if entity_type=='customer':
        allowed=mutation=='create';reason='CRM is master for customer identity; provider imports may create a missing identity but may not overwrite an existing CRM identity.'
    elif entity_type=='marketing_permission':
        allowed=False;reason='Marketing permission is CRM-mastered; provider events must enter the consent ledger and the most restrictive verified state wins.'
    elif entity_type=='product_content':
        allowed=False;reason='Product content and pricing remain CRM-mastered until an explicit publish action.'
    elif entity_type=='online_order':
        allowed=('commerce' in authority or 'shopify' in authority or (configured and configured==connection_id));reason='Provider-owned order status and totals may update the matching immutable provider order.'
    elif entity_type=='ad_performance':
        allowed=('advertising provider' in authority or 'meta' in provider_low or 'google' in provider_low);reason='Advertising performance is append/sync-only from the advertising provider.'
    elif entity_type=='inventory':
        routed=m.one("SELECT connection_id FROM v14_connection_routes WHERE scope_type='workspace' AND scope_key='default' AND channel='Inventory'")
        expected=configured or ((routed or {}).get('connection_id') if routed else 'INTERNAL')
        if expected=='INTERNAL':
            allowed=(provider_low in {'commerce crm','internal','local','commerce_crm'} and not connection_id)
            reason=('Commerce Business OS is the configured inventory authority.' if allowed else 'External inventory writes are blocked until the owner explicitly selects that connected store as inventory authority.')
        else:
            allowed=bool(expected and connection_id and expected==connection_id)
            reason=('This connected commerce account is the configured inventory authority.' if allowed else 'Inventory updates are blocked because another source is the configured inventory authority.')
    else:
        allowed=False;reason='No runtime authority rule is implemented for this entity type.'
    if persist:
        with m.connect() as con:con.execute('INSERT INTO v14_authority_decisions(id,entity_type,field_name,provider,connection_id,allowed,reason,object_id) VALUES(?,?,?,?,?,?,?,?)',(uid('AUTH'),entity_type,field_name,provider,connection_id,1 if allowed else 0,reason,object_id))
    return {'allowed':allowed,'reason':reason,'policy':row}


def connect_whatsapp_embedded(code: str, waba_id: str, phone_number_id: str, business_id: str='', label: str='WhatsApp Business') -> str:
    # Complete Meta Embedded Signup and only mark ready after operational setup.
    initialise();app=provider_app('meta')
    if not app['configured'] or not app['config'].get('whatsapp_config_id'):raise ValueError('WhatsApp Embedded Signup is not enabled for this platform yet. An administrator must configure the approved Meta signup app.')
    if not code or not waba_id or not phone_number_id:raise ValueError('Meta Embedded Signup did not return the WhatsApp account and phone-number details. Start the connection again.')
    base=legacy._public_base_url()
    if not base:raise ValueError('Configure a public HTTPS Base URL before connecting WhatsApp so Meta can deliver inbound messages and status webhooks to the CRM.')
    cid=_new_connection('whatsapp_cloud',label,{'phone_number_id':str(phone_number_id),'waba_id':str(waba_id),'business_id':str(business_id or ''),'graph_version':app['config'].get('graph_version') or 'v26.0','verify_token':secrets.token_urlsafe(24),'phone_registered':False,'webhook_subscribed':False,'webhook_endpoint':base.rstrip('/')+'/webhooks/meta/'+uid('END')})
    secret=provider_secret('meta','client_secret');version=app['config'].get('graph_version') or 'v26.0'
    url=f'https://graph.facebook.com/{version}/oauth/access_token?'+urllib.parse.urlencode({'client_id':app['client_id'],'client_secret':secret,'code':code})
    out=legacy.api_json(cid,'WhatsApp Embedded Signup token exchange',url,'GET')
    if not out.get('access_token'):raise ValueError('Meta did not return a WhatsApp access token. The connection was not marked Connected.')
    token=str(out['access_token']);legacy.store_secret(cid,'access_token',token);_set_token_meta(cid,out,['whatsapp_business_messaging','whatsapp_business_management'])
    pin=f'{secrets.randbelow(1_000_000):06d}';legacy.store_secret(cid,'two_step_pin',pin);hdr={'Authorization':'Bearer '+token}
    try:
        reg=legacy.api_json(cid,'Register WhatsApp phone',f'https://graph.facebook.com/{version}/{phone_number_id}/register','POST',hdr,{'messaging_product':'whatsapp','pin':pin})
        if not (reg.get('success') is True or reg.get('id') or reg=={}):raise ValueError('Meta did not confirm phone registration.')
        sub=legacy.api_json(cid,'Subscribe app to WhatsApp Business Account',f'https://graph.facebook.com/{version}/{waba_id}/subscribed_apps','POST',hdr,{})
        if not (sub.get('success') is True or sub.get('id') or sub=={}):raise ValueError('Meta did not confirm the WABA webhook subscription.')
        verify=legacy.api_json(cid,'Verify WhatsApp WABA subscription',f'https://graph.facebook.com/{version}/{waba_id}/subscribed_apps','GET',hdr)
        if str(app['client_id']) not in _waba_subscribed_app_ids(verify):
            raise ValueError('Meta did not return this app in the WABA subscribed-app list.')
        c=legacy.connection(cid);cfg=c['config'];cfg['phone_registered']=True;cfg['webhook_subscribed']=True;cfg['webhook_endpoint']=base.rstrip('/')+'/webhooks/meta/'+cid
        with m.connect() as con:con.execute('UPDATE v10_connections SET config_json=? WHERE id=?',(json.dumps(cfg),cid))
        test_connection(cid)
        m.audit('whatsapp.embedded_signup_completed',cid,'Phone registered and WABA subscribed; inbound webhook endpoint requires matching Meta App webhook configuration.')
        return cid
    except Exception as exc:
        with m.connect() as con:con.execute("UPDATE v10_connections SET status='Connection requires setup',last_error=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",(friendly_error(str(exc),'WhatsApp')[:1200],cid))
        raise ValueError(friendly_error(str(exc),'WhatsApp')) from None


def _legacy_whatsapp_test(connection_id: str) -> dict:
    return _legacy_test_connection(connection_id)



def disconnect_connection(connection_id: str) -> dict:
    """Disconnect a business account without overstating provider revocation.

    Google and Meta expose revocation endpoints we can call directly. Shopify and
    Microsoft do not provide an equivalent app-side token revocation operation for
    this connection pattern, so we remove local tokens and explain that limitation.
    """
    c=legacy.connection(connection_id);kind=c['connector_key'];provider_revoked=False;detail=''
    try:
        if kind=='google_account':
            token=legacy.load_secret(connection_id,'refresh_token') or legacy.load_secret(connection_id,'access_token')
            if token:
                _form_json(connection_id,'Revoke Google connection','https://oauth2.googleapis.com/revoke',{'token':token})
                provider_revoked=True;detail='Google account grant revoked.'
        elif kind=='meta_business':
            token=legacy.load_secret(connection_id,'access_token');ver=c['config'].get('graph_version') or 'v26.0'
            if token:
                legacy.api_json(connection_id,'Revoke Meta permissions',f'https://graph.facebook.com/{ver}/me/permissions','DELETE',{'Authorization':'Bearer '+token})
                provider_revoked=True;detail='Meta app permissions revoked.'
        elif kind=='whatsapp_cloud':
            detail='Local WhatsApp token removed. Meta business asset access can also be removed from Meta Business settings if required.'
        elif kind=='shopify':
            detail='Local Shopify token removed. The merchant can also uninstall the app from Shopify Admin.'
        elif kind=='microsoft_mailbox':
            detail='Local Microsoft tokens removed. The user or tenant administrator can separately revoke application consent in Microsoft.'
    except ValueError as exc:
        detail='Provider-side revocation could not be confirmed: '+friendly_error(str(exc),c.get('provider') or kind)
    legacy.disconnect(connection_id)
    with m.connect() as con:
        con.execute('DELETE FROM v14_token_metadata WHERE connection_id=?',(connection_id,))
        con.execute('DELETE FROM v14_connection_resources WHERE connection_id=?',(connection_id,))
        con.execute('DELETE FROM v14_sync_cursors WHERE connection_id=?',(connection_id,))
        con.execute('DELETE FROM v14_connection_routes WHERE connection_id=?',(connection_id,))
        con.execute("UPDATE v14_data_authority SET authority='Commerce Business OS',authority_connection_id='INTERNAL',updated_at=CURRENT_TIMESTAMP WHERE authority_connection_id=?",(connection_id,))
        con.execute("UPDATE v14_connection_health SET status='Resolved' WHERE connection_id=? AND status='Open'",(connection_id,))
    m.audit('integration.v14_disconnected',connection_id,detail or 'Local credentials removed.')
    return {'provider_revoked':provider_revoked,'detail':detail or 'Local credentials removed.'}

def account_selection_requirements(connection_id: str) -> list[dict]:
    c=legacy.connection(connection_id);types=[]
    if c['connector_key']=='meta_business':
        services=c['config'].get('services') or []
        if 'social' in services:types += [('facebook_page','Facebook Page',False),('instagram_account','Instagram Professional account',False)]
        if 'ads' in services:types += [('meta_ad_account','Meta ad account',True)]
        types += [('meta_business','Business Portfolio',False)]
    elif c['connector_key']=='google_account':
        services=c['config'].get('services') or []
        mapping={'ads':('google_ads_customer','Google Ads account'),'analytics':('ga4_property','GA4 property'),'search_console':('search_console_site','Search Console property'),'merchant':('merchant_account','Merchant Center account'),'youtube':('youtube_channel','YouTube channel'),'calendar':('calendar','Calendar'),'business_profile':('business_profile_account','Business Profile account')}
        for svc in services:
            if svc in mapping:types.append((mapping[svc][0],mapping[svc][1],svc in {'ads'}))
    out=[]
    for typ,label,required in types:
        rows=resources(connection_id,typ);out.append({'resource_type':typ,'label':label,'required':required,'resources':rows,'selected':[x for x in rows if x['selected']]})
    return out


def setup_status() -> list[dict]:
    st=m.settings();contacts=(m.one('SELECT count(*) n FROM contacts') or {'n':0})['n'];products=(m.one('SELECT count(*) n FROM products') or {'n':0})['n'];campaigns=(m.one('SELECT count(*) n FROM v10_unified_campaigns') or {'n':0})['n']
    brand=bool((st.get('brand_name') or '').strip() and (st.get('brand_name') or '').strip().lower() not in {'brand name pending','pending'})
    def conn(key):return next((x for x in legacy.connections(key) if x['status']=='Connected'),None)
    meta=conn('meta_business') or conn('meta_social') or conn('meta_ads');google=conn('google_account') or conn('google_business') or conn('google_ads')
    store=conn('shopify') or conn('wix');email=conn('resend');wa=conn('whatsapp_cloud');mailbox=conn('microsoft_mailbox')
    return [
        {'label':'Business profile','status':'Complete' if brand else 'Needs setup','detail':st.get('brand_name') or 'Add the real business name and commercial defaults.','url':'/settings'},
        {'label':'Store','status':'Complete' if store else 'Needs setup','detail':(store or {}).get('account_name') or 'Connect Shopify or Wix with normal store authorisation.','url':'/integrations/v14/connect/shopify'},
        {'label':'Marketing email','status':'Complete' if email else 'Needs setup','detail':(email or {}).get('account_name') or 'Configure the sending provider/domain in Advanced setup.','url':'/integrations'},
        {'label':'Business mailbox','status':'Complete' if mailbox or (google and 'gmail' in ((google.get('config') or {}).get('services') or [])) else 'Optional','detail':(mailbox or {}).get('account_name') or 'Connect Google Gmail or Microsoft 365 for customer/sales replies.','url':'/integrations'},
        {'label':'Meta / Instagram / Facebook','status':'Complete' if meta else 'Needs setup','detail':(meta or {}).get('account_name') or 'Click Connect Meta and choose your business resources.','url':'/integrations/v14/connect/meta_business'},
        {'label':'Google','status':'Complete' if google else 'Needs setup','detail':(google or {}).get('account_name') or 'Click Connect Google and choose the services you use.','url':'/integrations/v14/connect/google_account'},
        {'label':'WhatsApp Business','status':'Complete' if wa else 'Needs setup','detail':(wa or {}).get('account_name') or 'Use Meta Embedded Signup when the platform app is approved.','url':'/integrations/v14/connect/whatsapp_cloud'},
        {'label':'Customers','status':'Complete' if contacts else 'Needs setup','detail':f'{int(contacts):,} CRM contacts available.','url':'/contacts'},
        {'label':'Products','status':'Complete' if products else 'Needs setup','detail':f'{int(products):,} product records available.','url':'/product-workflow'},
        {'label':'First connected campaign','status':'Complete' if campaigns else 'Needs setup','detail':'Create one objective and let the builder adapt it to the accounts that are actually ready.','url':'/campaign-builder'},
    ]


def integration_audit_matrix() -> list[dict]:
    """Truthful implementation classification used by the V14 executive audit."""
    rows=[]
    catalog=business_catalog()
    for key,meta in catalog.items():
        status='Not implemented'
        auth='—';sync='—';write='—'
        if meta.get('implemented'):
            # Code-complete does not mean provider-accepted. A connector becomes Fully
            # Working only after a real business connection validates against the live
            # provider, so the static audit remains conservative.
            status='Partially Implemented' if meta.get('login_first') else 'API Only'
            auth='Login/OAuth' if meta.get('login_first') else 'Provider/API setup'
            caps=meta.get('capabilities') or [];sync='Yes' if any(str(x).startswith('sync_') for x in caps) else 'Limited'
            write='Yes, limited/reviewed' if any(x in caps for x in ['push_product_draft','send_email','send_template','publish_instagram_image','publish_facebook_image','send_mail','create_paid_campaign_paused']) else 'Read/sync only'
        rows.append({'key':key,'label':meta['label'],'status':status,'auth':auth,'sync':sync,'write':write,'external_dependency':'Provider app/account approval required for live acceptance.' if meta.get('login_first') else ('Provider credential required.' if meta.get('implemented') else 'Backend not built yet.')})
    return rows


def run_v14_acceptance_audit() -> dict:
    """Non-destructive 27-step readiness audit; no send/publish/spend occurs."""
    initialise();steps=[]
    def add(no,label,status,detail):steps.append({'step':no,'label':label,'status':status,'detail':detail})
    providers={k:provider_app(k) for k in PROVIDER_SPECS}
    conns=legacy.connections();connected={c['connector_key'] for c in conns if c['status']=='Connected'}
    has_contacts=(m.one('SELECT count(*) n FROM contacts') or {'n':0})['n']>0;has_products=(m.one('SELECT count(*) n FROM products') or {'n':0})['n']>0
    has_creatives=m.table_exists('v8_creative_assets') or m.table_exists('v7_creative_assets')
    add(1,'Create account','Pass' if m.table_exists('v11_users') else 'Blocked','Local/production account and role system exists.')
    add(2,'Business information','Pass' if (m.settings().get('brand_name') or '').strip() else 'Needs setup','Business settings are stored centrally.')
    add(3,'Connect store by login','Pass' if ('shopify' in connected or 'wix' in connected) else ('Ready to configure' if (providers['shopify']['configured'] or providers['wix']['configured']) else 'Blocked'),'Shopify and Wix login-first commerce flows are implemented; live success requires provider app setup and merchant approval.')
    add(4,'Connect Meta by login','Pass' if 'meta_business' in connected else ('Ready to configure' if providers['meta']['configured'] else 'Blocked'),'Meta login flow and account discovery are implemented; live app review/permissions still apply.')
    add(5,'Select Instagram/Facebook resources','Pass' if channel_readiness('Instagram/Facebook')['status']=='Connected' else 'Needs setup','Connected Meta resources must be selected before publishing.')
    add(6,'Connect Google by login','Pass' if 'google_account' in connected else ('Ready to configure' if providers['google']['configured'] else 'Blocked'),'Shared Google OAuth flow uses incremental scopes and resource discovery.')
    add(7,'Choose Google Ads account','Pass' if channel_readiness('Google Ads')['status']=='Connected' else 'Needs setup','Google Ads additionally needs a platform developer token and selected customer account.')
    add(8,'Connect Merchant Center','Pass' if any(r['resource_type']=='merchant_account' and r['selected'] for c in conns if c['connector_key']=='google_account' for r in resources(c['id'])) else 'Needs setup','Merchant accounts can be discovered through the shared Google connection.')
    add(9,'Connect mailbox','Pass' if 'microsoft_mailbox' in connected or any(c['connector_key']=='google_account' and 'gmail' in (c['config'].get('services') or []) for c in conns if c['status']=='Connected') else 'Needs setup','Gmail and Microsoft mailbox login paths are separated from marketing email transport.')
    add(10,'Marketing email/domain','Pass' if 'resend' in connected else 'Needs setup','Marketing sending still requires a sending provider/domain; mailbox OAuth alone is not sufficient.')
    add(11,'Connect WhatsApp','Pass' if 'whatsapp_cloud' in connected else ('Ready to configure' if providers['meta']['configured'] and providers['meta']['config'].get('whatsapp_config_id') else 'Blocked'),'Embedded Signup completion path is built; the Meta app must be approved/configured.')
    add(12,'Sync customers', 'Pass' if has_contacts else 'Needs setup','CRM can import and reconcile connected customer identities.')
    add(13,'Upload product images','Pass' if has_products else 'Needs setup','Product workflow accepts raw images and validates them.')
    add(14,'Generate product information','Pass' if m.table_exists('v6_product_content') else 'Blocked','Product content model exists with fact/provenance safeguards.')
    add(15,'Generate product imagery','Pass' if has_creatives else 'Ready','Creative engine exists; paid image model/account configuration may still be required.')
    add(16,'Generate video','Pass' if m.table_exists('v8_videos') or m.table_exists('v7_video_assets') else 'Ready','Video package workflow exists; generative motion provider remains optional/review-gated.')
    add(17,'Prepare store listing','Pass' if ('shopify' in connected or 'wix' in connected) else 'Needs setup','Reviewed product drafts can be created once a supported commerce store is connected.')
    add(18,'Generate campaign','Pass' if m.table_exists('v10_unified_campaigns') else 'Blocked','Unified campaign model exists.')
    add(19,'Select connected channels','Pass','Campaign readiness uses deterministic connection routing; ambiguous multi-account channels require an explicit default.')
    add(20,'Publish/send/launch','Partial','Email/WhatsApp and supported organic social writes exist. Meta/Google can create provider-confirmed PAUSED campaign shells, but activation remains deliberately blocked until final targeting/creative/conversion review.')
    add(21,'Capture engagement','Partial','Provider delivery/insight sync exists for implemented connectors; complete social/ad lead ingestion is still incomplete.')
    add(22,'Capture leads','Partial','CRM/event foundation exists; every provider lead source is not yet connected.')
    add(23,'Update CRM','Pass','Connected order/message/contact data maps to CRM identities where possible; Shopify inventory/content writes are governed by runtime source-of-truth decisions.')
    add(24,'Capture sales','Pass' if m.table_exists('orders') else 'Blocked','Orders are a first-class CRM entity and Shopify orders can sync.')
    add(25,'Attribute revenue','Partial','Touchpoints/metrics exist; full cross-device multi-touch attribution remains incomplete.')
    add(26,'Analyse performance','Pass' if m.table_exists('v10_channel_metrics') else 'Blocked','Provider metrics feed the performance centre without fabricated data.')
    add(27,'AI next recommendation','Pass' if m.table_exists('v9_recommendations') else 'Blocked','Action Centre can generate next-step recommendations from recorded business facts.')
    return {'steps':steps,'pass':sum(1 for x in steps if x['status']=='Pass'),'partial':sum(1 for x in steps if x['status']=='Partial'),'needs_setup':sum(1 for x in steps if x['status'] in {'Needs setup','Ready to configure','Ready'}),'blocked':sum(1 for x in steps if x['status']=='Blocked')}


# Keep references to legacy implementations before monkey-patching the module globals.
_legacy_test_connection=legacy.test_connection
_legacy_sync_connection=legacy.sync_connection
_legacy_google_access_token=legacy._google_access_token
_legacy_sync_google_business=legacy.sync_google_business
_legacy_sync_meta_ads=legacy.sync_meta_ads
_legacy_publish_instagram_image=legacy.publish_instagram_image
_legacy_publish_facebook_page_image=legacy.publish_facebook_page_image


def patch_legacy() -> None:
    patch_legacy_catalog()
    legacy._google_access_token=google_access_token
    legacy._shopify_graphql=shopify_graphql
    legacy.test_connection=test_connection
    legacy.sync_connection=sync_connection
    legacy.channel_readiness=channel_readiness
    legacy.publish_instagram_image=publish_instagram_image
    legacy.publish_facebook_page_image=publish_facebook_page_image

