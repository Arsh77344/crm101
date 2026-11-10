from __future__ import annotations

import datetime as dt
import re
import urllib.parse

import marketing as m
import db_layer
import v50_reliability as v50
import integration_layer as il
import owner_experience as ox
import v27_marketing as vm
import v35_truth as truth


def _pill(app,status):
    low=str(status or '').lower()
    kind='good' if any(x in low for x in ['ready','connected','complete','active']) else 'warn' if any(x in low for x in ['need','error','failed','blocked','not connected','planning only']) else 'purple'
    return f'<span class="pill {kind}">{app.e(status)}</span>'


def _readiness_action(app,row):
    status=str(row.get('status') or '').lower()
    channel=str(row.get('channel') or '')
    if 'not connected' in status or 'needs setup' in status:
        return app.button('Connect','/integrations','secondary small')
    if 'planning only' in status:
        return app.button('Plan content','/campaign-builder','secondary small')
    if 'partial' in status:
        return app.button('Review setup','/integrations','secondary small')
    if channel=='SEO/Blog':
        return app.button('Draft content','/blogs','secondary small')
    return app.button('View health','/integration-health','secondary small')


def _money_map(rows):
    vals=[]
    for cur,val in rows:
        if float(val or 0): vals.append((cur or '—',float(val or 0)))
    if not vals:return '0'
    if len(vals)==1:return f'{vals[0][0]} {vals[0][1]:,.2f}'
    return ' · '.join(f'{c} {v:,.2f}' for c,v in vals[:3]) + (' +' if len(vals)>3 else '')


class V27MarketingPages:
    def v27_get(self,path,q):
        if path=='/marketing':self.v27_marketing_home(q)
        elif path=='/campaign-builder':self.v27_campaign_builder(q)
        elif path=='/marketing-calendar':self.v27_marketing_calendar(q)
        elif path=='/customer-journeys':self.v27_customer_journeys(q)
        elif re.fullmatch(r'/campaign-builder/[^/]+/content',path):self.v27_channel_pack(path.split('/')[2],q)
        elif path=='/marketing-performance':self.v27_marketing_performance(q)
        else:return False
        return True

    def v27_post(self,path,f):
        val=lambda k,d='':f.get(k,[d])[0]
        if path=='/campaign-builder/create-business':
            raw={
                'goal_key':val('goal_key','sales'),'name':val('name'),'objective':val('objective_override') or val('objective'),
                'audience_query':val('audience_override') or val('audience_query'),'region':val('region'),'language':val('language'),
                'budget':val('budget'),'currency':val('currency','GBP'),'product_ids':f.get('product_ids',[]),'channels':f.get('channels',[]),'idempotency_key':val('idempotency_key'),
                'cta_goal':val('cta_goal','view_collection'),'start_date':val('start_date'),'end_date':val('end_date'),'owner_note':val('owner_note')
            }
            cid=vm.create_owner_campaign(raw)
            return self.redirect('/campaign-builder/'+cid+'?created_from_goal=1')
        if re.fullmatch(r'/marketing-calendar/[^/]+/schedule',path):
            cid=path.split('/')[2]
            vm.save_campaign_context(cid,{'cta_goal':val('cta_goal','view_collection'),'start_date':val('start_date'),'end_date':val('end_date'),'owner_note':val('owner_note')})
            return self.redirect('/marketing-calendar?saved=1')
        return False

    def v27_marketing_home(self,q):
        import app
        data=vm.overview(30)
        fin=v50.financial_summary((__import__('datetime').date.today()-__import__('datetime').timedelta(days=30)).isoformat(),__import__('datetime').date.today().isoformat())
        order_rows=[{'currency':r['currency'],'total':r['net_revenue']} for r in fin['currency_breakdown']]
        perf_rows=data['performance']['rows']
        spend_by={}
        for r in perf_rows:spend_by[r.get('currency') or '—']=spend_by.get(r.get('currency') or '—',0)+float(r.get('spend') or 0)
        actions=app.button('Create campaign','/campaign-builder')+app.button('Marketing calendar','/marketing-calendar','secondary')
        body=app.pagehead('Marketing','Turn products into campaigns, customer conversations and measurable sales without learning every advertising platform.',actions)
        body+=f'''<div class="stats-grid"><div class="card stat-card"><span class="stat-label">{data['campaigns']}</span><strong>Campaign plans</strong><span class="helper">Active workspaces</span></div><div class="card stat-card"><span class="stat-label">{data['crm_total']}</span><strong>CRM records</strong><span class="helper">Total records available for reviewed targeting</span></div><div class="card stat-card"><span class="stat-label">{data['orders']}</span><strong>Orders</strong><span class="helper">Last 30 days · {_money_map([(r['currency'],r['total']) for r in order_rows])}</span></div><div class="card stat-card"><span class="stat-label">{len(perf_rows)}</span><strong>Synced metric groups</strong><span class="helper">Recorded provider spend: {_money_map(list(spend_by.items()))}</span></div></div>'''
        body+='<div class="section-head"><div><div class="eyebrow">Start from the business outcome</div><h2>What do you want to do?</h2></div></div><div class="campaign-grid">'
        cards=[
            ('Promote products','Choose products and let the system prepare an audience, channel plan and content pack.','/campaign-builder','Create campaign'),
            ('Find the right audience','Describe the people you want to reach in plain English using recorded CRM/order facts.','/audience-builder','Build audience'),
            ('Plan social content','Schedule reviewed Instagram/Facebook image posts using approved CRM assets.','/operations/social','Open social planner'),
            ('Nurture customers','Review post-purchase, win-back and VIP-style journeys without silent sending.','/customer-journeys','Customer journeys'),
            ('Create SEO content','Turn product/collection demand into reviewed regional blog drafts.','/blogs','SEO & blog'),
            ('Understand results','Compare synced channel metrics with real CRM/order outcomes.','/marketing-performance','View results'),
        ]
        for title,desc,url,label in cards:body+=f'<div class="card"><h3>{app.e(title)}</h3><p class="helper">{app.e(desc)}</p>{app.button(label,url,"secondary")}</div>'
        body+='</div>'
        recs=data.get('recommendations') or []
        body+='<div class="two section"><div class="card"><div class="eyebrow">What needs attention?</div><h2>Marketing recommendations</h2>'
        if recs:
            for r in recs[:8]:
                title=r.get('title') or 'Review marketing signal';reason=r.get('reason') or r.get('detail') or '';url=r.get('action_url') or '/marketing-performance'
                body+=f'<div class="readiness-row"><div class="row-main"><strong>{app.e(title)}</strong><small>{app.e(reason)}</small></div>{app.button("Review",url,"secondary small")}</div>'
        else:body+='<div class="empty">No marketing exceptions are open right now. Create a campaign or sync connected channels to generate evidence-based recommendations.</div>'
        body+='</div><div class="card"><div class="eyebrow">Can the channels execute?</div><h2>Channel readiness</h2>'
        for r in data['readiness']:
            body+=f'<div class="readiness-row"><div class="row-main"><strong>{app.e(r["channel"])}</strong><small>{app.e(r.get("reason") or "")}</small></div>{_pill(app,r["status"])} {_readiness_action(app,r)}</div>'
        body+='</div></div>'
        body+='<div class="section-head"><div><div class="eyebrow">Upcoming work</div><h2>Campaign calendar</h2></div>'+app.button('Open calendar','/marketing-calendar','secondary')+'</div><div class="campaign-grid">'
        for c in data['upcoming'][:6]:
            when=(c.get('start_date') or 'Not scheduled') + ((' → '+c['end_date']) if c.get('end_date') else '')
            origin='Imported plan' if 'Imported from the earlier campaign studio' in str(c.get('owner_note') or '') else 'CRM plan'
            meta=origin+' · '+str(c.get('created_at') or '')[:10]+' · '+str(c.get('id') or '')[-6:]
            body+=f'<div class="card campaign-plan-card"><span class="pill">{app.e(c.get("status") or "Draft")}</span><h3>{app.e(c["name"])}</h3><p class="helper">{app.e(when)}</p><p class="tiny muted">{app.e(meta)}</p>{app.button("Open", "/campaign-builder/"+c["id"],"secondary")}</div>'
        if not data['upcoming']:body+='<div class="card empty">No campaign plans yet. Start with a product and business goal.</div>'
        body+='</div>'
        self.send_html(app.layout('Marketing',body,'marketing'))

    def v27_campaign_builder(self,q):
        import app
        vm.initialise()
        goal=(q.get('goal') or ['sales'])[0];defaults=ox.campaign_defaults(goal)
        products=m.rows("SELECT product_id,public_product_name,internal_sku,product_code,status,retail_price,currency,duplicate_group FROM products WHERE coalesce(status,'Draft')<>'Archived' ORDER BY public_product_name,internal_sku LIMIT 300")
        selected=(q.get('product') or q.get('product_id') or [''])[0]
        journey=(q.get('journey') or [''])[0]
        goals=[(k,v['label']) for k,v in ox.GOAL_PRESETS.items()]
        dup_counts={}
        for p in products:
            g=p.get('duplicate_group')
            if g: dup_counts[g]=dup_counts.get(g,0)+1
        actions=app.button('Marketing home','/marketing','secondary')+app.button('Calendar','/marketing-calendar','secondary')
        body=app.pagehead('Create a campaign','Choose the outcome, products and timing. The system handles channel structure and keeps unavailable channels out of the way until they are connected.',actions)
        body+='<div class="campaign-steps"><span class="step active">1 Outcome</span><span class="step">2 Products</span><span class="step">3 Audience</span><span class="step">4 Channels</span></div>'
        body+='<div class="card section"><form method="get" action="/campaign-builder">'+app.field('What do you want to achieve?','<select name="goal" onchange="this.form.submit()">'+app.options(goals,defaults['goal_key'])+'</select>','Choose the business result rather than an advertising-platform objective.')+'</form></div>'
        body+='<form class="card section" method="post" action="/campaign-builder/create-business"><input type="hidden" name="idempotency_key" value="'+app.e(m.uid('REQ50'))+'"><input type="hidden" name="goal_key" value="'+app.e(defaults['goal_key'])+'"><input type="hidden" name="objective" value="'+app.e(defaults['objective'])+'">'
        body+='<div class="section-head"><div><div class="eyebrow">1 · Outcome</div><h2>What should customers do?</h2></div></div><div class="formgrid">'
        body+=app.field('Campaign name','<input name="name" placeholder="'+app.e(defaults['goal'])+' · '+app.e(defaults['region'])+'" required>')
        body+=app.field('Customer action','<select name="cta_goal">'+app.options([(k,v[0]) for k,v in vm.CTA_GOALS.items()],'view_collection')+'</select>','Use business language. Technical conversion events stay behind the scenes.')
        body+=app.field('Location','<input name="region" value="'+app.e(defaults['region'])+'">')+app.field('Language','<input name="language" value="'+app.e(defaults['language'])+'">')+'</div>'
        body+='<div class="formgrid">'+app.field('Start date (optional)','<input type="date" name="start_date">')+app.field('End date (optional)','<input type="date" name="end_date">')+app.field('Total budget (optional)','<input type="number" name="budget" min="0" step="0.01" placeholder="500">')+app.field('Currency','<select name="currency">'+app.options(['GBP','EUR','USD','INR'],defaults.get('currency','GBP'))+'</select>','Suggested from the campaign location; you can change it.')+'</div>'
        body+='<div class="note info"><strong>Recommended approach:</strong> '+app.e(defaults['objective'])+'</div>'
        body+='<div class="section-head"><div><div class="eyebrow">2 · Products</div><h2>What are you promoting?</h2><p class="helper">Choose reviewed products where possible. Drafts can be planned, but missing stock or price will block live commerce actions later.</p></div></div><div class="product-pick-grid">'
        for p in products:
            checked='checked' if str(p['product_id'])==str(selected) else ''
            has_inventory=bool(m.one('SELECT 1 ok FROM v9_inventory WHERE product_id=? LIMIT 1',(p['product_id'],))) if m.table_exists('v9_inventory') else False
            available=truth.product_available(p['product_id']) if has_inventory else None
            stock='Available '+str(available) if available is not None else 'Inventory not set'
            code=p.get('product_code') or p.get('internal_sku') or p['product_id']
            price=(str(p.get('retail_price'))+' '+str(p.get('currency') or '')) if p.get('retail_price') not in (None,'') else 'Price not set'
            dup=' · Possible duplicate' if p.get('duplicate_group') and dup_counts.get(p.get('duplicate_group'),0)>1 else ''
            readiness='ready' if (available is not None and available>0 and p.get('retail_price') not in (None,'') and str(p.get('status') or '').lower()=='active') else 'review'
            badge='Ready to promote' if readiness=='ready' else 'Needs product review'
            body+=f'<label class="product-pick {readiness}"><input type="checkbox" name="product_ids" value="{app.e(p["product_id"])}" {checked}><span><strong>{app.e(p["public_product_name"] or code)}</strong><small>{app.e(code)} · {app.e(p.get("status") or "Draft")}{app.e(dup)}</small><small>{app.e(stock)} · {app.e(price)}</small><em>{app.e(badge)}</em></span></label>'
        if not products:body+='<div class="note warn">Add or upload a product first. Marketing should be grounded in the real catalogue.</div>'
        body+='</div>'
        audience=defaults['audience']
        if journey=='winback':audience='Previous customers who have not purchased recently'
        body+='<div class="section-head"><div><div class="eyebrow">3 · Audience</div><h2>Who should this reach?</h2></div>'+app.button('Preview audience','/audience-builder?q='+urllib.parse.quote(audience),'secondary small')+'</div>'
        body+=app.field('Audience in plain language','<textarea name="audience_query">'+app.e(audience)+'</textarea>','The system uses recorded CRM/order facts only. It does not infer sensitive traits.')
        ready=[ch for ch in defaults['channels'] if ch['ready']]
        blocked=[ch for ch in defaults['channels'] if not ch['ready']]
        body+='<div class="section-head"><div><div class="eyebrow">4 · Channels</div><h2>Where should it run?</h2><p class="helper">Only channels that are actually usable are shown as primary choices.</p></div></div><div class="check-grid">'
        for ch in ready:
            checked='checked' if ch['selected'] else ''
            body+=f'<label class="checkline channel-ready"><input type="checkbox" name="channels" value="{app.e(ch["channel"])}" {checked}><span><strong>{app.e(ch["channel"])}</strong><small>{app.e(ch["status"])}</small></span></label>'
        if not ready: body+='<div class="note warn">No live marketing channel is connected yet. You can still prepare SEO/blog drafts, or connect an account before launch.</div>'
        body+='</div>'
        if blocked:
            body+='<details class="section channel-setup"><summary><strong>Plan channels that are not connected yet ('+str(len(blocked))+')</strong></summary><p class="helper">You may include an unconnected channel for planning. It will remain blocked from live execution until the account is verified.</p><div class="setup-channel-list">'
            for ch in blocked: body+=f'<label><span><input type="checkbox" name="channels" value="{app.e(ch["channel"])}"> {app.e(ch["channel"])}</span>{_pill(app,ch["status"])}</label>'
            body+='</div>'+app.button('Connect marketing accounts','/integrations','secondary')+'</details>'
        body+='<details class="section"><summary><strong>Advanced campaign details</strong></summary>'+app.field('Override objective','<textarea name="objective_override">'+app.e(defaults['objective'])+'</textarea>')+app.field('Owner note','<textarea name="owner_note" placeholder="Anything the team should remember when reviewing this campaign"></textarea>')+'</details><div class="form-foot"><button class="btn" type="submit">Create campaign plan</button></div></form>'
        campaigns=m.rows("SELECT id,name,status,start_date,end_date FROM v10_unified_campaigns WHERE coalesce(status,'Draft')<>'Archived' ORDER BY created_at DESC LIMIT 20")
        body+='<div class="section-head"><h2>Recent campaign plans</h2></div><div class="campaign-grid">'
        for c in campaigns:
            timing=c.get('start_date') or 'Not scheduled'
            body+=f'<div class="card"><span class="pill">{app.e(c["status"])}</span><h3>{app.e(c["name"])}</h3><p class="helper">{app.e(timing)}</p>{app.button("Open","/campaign-builder/"+c["id"],"secondary")}</div>'
        if not campaigns:body+='<div class="card empty"><h3>Your first campaign starts here</h3><p>Choose a business goal and at least one product above. The system will prepare the channel-specific plan for review.</p></div>'
        body+='</div>'
        self.send_html(app.layout('Create campaign',body,'campaign_builder'))

    def v27_channel_pack(self,cid,q):
        import app
        c=il.campaign(cid);packs=vm.channel_pack(cid)
        body=app.pagehead('Channel content pack',c['name']+' · Drafts are adapted by channel and remain review-only until the relevant provider path is approved.',app.button('Back to campaign','/campaign-builder/'+cid,'secondary')+app.button('AI image & video studio','/creative-studio','secondary'))
        if not packs:body+='<div class="card empty">This campaign has no selected channels.</div>'
        else:
            body+='<div class="campaign-grid">'
            for p in packs:
                body+=f'<div class="card"><span class="pill purple">{app.e(p["channel"])}</span><h3>Prepared draft</h3>'
                for k,v in p['fields'].items():body+=f'<div class="section"><strong>{app.e(k)}</strong><p class="helper">{app.e(v)}</p></div>'
                body+='</div>'
            body+='</div>'
        body+=app.notice('These are locally prepared, product-grounded drafts. They are not proof of publication, delivery, ad activation or customer consent.','info')
        self.send_html(app.layout('Channel content pack',body,'campaign_builder'))

    def v27_marketing_calendar(self,q):
        import app
        vm.initialise();rows=m.rows("SELECT * FROM v10_unified_campaigns WHERE coalesce(status,'Draft')<>'Archived' ORDER BY CASE WHEN start_date IS NULL OR start_date='' THEN 1 ELSE 0 END,start_date,created_at DESC LIMIT 200")
        social=m.rows("SELECT * FROM v17_social_posts ORDER BY scheduled_at LIMIT 100") if m.table_exists('v17_social_posts') else []
        body=app.pagehead('Marketing calendar','See campaign timing and scheduled social work in one place. Dates are planning metadata until a real provider confirms execution.',app.button('Create campaign','/campaign-builder')+app.button('Social planner','/operations/social','secondary'))
        if q.get('saved'):body+=app.notice('Campaign timing saved. No external platform was changed.','success')
        body+='<div class="section-head"><h2>Campaign plans</h2></div><div class="campaign-grid">'
        for c in rows:
            origin='Imported plan' if 'Imported from the earlier campaign studio' in str(c.get('owner_note') or '') else 'CRM plan'
            meta=origin+' · '+str(c.get('created_at') or '')[:10]+' · '+str(c.get('id') or '')[-6:]
            start_input='<input type="date" name="start_date" value="'+app.e(c.get('start_date') or '')+'">'
            end_input='<input type="date" name="end_date" value="'+app.e(c.get('end_date') or '')+'">'
            schedule_fields=app.field("Start date",start_input)+app.field("End date",end_input)
            body+=f'<div class="card campaign-plan-card"><span class="pill">{app.e(c["status"])}</span><h3>{app.e(c["name"])}</h3><p class="tiny muted">{app.e(meta)}</p><p class="helper">Start: {app.e(c.get("start_date") or "Not scheduled")}<br>End: {app.e(c.get("end_date") or "Not set")}</p><form method="post" action="/marketing-calendar/{app.e(c["id"])}/schedule"><input type="hidden" name="cta_goal" value="{app.e(c.get("cta_goal") or "view_collection")}"><div class="formgrid">{schedule_fields}</div><button class="btn secondary small">Save timing</button></form></div>'
        if not rows:body+='<div class="card empty guided-empty"><h3>No campaign dates yet</h3><p>Create a campaign plan first. Once you add dates, it will appear here automatically.</p>'+app.button('Create first campaign','/campaign-builder')+'</div>'
        body+='</div><div class="section-head"><h2>Scheduled social posts</h2></div><div class="card">'
        if social:
            for s in social[:30]:body+=f'<div class="readiness-row"><span class="pill">{app.e(s["channel"])}</span><div class="row-main"><strong>{app.e(s.get("scheduled_at") or "")}</strong><small>{app.e((s.get("caption") or "")[:140])}</small></div>{_pill(app,s.get("status") or "Scheduled")}</div>'
        else:body+='<div class="empty">No social posts are scheduled. Use Social planner after approving a creative asset.</div>'
        body+='</div>'
        self.send_html(app.layout('Marketing calendar',body,'marketing_calendar'))

    def v27_customer_journeys(self,q):
        import app
        rows=vm.journey_readiness()
        body=app.pagehead('Customer journeys','Use repeatable lifecycle journeys without building every follow-up from scratch. The OS still respects consent, provider readiness and human review.',app.button('Audience builder','/audience-builder','secondary')+app.button('Retention queue','/operations/retention','secondary'))
        body+='<div class="campaign-grid">'
        for j in rows:
            body+=f'<div class="card">{_pill(app,j["status"])}<h3>{app.e(j["title"])}</h3><p class="helper"><strong>Starts when:</strong> {app.e(j["trigger"])}</p><p>{app.e(j["outcome"])}</p><p class="tiny muted">Audience: {app.e(j["audience"])}</p>{app.button("Open next step",j["action"],"secondary")}</div>'
        body+='</div>'+app.notice('A journey marked planning-only does not send messages automatically. Live execution requires a connected provider, documented eligibility and approved content.','info')
        self.send_html(app.layout('Customer journeys',body,'journeys'))

    def v27_marketing_performance(self,q):
        import app
        days=int((q.get('days') or ['30'])[0] or 30);days=max(1,min(days,365));data=vm.overview(days);perf=data['performance']
        fin=v50.financial_summary((__import__('datetime').date.today()-__import__('datetime').timedelta(days=days)).isoformat(),__import__('datetime').date.today().isoformat())
        order_rows=[{'currency':r['currency'],'total':r['net_revenue']} for r in fin['currency_breakdown']]
        body=app.pagehead('Marketing results','See provider performance beside actual CRM and order outcomes. Provider conversions and real orders are deliberately shown separately.',app.button('Marketing home','/marketing','secondary')+app.button('Create campaign','/campaign-builder','secondary'))
        body+='<div class="toolbar section">'+''.join(app.button(str(x)+' days','/marketing-performance?days='+str(x),'secondary') for x in [30,90,365])+'</div>'
        body+=f'''<div class="stats-grid"><div class="card stat-card"><span class="stat-label">{data['crm_total']}</span><strong>CRM records</strong><span class="helper">Total records; imports are not treated as new leads</span></div><div class="card stat-card"><span class="stat-label">{data['orders']}</span><strong>Orders</strong><span class="helper">{app.e(_money_map([(r['currency'],r['total']) for r in order_rows]))}</span></div><div class="card stat-card"><span class="stat-label">{data['campaigns']}</span><strong>Campaign plans</strong><span class="helper">Current active workspaces</span></div><div class="card stat-card"><span class="stat-label">{len(perf['rows'])}</span><strong>Provider metric groups</strong><span class="helper">Synced evidence only</span></div></div>'''
        if not perf['rows']:
            body+='<div class="card empty"><h2>No advertising metrics are synced yet</h2><p>Connect Meta/Google and run a sync, or continue using CRM/order results while setup is incomplete.</p>'+app.button('Connect channels','/integrations')+' '+app.button('Create campaign','/campaign-builder','secondary')+'</div>'
        else:
            body+='<div class="card section"><h2>Channel performance</h2><div class="table-wrap"><table><tr><th>Channel</th><th>Currency</th><th>Spend</th><th>Provider revenue</th><th>ROAS</th><th>Impressions</th><th>Clicks</th><th>CTR</th><th>Conversions</th><th>CPA</th></tr>'
            for r in perf['rows']:
                body+=f'<tr><td>{app.e(r["channel"])}</td><td>{app.e(r["currency"])}</td><td>{r["spend"]:.2f}</td><td>{r["revenue"]:.2f}</td><td>{("%.2fx"%r["roas"]) if r["roas"] is not None else "—"}</td><td>{r["impressions"]}</td><td>{r["clicks"]}</td><td>{("%.2f%%"%r["ctr"]) if r["ctr"] is not None else "—"}</td><td>{r["conversions"]:.2f}</td><td>{("%.2f"%r["cpa"]) if r["cpa"] is not None else "—"}</td></tr>'
            body+='</table></div></div>'
        recs=data.get('recommendations') or []
        body+='<div class="card section"><div class="eyebrow">What should we do next?</div><h2>Actionable recommendations</h2>'
        if recs:
            for r in recs[:10]:
                title=r.get('title') or 'Review marketing signal';reason=r.get('reason') or '';url=r.get('action_url') or '/campaign-builder'
                body+=f'<div class="readiness-row"><div class="row-main"><strong>{app.e(title)}</strong><small>{app.e(reason)}</small></div>{app.button("Take action",url,"secondary small")}</div>'
        else:body+='<div class="empty">No evidence-based recommendation is available yet. More connected sales and campaign data will improve this view.</div>'
        body+='</div>'+app.notice('Provider-reported revenue is not treated as identical to CRM order revenue. Cross-channel attribution remains evidence-based and incomplete until provider/web/order identifiers match.','info')
        self.send_html(app.layout('Marketing results',body,'performance'))
