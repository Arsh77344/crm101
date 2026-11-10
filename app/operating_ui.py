from __future__ import annotations
import json,re
import marketing as m
import operating_core as oc
import db_layer
import v35_truth as truth
import v50_reliability as v50

class OperatingPages:
    def v13_get(self,path,q):
        if path in {'/','/control-centre','/operating-centre'}:self.control_centre(q)
        elif path=='/capability-audit':self.capability_audit(q)
        elif path=='/quality-centre':self.quality_centre(q)
        elif path=='/ai-governance':self.ai_governance(q)
        elif path=='/consent-centre':self.consent_centre(q)
        elif path=='/event-stream':self.event_stream(q)
        elif path=='/product-workspace':self.product_selector(q)
        elif re.fullmatch(r'/product-workspace/[^/]+',path):self.product_workspace(path.split('/')[2],q)
        elif path=='/v13-e2e':self.v13_e2e(q)
        else:return False
        return True

    def v13_post(self,path,f):
        v=lambda k,d='':f.get(k,[d])[0]
        if re.fullmatch(r'/product-workspace/[^/]+/run',path):
            pid=path.split('/')[2];channels=f.get('channels',[]) or [x.strip() for x in oc.setting('v13_default_channels').split(',') if x.strip()]
            rid=oc.launch_product_pipeline(pid,channels,int(v('automation_level') or oc.setting('v13_default_automation_level','2')))
            return self.redirect('/product-workspace/'+pid+'?run='+rid)
        if path=='/operating-settings/save':
            oc.save_settings({'automation_level':v('automation_level'),'default_channels':v('default_channels'),'default_market':v('default_market'),'default_language':v('default_language'),'auto_product_qc':v('auto_product_qc','0'),'auto_local_assets':v('auto_local_assets','0'),'auto_creative_plan':v('auto_creative_plan','0'),'auto_paid_ai':v('auto_paid_ai','0'),'require_low_confidence_approval':v('require_low_confidence_approval','0')})
            return self.redirect('/control-centre?saved=1')
        if path=='/quality-centre/scan':
            pid=v('product_id');oc.assess_source_images(pid);oc.assess_product_copy(pid);oc.assess_commercial_readiness(pid);return self.redirect('/quality-centre?product_id='+pid+'&qc=1')
        if path=='/ai-governance/budget':
            oc.save_ai_budget(v('scope'),int(v('max_calls') or 0),float(v('max_cost') or 0),int(v('warn_percent') or 80));return self.redirect('/ai-governance?saved=1')
        if path=='/consent-centre/record':
            oc.record_consent(v('contact_id'),v('channel'),v('state'),v('source'),v('evidence'),v('jurisdiction'),(getattr(self,'current_user',{}) or {}).get('display_name','Owner'))
            return self.redirect('/consent-centre?contact_id='+v('contact_id')+'&saved=1')
        if re.fullmatch(r'/incidents/[^/]+/resolve',path):
            oc.resolve_incident(path.split('/')[2]);return self.redirect('/control-centre?resolved=1')
        if path=='/event-stream/process':
            out=oc.process_pending_events(100);oc.scan_inventory_events();return self.redirect('/event-stream?processed='+str(out['processed'])+'&failed='+str(out['failed']))
        if path=='/event-stream/rule':
            oc.save_rule({'name':v('name'),'trigger_event':v('trigger_event'),'condition_json':v('condition_json','{}'),'action_type':v('action_type'),'delay_seconds':v('delay_seconds','0'),'measurement_key':v('measurement_key'),'automation_level':v('automation_level','2'),'enabled':'1'})
            return self.redirect('/event-stream?saved=1')
        if path=='/v13-e2e/run':return self.redirect('/v13-e2e?run=1')
        return False

    def control_centre(self,q):
        import app
        oc.initialise();snapshot=oc.readiness_snapshot()
        try:
            import business_os as bos
            bos.generate_recommendations()
        except Exception as exc:
            from operational_guard import record_side_effect_failure
            record_side_effect_failure('control_centre','Owner recommendations could not refresh',exc,recovery='Open System health, resolve the underlying data or automation error, then refresh the business overview.',severity='Error')
        today_orders=(m.one("SELECT count(*) n FROM orders WHERE date(coalesce(ordered_at,''))=date('now')") or {'n':0})
        fin=v50.financial_summary(__import__('datetime').date.today().isoformat(),__import__('datetime').date.today().isoformat())
        revenue_rows=[{'currency':r['currency'],'revenue':r['net_revenue']} for r in fin['currency_breakdown']]
        revenue_text=' / '.join(f"{r['currency']} {float(r['revenue'] or 0):.2f}" for r in revenue_rows) or 'No revenue yet'
        leads=(m.one("SELECT count(*) n FROM contacts WHERE coalesce(lifecycle_stage,'') IN ('New','Contacted','Engaged','Qualified')") or {'n':0})['n'] if 'lifecycle_stage' in {r['name'] for r in m.rows('PRAGMA table_info(contacts)')} else (m.one('SELECT count(*) n FROM contacts') or {'n':0})['n']
        buckets={str(r.get('contact_type') or 'Unknown'):int(r.get('n') or 0) for r in m.rows("SELECT coalesce(nullif(contact_type,''),'Unknown') contact_type,count(*) n FROM contacts GROUP BY coalesce(nullif(contact_type,''),'Unknown')")}
        bucket_text=f"{buckets.get('B2B',0)} B2B / {buckets.get('B2C',0)} B2C / {buckets.get('Both',0)} Both / {buckets.get('Unknown',0)} Unknown"
        due=(m.one("SELECT count(*) n FROM m4_tasks WHERE status='Open' AND date(due_date)<=date('now')") or {'n':0})['n']
        approvals=(m.one("SELECT count(*) n FROM v11_approvals WHERE status='Pending'") or {'n':0})['n'] if m.table_exists('v11_approvals') else 0
        processing=(m.one("SELECT count(*) n FROM v12_worker_jobs WHERE status IN ('Queued','Retry','Running')") or {'n':0})['n'] if m.table_exists('v12_worker_jobs') else 0
        open_inc=m.rows("SELECT * FROM v13_incidents WHERE status='Open' ORDER BY CASE severity WHEN 'Critical' THEN 0 WHEN 'Error' THEN 1 WHEN 'Warning' THEN 2 ELSE 3 END,created_at DESC LIMIT 8")
        recs=m.rows("SELECT * FROM v9_recommendations WHERE status='Open' ORDER BY CASE priority WHEN 'High' THEN 0 WHEN 'Medium' THEN 1 ELSE 2 END,created_at DESC LIMIT 8") if m.table_exists('v9_recommendations') else []
        body=app.pagehead('Business overview','See what is ready, what needs you, and what the system is doing.',app.button('Upload products','/product-engine','')+app.button('Product workflow','/product-workspace','secondary'))
        if q.get('saved'):body+=app.notice('Operating defaults saved.','success')
        body+=f'''<div class="stats-grid"><div class="card stat-card"><span class="stat-label">{int(today_orders['n'] or 0)}</span><strong>Orders today</strong><span class="helper">Recorded transactions</span></div><div class="card stat-card"><span class="stat-label">{app.e(revenue_text)}</span><strong>Revenue today</strong><span class="helper">Currencies remain separate; no FX conversion</span></div><div class="card stat-card"><span class="stat-label">{int(leads or 0)}</span><strong>CRM records / leads</strong><span class="helper">{app.e(bucket_text)}</span></div><div class="card stat-card"><span class="stat-label">{int(due or 0)}</span><strong>Tasks due</strong><span class="helper">Human attention</span></div></div>'''
        body+='<div class="three section">'
        body+=f'''<div class="card"><div class="eyebrow">What needs attention?</div><h2>{len(open_inc)+int(approvals)} exception(s)</h2><p class="helper">{len(open_inc)} production/automation incident(s) · {int(approvals)} pending approval(s).</p>{app.button('Open approvals','/approvals','secondary')} {app.button('System health','/system-health','secondary')}</div>'''
        body+=f'''<div class="card"><div class="eyebrow">What is automation doing?</div><h2>{int(processing)} job(s) active</h2><p class="helper">Durable jobs can continue independently of the page you are viewing.</p>{app.button('Event stream','/event-stream','secondary')} {app.button('Background jobs','/scheduler','secondary')}</div>'''
        import handover_core as hc
        strict=hc.strict_capability_matrix();ready=sum(1 for x in strict if x['status']=='Fully Working');partial=sum(1 for x in strict if x['status']=='Partially Working');missing=sum(1 for x in strict if x['status'] in {'Configuration Required','Not Implemented','Broken'})
        body+=f'''<div class="card"><div class="eyebrow">Can the business run end-to-end?</div><h2>{ready} capability areas ready</h2><p class="helper">{partial} partial · {missing} require setup/implementation.</p>{app.button('Capability truth audit','/capability-audit','secondary')} {app.button('Run beginner end-to-end journey','/v17-e2e','secondary')}</div>'''
        body+='</div>'
        body+='<div class="two section"><div><div class="section-head"><h2>Exceptions</h2><span class="tiny muted">Only items that need human intervention</span></div>'
        if not open_inc:body+='<div class="card empty">No open operating incidents.</div>'
        for x in open_inc:
            body+=f'''<div class="card section"><span class="pill {'warn' if x['severity'] in ('Error','Critical') else 'purple'}">{app.e(x['severity'])}</span><h3>{app.e(x['title'])}</h3><p class="helper">{app.e(x['detail'])}</p><p class="tiny muted">Recovery: {app.e(x['recovery'])}</p><form method="post" action="/incidents/{app.e(x['id'])}/resolve"><button class="btn secondary small">Mark resolved</button></form></div>'''
        body+='</div><div><div class="section-head"><h2>What should I do next?</h2><span class="tiny muted">Prioritised actions</span></div>'
        if not recs:body+='<div class="card empty">No open recommendations. Upload a product or refresh the Action Centre.</div>'
        for r in recs:
            body+=f'''<div class="card section"><span class="pill {'warn' if r['priority']=='High' else 'purple'}">{app.e(r['priority'])}</span><h3>{app.e(r['title'])}</h3><p class="helper">{app.e(r['reason'])}</p>{app.button('Open',r['action_url'] or '/','secondary small') if r.get('action_url') else ''}</div>'''
        body+='</div></div>'
        body+=f'''<div class="card section"><div class="eyebrow">Automation policy</div><h2>How much should the system do automatically?</h2><form method="post" action="/operating-settings/save"><div class="formgrid">{app.field('Default automation level','<select name="automation_level">'+app.options([('1','Assist Me — recommend and draft'),('2','Work With Me — prepare and ask before important actions'),('3','Automate Routine Work — routine workflows run automatically'),('4','Advanced Automation — execute approved rules within limits')],oc.setting('v13_default_automation_level','2'))+'</select>')}{app.field('Default launch channels','<input name="default_channels" value="'+app.e(oc.setting('v13_default_channels'))+'">','Comma-separated business channels.')}{app.field('Default target market','<input name="default_market" value="'+app.e(oc.setting('v13_default_market','United Kingdom'))+'">')}{app.field('Default language','<input name="default_language" value="'+app.e(oc.setting('v13_default_language','English'))+'">')}<label class="checkline"><input type="checkbox" name="auto_product_qc" value="1" {'checked' if oc.setting('v13_auto_product_qc','1')=='1' else ''}>Run product QC automatically</label><label class="checkline"><input type="checkbox" name="auto_local_assets" value="1" {'checked' if oc.setting('v13_auto_local_assets','1')=='1' else ''}>Prepare safe local ecommerce assets automatically</label><label class="checkline"><input type="checkbox" name="auto_creative_plan" value="1" {'checked' if oc.setting('v13_auto_creative_plan','1')=='1' else ''}>Prepare cross-channel creative campaign automatically</label><label class="checkline"><input type="checkbox" name="auto_paid_ai" value="1" {'checked' if oc.setting('v13_auto_paid_ai','0')=='1' else ''}>Allow paid AI generation within budgets and approval policy</label><label class="checkline"><input type="checkbox" name="require_low_confidence_approval" value="1" {'checked' if oc.setting('v13_require_low_confidence_approval','1')=='1' else ''}>Require approval when confidence is low</label></div><div class="form-foot"><button class="btn">Save operating policy</button></div></form></div>'''
        self.send_html(app.layout('Business overview',body,'action'))

    def product_selector(self,q):
        import app
        products=m.rows('''SELECT p.*,(SELECT relative_path FROM product_images i WHERE i.product_id=p.product_id ORDER BY is_primary DESC LIMIT 1) img FROM products p WHERE coalesce(p.status,'Draft')<>'Archived' ORDER BY created_at DESC LIMIT 500''')
        archived=int((m.one("SELECT count(*) n FROM products WHERE status='Archived'") or {'n':0})['n'] or 0)
        actions=(app.button('Add product','/products/new','')+app.button('Upload raw images','/product-engine','secondary')+
                 app.button('Manage catalogue','/products','secondary')+app.button(f'Archived ({archived})','/products?view=archived','secondary'))
        body=app.pagehead('Prepare products','Choose a product and take it from raw images to launch-ready assets.',actions)
        body+=app.notice('Use Archive to take a product out of active business workflows without destroying order, campaign or asset history.','info')
        body+='<div class="campaign-grid section">'
        for p in products:
            last=oc.latest_pipeline(p['product_id']);status=last['status'] if last else 'Not prepared'
            img='/'+app.e(p['img']) if p.get('img') else ''
            pid=app.e(p['product_id'])
            body+=f'''<div class="card campaign-tile">{('<a href="/product-workspace/'+pid+'"><img src="'+img+'" alt="" style="width:100%;max-height:220px;object-fit:cover;border-radius:12px"></a>') if img else ''}<h3><a class="contact-name" href="/product-workspace/{pid}">{app.e(p.get('public_product_name') or p.get('internal_sku') or p['product_id'])}</a></h3><span class="pill {'good' if status=='Prepared' else 'warn'}">{app.e(status)}</span><p class="helper">{app.e(p.get('internal_sku') or '')} · {app.e(p.get('status') or 'Draft')}</p><div class="toolbar section">{app.button('Open workflow','/product-workspace/'+p['product_id'],'secondary small')}{app.button('Edit product','/products/'+p['product_id'],'secondary small')}<form method="post" action="/products/{pid}/archive" data-confirm="Archive this product from active use? Historical records will be preserved."><button class="btn secondary small">Archive</button></form></div></div>'''
        if not products:body+='<div class="card empty">No active products yet. Use <strong>Add product</strong> for manual entry or <strong>Upload raw images</strong> for AI-assisted intake.</div>'
        body+='</div>'
        self.send_html(app.layout('Prepare products',body,'product_engine'))

    def product_workspace(self,pid,q):
        import app
        p=m.one('SELECT * FROM products WHERE product_id=?',(pid,))
        if not p:raise ValueError('Product not found.')
        imgs=m.rows('SELECT * FROM product_images WHERE product_id=? ORDER BY is_primary DESC,image_role',(pid,));last=oc.latest_pipeline(pid);qs=oc.quality_summary(pid)
        lifecycle=f'<form method="post" action="/products/{app.e(pid)}/archive" data-confirm="Archive this product from active use? Historical records will be preserved."><button class="btn secondary">Archive</button></form>'
        actions=app.button('Add product','/products/new','')+app.button('Product catalogue','/products','secondary')+app.button('Back to workflow','/product-workspace','secondary')+lifecycle
        body=app.pagehead(p.get('public_product_name') or p.get('internal_sku') or 'Product workflow','One task-oriented workspace from raw product to launch preparation.',actions)
        if q.get('run'):body+=app.notice('The product launch-preparation workflow ran. Resolve only the steps that still need attention.','success')
        if q.get('qc'):body+=app.notice('Product quality checks refreshed.','success')
        body+='<div class="two section"><div class="card"><div class="eyebrow">Source product</div><h2>'+app.e(p.get('internal_sku') or '')+'</h2><p>'+app.e(p.get('description') or 'Draft product description')+'</p><div class="toolbar">'
        for im in imgs[:6]:body+=f'<img src="/{app.e(im["relative_path"])}" alt="{app.e(im.get("image_role") or "product")}" style="width:92px;height:110px;object-fit:cover;border-radius:10px">'
        body+='</div><div class="section"><strong>Retail:</strong> '+app.e(p.get('retail_price') or 'Not set')+' '+app.e(p.get('currency') or '')+' · <strong>Available stock:</strong> '+app.e(truth.product_available(pid))+'</div></div>'
        body+=f'''<div class="card"><div class="eyebrow">Quality gate</div><h2>{qs['score']:.0f}/100 · {app.e(qs['confidence'])} confidence</h2><p class="helper">Source images, product truth and later AI fidelity checks are treated as separate evidence. Low confidence blocks zero-touch use.</p><form method="post" action="/quality-centre/scan"><input type="hidden" name="product_id" value="{app.e(pid)}"><button class="btn secondary">Refresh product QC</button></form><div class="section">{app.button('Open Quality Centre','/quality-centre','secondary')}</div></div></div>'''
        channels=['Website','Instagram','Facebook','Meta Ads','Google Ads','Email','WhatsApp']
        body+='<div class="card section"><div class="eyebrow">Prepare this product</div><h2>Choose where you want to sell or market it</h2><form method="post" action="/product-workspace/'+app.e(pid)+'/run"><div class="checkgrid">'
        selected=set(x.strip() for x in oc.setting('v13_default_channels').split(','))
        for ch in channels:
            checked=' checked' if ch in selected else ''
            body+=f'<label class="check"><input type="checkbox" name="channels" value="{app.e(ch)}"{checked}><span class="row-main"><strong>{app.e(ch)}</strong><small>AI/automation adapts formats and readiness to this destination.</small></span></label>'
        body+='</div>'+app.field('Automation level','<select name="automation_level">'+app.options([('1','1 — Recommend'),('2','2 — Prepare'),('3','3 — Automate routine tasks'),('4','4 — Highly automated within rules')],oc.setting('v13_default_automation_level','2'))+'</select>')+'<div class="form-foot"><button class="btn">Prepare complete product launch</button></div></form></div>'
        if last:
            workflow_kind='good' if last['status']=='Prepared' else 'warn'
            body+=f'<div class="section-head"><h2>Latest launch workflow</h2><span class="pill {workflow_kind}">{app.e(last["status"])}</span></div><div class="card"><table><thead><tr><th>#</th><th>Stage</th><th>Status</th><th>What happened</th><th></th></tr></thead><tbody>'
            for s in last['steps']:
                step_kind='good' if s['status'] in ('Completed','Ready','Prepared','Pass') else 'warn'
                body+=f'<tr><td>{s["step_no"]}</td><td><strong>{app.e(s["label"])}</strong></td><td><span class="pill {step_kind}">{app.e(s["status"])}</span></td><td>{app.e(s.get("detail") or "")}</td><td>{app.button("Open",s["action_url"],"secondary small") if s.get("action_url") else ""}</td></tr>'
            body+='</tbody></table></div>'
        self.send_html(app.layout('Product operating workflow',body,'product_engine'))

    def quality_centre(self,q):
        import app
        view=(q.get('view') or ['current'])[0]
        if view not in {'current','history'}:view='current'
        all_rows=m.rows('''SELECT q.*,p.public_product_name,p.internal_sku FROM v13_quality_checks q LEFT JOIN products p ON p.product_id=q.entity_id
                       WHERE q.entity_type='product' ORDER BY q.created_at DESC,q.id DESC LIMIT 1000''')
        latest=[];seen=set()
        for r in all_rows:
            key=(r.get('entity_id'),r.get('check_type'))
            if key in seen:continue
            seen.add(key);latest.append(r)
        rows=(all_rows[:250] if view=='history' else latest)
        products=m.rows("SELECT product_id,coalesce(public_product_name,internal_sku,product_id) label FROM products WHERE coalesce(status,'Draft')<>'Archived' ORDER BY label")
        chosen=(q.get('product_id') or [''])[0]
        current_counts={'Pass':0,'Review recommended':0,'Approval required':0}
        for r in latest:current_counts[r.get('status')]=current_counts.get(r.get('status'),0)+1
        actions=app.button('Current results','/quality-centre?view=current','' if view=='current' else 'secondary')+app.button('Full history','/quality-centre?view=history','' if view=='history' else 'secondary')
        body=app.pagehead('Product quality & review','Current results show only the latest result for each product check. Full history keeps every QC run for auditability.',actions)
        if q.get('qc'):body+=app.notice('Local QC refreshed for the selected product. Previous checks remain in Full history.','success')
        body+=f'''<div class="stats-grid qc-summary"><div class="card stat-card"><span class="stat-label">{current_counts.get('Approval required',0)}</span><strong>Approval required</strong><span class="helper">Low-confidence or sale-blocking checks</span></div><div class="card stat-card"><span class="stat-label">{current_counts.get('Review recommended',0)}</span><strong>Review recommended</strong><span class="helper">Medium-confidence checks</span></div><div class="card stat-card"><span class="stat-label">{current_counts.get('Pass',0)}</span><strong>Passed</strong><span class="helper">Latest high-confidence checks</span></div></div>'''
        body+='<div class="card section"><form method="post" action="/quality-centre/scan" class="actions qc-run">'+app.field('Product','<select name="product_id" required>'+app.options([(p['product_id'],p['label']) for p in products],chosen,'Choose product')+'</select>')+'<button class="btn">Run local QC</button></form><p class="helper">A local QC run refreshes source-image quality, product-truth checks and commercial readiness together. It does not publish or change product facts.</p></div>'
        body+='<div class="card section"><div class="section-head"><div><h2>'+('Latest checks' if view=='current' else 'QC history')+'</h2><span class="tiny muted">'+('One current result per product/check.' if view=='current' else 'Newest 250 historical checks. Nothing is deleted.')+'</span></div></div><div class="table-wrap"><table class="qc-table"><thead><tr><th>Product</th><th>Check</th><th>Score</th><th>Confidence</th><th>Status</th><th>Issues</th><th>When</th></tr></thead><tbody>'
        for r in rows:
            try:issues=json.loads(r.get('issues_json') or '[]')
            except Exception:issues=[]
            issue_text='; '.join(issues[:3]) or 'No issues recorded.'
            check_label={'source_images':'Source images','product_truth':'Product facts & copy','commercial_readiness':'Commercial readiness'}.get(r.get('check_type'),str(r.get('check_type') or '').replace('_',' ').title())
            body+=f'<tr><td><a href="/product-workspace/{app.e(r["entity_id"])}">{app.e(r.get("public_product_name") or r.get("internal_sku") or r["entity_id"])}</a></td><td>{app.e(check_label)}</td><td>{float(r.get("score") or 0):.0f}</td><td><span class="pill {'good' if r['confidence']=='High' else 'warn'}">{app.e(r["confidence"])}</span></td><td>{app.e(r["status"])}</td><td class="qc-issues">{app.e(issue_text)}</td><td class="qc-when">{app.e(r["created_at"])}</td></tr>'
        if not rows:body+='<tr><td colspan="7" class="empty">Run local QC for a product to create its first quality snapshot.</td></tr>'
        body+='</tbody></table></div></div>'
        self.send_html(app.layout('Product quality & review',body,'quality'))

    def capability_audit(self,q):
        import app
        import handover_core as hc
        rows=hc.strict_capability_matrix();order={'Fully Working':0,'Partially Working':1,'Configuration Required':2,'UI Only':3,'Mock / Placeholder':4,'Not Implemented':5,'Broken':6};rows=sorted(rows,key=lambda x:(order.get(x['status'],9),x['label']))
        body=app.pagehead('Capability truth audit','Every area is labelled by what the backend can actually do — not by whether a menu item exists.','')
        body+=app.notice('The CRM does not count a page, table, token or button as proof. External capabilities remain Configuration Required or Partially Working until the relevant evidence exists.','info')
        body+='<div class="card section"><table><thead><tr><th>Capability</th><th>Reality</th><th>Evidence / remaining boundary</th><th></th></tr></thead><tbody>'
        for r in rows:
            cls='good' if r['status']=='Fully Working' else 'warn' if r['status'] in {'Partially Working','Configuration Required','Broken'} else ''
            body+=f'<tr><td><strong>{app.e(r["label"])}</strong></td><td><span class="pill {cls}">{app.e(r["status"])}</span></td><td>{app.e(r["detail"])}</td><td>{app.button("Open",r["action_url"],"secondary small") if r.get("action_url") else ""}</td></tr>'
        body+='</tbody></table></div>'
        self.send_html(app.layout('Capability audit',body,'readiness'))

    def ai_governance(self,q):
        import app
        budgets=oc.ai_budget_status();usage=m.rows('SELECT * FROM v13_ai_usage ORDER BY created_at DESC LIMIT 100')
        body=app.pagehead('AI settings & limits','Control AI usage, cost limits and when approval is required.','')
        if q.get('saved'):body+=app.notice('AI budget/usage limit saved.','success')
        body+='<div class="four section">'
        for b in budgets:
            body+=f'<div class="card"><div class="eyebrow">{app.e(b["scope"])}</div><h2>{b["calls"]} / {b["max_calls"] or "∞"} attempts</h2><p class="helper">{b.get("completed",0)} completed · {b.get("failed",0)} failed. Estimated cost recorded: ${b["cost"]:.2f} / {("$%.2f"%b["max_estimated_cost"]) if b["max_estimated_cost"] else "no cost ceiling"}</p><span class="pill {'warn' if b['blocked'] or b['percent']>=b['warn_percent'] else 'good'}">{b["percent"]:.0f}%</span></div>'
        body+='</div><div class="card section"><h2>Set limits</h2><form method="post" action="/ai-governance/budget" class="formgrid">'+app.field('Scope','<select name="scope">'+app.options([('daily','All AI / daily'),('monthly','All AI / monthly'),('daily_image','AI image / daily'),('daily_video','AI video / daily')],'daily')+'</select>')+app.field('Maximum attempts','<input type="number" min="0" name="max_calls" value="50">','Successful and failed provider attempts both count, preventing repeated failures from running without a limit.')+app.field('Optional estimated-cost ceiling (USD)','<input type="number" min="0" step="0.01" name="max_cost" value="0">','0 means no monetary ceiling; attempt limits still apply.')+app.field('Warn at %','<input type="number" min="0" max="100" name="warn_percent" value="80">')+'<div><button class="btn">Save limit</button></div></form></div>'
        body+='<div class="card section"><h2>Recent AI usage ledger</h2><table><thead><tr><th>When</th><th>Task</th><th>Provider/model</th><th>Object</th><th>Status</th><th>Units</th><th>Est. cost</th></tr></thead><tbody>'
        for u in usage:body+=f'<tr><td>{app.e(u["created_at"])}</td><td>{app.e(u["task_key"])}</td><td>{app.e(u["provider"])}<br><span class="tiny muted">{app.e(u.get("model") or "")}</span></td><td>{app.e((u.get("object_type") or "")+" "+(u.get("object_id") or ""))}</td><td>{app.e(u["status"])}</td><td>{int(u.get("input_units") or 0)} in · {int(u.get("output_units") or 0)} out · {int(u.get("image_count") or 0)} img · {float(u.get("video_seconds") or 0):.0f}s</td><td>${float(u.get("estimated_cost") or 0):.4f}</td></tr>'
        if not usage:body+='<tr><td colspan="7" class="empty">Governed AI calls are recorded here. Existing historical calls remain in their older module logs.</td></tr>'
        body+='</tbody></table></div>'
        self.send_html(app.layout('AI settings & limits',body,'models'))

    def consent_centre(self,q):
        import app
        cid=q.get('contact_id',[''])[0];contacts=m.rows('SELECT contact_id,coalesce(full_name,username,email,phone_number,contact_id) label FROM contacts ORDER BY label COLLATE NOCASE LIMIT 1000')
        hist=oc.consent_history(cid) if cid else []
        perms=m.rows('SELECT * FROM marketing_permissions WHERE contact_id=? ORDER BY channel',(cid,)) if cid else []
        body=app.pagehead('Consent & communication preferences','One append-only history for why a customer can or cannot be contacted. Automation uses the effective permission, not assumptions from public data.','')
        if q.get('saved'):body+=app.notice('Consent/permission event recorded and effective CRM permission updated.','success')
        body+='<div class="card"><form method="get" action="/consent-centre" class="actions">'+app.field('Customer','<select name="contact_id" required>'+app.options([(c['contact_id'],c['label']) for c in contacts],cid,'Choose customer')+'</select>')+'<button class="btn secondary">View</button></form></div>'
        if cid:
            body+='<div class="two section"><div class="card"><h2>Record permission event</h2><form method="post" action="/consent-centre/record" class="formgrid"><input type="hidden" name="contact_id" value="'+app.e(cid)+'">'+app.field('Channel','<select name="channel">'+app.options(['Email','WhatsApp','SMS','Phone','Other'],'Email')+'</select>')+app.field('State','<select name="state">'+app.options(['Unknown','Allowed','OptedIn','OptedOut','Suppressed','DoNotContact'],'Unknown')+'</select>')+app.field('Source / basis','<input name="source" placeholder="Signup form, customer request, contract...">')+app.field('Jurisdiction','<input name="jurisdiction" placeholder="UK / India / other">')+app.field('Evidence','<textarea name="evidence" rows="3" placeholder="Reference or evidence of the change"></textarea>')+'<div><button class="btn">Record event</button></div></form></div><div class="card"><h2>Effective permissions</h2>'
            for p in perms:body+=f'<div class="readiness-row"><span class="pill {'good' if p["status"] in ("Allowed","OptedIn") else 'warn'}">{app.e(p["status"])}</span><div class="row-main"><strong>{app.e(p["channel"])}</strong><small>{app.e(p.get("lawful_basis_or_reason") or "No basis recorded")}</small></div></div>'
            if not perms:body+='<div class="empty">No explicit channel permissions recorded.</div>'
            body+='</div></div><div class="card section"><h2>Permission history</h2><table><thead><tr><th>When</th><th>Channel</th><th>State</th><th>Source</th><th>Evidence</th><th>Jurisdiction</th></tr></thead><tbody>'
            for r in hist:body+=f'<tr><td>{app.e(r["occurred_at"])}</td><td>{app.e(r["channel"])}</td><td>{app.e(r["state"])}</td><td>{app.e(r.get("source") or "")}</td><td>{app.e(r.get("evidence") or "")}</td><td>{app.e(r.get("jurisdiction") or "")}</td></tr>'
            if not hist:body+='<tr><td colspan="6" class="empty">No consent-history events have been recorded yet. Existing effective permissions remain unchanged until a new event is recorded.</td></tr>'
            body+='</tbody></table></div>'
        self.send_html(app.layout('Consent Centre',body,'privacy'))

    def event_stream(self,q):
        import app
        events=m.rows('SELECT * FROM v13_events ORDER BY occurred_at DESC LIMIT 150');rules=m.rows('SELECT * FROM v13_automation_rules ORDER BY trigger_event,name')
        body=app.pagehead('Automations','See and manage the rules and background actions that keep routine work moving.','<form method="post" action="/event-stream/process"><button class="btn secondary">Process pending events</button></form>')
        if q.get('processed'):body+=app.notice(f"Processed {app.e(q['processed'][0])} rule action(s); {app.e(q.get('failed',['0'])[0])} failed.",'success')
        if q.get('saved'):body+=app.notice('Automation rule saved. Conditions are evaluated safely and unsupported keys fail closed.','success')
        body+='<div class="card section"><div class="eyebrow">Business rule builder</div><h2>Add an event rule</h2><p class="helper">Use business events rather than technical cron jobs. Conditions are optional JSON; unknown condition keys never trigger work.</p><form method="post" action="/event-stream/rule" class="formgrid">'+app.field('Rule name','<input name="name" required placeholder="Inbound WhatsApp → follow-up">')+app.field('Trigger event','<select name="trigger_event">'+app.options(['PRODUCT_CREATED','ORDER_PLACED','INVENTORY_LOW','MESSAGE_RECEIVED','QUALITY_REVIEW_REQUIRED'],'MESSAGE_RECEIVED')+'</select>')+app.field('Action','<select name="action_type">'+app.options([('RUN_PRODUCT_PIPELINE','Prepare product launch'),('POST_PURCHASE_RECOMMENDATION','Prepare retention action'),('OWNER_RECOMMENDATION','Create owner recommendation'),('CREATE_TASK','Create follow-up task'),('CREATE_APPROVAL','Request approval')],'CREATE_TASK')+'</select>')+app.field('Automation level','<select name="automation_level">'+app.options([('1','1 — Recommend'),('2','2 — Prepare'),('3','3 — Routine automation'),('4','4 — Highly automated')],'2')+'</select>')+app.field('Delay seconds','<input type="number" min="0" max="2592000" name="delay_seconds" value="0">','Use 0 for immediate; delayed rules use the durable queue.')+app.field('Measurement key','<input name="measurement_key" placeholder="reply_received / order_created">','Optional outcome label for later reporting.')+app.field('Optional conditions','<textarea name="condition_json" rows="3">{}</textarea>','Supported: entity_type, entity_id, payload_equals, payload_in.')+'<div><button class="btn">Save rule</button></div></form></div>'
        body+='<div class="card section"><h2>Active automation rules</h2><table><thead><tr><th>Trigger</th><th>Rule</th><th>Condition</th><th>Action</th><th>Delay</th><th>Level</th><th>Measurement</th></tr></thead><tbody>'
        for r in rules:body+=f'<tr><td><code>{app.e(r["trigger_event"])}</code></td><td>{app.e(r["name"])}</td><td><code>{app.e(r.get("condition_json") or "{}")}</code></td><td>{app.e(r["action_type"])}</td><td>{int(r.get("delay_seconds") or 0)}s</td><td>{r["automation_level"]}</td><td>{app.e(r.get("measurement_key") or "")}</td></tr>'
        body+='</tbody></table></div><div class="card section"><h2>Recent business events</h2><table><thead><tr><th>When</th><th>Event</th><th>Entity</th><th>Status</th><th>Error</th></tr></thead><tbody>'
        for r in events:body+=f'<tr><td>{app.e(r["occurred_at"])}</td><td><code>{app.e(r["event_type"])}</code></td><td>{app.e((r.get("entity_type") or "")+" "+(r.get("entity_id") or ""))}</td><td><span class="pill {'good' if r['status']=='Processed' else 'warn'}">{app.e(r["status"])}</span></td><td>{app.e(r.get("error") or "")}</td></tr>'
        if not events:body+='<tr><td colspan="5" class="empty">New product, order, inventory and inbound-message events will appear here.</td></tr>'
        body+='</tbody></table></div>'
        self.send_html(app.layout('Automations',body,'automation'))

    def v13_e2e(self,q):
        import app
        report=oc.run_end_to_end_audit() if q.get('run') else None
        body=app.pagehead('25-step business journey audit','Tests the actual capability chain. It does not send, publish, spend or charge customers.', '<form method="post" action="/v13-e2e/run"><button class="btn">Run 25-step audit</button></form>')
        if report:
            body+=f'<div class="card section"><span class="pill {'good' if report['status']=='Pass' else 'warn'}">{app.e(report["status"])}</span><h2>End-to-end capability result</h2><p class="helper">A Partial / Needs setup result is intentionally not disguised as production readiness.</p></div><div class="card section"><table><thead><tr><th>#</th><th>Business step</th><th>Reality</th><th>Evidence / blocker</th><th></th></tr></thead><tbody>'
            for s in report['steps']:
                body+=f'<tr><td>{s["no"]}</td><td><strong>{app.e(s["label"])}</strong></td><td><span class="pill {'good' if s['status']=='Pass' else 'warn'}">{app.e(s["status"])}</span></td><td>{app.e(s["detail"])}</td><td>{app.button("Open",s["action_url"],"secondary small") if s.get("action_url") else ""}</td></tr>'
            body+='</tbody></table></div>'
        else:body+='<div class="card section empty">Run the audit to check the full path from raw-product upload through retention and next-action recommendations.</div>'
        self.send_html(app.layout('25-step audit',body,'e2e'))
