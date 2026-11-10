from __future__ import annotations
import runtime_config as rc

import base64, datetime as dt, json, mimetypes, os, re, secrets, shutil, subprocess, tempfile, urllib.error, urllib.request
from pathlib import Path

import marketing as m
import product_engine as pe
import v5_features as v5
import media_store

ROOT = Path(__file__).resolve().parent
CREATIVE_ROOT = rc.STATIC_ROOT / 'generated' / 'creative'
FRAME_ROOT = rc.STATIC_ROOT / 'generated' / 'reel_frames'
BRAND_ROOT = rc.STATIC_ROOT / 'generated' / 'brand'

SCHEMA = '''
CREATE TABLE IF NOT EXISTS v7_creative_jobs(
 id TEXT PRIMARY KEY, product_id TEXT NOT NULL, job_type TEXT NOT NULL, preset TEXT,
 status TEXT DEFAULT 'Queued', attempt INTEGER DEFAULT 0, prompt TEXT, provider TEXT,
 error TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP, updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS v7_creative_assets(
 id TEXT PRIMARY KEY, product_id TEXT NOT NULL, job_id TEXT, asset_kind TEXT NOT NULL,
 channel TEXT, aspect_ratio TEXT, relative_path TEXT NOT NULL, source_kind TEXT NOT NULL,
 status TEXT DEFAULT 'Draft', fidelity_score REAL, fidelity_json TEXT, notes TEXT,
 created_at TEXT DEFAULT CURRENT_TIMESTAMP, updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS v7_publish_queue(
 id TEXT PRIMARY KEY, product_id TEXT NOT NULL, asset_id TEXT, channel TEXT NOT NULL,
 status TEXT DEFAULT 'Prepared', caption TEXT, destination TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP,
 updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS v7_creative_events(
 id TEXT PRIMARY KEY, product_id TEXT, job_id TEXT, action TEXT, detail TEXT,
 created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS v7_creative_jobs_product_idx ON v7_creative_jobs(product_id,status);
CREATE INDEX IF NOT EXISTS v7_creative_assets_product_idx ON v7_creative_assets(product_id,status);
'''

PRESETS = {
    'clean_ecommerce': {
        'label':'Clean ecommerce studio', 'kind':'AI ecommerce', 'ratio':'4:5', 'size':'1024x1280',
        'instruction':'Present the exact referenced product in a clean premium ecommerce studio composition, neatly draped or arranged so the border, body, pallu and distinctive details are visible. No person. Neutral background.'
    },
    'mannequin_studio': {
        'label':'Mannequin studio', 'kind':'AI mannequin', 'ratio':'4:5', 'size':'1024x1280',
        'instruction':'Dress a neutral headless fashion mannequin in the exact referenced product. Use a clean premium studio background and front three-quarter composition.'
    },
    'model_studio': {
        'label':'Model studio', 'kind':'AI model', 'ratio':'4:5', 'size':'1024x1280',
        'instruction':'Dress an adult fashion model in the exact referenced product in a premium neutral studio. Natural pose, full garment visible, editorial but commercially realistic.'
    },
    'model_editorial': {
        'label':'Editorial lifestyle', 'kind':'AI model', 'ratio':'4:5', 'size':'1024x1280',
        'instruction':'Dress an adult fashion model in the exact referenced product in an elegant Indian heritage-inspired interior with restrained styling. Keep the garment as the visual focus.'
    }
}

CHANNEL_SPECS = {
    'ecommerce_square':('Ecommerce square','1:1',(1600,1600)),
    'ecommerce_portrait':('Ecommerce portrait','4:5',(1600,2000)),
    'instagram_square':('Instagram / Facebook square','1:1',(1080,1080)),
    'instagram_portrait':('Instagram / Facebook portrait','4:5',(1080,1350)),
    'story':('Stories / Reels','9:16',(1080,1920)),
    'meta_ad_square':('Meta ad square','1:1',(1080,1080)),
    'meta_ad_portrait':('Meta ad portrait','4:5',(1080,1350)),
    'pinterest':('Pinterest pin','2:3',(1000,1500)),
    'email_card':('Email product card','4:5',(800,1000)),
}

def uid(prefix): return prefix+'-'+secrets.token_hex(7).upper()

def initialise():
    with m.connect() as con:
        con.executescript(SCHEMA)
        defaults={
            'creative_image_model':(m.routed_model('image_preserve','gpt-image-2.5-sunburst')),
            'creative_controller_model':(m.routed_model('product_understanding','gpt-6-sol')),
            'creative_auto_queue':'1',
            'creative_auto_generate':'0',
            'creative_auto_fidelity':'1',
            'creative_fidelity_threshold':'85',
            'creative_auto_channel_assets':'1',
            'creative_auto_approve':'0',
            'creative_reel_seconds':'8',
            'creative_cta':'Explore the collection',
            'creative_brand_primary':'#17131B',
            'creative_brand_accent':'#A27654',
        }
        for k,v in defaults.items(): con.execute('INSERT OR IGNORE INTO settings(setting_key,setting_value) VALUES(?,?)',(k,v))
    CREATIVE_ROOT.mkdir(parents=True, exist_ok=True); FRAME_ROOT.mkdir(parents=True, exist_ok=True); BRAND_ROOT.mkdir(parents=True, exist_ok=True)

def setting(key, default=''):
    r=m.one('SELECT setting_value FROM settings WHERE setting_key=?',(key,)); return (r['setting_value'] if r else default) or default

def save_settings(raw):
    model=(raw.get('creative_image_model') or m.routed_model('image_preserve','gpt-image-2.5-sunburst')).strip()
    if not re.fullmatch(r'[a-zA-Z0-9._-]{3,100}',model): raise ValueError('Use a valid image model ID.')
    try: threshold=int(raw.get('creative_fidelity_threshold') or '85')
    except ValueError: raise ValueError('Fidelity threshold must be a whole number.')
    if not 50<=threshold<=100: raise ValueError('Choose a fidelity threshold from 50 to 100.')
    primary=(raw.get('creative_brand_primary') or '#17131B').strip().upper()
    accent=(raw.get('creative_brand_accent') or '#A27654').strip().upper()
    if not re.fullmatch(r'#[0-9A-F]{6}',primary) or not re.fullmatch(r'#[0-9A-F]{6}',accent): raise ValueError('Brand colours must use six-digit hex values such as #17131B.')
    with m.connect() as con:
        for k,v in {
            'creative_image_model':model,
            'creative_controller_model':(raw.get('creative_controller_model') or m.routed_model('product_understanding','gpt-6-sol')).strip(),
            'creative_auto_queue':'1' if raw.get('creative_auto_queue')=='1' else '0',
            'creative_auto_generate':'1' if raw.get('creative_auto_generate')=='1' else '0',
            'creative_auto_fidelity':'1' if raw.get('creative_auto_fidelity')=='1' else '0',
            'creative_auto_channel_assets':'1' if raw.get('creative_auto_channel_assets')=='1' else '0',
            'creative_auto_approve':'1' if raw.get('creative_auto_approve')=='1' else '0',
            'creative_fidelity_threshold':str(threshold),
            'creative_cta':(raw.get('creative_cta') or 'Explore the collection').strip()[:100],
            'creative_brand_primary':primary,
            'creative_brand_accent':accent
        }.items(): con.execute('INSERT OR REPLACE INTO settings VALUES(?,?)',(k,v))
    event(None,None,'creative.settings','Creative automation settings updated.')

def event(product_id,job_id,action,detail=''):
    with m.connect() as con: con.execute('INSERT INTO v7_creative_events(id,product_id,job_id,action,detail) VALUES(?,?,?,?,?)',(uid('CEVT'),product_id,job_id,action,(detail or '')[:3000]))

def product(product_id):
    import record_lifecycle as lifecycle
    p=m.one('''SELECT p.*,coalesce(r.confirmed,0) confirmed,r.evidence FROM products p LEFT JOIN m4_product_review r USING(product_id) WHERE p.product_id=?''',(product_id,))
    return lifecycle.require_operationally_active_product(p)

def source_images(product_id, limit=5):
    return m.rows("SELECT * FROM product_images WHERE product_id=? ORDER BY CASE image_role WHEN 'Cover' THEN 0 WHEN 'Overall' THEN 1 WHEN 'Border / body' THEN 2 WHEN 'Pallu' THEN 3 WHEN 'Close-up' THEN 4 ELSE 8 END,is_primary DESC LIMIT ?",(product_id,limit))

def queue_job(product_id,preset):
    product(product_id)
    if preset not in PRESETS: raise ValueError('Choose a supported creative preset.')
    existing=m.one("SELECT id FROM v7_creative_jobs WHERE product_id=? AND preset=? AND status IN ('Queued','Running') ORDER BY created_at DESC LIMIT 1",(product_id,preset))
    if existing:return existing['id']
    jid=uid('CJOB')
    with m.connect() as con: con.execute('INSERT INTO v7_creative_jobs(id,product_id,job_type,preset,status) VALUES(?,?,?,?,?)',(jid,product_id,'AI visual',preset,'Queued'))
    event(product_id,jid,'creative.queued',PRESETS[preset]['label'])
    return jid

def queue_default_pack(product_id,source='product intake'):
    initialise(); ids=[]
    for preset in ('clean_ecommerce','mannequin_studio','model_studio'):
        ids.append(queue_job(product_id,preset))
    event(product_id,None,'creative.pack_queued',f'Standard ecommerce + mannequin + model pack queued from {source}.')
    return ids

def _data_url(path:Path):
    mime=mimetypes.guess_type(path.name)[0] or 'image/jpeg'
    return f'data:{mime};base64,'+base64.b64encode(path.read_bytes()).decode('ascii')

def _reference_content(product_id):
    content=[]
    for im in source_images(product_id,5):
        p=ROOT/im['relative_path']
        if p.exists():
            small=pe.analysis_copy(p)
            content.append({'type':'input_image','image_url':_data_url(small),'detail':'high'})
    if not content: raise ValueError('No product reference images are available.')
    return content

def _product_constraints(p,preset):
    c=pe.content(p['product_id'])
    known={k:p.get(k) for k in ['public_product_name','colour','fabric','weave_or_motif','category']}
    return f'''EDIT the supplied reference photographs into a commercial product visual. {PRESETS[preset]['instruction']}
This must depict the SAME physical garment/product as the references, not a new design. Preserve the visible colour family, border width and pattern, motif placement, pallu treatment, blouse-piece cues, sheen/texture appearance, and other distinguishing details. Do not invent motifs, embroidery, zari, logos, text, jewellery attached to the garment, or unseen design details. Do not change the product into a different fabric, weave or colour. If a detail is not visible, keep it simple rather than hallucinating it.
Product metadata is context only and is not a license to invent: {json.dumps(known,ensure_ascii=False)}.
Create a photorealistic commercial image with the full garment legible and not obscured. No text, no watermark, no brand logo. Generated image is a marketing visual and must later pass fidelity review before use.'''

def generate_visual(job_id):
    initialise(); job=m.one('SELECT * FROM v7_creative_jobs WHERE id=?',(job_id,))
    if not job: raise ValueError('Creative job not found.')
    if job['preset'] not in PRESETS: raise ValueError('Unsupported creative preset.')
    key=m.secret()
    if not key: raise ValueError('AI is not connected. Add the API key in Settings & AI before generating product visuals.')
    p=product(job['product_id']); spec=PRESETS[job['preset']]
    prompt=_product_constraints(p,job['preset'])
    content=[{'type':'input_text','text':prompt}]+_reference_content(job['product_id'])
    import ai_router
    controller_state=ai_router.preflight('product_understanding',object_type='product',object_id=job['product_id'],default_model=setting('creative_controller_model',m.routed_model('product_understanding','gpt-6-sol')))
    image_state=ai_router.preflight('image_generation',object_type='product',object_id=job['product_id'],default_model=setting('creative_image_model',m.routed_model('image_preserve','gpt-image-2.5-sunburst')))
    controller_model=controller_state['model']
    image_model=image_state['model']
    try:
        import operating_core as oc
        oc.guard_ai_call('image')
    except ImportError:
        oc=None
    body={'model':controller_model,'store':False,
          'input':[{'role':'user','content':content}],
          'tools':[{'type':'image_generation','model':image_model,'action':'edit','size':spec['size'],'quality':'high','output_format':'webp'}]}
    with m.connect() as con: con.execute("UPDATE v7_creative_jobs SET status='Running',attempt=attempt+1,prompt=?,provider=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",(prompt,'OpenAI GPT Image',job_id))
    try:
        out,attempts,duration_ms=ai_router.request_json('image_generation',body,timeout=240,object_type='product',object_id=job['product_id'],max_attempts=3)
    except ValueError as ex:
        with m.connect() as con: con.execute("UPDATE v7_creative_jobs SET status='Failed',error=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",(str(ex)[:500],job_id))
        raise
    image_data=None
    for item in out.get('output',[]):
        if item.get('type')=='image_generation_call' and item.get('result'):
            image_data=item['result']; break
    if not image_data:
        with m.connect() as con: con.execute("UPDATE v7_creative_jobs SET status='Failed',error='No image returned',updated_at=CURRENT_TIMESTAMP WHERE id=?",(job_id,))
        raise ValueError('The AI request completed without a usable image. Existing assets were not changed.')
    try: raw=base64.b64decode(image_data)
    except Exception: raise ValueError('The generated image response could not be decoded.') from None
    aid=uid('CASSET'); folder=CREATIVE_ROOT/job['product_id']; folder.mkdir(parents=True,exist_ok=True)
    dest=folder/(aid+'.webp'); dest.write_bytes(raw)
    rel=dest.relative_to(ROOT).as_posix();media_store.persist(rel,public=True)
    with m.connect() as con:
        con.execute('INSERT INTO v7_creative_assets(id,product_id,job_id,asset_kind,channel,aspect_ratio,relative_path,source_kind,status,notes) VALUES(?,?,?,?,?,?,?,?,?,?)',
                    (aid,job['product_id'],job_id,spec['kind'],'Ecommerce / marketing',spec['ratio'],rel,'AI generated','Fidelity review','AI-generated visual. Original photography remains the product source of truth.'))
        con.execute("UPDATE v7_creative_jobs SET status='Generated',error=NULL,updated_at=CURRENT_TIMESTAMP WHERE id=?",(job_id,))
    event(job['product_id'],job_id,'creative.generated',f'{spec["label"]} created. Fidelity review required.')
    try:
        usage=out.get('usage') or {}
        if oc:ai_router.record_success('image_generation','OpenAI',image_model,object_type='product',object_id=job['product_id'],input_units=usage.get('input_tokens',0),output_units=usage.get('output_tokens',0),image_count=1,provider_request_id=str(out.get('id') or ''),duration_ms=duration_ms,attempts=attempts)
    except Exception:pass
    if setting('creative_auto_fidelity','1')=='1':
        try: fidelity_check(aid)
        except ValueError as ex: event(job['product_id'],job_id,'fidelity.warning',str(ex))
    return aid

def fidelity_check(asset_id):
    key=m.secret()
    if not key: raise ValueError('AI is not connected, so automatic fidelity review cannot run.')
    a=m.one('SELECT * FROM v7_creative_assets WHERE id=?',(asset_id,))
    if not a: raise ValueError('Creative asset not found.')
    generated=ROOT/a['relative_path']
    if not generated.exists(): raise ValueError('Generated asset file is missing.')
    p=product(a['product_id'])
    content=[{'type':'input_text','text':'Compare the final AI-generated garment image against the following original product reference photographs. Judge PRODUCT FIDELITY only, not beauty. A model/mannequin pose may change drape, but the visible colour, motifs, border, pallu, blouse cues and distinctive design should remain the same. Flag invented, omitted or materially altered product details. Do not infer textile authenticity. Return the schema only.'}]
    content+=_reference_content(a['product_id'])
    content.append({'type':'input_text','text':'FINAL GENERATED IMAGE TO CHECK:'})
    content.append({'type':'input_image','image_url':_data_url(generated),'detail':'high'})
    schema={'type':'object','properties':{
        'score':{'type':'number'},'acceptable':{'type':'boolean'},'colour_match':{'type':'number'},'pattern_match':{'type':'number'},'border_match':{'type':'number'},'pallu_match':{'type':'number'},'fabric_appearance_match':{'type':'number'},
        'issues':{'type':'array','items':{'type':'string'}},'summary':{'type':'string'}},
        'required':['score','acceptable','colour_match','pattern_match','border_match','pallu_match','fabric_appearance_match','issues','summary'],'additionalProperties':False}
    model=setting('creative_controller_model',m.routed_model('product_understanding','gpt-6-sol'))
    try:
        import operating_core as oc2
        oc2.guard_ai_call('general')
    except ImportError:
        oc2=None
    body={'model':model,'store':False,'max_output_tokens':1600,
          'input':[{'role':'user','content':content}], 'text':{'format':{'type':'json_schema','name':'product_fidelity','strict':True,'schema':schema}}}
    import ai_router
    state=ai_router.preflight('image_fidelity',object_type='creative_asset',object_id=asset_id,default_model=model)
    body['model']=state['model']
    out,attempts,duration_ms=ai_router.request_json('image_fidelity',body,timeout=180,object_type='creative_asset',object_id=asset_id,max_attempts=3)
    try: data=json.loads(v5.response_text(out)); score=max(0,min(100,float(data['score'])))
    except Exception: raise ValueError('AI fidelity review returned an unusable response.') from None
    threshold=int(setting('creative_fidelity_threshold','85'))
    status='Ready for owner approval' if bool(data.get('acceptable')) and score>=threshold else 'Needs correction'
    with m.connect() as con: con.execute('UPDATE v7_creative_assets SET fidelity_score=?,fidelity_json=?,status=?,updated_at=CURRENT_TIMESTAMP WHERE id=?',(score,json.dumps(data,ensure_ascii=False),status,asset_id))
    event(a['product_id'],a['job_id'],'fidelity.checked',f'{score:.0f}/100; {status}.')
    try:
        usage=out.get('usage') or {}
        if oc2:
            ai_router.record_success('image_fidelity','OpenAI',state['model'],object_type='creative_asset',object_id=asset_id,input_units=usage.get('input_tokens',0),output_units=usage.get('output_tokens',0),duration_ms=duration_ms,provider_request_id=str(out.get('id') or ''),attempts=attempts)
            oc2._save_quality('creative_asset',asset_id,'product_fidelity',score,list(data.get('issues') or []),data)
    except Exception:pass
    # Optional zero-touch mode is deliberately stricter than the readiness threshold.
    if setting('creative_auto_approve','0')=='1' and bool(data.get('acceptable')) and score>=95:
        approve_asset(asset_id,True)
        event(a['product_id'],a['job_id'],'creative.auto_approved',f'Auto-approved after fidelity score {score:.0f}/100 (95+ policy).')
    return data

def approve_asset(asset_id,approved=True):
    a=m.one('SELECT * FROM v7_creative_assets WHERE id=?',(asset_id,))
    if not a: raise ValueError('Creative asset not found.')
    if a['source_kind']=='AI generated' and approved and a['fidelity_score'] is None:
        raise ValueError('Run fidelity review before approving an AI-generated garment visual.')
    with m.connect() as con: con.execute('UPDATE v7_creative_assets SET status=?,updated_at=CURRENT_TIMESTAMP WHERE id=?',('Approved' if approved else 'Rejected',asset_id))
    event(a['product_id'],a['job_id'],'creative.approval','Approved' if approved else 'Rejected')
    if approved and setting('creative_auto_channel_assets','1')=='1':
        try:
            create_channel_pack(a['product_id'],force=True)
            create_reel_package(a['product_id'])
            event(a['product_id'],a['job_id'],'creative.downstream_auto','Approved visual automatically refreshed social/ad assets and the reel package.')
        except Exception as ex:
            event(a['product_id'],a['job_id'],'creative.downstream_warning',str(ex))

def save_brand_logo(raw:bytes, filename:str):
    if not raw or len(raw)>5*1024*1024: raise ValueError('Choose a logo image under 5 MB.')
    if Path(filename).suffix.lower() not in {'.png','.jpg','.jpeg','.webp'}: raise ValueError('Use a PNG, JPG or WEBP logo image.')
    try:
        from PIL import Image, ImageOps
        img=Image.open(__import__('io').BytesIO(raw)); img=ImageOps.exif_transpose(img)
        if img.width<40 or img.height<20: raise ValueError('The logo image is too small.')
        img.thumbnail((1200,600))
        if img.mode not in {'RGBA','LA'}: img=img.convert('RGBA')
        BRAND_ROOT.mkdir(parents=True,exist_ok=True); dest=BRAND_ROOT/'logo.png'; img.save(dest,'PNG')
    except ValueError: raise
    except Exception: raise ValueError('The logo file could not be read as an image.') from None
    with m.connect() as con: con.execute("INSERT OR REPLACE INTO settings VALUES('creative_brand_logo','static/generated/brand/logo.png')")
    event(None,None,'brand.logo','Brand logo updated for generated marketing assets.')
    return dest


def brand_logo_path():
    rel=setting('creative_brand_logo','')
    p=ROOT/rel if rel else None
    return p if p and p.exists() else None


def _hex_rgb(value, default=(23,19,27)):
    try:
        value=value.lstrip('#'); return tuple(int(value[i:i+2],16) for i in (0,2,4))
    except Exception: return default


def _brand_text():
    s=m.settings(); brand=(s.get('brand_name') or '').strip()
    return brand if brand and brand.lower() not in {'brand name pending','tbd'} else ''

def preferred_visual(product_id):
    a=m.one("SELECT * FROM v7_creative_assets WHERE product_id=? AND source_kind='AI generated' AND status='Approved' ORDER BY fidelity_score DESC,created_at DESC LIMIT 1",(product_id,))
    if a and (ROOT/a['relative_path']).exists(): return ROOT/a['relative_path'],'Approved AI visual'
    im=m.one('SELECT * FROM product_images WHERE product_id=? ORDER BY is_primary DESC,CASE image_role WHEN "Cover" THEN 0 ELSE 1 END LIMIT 1',(product_id,))
    if not im: raise ValueError('This product has no source image.')
    return ROOT/im['relative_path'],'Original product image'

def _cover_crop(im,w,h):
    from PIL import Image, ImageOps
    return ImageOps.fit(im,(w,h),method=Image.Resampling.LANCZOS,centering=(0.5,0.45))

def create_channel_pack(product_id, force=False):
    initialise(); p=product(product_id); src,source_label=preferred_visual(product_id)
    try:
        from PIL import Image,ImageOps,ImageDraw,ImageFont
    except Exception: raise ValueError('Channel creative generation needs Pillow. The original and existing resized assets remain available.')
    brand=_brand_text(); cta=setting('creative_cta','Explore the collection'); title=(p['public_product_name'] or 'New collection')[:70]
    made=[]
    with Image.open(src) as raw:
        raw=ImageOps.exif_transpose(raw).convert('RGB')
        for key,(label,ratio,(w,h)) in CHANNEL_SPECS.items():
            existing=m.one("SELECT * FROM v7_creative_assets WHERE product_id=? AND asset_kind=? AND status<>'Archived' ORDER BY created_at DESC LIMIT 1",(product_id,key))
            if existing and not force and (ROOT/existing['relative_path']).exists(): continue
            if force:
                with m.connect() as con: con.execute("UPDATE v7_creative_assets SET status='Archived',updated_at=CURRENT_TIMESTAMP WHERE product_id=? AND asset_kind=? AND status<>'Archived'",(product_id,key))
            canvas=_cover_crop(raw,w,h)
            # Ecommerce derivatives stay text-free. Marketing placements get a restrained deterministic overlay.
            if not key.startswith('ecommerce_'):
                draw=ImageDraw.Draw(canvas,'RGBA')
                band_h=max(180,int(h*.19)); prgb=_hex_rgb(setting('creative_brand_primary','#17131B')); draw.rectangle((0,h-band_h,w,h),fill=(*prgb,205))
                try: font_big=ImageFont.truetype('/System/Library/Fonts/Helvetica.ttc',max(32,int(w*.042))); font_small=ImageFont.truetype('/System/Library/Fonts/Helvetica.ttc',max(22,int(w*.026)))
                except Exception: font_big=ImageFont.load_default();font_small=ImageFont.load_default()
                y=h-band_h+30
                logo=brand_logo_path()
                if logo:
                    try:
                        with Image.open(logo) as lim:
                            lim=lim.convert('RGBA');lim.thumbnail((180,72));canvas.paste(lim,(w-lim.width-40,h-band_h+24),lim)
                    except Exception: pass
                if brand: draw.text((40,y),brand,font=font_small,fill='white');y+=42
                draw.text((40,y),title,font=font_big,fill='white');y+=58
                draw.text((40,y),cta,font=font_small,fill=(240,240,240,255))
            aid=uid('CASSET'); folder=CREATIVE_ROOT/product_id/'channel_pack';folder.mkdir(parents=True,exist_ok=True);dest=folder/(aid+'.jpg')
            canvas.save(dest,'JPEG',quality=91,optimize=True);media_store.persist(dest.relative_to(ROOT).as_posix(),public=True)
            rel=dest.relative_to(ROOT).as_posix()
            with m.connect() as con: con.execute('INSERT INTO v7_creative_assets(id,product_id,asset_kind,channel,aspect_ratio,relative_path,source_kind,status,notes) VALUES(?,?,?,?,?,?,?,?,?)',(aid,product_id,key,label,ratio,rel,source_label,'Approved','Deterministic channel crop with local text overlay; no product details were generated.'))
            made.append(aid)
    event(product_id,None,'channel_pack.created',f'{len(made)} channel assets prepared from {source_label}.')
    prepare_publish_queue(product_id)
    return made

def prepare_publish_queue(product_id):
    # Queue is a planning surface only; no social/ecommerce API is called.
    assets=m.rows("SELECT * FROM v7_creative_assets WHERE product_id=? AND status='Approved' AND asset_kind IN ('ecommerce_square','ecommerce_portrait','instagram_square','instagram_portrait','story','meta_ad_square','meta_ad_portrait','pinterest','email_card') ORDER BY created_at DESC",(product_id,))
    channel_map={'ecommerce_square':'Website / ecommerce','ecommerce_portrait':'Website / ecommerce','instagram_square':'Instagram','instagram_portrait':'Instagram','story':'Instagram / Facebook Stories','meta_ad_square':'Meta Ads','meta_ad_portrait':'Meta Ads','pinterest':'Pinterest','email_card':'Email'}
    p=product(product_id); c=pe.content(product_id); name=p['public_product_name'] or 'New collection'; cta=setting('creative_cta','Explore the collection')
    desc=(c.get('short_description') or c.get('b2c_description') or p.get('description') or '').strip()
    made=0
    with m.connect() as con:
        for a in assets:
            ch=channel_map[a['asset_kind']]
            if con.execute('SELECT 1 FROM v7_publish_queue WHERE asset_id=? AND channel=?',(a['id'],ch)).fetchone(): continue
            if ch=='Pinterest': caption=f'{name} — {desc[:220]} {cta}'.strip()
            elif ch=='Meta Ads': caption=f'{name}. {cta}'.strip()
            elif ch.startswith('Instagram'): caption=f'{name}. {desc[:260]} {cta}'.strip()
            elif ch=='Website / ecommerce': caption=f'{name} — product image asset'.strip()
            else: caption=f'{name}. {cta}'.strip()
            con.execute('INSERT INTO v7_publish_queue(id,product_id,asset_id,channel,status,caption) VALUES(?,?,?,?,?,?)',(uid('PUB'),product_id,a['id'],ch,'Prepared',caption[:2000]));made+=1
    return made

def create_reel_package(product_id):
    initialise(); p=product(product_id)
    with m.connect() as con: con.execute("UPDATE v7_creative_assets SET status='Archived',updated_at=CURRENT_TIMESTAMP WHERE product_id=? AND asset_kind='promo_reel' AND status<>'Archived'",(product_id,))
    sources=[]
    # Prefer approved AI visual, then originals. Do not require generative media to create a usable reel.
    ai=m.rows("SELECT relative_path FROM v7_creative_assets WHERE product_id=? AND source_kind='AI generated' AND status='Approved' ORDER BY fidelity_score DESC LIMIT 2",(product_id,))
    sources += [ROOT/x['relative_path'] for x in ai if (ROOT/x['relative_path']).exists()]
    sources += [ROOT/x['relative_path'] for x in source_images(product_id,6) if (ROOT/x['relative_path']).exists()]
    if len(sources)<2: raise ValueError('At least two usable product images are needed for a promotional reel.')
    try:
        from PIL import Image,ImageOps,ImageDraw,ImageFont
    except Exception: raise ValueError('Reel frame generation needs Pillow.')
    rid=uid('REEL'); folder=FRAME_ROOT/product_id/rid;folder.mkdir(parents=True,exist_ok=True)
    brand=_brand_text(); title=(p['public_product_name'] or 'New collection')[:70]; frames=[]
    for i,src in enumerate(sources[:6],1):
        with Image.open(src) as raw:
            im=ImageOps.fit(ImageOps.exif_transpose(raw).convert('RGB'),(1080,1920),method=Image.Resampling.LANCZOS,centering=(0.5,0.45))
            draw=ImageDraw.Draw(im,'RGBA');draw.rectangle((0,1510,1080,1920),fill=(10,10,14,175))
            try: fb=ImageFont.truetype('/System/Library/Fonts/Helvetica.ttc',46);fs=ImageFont.truetype('/System/Library/Fonts/Helvetica.ttc',30)
            except Exception: fb=ImageFont.load_default();fs=ImageFont.load_default()
            y=1570
            if brand: draw.text((55,y),brand,font=fs,fill='white');y+=65
            draw.text((55,y),title,font=fb,fill='white');y+=95
            draw.text((55,y),setting('creative_cta','Explore the collection'),font=fs,fill='white')
            frame=folder/f'frame_{i:02d}.jpg';im.save(frame,'JPEG',quality=92);frames.append(frame)
    manifest={'product_id':product_id,'title':title,'format':'9:16','duration_seconds':int(setting('creative_reel_seconds','8')),'frames':[x.relative_to(ROOT).as_posix() for x in frames],'source_note':'Uses approved AI visuals where available plus original product photography.','status':'Frames ready'}
    manifest_path=folder/'reel_manifest.json';manifest_path.write_text(json.dumps(manifest,indent=2))
    output=folder/'promo_reel.mp4';renderer='Storyboard only'
    ffmpeg=shutil.which('ffmpeg')
    if ffmpeg:
        duration=max(0.8,int(setting('creative_reel_seconds','8'))/len(frames));concat=folder/'frames.txt'
        concat.write_text(''.join(f"file '{x.name}'\nduration {duration:.3f}\n" for x in frames)+f"file '{frames[-1].name}'\n")
        cmd=[ffmpeg,'-y','-f','concat','-safe','0','-i',str(concat),'-vf','scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2,format=yuv420p','-r','30','-c:v','libx264','-pix_fmt','yuv420p',str(output)]
        try: subprocess.run(cmd,cwd=folder,check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=120);renderer='FFmpeg MP4'
        except Exception: pass
    rendered=output.exists()
    path=output if rendered else manifest_path
    aid=uid('CASSET')
    # A storyboard JSON is useful planning output, but it is not a playable reel.
    # Keep it out of Approved/publishing paths until an actual MP4 exists.
    source_kind='Composed motion video' if rendered else 'Storyboard manifest'
    asset_status='Approved' if rendered else 'Prepared'
    with m.connect() as con: con.execute('INSERT INTO v7_creative_assets(id,product_id,asset_kind,channel,aspect_ratio,relative_path,source_kind,status,notes) VALUES(?,?,?,?,?,?,?,?,?)',(aid,product_id,'promo_reel','Reels / short video','9:16',path.relative_to(ROOT).as_posix(),source_kind,asset_status,renderer))
    event(product_id,None,'reel.created' if rendered else 'reel.storyboard_ready',renderer)
    return aid,renderer

def pack_status(product_id):
    jobs=m.rows('SELECT * FROM v7_creative_jobs WHERE product_id=? ORDER BY created_at DESC',(product_id,))
    assets=m.rows('SELECT * FROM v7_creative_assets WHERE product_id=? ORDER BY created_at DESC',(product_id,))
    pub=m.rows('SELECT * FROM v7_publish_queue WHERE product_id=? ORDER BY created_at DESC',(product_id,))
    return {'jobs':jobs,'assets':assets,'publish':pub}

def process_queue_once(limit=3):
    initialise()
    if setting('creative_auto_generate','0')!='1' or not m.secret(): return []
    results=[]
    for j in m.rows("SELECT id FROM v7_creative_jobs WHERE status='Queued' ORDER BY created_at LIMIT ?",(limit,)):
        try: results.append({'job':j['id'],'asset':generate_visual(j['id']),'status':'Generated'})
        except Exception as ex: results.append({'job':j['id'],'status':'Failed','error':str(ex)})
    return results

def watch_creative_loop(stop_event, interval=75):
    while not stop_event.is_set():
        try: process_queue_once()
        except Exception: pass
        stop_event.wait(interval)
