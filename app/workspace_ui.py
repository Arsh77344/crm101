"""Connected local CRM screens; original Marketing Studio retained underneath."""
from __future__ import annotations
import datetime as dt
import html
import json
import re
import shutil
import urllib.parse
import marketing as m
import db_layer
import contact_tools as ct
import crm_workspace as w
import record_lifecycle as lifecycle
import v24_ops as v24
import v35_truth as truth
from release_info import RELEASE_LABEL


def e(v):return html.escape('' if v is None else str(v),quote=True)
def url(path,params=None):return path+('?' + urllib.parse.urlencode({k:v for k,v in (params or {}).items() if v is not None}) if params else '')
def a(label,path,kind='secondary'):return f'<a class="btn {e(kind)}" href="{e(path)}">{e(label)}</a>'
def hidden(k,v):return f'<input type="hidden" name="{e(k)}" value="{e(v)}">'
def opt(values,current='',empty=None):
    s=f'<option value="">{e(empty)}</option>' if empty is not None else ''
    for item in values:
        value,label=item if isinstance(item,tuple) else (item,item)
        s+=f'<option value="{e(value)}" {"selected" if str(value)==str(current or "") else ""}>{e(label)}</option>'
    return s

def field(label,control,hint=''):return '<label class="field">'+e(label)+control+('<small>'+e(hint)+'</small>' if hint else '')+'</label>'
def inp(label,name,value='',typ='text',required=False,**attrs):
    at=' '.join(e(k.replace('_','-'))+'="'+e(v)+'"' for k,v in attrs.items())
    return field(label,f'<input type="{typ}" name="{e(name)}" value="{e(value)}" {"required" if required else ""} {at}>')
def select(label,name,values,current='',empty=None):return field(label,f'<select name="{e(name)}">'+opt(values,current,empty)+'</select>')
def area(label,name,value='',limit=4000):return field(label,f'<textarea name="{e(name)}" maxlength="{limit}" rows="4">{e(value)}</textarea>')
def note(text):return '<div class="note info">'+e(text)+'</div>'
def head(title,sub,actions=''):return f'<div class="top"><div><h1>{e(title)}</h1><p class="sub">{e(sub)}</p></div><div class="actions">{actions}</div></div>'
def pill(value,kind=''):return '<span class="pill '+e(kind)+'">'+e(value)+'</span>'
def cash(n,c='INR'):return e(c or 'Unspecified')+' '+format(float(n or 0),',.2f')
def empty(text):return '<div class="empty">'+e(text)+'</div>'
def metric(label,value,caption,path=''):
    return '<'+('a href="'+e(path)+'"' if path else 'div')+' class="card stat-card"><span class="stat-label">'+e(label)+'</span><strong>'+e(value)+'</strong><span class="helper">'+e(caption)+'</span></'+('a' if path else 'div')+'>'
def lookup(label,name,kind='Contact',value=''):
    names={'Contact':('contacts','contact_id','full_name'),'Deal':('opportunities','opportunity_id','name'),'Account':('companies','company_id','company_name')}
    if kind=='Campaign':
        r=truth.campaign(value) if value else None
        title=(r or {}).get('name','')
    else:
        table,col,title_col=names[kind];r=m.one('SELECT '+title_col+' title FROM '+table+' WHERE '+col+'=?',(value,)) if value else None;title=(r or {}).get('title','')
    return f'<div class="field lookup" data-lookup="{kind}"><label>{e(label)}<input class="lookup-input" role="combobox" aria-expanded="false" aria-autocomplete="list" autocomplete="off" placeholder="Search by name (2+ characters)" value="{e(title)}"></label>{hidden(name,value)}<div class="lookup-results" role="listbox" hidden></div><small>Choose a result to link it. Clearing the name clears the link.</small></div>'

def owner_select(label='Owner',current='',legacy_label=''):
    users=truth.active_users()
    values=[(u['user_id'],(u.get('display_name') or u.get('email') or u['user_id'])+' · '+(u.get('role') or 'User')) for u in users]
    control=select(label,'owner_user_id',values,current,'Unassigned')
    if legacy_label and not current:
        control+='<p class="helper">Historical owner label: '+e(legacy_label)+'. Choose a real user to convert the assignment.</p>'
    if not users:
        control+='<p class="helper">No active CRM users exist yet. <a href="/access-control">Create a user</a> before assigning ownership.</p>'
    return control
def task_fields(raw):
    return '<div class="formgrid">'+inp('Task','title',raw.get('title'),required=True,maxlength=200)+inp('Due date','due_date',raw.get('due_date') or dt.date.today().isoformat(),'date',True)+select('Priority','priority',w.PRIORITIES,raw.get('priority') or 'Normal')+select('Type','kind',w.KINDS,raw.get('kind') or 'Review')+owner_select('Owner',raw.get('owner_user_id',''),raw.get('owner',''))+select('Status','status',['Open','Done','Cancelled'],raw.get('status') or 'Open')+lookup('Contact','contact_id','Contact',raw.get('contact_id',''))+lookup('Deal','opportunity_id','Deal',raw.get('opportunity_id',''))+lookup('Campaign','campaign_id','Campaign',raw.get('campaign_id',''))+'</div>'+area('Notes','notes',raw.get('notes',''),2000)
def action_fields(raw=None):
    raw=raw or {}
    return select('Action','action',[('task','Create a follow-up task'),('owner','Assign an owner'),('tag','Add a tag'),('stage','Change customer stage'),('archive','Archive selected contacts')],raw.get('action') or 'task')+'<div class="action-fields" data-action-kind="task">'+inp('Task title','title',raw.get('title') or 'Review contact before outreach')+inp('Due in days','days',raw.get('days','2'),'number',min=0,max=365)+select('Task type','kind',w.KINDS,raw.get('kind') or 'Review')+'</div><div class="action-fields" data-action-kind="tag">'+inp('Tag to add','tag',raw.get('tag'),maxlength=100)+'</div><div class="action-fields" data-action-kind="stage">'+select('Customer stage','stage',w.LIFECYCLES,raw.get('stage') or 'New')+'</div><div class="action-fields" data-action-kind="owner task">'+owner_select('Owner',raw.get('owner_user_id',''),raw.get('owner',''))+'</div><div class="action-fields" data-action-kind="archive"><p class="helper">Selected contacts will move to Archived and remain in history. Existing permissions, activities, orders and deals are preserved.</p></div>'
class WorkspacePages:
    def workspace_page(self,title,body,active='dashboard'):
        import app
        return self.send_html(app.layout(title,body,active))

    def workspace_get(self,path,q):
        if path=='/today':self.dashboard()
        elif path=='/search':self.search_screen(q)
        elif path=='/api/record-search':
            v=q.get('q',[''])[0];kind=q.get('kind',['Contact'])[0]
            self.json_response([r for r in w.search(v) if r['type']==kind])
        elif path=='/properties':self.properties()
        elif path=='/reports':self.reports_page()
        elif path=='/reports.csv':
            report=w.reports();data=[['Metric','Category','Currency','Count','Amount','Basis']]
            data += [['Contacts',k,'',n,'','Stored records, not subscribers'] for k,n in report['contacts'].items()]
            data += [['Deals',r['stage'],r['currency'],r['n'],r['amount'],'Manually entered deal values'] for r in report['pipeline']]
            data += [['Orders',r['order_status'],r['currency'],r['n'],r['amount'],'Manual order ledger, not bank verification'] for r in report['orders']]
            self.send_file(ct.csv_bytes(data),'crm_report.csv')
        elif path=='/workflows':self.workflows()
        elif path=='/connections':self.connections()
        elif path=='/backups':self.backups(q)
        elif re.fullmatch(r'/backups/workspace_[a-zA-Z0-9_]+\.sqlite',path):
            p=m.DB.parent/'backups'/path.split('/')[-1]
            if not p.is_file():raise ValueError('Backup not found.')
            self.send_file(p.read_bytes(),p.name,'application/vnd.sqlite3')
        elif path=='/history':self.history_page(q)
        elif path=='/activity':self.activity_centre(q)
        elif re.fullmatch(r'/actions/[^/]+',path):self.action_preview(path.split('/')[2])
        elif path=='/opportunities/new':self.deal_form(q)
        elif re.fullmatch(r'/opportunities/[^/]+',path):self.deal_form(q,path.split('/')[2])
        elif path=='/orders/new':self.order_form(q)
        elif re.fullmatch(r'/orders/[^/]+',path):self.order_form(q,path.split('/')[2])
        elif path=='/companies/new':self.account_form(q)
        elif re.fullmatch(r'/companies/[^/]+',path):self.account_form(q,path.split('/')[2])
        elif path=='/tasks/new':self.task_form(q)
        elif re.fullmatch(r'/tasks/[^/]+/edit',path):self.task_form(q,path.split('/')[2])
        elif re.fullmatch(r'/contacts/[^/]+/review',path):self.classic_contact(path.split('/')[2])
        else:return False
        return True

    def workspace_post(self,path,f):
        raw={k:v[0] for k,v in f.items()};v=lambda k,d='':raw.get(k,d)
        if path=='/contacts/save':
            cid=v('contact_id') or None
            before=ct.profile(cid) if cid else None
            cid=ct.save_contact(raw,cid)
            with m.connect() as con:w.history(con,'Contact',cid,'Contact details saved',before,ct.profile(cid))
            self.redirect('/contacts/'+cid)
        elif re.fullmatch(r'/contacts/[^/]+/archive',path):
            cid=path.split('/')[2];lifecycle.archive_contact(cid);self.redirect('/contacts?state=active&archived=1')
        elif re.fullmatch(r'/contacts/[^/]+/restore',path):
            cid=path.split('/')[2];lifecycle.restore_contact(cid);self.redirect('/contacts/'+cid+'?restored=1')
        elif re.fullmatch(r'/contacts/[^/]+/update',path):
            cid=path.split('/')[2]
            if lifecycle.contact(cid).get('archived_at'):raise ValueError('Restore this contact before editing it.')
            old=m.contact(cid)
            fields={k:v(k) for k in ['contact_type','qualification_status','lifecycle_stage','country','language','niche','business_category']}
            w.choice(fields['contact_type'],['B2B','B2C','Both','Unknown'],'journey')
            w.choice(fields['qualification_status'],['Unreviewed','Qualified','Needs Review','Irrelevant','Do Not Contact'],'qualification')
            w.choice(fields['lifecycle_stage'],w.LIFECYCLES,'customer stage')
            fields={k:w.text(x,200) for k,x in fields.items()}
            with m.connect() as con:
                con.execute('UPDATE contacts SET '+','.join(k+'=?' for k in fields)+' WHERE contact_id=?',list(fields.values())+[cid])
                w.history(con,'Contact',cid,'Contact review updated',{k:old.get(k) for k in fields},fields)
            self.redirect('/contacts/'+cid)
        elif path=='/views/save':
            ident=w.save_view(raw);self.redirect('/contacts?view='+ident)
        elif path=='/views/delete':
            with m.connect() as con:con.execute('DELETE FROM m42_views WHERE id=?',(v('id'),))
            self.redirect('/contacts')
        elif path=='/contacts/bulk/preview':
            ident=w.plan_action(f.get('contact_ids',[]),raw);self.redirect('/actions/'+ident)
        elif re.fullmatch(r'/actions/[^/]+/apply',path):
            if v('confirm')!='1':raise ValueError('Review the affected records and confirm first.')
            ident=path.split('/')[2];w.apply_plan(ident);self.redirect('/actions/'+ident)
        elif re.fullmatch(r'/contacts/[^/]+/owner',path):
            cid=path.split('/')[2]
            if lifecycle.contact(cid).get('archived_at'):raise ValueError('Restore this contact before changing its owner.')
            w.set_owner(cid,v('owner_user_id'),v('owner'));self.redirect('/contacts/'+cid)
        elif re.fullmatch(r'/contacts/[^/]+/properties',path):
            cid=path.split('/')[2]
            if lifecycle.contact(cid).get('archived_at'):raise ValueError('Restore this contact before changing its properties.')
            w.save_properties(cid,raw);self.redirect('/contacts/'+cid+'?tab=properties')
        elif path=='/properties/create':w.field_def(raw);self.redirect('/properties')
        elif path=='/workflows/create':w.rule_save(raw);self.redirect('/workflows')
        elif re.fullmatch(r'/workflows/[^/]+/preview',path):
            ident=w.rule_preview(path.split('/')[2]);self.redirect('/actions/'+ident)
        elif path in {'/opportunities/save','/opportunities/create'}:
            ident=w.deal_save(raw,v('opportunity_id') or None);self.redirect('/opportunities/'+ident)
        elif re.fullmatch(r'/opportunities/[^/]+/stage',path):
            w.move_deal(path.split('/')[2],v('stage'),v('version'));self.redirect('/opportunities?pipeline='+urllib.parse.quote(v('pipeline','B2B')))
        elif path in {'/orders/save','/orders/create'}:
            products=f.get('line_product_id',[]);qtys=f.get('line_quantity',[]);prices=f.get('line_unit_price',[]);discounts=f.get('line_discount',[]);taxes=f.get('line_tax',[])
            n=max(len(products),len(qtys),len(prices),len(discounts),len(taxes),0);lines=[]
            for i in range(n):
                get=lambda xs: xs[i] if i<len(xs) else ''
                lines.append({'product_id':get(products),'quantity':get(qtys),'unit_price':get(prices),'discount':get(discounts),'tax':get(taxes)})
            ident=w.order_save(raw,v('order_id') or None,lines);self.redirect('/orders/'+ident)
        elif path=='/companies/save':
            ident=w.company_save(raw,v('company_id') or None);self.redirect('/companies/'+ident)
        elif re.fullmatch(r'/companies/[^/]+/archive',path):
            ident=path.split('/')[2];lifecycle.archive_company(ident);self.redirect('/companies?view=active&archived=1')
        elif re.fullmatch(r'/companies/[^/]+/restore',path):
            ident=path.split('/')[2];lifecycle.restore_company(ident);self.redirect('/companies/'+ident+'?restored=1')
        elif path=='/companies/link':
            w.link_account(v('contact_id'),v('company_id'),v('role'),v('primary')=='1');self.redirect('/companies/'+v('company_id'))
        elif path in {'/tasks/save','/tasks/create'}:
            w.task_save(raw,v('id') or None);self.redirect('/tasks')
        elif path in {'/tasks/status','/tasks/complete'}:
            w.task_status(v('id'),v('status','Done'));self.redirect('/tasks')
        elif path=='/tasks/bulk':
            count=w.bulk_tasks(f.get('task_ids',[]),v('bulk_action'),v('owner_user_id'))
            filt=v('filter','open')
            self.redirect('/tasks?filter='+urllib.parse.quote(filt)+'&bulk_done='+str(count)+'&bulk_action='+urllib.parse.quote(v('bulk_action')))
        elif path=='/activities/create':
            if v('follow_up_at') and not v('due_date'):raw['due_date']=v('follow_up_at')[:10]
            w.log_activity(raw);self.redirect('/contacts/'+v('contact_id'))
        elif path=='/backups/create':
            name=w.backup();self.redirect('/backups?created='+name)
        else:return False
        return True

    def dashboard(self):
        rep=w.reports();total=sum(rep['contacts'].values());summary=v24.daily_summary();business=m.settings().get('brand_name','Your business')
        attention=v24.attention_total(summary)
        headline='Some business checks need attention' if summary.get('degraded') else ('You are up to date' if attention==0 else 'Here is what needs your attention')
        body='<section class="owner-welcome"><div><p class="page-kicker">HOME</p><h1>'+e(headline)+'</h1><p>'+e(business)+' · Commerce Business OS has gathered the important work here so you do not need to check every section.</p></div><div class="actions">'+a('Add product','/products/new','')+a('Add customer','/contacts/new')+a('Create campaign','/campaign-builder')+'</div></section>'
        if summary.get('degraded'):
            body+=note('Some dashboard counts could not be verified. Open System health before relying on a zero shown here.')
        body+='<div class="stats-grid">'+metric('Due follow-ups',summary['tasks_due'],'Tasks due today or overdue','/tasks?filter=due')+metric('Products to review',summary['product_review'],'Products waiting for fact review','/products')+metric('Campaigns to review',summary['draft_campaigns'],'Unified campaign plans still in Draft','/campaign-builder')+metric('Orders to check',summary['pending_orders'],'Draft or pending orders','/orders')+metric('Low-stock products',summary['low_stock'],'Products with stock at 2 or below','/products?sort=stock_low')+metric('System alerts',summary.get('system_alerts',0),'Failed work or unresolved operational errors','/business-exceptions')+'</div>'
        body+='<div class="two section"><section class="card attention-card'+(' good' if attention==0 else '')+'"><div class="section-head"><div><h2>Needs your attention</h2><p class="helper">Decisions and exceptions that benefit from a person.</p></div>'+a('Open Needs Attention','/business-exceptions','secondary small')+'</div>'
        queue=[('Follow-ups due',summary['tasks_due'],'/tasks?filter=due','Review tasks'),('Products needing review',summary['product_review'],'/products','Review products'),('Campaigns still in draft',summary['draft_campaigns'],'/campaign-builder','Open campaigns'),('Orders waiting for action',summary['pending_orders'],'/orders','Review orders'),('Low-stock products',summary['low_stock'],'/products?sort=stock_low','Check stock'),('System alerts',summary.get('system_alerts',0),'/business-exceptions','Fix alerts')]
        for title,n,path,label in queue:
            if n:body+='<div class="readiness-row"><span class="round-number">'+str(n)+'</span><div class="row-main"><strong>'+e(title)+'</strong><small>'+str(n)+' item'+('' if n==1 else 's')+' waiting</small></div>'+a(label,path,'secondary small')+'</div>'
        if not any(n for _,n,_,_ in queue):body+=empty('Nothing urgent is waiting. You can continue preparing products, speaking with customers or planning marketing.')
        body+='</section><section class="card"><div class="section-head"><div><h2>Recently completed</h2><p class="helper">A simple record of what the system has changed.</p></div>'+a('View activity','/activity','secondary small')+'</div>'
        recent=v24.recent_business_activity(8)
        for r in recent:body+='<div class="readiness-row">'+pill(r['kind'])+'<div class="row-main"><a href="'+e(r.get('url') or '/activity')+'"><strong>'+e(r['title'])+'</strong></a><small>'+e(r['time'])+' · '+e(r['detail'])+'</small></div></div>'
        if not recent:body+=empty('No recent business changes yet. System maintenance stays in Recent activity and System health.')
        body+='</section></div>'
        body+='<div class="two section"><section class="card"><div class="section-head"><div><h2>Work queue</h2><p class="helper">See what is actively running and what has been prepared for you to start.</p></div></div>'
        running=0
        ai_state=m.ai_health();ai_ready=ai_state.get('status')=='Connected'
        if m.table_exists('v7_creative_jobs'):
            queued=int((m.one("SELECT count(*) n FROM v7_creative_jobs WHERE status IN ('Queued','Retry')") or {'n':0})['n'] or 0)
            processing=int((m.one("SELECT count(*) n FROM v7_creative_jobs WHERE status IN ('Processing','Running')") or {'n':0})['n'] or 0)
            running+=queued+processing
            if queued or processing:
                detail=[];path='/creative-studio';label='Open'
                if processing:detail.append(str(processing)+' image job(s) processing now')
                if queued:
                    if ai_ready:detail.append(str(queued)+' image job(s) ready to generate')
                    else:
                        detail.append(str(queued)+' image job(s) waiting for AI')
                        detail.append(str(ai_state.get('status') or 'AI not ready'))
                        path='/settings#ai';label='Fix AI'
                body+='<div class="readiness-row"><div class="row-main"><strong>Image generation queue</strong><small>'+e(' · '.join(detail))+'</small></div>'+a(label,path,'secondary small')+'</div>'
        if m.table_exists('v8_video_jobs'):
            local_q=int((m.one("SELECT count(*) n FROM v8_video_jobs WHERE status IN ('Queued','Retry') AND coalesce(provider,'local')<>'veo'") or {'n':0})['n'] or 0)
            veo_q=int((m.one("SELECT count(*) n FROM v8_video_jobs WHERE status IN ('Queued','Retry') AND provider='veo'") or {'n':0})['n'] or 0)
            processing=int((m.one("SELECT count(*) n FROM v8_video_jobs WHERE status IN ('Processing','Running')") or {'n':0})['n'] or 0)
            running+=local_q+veo_q+processing
            if local_q or veo_q or processing:
                detail=[]
                if processing:detail.append(str(processing)+' video job(s) processing now')
                if local_q:detail.append(str(local_q)+(' local video job(s) ready to render' if shutil.which('ffmpeg') else ' local storyboard job(s) ready; FFmpeg needed for MP4'))
                if veo_q:
                    try:
                        import creative_studio as cs
                        veo_ready=bool(cs.video_secret())
                    except Exception:veo_ready=False
                    detail.append(str(veo_q)+(' Veo job(s) ready to start' if veo_ready else ' Veo job(s) waiting for provider setup'))
                body+='<div class="readiness-row"><div class="row-main"><strong>Video generation queue</strong><small>'+e(' · '.join(detail))+'</small></div>'+a('Open','/creative-studio','secondary small')+'</div>'
        if m.table_exists('v12_worker_jobs'):
            queued=int((m.one("SELECT count(*) n FROM v12_worker_jobs WHERE status IN ('Queued','Retry')") or {'n':0})['n'] or 0)
            processing=int((m.one("SELECT count(*) n FROM v12_worker_jobs WHERE status IN ('Processing','Running')") or {'n':0})['n'] or 0)
            running+=queued+processing
            if queued or processing:
                detail=[]
                if processing:detail.append(str(processing)+' processing now')
                if queued:detail.append(str(queued)+' queued')
                body+='<div class="readiness-row"><div class="row-main"><strong>Background operations</strong><small>'+e(' · '.join(detail))+'</small></div>'+a('Open','/event-stream','secondary small')+'</div>'
        if not running:body+=empty('Nothing is running or waiting in the work queue right now.')
        body+='</section><section class="card"><div class="section-head"><div><h2>Business snapshot</h2><p class="helper">Stored operational records, not predictions.</p></div></div><div class="snapshot-grid">'+metric('Customers & leads',f'{total:,}','CRM records','/contacts')+metric('Open sales',summary['open_deals'],'Opportunities','/opportunities')+metric('Draft campaigns',summary['draft_campaigns'],'Still being prepared','/campaign-builder')+'</div></section></div>'
        self.workspace_page('Home',body,'today')

    def contacts(self,q):
        raw={k:v[0] for k,v in q.items()};view=None
        state=raw.get('state','active')
        if state not in {'active','archived','all'}:state='active'
        raw['record_state']=state
        if raw.get('view'):
            view=m.one('SELECT * FROM m42_views WHERE id=?',(raw['view'],))
            if view:raw={**json.loads(view['filters_json']),**{k:v for k,v in raw.items() if k not in {'view'}}}
        f,records=w.filter_contacts(raw)
        try:page=max(1,int(raw.get('page','1')))
        except ValueError:page=1
        total=len(records);page=min(page,max(1,(total+39)//40));shown=records[(page-1)*40:page*40]
        active_count=(m.one("SELECT count(*) n FROM contacts c LEFT JOIN m42_contact_meta cm USING(contact_id) WHERE cm.archived_at IS NULL") or {'n':0})['n']
        archived_count=(m.one("SELECT count(*) n FROM contacts c JOIN m42_contact_meta cm USING(contact_id) WHERE cm.archived_at IS NOT NULL") or {'n':0})['n']
        actions=a('Saved campaign audiences','/segments')+a('Import','/imports')
        if state!='archived':actions+=a('Add contact','/contacts/new','')
        body=head('Archived contacts' if state=='archived' else 'Contacts & audiences',f'{total:,} matching records / Archived contacts stay in history but are excluded from new outreach and CRM lookups.' if state=='archived' else f'{total:,} matching records / Select, organise and act without losing the relationship.',actions)
        body+='<nav class="view-tabs" aria-label="Contact views"><a href="/contacts?state=active" class="'+('selected' if state=='active' and not view else '')+'">Active ('+str(active_count)+')</a><a href="/contacts?state=archived" class="'+('selected' if state=='archived' and not view else '')+'">Archived ('+str(archived_count)+')</a>'
        for r in m.rows('SELECT * FROM m42_views ORDER BY name'):body+='<a class="'+('selected' if view and view['id']==r['id'] else '')+'" href="/contacts?view='+e(r['id'])+'">'+e(r['name'])+'</a>'
        body+='</nav>'
        if state!='archived':
            unassigned=sum(1 for c in records if not c.get('owner'))
            no_task=sum(1 for c in records if not c.get('task_due'))
            permission_unknown=sum(1 for c in records if c.get('permission_reason')=='Permission unknown')
            body+='<section class="crm-triage section"><div><span class="page-kicker">CRM TRIAGE</span><strong>Organise the current view</strong><small>These are workflow gaps, not reasons to send marketing.</small></div>'+a(str(unassigned)+' unassigned',url('/contacts',{'state':state,'owner':'__unassigned','channel':f['channel']}),'secondary small')+a(str(no_task)+' without next task',url('/contacts',{'state':state,'task':'missing','channel':f['channel']}),'secondary small')+a(str(permission_unknown)+' permission reviews',url('/contacts',{'state':state,'scope':'Unknown','channel':f['channel']}),'secondary small')+'</section>'
        body+='<form method="get" class="card compact-filter">'+hidden('state',state)+'<div class="filter-grid">'+inp('Search','search',f['search'],placeholder='Name, email, phone, company...')+select('Journey','type',['B2B','B2C','Both','Unknown'],f['type'],'All journeys')+select('Owner','owner',[('__unassigned','Unassigned')]+[(r['owner'],r['owner']) for r in m.rows("SELECT DISTINCT owner FROM m42_contact_meta WHERE owner<>'' ORDER BY owner")],f['owner'],'All owners')+select('Customer stage','stage',w.LIFECYCLES,f['stage'],'All stages')+select('Sort','sort',[('name','Name A–Z'),('name_desc','Name Z–A'),('recent','Newest first'),('oldest','Oldest first'),('priority','Keyword priority')],f['sort'])+'</div>'
        body+='<details class="section"><summary>Source, tags, channel review & custom filters</summary><div class="filter-grid section">'+select('Source','source',[(r['source'],r['source']) for r in m.rows('SELECT DISTINCT source FROM m41_sources ORDER BY source')],f['source'],'All sources')+select('Tag','tag',[r['tag'] for r in m.rows('SELECT DISTINCT tag FROM m41_tags ORDER BY tag')],f['tag'],'All tags')+select('Country / region hint','country',[r['country'] for r in m.rows("SELECT DISTINCT country FROM contacts WHERE coalesce(country,'')<>'' ORDER BY country")],f['country'],'All regions')+select('Channel','channel',['Email','WhatsApp','Social DM','SMS','Phone'],f['channel'])+select('Permission','scope',[('Eligible','Documented permission'),('Unknown','Permission unknown'),('Blocked','Other blocks / quality issues')],f['scope'],'All records')+select('Next task','task',[('missing','No open task'),('open','Has open task')],f['task'],'Any task state')+select('Custom property','property',[(r['id'],r['label']) for r in m.rows('SELECT * FROM m42_properties ORDER BY label')],f['property'],'No property filter')+inp('Property equals','property_value',f['property_value'])+'</div></details><div class="form-foot"><button class="btn">Apply filters</button>'+a('Reset','/contacts')+'</div></form>'
        body+='<div class="actions section"><details><summary>Save these filters as a view</summary><form method="post" action="/views/save" class="inline-form">'+''.join(hidden(k,v) for k,v in f.items())+inp('View name','name',required=True,maxlength=80)+'<button class="btn small">Save view</button></form></details>'
        if view:body+='<form method="post" action="/views/delete" data-confirm="Remove this saved view? Contact records stay unchanged.">'+hidden('id',view['id'])+'<button class="btn secondary small">Remove view</button></form>'
        body+='</div>'
        if state=='archived':body+='<div class="note warn section">Archived contacts are read-only and excluded from new outreach, workflows and lookup selectors. Restore a contact from its record before acting on it.</div>'
        body+='<form method="post" action="/contacts/bulk/preview" data-bulk><div class="selection-bar"><strong><span data-selection-count>0</span> selected</strong><span class="helper">Select this page only. No permission changes or deletions.</span><button type="button" class="btn secondary small" data-open-bulk>Choose action</button></div><div class="table-wrap compact-table"><table><thead><tr><th><input type="checkbox" data-select-page aria-label="Select this page"></th><th>Contact</th><th>Journey</th><th>Owner</th><th>Stage</th><th>'+e(f['channel'])+' review</th><th>Next task</th></tr></thead><tbody>'
        for c in shown:
            body+='<tr><td><input type="checkbox" name="contact_ids" value="'+e(c['contact_id'])+'" aria-label="Select '+e(c['full_name'])+'"></td><td><a class="contact-name" href="/contacts/'+e(c['contact_id'])+'">'+e(c['full_name'] or c['username'])+'</a><span class="tiny muted">'+e(c['email'] or c['phone_number'] or 'No email or phone')+'</span></td><td>'+pill(c['contact_type'],str(c['contact_type']).lower())+'</td><td>'+e(c['owner'] or 'Unassigned')+'</td><td>'+e(c['lifecycle_stage'])+'</td><td>'+pill(c['permission_reason'],'good' if c['eligible'] else 'warn')+'</td><td>'+e(c['task_due'] or '—')+'</td></tr>'
        if not shown:body+='<tr><td colspan="7">'+empty('No matching records. Adjust the filters or add a contact.')+'</td></tr>'
        body+='</tbody></table></div><details id="bulk-panel" class="card section"><summary>Choose an internal action for selected contacts</summary><div class="formgrid section" data-action-form>'+action_fields()+'</div><div class="form-foot"><button class="btn">Preview changes</button></div></details></form><div class="form-foot">'
        if page>1:body+=a('Previous',url('/contacts',{**f,'page':page-1}))
        body+='<span>Page '+str(page)+' of '+str(max(1,(total+39)//40))+'</span>'
        if page*40<total:body+=a('Next',url('/contacts',{**f,'page':page+1}))
        body+='</div><p class="helper section">B2B/B2C views include Both. Saved views store filters, not new copies of contacts. Channel checks also consider suppressed matching addresses.</p>'
        self.workspace_page('Contacts & audiences',body,'contacts')

    def contact(self,cid):
        c=ct.profile(cid);raw=m.contact(cid);meta=m.one('SELECT owner,owner_user_id,archived_at FROM m42_contact_meta WHERE contact_id=?',(cid,)) or {};owner=meta;q=getattr(self,'q',{});tab=q.get('tab',['timeline'])[0];archived=bool(meta.get('archived_at'))
        life=('<form method="post" action="/contacts/'+e(cid)+'/restore" data-confirm="Restore this contact to active CRM use? Existing channel permissions will stay unchanged."><button class="btn">Restore contact</button></form>' if archived else '<form method="post" action="/contacts/'+e(cid)+'/archive" data-confirm="Archive this contact? It will be removed from new outreach, workflows and lookups while history is preserved."><button class="btn secondary">Archive contact</button></form>')
        active_actions='' if archived else (a('Edit details','/contacts/'+cid+'/edit')+a('Review permissions','/contacts/'+cid+'/review')+a('Plan campaign',url('/campaigns/new',{'contact_id':cid,'audience':('B2C' if c['contact_type']=='B2C' else 'B2B')}),''))
        actions=active_actions+life
        body=head(c['full_name'] or c['username'],(c['contact_type'] or 'Unknown')+' / '+(c.get('source_name') or 'Source not recorded'),actions)
        if archived:body+=note('This contact is archived. Historical activities, campaigns, deals and orders remain visible, but the contact is excluded from new outreach and CRM selectors. Restore it before editing or acting on it.','warn')
        body+='<div class="record-layout"><section class="record-summary card"><div class="record-monogram">'+e((c['full_name'] or '?')[:1].upper())+'</div><h2>About this contact</h2><dl class="record-facts">'
        for label,value in [('Email',c.get('email')),('Phone',c.get('phone_number')),('Company field',c.get('company_name')),('Role',c.get('role_title')),('Customer stage',c.get('lifecycle_stage')),('Tags',c.get('tags')),('Country hint',c.get('country'))]:body+='<dt>'+e(label)+'</dt><dd>'+e(value or 'Not recorded')+'</dd>'
        if not archived:body+='</dl><form method="post" action="/contacts/'+e(cid)+'/owner">'+owner_select('Owner',owner.get('owner_user_id',''),owner.get('owner',''))+'<button class="btn secondary small section">Save owner</button></form><p class="helper section">Assignments now reference active CRM users; the old text label is retained only for history.</p>'
        else:body+='</dl><p class="helper section">Owner and profile edits are locked while this contact is archived.</p>'
        body+='</section><div class="record-main"><div class="quick-actions">'+a('Customer 360','/customer-360/'+e(cid))+(a('Log activity','#log-activity')+a('Add task',url('/tasks/new',{'contact_id':cid}))+a('Create deal',url('/opportunities/new',{'contact_id':cid,'pipeline':'B2C' if c['contact_type']=='B2C' else 'B2B'}))+a('Create showroom',url('/showrooms/new',{'contact_id':cid})) if not archived else '')+'</div>'
        body+='<nav class="view-tabs" aria-label="Contact tabs">'+''.join('<a class="'+('selected' if tab==t else '')+'" href="'+e(url('/contacts/'+cid,{'tab':t}))+'">'+label+'</a>' for t,label in [('timeline','Activity'),('marketing','Campaigns'),('properties','Properties')])+'</nav>'
        if tab=='properties':
            props=m.rows('SELECT p.*,v.value FROM m42_properties p LEFT JOIN m42_values v ON v.property_id=p.id AND v.contact_id=? ORDER BY p.label',(cid,))
            body+='<section class="card"><div class="top"><h2>Your contact properties</h2>'+a('Manage properties','/properties')+'</div><form method="post" action="/contacts/'+e(cid)+'/properties"><div class="formgrid">'
            for p in props:
                if p['kind']=='Dropdown':body+=select(p['label'],p['id'],json.loads(p['options_json']),p['value'],'Not recorded')
                else:body+=inp(p['label'],p['id'],p['value'],'date' if p['kind']=='Date' else 'text',maxlength=2000)
            body+='</div>'
            if props:body+='<button class="btn section">Save properties</button>'
            else:body+=empty('Add a custom property such as preferred collection, sourcing frequency or buying role.')
            body+='</form><p class="helper">Internal fields only. These values are not automatically sent to the AI provider or treated as consent.</p></section>'
        elif tab=='marketing':
            cams=m.rows('''SELECT ca.id campaign_id,ca.name campaign_name,ca.channels_json channel,coalesce(cm.member_status,'Linked') member_status,
              (SELECT count(*) FROM m4_drafts d WHERE d.campaign_id=ca.id AND d.contact_id=?) drafts
              FROM v10_unified_campaigns ca LEFT JOIN campaign_members cm ON cm.campaign_id=ca.id AND cm.contact_id=?
              WHERE cm.contact_id IS NOT NULL OR EXISTS (SELECT 1 FROM v10_campaign_sends s WHERE s.campaign_id=ca.id AND s.contact_id=?)
                 OR EXISTS (SELECT 1 FROM m42_deal_meta dm JOIN opportunities o ON o.opportunity_id=dm.deal_id WHERE o.contact_id=? AND coalesce(nullif(dm.canonical_campaign_id,''),dm.campaign_id)=ca.id)
                 OR EXISTS (SELECT 1 FROM m42_order_meta om JOIN orders oo ON oo.order_id=om.order_id WHERE oo.contact_id=? AND coalesce(nullif(om.canonical_campaign_id,''),om.campaign_id)=ca.id)
              ORDER BY ca.created_at DESC''',(cid,cid,cid,cid,cid))
            body+='<section class="card"><h2>Campaign involvement</h2>'
            for cam in cams:body+='<div class="readiness-row"><div class="row-main"><a href="/campaign-builder/'+e(cam['campaign_id'])+'">'+e(cam['campaign_name'])+'</a><small>'+e(cam['channel'])+' / '+str(cam['drafts'])+' drafts / '+e(cam['member_status'])+'</small></div></div>'
            if not cams:body+=empty('No campaigns linked. Planning a campaign does not mark this person as contacted.')
            body+='</section>'
        else:
            acts=m.rows('SELECT * FROM activities WHERE contact_id=? ORDER BY created_at DESC LIMIT 50',(cid,))
            changes=m.rows("SELECT * FROM m42_changes WHERE ((object_type='Contact' AND object_id=?) OR (related_object_type='Contact' AND related_object_id=?)) AND coalesce(event_scope,'business')='business' AND action<>'Activity logged' ORDER BY created_at DESC LIMIT 50",(cid,cid))
            events=[{'time':r['created_at'],'title':r['activity_type']+' / '+r['direction'],'text':r['summary'],'kind':'Manually logged'} for r in acts]
            events += [{'time':r['created_at'],'title':r['action'],'text':self.history_summary(r),'kind':'CRM change'} for r in changes]
            body+='<section class="card"><h2>Activity timeline</h2><p class="helper">Logged conversations and CRM actions. Not an inbox sync or delivery confirmation.</p>'
            for r in sorted(events,key=lambda r:r['time'],reverse=True)[:60]:body+='<article class="timeline-item"><div>'+pill(r['kind'])+' <time class="tiny muted">'+e(r['time'])+' UTC</time></div><h3>'+e(r['title'])+'</h3><p>'+e(r['text'])+'</p></article>'
            if not events:body+=empty('No activity yet. Add a note or log a real conversation below.')
            body+='</section>'
        if not archived:body+='<section class="card section" id="log-activity"><h2>Log a note or conversation</h2><form method="post" action="/activities/create">'+hidden('contact_id',cid)+'<div class="formgrid">'+select('Activity','activity_type',['Note','Email','WhatsApp','Call','Meeting','Follow-up'],'Note')+select('Direction','direction',['Internal','Inbound','Outbound'],'Internal')+select('Channel','channel',['Other','Email','WhatsApp','Social DM','Phone','Website','SMS'],'Other')+inp('Create follow-up task for','due_date','','date')+'</div>'+area('What happened?','summary')+'<details class="section"><summary>Link a deal or campaign</summary><div class="formgrid">'+lookup('Deal','opportunity_id','Deal')+lookup('Campaign','campaign_id','Campaign')+'</div></details><button class="btn section">Save activity</button></form></section>'
        body+='</div><div class="record-links">'
        accounts=m.rows('SELECT co.* FROM contact_companies cp JOIN companies co USING(company_id) WHERE cp.contact_id=? ORDER BY cp.is_primary DESC',(cid,))
        body+='<section class="card"><h3>B2B accounts</h3>'
        for r in accounts:body+='<p><a href="/companies/'+e(r['company_id'])+'">'+e(r['company_name'])+'</a></p>'
        if not accounts:body+='<p class="helper">No linked account.</p>'
        body+=a('Manage accounts','/companies','secondary small')+'</section><section class="card section"><h3>Open tasks</h3>'
        tasks=m.rows("SELECT * FROM m4_tasks WHERE contact_id=? AND status='Open' ORDER BY due_date LIMIT 5",(cid,))
        for r in tasks:body+='<p><a href="/tasks/'+e(r['id'])+'/edit">'+e(r['title'])+'</a><small class="tiny muted">Due '+e(r['due_date'])+'</small></p>'
        if not tasks:body+='<p class="helper">No open tasks.</p>'
        body+='</section><section class="card section"><h3>Deals</h3>'
        for r in m.rows('SELECT * FROM opportunities WHERE contact_id=? ORDER BY created_at DESC LIMIT 10',(cid,)):body+='<p><a href="/opportunities/'+e(r['opportunity_id'])+'">'+e(r['name'])+'</a><small class="tiny muted">'+e(r['stage'])+' / '+cash(r['estimated_value'],r['currency'])+'</small></p>'
        body+='</section><section class="card section"><h3>Channel review</h3>'
        pm=m.permissions_map();
        for ch in ['Email','WhatsApp']:
            ok,reason=m.eligibility(raw,ch,pm)
            if m.endpoint(raw,ch) in m.blocked_endpoints(pm,ch):ok,reason=False,'Matching address suppressed'
            body+='<p><strong>'+ch+'</strong><small class="tiny">'+pill(reason,'good' if ok else 'warn')+'</small></p>'
        body+=a('Review evidence','/contacts/'+cid+'/review','secondary small')+'</section></div></div>'
        self.workspace_page(c['full_name'],body,'contacts')

    def task_row(self,t):
        due=t['due_date'];late=due<dt.date.today().isoformat() and t['status']=='Open'
        choose='<label class="check compact-check" title="Select task for bulk action"><input type="checkbox" name="task_ids" value="'+e(t['id'])+'" form="task-bulk-form"><span class="visually-hidden">Select '+e(t['title'])+'</span></label>'
        body='<div class="readiness-row">'+choose+'<div class="row-main"><a href="/tasks/'+e(t['id'])+'/edit"><strong>'+e(t['title'])+'</strong></a><small>'+e(t.get('full_name') or 'General task')+' / '+e(t.get('owner') or 'Unassigned')+' / Due '+e(due)+'</small></div>'+pill('Overdue' if late else t['priority'],'warn' if late else '')
        body+='<div class="actions"><form method="post" action="/tasks/status">'+hidden('id',t['id'])+hidden('status','Done' if t['status']=='Open' else 'Open')+'<button class="btn secondary small">'+('Complete' if t['status']=='Open' else 'Reopen')+'</button></form>'
        if t['status']=='Open':body+='<form method="post" action="/tasks/status" data-confirm="Cancel this task? It will stay in task history and can be reopened.">'+hidden('id',t['id'])+hidden('status','Cancelled')+'<button class="btn secondary small">Cancel</button></form>'
        body+='</div></div>'
        return body

    def tasks(self,q):
        state=q.get('filter',['open'])[0];today=dt.date.today().isoformat();owner=q.get('owner',[''])[0]
        wh=[];args=[]
        if state=='done':wh.append("t.status='Done'")
        elif state=='cancelled':wh.append("t.status='Cancelled'")
        else:wh.append("t.status='Open'")
        if state=='due':wh.append('t.due_date<=?');args.append(today)
        if state=='upcoming':wh.append('t.due_date>?');args.append(today)
        if owner:wh.append('t.owner=?');args.append(owner)
        tasks=m.rows('SELECT t.*,c.full_name FROM m4_tasks t LEFT JOIN contacts c ON c.contact_id=t.contact_id WHERE '+' AND '.join(wh)+" ORDER BY due_date,CASE t.priority WHEN 'High' THEN 0 WHEN 'Normal' THEN 1 ELSE 2 END,t.created_at",args)
        body=head('Tasks & follow-ups',str(len(tasks))+' tasks in this view. Reminders stay inside this local CRM.',a('Add task','/tasks/new',''))
        if q.get('bulk_done'):
            label={'complete':'completed','reopen':'reopened','cancel':'cancelled','assign':'reassigned'}.get(q.get('bulk_action',[''])[0],'updated')
            body+=note(q['bulk_done'][0]+' selected task(s) '+label+'.')
        body+='<nav class="view-tabs">'+''.join('<a class="'+('selected' if state==v else '')+'" href="/tasks?filter='+v+'">'+label+'</a>' for v,label in [('open','Open'),('due','Due & overdue'),('upcoming','Upcoming'),('done','Completed'),('cancelled','Cancelled')])+'</nav>'
        body+='<form id="task-bulk-form" method="post" action="/tasks/bulk" class="card section">'+hidden('filter',state)+'<div class="formgrid">'+select('Bulk action','bulk_action',[('complete','Complete selected'),('reopen','Reopen selected'),('cancel','Cancel selected'),('assign','Assign selected')],'complete')+owner_select('Assign owner')+'</div><div class="form-foot"><button type="button" class="btn secondary" data-select-form="task-bulk-form">Select visible</button><button class="btn" data-confirm="Apply this action to the selected tasks?">Apply to selected</button></div><p class="helper">Up to 100 selected tasks are changed in one transaction. Cancelling preserves task history; tasks are not permanently deleted.</p></form><div class="card">'
        for t in tasks[:300]:body+=self.task_row(t)
        if not tasks:body+=empty('No tasks in this view. Create a linked follow-up from a contact, account or deal.')
        if len(tasks)>300:body+=note('Showing the first 300 tasks; use Due or Upcoming to narrow the worklist.')
        body+='</div>';self.workspace_page('Tasks & follow-ups',body,'tasks')

    def task_form(self,q,tid=None):
        t=m.one('SELECT * FROM m4_tasks WHERE id=?',(tid,)) if tid else {k:v[0] for k,v in q.items()}
        if tid and not t:raise ValueError('Task not found.')
        body=head('Edit task' if tid else 'Add a task','Link your next action to a contact, deal and campaign.',a('Back to tasks','/tasks'))+'<section class="card"><form method="post" action="/tasks/save">'+hidden('id',tid or '')+task_fields(t)+'<div class="form-foot"><button class="btn">Save task</button></div></form></section>'
        self.workspace_page('Task',body,'tasks')

    def opportunities(self):
        q=getattr(self,'q',{});pipeline=q.get('pipeline',['B2B'])[0];w.choice(pipeline,w.STAGES,'pipeline');mode=q.get('view',['board'])[0]
        meta_cols={r['name'] for r in m.rows("PRAGMA table_info(m42_deal_meta)")} if m.table_exists('m42_deal_meta') and not db_layer.USING_POSTGRES else {'pipeline','owner','owner_user_id','version','stage_changed_at'}
        owner_user_expr='d.owner_user_id' if 'owner_user_id' in meta_cols else "''"
        version_expr='d.version' if 'version' in meta_cols else '0'
        stage_changed_expr='d.stage_changed_at' if 'stage_changed_at' in meta_cols else "''"
        if m.table_exists('v11_users') and 'owner_user_id' in meta_cols:
            owner_display="coalesce(u.display_name,d.owner,'Unassigned')"
            user_join=' LEFT JOIN v11_users u ON u.user_id=d.owner_user_id '
        else:
            owner_display="coalesce(d.owner,'Unassigned')"
            user_join=' '
        deals=m.rows(f'''SELECT o.*,d.pipeline,d.owner,{owner_user_expr} owner_user_id,{version_expr} version,{stage_changed_expr} stage_changed_at,c.full_name,{owner_display} owner_display FROM opportunities o JOIN m42_deal_meta d ON d.deal_id=o.opportunity_id
          LEFT JOIN contacts c ON c.contact_id=o.contact_id {user_join} WHERE d.pipeline=? ORDER BY o.created_at DESC''',(pipeline,))
        body=head('Sales pipeline',str(len(deals))+' '+pipeline+' deals. A stage change does not send a message, create an order or confirm payment.',a('Add deal','/opportunities/new?pipeline='+pipeline,''))
        body+='<div class="top"><nav class="view-tabs">'+''.join('<a class="'+('selected' if p==pipeline else '')+'" href="'+e(url('/opportunities',{'pipeline':p,'view':mode}))+'">'+p+'</a>' for p in w.STAGES)+'</nav><div class="actions">'+a('Board',url('/opportunities',{'pipeline':pipeline,'view':'board'}))+a('Table',url('/opportunities',{'pipeline':pipeline,'view':'table'}))+'</div></div>'
        stages=w.STAGES[pipeline];unmapped=[d for d in deals if d['stage'] not in stages]
        if unmapped:body+=note(str(len(unmapped))+' legacy deals have stages outside this pipeline. They remain visible under Other / legacy; edit them to choose a current stage.')
        if mode=='table':
            body+='<div class="table-wrap compact-table"><table><thead><tr><th>Deal</th><th>Contact</th><th>Owner</th><th>Stage</th><th>Value</th><th>Expected close</th></tr></thead><tbody>'
            for d in deals:body+='<tr><td><a href="/opportunities/'+e(d['opportunity_id'])+'">'+e(d['name'])+'</a></td><td>'+e(d['full_name'] or 'Unlinked')+'</td><td>'+e(d.get('owner_display') or d.get('owner') or 'Unassigned')+'</td><td>'+e(d['stage'])+'</td><td>'+cash(d['estimated_value'],d['currency'])+'</td><td>'+e(d['expected_close_date'] or '—')+'</td></tr>'
            body+='</tbody></table></div>'
        else:
            body+='<div class="pipeline-scroll-note"><strong>Pipeline continues horizontally</strong><span>Use your trackpad, Shift + mouse wheel, or the scrollbar to reach Negotiation, Won and Lost.</span></div><p class="helper">Drag a card to a stage, or use its Move to menu. Won and Lost moves require confirmation. Different currencies are never added together.</p><div class="deal-board'+(' empty-board' if not deals else '')+'" data-board>'
            for stage in stages+(['Other / legacy'] if unmapped else []):
                cards=unmapped if stage=='Other / legacy' else [d for d in deals if d['stage']==stage]
                sums={}
                for d in cards:sums[d['currency'] or 'Unspecified']=sums.get(d['currency'] or 'Unspecified',0)+float(d['estimated_value'] or 0)
                body+='<section class="deal-lane" data-stage="'+e(stage)+'"><div class="lane-title"><h2>'+e(stage)+'</h2>'+pill(len(cards))+'</div><p class="lane-total">'+(' / '.join(cash(v,c) for c,v in sums.items()) or 'No deal value')+'</p>'
                for d in cards:
                    body+='<article class="deal-card" draggable="true" data-deal="'+e(d['opportunity_id'])+'"><a class="contact-name" href="/opportunities/'+e(d['opportunity_id'])+'">'+e(d['name'])+'</a><strong class="deal-value">'+cash(d['estimated_value'],d['currency'])+'</strong><p class="tiny muted">'+e(d['full_name'] or 'No linked contact')+'<br>'+e(d.get('owner_display') or d.get('owner') or 'Unassigned')+' / '+e(d['expected_close_date'] or 'No close date')+'</p><form method="post" action="/opportunities/'+e(d['opportunity_id'])+'/stage" data-move-form>'+hidden('version',d['version'])+hidden('pipeline',pipeline)+select('Move to','stage',stages,d['stage'])+'<button class="btn secondary small">Move</button></form><div class="actions section">'+a('Task',url('/tasks/new',{'opportunity_id':d['opportunity_id'],'contact_id':d['contact_id'] or ''}),'secondary small')+'</div></article>'
                if not cards:body+='<div class="lane-empty">No deals yet</div>'
                body+='</section>'
            body+='</div>'
        self.workspace_page('Sales pipeline',body,'opportunities')

    def deal_form(self,q,did=None):
        d=m.one("SELECT o.*,x.pipeline,x.owner,x.owner_user_id,coalesce(nullif(x.canonical_campaign_id,''),x.campaign_id) campaign_id,x.version FROM opportunities o JOIN m42_deal_meta x ON x.deal_id=o.opportunity_id WHERE opportunity_id=?",(did,)) if did else {k:v[0] for k,v in q.items()}
        if did and not d:raise ValueError('Deal not found.')
        pipeline=d.get('pipeline') or 'B2B';w.choice(pipeline,w.STAGES,'pipeline')
        body=head(d['name'] if did else 'Create a deal','Keep the contact, collection, campaign and next action connected.',a('Back to pipeline','/opportunities?pipeline='+pipeline))
        if did:body+='<div class="actions section">'+a('Add linked task',url('/tasks/new',{'opportunity_id':did,'contact_id':d.get('contact_id') or ''}))+a('Record an order',url('/orders/new',{'deal_id':did,'contact_id':d.get('contact_id') or '','campaign_id':d.get('campaign_id') or ''}))+'</div>'
        body+='<section class="card section"><form method="post" action="/opportunities/save">'+hidden('opportunity_id',did or '')+hidden('version',d.get('version',''))+'<div class="formgrid">'+inp('Deal name','name',d.get('name'),required=True)+select('Pipeline','pipeline',list(w.STAGES),pipeline)+select('Stage','stage',w.STAGES[pipeline],d.get('stage') or 'New')+owner_select('Owner',d.get('owner_user_id',''),d.get('owner',''))+lookup('Contact','contact_id','Contact',d.get('contact_id',''))+lookup('Originating campaign (manual attribution)','campaign_id','Campaign',d.get('campaign_id',''))+inp('Estimated value','estimated_value',d.get('estimated_value'),'number',min=0,step='0.01')+select('Currency','currency',w.CURRENCIES,d.get('currency') or m.settings().get('default_currency','INR'))+inp('Expected close','expected_close_date',d.get('expected_close_date'),'date')+select('Showroom','showroom_id',[(r['showroom_id'],r['title']) for r in m.rows("SELECT showroom_id,title FROM showrooms WHERE coalesce(status,'Draft') NOT IN ('Archived','Inactive') ORDER BY created_at DESC")],d.get('showroom_id'),'None')+'</div>'+area('Notes','notes',d.get('notes'))+'<p class="helper">Changing pipeline resets the stage selector to New. Original values remain in change history when you save.</p><div class="form-foot"><button class="btn">Save deal</button></div></form></section>'
        if did:body+=self.history_section('Deal',did)
        self.workspace_page('Deal',body,'opportunities')

    def companies(self):
        q=urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query);archived=(q.get('view') or ['active'])[0]=='archived'
        rows=m.rows("""SELECT co.*,(SELECT count(*) FROM contact_companies cp WHERE cp.company_id=co.company_id) contacts,
          (SELECT count(*) FROM opportunities o WHERE o.company_id=co.company_id AND stage NOT IN ('Won','Lost')) deals
          FROM companies co WHERE coalesce(co.status,'Active') """+('=' if archived else '<>')+""" 'Archived' ORDER BY company_name""")
        active=(m.one("SELECT count(*) n FROM companies WHERE coalesce(status,'Active')<>'Archived'") or {'n':0})['n'];arch=(m.one("SELECT count(*) n FROM companies WHERE status='Archived'") or {'n':0})['n']
        actions=a('Active accounts ('+str(active)+')','/companies?view=active','' if not archived else 'secondary')+a('Archived ('+str(arch)+')','/companies?view=archived','' if archived else 'secondary')
        if not archived:actions+=a('Add account','/companies/new','')
        body=head('Archived B2B accounts' if archived else 'B2B accounts',str(len(rows))+' '+('archived' if archived else 'active')+' accounts. Archived accounts stay in relationship history but cannot be selected for new links or deals.',actions)+'<div class="table-wrap compact-table"><table><thead><tr><th>Account</th><th>Type</th><th>Country</th><th>Contacts</th><th>Open deals</th></tr></thead><tbody>'
        for r in rows:body+='<tr><td><a class="contact-name" href="/companies/'+e(r['company_id'])+'">'+e(r['company_name'])+'</a><span class="tiny muted">'+e(r['website'])+'</span></td><td>'+e(r['company_type'])+'</td><td>'+e(r['country'])+'</td><td>'+str(r['contacts'])+'</td><td>'+str(r['deals'])+'</td></tr>'
        if not rows:body+='<tr><td colspan="5">'+empty('No archived accounts.' if archived else 'No accounts yet. Create one or link an existing B2B contact.')+'</td></tr>'
        body+='</tbody></table></div>';self.workspace_page('B2B accounts',body,'companies')

    def account_form(self,q,account=None):
        r=m.one('SELECT * FROM companies WHERE company_id=?',(account,)) if account else {}
        if account and not r:raise ValueError('Account not found.')
        archived=bool(account and (r.get('status') or 'Active')=='Archived')
        life=''
        if account:life=('<form method="post" action="/companies/'+e(account)+'/restore" data-confirm="Restore this account to active use?"><button class="btn">Restore account</button></form>' if archived else '<form method="post" action="/companies/'+e(account)+'/archive" data-confirm="Archive this account? Existing contacts, deals and activity will remain in history."><button class="btn secondary">Archive account</button></form>')
        body=head(r.get('company_name') or 'Create a B2B account','Account information, linked people and relationship history.',a('Back to accounts','/companies')+life)+'<div class="two"><section class="card"><h2>Account details</h2>'
        if archived:body+='<div class="note warn">This account is archived. It is retained for relationship history but excluded from new account links and automatic company association. Restore it before editing.</div><div class="section"><strong>'+e(r.get('company_name'))+'</strong><p class="helper">'+e(r.get('company_type'))+' / '+e(r.get('country'))+'<br>'+e(r.get('website'))+'</p></div>'
        else:body+='<form method="post" action="/companies/save">'+hidden('company_id',account or '')+'<div class="formgrid">'+inp('Account name','company_name',r.get('company_name'),required=True)+inp('Website','website',r.get('website'),typ='url')+inp('Business type','company_type',r.get('company_type'))+inp('Country (review before outreach)','country',r.get('country'))+inp('Wholesale tier','wholesale_tier',r.get('wholesale_tier'))+'</div>'+area('Notes','notes',r.get('notes'))+'<button class="btn section">Save account</button></form>'
        body+='</section><section class="card"><h2>Linked contacts</h2>'
        if account:
            contacts=m.rows('SELECT c.contact_id,c.full_name,cp.role_title,cp.is_primary FROM contact_companies cp JOIN contacts c USING(contact_id) WHERE cp.company_id=?',(account,))
            for c in contacts:body+='<div class="readiness-row"><div class="row-main"><a href="/contacts/'+e(c['contact_id'])+'">'+e(c['full_name'])+'</a><small>'+e(c['role_title'] or 'Role not recorded')+(' / Primary account' if c['is_primary'] else '')+'</small></div></div>'
            if not archived:body+='<form method="post" action="/companies/link" class="section">'+hidden('company_id',account)+lookup('Link a contact','contact_id')+inp('Role at account','role')+'<label class="checkline section"><input type="checkbox" name="primary" value="1">Make this the contact’s primary account and use its name for personalisation.</label><button class="btn secondary section">Link contact</button></form>'
            else:body+='<p class="helper section">Restore this account before linking new contacts.</p>'
        else:body+=empty('Save the account first, then link people.')
        body+='</section></div>'
        if account:
            body+='<section class="card section"><h2>Associated activity</h2>'
            for a1 in m.rows('SELECT a.*,c.full_name FROM activities a LEFT JOIN contacts c ON c.contact_id=a.contact_id WHERE a.company_id=? ORDER BY a.created_at DESC LIMIT 30',(account,)):body+='<div class="timeline-item"><strong>'+e(a1['activity_type'])+' / '+e(a1['full_name'])+'</strong><p>'+e(a1['summary'])+'</p><small>'+e(a1['created_at'])+' UTC / manually logged</small></div>'
            body+='<p class="helper">Activities logged after an account is linked can appear here. Older associations are not rewritten.</p></section>'
        self.workspace_page('B2B account',body,'companies')

    def orders(self):
        w.initial_schema()
        import integration_layer as _il
        _il.initialise()
        records=m.rows("""SELECT o.*,c.full_name,ca.name campaign_name,
          (SELECT count(*) FROM order_items oi WHERE oi.order_id=o.order_id) line_count
          FROM orders o LEFT JOIN contacts c ON c.contact_id=o.contact_id
          LEFT JOIN m42_order_meta x USING(order_id)
          LEFT JOIN v10_unified_campaigns ca ON ca.id=coalesce(nullif(x.canonical_campaign_id,''),x.campaign_id)
          ORDER BY o.ordered_at DESC""")
        body=head('Orders',str(len(records))+' orders. Physical sales now require product lines before Paid/Fulfilled states.',a('Create order','/orders/new',''))+'<div class="table-wrap compact-table orders-table"><table><thead><tr><th>Order</th><th>Contact</th><th>Status</th><th>Lines</th><th>Total</th><th>Campaign</th></tr></thead><tbody>'
        for r in records:
            integrity=' <span class="pill warn">Missing lines</span>' if r['order_status'] in {'Paid','Fulfilled'} and not int(r.get('line_count') or 0) else ''
            body+='<tr><td><a href="/orders/'+e(r['order_id'])+'">'+e(r['order_id'])+'</a>'+integrity+'</td><td>'+e(r['full_name'] or 'Unlinked')+'</td><td>'+pill(r['order_status'])+'</td><td>'+str(r.get('line_count') or 0)+'</td><td>'+cash(r['total'],r['currency'])+'</td><td>'+e(r['campaign_name'] or 'Unknown / Unattributed')+'</td></tr>'
        if not records:body+='<tr><td colspan="6">'+empty('No orders recorded. A won deal does not automatically become a paid order.')+'</td></tr>'
        body+='</tbody></table></div>';self.workspace_page('Orders',body,'orders')

    def order_form(self,q,oid=None):
        r=m.one("""SELECT o.*,x.deal_id,coalesce(nullif(x.canonical_campaign_id,''),x.campaign_id) campaign_id,x.attribution_note,x.version
                   FROM orders o LEFT JOIN m42_order_meta x USING(order_id) WHERE order_id=?""",(oid,)) if oid else {k:v[0] for k,v in q.items()}
        if oid and not r:raise ValueError('Order not found.')
        existing=m.rows("""SELECT oi.*,lm.unit_discount,lm.tax_amount,lm.line_total,lm.unit_cost_snapshot,lm.cost_source
                           FROM order_items oi LEFT JOIN v35_order_line_meta lm ON lm.order_item_id=oi.order_item_id
                           WHERE oi.order_id=? ORDER BY oi.order_item_id""",(oid,)) if oid else []
        products=m.rows("""SELECT p.product_id,coalesce(p.public_product_name,p.product_code,p.internal_sku,p.product_id) name,
                           p.retail_price,p.currency,coalesce(sum(i.on_hand-i.reserved),0) available
                           FROM products p LEFT JOIN v9_inventory i ON i.product_id=p.product_id
                           WHERE coalesce(p.status,'Draft')<>'Archived' GROUP BY p.product_id ORDER BY name COLLATE NOCASE""")
        pmap={x['product_id']:x for x in products}
        product_options=[(x['product_id'],f"{x['name']} · {int(x['available'] or 0)} available") for x in products]
        title='Edit order' if oid else 'Create order'
        body=head(title,'Record the actual products sold. Totals and downstream inventory work are derived from these transaction lines.',a('Back to orders','/orders'))
        if oid and r.get('order_status') in {'Paid','Fulfilled'} and not existing:
            body+=note('This is a migrated historical paid/fulfilled order with no product lines. The CRM keeps the history but flags it as incomplete instead of inventing products.')
        body+='<section class="card"><form method="post" action="/orders/save">'+hidden('order_id',oid or '')+hidden('version',r.get('version',''))+hidden('idempotency_key','' if oid else m.uid('IDEM36'))+'<div class="formgrid">'+lookup('Customer','contact_id','Contact',r.get('contact_id',''))+lookup('Deal','deal_id','Deal',r.get('deal_id',''))+lookup('Campaign / source (if known)','campaign_id','Campaign',r.get('campaign_id',''))+select('Order type','order_type',['B2B','B2C'],r.get('order_type') or 'B2C')+select('Status','order_status',['Draft','Pending','Paid','Fulfilled','Cancelled','Refunded'],r.get('order_status') or 'Draft')+select('Currency','currency',w.CURRENCIES,r.get('currency') or m.settings().get('default_currency','INR'))+inp('Payment or store reference','external_order_reference',r.get('external_order_reference'))+'</div>'
        body+='<div class="section"><div class="section-head"><div><h2>Products in this order</h2><p class="helper">Add the product, quantity and actual selling price. Discount and tax are optional line totals. Paid orders reserve canonical location stock.</p></div></div><div class="table-wrap"><table><thead><tr><th>Product</th><th>Qty</th><th>Unit price</th><th>Discount</th><th>Tax</th><th>Cost evidence</th></tr></thead><tbody>'
        rows=list(existing)
        while len(rows)<max(4,len(existing)+1):rows.append({})
        for line in rows:
            pid=line.get('product_id','');pr=pmap.get(pid,{})
            unit=line.get('unit_price') if line.get('unit_price') is not None else pr.get('retail_price')
            cost='Not captured yet'
            if line.get('unit_cost_snapshot') is not None:cost=(str(r.get('currency') or pr.get('currency') or '')+' '+format(float(line.get('unit_cost_snapshot') or 0),'.2f')+' · '+str(line.get('cost_source') or 'Recorded cost'))
            elif pid:
                pcost=truth.product_cost(pid);cost=('Missing cost data' if pcost.get('cost_price') is None else (str(pcost.get('currency') or '')+' '+format(float(pcost.get('cost_price') or 0),'.2f')+' · '+str(pcost.get('source') or 'Recorded cost')))
            body+='<tr><td><select name="line_product_id">'+opt(product_options,pid,'Choose product')+'</select></td><td><input name="line_quantity" type="number" min="0" step="1" value="'+e(line.get('quantity') or '')+'"></td><td><input name="line_unit_price" type="number" min="0" step="0.01" value="'+e(unit if unit is not None else '')+'"></td><td><input name="line_discount" type="number" min="0" step="0.01" value="'+e(line.get('unit_discount') or '')+'"></td><td><input name="line_tax" type="number" min="0" step="0.01" value="'+e(line.get('tax_amount') or '')+'"></td><td><span class="tiny muted">'+e(cost)+'</span></td></tr>'
        body+='</tbody></table></div><p class="helper section">Leave an unused row blank. The saved order total is calculated from quantity × unit price − discount + tax.</p></div>'+area('Attribution evidence / why this campaign or source is linked','attribution_note',r.get('attribution_note'),1000)+'<div class="form-foot"><button class="btn">Save order</button></div></form></section>'
        if oid:
            try:
                profit=truth.order_profitability(oid)
                status='Complete cost evidence' if profit['cost_complete'] else 'Profit incomplete · missing cost data'
                body+='<section class="card section"><h2>Transaction profitability</h2><div class="stats-grid">'+metric('Revenue',cash(profit['net_revenue'],profit['currency']),status)+metric('COGS',cash(profit['cogs'],profit['currency']),'Snapshotted at sale where available')+metric('Gross profit',cash(profit['gross_profit'],profit['currency']),('Margin '+format(profit['gross_margin_percent'],'.1f')+'%' if profit['gross_margin_percent'] is not None else 'No revenue'))+'</div></section>'
            except Exception:pass
            body+=self.history_section('Order',oid)
        self.workspace_page('Order',body,'orders')

    def properties(self):
        props=m.rows('SELECT * FROM m42_properties ORDER BY label')
        body=head('Custom contact properties','Add the business fields you need without changing code.',a('Contacts','/contacts'))+'<div class="two"><section class="card"><h2>Your properties</h2>'
        for r in props:body+='<div class="readiness-row"><div class="row-main"><strong>'+e(r['label'])+'</strong><small>'+e(r['kind'])+(' / '+e(', '.join(json.loads(r['options_json']))) if r['kind']=='Dropdown' else '')+'</small></div></div>'
        if not props:body+=empty('Examples: buying role, preferred collection, next buying date or typical order size.')
        body+='</section><section class="card"><h2>Add a property</h2><form method="post" action="/properties/create">'+inp('Property label','label',required=True,maxlength=100)+select('Type','kind',['Text','Number','Date','Dropdown'],'Text')+area('Dropdown choices (one per line)','options','','4000')+'<button class="btn section">Create property</button></form><p class="helper section">Use for operational facts, not sensitive profiling. A custom field cannot grant marketing permission. Fill values under each contact’s Properties tab.</p></section></div>'
        self.workspace_page('Custom properties',body,'properties')

    def action_preview(self,ident):
        p=m.one('SELECT * FROM m42_plans WHERE id=?',(ident,))
        if not p:raise ValueError('Action preview not found.')
        payload=json.loads(p['payload']);applied=p['status']=='Applied'
        body=head('Changes applied' if applied else 'Review before applying',p['kind']+' action / '+str(len(payload['contacts']))+' contacts / '+p['status'],a('Back to contacts','/contacts'))+note('Internal CRM action only. No emails, WhatsApp messages, permission grants or AI requests are made.')
        body+='<div class="card section"><h2>'+e(payload['action'].title())+'</h2><dl class="record-facts">'
        for k,v in payload['config'].items():body+='<dt>'+e(k.replace('_',' ').title())+'</dt><dd>'+e(v)+'</dd>'
        body+='</dl><h3 class="section">Affected contacts</h3><div class="preview-contacts">'
        for c in payload['contacts']:body+='<p><a href="/contacts/'+e(c['id'])+'">'+e(c['name'])+'</a></p>'
        body+='</div>'
        if not applied:body+='<form method="post" action="/actions/'+e(ident)+'/apply"><label class="checkline section"><input name="confirm" type="checkbox" value="1" required>I reviewed this action and these records.</label><p class="helper">This preview expires after 30 minutes. If a record changes before confirmation, the action is stopped for a fresh review.</p><button class="btn">Apply reviewed changes</button></form>'
        else:body+='<p class="helper">Reopening or refreshing this page will not apply the action a second time.</p>'
        body+='</div>';self.workspace_page('Review action',body,'workflows' if p['kind']=='Workflow' else 'contacts')

    def workflows(self):
        rules=m.rows('SELECT r.*,(SELECT count(*) FROM m42_enrolments e WHERE e.rule_id=r.id) enrolled FROM m42_rules r ORDER BY r.created_at DESC')
        body=head('Internal workflows','When records match your conditions, preview and apply one internal action.',a('Change history','/history'))+note('These are manually run, rule-based workflows—not AI agents or background automation. Each contact is processed once per workflow. No sending, consent changes or automatic task execution.')
        body+='<div class="two section"><section class="card"><h2>Your workflow recipes</h2>'
        for r in rules:
            cond=json.loads(r['conditions']);cfg=json.loads(r['config'])
            body+='<article class="workflow-card"><h3>'+e(r['name'])+'</h3><div class="workflow-step"><span>WHEN</span>'+e(' / '.join(k+': '+v for k,v in cond.items() if v))+'</div><div class="workflow-step"><span>THEN</span>'+e(r['action']+' / '+', '.join(k+': '+str(v) for k,v in cfg.items()))+'</div><small class="muted">'+str(r['enrolled'])+' contacts processed</small><form method="post" action="/workflows/'+e(r['id'])+'/preview" class="section"><button class="btn secondary">Preview next matches</button></form></article>'
        if not rules:body+=empty('Start with: B2B + New → create a review task in two days.')
        body+='</section><section class="card"><h2>Create a workflow</h2><form method="post" action="/workflows/create" data-action-form>'+inp('Workflow name','name',required=True,maxlength=200)+'<h3 class="section">Match all these conditions</h3>'+select('Journey','type',['B2B','B2C','Both','Unknown'],'','Any')+select('Customer stage','stage',w.LIFECYCLES,'','Any')+select('Has tag','tag_filter',[r['tag'] for r in m.rows('SELECT DISTINCT tag FROM m41_tags ORDER BY tag')],'','Any')+'<h3 class="section">Do this internal action</h3>'+action_fields()+'<button class="btn section">Save workflow</button></form><p class="helper section">Next preview shows up to 100 new matches. Saving the recipe does not run it. Do-not-contact records are excluded from workflow enrolment.</p></section></div>'
        self.workspace_page('Workflows',body,'workflows')

    def reports_page(self):
        rep=w.reports();tot=rep['contacts'];body=head('Reports','Actual local records. No estimated opens, deliveries or invented sales.',a('Export report CSV','/reports.csv'))
        body+='<div class="stats-grid">'+''.join(metric(k,format(v,','),'Stored '+k+' contacts',url('/contacts',{'type':k})) for k,v in tot.items())+'</div><div class="two section"><section class="card"><h2>Deal values by stage</h2><p class="helper">Unweighted pipeline totals, split by currency. Won is not cash received.</p>'
        for r in rep['pipeline']:body+='<div class="readiness-row"><div class="row-main"><strong>'+e(r['stage'])+'</strong><small>'+str(r['n'])+' deals</small></div><strong>'+cash(r['amount'],r['currency'])+'</strong></div>'
        if not rep['pipeline']:body+=empty('No deal values yet.')
        body+='</section><section class="card"><h2>Manual order ledger</h2><p class="helper">Paid, fulfilled, refunded and draft orders remain separate. Fulfilled does not establish payment.</p>'
        for r in rep['orders']:body+='<div class="readiness-row"><div class="row-main"><strong>'+e(r['order_status'])+'</strong><small>'+str(r['n'])+' orders</small></div><strong>'+cash(r['amount'],r['currency'])+'</strong></div>'
        if not rep['orders']:body+=empty('No recorded orders yet.')
        body+='</section></div><section class="card section"><h2>Campaign preparation</h2><div class="table-wrap compact-table"><table><thead><tr><th>Campaign</th><th>Channel</th><th>Planned contacts</th><th>Drafts</th><th>Approved</th><th>Delivered / replies</th></tr></thead><tbody>'
        for r in rep['campaigns']:body+='<tr><td><a href="/campaigns/'+e(r['campaign_id'])+'">'+e(r['campaign_name'])+'</a></td><td>'+e(r['channel'])+'</td><td>'+str(r['audience'])+'</td><td>'+str(r['drafts'])+'</td><td>'+str(r['approved'])+'</td><td>Not connected</td></tr>'
        if not rep['campaigns']:body+='<tr><td colspan="6">No campaign plans yet.</td></tr>'
        body+='</tbody></table></div></section><section class="card section"><h2>Explicit campaign attribution</h2><p class="helper">Only orders manually linked to a campaign. A showroom view or contact match does not attribute a sale.</p>'
        for r in rep['attribution']:body+='<div class="readiness-row"><div class="row-main"><strong>'+e(r['campaign_name'])+'</strong><small>'+str(r['orders'])+' orders / '+e(r['order_status'])+'</small></div><strong>'+cash(r['amount'],r['currency'])+'</strong></div>'
        if not rep['attribution']:body+=empty('No orders have been explicitly attributed to campaigns.')
        body+='</section>';self.workspace_page('Reports',body,'reports')

    def connections(self):
        return self.redirect('/integrations')

    def search_screen(self,q):
        term=q.get('q',[''])[0];rows=w.search(term)
        body=head('Search workspace','Find customers, companies, deals, campaigns, products, orders, tasks and customer selections.')+'<form method="get" action="/search" class="inline-form card">'+inp('Search','q',term,required=True)+'<button class="btn">Search</button></form><section class="card section">'
        for r in rows:body+='<div class="readiness-row">'+pill(r['type'])+'<div class="row-main"><a href="'+e(r['url'])+'">'+e(r['label'])+'</a><small>'+e(r['detail'])+'</small></div></div>'
        if not rows:body+=empty('Enter at least two characters, or try a different name.')
        body+='</section>';self.workspace_page('Search',body)

    def activity_centre(self,q):
        rows=v24.recent_activity(80)
        body=head('Recent activity','See what people and automations have changed recently.',a('Change history','/history')+a('System health','/system-health'))
        body+=note('This feed shows recorded system actions. It does not invent delivery, opens, customer views or payment events that an external provider has not confirmed.')
        body+='<section class="card section">'
        for r in rows:body+='<article class="timeline-item"><div>'+pill(r['kind'])+' <time class="tiny muted">'+e(r['time'])+'</time></div><h3><a href="'+e(r.get('url') or '/history')+'">'+e(r['title'])+'</a></h3><p>'+e(r['detail'])+'</p></article>'
        if not rows:body+=empty('No recorded activity yet. Actions will appear here as the OS processes real records.')
        body+='</section>';self.workspace_page('Recent activity',body,'activity')

    def history_summary(self,r):
        try:
            v=json.loads(r.get('after_json') or '{}') or {}
            if 'title' in v and 'due_date' in v:return str(v['title'])+' / Due '+str(v['due_date'])
            if 'name' in v and 'stage' in v:
                out=str(v['name'])+' / '+str(v['stage'])
                if v.get('value') is not None:out+=' / '+str(v.get('currency') or '')+' '+format(float(v['value']),',.2f')
                return out
            return ' / '.join(str(k).replace('_',' ').title()+': '+str(val) for k,val in v.items() if k not in {'contact_id','deal_id','task_id','plan_id','campaign_id','account_id','id','manually_logged'})[:1000]
        except (ValueError,AttributeError):return 'Record changed'

    def history_section(self,typ,ident):
        rows=m.rows('SELECT * FROM m42_changes WHERE object_type=? AND object_id=? ORDER BY created_at DESC LIMIT 40',(typ,ident))
        body='<section class="card section"><h2>Change history</h2>'
        for r in rows:body+='<div class="timeline-item"><strong>'+e(r['action'])+'</strong><small class="tiny muted">'+e(r['created_at'])+' UTC</small><p>'+e(self.history_summary(r))+'</p><details><summary>Before / after</summary><pre class="json-review">'+e(json.dumps({'before':json.loads(r['before_json']),'after':json.loads(r['after_json'])},indent=2,ensure_ascii=False))+'</pre></details></div>'
        if not rows:body+=empty('No changes recorded in this release yet. Earlier records are preserved.')
        return body+'</section>'

    def history_page(self,q):
        rows=m.rows('SELECT * FROM m42_changes ORDER BY created_at DESC LIMIT 150')
        body=head('Change history','The 150 most recent CRM record changes. This local history is not a tamper-proof compliance audit.')+'<section class="card">'
        for r in rows:body+='<div class="timeline-item">'+pill(r['object_type'])+' <strong>'+e(r['action'])+'</strong><small class="tiny muted">'+e(r['created_at'])+' UTC / '+e(r['object_id'])+'</small><p>'+e(self.history_summary(r))+'</p></div>'
        if not rows:body+=empty('No recorded workspace changes yet. Older version history is not reconstructed.')
        body+='</section>';self.workspace_page('Change history',body,'backups')

    def backups(self,q):
        folder=m.DB.parent/'backups';files=sorted(folder.glob('workspace_*.sqlite'),reverse=True) if (not db_layer.USING_POSTGRES and folder.exists()) else []
        body=head('Backups & history','Create a consistent snapshot without stopping the CRM.',a('Change history','/history'))+note('Database backups include customer data. Keep them private. Images and the separate API key are not included; keep a copy of your project’s static folder for a complete data backup.')
        body+='<section class="card section"><h2>Database snapshots</h2>'
        if db_layer.USING_POSTGRES:
            body+=note('This production workspace uses PostgreSQL. Browser SQLite snapshots are disabled; use the production full-backup workflow from System health.')+a('Open System health','/system-health','secondary')
        else:
            body+='<form method="post" action="/backups/create"><button class="btn">Create database backup</button></form><p class="helper section">Your active database is not overwritten. Restoring a backup is deliberately not a one-click browser action.</p>'
        for p in files[:30]:body+='<div class="readiness-row"><div class="row-main"><strong>'+e(p.name)+'</strong><small>'+format(p.stat().st_size/1024/1024,'.1f')+' MB / local SQLite snapshot</small></div>'+a('Download','/backups/'+p.name,'secondary small')+'</div>'
        if not files:body+=empty('No workspace snapshots created here yet. The first-run migration backup remains in the backups folder.')
        body+='</section>';self.workspace_page('Backups',body,'backups')
