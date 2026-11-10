#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import hashlib
import secrets
import importlib.util
import json
import os
import platform
import re
import shutil
import socket
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

APP_ROOT=Path(__file__).resolve().parent
RELEASE_ROOT=APP_ROOT.parent
DATA_ROOT=RELEASE_ROOT/'data'
RUNTIME_ROOT=RELEASE_ROOT/'runtime'
TEMPLATE_DB=DATA_ROOT/'sample_test_database.sqlite'
ACTIVE_DB=DATA_ROOT/'commerce_crm.sqlite'


def configure_environment(port: int|None=None) -> None:
    DATA_ROOT.mkdir(parents=True,exist_ok=True)
    for name in ('static','backups','config','logs','diagnostics','product_inbox'):
        (DATA_ROOT/name).mkdir(parents=True,exist_ok=True)
    os.environ.setdefault('CRM_TEAM_TEST','1')
    os.environ.setdefault('CRM_ALLOW_EXTERNAL_WRITES','0')
    os.environ.setdefault('CRM_DATA_ROOT',str(DATA_ROOT))
    os.environ.setdefault('CRM_DB_PATH',str(ACTIVE_DB))
    os.environ.setdefault('CRM_STATIC_ROOT',str(DATA_ROOT/'static'))
    os.environ.setdefault('BACKUP_DIR',str(DATA_ROOT/'backups'))
    os.environ.setdefault('CRM_CONFIG_DIR',str(DATA_ROOT/'config'))
    os.environ.setdefault('CRM_LOG_DIR',str(DATA_ROOT/'logs'))
    os.environ.setdefault('CRM_DIAGNOSTICS_DIR',str(DATA_ROOT/'diagnostics'))
    os.environ.setdefault('CRM_SECRET_PATH',str(DATA_ROOT/'config'/'ai.json'))
    os.environ.setdefault('CRM_VIDEO_SECRET_PATH',str(DATA_ROOT/'config'/'video.json'))
    os.environ.setdefault('CRM_INTEGRATION_KEY_PATH',str(DATA_ROOT/'config'/'integration-vault.key'))
    os.environ.setdefault('CRM_AUTH_KEY_PATH',str(DATA_ROOT/'config'/'auth-vault.key'))
    os.environ.setdefault('APP_ENV','local')
    os.environ.setdefault('BIND_HOST','127.0.0.1')
    os.environ.setdefault('PUBLIC_BASE_URL','')
    if port is not None:
        os.environ['PORT']=str(port)
    else:
        os.environ.setdefault('PORT','8765')


def _module_available(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def _runtime_ready() -> bool:
    return _module_available('cryptography') and _module_available('PIL')


def ensure_runtime(force_full: bool=False) -> None:
    """Use current Python for core local workflows, or prepare the private full runtime.

    Pillow and cryptography are required for normal local operation. MCP is an optional
    connector capability: it is installed by the full-runtime helper, but its absence does
    not prevent offline CRM testing when no MCP server is configured.
    """
    if os.environ.get('CRM_SKIP_TEAM_RUNTIME','0')=='1':
        return
    if not force_full:
        if not _runtime_ready():
            print('Core Team Test CRM will run with the Python standard library. Optional image/secure-connector packages are not installed; use PREPARE_FULL_RUNTIME.command while online to enable those capabilities.',flush=True)
        return
    if sys.version_info < (3,12):
        raise RuntimeError('Python 3.12 or newer is required. Install Python 3 from python.org, then double-click START_APP again.')
    venv=RUNTIME_ROOT/'venv'
    py=venv/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
    marker=venv/'.team_runtime_ready'
    RUNTIME_ROOT.mkdir(parents=True,exist_ok=True)
    try:
        if not py.exists():
            print('Preparing the private Team Test runtime (first launch only)...',flush=True)
            subprocess.run([sys.executable,'-m','venv',str(venv)],check=True)
        if not marker.exists():
            print('Installing required local packages (first launch only)...',flush=True)
            subprocess.run([str(py),'-m','pip','install','--disable-pip-version-check','-r',str(APP_ROOT/'requirements-team.txt')],check=True)
            marker.write_text('Commerce Business OS 1.0.0-beta.6 TEAM-TEST-006\n')
        if Path(sys.executable).resolve()!=py.resolve():
            os.execv(str(py),[str(py),str(Path(__file__).resolve()),*sys.argv[1:]])
    except (OSError,subprocess.CalledProcessError) as exc:
        raise RuntimeError('Automatic runtime setup could not finish. Check internet access and Python 3, then run START_APP again. Details: '+str(exc)) from exc


def _valid_db(path: Path) -> bool:
    if not path.is_file() or path.stat().st_size<4096:return False
    try:
        with sqlite3.connect(path) as con:
            if con.execute('PRAGMA quick_check').fetchone()[0]!='ok':return False
            tables={r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            return {'contacts','products','orders','settings'}.issubset(tables)
    except sqlite3.Error:
        return False


def _previous_release_source() -> tuple[Path,Path,str] | None:
    # Prefer the immediately previous semantic beta. Testers often keep each release
    # inside a wrapper such as Beta3_Team_Test/, so search one level around the current
    # extraction without depending on a developer-specific absolute path.
    # Search the extraction's immediate neighbourhood by default. Only step up
    # another level when the current release is itself inside an obvious Team Test
    # wrapper (for example Beta6_Team_Test/Commerce_Business_OS_1.0.0-beta.6).
    # This prevents a clean extraction from importing an unrelated historical/audit
    # database merely because one exists elsewhere under a broad parent directory.
    search_bases=[]
    immediate=RELEASE_ROOT.parent
    try: immediate=immediate.resolve()
    except OSError: pass
    search_bases.append(immediate)
    wrapper=immediate.name.lower()
    if (('team' in wrapper and 'test' in wrapper) or re.search(r'beta[^a-z0-9]*\d',wrapper)):
        upper=immediate.parent
        try: upper=upper.resolve()
        except OSError: pass
        if upper not in search_bases: search_bases.append(upper)
    for version in ('1.0.0-beta.5','1.0.0-beta.4','1.0.0-beta.3','1.0.0-beta.2','1.0.0-beta.1'):
        folder=f'Commerce_Business_OS_{version}'
        roots=[]
        for base in search_bases:
            roots.append(base/folder)
            try:roots.extend(sorted(p for p in base.glob('*/'+folder) if p.is_dir()))
            except OSError:pass
        seen=set()
        for root in roots:
            key=str(root)
            if key in seen or root==RELEASE_ROOT:continue
            seen.add(key)
            candidate=root/'data'/'commerce_crm.sqlite'
            if _valid_db(candidate):
                return candidate,root,version
    return None

def _copy_previous_tester_assets(previous_root: Path) -> None:
    """Preserve tester-owned media/config during a local sibling upgrade.

    These files are copied only at runtime from the tester's own previous release;
    they are never embedded into the shared team-test ZIP.
    """
    source_data=previous_root/'data'
    for name in ('static','product_inbox','config'):
        src=source_data/name;dst=DATA_ROOT/name
        if src.exists():
            shutil.copytree(src,dst,dirs_exist_ok=True)
    cred=source_data/'FIRST_RUN_CREDENTIALS.txt'
    if cred.is_file():
        shutil.copy2(cred,DATA_ROOT/'FIRST_RUN_CREDENTIALS.txt')


def ensure_database() -> None:
    if _valid_db(ACTIVE_DB):
        import team_beta6
        team_beta6.upgrade_workspace(ACTIVE_DB)
        return
    if ACTIVE_DB.exists():
        stamp=time.strftime('%Y%m%d_%H%M%S')
        bad=DATA_ROOT/'backups'/f'invalid_team_database_{stamp}.sqlite'
        shutil.move(str(ACTIVE_DB),str(bad))
        print('An invalid test database was preserved at '+str(bad),flush=True)
    previous=_previous_release_source()
    source=previous[0] if previous else None
    if previous:
        source,previous_root,previous_version=previous
        shutil.copy2(source,ACTIVE_DB)
        _copy_previous_tester_assets(previous_root)
        print(f'Upgrading a separate copy of the existing {previous_version} Team Test workspace.',flush=True)
    else:
        if not _valid_db(TEMPLATE_DB):
            raise RuntimeError('The packaged sample test database is missing or invalid. Re-extract the release ZIP and try again.')
        shutil.copy2(TEMPLATE_DB,ACTIVE_DB)
        sample_static=DATA_ROOT/'sample_static'
        active_static=DATA_ROOT/'static'
        if sample_static.exists() and not any(active_static.rglob('*')):
            shutil.copytree(sample_static,active_static,dirs_exist_ok=True)
        print('Created a private beta.6 team-test workspace from fictional sample data.',flush=True)
    import team_beta6
    team_beta6.upgrade_workspace(ACTIVE_DB)
    if not source:
        _rotate_fictional_test_passwords()
    try:ACTIVE_DB.chmod(0o600)
    except OSError:pass

def _rotate_fictional_test_passwords() -> None:
    """Create per-install test credentials so the shared ZIP contains no plaintext password."""
    credentials=[]
    with sqlite3.connect(ACTIVE_DB) as con:
        for email,label in [('owner@teamtest.invalid','Owner'),('sales@teamtest.invalid','Sales')]:
            password=secrets.token_urlsafe(15)
            salt=secrets.token_bytes(16)
            digest=hashlib.pbkdf2_hmac('sha256',password.encode('utf-8'),salt,310_000)
            cur=con.execute('UPDATE v11_users SET password_salt=?,password_hash=? WHERE lower(email)=lower(?)',(
                base64.urlsafe_b64encode(salt).decode('ascii'),
                base64.urlsafe_b64encode(digest).decode('ascii'),email))
            if cur.rowcount:
                credentials.append((label,email,password))
        con.commit()
    if not credentials:
        return
    out=DATA_ROOT/'FIRST_RUN_CREDENTIALS.txt'
    lines=['Commerce Business OS — fictional Team Test credentials','',
           'These credentials were generated locally on first launch and were NOT stored in the shared ZIP.','']
    for label,email,password in credentials:
        lines += [f'{label}:',f'  Email: {email}',f'  Password: {password}','']
    lines += ['Keep this file only with your local fictional test workspace. Delete it when testing is complete.']
    out.write_text('\n'.join(lines)+'\n',encoding='utf-8')
    try: out.chmod(0o600)
    except OSError: pass
    print('Generated local fictional test sign-in credentials: '+str(out),flush=True)



def acquire_instance_lock():
    """Hold one cross-platform process lock for the writable Team Test workspace.

    The lock is advisory and automatically released by the OS if the process exits,
    so a crash cannot leave a permanent stale-instance blocker. Doctor/diagnostics
    remain available while the app is running because only the web/worker process
    acquires this lock.
    """
    DATA_ROOT.mkdir(parents=True,exist_ok=True)
    path=DATA_ROOT/'.commerce_business_os.lock'
    handle=path.open('a+b')
    try:
        if os.name=='nt':
            import msvcrt
            handle.seek(0,2)
            if handle.tell()==0:
                handle.write(b'0')
                handle.flush()
            handle.seek(0)
            try:
                msvcrt.locking(handle.fileno(),msvcrt.LK_NBLCK,1)
            except OSError as exc:
                raise RuntimeError('Commerce Business OS is already running for this workspace. Use the existing browser window, or stop the first app before starting it again.') from exc
        else:
            import fcntl
            try:
                fcntl.flock(handle.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
            except OSError as exc:
                raise RuntimeError('Commerce Business OS is already running for this workspace. Use the existing browser window, or stop the first app before starting it again.') from exc
        return handle
    except Exception:
        handle.close()
        raise


def release_instance_lock(handle) -> None:
    if handle is None:
        return
    try:
        if os.name=='nt':
            import msvcrt
            handle.seek(0)
            msvcrt.locking(handle.fileno(),msvcrt.LK_UNLCK,1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(),fcntl.LOCK_UN)
    except Exception:
        pass
    finally:
        try: handle.close()
        except Exception: pass

def choose_port(preferred: int) -> int:
    for port in range(preferred,preferred+20):
        with socket.socket() as s:
            s.settimeout(0.15)
            if s.connect_ex(('127.0.0.1',port))!=0:return port
    raise RuntimeError('No local port is available between %d and %d. Close other local CRM windows and try again.'%(preferred,preferred+19))


def main() -> None:
    if sys.version_info < (3,12):
        raise RuntimeError('Python 3.12 or newer is required for this Team Test release.')
    ap=argparse.ArgumentParser(description='Start Commerce Business OS 1.0.0-beta.6 Team Test release.')
    ap.add_argument('--doctor',action='store_true')
    ap.add_argument('--no-browser',action='store_true')
    ap.add_argument('--port',type=int,default=8765)
    ap.add_argument('--diagnostics',action='store_true')
    ap.add_argument('--prepare-full-runtime',action='store_true',help='Install the full private runtime including optional MCP support.')
    args=ap.parse_args()
    # Configure paths first, then take the workspace lock before touching the live
    # database. This prevents a double-click from starting two worker/server
    # processes against the same SQLite workspace.
    configure_environment(args.port)
    ensure_runtime(force_full=args.prepare_full_runtime)
    if args.prepare_full_runtime:
        print('Full private Team Test runtime is ready, including optional connector packages.')
        return
    server_mode=not (args.doctor or args.diagnostics)
    instance_lock=acquire_instance_lock() if server_mode else None
    try:
        if server_mode:
            os.environ['PORT']=str(choose_port(args.port))
        ensure_database()
        if args.diagnostics:
            import team_diagnostics
            print(team_diagnostics.export_support_bundle())
            return
        import app
        if args.doctor:
            app.initialise()
            import handover_core as hc
            from release_info import PRODUCT_NAME,APP_VERSION,BUILD_ID,SCHEMA_VERSION
            report=hc.doctor_report()
            report['team_release']={'product':PRODUCT_NAME,'version':APP_VERSION,'build':BUILD_ID,'schema':SCHEMA_VERSION,'database':str(ACTIVE_DB),'data_root':str(DATA_ROOT),'external_writes_enabled':os.environ.get('CRM_ALLOW_EXTERNAL_WRITES')=='1'}
            print(json.dumps(report,indent=2,default=str))
            status=str((report.get('integrity') or {}).get('status') or '')
            raise SystemExit(2 if status=='Broken' else 0)
        app.run(open_browser=not args.no_browser)
    finally:
        release_instance_lock(instance_lock)


if __name__=='__main__':
    try:main()
    except KeyboardInterrupt:
        print('\nCommerce Business OS stopped. Test data is saved for the next launch.')
    except Exception as exc:
        print('\nSTARTUP PAUSED: '+str(exc),flush=True)
        print('Your test data was not deleted. See docs/QUICK_START.md or run EXPORT_DIAGNOSTICS.command.',flush=True)
        raise SystemExit(1)
