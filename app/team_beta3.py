from __future__ import annotations
import json, sqlite3
from pathlib import Path
import team_beta2

SCHEMA_VERSION='57'

PREFIXES={
    'Contact':('CNT-','CON-'),'Task':'TASK-','Order':'ORD-','Product':'PRD-','Deal':'OPP-','Opportunity':'OPP-',
    'Campaign':'UCAM-','Account':'CMP-','Company':'CMP-'
}
TABLE_KEYS={
    'Contact':('contacts','contact_id'),
    'Task':('m4_tasks','id'),
    'Order':('orders','order_id'),
    'Product':('products','product_id'),
    'Deal':('opportunities','opportunity_id'),
    'Opportunity':('opportunities','opportunity_id'),
    'Campaign':('v10_unified_campaigns','id'),
    'Account':('companies','company_id'),
    'Company':('companies','company_id'),
}

def _tables(con):
    return {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}

def _cols(con,table):
    return {r[1] for r in con.execute(f'PRAGMA table_info({table})')}

def _exists(con, table, key, ident):
    try:return con.execute(f'SELECT 1 FROM {table} WHERE {key}=? LIMIT 1',(ident,)).fetchone() is not None
    except sqlite3.Error:return False

def _repair_transaction_projections(con, changed):
    tables=_tables(con)
    if {'orders','order_items','v35_order_line_meta'}.issubset(tables):
        # Fill nullable order header arithmetic only when immutable line snapshots are
        # complete and prove the existing total. This is reconstruction, not invention.
        for o in con.execute("SELECT order_id,total,subtotal,discount,shipping FROM orders"):
            oid,total,subtotal,discount,shipping=o
            rows=con.execute('''SELECT oi.quantity,oi.unit_price,lm.unit_discount,lm.tax_amount,lm.line_total
                                FROM order_items oi LEFT JOIN v35_order_line_meta lm ON lm.order_item_id=oi.order_item_id
                                WHERE oi.order_id=?''',(oid,)).fetchall()
            if not rows or any(r[4] is None for r in rows):continue
            raw=sum(float(r[1] or 0)*int(r[0] or 0) for r in rows)
            disc=sum(float(r[2] or 0)*int(r[0] or 0) for r in rows)
            tax=sum(float(r[3] or 0) for r in rows)
            line_total=sum(float(r[4] or 0) for r in rows)
            if total is not None and abs(float(total)-line_total)>0.011:continue
            updates=[];params=[]
            if subtotal is None:updates.append('subtotal=?');params.append(round(raw,2))
            if discount is None:updates.append('discount=?');params.append(round(disc,2))
            if shipping is None:updates.append('shipping=?');params.append(0.0)
            if updates:
                params.append(oid);con.execute('UPDATE orders SET '+','.join(updates)+' WHERE order_id=?',params);changed['order_headers']+=1
        # Shipment evidence is authoritative for line fulfilment projection.
        if {'v37_shipment_items','v37_shipments'}.issubset(tables):
            for r in con.execute('''SELECT oi.order_item_id,oi.quantity,coalesce(sum(CASE WHEN s.status<>'Cancelled' THEN si.quantity ELSE 0 END),0) shipped
                                    FROM order_items oi LEFT JOIN v37_shipment_items si ON si.order_item_id=oi.order_item_id
                                    LEFT JOIN v37_shipments s ON s.id=si.shipment_id
                                    GROUP BY oi.order_item_id,oi.quantity'''):
                if int(r[2] or 0)>=int(r[1] or 0)>0:
                    cur=con.execute("UPDATE v35_order_line_meta SET fulfilment_status='Fulfilled',updated_at=CURRENT_TIMESTAMP WHERE order_item_id=? AND coalesce(fulfilment_status,'')<>'Fulfilled'",(r[0],))
                    changed['line_fulfilment']+=cur.rowcount
        # Completed return-item evidence is authoritative for returned quantity projection.
        if {'v18_return_items','v17_return_cases'}.issubset(tables):
            for r in con.execute('''SELECT ri.order_item_id,coalesce(sum(CASE WHEN rc.status='Completed' THEN ri.quantity ELSE 0 END),0) returned
                                    FROM v18_return_items ri JOIN v17_return_cases rc ON rc.id=ri.return_id GROUP BY ri.order_item_id'''):
                cur=con.execute('UPDATE v35_order_line_meta SET returned_quantity=?,updated_at=CURRENT_TIMESTAMP WHERE order_item_id=? AND coalesce(returned_quantity,0)<>?',(int(r[1] or 0),r[0],int(r[1] or 0)))
                changed['returned_quantity']+=cur.rowcount
    if {'orders','v17_return_cases'}.issubset(tables):
        # The normal transaction path sets Refunded once completed refunds reach the order total.
        # Repair older test workspaces to that same evidence-backed state.
        for r in con.execute('''SELECT o.order_id,o.total,o.order_status,coalesce(sum(CASE WHEN rc.status='Completed' THEN rc.refund_amount ELSE 0 END),0) refunded
                                FROM orders o LEFT JOIN v17_return_cases rc ON rc.order_id=o.order_id
                                GROUP BY o.order_id,o.total,o.order_status'''):
            if float(r[1] or 0)>0 and float(r[3] or 0)>=float(r[1] or 0)-0.001 and r[2] != 'Refunded':
                con.execute("UPDATE orders SET order_status='Refunded' WHERE order_id=?",(r[0],));changed['refund_status']+=1
    if {'v17_fulfilments','v17_inventory_movements'}.issubset(tables):
        for r in con.execute("SELECT id,order_id,inventory_status FROM v17_fulfilments WHERE status='Delivered'"):
            active=con.execute("""SELECT coalesce(sum(CASE WHEN movement_type='Reserve' THEN quantity WHEN movement_type IN ('Release reservation','Consume reservation') THEN -quantity ELSE 0 END),0)
                                FROM v17_inventory_movements WHERE reference_type='order' AND reference_id=?""",(r[1],)).fetchone()[0]
            if int(active or 0)==0 and str(r[2] or '')!='Consumed':
                con.execute("UPDATE v17_fulfilments SET inventory_status='Consumed',updated_at=CURRENT_TIMESTAMP WHERE id=?",(r[0],));changed['fulfilment_inventory']+=1

def upgrade_workspace(db_path: Path|str) -> dict:
    """Idempotent beta.2 -> beta.3 repair. Uses persisted evidence; never fabricates identities."""
    db_path=Path(db_path)
    changed={'beta2':{},'order_headers':0,'line_fulfilment':0,'returned_quantity':0,'refund_status':0,'fulfilment_inventory':0,'schema':0}
    changed['beta2']=team_beta2.upgrade_workspace(db_path)
    with sqlite3.connect(db_path) as con:
        _repair_transaction_projections(con,changed)
        con.execute("INSERT OR REPLACE INTO settings(setting_key,setting_value) VALUES('team_release_schema',?)",(SCHEMA_VERSION,))
        con.execute("INSERT OR REPLACE INTO settings(setting_key,setting_value) VALUES('team_release_version','1.0.0-beta.3')")
        con.execute("INSERT OR REPLACE INTO settings(setting_key,setting_value) VALUES('team_release_build','TEAM-TEST-003')")
        changed['schema']=1
        con.commit()
    return changed

def initialise():
    import os
    path=os.environ.get('CRM_DB_PATH')
    return upgrade_workspace(path) if path else {}

def doctor_findings(connect):
    findings=[]
    with connect() as con:
        tables=_tables(con)
        # Canonical business activity identity and referential integrity.
        if 'm42_changes' in tables:
            cols=_cols(con,'m42_changes')
            required={'event_scope','related_object_type','related_object_id'}
            if required-cols:
                findings.append({'check_key':'beta3_activity_contract','severity':'Critical','object_type':'activity','object_id':'','detail':'Canonical activity relationship columns are missing.'})
            else:
                rows=con.execute("SELECT id,object_type,object_id,related_object_type,related_object_id FROM m42_changes WHERE coalesce(event_scope,'business')='business'").fetchall()
                for event_id,typ,ident,rel_typ,rel_id in rows:
                    typ=str(typ or '');ident=str(ident or '')
                    pref=PREFIXES.get(typ)
                    if pref and not ident.startswith(pref):
                        findings.append({'check_key':'activity_entity_identity','severity':'Critical','object_type':'activity','object_id':event_id,'detail':f'{typ} activity uses invalid canonical ID {ident or "blank"}.'});continue
                    table_key=TABLE_KEYS.get(typ)
                    if table_key and table_key[0] in tables and not _exists(con,*table_key,ident):
                        findings.append({'check_key':'orphan_activity_entity','severity':'Critical','object_type':'activity','object_id':event_id,'detail':f'{typ} activity points to missing record {ident}.'})
                    if rel_typ and rel_id:
                        rk=TABLE_KEYS.get(str(rel_typ))
                        if rk and rk[0] in tables and not _exists(con,*rk,str(rel_id)):
                            findings.append({'check_key':'orphan_activity_relationship','severity':'High','object_type':'activity','object_id':event_id,'detail':f'Activity relationship points to missing {rel_typ} {rel_id}.'})
        if {'products','v9_inventory','v9_locations'}.issubset(tables):
            orphan=con.execute('SELECT count(*) FROM v9_inventory i LEFT JOIN v9_locations l ON l.id=i.location_id WHERE l.id IS NULL').fetchone()[0]
            if orphan:findings.append({'check_key':'inventory_location_authority','severity':'Critical','object_type':'inventory','object_id':'','detail':f'{orphan} inventory balance(s) have no valid stock location.'})
            invalid=con.execute('SELECT count(*) FROM v9_inventory WHERE on_hand<0 OR reserved<0 OR reserved>on_hand').fetchone()[0]
            if invalid:findings.append({'check_key':'inventory_balance_invalid','severity':'Critical','object_type':'inventory','object_id':'','detail':f'{invalid} inventory balance(s) have negative or over-reserved stock.'})
            mismatch=con.execute('''SELECT count(*) FROM (SELECT p.product_id,p.stock_qty cached,coalesce(sum(i.on_hand),0) actual
                FROM products p LEFT JOIN v9_inventory i ON i.product_id=p.product_id WHERE coalesce(p.status,'Draft')<>'Archived'
                GROUP BY p.product_id HAVING coalesce(p.stock_qty,0)<>coalesce(sum(i.on_hand),0))''').fetchone()[0]
            if mismatch:findings.append({'check_key':'product_location_stock_mismatch','severity':'Critical','object_type':'inventory','object_id':'','detail':f'{mismatch} active product(s) disagree with authoritative location inventory.'})
        if {'orders','order_items','v35_order_line_meta'}.issubset(tables):
            for r in con.execute('''SELECT o.order_id,o.total,o.subtotal,o.discount,o.shipping,
                    coalesce(sum(oi.quantity*oi.unit_price),0) raw,
                    coalesce(sum(oi.quantity*coalesce(lm.unit_discount,0)),0) discounts,
                    coalesce(sum(coalesce(lm.tax_amount,0)),0) tax,
                    coalesce(sum(coalesce(lm.line_total,oi.quantity*oi.unit_price)),0) line_total,
                    count(*) lines,count(lm.order_item_id) meta_lines
                    FROM orders o JOIN order_items oi ON oi.order_id=o.order_id
                    LEFT JOIN v35_order_line_meta lm ON lm.order_item_id=oi.order_item_id GROUP BY o.order_id'''):
                oid,total,subtotal,discount,shipping,raw,discounts,tax,line_total,lines,meta_lines=r
                if int(lines)==int(meta_lines) and total is not None and abs(float(total)-float(line_total))>0.011:
                    findings.append({'check_key':'order_total_line_mismatch','severity':'Critical','object_type':'order','object_id':oid,'detail':f'Order total {float(total):.2f} disagrees with immutable line total {float(line_total):.2f}.'})
                if int(lines)==int(meta_lines) and (subtotal is None or discount is None or shipping is None):
                    findings.append({'check_key':'order_header_financial_projection_incomplete','severity':'High','object_type':'order','object_id':oid,'detail':'Order line snapshots are complete but subtotal/discount/shipping header projection is incomplete.'})
        if {'order_items','v35_order_line_meta','v37_shipment_items','v37_shipments'}.issubset(tables):
            for r in con.execute('''SELECT oi.order_id,oi.order_item_id,oi.quantity,lm.fulfilment_status,
                    coalesce(sum(CASE WHEN s.status<>'Cancelled' THEN si.quantity ELSE 0 END),0) shipped
                    FROM order_items oi JOIN v35_order_line_meta lm ON lm.order_item_id=oi.order_item_id
                    LEFT JOIN v37_shipment_items si ON si.order_item_id=oi.order_item_id LEFT JOIN v37_shipments s ON s.id=si.shipment_id
                    GROUP BY oi.order_item_id HAVING shipped>=oi.quantity AND coalesce(lm.fulfilment_status,'')<>'Fulfilled' '''):
                findings.append({'check_key':'order_line_fulfilment_projection_stale','severity':'High','object_type':'order','object_id':r[0],'detail':f'Order line {r[1]} is fully shipped but still reports {r[3] or "blank"}.'})
        if {'v18_return_items','v17_return_cases','v35_order_line_meta'}.issubset(tables):
            for r in con.execute('''SELECT rc.order_id,ri.order_item_id,coalesce(sum(CASE WHEN rc.status='Completed' THEN ri.quantity ELSE 0 END),0) returned,lm.returned_quantity
                    FROM v18_return_items ri JOIN v17_return_cases rc ON rc.id=ri.return_id JOIN v35_order_line_meta lm ON lm.order_item_id=ri.order_item_id
                    GROUP BY rc.order_id,ri.order_item_id HAVING returned<>coalesce(lm.returned_quantity,0)'''):
                findings.append({'check_key':'order_line_return_projection_stale','severity':'High','object_type':'order','object_id':r[0],'detail':f'Order line {r[1]} return projection {r[3] or 0} disagrees with completed return quantity {r[2] or 0}.'})
        row=con.execute("SELECT setting_value FROM settings WHERE setting_key='team_release_schema'").fetchone() if 'settings' in tables else None
        if not row or str(row[0])!=SCHEMA_VERSION:
            findings.append({'check_key':'team_release_schema_mismatch','severity':'High','object_type':'release','object_id':'','detail':f'Team workspace schema marker is not {SCHEMA_VERSION}.'})
    return findings
