#!/usr/bin/env python3
from __future__ import annotations
import datetime as dt, json, os, shutil, subprocess, tempfile, zipfile
from pathlib import Path
from cryptography.fernet import Fernet
import runtime_config as rc

ROOT=Path(__file__).resolve().parent

def main():
    url=os.environ.get('DATABASE_URL','').strip()
    if not url.lower().startswith(('postgres://','postgresql://')):raise SystemExit('DATABASE_URL must point to PostgreSQL.')
    if not shutil.which('pg_dump'):raise SystemExit('pg_dump is required. The supplied Docker image includes the PostgreSQL client.')
    outdir=rc.BACKUP_DIR;outdir.mkdir(parents=True,exist_ok=True)
    stamp=dt.datetime.now(dt.UTC).strftime('%Y%m%d_%H%M%SZ')
    with tempfile.TemporaryDirectory(prefix='crm-backup-') as td:
        td=Path(td);dump=td/'database.dump'
        subprocess.run(['pg_dump','--format=custom','--no-owner','--file',str(dump),url],check=True)
        manifest={'created_at':stamp,'database':'postgresql','media_backend':rc.MEDIA_BACKEND,'media_bucket':rc.MEDIA_BUCKET,'includes_local_media':rc.MEDIA_BACKEND=='local'}
        (td/'manifest.json').write_text(json.dumps(manifest,indent=2))
        archive=outdir/f'commerce_crm_{stamp}.zip'
        with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
            z.write(dump,'database.dump');z.write(td/'manifest.json','manifest.json')
            if rc.MEDIA_BACKEND=='local':
                static=rc.STATIC_ROOT
                if static.is_dir():
                    for f in static.rglob('*'):
                        if f.is_file():z.write(f,'static/'+f.relative_to(static).as_posix())
        enc_key=os.environ.get('BACKUP_ENCRYPTION_KEY','').strip()
        final=archive
        if enc_key:
            try:cipher=Fernet(enc_key.encode())
            except Exception:raise SystemExit('BACKUP_ENCRYPTION_KEY must be a valid Fernet key.')
            encrypted=archive.with_suffix('.zip.enc');encrypted.write_bytes(cipher.encrypt(archive.read_bytes()));archive.unlink();final=encrypted
        bucket=os.environ.get('BACKUP_BUCKET','').strip()
        if bucket:
            try:import boto3
            except ImportError:raise SystemExit('BACKUP_BUCKET is configured but boto3 is not installed.')
            kwargs={}
            if rc.MEDIA_REGION:kwargs['region_name']=rc.MEDIA_REGION
            if rc.MEDIA_ENDPOINT_URL:kwargs['endpoint_url']=rc.MEDIA_ENDPOINT_URL
            key=f'commerce-crm-backups/{stamp[:4]}/{stamp[4:6]}/{final.name}'
            boto3.client('s3',**kwargs).upload_file(str(final),bucket,key,ExtraArgs={'ServerSideEncryption':'AES256'})
            print('Uploaded backup to s3://'+bucket+'/'+key)
        print(str(final))

if __name__=='__main__':main()
