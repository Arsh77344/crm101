from __future__ import annotations
import json,re
import marketing as m
import business_os as bos
import runtime_config as rc
import db_layer
import media_store
import v50_reliability as v50
import v37_business_readiness as v37br

class BusinessOSPages:
    def v9_get(self,path,q):
        if path in {'/','/action-centre','/daily'}:self.action_centre(q)
        elif path=='/automation-engine':self.automation_engine(q)
        elif path=='/integrations-v9':return self.redirect('/integrations')
        elif path=='/email-infrastructure':return self.redirect('/integrations')
        elif path=='/model-routing':self.model_routing(q)
        elif path=='/system-health':self.system_health_page(q)
        elif path=='/architecture-readiness':self.architecture_readiness(q)
        elif path=='/system-health/full-backup/latest':
            import app
            latest=v50.latest_full_backup(app.ROOT)
            if not latest:return self.redirect('/system-health?no_backup=1')
            raw=latest.read_bytes();return self.send_file(raw,latest.name,'application/zip')
        elif re.fullmatch(r'/customer-360/[^/]+',path):self.customer_360_page(path.split('/')[2],q)
        else:return False
        return True

    def v9_post(self,path,f):
        v=lambda k,d='':f.get(k,[d])[0]
        if path=='/action-centre/refresh':
            bos.generate_recommendations();return self.redirect('/action-centre?refreshed=1')
        if re.fullmatch(r'/recommendations/[^/]+/(resolve|dismiss)',path):
            rid=path.split('/')[2];status='Resolved' if path.endswith('/resolve') else 'Dismissed'
            with m.connect() as con:con.execute('UPDATE v9_recommendations SET status=?,resolved_at=CURRENT_TIMESTAMP WHERE id=?',(status,rid))
            return self.redirect('/action-centre')
        if path=='/automation-engine/run':
            result=bos.run_jobs(100);return self.redirect('/automation-engine?done='+str(result['completed'])+'&failed='+str(result['failed']))
        if re.fullmatch(r'/automation-engine/jobs/[^/]+/retry',path):
            jid=path.split('/')[3]
            with m.connect() as con:con.execute("UPDATE v9_jobs SET status='Retry',next_run_at=CURRENT_TIMESTAMP,last_error='',updated_at=CURRENT_TIMESTAMP WHERE id=?",(jid,))
            return self.redirect('/automation-engine')
        if re.fullmatch(r'/failures/[^/]+/resolve',path):
            fid=path.split('/')[2]
            with m.connect() as con:con.execute('UPDATE v9_failures SET resolved=1,resolved_at=CURRENT_TIMESTAMP WHERE id=?',(fid,))
            return self.redirect('/system-health')
        if path=='/model-routing/save':
            bos.save_model_route({k:x[0] for k,x in f.items()});return self.redirect('/model-routing?saved=1')
        if path=='/integrations-v9/save':
            raise ValueError('The manual V9 integration status editor was retired in V10. Use Integration Centre; only a successful provider test can mark an account Connected.')
        if path=='/email-infrastructure/save':
            raise ValueError('Manual DNS verification was retired in V10. Connect the email provider and use its real domain verification workflow in Integration Centre.')
        if path=='/identity/rebuild':
            bos.rebuild_identity_index();return self.redirect('/system-health?identities=1')
        if path=='/system-health/full-backup':
            import app
            bos.create_full_backup(app.ROOT);return self.redirect('/system-health?backup=1')
        if path=='/system-health/full-backup/verify':
            import app
            v50.verify_backup_restore(app.ROOT);return self.redirect('/system-health?restore_verified=1')
        return False

    def action_centre(self,q):
        import app
        bos.initialise();bos.generate_recommendations()
        recs=m.rows("SELECT * FROM v9_recommendations WHERE status='Open' ORDER BY CASE priority WHEN 'High' THEN 0 WHEN 'Medium' THEN 1 ELSE 2 END,created_at DESC")
        h=bos.system_health();due=m.one("SELECT count(*) n FROM m4_tasks WHERE status='Open' AND date(due_date)<=date('now')")['n'];open_deals=m.one("SELECT count(*) n FROM opportunities WHERE coalesce(stage,'') NOT IN ('Won','Lost','Closed')")['n']
        orders=m.one("SELECT count(*) n FROM orders WHERE date(coalesce(ordered_at,''))=date('now')")['n']
        fin=v50.financial_summary(__import__('datetime').date.today().isoformat(),__import__('datetime').date.today().isoformat())
        sales_rows=[{'currency':r['currency'],'total':r['net_revenue']} for r in fin['currency_breakdown']]
        sales=' / '.join(f"{r['currency']} {float(r['total'] or 0):.2f}" for r in sales_rows) or 'No recognized revenue yet'
        buckets={r['contact_type']:r['n'] for r in m.rows("SELECT coalesce(contact_type,'Unknown') contact_type,count(*) n FROM contacts GROUP BY coalesce(contact_type,'Unknown')")}
        body=app.pagehead('AI Daily Action Centre','One screen for what happened, what is blocked and what the business should do next.','<form method="post" action="/action-centre/refresh"><button class="btn secondary">Refresh recommendations</button></form>')
        if q.get('refreshed'):body+=app.notice('Recommendations and automation readiness were refreshed.','success')
        body+=f'''<div class="stats-grid"><div class="card stat-card"><span class="stat-label">{orders}</span><strong>Orders today</strong><span class="helper">Recorded orders</span></div><div class="card stat-card"><span class="stat-label">{app.e(sales)}</span><strong>Revenue today</strong><span class="helper">Currencies remain separate; no FX conversion</span></div><div class="card stat-card"><span class="stat-label">{open_deals}</span><strong>Open opportunities</strong><span class="helper">Sales pipeline</span></div><div class="card stat-card"><span class="stat-label">{due}</span><strong>Tasks due</strong><span class="helper">Human attention</span></div></div><div class="card section"><strong>{buckets.get('B2B',0)} B2B / {buckets.get('B2C',0)} B2C / {buckets.get('Both',0)} Both / {buckets.get('Unknown',0)} Unknown</strong><p class="helper">Contact journey breakdown. Unknown records stay visible for classification rather than disappearing from totals.</p></div>'''
        body+='<div class="two section"><div><div class="section-head"><h2>Needs your attention</h2><span class="tiny muted">Exceptions and recommendations, not a list of every record</span></div>'
        if not recs:body+='<div class="card empty">No open recommendations. The automation engine will surface exceptions here.</div>'
        for r in recs[:20]:
            pill='warn' if r['priority']=='High' else 'purple';body+=f'''<div class="card section"><div class="message-top"><div><span class="pill {pill}">{app.e(r['priority'])}</span><span class="pill">{app.e(r['kind'])}</span><h3>{app.e(r['title'])}</h3><p class="helper">{app.e(r['reason'])}</p></div></div><div class="toolbar section">{app.button('Open',r['action_url'] or '/','secondary small') if r['action_url'] else ''}<form method="post" action="/recommendations/{app.e(r['id'])}/resolve"><button class="btn small">Mark done</button></form><form method="post" action="/recommendations/{app.e(r['id'])}/dismiss"><button class="btn secondary small">Dismiss</button></form></div></div>'''
        body+='</div><div><div class="card"><div class="eyebrow">Platform readiness</div><h2>Can the business automate end-to-end?</h2>'
        checks=[('Database',h['db_quick_check']=='ok',h['db_quick_check']),('Automation queue',h['dead_jobs']==0,f"{h['queued_jobs']} active · {h['dead_jobs']} dead-letter"),('System failures',h['open_failures']==0,f"{h['open_failures']} unresolved"),('External integrations',h['connected']>=4,f"{h['connected']}/{h['connectors']} connected")]
        for label,ok,detail in checks:body+=f'<div class="readiness-row"><span class="pill {"good" if ok else "warn"}">{"READY" if ok else "ACTION"}</span><div class="row-main"><strong>{app.e(label)}</strong><small>{app.e(detail)}</small></div></div>'
        body+='<div class="toolbar section">'+app.button('System health','/system-health','secondary')+app.button('Integrations','/integrations','secondary')+app.button('Automation engine','/automation-engine','secondary')+'</div></div></div></div>'
        self.send_html(app.layout('Daily Action Centre',body,'action'))

    def automation_engine(self,q):
        import app
        jobs=m.rows('SELECT * FROM v9_jobs ORDER BY created_at DESC LIMIT 100');events=m.rows('SELECT * FROM v9_events ORDER BY created_at DESC LIMIT 50')
        body=app.pagehead('Automation engine','Event-driven jobs with retries and a dead-letter state. Automations never fail silently.','<form method="post" action="/automation-engine/run"><button class="btn secondary">Run due jobs</button></form>')
        if q.get('done'):body+=app.notice(f"Completed {app.e(q['done'][0])} jobs; {app.e(q.get('failed',['0'])[0])} failed.",'success')
        body+='''<div class="card section"><div class="eyebrow">Core event patterns</div><h2>Business actions become events</h2><div class="flow"><span>Product uploaded</span><b>→</b><span>Product readiness</span><b>→</b><span>Creative / commerce / campaign jobs</span></div><div class="flow section"><span>Lead received</span><b>→</b><span>Enrich / score</span><b>→</b><span>Segment / follow-up</span></div><div class="flow section"><span>Order recorded</span><b>→</b><span>Attribution</span><b>→</b><span>Post-purchase / review / cross-sell</span></div></div>'''
        body+='<div class="section-head"><h2>Job queue</h2><span class="tiny muted">Retryable background work</span></div><div class="table-wrap"><table><tr><th>Status</th><th>Job</th><th>Object</th><th>Attempts</th><th>Error</th><th></th></tr>'
        for j in jobs:body+=f'''<tr><td><span class="pill {"good" if j['status']=='Completed' else 'warn' if j['status'] in ('Retry','Dead letter') else ''}">{app.e(j['status'])}</span></td><td>{app.e(j['job_type'])}</td><td>{app.e(j['object_type'])} {app.e(j['object_id'])}</td><td>{j['attempts']}/{j['max_attempts']}</td><td>{app.e(j['last_error'])}</td><td>{('<form method="post" action="/automation-engine/jobs/'+app.e(j['id'])+'/retry"><button class="btn secondary small">Retry</button></form>') if j['status'] in ('Retry','Dead letter') else ''}</td></tr>'''
        body+='</table></div><div class="section-head"><h2>Recent events</h2></div><div class="table-wrap"><table><tr><th>When</th><th>Event</th><th>Object</th><th>Status</th></tr>'
        for e in events:body+=f'<tr><td>{app.e(e["created_at"])}</td><td>{app.e(e["event_type"])}</td><td>{app.e(e["object_type"])} {app.e(e["object_id"])}</td><td>{app.e(e["status"])}</td></tr>'
        body+='</table></div>';self.send_html(app.layout('Automation engine',body,'automation'))

    def integrations(self,q):
        import app
        rows=bos.connector_rows();body=app.pagehead('Integration centre','Modular connection registry. A connection marked here is a configuration status, not proof of a live provider handshake.',app.button('Email infrastructure','/email-infrastructure','secondary'))
        if q.get('saved'):body+=app.notice('Integration status saved. Live provider health should be verified by the connector when credentials are added.','success')
        cats={}
        for r in rows:cats.setdefault(r['category'],[]).append(r)
        for cat,items in cats.items():
            body+=f'<div class="section-head"><h2>{app.e(cat)}</h2></div><div class="product-grid">'
            for r in items:
                caps=', '.join(json.loads(r['capabilities_json'] or '[]'))
                body+=f'''<div class="card"><div class="message-top"><div><span class="pill {"good" if r['status']=='Connected' else 'warn'}">{app.e(r['status'])}</span><h3>{app.e(r['label'])}</h3><p class="helper">{app.e(r['provider'])}</p></div></div><p class="helper section">{app.e(caps)}</p><form method="post" action="/integrations-v9/save" class="section"><input type="hidden" name="connector_key" value="{app.e(r['connector_key'])}">{app.field('Provider','<input name="provider" value="'+app.e(r['provider'])+'">')}{app.field('Status','<select name="status">'+app.options(['Not connected','Needs setup','Connected','Error','Expired'],r['status'])+'</select>')}<button class="btn secondary">Save status</button></form></div>'''
            body+='</div>'
        self.send_html(app.layout('Integrations',body,'integrations'))

    def email_infrastructure(self,q):
        import app
        domains=m.rows('SELECT * FROM v9_email_domains ORDER BY updated_at DESC');body=app.pagehead('Email infrastructure','Guided sending-domain readiness for marketing, transactional, outreach and service email.')
        if q.get('saved'):body+=app.notice('Email-domain configuration saved. DNS states are owner/provider confirmations until a live DNS/provider verifier is connected.','success')
        body+='''<div class="card section"><div class="eyebrow">What production email requires</div><h2>Domain authentication and deliverability</h2><div class="flow"><span>Sending domain</span><b>→</b><span>SPF</span><b>→</b><span>DKIM</span><b>→</b><span>DMARC</span><b>→</b><span>Bounces / complaints / unsubscribes</span><b>→</b><span>Reputation monitoring</span></div><p class="helper section">The CRM keeps suppression and permission logic separate from provider delivery. Provider webhooks should update bounces, complaints, unsubscribes, deliveries and clicks once connected.</p></div>'''
        body+='<div class="two section"><div>'
        for d in domains:
            ready=d['domain_status']=='Verified';body+=f'''<div class="card section"><span class="pill {"good" if ready else 'warn'}">{app.e(d['domain_status'])}</span><h2>{app.e(d['domain'])}</h2><p class="helper">Sender: {app.e(d['sender_email'] or 'Not set')} · Provider: {app.e(d['provider'] or 'Not set')}</p><div class="readiness-row"><span>SPF</span><strong>{app.e(d['spf_status'])}</strong></div><div class="readiness-row"><span>DKIM</span><strong>{app.e(d['dkim_status'])}</strong></div><div class="readiness-row"><span>DMARC</span><strong>{app.e(d['dmarc_status'])}</strong></div><p class="helper">Daily safety limit: {d['daily_limit']}</p></div>'''
        if not domains:body+='<div class="card empty">No sending domain configured yet.</div>'
        body+='</div><div><div class="card"><h2>Add / review sending domain</h2><form method="post" action="/email-infrastructure/save">'+app.field('Domain','<input name="domain" placeholder="example.com" required>')+app.field('Provider','<input name="provider" placeholder="Your email provider">')+app.field('Sender name','<input name="sender_name" placeholder="Brand / team">')+app.field('Sender email','<input name="sender_email" type="email" placeholder="hello@example.com">')
        for key,label in [('spf_status','SPF'),('dkim_status','DKIM'),('dmarc_status','DMARC')]:body+=app.field(label,'<select name="'+key+'">'+app.options(['Unknown','Missing','Pending','Verified','Fail'],'Unknown')+'</select>')
        body+=app.field('Initial daily sending limit','<input type="number" name="daily_limit" min="1" max="100000" value="100">','Warm volume gradually and follow provider guidance; this is a business safety limit, not a provider quota.')+'<button class="btn">Save domain</button></form></div></div></div>'
        self.send_html(app.layout('Email infrastructure',body,'email'))

    def model_routing(self,q):
        import app
        routes=m.rows('SELECT * FROM v9_model_routes ORDER BY task_key');body=app.pagehead('AI model routing','Use different models for different jobs, with fallbacks. Provider/model IDs stay configurable so the platform can evolve.')
        if q.get('saved'):body+=app.notice('Model route updated.','success')
        body+='<div class="card section"><p class="helper">Defaults favour precision for product-preserving image edits, efficiency for high-volume copy, and stronger reasoning for business analysis. Real provider availability and cost should be monitored in production.</p></div>'
        for r in routes:
            body+=f'''<div class="card section"><form method="post" action="/model-routing/save"><input type="hidden" name="task_key" value="{app.e(r['task_key'])}"><div class="message-top"><div><span class="pill">{app.e(r['provider'])}</span><h3>{app.e(r['label'])}</h3><p class="helper">{app.e(r['notes'])}</p></div></div><div class="formgrid">{app.field('Provider','<input name="provider" value="'+app.e(r['provider'])+'">')}{app.field('Primary model','<input name="model" value="'+app.e(r['model'])+'">')}{app.field('Reasoning','<select name="reasoning">'+app.options(['','none','low','medium','high','xhigh','max'],r['reasoning'])+'</select>')}{app.field('Fallback','<input name="fallback_model" value="'+app.e(r['fallback_model'])+'">')}</div><input type="hidden" name="enabled" value="1"><button class="btn secondary section">Save route</button></form></div>'''
        self.send_html(app.layout('AI model routing',body,'models'))

    def system_health_page(self,q):
        import app
        # System health must diagnose a clean workspace without requiring some
        # other business-OS page to have created its v9 recovery tables first.
        bos.initialise()
        h=bos.system_health();fail=m.rows('SELECT * FROM v9_failures WHERE resolved=0 ORDER BY coalesce(last_seen,created_at) DESC LIMIT 50');
        incidents=m.rows("SELECT * FROM v13_incidents WHERE status='Open' AND severity IN ('Error','Critical') ORDER BY coalesce(last_seen,created_at) DESC LIMIT 50") if m.table_exists('v13_incidents') else []
        blocked=m.rows("SELECT id,process_type,object_type,object_id,status,current_step,updated_at FROM v17_processes WHERE status IN ('Blocked','Needs attention') ORDER BY updated_at DESC LIMIT 50") if m.table_exists('v17_processes') else []
        body=app.pagehead('System health & recovery','Canonical operational failures, dead-letter jobs, data integrity and recovery actions in one place.')
        if q.get('identities'):body+=app.notice('Customer identity index rebuilt.','success')
        if q.get('backup'):body+=app.notice('Full backup created. Recovery is still unverified until you run Verify latest restore.','success')
        if q.get('restore_verified'):body+=app.notice('Latest backup passed an isolated restore drill. Recovery readiness is verified for this exact archive.','success')
        if q.get('no_backup'):body+=app.notice('No full backup exists yet. Create one first, then Download latest will be available.','warn')
        body+=f'''<div class="stats-grid"><div class="card stat-card"><span class="stat-label">{app.e(h['db_quick_check'])}</span><strong>Database check</strong></div><div class="card stat-card"><span class="stat-label">{h['open_failures']}</span><strong>Unresolved failures</strong></div><div class="card stat-card"><span class="stat-label">{h['dead_jobs']}</span><strong>Dead-letter jobs</strong></div><div class="card stat-card"><span class="stat-label">{h['connected']}/{h['connectors']}</span><strong>Connected integrations</strong></div></div>'''
        backup=v50.backup_readiness(app.ROOT)
        backup_exists=bool(backup.get('latest')) and backup.get('status')!='NOT_CREATED'
        verify_btn='<form method="post" action="/system-health/full-backup/verify"><button class="btn secondary">Verify latest restore</button></form>' if backup_exists else '<button class="btn secondary" disabled aria-disabled="true" title="Create a backup first">Verify latest restore</button>'
        download_btn='<a class="btn secondary" href="/system-health/full-backup/latest">Download latest</a>' if backup_exists else '<button class="btn secondary" disabled aria-disabled="true" title="No backup artifact exists">Download latest</button>'
        body+=f'<div class="card section"><div class="eyebrow">Verified recovery</div><h2>{app.e(backup.get("display_status") or backup.get("status"))}</h2><p class="helper">{app.e(backup.get("detail"))}</p><div class="toolbar"><form method="post" action="/system-health/full-backup"><button class="btn secondary">Create full backup</button></form>{verify_btn}{download_btn}</div></div><div class="card section"><div class="eyebrow">Customer identity</div><h2>Prevent fragmented profiles</h2><p class="helper">Email, normalised phone and social username are indexed as identities. Imports should match these before creating another contact.</p><form method="post" action="/identity/rebuild"><button class="btn secondary">Rebuild identity index</button></form></div>'
        body+='<div class="section-head"><h2>Open operational failures</h2><span class="tiny muted">One canonical health view</span></div>'
        if not fail and not incidents and not blocked:body+='<div class="card empty">No unresolved operational failures recorded.</div>'
        for x in fail:
            occ=int(x.get('occurrence_count') or 1);extra=(f' · {occ} occurrences' if occ>1 else '')
            recovery=x.get('recovery_hint') or 'Review the affected workflow and retry when safe.'
            technical=x.get('message') or ''
            advanced=(f'<details class="section"><summary>Advanced details</summary><p class="helper">{app.e(technical)}</p></details>' if technical else '')
            body+=f'''<div class="card section"><span class="pill warn">{app.e(x['severity'])}</span><h3>{app.e(x['source'])}</h3><p>{app.e(recovery)}</p><p class="helper">{app.e(extra.lstrip(' ·')) if extra else 'Owner action required'}</p>{advanced}<form method="post" action="/failures/{app.e(x['id'])}/resolve"><button class="btn secondary">Mark resolved</button></form></div>'''
        for x in incidents:
            occ=int(x.get('occurrence_count') or 1)
            recovery=x.get('recovery') or 'Review the affected workflow and retry when safe.'
            technical=x.get('latest_error') or x.get('detail') or ''
            advanced=(f'<details class="section"><summary>Advanced details</summary><p class="helper">{app.e(technical)}</p></details>' if technical else '')
            _url=v37br.incident_action_url(x.get('entity_type') or '',x.get('entity_id') or '')
            _label,_url=v37br.recovery_action('Incident',x.get('title') or '',_url,x.get('entity_type') or '',x.get('entity_id') or '')
            body+=f'''<div class="card section"><span class="pill warn">{app.e(x['severity'])}</span><h3>{app.e(x['title'])}</h3><p>{app.e(recovery)}</p><p class="helper">{occ} occurrence(s) grouped into this incident.</p>{advanced}<a class="btn secondary" href="{app.e(_url)}">{app.e(_label)}</a></div>'''
        for x in blocked:
            _fallback='/operations/process/'+str(x['id'])
            _label,_url=v37br.recovery_action('Process',str(x.get('process_type') or ''),_fallback,x.get('object_type') or '',x.get('object_id') or '')
            body+=f'''<div class="card section"><span class="pill warn">Process</span><h3>Continue {app.e(str(x.get('process_type') or 'business process').replace('_',' '))}</h3><p>Stage: {app.e(x.get('current_step') or 'unknown')} · affected {app.e(x.get('object_type') or 'record')} {app.e(x.get('object_id') or '')}</p><a class="btn secondary" href="{app.e(_url)}">{app.e(_label)}</a></div>'''
        self.send_html(app.layout('System health',body,'health'))

    def customer_360_page(self,cid,q):
        import app
        d=bos.customer_360(cid);c=d['contact'];name=c.get('full_name') or c.get('username') or cid
        body=app.pagehead(name,'Unified customer journey across CRM, campaigns, communications, sales and orders.',app.button('Edit contact','/contacts/'+cid+'/edit','secondary'))
        body+=f'''<div class="stats-grid"><div class="card stat-card"><span class="stat-label">{len(d['orders'])}</span><strong>Orders</strong></div><div class="card stat-card"><span class="stat-label">{len(d['deals'])}</span><strong>Opportunities</strong></div><div class="card stat-card"><span class="stat-label">{len(d['campaigns'])}</span><strong>Campaigns</strong></div><div class="card stat-card"><span class="stat-label">{len(d['interactions'])+len(d['activities'])}</span><strong>Interactions</strong></div></div>'''
        body+='<div class="two section"><div><div class="card"><h2>Profile</h2><div class="kv"><div>Type</div><div>'+app.e(c.get('contact_type'))+'</div><div>Email</div><div>'+app.e(c.get('email'))+'</div><div>Phone</div><div>'+app.e(c.get('phone_number'))+'</div><div>Country</div><div>'+app.e(c.get('country'))+'</div><div>Stage</div><div>'+app.e(c.get('lifecycle_stage'))+'</div></div></div></div><div><div class="card"><h2>Channel permissions</h2>'
        for p in d['permissions'][:10]:body+=f'<div class="readiness-row"><span>{app.e(p["channel"])}</span><strong>{app.e(p["status"])}</strong></div>'
        body+='</div></div></div><div class="section-head"><h2>Journey timeline</h2></div><div class="card">'
        timeline=[]
        for x in d['activities']:timeline.append((x.get('created_at') or '',x.get('channel') or x.get('activity_type') or 'Activity',x.get('summary') or ''))
        for x in d['interactions']:timeline.append((x.get('occurred_at') or '',x.get('channel') or 'Interaction',x.get('subject_or_summary') or ''))
        for x in d['orders']:timeline.append((x.get('ordered_at') or '', 'Order', str(x.get('total') or '')+' '+str(x.get('currency') or '')))
        for x in d.get('delivery',[]):timeline.append((x.get('occurred_at') or '', x.get('channel') or 'Delivery', x.get('event_type') or ''))
        for x in d.get('touchpoints',[]):timeline.append((x.get('occurred_at') or '', x.get('channel') or 'Touchpoint', (x.get('source') or '')+' · '+(x.get('event_type') or '')))
        for when,kind,summary in sorted(timeline,reverse=True)[:80]:body+=f'<div class="readiness-row"><span class="pill">{app.e(kind)}</span><div class="row-main"><strong>{app.e(summary)}</strong><small>{app.e(when)}</small></div></div>'
        if not timeline:body+='<div class="empty">No journey events yet.</div>'
        body+='</div>';self.send_html(app.layout('Customer 360',body,'contacts'))

    def architecture_readiness(self,q):
        import app,platform_core as pc
        db_ok,db_detail=db_layer.database_ready();store=media_store.status();prod_gaps=rc.production_gaps()
        body=app.pagehead('Production architecture readiness','V14 retains the production foundation and adds login-first OAuth connections, connection health, source-of-truth controls and secure account selection on top of PostgreSQL, object storage, durable workers, MFA and HTTPS infrastructure.')
        items=[
          ('Database',('Ready' if db_ok and db_layer.USING_POSTGRES else 'Local mode' if db_ok else 'Action required'),f"Backend: {db_layer.backend_name()} · {db_detail}"),
          ('Object storage / CDN',('Ready' if store['publishable'] and store['backend']=='s3' else 'Action required'),f"Backend: {store['backend']} · public media {'ready' if store['publishable'] else 'not ready'}"),
          ('HTTPS / webhook ingress',('Ready' if bool(rc.valid_public_https(rc.PUBLIC_BASE_URL)) else 'Action required'),rc.PUBLIC_BASE_URL or 'No production PUBLIC_BASE_URL configured.'),
          ('Durable worker',('Implemented' if db_layer.USING_POSTGRES else 'Available'), 'Run durable_worker.py as a separate process in production; jobs use persistent database leases, retries and dead-letter states.'),
          ('Authentication / MFA',('Ready' if pc.auth_enabled() and pc.production_mfa_ready() else 'Action required'),'Production mode refuses to start unless sign-in is enabled and at least one active Owner has TOTP MFA.'),
          ('Credential encryption',('Ready' if (not rc.IS_PRODUCTION or bool(__import__('os').environ.get('CRM_VAULT_MASTER_KEY'))) else 'Action required'),'Production uses CRM_VAULT_MASTER_KEY from the deployment secret manager rather than creating a key on disk.'),
          ('Shopify product media','Implemented','Cloud-public product media can now be attached to Shopify DRAFT product creation; local-only media remains blocked.'),
          ('Backups / restore','Implemented foundation','PostgreSQL pg_dump/pg_restore scripts plus optional encrypted portable backup; provider PITR/object-storage versioning are still recommended.'),
          ('Observability','Improved','Structured worker logs and health/readiness endpoints exist; managed log aggregation, metrics, traces and alert routing still depend on the deployment platform.'),
          ('Paid ad writes','Still gated','Meta/Google paid mutation remains intentionally unavailable until budget ceilings, conversion tracking, approval and provider-account tests are completed.'),
        ]
        body+='<div class="card section"><h2>Production boundary</h2><p class="helper">V12 can run as a production-configured web + worker deployment, but it does not pretend external accounts or paid advertising are live until their real provider tests and permissions succeed. The supplied Docker/Caddy/PostgreSQL deployment is a reference stack; managed cloud services may replace those components.</p></div>'
        if prod_gaps:
            body+=app.notice('Production configuration still needs: '+' '.join(prod_gaps),'warn')
        for item in items:
            name,state,desc=item
            good=state in {'Ready','Implemented','Implemented foundation','Improved'}
            body+=f'<div class="card section"><div class="message-top"><div><span class="pill {"good" if good else "warn"}">{app.e(state)}</span><h3>{app.e(name)}</h3><p class="helper">{app.e(desc)}</p></div></div></div>'
        body+='<div class="card section"><h2>Deployment files included</h2><p class="helper"><code>Dockerfile</code>, <code>docker-compose.production.yml</code>, <code>.env.production.example</code>, <code>production/Caddyfile</code>, <code>production_migrate.py</code>, <code>backup_production.py</code>, <code>restore_production.py</code> and <code>PRODUCTION_RUNBOOK.md</code>.</p></div>'
        self.send_html(app.layout('Architecture readiness',body,'health'))
