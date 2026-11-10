from __future__ import annotations
import base64, hashlib, hmac, os, re, secrets, struct, time
from pathlib import Path
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

SCHEMA='''
CREATE TABLE IF NOT EXISTS v12_user_mfa(
  user_id TEXT PRIMARY KEY,
  encrypted_secret BLOB NOT NULL,
  enabled INTEGER NOT NULL DEFAULT 0,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  enabled_at TEXT,
  FOREIGN KEY(user_id) REFERENCES v11_users(user_id) ON DELETE CASCADE
);
'''

def initialise():
    with m.connect() as con:con.executescript(SCHEMA)

def _vault()->Fernet:
    env=os.environ.get('CRM_VAULT_MASTER_KEY','').strip().encode()
    if env:
        try:return Fernet(env)
        except Exception:raise RuntimeError('CRM_VAULT_MASTER_KEY is not a valid Fernet key.') from None
    if rc.IS_PRODUCTION:raise RuntimeError('CRM_VAULT_MASTER_KEY is required for production authentication secrets.')
    path=Path(os.environ.get('CRM_AUTH_KEY_PATH',str(Path.home()/'.config'/'commerce-crm'/'auth-vault.key')))
    path.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
    if not path.exists():
        fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'wb') as f:f.write(Fernet.generate_key())
    os.chmod(path,0o600);return Fernet(path.read_bytes().strip())

def _secret()->str:return base64.b32encode(secrets.token_bytes(20)).decode('ascii').rstrip('=')

def totp(secret:str,when:int|None=None)->str:
    when=int(time.time() if when is None else when);counter=when//30
    raw=base64.b32decode(secret+'='*((8-len(secret)%8)%8),casefold=True)
    digest=hmac.new(raw,struct.pack('>Q',counter),hashlib.sha1).digest();off=digest[-1]&15
    num=(struct.unpack('>I',digest[off:off+4])[0]&0x7fffffff)%1000000
    return str(num).zfill(6)

def verify(secret:str,code:str)->bool:
    code=re.sub(r'\D','',code or '')
    if len(code)!=6:return False
    now=int(time.time())
    return any(hmac.compare_digest(totp(secret,now+offset*30),code) for offset in (-1,0,1))

def begin(user_id:str)->str:
    initialise()
    if not m.one('SELECT 1 ok FROM v11_users WHERE user_id=?',(user_id,)):raise ValueError('User not found.')
    secret=_secret();enc=_vault().encrypt(secret.encode())
    with m.connect() as con:
        con.execute('INSERT INTO v12_user_mfa(user_id,encrypted_secret,enabled) VALUES(?,?,0) ON CONFLICT(user_id) DO UPDATE SET encrypted_secret=excluded.encrypted_secret,enabled=0,created_at=CURRENT_TIMESTAMP,enabled_at=NULL',(user_id,enc))
    return secret

def _decrypt(user_id:str)->str:
    initialise();row=m.one('SELECT encrypted_secret FROM v12_user_mfa WHERE user_id=?',(user_id,))
    if not row:return ''
    try:return _vault().decrypt(row['encrypted_secret']).decode()
    except (InvalidToken,ValueError,TypeError):raise ValueError('MFA secret cannot be decrypted; restart MFA setup.') from None

def info(user_id:str)->dict:
    initialise();return m.one('SELECT enabled,created_at,enabled_at FROM v12_user_mfa WHERE user_id=?',(user_id,)) or {'enabled':0,'created_at':'','enabled_at':''}

def pending_secret(user_id:str)->str:
    row=info(user_id);return _decrypt(user_id) if row and not row.get('enabled') else ''

def enable(user_id:str,code:str):
    secret=_decrypt(user_id)
    if not secret:raise ValueError('Start MFA setup first.')
    if not verify(secret,code):raise ValueError('The authenticator code is not valid. Check your device time and try again.')
    with m.connect() as con:con.execute('UPDATE v12_user_mfa SET enabled=1,enabled_at=CURRENT_TIMESTAMP WHERE user_id=?',(user_id,))
    m.audit('user.mfa_enabled',user_id,'TOTP MFA enabled.')

def disable(user_id:str):
    initialise()
    with m.connect() as con:con.execute('DELETE FROM v12_user_mfa WHERE user_id=?',(user_id,))
    m.audit('user.mfa_disabled',user_id,'TOTP MFA disabled.')

def required(user_id:str)->bool:return bool(info(user_id).get('enabled'))

def validate(user_id:str,code:str)->bool:
    return verify(_decrypt(user_id),code) if required(user_id) else True

def production_ready()->bool:
    try:
        initialise();row=m.one("SELECT count(*) n FROM v11_users u JOIN v12_user_mfa f ON f.user_id=u.user_id WHERE u.active=1 AND u.role='Owner' AND f.enabled=1")
        return bool(row and int(row['n'])>0)
    except Exception:
        return False
