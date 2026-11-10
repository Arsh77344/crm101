from __future__ import annotations
import os
from pathlib import Path
from urllib.parse import urlparse

ROOT=Path(__file__).resolve().parent
DATA_ROOT=Path(os.environ.get('CRM_DATA_ROOT', str(ROOT))).expanduser().resolve()
STATIC_ROOT=Path(os.environ.get('CRM_STATIC_ROOT', str(ROOT/'static'))).expanduser().resolve()
BACKUP_DIR=Path(os.environ.get('BACKUP_DIR', str(DATA_ROOT/'backups'))).expanduser().resolve()
CONFIG_DIR=Path(os.environ.get('CRM_CONFIG_DIR', str(DATA_ROOT/'config'))).expanduser().resolve()
LOG_DIR=Path(os.environ.get('CRM_LOG_DIR', str(DATA_ROOT/'logs'))).expanduser().resolve()
DIAGNOSTICS_DIR=Path(os.environ.get('CRM_DIAGNOSTICS_DIR', str(DATA_ROOT/'diagnostics'))).expanduser().resolve()
TEAM_TEST_MODE=os.environ.get('CRM_TEAM_TEST','0')=='1'
ALLOW_EXTERNAL_WRITES=os.environ.get('CRM_ALLOW_EXTERNAL_WRITES','0')=='1'

def require_external_write_allowed(action: str='external action') -> None:
    if TEAM_TEST_MODE and not ALLOW_EXTERNAL_WRITES:
        raise ValueError('Team Test Mode blocked '+str(action)+'. This release never performs real provider writes unless CRM_ALLOW_EXTERNAL_WRITES=1 is explicitly set by an administrator.')

APP_ENV=os.environ.get('APP_ENV','local').strip().lower() or 'local'
IS_PRODUCTION=APP_ENV in {'prod','production'}
BIND_HOST=os.environ.get('BIND_HOST','0.0.0.0' if IS_PRODUCTION else '127.0.0.1')
PORT=int(os.environ.get('PORT','8765'))
DATABASE_URL=os.environ.get('DATABASE_URL','').strip()
MEDIA_BACKEND=os.environ.get('MEDIA_BACKEND','local').strip().lower()
MEDIA_BUCKET=os.environ.get('MEDIA_BUCKET','').strip()
MEDIA_PRIVATE_BUCKET=os.environ.get('MEDIA_PRIVATE_BUCKET','').strip()
MEDIA_REGION=os.environ.get('MEDIA_REGION','').strip()
MEDIA_ENDPOINT_URL=os.environ.get('MEDIA_ENDPOINT_URL','').strip()
MEDIA_PUBLIC_BASE_URL=os.environ.get('MEDIA_PUBLIC_BASE_URL','').strip().rstrip('/')
PUBLIC_BASE_URL=os.environ.get('PUBLIC_BASE_URL','').strip().rstrip('/')
COOKIE_SECURE=os.environ.get('COOKIE_SECURE','1' if IS_PRODUCTION else '0')=='1'
TRUST_PROXY=os.environ.get('TRUST_PROXY','0')=='1'
WORKER_POLL_SECONDS=max(1,int(os.environ.get('WORKER_POLL_SECONDS','5')))
MONITORING_TOKEN=os.environ.get('MONITORING_TOKEN','').strip()
BACKUP_BUCKET=os.environ.get('BACKUP_BUCKET','').strip()


def valid_public_https(url:str)->bool:
    try:
        p=urlparse(url);host=(p.hostname or '').lower()
        return p.scheme=='https' and bool(host) and host not in {'localhost','127.0.0.1','::1'}
    except Exception:return False


def production_gaps()->list[str]:
    gaps=[]
    if IS_PRODUCTION:
        if not DATABASE_URL.lower().startswith(('postgres://','postgresql://')):gaps.append('DATABASE_URL must point to PostgreSQL.')
        if MEDIA_BACKEND!='s3':gaps.append('MEDIA_BACKEND should be s3 (or an S3-compatible object store).')
        if not MEDIA_BUCKET:gaps.append('MEDIA_BUCKET is required for public/cloud media.')
        if not MEDIA_PRIVATE_BUCKET:gaps.append('MEDIA_PRIVATE_BUCKET is required for raw/private media.')
        if MEDIA_BUCKET and MEDIA_PRIVATE_BUCKET and MEDIA_BUCKET==MEDIA_PRIVATE_BUCKET:gaps.append('Use separate public and private media buckets in production.')
        if not valid_public_https(PUBLIC_BASE_URL):gaps.append('PUBLIC_BASE_URL must be a real HTTPS URL.')
        if not MEDIA_PUBLIC_BASE_URL:gaps.append('MEDIA_PUBLIC_BASE_URL/CDN URL is required for provider-publishable assets.')
        if not os.environ.get('CRM_VAULT_MASTER_KEY','').strip():gaps.append('CRM_VAULT_MASTER_KEY is required for production secrets.')
        if not MONITORING_TOKEN:gaps.append('MONITORING_TOKEN is required to protect the production metrics endpoint.')
    return gaps
