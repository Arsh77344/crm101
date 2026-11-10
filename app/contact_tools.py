"""Local contact entry, conservative imports, provenance and saved audiences.
No delivery checks, enrichment requests, automatic permission grants or external calls.
"""
from __future__ import annotations
import collections
import csv
import datetime as dt
import hashlib
import io
import json
import os
import re
import sqlite3
import unicodedata
import zipfile
from decimal import Decimal, InvalidOperation
from pathlib import Path, PurePosixPath
from xml.etree import ElementTree as ET
import marketing as m

MAX_BYTES = 15 * 1024 * 1024
MAX_ROWS = 50000
MAX_COLUMNS = 80
MAX_CELL = 8000
CHANNELS = ('Email','WhatsApp','SMS','Phone','Other')
FIELDS = {
 'full_name':'Full name', 'first_name':'First name', 'last_name':'Last name',
 'email':'Email', 'phone_number':'Phone / WhatsApp number', 'username':'Social username',
 'contact_type':'B2B / B2C / Both / Unknown', 'company_name':'Company name', 'role_title':'Job role',
 'website':'Website', 'country':'Country (unverified)', 'language':'Language',
 'business_category':'Business category', 'source_reference':'Source URL / reference',
 'tags':'Tags (comma separated)', 'notes':'Internal notes', 'do_not_contact':'Do not contact / opt-out'
}
ALIASES = {
 'full_name':['name','fullname','full name','display name'], 'first_name':['first name','firstname'],
 'last_name':['last name','lastname','surname'], 'email':['email','email address','emails','public email'],
 'phone_number':['phone','phone number','mobile','mobile number','whatsapp','whatsapp number','telephone','contact number'],
 'username':['username','user name','instagram username','instagram handle','handle'],
 'contact_type':['type','contact type','b2b/b2c','b2b b2c','b2bb2c','customer type'],
 'company_name':['company','company name','business name'], 'role_title':['role','job title','designation'],
 'website':['website','website url','external url'], 'country':['country','country name'],
 'language':['language','preferred language'], 'business_category':['business category','category','niche'],
 'source_reference':['source reference','source url','source link'], 'tags':['tags','tag','source tag'],
 'notes':['notes','note','internal notes'], 'do_not_contact':['do not contact','opt out','opted out','unsubscribed','suppressed']
}
SCHEMA = '''
CREATE TABLE IF NOT EXISTS m41_profile(contact_id TEXT PRIMARY KEY, last_name TEXT, company_name TEXT, role_title TEXT, notes TEXT);
CREATE TABLE IF NOT EXISTS m41_tags(contact_id TEXT, tag TEXT COLLATE NOCASE, PRIMARY KEY(contact_id,tag));
CREATE INDEX IF NOT EXISTS m41_tag_lookup ON m41_tags(tag,contact_id);
CREATE TABLE IF NOT EXISTS m41_sources(contact_id TEXT, source TEXT, import_id TEXT, added_at TEXT DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY(contact_id,source));
CREATE INDEX IF NOT EXISTS m41_source_lookup ON m41_sources(source,contact_id);
CREATE TABLE IF NOT EXISTS m41_imports(id TEXT PRIMARY KEY, filename TEXT, status TEXT, payload TEXT, mapping TEXT, options TEXT, report TEXT, backup TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP, completed_at TEXT);
CREATE TABLE IF NOT EXISTS m41_suppressed_endpoints(channel TEXT, endpoint TEXT, reason TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY(channel,endpoint));
CREATE TABLE IF NOT EXISTS m41_segments(id TEXT PRIMARY KEY, name TEXT NOT NULL, filters TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
'''

def initialise():
    with m.connect() as con:
        con.executescript(SCHEMA)
        con.execute("INSERT OR IGNORE INTO m41_sources(contact_id,source) SELECT contact_id,source_name FROM contacts WHERE coalesce(source_name,'')<>''")
        con.execute("UPDATE m41_imports SET status='Expired',payload=NULL WHERE status IN ('Uploaded','Previewed') AND created_at<datetime('now','-1 day')")

def norm(value):
    return re.sub(r'[^a-z0-9]', '', unicodedata.normalize('NFKC', str(value)).lower())

def suggest_mapping(headers):
    mapping = {}
    used = set()
    for i, h in enumerate(headers):
        for key in FIELDS:
            if key not in used and norm(h) in {norm(key), *(norm(a) for a in ALIASES.get(key, []))}:
                mapping[str(i)] = key; used.add(key); break
    return mapping

def clean_text(value):
    s = unicodedata.normalize('NFC', '' if value is None else str(value)).replace('\x00','').strip()
    if len(s)>MAX_CELL: raise ValueError('A cell exceeds 8,000 characters.')
    return s

def clean_phone(value):
    raw=clean_text(value).lstrip("'")
    if not raw: return ''
    if re.fullmatch(r'\+?\d+\.0',raw): raw=raw[:-2]
    if 'e' in raw.lower():
        try:raw=format(Decimal(raw),'f')
        except InvalidOperation:pass
    raw=re.sub(r'[\s().-]','',raw)
    if raw.startswith('00'):raw='+'+raw[2:]
    if not re.fullmatch(r'\+?\d{8,15}',raw):raise ValueError('Phone must contain 8-15 digits; use an international +country code and no extension.')
    return raw

def tags(value):
    result=[]
    for t in re.split(r'[,;\n]',str(value or '')):
        t=clean_text(t)[:60]
        if t and t.casefold() not in {x.casefold() for x in result}:result.append(t)
    if len(result)>30:raise ValueError('Use at most 30 tags per record.')
    return result

def row_values(data, default_type='Unknown'):
    out={k:clean_text(data.get(k,'')) for k in FIELDS}
    out['email']=out['email'].lower()
    if out['email'] and (not re.fullmatch(r'[^\s@,;<>]+@[^\s@,;<>]+\.[^\s@,;<>]+',out['email']) or len(out['email'])>254):
        raise ValueError('Email is not a single correctly formatted address.')
    out['phone_number']=clean_phone(out['phone_number'])
    out['username']=out['username'].lstrip('@')
    if out['username'] and not re.fullmatch(r'[\w.\-]{1,100}',out['username']):raise ValueError('Use a social username, not a profile URL.')
    ct=out['contact_type'] or default_type
    types={'b2b':'B2B','business':'B2B','b2c':'B2C','consumer':'B2C','both':'Both','unknown':'Unknown'}
    if ct.lower() not in types:raise ValueError('Customer type must be B2B, B2C, Both or Unknown.')
    out['contact_type']=types[ct.lower()]
    # Remove spreadsheet/export wrapping quotes at ingestion so new records do not
    # carry display artefacts into CRM pages, campaign greetings or URLs.
    for key in ['full_name','first_name','last_name','company_name','role_title']:
        out[key]=clean_display_name(out[key])
    if not out['full_name']:out['full_name']=' '.join(s for s in [out['first_name'],out['last_name']] if s)
    if not any(out[k] for k in ['email','phone_number','username']):
        raise ValueError('Provide at least an email, phone number or social username to identify the contact.')
    if not out['full_name']:out['full_name']=out['company_name'] or out['username'] or out['email'] or out['phone_number']
    for key in ['full_name','first_name','last_name','company_name','role_title']:
        if len(out[key])>200 or '\n' in out[key] or '\r' in out[key]:raise ValueError('Names and roles must be single lines, under 200 characters.')
    if out['website'] and not re.match(r'^https?://[^\s]+$',out['website'],re.I):raise ValueError('Website must start with https:// or http://.')
    dnc=out['do_not_contact'].casefold()
    if dnc not in {'','0','false','no','n','1','true','yes','y','optedout','opted out','unsubscribed','suppressed'}:
        raise ValueError('Do not contact must be blank, yes/no, true/false or 1/0.')
    out['do_not_contact']=dnc in {'1','true','yes','y','optedout','opted out','unsubscribed','suppressed'}
    out['tags']=tags(out['tags'])
    return out

def _xml(blob):
    if re.search(br'<!\s*(DOCTYPE|ENTITY)',blob,re.I):raise ValueError('XML entities are not accepted in spreadsheets.')
    try:return ET.fromstring(blob)
    except ET.ParseError:raise ValueError('The spreadsheet XML could not be read.') from None

def _xlsx(data):
    """Read literal values in the first XLSX sheet. No macros/formulas/external fetches.
    Uses bounded ZIP/XML reading so installation needs only Python's standard library.
    """
    ns={'s':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
    try:z=zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:raise ValueError('This is not a valid XLSX file.') from None
    with z:
        members=z.infolist()
        if len(members)>2000 or sum(x.file_size for x in members)>100*1024*1024:raise ValueError('Spreadsheet expands beyond the 100 MB safety limit. Export a smaller CSV.')
        for item in members:
            if item.file_size>40*1024*1024 or (item.file_size>1024*1024 and item.file_size/max(1,item.compress_size)>300):
                raise ValueError('Spreadsheet compression exceeds the safety limit. Export a smaller CSV.')
            if item.flag_bits & 1:raise ValueError('Encrypted workbooks are not supported. Export unencrypted CSV or XLSX.')
            if 'vbaProject' in item.filename:raise ValueError('Macro-enabled workbooks are not accepted. Export CSV or plain XLSX.')
        try:
            wb=_xml(z.read('xl/workbook.xml'));rels=_xml(z.read('xl/_rels/workbook.xml.rels'))
            first=wb.find('s:sheets/s:sheet',ns)
            if first is None:raise ValueError('No worksheet was found.')
            rid=first.get('{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id')
            rel=next((r for r in rels if r.get('Id')==rid),None)
            if rel is None or rel.get('TargetMode')=='External':raise ValueError('The first worksheet cannot be read.')
            target=rel.get('Target','')
            if '..' in PurePosixPath(target).parts:raise ValueError('Unexpected worksheet path.')
            target=target.lstrip('/') if target.startswith('/') else 'xl/'+target
            sheet=_xml(z.read(target))
            shared=[]
            if 'xl/sharedStrings.xml' in z.namelist():
                for si in _xml(z.read('xl/sharedStrings.xml')).findall('s:si',ns):
                    shared.append(''.join(t.text or '' for t in si.findall('.//s:t',ns)))
                    if len(shared)>250000:raise ValueError('Too many shared strings. Export CSV.')
        except (KeyError,ValueError,ET.ParseError) as err:
            if isinstance(err,ValueError):raise
            raise ValueError('The workbook layout is not supported. Export its first sheet as CSV.') from None
        rows=[];bad=set()
        for record in sheet.findall('s:sheetData/s:row',ns):
            row=[];formulas=False
            for c in record.findall('s:c',ns):
                letters=re.match(r'[A-Za-z]+',c.get('r',''))
                idx=0
                if letters:
                    for ch in letters[0].upper():idx=idx*26+ord(ch)-64
                    idx-=1
                else:idx=len(row)
                if idx>=MAX_COLUMNS:raise ValueError('Import supports at most 80 columns.')
                while len(row)<=idx:row.append('')
                if c.find('s:f',ns) is not None:formulas=True;continue
                v=c.find('s:v',ns);text=v.text if v is not None and v.text else ''
                if c.get('t')=='s':
                    try:text=shared[int(text)]
                    except (ValueError,IndexError):raise ValueError('Invalid spreadsheet string reference.') from None
                elif c.get('t')=='inlineStr':text=''.join(t.text or '' for t in c.findall('.//s:t',ns))
                row[idx]=clean_text(text)
            if not any(row) and not formulas:continue
            if formulas:bad.add(len(rows))
            rows.append(row)
            if len(rows)>MAX_ROWS+1:raise ValueError('Use up to 50,000 contacts per import. Split larger lists into separate files.')
        return rows,bad,[f'First worksheet only: {first.get("name","Sheet 1")}. Formula rows are rejected. Phone numbers should be stored as text; lost Excel digits cannot be recovered.']

def parse_upload(data:bytes,filename:str):
    if not data or len(data)>MAX_BYTES:raise ValueError('Upload a non-empty file up to 15 MB.')
    ext=Path(filename).suffix.lower();bad=set();warnings=[]
    if ext=='.xlsx':matrix,bad,warnings=_xlsx(data)
    elif ext in {'.csv','.tsv'}:
        enc='utf-16' if data.startswith((b'\xff\xfe',b'\xfe\xff')) else 'utf-8-sig'
        try:text=data.decode(enc)
        except UnicodeError:raise ValueError('Export the file as CSV UTF-8, then import again.') from None
        try:
            dialect=csv.Sniffer().sniff(text[:8192],delimiters=',;\t')
        except csv.Error:dialect=csv.excel_tab if ext=='.tsv' else csv.excel
        matrix=[]
        try:
            for row in csv.reader(io.StringIO(text,newline=''),dialect=dialect):
                if len(row)>MAX_COLUMNS:raise ValueError('Import supports at most 80 columns.')
                if any(str(x).strip() for x in row):matrix.append([clean_text(x) for x in row])
                if len(matrix)>MAX_ROWS+1:raise ValueError('Use up to 50,000 contacts per import. Split larger lists into separate files.')
        except csv.Error:raise ValueError('CSV could not be parsed. Check quoting and delimiters.') from None
    else:raise ValueError('Use CSV, TSV or XLSX. Old XLS files must first be saved as XLSX or CSV.')
    if len(matrix)<2:raise ValueError('Include a header row and at least one contact row.')
    if 0 in bad:raise ValueError('Headers must contain text, not formulas.')
    headers=[x or f'Column {i+1}' for i,x in enumerate(matrix[0])]
    if len(set(headers))!=len(headers):warnings.append('Repeated column names detected. Check the sample values while mapping.')
    records=[]
    for i,row in enumerate(matrix[1:],1):
        records.append({'number':i+1,'cells':row,'error':'Formula cell in this row; export literal values.' if i in bad else ('More cells than headers.' if len(row)>len(headers) else '')})
    return {'headers':headers,'rows':records,'warnings':warnings}

def stage_import(data,filename):
    payload=parse_upload(data,filename);jid=m.uid('IMP')
    with m.connect() as con:con.execute('INSERT INTO m41_imports(id,filename,status,payload) VALUES(?,?,?,?)',(jid,Path(filename).name[:200],'Uploaded',json.dumps(payload)))
    return jid

def job(jid):
    r=m.one('SELECT * FROM m41_imports WHERE id=?',(jid,))
    if not r:raise ValueError('Import not found.')
    return r

def indexes(con):
    existing={r['contact_id']:dict(r) for r in con.execute('SELECT * FROM contacts')}
    for r in con.execute('SELECT * FROM m41_profile'):
        if r['contact_id'] in existing:existing[r['contact_id']].update(dict(r))
    for c in existing.values():
        for key in ['last_name','company_name','role_title','notes']:c.setdefault(key,'')
    ix={'email':collections.defaultdict(set),'phone_number':collections.defaultdict(set),'username':collections.defaultdict(set)}
    for cid,c in existing.items():add_index(ix,cid,c)
    return existing,ix

def index_value(key,val):
    if key=='phone_number':return re.sub(r'\D','',str(val or ''))
    return str(val or '').strip().lstrip('@').casefold()

def add_index(ix,cid,c):
    for key in ix:
        v=index_value(key,c.get(key))
        if v:ix[key][v].add(cid)

def match(ix,values):
    hits=set()
    for k in ix:hits.update(ix[k].get(index_value(k,values.get(k)),set()))
    return hits

def plan(payload,mapping,opts,con):
    chosen=[x for x in mapping.values() if x]
    if any(k not in FIELDS for k in chosen) or len(chosen)!=len(set(chosen)):
        raise ValueError('Map each destination field once only.')
    if not set(chosen)&{'email','phone_number','username'}:raise ValueError('Map an email, phone number or social username column.')
    existing,ix=indexes(con);steps=[]
    for r in payload['rows']:
        result={'row':r['number'],'action':'Invalid','reason':'','name':'','contact_id':'','values':{}, 'raw_cells':r['cells']}
        try:
            if r['error']:raise ValueError(r['error'])
            raw={target:(r['cells'][int(i)] if int(i)<len(r['cells']) else '') for i,target in mapping.items() if target}
            values=row_values(raw,opts.get('default_type','Unknown'));result['name']=values['full_name'];result['values']=values
            hits=match(ix,values)
            if len(hits)>1:
                result.update(action='Conflict',reason='Identifiers match different records. Nothing is merged; review manually.')
            elif hits:
                cid=next(iter(hits));old=existing[cid];result['contact_id']=cid
                # Never attach a different non-empty email/phone/username to an existing record automatically.
                divergent=[k for k in ix if values.get(k) and old.get(k) and index_value(k,values[k])!=index_value(k,old[k])]
                if divergent:
                    result.update(action='Conflict',reason='A match has different '+', '.join(divergent)+'. Review before merging.')
                else:
                    changes={k:v for k,v in values.items() if k in old and not old.get(k) and v and k not in {'contact_type','do_not_contact','tags'}}
                    action='Suppress' if values['do_not_contact'] else 'Fill blanks' if opts['policy']=='fill' and changes else 'Duplicate'
                    result.update(action=action,reason='Existing record; permissions and non-empty fields are preserved.',changes=changes if opts['policy']=='fill' else {})
                    if opts['policy']=='fill':old.update(changes);add_index(ix,cid,old)
            else:
                cid=m.uid('CNT');result.update(action='Add',contact_id=cid,reason='New contact; channel permissions will be Unknown.')
                existing[cid]=values.copy();add_index(ix,cid,values)
        except (ValueError,IndexError) as err:result['reason']=str(err)
        steps.append(result)
    return steps

def prepare(jid,mapping,opts):
    j=job(jid)
    if j['status'] not in {'Uploaded','Previewed'}:raise ValueError('This import is completed, cancelled or expired. Start a new import.')
    if opts.get('policy') not in {'skip','fill'}:raise ValueError('Choose skip duplicates or fill blank fields.')
    opts['source']=clean_text(opts.get('source',''))[:150]
    if not opts['source']:raise ValueError('Give this import a source/list name.')
    opts['tags']=tags(opts.get('tags',''))
    if opts.get('default_type','Unknown') not in {'B2B','B2C','Both','Unknown'}:raise ValueError('Choose a valid default contact type.')
    payload=json.loads(j['payload'])
    with m.connect() as con:steps=plan(payload,mapping,opts,con)
    report=report_for(steps);report['headers']=payload['headers']
    with m.connect() as con:con.execute("UPDATE m41_imports SET status='Previewed',mapping=?,options=?,report=? WHERE id=?",(json.dumps(mapping),json.dumps(opts),json.dumps(report),jid))
    return report

def report_for(steps):
    counts=collections.Counter(s['action'] for s in steps)
    return {'counts':dict(counts),'total':len(steps),'rows':[{k:v for k,v in s.items() if k not in {'values','changes'} and (k!='raw_cells' or s['action'] in {'Invalid','Conflict'})} for s in steps]}

def backup(label):
    folder=Path(m.DB).parent/'backups';folder.mkdir(exist_ok=True)
    path=folder/(label+'_'+dt.datetime.now(dt.timezone.utc).strftime('%Y%m%d_%H%M%S_%f')+'.sqlite')
    with m.connect() as src:
        with sqlite3.connect(path) as dst:src.backup(dst)
    os.chmod(path,0o600)
    return str(path)

def provenance(con,cid,source,taglist,jid=''):
    con.execute('INSERT OR IGNORE INTO m41_sources(contact_id,source,import_id) VALUES(?,?,?)',(cid,source,jid))
    con.executemany('INSERT OR IGNORE INTO m41_tags(contact_id,tag) VALUES(?,?)',[(cid,t) for t in taglist])

def insert_contact(con,cid,v,source,source_type='Imported'):
    cols=['contact_id','contact_type','full_name','first_name','email','phone_number','username','website','country','language','business_category','source_reference','source_name','source_type','qualification_status','lifecycle_stage']
    vals=[cid]+[v.get(k,'') for k in cols[1:12]]+[source,source_type,'Do Not Contact' if v.get('do_not_contact') else 'Unreviewed','New']
    con.execute('INSERT INTO contacts('+','.join(cols)+') VALUES('+','.join('?' for _ in cols)+')',vals)
    con.execute('INSERT INTO m41_profile(contact_id,last_name,company_name,role_title,notes) VALUES(?,?,?,?,?)',(cid,v.get('last_name',''),v.get('company_name',''),v.get('role_title',''),v.get('notes','')))
    con.executemany('INSERT INTO marketing_permissions(permission_id,contact_id,channel,status) VALUES(?,?,?,?)',[(m.uid('PER'),cid,ch,'Unknown') for ch in CHANNELS])

def apply_import(jid):
    j=job(jid)
    if j['status']=='Completed':return json.loads(j['report'])
    if j['status']!='Previewed':raise ValueError('Preview and confirm this import first.')
    b=backup('before_contact_import')
    with m.connect() as con:
        con.execute('BEGIN IMMEDIATE')
        j=dict(con.execute('SELECT * FROM m41_imports WHERE id=?',(jid,)).fetchone())
        if j['status']=='Completed':return json.loads(j['report'])
        if j['status']!='Previewed':raise ValueError('Import state changed. Refresh its preview.')
        opts=json.loads(j['options']);steps=plan(json.loads(j['payload']),json.loads(j['mapping']),opts,con)
        for step in steps:
            action=step['action'];cid=step['contact_id'];v=step['values']
            if action in {'Invalid','Conflict'}:continue
            if action=='Add':insert_contact(con,cid,v,opts['source'])
            else:
                for k,val in step.get('changes',{}).items():
                    if k in {'last_name','company_name','role_title','notes'}:
                        con.execute('INSERT OR IGNORE INTO m41_profile(contact_id) VALUES(?)',(cid,))
                        con.execute('UPDATE m41_profile SET '+k+'=? WHERE contact_id=? AND coalesce('+k+",'')=''",(val,cid))
                    elif k in {'first_name','full_name','email','phone_number','username','website','country','language','business_category','source_reference'}:
                        con.execute('UPDATE contacts SET '+k+'=? WHERE contact_id=? AND coalesce('+k+",'')=''",(val,cid))
                if action=='Suppress':con.execute("UPDATE contacts SET qualification_status='Do Not Contact' WHERE contact_id=?",(cid,))
            provenance(con,cid,opts['source'],list(dict.fromkeys(opts['tags']+v['tags'])),jid)
        report=report_for(steps);report['headers']=json.loads(j['payload'])['headers']
        con.execute("UPDATE m41_imports SET status='Completed',payload=NULL,report=?,backup=?,completed_at=CURRENT_TIMESTAMP WHERE id=?",(json.dumps(report),b,jid))
    m.audit('contacts.imported',jid,json.dumps(report['counts']))
    try:
        import business_os as bos
        bos.emit('contacts.import.completed','import',jid,report,'contacts.import.completed:'+jid)
    except Exception as exc:
        m.audit('contacts.import_automation_warning',jid,str(exc)[:1000])
    return report

def cancel_import(jid):
    with m.connect() as con:con.execute("UPDATE m41_imports SET status='Cancelled',payload=NULL WHERE id=? AND status IN ('Uploaded','Previewed')",(jid,))

def save_contact(raw,cid=None):
    is_new=not bool(cid)
    v=row_values(raw);source=clean_text(raw.get('source_name','Manual entry'))[:150] or 'Manual entry'
    with m.connect() as con:
        con.execute('BEGIN IMMEDIATE');existing,ix=indexes(con)
        if cid and cid not in existing:raise ValueError('Contact not found.')
        hits=match(ix,v)-({cid} if cid else set())
        if hits:raise ValueError('This email, phone or username already belongs to a contact. Search and edit the existing record instead.')
        if not cid:
            cid=m.uid('CNT');insert_contact(con,cid,v,source,'Manual')
        else:
            old=existing[cid]
            # A permission grant must not follow a changed delivery address.
            for field,channels in [('email',['Email']),('phone_number',['WhatsApp','SMS','Phone'])]:
                if index_value(field,old.get(field))!=index_value(field,v.get(field)):
                    for ch in channels:
                        denied=con.execute("SELECT 1 FROM marketing_permissions WHERE contact_id=? AND channel=? AND status IN ('OptedOut','Suppressed','DoNotContact')",(cid,ch)).fetchone()
                        ep=index_value(field,old.get(field))
                        if ep and (denied or old.get('qualification_status')=='Do Not Contact'):
                            con.execute('INSERT OR IGNORE INTO m41_suppressed_endpoints(channel,endpoint,reason) VALUES(?,?,?)',(ch,ep,'Retained when editing an opted-out contact endpoint'))
                        con.execute("UPDATE marketing_permissions SET status='Unknown',lawful_basis_or_reason=NULL,evidence_reference=NULL,jurisdiction=NULL,updated_at=CURRENT_TIMESTAMP WHERE contact_id=? AND channel=? AND status NOT IN ('OptedOut','Suppressed','DoNotContact')",(cid,ch))
            keys=['full_name','first_name','contact_type','email','phone_number','username','website','country','language','business_category','source_reference']
            con.execute('UPDATE contacts SET '+','.join(k+'=?' for k in keys)+' WHERE contact_id=?',[v[k] for k in keys]+[cid])
            con.execute('''INSERT INTO m41_profile(contact_id,last_name,company_name,role_title,notes) VALUES(?,?,?,?,?)
             ON CONFLICT(contact_id) DO UPDATE SET last_name=excluded.last_name,company_name=excluded.company_name,role_title=excluded.role_title,notes=excluded.notes''',(cid,v['last_name'],v['company_name'],v['role_title'],v['notes']))
            if v['do_not_contact']:con.execute("UPDATE contacts SET qualification_status='Do Not Contact' WHERE contact_id=?",(cid,))
        provenance(con,cid,source,v['tags'])
    m.audit('contact.saved',cid,'Explicit manual edit; no permission granted')
    try:
        import business_os as bos
        bos.emit('lead.created' if is_new else 'contact.updated','contact',cid,{'source':source},('lead.created:' if is_new else 'contact.updated:')+cid+':'+str(int(__import__('time').time())))
        if is_new: bos.enqueue('lead.followup','contact',cid,{'source':source})
    except Exception as exc:
        m.audit('contact.automation_warning',cid,str(exc)[:1000])
    return cid

def clean_display_name(value):
    text=re.sub(r'\s+',' ',str(value or '')).strip()
    # Imports from spreadsheets/social exports sometimes retain wrapping quotes.
    # Remove only symmetric outer quote characters; preserve punctuation inside names.
    changed=True
    while changed and len(text)>=2:
        changed=False
        pairs=[('"','"'),("'","'"),('“','”'),('‘','’')]
        for left,right in pairs:
            if text.startswith(left) and text.endswith(right):
                text=text[1:-1].strip();changed=True;break
    return text


def greeting_name(contact):
    first=clean_display_name(contact.get('first_name'))
    if first:return first
    full=clean_display_name(contact.get('full_name'))
    company=clean_display_name(contact.get('company_name'))
    if company and full.casefold()==company.casefold():return ''
    # Avoid greeting a likely organisation as though it were a person's name.
    org_words={'studio','handloom','handlooms','boutique','textiles','textile','fashion','sarees','saree','shop','store','ltd','limited','llp','pvt','company','co','enterprise','enterprises'}
    words={re.sub(r'[^a-z]','',w.casefold()) for w in full.split()}
    if contact.get('contact_type') in {'B2B','Both'} and words & org_words:return ''
    return full


def profile(cid):
    c=m.contact(cid);c.update(m.one('SELECT * FROM m41_profile WHERE contact_id=?',(cid,)) or {})
    if not c.get('company_name'):
        linked=m.one('SELECT co.company_name,cp.role_title FROM contact_companies cp JOIN companies co USING(company_id) WHERE cp.contact_id=? ORDER BY cp.is_primary DESC LIMIT 1',(cid,)) or {}
        c['company_name']=linked.get('company_name','');c['role_title']=c.get('role_title') or linked.get('role_title','')
    c['tags']=', '.join(r['tag'] for r in m.rows('SELECT tag FROM m41_tags WHERE contact_id=? ORDER BY tag',(cid,)))
    return c

def csv_bytes(rows):
    s=io.StringIO(newline='');w=csv.writer(s)
    for row in rows:
        cleaned=[]
        for cell in row:
            text=str(cell if cell is not None else '')
            # Protect downstream spreadsheets against formula interpretation.
            if text.lstrip().startswith(('=','+','-','@','\t','\r','\n')):text="'"+text
            cleaned.append(text)
        w.writerow(cleaned)
    return b'\xef\xbb\xbf'+s.getvalue().encode('utf-8')
