from __future__ import annotations
import json, os, sqlite3
from pathlib import Path

WAREHOUSE_ID='MAIN'
WAREHOUSE_NAME='Team Test Warehouse'

def _cols(con, table):
    return {r[1] for r in con.execute(f'PRAGMA table_info({table})')}

def upgrade_workspace(db_path: Path|str) -> dict:
    """Idempotent beta.1 -> beta.2 migration. Never fabricates production identities."""
    db_path=Path(db_path)
    changed={'activity_schema':0,'relationship_events':0,'warehouse':0}
    with sqlite3.connect(db_path) as con:
        con.row_factory=sqlite3.Row
        tables={r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if 'm42_changes' in tables:
            cols=_cols(con,'m42_changes')
            for name,definition in [('related_object_type','TEXT'),('related_object_id','TEXT'),('event_scope',"TEXT DEFAULT 'business'")]:
                if name not in cols:
                    con.execute(f'ALTER TABLE m42_changes ADD COLUMN {name} {definition}'); changed['activity_schema']+=1
            rows=con.execute("SELECT id,object_type,object_id,action,after_json,event_scope FROM m42_changes").fetchall()
            for r in rows:
                if (r['event_scope'] or 'business')!='business': continue
                try: payload=json.loads(r['after_json'] or '{}') or {}
                except Exception: payload={}
                typ=str(r['object_type'] or '')
                rel_type=rel_id=''; scope='business'
                if typ=='Contact':
                    for key,label in [('task_id','Task'),('order_id','Order'),('deal_id','Opportunity')]:
                        if payload.get(key): rel_type,label_id=label,str(payload[key]); rel_id=label_id; scope='relationship'; break
                elif typ=='Task' and payload.get('contact_id'): rel_type,rel_id='Contact',str(payload['contact_id'])
                elif typ in {'Deal','Opportunity'} and payload.get('contact_id'): rel_type,rel_id='Contact',str(payload['contact_id'])
                elif typ=='Order' and payload.get('contact_id'): rel_type,rel_id='Contact',str(payload['contact_id'])
                if rel_type or scope!='business':
                    con.execute('UPDATE m42_changes SET related_object_type=?,related_object_id=?,event_scope=? WHERE id=?',(rel_type or None,rel_id or None,scope,r['id']))
                    changed['relationship_events']+=1
        # beta.1 already used MAIN in canonical inventory/movement records. Make that
        # existing authority explicit instead of inventing a second location identity.
        con.execute('''CREATE TABLE IF NOT EXISTS v9_locations(
          id TEXT PRIMARY KEY, brand_id TEXT, name TEXT NOT NULL, location_type TEXT NOT NULL DEFAULT 'Warehouse',
          country TEXT DEFAULT '', city TEXT DEFAULT '', address TEXT DEFAULT '', timezone TEXT DEFAULT '', status TEXT DEFAULT 'Active')''')
        inv_exists='v9_inventory' in tables or con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='v9_inventory'").fetchone()
        if inv_exists and con.execute('SELECT 1 FROM v9_inventory WHERE location_id=? LIMIT 1',(WAREHOUSE_ID,)).fetchone():
            if not con.execute('SELECT 1 FROM v9_locations WHERE id=?',(WAREHOUSE_ID,)).fetchone():
                con.execute('INSERT INTO v9_locations(id,name,location_type,country,city,timezone,status) VALUES(?,?,?,?,?,?,?)',
                            (WAREHOUSE_ID,WAREHOUSE_NAME,'Warehouse','United Kingdom','Test location','Europe/London','Active'))
                changed['warehouse']=1
        con.execute("INSERT OR REPLACE INTO settings(setting_key,setting_value) VALUES('team_release_schema','56')")
        con.commit()
    return changed

def initialise():
    path=os.environ.get('CRM_DB_PATH')
    return upgrade_workspace(path) if path else {}

def doctor_findings(connect):
    findings=[]
    with connect() as con:
        tables={r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if 'm42_changes' in tables:
            cols=_cols(con,'m42_changes')
            if {'event_scope','related_object_type','related_object_id'}-cols:
                findings.append({'check_key':'beta2_activity_contract','severity':'Critical','object_type':'activity','object_id':'','detail':'Canonical activity relationship columns are missing.'})
            else:
                bad=con.execute("""SELECT count(*) FROM m42_changes WHERE coalesce(event_scope,'business')='business' AND
                  ((object_type='Order' AND object_id NOT LIKE 'ORD-%') OR (object_type='Task' AND object_id NOT LIKE 'TASK-%'))""").fetchone()[0]
                if bad: findings.append({'check_key':'activity_entity_identity','severity':'Critical','object_type':'activity','object_id':'','detail':f'{bad} business activity event(s) use an invalid canonical entity identity.'})
        if {'products','v9_inventory','v9_locations'}.issubset(tables):
            orphan=con.execute('SELECT count(*) FROM v9_inventory i LEFT JOIN v9_locations l ON l.id=i.location_id WHERE l.id IS NULL').fetchone()[0]
            if orphan: findings.append({'check_key':'inventory_location_authority','severity':'Critical','object_type':'inventory','object_id':'','detail':f'{orphan} inventory balance(s) have no valid stock location.'})
            mismatch=con.execute("""SELECT count(*) FROM (SELECT p.product_id,p.stock_qty cached,coalesce(sum(i.on_hand),0) actual
              FROM products p LEFT JOIN v9_inventory i ON i.product_id=p.product_id WHERE coalesce(p.status,'Draft')<>'Archived'
              GROUP BY p.product_id HAVING coalesce(p.stock_qty,0)<>coalesce(sum(i.on_hand),0))""").fetchone()[0]
            if mismatch: findings.append({'check_key':'product_location_stock_mismatch','severity':'Critical','object_type':'inventory','object_id':'','detail':f'{mismatch} active product(s) disagree with location inventory.'})
    return findings
