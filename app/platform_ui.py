from __future__ import annotations
import html
import json
import re
import urllib.parse

import marketing as m
import platform_core as pc
import db_layer


def login_document(message: str='') -> str:
    brand=html.escape(m.settings().get('brand_name') or 'Commerce Business OS')
    note=f'<div class="note error">{html.escape(message)}</div>' if message else ''
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Sign in · Commerce Business OS</title><style>
    body{{font-family:Inter,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;background:#f7f6fb;color:#202126;margin:0;display:grid;place-items:center;min-height:100vh}}.box{{width:min(440px,calc(100% - 32px));background:white;border:1px solid #e5e2ef;border-radius:18px;padding:30px;box-shadow:0 16px 48px rgba(40,30,80,.08)}}h1{{margin:0 0 6px}}p{{color:#6c6875}}label{{display:grid;gap:6px;margin:14px 0}}input{{font:inherit;padding:12px;border:1px solid #ddd8ea;border-radius:10px}}button{{width:100%;border:0;border-radius:10px;padding:12px;background:#6b4eff;color:white;font-weight:700;cursor:pointer}}.note{{padding:10px 12px;border-radius:10px;background:#fff0f0;color:#8a3030;margin:14px 0}}small{{color:#7d7888}}</style></head><body><form class="box" method="post" action="/login"><h1>{brand}</h1><p>Sign in to the business workspace.</p>{note}<label>Email<input type="email" name="email" autocomplete="username" required></label><label>Password<input type="password" name="password" autocomplete="current-password" required></label><label>Authenticator code <span style="font-size:12px;color:#7d7888">(if enabled)</span><input name="otp" inputmode="numeric" pattern="[0-9 ]{6,8}" autocomplete="one-time-code"></label><button>Sign in</button><p><small>Account access is controlled by the Owner / Administrator roles.</small></p></form></body></html>'''


class PlatformPages:
    def v11_get(self,path,q):
        if re.fullmatch(r'/privacy/contacts/[^/]+/export',path):
            raw=json.dumps(pc.contact_portability(path.split('/')[3]),indent=2,default=str).encode('utf-8');self.send_file(raw,'contact-data-export.json','application/json')
        elif path=='/access-control':self.access_control(q)
        elif path=='/approvals':self.approval_centre(q)
        elif path=='/scheduler':self.scheduler_page(q)
        elif path=='/identity-resolution':self.identity_resolution(q)
        elif re.fullmatch(r'/identity-resolution/[^/]+',path):self.identity_detail(path.split('/')[-1],q)
        elif path=='/integration-health':self.integration_health(q)
        elif path=='/privacy':self.privacy_page(q)
        elif path=='/locations':self.locations_page(q)
        elif re.fullmatch(r'/locations/[^/]+',path):self.location_detail(path.split('/')[-1],q)
        elif path=='/e2e-test':self.e2e_page(q)
        else:return False
        return True

    def v11_post(self,path,f):
        import app
        v=lambda k,d='':f.get(k,[d])[0]
        user=getattr(self,'current_user',None) or {}
        if path=='/access-control/user':
            if not pc.can(user,'users.manage') and pc.auth_enabled():raise ValueError('Your role cannot manage users.')
            pc.create_user(v('email'),v('display_name'),v('role'),v('password'))
            return self.redirect('/access-control?user_created=1')
        if path=='/access-control/settings':
            if not pc.can(user,'settings.manage') and pc.auth_enabled():raise ValueError('Your role cannot change security settings.')
            mode=v('auth_enabled')=='1'
            if mode and not pc.users():raise ValueError('Create at least one Owner or Administrator before enabling sign-in.')
            pc.set_sec('auth_enabled','1' if mode else '0')
            return self.redirect('/access-control?saved=1')
        if re.fullmatch(r'/access-control/users/[^/]+/(enable|disable)',path):
            if not pc.can(user,'users.manage') and pc.auth_enabled():raise ValueError('Your role cannot manage users.')
            uid=path.split('/')[3];pc.set_user_active(uid,path.endswith('/enable'))
            return self.redirect('/access-control?user_updated=1')
        if re.fullmatch(r'/access-control/users/[^/]+/reset-password',path):
            if not pc.can(user,'users.manage') and pc.auth_enabled():raise ValueError('Your role cannot manage users.')
            uid=path.split('/')[3];pc.reset_user_password(uid,v('password'))
            return self.redirect('/access-control?password_reset=1')
        if re.fullmatch(r'/access-control/users/[^/]+/mfa/start',path):
            if not pc.can(user,'users.manage') and pc.auth_enabled():raise ValueError('Your role cannot manage users.')
            uid=path.split('/')[3];pc.begin_mfa(uid);return self.redirect('/access-control?mfa_started='+urllib.parse.quote(uid))
        if re.fullmatch(r'/access-control/users/[^/]+/mfa/enable',path):
            if not pc.can(user,'users.manage') and pc.auth_enabled():raise ValueError('Your role cannot manage users.')
            uid=path.split('/')[3];pc.enable_mfa(uid,v('code'));return self.redirect('/access-control?mfa_enabled=1')
        if re.fullmatch(r'/access-control/users/[^/]+/mfa/disable',path):
            if not pc.can(user,'users.manage') and pc.auth_enabled():raise ValueError('Your role cannot manage users.')
            uid=path.split('/')[3];pc.disable_mfa(uid);return self.redirect('/access-control?mfa_disabled=1')
        if re.fullmatch(r'/approvals/[^/]+/(approve|reject)',path):
            if not pc.can(user,'approvals.manage') and pc.auth_enabled():raise ValueError('Your role cannot decide approvals.')
            aid=path.split('/')[2];decision='Approved' if path.endswith('/approve') else 'Rejected';pc.decide_approval(aid,decision,user.get('user_id',''),v('note'))
            return self.redirect('/approvals?decided=1')
        if path=='/scheduler/run':
            if not pc.can(user,'integrations.manage') and pc.auth_enabled():raise ValueError('Your role cannot run integration jobs.')
            out=pc.run_due_schedules(50);return self.redirect('/scheduler?run='+urllib.parse.quote(json.dumps(out)))
        if re.fullmatch(r'/scheduler/[^/]+/save',path):
            if not pc.can(user,'integrations.manage') and pc.auth_enabled():raise ValueError('Your role cannot change schedules.')
            pc.save_schedule(path.split('/')[2],int(v('interval_minutes','60')),v('enabled')=='1');return self.redirect('/scheduler?saved=1')
        if path=='/identity-resolution/refresh':
            out=pc.refresh_identity_candidates();return self.redirect('/identity-resolution?created='+str(out['created']))
        if re.fullmatch(r'/identity-resolution/[^/]+/(dismiss|merge)',path):
            cid=path.split('/')[2]
            if path.endswith('/dismiss'):pc.dismiss_identity_candidate(cid);return self.redirect('/identity-resolution?dismissed=1')
            if not pc.can(user,'contacts.manage') and pc.auth_enabled():raise ValueError('Your role cannot merge contact records.')
            out=pc.merge_contacts(cid,user.get('user_id',''));return self.redirect('/contacts/'+urllib.parse.quote(out['primary_contact_id'])+'?merged=1')
        if path=='/privacy/request':
            if not pc.can(user,'contacts.manage') and pc.auth_enabled():raise ValueError('Your role cannot manage privacy requests.')
            pc.create_privacy_request(v('contact_id'),v('request_type'),v('notes'));return self.redirect('/privacy?created=1')
        if re.fullmatch(r'/privacy/[^/]+/complete',path):
            if not pc.can(user,'contacts.manage') and pc.auth_enabled():raise ValueError('Your role cannot manage privacy requests.')
            pc.complete_privacy_request(path.split('/')[2],user.get('user_id',''),v('notes'));return self.redirect('/privacy?completed=1')
        if re.fullmatch(r'/privacy/contacts/[^/]+/anonymize',path):
            if not pc.can(user,'contacts.manage') and pc.auth_enabled():raise ValueError('Your role cannot anonymise contacts.')
            if v('confirm').strip().upper()!='ANONYMISE':raise ValueError('Type ANONYMISE to confirm this irreversible action.')
            pc.anonymize_contact(path.split('/')[3],user.get('user_id',''));return self.redirect('/privacy?anonymised=1')
        if path=='/locations/save':
            if not pc.can(user,'products.manage') and pc.auth_enabled():raise ValueError('Your role cannot manage stock locations.')
            lid=pc.save_location({k:x[0] for k,x in f.items() if x});return self.redirect('/locations/'+urllib.parse.quote(lid)+'?saved=1')
        if path=='/brands/save':
            if not pc.can(user,'products.manage') and pc.auth_enabled():raise ValueError('Your role cannot manage brands.')
            pc.save_brand(v('name'),v('currency','INR'),v('language','English'),v('brand_id'));return self.redirect('/locations?brand_saved=1')
        if re.fullmatch(r'/locations/[^/]+/inventory',path):
            if not pc.can(user,'products.manage') and pc.auth_enabled():raise ValueError('Your role cannot manage stock.')
            lid=path.split('/')[2];pc.save_location_inventory(lid,v('product_id'),int(v('on_hand','0')),int(v('reserved','0')),int(v('reorder_point','0')));return self.redirect('/locations/'+urllib.parse.quote(lid)+'?stock_saved=1')
        if path=='/e2e-test/run':
            if not pc.can(user,'integrations.manage') and pc.auth_enabled():raise ValueError('Your role cannot run the operational readiness test.')
            rid=pc.run_e2e_test();return self.redirect('/e2e-test?run='+urllib.parse.quote(rid))
        return False

    def access_control(self,q):
        import app
        pc.initialise()
        users=pc.users();enabled=pc.auth_enabled()
        actions=''
        body=app.pagehead('Access, roles & approval policy','Database-backed users, roles and authenticator MFA are functional. Production mode requires sign-in and MFA for at least one active Owner.',actions)
        if q.get('saved'):body+=app.notice('Security settings saved.','success')
        if q.get('user_created'):body+=app.notice('User account created.','success')
        if q.get('user_updated'):body+=app.notice('User status updated.','success')
        if q.get('password_reset'):body+=app.notice('Password reset and existing sessions revoked.','success')
        if q.get('mfa_enabled'):body+=app.notice('Authenticator MFA enabled.','success')
        if q.get('mfa_disabled'):body+=app.notice('Authenticator MFA disabled.','success')
        body+=f'''<div class="two"><div class="card"><h2>Access mode</h2><form method="post" action="/access-control/settings"><label class="check"><input type="checkbox" name="auth_enabled" value="1" {'checked' if enabled else ''}><span><strong>Require database sign-in</strong><small>Enable before any public deployment. Existing local Basic Auth via CRM_PASSWORD remains a separate emergency option.</small></span></label><button class="btn">Save security policy</button></form><div class="divider"></div><h3>Business automation</h3><p class="helper">Automation is configured once in the owner-facing Automation level screen. Access control no longer keeps a second conflicting automation setting.</p>{app.button('Open automation level','/owner-automation','secondary')}</div><div class="card"><h2>Create user</h2><form method="post" action="/access-control/user" class="formgrid"><label class="field">Name<input name="display_name" required></label><label class="field">Email<input type="email" name="email" required></label><label class="field">Role<select name="role">{app.options(pc.ROLES,'Owner')}</select></label><label class="field">Password<input type="password" name="password" minlength="12" required></label><div><button class="btn">Create user</button></div></form></div></div>'''
        body+='<div class="card section"><h2>Users</h2><table><thead><tr><th>User</th><th>Role</th><th>Status</th><th>Last login</th><th>Controls</th></tr></thead><tbody>'
        if users:
            for u in users:
                toggle='enable' if not u['active'] else 'disable';toggle_label='Enable' if not u['active'] else 'Disable'
                mi=pc.mfa_info(u['user_id']);pending=pc.pending_mfa_secret(u['user_id'])
                mfa_controls=(f'<span class="pill good">MFA on</span><form method="post" action="/access-control/users/{app.e(u["user_id"])}/mfa/disable"><button class="btn secondary small">Disable MFA</button></form>' if mi.get('enabled') else f'<form method="post" action="/access-control/users/{app.e(u["user_id"])}/mfa/start"><button class="btn secondary small">Set up MFA</button></form>')
                if pending:
                    issuer=urllib.parse.quote(m.settings().get('brand_name') or 'Commerce Business OS');label=urllib.parse.quote(u['email']);uri=f'otpauth://totp/{issuer}:{label}?secret={pending}&issuer={issuer}&digits=6&period=30'
                    mfa_controls+=f'<div class="tiny"><strong>Authenticator secret:</strong> <code>{app.e(pending)}</code><form method="post" action="/access-control/users/{app.e(u["user_id"])}/mfa/enable"><input name="code" inputmode="numeric" placeholder="6-digit code" required><button class="btn small">Enable MFA</button></form><details><summary>Authenticator URI</summary><code style="word-break:break-all">{app.e(uri)}</code></details></div>'
                controls=f'''<div class="actions"><form method="post" action="/access-control/users/{app.e(u['user_id'])}/{toggle}"><button class="btn secondary small">{toggle_label}</button></form><form method="post" action="/access-control/users/{app.e(u['user_id'])}/reset-password"><input type="password" name="password" minlength="12" placeholder="New 12+ character password" required><button class="btn secondary small">Reset password</button></form>{mfa_controls}</div>'''
                body+=f'<tr><td><strong>{app.e(u["display_name"])}</strong><br><span class="tiny muted">{app.e(u["email"])}</span></td><td>{app.e(u["role"])}</td><td>{"Active" if u["active"] else "Disabled"}</td><td>{app.e(u["last_login_at"] or "Never")}</td><td>{controls}</td></tr>'
        else:body+='<tr><td colspan="5" class="empty">No database user accounts yet. Local private access is unchanged until you create an account and enable sign-in.</td></tr>'
        body+='</tbody></table></div>'
        self.send_html(app.layout('Access & roles',body,'access'))

    def approval_centre(self,q):
        import app
        import owner_experience as ox
        # This page must be independently safe on a fresh workspace.
        # Do not rely on Access & roles or another platform page having
        # initialised the approval/security schema first.
        pc.initialise()
        pending=pc.approvals('Pending',250);past=pc.approvals('',100)
        draft_rows=m.rows("SELECT d.*,c.campaign_name,coalesce(ct.full_name,ct.username,'Contact') contact_name FROM m4_drafts d JOIN campaigns c ON c.campaign_id=d.campaign_id JOIN contacts ct ON ct.contact_id=d.contact_id WHERE d.status<>'Approved' ORDER BY d.created_at DESC LIMIT 100")
        draft_ready=[];draft_blocked=[]
        for d in draft_rows:
            issues=[x for x in m.draft_gate(d) if x!='Human draft approval required']
            (draft_blocked if issues else draft_ready).append((d,issues))
        creative=[]
        if m.table_exists('v8_creative_campaign_assets'):
            creative=m.rows("SELECT a.id,a.campaign_id,a.product_id,a.placement_key,a.status,a.created_at,coalesce(c.name,a.campaign_id) campaign_name,coalesce(p.public_product_name,a.product_id) product_name FROM v8_creative_campaign_assets a LEFT JOIN v8_creative_campaigns c ON c.id=a.campaign_id LEFT JOIN products p ON p.product_id=a.product_id WHERE a.status IN ('Needs review','QC passed','Fidelity review','Needs correction') ORDER BY a.created_at DESC LIMIT 100")
        mode=ox.automation_mode()
        total_pending=len(pending)+len(draft_ready)+len(draft_blocked)+len(creative)
        body=app.pagehead('Approval centre','One review queue for provider actions, campaign copy and creative exceptions. Blocked items show what must be fixed instead of pretending they are approvable.',app.button('Automation level','/owner-automation','secondary'))
        body+=f'<div class="grid"><div class="card stat"><div class="label">Review queue</div><div class="value">{total_pending}</div><div class="hint">Provider approvals + campaign drafts + creative reviews.</div></div><div class="card stat"><div class="label">Automation level</div><div class="value" style="font-size:24px">{app.e(mode["name"])}</div><div class="hint">Single owner-facing automation policy.</div></div></div>'
        body+='<div class="card section"><h2>Provider / operational approvals</h2>'
        if not pending:body+='<div class="empty">No provider or operational approval is waiting.</div>'
        for x in pending:
            klass='warn' if x['risk_level'] in ('High','Critical') else 'purple'
            body+=f'<div class="readiness-row"><div class="row-main"><span class="pill {klass}">{app.e(x["risk_level"])}</span><strong>{app.e(x["action_type"])}</strong><small>{app.e(x["summary"])}</small></div><div class="actions"><form method="post" action="/approvals/{app.e(x["id"])}/approve"><input name="note" placeholder="Optional note"><button class="btn good">Approve</button></form><form method="post" action="/approvals/{app.e(x["id"])}/reject"><button class="btn secondary">Reject</button></form></div></div>'
        body+='</div>'
        body+='<div class="card section"><h2>Campaign copy review</h2><p class="helper">Permission and product-truth blockers must be resolved before a draft can be approved for handoff.</p>'
        if not draft_ready and not draft_blocked:body+='<div class="empty">No campaign drafts are waiting for review.</div>'
        for d,issues in (draft_ready+draft_blocked)[:60]:
            ready=not issues;status='Ready for review' if ready else 'Blocked';klass='good' if ready else 'warn'
            detail='Ready for human content review.' if ready else '; '.join(issues)
            url='/campaigns/'+urllib.parse.quote(d['campaign_id'])+'?contact='+urllib.parse.quote(d['contact_id'])
            body+=f'<div class="readiness-row"><div class="row-main"><span class="pill {klass}">{status}</span><strong>{app.e(d["campaign_name"])}</strong><small>{app.e(d["contact_name"])} · {app.e(detail)}</small></div>{app.button("Review draft",url,"secondary small")}</div>'
        body+='</div>'
        body+='<div class="card section"><h2>Creative review</h2><p class="helper">Creative only becomes publishable after its QC/fidelity state and owner decision are consistent.</p>'
        if not creative:body+='<div class="empty">No creative assets are waiting for review.</div>'
        for x in creative[:60]:
            klass='warn' if x['status'] in ('Needs correction','Fidelity review') else 'purple'
            body+=f'<div class="readiness-row"><div class="row-main"><span class="pill {klass}">{app.e(x["status"])}</span><strong>{app.e(x["product_name"])}</strong><small>{app.e(x["campaign_name"])} · {app.e(x["placement_key"])}</small></div>{app.button("Open creative","/creative-studio/campaigns/"+urllib.parse.quote(x["campaign_id"]),"secondary small")}</div>'
        body+='</div><div class="card section"><h2>Recent decisions</h2><table><thead><tr><th>Action</th><th>Risk</th><th>Status</th><th>Created</th></tr></thead><tbody>'
        decided=[x for x in past if x['status']!='Pending'][:50]
        for x in decided:body+=f'<tr><td>{app.e(x["action_type"])}<br><span class="tiny muted">{app.e(x["summary"])}</span></td><td>{app.e(x["risk_level"])}</td><td>{app.e(x["status"])}</td><td>{app.e(x["created_at"])}</td></tr>'
        if not decided:body+='<tr><td colspan="4" class="empty">No approval decisions yet.</td></tr>'
        body+='</tbody></table></div>'
        self.send_html(app.layout('Approval centre',body,'approvals'))

    def scheduler_page(self,q):
        import app
        rows=pc.schedules();body=app.pagehead('Background jobs & sync schedule','Schedules persist in the database. Local mode can run them in-process; production runs them through the separate durable worker service.',app.button('Run due jobs now','javascript:void(0)','secondary'))
        if q.get('saved'):body+=app.notice('Schedule updated.','success')
        if q.get('run'):body+=app.notice('Due jobs were processed.','success')
        body+='<form method="post" action="/scheduler/run" class="section"><button class="btn">Run due jobs now</button></form><div class="card section"><table><thead><tr><th>Job</th><th>Type</th><th>Frequency</th><th>Next run</th><th>Last result</th><th>Controls</th></tr></thead><tbody>'
        for r in rows:
            body+=f'''<tr><td><strong>{app.e(r['job_key'])}</strong>{('<br><span class="tiny muted">'+app.e(r['connection_id'])+'</span>') if r['connection_id'] else ''}</td><td>{app.e(r['job_type'])}</td><td>{r['interval_minutes']} min</td><td>{app.e(r['next_run_at'])}</td><td>{app.e(r['last_status'])}{('<br><span class="tiny error">'+app.e(r['last_error'])+'</span>') if r['last_error'] else ''}</td><td><form method="post" action="/scheduler/{app.e(r['job_key'])}/save"><input type="number" name="interval_minutes" min="15" max="10080" value="{r['interval_minutes']}" style="width:90px"><label class="tiny"><input type="checkbox" name="enabled" value="1" {'checked' if r['enabled'] else ''}> enabled</label><button class="btn secondary small">Save</button></form></td></tr>'''
        body+='</tbody></table></div>'
        self.send_html(app.layout('Scheduler',body,'scheduler'))

    def identity_resolution(self,q):
        import app
        items=pc.identity_candidates('Needs review',250)
        body=app.pagehead('Identity resolution','Potential duplicates are detected from recorded email, phone and social identities. Nothing is merged automatically.','<form method="post" action="/identity-resolution/refresh"><button class="btn secondary">Refresh candidates</button></form>')
        if q.get('created'):body+=app.notice(q['created'][0]+' new candidate pairs found.','success')
        body+=f'<div class="card section"><h2>{len(items)} candidates need review</h2><table><thead><tr><th>Primary</th><th>Possible duplicate</th><th>Matched on</th><th></th></tr></thead><tbody>'
        for x in items:
            body+=f'<tr><td>{app.e(x["primary_name"])}</td><td>{app.e(x["duplicate_name"])}</td><td>{app.e(", ".join(x["match_types"]))}</td><td>{app.button("Review","/identity-resolution/"+x["id"],"secondary small")}</td></tr>'
        if not items:body+='<tr><td colspan="4" class="empty">No unresolved duplicate candidates.</td></tr>'
        body+='</tbody></table></div>'
        self.send_html(app.layout('Identity resolution',body,'identity'))

    def identity_detail(self,cid,q):
        import app
        p=pc.merge_preview(cid);body=app.pagehead('Review possible duplicate','A merge is deliberately blocked when core identity fields conflict.','')
        body+=f'<div class="two"><div class="card"><h2>Keep as primary</h2><pre class="kb-text">{app.e(json.dumps({k:p["primary"].get(k) for k in ["contact_id","full_name","email","phone_number","username","country","contact_type","lifecycle_stage"]},indent=2,default=str))}</pre></div><div class="card"><h2>Possible duplicate</h2><pre class="kb-text">{app.e(json.dumps({k:p["duplicate"].get(k) for k in ["contact_id","full_name","email","phone_number","username","country","contact_type","lifecycle_stage"]},indent=2,default=str))}</pre></div></div>'
        if p['conflicts']:
            body+='<div class="note warn section"><strong>Conflicting fields</strong><br>'+app.e('; '.join(f'{f}: {a} / {b}' for f,a,b in p['conflicts']))+'</div>'
        if p['fillable']:body+='<div class="note section"><strong>Blank primary fields that can be filled</strong><br>'+app.e('; '.join(f'{f} ← {v}' for f,v in p['fillable']))+'</div>'
        critical=any(f in {'email','phone_number','username','full_name'} for f,_,_ in p['conflicts'])
        body+=f'''<div class="actions section"><form method="post" action="/identity-resolution/{app.e(cid)}/dismiss"><button class="btn secondary">Not the same person</button></form>{'' if critical else f'<form method="post" action="/identity-resolution/{app.e(cid)}/merge"><button class="btn good">Merge into primary</button></form>'}</div>'''
        if critical:body+=app.notice('Edit the records to resolve the highlighted core identity conflict before merging.','warn')
        self.send_html(app.layout('Identity review',body,'identity'))

    def integration_health(self,q):
        import app
        rows=pc.connection_health();connected=sum(1 for x in rows if x['status']=='Connected');errors=sum(1 for x in rows if x['status'] in {'Connection error','Reconnect required','Permission required'})
        body=app.pagehead('Integration health centre','One place to see account state, sync freshness, errors and background schedule.','')
        body+=f'<div class="grid"><div class="card stat"><div class="label">Verified connections</div><div class="value">{connected}</div></div><div class="card stat"><div class="label">Connections needing attention</div><div class="value">{errors}</div></div></div>'
        cats=[]
        for r in rows:
            if r['category'] not in cats:cats.append(r['category'])
        for cat in cats:
            body+=f'<div class="card section"><h2>{app.e(cat)}</h2><table><thead><tr><th>Integration</th><th>Status</th><th>Account</th><th>Last successful sync</th><th>Background sync</th><th>Issue</th></tr></thead><tbody>'
            for r in [x for x in rows if x['category']==cat]:
                sch=r.get('schedule')
                status_kind="good" if r["status"]=="Connected" else "warn"
                schedule_label=(str(sch["interval_minutes"])+" min") if sch and sch.get("enabled") else "Off"
                manage_button=' '+app.button('Manage','/integrations/'+r['connection_id'],'secondary small') if r.get('connection_id') else ''
                body+=f'<tr><td><strong>{app.e(r["label"])}</strong></td><td><span class="pill {status_kind}">{app.e(r["status"])}</span></td><td>{app.e(r.get("account") or "—")}</td><td>{app.e(r.get("last_success") or "Never")}</td><td>{app.e(schedule_label)}</td><td>{app.e(r.get("last_error") or "")}{manage_button}</td></tr>'
            body+='</tbody></table></div>'
        self.send_html(app.layout('Integration health',body,'integration_health'))

    def privacy_page(self,q):
        import app
        open_items=pc.privacy_requests('Open',200);contacts=m.rows("SELECT contact_id,coalesce(full_name,username,email,phone_number,contact_id) label FROM contacts ORDER BY label COLLATE NOCASE LIMIT 500")
        body=app.pagehead('Privacy & data requests','Handle exports, corrections, consent reviews and controlled anonymisation without deleting linked financial/order history.','')
        if q.get('created'):body+=app.notice('Privacy request recorded.','success')
        if q.get('completed'):body+=app.notice('Privacy request marked complete.','success')
        if q.get('anonymised'):body+=app.notice('Contact personal data was anonymised and channel permissions were set to Do Not Contact.','success')
        body+=f'''<div class="card"><h2>Create request</h2><form method="post" action="/privacy/request" class="formgrid"><label class="field">Contact<select name="contact_id" required>{app.options([(c['contact_id'],c['label']) for c in contacts],'','Choose contact')}</select></label><label class="field">Request type<select name="request_type">{app.options(['Export','Correction','Deletion / anonymisation','Consent review'],'Export')}</select></label><label class="field" style="grid-column:1/-1">Notes<textarea name="notes" rows="2"></textarea></label><div><button class="btn">Record request</button></div></form></div>'''
        body+='<div class="card section"><h2>Open requests</h2><table><thead><tr><th>Contact</th><th>Request</th><th>Requested</th><th>Actions</th></tr></thead><tbody>'
        for r in open_items:
            export=app.button('Export data','/privacy/contacts/'+r['contact_id']+'/export','secondary small')
            complete=f'<form method="post" action="/privacy/{app.e(r["id"])}/complete"><button class="btn secondary small">Mark complete</button></form>'
            anonym=''
            if r['request_type']=='Deletion / anonymisation':
                anonym=f'''<form method="post" action="/privacy/contacts/{app.e(r['contact_id'])}/anonymize"><input name="confirm" placeholder="Type ANONYMISE" required><button class="btn warn small">Anonymise PII</button></form>'''
            body+=f'<tr><td>{app.e(r["contact_name"])}</td><td><strong>{app.e(r["request_type"])}</strong><br><span class="tiny muted">{app.e(r.get("notes") or "")}</span></td><td>{app.e(r["requested_at"])}</td><td><div class="actions">{export}{complete}{anonym}</div></td></tr>'
        if not open_items:body+='<tr><td colspan="4" class="empty">No open privacy requests.</td></tr>'
        body+='</tbody></table></div>'+app.notice('Anonymisation is intentionally irreversible in the application. Keep required financial/order records only as permitted by your legal retention obligations.','warn')
        self.send_html(app.layout('Privacy & data requests',body,'privacy'))

    def locations_page(self,q):
        import app
        rows=pc.locations();brands=pc.brands();alerts=pc.stock_alerts(50)
        body=app.pagehead('Stock & locations','Manage physical stock locations and the inventory held at each one.',app.button('Customer selections','/showrooms','secondary'))
        body+=app.notice('Physical stock locations are different from Customer selections. A physical showroom or warehouse holds inventory; a Customer selection is a digital product selection you can share with a prospect.')
        if q.get('brand_saved'):body+=app.notice('Brand defaults saved.','success')
        body+='<div class="stock-layout"><section class="card"><div class="section-head"><div><h2>Physical locations</h2><p class="helper">Warehouses, studios and physical showrooms where stock is actually held.</p></div></div><div class="table-wrap"><table><thead><tr><th>Location</th><th>Type</th><th>Status</th><th>City / country</th><th>On hand</th><th>Reserved</th><th>Low stock</th><th></th></tr></thead><tbody>'
        for r in rows:
            body+=f'<tr><td><strong>{app.e(r["name"])}</strong><br><span class="tiny muted">{app.e(r.get("brand_name") or "No brand assigned")}</span></td><td>{app.e("Physical showroom" if r["location_type"]=="Showroom" else r["location_type"])}</td><td><span class="pill {"good" if (r.get("status") or "Active")=="Active" else "warn"}">{app.e(r.get("status") or "Active")}</span></td><td>{app.e(" / ".join(x for x in [r.get("city"),r.get("country")] if x) or "—")}</td><td>{int(r.get("on_hand") or 0)}</td><td>{int(r.get("reserved") or 0)}</td><td>{int(r.get("low_stock_skus") or 0)}</td><td>{app.button("Manage","/locations/"+r["id"],"secondary small")}</td></tr>'
        if not rows:body+='<tr><td colspan="8"><div class="empty-action"><strong>No physical stock locations yet</strong><span class="helper">Add your first warehouse, studio or physical showroom using the form on this page.</span></div></td></tr>'
        body+='</tbody></table></div></section><aside class="card"><div class="eyebrow">ADD A LOCATION</div><h2>Where is stock held?</h2><p class="helper">Start with the place you physically store or sell products. You can add stock quantities after saving it.</p><form method="post" action="/locations/save" class="section"><div class="formgrid"><label class="field">Location name<input name="name" placeholder="Example: Reading stock room" required></label><label class="field">Type<select name="location_type">'+app.options([('Warehouse','Warehouse'),('Showroom','Physical showroom'),('Studio','Studio'),('Consignment','Consignment'),('Other','Other')],'Warehouse')+'</select></label><label class="field">Country<input name="country"></label><label class="field">City<input name="city"></label><label class="field">Timezone<input name="timezone" placeholder="Europe/London"></label><label class="field">Brand<select name="brand_id">'+app.options([(b['id'],b['name']) for b in brands],'', 'No specific brand')+'</select></label><label class="field" style="grid-column:1/-1">Address<textarea name="address" rows="2"></textarea></label></div><div class="form-foot"><button class="btn">Add physical location</button></div></form></aside></div>'
        body+='<details class="manual-entry brand-details"><summary>Optional: brand defaults</summary><div class="manual-body"><p class="helper section">Only use this if you operate multiple brands or need a separate currency/language default for a brand.</p><form method="post" action="/brands/save" class="formgrid"><label class="field">Brand name<input name="name" required></label><label class="field">Default currency<input name="currency" value="INR" maxlength="8"></label><label class="field">Default language<input name="language" value="English"></label><div><button class="btn secondary">Save brand defaults</button></div></form></div></details>'
        if alerts:
            body+='<div class="card section"><h2>Stock needing attention</h2><p class="helper">Products at or below their reorder point.</p><table><thead><tr><th>Product</th><th>Location</th><th>Available</th><th>Reorder point</th></tr></thead><tbody>'
            for a in alerts:body+=f'<tr><td>{app.e(a.get("public_product_name") or a.get("internal_sku") or a["product_id"])}</td><td>{app.e(a["location_name"])}</td><td>{int(a["on_hand"])-int(a["reserved"])}</td><td>{int(a["reorder_point"])}</td></tr>'
            body+='</tbody></table></div>'
        self.send_html(app.layout('Stock & locations',body,'locations'))

    def location_detail(self,lid,q):
        import app
        loc=m.one('SELECT * FROM v9_locations WHERE id=?',(lid,))
        if not loc:raise ValueError('Stock location not found.')
        inv=pc.location_inventory(lid);brands=pc.brands()
        body=app.pagehead(loc['name'],'Manage this physical location and the stock held here.',app.button('All stock locations','/locations','secondary'))
        if q.get('saved'):body+=app.notice('Location details saved.','success')
        if q.get('stock_saved'):body+=app.notice('Stock updated.','success')
        body+='<div class="two"><section class="card"><div class="message-top"><div><div class="eyebrow">LOCATION</div><h2>Location details</h2></div><span class="pill '+('good' if (loc.get('status') or 'Active')=='Active' else 'warn')+'">'+app.e(loc.get('status') or 'Active')+'</span></div><form method="post" action="/locations/save"><input type="hidden" name="id" value="'+app.e(lid)+'"><div class="formgrid">'+app.field('Name','<input name="name" value="'+app.e(loc['name'])+'" required>')+app.field('Type','<select name="location_type">'+app.options([('Warehouse','Warehouse'),('Showroom','Physical showroom'),('Studio','Studio'),('Consignment','Consignment'),('Other','Other')],loc['location_type'])+'</select>')+app.field('Status','<select name="status">'+app.options(['Active','Inactive'],loc.get('status') or 'Active')+'</select>')+app.field('Brand','<select name="brand_id">'+app.options([(b['id'],b['name']) for b in brands],loc.get('brand_id') or '', 'No specific brand')+'</select>')+app.field('Country','<input name="country" value="'+app.e(loc.get('country') or '')+'">')+app.field('City','<input name="city" value="'+app.e(loc.get('city') or '')+'">')+app.field('Timezone','<input name="timezone" value="'+app.e(loc.get('timezone') or '')+'" placeholder="Europe/London">')+'</div>'+app.field('Address','<textarea name="address">'+app.e(loc.get('address') or '')+'</textarea>')+'<div class="form-foot"><button class="btn secondary">Save location details</button></div></form></section><section class="concept-card"><h3>Physical location</h3><p>This record is for real inventory. It is not the same as a Customer selection, which is a digital product selection created for a prospect.</p><div class="section">'+app.button('Open customer selections','/showrooms','secondary')+'</div></section></div>'
        body+='<div class="card section"><div class="section-head"><div><h2>Stock at this location</h2><p class="helper">On hand is physical stock. Reserved stock cannot exceed on-hand stock.</p></div></div><div class="table-wrap"><table><thead><tr><th>Product</th><th>On hand</th><th>Reserved</th><th>Reorder point</th><th>Available</th><th></th></tr></thead><tbody>'
        for r in inv:
            body+=f'''<tr><td><strong>{app.e(r.get('public_product_name') or r.get('internal_sku') or r['product_id'])}</strong><br><span class="tiny muted">{app.e(r.get('internal_sku') or '')}</span></td><td colspan="5"><form method="post" action="/locations/{app.e(lid)}/inventory" class="actions"><input type="hidden" name="product_id" value="{app.e(r['product_id'])}"><input type="number" aria-label="On hand" name="on_hand" min="0" value="{int(r['on_hand'])}" style="width:90px"><input type="number" aria-label="Reserved" name="reserved" min="0" value="{int(r['reserved'])}" style="width:90px"><input type="number" aria-label="Reorder point" name="reorder_point" min="0" value="{int(r['reorder_point'])}" style="width:90px"><span class="pill">{int(r['on_hand'])-int(r['reserved'])} available</span><button class="btn secondary small">Save stock</button></form></td></tr>'''
        if not inv:body+='<tr><td colspan="6"><div class="empty-action"><strong>No active products to stock</strong><span class="helper">Add or restore products first, then return here to set stock quantities.</span>'+app.button('Open products','/products','secondary small')+'</div></td></tr>'
        body+='</tbody></table></div></div>'
        self.send_html(app.layout('Location stock',body,'locations'))

    def e2e_page(self,q):
        import app
        run_id=q.get('run',[''])[0];run=pc.e2e_run(run_id) if run_id else pc.latest_e2e()
        body=app.pagehead('End-to-end operational test','A non-destructive audit of the actual local pipeline and verified external connections. It never sends, publishes, charges or changes ad budgets.','<form method="post" action="/e2e-test/run"><button class="btn">Run operational test</button></form>')
        if not run:body+='<div class="card section empty">No operational test has been run yet.</div>'
        else:
            body+=f'<div class="card section"><div class="message-top"><div><span class="pill {"good" if run["status"]=="Pass" else "warn"}">{app.e(run["status"])}</span><h2>Run {app.e(run["id"])}</h2><p class="helper">Started {app.e(run["started_at"])} · finished {app.e(run["finished_at"] or "Running")}</p></div></div></div><div class="card section"><table><thead><tr><th>#</th><th>System step</th><th>Status</th><th>Evidence</th></tr></thead><tbody>'
            for s in run['steps']:body+=f'<tr><td>{s["step_no"]}</td><td><strong>{app.e(s["label"])}</strong></td><td><span class="pill {"good" if s["status"]=="Pass" else "warn"}">{app.e(s["status"])}</span></td><td>{app.e(s["detail"])}</td></tr>'
            body+='</tbody></table></div>'
        self.send_html(app.layout('End-to-end test',body,'e2e'))
