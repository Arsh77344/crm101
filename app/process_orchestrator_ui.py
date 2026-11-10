from __future__ import annotations

import csv
import io
import re

import marketing as m
import process_orchestrator as po
import db_layer
import integration_layer as il


def _pill(app,status: str) -> str:
    s=(status or '').lower()
    kind='good' if s in {'complete','published','delivered','ready','posted','completed','closed'} else 'warn' if any(x in s for x in ['attention','blocked','setup','shortage','failed','retry','rejected']) else 'purple'
    return f'<span class="pill {kind}">{app.e(status)}</span>'


def _post_button(label: str, action: str, kind: str='secondary', confirm: str='') -> str:
    attr=f' data-confirm="{confirm}"' if confirm else ''
    return f'<form method="post" action="{action}" style="display:inline"{attr}><button class="btn {kind}" type="submit">{label}</button></form>'


class ProcessOrchestratorPages:
    def v17_get(self,path,q):
        if path=='/operations':self.operations_home(q)
        elif path=='/operations/refresh':self.redirect('/operations')
        elif path=='/operations/actions':self.operations_actions(q)
        elif path=='/operations/inbox':self.operations_inbox(q)
        elif path=='/operations/fulfilments':self.operations_fulfilments(q)
        elif path=='/operations/returns':self.operations_returns(q)
        elif path=='/operations/retention':self.operations_retention(q)
        elif path=='/operations/social':self.operations_social(q)
        elif path=='/operations/accounting':self.operations_accounting(q)
        elif path=='/operations/accounting.csv':self.operations_accounting_csv()
        elif path=='/v17-e2e' or path=='/v18-e2e':self.operations_e2e(q)
        elif re.fullmatch(r'/operations/process/[^/]+',path):self.operations_process(path.split('/')[-1])
        elif re.fullmatch(r'/operations/orders/[^/]+',path):self.operations_order(path.split('/')[-1],q)
        else:return False
        return True

    def v17_post(self,path,f):
        val=lambda k,d='':f.get(k,[d])[0]
        if path=='/operations/refresh':
            po.refresh_all(500);return self.redirect('/operations?refreshed=1')
        if re.fullmatch(r'/operations/orders/[^/]+/prepare',path):
            oid=path.split('/')[-2];po.ensure_fulfilment(oid);pid=po.ensure_process('order_to_retention','order',oid,order_id=oid);po.refresh_process(pid);return self.redirect('/operations/orders/'+oid+'?prepared=1')
        if re.fullmatch(r'/operations/orders/[^/]+/reserve',path):
            oid=path.split('/')[-2];po.reserve_order_inventory(oid);return self.redirect('/operations/orders/'+oid+'?reserved=1')
        if re.fullmatch(r'/operations/fulfilments/[^/]+/packed',path):
            fid=path.split('/')[-2];po.mark_packed(fid);row=m.one('SELECT order_id FROM v17_fulfilments WHERE id=?',(fid,));return self.redirect('/operations/orders/'+row['order_id']+'?packed=1')
        if re.fullmatch(r'/operations/fulfilments/[^/]+/shipped',path):
            fid=path.split('/')[-2];po.mark_shipped(fid,val('carrier'),val('tracking_number'),val('tracking_url'));row=m.one('SELECT order_id FROM v17_fulfilments WHERE id=?',(fid,));return self.redirect('/operations/orders/'+row['order_id']+'?shipped=1')
        if re.fullmatch(r'/operations/fulfilments/[^/]+/partial-shipment',path):
            fid=path.split('/')[-2];row=m.one('SELECT order_id FROM v17_fulfilments WHERE id=?',(fid,));items={}
            for k,values in f.items():
                if not k.startswith('ship_'):continue
                try:qty=int(values[0] or 0)
                except Exception:qty=0
                if qty>0:items[k[5:]]=qty
            po.create_partial_shipment(fid,items,val('carrier'),val('tracking_number'),val('tracking_url'),val('idempotency_key'))
            return self.redirect('/operations/orders/'+row['order_id']+'?partial_shipped=1')
        if re.fullmatch(r'/operations/shipments/[^/]+/delivered',path):
            sid=path.split('/')[-2];row=m.one('SELECT order_id FROM v37_shipments WHERE id=?',(sid,));po.mark_shipment_delivered(sid);return self.redirect('/operations/orders/'+row['order_id']+'?shipment_delivered=1')
        if re.fullmatch(r'/operations/fulfilments/[^/]+/delivered',path):
            fid=path.split('/')[-2];po.mark_delivered(fid);row=m.one('SELECT order_id FROM v17_fulfilments WHERE id=?',(fid,));return self.redirect('/operations/orders/'+row['order_id']+'?delivered=1')
        if re.fullmatch(r'/operations/orders/[^/]+/return',path):
            oid=path.split('/')[-2];items={}
            for k,values in f.items():
                if not k.startswith('item_'):continue
                try:qty=int(values[0] or 0)
                except Exception:qty=0
                if qty>0:items[k[5:]]=qty
            po.create_return(oid,val('reason'),val('resolution','Refund'),val('case_type','Return'),items);return self.redirect('/operations/orders/'+oid+'?return_created=1')
        if re.fullmatch(r'/operations/returns/[^/]+/update',path):
            rid=path.split('/')[-2];po.update_return(rid,val('status'),val('refund_amount','0'),val('restock')=='1',val('note'),val('external_refund_id'));row=m.one('SELECT order_id FROM v17_return_cases WHERE id=?',(rid,));return self.redirect('/operations/orders/'+row['order_id']+'?return_updated=1')
        if path=='/operations/social/schedule':
            asset_url=val('asset_url')
            if not asset_url and val('asset_ref'):
                asset_url=po.resolve_campaign_asset_url(val('asset_ref'))
            po.schedule_social_post(val('campaign_id'),val('channel'),asset_url,val('caption'),val('scheduled_at'),val('product_id'));return self.redirect('/operations/social?scheduled=1')
        if re.fullmatch(r'/operations/social/[^/]+/(retry|publish-now|cancel)',path):
            parts=path.split('/');sid=parts[-2];action={'retry':'retry','publish-now':'publish_now','cancel':'cancel'}[parts[-1]];po.social_post_action(sid,action);return self.redirect('/operations/social?action='+action)
        if re.fullmatch(r'/operations/actions/[^/]+/done',path):
            aid=path.split('/')[-2];po.resolve_next_action(aid,val('note'));return self.redirect('/operations/actions?resolved=1')
        if re.fullmatch(r'/operations/actions/[^/]+/snooze',path):
            aid=path.split('/')[-2];po.snooze_next_action(aid,int(val('days','1') or 1));return self.redirect('/operations/actions?snoozed=1')
        if path=='/operations/inbox/mark-read':
            cid=val('conversation_id')
            with m.connect() as con:con.execute('UPDATE v17_conversations SET unread_count=0,updated_at=CURRENT_TIMESTAMP WHERE id=?',(cid,))
            return self.redirect('/operations/inbox')
        if re.fullmatch(r'/operations/inbox/[^/]+/assign',path):
            po.assign_conversation(path.split('/')[-2],val('owner'));return self.redirect('/operations/inbox?assigned=1')
        if re.fullmatch(r'/operations/inbox/[^/]+/(close|reopen)',path):
            cid=path.split('/')[-2];po.set_conversation_status(cid,'Closed' if path.endswith('/close') else 'Open');return self.redirect('/operations/inbox?status=1')
        if re.fullmatch(r'/operations/inbox/[^/]+/task',path):
            po.create_conversation_task(path.split('/')[-2],val('title','Reply to customer'));return self.redirect('/operations/inbox?task=1')
        if re.fullmatch(r'/operations/inbox/[^/]+/email',path):
            po.send_conversation_email(path.split('/')[-2],val('subject'),val('message'),val('confirm'));return self.redirect('/operations/inbox?email_sent=1')
        if re.fullmatch(r'/operations/retention/[^/]+/(complete|cancel|snooze)',path):
            rid=path.split('/')[-2];action=path.split('/')[-1];po.update_retention_action(rid,action,int(val('days','7') or 7));return self.redirect('/operations/retention?action='+action)
        if re.fullmatch(r'/operations/accounting/[^/]+/status',path):
            po.update_accounting_entry(path.split('/')[-2],val('status'),val('external_id'),val('note'));return self.redirect('/operations/accounting?updated=1')
        return False

    def operations_home(self,q):
        import app
        d=po.dashboard();counts={r['status']:int(r['n']) for r in d['process_counts']};profit=d['profitability']
        try:profit_evidence=json.loads(profit.get('evidence_json') or '{}')
        except Exception:profit_evidence={}
        if str(profit.get('currency') or '')=='MULTI':
            contribution_label='Multiple currencies';contribution_help='Not combined. Open Reporting for currency-separated totals.'
        elif not profit_evidence.get('cost_complete',True):
            contribution_label=app.e(profit.get('currency') or '')+' '+format(float(profit.get('contribution') or 0),'.2f');contribution_help='Profit incomplete · one or more sold lines have no cost snapshot.'
        else:
            contribution_label=app.e(profit.get('currency') or '')+' '+format(float(profit.get('contribution') or 0),'.2f');contribution_help='Revenue − recorded COGS − synced ad spend'
        actions=_post_button('Refresh processes','/operations/refresh','secondary')
        body=app.pagehead('Operations Centre','Run the handoffs between product, marketing, CRM, orders, fulfilment, service, finance and retention.',actions)
        if q.get('refreshed'):body+=app.notice('Business processes refreshed from current evidence.','success')
        body+=f'''<div class="stats-grid"><div class="card stat-card"><span class="stat-label">{sum(counts.values())}</span><strong>Tracked processes</strong><span class="helper">Products, leads, campaigns and orders</span></div><div class="card stat-card"><span class="stat-label">{counts.get('Needs attention',0)+counts.get('Blocked',0)}</span><strong>Need attention</strong><span class="helper">Unsafe or blocked handoffs</span></div><div class="card stat-card"><span class="stat-label">{d['inbox']['unread']}</span><strong>Unread conversations</strong><span class="helper">Unified customer activity</span></div><div class="card stat-card"><span class="stat-label">{contribution_label}</span><strong>Contribution</strong><span class="helper">{contribution_help}</span></div></div>'''
        body+='<div class="two section"><div class="card"><div class="eyebrow">What needs action?</div><h2>Next actions</h2>'
        if d['open_actions']:
            for x in d['open_actions'][:8]:body+=f'<div class="readiness-row"><div class="row-main"><strong>{app.e(x["title"])}</strong><small>{app.e(x["reason"])}</small></div>{app.button("Open",x["action_url"] or "/operations/actions","secondary small")}</div>'
        else:body+='<p class="helper">No open next actions are recorded.</p>'
        body+='</div><div class="card"><div class="eyebrow">Order operations</div><h2>Fulfilment queue</h2>'
        if d['fulfilments']:
            for f in d['fulfilments'][:8]:body+=f'<div class="readiness-row"><div class="row-main"><strong>{app.e(f["order_id"])}</strong><small>{app.e(f["status"])} · inventory {app.e(f["inventory_status"])}</small></div>{app.button("Open","/operations/orders/"+f["order_id"],"secondary small")}</div>'
        else:body+='<p class="helper">No open fulfilments.</p>'
        body+='</div></div>'
        body+='<div class="campaign-grid section">'+app.button('Next actions','/operations/actions','secondary')+app.button('Fulfilment & shipping','/operations/fulfilments','secondary')+app.button('Returns & refunds','/operations/returns','secondary')+app.button('Unified inbox','/operations/inbox','secondary')+app.button('Retention','/operations/retention','secondary')+app.button('Social scheduler','/operations/social','secondary')+app.button('Accounting handoff','/operations/accounting','secondary')+'</div>'
        procs=po.processes(100);body+='<div class="card section"><h2>End-to-end processes</h2><table><thead><tr><th>Process</th><th>Object</th><th>Status</th><th>Current handoff</th><th></th></tr></thead><tbody>'
        for p in procs:body+=f'<tr><td>{app.e(p["process_type"].replace("_"," ").title())}</td><td>{app.e(p["object_id"])}</td><td>{_pill(app,p["status"])}</td><td>{app.e(p["current_step"] or "Complete")}</td><td>{app.button("Open","/operations/process/"+p["id"],"secondary small")}</td></tr>'
        if not procs:body+='<tr><td colspan="5">No processes yet. Use Refresh processes to bootstrap from existing products, contacts, campaigns and orders.</td></tr>'
        body+='</tbody></table></div>'
        self.send_html(app.layout('Operations Centre',body,'operations'))

    def operations_process(self,pid):
        import app
        p=po.process(pid);body=app.pagehead(p['process_type'].replace('_',' ').title(),f"Tracks the handoffs for {p['object_type']} {p['object_id']}.",app.button('Operations Centre','/operations','secondary'))
        body+=f'<div class="card section"><strong>Overall status:</strong> {_pill(app,p["status"])} <span class="helper">Current handoff: {app.e(p["current_step"] or "Complete")}</span></div>'
        body+='<div class="card section"><table><thead><tr><th>#</th><th>Stage</th><th>Status</th><th>Evidence / blocker</th><th></th></tr></thead><tbody>'
        for s in p['steps']:body+=f'<tr><td>{s["sequence_no"]}</td><td><strong>{app.e(s["label"])}</strong></td><td>{_pill(app,s["status"])}</td><td>{app.e(s["detail"])}</td><td>{app.button("Open",s["action_url"],"secondary small") if s.get("action_url") else ""}</td></tr>'
        body+='</tbody></table></div>'
        if p['process_type']=='campaign_to_revenue':
            rows=m.rows('SELECT * FROM v17_campaign_actions WHERE campaign_id=? ORDER BY channel,action_type',(p['object_id'],));body+='<div class="card section"><h2>Channel execution handoffs</h2><p class="helper">Ready never means sent, published or launched. Completion requires execution/provider evidence.</p><table><thead><tr><th>Channel</th><th>Action</th><th>Status</th><th>Next step</th><th></th></tr></thead><tbody>'
            for x in rows:body+=f'<tr><td>{app.e(x["channel"])}</td><td><strong>{app.e(x["action_type"])}</strong></td><td>{_pill(app,x["status"])}</td><td>{app.e(x["detail"])}</td><td>{app.button("Open",x["action_url"],"secondary small") if x.get("action_url") else ""}</td></tr>'
            if not rows:body+='<tr><td colspan="5">No channel handoffs have been prepared yet.</td></tr>'
            body+='</tbody></table></div>'
        self.send_html(app.layout('Business process',body,'operations'))

    def operations_fulfilments(self,q):
        import app
        status=(q.get('status') or [''])[0] if isinstance(q.get('status'),list) else (q.get('status') or '')
        where='';args=[]
        if status:where=' WHERE f.status=?';args=[status]
        rows=m.rows('SELECT f.*,o.total,o.currency,o.order_status FROM v17_fulfilments f LEFT JOIN orders o USING(order_id)'+where+' ORDER BY CASE f.status WHEN \'Needs item review\' THEN 0 WHEN \'Ready to pack\' THEN 1 WHEN \'Packed\' THEN 2 WHEN \'Shipped\' THEN 3 ELSE 4 END,f.created_at DESC LIMIT 500',tuple(args))
        body=app.pagehead('Fulfilment & shipping','Operational queue from inventory reservation through delivery.',app.button('Operations Centre','/operations','secondary'))
        body+='<div class="campaign-grid section">'+''.join(app.button(x or 'All','/operations/fulfilments'+(('?status='+app.query(x)) if x else ''),'secondary') for x in ['', 'Needs item review','Ready to pack','Packed','Shipped','Delivered'])+'</div>'
        body+='<div class="card section"><table><thead><tr><th>Order</th><th>Order status</th><th>Inventory</th><th>Fulfilment</th><th>Carrier</th><th>Tracking</th><th></th></tr></thead><tbody>'
        for r in rows:body+=f'<tr><td><strong>{app.e(r["order_id"])}</strong></td><td>{app.e(r["order_status"])}</td><td>{_pill(app,r["inventory_status"])}</td><td>{_pill(app,r["status"])}</td><td>{app.e(r["carrier"] or "—")}</td><td>{app.e(r["tracking_number"] or "—")}</td><td>{app.button("Open","/operations/orders/"+r["order_id"],"secondary small")}</td></tr>'
        if not rows:body+='<tr><td colspan="7">No fulfilments in this view.</td></tr>'
        body+='</tbody></table></div>';self.send_html(app.layout('Fulfilment & shipping',body,'operations'))

    def operations_order(self,oid,q):
        import app
        order=m.one('SELECT * FROM orders WHERE order_id=?',(oid,))
        if not order:return self.error_page('Order not found.',404)
        existing=m.one("SELECT id FROM v17_processes WHERE process_type='order_to_retention' AND object_type='order' AND object_id=?",(oid,));pid=(existing or {}).get('id','')
        f=m.one('SELECT * FROM v17_fulfilments WHERE order_id=?',(oid,));returns=m.rows('SELECT * FROM v17_return_cases WHERE order_id=? ORDER BY requested_at DESC',(oid,));acc=m.rows('SELECT * FROM v18_accounting_entries WHERE order_id=? ORDER BY created_at DESC',(oid,)) if m.table_exists('v18_accounting_entries') else [];ret=m.rows('SELECT * FROM v17_retention_actions WHERE order_id=? ORDER BY due_at',(oid,));returnable=po.order_returnable_items(oid);events=po.operation_events('order',oid,50)
        head=(app.button('Process view','/operations/process/'+pid,'secondary') if pid else '')+app.button('Orders','/orders','secondary')
        body=app.pagehead('Order operations · '+oid,'Move this order safely from inventory through fulfilment, delivery, returns, finance and retention.',head)
        for key,msg in [('prepared','Fulfilment prepared.'),('reserved','Inventory reservation refreshed.'),('packed','Order marked packed.'),('shipped','Shipment confirmed.'),('partial_shipped','Partial shipment confirmed.'),('shipment_delivered','Shipment delivery confirmed.'),('delivered','Delivery confirmed.'),('return_created','Return/exchange case opened.'),('return_updated','Return/refund case updated.')]:
            if q.get(key):body+=app.notice(msg,'success')
        if not f:
            body+='<div class="card section"><h2>Start fulfilment</h2><p class="helper">This creates the operational fulfilment record and idempotently reserves recorded inventory. It does not book a carrier.</p>'+_post_button('Prepare fulfilment','/operations/orders/'+app.e(oid)+'/prepare','')+'</div>'
        else:
            body+=f'<div class="card section"><div class="message-top"><div><h2>Fulfilment</h2>{_pill(app,f["status"])}</div></div><p class="helper">Inventory: {app.e(f["inventory_status"])} · Carrier: {app.e(f["carrier"] or "Not selected")} · Tracking: {app.e(f["tracking_number"] or "Not assigned")}</p>'
            if f['inventory_status'] in {'Pending','Shortage'}:body+=_post_button('Recheck inventory','/operations/orders/'+app.e(oid)+'/reserve','secondary')
            if f['status'] in {'Ready to pack'}:body+=_post_button('Mark packed','/operations/fulfilments/'+app.e(f['id'])+'/packed','secondary')
            progress=po.fulfilment_line_progress(oid);shipments=po.shipment_rows(oid)
            if f['status'] in {'Packed','Partially shipped'} and progress:
                body+='<div class="section"><h3>Ship order items</h3><p class="helper">Choose exactly what is leaving now. Remaining quantities stay reserved for a later shipment.</p><form method="post" action="/operations/fulfilments/'+app.e(f['id'])+'/partial-shipment"><table><thead><tr><th>Product</th><th>Ordered</th><th>Already shipped</th><th>Ship now</th></tr></thead><tbody>'
                for line in progress:body+=f'<tr><td>{app.e(line["product_name"])}</td><td>{line["ordered_quantity"]}</td><td>{line["shipped_quantity"]}</td><td><input style="width:90px" type="number" min="0" max="{line["remaining_quantity"]}" value="{line["remaining_quantity"]}" name="ship_{app.e(line["order_item_id"])}"></td></tr>'
                body+='</tbody></table><div class="formgrid section">'+app.field('Carrier','<input name="carrier" required placeholder="Royal Mail / DHL / other">')+app.field('Tracking number','<input name="tracking_number" required>')+app.field('Tracking URL','<input name="tracking_url" type="url" placeholder="https://...">')+'</div><input type="hidden" name="idempotency_key" value="'+app.e('ship:'+oid+':'+str(len(shipments)+1))+'"><button class="btn" type="submit">Confirm this shipment</button></form></div>'
            if shipments:
                body+='<div class="section"><h3>Shipment history</h3>'
                for sh in shipments:
                    body+=f'<div class="readiness-row"><div class="row-main"><strong>{app.e(sh["carrier"])} · {app.e(sh["tracking_number"])}</strong><small>{int(sh["item_quantity"] or 0)} unit(s) · {app.e(sh["status"])}</small></div>'
                    if sh['status']!='Delivered':body+=_post_button('Confirm delivered','/operations/shipments/'+app.e(sh['id'])+'/delivered','secondary','Confirm this shipment was delivered?')
                    body+='</div>'
                body+='</div>'
            if f['status']=='Shipped' and not shipments:body+=_post_button('Confirm delivered','/operations/fulfilments/'+app.e(f['id'])+'/delivered','', 'Confirm the customer/order has actually been delivered?')
            body+='</div>'
        body+='<div class="two section"><div class="card"><h2>Open return / exchange</h2><form method="post" action="/operations/orders/'+app.e(oid)+'/return"><div class="formgrid">'+app.field('Type','<select name="case_type">'+app.options(['Return','Exchange','Refund request'])+'</select>')+app.field('Resolution','<select name="resolution">'+app.options(['Refund','Exchange','Store credit','Repair/other'])+'</select>')+'</div>'
        if returnable:
            body+='<p class="helper">Choose only the items and quantities the customer is actually returning.</p><table><thead><tr><th>Product</th><th>Purchased</th><th>Shipped</th><th>Already claimed</th><th>Return now</th></tr></thead><tbody>'
            for item in returnable:body+=f'<tr><td>{app.e(item["product_name"])}</td><td>{item["quantity"]}</td><td>{item.get("shipped_quantity",item["quantity"])}</td><td>{item["claimed_quantity"]}</td><td><input style="width:90px" type="number" min="0" max="{item["returnable_quantity"]}" value="0" name="item_{app.e(item["order_item_id"])}"></td></tr>'
            body+='</tbody></table>'
        body+=app.field('Reason','<textarea name="reason" required></textarea>')+'<button class="btn secondary" type="submit">Open case</button></form></div><div class="card"><h2>Accounting handoff</h2>'
        for a in acc:body+=f'<div class="readiness-row"><div class="row-main"><strong>{app.e(a["entry_type"])}</strong><small>{app.e(a["currency"])} {float(a["amount"] or 0):.2f}</small></div>{_pill(app,a["status"])}</div>'
        if not acc:body+='<p class="helper">Accounting entries are prepared automatically when the order process refreshes.</p>'
        body+='</div></div>'
        if returns:
            body+='<div class="card section"><h2>Return/refund cases</h2>'
            for r in returns:
                items=po.return_items(r['id']);value=sum(int(x.get('quantity') or 0)*float(x.get('unit_price') or 0) for x in items)
                body+=f'<div class="card section"><div class="message-top"><div><strong>{app.e(r["case_type"])} · {app.e(r["requested_resolution"])}</strong>{_pill(app,r["status"])}</div><span class="helper">Eligible value {app.e(r["currency"])} {value:.2f}</span></div><p class="helper">{app.e(r["reason"])}</p>'
                if items:body+='<p class="tiny muted">'+app.e(' · '.join(f"{x['product_name']} × {x['quantity']}" for x in items))+'</p>'
                if r['status'] not in {'Completed','Rejected','Cancelled'}:
                    allowed=list(po._RETURN_TRANSITIONS.get(r['status'],set()));body+='<form method="post" action="/operations/returns/'+app.e(r['id'])+'/update"><div class="formgrid">'+app.field('Next status','<select name="status">'+app.options([(r['status'],r['status'])]+[(x,x) for x in allowed],r['status'])+'</select>')+app.field('Refund amount','<input type="number" step="0.01" min="0" max="'+str(value)+'" name="refund_amount" value="'+app.e(r['refund_amount'])+'">')+app.field('External/manual refund reference','<input name="external_refund_id" value="'+app.e(r['external_refund_id'])+'">')+'</div><label class="checkline"><input type="checkbox" name="restock" value="1" '+('checked' if r['restock'] else '')+'> Restock only the returned quantities when completed</label>'+app.field('Note','<textarea name="note">'+app.e(r['note'])+'</textarea>')+'<button class="btn secondary" type="submit">Update case</button></form>'
                body+='</div>'
            body+='</div>'
        body+='<div class="card section"><h2>Post-purchase & retention</h2>'
        for r in ret:body+=f'<div class="readiness-row"><div class="row-main"><strong>{app.e(r["title"])}</strong><small>Due {app.e(r["due_at"])} · {app.e(r["reason"])}</small></div>{_pill(app,r["status"])}</div>'
        if not ret:body+='<p class="helper">Retention actions are created after verified purchase/delivery evidence.</p>'
        body+='</div><div class="card section"><h2>Operational audit trail</h2>'
        for ev in events:body+=f'<div class="readiness-row"><div class="row-main"><strong>{app.e(ev["event_type"])}</strong><small>{app.e(ev["created_at"])} · {app.e(ev["detail"])}</small></div></div>'
        if not events:body+='<p class="helper">No operation events recorded yet.</p>'
        body+='</div>';self.send_html(app.layout('Order operations',body,'operations'))

    def operations_actions(self,q):
        import app
        rows=m.rows("SELECT a.*,s.snoozed_until,s.resolution_note FROM v17_next_actions a LEFT JOIN v18_action_state s ON s.action_id=a.id WHERE a.status IN ('Open','Snoozed') ORDER BY CASE a.status WHEN 'Open' THEN 0 ELSE 1 END,CASE priority WHEN 'High' THEN 0 WHEN 'Medium' THEN 1 ELSE 2 END,a.created_at DESC LIMIT 500")
        body=app.pagehead('Next actions','Actionable work generated by current business evidence.',app.button('Operations Centre','/operations','secondary'))
        if q.get('resolved'):body+=app.notice('Action marked resolved. It will reopen only if the underlying condition is still present on a later refresh.','success')
        if q.get('snoozed'):body+=app.notice('Action snoozed.','success')
        for x in rows:
            snoozed_note='<p class="tiny muted">Snoozed until '+app.e(x["snoozed_until"])+"</p>" if x.get("snoozed_until") else ""
            body+=f'<div class="card section"><div class="message-top"><div>{_pill(app,x["priority"])} <strong>{app.e(x["title"])}</strong><p class="helper">{app.e(x["reason"])}</p>{snoozed_note}</div><div class="actions">{app.button("Open",x["action_url"] or "/operations","secondary")}</div></div>'
            body+=f'<form method="post" action="/operations/actions/{app.e(x["id"])}/done" class="section"><div class="formgrid">'+app.field('Resolution note','<input name="note" placeholder="What changed?">')+'<div><button class="btn secondary" type="submit">Mark resolved</button></div></div></form>'
            body+=f'<form method="post" action="/operations/actions/{app.e(x["id"])}/snooze"><div class="formgrid">'+app.field('Snooze days','<input type="number" min="1" max="90" name="days" value="1">')+'<div><button class="btn secondary" type="submit">Snooze</button></div></div></form></div>'
        if not rows:body+='<div class="card empty">No open or snoozed next actions.</div>'
        self.send_html(app.layout('Next actions',body,'operations'))

    def operations_inbox(self,q):
        import app
        convs=m.rows('SELECT * FROM v17_conversations ORDER BY CASE status WHEN \'Open\' THEN 0 ELSE 1 END,unread_count DESC,last_message_at DESC LIMIT 300')
        body=app.pagehead('Unified inbox','One customer conversation view with ownership, follow-up and safe Email reply.',app.button('Operations Centre','/operations','secondary'))
        for key,msg in [('assigned','Conversation owner updated.'),('status','Conversation status updated.'),('task','Follow-up task created.'),('email_sent','Email submitted through the connected provider.')]:
            if q.get(key):body+=app.notice(msg,'success')
        for c in convs:
            msgs=m.rows('SELECT * FROM v17_messages WHERE conversation_id=? ORDER BY occurred_at DESC LIMIT 8',(c['id'],));contact=m.one('SELECT * FROM contacts WHERE contact_id=?',(c['contact_id'],)) if c.get('contact_id') else None
            body+=f'<div class="card section"><div class="message-top"><div><h3>{app.e(c["channel"])} · {app.e((contact or {}).get("full_name") or (contact or {}).get("email") or c["contact_id"] or "Unmatched contact")}</h3><p class="helper">{app.e(c["subject"])} · Owner: {app.e(c["owner"] or "Unassigned")}</p></div>{_pill(app,"Unread "+str(c["unread_count"]) if c["unread_count"] else c["status"])}</div>'
            for x in msgs:body+=f'<p><strong>{app.e(x["direction"] or x["source_type"])}</strong> · {app.e(x["occurred_at"])}<br>{app.e(x["body"])}</p>'
            body+=f'<div class="campaign-grid"><form method="post" action="/operations/inbox/{app.e(c["id"])}/assign">'+app.field('Assign owner','<input name="owner" value="'+app.e(c['owner'])+'" placeholder="Name/team">')+'<button class="btn secondary" type="submit">Assign</button></form><form method="post" action="/operations/inbox/{app.e(c["id"])}/task">'+app.field('Follow-up task','<input name="title" value="Reply to customer">')+'<button class="btn secondary" type="submit">Create task</button></form></div>'
            if c['unread_count']:body+=f'<form method="post" action="/operations/inbox/mark-read" style="display:inline"><input type="hidden" name="conversation_id" value="{app.e(c["id"])}"><button class="btn secondary" type="submit">Mark read</button></form> '
            body+=_post_button('Close' if c['status']=='Open' else 'Reopen',f'/operations/inbox/{app.e(c["id"])}/'+('close' if c['status']=='Open' else 'reopen'),'secondary')
            if str(c.get('channel') or '').lower()=='email' and contact and contact.get('email'):
                body+=f'<details class="section"><summary><strong>Send one-to-one email</strong></summary><form method="post" action="/operations/inbox/{app.e(c["id"])}/email" data-confirm="This submits a real customer email through the connected provider. Continue?">'+app.field('Subject','<input name="subject" required>')+app.field('Message','<textarea name="message" required></textarea>')+app.field('Type SEND to confirm','<input name="confirm" required autocomplete="off">')+'<button class="btn" type="submit">Send email</button></form></details>'
            elif str(c.get('channel') or '').lower()=='whatsapp':body+='<p class="tiny muted section">WhatsApp replies are not exposed as a generic free-form send because provider 24-hour-session/template rules must be honoured. Use the connected WhatsApp tools or create a follow-up task.</p>'
            body+='</div>'
        if not convs:body+='<div class="card empty">No recorded conversations yet. Live connectors and CRM interactions will feed this view.</div>'
        self.send_html(app.layout('Unified inbox',body,'operations'))

    def operations_returns(self,q):
        import app
        status=(q.get('status') or [''])[0] if isinstance(q.get('status'),list) else (q.get('status') or '')
        where='';args=[]
        if status:where=' WHERE r.status=?';args=[status]
        rows=m.rows('SELECT r.*,coalesce(sum(ri.quantity),0) item_qty FROM v17_return_cases r LEFT JOIN v18_return_items ri ON ri.return_id=r.id'+where+' GROUP BY r.id ORDER BY requested_at DESC LIMIT 500',tuple(args))
        body=app.pagehead('Returns, exchanges & refunds','Line-item return cases with controlled state transitions and refund evidence.',app.button('Operations Centre','/operations','secondary'))
        body+='<div class="campaign-grid section">'+''.join(app.button(x or 'All','/operations/returns'+(('?status='+app.query(x)) if x else ''),'secondary') for x in ['', 'Requested','Approved','In transit','Received','Refund pending','Completed','Rejected','Cancelled'])+'</div>'
        body+='<div class="card section"><table><thead><tr><th>Order</th><th>Type</th><th>Resolution</th><th>Qty</th><th>Status</th><th>Refund</th><th></th></tr></thead><tbody>'
        for r in rows:body+=f'<tr><td>{app.e(r["order_id"])}</td><td>{app.e(r["case_type"])}</td><td>{app.e(r["requested_resolution"])}</td><td>{int(r["item_qty"] or 0)}</td><td>{_pill(app,r["status"])}</td><td>{app.e(r["currency"])} {float(r["refund_amount"] or 0):.2f}</td><td>{app.button("Open order","/operations/orders/"+r["order_id"],"secondary small")}</td></tr>'
        if not rows:body+='<tr><td colspan="7">No return/refund cases in this view.</td></tr>'
        body+='</tbody></table></div>';self.send_html(app.layout('Returns',body,'operations'))

    def operations_retention(self,q):
        import app
        rows=m.rows('SELECT * FROM v17_retention_actions ORDER BY CASE status WHEN \'Ready\' THEN 0 WHEN \'Planned\' THEN 1 ELSE 2 END,due_at LIMIT 500')
        body=app.pagehead('Post-purchase & retention','Review, complete, snooze or cancel post-purchase actions without silently sending marketing.',app.button('Operations Centre','/operations','secondary'))
        for r in rows:
            body+=f'<div class="card section"><div class="message-top"><div><strong>{app.e(r["title"])}</strong><p class="helper">Customer {app.e(r["contact_id"])} · Order {app.e(r["order_id"])} · Due {app.e(r["due_at"])} · Channel {app.e(r["channel"] or "Not selected")}</p><p>{app.e(r["reason"])}</p></div>{_pill(app,r["status"])}</div>'
            if r['status'] in {'Ready','Planned'}:
                body+=_post_button('Complete',f'/operations/retention/{app.e(r["id"])}/complete','secondary')+' '+_post_button('Cancel',f'/operations/retention/{app.e(r["id"])}/cancel','secondary')
                body+=f'<form method="post" action="/operations/retention/{app.e(r["id"])}/snooze" style="display:inline-flex;gap:8px;align-items:end"><label class="field">Snooze days<input type="number" name="days" min="1" max="90" value="7" style="width:90px"></label><button class="btn secondary" type="submit">Snooze</button></form>'
            body+='</div>'
        if not rows:body+='<div class="card empty">No retention actions yet. Paid/delivered orders create them automatically.</div>'
        self.send_html(app.layout('Retention',body,'operations'))

    def operations_social(self,q):
        import app
        rows=m.rows('SELECT * FROM v17_social_posts ORDER BY scheduled_at DESC LIMIT 300');campaigns=m.rows('SELECT id,name FROM v10_unified_campaigns ORDER BY created_at DESC LIMIT 200') if m.table_exists('v10_unified_campaigns') else [];assets=po.publishable_campaign_assets(250)
        ready=il.channel_readiness('Instagram/Facebook');connected=str(ready.get('status') or '')=='Connected'
        body=app.pagehead('Social scheduler','Plan and, when Meta is connected, publish reviewed Facebook/Instagram images with provider-confirmed states.',app.button('Operations Centre','/operations','secondary'))
        if q.get('scheduled'):
            body+=app.notice('Social post '+('scheduled for provider execution.' if connected else 'saved as a plan. It will not publish until Meta is connected and the asset is publicly reachable.'),'success' if connected else 'info')
        if not connected:
            body+=app.notice('Planning mode: Instagram/Facebook is not connected. Saving a post records the plan as Needs setup; it does not publish anything.','warn')
        asset_select='<select name="asset_ref"><option value="">Use URL below</option>'+''.join(f'<option value="{app.e(x["id"])}">{app.e(x["label"])} · {app.e(x["product_id"])}</option>' for x in assets)+'</select>'
        schedule_label='Scheduled time' if connected else 'Planned time'
        button_label='Schedule post' if connected else 'Save planned post'
        body+='<div class="card section"><form method="post" action="/operations/social/schedule"><div class="formgrid">'+app.field('Campaign','<select name="campaign_id"><option value="">None</option>'+''.join(f'<option value="{app.e(x["id"])}">{app.e(x["name"])}</option>' for x in campaigns)+'</select>')+app.field('Channel','<select name="channel">'+app.options(['Instagram','Facebook'])+'</select>')+app.field(schedule_label,'<input type="datetime-local" name="scheduled_at" required>')+app.field('CRM creative asset',asset_select,'Only approved assets with a public HTTPS URL are selectable for provider publishing.')+'</div>'+app.field('Or public HTTPS image URL','<input name="asset_url" type="url" placeholder="https://...">','Use this when the asset is hosted outside the CRM.')+app.field('Caption','<textarea name="caption"></textarea>')+'<div class="form-foot"><button class="btn" type="submit">'+button_label+'</button>'+(' '+app.button('Connect Meta','/integrations','secondary') if not connected else '')+'</div></form></div>'
        if not assets:body+=app.notice('No CRM creative asset currently resolves to a public HTTPS URL. Local files stay private; configure public media storage or use an external HTTPS image URL before live publishing.','warn')
        for r in rows:
            err_html=('<p class="note warn">'+app.e(r['last_error'])+'</p>') if r['last_error'] else ''
            body+=f'<div class="card section"><div class="message-top"><div><strong>{app.e(r["channel"])}</strong><p class="helper">{app.e(r["scheduled_at"])} · attempts {int(r["attempts"] or 0)} · {app.e(r["caption"][:160])}</p></div>{_pill(app,r["status"])}</div>{err_html}'
            if r['status'] not in {'Published','Cancelled'}:
                if not connected and r['status']=='Needs setup':body+=app.button('Connect Meta','/integrations','secondary small')+' '+_post_button('Cancel',f'/operations/social/{app.e(r["id"])}/cancel','secondary')
                else:body+=_post_button('Publish/retry now',f'/operations/social/{app.e(r["id"])}/publish-now','secondary','This may submit a real social post to the connected account. Continue?')+' '+_post_button('Cancel',f'/operations/social/{app.e(r["id"])}/cancel','secondary')
            if r['provider_post_id']:body+=f'<p class="tiny muted">Provider post ID: {app.e(r["provider_post_id"])}</p>'
            body+='</div>'
        self.send_html(app.layout('Social scheduler',body,'operations'))

    def operations_accounting(self,q):
        import app
        rows=po.accounting_export_rows();body=app.pagehead('Accounting handoff','Auditable sale/refund entries. Export now; mark status when your finance system accepts them.',app.button('Download CSV','/operations/accounting.csv','secondary')+app.button('Operations Centre','/operations','secondary'))
        if q.get('updated'):body+=app.notice('Accounting handoff updated.','success')
        for r in rows:
            body+=f'<div class="card section"><div class="message-top"><div><strong>{app.e(r["order_id"])} · {app.e(r["entry_type"])}</strong><p class="helper">{app.e(r["currency"])} {float(r["amount"] or 0):.2f} · source {app.e(r["source_type"])} {app.e(r["source_id"])}</p></div>{_pill(app,r["status"])}</div><form method="post" action="/operations/accounting/{app.e(r["id"])}/status"><div class="formgrid">'+app.field('Status','<select name="status">'+app.options(['Prepared','Exported','Posted','Rejected'],r['status'])+'</select>')+app.field('External/accounting ID','<input name="external_id" value="'+app.e(r['external_id'])+'">')+app.field('Note','<input name="note" placeholder="Export batch / posting note">')+'</div><button class="btn secondary" type="submit">Update handoff</button></form></div>'
        if not rows:body+='<div class="card empty">No accounting entries yet.</div>'
        self.send_html(app.layout('Accounting handoff',body,'operations'))

    def operations_e2e(self,q):
        import app
        import handover_core as hc
        report=hc.journey_audit();procs=po.processes(500);counts={}
        for p in procs:counts[p['status']]=counts.get(p['status'],0)+1
        body=app.pagehead('End-to-end process test','Owner journey plus the current operational handoff engine. Status is based on evidence, not page presence.',app.button('Operations Centre','/operations','secondary'))
        body+='<div class="stats-grid">'+''.join(f'<div class="card stat-card"><span class="stat-label">{n}</span><strong>{app.e(k)}</strong><span class="helper">Tracked processes</span></div>' for k,n in sorted(counts.items()))+'</div>'
        body+='<div class="card section"><table><thead><tr><th>#</th><th>Business stage</th><th>Status</th><th>What this means</th><th></th></tr></thead><tbody>'
        for x in report['steps']:body+=f'<tr><td>{x["no"]}</td><td><strong>{app.e(x["label"])}</strong></td><td>{_pill(app,x["status"])}</td><td>{app.e(x["detail"])}</td><td>{app.button("Open",x["action_url"],"secondary small") if x.get("action_url") else ""}</td></tr>'
        body+='</tbody></table></div>';self.send_html(app.layout('End-to-end process test',body,'e2e'))

    def operations_accounting_csv(self):
        rows=po.accounting_export_rows(20000);buf=io.StringIO();w=csv.writer(buf);w.writerow(['Order ID','Source Type','Source ID','Entry Type','Amount','Currency','Tax Amount','Status','External ID','Created At'])
        for r in rows:w.writerow([r['order_id'],r['source_type'],r['source_id'],r['entry_type'],r['amount'],r['currency'],r['tax_amount'],r['status'],r['external_id'],r['created_at']])
        return self.send_file(buf.getvalue().encode('utf-8-sig'),'accounting_handoff_v18_3.csv','text/csv; charset=utf-8')
