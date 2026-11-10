"""V4.2 screens: contact entry, staged imports, sequences and saved audiences."""
from __future__ import annotations
import html
import json
import urllib.parse
from pathlib import Path
import marketing as m
import contact_tools as ct
import outreach as o
from release_info import RELEASE_LABEL

def e(v):return html.escape('' if v is None else str(v),quote=True)
def field(label,control,hint=''):
    return f'<label class="field">{e(label)}{control}'+(f'<small>{e(hint)}</small>' if hint else '')+'</label>'
def opts(items,current='',empty=None):
    result=f'<option value="">{e(empty)}</option>' if empty is not None else ''
    for item in items:
        v,label=item if isinstance(item,tuple) else (item,item)
        result+=f'<option value="{e(v)}" {"selected" if str(v)==str(current) else ""}>{e(label)}</option>'
    return result

def note(text):return '<div class="note info">'+e(text)+'</div>'
def link(text,url,kind='secondary'):return f'<a class="btn {kind}" href="{e(url)}">{e(text)}</a>'
def title(name,sub,actions=''):
    return f'<div class="top"><div><h1>{e(name)}</h1><p class="sub">{e(sub)}</p></div><div class="actions">{actions}</div></div>'

def personalisation_fields(raw=None,journey='B2B'):
    v={**o.defaults(journey),**(raw or {})}
    templates=m.rows('SELECT id,name,audience,channel FROM m41_templates ORDER BY name')
    h='<details class="personalise-box" open><summary><strong>Personalisation &amp; follow-up plan</strong></summary><div class="formgrid section">'
    h+=field('Greeting style','<select name="greeting">'+opts([('full','Full name'),('first','First name (only when recorded)'),('company','Company name'),('neutral','Neutral greeting')],v['greeting'])+'</select>','Missing names use a neutral greeting. No name guessing.')
    h+=field('Message length','<select name="length">'+opts(['Concise','Standard'],v['length'])+'</select>')
    h+=field('Confirmed preferences','<select name="use_preferences">'+opts([('yes','Use confirmed preferences'),('no','Do not use customer preferences')],v['use_preferences'])+'</select>')
    h+=field('Reusable sequence','<select name="template_id">'+opts([(t['id'],t['name']+' / '+t['audience']+' / '+t['channel']) for t in templates],v['template_id'],empty='Use built-in playbook')+'</select>','Custom templates affect local drafting. AI uses the campaign brief and approved knowledge instead.')
    h+=field('Follow-up 1: day after introduction',f'<input type="number" name="day1" value="{e(v["day1"])}" min="1" max="59" required>')
    h+=field('Follow-up 2: day after introduction',f'<input type="number" name="day2" value="{e(v["day2"])}" min="2" max="60" required>')
    h+=field('Sender name',f'<input name="sender_name" maxlength="100" value="{e(v["sender_name"])}" placeholder="Your sender name">')
    h+=field('Call-to-action wording',f'<input name="cta_text" maxlength="240" value="{e(v["cta_text"])}" placeholder="Example: Reply to discuss a wholesale collection">')
    h+='</div><div class="section">'+field('Optional public HTTPS destination',f'<input name="cta_url" maxlength="1000" value="{e(v["cta_url"])}" placeholder="Leave blank while your showroom is local">','Entering a link does not publish your CRM or showroom.')+'</div>'
    h+='<div class="section">'+field('Signature',f'<textarea name="signature" maxlength="500" rows="3" placeholder="Your name and business details">{e(v["signature"])}</textarea>')+'</div>'
    h+='<p class="helper">These are proposed follow-up days, not scheduled deliveries. Check replies, orders and opt-outs before any contact.</p></details>'
    return h

class ContactPages:
    def growth_page(self,name,body,active='contacts'):
        import app
        return self.send_html(app.layout(name,body,active))

    def contact_form(self,cid=None,q=None):
        v=ct.profile(cid) if cid else {};mode='Edit contact' if cid else 'Add a contact'
        body=title(mode,'Start with how you can identify or contact the person. Business context can be added only when useful.',link('Back to contacts','/contacts'))
        body+=f'<form method="post" action="/contacts/save"><input type="hidden" name="contact_id" value="{e(cid or "")}">'
        body+='<div class="two"><div class="card"><div class="eyebrow">ESSENTIALS</div><h2>Who is this?</h2><div class="formgrid">'
        body+=field('Full name',f'<input name="full_name" type="text" value="{e(v.get("full_name", ""))}" maxlength="254" placeholder="Person or business contact name">')
        body+=field('Email address',f'<input name="email" type="email" value="{e(v.get("email", ""))}" maxlength="254">')
        body+=field('Phone / WhatsApp number',f'<input name="phone_number" type="text" value="{e(v.get("phone_number", ""))}" maxlength="80">','Include +country code; this does not verify WhatsApp availability.')
        body+=field('Social username',f'<input name="username" type="text" value="{e(v.get("username", ""))}" maxlength="254">')
        body+=field('Customer journey','<select name="contact_type">'+opts(['Unknown','B2B','B2C','Both'],v.get('contact_type','Unknown'))+'</select>')
        body+='</div><p class="helper section">Add at least an email, phone or social username. Duplicates are checked across those identifiers, not by name alone.</p></div>'
        body+='<div class="card"><div class="eyebrow">ORGANISE</div><h2>Where did this contact come from?</h2>'
        body+=field('Source / list name',f'<input name="source_name" required maxlength="150" value="{e(v.get("source_name") or "Manual entry")}">','Examples: Website enquiries, Exhibition September, Supplier referrals.')
        body+='<div class="section">'+field('Tags',f'<input name="tags" maxlength="1800" value="{e(v.get("tags", ""))}" placeholder="boutique, bridal, September">','Comma-separated tags. Existing tags are retained when you edit.')+'</div>'
        body+=f'<p><label class="checkline"><input type="checkbox" name="do_not_contact" value="yes" {"checked" if v.get("qualification_status")=="Do Not Contact" else ""}>Mark as do not contact</label></p>'
        body+='<div class="form-foot"><button class="btn" type="submit">Save contact</button></div></div></div>'
        body+='<details class="manual-entry section"><summary>Name, business &amp; location details (optional)</summary><div class="manual-body"><div class="formgrid">'
        for label,key,typ in [('First name','first_name','text'),('Last name','last_name','text'),('Website','website','url'),('Company name','company_name','text'),('Job role','role_title','text'),('Country / region','country','text'),('Language','language','text'),('Business category','business_category','text')]:
            placeholder='https://...' if key=='website' else ''
            body+=field(label,f'<input name="{key}" type="{typ}" value="{e(v.get(key, ""))}" maxlength="254" placeholder="{placeholder}">')
        body+='</div><p class="helper">Company and role are personalisation fields. B2B account linking stays in the contact review screen.</p></div></details>'
        body+='<details class="manual-entry section"><summary>Notes &amp; source reference (optional)</summary><div class="manual-body">'
        body+=field('Source URL / reference',f'<input name="source_reference" value="{e(v.get("source_reference", ""))}" maxlength="1000">')
        body+='<div class="section">'+field('Internal notes',f'<textarea name="notes" maxlength="8000">{e(v.get("notes", ""))}</textarea>','These notes are not automatically sent to AI. Confirm customer preferences separately.')+'</div>'
        body+=note('New contacts start with Unknown channel permissions. This form cannot grant consent or clear an existing opt-out. Changing an email or number resets positive permission for that channel.')
        body+='</div></details><div class="form-foot section"><button class="btn" type="submit">Save contact</button>'+link('Cancel','/contacts')+'</div></form>'
        return self.growth_page(mode,body)

    def imports_home(self):
        body=title('Import contacts','Upload locally. Match your columns. Preview every decision. Then confirm.',link('Add one contact','/contacts/new'))
        body+='<div class="two"><div class="card"><div class="eyebrow">01 / Choose a file</div><h2>Bring your next audience into the CRM</h2><form method="post" action="/imports/upload" enctype="multipart/form-data" data-busy="Reading file...">'
        body+='<label class="upload-zone"><span class="upload-icon">&#8679;</span><strong>Choose a contact file</strong><span>CSV, TSV or XLSX / up to 15 MB and 50,000 rows per import</span><input name="contact_file" type="file" required accept=".csv,.tsv,.xlsx"><small>For XLSX: first worksheet, with headers in its first populated row. Formula rows are rejected.</small></label>'
        body+='<div class="form-foot"><button class="btn" type="submit">Upload &amp; match columns</button></div></form></div><div class="card"><h2>Your data, without the mess</h2><p class="helper">Start with a template or bring your existing export. You choose which columns enter the CRM. Keep phone numbers as text so spreadsheet software does not remove digits.</p><div class="actions">'+link('Download CSV template','/imports/template.csv')+link('Download Excel template','/imports/template.xlsx')+'</div><div class="section">'+note('No messages are sent and no permission is granted by an import. Existing data is backed up before confirmation. Skip duplicates is the default; conflicts are held for review.')+'</div></div></div>'
        jobs=m.rows('SELECT id,filename,status,created_at,report FROM m41_imports ORDER BY created_at DESC LIMIT 25')
        body+='<div class="section"><div class="section-head"><h2>Import history</h2><span class="helper">The latest 25 uploads</span></div><div class="table-wrap"><table><tr><th>File</th><th>Uploaded</th><th>Status</th><th>Summary</th><th>Review</th></tr>'
        for j in jobs:
            report=json.loads(j['report'] or '{}');summary=', '.join(f'{v} {k.lower()}' for k,v in report.get('counts',{}).items())
            body+=f'<tr><td>{e(j["filename"])}</td><td>{e(j["created_at"])}</td><td><span class="pill purple">{e(j["status"])}</span></td><td>{e(summary)}</td><td><a href="/imports/{e(j["id"])}">Open</a></td></tr>'
        if not jobs:body+='<tr><td colspan="5" class="empty">No contact imports yet. Your existing contacts are unchanged.</td></tr>'
        body+='</table></div></div>'
        return self.growth_page('Import contacts',body,'imports')

    def import_detail(self,jid,q=None):
        j=ct.job(jid);body=title(j['filename'],'Staged locally: no contact changes until you confirm.',link('Import history','/imports'))
        if j['status']=='Uploaded' or (j['status']=='Previewed' and q and q.get('remap')):
            data=json.loads(j['payload']);mapping=json.loads(j['mapping']) if j['mapping'] else ct.suggest_mapping(data['headers']);old=json.loads(j['options'] or '{}')
            body+='<ol class="steps"><li><span>1</span>Upload</li><li class="current"><span>2</span>Match columns</li><li><span>3</span>Preview &amp; import</li></ol>'
            for text in data['warnings']:body+=note(text)
            body+=f'<form method="post" action="/imports/{e(jid)}/preview"><div class="two"><div class="card"><h2>Match your columns</h2><p class="helper">{len(data["rows"]):,} rows found. Map each CRM field once. Fields left as Ignore are not imported.</p><div class="table-wrap"><table><tr><th>Your column</th><th>Example values</th><th>CRM field</th></tr>'
            for i,h in enumerate(data['headers']):
                examples=' / '.join((r['cells'][i] if i<len(r['cells']) else '')[:55] for r in data['rows'][:2])
                body+=f'<tr><td><strong>{e(h)}</strong></td><td class="tiny muted">{e(examples)}</td><td><select name="map_{i}">'+opts(list(ct.FIELDS.items()),mapping.get(str(i),''),empty='Ignore this column')+'</select></td></tr>'
            body+='</table></div></div><div class="card sticky-panel"><h2>Keep the list organised</h2>'
            body+=field('Source / list name',f'<input name="source" required maxlength="150" value="{e(old.get("source",Path(j["filename"]).stem))}">')
            body+='<div class="section">'+field('Tags for this import',f'<input name="tags" value="{e(", ".join(old.get("tags",[])))}" placeholder="boutique, September">')+'</div>'
            body+='<div class="section">'+field('When a row has no customer type','<select name="default_type">'+opts(['Unknown','B2B','B2C','Both'],old.get('default_type','Unknown'))+'</select>')+'</div>'
            body+='<div class="section">'+field('When a contact already exists','<select name="policy">'+opts([('skip','Skip changes to existing contact fields'),('fill','Fill empty fields only; never overwrite')],old.get('policy','skip'))+'</select>','Both modes record source membership and add tags. Different identifiers are held for review. Importing opt-outs can only restrict contact.')+'</div>'
            body+='<div class="section">'+note('Positive consent columns are deliberately not mappable. New contacts keep Unknown permissions. Use the contact review screen to document a valid channel basis.')+'</div>'
            body+='<div class="form-foot"><button class="btn" type="submit">Preview import</button></div></div></div></form>'
        elif j['status'] in {'Previewed','Completed'}:
            r=json.loads(j['report']);body+='<div class="import-stats">'
            for name in ['Add','Fill blanks','Duplicate','Suppress','Conflict','Invalid']:
                body+=f'<div class="card"><div class="label">{name if j["status"]=="Previewed" else {"Add":"Added","Fill blanks":"Filled blanks","Suppress":"Restricted"}.get(name,name)}</div><div class="value">{r["counts"].get(name,0):,}</div></div>'
            body+='</div>'
            if j['status']=='Completed':body+='<div class="section">'+note('Import completed. Your original records were not overwritten. A pre-import database backup is saved in this workspace\'s backups folder. No messages were sent.')+'</div><div class="actions section">'+link('View this source list','/contacts?'+urllib.parse.urlencode({'source':json.loads(j['options'])['source']}))+link('Import another file','/imports')+'</div>'
            else:
                body+=f'<div class="card section"><h2>Review, then confirm</h2><p class="helper">New records have Unknown marketing permissions. Duplicates add source membership and tags; existing non-empty fields stay unchanged. Invalid and conflicting rows are skipped. Identity checks run again on confirmation.</p><form method="post" action="/imports/{e(jid)}/commit" data-busy="Importing safely..."><label class="checkline"><input type="checkbox" name="confirm" value="1" required>I reviewed this plan and want to import its valid rows.</label><div class="form-foot">'+link('Change column mapping','/imports/'+jid+'?remap=1')+'<button class="btn" type="submit">Confirm contact import</button></div></form></div>'
            body+='<div class="section"><div class="section-head"><h2>Row-by-row review</h2><div class="actions">'+link('Download report CSV','/imports/'+jid+'/report.csv')+link('Download rejected rows','/imports/'+jid+'/rejected.csv')+'</div></div><p class="helper">Showing up to 50 rows; the downloadable report includes all decisions. Row numbers refer to populated data rows including the header.</p><div class="table-wrap"><table><tr><th>Row</th><th>Contact</th><th>Decision</th><th>Reason</th></tr>'
            for row in r['rows'][:50]:body+=f'<tr><td>{row["row"]}</td><td>{e(row["name"])}</td><td><span class="pill {"warn" if row["action"] in {"Invalid","Conflict"} else "purple"}">{e(row["action"])}</span></td><td>{e(row["reason"])}</td></tr>'
            body+='</table></div></div>'
        else:body+=note('This upload is '+j['status'].lower()+'. Start a new import to continue.')
        if j['status'] in {'Uploaded','Previewed'}:body+=f'<form class="section" method="post" action="/imports/{e(jid)}/cancel" data-confirm="Discard this staged upload? Existing CRM contacts are not changed."><button class="btn secondary">Discard staged upload</button></form>'
        return self.growth_page('Review import',body,'imports')

    def outreach_library(self):
        body=title('Outreach playbooks','Different conversations for stockists and individual buyers. Every playbook creates a draft plan.',link('My sequence templates','/templates')+link('Start a blank campaign','/campaigns/new',''))
        body+='<div class="channel-strip"><span class="pill purple">Email drafts + manual handoff</span><span class="pill good">WhatsApp drafts + manual handoff</span><span class="pill">Social DM scripts: planning only</span><span class="pill">SMS / phone scripts: planning only</span></div>'
        body+='<div class="campaign-grid section">'
        for code,aud,name,goal,brief in o.PLAYBOOKS:
            params={'audience':aud,'goal':goal,'brief':brief,'playbook':code}
            if code in {'reorder','feedback','reconnect'}:params['lifecycle']='Customer'
            url='/campaigns/new?'+urllib.parse.urlencode(params)
            body+=f'<a class="card recipe" href="{e(url)}"><span class="pill {aud.lower()}">{e(aud)}</span><h3>{e(name)}</h3><p>{e(brief)}</p><span class="arrow">Use this playbook &rarr;</span></a>'
        body+='</div><div class="section">'+note('Playbooks do not verify product claims or grant permission to contact anyone. Check the audience, knowledge sources and current channel status before any handoff.')+'</div>'
        return self.growth_page('Outreach playbooks',body,'outreach')

    def templates(self,q=None,tid=None):
        templates=m.rows('SELECT * FROM m41_templates ORDER BY updated_at DESC')
        body=title('Sequence templates','Write once, personalise per recipient, then review. Local templates are not AI.',link('Outreach playbooks','/outreach')+link('New sequence template','/templates/new',''))
        if tid=='new' or tid:
            t=m.one('SELECT * FROM m41_templates WHERE id=?',(tid,)) if tid!='new' else None
            if tid!='new' and not t:raise ValueError('Template not found.')
            t=t or {};msgs=json.loads(t['messages_json']) if t else [{'subject':'A collection for {{company_name}}','body':'{{greeting}}\n\nHello from {{brand}}. Would you like to explore {{collection}}?\n\n{{cta}}\n\n{{sender_name}}'}, {'subject':'A closer look?','body':'{{greeting}}\n\nA gentle follow-up from {{brand}}. Which styles would be useful to explore?\n\n{{cta}}'}, {'subject':'Shall we keep in touch?','body':'{{greeting}}\n\nA final note from {{brand}}. Shall we keep the conversation open, or leave it here for now?\n\n{{cta}}'}]
            body+=f'<form method="post" action="/templates/save"><input type="hidden" name="id" value="{e(t.get("id",""))}"><div class="two"><div class="card"><h2>Reusable three-message sequence</h2><div class="formgrid">'
            body+=field('Template name',f'<input name="name" value="{e(t.get("name",""))}" required maxlength="180">')
            body+=field('Customer journey','<select name="audience">'+opts(['B2B','B2C','Both'],t.get('audience','B2B'))+'</select>')
            body+=field('Channel','<select name="channel">'+opts(['Email','WhatsApp','Social DM','SMS','Phone'],t.get('channel','Email'))+'</select>')+'</div>'
            for i,msg in enumerate(msgs):
                body+=f'<div class="section"><h3>{["Introduction","Follow-up","Final check-in"][i]}</h3>'+field('Email subject (ignored for other channels)',f'<input name="subject{i}" maxlength="200" value="{e(msg["subject"])}">')
                body+='<div class="section">'+field('Message',f'<textarea name="body{i}" rows="7" maxlength="4000" required>{e(msg["body"])}</textarea>')+'</div></div>'
            body+='<div class="form-foot"><button class="btn">Save sequence template</button></div></div><div class="card sticky-panel"><h2>Available merge fields</h2><div class="token-grid">'+''.join('<code>{{'+e(k)+'}}</code>' for k in sorted(o.TOKENS))+'</div><p class="helper">Use the exact field spelling, including double braces. Only recorded names and roles are used; no identity or preference is inferred. Select this sequence in the campaign builder to preview actual recipients.</p>'+note('A missing first name becomes "there". Missing company uses "your business" for B2B. Unverified products are described generically. Keep {{brand}} in every message. Opt-out wording is appended automatically.')+'<div class="section">'+note('Editing this template does not overwrite existing drafts. Regenerate and review drafts that used it before handoff. Proposed timing is set per campaign.')+'</div></div></div></form>'
        else:
            body+='<div class="campaign-grid">'
            for t in templates:
                url='/campaigns/new?'+urllib.parse.urlencode({'audience':t['audience'],'channel':t['channel'],'template_id':t['id']})
                body+=f'<div class="card"><span class="pill purple">{e(t["audience"])}</span> <span class="pill">{e(t["channel"])}</span><h3>{e(t["name"])}</h3><p class="helper">Three locally personalised messages. Human review required.</p><div class="actions">'+link('Edit','/templates/'+t['id'])+link('Use in campaign',url,'')+'</div></div>'
            if not templates:body+='<div class="card empty"><h2>Your own reusable voice</h2><p>Create an email, WhatsApp, SMS or call-script sequence and reuse it across campaigns.</p>'+link('Create a sequence','/templates/new','')+'</div>'
            body+='</div>'
        return self.growth_page('Sequence templates',body,'outreach')

    def campaign_personalise(self,camid):
        cam=m.campaign(camid);raw=o.load(camid,cam['audience_type'])
        body=title('Personalise this campaign',cam['campaign_name'],link('Back to campaign','/campaigns/'+camid))
        body+=note('Saving these choices preserves existing drafts. Their handoff approval will need a fresh review after you regenerate them.')
        body+=f'<form method="post" action="/campaigns/{e(camid)}/personalise"><div class="card section">'+personalisation_fields(raw,cam['audience_type'])+'<div class="form-foot"><button class="btn">Save campaign choices</button></div></div></form>'
        return self.growth_page('Personalisation',body,'campaigns')

    def segments(self,preview=None):
        segments=m.rows('SELECT * FROM m41_segments ORDER BY created_at DESC');sources=m.rows('SELECT DISTINCT source FROM m41_sources ORDER BY source');taglist=m.rows('SELECT DISTINCT tag FROM m41_tags ORDER BY tag')
        body=title('Saved audiences','Reusable targeting rules, not a promise of permission. Membership is recalculated when you create a campaign.',link('All contacts','/contacts'))
        if preview:
            r=preview['result'];f=preview['filters']
            body+='<div class="card section audience-preview"><div class="section-head"><div><div class="eyebrow">PREVIEW ONLY</div><h2>'+f'{r["matching"]:,}'+' contacts match this planning view</h2><p class="helper">'+f'{r["eligible"]:,}'+' currently have documented permission for '+e(f['channel'])+'. '+f'{r["suppressed"]:,}'+' suppressed/blocked endpoint(s) were excluded.</p></div>'+link('Clear preview','/segments','secondary')+'</div>'
            if r['selected']:
                body+='<div class="preview-people">'+''.join('<span class="tag">'+e((c.get('full_name') or c.get('username') or c.get('email') or 'Unnamed contact'))+'</span>' for c in r['selected'][:8])+'</div>'
            body+='<p class="tiny muted section">Previewing never sends a message and does not change permission records.</p></div>'
        body+='<div class="two"><div><div class="campaign-grid">'
        for srow in segments:
            f=json.loads(srow['filters']);url='/campaigns/new?'+urllib.parse.urlencode(f)
            try:r=m.audience_preview(f);counts=f'{r["matching"]:,} match · {r["eligible"]:,} documented eligible'
            except Exception:counts='Recalculated when used'
            body+='<div class="card"><span class="pill purple">'+e(f['audience'])+'</span><h3>'+e(srow['name'])+'</h3><p class="helper">'+e(counts)+'<br>Source: '+e(f['source'] or 'All')+'<br>Tag: '+e(f.get('tag') or 'All')+'<br>Channel: '+e(f['channel'])+'</p>'+link('Plan campaign',url,'')+'</div>'
        if not segments:body+='<div class="card empty">Save your first reusable audience here. Preview it before you save so you can see the size and permission state.</div>'
        body+='</div></div><div class="card"><h2>Create a saved audience</h2><p class="helper">Choose the business rules first. Preview the result before saving or using it in a campaign.</p><form method="post" action="/segments/save"><div class="formgrid">'
        defaults=(preview or {}).get('filters',{})
        body+=field('Audience name','<input name="name" maxlength="180" placeholder="Example: September boutique leads">')
        body+=field('Customer journey','<select name="audience">'+opts(['B2B','B2C','Both'],defaults.get('audience','B2B'))+'</select>')
        body+=field('Channel','<select name="channel">'+opts(['Email','WhatsApp','Social DM','SMS','Phone'],defaults.get('channel','Email'))+'</select>')
        body+=field('Source / list','<select name="source">'+opts([r['source'] for r in sources],defaults.get('source',''),empty='All sources')+'</select>')
        body+=field('Tag','<select name="tag">'+opts([r['tag'] for r in taglist],defaults.get('tag',''),empty='All tags')+'</select>')
        body+=field('Customer stage','<select name="lifecycle">'+opts(['New','Contacted','Engaged','Qualified','Customer','Repeat Customer','Inactive'],defaults.get('lifecycle',''),empty='All stages')+'</select>')
        body+=field('Company/category search','<input name="search" value="'+e(defaults.get('search',''))+'" placeholder="Optional: boutique">')
        body+=field('Permission mode','<select name="scope">'+opts([('Preview','Planning preview (never sends)'),('Eligible','Documented permission only')],defaults.get('scope','Preview'))+'</select>')
        body+='</div><div class="form-foot"><button class="btn secondary" type="submit" formaction="/segments/preview" formnovalidate>Preview matches</button><button class="btn" type="submit">Save audience</button></div></form></div></div>'
        return self.growth_page('Saved audiences',body,'contacts')
