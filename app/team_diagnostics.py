from __future__ import annotations
import json, os, platform, sqlite3, sys, time
from pathlib import Path

APP_ROOT=Path(__file__).resolve().parent
RELEASE_ROOT=APP_ROOT.parent
DATA_ROOT=Path(os.environ.get('CRM_DATA_ROOT',str(RELEASE_ROOT/'data'))).resolve()
DB=Path(os.environ.get('CRM_DB_PATH',str(DATA_ROOT/'commerce_crm.sqlite'))).resolve()


def _table_count(con,table):
    try:return int(con.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0])
    except Exception:return None


def build_support_bundle():
    from release_info import PRODUCT_NAME,APP_VERSION,BUILD_ID,SCHEMA_VERSION
    result={'product':PRODUCT_NAME,'version':APP_VERSION,'build':BUILD_ID,'schema':SCHEMA_VERSION,
            'generated_at_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),
            'runtime':{'python':sys.version.split()[0],'os':platform.platform(),'team_test_mode':os.environ.get('CRM_TEAM_TEST','0')=='1','external_writes_enabled':os.environ.get('CRM_ALLOW_EXTERNAL_WRITES','0')=='1'},
            'database':{'present':DB.is_file(),'path_kind':'release-data-directory'},'counts':{},'health':{},'connectors':[],'backups':{}}
    if DB.is_file():
        try:
            with sqlite3.connect(DB) as con:
                result['database']['quick_check']=con.execute('PRAGMA quick_check').fetchone()[0]
                for t in ['products','contacts','companies','opportunities','orders','campaigns','m4_tasks','v13_incidents','v9_failures','v9_jobs']:
                    n=_table_count(con,t)
                    if n is not None:result['counts'][t]=n
                try:result['health']['open_incidents']=int(con.execute("SELECT count(*) FROM v13_incidents WHERE status='Open'").fetchone()[0])
                except Exception:pass
                try:result['health']['unresolved_failures']=int(con.execute('SELECT count(*) FROM v9_failures WHERE resolved=0').fetchone()[0])
                except Exception:pass
                try:result['health']['stuck_jobs']=int(con.execute("SELECT count(*) FROM v9_jobs WHERE status IN ('Running','Retry','Dead')").fetchone()[0])
                except Exception:pass
                try:
                    result['connectors']=[{'connector_key':r[0],'status':r[1]} for r in con.execute("SELECT connector_key,status FROM v10_connections ORDER BY connector_key")]
                except Exception:pass
        except sqlite3.Error as exc:
            result['database']['quick_check']='ERROR';result['database']['error_type']=type(exc).__name__
    backup_dir=DATA_ROOT/'backups'
    files=list(backup_dir.glob('*.sqlite'))+list(backup_dir.glob('*.zip')) if backup_dir.is_dir() else []
    result['backups']={'count':len(files),'latest':max((p.name for p in files),default='')}
    return result


def export_support_bundle():
    outdir=DATA_ROOT/'diagnostics';outdir.mkdir(parents=True,exist_ok=True)
    path=outdir/('support_bundle_'+time.strftime('%Y%m%d_%H%M%S')+'.json')
    path.write_text(json.dumps(build_support_bundle(),indent=2))
    return str(path)

if __name__=='__main__':print(export_support_bundle())
