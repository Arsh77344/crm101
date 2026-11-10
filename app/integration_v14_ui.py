from __future__ import annotations

import html
import json
import re
import urllib.parse

import marketing as m
import runtime_config as rc
import integration_layer as legacy
import integration_v14 as v14
import mcp_connectors as mcp
import connection_service as connection_service
import platform_core as pc
from release_info import RELEASE_LABEL


def esc(v):
    return html.escape('' if v is None else str(v), quote=True)


def _pill(status: str) -> str:
    s=(status or '').lower()
    if s in {'connected','complete','healthy','configured','fully working'}:kind='good'
    elif s in {'syncing','available to connect','optional','ready','ready to configure','partially implemented','requires setup'}:kind='purple'
    elif 'error' in s or 'reconnect' in s or 'blocked' in s or 'missing' in s:kind='warn'
    elif 'planning only' in s or 'planned' in s or 'not implemented' in s:kind='muted'
    else:kind='warn'
    return f'<span class="pill {kind}">{esc(status)}</span>'


class IntegrationV14Pages:
    """Login-first business integration UX for V14.

    Normal business users never receive provider client-secret / token forms. Those are
    isolated under /developer/integrations for Owner/Administrator setup only.
    """

    def _v14_base_url(self) -> str:
        configured=(rc.PUBLIC_BASE_URL or str(m.settings().get('public_base_url','') or '')).strip().rstrip('/')
        if configured:return configured
        host=(self.headers.get('Host') or '127.0.0.1:8765').strip()
        return 'http://'+host

    def _v14_admin_only(self):
        if not pc.auth_enabled():return
        role=(self.current_user or {}).get('role','')
        if role not in {'Owner','Administrator'}:
            raise ValueError('Advanced integration setup is available only to an Owner or Administrator.')

    def _v14_connection_for_key(self,key):
        rows=legacy.connections(key)
        return rows[0] if rows else None

    def _v14_connection_status_for_card(self,key,meta):
        if not meta.get('implemented'):
            return 'Unsupported / planned',None
        c=self._v14_connection_for_key(key)
        if c:
            return c.get('status') or 'Connection requires setup',c
        provider_key=meta.get('provider_key') or ''
        if meta.get('login_first') and provider_key:
            app=v14.provider_app(provider_key)
            if not app['configured']:
                return 'Connection requires setup',None
            if key=='whatsapp_cloud' and not app['config'].get('whatsapp_config_id'):
                return 'Connection requires setup',None
            return 'Available to connect',None
        if key in {'resend','stripe'}:
            return 'Connection requires setup',None
        return 'Available to connect',None

    def v14_get(self,path,q):
        if path=='/integrations':self.v14_integration_centre(q)
        elif path=='/setup':self.v14_setup(q)
        elif path=='/integration-health':self.v14_integration_health(q)
        elif path=='/developer/integrations':self.v14_developer_integrations(q)
        elif path=='/developer/integrations/mcp':self.v42_mcp_setup(q)
        elif re.fullmatch(r'/developer/integrations/(google|meta|shopify|wix|microsoft)',path):self.v14_developer_provider(path.split('/')[-1],q)
        elif re.fullmatch(r'/integrations/v14/connect/[^/]+',path):self.v14_connect_page(path.split('/')[-1],q)
        elif re.fullmatch(r'/integrations/v14/[^/]+',path):self.v14_connection_detail(path.split('/')[-1],q)
        elif re.fullmatch(r'/oauth/v14/(google|meta|shopify|wix|microsoft)/callback',path):return self.v14_oauth_callback(path.split('/')[3],q)
        elif path=='/data-ownership':self.v14_data_ownership(q)
        elif path=='/v14-e2e':return self.redirect('/v17-e2e')
        else:return False
        return True

    def v14_post(self,path,f):
        val=lambda k,d='':f.get(k,[d])[0]
        if re.fullmatch(r'/integrations/v14/connect/(shopify|wix|google_account|meta_business|microsoft_mailbox)',path):
            key=path.split('/')[-1]
            callback_provider={'shopify':'shopify','wix':'wix','google_account':'google','meta_business':'meta','microsoft_mailbox':'microsoft'}[key]
            options={'label':val('label'),'_initiated_user_id':(self.current_user or {}).get('user_id','')}
            if key=='shopify':options['store_domain']=val('store_domain')
            elif key=='google_account':options['services']=f.get('services',[])
            elif key=='meta_business':options['services']=f.get('services',[])
            elif key=='microsoft_mailbox':options['services']=f.get('services',[])
            redirect_uri=v14.provider_callback_urls(self._v14_base_url())[callback_provider]
            out=(v14.begin_wix_install(redirect_uri,options.get('label') or 'Wix',val('connection_id'),options.get('_initiated_user_id') or '') if key=='wix' else v14.begin_oauth(key,redirect_uri,options,val('connection_id')))
            return self.redirect(out['url'])
        if path=='/integrations/v14/whatsapp/embedded/complete':
            cid=v14.connect_whatsapp_embedded(val('code'),val('waba_id'),val('phone_number_id'),val('business_id'),val('label') or 'WhatsApp Business')
            return self.redirect('/integrations/v14/'+cid+'?connected=1')
        if re.fullmatch(r'/integrations/v14/[^/]+/test',path):
            cid=path.split('/')[3];v14.test_connection(cid);return self.redirect('/integrations/v14/'+cid+'?tested=1')
        if re.fullmatch(r'/integrations/v14/[^/]+/sync',path):
            cid=path.split('/')[3];v14.sync_connection(cid);return self.redirect('/integrations/v14/'+cid+'?synced=1')
        if re.fullmatch(r'/integrations/v14/[^/]+/product-draft',path):
            import connection_service as cs
            cid=path.split('/')[3]
            cs.execute(cid,'push_product_draft',{'product_id':val('product_id')},write=True)
            return self.redirect('/integrations/v14/'+cid+'?product_draft=1')
        if re.fullmatch(r'/integrations/v14/[^/]+/disconnect',path):
            cid=path.split('/')[3];out=v14.disconnect_connection(cid);msg='1' if out.get('provider_revoked') else 'local'
            return self.redirect('/integrations?disconnected='+msg)
        if re.fullmatch(r'/integrations/v14/[^/]+/resources',path):
            cid=path.split('/')[3];reqs=v14.account_selection_requirements(cid);selections={}
            for req in reqs:
                typ=req['resource_type'];raw=f.get('resource_'+typ,[])
                if len(raw)==1:selections[typ]=raw[0]
                elif raw:selections[typ]=raw
                else:selections[typ]=[]
                if req['required'] and not raw:raise ValueError('Choose a '+req['label']+'.')
            v14.select_resources(cid,selections);v14.test_connection(cid)
            return self.redirect('/integrations/v14/'+cid+'?resources_saved=1')
        if re.fullmatch(r'/integrations/v14/[^/]+/route',path):
            cid=path.split('/')[3];v14.set_connection_route(val('channel'),cid);return self.redirect('/integrations/v14/'+cid+'?route_saved=1')
        if path=='/integrations/v14/health/run':
            out=v14.run_health_checks(active=True)
            return self.redirect('/integration-health?checked='+str(out.get('checked',0))+'&attention='+str(out.get('attention',0)))
        if re.fullmatch(r'/developer/integrations/(google|meta|shopify|wix|microsoft)/save',path):
            self._v14_admin_only();provider=path.split('/')[-2]
            cfg={}
            extras={}
            if provider=='google':extras['developer_token']=val('developer_token')
            elif provider=='meta':
                cfg={'graph_version':val('graph_version','v26.0'),'login_config_id':val('login_config_id'),'whatsapp_config_id':val('whatsapp_config_id')}
            elif provider=='shopify':cfg={'scopes':val('scopes','read_products,write_products,read_customers,read_orders,read_inventory')}
            elif provider=='wix':cfg={'install_url':val('install_url')}
            elif provider=='microsoft':cfg={'tenant':val('tenant','common')}
            v14.configure_provider_app(provider,val('client_id'),val('client_secret'),cfg,extras)
            return self.redirect('/developer/integrations/'+provider+'?saved=1')
        if path=='/developer/integrations/mcp/register':
            self._v14_admin_only();mid=mcp.register(val('provider_key'),val('label'),val('endpoint'),val('auth_type','none'),[],[])
            return self.redirect('/developer/integrations/mcp?created='+urllib.parse.quote(mid))
        if re.fullmatch(r'/developer/integrations/mcp/[^/]+/test',path):
            self._v14_admin_only();mid=path.split('/')[-2];out=mcp.test(mid)
            return self.redirect('/developer/integrations/mcp?tested='+urllib.parse.quote(mid)+'&ok='+('1' if out.get('ok') else '0'))
        if re.fullmatch(r'/developer/integrations/mcp/[^/]+/disconnect',path):
            self._v14_admin_only();mid=path.split('/')[-2];mcp.disconnect(mid)
            return self.redirect('/developer/integrations/mcp?disconnected='+urllib.parse.quote(mid))
        if path=='/data-ownership/save':
            self._v14_admin_only();entity=val('entity_type');v14.update_data_authority(entity,val('authority'),val('conflict_policy'),val('explanation'),val('authority_connection_id'))
            return self.redirect('/data-ownership?saved=1')
        return False

    def v14_oauth_callback(self,provider,q):
        error=q.get('error',[''])[0]
        if error:
            detail=q.get('error_description',[error])[0]
            return self.redirect('/integrations?oauth_error='+urllib.parse.quote(v14.friendly_error(detail,provider)))
        if provider=='wix':
            signed=(q.get('signedInstance') or q.get('instance') or [''])[0]
            if not signed:raise ValueError('Wix did not return a signed app instance. Check the Wix post-install redirect and reconnect.')
            cid=v14.complete_wix_install(signed,(q.get('connection_id') or [''])[0],current_user_id=(self.current_user or {}).get('user_id',''))
            return self.redirect('/integrations/v14/'+cid+'?connected=1')
        state=q.get('state',[''])[0];code=q.get('code',[''])[0]
        if not state or not code:raise ValueError('The provider did not return a valid login response. Start Connect again.')
        raw=urllib.parse.urlparse(self.path).query
        cid=v14.complete_oauth(provider,state,code,raw,current_user_id=(self.current_user or {}).get('user_id',''))
        return self.redirect('/integrations/v14/'+cid+'?connected=1')

    def v14_integration_centre(self,q):
        import app
        v14.initialise();catalog=v14.business_catalog();existing=legacy.connections();bykey={}
        for c in existing:bykey.setdefault(c['connector_key'],[]).append(c)
        actions=app.button('Guided setup','/setup','secondary')+app.button('Connection health','/integration-health','secondary')
        if not pc.auth_enabled() or (self.current_user or {}).get('role') in {'Owner','Administrator'}:
            actions+=app.button('Advanced platform setup','/developer/integrations','secondary')
        body=app.pagehead('Connect business accounts','Sign in once. The platform stores provider tokens securely and keeps technical credentials out of the normal business workflow.',actions)
        if q.get('oauth_error'):body+=app.notice(q['oauth_error'][0],'warn')
        if q.get('disconnected'):
            txt='Connection removed locally.' if q['disconnected'][0]=='local' else 'Connection removed and the provider session was revoked where the provider supported it.'
            body+=app.notice(txt,'success')
        body+='''<div class="card section"><div class="message-top"><div><div class="eyebrow">Business-user connection model</div><h2>Connect → choose account → sync</h2><p class="helper">You should not need API keys, access tokens, client secrets or webhook URLs here. Those belong to platform administration, and only where a provider requires them.</p></div></div></div>'''
        categories=[]
        for meta in catalog.values():
            if meta['category'] not in categories:categories.append(meta['category'])
        for category in categories:
            body+=f'<div class="section"><div class="eyebrow">{esc(category)}</div><div class="cards">'
            for key,meta in catalog.items():
                if meta['category']!=category:continue
                status,c=self._v14_connection_status_for_card(key,meta)
                account=(c or {}).get('account_name') or ''
                last=(c or {}).get('last_sync_at') or (c or {}).get('last_success_at') or ''
                detail=meta.get('help','')
                body+='<div class="card"><div class="message-top"><div><h3>'+esc(meta['label'])+'</h3>'+_pill(status)+'</div></div>'
                if account:body+=f'<p><strong>{esc(account)}</strong></p>'
                body+=f'<p class="helper">{esc(detail)}</p>'
                if last:body+=f'<p class="tiny muted">Last successful activity: {esc(last)}</p>'
                if c:
                    body+=app.button('Manage','/integrations/v14/'+c['id'],'secondary')
                    if status in {'Reconnect required','Connection error','Permission required','Connection requires setup'} and meta.get('login_first'):
                        body+=app.button('Reconnect','/integrations/v14/connect/'+key+'?connection_id='+urllib.parse.quote(c['id']),'')
                elif not meta.get('implemented'):
                    body+=_pill('Planning only')
                elif meta.get('login_first'):
                    prov=v14.provider_app(meta['provider_key'])
                    if status=='Connection requires setup':
                        body+='<p class="tiny muted">The platform administrator must configure this provider once before business users can sign in.</p>'
                        if not pc.auth_enabled() or (self.current_user or {}).get('role') in {'Owner','Administrator'}:
                            body+=app.button('Platform setup','/developer/integrations/'+meta['provider_key'],'secondary')
                    else:body+=app.button('Connect','/integrations/v14/connect/'+key,'')
                else:
                    body+='<p class="tiny muted">This provider does not currently offer a suitable business-login flow for this implementation.</p>'
                    if not pc.auth_enabled() or (self.current_user or {}).get('role') in {'Owner','Administrator'}:
                        body+=app.button('Advanced setup','/developer/integrations','secondary')
                body+='</div>'
            body+='</div></div>'
        mcp_rows=mcp.list_connectors()
        body+='<div class="section"><div class="eyebrow">MCP CONNECTORS</div><div class="card"><div class="message-top"><div><h2>Managed connector layer</h2><p class="helper">MCP is an alternative transport behind the same business-connection model. A connector is shown as Connected only after its server responds and exposes real tools.</p></div>'
        if not pc.auth_enabled() or (self.current_user or {}).get('role') in {'Owner','Administrator'}:body+=app.button('Manage MCP connectors','/developer/integrations/mcp','secondary')
        body+='</div>'
        if mcp_rows:
            body+='<div class="table-wrap"><table><tr><th>Connector</th><th>Provider</th><th>Status</th><th>Capabilities</th><th>Last success</th></tr>'
            for mc in mcp_rows:
                body+=f'<tr><td>{esc(mc["label"])}</td><td>{esc(mc["provider_key"])}</td><td>{_pill(mc["status"])}</td><td>{esc(", ".join(mc.get("capabilities") or []) or "Not validated")}</td><td>{esc(mc.get("last_success_at") or "Never")}</td></tr>'
            body+='</table></div>'
        else:body+='<p class="helper">No MCP connector is configured. This does not block the existing OAuth connections.</p>'
        body+='</div></div>'
        legacy_rows=[c for c in existing if legacy.CONNECTOR_CATALOG.get(c['connector_key'],{}).get('legacy')]
        if legacy_rows:
            body+='<details class="card section"><summary><strong>Legacy technical connections</strong></summary><p class="helper">These older token-based connections remain available so existing workspaces do not break. Reconnect through the login-first Meta/Google connection when practical.</p><div class="table-wrap"><table><thead><tr><th>Connection</th><th>Status</th><th>Action</th></tr></thead><tbody>'
            for c in legacy_rows:body+=f'<tr><td>{esc(c["label"])}</td><td>{_pill(c["status"])}</td><td>{app.button("Open","/integrations/"+c["id"],"secondary")}</td></tr>'
            body+='</tbody></table></div></details>'
        self.send_html(app.layout('Integration Centre',body,'integrations'))

    def v14_connect_page(self,key,q):
        import app
        meta=v14.business_catalog().get(key)
        if not meta:raise ValueError('Unknown integration.')
        body=app.pagehead('Connect '+meta['label'],'Business setup only. Technical provider credentials are deliberately kept out of this page.',app.button('Back','/integrations','secondary'))
        if not meta.get('implemented'):
            body+=app.notice('This integration is planned. No connection button is shown because the backend workflow does not exist yet.','warn')
            return self.send_html(app.layout('Connect '+meta['label'],body,'integrations'))
        if not meta.get('login_first'):
            body+=app.notice('This integration currently requires provider/API configuration. It is kept in Advanced setup rather than exposing credentials in the normal business workflow.','warn')
            if not pc.auth_enabled() or (self.current_user or {}).get('role') in {'Owner','Administrator'}:body+=app.button('Open advanced setup','/developer/integrations','secondary')
            return self.send_html(app.layout('Connect '+meta['label'],body,'integrations'))
        provider=v14.provider_app(meta['provider_key'])
        if not provider['configured'] or (key=='whatsapp_cloud' and not provider['config'].get('whatsapp_config_id')):
            body+=app.notice(meta['label']+' login is not enabled on this installation yet. An administrator must configure the platform provider app once.','warn')
            if not pc.auth_enabled() or (self.current_user or {}).get('role') in {'Owner','Administrator'}:body+=app.button('Configure platform '+provider['label'],'/developer/integrations/'+meta['provider_key'],'secondary')
            return self.send_html(app.layout('Connect '+meta['label'],body,'integrations'))
        existing_id=(q.get('connection_id') or [''])[0]
        hidden=f'<input type="hidden" name="connection_id" value="{esc(existing_id)}">' if existing_id else ''
        body+=f'<div class="card section"><h2>{esc(meta["label"])}</h2><p>{esc(meta["help"])}</p>'
        if key=='shopify':
            body+='''<form method="post" action="/integrations/v14/connect/shopify">'''+hidden+'''<label class="field">Permanent Shopify store address<input name="store_domain" placeholder="your-store.myshopify.com" required><small>Use the permanent .myshopify.com address. You will sign in to Shopify on the next screen.</small></label><button class="btn" type="submit">Continue to Shopify</button></form>'''
        elif key=='wix':
            body+='<form method="post" action="/integrations/v14/connect/wix">'+hidden+'<p class="helper">Continue to Wix to choose a site and approve the Commerce Business OS app. Access tokens are created from the verified Wix app instance; you never paste one here.</p><button class="btn" type="submit">Continue to Wix</button></form>'
        elif key=='google_account':
            body+='<form method="post" action="/integrations/v14/connect/google_account">'+hidden+'<h3>Choose what to connect</h3><p class="helper">Only request permissions for services you actually use. You can add more later.</p>'
            defaults={'ads','analytics','merchant','search_console'}
            for svc,label in v14.GOOGLE_SERVICE_LABELS.items():body+=f'<label class="check"><input type="checkbox" name="services" value="{esc(svc)}" {"checked" if svc in defaults else ""}> {esc(label)}</label>'
            body+='<div class="section"><button class="btn" type="submit">Sign in with Google</button></div></form>'
        elif key=='meta_business':
            body+='<form method="post" action="/integrations/v14/connect/meta_business">'+hidden+'<h3>Choose Meta capabilities</h3><label class="check"><input type="checkbox" name="services" value="social" checked> Facebook & Instagram publishing/insights</label><label class="check"><input type="checkbox" name="services" value="ads" checked> Meta Ads reporting/account access</label><label class="check"><input type="checkbox" name="services" value="leads"> Lead forms</label><div class="section"><button class="btn" type="submit">Continue with Meta</button></div></form>'
        elif key=='microsoft_mailbox':
            body+='<form method="post" action="/integrations/v14/connect/microsoft_mailbox">'+hidden+'<h3>Mailbox access</h3><label class="check"><input type="checkbox" name="services" value="mail_read" checked> Read business mailbox replies</label><label class="check"><input type="checkbox" name="services" value="mail_send"> Send reviewed sales/customer-service email</label><div class="section"><button class="btn" type="submit">Sign in with Microsoft</button></div></form>'
        elif key=='whatsapp_cloud':
            cfg=provider['config'];body+=f'''<div id="wa-embedded" data-app-id="{esc(provider['client_id'])}" data-config-id="{esc(cfg.get('whatsapp_config_id',''))}" data-graph-version="{esc(cfg.get('graph_version','v26.0'))}"><p class="helper">Meta will open a secure onboarding window where you choose or create the WhatsApp Business account and phone number.</p><button class="btn" type="button" id="wa-connect-button">Connect WhatsApp</button><p id="wa-status" class="helper" aria-live="polite"></p></div><form id="wa-complete-form" method="post" action="/integrations/v14/whatsapp/embedded/complete" hidden><input name="code" id="wa-code"><input name="waba_id" id="wa-waba"><input name="phone_number_id" id="wa-phone"><input name="business_id" id="wa-business"><input name="label" value="WhatsApp Business"></form><script defer src="/ui/integrations_v14.js"></script>'''
        body+='</div>'
        self.send_html(app.layout('Connect '+meta['label'],body,'integrations'))

    def v42_mcp_setup(self,q):
        import app
        self._v14_admin_only();mcp.initialise();rows=mcp.list_connectors()
        body=app.pagehead('MCP connector setup','Advanced connector administration. Ordinary owners use Connected apps; they do not need to understand MCP endpoints.',app.button('Connected apps','/integrations','secondary'))
        if q.get('created'):body+=app.notice('MCP connector registered. It is not Connected until Test succeeds and tools are discovered.','success')
        if q.get('tested'):body+=app.notice('MCP test '+('succeeded.' if q.get('ok',['0'])[0]=='1' else 'failed. The connector remains Needs Attention.'),'success' if q.get('ok',['0'])[0]=='1' else 'warn')
        body+='<div class="card section"><h2>Add validated MCP server</h2><form method="post" action="/developer/integrations/mcp/register"><div class="formgrid">'+app.field('Provider key','<input name="provider_key" required placeholder="shopify, meta, gmail...">')+app.field('Display name','<input name="label" required placeholder="Shopify MCP">')+app.field('MCP endpoint','<input name="endpoint" required placeholder="https://connector.example/mcp">')+app.field('Authentication','<select name="auth_type"><option value="none">Managed / none in CRM</option><option value="external">External connector auth</option></select>','Secrets are not collected from normal business users.')+'</div><div class="form-foot"><button class="btn">Register connector</button></div></form></div>'
        body+='<div class="card section"><h2>Registered MCP connectors</h2>'
        if rows:
            body+='<div class="table-wrap"><table><tr><th>Name</th><th>Endpoint</th><th>Status</th><th>Discovered tools</th><th>Actions</th></tr>'
            for r in rows:
                actions=f'<form method="post" action="/developer/integrations/mcp/{esc(r["id"])}/test"><button class="btn secondary small">Test & discover</button></form><form method="post" action="/developer/integrations/mcp/{esc(r["id"])}/disconnect"><button class="btn secondary small">Disconnect</button></form>'
                body+=f'<tr><td>{esc(r["label"])}</td><td>{esc(r["endpoint"])}</td><td>{_pill(r["status"])}</td><td>{esc(", ".join(r.get("capabilities") or []) or "None validated")}</td><td><div class="toolbar">{actions}</div></td></tr>'
            body+='</table></div>'
        else:body+='<p class="helper">No MCP connectors registered.</p>'
        body+='</div>'
        self.send_html(app.layout('MCP connector setup',body,'integrations'))

    def v14_connection_detail(self,cid,q):
        import app
        c=legacy.connection(cid);meta=v14.business_catalog().get(c['connector_key']) or legacy.CONNECTOR_CATALOG.get(c['connector_key'],{})
        if not meta:raise ValueError('Unknown integration connection.')
        health=v14.connection_health(cid,persist=False);tm=v14.token_metadata(cid);reqs=v14.account_selection_requirements(cid)
        body=app.pagehead(c['label'],meta.get('help','Connected business account.'),app.button('Back','/integrations','secondary'))
        if q.get('connected'):body+=app.notice('Provider login completed and the account was validated.','success')
        if q.get('tested'):body+=app.notice('Connection test succeeded against the provider.','success')
        if q.get('synced'):body+=app.notice('Sync completed. The provider confirmed the requested data operation.','success')
        if q.get('resources_saved'):body+=app.notice('Account selection saved and revalidated.','success')
        if q.get('route_saved'):body+=app.notice('Default business routing updated. Automations will use this account for the selected channel.','success')
        if q.get('product_draft'):body+=app.notice('Store product draft was created through the shared commerce connector. Review it in the store before publishing.','success')
        body+=f'<div class="cards"><div class="card"><div class="eyebrow">Connection</div><h2>{_pill(c["status"])}</h2><p><strong>{esc(c.get("account_name") or "Account not validated")}</strong></p><p class="helper">Last sync: {esc(c.get("last_sync_at") or "Not yet")}</p><p class="helper">Last successful provider activity: {esc(c.get("last_success_at") or "Not yet")}</p></div>'
        body+='<div class="card"><div class="eyebrow">Health</div><h2>'+('Healthy' if health['healthy'] else 'Needs attention')+'</h2>'
        if not health['issues']:body+='<p class="helper">No current connection-health issues detected.</p>'
        for issue in health['issues']:body+=f'<div class="note warn"><strong>{esc(issue["summary"])}</strong><br>{esc(issue["owner_action"])}</div>'
        body+='</div></div>'
        body+='<div class="card section"><h2>Actions</h2><div class="actions"><form method="post" action="/integrations/v14/'+esc(cid)+'/test"><button class="btn" type="submit">Test connection</button></form>'
        if c['status']=='Connected':body+='<form method="post" action="/integrations/v14/'+esc(cid)+'/sync"><button class="btn secondary" type="submit">Sync now</button></form>'
        if meta.get('login_first'):body+=app.button('Reconnect','/integrations/v14/connect/'+c['connector_key']+'?connection_id='+urllib.parse.quote(cid),'secondary')+app.button('Connect another','/integrations/v14/connect/'+c['connector_key'],'secondary')
        body+='<form method="post" action="/integrations/v14/'+esc(cid)+'/disconnect"><button class="btn secondary" type="submit">Disconnect</button></form></div></div>'
        if c['status']=='Connected' and c['connector_key'] in {'wix','shopify'}:
            products=m.rows("SELECT product_id,coalesce(public_product_name,product_code,internal_sku,product_id) name FROM products WHERE coalesce(status,'Draft')<>'Archived' ORDER BY name LIMIT 250") if m.table_exists('products') else []
            body+='<div class="card section"><h2>Create a store draft</h2><p class="helper">Send one reviewed CRM product through the shared CommerceConnector. This creates a draft/reviewable store record; it does not claim the item is published.</p><form method="post" action="/integrations/v14/'+esc(cid)+'/product-draft"><label class="field">Product<select name="product_id" required><option value="">Choose product</option>'+''.join('<option value="'+esc(x['product_id'])+'">'+esc(x['name'])+'</option>' for x in products)+'</select></label><button class="btn secondary" type="submit">Create store draft</button></form></div>'
        route_channels=v14.route_channels_for_connection(cid)
        if route_channels and c['status']=='Connected':
            current={r['channel']:r['connection_id'] for r in v14.connection_routes()}
            body+='<div class="card section"><h2>Automation routing</h2><p class="helper">When more than one account is connected, choose exactly which account business automation should use instead of relying on connection order.</p><div class="actions">'
            for ch in route_channels:
                selected=current.get(ch)==cid;label=('Inventory authority' if ch=='Inventory' else 'Default for '+ch)
                if selected:body+=f'<span class="pill good">{esc(label)} ✓</span>'
                else:body+=f'<form method="post" action="/integrations/v14/{esc(cid)}/route"><input type="hidden" name="channel" value="{esc(ch)}"><button class="btn secondary" type="submit">Use as {esc(label.lower())}</button></form>'
            body+='</div></div>'
        if reqs:
            body+='<div class="card section"><h2>Choose business accounts</h2><p class="helper">Only resources returned by this provider login are selectable. Required resources must be selected before the related channel becomes ready.</p><form method="post" action="/integrations/v14/'+esc(cid)+'/resources">'
            for req in reqs:
                rows=req['resources'];body+=f'<label class="field">{esc(req["label"])}'
                if not rows:body+='<div class="note warn">No '+esc(req['label'])+' was returned. Check permissions or reconnect.</div>'
                else:
                    body+=f'<select name="resource_{esc(req["resource_type"])}" {"required" if req["required"] else ""}><option value="">Not selected</option>'
                    for r in rows:body+=f'<option value="{esc(r["external_id"])}" {"selected" if r["selected"] else ""}>{esc(r["display_name"])}</option>'
                    body+='</select>'
                body+='</label>'
            body+='<button class="btn" type="submit">Save account choices</button></form></div>'
        if tm:
            body+='<details class="card section"><summary><strong>Permissions & account session</strong></summary><p class="helper">Technical details are shown for diagnosis only.</p><p><strong>Granted permissions:</strong> '+esc(', '.join(tm.get('granted_scopes') or []) or 'Provider did not return a scope list')+'</p><p><strong>Session expiry:</strong> '+esc(tm.get('expires_at') or 'Provider did not publish an expiry')+'</p></details>'
        runs=m.rows('SELECT * FROM v10_sync_runs WHERE connection_id=? ORDER BY started_at DESC LIMIT 10',(cid,))
        if runs:
            body+='<details class="card section"><summary><strong>Recent sync history</strong></summary><div class="table-wrap"><table><thead><tr><th>Started</th><th>Type</th><th>Status</th><th>Seen</th><th>Updated</th><th>Errors</th></tr></thead><tbody>'
            for r in runs:body+=f'<tr><td>{esc(r.get("started_at"))}</td><td>{esc(r.get("sync_type"))}</td><td>{esc(r.get("status"))}</td><td>{esc(r.get("records_seen"))}</td><td>{esc(r.get("records_updated"))}</td><td>{esc(r.get("errors"))}</td></tr>'
            body+='</tbody></table></div></details>'
        logs=legacy.connection_audit(cid,30)
        if logs:
            body+='<details class="card section"><summary><strong>Advanced connection log</strong></summary><p class="helper">Secrets and authorization headers are never displayed here.</p><div class="table-wrap"><table><thead><tr><th>Time</th><th>Operation</th><th>Status</th><th>Result</th></tr></thead><tbody>'
            for r in logs:body+=f'<tr><td>{esc(r.get("created_at"))}</td><td>{esc(r.get("operation"))}</td><td>{esc(r.get("status_code") or "")}</td><td>{"OK" if r.get("success") else esc(r.get("error_message") or r.get("error_class") or "Failed")}</td></tr>'
            body+='</tbody></table></div></details>'
        self.send_html(app.layout(c['label'],body,'integrations'))

    def v14_developer_integrations(self,q):
        import app
        self._v14_admin_only()
        body=app.pagehead('Advanced platform integrations','One-time operator configuration. Normal business users should use Connect business accounts instead.',app.button('Business Integration Centre','/integrations','secondary'))
        body+=app.notice('Provider client secrets belong in a deployment secret manager in production. This page never displays saved secret values.','warn')
        body+='<div class="cards">'
        for provider in ('shopify','wix','meta','google','microsoft'):
            p=v14.provider_app(provider);h=v14.provider_hints(provider)
            display_status='Configured' if p.get('configured') else 'Platform setup required'
            setup_detail=('Configured from deployment environment' if p["source"]=="environment" else ('Encrypted platform configuration is stored locally' if p.get('configured') else 'No provider application credentials are configured on this test installation'))
            body+=f'<div class="card"><h3>{esc(p["label"])}</h3>{_pill(display_status)}<p class="helper">{esc(setup_detail)}</p>'
            if h:body+='<p class="tiny muted">Saved secret: '+esc(', '.join(k+' '+v for k,v in h.items()))+'</p>'
            body+=app.button('Configure','/developer/integrations/'+provider,'secondary')+'</div>'
        body+='</div><div class="card section"><h2>Administrator-configured providers</h2><p>Marketing email (Resend) and Stripe use restricted provider credentials rather than business OAuth in this build. Their setup lives here deliberately; they are not presented as one-click login connections.</p><div class="actions">'+app.button('Configure Resend','/integrations/connect/resend','secondary')+app.button('Configure Stripe','/integrations/connect/stripe','secondary')+'</div></div>'
        body+='<div class="card section"><h2>Source-of-truth policy</h2><p class="helper">Control which connected system owns customer, order, product-content, advertising, consent and inventory facts.</p>'+app.button('Manage data ownership','/data-ownership','secondary')+'</div>'
        self.send_html(app.layout('Advanced platform integrations',body,'integrations'))

    def v14_developer_provider(self,provider,q):
        import app
        self._v14_admin_only();p=v14.provider_app(provider);cfg=p['config'];h=v14.provider_hints(provider);callbacks=v14.provider_callback_urls(self._v14_base_url())
        body=app.pagehead('Configure '+p['label'],'This is operator/developer configuration. Business staff will only see the resulting Connect button.',app.button('Back','/developer/integrations','secondary'))
        if q.get('saved'):body+=app.notice('Provider application settings saved. Secret values remain hidden.','success')
        body+=f'<div class="card section"><h2>Provider app</h2><p class="helper">Configure this once for the whole platform. In production, supply client secrets using the deployment secret manager/environment.</p><form method="post" action="/developer/integrations/{esc(provider)}/save"><label class="field">Client / App ID<input name="client_id" value="{esc(p["client_id"])}" required></label>'
        if not rc.IS_PRODUCTION:body+=f'<label class="field">Client / App secret<input type="password" name="client_secret" autocomplete="new-password" placeholder="{esc(h.get("client_secret","leave blank to keep existing"))}"><small>Stored encrypted locally. Leave blank to keep the existing secret.</small></label>'
        else:body+='<div class="note info">Production secret values are accepted only from deployment environment/secret-manager variables, not browser forms.</div>'
        if provider=='google':
            if not rc.IS_PRODUCTION:body+=f'<label class="field">Google Ads developer token<input type="password" name="developer_token" placeholder="{esc(h.get("developer_token","optional until Google Ads is enabled"))}"></label>'
        elif provider=='meta':
            body+=f'<label class="field">Graph API version<input name="graph_version" value="{esc(cfg.get("graph_version","v26.0"))}"></label><label class="field">Facebook Login configuration ID<input name="login_config_id" value="{esc(cfg.get("login_config_id",""))}"></label><label class="field">WhatsApp Embedded Signup configuration ID<input name="whatsapp_config_id" value="{esc(cfg.get("whatsapp_config_id",""))}"></label>'
        elif provider=='shopify':body+=f'<label class="field">Requested Shopify scopes<input name="scopes" value="{esc(cfg.get("scopes","read_products,write_products,read_customers,read_orders,read_inventory"))}"></label>'
        elif provider=='wix':body+=f'<label class="field">Wix app install URL<input name="install_url" value="{esc(cfg.get("install_url",""))}" placeholder="https://www.wix.com/app-market/install/..."><small>Use the Wix install/external-install URL for the released app. Configure its post-install redirect to the callback shown below.</small></label>'
        elif provider=='microsoft':body+=f'<label class="field">Tenant<input name="tenant" value="{esc(cfg.get("tenant","common"))}"><small>Use common unless the application is intentionally single-tenant.</small></label>'
        body+='<button class="btn" type="submit">Save platform configuration</button></form></div>'
        cb=callbacks['whatsapp' if provider=='meta' else provider]
        body+=f'<div class="card section"><h2>Redirect / callback URL</h2><p class="helper">Register this exact URL in the provider developer console for this environment.</p><code>{esc(cb)}</code></div>'
        self.send_html(app.layout('Configure '+p['label'],body,'integrations'))

    def v14_integration_health(self,q):
        import app
        import owner_experience as ox
        ai=m.ai_health()
        checked=int((q.get('checked') or ['-1'])[0] or -1)
        attention=int((q.get('attention') or ['0'])[0] or 0)
        if checked==0:notice=app.notice('No connected business accounts were available to test. Complete the required setup below first.','warn')
        elif checked>0 and attention:notice=app.notice(f'Checked {checked} connection(s); {attention} need attention.','warn')
        elif checked>0:notice=app.notice(f'Checked {checked} connection(s); no provider issues were found.','success')
        else:notice=''
        rows=legacy.connections();body=app.pagehead('Connection health','Live provider checks plus token, permission, routing, stale-sync and AI readiness in business language.','<form method="post" action="/integrations/v14/health/run"><button class="btn" type="submit">Check all connected accounts</button></form>')+notice
        ai_kind='good' if ai['status']=='Connected' else 'warn'
        body+=f'<div class="card section"><div class="message-top"><div><span class="pill {ai_kind}">{app.e(ai["status"])}</span><h2>AI connection</h2><p class="helper">{app.e(ai["detail"])}</p></div>{app.button("Open AI settings","/settings#ai","secondary")}</div>'
        if ai.get('checked_at'):body+=f'<p class="tiny muted">Last checked: {app.e(ai["checked_at"])} · Model: {app.e(ai.get("model") or "—")}</p>'
        body+='</div>'
        body+='<div class="card section"><div class="table-wrap"><table><thead><tr><th>Platform</th><th>Status</th><th>Account</th><th>Last sync</th><th>Attention</th></tr></thead><tbody>'
        visible=0
        for c in rows:
            if c['connector_key'] not in v14.business_catalog() and not legacy.CONNECTOR_CATALOG.get(c['connector_key'],{}).get('legacy'):continue
            visible+=1;health=v14.connection_health(c['id'],persist=False);issues='; '.join(i['summary'] for i in health['issues']) or 'Healthy'
            href='/integrations/v14/'+c['id'] if c['connector_key'] in v14.business_catalog() else '/integrations/'+c['id']
            body+=f'<tr><td><a href="{esc(href)}">{esc(c["label"])}</a></td><td>{_pill(c["status"])}</td><td>{esc(c.get("account_name") or "—")}</td><td>{esc(c.get("last_sync_at") or "Never")}</td><td>{esc(issues)}</td></tr>'
        if not visible:body+='<tr><td colspan="5">No business accounts connected yet. The cards below show what is blocked and where to continue.</td></tr>'
        body+='</tbody></table></div></div>'
        body+='<div class="section-head"><h2>Setup blockers</h2><span class="tiny muted">Only real provider readiness is counted</span></div><div class="campaign-grid">'
        groups=ox.integration_groups()
        shown=0
        for group in groups:
            for c in group['cards']:
                if c['status']=='Connected':continue
                shown+=1;action=app.button('Continue setup',c['action_url'],'secondary') if c.get('action_url') else ''
                body+=f'<div class="card"><span class="pill warn">{app.e(c["status"])}</span><h3>{app.e(c["label"])}</h3><p class="helper">{app.e(c["help"])}</p>{action}</div>'
        if not shown:body+='<div class="card empty">All currently configured business connections are ready.</div>'
        body+='</div>'
        self.send_html(app.layout('Connection health',body,'integration_health'))

    def v14_setup(self,q):
        import app
        steps=v14.setup_status();complete=sum(1 for x in steps if x['status']=='Complete');total=len(steps)
        body=app.pagehead('Connect your business','A guided non-technical setup. Connect accounts once; the system handles OAuth tokens, refresh and synchronisation behind the scenes.',app.button('Integration Centre','/integrations','secondary'))
        body+=f'<div class="card section"><h2>{complete} of {total} core steps complete</h2><div style="height:10px;background:#eee;border-radius:999px;overflow:hidden"><div style="height:100%;width:{(complete/total*100 if total else 0):.1f}%;background:#6b4eff"></div></div></div>'
        for i,s in enumerate(steps,1):body+=f'<div class="card section"><div class="message-top"><div>{_pill(s["status"])}<h3>Step {i} — {esc(s["label"])}</h3><p class="helper">{esc(s["detail"])}</p></div>{app.button("Open",s["url"],"secondary")}</div></div>'
        self.send_html(app.layout('Connect your business',body,'setup'))

    def v14_data_ownership(self,q):
        import app
        self._v14_admin_only();rows=v14.data_authority();body=app.pagehead('Where your business data is managed','Choose the system that owns stock. Other core records use safe defaults; technical conflict rules are available under Advanced details.',app.button('Back','/developer/integrations','secondary'))
        if q.get('saved'):body+=app.notice('Source-of-truth routing updated. Runtime enforcement remains active.','success')
        commerce=[c for key in ('shopify','wix') for c in legacy.connections(key) if c['status']=='Connected']
        body+=app.notice(RELEASE_LABEL+' separates policy explanation from executable authority. Customer identity, consent, product content, orders and ad metrics use fixed audited rules. Only the inventory authority is owner-configurable because the runtime can enforce that exact connection.','info')
        for r in rows:
            default=v14.DATA_AUTHORITY_DEFAULTS.get(r['entity_type'],(r['authority'],r['conflict_policy'],r['explanation']))
            authority,policy,explanation=default
            business_labels={'customer':'Customers','online_order':'Online orders','product_content':'Product content','ad_performance':'Advertising performance','marketing_permission':'Marketing permissions','inventory':'Inventory'}
            body+=f'<div class="card section"><div class="message-top"><div><span class="pill good">Protected</span><h3>{esc(business_labels.get(r["entity_type"],r["entity_type"].replace("_"," ").title()))}</h3><p class="helper">Managed by <strong>{esc(authority)}</strong></p></div></div><details><summary>Why? / Advanced details</summary><div class="kv section"><div>Conflict handling</div><div>{esc(policy)}</div><div>Reason</div><div>{esc(explanation)}</div></div></details>'
            if r['entity_type']=='inventory':
                body+='<div class="divider"></div><form method="post" action="/data-ownership/save"><input type="hidden" name="entity_type" value="inventory"><input type="hidden" name="authority" value="'+esc(authority)+'"><input type="hidden" name="conflict_policy" value="'+esc(policy)+'"><input type="hidden" name="explanation" value="'+esc(explanation)+'"><label class="field">Authoritative connected store<select name="authority_connection_id"><option value="">Commerce Business OS internal inventory</option>'
                for c in commerce:body+=f'<option value="{esc(c["id"])}" {"selected" if r.get("authority_connection_id")==c["id"] else ""}>{esc(c.get("account_name") or c.get("label") or c["id"])}</option>'
                body+='</select><small>Only this validated store may write inventory. Leave blank to block provider inventory writes.</small></label>'
                body+='<button class="btn secondary" type="submit">Save inventory manager</button>'
                if not commerce:body+=app.notice('Commerce Business OS is managing inventory internally. Connect a store only if you want that validated store to become the stock authority.','info')+app.button('Connect a store','/integrations','secondary')
                body+='</form>'
            body+='</div>'
        self.send_html(app.layout('Data ownership',body,'integrations'))

    def v14_e2e(self,q):
        import app
        report=v14.run_v14_acceptance_audit();body=app.pagehead('27-step connected business test','Non-destructive audit of account connection → products → campaigns → CRM → sales → attribution → AI next action.',app.button('Integration Centre','/integrations','secondary'))
        body+=f'<div class="cards"><div class="card"><div class="eyebrow">Pass</div><h2>{report["pass"]}</h2></div><div class="card"><div class="eyebrow">Partial</div><h2>{report["partial"]}</h2></div><div class="card"><div class="eyebrow">Needs setup</div><h2>{report["needs_setup"]}</h2></div><div class="card"><div class="eyebrow">Blocked</div><h2>{report["blocked"]}</h2></div></div>'
        body+='<div class="card section"><div class="table-wrap"><table><thead><tr><th>#</th><th>Workflow stage</th><th>Status</th><th>What this means</th></tr></thead><tbody>'
        for s in report['steps']:body+=f'<tr><td>{s["step"]}</td><td>{esc(s["label"])}</td><td>{_pill(s["status"])}</td><td>{esc(s["detail"])}</td></tr>'
        body+='</tbody></table></div></div>'
        self.send_html(app.layout('Connected business test',body,'e2e'))
