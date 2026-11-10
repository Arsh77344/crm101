#!/usr/bin/env python3
import html, os, re, sqlite3, uuid, base64, hmac
import db_layer
import runtime_config as rc
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs, quote
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DB = db_layer.SQLITE_PATH
STATIC = rc.STATIC_ROOT
HOST = '127.0.0.1'
PORT = int(os.environ.get('PORT', '8765'))
ADMIN_USER = os.environ.get('CRM_USER','admin')
ADMIN_PASSWORD = os.environ.get('CRM_PASSWORD','')


def db():
    return db_layer.connect(DB if not db_layer.USING_POSTGRES else None)


def esc(v):
    return html.escape('' if v is None else str(v))


def money(v, c='INR'):
    if v is None or v == '': return '—'
    sym = {'INR':'₹','GBP':'£','USD':'$','EUR':'€'}.get(c or '', (c or '')+' ')
    return f"{sym}{float(v):,.0f}"


def ensure_schema():
    with db() as con:
        cols = {r['name'] for r in con.execute('pragma table_info(contacts)')}
        for name, typ in [
            ('lead_score','INTEGER DEFAULT 0'),('business_category','TEXT'),('relevance_reason','TEXT'),
            ('data_quality','TEXT DEFAULT "Unknown"'),('next_follow_up','TEXT')]:
            if name not in cols:
                con.execute(f'alter table contacts add column {name} {typ}')
        pcols = {r['name'] for r in con.execute('pragma table_info(products)')}
        for name, typ in [
            ('tags','TEXT'),('published_at','TEXT'),('product_code','TEXT'),('duplicate_group','TEXT')]:
            if name not in pcols:
                con.execute(f'alter table products add column {name} {typ}')
        scols = {r['name'] for r in con.execute('pragma table_info(showrooms)')}
        for name, typ in [('intro_text','TEXT'),('cta_text','TEXT'),('public_enabled','INTEGER DEFAULT 1')]:
            if name not in scols:
                con.execute(f'alter table showrooms add column {name} {typ}')
        ocols = {r['name'] for r in con.execute('pragma table_info(opportunities)')}
        if 'showroom_id' not in ocols:
            con.execute('alter table opportunities add column showroom_id TEXT')
        con.execute("""create table if not exists showroom_views (
          view_id TEXT PRIMARY KEY, showroom_id TEXT NOT NULL, viewed_at TEXT DEFAULT CURRENT_TIMESTAMP,
          user_agent TEXT, FOREIGN KEY(showroom_id) REFERENCES showrooms(showroom_id))""")
        con.execute("""create table if not exists showroom_events (
          event_id TEXT PRIMARY KEY, showroom_id TEXT NOT NULL, product_id TEXT,
          event_type TEXT NOT NULL, event_at TEXT DEFAULT CURRENT_TIMESTAMP, user_agent TEXT,
          FOREIGN KEY(showroom_id) REFERENCES showrooms(showroom_id),
          FOREIGN KEY(product_id) REFERENCES products(product_id))""")
        con.execute("""create table if not exists activities (
          activity_id TEXT PRIMARY KEY, contact_id TEXT, company_id TEXT, opportunity_id TEXT,
          activity_type TEXT, channel TEXT, direction TEXT, summary TEXT,
          follow_up_at TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP,
          FOREIGN KEY(contact_id) REFERENCES contacts(contact_id))""")
        con.execute("""create table if not exists campaign_members (
          campaign_id TEXT NOT NULL, contact_id TEXT NOT NULL, member_status TEXT DEFAULT 'Planned',
          added_at TEXT DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY(campaign_id, contact_id),
          FOREIGN KEY(campaign_id) REFERENCES campaigns(campaign_id),
          FOREIGN KEY(contact_id) REFERENCES contacts(contact_id))""")
        con.execute("""create table if not exists settings (
          setting_key TEXT PRIMARY KEY, setting_value TEXT)""")
        defaults={
          'brand_name':'Brand name pending','business_whatsapp':'','business_email':'',
          'public_base_url':'','default_currency':'INR','booking_url':''}
        for k,v in defaults.items():
            con.execute('insert or ignore into settings(setting_key,setting_value) values(?,?)',(k,v))
        rows=con.execute('select product_id,internal_sku,public_product_name,colour,product_code from products').fetchall()
        groups={}
        for r in rows:
            if not r['product_code']:
                con.execute('update products set product_code=? where product_id=?',(r['internal_sku'] or r['product_id'],r['product_id']))
            key=((r['public_product_name'] or '').strip().lower(),(r['colour'] or '').strip().lower())
            groups.setdefault(key,[]).append(r['product_id'])
        for key,ids in groups.items():
            if key[0] and len(ids)>1:
                gid='DUP-'+uuid.uuid5(uuid.NAMESPACE_DNS,'|'.join(key)).hex[:8].upper()
                con.executemany('update products set duplicate_group=? where product_id=?',[(gid,x) for x in ids])


def setting(key, default=''):
    with db() as con:
        r=con.execute('select setting_value from settings where setting_key=?',(key,)).fetchone()
    return (r[0] if r else default) or default


def public_base_url():
    return setting('public_base_url','').rstrip('/')


def infer_country(phone):
    p = re.sub(r'\s+','', phone or '')
    for prefix, country in [('+91','India'),('+44','United Kingdom'),('+880','Bangladesh'),('+971','United Arab Emirates'),('+92','Pakistan'),('+61','Australia'),('+65','Singapore'),('+1','United States / Canada')]:
        if p.startswith(prefix): return country
    return ''




def data_quality(email, phone, website):
    issues=[]
    e=(email or '').strip().lower()
    if not e or '@' not in e or e.endswith('.con') or 'devnull.facebook.com' in e:
        issues.append('Email needs review')
    p=re.sub(r'\D','',phone or '')
    if phone and len(p)<8: issues.append('Phone needs review')
    if not email and not phone: issues.append('No direct channel')
    if issues: return 'Needs Review: ' + '; '.join(issues)
    if email and phone: return 'Good'
    return 'Usable'


def classify(text, ctype):
    t = (text or '').lower()
    strong = ['saree','sari','boutique','textile','silk','handloom','ethnic wear','ethnicwear','bridal','wedding wear','fashion store','clothing store','apparel','designer','weaver','loom','banarasi','banaras','lehenga','kurta','fashion house']
    medium = ['fashion','style','studio','retail','shop','store','collection','couture','garment','clothing','jewellery','jewelry','wedding','bridalwear']
    negative = ['chef','restaurant','travel','museum','artist network','crypto','real estate','fitness','photography','makeup artist','meme','gaming']
    score = 25 if ctype == 'B2C' else 40 if ctype == 'B2B' else 30
    reasons=[]
    hit_s=[x for x in strong if x in t]
    hit_m=[x for x in medium if x in t]
    hit_n=[x for x in negative if x in t]
    score += min(45, len(hit_s)*15) + min(20, len(hit_m)*7) - min(40, len(hit_n)*20)
    score = max(0,min(100,score))
    if hit_s: reasons.append('Relevant fashion/saree signals: '+', '.join(hit_s[:3]))
    elif hit_m: reasons.append('General fashion/retail signals: '+', '.join(hit_m[:3]))
    if hit_n: reasons.append('Possible unrelated signals: '+', '.join(hit_n[:2]))
    if not reasons: reasons.append('Needs manual review; limited profile signals')
    if any(x in t for x in ['saree','sari','banarasi','banaras','silk','handloom']): cat='Saree / Textile'
    elif any(x in t for x in ['boutique','retail','store','shop']): cat='Boutique / Retailer'
    elif any(x in t for x in ['designer','couture','fashion house']): cat='Designer / Fashion'
    elif any(x in t for x in ['wedding','bridal']): cat='Wedding / Bridal'
    elif ctype == 'B2C': cat='Consumer'
    else: cat='Other / Review'
    qual = 'Qualified' if score >= 75 else 'Needs Review' if score >= 45 else 'Irrelevant' if score < 25 else 'Unreviewed'
    return score, cat, '; '.join(reasons), qual


def run_enrichment():
    changed=0
    with db() as con:
        rows=con.execute('select contact_id,contact_type,username,full_name,biography,website,email,phone_number,country,qualification_status from contacts').fetchall()
        for r in rows:
            text=' '.join(str(r[k] or '') for k in ['username','full_name','biography','website','email'])
            score,cat,reason,qual=classify(text,r['contact_type'])
            country=r['country'] or infer_country(r['phone_number'])
            quality=data_quality(r['email'],r['phone_number'],r['website'])
            current=r['qualification_status'] or 'Unreviewed'
            if current in ('Qualified','Irrelevant','Do Not Contact'):
                qual=current
            con.execute('update contacts set lead_score=?,business_category=?,relevance_reason=?,country=?,qualification_status=?,data_quality=? where contact_id=?',(score,cat,reason,country,qual,quality,r['contact_id']))
            changed+=1
    return changed


def layout(title, body, active='dashboard'):
    nav=[('dashboard','/','Dashboard','◫'),('contacts','/contacts','Contacts','◎'),('companies','/companies','Companies','▦'),('products','/products','Products','◇'),('opportunities','/opportunities','Opportunities','◈'),('orders','/orders','Orders','▤'),('campaigns','/campaigns','Campaigns','✦'),('showrooms','/showrooms','Showrooms','▱'),('settings','/settings','Settings','⚙')]
    nav_html=''.join(f'<a class="nav {"active" if k==active else ""}" href="{u}"><span>{ic}</span>{n}</a>' for k,u,n,ic in nav)
    return f'''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{esc(title)} · Commerce Business OS</title><style>
:root{{--bg:#f7f6f2;--card:#fff;--ink:#1f201d;--muted:#74766f;--line:#e8e6df;--accent:#6d3f3a;--accent2:#f1e7e3;--good:#28614b;--warn:#8a5a19}}
*{{box-sizing:border-box}} body{{margin:0;font-family:Inter,ui-sans-serif,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;background:var(--bg);color:var(--ink)}}
.shell{{display:grid;grid-template-columns:230px 1fr;min-height:100vh}} aside{{background:#24251f;color:#fff;padding:24px 16px;position:sticky;top:0;height:100vh}} .brand{{font-size:19px;font-weight:750;letter-spacing:.2px;margin:4px 10px 26px}} .brand small{{display:block;font-size:11px;color:#aaa99f;font-weight:500;margin-top:4px}} .nav{{display:flex;gap:11px;align-items:center;color:#c8c8bf;text-decoration:none;padding:11px 12px;border-radius:9px;margin:3px 0;font-size:14px}} .nav:hover,.nav.active{{background:#37382f;color:#fff}} .nav span{{width:18px;text-align:center}}
main{{padding:34px 38px 60px;max-width:1500px;width:100%}} h1{{font-size:28px;margin:0}} h2{{font-size:19px;margin:0 0 14px}} .sub{{color:var(--muted);margin-top:7px;font-size:14px}} .top{{display:flex;justify-content:space-between;align-items:flex-start;gap:20px;margin-bottom:26px}} .actions{{display:flex;gap:8px;flex-wrap:wrap}} .btn{{border:0;border-radius:9px;padding:10px 14px;text-decoration:none;display:inline-block;font-weight:650;font-size:13px;background:var(--accent);color:#fff;cursor:pointer}} .btn.secondary{{background:#fff;color:var(--ink);border:1px solid var(--line)}} .btn.good{{background:#28614b}}
.grid{{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:14px}} .card{{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:18px}} .stat .label{{font-size:12px;color:var(--muted);text-transform:uppercase;letter-spacing:.5px}} .stat .value{{font-size:30px;font-weight:750;margin-top:7px}} .stat .hint{{font-size:12px;color:var(--muted);margin-top:4px}}
.section{{margin-top:24px}} table{{width:100%;border-collapse:collapse;background:#fff;border:1px solid var(--line);border-radius:14px;overflow:hidden}} th,td{{padding:12px 14px;border-bottom:1px solid var(--line);text-align:left;font-size:13px;vertical-align:top}} th{{font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.45px;background:#faf9f6}} tr:last-child td{{border-bottom:0}} tr:hover td{{background:#fcfbf8}} a.link{{color:var(--accent);text-decoration:none;font-weight:650}} .pill{{display:inline-block;padding:4px 8px;border-radius:999px;background:#f1f0eb;color:#555;font-size:11px}} .pill.b2b{{background:#e7eef6;color:#31587d}} .pill.b2c{{background:#f5e9ef;color:#844867}} .pill.both{{background:#ece8f5;color:#5a4a86}} .pill.good{{background:#e7f2ec;color:#28614b}} .score{{font-weight:750}} .score.high{{color:#28614b}} .score.mid{{color:#8a5a19}} .score.low{{color:#9a3b3b}}
.filters{{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:14px}} input,select,textarea{{border:1px solid var(--line);background:#fff;border-radius:9px;padding:10px 11px;font:inherit;font-size:13px}} input[type=text],input[type=email],input[type=number]{{min-width:220px}} textarea{{width:100%;min-height:90px}} .empty{{padding:28px;color:var(--muted);text-align:center}} .two{{display:grid;grid-template-columns:1.3fr .7fr;gap:18px}} .kv{{display:grid;grid-template-columns:150px 1fr;gap:8px 18px;font-size:13px}} .kv div:nth-child(odd){{color:var(--muted)}} .product-grid{{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:16px}} .product{{background:#fff;border:1px solid var(--line);border-radius:14px;overflow:hidden}} .product img{{width:100%;aspect-ratio:4/5;object-fit:cover;background:#eee}} .product .pbody{{padding:14px}} .product h3{{font-size:14px;margin:0 0 6px}} .product p{{margin:0;color:var(--muted);font-size:12px}} .gallery{{display:grid;grid-template-columns:repeat(3,1fr);gap:10px}} .gallery img{{width:100%;aspect-ratio:1;object-fit:cover;border-radius:10px;border:1px solid var(--line)}} .note{{background:#fff8e8;border:1px solid #f0dfb9;border-radius:10px;padding:12px 14px;font-size:12px;color:#6b531f}} .field{{display:grid;gap:5px}} .formgrid{{display:grid;grid-template-columns:1fr 1fr;gap:12px}} .checkgrid{{display:grid;grid-template-columns:repeat(2,1fr);gap:10px}} .check{{display:flex;gap:10px;align-items:center;border:1px solid var(--line);border-radius:10px;padding:9px;background:#fff}} .check img{{width:58px;height:72px;object-fit:cover;border-radius:6px}} .public{{max-width:1100px;margin:0 auto;padding:30px}} .hero{{padding:42px 0 24px}} .showgrid{{display:grid;grid-template-columns:repeat(3,1fr);gap:20px}} .showcard{{background:#fff;border:1px solid var(--line);border-radius:14px;overflow:hidden}} .showcard img{{width:100%;aspect-ratio:4/5;object-fit:cover}} .showcard .pbody{{padding:14px}}
@media(max-width:1000px){{.shell{{grid-template-columns:72px 1fr}} aside{{padding:20px 8px}} .brand{{font-size:0;margin:4px 4px 20px}} .brand:before{{content:'C';font-size:20px}} .brand small{{display:none}} .nav{{font-size:0;justify-content:center}} .nav span{{font-size:16px}} main{{padding:26px 20px}} .grid,.product-grid,.showgrid{{grid-template-columns:repeat(2,1fr)}} .two,.formgrid{{grid-template-columns:1fr}}}}
</style></head><body><div class="shell"><aside><div class="brand">Commerce Business OS<small>{esc(setting('brand_name','Brand name pending'))}</small></div>{nav_html}</aside><main>{body}</main></div></body></html>'''


class App(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args): pass
    def require_auth(self):
        if not ADMIN_PASSWORD: return True
        raw=self.headers.get('Authorization','')
        if raw.startswith('Basic '):
            try:
                userpw=base64.b64decode(raw[6:]).decode('utf-8')
                user,pw=userpw.split(':',1)
                if hmac.compare_digest(user,ADMIN_USER) and hmac.compare_digest(pw,ADMIN_PASSWORD): return True
            except Exception: pass
        self.send_response(401); self.send_header('WWW-Authenticate','Basic realm="Commerce Business OS"'); self.end_headers(); return False
    def send_html(self,s,code=200):
        b=s.encode('utf-8'); self.send_response(code); self.send_header('Content-Type','text/html; charset=utf-8'); self.send_header('Content-Length',str(len(b))); self.end_headers(); self.wfile.write(b)
    def redirect(self,path): self.send_response(303); self.send_header('Location',path); self.end_headers()
    def form(self):
        n=int(self.headers.get('Content-Length','0')); return parse_qs(self.rfile.read(n).decode())
    def serve_static(self,path):
        rel=path[len('/static/'):]; fp=(STATIC/rel).resolve()
        if STATIC.resolve() not in fp.parents or not fp.exists(): return self.send_error(404)
        ctype='image/jpeg'
        if fp.suffix.lower()=='.png': ctype='image/png'
        elif fp.suffix.lower()=='.webp': ctype='image/webp'
        data=fp.read_bytes(); self.send_response(200); self.send_header('Content-Type',ctype); self.send_header('Content-Length',str(len(data))); self.end_headers(); self.wfile.write(data)

    def do_POST(self):
        p=urlparse(self.path)
        if not self.require_auth(): return
        f=self.form()
        if p.path=='/enrich':
            run_enrichment(); return self.redirect('/contacts?enriched=1')
        if p.path.startswith('/contacts/') and p.path.endswith('/update'):
            cid=p.path.split('/')[2]; fields=['contact_type','qualification_status','lifecycle_stage','country','language','niche','business_category']
            vals=[f.get(x,[''])[0] for x in fields]
            with db() as con: con.execute('update contacts set '+','.join(x+'=?' for x in fields)+' where contact_id=?',(*vals,cid))
            return self.redirect('/contacts/'+quote(cid))
        if p.path.startswith('/contacts/') and p.path.endswith('/create-company'):
            cid=p.path.split('/')[2]
            with db() as con:
                r=con.execute('select * from contacts where contact_id=?',(cid,)).fetchone()
                if r:
                    company_id='CMP-'+uuid.uuid4().hex[:10].upper(); name=(r['full_name'] or r['username'] or 'Unnamed business').strip(); website=r['website']; country=r['country']; ctype=r['business_category'] or 'Other / Review'
                    con.execute('insert into companies(company_id,company_name,website,country,company_type) values(?,?,?,?,?)',(company_id,name,website,country,ctype))
                    con.execute('insert or ignore into contact_companies(contact_id,company_id,role_title,is_primary) values(?,?,?,1)',(cid,company_id,'Primary contact'))
            return self.redirect('/companies')
        if p.path.startswith('/products/') and p.path.endswith('/update'):
            pid=p.path.split('/')[2]; fields=['public_product_name','product_code','colour','weave_or_motif','fabric','category','description','retail_price','wholesale_price','currency','stock_qty','moq','status','tags']
            vals=[f.get(x,[''])[0] for x in fields]
            for i in [7,8,10,11]: vals[i]=None if vals[i]=='' else vals[i]
            with db() as con: con.execute('update products set '+','.join(x+'=?' for x in fields)+' where product_id=?',(*vals,pid))
            return self.redirect('/products/'+quote(pid))
        if p.path=='/showrooms/create':
            cid=f.get('contact_id',[''])[0]; title=f.get('title',['Personalised Collection'])[0].strip() or 'Personalised Collection'; pricing=f.get('pricing_mode',['Hidden'])[0]; products=f.get('product_ids',[])
            intro=f.get('intro_text',['Selected products from our current collection.'])[0].strip(); cta=f.get('cta_text',['Ask about this piece'])[0].strip()
            slug=(re.sub(r'[^a-z0-9]+','-',title.lower()).strip('-') or 'showroom')+'-'+uuid.uuid4().hex[:6]
            sid='SHR-'+uuid.uuid4().hex[:10].upper()
            with db() as con:
                con.execute('insert into showrooms(showroom_id,contact_id,slug,title,pricing_mode,status,intro_text,cta_text,public_enabled) values(?,?,?,?,?,?,?,?,1)',(sid,cid or None,slug,title,pricing,'Active',intro,cta))
                for ix,pid in enumerate(products): con.execute('insert into showroom_products(showroom_id,product_id,sort_order) values(?,?,?)',(sid,pid,ix))
            return self.redirect('/showrooms/'+sid)
        if p.path=='/campaigns/create':
            name=f.get('campaign_name',['Untitled Campaign'])[0]; aud=f.get('audience_type',['Both'])[0]; ch=f.get('channel',['Email'])[0]
            with db() as con: con.execute('insert into campaigns(campaign_id,campaign_name,audience_type,channel,status) values(?,?,?,?,?)',('CAM-'+uuid.uuid4().hex[:10].upper(),name,aud,ch,'Draft'))
            return self.redirect('/campaigns')
        if p.path=='/settings/update':
            keys=['brand_name','business_whatsapp','business_email','public_base_url','default_currency','booking_url']
            with db() as con:
                for k in keys:
                    con.execute('insert into settings(setting_key,setting_value) values(?,?) on conflict(setting_key) do update set setting_value=excluded.setting_value',(k,f.get(k,[''])[0].strip()))
            return self.redirect('/settings?saved=1')
        if p.path=='/activities/create':
            cid=f.get('contact_id',[''])[0]; summary=f.get('summary',[''])[0].strip(); channel=f.get('channel',['Other'])[0]; atype=f.get('activity_type',['Note'])[0]; direction=f.get('direction',['Outbound'])[0]; follow=f.get('follow_up_at',[''])[0]
            if cid and summary:
                with db() as con:
                    con.execute('insert into activities(activity_id,contact_id,activity_type,channel,direction,summary,follow_up_at) values(?,?,?,?,?,?,?)',('ACT-'+uuid.uuid4().hex[:10].upper(),cid,atype,channel,direction,summary,follow or None))
                    if follow: con.execute('update contacts set next_follow_up=? where contact_id=?',(follow,cid))
            return self.redirect('/contacts/'+quote(cid))
        if p.path=='/permissions/update':
            cid=f.get('contact_id',[''])[0]; channel=f.get('channel',['Email'])[0]; status=f.get('status',['Unknown'])[0]; reason=f.get('reason',[''])[0]
            with db() as con:
                row=con.execute('select permission_id from marketing_permissions where contact_id=? and channel=?',(cid,channel)).fetchone()
                if row: con.execute('update marketing_permissions set status=?,lawful_basis_or_reason=?,updated_at=CURRENT_TIMESTAMP where permission_id=?',(status,reason,row[0]))
                else: con.execute('insert into marketing_permissions(permission_id,contact_id,channel,status,lawful_basis_or_reason) values(?,?,?,?,?)',('PER-'+uuid.uuid4().hex[:10].upper(),cid,channel,status,reason))
            return self.redirect('/contacts/'+quote(cid))
        if p.path=='/opportunities/create':
            oid='OPP-'+uuid.uuid4().hex[:10].upper(); cid=f.get('contact_id',[''])[0] or None; sid=f.get('showroom_id',[''])[0] or None
            with db() as con:
                con.execute('insert into opportunities(opportunity_id,contact_id,name,stage,estimated_value,currency,expected_close_date,notes,showroom_id) values(?,?,?,?,?,?,?,?,?)',(oid,cid,f.get('name',['New opportunity'])[0],f.get('stage',['New'])[0],f.get('estimated_value',[''])[0] or None,f.get('currency',[setting('default_currency','INR')])[0],f.get('expected_close_date',[''])[0] or None,f.get('notes',[''])[0],sid))
            return self.redirect('/opportunities')
        if p.path=='/orders/create':
            oid='ORD-'+uuid.uuid4().hex[:10].upper(); cid=f.get('contact_id',[''])[0] or None; total=f.get('total',[''])[0] or None
            with db() as con:
                con.execute('insert into orders(order_id,contact_id,order_type,order_status,total,currency,external_order_reference,ordered_at) values(?,?,?,?,?,?,?,CURRENT_TIMESTAMP)',(oid,cid,f.get('order_type',['B2C'])[0],f.get('order_status',['Draft'])[0],total,f.get('currency',[setting('default_currency','INR')])[0],f.get('external_order_reference',[''])[0]))
                if cid and f.get('order_status',[''])[0] in ('Paid','Completed','Fulfilled'):
                    con.execute("update contacts set lifecycle_stage='Customer' where contact_id=?",(cid,))
            return self.redirect('/orders')
        if p.path.startswith('/campaigns/') and p.path.endswith('/populate'):
            camid=p.path.split('/')[2]
            with db() as con:
                cam=con.execute('select * from campaigns where campaign_id=?',(camid,)).fetchone()
                if cam:
                    where=["qualification_status='Qualified'","lead_score>=75"] ; ps=[]
                    if cam['audience_type'] in ('B2B','B2C'): where.append('contact_type=?'); ps.append(cam['audience_type'])
                    rows=con.execute('select contact_id from contacts where '+' and '.join(where),ps).fetchall()
                    for r in rows: con.execute('insert or ignore into campaign_members(campaign_id,contact_id) values(?,?)',(camid,r[0]))
            return self.redirect('/campaigns/'+quote(camid))
        self.send_error(404)

    def do_GET(self):
        p=urlparse(self.path); q=parse_qs(p.query)
        public_path=p.path.startswith('/static/') or p.path.startswith('/s/') or p.path.startswith('/interest/')
        if not public_path and not self.require_auth(): return
        if p.path.startswith('/static/'): return self.serve_static(p.path)
        if p.path.startswith('/interest/'):
            parts=p.path.split('/')
            if len(parts)>=4: return self.showroom_interest(parts[2],parts[3])
        if p.path.startswith('/s/'): return self.public_showroom(p.path.split('/')[2])
        if p.path=='/': return self.dashboard()
        if p.path=='/contacts': return self.contacts(q)
        if p.path.startswith('/contacts/'): return self.contact(p.path.split('/')[2])
        if p.path=='/companies': return self.companies()
        if p.path=='/products': return self.products()
        if p.path.startswith('/products/'): return self.product(p.path.split('/')[2])
        if p.path=='/opportunities': return self.opportunities()
        if p.path=='/orders': return self.orders()
        if p.path=='/campaigns': return self.campaigns()
        if p.path.startswith('/campaigns/'): return self.campaign(p.path.split('/')[2])
        if p.path=='/showrooms/new': return self.new_showroom(q)
        if p.path=='/showrooms': return self.showrooms()
        if p.path.startswith('/showrooms/'): return self.showroom(p.path.split('/')[2])
        if p.path=='/settings': return self.settings(q)
        self.send_error(404)

    def dashboard(self):
        con=db(); count=lambda sql,ps=(): con.execute(sql,ps).fetchone()[0]
        total=count('select count(*) from contacts'); b2b=count("select count(*) from contacts where contact_type='B2B'"); b2c=count("select count(*) from contacts where contact_type='B2C'"); high=count('select count(*) from contacts where lead_score>=75'); products=count('select count(*) from products'); companies=count('select count(*) from companies'); showrooms=count('select count(*) from showrooms')
        recent=con.execute('select contact_id,username,full_name,contact_type,email,lead_score,qualification_status from contacts order by lead_score desc,rowid desc limit 8').fetchall(); con.close()
        cards=''.join(f'<div class="card stat"><div class="label">{a}</div><div class="value">{b:,}</div><div class="hint">{c}</div></div>' for a,b,c in [('Contacts',total,'Master database'),('High-score leads',high,'Score 75+'),('Companies',companies,'B2B accounts'),('Products',products,'Catalogue')])
        rows=''.join(f'<tr><td><a class="link" href="/contacts/{esc(r[0])}">{esc(r[2] or r[1] or "Unnamed")}</a><br><span style="color:#888">@{esc(r[1])}</span></td><td><span class="pill {str(r[3] or "").lower()}">{esc(r[3])}</span></td><td>{esc(r[4] or "—")}</td><td><span class="score {"high" if (r[5] or 0)>=75 else "mid" if (r[5] or 0)>=45 else "low"}">{r[5] or 0}</span></td><td>{esc(r[6])}</td></tr>' for r in recent)
        body=f'''<div class="top"><div><h1>Dashboard</h1><div class="sub">B2B + B2C sales system · V3</div></div><div class="actions"><form method="post" action="/enrich"><button class="btn good">Run contact intelligence</button></form><a class="btn" href="/showrooms/new">Create showroom</a></div></div><div class="grid">{cards}</div><div class="two section"><div><h2>Highest-scoring contacts</h2><table><tr><th>Contact</th><th>Type</th><th>Email</th><th>Score</th><th>Status</th></tr>{rows}</table></div><div><h2>System status</h2><div class="card"><div class="kv"><div>B2B contacts</div><div>{b2b:,}</div><div>B2C contacts</div><div>{b2c:,}</div><div>Showrooms</div><div>{showrooms:,}</div></div><div class="note" style="margin-top:16px">Contact intelligence uses local profile text and phone prefixes only. It does not browse the web or send marketing messages.</div></div></div>'''
        self.send_html(layout('Dashboard',body,'dashboard'))

    def contacts(self,q):
        term=q.get('q',[''])[0].strip(); typ=q.get('type',[''])[0]; qual=q.get('qual',[''])[0]; minscore=q.get('minscore',[''])[0]; page=max(1,int(q.get('page',['1'])[0] or 1)); per=50; where=[]; ps=[]
        if term: where.append('(username like ? or full_name like ? or email like ? or phone_number like ? or biography like ?)'); ps += ['%'+term+'%']*5
        if typ: where.append('contact_type=?'); ps.append(typ)
        if qual: where.append('qualification_status=?'); ps.append(qual)
        if minscore: where.append('lead_score>=?'); ps.append(int(minscore))
        w=' where '+' and '.join(where) if where else ''
        con=db(); total=con.execute('select count(*) from contacts'+w,ps).fetchone()[0]
        rows=con.execute('select contact_id,username,full_name,contact_type,email,phone_number,country,business_category,qualification_status,lifecycle_stage,lead_score from contacts'+w+' order by lead_score desc,rowid limit ? offset ?',(*ps,per,(page-1)*per)).fetchall(); con.close()
        trs=''.join(f'<tr><td><a class="link" href="/contacts/{esc(r[0])}">{esc(r[2] or r[1] or "Unnamed")}</a><br><span style="color:#888">@{esc(r[1])}</span></td><td><span class="pill {str(r[3] or "").lower()}">{esc(r[3])}</span></td><td>{esc(r[4] or "—")}</td><td>{esc(r[5] or "—")}</td><td>{esc(r[6] or "—")}</td><td>{esc(r[7] or "—")}</td><td><span class="score {"high" if (r[10] or 0)>=75 else "mid" if (r[10] or 0)>=45 else "low"}">{r[10] or 0}</span></td><td>{esc(r[8])}</td></tr>' for r in rows)
        qs=f'q={quote(term)}&type={quote(typ)}&qual={quote(qual)}&minscore={quote(minscore)}'
        body=f'''<div class="top"><div><h1>Contacts</h1><div class="sub">{total:,} matching contacts</div></div><form method="post" action="/enrich"><button class="btn good">Run contact intelligence</button></form></div><form class="filters" method="get"><input name="q" type="text" value="{esc(term)}" placeholder="Search name, username, email, phone"><select name="type"><option value="">All types</option>{''.join(f'<option value="{x}" {"selected" if typ==x else ""}>{x}</option>' for x in ['B2B','B2C','Both','Unknown'])}</select><select name="qual"><option value="">All qualification</option>{''.join(f'<option value="{x}" {"selected" if qual==x else ""}>{x}</option>' for x in ['Qualified','Needs Review','Unreviewed','Irrelevant','Do Not Contact'])}</select><select name="minscore"><option value="">Any score</option>{''.join(f'<option value="{x}" {"selected" if minscore==str(x) else ""}>{x}+</option>' for x in [75,60,45])}</select><button class="btn">Filter</button><a class="btn secondary" href="/contacts">Reset</a></form><table><tr><th>Contact</th><th>Type</th><th>Email</th><th>Phone</th><th>Country</th><th>Category</th><th>Score</th><th>Qualification</th></tr>{trs or '<tr><td colspan="8" class="empty">No contacts found.</td></tr>'}</table><div style="display:flex;justify-content:space-between;margin-top:12px"><div class="sub">Page {page} · showing {len(rows)} of {total:,}</div><div>{f'<a class="btn secondary" href="/contacts?{qs}&page={page-1}">Previous</a> ' if page>1 else ''}{f'<a class="btn secondary" href="/contacts?{qs}&page={page+1}">Next</a>' if page*per<total else ''}</div></div>'''
        self.send_html(layout('Contacts',body,'contacts'))

    def contact(self,cid):
        con=db(); r=con.execute('select * from contacts where contact_id=?',(cid,)).fetchone()
        if not r: con.close(); return self.send_error(404)
        perms=con.execute('select channel,status,lawful_basis_or_reason,jurisdiction,updated_at from marketing_permissions where contact_id=? order by channel',(cid,)).fetchall()
        comps=con.execute('select c.company_id,c.company_name,c.company_type from companies c join contact_companies cc on c.company_id=cc.company_id where cc.contact_id=?',(cid,)).fetchall()
        acts=con.execute('select * from activities where contact_id=? order by created_at desc limit 30',(cid,)).fetchall()
        latest_show=con.execute('select slug,title from showrooms where contact_id=? order by created_at desc limit 1',(cid,)).fetchone(); con.close()
        phtml=''.join(f'<tr><td>{esc(x[0])}</td><td><span class="pill">{esc(x[1])}</span></td><td>{esc(x[2] or "—")}</td><td>{esc(x[3] or "—")}</td><td>{esc(x[4] or "—")}</td></tr>' for x in perms)
        comphtml=''.join(f'<div>{esc(x[1])} · {esc(x[2] or "")}</div>' for x in comps) or 'No company linked yet.'
        score=r['lead_score'] or 0
        share=''
        if latest_show:
            base=public_base_url() or f'http://127.0.0.1:{PORT}'
            share=base+'/s/'+latest_show['slug']
        phone=re.sub(r'\D','',r['phone_number'] or '')
        wa_text=quote((f"Hello, I wanted to share a collection selected for you: {share}" if share else "Hello, I wanted to connect regarding our saree collection."))
        wa=f'https://wa.me/{phone}?text={wa_text}' if phone else ''
        mail=f'mailto:{quote(r["email"] or "")}?subject={quote("A collection selected for you")}&body={wa_text}' if r['email'] else ''
        actrows=''.join(f'<tr><td>{esc(a["created_at"])}</td><td>{esc(a["activity_type"])}</td><td>{esc(a["channel"])}</td><td>{esc(a["direction"])}</td><td>{esc(a["summary"])}</td><td>{esc(a["follow_up_at"] or "—")}</td></tr>' for a in acts)
        quick=''.join(x for x in [f'<a class="btn good" target="_blank" href="{wa}">Open WhatsApp</a>' if wa else '', f'<a class="btn secondary" href="{mail}">Draft email</a>' if mail else ''])
        body=f'''<div class="top"><div><h1>{esc(r['full_name'] or r['username'] or 'Unnamed contact')}</h1><div class="sub">@{esc(r['username'])} · {esc(r['source_name'])}</div></div><div class="actions">{quick}<a class="btn" href="/showrooms/new?contact_id={quote(cid)}">Create showroom</a><a class="btn secondary" href="/contacts">Back</a></div></div>
        <div class="two"><div class="card"><h2>Contact intelligence</h2><div class="kv"><div>Lead score</div><div><span class="score {'high' if score>=75 else 'mid' if score>=45 else 'low'}">{score}/100</span></div><div>Category</div><div>{esc(r['business_category'] or '—')}</div><div>Reason</div><div>{esc(r['relevance_reason'] or 'Not enriched yet')}</div><div>Data quality</div><div>{esc(r['data_quality'] or 'Unknown')}</div><div>Type</div><div><span class="pill {str(r['contact_type']).lower()}">{esc(r['contact_type'])}</span></div><div>Email</div><div>{esc(r['email'] or '—')}</div><div>Phone</div><div>{esc(r['phone_number'] or '—')}</div><div>Website</div><div>{esc(r['website'] or '—')}</div><div>Country</div><div>{esc(r['country'] or '—')}</div><div>Next follow-up</div><div>{esc(r['next_follow_up'] or '—')}</div><div>Biography</div><div>{esc(r['biography'] or '—')}</div><div>Company</div><div>{comphtml}</div></div>{'' if comps or r['contact_type'] not in ('B2B','Both') else f'<form method="post" action="/contacts/{esc(cid)}/create-company" style="margin-top:16px"><button class="btn secondary">Create company from this contact</button></form>'}</div>
        <div class="card"><h2>Qualification</h2><form method="post" action="/contacts/{esc(cid)}/update"><div style="display:grid;gap:10px"><label>Contact type<br><select name="contact_type">{''.join(f'<option {"selected" if r["contact_type"]==x else ""}>{x}</option>' for x in ['B2B','B2C','Both','Unknown'])}</select></label><label>Qualification<br><select name="qualification_status">{''.join(f'<option {"selected" if r["qualification_status"]==x else ""}>{x}</option>' for x in ['Unreviewed','Qualified','Needs Review','Irrelevant','Do Not Contact'])}</select></label><label>Lifecycle stage<br><select name="lifecycle_stage">{''.join(f'<option {"selected" if r["lifecycle_stage"]==x else ""}>{x}</option>' for x in ['New','Contacted','Engaged','Qualified','Customer','Repeat Customer','Inactive'])}</select></label><label>Country<br><input type="text" name="country" value="{esc(r['country'])}"></label><label>Language<br><input type="text" name="language" value="{esc(r['language'])}"></label><label>Niche<br><input type="text" name="niche" value="{esc(r['niche'])}"></label><label>Business category<br><input type="text" name="business_category" value="{esc(r['business_category'])}"></label><button class="btn">Save changes</button></div></form></div></div>
        <div class="two section"><div><h2>Activity timeline</h2><table><tr><th>When</th><th>Type</th><th>Channel</th><th>Direction</th><th>Summary</th><th>Follow-up</th></tr>{actrows or '<tr><td colspan="6" class="empty">No activity yet.</td></tr>'}</table></div><div class="card"><h2>Log activity</h2><form method="post" action="/activities/create"><input type="hidden" name="contact_id" value="{esc(cid)}"><div style="display:grid;gap:10px"><div class="formgrid"><label>Type<br><select name="activity_type"><option>Note</option><option>Email</option><option>WhatsApp</option><option>Call</option><option>Meeting</option><option>Follow-up</option></select></label><label>Channel<br><select name="channel"><option>Other</option><option>Email</option><option>WhatsApp</option><option>Phone</option><option>Website</option></select></label></div><label>Direction<br><select name="direction"><option>Outbound</option><option>Inbound</option><option>Internal</option></select></label><label>Summary<br><textarea name="summary" required></textarea></label><label>Follow-up date/time<br><input type="datetime-local" name="follow_up_at"></label><button class="btn">Save activity</button></div></form></div></div>
        <div class="section"><h2>Marketing permissions</h2><table><tr><th>Channel</th><th>Status</th><th>Basis / reason</th><th>Jurisdiction</th><th>Updated</th></tr>{phtml or '<tr><td colspan="5" class="empty">No channel permissions recorded.</td></tr>'}</table><div class="card" style="margin-top:12px"><form method="post" action="/permissions/update" class="filters"><input type="hidden" name="contact_id" value="{esc(cid)}"><select name="channel"><option>Email</option><option>WhatsApp</option><option>Phone</option><option>SMS</option><option>Other</option></select><select name="status"><option>Unknown</option><option>Allowed</option><option>OptedIn</option><option>OptedOut</option><option>Suppressed</option><option>DoNotContact</option></select><input name="reason" placeholder="Basis / evidence / reason"><button class="btn">Update permission</button></form></div></div>'''
        self.send_html(layout('Contact',body,'contacts'))

    def companies(self):
        con=db(); rows=con.execute('''select c.*, count(cc.contact_id) contacts from companies c left join contact_companies cc on c.company_id=cc.company_id group by c.company_id order by c.created_at desc''').fetchall(); con.close()
        trs=''.join(f'<tr><td>{esc(r["company_name"])}</td><td>{esc(r["company_type"] or "—")}</td><td>{esc(r["website"] or "—")}</td><td>{esc(r["country"] or "—")}</td><td>{r["contacts"]}</td><td>{esc(r["wholesale_tier"] or "—")}</td></tr>' for r in rows)
        body=f'<div class="top"><div><h1>Companies</h1><div class="sub">{len(rows)} B2B account records</div></div></div><table><tr><th>Company name</th><th>Type</th><th>Website</th><th>Country</th><th>Contacts</th><th>Wholesale tier</th></tr>{trs or "<tr><td colspan=6 class=empty>Create companies from qualified B2B contact profiles.</td></tr>"}</table>'
        self.send_html(layout('Companies',body,'companies'))

    def products(self):
        con=db(); rows=con.execute('''select p.*, (select relative_path from product_images i where i.product_id=p.product_id order by is_primary desc limit 1) img from products p order by created_at''').fetchall(); con.close()
        cards=''.join(f'''<a href="/products/{esc(r['product_id'])}" style="text-decoration:none;color:inherit"><div class="product">{f'<img src="/{esc(r["img"])}">' if r['img'] else '<div style="aspect-ratio:4/5;background:#eee"></div>'}<div class="pbody"><h3>{esc(r['public_product_name'] or r['internal_sku'])}</h3><p>{esc(r['internal_sku'])} · {esc(r['colour'])}</p><p style="margin-top:6px"><span class="pill">{esc(r['status'])}</span> · {money(r['retail_price'],r['currency'])}</p></div></div></a>''' for r in rows)
        body=f'<div class="top"><div><h1>Products</h1><div class="sub">Editable product catalogue</div></div><a class="btn" href="/showrooms/new">Build showroom</a></div><div class="product-grid">{cards}</div>'
        self.send_html(layout('Products',body,'products'))

    def product(self,pid):
        con=db(); r=con.execute('select * from products where product_id=?',(pid,)).fetchone(); imgs=con.execute('select * from product_images where product_id=? order by is_primary desc,image_role',(pid,)).fetchall(); con.close()
        if not r: return self.send_error(404)
        gallery=''.join(f'<div><img src="/{esc(i["relative_path"])}"><div class="sub" style="margin-top:4px">{esc(i["image_role"])}</div></div>' for i in imgs)
        body=f'''<div class="top"><div><h1>{esc(r['public_product_name'])}</h1><div class="sub">{esc(r['internal_sku'])}</div></div><a class="btn secondary" href="/products">Back</a></div><div class="two"><div class="card"><div class="gallery">{gallery}</div></div><div class="card"><h2>Edit product</h2><form method="post" action="/products/{esc(pid)}/update"><div style="display:grid;gap:10px"><label>Name<br><input name="public_product_name" value="{esc(r['public_product_name'])}"></label><label>Product code / SKU<br><input name="product_code" value="{esc(r['product_code'] or r['internal_sku'])}"></label><div class="formgrid"><label>Colour<br><input name="colour" value="{esc(r['colour'])}"></label><label>Fabric<br><input name="fabric" value="{esc(r['fabric'])}"></label><label>Weave / motif<br><input name="weave_or_motif" value="{esc(r['weave_or_motif'])}"></label><label>Category<br><input name="category" value="{esc(r['category'])}"></label><label>Retail price<br><input type="number" step="0.01" name="retail_price" value="{esc(r['retail_price'])}"></label><label>Wholesale price<br><input type="number" step="0.01" name="wholesale_price" value="{esc(r['wholesale_price'])}"></label><label>Currency<br><select name="currency">{''.join(f'<option {"selected" if r["currency"]==x else ""}>{x}</option>' for x in ['INR','GBP','USD','EUR'])}</select></label><label>Stock<br><input type="number" name="stock_qty" value="{esc(r['stock_qty'])}"></label><label>MOQ<br><input type="number" name="moq" value="{esc(r['moq'])}"></label><label>Status<br><select name="status">{''.join(f'<option {"selected" if r["status"]==x else ""}>{x}</option>' for x in ['Draft','Active','Archived','Sold Out'])}</select></label></div><label>Tags<br><input name="tags" value="{esc(r['tags'])}" placeholder="bridal, red, premium"></label><label>Description<br><textarea name="description">{esc(r['description'])}</textarea></label><button class="btn">Save product</button></div></form><div class="note" style="margin-top:16px">Source filenames remain traceability metadata only and are not your brand. {('Possible duplicate group: '+esc(r['duplicate_group'])) if r['duplicate_group'] else ''}</div></div></div>'''
        self.send_html(layout('Product',body,'products'))

    def new_showroom(self,q):
        cid=q.get('contact_id',[''])[0]
        con=db(); contacts=con.execute("select contact_id,full_name,username,contact_type,lead_score from contacts where qualification_status not in ('Irrelevant','Do Not Contact') order by lead_score desc limit 750").fetchall(); products=con.execute('''select p.product_id,p.public_product_name,p.internal_sku,p.product_code,p.colour,p.retail_price,p.wholesale_price,p.currency,p.duplicate_group,(select relative_path from product_images i where i.product_id=p.product_id order by is_primary desc limit 1) img from products p where status!='Archived' order by created_at''').fetchall(); con.close()
        opts=''.join(f'<option value="{esc(r[0])}" {"selected" if cid==r[0] else ""}>{esc(r[1] or r[2])} · {esc(r[3])} · score {r[4] or 0}</option>' for r in contacts)
        checks=''
        for r in products:
            image='<img src="/'+esc(r[9])+'">' if r[9] else ''
            duplicate=' · possible duplicate' if r[8] else ''
            checks+=f'<label class="check"><input type="checkbox" name="product_ids" value="{esc(r[0])}" checked>{image}<span><strong>{esc(r[1] or r[2])}</strong><br><span class="sub">{esc(r[3])} · {esc(r[4])} · Retail {money(r[5],r[7])} · Wholesale {money(r[6],r[7])}{duplicate}</span></span></label>'
        body=f'''<div class="top"><div><h1>Create personalised showroom</h1><div class="sub">Choose a prospect, message, pricing and products.</div></div></div><form method="post" action="/showrooms/create"><div class="two"><div class="card"><div style="display:grid;gap:12px"><label>Contact<br><select name="contact_id" style="width:100%"><option value="">No contact / generic showroom</option>{opts}</select></label><label>Showroom title<br><input name="title" value="A collection selected for you" style="width:100%"></label><label>Personalised introduction<br><textarea name="intro_text">Selected pieces from our current collection that may be relevant for you.</textarea></label><div class="formgrid"><label>Pricing mode<br><select name="pricing_mode"><option>Hidden</option><option>Wholesale</option><option>Retail</option></select></label><label>CTA text<br><input name="cta_text" value="Ask about this piece"></label></div></div></div><div class="card"><h2>What happens next</h2><div class="sub">The system creates a private showroom, tracks views and product-interest clicks, and displays only the selected products. No marketing message is sent automatically.</div><div class="note" style="margin-top:16px">To share outside your Mac, set an online Public Base URL in Settings after deployment.</div></div></div><div class="section"><h2>Select products</h2><div class="checkgrid">{checks}</div></div><div class="section"><button class="btn">Create showroom</button></div></form>'''
        self.send_html(layout('Create Showroom',body,'showrooms'))

    def showrooms(self):
        con=db(); rows=con.execute('''select s.*,c.full_name,c.username,(select count(*) from showroom_products sp where sp.showroom_id=s.showroom_id) product_count,(select count(*) from showroom_views sv where sv.showroom_id=s.showroom_id) view_count from showrooms s left join contacts c on s.contact_id=c.contact_id order by s.created_at desc''').fetchall(); con.close()
        trs=''.join(f'<tr><td><a class="link" href="/showrooms/{esc(r["showroom_id"])}">{esc(r["title"])}</a></td><td>{esc(r["full_name"] or r["username"] or "Generic")}</td><td>{esc(r["pricing_mode"])}</td><td>{r["product_count"]}</td><td>{r["view_count"]}</td><td><a class="link" href="/s/{esc(r["slug"])}" target="_blank">Open</a></td></tr>' for r in rows)
        body=f'<div class="top"><div><h1>Showrooms</h1><div class="sub">{len(rows)} personalised digital showrooms</div></div><a class="btn" href="/showrooms/new">Create showroom</a></div><table><tr><th>Title</th><th>Contact</th><th>Pricing</th><th>Products</th><th>Views</th><th>Preview</th></tr>{trs or "<tr><td colspan=6 class=empty>No showrooms yet.</td></tr>"}</table>'
        self.send_html(layout('Showrooms',body,'showrooms'))

    def showroom(self,sid):
        con=db(); r=con.execute('''select s.*,c.full_name,c.username from showrooms s left join contacts c on s.contact_id=c.contact_id where s.showroom_id=?''',(sid,)).fetchone(); products=con.execute('''select p.*,(select relative_path from product_images i where i.product_id=p.product_id order by is_primary desc limit 1) img,sp.custom_price from products p join showroom_products sp on p.product_id=sp.product_id where sp.showroom_id=? order by sp.sort_order''',(sid,)).fetchall(); views=con.execute('select count(*) from showroom_views where showroom_id=?',(sid,)).fetchone()[0]; clicks=con.execute("select count(*) from showroom_events where showroom_id=? and event_type='Product Interest'",(sid,)).fetchone()[0]; con.close()
        if not r: return self.send_error(404)
        cards=''
        for p in products:
            img_tag = '<img src="/' + esc(p['img']) + '">' if p['img'] else ''
            cards += f'<div class="product">{img_tag}<div class="pbody"><h3>{esc(p["public_product_name"])}</h3><p>{esc(p["product_code"] or p["internal_sku"])} · {esc(p["colour"])} · {esc(p["fabric"] or "")}</p></div></div>'
        base=public_base_url() or f'http://127.0.0.1:{PORT}'; share=base+'/s/'+r['slug']
        scope='Public share URL' if public_base_url() else 'Local preview URL'
        warn='' if public_base_url() else '<div class="note" style="margin-top:14px">This is still local-only. Set Public Base URL in Settings after deployment before sending the link to prospects.</div>'
        body=f'''<div class="top"><div><h1>{esc(r['title'])}</h1><div class="sub">For {esc(r['full_name'] or r['username'] or 'generic audience')} · {views} views · {clicks} product-interest clicks</div></div><div class="actions"><a class="btn" target="_blank" href="/s/{esc(r['slug'])}">Open prospect view</a><a class="btn secondary" href="/showrooms">Back</a></div></div><div class="card"><div class="kv"><div>Pricing</div><div>{esc(r['pricing_mode'])}</div><div>Status</div><div>{esc(r['status'])}</div><div>{scope}</div><div>{esc(share)}</div><div>Introduction</div><div>{esc(r['intro_text'] or '—')}</div></div>{warn}</div><div class="product-grid section">{cards}</div>'''
        self.send_html(layout('Showroom',body,'showrooms'))

    def showroom_interest(self,slug,pid):
        con=db(); r=con.execute('select showroom_id,title from showrooms where slug=?',(slug,)).fetchone(); p=con.execute('select public_product_name,product_code from products where product_id=?',(pid,)).fetchone()
        if not r or not p: con.close(); return self.send_error(404)
        con.execute('insert into showroom_events(event_id,showroom_id,product_id,event_type,user_agent) values(?,?,?,?,?)',('EVT-'+uuid.uuid4().hex[:12].upper(),r['showroom_id'],pid,'Product Interest',self.headers.get('User-Agent',''))); con.commit(); con.close()
        bw=re.sub(r'\D','',setting('business_whatsapp',''))
        if bw:
            text=quote(f"Hello, I am interested in {p['public_product_name']} ({p['product_code'] or pid}) from the showroom {r['title']}.")
            return self.redirect(f'https://wa.me/{bw}?text={text}')
        body=f'''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Interest recorded</title></head><body style="font-family:-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif;padding:40px;background:#f7f6f2"><div style="max-width:600px;margin:auto;background:white;padding:28px;border-radius:16px"><h1>Thanks — your interest is recorded</h1><p>Product: {esc(p['public_product_name'])}</p><p>The seller can see this interest in their CRM.</p></div></body></html>'''
        self.send_html(body)

    def public_showroom(self,slug):
        con=db(); r=con.execute('''select s.*,c.full_name,c.username from showrooms s left join contacts c on s.contact_id=c.contact_id where s.slug=? and coalesce(s.public_enabled,1)=1''',(slug,)).fetchone()
        if not r: con.close(); return self.send_error(404)
        con.execute('insert into showroom_views(view_id,showroom_id,user_agent) values(?,?,?)',('VW-'+uuid.uuid4().hex[:12].upper(),r['showroom_id'],self.headers.get('User-Agent',''))); con.commit()
        products=con.execute('''select p.*,(select relative_path from product_images i where i.product_id=p.product_id order by is_primary desc limit 1) img,sp.custom_price from products p join showroom_products sp on p.product_id=sp.product_id where sp.showroom_id=? order by sp.sort_order''',(r['showroom_id'],)).fetchall(); con.close()
        cards=''; brand=setting('brand_name','')
        for p in products:
            price=''
            if r['pricing_mode']=='Retail': price=f'<p><strong>{money(p["retail_price"],p["currency"])}</strong></p>'
            elif r['pricing_mode']=='Wholesale': price=f'<p><strong>{money(p["wholesale_price"],p["currency"])}</strong></p>'
            img_tag = '<img src="/' + esc(p['img']) + '">' if p['img'] else ''
            cards += f'<div class="showcard">{img_tag}<div class="pbody"><h3>{esc(p["public_product_name"])}</h3><p class="sub">{esc(p["colour"])} · {esc(p["fabric"] or "")} · {esc(p["product_code"] or p["internal_sku"])}</p>{price}<a class="cta" href="/interest/{esc(slug)}/{esc(p["product_id"])}">{esc(r["cta_text"] or "Ask about this piece")}</a></div></div>'
        who=esc(r['full_name'] or r['username'] or '')
        body=f'''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{esc(r['title'])}</title><style>body{{margin:0;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;background:#f7f6f2;color:#1f201d}} .public{{max-width:1120px;margin:auto;padding:34px 24px 70px}} .hero{{padding:30px 0}} .sub{{color:#74766f}} .showgrid{{display:grid;grid-template-columns:repeat(3,1fr);gap:20px}} .showcard{{background:#fff;border:1px solid #e8e6df;border-radius:14px;overflow:hidden}} .showcard img{{width:100%;aspect-ratio:4/5;object-fit:cover}} .pbody{{padding:15px}} .cta{{display:inline-block;margin-top:10px;background:#6d3f3a;color:white;text-decoration:none;padding:10px 13px;border-radius:8px;font-weight:650;font-size:13px}} @media(max-width:800px){{.showgrid{{grid-template-columns:1fr}}}}</style></head><body><div class="public"><div class="hero"><div class="sub">{esc(brand) if brand and brand!='Brand name pending' else 'Private collection'} {('for '+who) if who else ''}</div><h1>{esc(r['title'])}</h1><p class="sub">{esc(r['intro_text'] or 'Selected products from our current collection.')}</p></div><div class="showgrid">{cards}</div></div></body></html>'''
        self.send_html(body)

    def campaigns(self):
        con=db(); rows=con.execute('''select c.*, (select count(*) from campaign_members cm where cm.campaign_id=c.campaign_id) member_count from campaigns c order by created_at desc''').fetchall(); con.close()
        trs=''.join(f'<tr><td><a class="link" href="/campaigns/{esc(r["campaign_id"])}">{esc(r["campaign_name"])}</a></td><td>{esc(r["audience_type"])}</td><td>{esc(r["channel"])}</td><td>{esc(r["status"])}</td><td>{r["member_count"]}</td><td>{esc(r["created_at"])}</td></tr>' for r in rows)
        body=f'''<div class="top"><div><h1>Campaigns</h1><div class="sub">Audience planning and tracking. V3 still does not bulk-send messages automatically.</div></div></div><div class="card"><form method="post" action="/campaigns/create" class="filters"><input name="campaign_name" placeholder="Campaign name" required><select name="audience_type"><option>B2B</option><option>B2C</option><option>Both</option></select><select name="channel"><option>Email</option><option>WhatsApp</option><option>Mixed</option></select><button class="btn">Create draft</button></form></div><div class="section"><table><tr><th>Name</th><th>Audience</th><th>Channel</th><th>Status</th><th>Members</th><th>Created</th></tr>{trs or '<tr><td colspan="6" class="empty">No campaigns yet.</td></tr>'}</table></div>'''
        self.send_html(layout('Campaigns',body,'campaigns'))

    def campaign(self,camid):
        con=db(); c=con.execute('select * from campaigns where campaign_id=?',(camid,)).fetchone()
        if not c: con.close(); return self.send_error(404)
        rows=con.execute('''select cm.*,ct.full_name,ct.username,ct.email,ct.phone_number,ct.lead_score,ct.qualification_status from campaign_members cm join contacts ct on cm.contact_id=ct.contact_id where cm.campaign_id=? order by ct.lead_score desc limit 500''',(camid,)).fetchall(); con.close()
        trs=''.join(f'<tr><td><a class="link" href="/contacts/{esc(r["contact_id"])}">{esc(r["full_name"] or r["username"])}</a></td><td>{esc(r["email"] or "—")}</td><td>{esc(r["phone_number"] or "—")}</td><td>{r["lead_score"] or 0}</td><td>{esc(r["member_status"])}</td></tr>' for r in rows)
        body=f'''<div class="top"><div><h1>{esc(c['campaign_name'])}</h1><div class="sub">{esc(c['audience_type'])} · {esc(c['channel'])} · {len(rows)} members shown</div></div><a class="btn secondary" href="/campaigns">Back</a></div><div class="card"><form method="post" action="/campaigns/{esc(camid)}/populate"><button class="btn">Add qualified score 75+ audience</button></form><div class="note" style="margin-top:12px">This creates a reviewable campaign audience. It does not send messages. Channel permissions must still be checked per contact.</div></div><div class="section"><table><tr><th>Contact</th><th>Email</th><th>Phone</th><th>Score</th><th>Status</th></tr>{trs or '<tr><td colspan="5" class="empty">No members yet.</td></tr>'}</table></div>'''
        self.send_html(layout('Campaign',body,'campaigns'))

    def opportunities(self):
        con=db(); rows=con.execute('''select o.*,c.full_name,c.username from opportunities o left join contacts c on o.contact_id=c.contact_id order by o.created_at desc''').fetchall(); contacts=con.execute("select contact_id,full_name,username from contacts where qualification_status='Qualified' order by lead_score desc limit 500").fetchall(); shows=con.execute('select showroom_id,title from showrooms order by created_at desc limit 200').fetchall(); con.close()
        trs=''.join(f'<tr><td>{esc(r["name"])}</td><td>{esc(r["full_name"] or r["username"] or "—")}</td><td>{esc(r["stage"])}</td><td>{money(r["estimated_value"],r["currency"])}</td><td>{esc(r["expected_close_date"] or "—")}</td></tr>' for r in rows)
        copts=''.join(f'<option value="{esc(x[0])}">{esc(x[1] or x[2])}</option>' for x in contacts); sopts=''.join(f'<option value="{esc(x[0])}">{esc(x[1])}</option>' for x in shows)
        body=f'''<div class="top"><div><h1>Opportunities</h1><div class="sub">Track B2B/B2C potential revenue from contact to close.</div></div></div><div class="card"><form method="post" action="/opportunities/create"><div class="formgrid"><label>Name<br><input name="name" required></label><label>Contact<br><select name="contact_id"><option value="">None</option>{copts}</select></label><label>Stage<br><select name="stage"><option>New</option><option>Qualified</option><option>Showroom Sent</option><option>Negotiation</option><option>Won</option><option>Lost</option></select></label><label>Estimated value<br><input type="number" step="0.01" name="estimated_value"></label><label>Currency<br><select name="currency">{''.join(f'<option>{x}</option>' for x in ['INR','GBP','USD','EUR'])}</select></label><label>Expected close<br><input type="date" name="expected_close_date"></label><label>Showroom<br><select name="showroom_id"><option value="">None</option>{sopts}</select></label><label>Notes<br><input name="notes"></label></div><button class="btn" style="margin-top:12px">Create opportunity</button></form></div><div class="section"><table><tr><th>Name</th><th>Contact</th><th>Stage</th><th>Value</th><th>Expected close</th></tr>{trs or '<tr><td colspan="5" class="empty">No opportunities yet.</td></tr>'}</table></div>'''
        self.send_html(layout('Opportunities',body,'opportunities'))

    def orders(self):
        con=db(); rows=con.execute('''select o.*,c.full_name,c.username from orders o left join contacts c on o.contact_id=c.contact_id order by o.ordered_at desc''').fetchall(); contacts=con.execute("select contact_id,full_name,username,contact_type from contacts where lifecycle_stage in ('Engaged','Qualified','Customer','Repeat Customer') or qualification_status='Qualified' order by lead_score desc limit 750").fetchall(); con.close()
        trs=''.join(f'<tr><td>{esc(r["order_id"])}</td><td>{esc(r["full_name"] or r["username"] or "—")}</td><td>{esc(r["order_type"])}</td><td>{esc(r["order_status"])}</td><td>{money(r["total"],r["currency"])}</td><td>{esc(r["ordered_at"] or "—")}</td></tr>' for r in rows)
        copts=''.join(f'<option value="{esc(x[0])}">{esc(x[1] or x[2])} · {esc(x[3])}</option>' for x in contacts)
        body=f'''<div class="top"><div><h1>Orders</h1><div class="sub">Manual order ledger until Shopify/payment integrations are connected.</div></div></div><div class="card"><form method="post" action="/orders/create"><div class="formgrid"><label>Contact<br><select name="contact_id"><option value="">None</option>{copts}</select></label><label>Order type<br><select name="order_type"><option>B2C</option><option>B2B</option></select></label><label>Status<br><select name="order_status"><option>Draft</option><option>Pending</option><option>Paid</option><option>Fulfilled</option><option>Cancelled</option></select></label><label>Total<br><input type="number" step="0.01" name="total"></label><label>Currency<br><select name="currency">{''.join(f'<option>{x}</option>' for x in ['INR','GBP','USD','EUR'])}</select></label><label>External reference<br><input name="external_order_reference" placeholder="Shopify/payment/reference"></label></div><button class="btn" style="margin-top:12px">Create order</button></form></div><div class="section"><table><tr><th>Order</th><th>Contact</th><th>Type</th><th>Status</th><th>Total</th><th>Ordered</th></tr>{trs or '<tr><td colspan="6" class="empty">No orders yet.</td></tr>'}</table></div>'''
        self.send_html(layout('Orders',body,'orders'))

    def settings(self,q):
        vals={k:setting(k,'') for k in ['brand_name','business_whatsapp','business_email','public_base_url','default_currency','booking_url']}
        saved='<div class="note" style="margin-bottom:16px">Settings saved.</div>' if q.get('saved') else ''
        body=f'''<div class="top"><div><h1>Settings</h1><div class="sub">Brand, contact details and deployment settings.</div></div></div>{saved}<div class="two"><div class="card"><h2>Business settings</h2><form method="post" action="/settings/update"><div style="display:grid;gap:12px"><label>Brand name<br><input name="brand_name" value="{esc(vals['brand_name'])}" style="width:100%"></label><label>Business WhatsApp number<br><input name="business_whatsapp" value="{esc(vals['business_whatsapp'])}" placeholder="e.g. +919876543210" style="width:100%"></label><label>Business email<br><input type="email" name="business_email" value="{esc(vals['business_email'])}" style="width:100%"></label><label>Booking URL<br><input name="booking_url" value="{esc(vals['booking_url'])}" style="width:100%"></label><label>Default currency<br><select name="default_currency">{''.join(f'<option {"selected" if vals["default_currency"]==x else ""}>{x}</option>' for x in ['INR','GBP','USD','EUR'])}</select></label><label>Public Base URL<br><input name="public_base_url" value="{esc(vals['public_base_url'])}" placeholder="https://crm.yourdomain.com" style="width:100%"></label><button class="btn">Save settings</button></div></form></div><div class="card"><h2>Deployment readiness</h2><div class="kv"><div>Local app</div><div>Ready</div><div>Public URL configured</div><div>{'Yes' if vals['public_base_url'] else 'No'}</div><div>WhatsApp CTA configured</div><div>{'Yes' if vals['business_whatsapp'] else 'No'}</div></div><div class="note" style="margin-top:16px">Do not expose this CRM publicly without authentication and HTTPS. The package includes deployment files, but hosting credentials are intentionally not embedded.</div></div></div>'''
        self.send_html(layout('Settings',body,'settings'))

    def simple_table(self,title,table,cols,active):
        con=db(); rows=con.execute('select '+','.join(cols)+' from '+table+' order by rowid desc limit 200').fetchall(); con.close(); head=''.join('<th>'+esc(c.replace('_',' '))+'</th>' for c in cols); trs=''.join('<tr>'+''.join('<td>'+esc(v if v not in (None,'') else '—')+'</td>' for v in row)+'</tr>' for row in rows)
        body=f'<div class="top"><div><h1>{esc(title)}</h1><div class="sub">{len(rows)} records shown</div></div></div><table><tr>{head}</tr>{trs or f"<tr><td colspan={len(cols)} class=empty>No records yet.</td></tr>"}</table>'
        self.send_html(layout(title,body,active))


if __name__=='__main__':
    ensure_schema()
    print(f'\nCommerce Business OS V3 is running at http://{HOST}:{PORT}\nPress Control+C to stop.\n')
    ThreadingHTTPServer((HOST,PORT),App).serve_forever()
