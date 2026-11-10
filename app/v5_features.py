from __future__ import annotations
import runtime_config as rc
import csv, datetime as dt, html, io, json, os, re, secrets, shutil, sqlite3, urllib.error, urllib.parse, urllib.request
from pathlib import Path
import marketing as m

ROOT=Path(__file__).resolve().parent

def e(v): return html.escape('' if v is None else str(v), quote=True)
def uid(prefix): return prefix+'-'+secrets.token_hex(6).upper()
def val(v,limit=500): return (v or '').strip()[:limit]
def slugify(v):
    s=re.sub(r'[^a-z0-9]+','-',(v or '').lower()).strip('-')
    return s[:90] or 'draft'

def initialise():
    with m.connect() as con:
        con.executescript('''
        CREATE TABLE IF NOT EXISTS v5_blogs(
          id TEXT PRIMARY KEY,title TEXT,primary_keyword TEXT,secondary_keywords TEXT,region TEXT,language TEXT,
          audience TEXT,intent TEXT,tone TEXT,meta_title TEXT,meta_description TEXT,slug TEXT,excerpt TEXT,
          outline_json TEXT,content TEXT,sources_json TEXT,status TEXT DEFAULT 'Draft',engine TEXT,created_at TEXT DEFAULT CURRENT_TIMESTAMP,updated_at TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS v5_growth_plans(
          id TEXT PRIMARY KEY,name TEXT,audience TEXT,region TEXT,goal TEXT,channels_json TEXT,product_ids_json TEXT,
          brief TEXT,recommendation_json TEXT,engine TEXT,status TEXT DEFAULT 'Draft',created_at TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS v5_product_imports(
          id TEXT PRIMARY KEY,filename TEXT,status TEXT DEFAULT 'Preview',report_json TEXT,created_at TEXT DEFAULT CURRENT_TIMESTAMP);
        ''')
    # Product creation writes stock through the canonical location ledger.
    # Initialise that dependency even when this module is used on its own in a
    # clean/imported workspace instead of through app.initialise().
    import platform_core as _pc
    import v35_truth as truth
    _pc._ensure_stock_location_schema()
    truth.initialise()

# ---------- products ----------
def next_sku(con):
    n=con.execute("SELECT count(*) FROM products").fetchone()[0]+1
    while con.execute('SELECT 1 FROM products WHERE internal_sku=?',(f'PRD-{n:05d}',)).fetchone(): n+=1
    return f'PRD-{n:05d}'

def create_product(raw:dict, image:tuple[bytes,str]|None=None):
    name=val(raw.get('public_product_name'),180)
    if not name: raise ValueError('Enter a product name.')
    requested_stock=val(raw.get('stock_qty'),20)
    if requested_stock:
        try: requested_stock_int=int(requested_stock)
        except ValueError: raise ValueError('Stock quantity must be a whole number.') from None
        if requested_stock_int<0: raise ValueError('Stock quantity cannot be negative.')
    else: requested_stock_int=0
    with m.connect() as con:
        sku=val(raw.get('internal_sku'),80) or next_sku(con)
        if con.execute('SELECT 1 FROM products WHERE internal_sku=?',(sku,)).fetchone(): raise ValueError('That SKU already exists.')
        pid=uid('PRD')
        data={
          'product_id':pid,'internal_sku':sku,'product_code':val(raw.get('product_code'),80) or sku,
          'source_product_name':val(raw.get('source_product_name'),180),'public_product_name':name,
          'colour':val(raw.get('colour'),100),'weave_or_motif':val(raw.get('weave_or_motif'),180),'fabric':val(raw.get('fabric'),180),
          'category':val(raw.get('category'),120) or 'Banarasi Saree','description':val(raw.get('description'),5000),
          'currency':val(raw.get('currency'),8) or 'INR','status':val(raw.get('status'),30) or 'Draft','tags':val(raw.get('tags'),1000),
        }
        for key in ['cost_price','retail_price','wholesale_price']:
            x=val(raw.get(key),40); data[key]=float(x) if x else None
        # ``products.stock_qty`` is a compatibility cache only.  New stock is
        # written to canonical location inventory below and the cache is derived.
        data['stock_qty']=0
        x=val(raw.get('moq'),20); data['moq']=int(x) if x else None
        cols={r['name'] for r in con.execute('PRAGMA table_info(products)')}
        data={k:v for k,v in data.items() if k in cols}
        con.execute('INSERT INTO products('+','.join(data)+') VALUES('+','.join('?'*len(data))+')',tuple(data.values()))
    # Every product gets a canonical inventory row immediately, including a
    # zero-balance product.  This prevents UI-entered stock from living only in
    # the legacy products.stock_qty cache.
    import v35_truth as truth
    truth.initialise()
    truth.adjust_stock_to(pid,'MAIN',requested_stock_int,'Initial stock from product creation')
    if image: save_product_image(pid,*image)
    m.audit('product.created',pid,'Created manually in V5')
    return pid

def save_product_image(pid,raw:bytes,filename:str):
    if len(raw)>12*1024*1024: raise ValueError('Keep each product image under 12 MB.')
    ext=Path(filename).suffix.lower()
    if ext not in {'.jpg','.jpeg','.png','.webp'}: raise ValueError('Use JPG, PNG or WEBP product images.')
    folder=rc.STATIC_ROOT/'uploads'/'products'/pid; folder.mkdir(parents=True,exist_ok=True)
    clean='primary'+ext; dest=folder/clean; dest.write_bytes(raw)
    rel='static/uploads/products/'+pid+'/'+clean
    with m.connect() as con:
        con.execute('INSERT INTO product_images(image_id,product_id,image_role,original_filename,source_archive,relative_path,is_primary) VALUES(?,?,?,?,?,?,1)',(uid('IMG'),pid,'Primary',Path(filename).name,'Manual upload',rel))
    return rel

def product_csv_preview(raw:bytes):
    if len(raw)>8*1024*1024: raise ValueError('Keep product CSV files under 8 MB.')
    try:text=raw.decode('utf-8-sig')
    except UnicodeDecodeError: raise ValueError('Save the product file as UTF-8 CSV.') from None
    rows=list(csv.DictReader(io.StringIO(text)))
    if len(rows)>5000: raise ValueError('Import up to 5,000 products at a time.')
    expected={'public_product_name','internal_sku','colour','fabric','weave_or_motif','category','description','cost_price','retail_price','wholesale_price','currency','stock_qty','moq','tags'}
    if not rows or not expected.intersection(rows[0]): raise ValueError('Use the product CSV template headings.')
    report=[]; seen=set()
    with m.connect() as con:
        existing={x[0] for x in con.execute('SELECT internal_sku FROM products WHERE internal_sku IS NOT NULL')}
        for i,r in enumerate(rows,2):
            name=val(r.get('public_product_name'),180); sku=val(r.get('internal_sku'),80)
            if not name: report.append({'row':i,'action':'Skip','reason':'Missing product name','data':r}); continue
            if sku and (sku in existing or sku in seen): report.append({'row':i,'action':'Skip','reason':'SKU already exists or repeats in this file','data':r}); continue
            bad=''
            for key in ['cost_price','retail_price','wholesale_price']:
                x=val(r.get(key),40)
                if x:
                    try: float(x)
                    except ValueError: bad=key+' must be a number'; break
            if not bad:
                for key in ['stock_qty','moq']:
                    x=val(r.get(key),20)
                    if x:
                        try: int(x)
                        except ValueError: bad=key+' must be a whole number'; break
            if bad: report.append({'row':i,'action':'Skip','reason':bad,'data':r}); continue
            if sku: seen.add(sku)
            report.append({'row':i,'action':'Add','reason':'Ready','data':r})
    return report

def commit_product_csv(report):
    made=0
    for row in report:
        if row['action']=='Add': create_product(row['data']); made+=1
    return made

# ---------- AI helpers ----------
def ai_key(): return m.secret()
def ai_model(): return m.routed_model('seo_strategy','gpt-6-sol')
def response_text(out):
    return ''.join(part.get('text','') for item in out.get('output',[]) if item.get('type')=='message' for part in item.get('content',[]) if part.get('type')=='output_text')
def citations(out):
    seen=[]
    for item in out.get('output',[]):
        for part in item.get('content',[]) if item.get('type')=='message' else []:
            for a in part.get('annotations',[]) or []:
                if a.get('type')=='url_citation':
                    u=a.get('url'); title=a.get('title') or u
                    if u and u not in {x['url'] for x in seen}: seen.append({'url':u,'title':title})
    return seen

def call_ai(system,user,schema,name,max_tokens=4500,web=False):
    """Central V44 Responses execution for legacy product/growth helpers."""
    import ai_router
    try:
        import operating_core as oc
        oc.guard_ai_call('general')
    except ImportError:
        oc=None
    state=ai_router.preflight('seo_strategy',default_model=ai_model())
    body={'model':state['model'],'store':False,'max_output_tokens':max_tokens,
          'input':[{'role':'system','content':system},{'role':'user','content':json.dumps(user,ensure_ascii=False)}],
          'text':{'format':{'type':'json_schema','name':name,'strict':True,'schema':schema}}}
    if web: body['tools']=[{'type':'web_search'}]
    out,attempts,duration_ms=ai_router.request_json('seo_strategy',body,max_attempts=3)
    if out.get('status') not in {None,'completed'}:
        ai_router.record_failure('seo_strategy','OpenAI',state['model'],error='Provider response status: '+str(out.get('status')),attempts=attempts,duration_ms=duration_ms)
        raise ValueError('AI response did not complete. Nothing was saved.')
    try:
        data=json.loads(response_text(out))
    except Exception:
        ai_router.record_failure('seo_strategy','OpenAI',state['model'],error='Response parsing failed: expected JSON schema output.',attempts=attempts,duration_ms=duration_ms)
        raise ValueError('AI returned an unusable response. Nothing was saved.') from None
    usage=out.get('usage') or {}
    ai_router.record_success('seo_strategy','OpenAI',state['model'],input_units=int(usage.get('input_tokens') or 0),output_units=int(usage.get('output_tokens') or 0),duration_ms=duration_ms,provider_request_id=str(out.get('id') or ''),attempts=attempts)
    return data,citations(out),usage

# ---------- growth intelligence ----------
def local_growth_plan(raw,products):
    aud=raw.get('audience','B2B'); region=raw.get('region') or 'your selected region'; goal=raw.get('goal') or 'Generate qualified conversations'
    channels=raw.get('channels') or ['Email','WhatsApp']
    if aud=='B2B':
        segment='Boutiques, retailers, designers and saree/textile businesses that match the selected region and have reviewed contact data.'
        angle='Lead with collection relevance, sourcing needs, MOQ/wholesale facts only when verified, and a private showroom or call as the CTA.'
    else:
        segment='Consumers with explicit preferences, enquiries, prior purchases or opted-in marketing status. Do not infer preferences from names or profiles.'
        angle='Lead with discovery, styling help and a small relevant collection; ask questions where preferences are unknown.'
    return {'summary':f'{goal} for {aud} in {region}.','segment':segment,'channel_plan':[f'{c}: reviewed draft, human approval before handoff' for c in channels],
            'message_angles':[angle,'Use only approved product facts and brand knowledge.','Follow up only where the channel status and business rules allow it.'],
            'experiments':['Test two subject/CTA variants','Compare product-led vs conversation-led opening','Track replies, showroom enquiries, quotes and actual orders separately'],
            'kpis':['Qualified replies','Showroom/product enquiries','Quotes or buying conversations','Orders and attributed revenue'],
            'next_actions':['Review audience readiness and channel permission status','Confirm product facts/pricing','Create one small channel-specific campaign','Review 10 personalised drafts before scaling']}

def growth_plan(raw,product_ids,engine='local'):
    products=[p for p in m.products() if p['product_id'] in product_ids]
    base={'name':val(raw.get('name'),180) or 'Growth plan','audience':raw.get('audience','B2B'),'region':val(raw.get('region'),180),'goal':val(raw.get('goal'),300),'channels':raw.get('channels',[]),'brief':val(raw.get('brief'),4000),'products':[{'id':p['product_id'],'name':p['public_product_name'],'verified':bool(p['confirmed']),'colour':p['colour']} for p in products]}
    if engine=='ai':
        schema={'type':'object','properties':{k:{'type':'string'} for k in ['summary','segment']}|{
          'channel_plan':{'type':'array','items':{'type':'string'}},'message_angles':{'type':'array','items':{'type':'string'}},'experiments':{'type':'array','items':{'type':'string'}},'kpis':{'type':'array','items':{'type':'string'}},'next_actions':{'type':'array','items':{'type':'string'}}},'required':['summary','segment','channel_plan','message_angles','experiments','kpis','next_actions'],'additionalProperties':False}
        system='''You are a growth-planning assistant for a Banarasi saree business. Create a practical B2B or B2C marketing plan for human review. Do not claim permission to contact, purchase intent, product facts, stock, pricing, provenance or customer preferences unless explicitly provided. Treat unverified product names as labels only. Keep channels separate. Email, WhatsApp, social DMs, SMS and phone have different permission/platform rules. Suggest experiments and measurable sales outcomes. Return only the schema.'''
        rec,_,_=call_ai(system,base,schema,'growth_plan',3000,False)
    else: rec=local_growth_plan(base,products)
    gid=uid('GROW')
    with m.connect() as con: con.execute('INSERT INTO v5_growth_plans(id,name,audience,region,goal,channels_json,product_ids_json,brief,recommendation_json,engine) VALUES(?,?,?,?,?,?,?,?,?,?)',(gid,base['name'],base['audience'],base['region'],base['goal'],json.dumps(base['channels']),json.dumps(product_ids),base['brief'],json.dumps(rec),engine))
    return gid

# ---------- blogs ----------
def local_blog(raw):
    kw=val(raw.get('primary_keyword'),180); region=val(raw.get('region'),180) or 'your market'; aud=val(raw.get('audience'),180) or 'saree buyers'
    title=f'{kw.title()}: A Practical Guide for {region}' if kw else f'A Banarasi Saree Guide for {region}'
    outline=['What to know before choosing','How to compare fabrics, weave and occasion','Questions to ask before buying','Care and styling considerations','Explore the collection or ask for guidance']
    body=f'''# {title}\n\nThis draft is a starting point for {aud}. Verify all product, provenance, material and care claims before publishing.\n\n## {outline[0]}\nStart with the occasion, preferred look, budget and the details you can verify about each saree.\n\n## {outline[1]}\nCompare colour, motif, drape, finish and verified product information rather than relying on assumptions.\n\n## {outline[2]}\nAsk about material, dimensions, blouse piece, care, availability, delivery and returns where relevant.\n\n## {outline[3]}\nGive practical care guidance only when it is supported by supplier or product evidence.\n\n## {outline[4]}\nInvite the reader to browse a curated collection or contact the business for help choosing a piece.\n'''
    return {'title':title,'meta_title':title[:60],'meta_description':f'Explore a practical guide to {kw or "Banarasi sarees"} for {region}, with buying questions and selection guidance.'[:155],'slug':slugify(title),'excerpt':f'A practical guide to {kw or "Banarasi sarees"} for {region}.','outline':outline,'content':body,'sources':[]}

def generate_blog(raw,engine='local'):
    kw=val(raw.get('primary_keyword'),180)
    if not kw: raise ValueError('Enter a primary keyword.')
    payload={k:val(raw.get(k),4000 if k=='brief' else 500) for k in ['primary_keyword','secondary_keywords','region','language','audience','intent','tone','brief']}
    research=raw.get('research')=='1'
    if engine=='ai':
        schema={'type':'object','properties':{
          'title':{'type':'string'},'meta_title':{'type':'string'},'meta_description':{'type':'string'},'slug':{'type':'string'},'excerpt':{'type':'string'},
          'outline':{'type':'array','items':{'type':'string'}},'content':{'type':'string'}},'required':['title','meta_title','meta_description','slug','excerpt','outline','content'],'additionalProperties':False}
        system='''You are an SEO content assistant for a Banarasi saree business. Draft an original, useful article for human review using the requested keyword, region and audience. Do not invent product availability, prices, discounts, silk purity, handloom status, GI status, provenance, care instructions, testimonials or local market facts. If web research is enabled, use it for current regional context and do not copy source wording. The article should answer search intent naturally, avoid keyword stuffing, include clear headings, a useful FAQ-style section when appropriate, and a soft commercial CTA. Return Markdown in content and only the requested schema. A human will fact-check before publishing.'''
        data,sources,_=call_ai(system,payload,schema,'seo_blog',7000,research)
        data['sources']=sources
    else:data=local_blog(payload)
    bid=uid('BLOG')
    with m.connect() as con: con.execute('''INSERT INTO v5_blogs(id,title,primary_keyword,secondary_keywords,region,language,audience,intent,tone,meta_title,meta_description,slug,excerpt,outline_json,content,sources_json,status,engine) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',(bid,data['title'],payload['primary_keyword'],payload['secondary_keywords'],payload['region'],payload['language'] or 'English',payload['audience'],payload['intent'],payload['tone'],data['meta_title'],data['meta_description'],slugify(data['slug']),data['excerpt'],json.dumps(data['outline']),data['content'],json.dumps(data.get('sources',[])),'Draft',engine))
    return bid

class FeaturePages:
    def v5_get(self,path,q):
        if path=='/growth': self.v5_growth(q)
        elif re.fullmatch(r'/growth/[^/]+',path): self.v5_growth_detail(path.split('/')[2])
        elif path=='/blogs': self.v5_blogs(q)
        elif path=='/blogs/new': self.v5_blog_new(q)
        elif re.fullmatch(r'/blogs/[^/]+',path): self.v5_blog_detail(path.split('/')[2])
        elif path=='/products/new': self.v5_product_new()
        elif path=='/products/import': self.v5_product_import()
        elif path=='/products/template.csv': self.send_file(('public_product_name,internal_sku,colour,fabric,weave_or_motif,category,description,cost_price,retail_price,wholesale_price,currency,stock_qty,moq,tags\n').encode(),'product_import_template.csv')
        else:return False
        return True

    def v5_post(self,path,f):
        raw={k:v[0] for k,v in f.items()}; v=lambda k,d='':raw.get(k,d)
        if path=='/products/create':
            image=getattr(self,'_product_upload',None);pid=create_product(raw,image);self.redirect('/products/'+pid)
        elif path=='/products/import/preview':
            upload=getattr(self,'_product_csv_upload',None)
            if not upload: raise ValueError('Choose a product CSV file.')
            report=product_csv_preview(upload[0]); iid=uid('PIMP')
            with m.connect() as con: con.execute('INSERT INTO v5_product_imports(id,filename,report_json) VALUES(?,?,?)',(iid,Path(upload[1]).name,json.dumps(report)))
            self.redirect('/products/import?id='+iid)
        elif path=='/products/import/commit':
            iid=v('id');r=m.one('SELECT * FROM v5_product_imports WHERE id=?',(iid,))
            if not r: raise ValueError('Product import preview not found.')
            report=json.loads(r['report_json']); made=commit_product_csv(report)
            with m.connect() as con:con.execute("UPDATE v5_product_imports SET status='Imported' WHERE id=?",(iid,))
            self.redirect('/products?imported='+str(made))
        elif path=='/growth/create':
            channels=f.get('channels',[]); products=f.get('product_ids',[]);raw['channels']=channels
            gid=growth_plan(raw,products,v('engine','local'));self.redirect('/growth/'+gid)
        elif path=='/blogs/generate':
            bid=generate_blog(raw,v('engine','local'));self.redirect('/blogs/'+bid)
        elif re.fullmatch(r'/blogs/[^/]+/save',path):
            bid=path.split('/')[2]
            with m.connect() as con:con.execute('UPDATE v5_blogs SET title=?,meta_title=?,meta_description=?,slug=?,excerpt=?,content=?,status=?,updated_at=CURRENT_TIMESTAMP WHERE id=?',(v('title')[:240],v('meta_title')[:180],v('meta_description')[:320],slugify(v('slug')),v('excerpt')[:1200],v('content')[:40000],v('status','Draft'),bid))
            self.redirect('/blogs/'+bid+'?saved=1')
        else:return False
        return True

    def v5_growth(self,q):
        import app
        # Growth can be the first V5 screen an owner opens in a new workspace.
        # Initialise its own schema instead of depending on an earlier product
        # import/blog/growth action having created v5_growth_plans.
        initialise()
        rows=m.rows('SELECT * FROM v5_growth_plans ORDER BY created_at DESC LIMIT 20')
        products=m.products(); connected=bool(m.secret())
        actions=app.button('New campaign','/campaigns/new')+app.button('SEO blog studio','/blogs','secondary')
        body=app.pagehead('Growth centre','Plan the shortest route from audience to conversation to sale.',actions)
        body+='''<div class="stats-grid"><div class="card stat-card"><span class="stat-label">1</span><strong>Choose a growth goal</strong><span class="helper">B2B stockists or B2C buyers.</span></div><div class="card stat-card"><span class="stat-label">2</span><strong>Review audience readiness</strong><span class="helper">Data quality, channel status and exclusions.</span></div><div class="card stat-card"><span class="stat-label">3</span><strong>Build channel drafts</strong><span class="helper">Email, WhatsApp, social, SMS or call scripts.</span></div><div class="card stat-card"><span class="stat-label">4</span><strong>Track real sales</strong><span class="helper">Deals, orders and explicit attribution.</span></div></div>'''
        body+='<div class="two section"><form class="card" method="post" action="/growth/create"><h2>AI-assisted growth plan</h2><p class="helper">The plan does not send anything and does not turn public contact data into permission.</p><div class="formgrid">'
        body+=app.field('Plan name','<input name="name" value="Next growth sprint" required>')+app.field('Journey','<select name="audience">'+app.options(['B2B','B2C'])+'</select>')
        body+=app.field('Region','<input name="region" placeholder="Example: India, UK, London, Mumbai">')+app.field('Goal','<select name="goal">'+app.options(['Generate qualified conversations','Introduce a new collection','Book video consultations','Re-engage previous customers','Drive showroom enquiries','Generate wholesale opportunities'])+'</select>')+'</div>'
        body+=app.field('Commercial brief','<textarea name="brief" placeholder="What are you trying to sell, who is it relevant to, and what should the prospect do next?"></textarea>')
        body+='<div class="section"><strong>Channels to include</strong><div class="toolbar">'+''.join(f'<label class="checkline"><input type="checkbox" name="channels" value="{c}" checked>{c}</label>' for c in ['Email','WhatsApp','Social DM','Phone'])+'</div></div><div class="section"><strong>Products</strong><div class="checkgrid">'
        for p in products: body+=f'<label class="check"><input type="checkbox" name="product_ids" value="{e(p["product_id"])}"><span><strong>{e(p["public_product_name"])}</strong><small>{"Verified" if p["confirmed"] else "Needs fact review"}</small></span></label>'
        body+='</div></div><div class="form-foot"><button class="btn secondary" name="engine" value="local">Build safe local plan</button><button class="btn" name="engine" value="ai" '+('' if connected else 'disabled')+'>Build AI plan</button></div></form><div class="card"><h2>What happens next</h2><div class="readiness-row"><strong>Plan</strong><span>Channel mix, audience, experiments and KPIs</span></div><div class="readiness-row"><strong>Campaign</strong><span>Create one channel-specific campaign at a time</span></div><div class="readiness-row"><strong>Personalise</strong><span>AI or templates use approved knowledge and verified product facts</span></div><div class="readiness-row"><strong>Review</strong><span>Human approval before external handoff</span></div>'+app.notice('AI is '+('connected for explicit paid requests.' if connected else 'not connected. Local planning remains available.'),'info')+'</div></div>'
        body+='<div class="section"><h2>Recent growth plans</h2><div class="campaign-grid">'
        for r in rows: body+=f'<a class="card" href="/growth/{e(r["id"])}"><span class="pill purple">{e(r["audience"])}</span><h3>{e(r["name"])}</h3><p>{e(r["region"] or "All regions")} / {e(r["goal"])}</p><small>{e(r["engine"])} plan</small></a>'
        if not rows: body+='<div class="card empty">No growth plans yet. Start with one small B2B or B2C objective.</div>'
        body+='</div></div>'
        self.send_html(app.layout('Growth centre',body,'growth'))

    def v5_growth_detail(self,gid):
        import app
        r=m.one('SELECT * FROM v5_growth_plans WHERE id=?',(gid,))
        if not r: raise ValueError('Growth plan not found.')
        rec=json.loads(r['recommendation_json']); ch=json.loads(r['channels_json'])
        params={'audience':r['audience'],'goal':'Catalogue discovery','brief':r['brief'],'region':r['region']}
        body=app.pagehead(r['name'],f'{r["audience"]} / {r["region"] or "All regions"} / {r["engine"]}',app.button('Create campaign from this plan','/campaigns/new?'+urllib.parse.urlencode(params))+app.button('Back','/growth','secondary'))
        body+=f'<div class="card"><h2>Plan summary</h2><p>{e(rec.get("summary"))}</p><h3>Suggested audience</h3><p>{e(rec.get("segment"))}</p></div>'
        for key,label in [('channel_plan','Channel plan'),('message_angles','Message angles'),('experiments','Experiments'),('kpis','Sales KPIs'),('next_actions','Next actions')]:
            body+='<div class="card section"><h2>'+label+'</h2><ol>'+''.join('<li>'+e(x)+'</li>' for x in rec.get(key,[]))+'</ol></div>'
        self.send_html(app.layout('Growth plan',body,'growth'))

    def v5_blogs(self,q):
        import app
        rows=m.rows('SELECT * FROM v5_blogs ORDER BY updated_at DESC')
        body=app.pagehead('SEO blog studio','Create region-aware, keyword-led drafts for human review.',app.button('New blog draft','/blogs/new'))
        body+=app.notice('AI research can use current web search when enabled. Review citations and every factual claim before publishing. The CRM does not publish to your website automatically.')
        body+='<div class="table-wrap section"><table><thead><tr><th>Article</th><th>Keyword</th><th>Region</th><th>Engine</th><th>Status</th></tr></thead><tbody>'
        for r in rows: body+=f'<tr><td><a href="/blogs/{e(r["id"])}"><strong>{e(r["title"])}</strong></a><span class="tiny muted">/{e(r["slug"])}</span></td><td>{e(r["primary_keyword"])}</td><td>{e(r["region"] or "—")}</td><td>{e(r["engine"])}</td><td><span class="pill">{e(r["status"])}</span></td></tr>'
        if not rows: body+='<tr><td colspan="5">No blog drafts yet.</td></tr>'
        body+='</tbody></table></div>'
        self.send_html(app.layout('SEO blog studio',body,'blogs'))

    def v5_blog_new(self,q):
        import app
        connected=bool(m.secret())
        body=app.pagehead('Create an SEO article','Use a keyword, region and search intent. AI can optionally research current web sources.',app.button('All blog drafts','/blogs','secondary'))
        body+='<form class="card" method="post" action="/blogs/generate"><div class="formgrid">'
        body+=app.field('Primary keyword','<input name="primary_keyword" required placeholder="Example: Banarasi silk sarees in UK">')+app.field('Secondary keywords','<input name="secondary_keywords" placeholder="comma separated">')
        body+=app.field('Target region','<input name="region" placeholder="Example: United Kingdom / London">')+app.field('Language','<input name="language" value="English">')
        body+=app.field('Audience','<select name="audience">'+app.options(['B2C shoppers','B2B boutiques and retailers','Both'])+'</select>')+app.field('Search intent','<select name="intent">'+app.options(['Informational','Commercial investigation','Transactional support','Local discovery'])+'</select>')
        body+=app.field('Tone','<select name="tone">'+app.options(['Helpful and premium','Warm and conversational','Expert and educational','Editorial and elegant'])+'</select>')+'</div>'
        body+=app.field('Business angle / brief','<textarea name="brief" placeholder="What should the article help the reader understand or do?"></textarea>')
        body+='<label class="checkline section"><input type="checkbox" name="research" value="1">Use live web research for regional/current context (AI only; may add API tool cost)</label><div class="form-foot"><button class="btn secondary" name="engine" value="local">Build local SEO outline</button><button class="btn" name="engine" value="ai" '+('' if connected else 'disabled')+'>Generate AI article</button></div></form>'
        if not connected: body+=app.notice('AI is not connected. You can still create a structured local draft, or connect an API key in Settings & AI.')
        self.send_html(app.layout('New SEO article',body,'blogs'))

    def v5_blog_detail(self,bid):
        import app
        r=m.one('SELECT * FROM v5_blogs WHERE id=?',(bid,))
        if not r: raise ValueError('Blog draft not found.')
        sources=json.loads(r['sources_json'] or '[]')
        body=app.pagehead(r['title'],f'{r["primary_keyword"]} / {r["region"] or "No region"} / {r["engine"]}',app.button('All blogs','/blogs','secondary'))
        body+='<form class="card" method="post" action="/blogs/'+e(bid)+'/save"><div class="formgrid">'+app.field('Title','<input name="title" value="'+e(r['title'])+'">')+app.field('Slug','<input name="slug" value="'+e(r['slug'])+'">')+app.field('Meta title','<input name="meta_title" value="'+e(r['meta_title'])+'">')+app.field('Status','<select name="status">'+app.options(['Draft','Reviewed','Ready to publish','Archived'],r['status'])+'</select>')+'</div>'+app.field('Meta description','<textarea name="meta_description">'+e(r['meta_description'])+'</textarea>')+app.field('Excerpt','<textarea name="excerpt">'+e(r['excerpt'])+'</textarea>')+app.field('Article (Markdown)','<textarea name="content" rows="28" style="min-height:620px">'+e(r['content'])+'</textarea>')+'<div class="form-foot"><button class="btn">Save draft</button></div></form>'
        body+='<div class="card section"><h2>Research sources</h2>'
        if sources:
            for s in sources: body+=f'<p><a href="{e(s["url"])}" target="_blank" rel="noopener noreferrer">{e(s["title"])}</a></p>'
        else: body+='<p class="helper">No live web sources were used for this draft.</p>'
        body+=app.notice('Sources support research context; they do not automatically verify claims about your own products. Fact-check the final article before publishing.')+'</div>'
        self.send_html(app.layout('SEO article',body,'blogs'))

    def v5_product_new(self):
        import app
        body=app.pagehead('Add a product','The easiest route is to upload photos and let the system prepare the first draft for you.',app.button('Products','/products','secondary'))
        body+='''<div class="choice-hero"><section class="choice-card recommended"><div class="eyebrow">Recommended</div><h2>Start with product photos</h2><p>Upload one or more raw product images. The product engine can group them, draft product information and prepare channel-ready assets while keeping uncertain facts for your review.</p><a class="btn" href="/product-engine">Upload product photos</a></section><section class="choice-card"><div class="eyebrow">Already have a catalogue?</div><h2>Import a spreadsheet</h2><p>Use a CSV when your product names, SKUs, prices and other product facts already exist outside the CRM.</p><a class="btn secondary" href="/products/import">Import product CSV</a></section></div>'''
        body+='<details class="manual-entry"><summary>Enter product details manually</summary><div class="manual-body"><p class="helper section">Use this when you already know the product facts and do not need image-first preparation. Start with the basics; optional details are grouped below.</p><form method="post" action="/products/create" enctype="multipart/form-data"><div class="formgrid manual-basics">'
        for label,name in [('Product name','public_product_name'),('SKU (optional)','internal_sku'),('Product code (optional)','product_code')]:
            body+=app.field(label,f'<input type="text" name="{name}" '+('required' if name=='public_product_name' else '')+'>')
        body+='</div>'+app.field('Primary image (optional)','<input type="file" name="product_image" accept="image/jpeg,image/png,image/webp">')
        body+='<details class="manual-section"><summary>Product facts (optional)</summary><div><div class="formgrid">'
        for label,name in [('Colour','colour'),('Fabric / material','fabric'),('Weave / motif','weave_or_motif'),('Category','category'),('Tags','tags')]:
            body+=app.field(label,f'<input type="text" name="{name}">')
        body+='</div>'+app.field('Description','<textarea name="description" placeholder="Only include facts you can verify."></textarea>')+'</div></details>'
        body+='<details class="manual-section"><summary>Price & stock (optional)</summary><div><div class="formgrid">'
        for label,name,typ,value in [('Cost price','cost_price','number',''),('Retail price','retail_price','number',''),('Wholesale price','wholesale_price','number',''),('Currency','currency','text','INR'),('Stock quantity','stock_qty','number',''),('B2B MOQ','moq','number','')]:
            body+=app.field(label,f'<input type="{typ}" name="{name}" value="{value}">')
        body+='</div></div></details>'+app.notice('New products remain Draft and unverified until you review their facts and evidence on the product page.')+'<div class="form-foot"><button class="btn">Add product</button></div></form></div></details>'
        self.send_html(app.layout('Add product',body,'products'))

    def v5_product_import(self):
        import app
        q=getattr(self,'q',{}); iid=q.get('id',[''])[0]; r=m.one('SELECT * FROM v5_product_imports WHERE id=?',(iid,)) if iid else None
        body=app.pagehead('Import product spreadsheet','Best for an existing catalogue with product facts already organised in CSV format.',app.button('Upload product photos','/product-engine','')+app.button('Download CSV template','/products/template.csv','secondary')+app.button('Products','/products','secondary'))
        body+=app.notice('Starting from product photography instead? Use Upload product photos and let the product engine prepare the first draft for you.')
        if not r:
            body+='<form class="card section" method="post" action="/products/import/preview" enctype="multipart/form-data"><div class="file-well">'+app.field('Choose product CSV','<input type="file" name="product_csv" accept=".csv,text/csv" required>','Your existing file is previewed before anything is added.')+'</div>'+app.notice('The preview never overwrites an existing SKU. Rows with an existing SKU or missing product name are skipped.')+'<div class="form-foot"><button class="btn">Preview import</button></div></form>'
        else:
            report=json.loads(r['report_json']);add=sum(x['action']=='Add' for x in report);skip=len(report)-add
            body+=f'<div class="stats-grid"><div class="card stat-card"><strong>{add}</strong><span>Ready to add</span></div><div class="card stat-card"><strong>{skip}</strong><span>Skipped / review</span></div></div><div class="table-wrap section"><table><tr><th>Row</th><th>Product</th><th>Decision</th><th>Reason</th></tr>'
            for x in report[:100]: body+=f'<tr><td>{x["row"]}</td><td>{e(x["data"].get("public_product_name"))}</td><td>{e(x["action"])}</td><td>{e(x["reason"])}</td></tr>'
            body+='</table></div>'
            if r['status']=='Preview': body+=f'<form method="post" action="/products/import/commit" class="section"><input type="hidden" name="id" value="{e(iid)}"><button class="btn">Import {add} products</button></form>'
            else: body+=app.notice('This preview has already been imported.','success')
        self.send_html(app.layout('Import products',body,'products'))
