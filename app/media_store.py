from __future__ import annotations
import hashlib
import mimetypes
from pathlib import Path
from urllib.parse import quote
import runtime_config as rc

ROOT=Path(__file__).resolve().parent
STATIC=rc.STATIC_ROOT.resolve()

def _safe_local(relative_path:str)->Path:
    rel=str(relative_path or '').lstrip('/')
    if rel.startswith('static/'):rel=rel[len('static/'):]
    path=(STATIC/rel).resolve()
    if path!=STATIC and STATIC not in path.parents:raise ValueError('Media path is outside the application media directory.')
    if not path.is_file():raise ValueError('Media file does not exist locally.')
    return path

def object_key(relative_path:str)->str:
    path=_safe_local(relative_path);digest=hashlib.sha256(path.read_bytes()).hexdigest()[:16]
    return f'commerce-crm/{digest}/{path.relative_to(STATIC).as_posix()}'

def is_public_asset(relative_path:str)->bool:
    rel=str(relative_path or '').replace('\\','/').lstrip('/')
    return rel.startswith(('static/generated/','generated/','static/brand/','brand/'))

def _client():
    try:import boto3
    except ImportError as exc:raise RuntimeError('Cloud media requires boto3. Use the production runtime requirements.') from exc
    kwargs={}
    if rc.MEDIA_REGION:kwargs['region_name']=rc.MEDIA_REGION
    if rc.MEDIA_ENDPOINT_URL:kwargs['endpoint_url']=rc.MEDIA_ENDPOINT_URL
    return boto3.client('s3',**kwargs)

def upload(relative_path:str,public:bool|None=None)->dict:
    if rc.MEDIA_BACKEND=='local':
        rel=str(relative_path or '').lstrip('/')
        return {'backend':'local','key':rel,'url':'','public':False}
    path=_safe_local(relative_path)
    if rc.MEDIA_BACKEND!='s3':raise ValueError('MEDIA_BACKEND must be local or s3.')
    public=is_public_asset(relative_path) if public is None else bool(public)
    bucket=rc.MEDIA_BUCKET if public else rc.MEDIA_PRIVATE_BUCKET
    if not bucket:raise ValueError(('MEDIA_BUCKET' if public else 'MEDIA_PRIVATE_BUCKET')+' is not configured.')
    key=object_key(relative_path);ctype=mimetypes.guess_type(path.name)[0] or 'application/octet-stream'
    extra={'ContentType':ctype,'CacheControl':'public,max-age=31536000,immutable' if public else 'private,no-store'}
    _client().upload_file(str(path),bucket,key,ExtraArgs=extra)
    url=rc.MEDIA_PUBLIC_BASE_URL.rstrip('/')+'/'+quote(key,safe='/') if public and rc.MEDIA_PUBLIC_BASE_URL else ''
    return {'backend':'s3','bucket':bucket,'key':key,'url':url,'public':public}

def persist(relative_path:str,public:bool|None=None)->dict:return upload(relative_path,public)

def public_url(relative_path:str,upload_if_needed:bool=True)->str:
    if rc.MEDIA_BACKEND=='s3':
        if not rc.MEDIA_PUBLIC_BASE_URL:return ''
        if upload_if_needed:return upload(relative_path,True).get('url','')
        return rc.MEDIA_PUBLIC_BASE_URL.rstrip('/')+'/'+quote(object_key(relative_path),safe='/')
    if rc.valid_public_https(rc.PUBLIC_BASE_URL):
        rel=str(relative_path or '').lstrip('/')
        if not rel.startswith('static/'):rel='static/'+rel
        return rc.PUBLIC_BASE_URL.rstrip('/')+'/'+quote(rel,safe='/')
    return ''

def sync_tree()->dict:
    if rc.MEDIA_BACKEND!='s3':return {'uploaded':0,'backend':'local'}
    uploaded=0;failed=[]
    for path in STATIC.rglob('*'):
        if not path.is_file():continue
        rel='static/'+path.relative_to(STATIC).as_posix()
        try:upload(rel,is_public_asset(rel));uploaded+=1
        except Exception as exc:failed.append({'path':rel,'error':str(exc)})
    if failed:raise RuntimeError(f'Media sync uploaded {uploaded} file(s) but {len(failed)} failed. First failure: {failed[0]["path"]}: {failed[0]["error"]}')
    return {'uploaded':uploaded,'backend':'s3'}

def status()->dict:
    return {'backend':rc.MEDIA_BACKEND,'public_bucket':rc.MEDIA_BUCKET,'private_bucket':rc.MEDIA_PRIVATE_BUCKET,'public_base_url':rc.MEDIA_PUBLIC_BASE_URL,
            'publishable':bool(rc.MEDIA_PUBLIC_BASE_URL and rc.MEDIA_BUCKET) if rc.MEDIA_BACKEND=='s3' else rc.valid_public_https(rc.PUBLIC_BASE_URL)}
