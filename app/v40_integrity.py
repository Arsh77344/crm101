"""V40 business-truth, external-order and recovery integrity checks."""
from __future__ import annotations

import json
import db_layer
import marketing as m
import v39_integrity


def integrity_gate(record: bool=False) -> dict:
    base=v39_integrity.integrity_gate(record=record)
    findings=list(base.get('findings',[]))

    def add(key,severity,obj,oid,detail):
        finding={'check_key':key,'severity':severity,'object_type':obj,'object_id':str(oid or ''),'detail':detail}
        # Keep one factual instance when inherited checks overlap.
        if not any(x.get('check_key')==key and x.get('object_type')==obj and str(x.get('object_id') or '')==str(oid or '') for x in findings):
            findings.append(finding)

    # External provider orders must enter the same physical/commercial truth as
    # owner-created orders. A provider-confirmed paid/fulfilled order with no
    # mapped lines cannot support inventory, fulfilment or COGS truth.
    if m.table_exists('v40_external_order_meta') and m.table_exists('orders'):
        for r in m.rows('''SELECT o.order_id,o.order_status,o.total,o.currency,x.sync_state,x.unmapped_line_count,x.unmapped_lines_json,
                                  x.external_status,x.provider_refund_total,x.provider_refund_currency
                           FROM orders o JOIN v40_external_order_meta x ON x.order_id=o.order_id'''):
            line_count=int((m.one('SELECT count(*) n FROM order_items WHERE order_id=?',(r['order_id'],)) or {'n':0})['n']) if m.table_exists('order_items') else 0
            if r['order_status'] in {'Paid','Fulfilled','Refunded'} and line_count==0:
                add('external_order_missing_lines','Critical','order',r['order_id'],'Provider-confirmed order has no canonical product lines. Revenue, fulfilment and profitability cannot be trusted until its products are mapped and the order is resynced.')
            if int(r.get('unmapped_line_count') or 0)>0 or str(r.get('sync_state') or '')!='Synced':
                try: details=json.loads(r.get('unmapped_lines_json') or '[]')
                except Exception: details=[]
                labels=', '.join(str(x.get('sku') or x.get('external_product_id') or 'unmapped item') for x in details[:5])
                add('external_order_product_mapping','High','order',r['order_id'],f"{int(r.get('unmapped_line_count') or 0)} provider order line(s) are not mapped to canonical products"+(f': {labels}' if labels else '')+'. Map the products/SKUs and resync before relying on fulfilment or margin.')
            provider_refund=float(r.get('provider_refund_total') or 0)
            external_state=str(r.get('external_status') or '').upper()
            if 'REFUND' in external_state and provider_refund<=0:
                add('external_refund_missing_amount','High','order',r['order_id'],'The provider reports a refunded/partially refunded order but no provider refund amount was synced. Revenue and margin need reconciliation before they can be trusted.')
            if provider_refund>float(r.get('total') or 0)+0.01:
                add('external_refund_exceeds_order','Critical','order',r['order_id'],'Provider refund total exceeds the recorded order total. Reconcile the provider order before relying on revenue or profitability.')
            refund_currency=str(r.get('provider_refund_currency') or r.get('currency') or '')
            if provider_refund>0 and refund_currency and str(r.get('currency') or '') and refund_currency!=str(r.get('currency') or ''):
                add('external_refund_currency_mismatch','Critical','order',r['order_id'],'Provider refund currency differs from the order currency. Automatic profitability calculation is unsafe until the order is reconciled.')

    # Source-photo identity must not point to a product that has disappeared.
    if m.table_exists('v40_product_source_fingerprints'):
        for r in m.rows('''SELECT f.product_id,f.fingerprint FROM v40_product_source_fingerprints f
                           LEFT JOIN products p ON p.product_id=f.product_id WHERE p.product_id IS NULL LIMIT 100'''):
            add('product_source_identity_orphaned','High','product',r['product_id'],'A product source-photo identity points to a missing product. Repair the intake identity before processing the same photographs again.')


    # Product uploads staged for recovery must not disappear silently after a restart.
    if m.table_exists('v40_intake_recovery'):
        for r in m.rows("SELECT recovery_id,intake_id,status,last_error,created_at FROM v40_intake_recovery WHERE status='Failed' ORDER BY updated_at DESC LIMIT 50"):
            add('product_intake_retryable','High','product_intake',r.get('intake_id') or r.get('recovery_id'),'A product upload was interrupted but its original ZIP is preserved locally for retry. Open Product preparation and retry or dismiss it after review.')
        for r in m.rows("SELECT recovery_id,intake_id,created_at FROM v40_intake_recovery WHERE status='Staged' AND created_at<datetime('now','-1 hour') LIMIT 50"):
            add('product_intake_stuck','High','product_intake',r.get('intake_id') or r.get('recovery_id'),'A staged product upload has not completed for more than one hour. Product preparation can reconcile it into a retryable failed intake after restart.')

    # Repeated provider failure should be visible as an operational exception,
    # even when the API returned no billable units.
    if m.table_exists('v13_ai_usage'):
        row=m.one("""SELECT count(*) n FROM v13_ai_usage
                     WHERE status<>'Completed' AND datetime(created_at)>=datetime('now','-1 day')""") or {'n':0}
        if int(row.get('n') or 0)>=5:
            add('repeated_ai_provider_failures','High','integration','ai',f"{int(row['n'])} governed AI attempts failed in the last 24 hours. Resolve provider/billing/model access before retrying bulk generation.")

    critical=sum(1 for x in findings if x.get('severity')=='Critical')
    high=sum(1 for x in findings if x.get('severity')=='High')
    return {'status':'Broken' if critical else ('Needs attention' if high else 'Working'),'critical':critical,'high':high,'findings':findings}
