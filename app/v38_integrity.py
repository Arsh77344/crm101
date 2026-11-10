"""V38 canonical transaction integrity checks."""
import db_layer
import marketing as m
import v36_integrity


def integrity_gate(record: bool=False) -> dict:
    base=v36_integrity.integrity_gate(record=record);findings=list(base.get('findings',[]))
    def add(key,severity,obj,oid,detail):findings.append({'check_key':key,'severity':severity,'object_type':obj,'object_id':str(oid or ''),'detail':detail})
    if m.table_exists('orders') and m.table_exists('v17_fulfilments'):
        for r in m.rows('''SELECT o.order_id,o.order_status,f.status fulfilment_status
                           FROM orders o JOIN v17_fulfilments f ON f.order_id=o.order_id'''):
            os=str(r.get('order_status') or '');fs=str(r.get('fulfilment_status') or '')
            if fs=='Delivered' and os not in {'Fulfilled','Refunded'}:
                add('delivered_order_status_mismatch','Critical','order',r['order_id'],f'Fulfilment is Delivered but order status is {os or "blank"}.')
            if os=='Fulfilled' and fs!='Delivered':
                add('fulfilled_without_delivery','Critical','order',r['order_id'],f'Order is Fulfilled but fulfilment status is {fs or "missing"}.')
    if m.table_exists('v37_shipment_items'):
        for r in m.rows('''SELECT oi.order_id,si.order_item_id,oi.quantity ordered,coalesce(sum(si.quantity),0) shipped
                           FROM order_items oi JOIN v37_shipment_items si ON si.order_item_id=oi.order_item_id
                           JOIN v37_shipments s ON s.id=si.shipment_id AND s.status<>'Cancelled'
                           GROUP BY oi.order_id,si.order_item_id,oi.quantity HAVING shipped>ordered'''):
            add('over_shipped_order_line','Critical','order',r['order_id'],f"Order line {r['order_item_id']} shipped {r['shipped']} against {r['ordered']} ordered.")
    # Paid orders must reconcile ordered quantity = shipped quantity + active reservation.
    # This catches split failures where payment/status persisted but inventory reservation did not.
    if all(m.table_exists(t) for t in ('orders','order_items','v17_fulfilments','v17_inventory_movements')):
        rows=m.rows("""SELECT o.order_id,oi.product_id,sum(oi.quantity) ordered
                       FROM orders o JOIN order_items oi ON oi.order_id=o.order_id
                       JOIN v17_fulfilments f ON f.order_id=o.order_id
                       WHERE o.order_status='Paid' AND f.status NOT IN ('Delivered','Cancelled')
                       GROUP BY o.order_id,oi.product_id""")
        for r in rows:
            shipped=0
            if m.table_exists('v37_shipment_items') and m.table_exists('v37_shipments'):
                q=m.one("""SELECT coalesce(sum(si.quantity),0) n FROM v37_shipment_items si
                         JOIN v37_shipments s ON s.id=si.shipment_id
                         WHERE s.order_id=? AND si.product_id=? AND s.status<>'Cancelled'""",(r['order_id'],r['product_id']))
                shipped=int((q or {'n':0})['n'] or 0)
            q=m.one("""SELECT coalesce(sum(CASE WHEN movement_type='Reserve' THEN quantity
                                      WHEN movement_type IN ('Release reservation','Consume reservation') THEN -quantity ELSE 0 END),0) n
                     FROM v17_inventory_movements WHERE reference_type='order' AND reference_id=? AND product_id=?""",(r['order_id'],r['product_id']))
            active=int((q or {'n':0})['n'] or 0);expected=max(0,int(r['ordered'] or 0)-shipped)
            if active!=expected:
                add('paid_order_reservation_mismatch','Critical','order',r['order_id'],f"Product {r['product_id']} has {active} reserved but {expected} unshipped unit(s) require reservation.")

    if m.table_exists('v17_return_cases') and m.table_exists('v18_return_items'):
        for r in m.rows('''SELECT rc.id,rc.order_id,ri.order_item_id,ri.quantity,ri.restocked_quantity
                           FROM v17_return_cases rc JOIN v18_return_items ri ON ri.return_id=rc.id
                           WHERE rc.status='Completed' AND rc.restock=1 AND coalesce(ri.restocked_quantity,0)<ri.quantity'''):
            add('completed_return_not_restocked','Critical','return',r['id'],f"Completed restock return still has {int(r['quantity'])-int(r.get('restocked_quantity') or 0)} unit(s) not posted to inventory.")
        if m.table_exists('v18_accounting_entries'):
            for r in m.rows('''SELECT rc.id,rc.order_id,rc.refund_amount FROM v17_return_cases rc
                               LEFT JOIN v18_accounting_entries ae ON ae.source_type='return' AND ae.source_id=rc.id AND ae.entry_type='Refund'
                               WHERE rc.status='Completed' AND coalesce(rc.refund_amount,0)>0 AND ae.id IS NULL'''):
                add('completed_refund_missing_accounting','Critical','return',r['id'],'Completed monetary refund has no accounting entry.')
    critical=sum(1 for x in findings if x.get('severity')=='Critical');high=sum(1 for x in findings if x.get('severity')=='High')
    return {'status':'Broken' if critical else ('Needs attention' if high else 'Working'),'critical':critical,'high':high,'findings':findings}
