"""V39 canonical handoff and retry-safety integrity checks."""
import db_layer
import marketing as m
import v38_integrity


def integrity_gate(record: bool=False) -> dict:
    base=v38_integrity.integrity_gate(record=record); findings=list(base.get('findings',[]))
    def add(key,severity,obj,oid,detail):
        findings.append({'check_key':key,'severity':severity,'object_type':obj,'object_id':str(oid or ''),'detail':detail})

    # A paid physical order is not valid unless fulfilment exists. V38 reservation
    # checks join fulfilment, so a completely missing handoff needs its own check.
    if m.table_exists('orders') and m.table_exists('v17_fulfilments'):
        for r in m.rows("""SELECT o.order_id FROM orders o
                           LEFT JOIN v17_fulfilments f ON f.order_id=o.order_id
                           WHERE o.order_status='Paid' AND f.id IS NULL"""):
            add('paid_order_missing_fulfilment','Critical','order',r['order_id'],'Paid order has no fulfilment record, so stock reservation/shipping cannot be trusted.')

    # Active paid orders must not silently depend on a product that has become
    # Draft/Sold Out/Archived before dispatch.
    if m.table_exists('orders') and m.table_exists('order_items') and m.table_exists('products'):
        for r in m.rows("""SELECT DISTINCT o.order_id,p.product_id,p.status FROM orders o
                           JOIN order_items oi ON oi.order_id=o.order_id
                           JOIN products p ON p.product_id=oi.product_id
                           WHERE o.order_status='Paid' AND coalesce(p.status,'Draft')<>'Active'"""):
            add('paid_order_product_not_active','High','order',r['order_id'],f"Product {r['product_id']} is {r['status'] or 'Draft'} while the order is still Paid/unfulfilled.")

    # Every order line should carry the immutable commercial snapshot used by
    # profitability. Missing metadata means historical COGS/discount/tax truth is incomplete.
    if m.table_exists('order_items') and m.table_exists('v35_order_line_meta'):
        for r in m.rows("""SELECT oi.order_id,oi.order_item_id,oi.product_id FROM order_items oi
                           LEFT JOIN v35_order_line_meta lm ON lm.order_item_id=oi.order_item_id
                           WHERE lm.order_item_id IS NULL"""):
            add('order_line_missing_commercial_snapshot','High','order',r['order_id'],f"Order line {r['order_item_id']} ({r['product_id']}) has no immutable discount/tax/cost snapshot.")

    # Outbound campaign activity must retain the canonical campaign identity in
    # Customer 360 rather than living only inside opaque metadata JSON.
    if m.table_exists('v10_campaign_sends') and m.table_exists('interactions'):
        try: cols={r['name'] for r in m.rows('PRAGMA table_info(interactions)')}
        except Exception: cols=set()
        if 'canonical_campaign_id' in cols:
            for r in m.rows("""SELECT s.campaign_id,s.contact_id,s.id FROM v10_campaign_sends s
                               WHERE s.status='Submitted' AND NOT EXISTS(
                                 SELECT 1 FROM interactions i WHERE i.contact_id=s.contact_id
                                 AND i.canonical_campaign_id=s.campaign_id
                                 AND json_extract(i.metadata_json,'$.provider_message_id')=s.provider_message_id
                               ) LIMIT 100"""):
                add('campaign_send_missing_customer360_link','High','campaign',r['campaign_id'],f"Submitted campaign send {r['id']} is not represented by a canonical interaction for contact {r['contact_id']}.")

    critical=sum(1 for x in findings if x.get('severity')=='Critical')
    high=sum(1 for x in findings if x.get('severity')=='High')
    return {'status':'Broken' if critical else ('Needs attention' if high else 'Working'),'critical':critical,'high':high,'findings':findings}
