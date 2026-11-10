from __future__ import annotations
import runtime_config as rc

import base64, datetime as dt, io, json, mimetypes, os, re, secrets, shutil, subprocess, time, urllib.error, urllib.request, zipfile
from pathlib import Path

import marketing as m
import product_engine as pe
import creative_engine as ce
import v5_features as v5
import media_store

ROOT = Path(__file__).resolve().parent
CAMPAIGN_ROOT = rc.STATIC_ROOT / 'generated' / 'creative_campaigns'
VIDEO_ROOT = rc.STATIC_ROOT / 'generated' / 'creative_video'
MUSIC_ROOT = rc.STATIC_ROOT / 'generated' / 'music'
VIDEO_SECRET_PATH = Path(os.environ.get('CRM_VIDEO_SECRET_PATH', str(Path.home() / '.config' / 'commerce-crm' / 'video.json')))

SCHEMA = '''
CREATE TABLE IF NOT EXISTS v8_creative_campaigns(
 id TEXT PRIMARY KEY, name TEXT NOT NULL, campaign_type TEXT, target_market TEXT, language TEXT,
 visual_style TEXT, background_style TEXT, subject_mode TEXT, model_style TEXT,
 text_mode TEXT, promotional_message TEXT, cta TEXT, price_text TEXT, offer_text TEXT,
 logo_mode TEXT, status TEXT DEFAULT 'Draft', created_at TEXT DEFAULT CURRENT_TIMESTAMP,
 updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS v8_creative_campaign_products(
 campaign_id TEXT NOT NULL, product_id TEXT NOT NULL,
 PRIMARY KEY(campaign_id,product_id)
);
CREATE TABLE IF NOT EXISTS v8_creative_campaign_placements(
 campaign_id TEXT NOT NULL, placement_key TEXT NOT NULL, variations INTEGER DEFAULT 1,
 PRIMARY KEY(campaign_id,placement_key)
);
CREATE TABLE IF NOT EXISTS v8_creative_campaign_assets(
 id TEXT PRIMARY KEY, campaign_id TEXT NOT NULL, product_id TEXT NOT NULL, placement_key TEXT NOT NULL,
 media_type TEXT NOT NULL, variation INTEGER DEFAULT 1, relative_path TEXT NOT NULL,
 source_kind TEXT, source_asset_id TEXT, status TEXT DEFAULT 'Draft', version_no INTEGER DEFAULT 1,
 notes TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP, updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS v8_video_jobs(
 id TEXT PRIMARY KEY, campaign_id TEXT NOT NULL, product_id TEXT NOT NULL, placement_key TEXT NOT NULL,
 provider TEXT NOT NULL, duration_seconds INTEGER NOT NULL, aspect_ratio TEXT NOT NULL,
 style TEXT, music_mode TEXT, voiceover_mode TEXT, voiceover_text TEXT, language TEXT,
 transition_style TEXT DEFAULT 'Fade', captions_mode TEXT DEFAULT 'off', logo_mode TEXT DEFAULT 'Use logo',
 status TEXT DEFAULT 'Queued', operation_name TEXT, output_path TEXT, error TEXT,
 created_at TEXT DEFAULT CURRENT_TIMESTAMP, updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS v8_music_assets(
 id TEXT PRIMARY KEY, label TEXT, relative_path TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS v8_custom_placements(
 campaign_id TEXT NOT NULL, placement_key TEXT NOT NULL, media_type TEXT NOT NULL, label TEXT, platform TEXT,
 width INTEGER NOT NULL, height INTEGER NOT NULL, aspect_ratio TEXT, text_policy TEXT DEFAULT 'allowed', variations INTEGER DEFAULT 1,
 PRIMARY KEY(campaign_id,placement_key)
);
CREATE TABLE IF NOT EXISTS v8_publish_handoffs(
 id TEXT PRIMARY KEY, campaign_id TEXT NOT NULL, asset_id TEXT NOT NULL, platform TEXT NOT NULL, status TEXT DEFAULT 'Prepared',
 caption TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP, updated_at TEXT DEFAULT CURRENT_TIMESTAMP, UNIQUE(asset_id,platform)
);
CREATE INDEX IF NOT EXISTS v8_campaign_assets_idx ON v8_creative_campaign_assets(campaign_id,product_id,placement_key);
CREATE INDEX IF NOT EXISTS v8_video_jobs_idx ON v8_video_jobs(campaign_id,product_id,status);
CREATE TABLE IF NOT EXISTS v19_creative_quality(
 asset_id TEXT PRIMARY KEY, campaign_id TEXT NOT NULL, product_id TEXT NOT NULL,
 qc_status TEXT NOT NULL DEFAULT 'Needs review', score REAL DEFAULT 0,
 issues_json TEXT DEFAULT '[]', checks_json TEXT DEFAULT '{}', checked_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS v19_creative_campaign_links(
 creative_campaign_id TEXT PRIMARY KEY, unified_campaign_id TEXT, status TEXT DEFAULT 'Draft',
 detail TEXT DEFAULT '', updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);
'''

IMAGE_PLACEMENTS = {
    # Organic social
    'ig_feed_portrait': {'platform':'Instagram','label':'Instagram Feed portrait','ratio':'4:5','size':(1080,1350),'layout':'feed','text':'allowed','recommended':True},
    'ig_feed_square': {'platform':'Instagram','label':'Instagram Feed square','ratio':'1:1','size':(1080,1080),'layout':'feed','text':'allowed'},
    'ig_story': {'platform':'Instagram','label':'Instagram Story','ratio':'9:16','size':(1080,1920),'layout':'story','text':'allowed','recommended':True},
    'fb_feed_portrait': {'platform':'Facebook','label':'Facebook Feed portrait','ratio':'4:5','size':(1080,1350),'layout':'feed','text':'allowed','recommended':True},
    'fb_feed_square': {'platform':'Facebook','label':'Facebook Feed square','ratio':'1:1','size':(1080,1080),'layout':'feed','text':'allowed'},
    # Meta Ads
    'meta_feed_portrait': {'platform':'Meta Ads','label':'Meta Feed ad 4:5','ratio':'4:5','size':(1080,1350),'layout':'performance','text':'allowed','recommended':True},
    'meta_feed_square': {'platform':'Meta Ads','label':'Meta Feed / carousel ad 1:1','ratio':'1:1','size':(1080,1080),'layout':'performance','text':'allowed','recommended':True},
    'meta_story': {'platform':'Meta Ads','label':'Meta Stories ad 9:16','ratio':'9:16','size':(1080,1920),'layout':'story','text':'allowed','recommended':True},
    'meta_reel_cover': {'platform':'Meta Ads','label':'Meta Reels cover 9:16','ratio':'9:16','size':(1080,1920),'layout':'reel','text':'allowed','recommended':True},
    # Google image assets: keep text/graphics off the image itself.
    'google_search_square': {'platform':'Google Ads','label':'Google Search image asset square','ratio':'1:1','size':(1200,1200),'layout':'google_clean','text':'forbidden','recommended':True},
    'google_search_landscape': {'platform':'Google Ads','label':'Google Search image asset landscape','ratio':'1.91:1','size':(1200,628),'layout':'google_clean','text':'forbidden','recommended':True},
    'google_pmax_square': {'platform':'Google Ads','label':'Performance Max square','ratio':'1:1','size':(1200,1200),'layout':'google_clean','text':'forbidden','recommended':True},
    'google_pmax_landscape': {'platform':'Google Ads','label':'Performance Max landscape','ratio':'1.91:1','size':(1200,628),'layout':'google_clean','text':'forbidden','recommended':True},
    'google_pmax_portrait': {'platform':'Google Ads','label':'Performance Max portrait','ratio':'4:5','size':(960,1200),'layout':'google_clean','text':'forbidden','recommended':True},
    'google_demandgen_square': {'platform':'Google Ads','label':'Demand Gen square','ratio':'1:1','size':(1200,1200),'layout':'google_clean','text':'forbidden'},
    'google_demandgen_landscape': {'platform':'Google Ads','label':'Demand Gen landscape','ratio':'1.91:1','size':(1200,628),'layout':'google_clean','text':'forbidden'},
    'google_demandgen_portrait': {'platform':'Google Ads','label':'Demand Gen portrait','ratio':'4:5','size':(960,1200),'layout':'google_clean','text':'forbidden'},
    'google_demandgen_vertical': {'platform':'Google Ads','label':'Demand Gen / Shorts vertical','ratio':'9:16','size':(1080,1920),'layout':'google_clean','text':'forbidden'},
    # Uploaded display ad canvases (creative text can be part of the ad artwork).
    'gdn_300x250': {'platform':'Google Display','label':'Display inline rectangle','ratio':'6:5','size':(300,250),'layout':'banner','text':'allowed'},
    'gdn_336x280': {'platform':'Google Display','label':'Display large rectangle','ratio':'6:5','size':(336,280),'layout':'banner','text':'allowed'},
    'gdn_300x600': {'platform':'Google Display','label':'Display half-page','ratio':'1:2','size':(300,600),'layout':'tall_banner','text':'allowed'},
    'gdn_728x90': {'platform':'Google Display','label':'Display leaderboard','ratio':'8.09:1','size':(728,90),'layout':'wide_banner','text':'allowed'},
    'gdn_320x100': {'platform':'Google Display','label':'Display mobile large banner','ratio':'3.2:1','size':(320,100),'layout':'wide_banner','text':'allowed'},
    'pinterest_pin': {'platform':'Pinterest','label':'Pinterest product pin','ratio':'2:3','size':(1000,1500),'layout':'feed','text':'allowed'},
}

VIDEO_PLACEMENTS = {
    'ig_reel_video': {'platform':'Instagram','label':'Instagram Reel','ratio':'9:16','size':(1080,1920),'recommended':True},
    'ig_story_video': {'platform':'Instagram','label':'Instagram Story video','ratio':'9:16','size':(1080,1920),'recommended':True},
    'fb_reel_video': {'platform':'Facebook','label':'Facebook Reel','ratio':'9:16','size':(1080,1920),'recommended':True},
    'meta_reel_video': {'platform':'Meta Ads','label':'Meta Reels video ad','ratio':'9:16','size':(1080,1920),'recommended':True},
    'meta_story_video': {'platform':'Meta Ads','label':'Meta Stories video ad','ratio':'9:16','size':(1080,1920),'recommended':True},
    'youtube_landscape': {'platform':'Google / YouTube','label':'YouTube landscape video ad','ratio':'16:9','size':(1920,1080),'recommended':True},
    'youtube_vertical': {'platform':'Google / YouTube','label':'YouTube Shorts vertical ad','ratio':'9:16','size':(1080,1920),'recommended':True},
    'youtube_square': {'platform':'Google / YouTube','label':'YouTube square video asset','ratio':'1:1','size':(1080,1080)},
}

PRESET_BUNDLES = {
    'instagram_launch': ['ig_feed_portrait','ig_feed_square','ig_story','ig_reel_video'],
    'meta_ads': ['meta_feed_portrait','meta_feed_square','meta_story','meta_reel_video'],
    'google_ads': ['google_search_square','google_search_landscape','google_pmax_square','google_pmax_landscape','google_pmax_portrait','google_demandgen_square','google_demandgen_landscape','google_demandgen_portrait','google_demandgen_vertical','youtube_landscape','youtube_vertical'],
    'full_social': ['ig_feed_portrait','ig_story','ig_reel_video','fb_feed_portrait','fb_reel_video','pinterest_pin'],
    'full_launch': ['ig_feed_portrait','ig_story','ig_reel_video','fb_feed_portrait','meta_feed_portrait','meta_feed_square','meta_story','meta_reel_video','google_search_square','google_search_landscape','google_pmax_square','google_pmax_landscape','google_pmax_portrait','google_demandgen_square','google_demandgen_landscape','google_demandgen_portrait','google_demandgen_vertical','youtube_landscape','youtube_vertical','pinterest_pin'],
}

VISUAL_STYLES = ['Minimal studio','Luxury studio','Traditional','Festive','Wedding','Heritage editorial','Modern fashion','Lifestyle','Product-first performance ad']
BACKGROUND_STYLES = ['White / clean','Warm neutral','Luxury cream','Soft gradient','Indian heritage interior','Festive ambience','Wedding ambience','Dark premium','Lifestyle environment']
SUBJECT_MODES = ['Product only','Mannequin','Adult model','Lifestyle model']
MODEL_STYLES = ['Neutral adult fashion model','South Asian adult fashion model','Editorial adult fashion model','Traditional styling','Contemporary styling']
CAMPAIGN_TYPES = ['New arrival','Collection launch','Product spotlight','Sale / promotion','Bridal / wedding','Festive','Wholesale / B2B','Retargeting','Evergreen catalogue']
VIDEO_STYLES = ['Product showcase','Luxury fashion','Fast social reel','New arrival','Sale / promotion','Collection launch','Craftsmanship detail','Lifestyle editorial']
DURATIONS = [6,10,15,20,30]

MASTER_KINDS = {
    'product': {'label':'Clean studio product','subject':'Product only','description':'Clean product-first ecommerce/studio visual with no person.'},
    'mannequin': {'label':'Mannequin','subject':'Mannequin','description':'Headless mannequin wearing the same garment.'},
    'model': {'label':'Model','subject':'Adult model','description':'Adult fashion model wearing the same garment.'},
    'lifestyle': {'label':'Lifestyle model','subject':'Lifestyle model','description':'Adult model in a controlled lifestyle scene.'},
}

MASTER_PRIORITY = {
    'google_clean':['product','mannequin','model','lifestyle'],
    'banner':['product','model','mannequin','lifestyle'],
    'wide_banner':['product','model','mannequin','lifestyle'],
    'tall_banner':['model','product','mannequin','lifestyle'],
    'performance':['model','lifestyle','mannequin','product'],
    'story':['model','lifestyle','mannequin','product'],
    'reel':['model','lifestyle','mannequin','product'],
    'feed':['model','product','mannequin','lifestyle'],
}


def uid(prefix: str) -> str:
    return prefix + '-' + secrets.token_hex(7).upper()


def initialise() -> None:
    with m.connect() as con:
        con.executescript(SCHEMA)
        existing={str(r['name']) if isinstance(r,dict) else str(r[1]) for r in con.execute('PRAGMA table_info(v8_video_jobs)')}
        for col,ddl in [('transition_style',"TEXT DEFAULT 'Fade'"),('captions_mode',"TEXT DEFAULT 'off'"),('logo_mode',"TEXT DEFAULT 'Use logo'")]:
            if col not in existing:con.execute(f'ALTER TABLE v8_video_jobs ADD COLUMN {col} {ddl}')
        defaults = {
            'v8_default_language':'English',
            'v8_default_market':'United Kingdom',
            'v8_default_variations':'2',
            'v8_video_provider':'local',
            'v8_veo_model':'veo-3.1-generate-preview',
            'v8_tts_model':m.routed_model('voiceover','gpt-4o-mini-tts'),
            'v8_tts_voice':'marin',
            'v8_auto_detail_pack':'1',
        }
        for k,v in defaults.items():
            con.execute('INSERT OR IGNORE INTO settings(setting_key,setting_value) VALUES(?,?)',(k,v))
        # Truthful approval migration: older releases could retain placement images
        # as Approved even though no V19 placement-QC evidence existed.  V22 never
        # treats those legacy rows as publishable until they are checked again.
        repaired=con.execute("""UPDATE v8_creative_campaign_assets
          SET status='Needs review',notes=coalesce(notes,'')||CASE WHEN coalesce(notes,'')='' THEN '' ELSE '\n' END||'V22: approval reset because placement QC evidence was missing.',updated_at=CURRENT_TIMESTAMP
          WHERE status='Approved' AND media_type='image' AND placement_key NOT LIKE 'MASTER%'
            AND NOT EXISTS (SELECT 1 FROM v19_creative_quality q WHERE q.asset_id=v8_creative_campaign_assets.id AND q.qc_status='Passed')""").rowcount
    if repaired:
        m.audit('creative.legacy_approval_reset','',f'{repaired} approved image asset(s) moved back to Needs review because placement QC evidence was missing.')
    for p in (CAMPAIGN_ROOT,VIDEO_ROOT,MUSIC_ROOT):p.mkdir(parents=True,exist_ok=True)


def setting(key, default=''):
    return ce.setting(key,default)


def save_default_settings(raw: dict) -> None:
    vals={
        'v8_default_language':(raw.get('v8_default_language') or 'English').strip()[:80],
        'v8_default_market':(raw.get('v8_default_market') or 'United Kingdom').strip()[:120],
        'v8_default_variations':str(max(1,min(4,int(raw.get('v8_default_variations') or 2)))),
        'v8_video_provider':raw.get('v8_video_provider') if raw.get('v8_video_provider') in {'local','veo'} else 'local',
        'v8_veo_model':(raw.get('v8_veo_model') or 'veo-3.1-generate-preview').strip(),
        'v8_tts_model':(raw.get('v8_tts_model') or m.routed_model('voiceover','gpt-4o-mini-tts')).strip(),
        'v8_tts_voice':(raw.get('v8_tts_voice') or 'marin').strip(),
        'v8_auto_detail_pack':'1' if raw.get('v8_auto_detail_pack')=='1' else '0',
    }
    with m.connect() as con:
        for k,v in vals.items():con.execute('INSERT OR REPLACE INTO settings VALUES(?,?)',(k,v))


def video_secret() -> str:
    env=os.environ.get('GEMINI_API_KEY','').strip()
    if env:return env
    try:return json.loads(VIDEO_SECRET_PATH.read_text()).get('api_key','')
    except (OSError,ValueError,AttributeError):return ''


def save_video_secret(key: str) -> None:
    key=(key or '').strip()
    if len(key)<20 or any(c.isspace() for c in key):raise ValueError('That video API key does not look complete. No key was saved.')
    VIDEO_SECRET_PATH.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
    tmp=VIDEO_SECRET_PATH.with_suffix('.tmp')
    fd=os.open(tmp,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
    with os.fdopen(fd,'w') as f:json.dump({'api_key':key},f)
    os.chmod(tmp,0o600);os.replace(tmp,VIDEO_SECRET_PATH)


def clear_video_secret() -> None:
    try:VIDEO_SECRET_PATH.unlink()
    except FileNotFoundError:pass


def save_music(raw: bytes, filename: str, label='Uploaded music') -> str:
    if not raw or len(raw)>30*1024*1024:raise ValueError('Choose an audio file under 30 MB.')
    suffix=Path(filename).suffix.lower()
    if suffix not in {'.mp3','.wav','.m4a','.aac','.ogg','.flac'}:raise ValueError('Use MP3, WAV, M4A, AAC, OGG or FLAC audio.')
    mid=uid('MUSIC');dest=MUSIC_ROOT/(mid+suffix);dest.write_bytes(raw)
    with m.connect() as con:con.execute('INSERT INTO v8_music_assets(id,label,relative_path) VALUES(?,?,?)',(mid,(label or Path(filename).stem)[:120],dest.relative_to(ROOT).as_posix()))
    return mid


def music_assets():
    return m.rows('SELECT * FROM v8_music_assets ORDER BY created_at DESC')


def _automation_level() -> int:
    try:
        row=m.one("SELECT setting_value FROM settings WHERE setting_key='v13_default_automation_level'")
        return max(1,min(4,int((row or {}).get('setting_value') or 2)))
    except Exception:
        return 2


def ai_image_ready() -> bool:
    return bool(m.secret())


def brief_readiness(cid: str) -> dict:
    c=campaign(cid);products=campaign_products(cid);issues=[];warnings=[]
    if not (c.get('cta') or '').strip():issues.append('Call to action is missing.')
    if c.get('text_mode')!='No text' and not (c.get('promotional_message') or '').strip():warnings.append('No promotional message is set; placement copy will fall back to the product title.')
    if not (c.get('price_text') or '').strip():warnings.append('No price text is included.')
    if not (c.get('offer_text') or '').strip():warnings.append('No offer is included.')
    for p in products:
        ready=pe.readiness(p['product_id'])
        if not ready.get('confirmed'):issues.append(f"{p.get('public_product_name') or p['product_id']}: product facts are not owner/supplier verified.")
        title=(p.get('public_product_name') or '').strip()
        if len(title)>80 or any(x in title.lower() for x in [' colour ',' body plain',' pallu body']):warnings.append(f"{title or p['product_id']}: customer-facing title may still read like source metadata and should be reviewed.")
    return {'ready':not issues,'issues':issues,'warnings':warnings}


def placement_qc(asset_id: str) -> dict:
    initialise();a=m.one('SELECT * FROM v8_creative_campaign_assets WHERE id=?',(asset_id,))
    if not a:raise ValueError('Creative asset not found.')
    issues=[];checks={};score=100.0;path=ROOT/a['relative_path'];checks['file_exists']=path.exists()
    if not path.exists():issues.append('Generated file is missing.');score-=60
    spec=placement_spec(a['campaign_id'],a['placement_key'])
    if a['media_type']=='image' and path.exists() and spec:
        try:
            from PIL import Image
            with Image.open(path) as im:
                checks['actual_size']=list(im.size);checks['expected_size']=list(spec['size'])
                if tuple(im.size)!=tuple(spec['size']):issues.append(f"Canvas is {im.size[0]}×{im.size[1]} but placement requires {spec['size'][0]}×{spec['size'][1]}.");score-=35
                if min(im.size)<250:issues.append('Image resolution is too small for a campaign placement.');score-=30
        except Exception:issues.append('Generated image could not be decoded for quality review.');score-=50
        c=campaign(a['campaign_id']);p=ce.product(a['product_id'])
        if spec.get('text')=='allowed' and c.get('text_mode')!='No text':
            promo=(c.get('promotional_message') or p.get('public_product_name') or '').strip();cta=(c.get('cta') or '').strip();checks['promo_chars']=len(promo);checks['cta_chars']=len(cta)
            limits={'story':80,'reel':80,'feed':70,'performance':70,'banner':46,'wide_banner':34,'tall_banner':48};lim=limits.get(spec.get('layout'),70)
            if len(promo)>lim:issues.append(f'Headline is too long for the {spec.get("layout") or "placement"} safe zone ({len(promo)} characters; target <= {lim}).');score-=20
            if len(cta)>28:issues.append('CTA is too long for the placement safe zone.');score-=15
        if spec.get('text')=='forbidden':checks['text_free_policy']=True
    try:
        ready=pe.readiness(a['product_id']);checks['product_facts_confirmed']=bool(ready.get('confirmed'))
        if not ready.get('confirmed'):checks['product_truth_warning']='Product facts are not owner/supplier verified; publishing handoff remains blocked until they are confirmed.'
    except Exception as exc:
        issues.append('Product truth/readiness could not be verified; approval is blocked until the check succeeds.');score-=50
        checks['product_truth_error']=str(exc)[:500]
        from operational_guard import record_side_effect_failure
        record_side_effect_failure('creative_qc','Creative QC could not verify product truth',exc,recovery='Open the product workspace, verify product facts, then rerun creative quality review.',entity_type='product',entity_id=a['product_id'],severity='Error')
    score=max(0.0,min(100.0,score));status='Passed' if not issues else 'Needs attention'
    with m.connect() as con:
        con.execute("INSERT INTO v19_creative_quality(asset_id,campaign_id,product_id,qc_status,score,issues_json,checks_json,checked_at) VALUES(?,?,?,?,?,?,?,CURRENT_TIMESTAMP) ON CONFLICT(asset_id) DO UPDATE SET qc_status=excluded.qc_status,score=excluded.score,issues_json=excluded.issues_json,checks_json=excluded.checks_json,checked_at=CURRENT_TIMESTAMP",(asset_id,a['campaign_id'],a['product_id'],status,score,json.dumps(issues,ensure_ascii=False),json.dumps(checks,ensure_ascii=False)))
    return {'status':status,'score':score,'issues':issues,'checks':checks}


def quality_for(asset_id: str) -> dict:
    row=m.one('SELECT * FROM v19_creative_quality WHERE asset_id=?',(asset_id,))
    if not row:return {'qc_status':'Not checked','score':None,'issues':[]}
    try:issues=json.loads(row.get('issues_json') or '[]')
    except Exception:issues=[]
    return {**row,'issues':issues}


def _auto_prepare_if_ready(cid: str) -> int:
    if _automation_level()<2:return 0
    rows=[a for a in campaign_assets(cid) if not a['placement_key'].startswith('MASTER') and a['status']!='Archived']
    if not rows:return 0
    if any(a['status'] in {'Needs review','QC passed','Draft'} for a in rows):return 0
    return prepare_publish_handoffs(cid)


def ensure_unified_campaign(cid: str) -> str:
    initialise();existing=m.one('SELECT * FROM v19_creative_campaign_links WHERE creative_campaign_id=?',(cid,))
    if existing and existing.get('unified_campaign_id'):return existing['unified_campaign_id']
    c=campaign(cid);products=campaign_products(cid);handoffs=publish_handoffs(cid)
    if not handoffs:raise ValueError('Approve the required creative assets before creating the business campaign plan.')
    import owner_experience as oe
    defaults=oe.campaign_defaults('collection');ready=[x['channel'] for x in defaults['channels'] if x.get('ready')]
    if not ready:raise ValueError('No business channels are ready yet. Connect at least one channel before creating the campaign plan.')
    ucid=oe.create_business_campaign({'goal_key':'collection','name':c['name'],'product_ids':[p['product_id'] for p in products],'channels':ready,'region':c['target_market'],'language':c['language']})
    with m.connect() as con:con.execute("INSERT INTO v19_creative_campaign_links(creative_campaign_id,unified_campaign_id,status,detail) VALUES(?,?,?,?) ON CONFLICT(creative_campaign_id) DO UPDATE SET unified_campaign_id=excluded.unified_campaign_id,status=excluded.status,detail=excluded.detail,updated_at=CURRENT_TIMESTAMP",(cid,ucid,'Prepared','Business-goal campaign plan created from approved creative handoffs.'))
    return ucid


def refresh_creative_campaign_status(cid: str) -> str:
    assets=[a for a in campaign_assets(cid) if not a['placement_key'].startswith('MASTER') and a['status']!='Archived']
    handoffs=publish_handoffs(cid) if assets else []
    if handoffs:status='Handoffs prepared'
    elif any(a['status'] in {'Needs review','QC passed','Draft'} for a in assets):status='Creative review'
    elif any(a['status']=='Approved' for a in assets):status='Approved creative'
    elif assets:status='Needs attention'
    else:status='Draft'
    with m.connect() as con:con.execute('UPDATE v8_creative_campaigns SET status=?,updated_at=CURRENT_TIMESTAMP WHERE id=?',(status,cid))
    return status


def create_campaign(raw: dict, product_ids: list[str], placements: list[str]) -> str:
    initialise()
    product_ids=list(dict.fromkeys([p for p in product_ids if p]))
    if not product_ids:raise ValueError('Select at least one product.')
    for pid in product_ids:ce.product(pid)
    placements=list(dict.fromkeys([x for x in placements if x in IMAGE_PLACEMENTS or x in VIDEO_PLACEMENTS]))
    if not placements:raise ValueError('Select at least one image or video placement.')
    cid=uid('CCAMP')
    name=(raw.get('name') or 'Creative launch').strip()[:180]
    try:variations=max(1,min(4,int(raw.get('variations') or setting('v8_default_variations','2'))))
    except ValueError:variations=2
    values=(cid,name,(raw.get('campaign_type') or 'New arrival')[:80],(raw.get('target_market') or setting('v8_default_market','United Kingdom'))[:120],(raw.get('language') or setting('v8_default_language','English'))[:80],(raw.get('visual_style') or 'Luxury studio')[:80],(raw.get('background_style') or 'Warm neutral')[:100],(raw.get('subject_mode') or 'Adult model')[:80],(raw.get('model_style') or 'South Asian adult fashion model')[:120],(raw.get('text_mode') or 'Marketing text')[:40],(raw.get('promotional_message') or '')[:300],(raw.get('cta') or ce.setting('creative_cta','Explore the collection'))[:100],(raw.get('price_text') or '')[:100],(raw.get('offer_text') or '')[:140],(raw.get('logo_mode') or 'Use logo')[:40],'Draft')
    with m.connect() as con:
        con.execute('''INSERT INTO v8_creative_campaigns(id,name,campaign_type,target_market,language,visual_style,background_style,subject_mode,model_style,text_mode,promotional_message,cta,price_text,offer_text,logo_mode,status) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',values)
        for pid in product_ids:con.execute('INSERT INTO v8_creative_campaign_products VALUES(?,?)',(cid,pid))
        for pl in placements:con.execute('INSERT INTO v8_creative_campaign_placements VALUES(?,?,?)',(cid,pl,variations if pl in IMAGE_PLACEMENTS else 1))
        # Optional custom canvas dimensions for unusual ad placements or retailer requirements.
        for media,prefix in [('image','custom_image'),('video','custom_video')]:
            try:w=int(raw.get(prefix+'_width') or 0);h=int(raw.get(prefix+'_height') or 0)
            except ValueError:w=h=0
            if w and h:
                if not (100<=w<=4096 and 100<=h<=4096):raise ValueError('Custom creative dimensions must be between 100 and 4096 pixels.')
                key=f'{prefix}_{w}x{h}';label=(raw.get(prefix+'_label') or f'Custom {media} {w}×{h}')[:100];ratio=f'{w}:{h}'
                con.execute('INSERT INTO v8_custom_placements(campaign_id,placement_key,media_type,label,platform,width,height,aspect_ratio,text_policy,variations) VALUES(?,?,?,?,?,?,?,?,?,?)',(cid,key,media,label,'Custom',w,h,ratio,'allowed',variations if media=='image' else 1))
                con.execute('INSERT INTO v8_creative_campaign_placements VALUES(?,?,?)',(cid,key,variations if media=='image' else 1))
    return cid


def campaign(cid: str) -> dict:
    row=m.one('SELECT * FROM v8_creative_campaigns WHERE id=?',(cid,))
    if not row:raise ValueError('Creative campaign not found.')
    return row


def campaign_products(cid: str):
    return m.rows('''SELECT p.*,(SELECT relative_path FROM product_images i WHERE i.product_id=p.product_id ORDER BY is_primary DESC LIMIT 1) img FROM products p JOIN v8_creative_campaign_products cp ON cp.product_id=p.product_id WHERE cp.campaign_id=? AND coalesce(p.status,'Draft')<>'Archived' ORDER BY p.public_product_name''',(cid,))


def placement_spec(cid: str, key: str):
    if key in IMAGE_PLACEMENTS:return IMAGE_PLACEMENTS[key]
    if key in VIDEO_PLACEMENTS:return VIDEO_PLACEMENTS[key]
    r=m.one('SELECT * FROM v8_custom_placements WHERE campaign_id=? AND placement_key=?',(cid,key))
    if not r:return None
    base={'platform':r['platform'] or 'Custom','label':r['label'] or key,'ratio':r['aspect_ratio'] or f"{r['width']}:{r['height']}",'size':(int(r['width']),int(r['height']))}
    if r['media_type']=='image':base.update({'layout':'feed' if r['height']>=r['width'] else 'banner','text':r['text_policy'] or 'allowed'})
    return base


def campaign_placements(cid: str):
    return m.rows('SELECT * FROM v8_creative_campaign_placements WHERE campaign_id=? ORDER BY placement_key',(cid,))


def campaign_assets(cid: str):
    return m.rows('SELECT * FROM v8_creative_campaign_assets WHERE campaign_id=? ORDER BY product_id,placement_key,variation,version_no DESC',(cid,))


def list_campaigns(include_archived: bool=False):
    where='' if include_archived else "WHERE coalesce(c.status,'Draft')<>'Archived'"
    return m.rows('''SELECT c.*,(SELECT count(*) FROM v8_creative_campaign_products p WHERE p.campaign_id=c.id) product_count,(SELECT count(*) FROM v8_creative_campaign_assets a WHERE a.campaign_id=c.id AND a.status<>'Archived') asset_count FROM v8_creative_campaigns c '''+where+''' ORDER BY c.created_at DESC''')

def archive_campaign(cid: str) -> None:
    c=campaign(cid)
    if c.get('status')=='Archived':return
    with m.connect() as con:con.execute("UPDATE v8_creative_campaigns SET status='Archived',updated_at=CURRENT_TIMESTAMP WHERE id=?",(cid,))
    m.audit('creative_campaign.archived',cid,'Creative campaign archived; generated assets and handoff history were preserved.')

def restore_campaign(cid: str) -> None:
    c=campaign(cid)
    if c.get('status')!='Archived':return
    with m.connect() as con:con.execute("UPDATE v8_creative_campaigns SET status='Draft',updated_at=CURRENT_TIMESTAMP WHERE id=?",(cid,))
    m.audit('creative_campaign.restored',cid,'Creative campaign restored to Draft for review.')

def require_active_campaign(cid: str) -> dict:
    c=campaign(cid)
    if c.get('status')=='Archived':raise ValueError('This creative campaign is archived. Restore it before generating, reviewing or exporting assets.')
    return c


def _source_for_campaign(cid: str, product_id: str, placement_key: str = '') -> tuple[Path,str,str]:
    # Pick the approved AI master that best fits the intended placement. Clean Google
    # image assets prefer product-only photography, while social/performance placements
    # can prefer model/lifestyle masters. Originals remain the fallback source of truth.
    spec=placement_spec(cid,placement_key) if placement_key else None
    layout=(spec or {}).get('layout','feed')
    priorities=MASTER_PRIORITY.get(layout,['model','product','mannequin','lifestyle'])
    for kind in priorities:
        pkey='MASTER_'+kind.upper()
        a=m.one("""SELECT a.*,v.relative_path FROM v8_creative_campaign_assets a LEFT JOIN v7_creative_assets v ON v.id=a.source_asset_id WHERE a.campaign_id=? AND a.product_id=? AND a.placement_key=? AND a.status='Approved' ORDER BY a.version_no DESC LIMIT 1""",(cid,product_id,pkey))
        if a and a.get('relative_path') and (ROOT/a['relative_path']).exists():
            return ROOT/a['relative_path'],f'Approved AI {kind} master',a.get('source_asset_id') or ''
    # Backward compatibility with V8 drafts created before named master types.
    a=m.one("""SELECT a.*,v.relative_path FROM v8_creative_campaign_assets a LEFT JOIN v7_creative_assets v ON v.id=a.source_asset_id WHERE a.campaign_id=? AND a.product_id=? AND a.placement_key='MASTER' AND a.status='Approved' ORDER BY a.version_no DESC LIMIT 1""",(cid,product_id))
    if a and a.get('relative_path') and (ROOT/a['relative_path']).exists():return ROOT/a['relative_path'],'Approved AI campaign master',a.get('source_asset_id') or ''
    path,label=ce.preferred_visual(product_id)
    return path,label,''

def _data_url(path: Path) -> str:
    mime=mimetypes.guess_type(path.name)[0] or 'image/jpeg'
    return f'data:{mime};base64,'+base64.b64encode(path.read_bytes()).decode('ascii')


def _reference_images(product_id: str, limit=5):
    out=[]
    for im in ce.source_images(product_id,limit):
        p=ROOT/im['relative_path']
        if p.exists():
            small=pe.analysis_copy(p)
            out.append({'type':'input_image','image_url':_data_url(small),'detail':'high'})
    return out


def _master_prompt(c: dict, p: dict, variation: int, master_kind='model') -> str:
    kind=master_kind if master_kind in MASTER_KINDS else 'model'
    subject=MASTER_KINDS[kind]['subject'];style=c['visual_style'];background=c['background_style'];model=c['model_style']
    subject_text={
        'Product only':'Present the garment/product without a person, professionally arranged so the complete design remains legible. Use premium studio product photography.',
        'Mannequin':'Dress a neutral headless fashion mannequin in the exact same garment. Keep the drape plausible and the product unobscured.',
        'Adult model':f'Dress an adult fashion model in the exact same garment. Model styling: {model}. Keep styling secondary to the product.',
        'Lifestyle model':f'Dress an adult fashion model in the exact same garment in a controlled lifestyle scene. Model styling: {model}. Keep the garment dominant and clearly visible.',
    }.get(subject,'Present the exact product clearly.')
    variation_hint=['front three-quarter composition','full-length balanced composition','slightly asymmetric editorial composition','close commercial composition'][max(0,min(3,variation-1))]
    return f'''EDIT the supplied product reference photographs into a professional fashion-commerce master image.
MASTER TYPE: {MASTER_KINDS[kind]['label']}. SUBJECT: {subject_text}
VISUAL STYLE: {style}. BACKGROUND: {background}. COMPOSITION: {variation_hint}.
The garment is the product being sold. It must be the SAME physical design shown in the references, not a redesign. Preserve its visible colour, motif shapes, motif spacing, embroidery/print placement, border width and border pattern, pallu treatment, blouse cues, texture/sheens and distinguishing details. Do not simplify, add, remove or reinterpret the textile design. Do not invent jewellery attached to the product, new embroidery, new zari, new logos, text, labels or unseen details. If a product detail is unclear, keep it visually conservative rather than hallucinating it.
Keep the garment unobscured and commercially legible. Avoid hands, props, folds or crops covering important motifs/borders. No text, watermark, price, CTA or logo in this master image. Product metadata is context only: {json.dumps({k:p.get(k) for k in ['public_product_name','colour','fabric','weave_or_motif','category']},ensure_ascii=False)}.
This output will be fidelity-checked against the originals before it is used for advertising.'''


def generate_master(cid: str, product_id: str, variation=1, master_kind='model') -> str:
    c=campaign(cid);p=ce.product(product_id);kind=master_kind if master_kind in MASTER_KINDS else 'model'
    if product_id not in {x['product_id'] for x in campaign_products(cid)}:raise ValueError('That product is not part of this creative campaign.')
    key=m.secret()
    if not key:raise ValueError('Connect the OpenAI API key in Settings & AI before generating a model/mannequin/studio master.')
    try:
        import operating_core as oc
        oc.guard_ai_call('image')
    except ImportError:oc=None
    import ai_router
    controller_state=ai_router.preflight('product_understanding',object_type='product',object_id=product_id,default_model=ce.setting('creative_controller_model',m.routed_model('product_understanding','gpt-6-sol')))
    image_state=ai_router.preflight('creative_master',object_type='product',object_id=product_id,default_model=ce.setting('creative_image_model',m.routed_model('image_preserve','gpt-image-2.5-sunburst')))
    prompt=_master_prompt(c,p,int(variation),kind);content=[{'type':'input_text','text':prompt}]+_reference_images(product_id,5)
    body={'model':controller_state['model'],'store':False,'input':[{'role':'user','content':content}],
          'tools':[{'type':'image_generation','model':image_state['model'],'action':'edit','size':'1024x1280','quality':'high','output_format':'webp'}]}
    out,attempts,duration_ms=ai_router.request_json('creative_master',body,timeout=300,object_type='product',object_id=product_id,max_attempts=3)
    encoded=None
    for item in out.get('output',[]):
        if item.get('type')=='image_generation_call' and item.get('result'):encoded=item['result'];break
    if not encoded:
        if oc:
            try:ai_router.record_failure('creative_master','OpenAI',body['tools'][0]['model'],error='No usable image returned',object_type='product',object_id=product_id)
            except Exception:pass
        raise ValueError('The AI request finished without a usable image.')
    if oc:
        try:
            usage=out.get('usage') or {}
            ai_router.record_success('creative_master','OpenAI',body['tools'][0]['model'],object_type='product',object_id=product_id,input_units=int(usage.get('input_tokens') or 0),output_units=int(usage.get('output_tokens') or 0),image_count=1,provider_request_id=str(out.get('id') or ''),duration_ms=duration_ms,attempts=attempts)
        except Exception:pass
    raw=base64.b64decode(encoded);vid=uid('CASSET');folder=CAMPAIGN_ROOT/cid/product_id/'masters'/kind;folder.mkdir(parents=True,exist_ok=True);dest=folder/(vid+'.webp');dest.write_bytes(raw)
    rel=dest.relative_to(ROOT).as_posix();media_store.persist(rel,public=True);pkey='MASTER_'+kind.upper()
    with m.connect() as con:
        con.execute('INSERT INTO v7_creative_assets(id,product_id,job_id,asset_kind,channel,aspect_ratio,relative_path,source_kind,status,notes) VALUES(?,?,?,?,?,?,?,?,?,?)',(vid,product_id,None,f'AI {kind} campaign master','Creative Studio','4:5',rel,'AI generated','Fidelity review',f'Campaign-specific {kind} AI visual. Original photography remains source of truth.'))
        ver=con.execute('SELECT coalesce(max(version_no),0)+1 FROM v8_creative_campaign_assets WHERE campaign_id=? AND product_id=? AND placement_key=?',(cid,product_id,pkey)).fetchone()[0]
        link=uid('V8A');con.execute('INSERT INTO v8_creative_campaign_assets(id,campaign_id,product_id,placement_key,media_type,variation,relative_path,source_kind,source_asset_id,status,version_no,notes) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',(link,cid,product_id,pkey,'image',int(variation),rel,f'AI generated — {kind}',vid,'Fidelity review',ver,prompt[:1000]))
    if ce.setting('creative_auto_fidelity','1')=='1':
        try:
            ce.fidelity_check(vid);row=m.one('SELECT status,fidelity_score FROM v7_creative_assets WHERE id=?',(vid,))
            with m.connect() as con:con.execute('UPDATE v8_creative_campaign_assets SET status=?,notes=coalesce(notes,'')||?,updated_at=CURRENT_TIMESTAMP WHERE source_asset_id=?',(row['status'],'\nFidelity '+str(row['fidelity_score']),vid))
        except Exception:pass
    return vid


def generate_master_pack(cid: str, kinds: list[str], variations=1) -> dict:
    kinds=[k for k in dict.fromkeys(kinds) if k in MASTER_KINDS]
    if not kinds:raise ValueError('Choose at least one AI master type.')
    try:variations=max(1,min(2,int(variations)))
    except Exception:variations=1
    made=[];errors=[]
    for p in campaign_products(cid):
        for kind in kinds:
            for v in range(1,variations+1):
                try:made.append(generate_master(cid,p['product_id'],v,kind))
                except Exception as ex:errors.append({'product_id':p['product_id'],'kind':kind,'error':str(ex)[:240]})
    return {'generated':len(made),'errors':errors}

def approve_master(source_asset_id: str, approved=True) -> None:
    a=m.one('SELECT * FROM v8_creative_campaign_assets WHERE source_asset_id=? ORDER BY created_at DESC LIMIT 1',(source_asset_id,))
    if not a:raise ValueError('Campaign master not found.')
    ce.approve_asset(source_asset_id,approved)
    with m.connect() as con:con.execute('UPDATE v8_creative_campaign_assets SET status=?,updated_at=CURRENT_TIMESTAMP WHERE source_asset_id=?',('Approved' if approved else 'Rejected',source_asset_id))
    if approved and _automation_level()>=2:
        try:generate_all_images(a['campaign_id'],force=True)
        except Exception as exc:
            from operational_guard import record_side_effect_failure
            record_side_effect_failure('creative_automation','Approved master could not generate placement assets',exc,recovery='Open Creative Studio, review the approved master, then retry Generate placements.',entity_type='campaign',entity_id=a['campaign_id'],severity='Error',action_url='/creative-studio/'+a['campaign_id'])


def _brand_name() -> str:
    s=m.settings();return (s.get('brand_name') or '').strip()


def _hex(value, default):
    try:
        v=(value or '').lstrip('#');return tuple(int(v[i:i+2],16) for i in (0,2,4))
    except Exception:return default


def _font(size):
    from PIL import ImageFont
    candidates=['/System/Library/Fonts/Helvetica.ttc','/System/Library/Fonts/Supplemental/Arial.ttf','/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf']
    for c in candidates:
        try:return ImageFont.truetype(c,max(8,int(size)))
        except Exception:pass
    return ImageFont.load_default()


def _fit_contain(img, box, bg=(247,245,242), pad=0):
    from PIL import Image,ImageOps
    w,h=box;canvas=Image.new('RGB',(w,h),bg);inner=(max(1,w-2*pad),max(1,h-2*pad));piece=ImageOps.contain(img,inner,method=Image.Resampling.LANCZOS);canvas.paste(piece,((w-piece.width)//2,(h-piece.height)//2));return canvas


def _blur_background(img, size):
    from PIL import Image,ImageOps,ImageFilter
    bg=ImageOps.fit(img,size,method=Image.Resampling.LANCZOS);bg=bg.filter(ImageFilter.GaussianBlur(radius=max(12,min(size)//28)));veil=Image.new('RGBA',size,(255,255,255,70));bg=bg.convert('RGBA');bg.alpha_composite(veil);return bg.convert('RGB')


def _wrap(draw,text,font,max_width,max_lines=3):
    if not text:return []
    words=str(text).split();lines=[];cur=''
    for word in words:
        trial=(cur+' '+word).strip()
        if draw.textbbox((0,0),trial,font=font)[2]<=max_width:cur=trial
        else:
            if cur:lines.append(cur)
            cur=word
            if len(lines)>=max_lines-1:break
    if cur and len(lines)<max_lines:lines.append(cur)
    return lines[:max_lines]


def compose_image(cid: str, product_id: str, placement_key: str, variation=1, force=False) -> str:
    initialise();c=campaign(cid);p=ce.product(product_id);spec=placement_spec(cid,placement_key)
    custom=m.one('SELECT media_type FROM v8_custom_placements WHERE campaign_id=? AND placement_key=?',(cid,placement_key))
    if not spec or (placement_key not in IMAGE_PLACEMENTS and (not custom or custom['media_type']!='image')):raise ValueError('Choose a supported image placement.')
    from PIL import Image,ImageOps,ImageDraw,ImageEnhance,ImageFilter
    src,source_kind,source_asset=_source_for_campaign(cid,product_id,placement_key)
    w,h=spec['size'];layout=spec['layout'];var=int(variation)
    folder=CAMPAIGN_ROOT/cid/product_id/placement_key;folder.mkdir(parents=True,exist_ok=True)
    if force:
        with m.connect() as con:con.execute("UPDATE v8_creative_campaign_assets SET status='Archived',updated_at=CURRENT_TIMESTAMP WHERE campaign_id=? AND product_id=? AND placement_key=? AND variation=? AND status<>'Archived'",(cid,product_id,placement_key,var))
    with Image.open(src) as raw:
        raw=ImageOps.exif_transpose(raw).convert('RGB')
        primary=_hex(ce.setting('creative_brand_primary','#17131B'),(23,19,27));accent=_hex(ce.setting('creative_brand_accent','#A27654'),(162,118,84))
        warm={'White / clean':(250,250,249),'Warm neutral':(244,239,232),'Luxury cream':(245,238,224),'Dark premium':primary}.get(c['background_style'],(244,239,232))
        if layout=='google_clean':
            canvas=_fit_contain(raw,(w,h),warm,pad=max(28,int(min(w,h)*.08)))
        elif layout in {'story','reel'}:
            canvas=_blur_background(raw,(w,h));piece=ImageOps.contain(raw,(int(w*.88),int(h*.72)),method=Image.Resampling.LANCZOS)
            x=(w-piece.width)//2 if var%2 else max(28,int(w*.07));y=max(35,int(h*.06));canvas.paste(piece,(x,y))
        elif layout=='feed':
            canvas=Image.new('RGB',(w,h),warm);piece=ImageOps.contain(raw,(int(w*.90),int(h*.72)),method=Image.Resampling.LANCZOS);x=(w-piece.width)//2;y=max(20,int(h*.04));canvas.paste(piece,(x,y))
        elif layout=='performance':
            canvas=Image.new('RGB',(w,h),warm);piece=ImageOps.contain(raw,(int(w*.88),int(h*.72)),method=Image.Resampling.LANCZOS);x=(w-piece.width)//2;y=max(18,int(h*.03));canvas.paste(piece,(x,y))
        elif layout in {'banner','wide_banner','tall_banner'}:
            canvas=Image.new('RGB',(w,h),warm)
            if layout=='wide_banner':
                piece=ImageOps.fit(raw,(int(w*.40),h),method=Image.Resampling.LANCZOS,centering=(.5,.45));canvas.paste(piece,(0,0))
            elif layout=='tall_banner':
                piece=ImageOps.fit(raw,(w,int(h*.58)),method=Image.Resampling.LANCZOS,centering=(.5,.4));canvas.paste(piece,(0,0))
            else:
                piece=ImageOps.fit(raw,(int(w*.48),h),method=Image.Resampling.LANCZOS,centering=(.5,.45));canvas.paste(piece,(0,0))
        else:canvas=ImageOps.fit(raw,(w,h),method=Image.Resampling.LANCZOS)
        # Marketing text stays in safe, placement-aware zones. Google image assets remain text-free by policy.
        if spec['text']=='allowed' and c['text_mode']!='No text':
            draw=ImageDraw.Draw(canvas,'RGBA');brand=_brand_name();promo=(c['promotional_message'] or p['public_product_name'] or 'New collection').strip();cta=(c['cta'] or '').strip();price=(c['price_text'] or '').strip();offer=(c['offer_text'] or '').strip()
            if layout in {'story','reel','feed','performance'}:
                band_h=int(h*(.23 if layout in {'story','reel'} else .25));y0=h-band_h;draw.rectangle((0,y0,w,h),fill=(*primary,225));pad=max(26,int(w*.045));maxw=w-pad*2
                fbrand=_font(max(18,w*.026));fhead=_font(max(28,w*.046));fsmall=_font(max(18,w*.029));y=y0+max(18,int(band_h*.10))
                if brand:draw.text((pad,y),brand,font=fbrand,fill='white');y+=int(fbrand.size*1.4 if hasattr(fbrand,'size') else 32)
                for line in _wrap(draw,promo,fhead,maxw,2):draw.text((pad,y),line,font=fhead,fill='white');y+=int((getattr(fhead,'size',32))*1.18)
                secondary=' · '.join([x for x in [price,offer] if x]);
                if secondary:draw.text((pad,y),secondary,font=fsmall,fill=(250,235,218,255));y+=int(getattr(fsmall,'size',22)*1.3)
                if cta:draw.rounded_rectangle((pad,y,pad+min(maxw,int(w*.48)),min(h-16,y+max(42,int(h*.035)))),radius=14,fill=(*accent,255));draw.text((pad+16,y+8),cta,font=fsmall,fill='white')
            elif layout in {'banner','wide_banner','tall_banner'}:
                if layout=='wide_banner':tx=int(w*.44);ty=max(8,int(h*.12));maxw=w-tx-10
                elif layout=='tall_banner':tx=14;ty=int(h*.62);maxw=w-28
                else:tx=int(w*.52);ty=max(12,int(h*.12));maxw=w-tx-12
                fbrand=_font(max(9,min(w,h)*.055));fhead=_font(max(11,min(w,h)*.075));fsmall=_font(max(9,min(w,h)*.052));
                if brand:draw.text((tx,ty),brand,font=fbrand,fill=primary);ty+=max(12,int(getattr(fbrand,'size',10)*1.25))
                for line in _wrap(draw,promo,fhead,maxw,2):draw.text((tx,ty),line,font=fhead,fill=primary);ty+=max(13,int(getattr(fhead,'size',12)*1.15))
                sec=' · '.join([x for x in [price,offer] if x]);
                if sec and ty<h-18:draw.text((tx,ty),sec,font=fsmall,fill=accent);ty+=max(12,int(getattr(fsmall,'size',9)*1.2))
                if cta and ty<h-12:draw.text((tx,ty),cta,font=fsmall,fill=primary)
        # Logo is optional and never added to text-free Google image assets.
        if spec['text']=='allowed' and c['logo_mode']=='Use logo':
            logo=ce.brand_logo_path()
            if logo:
                try:
                    with Image.open(logo) as li:
                        li=li.convert('RGBA');li.thumbnail((max(60,int(w*.18)),max(30,int(h*.07))));canvas=canvas.convert('RGBA');canvas.alpha_composite(li,(w-li.width-max(12,int(w*.03)),max(12,int(h*.025))));canvas=canvas.convert('RGB')
                except Exception:pass
    aid=uid('V8A');dest=folder/(f'{aid}.jpg');canvas.save(dest,'JPEG',quality=92,optimize=True)
    rel=dest.relative_to(ROOT).as_posix();media_store.persist(rel,public=True)
    with m.connect() as con:
        ver=con.execute('SELECT coalesce(max(version_no),0)+1 FROM v8_creative_campaign_assets WHERE campaign_id=? AND product_id=? AND placement_key=? AND variation=?',(cid,product_id,placement_key,var)).fetchone()[0]
        con.execute('INSERT INTO v8_creative_campaign_assets(id,campaign_id,product_id,placement_key,media_type,variation,relative_path,source_kind,source_asset_id,status,version_no,notes) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',(aid,cid,product_id,placement_key,'image',var,rel,source_kind,source_asset,'Needs review',ver,'Placement-aware composition; product source was not regenerated.'))
    qc=placement_qc(aid)
    if qc['status']=='Passed':
        with m.connect() as con:con.execute("UPDATE v8_creative_campaign_assets SET status='QC passed',updated_at=CURRENT_TIMESTAMP WHERE id=?",(aid,))
        if _automation_level()>=4:update_asset_status(aid,'Approved')
    return aid


def create_detail_pack(cid: str, product_id: str) -> list[str]:
    from PIL import Image,ImageOps,ImageEnhance,ImageFilter,ImageDraw
    rows=m.rows("SELECT * FROM product_images WHERE product_id=? ORDER BY CASE image_role WHEN 'Close-up' THEN 0 WHEN 'Border / body' THEN 1 WHEN 'Pallu' THEN 2 WHEN 'Blouse' THEN 3 ELSE 8 END,is_primary DESC LIMIT 4",(product_id,))
    made=[]
    for idx,row in enumerate(rows,1):
        src=ROOT/row['relative_path']
        if not src.exists():continue
        with Image.open(src) as raw:
            im=ImageOps.exif_transpose(raw).convert('RGB');im=ImageOps.fit(im,(1200,1200),method=Image.Resampling.LANCZOS,centering=(.5,.5));im=ImageEnhance.Sharpness(im).enhance(1.15);im=ImageEnhance.Contrast(im).enhance(1.03)
            folder=CAMPAIGN_ROOT/cid/product_id/'detail';folder.mkdir(parents=True,exist_ok=True);aid=uid('V8A');dest=folder/(aid+'.jpg');im.save(dest,'JPEG',quality=94,optimize=True);rel=dest.relative_to(ROOT).as_posix();media_store.persist(rel,public=True);pl='detail_'+re.sub(r'[^a-z0-9]+','_',row['image_role'].lower()).strip('_')
            with m.connect() as con:con.execute('INSERT INTO v8_creative_campaign_assets(id,campaign_id,product_id,placement_key,media_type,variation,relative_path,source_kind,status,version_no,notes) VALUES(?,?,?,?,?,?,?,?,?,?,?)',(aid,cid,product_id,pl,'image',idx,rel,'Original detail crop','Needs review',1,f'Enhanced from original {row["image_role"]} photograph; no motif generation.'))
            qc=placement_qc(aid)
            if qc['status']=='Passed':
                with m.connect() as con:con.execute("UPDATE v8_creative_campaign_assets SET status='QC passed',updated_at=CURRENT_TIMESTAMP WHERE id=?",(aid,))
                if _automation_level()>=4:update_asset_status(aid,'Approved')
            made.append(aid)
    return made


def generate_all_images(cid: str, force=False) -> dict:
    prods=campaign_products(cid);placements=[x for x in campaign_placements(cid) if (x['placement_key'] in IMAGE_PLACEMENTS) or (m.one('SELECT media_type FROM v8_custom_placements WHERE campaign_id=? AND placement_key=?',(cid,x['placement_key'])) or {}).get('media_type')=='image'];made=[];details=[]
    for p in prods:
        if setting('v8_auto_detail_pack','1')=='1':details+=create_detail_pack(cid,p['product_id'])
        for pl in placements:
            for v in range(1,int(pl['variations'])+1):made.append(compose_image(cid,p['product_id'],pl['placement_key'],v,force=force))
    refresh_creative_campaign_status(cid)
    return {'placement_assets':len(made),'detail_assets':len(details)}


def _video_size(placement_key,cid=''):
    s=VIDEO_PLACEMENTS.get(placement_key) or (placement_spec(cid,placement_key) if cid else None)
    custom=m.one('SELECT media_type FROM v8_custom_placements WHERE campaign_id=? AND placement_key=?',(cid,placement_key)) if cid else None
    if not s or (placement_key not in VIDEO_PLACEMENTS and (not custom or custom['media_type']!='video')):raise ValueError('Choose a supported video placement.')
    return s['size'],s['ratio']


def create_video_job(cid: str, product_id: str, placement_key: str, raw: dict) -> str:
    campaign(cid);ce.product(product_id);size,ratio=_video_size(placement_key,cid)
    try:duration=int(raw.get('duration') or 15)
    except ValueError:duration=15
    duration=max(4,min(60,duration))
    provider=raw.get('provider') if raw.get('provider') in {'local','veo'} else setting('v8_video_provider','local')
    jid=uid('VJOB')
    with m.connect() as con:con.execute('''INSERT INTO v8_video_jobs(id,campaign_id,product_id,placement_key,provider,duration_seconds,aspect_ratio,style,music_mode,voiceover_mode,voiceover_text,language,transition_style,captions_mode,logo_mode,status) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',(jid,cid,product_id,placement_key,provider,duration,ratio,(raw.get('video_style') or 'Product showcase')[:80],(raw.get('music_mode') or 'none')[:80],(raw.get('voiceover_mode') or 'none')[:80],(raw.get('voiceover_text') or '')[:2000],(raw.get('language') or campaign(cid)['language'])[:80],(raw.get('transition_style') or 'Fade')[:40],(raw.get('captions_mode') or 'off')[:20],(raw.get('logo_mode') or campaign(cid)['logo_mode'])[:40],'Queued'))
    return jid


def _caption_chunks(text: str, count: int) -> list[str]:
    words=(text or '').split()
    if not words or count<=0:return ['']*max(0,count)
    # Keep captions compact and evenly distributed across scenes.
    step=max(3,(len(words)+count-1)//count);chunks=[]
    for i in range(count):chunks.append(' '.join(words[i*step:(i+1)*step]))
    if len(chunks)<count:chunks+=['']*(count-len(chunks))
    return chunks[:count]


def _video_frames(cid,product_id,w,h,max_frames=7,job=None):
    from PIL import Image,ImageOps,ImageDraw
    c=campaign(cid);p=ce.product(product_id);folder=VIDEO_ROOT/cid/product_id/'frames';folder.mkdir(parents=True,exist_ok=True)
    assets=m.rows("SELECT * FROM v8_creative_campaign_assets WHERE campaign_id=? AND product_id=? AND media_type='image' AND status='Approved' AND placement_key NOT LIKE 'MASTER%' ORDER BY CASE WHEN placement_key LIKE 'detail_%' THEN 1 ELSE 0 END,created_at DESC LIMIT 8",(cid,product_id))
    paths=[ROOT/a['relative_path'] for a in assets if (ROOT/a['relative_path']).exists()]
    if len(paths)<2:paths += [ROOT/x['relative_path'] for x in ce.source_images(product_id,6) if (ROOT/x['relative_path']).exists()]
    paths=list(dict.fromkeys(paths))[:max_frames]
    if len(paths)<2:raise ValueError('At least two product images are needed for a video.')
    text_enabled=c['text_mode']!='No text';captions_on=bool(job and str(job.get('captions_mode','off')).lower()=='on');logo_on=bool(job and job.get('logo_mode')=='Use logo')
    caption_text=(job.get('voiceover_text') if job else '') or ''
    captions=_caption_chunks(caption_text,len(paths)) if captions_on else ['']*len(paths)
    out=[];safe_top=max(20,int(h*.055));safe_side=max(18,int(w*.045));safe_bottom=max(26,int(h*.07));primary=_hex(ce.setting('creative_brand_primary','#17131B'),(23,19,27));accent=_hex(ce.setting('creative_brand_accent','#A27654'),(162,118,84));brand=_brand_name()
    logo=ce.brand_logo_path() if logo_on else None
    for i,path in enumerate(paths,1):
        with Image.open(path) as raw:
            raw=ImageOps.exif_transpose(raw).convert('RGB');bg=_blur_background(raw,(w,h))
            reserve=int(h*.22) if text_enabled else int(h*.07)
            piece=ImageOps.contain(raw,(int(w*.88),max(1,h-reserve-safe_top-safe_bottom)),method=Image.Resampling.LANCZOS);bg.paste(piece,((w-piece.width)//2,safe_top))
            draw=ImageDraw.Draw(bg,'RGBA')
            if text_enabled:
                band=int(h*.21);y0=h-band;draw.rectangle((0,y0,w,h),fill=(*primary,226));pad=safe_side;fbrand=_font(max(18,w*.025));fhead=_font(max(22,w*.041));fsmall=_font(max(15,w*.025));promo=(c['promotional_message'] or p['public_product_name'] or 'New collection');y=y0+max(14,int(band*.09))
                if brand:draw.text((pad,y),brand,font=fbrand,fill='white');y+=int(getattr(fbrand,'size',18)*1.35)
                for line in _wrap(draw,promo,fhead,w-pad*2,2):draw.text((pad,y),line,font=fhead,fill='white');y+=int(getattr(fhead,'size',28)*1.13)
                sec=' · '.join([x for x in [c['price_text'],c['offer_text']] if x])
                if sec and y<h-safe_bottom:draw.text((pad,y),sec,font=fsmall,fill=(255,232,210,255));y+=int(getattr(fsmall,'size',18)*1.3)
                if c['cta'] and y<h-safe_bottom:draw.text((pad,y),c['cta'],font=fsmall,fill=(*accent,255))
            cap=captions[i-1]
            if cap:
                fcap=_font(max(18,w*.032));lines=_wrap(draw,cap,fcap,int(w*.78),2);lh=int(getattr(fcap,'size',22)*1.3);boxh=lh*len(lines)+20;cy=(int(h*.68)-boxh//2) if text_enabled else h-safe_bottom-boxh;cx=int(w*.1);cw=int(w*.8);draw.rounded_rectangle((cx,cy,cx+cw,cy+boxh),radius=max(10,int(w*.018)),fill=(0,0,0,165));yy=cy+10
                for line in lines:
                    bbox=draw.textbbox((0,0),line,font=fcap);draw.text(((w-(bbox[2]-bbox[0]))//2,yy),line,font=fcap,fill='white');yy+=lh
            if logo and Path(logo).exists():
                try:
                    with Image.open(logo) as li:
                        li=li.convert('RGBA');li.thumbnail((max(72,int(w*.20)),max(40,int(h*.065))));rgba=bg.convert('RGBA');rgba.alpha_composite(li,(w-li.width-safe_side,safe_top));bg=rgba.convert('RGB')
                except Exception:pass
            dest=folder/f'{uid("VF")}.jpg';bg.save(dest,'JPEG',quality=92);out.append(dest)
    return out

def _generate_tts(text: str, out: Path, language='English') -> bool:
    if not text.strip() or not m.secret(): return False
    try:
        import operating_core as oc
        oc.guard_ai_call('general')
    except ImportError:
        oc=None
    import ai_router
    model=setting('v8_tts_model',m.routed_model('voiceover','gpt-4o-mini-tts'))
    try:
        state=ai_router.preflight('voiceover',object_type='asset',object_id=out.name,default_model=model)
        body={'model':state['model'],'voice':setting('v8_tts_voice','marin'),'input':text[:4096],'instructions':f'Professional, warm fashion-commerce voice. Speak naturally in {language}.','response_format':'mp3'}
        raw,attempts,duration_ms=ai_router.request_provider_bytes('voiceover','OpenAI',state['model'],'https://api.openai.com/v1/audio/speech',headers={'Authorization':'Bearer '+m.secret(),'Content-Type':'application/json'},payload=body,timeout=180,object_type='asset',object_id=out.name,max_attempts=3)
        out.write_bytes(raw)
        ai_router.record_success('voiceover','OpenAI',state['model'],object_type='asset',object_id=out.name,input_units=len(text),duration_ms=duration_ms,attempts=attempts)
        return True
    except Exception:
        return False

def render_local_video(job_id: str, music_id='') -> tuple[str,str]:
    j=m.one('SELECT * FROM v8_video_jobs WHERE id=?',(job_id,))
    if not j:raise ValueError('Video job not found.')
    (w,h),ratio=_video_size(j['placement_key'],j['campaign_id']);folder=VIDEO_ROOT/j['campaign_id']/j['product_id']/job_id;folder.mkdir(parents=True,exist_ok=True);frames=_video_frames(j['campaign_id'],j['product_id'],w,h,job=j)
    manifest={'job_id':job_id,'placement':j['placement_key'],'ratio':ratio,'duration_seconds':j['duration_seconds'],'style':j['style'],'transition_style':j.get('transition_style') or 'Fade','captions_mode':j.get('captions_mode') or 'off','logo_mode':j.get('logo_mode') or 'No logo','voiceover_mode':j['voiceover_mode'],'music_id':music_id or None,'frames':[p.relative_to(ROOT).as_posix() for p in frames],'status':'Storyboard ready','ai_voice_disclosure_required':j['voiceover_mode']=='ai'}
    manifest_path=folder/'manifest.json';manifest_path.write_text(json.dumps(manifest,indent=2));out=folder/'video.mp4';ffmpeg=shutil.which('ffmpeg');renderer='Storyboard only'
    if ffmpeg:
        per=max(.55,float(j['duration_seconds'])/len(frames));clips=[];transition=(j.get('transition_style') or 'Fade').lower()
        for i,frame in enumerate(frames):
            clip=folder/f'clip_{i:02d}.mp4';base=f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h}"
            if transition=='clean cuts':vf=base+',format=yuv420p'
            elif transition=='slow zoom':vf=base+f",zoompan=z='min(zoom+0.0008,1.06)':d={max(1,int(per*30))}:s={w}x{h}:fps=30,format=yuv420p"
            else:vf=base+f",zoompan=z='min(zoom+0.0008,1.06)':d={max(1,int(per*30))}:s={w}x{h}:fps=30,fade=t=in:st=0:d=0.25,fade=t=out:st={max(.1,per-.25):.2f}:d=0.25,format=yuv420p"
            cmd=[ffmpeg,'-y','-loop','1','-i',str(frame),'-t',f'{per:.3f}','-vf',vf,'-r','30','-an','-c:v','libx264','-pix_fmt','yuv420p',str(clip)]
            try:subprocess.run(cmd,check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=120);clips.append(clip)
            except Exception:clips=[];break
        if clips:
            concat=folder/'clips.txt';concat.write_text(''.join("file '"+x.name.replace("'","'\\''")+"'\n" for x in clips));base=folder/'base.mp4';cmd=[ffmpeg,'-y','-f','concat','-safe','0','-i',str(concat),'-c','copy',str(base)]
            try:
                subprocess.run(cmd,cwd=folder,check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=120)
                voice=None;music=None;duration=str(int(j['duration_seconds']))
                if j['voiceover_mode']=='ai' and j['voiceover_text']:
                    vp=folder/'voice.mp3';voice=vp if _generate_tts(j['voiceover_text'],vp,j['language']) and vp.exists() else None
                if music_id:
                    mr=m.one('SELECT relative_path FROM v8_music_assets WHERE id=?',(music_id,));music=ROOT/mr['relative_path'] if mr and (ROOT/mr['relative_path']).exists() else None
                cmd=[ffmpeg,'-y','-i',str(base)]
                if music:cmd+=['-stream_loop','-1','-i',str(music)]
                if voice:cmd+=['-i',str(voice)]
                if music and voice:
                    cmd+=['-filter_complex',f'[1:a]volume=0.16[bg];[2:a]volume=1.0,apad=pad_dur={duration}[vo];[bg][vo]amix=inputs=2:duration=longest:dropout_transition=2[a]','-map','0:v','-map','[a]','-t',duration,'-c:v','copy','-c:a','aac','-movflags','+faststart',str(out)]
                elif music:
                    cmd+=['-filter_complex','[1:a]volume=0.18[a]','-map','0:v','-map','[a]','-t',duration,'-c:v','copy','-c:a','aac','-movflags','+faststart',str(out)]
                elif voice:
                    cmd+=['-filter_complex',f'[1:a]apad=pad_dur={duration}[a]','-map','0:v','-map','[a]','-t',duration,'-c:v','copy','-c:a','aac','-movflags','+faststart',str(out)]
                else:cmd+=['-t',duration,'-c','copy','-movflags','+faststart',str(out)]
                subprocess.run(cmd,check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=120);renderer='FFmpeg placement-aware motion video'
            except Exception:pass
    rendered=out.exists()
    path=out if rendered else manifest_path
    aid=uid('V8A');rel=path.relative_to(ROOT).as_posix();media_store.persist(rel,public=True)
    notes=renderer+(' · AI-generated voice disclosure required.' if j['voiceover_mode']=='ai' else '')
    media_type='video' if rendered else 'storyboard'
    source_kind='Local motion compositor' if rendered else 'Storyboard manifest'
    asset_status='Approved' if rendered else 'Needs review'
    job_status='Generated' if rendered else 'Storyboard ready'
    if not rendered:notes+=' · No playable MP4 was produced; install/repair FFmpeg and retry to create publishable video.'
    with m.connect() as con:
        con.execute('INSERT INTO v8_creative_campaign_assets(id,campaign_id,product_id,placement_key,media_type,variation,relative_path,source_kind,status,version_no,notes) VALUES(?,?,?,?,?,?,?,?,?,?,?)',(aid,j['campaign_id'],j['product_id'],j['placement_key'],media_type,1,rel,source_kind,asset_status,1,notes))
        con.execute("UPDATE v8_video_jobs SET status=?,output_path=?,error=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",(job_status,rel,'' if rendered else 'Playable video not rendered; storyboard only.',job_id))
    return aid,renderer

def generate_veo_video(job_id: str) -> tuple[str,str]:
    j=m.one('SELECT * FROM v8_video_jobs WHERE id=?',(job_id,))
    if not j:raise ValueError('Video job not found.')
    key=video_secret()
    if not key:raise ValueError('Configure the Google/Gemini video provider in Settings → Advanced AI provider setup before using AI motion.')
    try:
        import operating_core as oc
        oc.guard_ai_call('video','Google')
    except ImportError:oc=None
    c=campaign(j['campaign_id']);p=ce.product(j['product_id']);model=setting('v8_veo_model','veo-3.1-generate-preview')
    refs=[]
    # Use up to three reference images as product assets; Veo 3.1 requires 8s with reference images.
    for row in ce.source_images(j['product_id'],3):
        path=ROOT/row['relative_path']
        if path.exists():
            small=pe.analysis_copy(path);mime=mimetypes.guess_type(small.name)[0] or 'image/jpeg';refs.append({'image':{'inlineData':{'mimeType':mime,'data':base64.b64encode(small.read_bytes()).decode()}},'referenceType':'asset'})
    if not refs:raise ValueError('No usable product references are available for AI video.')
    prompt=f'''Create an 8-second premium fashion advertising shot featuring the exact same product shown in the reference images. Product: {p['public_product_name']}. Style: {j['style']}. Campaign: {c['campaign_type']}. Target market: {c['target_market']}. Preserve the garment's colour, motifs, embroidery/print placement, border, pallu, blouse cues and fabric appearance. Do not invent or redesign textile details. Keep the product visible and unobscured. Use subtle realistic motion, elegant camera movement and commercial lighting. No on-screen text, logo or price; those are composed later. Adult models only if people are shown.'''
    payload={'instances':[{'prompt':prompt,'referenceImages':refs}],'parameters':{'aspectRatio':j['aspect_ratio'],'durationSeconds':'8','resolution':'720p','personGeneration':'allow_adult','numberOfVideos':1}}
    import ai_router
    state=ai_router.provider_preflight('video_generation','Google',model,credential_present=bool(key),object_type='video_job',object_id=job_id)
    if not state['ready']:
        raise ValueError(state.get('owner_message') or state.get('detail') or 'AI video provider is not configured.')
    base='https://generativelanguage.googleapis.com/v1beta';url=f'{base}/models/{model}:predictLongRunning'
    start,provider_attempts,provider_duration_ms=ai_router.request_provider_json('video_generation','Google',model,url,headers={'x-goog-api-key':key,'Content-Type':'application/json'},payload=payload,timeout=120,object_type='video_job',object_id=job_id,max_attempts=3)
    op=start.get('name')
    if not op:raise ValueError('AI video provider did not return an operation ID.')
    with m.connect() as con:con.execute("UPDATE v8_video_jobs SET status='Running',operation_name=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",(op,job_id))
    deadline=time.time()+900;status={}
    while time.time()<deadline:
        try:
            status,_,_=ai_router.request_provider_json('video_generation','Google',model,f'{base}/{op}',method='GET',headers={'x-goog-api-key':key},payload=None,timeout=60,object_type='video_job',object_id=job_id,max_attempts=2)
        except ValueError:
            time.sleep(10);continue
        if status.get('done'):break
        time.sleep(10)
    if not status.get('done'):
        with m.connect() as con:con.execute("UPDATE v8_video_jobs SET status='Failed',error='Timed out waiting for provider',updated_at=CURRENT_TIMESTAMP WHERE id=?",(job_id,))
        if oc:
            try:ai_router.record_failure('video_generation','Google',model,error='Timed out waiting for provider',object_type='video_job',object_id=job_id)
            except Exception:pass
        raise ValueError('AI video generation is still taking too long. The job was kept for diagnosis.')
    uri=(((status.get('response') or {}).get('generateVideoResponse') or {}).get('generatedSamples') or [{}])[0].get('video',{}).get('uri')
    if not uri:raise ValueError('AI video generation completed without a downloadable video.')
    folder=VIDEO_ROOT/j['campaign_id']/j['product_id']/job_id;folder.mkdir(parents=True,exist_ok=True);clip=folder/'veo_clip.mp4'
    raw,_,_=ai_router.request_provider_bytes('video_generation','Google',model,uri,method='GET',headers={'x-goog-api-key':key},payload=None,timeout=180,object_type='video_job',object_id=job_id,max_attempts=3)
    clip.write_bytes(raw)
    # Veo reference-image generation returns an 8s clip. Longer requested durations
    # require a successful local extension; never label an 8s fallback as a completed
    # 15/20/30s deliverable.
    final=clip;requested_duration=int(j['duration_seconds']);duration_complete=(requested_duration==8)
    if requested_duration!=8 and shutil.which('ffmpeg'):
        local_id,_=render_local_video(job_id)
        lr=m.one('SELECT relative_path FROM v8_creative_campaign_assets WHERE id=?',(local_id,));local=ROOT/lr['relative_path'] if lr else None
        if local and local.suffix=='.mp4' and local.exists():
            out=folder/'ai_plus_product_edit.mp4';ffmpeg=shutil.which('ffmpeg');concat=folder/'mix.txt';concat.write_text(f"file '{clip.name}'\nfile '{local.name}'\n")
            try:
                subprocess.run([ffmpeg,'-y','-f','concat','-safe','0','-i',str(concat),'-t',str(requested_duration),'-c:v','libx264','-c:a','aac','-pix_fmt','yuv420p',str(out)],cwd=folder,check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=180)
                if out.exists():final=out;duration_complete=True
            except Exception:
                duration_complete=False
    aid=uid('V8A');rel=final.relative_to(ROOT).as_posix();media_store.persist(rel,public=True)
    duration_note='Reference-image AI motion. Review garment fidelity frame-by-frame before publishing.'
    if not duration_complete:duration_note+=f' Provider produced 8s but {requested_duration}s was requested; local extension is incomplete. Retry after the local video renderer is available.'
    with m.connect() as con:
        con.execute('INSERT INTO v8_creative_campaign_assets(id,campaign_id,product_id,placement_key,media_type,variation,relative_path,source_kind,status,version_no,notes) VALUES(?,?,?,?,?,?,?,?,?,?,?)',(aid,j['campaign_id'],j['product_id'],j['placement_key'],'video',1,rel,'Google Veo 3.1 AI motion','Needs review',1,duration_note))
        con.execute("UPDATE v8_video_jobs SET status=?,output_path=?,error=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",('Generated' if duration_complete else 'Partial',rel,'' if duration_complete else f'Only 8s generated; {requested_duration}s requested.',job_id))
    if oc:
        try:
            ai_router.record_success('video_generation','Google',model,object_type='video_job',object_id=job_id,video_seconds=8.0,duration_ms=provider_duration_ms,attempts=provider_attempts)
            oc._save_quality('creative_asset',aid,'video_fidelity',50,['Generative fashion video requires frame-by-frame owner review before publishing because textile details can drift between frames.'],{'provider':'Google','model':model,'product_id':j['product_id'],'job_id':job_id})
        except Exception:pass
    return aid,'Google Veo 3.1 reference-image motion'


def process_video_job(job_id: str, music_id=''):
    j=m.one('SELECT * FROM v8_video_jobs WHERE id=?',(job_id,))
    if not j:raise ValueError('Video job not found.')
    return generate_veo_video(job_id) if j['provider']=='veo' else render_local_video(job_id,music_id)


def prepare_publish_handoffs(cid: str) -> int:
    c=campaign(cid);made=0
    brief=brief_readiness(cid)
    if brief['issues']:raise ValueError('Campaign is not ready for publishing handoff: '+'; '.join(brief['issues'][:4]))
    assets=[]
    for a in campaign_assets(cid):
        if a['status']!='Approved' or a['placement_key'].startswith('MASTER'):continue
        qc=placement_qc(a['id'])
        if qc['status']=='Passed':assets.append(a)
    with m.connect() as con:
        for a in assets:
            spec=placement_spec(cid,a['placement_key'])
            if not spec:continue
            platform=spec.get('platform') or 'Custom'
            caption='' if platform.startswith('Google') else ' · '.join(x for x in [c.get('promotional_message'),c.get('price_text'),c.get('offer_text'),c.get('cta')] if x)
            if con.execute('SELECT 1 FROM v8_publish_handoffs WHERE asset_id=? AND platform=?',(a['id'],platform)).fetchone():continue
            con.execute('INSERT INTO v8_publish_handoffs(id,campaign_id,asset_id,platform,status,caption) VALUES(?,?,?,?,?,?)',(uid('HANDOFF'),cid,a['id'],platform,'Prepared',caption[:1800]));made+=1
    refresh_creative_campaign_status(cid)
    if _automation_level()>=3:
        try:ensure_unified_campaign(cid)
        except ValueError:pass
    return made


def publish_handoffs(cid: str):
    return m.rows("SELECT h.*,a.product_id,a.placement_key,a.media_type,a.relative_path FROM v8_publish_handoffs h JOIN v8_creative_campaign_assets a ON a.id=h.asset_id WHERE h.campaign_id=? ORDER BY h.platform,a.product_id,a.placement_key",(cid,))


def update_campaign(cid: str, raw: dict) -> None:
    c=campaign(cid)
    allowed={
        'campaign_type':(raw.get('campaign_type') or c['campaign_type'])[:80],
        'target_market':(raw.get('target_market') or c['target_market'])[:120],
        'language':(raw.get('language') or c['language'])[:80],
        'visual_style':(raw.get('visual_style') or c['visual_style'])[:80],
        'background_style':(raw.get('background_style') or c['background_style'])[:100],
        'subject_mode':(raw.get('subject_mode') or c['subject_mode'])[:80],
        'model_style':(raw.get('model_style') or c['model_style'])[:120],
        'text_mode':(raw.get('text_mode') or c['text_mode'])[:40],
        'promotional_message':(raw.get('promotional_message') if raw.get('promotional_message') is not None else c['promotional_message'])[:300],
        'cta':(raw.get('cta') if raw.get('cta') is not None else c['cta'])[:100],
        'price_text':(raw.get('price_text') if raw.get('price_text') is not None else c['price_text'])[:100],
        'offer_text':(raw.get('offer_text') if raw.get('offer_text') is not None else c['offer_text'])[:140],
        'logo_mode':(raw.get('logo_mode') or c['logo_mode'])[:40],
    }
    with m.connect() as con:
        con.execute('''UPDATE v8_creative_campaigns SET campaign_type=?,target_market=?,language=?,visual_style=?,background_style=?,subject_mode=?,model_style=?,text_mode=?,promotional_message=?,cta=?,price_text=?,offer_text=?,logo_mode=?,updated_at=CURRENT_TIMESTAMP WHERE id=?''',tuple(allowed.values())+(cid,))


def update_asset_status(asset_id: str, status: str):
    if status not in {'Approved','Rejected','Needs review','QC passed'}:raise ValueError('Choose a valid asset review status.')
    a=m.one('SELECT * FROM v8_creative_campaign_assets WHERE id=?',(asset_id,))
    if not a:raise ValueError('Creative asset not found.')
    if status=='Approved' and not a['placement_key'].startswith('MASTER'):
        qc=placement_qc(asset_id)
        if qc['status']!='Passed':raise ValueError('This creative failed placement QC: '+'; '.join(qc['issues'][:4]))
    with m.connect() as con:con.execute('UPDATE v8_creative_campaign_assets SET status=?,updated_at=CURRENT_TIMESTAMP WHERE id=?',(status,asset_id))
    if status in {'Approved','Rejected'}:
        try:_auto_prepare_if_ready(a['campaign_id'])
        except ValueError:pass
    refresh_creative_campaign_status(a['campaign_id'])

def regenerate_asset(asset_id: str) -> str:
    a=m.one('SELECT * FROM v8_creative_campaign_assets WHERE id=?',(asset_id,))
    if not a:raise ValueError('Creative asset not found.')
    if a['media_type']!='image' or a['placement_key'].startswith('MASTER'):raise ValueError('This asset is not a placement image. Regenerate its video job or AI master instead.')
    spec=placement_spec(a['campaign_id'],a['placement_key'])
    if not spec:raise ValueError('This placement is no longer available.')
    return compose_image(a['campaign_id'],a['product_id'],a['placement_key'],a['variation'],force=False)


def export_campaign_zip(cid: str) -> bytes:
    c=campaign(cid);assets=[a for a in campaign_assets(cid) if a['status']!='Archived']
    buf=io.BytesIO()
    with zipfile.ZipFile(buf,'w',zipfile.ZIP_DEFLATED) as z:
        manifest={'campaign':c,'assets':[]}
        for a in assets:
            path=ROOT/a['relative_path']
            if path.exists():
                spec=placement_spec(cid,a['placement_key']);platform=re.sub(r'[^A-Za-z0-9._-]+','_',((spec or {}).get('platform') or 'Product_details')).strip('_') or 'Other'
                arc=f"{a['product_id']}/{platform}/{a['placement_key']}/v{a['version_no']}_{path.name}";z.write(path,arc);manifest['assets'].append({k:a[k] for k in ['id','product_id','placement_key','media_type','variation','status','source_kind','version_no']}|{'platform':(spec or {}).get('platform') or 'Product details','file':arc})
        z.writestr('manifest.json',json.dumps(manifest,ensure_ascii=False,indent=2))
    return buf.getvalue()


def placement_groups():
    groups={}
    for key,spec in IMAGE_PLACEMENTS.items():groups.setdefault(spec['platform'],[]).append((key,spec))
    for key,spec in VIDEO_PLACEMENTS.items():groups.setdefault(spec['platform'],[]).append((key,spec))
    return groups
