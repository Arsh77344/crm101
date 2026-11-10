from __future__ import annotations

import html
import urllib.parse

import marketing as m
import integration_v14 as v14
import owner_experience as ox
import v50_reliability as v50


def esc(v):
    return html.escape('' if v is None else str(v),quote=True)


def pill(status: str) -> str:
    s=(status or '').lower()
    if s in {'connected','ready','complete','good'}:kind='good'
    elif 'attention' in s or 'error' in s or 'reconnect' in s or 'needed' in s or 'required' in s:kind='warn'
    elif 'planning only' in s or 'coming soon' in s or 'not implemented' in s:kind='muted'
    else:kind='purple'
    return f'<span class="pill {kind}">{esc(status)}</span>'


class OwnerExperiencePages:
    def v16_get(self,path,q):
        if path=='/':self.owner_dashboard(q)
        elif path=='/setup':self.owner_setup(q)
        elif path=='/integrations':self.owner_integrations(q)
        elif path=='/campaign-builder':self.owner_campaign_builder(q)
        elif path=='/owner-automation':self.owner_automation(q)
        elif path=='/v16-e2e':self.owner_e2e(q)
        else:return False
        return True

    def v16_post(self,path,f):
        val=lambda k,d='':f.get(k,[d])[0]
        if path=='/v16/automation-mode':
            ox.set_automation_mode(val('automation_mode','2'))
            return self.redirect('/owner-automation?saved=1')
        if path=='/campaign-builder/create-business':
            raw={
                'goal_key':val('goal_key','sales'),'name':val('name'),'objective':val('objective_override') or val('objective'),'audience_query':val('audience_override') or val('audience_query'),
                'region':val('region'),'language':val('language'),'budget':val('budget'),'currency':val('currency','GBP'),
                'product_ids':f.get('product_ids',[]),'channels':f.get('channels',[]),'idempotency_key':val('idempotency_key'),
            }
            cid=ox.create_business_campaign(raw)
            return self.redirect('/campaign-builder/'+cid+'?created_from_goal=1')
        return False

    def owner_dashboard(self,q):
        import app
        setup=ox.setup_progress();attention=ox.attention_summary();activity=ox.system_activity();mode=ox.automation_mode()
        try:
            orders=m.one("SELECT count(*) n FROM orders WHERE date(coalesce(ordered_at,''))=date('now')") or {'n':0}
            fin=v50.financial_summary(__import__('datetime').date.today().isoformat(),__import__('datetime').date.today().isoformat())
            revenue_rows=[{'currency':r['currency'],'revenue':r['net_revenue']} for r in fin['currency_breakdown']]
            revenue_text=' / '.join(f"{r['currency']} {float(r['revenue'] or 0):.2f}" for r in revenue_rows) or 'No revenue yet'
        except Exception:
            orders={'n':0};revenue_text='Unavailable'
        try:
            leads=int((m.one("SELECT count(*) n FROM contacts WHERE coalesce(lifecycle_stage,'') NOT IN ('Purchased','Lost')") or {'n':0})['n'])
            buckets={str(r.get('contact_type') or 'Unknown'):int(r.get('n') or 0) for r in m.rows("SELECT coalesce(nullif(contact_type,''),'Unknown') contact_type,count(*) n FROM contacts GROUP BY coalesce(nullif(contact_type,''),'Unknown')")}
            bucket_text=f"{buckets.get('B2B',0)} B2B / {buckets.get('B2C',0)} B2C / {buckets.get('Both',0)} Both / {buckets.get('Unknown',0)} Unknown"
        except Exception:
            leads=0;bucket_text='CRM mix unavailable'
        body=app.pagehead('Business Control Centre','See what happened, what needs you, what the system is doing and what should happen next.',app.button('Upload products','/product-workspace')+app.button('Create marketing','/campaign-builder','secondary'))
        body+=f'''<div class="stats-grid"><div class="card stat-card"><span class="stat-label">{int(orders['n'] or 0)}</span><strong>Orders today</strong><span class="helper">Recorded transactions</span></div><div class="card stat-card"><span class="stat-label">{app.e(revenue_text)}</span><strong>Revenue today</strong><span class="helper">Currencies remain separate</span></div><div class="card stat-card"><span class="stat-label">{leads}</span><strong>Open CRM records</strong><span class="helper">{app.e(bucket_text)}</span></div><div class="card stat-card"><span class="stat-label">{setup['percent']}%</span><strong>Business setup</strong><span class="helper">{setup['complete']} of {setup['total']} steps complete</span></div></div>'''
        if setup['next']:
            n=setup['next'];body+=f'''<div class="card section"><div class="message-top"><div><div class="eyebrow">Continue setup</div><h2>{app.e(n['title'])}</h2><p class="helper">{app.e(n['detail'])}</p><p class="tiny muted">Why this matters: {app.e(n['why'])}</p></div>{app.button('Continue setup',n['url'],'')}</div></div>'''
        body+='<div class="two section"><div class="card"><div class="eyebrow">What needs me?</div><h2>Owner attention</h2>'
        for item in attention:
            body+=f'''<div class="readiness-row"><div class="row-main"><strong>{app.e(item['title'])}</strong><small>{app.e(item['detail'])}</small></div>{app.button('Open',item['url'],'secondary small')}</div>'''
        body+='</div><div class="card"><div class="eyebrow">How autonomous is the system?</div><h2>'+app.e(mode['name'])+'</h2><p>'+app.e(mode['summary'])+'</p><p class="helper"><strong>System:</strong> '+app.e(mode['automatic'])+'</p><p class="helper"><strong>You:</strong> '+app.e(mode['approval'])+'</p>'+app.button('Change automation level','/owner-automation','secondary')+'</div></div>'
        body+='<div class="two section"><div class="card"><div class="eyebrow">What is the system doing?</div><h2>Automation activity</h2>'
        if activity:
            for x in activity:body+=f'<div class="readiness-row"><div class="row-main"><strong>{app.e(x["label"])}</strong><small>{app.e(x["time"])}</small></div>{pill(x["status"])}</div>'
        else:body+='<p class="helper">No queued or retrying background work is currently recorded.</p>'
        body+='</div><div class="card"><div class="eyebrow">What should happen next?</div><h2>Recommended next move</h2>'
        if attention and attention[0]['priority']!='Good':
            x=attention[0];body+=f'<p><strong>{app.e(x["title"])}</strong></p><p class="helper">{app.e(x["detail"])}</p>{app.button("Take action",x["url"],"")}'
        elif setup['next']:
            x=setup['next'];body+=f'<p><strong>{app.e(x["title"])}</strong></p><p class="helper">Finish setup so more of the business can run automatically.</p>{app.button("Continue setup",x["url"],"")}'
        else:
            body+='<p><strong>Create your next growth campaign.</strong></p><p class="helper">Choose a business goal and let the platform recommend channels that are actually ready.</p>'+app.button('Create marketing','/campaign-builder','')
        body+='</div></div>'
        self.send_html(app.layout('Business Control Centre',body,'action'))

    def owner_setup(self,q):
        import app
        prog=ox.setup_progress();body=app.pagehead('Set up your business','A resumable business setup. You do not need to understand APIs, tokens or webhooks.',app.button('Business connections','/integrations','secondary'))
        body+=f'''<div class="card section"><div class="message-top"><div><div class="eyebrow">Setup progress</div><h2>{prog['percent']}% complete</h2><p class="helper">{prog['complete']} of {prog['total']} business steps are complete.</p></div>{app.button('Continue setup',prog['next']['url'] if prog['next'] else '/','') if prog['next'] else pill('Complete')}</div><div style="height:10px;background:#eee;border-radius:999px;overflow:hidden"><div style="height:100%;width:{prog['percent']}%;background:#6b4eff"></div></div></div>'''
        for i,s in enumerate(prog['steps'],1):
            kind='good' if s['status']=='Complete' else 'purple' if s['status']=='Optional' else 'warn'
            body+=f'''<div class="card section"><div class="message-top"><div><span class="pill {kind}">Step {i} · {app.e(s['status'])}</span><h3>{app.e(s['title'])}</h3><p class="helper">{app.e(s['detail'])}</p><p class="tiny muted">Why this matters: {app.e(s['why'])}</p></div>{app.button('Open',s['url'],'secondary')}</div></div>'''
        self.send_html(app.layout('Business setup',body,'setup'))

    def owner_integrations(self,q):
        import app
        groups=ox.integration_groups();body=app.pagehead('Business Connections','Connect business accounts in normal business language. Technical credentials stay in Advanced platform setup.',app.button('Guided setup','/setup','secondary')+app.button('Connection health','/integration-health','secondary'))
        if q.get('disconnected'):body+=app.notice('The selected connection was removed.','success')
        body+='''<div class="card section"><div class="eyebrow">Normal owner experience</div><h2>Connect → Login → Approve → Choose Account → Done</h2><p class="helper">If a provider returns only one valid account/resource, the CRM can select it automatically instead of making you click through an unnecessary choice screen.</p><p class="tiny muted"><strong>Planning only</strong> means the provider is on the roadmap and deliberately has no Connect button until a functional backend exists.</p></div>'''
        planned=[]
        for group in groups:
            active=[c for c in group['cards'] if c['status']!='Planning only']
            planned.extend((group['group'],c) for c in group['cards'] if c['status']=='Planning only')
            if not active:continue
            body+=f'<div class="section-head"><h2>{app.e(group["group"])}</h2></div><div class="campaign-grid">'
            for c in active:
                action=''
                if c['action_url']:
                    label='Manage' if c['status'] in {'Connected','Needs attention'} else 'Connect' if c['status']=='Ready to connect' else 'Setup required'
                    action=app.button(label,c['action_url'],'secondary' if label!='Connect' else '')
                body+=f'''<div class="card"><div class="message-top"><div><h3>{app.e(c['label'])}</h3>{pill(c['status'])}</div></div>{('<p><strong>'+app.e(c['account'])+'</strong></p>') if c['account'] else ''}<p class="helper">{app.e(c['help'])}</p>{('<p class="tiny muted">Last successful activity: '+app.e(c['last_activity'])+'</p>') if c['last_activity'] else ''}<div class="actions">{action}</div></div>'''
            body+='</div>'
        if planned:
            body+='<details class="card section"><summary><strong>Planned integrations</strong></summary><p class="helper">These providers are roadmap items, not broken connections. They have no Connect action until a functional backend is implemented.</p><div class="token-grid section">'
            for group_name,c in planned:body+='<span class="tag">'+app.e(c['label'])+' · '+app.e(group_name)+'</span>'
            body+='</div></details>'
        body+='<details class="card section"><summary><strong>Advanced platform setup</strong></summary><p class="helper">Client IDs, app secrets, developer tokens, callback URLs and other technical setup belong here—not in the normal owner workflow.</p>'+app.button('Open advanced setup','/developer/integrations','secondary')+'</details>'
        self.send_html(app.layout('Business Connections',body,'integrations'))

    def owner_campaign_builder(self,q):
        import app
        goal=q.get('goal',['sales'])[0] if q else 'sales';defaults=ox.campaign_defaults(goal);products=m.rows("SELECT product_id,public_product_name,internal_sku,status FROM products WHERE coalesce(status,'Draft')<>'Archived' ORDER BY public_product_name LIMIT 250")
        goals=[(k,v['label']) for k,v in ox.GOAL_PRESETS.items()]
        body=app.pagehead('Create marketing','Start with what you want the business to achieve. The platform translates that into the channel structure behind the scenes.',app.button('Marketing performance','/marketing-performance','secondary'))
        body+='<div class="card section"><form method="get" action="/campaign-builder">'+app.field('What do you want to achieve?','<select name="goal" onchange="this.form.submit()">'+app.options(goals,defaults['goal_key'])+'</select>','Choose the business result, not an advertising-platform setting.')+'</form></div>'
        body+='<div class="card section"><form method="post" action="/campaign-builder/create-business">'+ '<input type="hidden" name="idempotency_key" value="'+app.e(m.uid('REQ50'))+'">'
        body+=f'<input type="hidden" name="goal_key" value="{app.e(defaults["goal_key"])}">'
        body+=app.field('Campaign name','<input name="name" placeholder="'+app.e(defaults['goal'])+' · '+app.e(defaults['region'])+'" required>')
        body+=f'<div class="note info"><strong>Recommended objective:</strong> {app.e(defaults["objective"])}</div>'
        body+='<input type="hidden" name="objective" value="'+app.e(defaults['objective'])+'"><input type="hidden" name="audience_query" value="'+app.e(defaults['audience'])+'">'
        body+='<div class="formgrid">'+app.field('Location','<input name="region" value="'+app.e(defaults['region'])+'">')+app.field('Language','<input name="language" value="'+app.e(defaults['language'])+'">')+app.field('Budget (optional)','<input type="number" name="budget" min="0" step="0.01" placeholder="500">')+app.field('Currency','<select name="currency">'+app.options(['GBP','EUR','USD','INR'],m.settings().get('default_currency','GBP'))+'</select>')+'</div>'
        body+='<h3 class="section">Which products?</h3><p class="helper">Choose the products or collection you want to promote.</p><div class="check-grid">'
        for p in products:
            body+=f'<label class="checkline"><input type="checkbox" name="product_ids" value="{app.e(p["product_id"])}">{app.e(p["public_product_name"] or p["internal_sku"])} <span class="tiny muted">{app.e(p["status"])}</span></label>'
        if not products:body+='<div class="note warn">Upload a product first. Campaigns must be grounded in real products rather than invented catalogue items.</div>'
        body+='</div><h3 class="section">Recommended channels</h3><p class="helper">Ready channels are selected automatically. A channel that is not connected is shown but not silently treated as ready.</p><div class="check-grid">'
        connect_urls={'Website':'/integrations/v14/connect/shopify','Instagram/Facebook':'/integrations/v14/connect/meta_business','Meta Ads':'/integrations/v14/connect/meta_business','Google Ads':'/integrations/v14/connect/google_account','Email':'/integrations','WhatsApp':'/integrations/v14/connect/whatsapp_cloud'}
        for ch in defaults['channels']:
            checked='checked' if ch['selected'] else ''
            disabled='' if ch['ready'] else 'disabled'
            body+=f'<div class="checkline"><label><input type="checkbox" name="channels" value="{app.e(ch["channel"])}" {checked} {disabled}> {app.e(ch["channel"])}</label> {pill(ch["status"])}'
            if not ch['ready'] and ch['channel'] in connect_urls:body+=' '+app.button('Connect',connect_urls[ch['channel']],'secondary small')
            body+='</div>'
        body+='</div><details class="section"><summary><strong>Advanced campaign details</strong></summary><p class="helper">Use these only when you need to override the recommended audience/objective.</p>'+app.field('Detailed objective','<textarea name="objective_override">'+app.e(defaults['objective'])+'</textarea>')+app.field('Audience description','<textarea name="audience_override">'+app.e(defaults['audience'])+'</textarea>')+'</details><div class="form-foot"><button class="btn" type="submit">Create recommended campaign</button></div></form></div>'
        campaigns=m.rows('SELECT * FROM v10_unified_campaigns ORDER BY created_at DESC LIMIT 30')
        body+='<div class="section-head"><h2>Recent campaigns</h2></div><div class="campaign-grid">'
        for c in campaigns:body+=f'<div class="card"><span class="pill">{app.e(c["status"])}</span><h3>{app.e(c["name"])}</h3><p class="helper">{app.e(c["objective"])}</p>{app.button("Open","/campaign-builder/"+c["id"],"secondary")}</div>'
        if not campaigns:body+='<div class="card empty">No campaigns yet. Choose a goal above to create the first one.</div>'
        body+='</div>'
        self.send_html(app.layout('Create marketing',body,'campaign_builder'))


    def owner_e2e(self,q):
        import app
        report=ox.beginner_e2e();body=app.pagehead('Beginner end-to-end test','A strict 20-step owner journey. Working means there is evidence behind the workflow; setup-dependent and incomplete steps stay visible.',app.button('Business setup','/setup','secondary'))
        body+=f'<div class="card section"><h2>{pill(report["status"])}</h2><p class="helper">'+app.e(' · '.join(f'{n} {k.lower()}' for k,n in report['counts'].items() if n))+'</p></div>'
        body+='<div class="card section"><table><thead><tr><th>#</th><th>Owner step</th><th>Status</th><th>What this means</th><th></th></tr></thead><tbody>'
        for x in report['steps']:
            body+=f'<tr><td>{x["no"]}</td><td><strong>{app.e(x["label"])}</strong></td><td>{pill(x["status"])}</td><td>{app.e(x["detail"])}</td><td>{app.button("Open",x["url"],"secondary small") if x.get("url") else ""}</td></tr>'
        body+='</tbody></table></div>'
        self.send_html(app.layout('Beginner end-to-end test',body,'e2e'))

    def owner_automation(self,q):
        import app
        current=ox.automation_mode();ready=ox.automation_readiness();body=app.pagehead('Automation level',"Choose the policy for routine work. The page also shows what can actually execute with today's rules and connections.",app.button('Automation rules','/event-stream','secondary'))
        if q.get('saved'):body+=app.notice('Automation policy updated. Effective execution still depends on the readiness shown below.','success')
        body+=f'''<div class="card section automation-truth"><div class="section-head"><div><div class="eyebrow">EFFECTIVE TODAY</div><h2>{app.e(ready['effective'])}</h2><p class="helper">Selected policy: {app.e(current['name'])}. A policy is a permission ceiling, not proof that providers or rules are ready.</p></div>{pill(ready['ai_status'])}</div><div class="snapshot-grid"><div class="mini-stat"><strong>{ready['enabled_rules']}</strong><span>enabled automation rules</span></div><div class="mini-stat"><strong>{ready['connected_accounts']}</strong><span>connected external accounts</span></div><div class="mini-stat"><strong>{app.e(ready['ai_status'])}</strong><span>AI runtime status</span></div></div>'''
        if ready['blockers']:
            body+='<div class="section">'+''.join('<div class="readiness-row"><span class="pill warn">LIMIT</span><div class="row-main"><strong>'+app.e(x)+'</strong></div></div>' for x in ready['blockers'])+'</div>'
        body+='</div><div class="campaign-grid">'
        for key,meta in ox.AUTOMATION_MODES.items():
            body+=f'''<div class="card"><div class="message-top"><div><h3>{app.e(meta['name'])}</h3>{pill('Selected policy' if key==current['key'] else 'Available')}</div></div><p>{app.e(meta['summary'])}</p><p class="helper"><strong>System may handle:</strong> {app.e(meta['automatic'])}</p><p class="helper"><strong>You approve:</strong> {app.e(meta['approval'])}</p><form method="post" action="/v16/automation-mode"><input type="hidden" name="automation_mode" value="{app.e(key)}"><button class="btn {'secondary' if key==current['key'] else ''}" type="submit">{'Selected' if key==current['key'] else 'Use this level'}</button></form></div>'''
        body+='</div><div class="card section"><h2>Safety does not disappear at higher automation</h2><p class="helper">Consent, provider permissions, budget controls, source-of-truth rules, low-confidence approvals and explicit provider confirmation still apply. A higher level does not turn incomplete integrations into working ones.</p></div>'
        self.send_html(app.layout('Automation level',body,'automation'))
