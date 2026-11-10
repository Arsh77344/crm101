from __future__ import annotations
import json,re,urllib.parse
import marketing as m
import integration_layer as il

class IntegrationPages:
    def v10_get(self,path,q):
        if path=='/setup':self.setup_wizard(q)
        elif path=='/integrations':self.integration_centre(q)
        elif re.fullmatch(r'/integrations/connect/[^/]+',path):self.connection_form(path.split('/')[-1],q)
        elif re.fullmatch(r'/integrations/[^/]+',path):self.connection_detail(path.split('/')[-1],q)
        elif re.fullmatch(r'/oauth/(google|meta)/start/[^/]+',path):return self.oauth_start(path.split('/')[2],path.split('/')[4])
        elif path in {'/oauth/google/callback','/oauth/meta/callback'}:return self.oauth_callback(path.split('/')[2],q)
        elif path=='/campaign-builder':self.campaign_builder(q)
        elif re.fullmatch(r'/campaign-builder/[^/]+',path):self.campaign_detail(path.split('/')[-1],q)
        elif path=='/audience-builder':self.audience_builder(q)
        elif path=='/marketing-performance':self.marketing_performance(q)
        elif path=='/integration-logs':self.integration_logs(q)
        else:return False
        return True

    def v10_post(self,path,f):
        v=lambda k,d='':f.get(k,[d])[0]
        if re.fullmatch(r'/integrations/save/[^/]+',path):
            key=path.split('/')[-1];cid=v('connection_id');config={};sec={}
            if key=='shopify':
                config={'store_domain':v('store_domain'),'api_version':v('api_version','2026-07')};sec={'access_token':v('access_token'),'app_secret':v('app_secret')}
            elif key=='resend':sec={'api_key':v('api_key')}
            elif key=='whatsapp_cloud':
                config={'phone_number_id':v('phone_number_id'),'waba_id':v('waba_id'),'graph_version':v('graph_version','v26.0'),'verify_token':v('verify_token')};sec={'access_token':v('access_token'),'app_secret':v('app_secret')}
            elif key=='meta_ads':
                config={'ad_account_id':v('ad_account_id'),'graph_version':v('graph_version','v26.0'),'app_id':v('app_id')};sec={'access_token':v('access_token'),'app_secret':v('app_secret')}
            elif key=='meta_social':
                config={'page_id':v('page_id'),'instagram_user_id':v('instagram_user_id'),'graph_version':v('graph_version','v26.0'),'app_id':v('app_id')};sec={'access_token':v('access_token'),'app_secret':v('app_secret')}
            elif key=='google_ads':
                config={'client_id':v('client_id'),'customer_id':v('customer_id'),'login_customer_id':v('login_customer_id')};sec={'client_secret':v('client_secret'),'refresh_token':v('refresh_token'),'developer_token':v('developer_token')}
            elif key=='google_business':
                config={'client_id':v('client_id'),'services':f.get('services',[]),'ga4_property_id':v('ga4_property_id'),'search_console_site':v('search_console_site'),'merchant_account_id':v('merchant_account_id'),'calendar_id':v('calendar_id','primary')};sec={'client_secret':v('client_secret'),'refresh_token':v('refresh_token')}
            elif key=='stripe':sec={'api_key':v('api_key')}
            else:raise ValueError('This connector is not configurable in this release.')
            new=il.upsert_connection(key,v('label'),config,sec,cid)
            # Do not fake success: only a provider call can set Connected.
            try:il.test_connection(new);return self.redirect('/integrations/'+new+'?connected=1')
            except ValueError:return self.redirect('/integrations/'+new+'?test_failed=1')
        if re.fullmatch(r'/integrations/[^/]+/test',path):
            cid=path.split('/')[2];il.test_connection(cid);return self.redirect('/integrations/'+cid+'?tested=1')
        if re.fullmatch(r'/integrations/[^/]+/sync',path):
            cid=path.split('/')[2];il.sync_connection(cid);return self.redirect('/integrations/'+cid+'?synced=1')
        if re.fullmatch(r'/integrations/[^/]+/disconnect',path):
            cid=path.split('/')[2];il.disconnect(cid);return self.redirect('/integrations?disconnected=1')
        if re.fullmatch(r'/integrations/[^/]+/shopify/publish',path):
            cid=path.split('/')[2];prod=il.publish_product_to_shopify(cid,v('product_id'));return self.redirect('/integrations/'+cid+'?published='+urllib.parse.quote(prod.get('id','')))
        if re.fullmatch(r'/integrations/[^/]+/shopify/webhooks/register',path):
            cid=path.split('/')[2];il.shopify_register_webhooks(cid);return self.redirect('/integrations/'+cid+'?shopify_webhooks=1')
        if re.fullmatch(r'/integrations/[^/]+/resend/domain',path):
            cid=path.split('/')[2];il.resend_create_domain(cid,v('domain'));return self.redirect('/integrations/'+cid+'?domain_created=1')
        if re.fullmatch(r'/integrations/[^/]+/resend/verify',path):
            cid=path.split('/')[2];il.resend_verify_domain(cid,v('domain_id'));return self.redirect('/integrations/'+cid+'?domain_verify=1')
        if re.fullmatch(r'/integrations/[^/]+/resend/test-email',path):
            cid=path.split('/')[2];il.resend_send_email(cid,v('from_email'),v('to_email'),v('subject'),'<p>'+self.escape_text(v('message'))+'</p>',v('message'),'test-'+cid+'-'+v('to_email'))
            return self.redirect('/integrations/'+cid+'?email_sent=1')
        if re.fullmatch(r'/integrations/[^/]+/resend/webhook/register',path):
            cid=path.split('/')[2];il.resend_register_webhook(cid);return self.redirect('/integrations/'+cid+'?webhook_registered=1')
        if re.fullmatch(r'/integrations/[^/]+/whatsapp/test-template',path):
            cid=path.split('/')[2];il.whatsapp_send_template(cid,v('to_phone'),v('template_name'),v('language','en_US'));return self.redirect('/integrations/'+cid+'?wa_sent=1')
        if re.fullmatch(r'/integrations/[^/]+/meta-social/select',path):
            cid=path.split('/')[2];il.select_meta_social_accounts(cid,v('page_id'),v('instagram_user_id'));return self.redirect('/integrations/'+cid+'?meta_selected=1')
        if re.fullmatch(r'/integrations/[^/]+/meta-social/facebook-publish',path):
            cid=path.split('/')[2]
            if v('confirm')!='PUBLISH':raise ValueError('Type PUBLISH to submit a real Facebook Page post.')
            il.publish_facebook_page_image(cid,v('image_url'),v('caption'));return self.redirect('/integrations/'+cid+'?facebook_published=1')
        if re.fullmatch(r'/integrations/[^/]+/meta-social/instagram-publish',path):
            cid=path.split('/')[2]
            if v('confirm')!='PUBLISH':raise ValueError('Type PUBLISH to submit a real Instagram image post.')
            il.publish_instagram_image(cid,v('image_url'),v('caption'));return self.redirect('/integrations/'+cid+'?instagram_published=1')
        if re.fullmatch(r'/campaign-builder/[^/]+/ai-plan',path):
            cid=path.split('/')[2];il.generate_ai_campaign_plan(cid);return self.redirect('/campaign-builder/'+cid+'?ai_plan=1')
        if re.fullmatch(r'/campaign-builder/[^/]+/email/send',path):
            cid=path.split('/')[2]
            if v('confirm')!='SEND':raise ValueError('Type SEND in the confirmation field before a real provider submission.')
            out=il.send_email_campaign(cid,v('from_email'),v('subject'),v('body_text'),int(v('max_recipients','50') or 50))
            return self.redirect('/campaign-builder/'+cid+'?email_submitted='+str(out['submitted'])+'&email_failed='+str(out['failed']))
        if re.fullmatch(r'/campaign-builder/[^/]+/whatsapp/send',path):
            cid=path.split('/')[2]
            if v('confirm')!='SEND':raise ValueError('Type SEND in the confirmation field before a real provider submission.')
            out=il.send_whatsapp_campaign(cid,v('template_name'),v('language','en_US'),int(v('max_recipients','50') or 50))
            return self.redirect('/campaign-builder/'+cid+'?wa_submitted='+str(out['submitted'])+'&wa_failed='+str(out['failed']))
        if re.fullmatch(r'/campaign-builder/[^/]+/paid/(meta|google)/create',path):
            cid=path.split('/')[2];provider=path.split('/')[4]
            import integration_v14 as v14
            channel='Meta Ads' if provider=='meta' else 'Google Ads'
            out=v14.create_reviewed_paid_campaign(cid,channel,v('daily_budget'),v('countries'),v('confirm'),v('eu_political_status','DOES_NOT_CONTAIN_EU_POLITICAL_ADVERTISING'))
            return self.redirect('/campaign-builder/'+cid+'?paid_created='+urllib.parse.quote(channel)+'&paid_id='+urllib.parse.quote(out['id']))
        if path=='/campaign-builder/create':
            raw={k:(x if len(x)>1 else x[0]) for k,x in f.items() if k!='_csrf'};raw['channels']=f.get('channels',[]);raw['product_ids']=f.get('product_ids',[])
            cid=il.create_unified_campaign(raw);return self.redirect('/campaign-builder/'+cid)
        return False

    def escape_text(self,text):
        import html
        return html.escape(text or '')

    def setup_wizard(self,q):
        import app
        steps=il.setup_status();done=sum(1 for x in steps if x['status']=='Complete')
        body=app.pagehead('Business setup','Connect once, then let products, customers, campaigns and performance sync into one workspace.','')
        body+=f'<div class="card section"><div class="message-top"><div><div class="eyebrow">Guided setup</div><h2>{done} of {len(steps)} steps complete</h2><p class="helper">This wizard only marks a connection complete after a real provider test or real local business data exists.</p></div><span class="pill {"good" if done==len(steps) else "purple"}">{round(done/len(steps)*100)}%</span></div><div style="height:10px;background:#eee;border-radius:999px;overflow:hidden"><div style="height:100%;width:{done/len(steps)*100:.1f}%;background:#6b4eff"></div></div></div>'
        for i,s in enumerate(steps,1):
            body+=f'''<div class="card section"><div class="message-top"><div><span class="pill {"good" if s["status"]=="Complete" else "warn"}">Step {i} · {app.e(s["status"])}</span><h3>{app.e(s["label"])}</h3><p class="helper">{app.e(s["detail"])}</p></div>{app.button('Open',s['url'],'secondary')}</div></div>'''
        self.send_html(app.layout('Business setup',body,'setup'))

    def integration_centre(self,q):
        import app
        il.initialise();existing=il.connections();bykey={}
        for c in existing:bykey.setdefault(c['connector_key'],[]).append(c)
        body=app.pagehead('Integration Centre','Only real, testable connections can become Connected. Planned integrations have no working Connect button.','')
        if q.get('disconnected'):body+=app.notice('Connection credentials removed.','success')
        categories=[]
        for meta in il.CONNECTOR_CATALOG.values():
            if meta['category'] not in categories:categories.append(meta['category'])
        for cat in categories:
            body+=f'<div class="section-head"><h2>{app.e(cat)}</h2></div><div class="campaign-grid">'
            for key,meta in il.CONNECTOR_CATALOG.items():
                if meta['category']!=cat:continue
                conns=bykey.get(key,[]);connected=[c for c in conns if c['status']=='Connected']
                state='Connected' if connected else ('Available to connect' if meta['implemented'] else 'Unsupported / planned')
                cls='good' if state=='Connected' else 'purple' if meta['implemented'] else 'warn'
                body+=f'<div class="card"><div class="message-top"><div><span class="pill {cls}">{app.e(state)}</span><h3>{app.e(meta["label"])}</h3><p class="helper">{app.e(meta["help"])}</p></div></div>'
                if connected:
                    for c in connected[:3]:body+=f'<div class="readiness-row"><div class="row-main"><strong>{app.e(c["account_name"] or c["label"])}</strong><small>Last sync: {app.e(c["last_sync_at"] or "Never")}</small></div>{app.button("Manage","/integrations/"+c["id"],"secondary small")}</div>'
                if meta['implemented']:body+=app.button('Connect another account','/integrations/connect/'+key,'secondary')
                else:body+='<span class="tiny muted">No connection workflow is exposed in this build.</span>'
                body+='</div>'
            body+='</div>'
        self.send_html(app.layout('Integration Centre',body,'integrations'))

    def connection_form(self,key,q):
        import app
        meta=il.CONNECTOR_CATALOG.get(key)
        if not meta or not meta.get('implemented'):raise ValueError('That integration is not implemented yet.')
        cid=q.get('id',[''])[0];c=il.connection(cid) if cid else None;cfg=(c or {}).get('config',{});hints=il.secret_hints(cid) if cid else {}
        body=app.pagehead('Connect '+meta['label'],meta['help'],app.button('Integration Centre','/integrations','secondary'))
        body+='<div class="card section"><form method="post" action="/integrations/save/'+app.e(key)+'">'+(f'<input type="hidden" name="connection_id" value="{app.e(cid)}">' if cid else '')
        body+=app.field('Connection label',f'<input name="label" value="{app.e((c or {}).get("label") or meta["label"])}">')
        if key=='shopify':
            body+=app.field('Permanent Shopify store domain',f'<input name="store_domain" value="{app.e(cfg.get("store_domain",""))}" placeholder="your-store.myshopify.com">','Use the permanent *.myshopify.com domain.')
            body+=app.field('Admin API version',f'<input name="api_version" value="{app.e(cfg.get("api_version","2026-07"))}">')
            body+=app.field('Admin API access token',f'<input type="password" name="access_token" autocomplete="new-password" placeholder="{app.e(hints.get("access_token","Paste token"))}">','Request only the scopes you need. Read sync needs products/customers/orders; publishing needs write_products.')
            body+=app.field('Shopify app/client secret (optional, for signed webhooks)',f'<input type="password" name="app_secret" autocomplete="new-password" placeholder="{app.e(hints.get("app_secret","Add before webhook registration"))}">','Needed only for cryptographic webhook validation after public deployment.')
        elif key=='resend':
            body+=app.field('Resend API key',f'<input type="password" name="api_key" autocomplete="new-password" placeholder="{app.e(hints.get("api_key","Paste API key"))}">','Stored encrypted on this Mac; never shown again.')
        elif key=='whatsapp_cloud':
            body+=app.field('Phone number ID',f'<input name="phone_number_id" value="{app.e(cfg.get("phone_number_id",""))}">')+app.field('WhatsApp Business Account ID',f'<input name="waba_id" value="{app.e(cfg.get("waba_id",""))}">')+app.field('Graph API version',f'<input name="graph_version" value="{app.e(cfg.get("graph_version","v26.0"))}">')
            body+=app.field('System-user access token',f'<input type="password" name="access_token" autocomplete="new-password" placeholder="{app.e(hints.get("access_token","Paste token"))}">','Requires WhatsApp Business messaging permissions.')
            body+=app.field('Meta App Secret (for signed webhook validation)',f'<input type="password" name="app_secret" placeholder="{app.e(hints.get("app_secret","Add before receiving replies/statuses"))}">')
            body+=app.field('Webhook verify token',f'<input name="verify_token" value="{app.e(cfg.get("verify_token",""))}" placeholder="Choose a private verification phrase">','Meta uses this once when validating your webhook URL.')
        elif key=='meta_ads':
            body+=app.field('Ad account ID',f'<input name="ad_account_id" value="{app.e(cfg.get("ad_account_id",""))}" placeholder="123456789">')+app.field('Graph / Marketing API version',f'<input name="graph_version" value="{app.e(cfg.get("graph_version","v26.0"))}">')
            body+=app.field('Meta App ID (optional for OAuth)',f'<input name="app_id" value="{app.e(cfg.get("app_id",""))}">')+app.field('Meta App Secret',f'<input type="password" name="app_secret" placeholder="{app.e(hints.get("app_secret","Optional for OAuth"))}">')
            body+=app.field('Access token',f'<input type="password" name="access_token" placeholder="{app.e(hints.get("access_token","Paste token, or use OAuth after saving"))}">','A token can connect directly. OAuth is available after app credentials are saved.')
        elif key=='google_ads':
            body+=app.field('OAuth client ID',f'<input name="client_id" value="{app.e(cfg.get("client_id",""))}">')+app.field('OAuth client secret',f'<input type="password" name="client_secret" placeholder="{app.e(hints.get("client_secret","Paste client secret"))}">')
            body+=app.field('Refresh token (optional if using Google login)',f'<input type="password" name="refresh_token" placeholder="{app.e(hints.get("refresh_token","Use OAuth or paste refresh token"))}">')+app.field('Developer token',f'<input type="password" name="developer_token" placeholder="{app.e(hints.get("developer_token","Paste developer token"))}">')
            body+=app.field('Google Ads customer ID',f'<input name="customer_id" value="{app.e(cfg.get("customer_id",""))}" placeholder="1234567890">')+app.field('Manager login customer ID (optional)',f'<input name="login_customer_id" value="{app.e(cfg.get("login_customer_id",""))}">')
        elif key=='google_business':
            selected=cfg.get('services') or []
            if isinstance(selected,str):selected=[x for x in selected.split(',') if x]
            body+=app.field('OAuth client ID',f'<input name="client_id" value="{app.e(cfg.get("client_id",""))}">')+app.field('OAuth client secret',f'<input type="password" name="client_secret" placeholder="{app.e(hints.get("client_secret","Paste client secret"))}">')
            body+=app.field('Refresh token (optional if using Google login)',f'<input type="password" name="refresh_token" placeholder="{app.e(hints.get("refresh_token","Use Google login after saving"))}">')
            choices=[('analytics','Google Analytics 4'),('search_console','Search Console'),('merchant','Merchant Center'),('gmail','Gmail mailbox (read-only sync)'),('calendar','Google Calendar (read-only sync)')]
            body+='<div class="field"><span>Google services</span><div class="checkgrid">'+''.join(f'<label class="check"><input type="checkbox" name="services" value="{app.e(k)}" {"checked" if k in selected else ""}><span>{app.e(label)}</span></label>' for k,label in choices)+'</div><small>Only selected scopes are requested. You can reconnect later to add another service.</small></div>'
            body+=app.field('GA4 property ID',f'<input name="ga4_property_id" value="{app.e(cfg.get("ga4_property_id",""))}" placeholder="123456789">')+app.field('Search Console property',f'<input name="search_console_site" value="{app.e(cfg.get("search_console_site",""))}" placeholder="sc-domain:example.com">')
            body+=app.field('Merchant Center account ID',f'<input name="merchant_account_id" value="{app.e(cfg.get("merchant_account_id",""))}">')+app.field('Calendar ID',f'<input name="calendar_id" value="{app.e(cfg.get("calendar_id","primary"))}">')
        elif key=='meta_social':
            body+=app.field('Meta App ID',f'<input name="app_id" value="{app.e(cfg.get("app_id",""))}">')+app.field('Meta App Secret',f'<input type="password" name="app_secret" placeholder="{app.e(hints.get("app_secret","Paste app secret"))}">')
            body+=app.field('Access token (optional if using Meta login)',f'<input type="password" name="access_token" placeholder="{app.e(hints.get("access_token","Use OAuth or paste token"))}">')+app.field('Graph API version',f'<input name="graph_version" value="{app.e(cfg.get("graph_version","v26.0"))}">')
            body+=app.field('Facebook Page ID (optional until selected)',f'<input name="page_id" value="{app.e(cfg.get("page_id",""))}">')+app.field('Instagram Professional account ID (optional until selected)',f'<input name="instagram_user_id" value="{app.e(cfg.get("instagram_user_id",""))}">')
        elif key=='stripe':
            body+=app.field('Stripe restricted/test secret key',f'<input type="password" name="api_key" autocomplete="new-password" placeholder="{app.e(hints.get("api_key","Paste restricted/test key"))}">','V11 reads account balance and recent PaymentIntents only. It does not create charges or refunds.')
        body+='<div class="form-foot"><button class="btn">Save & test connection</button></div></form></div>'
        body+=app.notice('Saving credentials does not mark the connection Connected. The backend immediately calls the provider; only a successful provider response changes the status.','info')
        self.send_html(app.layout('Connect '+meta['label'],body,'integrations'))

    def oauth_start(self,provider,cid):
        # Real server-side OAuth. User must configure this exact callback URI in the provider app.
        host=self.headers.get('Host','127.0.0.1:8765');redirect=f'http://{host}/oauth/{provider}/callback'
        url=il.begin_oauth(cid,provider,redirect);self.send_response(302);self.send_header('Location',url);self.end_headers()

    def oauth_callback(self,provider,q):
        import app
        if q.get('error'):return self.error_page('OAuth was not approved: '+q.get('error_description',q['error'])[0])
        state=q.get('state',[''])[0];code=q.get('code',[''])[0]
        if not state or not code:raise ValueError('OAuth callback is missing its state or code.')
        cid=il.complete_oauth(provider,state,code)
        try:il.test_connection(cid);return self.redirect('/integrations/'+cid+'?connected=1')
        except ValueError:return self.redirect('/integrations/'+cid+'?test_failed=1')

    def connection_detail(self,cid,q):
        import app
        c=il.connection(cid);meta=il.CONNECTOR_CATALOG[c['connector_key']];syncs=il.recent_syncs(cid,20);logs=il.connection_audit(cid,20);cfg=c['config']
        body=app.pagehead(c['label'],meta['label']+' · '+c['provider'],app.button('Edit setup','/integrations/connect/'+c['connector_key']+'?id='+cid,'secondary')+app.button('All integrations','/integrations','secondary'))
        for key,text in [('connected','Provider authorised the connection successfully.'),('tested','Connection test passed.'),('synced','Sync completed.'),('domain_created','Domain creation request sent to Resend.'),('domain_verify','Domain verification requested.'),('email_sent','Test email submitted to Resend.'),('webhook_registered','Signed Resend webhook registered for the configured public HTTPS URL.'),('shopify_webhooks','Signed Shopify webhooks registered for the configured public HTTPS URL.'),('wa_sent','WhatsApp template submitted.'),('published','Product draft created in Shopify.'),('meta_selected','Meta Page / Instagram account selection saved.'),('facebook_published','Facebook Page image post submitted.'),('instagram_published','Instagram image post submitted.')]:
            if q.get(key):body+=app.notice(text,'success')
        if q.get('test_failed'):body+=app.notice('Connection details were saved, but the provider test failed. Check the error below and correct the setup.','warn')
        body+=f'''<div class="stats-grid"><div class="card stat-card"><span class="stat-label">{app.e(c['status'])}</span><strong>Status</strong></div><div class="card stat-card"><span class="stat-label">{app.e(c['account_name'] or '—')}</span><strong>Connected account</strong></div><div class="card stat-card"><span class="stat-label">{app.e(c['last_sync_at'] or 'Never')}</span><strong>Last sync</strong></div><div class="card stat-card"><span class="stat-label">{len(c['capabilities'])}</span><strong>Implemented capabilities</strong></div></div>'''
        if c.get('last_error'):body+=app.notice(c['last_error'],'warn')
        body+='<div class="card section"><h2>Connection actions</h2><div class="toolbar"><form method="post" action="/integrations/'+cid+'/test"><button class="btn secondary">Test connection</button></form>'
        if any(str(cap).startswith('sync_') for cap in c['capabilities']):body+='<form method="post" action="/integrations/'+cid+'/sync"><button class="btn">Sync now</button></form>'
        if c['connector_key'] in {'google_ads','google_business'} and cfg.get('client_id'):body+=app.button('Sign in with Google','/oauth/google/start/'+cid,'secondary')
        if c['connector_key'] in {'meta_ads','meta_social'} and cfg.get('app_id'):body+=app.button('Sign in with Meta','/oauth/meta/start/'+cid,'secondary')
        body+='</div><p class="helper">Capabilities: '+app.e(', '.join(c['capabilities']))+'</p></div>'
        if c['connector_key']=='shopify':self.shopify_tools(cid,body_ref:=[])
        # helper returns html through list to avoid a giant branch above
        if c['connector_key']=='shopify':body+=''.join(body_ref)
        elif c['connector_key']=='resend':body+=self.resend_tools(cid)
        elif c['connector_key']=='whatsapp_cloud':body+=self.whatsapp_tools(cid)
        elif c['connector_key']=='meta_social':body+=self.meta_social_tools(cid)
        body+='<div class="two section"><div class="card"><h2>Recent syncs</h2>'
        if syncs:
            for x in syncs:body+=f'<div class="readiness-row"><div class="row-main"><strong>{app.e(x["sync_type"])}</strong><small>{app.e(x["status"])} · {app.e(x["started_at"])} · seen {x["records_seen"]}, created {x["records_created"]}, updated {x["records_updated"]}</small></div></div>'
        else:body+='<p class="helper">No sync has run yet.</p>'
        body+='</div><div class="card"><h2>Recent API activity</h2>'
        if logs:
            for x in logs:body+=f'<div class="readiness-row"><span class="pill {"good" if x["success"] else "warn"}">{app.e(x["status_code"] or "ERR")}</span><div class="row-main"><strong>{app.e(x["operation"])}</strong><small>{app.e(x["method"])} · {app.e(x["created_at"])} · {app.e(x["duration_ms"])} ms</small></div></div>'
        else:body+='<p class="helper">No provider API calls logged yet.</p>'
        body+='</div></div><div class="card section"><h2>Disconnect</h2><p class="helper">Removes saved credentials from the encrypted local vault. Synced CRM records remain.</p><form method="post" action="/integrations/'+cid+'/disconnect" data-confirm="Disconnect this account and delete its saved credentials?"><button class="btn secondary">Disconnect account</button></form></div>'
        self.send_html(app.layout('Integration',body,'integrations'))

    def meta_social_tools(self,cid):
        import app
        c=il.connection(cid);cfg=c['config'];pages=[];igs=[]
        for x in m.rows("SELECT object_type,external_id,payload_json FROM v10_external_objects WHERE connection_id=? AND object_type IN ('facebook_page','instagram_account') ORDER BY synced_at DESC",(cid,)):
            try:p=json.loads(x['payload_json'])
            except Exception:p={}
            if x['object_type']=='facebook_page':pages.append((x['external_id'],p.get('name') or x['external_id']))
            else:igs.append((x['external_id'],'@'+str(p.get('username') or x['external_id'])))
        html='<div class="two section"><div class="card"><h2>Select connected Meta accounts</h2><p class="helper">Run Sync now first. Only Page / Instagram accounts returned by the authorised Meta account can be selected.</p><form method="post" action="/integrations/'+cid+'/meta-social/select">'+app.field('Facebook Page','<select name="page_id">'+app.options(pages,cfg.get('page_id',''),'No Page selected')+'</select>')+app.field('Instagram Professional account','<select name="instagram_user_id">'+app.options(igs,cfg.get('instagram_user_id',''),'No Instagram selected')+'</select>')+'<button class="btn secondary">Save selection</button></form></div><div class="card"><h2>Publishing readiness</h2><p class="helper">Real organic publishing requires a public HTTPS media URL. Local <code>127.0.0.1</code> images cannot be fetched by Meta.</p><p><strong>Facebook Page:</strong> '+app.e(cfg.get('page_id') or 'Not selected')+'<br><strong>Instagram:</strong> '+app.e(cfg.get('instagram_user_id') or 'Not selected')+'</p></div></div>'
        if c['status']=='Connected':
            html+='<div class="two section"><div class="card"><h2>Publish Facebook Page image</h2><form method="post" action="/integrations/'+cid+'/meta-social/facebook-publish">'+app.field('Public HTTPS image URL','<input type="url" name="image_url" placeholder="https://cdn.example.com/creative.jpg" required>')+app.field('Caption','<textarea name="caption" rows="4"></textarea>')+app.field('Confirmation','<input name="confirm" placeholder="Type PUBLISH" required>')+'<button class="btn">Publish real Page post</button></form></div><div class="card"><h2>Publish Instagram image</h2><form method="post" action="/integrations/'+cid+'/meta-social/instagram-publish">'+app.field('Public HTTPS image URL','<input type="url" name="image_url" placeholder="https://cdn.example.com/creative.jpg" required>')+app.field('Caption','<textarea name="caption" rows="4"></textarea>')+app.field('Confirmation','<input name="confirm" placeholder="Type PUBLISH" required>')+'<button class="btn">Publish real Instagram post</button></form></div></div>'
        return html

    def shopify_tools(self,cid,out):
        import app
        products=m.rows("SELECT product_id,public_product_name,internal_sku,retail_price,status FROM products WHERE coalesce(status,'Draft')<>'Archived' ORDER BY created_at DESC LIMIT 100")
        html='<div class="card section"><h2>Shopify product draft</h2><p class="helper">Creates a real DRAFT product in Shopify. It does not publish it to the storefront. Requires write_products permission.</p><form method="post" action="/integrations/'+cid+'/shopify/publish">'+app.field('Product','<select name="product_id">'+app.options([(p['product_id'],(p['public_product_name'] or p['internal_sku'])+' · '+str(p['retail_price'] or 'price missing')) for p in products],empty='Choose product')+'</select>')+'<button class="btn secondary">Create Shopify draft</button></form></div>'
        base=il._public_base_url();secret=il.secret_hints(cid).get('app_secret')
        html+='<div class="card section"><h2>Real-time Shopify webhooks</h2><p class="helper">Orders, customers and product changes can trigger reconciliation without waiting for a manual sync.</p>'
        if base and secret:html+='<form method="post" action="/integrations/'+cid+'/shopify/webhooks/register" data-confirm="Register signed Shopify webhooks at the configured public HTTPS URL?"><button class="btn secondary">Register signed webhooks</button></form><p class="tiny muted">Endpoint: '+app.e(base.rstrip('/')+'/webhooks/shopify/'+cid)+'</p>'
        else:html+='<p class="helper">Requires configuration: a public HTTPS Base URL and the Shopify app/client secret. No registration button is shown until both exist.</p>'
        html+='</div>';out.append(html)

    def resend_tools(self,cid):
        import app
        domains=[x for x in m.rows("SELECT external_id,payload_json FROM v10_external_objects WHERE connection_id=? AND object_type='email_domain' ORDER BY synced_at DESC",(cid,))]
        wh=il.resend_webhook_status(cid)
        html='<div class="two section"><div class="card"><h2>Email domain</h2><form method="post" action="/integrations/'+cid+'/resend/domain">'+app.field('Domain','<input name="domain" placeholder="mail.yourbrand.com" required>')+'<button class="btn secondary">Create domain in Resend</button></form><div class="section">'
        for d in domains[:20]:
            try:p=json.loads(d['payload_json'])
            except:p={}
            html+=f'<div class="readiness-row"><div class="row-main"><strong>{app.e(p.get("name") or d["external_id"])}</strong><small>{app.e(p.get("status") or "Synced")}</small></div><form method="post" action="/integrations/{app.e(cid)}/resend/verify"><input type="hidden" name="domain_id" value="{app.e(d["external_id"])}"><button class="btn secondary small">Verify DNS</button></form></div>'
            records=p.get('records') or []
            if records:
                html+='<div class="table-wrap compact-table"><table><tr><th>Type</th><th>Name</th><th>Value / target</th><th>Status</th></tr>'
                for rr in records:
                    value=rr.get('value') or rr.get('content') or rr.get('target') or ''
                    html+=f'<tr><td>{app.e(rr.get("record") or rr.get("type") or "")}</td><td>{app.e(rr.get("name") or "")}</td><td><code>{app.e(value)}</code></td><td>{app.e(rr.get("status") or "")}</td></tr>'
                html+='</table></div>'
        html+='</div></div><div class="card"><h2>Send a test email</h2><p class="helper">This is a real send. Use your own address while testing.</p><form method="post" action="/integrations/'+cid+'/resend/test-email">'+app.field('From','<input type="email" name="from_email" required>')+app.field('To','<input type="email" name="to_email" required>')+app.field('Subject','<input name="subject" value="Commerce Business OS connection test" required>')+app.field('Message','<textarea name="message" required>This is a connection test from Commerce Business OS.</textarea>')+'<button class="btn">Send test email</button></form></div></div>'
        html+='<div class="card section"><div class="message-top"><div><div class="eyebrow">Delivery events</div><h2>Signed provider webhook</h2><p class="helper">Delivery, bounce, complaint, click and unsubscribe events can update campaign history and suppression automatically only after the CRM has a public HTTPS URL.</p></div><span class="pill '+('good' if wh['registered'] else 'warn')+'">'+('Registered' if wh['registered'] else 'Not registered')+'</span></div>'
        if wh['registered']:
            try:wp=json.loads(wh['external']['payload_json']) if wh['external'] else {}
            except:wp={}
            html+='<p class="helper">Endpoint: <code>'+app.e(wp.get('endpoint') or '')+'</code></p><p class="helper">The signing secret is encrypted and is never rendered in the browser.</p>'
        elif wh['public_base_url']:
            html+='<form method="post" action="/integrations/'+cid+'/resend/webhook/register" data-confirm="Register a real signed Resend webhook at your configured public HTTPS URL?"><button class="btn secondary">Register delivery webhook</button></form>'
        else:
            html+='<p class="helper">Requires configuration: add a real public HTTPS Base URL in Settings after deployment. Localhost cannot receive provider callbacks, so no Register button is shown yet.</p>'
        html+='</div>'
        return html

    def whatsapp_tools(self,cid):
        import app
        templates=m.rows("SELECT external_id,payload_json FROM v10_external_objects WHERE connection_id=? AND object_type='whatsapp_template' ORDER BY synced_at DESC LIMIT 100",(cid,))
        opts=[]
        for x in templates:
            try:p=json.loads(x['payload_json']);opts.append((p.get('name') or x['external_id'],(p.get('name') or x['external_id'])+' · '+(p.get('status') or '')))
            except:pass
        html='<div class="card section"><h2>Send approved WhatsApp template</h2><p class="helper">Real message submission. Use only a recipient with valid WhatsApp marketing/service eligibility and an approved template.</p><form method="post" action="/integrations/'+cid+'/whatsapp/test-template">'+app.field('Recipient number','<input name="to_phone" placeholder="447..." required>')+app.field('Approved template','<select name="template_name">'+app.options(opts,empty='Sync templates first')+'</select>')+app.field('Language code','<input name="language" value="en_US">')+'<button class="btn">Send template</button></form></div>'
        c=il.connection(cid);base=il._public_base_url();h=il.secret_hints(cid)
        html+='<div class="card section"><h2>Replies & delivery-status webhook</h2><p class="helper">When deployed publicly, signed WhatsApp callbacks can attach replies and delivery/read statuses to CRM contacts.</p>'
        if base and c['config'].get('verify_token') and h.get('app_secret'):
            html+='<p class="helper">Callback URL: <code>'+app.e(base.rstrip('/')+'/webhooks/meta/'+cid)+'</code></p><p class="helper">Use the private verification token you configured for this connection. The App Secret is encrypted and is never shown here.</p>'
        else:html+='<p class="helper">Requires configuration: public HTTPS Base URL, webhook verify token and Meta App Secret. Until then the CRM cannot receive replies/statuses.</p>'
        html+='</div>';return html

    def audience_builder(self,q):
        import app
        query=q.get('q',[''])[0];preview=il.audience_preview_nl(query) if query else None
        body=app.pagehead('AI Audience Builder','Describe the audience in plain language. The parser uses recorded CRM and order facts only; it does not infer sensitive traits.','')
        body+='<div class="card section"><form method="get" action="/audience-builder">'+app.field('Audience description',f'<textarea name="q" placeholder="Customers in United Kingdom who bought before but have not purchased in 6 months">{app.e(query)}</textarea>')+'<button class="btn">Preview audience</button></form></div>'
        if preview:
            body+=f'<div class="card section"><span class="pill purple">{preview["count"]:,} matches</span><h2>Recognised rules</h2><p class="helper">{app.e(", ".join(preview["recognized"]) or "No structured rule recognised; preview remains broad.")}</p></div><div class="card section"><h2>Sample contacts</h2><div class="table-wrap"><table><tr><th>Name</th><th>Type</th><th>Country</th><th>Stage</th></tr>'
            for c in preview['contacts'][:100]:body+=f'<tr><td>{app.e(c["full_name"] or c["username"])}</td><td>{app.e(c["contact_type"])}</td><td>{app.e(c["country"])}</td><td>{app.e(c["lifecycle_stage"])}</td></tr>'
            body+='</table></div></div>'
        self.send_html(app.layout('Audience Builder',body,'audiences'))

    def campaign_builder(self,q):
        import app
        products=m.rows("SELECT product_id,public_product_name,internal_sku,status FROM products WHERE coalesce(status,'Draft')<>'Archived' ORDER BY public_product_name")
        body=app.pagehead('Unified AI Campaign Builder','Start with one business objective. The workspace adapts it across selected channels and shows real connection readiness before launch.','')
        body+='<div class="card section"><form method="post" action="/campaign-builder/create"><input type="hidden" name="idempotency_key" value="'+app.e(m.uid('REQ50'))+'">'+app.field('Campaign name','<input name="name" placeholder="Autumn Banarasi launch" required>')+app.field('Objective','<textarea name="objective" placeholder="Promote the new Banarasi collection and drive qualified enquiries / purchases" required></textarea>')+app.field('Audience in plain language','<textarea name="audience_query" placeholder="B2B boutiques in United Kingdom"></textarea>')+'<div class="formgrid">'+app.field('Region','<input name="region" placeholder="United Kingdom">')+app.field('Language','<input name="language" value="English">')+app.field('Budget (optional)','<input type="number" step="0.01" min="0" name="budget">')+app.field('Currency','<select name="currency">'+app.options(['INR','GBP','USD','EUR'],m.settings().get('default_currency','INR'))+'</select>')+'</div><h3 class="section">Products</h3><div class="check-grid">'
        for p in products[:200]:body+=f'<label class="checkline"><input type="checkbox" name="product_ids" value="{app.e(p["product_id"])}">{app.e(p["public_product_name"] or p["internal_sku"])} <span class="tiny muted">{app.e(p["status"])}</span></label>'
        body+='</div><h3 class="section">Channels</h3><div class="check-grid">'
        connect_urls={'Email':'/integrations','WhatsApp':'/integrations/v14/connect/whatsapp_cloud','Meta Ads':'/integrations/v14/connect/meta_business','Google Ads':'/integrations/v14/connect/google_account','Website':'/integrations/v14/connect/shopify','Instagram/Facebook':'/integrations/v14/connect/meta_business','Pinterest':'/integrations'}
        for ch in ['Email','WhatsApp','Meta Ads','Google Ads','Website','Instagram/Facebook','Pinterest','SEO/Blog']:
            r=il.channel_readiness(ch);kind='good' if r['status'] in {'Connected','Ready'} else 'warn';link=''
            if r['status'] not in {'Connected','Ready'} and ch in connect_urls:link=f' <a class="tiny" href="{app.e(connect_urls[ch])}">Connect / setup</a>'
            body+=f'<div class="checkline"><label><input type="checkbox" name="channels" value="{app.e(ch)}"> {app.e(ch)}</label> <span class="pill {kind}">{app.e(r["status"])}</span>{link}</div>'
        body+='</div><div class="form-foot"><button class="btn">Create campaign workspace</button></div></form></div>'
        campaigns=m.rows('SELECT * FROM v10_unified_campaigns ORDER BY created_at DESC LIMIT 50')
        body+='<div class="section-head"><h2>Campaign workspaces</h2></div><div class="campaign-grid">'
        for c in campaigns:body+=f'<div class="card"><span class="pill">{app.e(c["status"])}</span><h3>{app.e(c["name"])}</h3><p class="helper">{app.e(c["objective"])}</p>{app.button("Open","/campaign-builder/"+c["id"],"secondary")}</div>'
        if not campaigns:body+='<div class="card empty">No unified campaigns yet.</div>'
        body+='</div>';self.send_html(app.layout('Campaign Builder',body,'campaign_builder'))

    def campaign_detail(self,cid,q):
        import app
        c=il.campaign(cid);preview=il.audience_preview_nl(c.get('audience_query',''));products=[]
        if c['product_ids']:
            placeholders=','.join('?'*len(c['product_ids']));products=m.rows('SELECT * FROM products WHERE product_id IN ('+placeholders+')',tuple(c['product_ids']))
        body=app.pagehead(c['name'],c['objective'],app.button('Marketing home','/marketing','secondary')+app.button('Channel content pack','/campaign-builder/'+cid+'/content','secondary')+app.button('Calendar','/marketing-calendar','secondary'))
        body+=f'<div class="stats-grid"><div class="card stat-card"><span class="stat-label">{preview["count"]:,}</span><strong>Audience matches</strong></div><div class="card stat-card"><span class="stat-label">{len(products)}</span><strong>Products</strong></div><div class="card stat-card"><span class="stat-label">{len(c["channels"])}</span><strong>Channels</strong></div><div class="card stat-card"><span class="stat-label">{app.e(c["status"])}</span><strong>Status</strong></div></div><div class="card section"><h2>Channel readiness</h2>'
        connect_urls={'Email':'/integrations','WhatsApp':'/integrations/v14/connect/whatsapp_cloud','Meta Ads':'/integrations/v14/connect/meta_business','Google Ads':'/integrations/v14/connect/google_account','Website':'/integrations/v14/connect/shopify','Instagram/Facebook':'/integrations/v14/connect/meta_business','Pinterest':'/integrations'}
        for row in c['channel_rows']:
            readiness=il.channel_readiness(row['channel']);kind='good' if readiness['status'] in {'Connected','Ready'} else 'warn';action=''
            if readiness['status'] not in {'Connected','Ready'} and row['channel'] in connect_urls:action=app.button('Connect / setup',connect_urls[row['channel']],'secondary small')
            body+=f'<div class="readiness-row"><span class="pill {kind}">{app.e(readiness["status"])}</span><div class="row-main"><strong>{app.e(row["channel"])}</strong><small>{app.e(readiness["reason"])}</small></div>{action}</div>'
        body+='</div><div class="two section"><div class="card"><h2>Audience interpretation</h2><p class="helper">'+app.e(c.get('audience_query') or 'No audience description')+'</p><p><strong>Recognised:</strong> '+app.e(', '.join(preview['recognized']) or 'No structured rules')+'</p>'+app.button('Refine in Audience Builder','/audience-builder?q='+urllib.parse.quote(c.get('audience_query') or ''),'secondary')+'</div><div class="card"><h2>Creative & copy</h2><p class="helper">Use the existing AI Campaign Studio and Creative Studio for reviewed copy and product-accurate images/video. Connected delivery actions appear below only for channels with a real backend.</p>'+app.button('Campaign Studio','/campaigns/new','secondary')+app.button('AI Creative Studio','/creative-studio/new','secondary')+'</div></div>'
        if q.get('ai_plan'):body+=app.notice('AI campaign strategy was generated from aggregate audience, product and synced-performance context. It did not launch or send anything.','success')
        plan=il.campaign_plan(cid)
        body+='<div class="card section"><div class="message-top"><div><div class="eyebrow">AI marketing intelligence</div><h2>Campaign strategy</h2><p class="helper">The AI receives aggregate audience counts, verified/safe product fields, selected channels and synced channel metrics — not recipient names, emails or phone numbers.</p></div>'
        if m.secret():body+='<form method="post" action="/campaign-builder/'+app.e(cid)+'/ai-plan"><button class="btn secondary">'+('Regenerate AI plan' if plan else 'Generate AI plan')+'</button></form>'
        else:body+=app.button('Connect AI','/settings','secondary')
        body+='</div>'
        if plan:
            body+='<h3>'+app.e(plan.get('summary',''))+'</h3><div class="two"><div><strong>Audience strategy</strong><p class="helper">'+app.e(plan.get('audience_strategy',''))+'</p></div><div><strong>Product strategy</strong><p class="helper">'+app.e(plan.get('product_strategy',''))+'</p></div></div>'
            recs=plan.get('channel_recommendations') or []
            if recs:
                body+='<h3>Channel recommendations</h3>'
                for x in recs:body+=f'<div class="readiness-row"><span class="pill purple">{app.e(x.get("priority",""))}</span><div class="row-main"><strong>{app.e(x.get("channel",""))}</strong><small>{app.e(x.get("role",""))} · {app.e(x.get("reason",""))}</small></div></div>'
            for title,key in [('Content angles','content_angles'),('Experiments','experiments'),('KPIs','kpis'),('Risks / constraints','risks'),('Next actions','next_actions')]:
                vals=plan.get(key) or []
                if vals:body+='<h3>'+title+'</h3><ul>'+''.join('<li>'+app.e(str(v))+'</li>' for v in vals)+'</ul>'
        else:body+='<p class="helper">No AI strategy generated yet. You can still use the campaign workspace manually.</p>'
        body+='</div>'
        if q.get('email_submitted'):body+=app.notice(f'Email provider accepted {app.e(q["email_submitted"][0])} submissions; {app.e(q.get("email_failed",["0"])[0])} failed. Submitted does not mean delivered.','success')
        if q.get('wa_submitted'):body+=app.notice(f'WhatsApp provider accepted {app.e(q["wa_submitted"][0])} submissions; {app.e(q.get("wa_failed",["0"])[0])} failed. Delivery status requires webhook/event sync.','success')
        if q.get('paid_created'):body+=app.notice(app.e(q['paid_created'][0])+' provider confirmed a PAUSED campaign. Nothing was activated and no ad spend was enabled.','success')
        if 'Email' in c['channels']:
            r=il.campaign_send_readiness(cid,'Email');body+=f'<div class="card section"><div class="message-top"><div><span class="pill {"good" if r["connection_status"]=="Connected" else "warn"}">{app.e(r["connection_status"])}</span><h2>Email execution</h2><p class="helper">{r["eligible_count"]} eligible · {r["blocked_count"]} blocked/review-required from the first {len(r["sample_eligible"])+len(r["sample_blocked"])} sampled records. The sender submits only documented eligible recipients and never converts Unknown permission into consent.</p></div></div>'
            if r['connection_status']=='Connected':
                sender=m.settings().get('business_email','');default_subject=c['name'];default_body='Hello {{first_name}},\n\n'+c['objective']+'\n\n{{brand}}'
                body+='<form method="post" action="/campaign-builder/'+app.e(cid)+'/email/send" data-confirm="This submits real email messages to eligible recipients through the connected provider. Continue?">'+app.field('Verified From address',f'<input type="email" name="from_email" value="{app.e(sender)}" required>')+app.field('Subject',f'<input name="subject" value="{app.e(default_subject)}" required>')+app.field('Reviewed message',f'<textarea name="body_text" required>{app.e(default_body)}</textarea>','Supported merge fields: {{first_name}}, {{full_name}}, {{company_name}}, {{brand}}, {{objective}}.')+'<div class="formgrid">'+app.field('Maximum recipients this run','<input type="number" name="max_recipients" value="25" min="1" max="100">')+app.field('Type SEND to confirm','<input name="confirm" autocomplete="off" required>')+'</div><button class="btn">Submit eligible email batch</button></form>'
            else:body+='<p class="helper">Connect and test the email provider before a send control is shown.</p>'
            body+='</div>'
        if 'WhatsApp' in c['channels']:
            r=il.campaign_send_readiness(cid,'WhatsApp');body+=f'<div class="card section"><div class="message-top"><div><span class="pill {"good" if r["connection_status"]=="Connected" else "warn"}">{app.e(r["connection_status"])}</span><h2>WhatsApp execution</h2><p class="helper">{r["eligible_count"]} eligible · {r["blocked_count"]} blocked/review-required. WhatsApp requires the existing explicit opt-in/evidence gate.</p></div></div>'
            if r['connection_status']=='Connected':
                conid=r['connection']['id'];rows=m.rows("SELECT payload_json FROM v10_external_objects WHERE connection_id=? AND object_type='whatsapp_template' ORDER BY synced_at DESC",(conid,));opts=[]
                for x in rows:
                    try:
                        pp=json.loads(x['payload_json']);
                        if str(pp.get('status','')).upper()=='APPROVED':opts.append((pp.get('name',''),(pp.get('name','')+' · '+pp.get('language',''))))
                    except Exception:pass
                if opts:
                    body+='<form method="post" action="/campaign-builder/'+app.e(cid)+'/whatsapp/send" data-confirm="This submits real WhatsApp template messages to eligible opted-in recipients. Continue?">'+app.field('Approved parameter-free template','<select name="template_name">'+app.options(opts)+'</select>')+app.field('Language code','<input name="language" value="en_US">')+'<div class="formgrid">'+app.field('Maximum recipients this run','<input type="number" name="max_recipients" value="25" min="1" max="100">')+app.field('Type SEND to confirm','<input name="confirm" autocomplete="off" required>')+'</div><button class="btn">Submit eligible WhatsApp batch</button></form>'
                else:body+='<p class="helper">No approved templates are synced. Open the WhatsApp connection and run Sync now first.</p>'
            else:body+='<p class="helper">Connect and test WhatsApp before a send control is shown.</p>'
            body+='</div>'
        if any(ch in c['channels'] for ch in ['Meta Ads','Google Ads']):
            import integration_v14 as v14
            body+='<div class="section-head"><h2>Reviewed paid-media creation</h2><p class="helper">These controls create real provider objects only in PAUSED state. They do not create a live ad, activate delivery or spend budget.</p></div>'
            for channel,slug in [('Meta Ads','meta'),('Google Ads','google')]:
                if channel not in c['channels']:continue
                r=v14.paid_write_readiness(channel);kind='good' if r.get('status')=='Ready' else 'warn'
                body+=f'<div class="card section"><div class="message-top"><div><span class="pill {kind}">{app.e(r.get("status",""))}</span><h2>{app.e(channel)} · create PAUSED</h2><p class="helper">{app.e(r.get("reason",""))}</p></div></div>'
                if r.get('status')=='Ready':
                    political=''
                    if channel=='Google Ads':
                        political=app.field('EU political advertising declaration','<select name="eu_political_status" required><option value="">Choose declaration</option><option value="DOES_NOT_CONTAIN_EU_POLITICAL_ADVERTISING">Does not contain EU political advertising</option><option value="CONTAINS_EU_POLITICAL_ADVERTISING">Contains EU political advertising</option></select>','Google Ads requires this declaration. The CRM does not infer it.')
                    body+='<form method="post" action="/campaign-builder/'+app.e(cid)+'/paid/'+slug+'/create" data-confirm="This creates a real provider campaign in PAUSED state. Continue?">'+app.field('Daily budget',f'<input type="number" step="0.01" min="0.01" name="daily_budget" required>','Currency: '+app.e(c.get('currency') or m.settings().get('default_currency','GBP'))+'. No spend can occur while the provider campaign remains PAUSED.')+app.field('Country codes','<input name="countries" placeholder="GB" required>','ISO two-letter codes separated by commas, for example GB, FR. Meta applies these to the PAUSED ad set; Google records them for a later reviewed location-criterion step.')+political+app.field('Type PAUSED to confirm','<input name="confirm" autocomplete="off" required>')+'<button class="btn">Create provider PAUSED campaign</button></form>'
                body+='</div>'
            rows=v14.paid_campaigns(cid)
            if rows:
                body+='<div class="card section"><h2>Provider campaign history</h2><div class="table-wrap"><table><tr><th>When</th><th>Provider</th><th>Status</th><th>Daily budget</th><th>Provider campaign</th><th>Targeting</th></tr>'
                for x in rows:body+=f'<tr><td>{app.e(x["created_at"])}</td><td>{app.e(x["provider"])}</td><td>{app.e(x["provider_status"])}</td><td>{app.e(x["currency"])} {float(x["daily_budget"]):.2f}</td><td>{app.e(x["provider_campaign_id"] or "—")}</td><td>{app.e(x["targeting_status"])}</td></tr>'
                body+='</table></div></div>'
        sends=il.campaign_sends(cid,100)
        if sends:
            body+='<div class="card section"><h2>Real submission history</h2><div class="table-wrap"><table><tr><th>When</th><th>Channel</th><th>Contact</th><th>Status</th><th>Provider ID</th></tr>'
            for x in sends:body+=f'<tr><td>{app.e(x["created_at"])}</td><td>{app.e(x["channel"])}</td><td>{app.e(x["contact_name"] or x["endpoint"])}</td><td>{app.e(x["status"])}</td><td>{app.e(x["provider_message_id"] or "—")}</td></tr>'
            body+='</table></div></div>'
        self.send_html(app.layout('Unified campaign',body,'campaign_builder'))

    def marketing_performance(self,q):
        import app
        days=int(q.get('days',['30'])[0] or 30);days=min(365,max(1,days));data=il.performance_summary(days)
        body=app.pagehead('Marketing Performance Centre','Synced provider metrics only. No inferred spend or conversion values.','')
        body+='<div class="toolbar section">'+app.button('30 days','/marketing-performance?days=30','secondary')+app.button('90 days','/marketing-performance?days=90','secondary')+app.button('365 days','/marketing-performance?days=365','secondary')+'</div>'
        if not data['rows']:body+='<div class="card empty">No connected advertising metrics yet. Connect and sync Meta Ads or Google Ads.</div>'
        else:
            body+='<div class="card section"><div class="table-wrap"><table><tr><th>Channel</th><th>Currency</th><th>Spend</th><th>Revenue</th><th>ROAS</th><th>Impressions</th><th>Clicks</th><th>CTR</th><th>Conversions</th><th>CPA</th></tr>'
            for r in data['rows']:
                body+=f'<tr><td>{app.e(r["channel"])}</td><td>{app.e(r["currency"])}</td><td>{r["spend"]:.2f}</td><td>{r["revenue"]:.2f}</td><td>{("%.2fx"%r["roas"]) if r["roas"] is not None else "—"}</td><td>{r["impressions"]}</td><td>{r["clicks"]}</td><td>{("%.2f%%"%r["ctr"]) if r["ctr"] is not None else "—"}</td><td>{r["conversions"]:.2f}</td><td>{("%.2f"%r["cpa"]) if r["cpa"] is not None else "—"}</td></tr>'
            body+='</table></div></div>'
        if data.get('recommendations'):
            body+='<div class="card section"><div class="eyebrow">Decision support</div><h2>Performance signals</h2><p class="helper">Rule-based observations from synced provider metrics. These are not forecasts and do not change budgets automatically.</p>'
            for r in data['recommendations']:
                body+=f'<div class="readiness-row"><span class="pill {"warn" if r["severity"]=="Review" else "good"}">{app.e(r["severity"])}</span><div class="row-main"><strong>{app.e(r["channel"])}</strong><small>{app.e(r["message"])}</small></div></div>'
            body+='</div>'
        body+=app.notice('Revenue depends on what each advertising provider reports. Cross-channel attribution remains separate from provider-reported conversions and should be reconciled with actual orders.','info')
        self.send_html(app.layout('Marketing Performance',body,'performance'))

    def integration_logs(self,q):
        import app
        logs=m.rows('SELECT l.*,c.label FROM v10_api_logs l LEFT JOIN v10_connections c ON c.id=l.connection_id ORDER BY l.created_at DESC LIMIT 250');syncs=il.recent_syncs(limit=100)
        body=app.pagehead('Integration activity','Provider requests and synchronisation history. Secrets and Authorization headers are never rendered here.','')
        body+='<div class="two"><div class="card"><h2>API requests</h2>'
        for x in logs:body+=f'<div class="readiness-row"><span class="pill {"good" if x["success"] else "warn"}">{app.e(x["status_code"] or "ERR")}</span><div class="row-main"><strong>{app.e(x["label"] or "Integration")} · {app.e(x["operation"])}</strong><small>{app.e(x["method"])} · {app.e(x["created_at"])} · {app.e(x["duration_ms"])} ms</small></div></div>'
        if not logs:body+='<p class="helper">No API calls yet.</p>'
        body+='</div><div class="card"><h2>Sync runs</h2>'
        for x in syncs:body+=f'<div class="readiness-row"><span class="pill {"good" if x["status"]=="Completed" else "warn"}">{app.e(x["status"])}</span><div class="row-main"><strong>{app.e(x["sync_type"])}</strong><small>{app.e(x["started_at"])} · seen {x["records_seen"]}</small></div></div>'
        if not syncs:body+='<p class="helper">No syncs yet.</p>'
        body+='</div></div>';self.send_html(app.layout('Integration activity',body,'integrations'))
