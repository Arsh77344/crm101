from __future__ import annotations

"""V35 canonical business-truth services.

This module does not create a second business operating model.  It provides a
single service boundary over the historical tables that already exist in the
application, records explicit legacy-to-canonical mappings, and centralises the
business rules that must be shared by Product, Inventory, Campaign, CRM, Order,
Fulfilment, Profitability and Sales-priority workflows.
"""

import datetime as dt
import json
import math
import re
import uuid
from typing import Any

import db_layer
import marketing as m


def uid(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:16].upper()}"


SCHEMA = r'''
CREATE TABLE IF NOT EXISTS v35_campaign_identity(
  legacy_campaign_id TEXT PRIMARY KEY,
  canonical_campaign_id TEXT NOT NULL,
  migration_source TEXT NOT NULL DEFAULT 'legacy_campaigns',
  mapped_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS v35_campaign_identity_canonical ON v35_campaign_identity(canonical_campaign_id);

CREATE TABLE IF NOT EXISTS v35_order_line_meta(
  order_item_id TEXT PRIMARY KEY,
  sku_snapshot TEXT DEFAULT '',
  unit_discount REAL DEFAULT 0,
  tax_amount REAL DEFAULT 0,
  line_total REAL DEFAULT 0,
  unit_cost_snapshot REAL,
  cost_currency TEXT DEFAULT '',
  cost_source TEXT DEFAULT '',
  fulfilment_status TEXT DEFAULT 'Unfulfilled',
  returned_quantity INTEGER DEFAULT 0,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS v35_product_cost_history(
  id TEXT PRIMARY KEY,
  product_id TEXT NOT NULL,
  cost_price REAL,
  currency TEXT DEFAULT '',
  source TEXT NOT NULL DEFAULT 'Owner entry',
  supplier TEXT DEFAULT '',
  effective_at TEXT NOT NULL,
  note TEXT DEFAULT '',
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS v35_product_cost_product ON v35_product_cost_history(product_id,effective_at);

CREATE TABLE IF NOT EXISTS v35_collections(
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL UNIQUE COLLATE NOCASE,
  description TEXT DEFAULT '',
  status TEXT NOT NULL DEFAULT 'Active',
  ai_source TEXT DEFAULT '',
  store_mapping TEXT DEFAULT '',
  marketing_mapping TEXT DEFAULT '',
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS v35_collection_products(
  collection_id TEXT NOT NULL,
  product_id TEXT NOT NULL,
  source TEXT DEFAULT 'Owner',
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY(collection_id,product_id)
);

CREATE TABLE IF NOT EXISTS v35_inventory_movements(
  id TEXT PRIMARY KEY,
  product_id TEXT NOT NULL,
  location_id TEXT NOT NULL DEFAULT 'MAIN',
  movement_type TEXT NOT NULL,
  direction TEXT NOT NULL,
  quantity INTEGER NOT NULL,
  reason TEXT NOT NULL DEFAULT '',
  actor_user_id TEXT DEFAULT '',
  reference_type TEXT DEFAULT '',
  reference_id TEXT DEFAULT '',
  order_item_id TEXT DEFAULT '',
  before_on_hand INTEGER NOT NULL DEFAULT 0,
  after_on_hand INTEGER NOT NULL DEFAULT 0,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS v35_inventory_movement_product ON v35_inventory_movements(product_id,location_id,created_at);
CREATE INDEX IF NOT EXISTS v35_inventory_movement_reference ON v35_inventory_movements(reference_type,reference_id,created_at);

CREATE TABLE IF NOT EXISTS v35_sales_priority(
  contact_id TEXT PRIMARY KEY,
  fit_score INTEGER NOT NULL DEFAULT 0,
  intent_score INTEGER NOT NULL DEFAULT 0,
  urgency_score INTEGER NOT NULL DEFAULT 0,
  priority_score INTEGER NOT NULL DEFAULT 0,
  priority_label TEXT NOT NULL DEFAULT 'Normal',
  reasons_json TEXT NOT NULL DEFAULT '[]',
  calculated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS v35_integrity_findings(
  id TEXT PRIMARY KEY,
  check_key TEXT NOT NULL,
  severity TEXT NOT NULL,
  object_type TEXT DEFAULT '',
  object_id TEXT DEFAULT '',
  detail TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'Open',
  detected_at TEXT DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(check_key,object_type,object_id,detail)
);
'''


def _columns(table: str) -> set[str]:
    try:
        return {str(r['name']) for r in m.rows(f'PRAGMA table_info({table})')}
    except Exception:
        return set()


def _add_column(table: str, column: str, ddl: str) -> None:
    if not m.table_exists(table):
        return
    if column in _columns(table):
        return
    with m.connect() as con:
        con.execute(f'ALTER TABLE {table} ADD COLUMN {column} {ddl}')


def initialise() -> None:
    """Create V35 compatibility metadata and migrate existing truth safely."""
    with m.connect() as con:
        con.executescript(SCHEMA)
    # Real authenticated-user assignments while retaining legacy labels for history.
    _add_column('m42_contact_meta','owner_user_id',"TEXT DEFAULT ''")
    _add_column('m42_deal_meta','owner_user_id',"TEXT DEFAULT ''")
    _add_column('m4_tasks','owner_user_id',"TEXT DEFAULT ''")
    _add_column('v17_conversations','owner_user_id',"TEXT DEFAULT ''")
    # Canonical attribution field remains alongside the old column for safe migration.
    _add_column('m42_order_meta','canonical_campaign_id',"TEXT DEFAULT ''")
    _add_column('m42_deal_meta','canonical_campaign_id',"TEXT DEFAULT ''")
    _add_column('activities','canonical_campaign_id',"TEXT DEFAULT ''")
    # Product current-cost provenance. products.cost_price remains the compatibility cache.
    _add_column('products','cost_currency',"TEXT DEFAULT ''")
    _add_column('products','cost_source',"TEXT DEFAULT ''")
    _add_column('products','cost_effective_at','TEXT')
    _add_column('products','cost_supplier',"TEXT DEFAULT ''")
    migrate_campaign_identity()
    migrate_owner_assignments()
    bootstrap_inventory_truth()
    bootstrap_cost_history()
    migrate_canonical_campaign_references()


def migrate_campaign_identity() -> int:
    """Make v10_unified_campaigns the canonical campaign model.

    Historical ``campaigns`` rows are migrated once into the canonical model and
    explicitly mapped.  They remain in place only as history/compatibility input.
    """
    if not m.table_exists('v10_unified_campaigns'):
        return 0
    migrated = 0
    legacy_rows = m.rows('SELECT * FROM campaigns ORDER BY created_at') if m.table_exists('campaigns') else []
    settings=m.settings()
    for row in legacy_rows:
        old=str(row.get('campaign_id') or '').strip()
        if not old:
            continue
        existing=m.one('SELECT id FROM v10_unified_campaigns WHERE id=?',(old,))
        canonical=old
        if not existing:
            channel=str(row.get('channel') or '').strip()
            channel_map={
                'email':'Email','whatsapp':'WhatsApp','instagram':'Instagram/Facebook','facebook':'Instagram/Facebook',
                'meta ads':'Meta Ads','facebook ads':'Meta Ads','google ads':'Google Ads','website':'Website','web':'Website',
                'pinterest':'Pinterest','seo':'SEO/Blog','blog':'SEO/Blog','seo/blog':'SEO/Blog'
            }
            channels=[channel_map.get(channel.lower())] if channel_map.get(channel.lower()) else []
            extra=m.one('SELECT goal,brief,product_ids_json FROM m4_campaigns WHERE campaign_id=?',(old,)) if m.table_exists('m4_campaigns') else None
            products=[]
            if extra:
                try:
                    products=json.loads(extra.get('product_ids_json') or '[]')
                    if not isinstance(products,list): products=[]
                except Exception: products=[]
            objective=str((extra or {}).get('goal') or (extra or {}).get('brief') or 'Historical campaign plan')[:2000]
            created=row.get('created_at') or None
            with m.connect() as con:
                con.execute('''INSERT INTO v10_unified_campaigns(id,name,objective,audience_query,product_ids_json,channels_json,region,language,budget,currency,status,created_at,updated_at)
                               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,coalesce(?,CURRENT_TIMESTAMP))''',
                            (canonical,str(row.get('campaign_name') or 'Historical campaign')[:180],objective,
                             (str(row.get('audience_type') or '')+' audience migrated from the earlier campaign workspace').strip()[:2000],
                             json.dumps(products),json.dumps(channels),'',str(settings.get('default_language') or 'English')[:80],None,
                             str(settings.get('default_currency') or 'INR'),str(row.get('status') or 'Draft'),created,created))
            migrated+=1
        with m.connect() as con:
            con.execute('''INSERT INTO v35_campaign_identity(legacy_campaign_id,canonical_campaign_id,migration_source)
                           VALUES(?,?,?) ON CONFLICT(legacy_campaign_id) DO UPDATE SET canonical_campaign_id=excluded.canonical_campaign_id''',
                        (old,canonical,'legacy_campaigns'))
    return migrated


def canonical_campaign_id(value: str|None, *, required: bool=False) -> str|None:
    raw=str(value or '').strip()
    if not raw:
        if required: raise ValueError('Choose a campaign.')
        return None
    if m.table_exists('v10_unified_campaigns') and m.one('SELECT 1 ok FROM v10_unified_campaigns WHERE id=?',(raw,)):
        return raw
    mapped=m.one('SELECT canonical_campaign_id FROM v35_campaign_identity WHERE legacy_campaign_id=?',(raw,)) if m.table_exists('v35_campaign_identity') else None
    if mapped and m.one('SELECT 1 ok FROM v10_unified_campaigns WHERE id=?',(mapped['canonical_campaign_id'],)):
        return mapped['canonical_campaign_id']
    # A legacy record may have arrived since startup. Migrate and retry once.
    if m.table_exists('campaigns') and m.one('SELECT 1 ok FROM campaigns WHERE campaign_id=?',(raw,)):
        migrate_campaign_identity()
        mapped=m.one('SELECT canonical_campaign_id FROM v35_campaign_identity WHERE legacy_campaign_id=?',(raw,))
        if mapped:return mapped['canonical_campaign_id']
    raise ValueError('The selected campaign no longer exists in the canonical campaign workspace. Refresh and choose it again.')


def campaign(value: str|None) -> dict|None:
    if not value:return None
    try:cid=canonical_campaign_id(value)
    except ValueError:return None
    return m.one('SELECT * FROM v10_unified_campaigns WHERE id=?',(cid,))


def campaign_search(term: str, limit: int=8) -> list[dict]:
    term=str(term or '').strip()
    if len(term)<2:return []
    like=f'%{term}%';limit=max(1,min(int(limit),50))
    if m.table_exists('v10_unified_campaigns'):
        return m.rows('''SELECT id,name,coalesce(nullif(channels_json,'[]'),'') channels,status
                         FROM v10_unified_campaigns
                         WHERE name LIKE ? AND coalesce(status,'Draft')<>'Archived'
                         ORDER BY updated_at DESC,name LIMIT ?''',(like,limit))
    # Migration/test fallback only. Normal V38 startup always creates the canonical table.
    if m.table_exists('campaigns'):
        return m.rows('''SELECT campaign_id id,campaign_name name,channel channels,status FROM campaigns
                         WHERE campaign_name LIKE ? AND coalesce(status,'Draft')<>'Archived'
                         ORDER BY created_at DESC,campaign_name LIMIT ?''',(like,limit))
    return []


def migrate_canonical_campaign_references() -> int:
    count=0
    specs=[('m42_order_meta','campaign_id','canonical_campaign_id','order_id'),('m42_deal_meta','campaign_id','canonical_campaign_id','deal_id'),('activities','campaign_id','canonical_campaign_id','activity_id')]
    for table,old_col,new_col,key in specs:
        if not m.table_exists(table) or new_col not in _columns(table):continue
        for r in m.rows(f"SELECT {key} object_id,{old_col} campaign_id FROM {table} WHERE coalesce({old_col},'')<>'' AND coalesce({new_col},'')='' LIMIT 100000"):
            try:cid=canonical_campaign_id(r['campaign_id'])
            except ValueError:continue
            with m.connect() as con:con.execute(f'UPDATE {table} SET {new_col}=? WHERE {key}=?',(cid,r['object_id']))
            count+=1
    return count


def active_users() -> list[dict]:
    if not m.table_exists('v11_users'):return []
    return m.rows("SELECT user_id,display_name,email,role FROM v11_users WHERE active=1 ORDER BY display_name COLLATE NOCASE,email")


def resolve_user(value: str|None) -> str:
    raw=str(value or '').strip()
    if not raw:return ''
    row=m.one('SELECT user_id FROM v11_users WHERE user_id=? AND active=1',(raw,)) if m.table_exists('v11_users') else None
    if row:return row['user_id']
    raise ValueError('Choose an active CRM user as the owner.')


def user_label(user_id: str|None, fallback: str='') -> str:
    if user_id and m.table_exists('v11_users'):
        r=m.one('SELECT display_name,email FROM v11_users WHERE user_id=?',(user_id,))
        if r:return r.get('display_name') or r.get('email') or fallback
    return fallback or 'Unassigned'


def migrate_owner_assignments() -> int:
    if not m.table_exists('v11_users'):return 0
    users=active_users();by_name={str(u.get('display_name') or '').strip().casefold():u['user_id'] for u in users};by_email={str(u.get('email') or '').strip().casefold():u['user_id'] for u in users}
    changed=0
    specs=[('m42_contact_meta','contact_id'),('m42_deal_meta','deal_id'),('m4_tasks','id'),('v17_conversations','id')]
    for table,key in specs:
        if not m.table_exists(table) or 'owner_user_id' not in _columns(table) or 'owner' not in _columns(table):continue
        for r in m.rows(f"SELECT {key} object_id,owner FROM {table} WHERE coalesce(owner,'')<>'' AND coalesce(owner_user_id,'')='' LIMIT 100000"):
            raw=str(r.get('owner') or '').strip().casefold();uidv=by_name.get(raw) or by_email.get(raw)
            if uidv:
                with m.connect() as con:con.execute(f'UPDATE {table} SET owner_user_id=? WHERE {key}=?',(uidv,r['object_id']))
                changed+=1
    return changed


def set_owner_user(table: str, key_col: str, object_id: str, user_id: str|None, legacy_label_col: str='owner') -> str:
    uidv=resolve_user(user_id) if user_id else ''
    label=user_label(uidv,'') if uidv else ''
    allowed={'m42_contact_meta','m42_deal_meta','m4_tasks','v17_conversations'}
    if table not in allowed:raise ValueError('Unsupported assignment target.')
    with m.connect() as con:
        con.execute(f'UPDATE {table} SET owner_user_id=?,{legacy_label_col}=? WHERE {key_col}=?',(uidv,label,object_id))
    return uidv


def _ensure_inventory_row(product_id: str, location_id: str='MAIN') -> dict:
    if not m.table_exists('v9_inventory'):raise ValueError('Inventory storage is not available.')
    row=m.one('SELECT * FROM v9_inventory WHERE product_id=? AND location_id=?',(product_id,location_id))
    if row:return row
    stock=m.one('SELECT coalesce(stock_qty,0) stock_qty FROM products WHERE product_id=?',(product_id,))
    if not stock:raise ValueError('Product not found.')
    on=max(0,int(stock.get('stock_qty') or 0))
    with m.connect() as con:
        con.execute('INSERT INTO v9_inventory(product_id,location_id,on_hand,reserved,reorder_point) VALUES(?,?,?,?,?)',(product_id,location_id,on,0,0))
    return m.one('SELECT * FROM v9_inventory WHERE product_id=? AND location_id=?',(product_id,location_id))


def bootstrap_inventory_truth() -> int:
    if not m.table_exists('v9_inventory') or not m.table_exists('products'):return 0
    # Products that pre-date location inventory get a MAIN opening balance.
    for p in m.rows("SELECT product_id,coalesce(stock_qty,0) stock_qty FROM products WHERE coalesce(status,'')<>'Archived'"):
        if not m.one('SELECT 1 ok FROM v9_inventory WHERE product_id=?',(p['product_id'],)):
            with m.connect() as con:con.execute('INSERT INTO v9_inventory(product_id,location_id,on_hand,reserved,reorder_point) VALUES(?,?,?,?,?)',(p['product_id'],'MAIN',max(0,int(p.get('stock_qty') or 0)),0,0))
    created=0
    for inv in m.rows('SELECT product_id,location_id,on_hand FROM v9_inventory'):
        if not m.one("SELECT 1 ok FROM v35_inventory_movements WHERE product_id=? AND location_id=? AND movement_type='Opening balance'",(inv['product_id'],inv['location_id'])):
            on=max(0,int(inv.get('on_hand') or 0))
            with m.connect() as con:
                con.execute('''INSERT INTO v35_inventory_movements(id,product_id,location_id,movement_type,direction,quantity,reason,before_on_hand,after_on_hand)
                               VALUES(?,?,?,?,?,?,?,?,?)''',(uid('MOV35'),inv['product_id'],inv['location_id'],'Opening balance','In',on,'Migrated V34 location balance',0,on))
            created+=1
    sync_all_product_stock_caches()
    return created


def canonical_inventory(product_id: str, location_id: str='MAIN') -> dict:
    row=_ensure_inventory_row(product_id,location_id)
    reserved=max(0,int(row.get('reserved') or 0));on=max(0,int(row.get('on_hand') or 0))
    return {**row,'on_hand':on,'reserved':reserved,'available':max(0,on-reserved)}


def product_available(product_id: str) -> int:
    if not m.table_exists('v9_inventory'):return 0
    r=m.one('SELECT coalesce(sum(on_hand-reserved),0) n FROM v9_inventory WHERE product_id=?',(product_id,)) or {'n':0}
    return max(0,int(r.get('n') or 0))


def sync_product_stock_cache(product_id: str) -> int:
    if not m.table_exists('products') or not m.table_exists('v9_inventory'):return 0
    total=int((m.one('SELECT coalesce(sum(on_hand),0) n FROM v9_inventory WHERE product_id=?',(product_id,)) or {'n':0}).get('n') or 0)
    with m.connect() as con:con.execute('UPDATE products SET stock_qty=? WHERE product_id=?',(total,product_id))
    return total


def sync_all_product_stock_caches() -> None:
    if not m.table_exists('products') or not m.table_exists('v9_inventory'):return
    # Only inventory-backed products have a canonical location balance.  Do not
    # zero an archived/legacy product merely because it has no v9_inventory row.
    for r in m.rows('SELECT DISTINCT product_id FROM v9_inventory'):
        sync_product_stock_cache(r['product_id'])


def reconcile_provider_aggregate_stock(product_id: str, quantity: int, provider: str, reference_id: str='') -> dict:
    """Reconcile a provider's aggregate stock only when local location mapping is unambiguous.

    Shopify/Wix aggregate quantities do not identify an internal location.  One
    local inventory location can be reconciled safely; multiple locations require
    owner mapping rather than guessing.
    """
    if not m.table_exists('v9_inventory'):
        raise ValueError('Inventory storage is not available.')
    rows=m.rows('SELECT location_id,on_hand,reserved FROM v9_inventory WHERE product_id=? ORDER BY location_id',(product_id,))
    if len(rows)>1:
        return {'applied':False,'reason':'multiple_locations','locations':[r.get('location_id') for r in rows]}
    loc=(rows[0].get('location_id') if rows else 'MAIN') or 'MAIN'
    before=int((rows[0].get('on_hand') if rows else (m.one('SELECT coalesce(stock_qty,0) stock_qty FROM products WHERE product_id=?',(product_id,)) or {}).get('stock_qty',0)) or 0)
    result=_reconcile_provider_stock(product_id,max(0,int(quantity)),provider,loc,reference_id)
    return {'applied':True,'location_id':loc,'before':before,'after':int(result.get('on_hand') or 0),'inventory':result}


def _record_stock_movement(product_id: str, location_id: str, movement_type: str, delta: int, reason: str,
                           actor_user_id: str='', reference_type: str='', reference_id: str='', order_item_id: str='') -> dict:
    inv=_ensure_inventory_row(product_id,location_id);before=int(inv.get('on_hand') or 0);after=before+int(delta)
    if after<0:raise ValueError(f'Not enough on-hand stock for {product_id} at {location_id}.')
    direction='In' if delta>=0 else 'Out';qty=abs(int(delta))
    with m.connect() as con:
        con.execute('UPDATE v9_inventory SET on_hand=?,updated_at=CURRENT_TIMESTAMP WHERE product_id=? AND location_id=?',(after,product_id,location_id))
        con.execute('''INSERT INTO v35_inventory_movements(id,product_id,location_id,movement_type,direction,quantity,reason,actor_user_id,reference_type,reference_id,order_item_id,before_on_hand,after_on_hand)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)''',(uid('MOV35'),product_id,location_id,movement_type,direction,qty,reason[:1000],actor_user_id[:120],reference_type[:60],reference_id[:180],order_item_id[:180],before,after))
    sync_product_stock_cache(product_id)
    return canonical_inventory(product_id,location_id)


def adjust_stock_to(product_id: str, location_id: str, target_on_hand: int, reason: str, actor_user_id: str='', reorder_point: int|None=None) -> dict:
    reason=str(reason or '').strip()
    if not reason:raise ValueError('Choose or enter a reason for the stock adjustment.')
    target=max(0,int(target_on_hand));inv=_ensure_inventory_row(product_id,location_id);before=int(inv.get('on_hand') or 0)
    delta=target-before
    if delta:
        _record_stock_movement(product_id,location_id,'Stock adjustment',delta,reason,actor_user_id)
    if reorder_point is not None:
        with m.connect() as con:con.execute('UPDATE v9_inventory SET reorder_point=?,updated_at=CURRENT_TIMESTAMP WHERE product_id=? AND location_id=?',(max(0,int(reorder_point)),product_id,location_id))
    sync_product_stock_cache(product_id)
    return canonical_inventory(product_id,location_id)


def adjust_stock_delta(product_id: str, location_id: str, delta: int, movement_type: str, reason: str,
                       actor_user_id: str='', reference_type: str='', reference_id: str='', order_item_id: str='') -> dict:
    return _record_stock_movement(product_id,location_id,movement_type,int(delta),reason,actor_user_id,reference_type,reference_id,order_item_id)


def reconcile_provider_stock(product_id: str, quantity: int, provider: str='Provider', location_id: str='MAIN', reference_id: str='') -> dict:
    return adjust_stock_to(product_id,location_id,max(0,int(quantity)),f'{provider} inventory reconciliation',reference_id=reference_id) if False else _reconcile_provider_stock(product_id,quantity,provider,location_id,reference_id)


def _reconcile_provider_stock(product_id: str, quantity: int, provider: str, location_id: str, reference_id: str) -> dict:
    inv=_ensure_inventory_row(product_id,location_id);target=max(0,int(quantity));delta=target-int(inv.get('on_hand') or 0)
    if delta:
        return _record_stock_movement(product_id,location_id,f'{provider} reconciliation',delta,f'{provider} stock sync',reference_type='provider',reference_id=reference_id)
    sync_product_stock_cache(product_id);return canonical_inventory(product_id,location_id)


def active_reservation_quantity(order_id: str, product_id: str, location_id: str='MAIN') -> int:
    if not m.table_exists('v17_inventory_movements'):return 0
    reserve=int((m.one("SELECT coalesce(sum(quantity),0) q FROM v17_inventory_movements WHERE reference_type='order' AND reference_id=? AND product_id=? AND location_id=? AND movement_type='Reserve'",(order_id,product_id,location_id)) or {'q':0}).get('q') or 0)
    released=int((m.one("SELECT coalesce(sum(quantity),0) q FROM v17_inventory_movements WHERE reference_type='order' AND reference_id=? AND product_id=? AND location_id=? AND movement_type IN ('Release reservation','Consume reservation')",(order_id,product_id,location_id)) or {'q':0}).get('q') or 0)
    return max(0,reserve-released)


def recalculate_reserved(product_id: str, location_id: str='MAIN') -> int:
    if not m.table_exists('v17_inventory_movements'):return 0
    reserve=int((m.one("SELECT coalesce(sum(quantity),0) q FROM v17_inventory_movements WHERE product_id=? AND location_id=? AND movement_type='Reserve'",(product_id,location_id)) or {'q':0}).get('q') or 0)
    released=int((m.one("SELECT coalesce(sum(quantity),0) q FROM v17_inventory_movements WHERE product_id=? AND location_id=? AND movement_type IN ('Release reservation','Consume reservation')",(product_id,location_id)) or {'q':0}).get('q') or 0)
    derived=max(0,reserve-released)
    _ensure_inventory_row(product_id,location_id)
    with m.connect() as con:con.execute('UPDATE v9_inventory SET reserved=?,updated_at=CURRENT_TIMESTAMP WHERE product_id=? AND location_id=?',(derived,product_id,location_id))
    return derived


def consume_order_reservations(order_id: str, location_id: str='MAIN') -> int:
    if not m.table_exists('order_items'):return 0
    consumed=0
    items=m.rows('SELECT order_item_id,product_id,quantity FROM order_items WHERE order_id=?',(order_id,))
    for item in items:
        active=active_reservation_quantity(order_id,item['product_id'],location_id)
        qty=min(max(0,int(item.get('quantity') or 0)),active)
        if qty<=0:continue
        inv=canonical_inventory(item['product_id'],location_id)
        if int(inv['on_hand'])<qty:raise ValueError(f"Inventory for {item['product_id']} fell below the reserved quantity. Reconcile stock before shipping.")
        with m.connect() as con:
            con.execute('UPDATE v9_inventory SET reserved=max(0,reserved-?),updated_at=CURRENT_TIMESTAMP WHERE product_id=? AND location_id=?',(qty,item['product_id'],location_id))
            con.execute('INSERT INTO v17_inventory_movements(id,product_id,location_id,movement_type,quantity,reference_type,reference_id,note) VALUES(?,?,?,?,?,?,?,?)',(uid('MOV35R'),item['product_id'],location_id,'Consume reservation',qty,'order',order_id,'Reservation consumed by dispatch.'))
        adjust_stock_delta(item['product_id'],location_id,-qty,'Dispatch','Order shipped',reference_type='order',reference_id=order_id,order_item_id=item.get('order_item_id') or '')
        consumed+=qty
    return consumed


def set_product_cost(product_id: str, cost_price: float|str|None, currency: str, source: str='Owner entry', supplier: str='', effective_at: str|None=None, note: str='') -> str:
    if not m.one('SELECT 1 ok FROM products WHERE product_id=?',(product_id,)):raise ValueError('Product not found.')
    if cost_price in (None,''):
        with m.connect() as con:con.execute("UPDATE products SET cost_price=NULL,cost_currency=?,cost_source='',cost_effective_at=NULL,cost_supplier='' WHERE product_id=?",(currency or '',product_id))
        return ''
    try:cost=float(cost_price)
    except Exception:raise ValueError('Enter a valid cost price.') from None
    if not math.isfinite(cost) or cost<0:raise ValueError('Cost price must be zero or greater.')
    source=str(source or 'Owner entry').strip()
    if source not in {'Owner entry','Supplier purchase cost','Imported cost','Estimated cost'}:raise ValueError('Choose a valid cost source.')
    when=str(effective_at or dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()).strip()
    ident=uid('COST35')
    with m.connect() as con:
        con.execute('INSERT INTO v35_product_cost_history(id,product_id,cost_price,currency,source,supplier,effective_at,note) VALUES(?,?,?,?,?,?,?,?)',(ident,product_id,cost,currency[:10],source,supplier[:200],when,note[:1000]))
        con.execute('UPDATE products SET cost_price=?,cost_currency=?,cost_source=?,cost_effective_at=?,cost_supplier=? WHERE product_id=?',(cost,currency[:10],source,when,supplier[:200],product_id))
    return ident


def bootstrap_cost_history() -> int:
    if not m.table_exists('products'):return 0
    created=0
    for p in m.rows('SELECT product_id,cost_price,currency,cost_currency,cost_source,cost_effective_at,cost_supplier FROM products WHERE cost_price IS NOT NULL'):
        if m.one('SELECT 1 ok FROM v35_product_cost_history WHERE product_id=? LIMIT 1',(p['product_id'],)):continue
        ident=uid('COST35')
        with m.connect() as con:
            con.execute('INSERT INTO v35_product_cost_history(id,product_id,cost_price,currency,source,supplier,effective_at,note) VALUES(?,?,?,?,?,?,coalesce(?,CURRENT_TIMESTAMP),?)',
                        (ident,p['product_id'],float(p.get('cost_price') or 0),p.get('cost_currency') or p.get('currency') or '',p.get('cost_source') or 'Imported cost',p.get('cost_supplier') or '',p.get('cost_effective_at'),'Migrated from V34 product cost cache.'))
        created+=1
    return created


def product_cost(product_id: str, at: str|None=None) -> dict:
    if at:
        row=m.one('''SELECT * FROM v35_product_cost_history WHERE product_id=? AND effective_at<=? ORDER BY effective_at DESC,created_at DESC LIMIT 1''',(product_id,at))
    else:
        row=m.one('SELECT * FROM v35_product_cost_history WHERE product_id=? ORDER BY effective_at DESC,created_at DESC LIMIT 1',(product_id,))
    if row:return row
    p=m.one('SELECT cost_price,currency,cost_currency,cost_source FROM products WHERE product_id=?',(product_id,))
    return {'cost_price':p.get('cost_price') if p else None,'currency':(p or {}).get('cost_currency') or (p or {}).get('currency') or '','source':(p or {}).get('cost_source') or ''}


def upsert_order_line_meta(order_item_id: str, product_id: str, unit_discount: float=0, tax_amount: float=0, line_total: float=0, ordered_at: str|None=None) -> None:
    p=m.one('SELECT internal_sku,product_code,currency FROM products WHERE product_id=?',(product_id,)) or {}
    cost=product_cost(product_id,ordered_at)
    with m.connect() as con:
        con.execute('''INSERT INTO v35_order_line_meta(order_item_id,sku_snapshot,unit_discount,tax_amount,line_total,unit_cost_snapshot,cost_currency,cost_source)
                       VALUES(?,?,?,?,?,?,?,?)
                       ON CONFLICT(order_item_id) DO UPDATE SET sku_snapshot=excluded.sku_snapshot,unit_discount=excluded.unit_discount,tax_amount=excluded.tax_amount,line_total=excluded.line_total,
                       unit_cost_snapshot=coalesce(v35_order_line_meta.unit_cost_snapshot,excluded.unit_cost_snapshot),cost_currency=coalesce(nullif(v35_order_line_meta.cost_currency,''),excluded.cost_currency),cost_source=coalesce(nullif(v35_order_line_meta.cost_source,''),excluded.cost_source),updated_at=CURRENT_TIMESTAMP''',
                    (order_item_id,p.get('internal_sku') or p.get('product_code') or '',float(unit_discount or 0),float(tax_amount or 0),float(line_total or 0),cost.get('cost_price'),cost.get('currency') or p.get('currency') or '',cost.get('source') or ''))


def product_readiness(product_id: str) -> dict:
    p=m.one('SELECT * FROM products WHERE product_id=?',(product_id,))
    if not p:return {'product_id':product_id,'ready_to_sell':False,'ready_for_marketing':False,'ready_for_store':False,'blockers':['Product not found'],'states':['Needs Review']}
    blockers=[];marketing=[];store=[]
    if str(p.get('status') or 'Draft')!='Active':blockers.append('Product is not Active')
    if not (p.get('internal_sku') or p.get('product_code')):blockers.append('Missing SKU')
    if not (p.get('public_product_name') or p.get('product_code')):blockers.append('Missing product name')
    if not p.get('description'):marketing.append('Missing description')
    if p.get('retail_price') in (None,'') or float(p.get('retail_price') or 0)<=0:blockers.append('Missing or invalid price')
    cost=product_cost(product_id)
    if cost.get('cost_price') in (None,''):blockers.append('Missing cost data')
    has_inventory=bool(m.table_exists('v9_inventory') and m.one('SELECT 1 ok FROM v9_inventory WHERE product_id=?',(product_id,)))
    if not has_inventory:blockers.append('Missing inventory')
    elif product_available(product_id)<=0:blockers.append('No available stock')
    approved_image=False
    if m.table_exists('product_images'):
        approved_image=bool(m.one('SELECT 1 ok FROM product_images WHERE product_id=? LIMIT 1',(product_id,)))
    if m.table_exists('v6_product_assets'):
        approved_image=approved_image or bool(m.one('SELECT 1 ok FROM v6_product_assets WHERE product_id=? LIMIT 1',(product_id,)))
    if not approved_image:marketing.append('Missing approved/product image')
    if not p.get('category'):store.append('Missing category')
    review=m.one('SELECT confirmed FROM m4_product_review WHERE product_id=?',(product_id,)) if m.table_exists('m4_product_review') else None
    if review and not int(review.get('confirmed') or 0):store.append('Needs product fact review')
    all_blockers=list(dict.fromkeys(blockers+marketing+store))
    ready_sell=not blockers
    ready_marketing=ready_sell and not marketing
    ready_store=ready_marketing and not store
    states=[]
    states.append('Ready to Sell' if ready_sell else (blockers[0] if blockers else 'Needs Review'))
    states.append('Ready for Marketing' if ready_marketing else (marketing[0] if marketing else 'Needs Review'))
    states.append('Ready for Store' if ready_store else (store[0] if store else 'Needs Review'))
    return {'product_id':product_id,'ready_to_sell':ready_sell,'ready_for_marketing':ready_marketing,'ready_for_store':ready_store,'blockers':all_blockers,'states':states,'available_stock':product_available(product_id),'cost':cost}


def assign_products_to_collection(product_ids: list[str], name: str, source: str = 'Owner bulk assignment') -> dict:
    """Attach selected active products to one canonical merchandise collection atomically."""
    initialise()
    ids=list(dict.fromkeys(str(x or '').strip() for x in (product_ids or []) if str(x or '').strip()))
    if not ids:
        raise ValueError('Select at least one product.')
    if len(ids)>100:
        raise ValueError('Select no more than 100 products at a time.')
    collection_name=re.sub(r'\s+',' ',str(name or '').strip())[:160]
    if not collection_name:
        raise ValueError('Enter a collection name before applying the bulk change.')
    placeholders=','.join('?' for _ in ids)
    products=m.rows(f'SELECT product_id,status FROM products WHERE product_id IN ({placeholders})',tuple(ids))
    pmap={r['product_id']:r for r in products}
    if any(pid not in pmap for pid in ids):
        raise ValueError('One or more selected products no longer exist. Refresh the page and try again.')
    if any(str(pmap[pid].get('status') or '')=='Archived' for pid in ids):
        raise ValueError('Archived products cannot be assigned to active collections. Restore them first.')
    existing=m.one('SELECT * FROM v35_collections WHERE lower(name)=lower(?)',(collection_name,))
    if existing and str(existing.get('status') or 'Active')=='Archived':
        raise ValueError('That collection is archived. Restore or choose another collection before assigning products.')
    cid=existing['id'] if existing else uid('COL35')
    with m.connect() as con:
        if not existing:
            con.execute('INSERT INTO v35_collections(id,name,description,status,ai_source) VALUES(?,?,?,?,?)',(cid,collection_name,'','Active',''))
        for pid in ids:
            con.execute('''INSERT INTO v35_collection_products(collection_id,product_id,source) VALUES(?,?,?)
                ON CONFLICT(collection_id,product_id) DO UPDATE SET source=excluded.source''',(cid,pid,source[:160]))
    for pid in ids:
        m.audit('product.collection_bulk_assigned',pid,'Added to merchandise collection '+collection_name+' via '+source+'.')
    return {'id':cid,'name':collection_name,'count':len(ids)}


def apply_collection_suggestions(product_id: str, names: list[str]) -> list[str]:
    if not m.one('SELECT 1 ok FROM products WHERE product_id=?',(product_id,)):raise ValueError('Product not found.')
    ids=[]
    for raw in names:
        name=re.sub(r'\s+',' ',str(raw or '').strip())[:160]
        if not name:continue
        row=m.one('SELECT id FROM v35_collections WHERE lower(name)=lower(?)',(name,))
        cid=row['id'] if row else uid('COL35')
        with m.connect() as con:
            if not row:con.execute('INSERT INTO v35_collections(id,name,ai_source) VALUES(?,?,?)',(cid,name,'AI suggested collection'))
            con.execute('INSERT INTO v35_collection_products(collection_id,product_id,source) VALUES(?,?,?) ON CONFLICT(collection_id,product_id) DO UPDATE SET source=excluded.source',(cid,product_id,'AI suggestion approved by owner'))
        ids.append(cid)
    return ids


def contact_priority(contact_id: str) -> dict:
    c=m.one('SELECT * FROM contacts WHERE contact_id=?',(contact_id,))
    if not c:raise ValueError('Contact not found.')
    fit=max(0,min(100,int(c.get('lead_score') or 0)))
    intent=0;urgency=0;reasons=[]
    # Explicit open opportunity is stronger than keyword/profile fit.
    open_deals=m.rows("SELECT opportunity_id,stage,expected_close_date,estimated_value FROM opportunities WHERE contact_id=? AND coalesce(stage,'') NOT IN ('Won','Lost') ORDER BY created_at DESC LIMIT 10",(contact_id,)) if m.table_exists('opportunities') else []
    if open_deals:
        intent=max(intent,55);reasons.append('Existing open opportunity')
        stage=str(open_deals[0].get('stage') or '').lower()
        if stage in {'quote sent','negotiation','payment pending','selection confirmed'}:intent=max(intent,80);reasons.append('Opportunity is at a buying stage')
    # Due/overdue tasks are urgency, not fit.
    today=dt.date.today().isoformat()
    task=m.one("SELECT due_date,title FROM m4_tasks WHERE contact_id=? AND status='Open' ORDER BY due_date LIMIT 1",(contact_id,)) if m.table_exists('m4_tasks') else None
    if task:
        if str(task.get('due_date') or '')<=today:urgency=max(urgency,80);reasons.append('Follow-up task is due or overdue')
        else:urgency=max(urgency,35);reasons.append('Open follow-up task')
    # Unanswered inbound conversations/messages.
    if m.table_exists('v17_conversations'):
        conv=m.one("SELECT unread_count,last_message_at FROM v17_conversations WHERE contact_id=? AND status='Open' AND coalesce(unread_count,0)>0 ORDER BY last_message_at DESC LIMIT 1",(contact_id,))
        if conv:intent=max(intent,75);urgency=max(urgency,90);reasons.append('Unanswered inbound conversation')
    if m.table_exists('activities'):
        recent=m.one("SELECT activity_type,summary,created_at FROM activities WHERE contact_id=? ORDER BY created_at DESC LIMIT 1",(contact_id,))
        if recent:
            text=(str(recent.get('activity_type') or '')+' '+str(recent.get('summary') or '')).lower()
            if any(k in text for k in ['quote','price','pricing','catalogue','catalog','appointment','enquiry','inquiry','interested']):
                intent=max(intent,70);reasons.append('Recent activity shows buying intent')
    # Weighted priority intentionally gives intent and urgency far more weight than fit.
    score=round(0.2*fit+0.4*intent+0.4*urgency)
    label='High' if score>=65 or urgency>=80 else 'Medium' if score>=35 or intent>=55 else 'Normal'
    result={'contact_id':contact_id,'fit_score':fit,'intent_score':intent,'urgency_score':urgency,'priority_score':score,'priority_label':label,'reasons':list(dict.fromkeys(reasons))}
    with m.connect() as con:
        con.execute('''INSERT INTO v35_sales_priority(contact_id,fit_score,intent_score,urgency_score,priority_score,priority_label,reasons_json)
                       VALUES(?,?,?,?,?,?,?) ON CONFLICT(contact_id) DO UPDATE SET fit_score=excluded.fit_score,intent_score=excluded.intent_score,urgency_score=excluded.urgency_score,priority_score=excluded.priority_score,priority_label=excluded.priority_label,reasons_json=excluded.reasons_json,calculated_at=CURRENT_TIMESTAMP''',
                    (contact_id,fit,intent,urgency,score,label,json.dumps(result['reasons'])))
    return result


def refresh_sales_priorities(limit: int=5000) -> int:
    rows=m.rows("SELECT contact_id FROM contacts WHERE coalesce(lifecycle_stage,'') NOT IN ('Purchased','Lost') ORDER BY created_at DESC LIMIT ?",(max(1,min(int(limit),100000)),))
    for r in rows:
        try:contact_priority(r['contact_id'])
        except Exception:pass
    return len(rows)


def order_profitability(order_id: str) -> dict:
    o=m.one('SELECT * FROM orders WHERE order_id=?',(order_id,))
    if not o:raise ValueError('Order not found.')
    lines=m.rows('''SELECT oi.order_item_id,oi.product_id,oi.quantity,oi.unit_price,lm.unit_discount,lm.tax_amount,lm.line_total,lm.unit_cost_snapshot,lm.cost_source
                    FROM order_items oi LEFT JOIN v35_order_line_meta lm ON lm.order_item_id=oi.order_item_id WHERE oi.order_id=?''',(order_id,)) if m.table_exists('order_items') else []
    revenue=float(o.get('total') or 0);cogs=0.0;missing=[];estimated=[]
    for line in lines:
        if line.get('unit_cost_snapshot') is None:missing.append(line['product_id']);continue
        cogs+=float(line.get('unit_cost_snapshot') or 0)*int(line.get('quantity') or 0)
        if str(line.get('cost_source') or '')=='Estimated cost':estimated.append(line['product_id'])
    local_refunds=float((m.one("SELECT coalesce(sum(refund_amount),0) v FROM v17_return_cases WHERE order_id=? AND status='Completed'",(order_id,)) or {'v':0}).get('v') or 0) if m.table_exists('v17_return_cases') else 0
    provider_refunds=0.0
    if m.table_exists('v40_external_order_meta'):
        ext=m.one('SELECT provider_refund_total,provider_refund_currency FROM v40_external_order_meta WHERE order_id=?',(order_id,)) or {}
        try: provider_refunds=float(ext.get('provider_refund_total') or 0)
        except Exception: provider_refunds=0.0
    # For provider-managed orders, the provider's cumulative refund total is the
    # payment truth once present. Local return records may describe the same refund,
    # so never add both and double-count revenue reversal.
    refunds=provider_refunds if provider_refunds>0 else local_refunds
    # COGS is reversed only for quantities that were physically returned to sellable stock.
    # Refunded-but-not-restocked/damaged items continue to carry their cost.
    cogs_reversal=0.0
    if m.table_exists('v18_return_items') and m.table_exists('v17_return_cases'):
        row=m.one('''SELECT coalesce(sum(coalesce(ri.restocked_quantity,0)*coalesce(lm.unit_cost_snapshot,0)),0) v
                     FROM v18_return_items ri JOIN v17_return_cases rc ON rc.id=ri.return_id
                     JOIN order_items oi ON oi.order_item_id=ri.order_item_id
                     LEFT JOIN v35_order_line_meta lm ON lm.order_item_id=oi.order_item_id
                     WHERE rc.order_id=? AND rc.status='Completed' AND rc.restock=1''',(order_id,)) or {'v':0}
        cogs_reversal=float(row.get('v') or 0)
    cogs=max(0.0,cogs-cogs_reversal)
    net=revenue-refunds;gross=net-cogs;margin=(gross/net*100) if net else None
    return {'order_id':order_id,'revenue':revenue,'refunds':refunds,'local_refunds':local_refunds,'provider_refunds':provider_refunds,'net_revenue':net,'cogs':cogs,'cogs_reversal':cogs_reversal,'gross_profit':gross,'gross_margin_percent':margin,'currency':o.get('currency') or '','cost_complete':not missing,'missing_cost_products':missing,'estimated_cost_products':estimated,'line_count':len(lines)}


def integrity_report(record: bool=True) -> dict:
    initialise_light=False
    findings=[]
    def add(key,severity,objtype,objid,detail):findings.append({'check_key':key,'severity':severity,'object_type':objtype,'object_id':str(objid or ''),'detail':detail})
    # Canonical campaign references.
    if m.table_exists('m42_order_meta'):
        for r in m.rows("SELECT order_id,coalesce(canonical_campaign_id,campaign_id) cid FROM m42_order_meta WHERE coalesce(canonical_campaign_id,campaign_id,'')<>''"):
            if not m.one('SELECT 1 ok FROM v10_unified_campaigns WHERE id=?',(r['cid'],)):add('campaign_integrity','Critical','order',r['order_id'],'Order references a campaign that is missing from the canonical campaign workspace.')
    if m.table_exists('m42_deal_meta'):
        for r in m.rows("SELECT deal_id,coalesce(canonical_campaign_id,campaign_id) cid FROM m42_deal_meta WHERE coalesce(canonical_campaign_id,campaign_id,'')<>''"):
            if not m.one('SELECT 1 ok FROM v10_unified_campaigns WHERE id=?',(r['cid'],)):add('campaign_integrity','High','opportunity',r['deal_id'],'Opportunity references a campaign that is missing from the canonical campaign workspace.')
    # Operational orders must have lines.
    if m.table_exists('orders'):
        for r in m.rows("SELECT o.order_id,o.order_status,o.order_type FROM orders o WHERE o.order_status IN ('Paid','Fulfilled') AND NOT EXISTS (SELECT 1 FROM order_items oi WHERE oi.order_id=o.order_id)"):
            add('order_integrity','Critical','order',r['order_id'],f"{r['order_status']} physical order has no line items.")
    # Product stock cache is allowed only as derived compatibility data.
    if m.table_exists('v9_inventory'):
        for r in m.rows('''SELECT p.product_id,coalesce(p.stock_qty,0) cached,coalesce(sum(i.on_hand),0) canonical
                           FROM products p LEFT JOIN v9_inventory i ON i.product_id=p.product_id GROUP BY p.product_id HAVING coalesce(p.stock_qty,0)<>coalesce(sum(i.on_hand),0)'''):
            add('inventory_integrity','High','product',r['product_id'],f"Catalogue stock cache {r['cached']} differs from canonical location stock {r['canonical']}.")
    # Sold lines need cost snapshots.
    if m.table_exists('v35_order_line_meta'):
        for r in m.rows('''SELECT oi.order_item_id,oi.order_id,oi.product_id FROM order_items oi JOIN orders o ON o.order_id=oi.order_id
                           LEFT JOIN v35_order_line_meta lm ON lm.order_item_id=oi.order_item_id
                           WHERE o.order_status IN ('Paid','Fulfilled','Refunded') AND lm.unit_cost_snapshot IS NULL'''):
            add('cogs_integrity','High','order',r['order_id'],f"Sold line {r['order_item_id']} ({r['product_id']}) has no cost snapshot; profit is incomplete.")
    # Owner references should resolve where owner_user_id is set.
    for table,key,otype in [('m42_contact_meta','contact_id','contact'),('m42_deal_meta','deal_id','opportunity'),('m4_tasks','id','task')]:
        if m.table_exists(table) and 'owner_user_id' in _columns(table):
            for r in m.rows(f"SELECT {key} oid,owner_user_id FROM {table} WHERE coalesce(owner_user_id,'')<>''"):
                if not m.one('SELECT 1 ok FROM v11_users WHERE user_id=? AND active=1',(r['owner_user_id'],)):add('assignment_integrity','High',otype,r['oid'],'Assigned owner does not resolve to an active authenticated user.')
    if record:
        with m.connect() as con:
            con.execute("UPDATE v35_integrity_findings SET status='Resolved' WHERE status='Open'")
            for f in findings:
                con.execute('''INSERT INTO v35_integrity_findings(id,check_key,severity,object_type,object_id,detail,status)
                               VALUES(?,?,?,?,?,?,'Open') ON CONFLICT(check_key,object_type,object_id,detail) DO UPDATE SET severity=excluded.severity,status='Open',detected_at=CURRENT_TIMESTAMP''',
                            (uid('INT35'),f['check_key'],f['severity'],f['object_type'],f['object_id'],f['detail']))
    counts={s:sum(1 for f in findings if f['severity']==s) for s in ['Critical','High','Medium','Low']}
    return {'status':'Pass' if not findings else 'Needs attention','findings':findings,'counts':counts,'total':len(findings)}
