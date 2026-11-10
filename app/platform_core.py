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
import threading
import time
import uuid
from pathlib import Path
from typing import Any

import marketing as m
import db_layer
import business_os as bos
import mfa_auth
import v35_truth as truth

ROOT = Path(__file__).resolve().parent

SCHEMA = r'''
CREATE TABLE IF NOT EXISTS v11_users(
  user_id TEXT PRIMARY KEY,
  email TEXT NOT NULL UNIQUE,
  display_name TEXT NOT NULL,
  role TEXT NOT NULL,
  password_salt TEXT NOT NULL,
  password_hash TEXT NOT NULL,
  active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  last_login_at TEXT
);
CREATE TABLE IF NOT EXISTS v11_sessions(
  session_hash TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  last_seen_at TEXT DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY(user_id) REFERENCES v11_users(user_id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS v11_login_guards(
  guard_key TEXT PRIMARY KEY,
  failed_count INTEGER NOT NULL DEFAULT 0,
  window_started_at TEXT DEFAULT CURRENT_TIMESTAMP,
  last_failed_at TEXT,
  lock_until TEXT
);
CREATE TABLE IF NOT EXISTS v11_role_permissions(
  role TEXT NOT NULL,
  permission TEXT NOT NULL,
  allowed INTEGER NOT NULL DEFAULT 1,
  PRIMARY KEY(role,permission)
);
CREATE TABLE IF NOT EXISTS v11_approvals(
  id TEXT PRIMARY KEY,
  action_type TEXT NOT NULL,
  object_type TEXT NOT NULL DEFAULT '',
  object_id TEXT NOT NULL DEFAULT '',
  summary TEXT NOT NULL,
  risk_level TEXT NOT NULL DEFAULT 'Medium',
  status TEXT NOT NULL DEFAULT 'Pending',
  requested_by TEXT DEFAULT '',
  decided_by TEXT DEFAULT '',
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  decided_at TEXT,
  decision_note TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS v11_approvals_status ON v11_approvals(status,risk_level,created_at);
CREATE TABLE IF NOT EXISTS v11_schedules(
  id TEXT PRIMARY KEY,
  job_key TEXT NOT NULL UNIQUE,
  job_type TEXT NOT NULL,
  connection_id TEXT DEFAULT '',
  payload_json TEXT NOT NULL DEFAULT '{}',
  interval_minutes INTEGER NOT NULL DEFAULT 60,
  enabled INTEGER NOT NULL DEFAULT 1,
  next_run_at TEXT DEFAULT CURRENT_TIMESTAMP,
  last_run_at TEXT,
  last_status TEXT DEFAULT 'Never',
  last_error TEXT DEFAULT '',
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS v11_schedules_due ON v11_schedules(enabled,next_run_at);
CREATE TABLE IF NOT EXISTS v11_identity_candidates(
  id TEXT PRIMARY KEY,
  primary_contact_id TEXT NOT NULL,
  duplicate_contact_id TEXT NOT NULL,
  match_types_json TEXT NOT NULL DEFAULT '[]',
  match_values_json TEXT NOT NULL DEFAULT '[]',
  status TEXT NOT NULL DEFAULT 'Needs review',
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  reviewed_at TEXT,
  UNIQUE(primary_contact_id,duplicate_contact_id)
);
CREATE TABLE IF NOT EXISTS v11_merge_history(
  id TEXT PRIMARY KEY,
  primary_contact_id TEXT NOT NULL,
  duplicate_contact_id TEXT NOT NULL,
  snapshot_json TEXT NOT NULL DEFAULT '{}',
  merged_by TEXT DEFAULT '',
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS v11_e2e_runs(
  id TEXT PRIMARY KEY,
  status TEXT NOT NULL DEFAULT 'Running',
  started_at TEXT DEFAULT CURRENT_TIMESTAMP,
  finished_at TEXT,
  summary_json TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS v11_e2e_steps(
  id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL,
  step_no INTEGER NOT NULL,
  label TEXT NOT NULL,
  status TEXT NOT NULL,
  detail TEXT NOT NULL DEFAULT '',
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY(run_id) REFERENCES v11_e2e_runs(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS v11_health_checks(
  id TEXT PRIMARY KEY,
  connection_id TEXT DEFAULT '',
  check_type TEXT NOT NULL,
  status TEXT NOT NULL,
  detail TEXT DEFAULT '',
  checked_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS v11_health_checks_conn ON v11_health_checks(connection_id,checked_at);
CREATE TABLE IF NOT EXISTS v11_security_config(
  setting_key TEXT PRIMARY KEY,
  setting_value TEXT NOT NULL DEFAULT '',
  updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS v11_privacy_requests(
  id TEXT PRIMARY KEY,
  contact_id TEXT NOT NULL,
  request_type TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'Open',
  notes TEXT DEFAULT '',
  requested_at TEXT DEFAULT CURRENT_TIMESTAMP,
  completed_at TEXT,
  completed_by TEXT DEFAULT '',
  FOREIGN KEY(contact_id) REFERENCES contacts(contact_id)
);
CREATE INDEX IF NOT EXISTS v11_privacy_requests_status ON v11_privacy_requests(status,requested_at);
'''

ROLES = [
    'Owner','Administrator','Marketing','Sales','Showroom staff','Customer service','Finance','Read-only analyst'
]

ROLE_PERMISSIONS = {
    'Owner': {'*'},
    'Administrator': {'workspace.read','contacts.manage','products.manage','marketing.manage','sales.manage','orders.manage','integrations.manage','settings.manage','users.manage','approvals.manage','reports.read'},
    'Marketing': {'workspace.read','contacts.read','products.read','marketing.manage','reports.read','approvals.request'},
    'Sales': {'workspace.read','contacts.manage','products.read','sales.manage','orders.read','marketing.read','reports.read','approvals.request'},
    'Showroom staff': {'workspace.read','contacts.manage','products.read','sales.manage','orders.read'},
    'Customer service': {'workspace.read','contacts.manage','orders.read','marketing.read'},
    'Finance': {'workspace.read','contacts.read','orders.manage','reports.read'},
    'Read-only analyst': {'workspace.read','contacts.read','products.read','marketing.read','sales.read','orders.read','reports.read'},
}

PATH_PERMISSIONS = [
    (r'^/launch/ai(?:/|$)', 'settings.manage'),
    (r'^/launch/store', 'integrations.manage'),
    (r'^/launch(?:/|$)', 'products.read'),
    (r'^/operations/refresh', 'integrations.manage'),
    (r'^/operations/social', 'marketing.read'),
    (r'^/operations/(inbox|retention)', 'contacts.read'),
    (r'^/operations/(orders|fulfilments|returns|accounting)', 'orders.read'),
    (r'^/operations/actions', 'sales.read'),
    (r'^/(operations|v17-e2e|v18-e2e)', 'workspace.read'),
    (r'^/reports(?:/|$)', 'reports.read'),
    (r'^/v16/automation-mode', 'settings.manage'),
    (r'^/v15/openai/test', 'settings.manage'),
    (r'^/(integrations|setup|integration-logs|integration-health|system-health|architecture-readiness|access-control|scheduler|e2e-test|v14-e2e|v15-e2e|external-requirements|developer/integrations|data-ownership)', 'integrations.manage'),
    (r'^/(settings|backups|properties)', 'settings.manage'),
    (r'^/(campaign|outreach|knowledge|audience-builder|marketing-performance|marketing-calendar|marketing|customer-journeys|growth|blogs)', 'marketing.read'),
    (r'^/(product|creative|locations|brands)', 'products.read'),
    (r'^/(opportunities|showrooms|companies|tasks|workflows)', 'sales.read'),
    (r'^/orders', 'orders.read'),
    (r'^/(contacts|imports|identity-resolution|privacy)', 'contacts.read'),
]

# Route-specific write permissions are evaluated before the broad read map.
# This prevents direct POST requests to owner/admin actions from inheriting
# the generic workspace.read fallback merely because the button is hidden.
WRITE_PATH_PERMISSIONS = [
    (r'^/launch/ai-connect$', 'settings.manage'),
    (r'^/launch/brand$', 'settings.manage'),
    (r'^/launch/deliver$', 'integrations.manage'),
    (r'^/launch/(social|social-save)$', 'marketing.manage'),
    (r'^/launch(?:/|$)', 'products.manage'),
    (r'^/operations/fulfilments(?:/|$)', 'orders.manage'),
    (r'^/operations/shipments(?:/|$)', 'orders.manage'),
    (r'^/operations/returns(?:/|$)', 'orders.manage'),
    (r'^/operations/accounting(?:/|$)', 'orders.manage'),
    (r'^/operations/inbox(?:/|$)', 'contacts.manage'),
    (r'^/operations/retention(?:/|$)', 'contacts.manage'),
    (r'^/operations/social(?:/|$)', 'marketing.manage'),
    (r'^/operations/actions(?:/|$)', 'sales.manage'),
    (r'^/(marketing-calendar|campaign-builder)(?:/|$)', 'marketing.manage'),
    (r'^/ai(?:/|$)', 'settings.manage'),
    (r'^/(permissions|preferences|activities|views|actions|enrich)(?:/|$)', 'contacts.manage'),
    (r'^/(drafts|templates|segments)(?:/|$)', 'marketing.manage'),
    (r'^/(ai-governance|operating-settings|model-routing)(?:/|$)', 'settings.manage'),
    (r'^/(consent-centre|identity)(?:/|$)', 'contacts.manage'),
    (r'^/(event-stream|automation-engine)(?:/|$)', 'settings.manage'),
    (r'^/email-infrastructure(?:/|$)', 'integrations.manage'),
    (r'^/(recommendations|action-centre)(?:/|$)', 'marketing.manage'),
    (r'^/failures(?:/|$)', 'integrations.manage'),
    (r'^/approvals(?:/|$)', 'approvals.manage'),
]


def uid(prefix: str) -> str:
    return prefix + '-' + uuid.uuid4().hex[:16].upper()


def initialise() -> None:
    with m.connect() as con:
        con.executescript(SCHEMA)
        for role, perms in ROLE_PERMISSIONS.items():
            if '*' in perms:
                con.execute("INSERT OR IGNORE INTO v11_role_permissions(role,permission,allowed) VALUES(?,?,1)",(role,'*'))
            else:
                for perm in perms:
                    con.execute("INSERT OR IGNORE INTO v11_role_permissions(role,permission,allowed) VALUES(?,?,1)",(role,perm))
        con.execute("INSERT OR IGNORE INTO v11_security_config(setting_key,setting_value) VALUES('auth_enabled','0')")
        con.execute("INSERT OR IGNORE INTO v11_security_config(setting_key,setting_value) VALUES('automation_mode','Manual')")
    refresh_identity_candidates()
    ensure_default_schedules()


def _sec(key: str, default: str='') -> str:
    try:
        row=m.one('SELECT setting_value FROM v11_security_config WHERE setting_key=?',(key,))
        return row['setting_value'] if row else default
    except sqlite3.OperationalError:
        # Pre-V11 workspaces/test fixtures can reach auth checks before migration.
        # Startup initialises the table before normal V11 use.
        return default


def set_sec(key: str, value: str) -> None:
    with m.connect() as con:
        con.execute('''INSERT INTO v11_security_config(setting_key,setting_value) VALUES(?,?)
                       ON CONFLICT(setting_key) DO UPDATE SET setting_value=excluded.setting_value,updated_at=CURRENT_TIMESTAMP''',(key,str(value)))


def auth_enabled() -> bool:
    return _sec('auth_enabled','0') == '1'


def automation_mode() -> str:
    # V20 keeps one owner-facing automation source of truth. Older V11 security
    # settings are read only as a fallback for migrated workspaces.
    try:
        row=m.one("SELECT setting_value FROM settings WHERE setting_key='v13_default_automation_level'")
        level=str((row or {}).get('setting_value') or '')
        mapped={'1':'Manual','2':'Assisted','3':'Automated','4':'Automated'}.get(level)
        if mapped:return mapped
    except Exception:
        pass
    mode=_sec('automation_mode','Manual')
    return mode if mode in {'Manual','Assisted','Automated'} else 'Manual'


def set_automation_mode(mode: str) -> None:
    if mode not in {'Manual','Assisted','Automated'}: raise ValueError('Choose Manual, Assisted or Automated.')
    level={'Manual':'1','Assisted':'2','Automated':'3'}[mode]
    # Keep the legacy security setting and the owner-facing automation level in
    # one transaction. V25 could silently save only one side and leave the UI
    # disagreeing with the automation engine after a database error.
    with m.connect() as con:
        con.execute('''INSERT INTO v11_security_config(setting_key,setting_value) VALUES('automation_mode',?)
                       ON CONFLICT(setting_key) DO UPDATE SET setting_value=excluded.setting_value,updated_at=CURRENT_TIMESTAMP''',(mode,))
        con.execute("INSERT INTO settings(setting_key,setting_value) VALUES('v13_default_automation_level',?) ON CONFLICT(setting_key) DO UPDATE SET setting_value=excluded.setting_value",(level,))


def _password_hash(password: str, salt: bytes) -> str:
    raw=hashlib.pbkdf2_hmac('sha256',password.encode('utf-8'),salt,310_000)
    return base64.urlsafe_b64encode(raw).decode('ascii')


def create_user(email: str, display_name: str, role: str, password: str) -> str:
    email=email.strip().lower();display_name=display_name.strip()
    if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',email):raise ValueError('Enter a valid email address.')
    if role not in ROLES:raise ValueError('Choose a valid role.')
    if len(password)<12:raise ValueError('Use at least 12 characters for the password.')
    if not display_name:raise ValueError('Enter the user name.')
    salt=secrets.token_bytes(16);uidv=uid('USR')
    with m.connect() as con:
        con.execute('INSERT INTO v11_users(user_id,email,display_name,role,password_salt,password_hash) VALUES(?,?,?,?,?,?)',
                    (uidv,email,display_name,role,base64.urlsafe_b64encode(salt).decode('ascii'),_password_hash(password,salt)))
    m.audit('user.created',uidv,role)
    return uidv


def users() -> list[dict]:
    return m.rows('SELECT user_id,email,display_name,role,active,created_at,last_login_at FROM v11_users ORDER BY active DESC,display_name COLLATE NOCASE')


def set_user_active(user_id: str, active: bool) -> None:
    row=m.one('SELECT user_id,role,active FROM v11_users WHERE user_id=?',(user_id,))
    if not row: raise ValueError('User not found.')
    if not active and row['role']=='Owner' and row['active']:
        owners=m.one("SELECT count(*) n FROM v11_users WHERE role='Owner' AND active=1")['n']
        if owners<=1: raise ValueError('Keep at least one active Owner account.')
    with m.connect() as con:
        con.execute('UPDATE v11_users SET active=? WHERE user_id=?',(1 if active else 0,user_id))
        if not active: con.execute('DELETE FROM v11_sessions WHERE user_id=?',(user_id,))
    m.audit('user.status_changed',user_id,'Active' if active else 'Disabled')


def reset_user_password(user_id: str, password: str) -> None:
    if len(password)<12: raise ValueError('Use at least 12 characters for the password.')
    if not m.one('SELECT 1 ok FROM v11_users WHERE user_id=?',(user_id,)): raise ValueError('User not found.')
    salt=secrets.token_bytes(16)
    with m.connect() as con:
        con.execute('UPDATE v11_users SET password_salt=?,password_hash=? WHERE user_id=?',(base64.urlsafe_b64encode(salt).decode('ascii'),_password_hash(password,salt),user_id))
        con.execute('DELETE FROM v11_sessions WHERE user_id=?',(user_id,))
    m.audit('user.password_reset',user_id,'Password reset; existing sessions revoked.')


def _login_guard_key(email: str, source: str='') -> str:
    raw=(email.strip().lower()+'|'+(source or 'local')).encode('utf-8')
    return hashlib.sha256(raw).hexdigest()


def _login_guard(email: str, source: str='') -> dict|None:
    return m.one('SELECT * FROM v11_login_guards WHERE guard_key=?',(_login_guard_key(email,source),))


def _record_login_failure(email: str, source: str='') -> None:
    key=_login_guard_key(email,source)
    now=dt.datetime.now(dt.UTC);row=_login_guard(email,source)
    count=1
    if row:
        try:
            started=dt.datetime.fromisoformat(str(row.get('window_started_at') or '').replace('Z','+00:00'))
            if started.tzinfo is None: started=started.replace(tzinfo=dt.UTC)
            if now-started <= dt.timedelta(minutes=15): count=int(row.get('failed_count') or 0)+1
        except Exception:
            pass
    lock=(now+dt.timedelta(minutes=15)).replace(microsecond=0).isoformat().replace('+00:00','Z') if count>=5 else None
    sql=("INSERT INTO v11_login_guards(guard_key,failed_count,window_started_at,last_failed_at,lock_until) "
         "VALUES(?,?,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP,?) "
         "ON CONFLICT(guard_key) DO UPDATE SET failed_count=?, "
         "window_started_at=CASE WHEN ?=1 THEN CURRENT_TIMESTAMP ELSE window_started_at END, "
         "last_failed_at=CURRENT_TIMESTAMP,lock_until=?")
    with m.connect() as con:
        con.execute(sql,(key,count,lock,count,1 if count==1 else 0,lock))


def authenticate(email: str, password: str, source: str='', otp: str='') -> tuple[dict,str]:
    guard=_login_guard(email,source)
    if guard and guard.get('lock_until'):
        try:
            until=dt.datetime.fromisoformat(str(guard['lock_until']).replace('Z','+00:00'))
            if until.tzinfo is None: until=until.replace(tzinfo=dt.UTC)
            if until > dt.datetime.now(dt.UTC): raise ValueError('Too many sign-in attempts. Try again in about 15 minutes.')
        except ValueError:
            raise
        except Exception:
            pass
    user=m.one('SELECT * FROM v11_users WHERE lower(email)=lower(?) AND active=1',(email.strip(),))
    if not user:
        _record_login_failure(email,source);raise ValueError('Email or password is incorrect.')
    try:
        salt=base64.urlsafe_b64decode(user['password_salt'].encode('ascii'))
    except Exception:
        raise ValueError('This account needs to be reset.') from None
    candidate=_password_hash(password,salt)
    if not hmac.compare_digest(candidate,user['password_hash']):
        _record_login_failure(email,source);raise ValueError('Email or password is incorrect.')
    if mfa_auth.required(user['user_id']) and not mfa_auth.validate(user['user_id'],otp):
        _record_login_failure(email,source);raise ValueError('Enter the current 6-digit authenticator code.')
    token=secrets.token_urlsafe(40);digest=hashlib.sha256(token.encode()).hexdigest();expiry=(dt.datetime.now(dt.UTC)+dt.timedelta(hours=12)).replace(microsecond=0).isoformat().replace('+00:00','Z')
    with m.connect() as con:
        con.execute('INSERT INTO v11_sessions(session_hash,user_id,expires_at) VALUES(?,?,?)',(digest,user['user_id'],expiry))
        con.execute('UPDATE v11_users SET last_login_at=CURRENT_TIMESTAMP WHERE user_id=?',(user['user_id'],))
        con.execute('DELETE FROM v11_login_guards WHERE guard_key=?',(_login_guard_key(email,source),))
    return {k:user[k] for k in ['user_id','email','display_name','role']},token


def session_user(cookie_header: str) -> dict|None:
    if not cookie_header:return None
    token=''
    for part in cookie_header.split(';'):
        k,sep,v=part.strip().partition('=')
        if sep and k=='crm_session':token=v;break
    if not token:return None
    digest=hashlib.sha256(token.encode()).hexdigest()
    row=m.one("""SELECT u.user_id,u.email,u.display_name,u.role,s.expires_at
                 FROM v11_sessions s JOIN v11_users u ON u.user_id=s.user_id
                 WHERE s.session_hash=? AND u.active=1 AND datetime(s.expires_at)>datetime('now')""",(digest,))
    if not row:return None
    with m.connect() as con:con.execute('UPDATE v11_sessions SET last_seen_at=CURRENT_TIMESTAMP WHERE session_hash=?',(digest,))
    return row


def logout_cookie(cookie_header: str) -> None:
    if not cookie_header:return
    for part in cookie_header.split(';'):
        k,sep,v=part.strip().partition('=')
        if sep and k=='crm_session':
            digest=hashlib.sha256(v.encode()).hexdigest()
            with m.connect() as con:con.execute('DELETE FROM v11_sessions WHERE session_hash=?',(digest,))
            break


def can(user: dict|None, permission: str) -> bool:
    if not auth_enabled():return True
    if not user:return False
    role=user.get('role','')
    if role=='Owner':return True
    # A manage grant includes the corresponding read grant. Earlier betas stored
    # least-privilege role rows such as contacts.manage/sales.manage without also
    # duplicating contacts.read/sales.read, which incorrectly blocked those roles
    # from opening the very records they were allowed to manage.
    candidates=[permission]
    if permission.endswith('.read'):
        candidates.append(permission[:-5]+'.manage')
    placeholders=','.join('?' for _ in candidates)
    row=m.one(
        f"SELECT allowed FROM v11_role_permissions WHERE role=? AND (permission IN ({placeholders}) OR permission='*') ORDER BY CASE permission WHEN '*' THEN 1 ELSE 0 END LIMIT 1",
        (role,*candidates)
    )
    return bool(row and row['allowed'])


def permission_for_path(path: str, method: str='GET') -> str:
    # V26 fails closed for writes. Hidden buttons are not authorization.
    # Route-specific mutations are checked before broad feature families.
    method=(method or 'GET').upper()
    if method not in {'GET','HEAD'}:
        for pattern,permission in WRITE_PATH_PERMISSIONS:
            if re.match(pattern,path):
                return permission
    for pattern,base in PATH_PERMISSIONS:
        if re.match(pattern,path):
            if method not in {'GET','HEAD'} and base.endswith('.read'):
                return base[:-5]+'.manage'
            return base
    # Unknown read pages may still be general workspace screens. Unknown
    # mutations are owner/admin configuration until they receive an explicit
    # least-privilege mapping; never let a write fall back to workspace.read.
    return 'workspace.read' if method in {'GET','HEAD'} else 'settings.manage'


def approval(action_type: str, object_type: str, object_id: str, summary: str, risk_level='Medium', requested_by='') -> str:
    if risk_level not in {'Low','Medium','High','Critical'}:risk_level='Medium'
    aid=uid('APR')
    with m.connect() as con:
        con.execute('INSERT INTO v11_approvals(id,action_type,object_type,object_id,summary,risk_level,requested_by) VALUES(?,?,?,?,?,?,?)',
                    (aid,action_type,object_type,object_id,summary[:2000],risk_level,requested_by))
    return aid


def approvals(status='Pending',limit=200)->list[dict]:
    if status:return m.rows('SELECT * FROM v11_approvals WHERE status=? ORDER BY CASE risk_level WHEN \'Critical\' THEN 1 WHEN \'High\' THEN 2 WHEN \'Medium\' THEN 3 ELSE 4 END,created_at DESC LIMIT ?',(status,limit))
    return m.rows('SELECT * FROM v11_approvals ORDER BY created_at DESC LIMIT ?',(limit,))


def decide_approval(aid: str, decision: str, user_id='', note='') -> None:
    if decision not in {'Approved','Rejected'}:raise ValueError('Choose Approved or Rejected.')
    with m.connect() as con:
        if not con.execute("SELECT 1 FROM v11_approvals WHERE id=? AND status='Pending'",(aid,)).fetchone():raise ValueError('Approval is no longer pending.')
        con.execute('UPDATE v11_approvals SET status=?,decided_by=?,decision_note=?,decided_at=CURRENT_TIMESTAMP WHERE id=?',(decision,user_id,note[:1000],aid))


def external_action_policy(action_type: str, risk='Medium') -> str:
    """Return auto/review/manual based on owner automation mode. External sends/publishes never auto in Manual."""
    mode=automation_mode()
    if mode=='Manual':return 'manual'
    if mode=='Assisted':return 'auto' if risk=='Low' and action_type.startswith('internal.') else 'review'
    # Automated: only pre-approved low-risk internal or transactional actions auto; paid ads, cold outreach and refunds still review.
    if risk in {'High','Critical'} or action_type.startswith(('paid_ads.','cold_outreach.','refund.','discount.large')):return 'review'
    return 'auto'


def ensure_default_schedules() -> None:
    defaults=[
        ('business-jobs','business_jobs','',15,{}),
        ('growth-recommendations','recommendations','',60,{}),
        ('integration-health','integration_health','',60,{}),
    ]
    with m.connect() as con:
        for key,jtype,cid,mins,payload in defaults:
            con.execute('''INSERT OR IGNORE INTO v11_schedules(id,job_key,job_type,connection_id,payload_json,interval_minutes)
                           VALUES(?,?,?,?,?,?)''',(uid('SCH'),key,jtype,cid,json.dumps(payload),mins))


def ensure_connection_schedule(connection_id: str, interval_minutes: int=60) -> None:
    key='sync-'+connection_id
    with m.connect() as con:
        con.execute('''INSERT INTO v11_schedules(id,job_key,job_type,connection_id,payload_json,interval_minutes,enabled,next_run_at)
                       VALUES(?,?,?,?,?,?,1,datetime('now','+5 minutes'))
                       ON CONFLICT(job_key) DO UPDATE SET interval_minutes=excluded.interval_minutes,enabled=1,updated_at=CURRENT_TIMESTAMP''',
                    (uid('SCH'),key,'sync_connection',connection_id,'{}',max(15,min(interval_minutes,1440))))


def schedules()->list[dict]:
    return m.rows('SELECT * FROM v11_schedules ORDER BY enabled DESC,next_run_at,job_key')


def save_schedule(job_key:str,interval_minutes:int,enabled:bool) -> None:
    with m.connect() as con:
        if not con.execute('SELECT 1 FROM v11_schedules WHERE job_key=?',(job_key,)).fetchone():raise ValueError('Schedule not found.')
        con.execute("UPDATE v11_schedules SET interval_minutes=?,enabled=?,next_run_at=CASE WHEN ? THEN datetime('now','+1 minute') ELSE next_run_at END,updated_at=CURRENT_TIMESTAMP WHERE job_key=?",
                    (max(15,min(int(interval_minutes),10080)),1 if enabled else 0,1 if enabled else 0,job_key))


def _run_schedule(row: dict) -> str:
    if row['job_type']=='business_jobs':
        out=bos.run_jobs(100);return json.dumps(out)
    if row['job_type']=='recommendations':
        return str(bos.generate_recommendations())+' recommendations refreshed'
    if row['job_type']=='sync_connection':
        import integration_v14 as int14
        out=int14.sync_connection(row['connection_id']);return json.dumps(out)[:1500]
    if row['job_type']=='integration_health':
        import integration_v14 as int14
        return json.dumps(int14.run_health_checks())[:1500]
    raise ValueError('Unknown scheduled job type.')


def run_due_schedules(limit=20) -> dict:
    due=m.rows("SELECT * FROM v11_schedules WHERE enabled=1 AND datetime(next_run_at)<=datetime('now') ORDER BY next_run_at LIMIT ?",(limit,))
    ok=failed=0
    for row in due:
        try:
            detail=_run_schedule(row);ok+=1
            with m.connect() as con:con.execute("UPDATE v11_schedules SET last_run_at=CURRENT_TIMESTAMP,last_status='Completed',last_error='',next_run_at=datetime('now',?),updated_at=CURRENT_TIMESTAMP WHERE id=?",(f'+{int(row["interval_minutes"])} minutes',row['id']))
            m.audit('schedule.completed',row['id'],detail)
        except Exception as exc:
            failed+=1;bos.failure('scheduler',str(exc),'Open Integration Health or System Health, fix the connection, then use Sync now.', 'schedule',row['id'],'Error')
            with m.connect() as con:con.execute("UPDATE v11_schedules SET last_run_at=CURRENT_TIMESTAMP,last_status='Failed',last_error=?,next_run_at=datetime('now',?),updated_at=CURRENT_TIMESTAMP WHERE id=?",(str(exc)[:1200],f'+{min(max(int(row["interval_minutes"]),15),60)} minutes',row['id']))
    return {'run':len(due),'completed':ok,'failed':failed}


_scheduler_started=False
_scheduler_lock=threading.Lock()

def start_scheduler() -> None:
    global _scheduler_started
    with _scheduler_lock:
        if _scheduler_started:return
        _scheduler_started=True
    def loop():
        while True:
            try:run_due_schedules()
            except Exception as exc:
                try:bos.failure('scheduler.loop',str(exc),'Restart the CRM if the scheduler continues failing.','','','Error')
                except Exception:pass
            time.sleep(30)
    threading.Thread(target=loop,name='commerce-crm-scheduler',daemon=True).start()


def _norm_email(v:str)->str:return (v or '').strip().lower()
def _norm_phone(v:str)->str:return re.sub(r'\D','',v or '')
def _norm_social(v:str)->str:return (v or '').strip().lstrip('@').lower()


def refresh_identity_candidates() -> dict:
    rows=m.rows('SELECT contact_id,email,phone_number,username FROM contacts ORDER BY contact_id')
    buckets:dict[tuple[str,str],list[str]]={}
    for r in rows:
        for typ,val in [('email',_norm_email(r.get('email',''))),('phone',_norm_phone(r.get('phone_number',''))),('social',_norm_social(r.get('username','')))]:
            if val:buckets.setdefault((typ,val),[]).append(r['contact_id'])
    pairs:dict[tuple[str,str],dict[str,list[str]]]={}
    for (typ,val),ids in buckets.items():
        if len(ids)<2:continue
        base=ids[0]
        for dup in ids[1:]:
            key=tuple(sorted([base,dup]));data=pairs.setdefault(key,{'types':[],'values':[]});data['types'].append(typ);data['values'].append(val)
    created=0
    with m.connect() as con:
        for (a,b),data in pairs.items():
            primary,dup=(a,b)
            existing=con.execute('SELECT status FROM v11_identity_candidates WHERE primary_contact_id=? AND duplicate_contact_id=?',(primary,dup)).fetchone()
            if existing:continue
            con.execute('INSERT INTO v11_identity_candidates(id,primary_contact_id,duplicate_contact_id,match_types_json,match_values_json) VALUES(?,?,?,?,?)',
                        (uid('IDR'),primary,dup,json.dumps(data['types']),json.dumps(data['values'])));created+=1
    return {'candidate_pairs':len(pairs),'created':created}


def identity_candidates(status='Needs review',limit=200)->list[dict]:
    sql='''SELECT x.*,coalesce(a.full_name,a.username,a.email,a.phone_number,a.contact_id) primary_name,
                  coalesce(b.full_name,b.username,b.email,b.phone_number,b.contact_id) duplicate_name
           FROM v11_identity_candidates x JOIN contacts a ON a.contact_id=x.primary_contact_id JOIN contacts b ON b.contact_id=x.duplicate_contact_id'''
    args=[]
    if status:sql+=' WHERE x.status=?';args.append(status)
    sql+=' ORDER BY x.created_at DESC LIMIT ?';args.append(limit)
    out=m.rows(sql,tuple(args))
    for r in out:r['match_types']=json.loads(r.get('match_types_json') or '[]');r['match_values']=json.loads(r.get('match_values_json') or '[]')
    return out


def dismiss_identity_candidate(candidate_id:str)->None:
    with m.connect() as con:con.execute("UPDATE v11_identity_candidates SET status='Not a duplicate',reviewed_at=CURRENT_TIMESTAMP WHERE id=?",(candidate_id,))


def merge_preview(candidate_id:str)->dict:
    cand=m.one('SELECT * FROM v11_identity_candidates WHERE id=?',(candidate_id,))
    if not cand:raise ValueError('Identity candidate not found.')
    a=m.one('SELECT * FROM contacts WHERE contact_id=?',(cand['primary_contact_id'],));b=m.one('SELECT * FROM contacts WHERE contact_id=?',(cand['duplicate_contact_id'],))
    if not a or not b:raise ValueError('One of the contact records no longer exists.')
    conflicts=[];fillable=[]
    for field in ['full_name','email','phone_number','username','website','country','language','niche','business_category','contact_type','lifecycle_stage']:
        av=str(a.get(field) or '').strip();bv=str(b.get(field) or '').strip()
        if not av and bv:fillable.append((field,bv))
        elif av and bv and av.lower()!=bv.lower():conflicts.append((field,av,bv))
    return {'candidate':cand,'primary':a,'duplicate':b,'conflicts':conflicts,'fillable':fillable}


def _pragma_column_name(row) -> str:
    # sqlite3.Row exposes the name at index 1; the PostgreSQL compatibility
    # layer exposes an explicit `name` field. Prefer the semantic field.
    try:return str(row['name'])
    except (TypeError,KeyError,IndexError):return str(row[1])


def _table_has_column(con:sqlite3.Connection,table:str,column:str)->bool:
    return any(_pragma_column_name(r)==column for r in con.execute(f'PRAGMA table_info("{table}")'))


def merge_contacts(candidate_id:str,merged_by='')->dict:
    prev=merge_preview(candidate_id);cand=prev['candidate'];primary=cand['primary_contact_id'];dup=cand['duplicate_contact_id']
    critical={'email','phone_number','username','full_name'}
    if any(field in critical for field,_,_ in prev['conflicts']):raise ValueError('Merge blocked because core identity fields conflict. Edit the records first, then review again.')
    snapshot={'primary':prev['primary'],'duplicate':prev['duplicate'],'fillable':prev['fillable'],'conflicts':prev['conflicts']}
    simple_tables=['activities','interactions','opportunities','orders','v9_delivery_events','v9_attribution_touchpoints','m4_tasks','v10_campaign_sends','v11_privacy_requests']
    with m.connect() as con:
        con.execute('BEGIN IMMEDIATE')
        try:
            for field,val in prev['fillable']:
                if re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*',field):con.execute(f"UPDATE contacts SET \"{field}\"=? WHERE contact_id=? AND (\"{field}\" IS NULL OR \"{field}\"='')",(val,primary))
            for table in simple_tables:
                if _table_has_column(con,table,'contact_id'):con.execute(f'UPDATE "{table}" SET contact_id=? WHERE contact_id=?',(primary,dup))

            # Copy set-like relationships without duplicating rows.
            for table,cols in [
                ('contact_companies',['company_id','role_title','is_primary']),('campaign_members',['campaign_id','member_status']),
                ('m41_tags',['tag']),('m41_sources',['source','import_id']),('m42_values',['property_id','value']),('m42_enrolments',['rule_id','plan_id'])]:
                if not _table_has_column(con,table,'contact_id'):continue
                available={_pragma_column_name(r) for r in con.execute(f'PRAGMA table_info("{table}")')};cols=[c for c in cols if c in available]
                if not cols:continue
                rows=con.execute(f'SELECT {",".join(cols)} FROM "{table}" WHERE contact_id=?',(dup,)).fetchall()
                placeholders=','.join('?' for _ in range(len(cols)+1));colsql='contact_id,'+','.join(cols)
                for row in rows:con.execute(f'INSERT OR IGNORE INTO "{table}"({colsql}) VALUES({placeholders})',(primary,*tuple(row)))
                con.execute(f'DELETE FROM "{table}" WHERE contact_id=?',(dup,))

            # One-row profile/meta tables: keep primary, fill its blank values from duplicate when possible.
            for table in ['m41_profile','m42_contact_meta','m4_preferences']:
                if not _table_has_column(con,table,'contact_id'):continue
                prow=con.execute(f'SELECT * FROM "{table}" WHERE contact_id=?',(primary,)).fetchone();drow=con.execute(f'SELECT * FROM "{table}" WHERE contact_id=?',(dup,)).fetchone()
                if not drow:continue
                columns=[_pragma_column_name(x) for x in con.execute(f'PRAGMA table_info("{table}")') if _pragma_column_name(x) != 'contact_id']
                if not prow:
                    con.execute(f'UPDATE "{table}" SET contact_id=? WHERE contact_id=?',(primary,dup))
                else:
                    for col in columns:
                        if (prow[col] is None or str(prow[col])=='') and drow[col] not in (None,''):
                            con.execute(f'UPDATE "{table}" SET "{col}"=? WHERE contact_id=?',(drow[col],primary))
                    con.execute(f'DELETE FROM "{table}" WHERE contact_id=?',(dup,))

            # Permissions are merged channel-by-channel; never let a merge weaken an opt-out/suppression.
            if _table_has_column(con,'marketing_permissions','contact_id'):
                rank={'Unknown':0,'Allowed':1,'OptedIn':2,'OptedOut':3,'DoNotContact':4,'Suppressed':5}
                for dperm in con.execute('SELECT * FROM marketing_permissions WHERE contact_id=?',(dup,)).fetchall():
                    channel=dperm['channel'];pp=con.execute('SELECT * FROM marketing_permissions WHERE contact_id=? AND channel=? ORDER BY updated_at DESC LIMIT 1',(primary,channel)).fetchone()
                    if not pp:
                        con.execute('UPDATE marketing_permissions SET contact_id=? WHERE permission_id=?',(primary,dperm['permission_id']));continue
                    chosen=dperm if rank.get(dperm['status'],0)>rank.get(pp['status'],0) else pp
                    con.execute('''UPDATE marketing_permissions SET status=?,lawful_basis_or_reason=?,evidence_reference=?,jurisdiction=?,updated_at=CURRENT_TIMESTAMP WHERE permission_id=?''',
                                (chosen['status'],chosen['lawful_basis_or_reason'],chosen['evidence_reference'],chosen['jurisdiction'],pp['permission_id']))
                    con.execute('DELETE FROM marketing_permissions WHERE permission_id=?',(dperm['permission_id'],))
                # Collapse any historical duplicates on the primary, keeping the most restrictive/latest evidence.
                for channel in [r[0] for r in con.execute('SELECT DISTINCT channel FROM marketing_permissions WHERE contact_id=?',(primary,))]:
                    perms=con.execute('SELECT * FROM marketing_permissions WHERE contact_id=? AND channel=? ORDER BY updated_at DESC',(primary,channel)).fetchall()
                    if len(perms)>1:
                        chosen=max(perms,key=lambda r:(rank.get(r['status'],0),str(r['updated_at'] or '')));keep=perms[0]['permission_id']
                        con.execute('UPDATE marketing_permissions SET status=?,lawful_basis_or_reason=?,evidence_reference=?,jurisdiction=?,updated_at=CURRENT_TIMESTAMP WHERE permission_id=?',(chosen['status'],chosen['lawful_basis_or_reason'],chosen['evidence_reference'],chosen['jurisdiction'],keep))
                        for r in perms[1:]:con.execute('DELETE FROM marketing_permissions WHERE permission_id=?',(r['permission_id'],))

            # Rebuild identities after commit instead of mutating the uniqueness-constrained identity index in place.
            if _table_has_column(con,'v9_identities','contact_id'):con.execute('DELETE FROM v9_identities WHERE contact_id IN (?,?)',(primary,dup))
            con.execute('DELETE FROM contacts WHERE contact_id=?',(dup,))
            con.execute("UPDATE v11_identity_candidates SET status='Merged',reviewed_at=CURRENT_TIMESTAMP WHERE id=?",(candidate_id,))
            con.execute("UPDATE v11_identity_candidates SET status='Superseded',reviewed_at=CURRENT_TIMESTAMP WHERE status='Needs review' AND id<>? AND (primary_contact_id=? OR duplicate_contact_id=?)",(candidate_id,dup,dup))
            con.execute('INSERT INTO v11_merge_history(id,primary_contact_id,duplicate_contact_id,snapshot_json,merged_by) VALUES(?,?,?,?,?)',(uid('MRG'),primary,dup,json.dumps(snapshot,default=str),merged_by))
            con.commit()
        except Exception:
            con.rollback();raise
    bos.rebuild_identity_index();m.audit('contact.merged',primary,f'Merged duplicate {dup}')
    return {'primary_contact_id':primary,'duplicate_contact_id':dup}


def privacy_requests(status='Open',limit=200) -> list[dict]:
    sql='''SELECT r.*,coalesce(c.full_name,c.username,c.email,c.phone_number,c.contact_id) contact_name
           FROM v11_privacy_requests r JOIN contacts c ON c.contact_id=r.contact_id'''
    args=[]
    if status: sql+=' WHERE r.status=?';args.append(status)
    sql+=' ORDER BY r.requested_at DESC LIMIT ?';args.append(limit)
    return m.rows(sql,tuple(args))


def create_privacy_request(contact_id:str,request_type:str,notes='')->str:
    if request_type not in {'Export','Correction','Deletion / anonymisation','Consent review'}: raise ValueError('Choose a valid privacy request type.')
    if not m.one('SELECT 1 ok FROM contacts WHERE contact_id=?',(contact_id,)): raise ValueError('Contact not found.')
    rid=uid('PRV')
    with m.connect() as con:con.execute('INSERT INTO v11_privacy_requests(id,contact_id,request_type,notes) VALUES(?,?,?,?)',(rid,contact_id,request_type,str(notes)[:2000]))
    m.audit('privacy.request_created',rid,request_type);return rid


def contact_portability(contact_id:str)->dict:
    data=bos.customer_360(contact_id)
    # Add only business records explicitly linked to this contact. Provider secrets/configuration are never exported.
    data['companies']=m.rows('''SELECT co.* FROM companies co JOIN contact_companies cc ON cc.company_id=co.company_id WHERE cc.contact_id=?''',(contact_id,))
    data['privacy_requests']=m.rows('SELECT * FROM v11_privacy_requests WHERE contact_id=? ORDER BY requested_at DESC',(contact_id,))
    data['generated_at']=dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat().replace('+00:00','Z')
    return data


def anonymize_contact(contact_id:str,completed_by='')->None:
    c=m.one('SELECT * FROM contacts WHERE contact_id=?',(contact_id,))
    if not c: raise ValueError('Contact not found.')
    anon='ANON-'+hashlib.sha256(contact_id.encode()).hexdigest()[:12].upper()
    with m.connect() as con:
        con.execute('BEGIN IMMEDIATE')
        try:
            con.execute('''UPDATE contacts SET username=NULL,first_name=NULL,full_name=?,email=NULL,phone_number=NULL,phone_country_code=NULL,website=NULL,biography=NULL,
                           country=NULL,language=NULL,niche=NULL,entity_type=NULL,followers=NULL,following=NULL,qualification_status='Do not contact',lifecycle_stage='Inactive',
                           relevance_reason='Personal data anonymised by an approved privacy request.',data_quality='Anonymised',next_follow_up=NULL WHERE contact_id=?''',(anon,contact_id))
            con.execute("UPDATE marketing_permissions SET status='DoNotContact',lawful_basis_or_reason='Personal data anonymised / contact closed',evidence_reference='',updated_at=CURRENT_TIMESTAMP WHERE contact_id=?",(contact_id,))
            con.execute('DELETE FROM v9_identities WHERE contact_id=?',(contact_id,))
            con.execute("UPDATE v11_privacy_requests SET status='Completed',completed_at=CURRENT_TIMESTAMP,completed_by=? WHERE contact_id=? AND request_type='Deletion / anonymisation' AND status='Open'",(completed_by,contact_id))
            con.commit()
        except Exception:
            con.rollback();raise
    m.audit('privacy.contact_anonymised',contact_id,'PII cleared; linked commercial records retained under anonymised contact ID.')


def complete_privacy_request(request_id:str,completed_by='',notes='')->None:
    with m.connect() as con:
        row=con.execute('SELECT * FROM v11_privacy_requests WHERE id=?',(request_id,)).fetchone()
        if not row: raise ValueError('Privacy request not found.')
        con.execute("UPDATE v11_privacy_requests SET status='Completed',completed_at=CURRENT_TIMESTAMP,completed_by=?,notes=CASE WHEN ?<>'' THEN ? ELSE notes END WHERE id=?",(completed_by,notes,notes,request_id))


def _ensure_stock_location_schema() -> None:
    """Ensure the small V9 stock/location dependency is safe when this module is used standalone.

    Normal application startup initialises business_os first. Component tests, repair tools,
    and narrowly scoped scripts can legitimately initialise platform_core directly, so the
    stock pages must not fail merely because the broader V9 bootstrap has not run yet.
    """
    with m.connect() as con:
        con.executescript(r"""
        CREATE TABLE IF NOT EXISTS v9_brands(
          id TEXT PRIMARY KEY, name TEXT NOT NULL, default_currency TEXT DEFAULT 'INR', default_language TEXT DEFAULT 'English',
          status TEXT DEFAULT 'Active', created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS v9_locations(
          id TEXT PRIMARY KEY, brand_id TEXT, name TEXT NOT NULL, location_type TEXT NOT NULL DEFAULT 'Warehouse',
          country TEXT DEFAULT '', city TEXT DEFAULT '', address TEXT DEFAULT '', timezone TEXT DEFAULT '', status TEXT DEFAULT 'Active'
        );
        CREATE TABLE IF NOT EXISTS v9_inventory(
          product_id TEXT NOT NULL, location_id TEXT NOT NULL, on_hand INTEGER DEFAULT 0, reserved INTEGER DEFAULT 0,
          reorder_point INTEGER DEFAULT 0, updated_at TEXT DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY(product_id, location_id)
        );
        CREATE INDEX IF NOT EXISTS v9_inventory_product ON v9_inventory(product_id);
        """)


def brands() -> list[dict]:
    _ensure_stock_location_schema()
    return m.rows('SELECT * FROM v9_brands ORDER BY status DESC,name COLLATE NOCASE')


def save_brand(name: str, currency='INR', language='English', brand_id='') -> str:
    _ensure_stock_location_schema()
    name=(name or '').strip();currency=(currency or 'INR').strip().upper()[:8];language=(language or 'English').strip()[:80]
    if not name: raise ValueError('Enter the brand name.')
    bid=brand_id or uid('BRD')
    with m.connect() as con:
        con.execute('''INSERT INTO v9_brands(id,name,default_currency,default_language,status) VALUES(?,?,?,?,'Active')
                       ON CONFLICT(id) DO UPDATE SET name=excluded.name,default_currency=excluded.default_currency,default_language=excluded.default_language''',(bid,name,currency,language))
    m.audit('brand.saved',bid,name);return bid


def locations() -> list[dict]:
    _ensure_stock_location_schema()
    return m.rows('''SELECT l.*,b.name brand_name,
                     coalesce(sum(i.on_hand),0) on_hand,coalesce(sum(i.reserved),0) reserved,
                     sum(CASE WHEN i.on_hand-i.reserved<=i.reorder_point THEN 1 ELSE 0 END) low_stock_skus
                     FROM v9_locations l LEFT JOIN v9_brands b ON b.id=l.brand_id LEFT JOIN v9_inventory i ON i.location_id=l.id
                     GROUP BY l.id ORDER BY l.status DESC,l.name COLLATE NOCASE''')


def save_location(data: dict) -> str:
    _ensure_stock_location_schema()
    name=str(data.get('name') or '').strip();kind=str(data.get('location_type') or 'Warehouse').strip()
    if not name: raise ValueError('Enter a location name.')
    if kind not in {'Warehouse','Showroom','Studio','Consignment','Other'}: raise ValueError('Choose a valid location type.')
    lid=str(data.get('id') or '').strip() or uid('LOC')
    with m.connect() as con:
        con.execute('''INSERT INTO v9_locations(id,brand_id,name,location_type,country,city,address,timezone,status)
                       VALUES(?,?,?,?,?,?,?,?,?)
                       ON CONFLICT(id) DO UPDATE SET brand_id=excluded.brand_id,name=excluded.name,location_type=excluded.location_type,
                       country=excluded.country,city=excluded.city,address=excluded.address,timezone=excluded.timezone,status=excluded.status''',
                    (lid,str(data.get('brand_id') or '') or None,name,kind,str(data.get('country') or '')[:120],str(data.get('city') or '')[:120],str(data.get('address') or '')[:800],str(data.get('timezone') or '')[:80],str(data.get('status') or 'Active')[:40]))
    m.audit('location.saved',lid,name);return lid


def location_inventory(location_id: str) -> list[dict]:
    _ensure_stock_location_schema()
    if not m.one('SELECT 1 ok FROM v9_locations WHERE id=?',(location_id,)): raise ValueError('Stock location not found.')
    return m.rows('''SELECT p.product_id,p.internal_sku,p.public_product_name,p.status,
                     coalesce(i.on_hand,0) on_hand,coalesce(i.reserved,0) reserved,coalesce(i.reorder_point,0) reorder_point
                     FROM products p LEFT JOIN v9_inventory i ON i.product_id=p.product_id AND i.location_id=?
                     WHERE coalesce(p.status,'Draft')<>'Archived'
                     ORDER BY coalesce(p.public_product_name,p.internal_sku,p.product_id) COLLATE NOCASE''',(location_id,))


def save_location_inventory(location_id: str, product_id: str, on_hand: int, reserved: int|None=None, reorder_point: int=0, reason: str='Manual stock adjustment', actor_user_id: str='') -> None:
    """Adjust canonical location stock through an auditable movement.

    ``reserved`` remains accepted for backwards-compatible administrative/test
    callers, but the owner UI no longer exposes it.  In normal V35 operation
    reservations are derived from reservation/consumption movements.
    """
    _ensure_stock_location_schema();truth.initialise()
    if not m.one('SELECT 1 ok FROM v9_locations WHERE id=?',(location_id,)): raise ValueError('Stock location not found.')
    p=m.one('SELECT status FROM products WHERE product_id=?',(product_id,))
    if not p: raise ValueError('Product not found.')
    if p.get('status')=='Archived': raise ValueError('This product is archived. Restore it before changing inventory.')
    rp=max(0,int(reorder_point));truth.adjust_stock_to(product_id,location_id,max(0,int(on_hand)),reason or 'Manual stock adjustment',actor_user_id,rp)
    if reserved is not None:
        current=int((m.one('SELECT reserved FROM v9_inventory WHERE product_id=? AND location_id=?',(product_id,location_id)) or {'reserved':0}).get('reserved') or 0)
        if max(0,int(reserved))!=current:
            raise ValueError('Reserved stock is derived from active orders and cannot be edited directly. Release/cancel the related order reservation instead.')
    row=truth.canonical_inventory(product_id,location_id);available=int(row['available'])
    m.audit('inventory.location_adjusted',product_id,f'{location_id}: on_hand={row["on_hand"]}, reserved={row["reserved"]}, available={available}, reorder={rp}; reason={reason}')
    if available<=rp:
        try:
            import operating_core as oc
            oc.emit_event('INVENTORY_LOW','product',product_id,{'location_id':location_id,'available':available,'reorder_point':rp},dedupe_key=f'inventory-low:{product_id}:{location_id}:{available}:{rp}')
        except Exception:pass

def stock_alerts(limit=100) -> list[dict]:
    _ensure_stock_location_schema()
    return m.rows('''SELECT i.*,l.name location_name,p.internal_sku,p.public_product_name
                     FROM v9_inventory i JOIN v9_locations l ON l.id=i.location_id JOIN products p ON p.product_id=i.product_id
                     WHERE coalesce(l.status,'Active')='Active' AND i.on_hand-i.reserved<=i.reorder_point ORDER BY (i.on_hand-i.reserved) ASC LIMIT ?''',(limit,))


def connection_health() -> list[dict]:
    import integration_layer as il
    out=[]
    for key,meta in il.CONNECTOR_CATALOG.items():
        conns=il.connections(key)
        if not conns:
            out.append({'connector_key':key,'label':meta['label'],'category':meta['category'],'implemented':meta.get('implemented',False),'status':'Available to connect' if meta.get('implemented') else 'Unsupported / planned','account':'','last_sync':'','last_success':'','last_error':'','schedule':''})
            continue
        for c in conns:
            sch=m.one('SELECT * FROM v11_schedules WHERE connection_id=?',(c['id'],))
            out.append({'connector_key':key,'label':meta['label'],'category':meta['category'],'implemented':meta.get('implemented',False),'status':c['status'],'account':c.get('account_name') or c.get('label'),'last_sync':c.get('last_sync_at') or '', 'last_success':c.get('last_success_at') or '', 'last_error':c.get('last_error') or '', 'connection_id':c['id'],'schedule':sch})
    return out


def run_e2e_test() -> str:
    """Non-destructive 22-step operational audit. Never sends, publishes, charges, or changes provider budgets."""
    rid=uid('E2E')
    with m.connect() as con:con.execute('INSERT INTO v11_e2e_runs(id) VALUES(?)',(rid,))
    steps=[]
    def add(label,status,detail):
        steps.append((len(steps)+1,label,status,detail))
    def table(name):
        return m.table_exists(name)
    def count(sql,args=()):
        try:return int((m.one(sql,args) or {'n':0})['n'])
        except Exception as exc:
            if db_layer.is_database_error(exc):return 0
            raise
    health=connection_health()
    def conn(key):
        return next((x for x in health if x['connector_key']==key and x['status']=='Connected'),None)
    products=count('SELECT count(*) n FROM products');images=count('SELECT count(*) n FROM product_images')
    intakes=count('SELECT count(*) n FROM v6_product_intakes') if table('v6_product_intakes') else 0
    add('1. Raw image upload','Pass' if table('v6_product_intakes') else 'Blocked',f'Product intake engine available; {intakes} historical intake(s), {images} product image record(s).')
    ai_ready=bool(m.secret());facts=count('SELECT count(*) n FROM v6_product_fields') if table('v6_product_fields') else 0
    add('2. AI product understanding','Pass' if ai_ready else 'Needs setup',f'{facts} extracted/reviewable product fact record(s). '+('AI key is configured.' if ai_ready else 'Connect AI for multimodal understanding; filename-based local parsing remains available.'))
    add('3. Product record creation','Pass' if products else 'Blocked',f'{products} product record(s).')
    described=count("SELECT count(*) n FROM products WHERE coalesce(description,'')<>''")
    add('4. Description and metadata generation','Pass' if described else ('Needs data' if products else 'Blocked'),f'{described}/{products} products currently have a description; SEO/product-engine tables are available.' if products else 'No products yet.')
    prepared=count("SELECT count(*) n FROM v6_product_assets") if table('v6_product_assets') else 0
    add('5. Product image enhancement','Pass' if prepared else ('Needs data' if images else 'Blocked'),f'{prepared} prepared derivative asset(s); originals remain separate from derivatives.')
    master_jobs=count("SELECT count(*) n FROM v7_creative_jobs") if table('v7_creative_jobs') else 0
    add('6. Mannequin / model generation','Pass' if ai_ready and table('v7_creative_jobs') else 'Needs setup',f'Creative Studio master-generation queue available; {master_jobs} master job(s). Paid/reference image generation still requires a configured AI provider and review.')
    social_assets=count("SELECT count(*) n FROM v8_creative_campaign_assets a JOIN v8_creative_campaign_placements p ON p.campaign_id=a.campaign_id AND p.placement_key=a.placement_key WHERE p.placement_key LIKE 'ig_%' OR p.placement_key LIKE 'fb_%' OR p.placement_key LIKE 'meta_%'") if table('v8_creative_campaign_assets') else 0
    add('7. Social creatives','Pass' if table('v8_creative_campaign_assets') else 'Blocked',f'{social_assets} social creative asset record(s); deterministic format generation can run without publishing.')
    ad_assets=count("SELECT count(*) n FROM v8_creative_campaign_assets WHERE placement_key LIKE 'google_%' OR placement_key LIKE 'gdn_%' OR placement_key LIKE 'meta_%'") if table('v8_creative_campaign_assets') else 0
    add('8. Advertising creatives','Pass' if table('v8_creative_campaign_assets') else 'Blocked',f'{ad_assets} Meta/Google-oriented creative asset record(s).')
    video_assets=count("SELECT count(*) n FROM v8_video_jobs WHERE status IN ('Rendered','Completed','Approved')") if table('v8_video_jobs') else 0
    add('9. Promotional video generation','Pass' if table('v8_video_jobs') else 'Needs setup',f'Video job workflow available; {video_assets} completed/rendered video job(s). Generative video remains provider-dependent and product-fidelity review is required.')
    shop=conn('shopify')
    add('10. Connected store preparation','Pass' if shop else 'Needs setup',(shop or {}).get('account','No verified Shopify connection. Products can be prepared locally but not synchronised live.'))
    social=conn('meta_social')
    add('11. Organic social campaign path','Pass' if social else 'Needs setup',(social or {}).get('account','Connect Meta organic to publish supported Instagram/Facebook content.'))
    email=conn('resend')
    add('12. Email campaign path','Pass' if email else 'Needs setup',(email or {}).get('account','No verified email transport/domain connection.'))
    wa=conn('whatsapp_cloud')
    add('13. WhatsApp campaign path','Pass' if wa else 'Needs setup',(wa or {}).get('account','No verified WhatsApp Business Cloud connection.'))
    meta=conn('meta_ads')
    add('14. Meta advertising preparation','Needs setup' if meta else 'Needs setup','Meta Ads read/sync is available when connected; paid campaign creation/activation remains deliberately unavailable until write permissions, conversion tracking and approval limits are production-configured.')
    google=conn('google_ads')
    add('15. Google advertising preparation','Needs setup','Google Ads read/sync is available when connected; campaign write/activation remains deliberately unavailable in this build.')
    engagement=count('SELECT count(*) n FROM v9_delivery_events')+count('SELECT count(*) n FROM interactions')
    add('16. Campaign engagement into CRM','Pass' if table('v9_delivery_events') and table('interactions') else 'Blocked',f'{engagement} delivery/interaction record(s) available for CRM timelines.')
    contacts=count('SELECT count(*) n FROM contacts');activities=count('SELECT count(*) n FROM activities')
    add('17. Lead/customer activity tracking','Pass' if contacts else 'Blocked',f'{contacts:,} contact(s); {activities} activity record(s).')
    orders=count('SELECT count(*) n FROM orders')
    add('18. Order / sale recording','Pass' if orders or shop else 'Needs data',f'{orders} local/synchronised order record(s).')
    touch=count('SELECT count(*) n FROM v9_attribution_touchpoints')
    add('19. Revenue attribution','Pass' if table('v9_attribution_touchpoints') else 'Blocked',f'{touch} attribution touchpoint(s). Full cross-channel revenue attribution depends on connected channel identifiers and commerce/payment events.')
    post=count("SELECT count(*) n FROM v9_jobs WHERE job_type='order.postpurchase'")
    add('20. Post-purchase automation','Pass' if table('v9_jobs') else 'Blocked',f'{post} post-purchase automation job(s). Rules are event-driven; real transactional messages depend on connected transports.')
    metrics=count('SELECT count(*) n FROM v10_channel_metrics') if table('v10_channel_metrics') else 0
    add('21. Analytics update','Pass' if table('v10_channel_metrics') else 'Blocked',f'{metrics} provider-synchronised channel metric row(s).')
    recs=count("SELECT count(*) n FROM v9_recommendations WHERE status='Open'")
    add('22. AI / rule-based next action','Pass' if table('v9_recommendations') else 'Blocked',f'{recs} open owner recommendation(s); AI recommendations require connected business data and AI configuration, while deterministic checks run locally.')
    dead=count("SELECT count(*) n FROM v9_jobs WHERE status='Dead letter'");failures=count('SELECT count(*) n FROM v9_failures WHERE resolved=0')
    if dead or failures:add('Reliability gate','Needs attention',f'{dead} dead-letter job(s); {failures} unresolved failure(s).')
    if not auth_enabled():add('Production access gate','Needs setup','Database-backed sign-in/RBAC is disabled. Enable it before any public deployment.')
    public=(m.settings().get('public_base_url') or '').strip()
    if not public.startswith('https://'):add('Public webhook gate','Needs setup','No public HTTPS Base URL is configured. External providers cannot reach localhost webhooks.')
    overall='Pass' if all(s in {'Pass','Needs data'} for _,_,s,_ in steps) else 'Needs setup'
    with m.connect() as con:
        for no,label,status,detail in steps:con.execute('INSERT INTO v11_e2e_steps(id,run_id,step_no,label,status,detail) VALUES(?,?,?,?,?,?)',(uid('STP'),rid,no,label,status,detail[:2000]))
        con.execute('UPDATE v11_e2e_runs SET status=?,finished_at=CURRENT_TIMESTAMP,summary_json=? WHERE id=?',(overall,json.dumps({'steps':len(steps),'products':products,'contacts':contacts,'connected_integrations':sum(1 for x in health if x['status']=='Connected')}),rid))
    return rid


def e2e_run(run_id:str)->dict:
    run=m.one('SELECT * FROM v11_e2e_runs WHERE id=?',(run_id,))
    if not run:raise ValueError('End-to-end test not found.')
    run['steps']=m.rows('SELECT * FROM v11_e2e_steps WHERE run_id=? ORDER BY step_no',(run_id,));return run


def latest_e2e()->dict|None:
    row=m.one('SELECT id FROM v11_e2e_runs ORDER BY started_at DESC LIMIT 1')
    return e2e_run(row['id']) if row else None

# V12 MFA helpers
begin_mfa=mfa_auth.begin
mfa_info=mfa_auth.info
pending_mfa_secret=mfa_auth.pending_secret
enable_mfa=mfa_auth.enable
disable_mfa=mfa_auth.disable
production_mfa_ready=mfa_auth.production_ready
