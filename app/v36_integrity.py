"""V36 production-integrity gate.

Non-destructive checks for contradictions that make the OS unsafe even when pages load.
"""
from __future__ import annotations
import db_layer
import marketing as m
import v35_truth as truth


def _active_reservations(order_id: str) -> int:
    if not m.table_exists('v17_inventory_movements'):return 0
    r=m.one("""SELECT coalesce(sum(CASE WHEN movement_type='Reserve' THEN quantity
                      WHEN movement_type IN ('Release reservation','Consume reservation') THEN -quantity ELSE 0 END),0) n
               FROM v17_inventory_movements WHERE reference_type='order' AND reference_id=?""",(order_id,)) or {'n':0}
    return max(0,int(r.get('n') or 0))


def integrity_gate(record: bool=False) -> dict:
    truth.initialise();findings=[]
    def add(key,severity,obj,id,detail):findings.append({'check_key':key,'severity':severity,'object_type':obj,'object_id':str(id or ''),'detail':detail})
    base=truth.integrity_report(record=record)
    findings.extend(base.get('findings',[]))
    if m.table_exists('orders'):
        for o in m.rows("SELECT order_id,order_status,external_order_reference FROM orders"):
            active=_active_reservations(o['order_id'])
            if o.get('order_status') in {'Cancelled','Refunded','Fulfilled'} and active:
                add('terminal_order_reservation','Critical','order',o['order_id'],f"{o.get('order_status')} order still has {active} active reserved unit(s).")
        for r in m.rows("""SELECT external_order_reference,count(*) n FROM orders
                         WHERE coalesce(external_order_reference,'')<>'' GROUP BY external_order_reference HAVING count(*)>1"""):
            add('duplicate_order_reference','Critical','order_reference',r['external_order_reference'],f"External/reference ID is used by {int(r['n'])} orders.")
    if m.table_exists('v17_fulfilments'):
        for f in m.rows("SELECT order_id,status FROM v17_fulfilments WHERE status IN ('Shipped','Delivered')"):
            active=_active_reservations(f['order_id'])
            if active:add('shipped_reservation','Critical','order',f['order_id'],f"{f['status']} fulfilment still has {active} active reserved unit(s).")
    if m.table_exists('campaigns') and m.table_exists('v10_unified_campaigns'):
        for r in m.rows("""SELECT c.campaign_id FROM campaigns c LEFT JOIN v10_unified_campaigns u ON u.id=c.campaign_id
                         WHERE u.id IS NULL AND coalesce(c.status,'Draft')<>'Archived'"""):
            add('legacy_campaign_without_canonical','High','campaign',r['campaign_id'],'Active legacy campaign has no canonical unified campaign row.')
    critical=sum(1 for x in findings if x['severity']=='Critical')
    high=sum(1 for x in findings if x['severity']=='High')
    return {'status':'Broken' if critical else ('Needs attention' if high else 'Working'),'critical':critical,'high':high,'findings':findings}
