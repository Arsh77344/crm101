from __future__ import annotations
import runtime_config as rc

import base64
import datetime as dt
import hashlib
import html
import io
import json
import mimetypes
import os
import re
import secrets
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath

import marketing as m
import v5_features as v5
import media_store
import v35_truth as truth

ROOT = Path(__file__).resolve().parent
UPLOAD_ROOT = rc.STATIC_ROOT / 'uploads' / 'product_engine'
ASSET_ROOT = rc.STATIC_ROOT / 'generated' / 'product_assets'
INBOX_ROOT = rc.DATA_ROOT / 'product_inbox'
RECOVERY_ROOT = INBOX_ROOT / 'recovery'
IMAGE_EXTS = {'.jpg', '.jpeg', '.png', '.webp', '.avif', '.heic', '.heif', '.tif', '.tiff', '.bmp'}
CANONICAL_IMAGE_FORMATS = {'JPEG': '.jpg', 'PNG': '.png', 'WEBP': '.webp'}
CONVERTIBLE_IMAGE_FORMATS = {'AVIF', 'TIFF', 'BMP', 'HEIF', 'HEIC'}
MAX_ARCHIVE_BYTES = 180 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 500 * 1024 * 1024
MAX_FILES = 250

ROLE_PATTERNS = [
    ('Cover', r'\b(cover\s*photo|cover|hero|main)\b'),
    ('Overall', r'\b(overall|full\s*view|full)\b'),
    ('Pallu', r'\b(pallu|palloo|anchal)\b'),
    ('Blouse', r'\b(blouse|blouse\s*piece)\b'),
    ('Border / body', r'\b(border\s*body|body\s*border|border|body)\b'),
    ('Close-up', r'\b(close\s*up|closeup|detail|texture|zoom)\b'),
]
ROLE_TOKENS = re.compile(r'(?i)([-_ ](?:cover\s*photo|cover|hero|main|overall|full\s*view|full|pallu\s*border|pallu|palloo|anchal|blouse\s*piece|blouse|border\s*body|body\s*border|border|body|close\s*up|closeup|detail|texture|zoom))+$')

COLOURS = [
    'navy blue', 'royal blue', 'sky blue', 'powder blue', 'emerald green', 'bottle green', 'olive green',
    'mustard yellow', 'lemon yellow', 'wine colour', 'wine', 'maroon', 'burgundy', 'magenta', 'fuchsia',
    'purple', 'lavender', 'lilac', 'teal', 'turquoise', 'peach', 'coral', 'orange', 'rust', 'beige', 'cream',
    'ivory', 'off white', 'white', 'black', 'grey', 'gray', 'silver', 'gold', 'red', 'pink', 'green', 'blue', 'yellow', 'brown'
]
FABRICS = [
    'mashru satin silk', 'mashru silk', 'katan silk', 'organza silk', 'tussar silk', 'tissue silk',
    'georgette silk', 'crepe silk', 'raw silk', 'satin silk', 'silk', 'organza', 'georgette', 'cotton', 'linen'
]
MOTIFS = [
    'sona rupa buta', 'sona rupa', 'butidar', 'buti', 'buta', 'jangla', 'shikargah', 'tanchoi', 'jamdani',
    'meenakari', 'floral', 'paisley', 'geometric'
]
CATEGORY_WORDS = {
    'saree': 'Saree', 'sari': 'Saree', 'suit': 'Suit', 'salwar': 'Suit', 'kurta': 'Suit', 'dupatta': 'Dupatta',
    'fabric': 'Fabric', 'lehenga': 'Lehenga', 'stole': 'Stole', 'scarf': 'Scarf'
}

SCHEMA = '''
CREATE TABLE IF NOT EXISTS v6_product_intakes(
 id TEXT PRIMARY KEY, archive_name TEXT NOT NULL, source_label TEXT, requested_type TEXT,
 engine TEXT DEFAULT 'Local filename engine', status TEXT DEFAULT 'Processed',
 product_count INTEGER DEFAULT 0, image_count INTEGER DEFAULT 0, warning_count INTEGER DEFAULT 0,
 created_at TEXT DEFAULT CURRENT_TIMESTAMP, processed_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS v6_intake_products(
 intake_id TEXT NOT NULL, product_id TEXT NOT NULL, group_label TEXT, source_name TEXT,
 PRIMARY KEY(intake_id,product_id)
);
CREATE TABLE IF NOT EXISTS v6_product_fields(
 product_id TEXT NOT NULL, field_name TEXT NOT NULL, field_value TEXT,
 source_type TEXT NOT NULL, confidence REAL, verification_status TEXT DEFAULT 'Needs review',
 evidence TEXT, updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
 PRIMARY KEY(product_id,field_name,source_type)
);
CREATE TABLE IF NOT EXISTS v6_product_content(
 product_id TEXT PRIMARY KEY, suggested_name TEXT, short_description TEXT, b2c_description TEXT,
 b2b_description TEXT, seo_title TEXT, meta_description TEXT, slug TEXT,
 tags_json TEXT, collections_json TEXT, visual_details_json TEXT, warnings_json TEXT,
 engine TEXT DEFAULT 'Local', updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS v6_product_assets(
 id TEXT PRIMARY KEY, product_id TEXT NOT NULL, image_id TEXT, variant TEXT NOT NULL,
 relative_path TEXT NOT NULL, method TEXT, status TEXT DEFAULT 'Ready', created_at TEXT DEFAULT CURRENT_TIMESTAMP,
 UNIQUE(product_id,image_id,variant)
);
CREATE TABLE IF NOT EXISTS v6_engine_events(
 id TEXT PRIMARY KEY, product_id TEXT, intake_id TEXT, action TEXT, detail TEXT,
 created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS v18_3_intake_file_issues(
 id TEXT PRIMARY KEY, intake_id TEXT NOT NULL, filename TEXT NOT NULL, issue TEXT NOT NULL,
 created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS v40_intake_archive_fingerprints(
 fingerprint TEXT PRIMARY KEY,
 intake_id TEXT NOT NULL,
 created_at TEXT DEFAULT CURRENT_TIMESTAMP,
 last_seen_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS v40_product_source_fingerprints(
 fingerprint TEXT PRIMARY KEY,
 product_id TEXT NOT NULL,
 first_intake_id TEXT NOT NULL,
 created_at TEXT DEFAULT CURRENT_TIMESTAMP,
 last_seen_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS v40_intake_recovery(
 recovery_id TEXT PRIMARY KEY, intake_id TEXT, archive_name TEXT NOT NULL, relative_path TEXT NOT NULL,
 requested_type TEXT DEFAULT 'Auto', engine TEXT DEFAULT 'local', auto_assets INTEGER DEFAULT 1,
 status TEXT DEFAULT 'Staged', last_error TEXT DEFAULT '', created_at TEXT DEFAULT CURRENT_TIMESTAMP, updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS v40_intake_recovery_intake_idx ON v40_intake_recovery(intake_id);
CREATE INDEX IF NOT EXISTS v18_3_issue_intake_idx ON v18_3_intake_file_issues(intake_id);
CREATE INDEX IF NOT EXISTS v6_intake_product_idx ON v6_intake_products(product_id);
CREATE INDEX IF NOT EXISTS v6_field_product_idx ON v6_product_fields(product_id);
'''


def e(v):
    return html.escape('' if v is None else str(v), quote=True)


def uid(prefix):
    return prefix + '-' + secrets.token_hex(7).upper()


def initialise():
    with m.connect() as con:
        con.executescript(SCHEMA)
        con.execute("INSERT OR IGNORE INTO settings(setting_key,setting_value) VALUES('product_ignore_tokens','Usaya')")
        con.execute("INSERT OR IGNORE INTO settings(setting_key,setting_value) VALUES('default_product_type','Saree')")
        con.execute("INSERT OR IGNORE INTO settings(setting_key,setting_value) VALUES('product_auto_assets','1')")
        con.execute("INSERT OR IGNORE INTO settings(setting_key,setting_value) VALUES('product_asset_quality','balanced')")
    # Product intake now creates canonical inventory immediately. Ensure that
    # small dependency even when the intake engine is initialised standalone.
    import platform_core as _pc
    _pc._ensure_stock_location_schema()
    truth.initialise()
    INBOX_ROOT.mkdir(parents=True, exist_ok=True)
    (INBOX_ROOT/'processed').mkdir(exist_ok=True)
    (INBOX_ROOT/'failed').mkdir(exist_ok=True)
    RECOVERY_ROOT.mkdir(exist_ok=True)


def setting(key, default=''):
    r = m.one('SELECT setting_value FROM settings WHERE setting_key=?', (key,))
    return (r['setting_value'] if r else default) or default


def save_settings(raw):
    ignored = ','.join(x.strip() for x in (raw.get('product_ignore_tokens') or '').split(',') if x.strip())[:500]
    ptype = (raw.get('default_product_type') or 'Saree').strip()
    if ptype not in {'Saree', 'Suit', 'Dupatta', 'Fabric', 'Lehenga', 'Other'}:
        raise ValueError('Choose a supported default product type.')
    with m.connect() as con:
        con.execute("INSERT OR REPLACE INTO settings VALUES('product_ignore_tokens',?)", (ignored,))
        con.execute("INSERT OR REPLACE INTO settings VALUES('default_product_type',?)", (ptype,))
        con.execute("INSERT OR REPLACE INTO settings VALUES('product_auto_assets',?)", ('1' if raw.get('product_auto_assets') == '1' else '0',))
    event(None, None, 'engine.settings', 'Product intake defaults updated.')


def event(product_id, intake_id, action, detail=''):
    with m.connect() as con:
        con.execute('INSERT INTO v6_engine_events(id,product_id,intake_id,action,detail) VALUES(?,?,?,?,?)',
                    (uid('EVT'), product_id, intake_id, action, (detail or '')[:2000]))


def safe_member(name):
    p = PurePosixPath(name)
    if p.is_absolute() or '..' in p.parts:
        return False
    return not any(part.startswith('__MACOSX') for part in p.parts)


def clean_stem(value):
    s = Path(value).stem
    s = re.sub(r'^\s*\d+\.\s*', '', s)
    s = re.sub(r'-20\d{6}T\d{6}Z-\d+-\d+$', '', s)
    s = ROLE_TOKENS.sub('', s)
    s = re.sub(r'[_]+', ' ', s)
    s = re.sub(r'\s*-\s*', '-', s)
    s = re.sub(r'\s+', ' ', s).strip(' -_.')
    return s


def ignore_tokens():
    raw = setting('product_ignore_tokens', 'Usaya')
    return [x.strip() for x in raw.split(',') if x.strip()]


def strip_ignored_prefix(name):
    out = name.strip()
    for token in ignore_tokens():
        out = re.sub(r'^' + re.escape(token) + r'\s*[-_: ]+\s*', '', out, flags=re.I)
    return out.strip(' -_')


def image_role(filename):
    text = Path(filename).stem.replace('_', ' ').replace('-', ' ')
    for role, pat in ROLE_PATTERNS:
        if re.search(pat, text, re.I):
            return role
    return 'Other'


def detect_product_name(file_names, group_label=''):
    stems = [clean_stem(Path(x).name) for x in file_names]
    stems = [x for x in stems if x]
    candidate = ''
    if stems:
        # Most common cleaned stem is stable when role suffixes are present.
        counts = {}
        for s in stems:
            counts[s] = counts.get(s, 0) + 1
        candidate = max(counts, key=lambda k: (counts[k], len(k)))
    if not candidate:
        candidate = clean_stem(group_label)
    candidate = strip_ignored_prefix(candidate)
    return candidate or 'Untitled product'


def find_phrase(text, choices):
    low = (text or '').lower()
    for item in sorted(choices, key=len, reverse=True):
        if re.search(r'(?<!\w)' + re.escape(item.lower()) + r'(?!\w)', low):
            return item
    return ''


def title_case_phrase(v):
    return ' '.join(x if x.upper() in {'GI'} else x.capitalize() for x in (v or '').split())


def parse_filename_facts(name, requested_type='Auto'):
    raw = strip_ignored_prefix(clean_stem(name))
    low = raw.lower()
    colour = find_phrase(low, COLOURS)
    if colour == 'wine colour': colour = 'wine'
    fabric = find_phrase(low, FABRICS)
    motif = find_phrase(low, MOTIFS)
    category = ''
    if requested_type and requested_type != 'Auto':
        category = requested_type
    else:
        for token, label in CATEGORY_WORDS.items():
            if re.search(r'\b' + re.escape(token) + r'\b', low):
                category = label
                break
        if not category:
            category = setting('default_product_type', 'Saree')
    facts = {
        'source_product_name': raw,
        'colour': title_case_phrase(colour),
        'fabric': title_case_phrase(fabric),
        'weave_or_motif': title_case_phrase(motif),
        'category': category,
    }
    return facts


def safe_public_name(source_name, facts):
    name = source_name.strip()
    category = facts.get('category') or ''
    if category and category.lower() not in name.lower():
        name = f'{name} {category}'
    return re.sub(r'\s+', ' ', name).strip()[:180]


def local_content(public_name, facts):
    colour = facts.get('colour') or ''
    fabric = facts.get('fabric') or ''
    motif = facts.get('weave_or_motif') or ''
    category = facts.get('category') or 'Product'
    pieces = [x for x in [colour, motif, fabric, category] if x]
    short = ' / '.join(pieces)
    source_bits = []
    if colour: source_bits.append(colour.lower())
    if motif: source_bits.append(motif)
    if fabric: source_bits.append(fabric)
    source_sentence = ', '.join(source_bits)
    b2c = f'{public_name}. Draft product copy created from the supplied filename and imagery. {source_sentence}. Verify material, provenance, dimensions, care and availability before publishing.'
    b2b = f'{public_name}. Draft wholesale catalogue copy. Source-supplied details currently include {source_sentence or "the product label"}. Confirm composition, MOQ, stock, lead time and wholesale terms before sharing with buyers.'
    tags = []
    for x in [colour, fabric, motif, category, 'Premium' if re.search(r'\bpremium\b', public_name, re.I) else '']:
        if x and x.lower() not in {y.lower() for y in tags}: tags.append(x)
    collections = []
    if category: collections.append(category + 's' if not category.endswith('s') else category)
    if colour: collections.append(colour + ' Collection')
    if fabric: collections.append(fabric)
    seo_title = public_name[:60]
    meta = f'Explore {public_name}. Product details are prepared from source information and should be verified before publishing.'[:155]
    slug = v5.slugify(public_name)
    warnings = ['Fabric, provenance, purity, handloom status, GI status, dimensions and care are not verified by image appearance alone.']
    return {
        'suggested_name': public_name, 'short_description': short, 'b2c_description': b2c[:4000],
        'b2b_description': b2b[:4000], 'seo_title': seo_title, 'meta_description': meta, 'slug': slug,
        'tags': tags, 'collections': collections, 'visual_details': [], 'warnings': warnings,
    }


def upsert_field(product_id, field_name, value, source_type, confidence=None, status='Needs review', evidence=''):
    if value is None or str(value).strip() == '':
        return
    with m.connect() as con:
        con.execute('''INSERT INTO v6_product_fields(product_id,field_name,field_value,source_type,confidence,verification_status,evidence)
        VALUES(?,?,?,?,?,?,?) ON CONFLICT(product_id,field_name,source_type) DO UPDATE SET field_value=excluded.field_value,
        confidence=excluded.confidence,verification_status=excluded.verification_status,evidence=excluded.evidence,updated_at=CURRENT_TIMESTAMP''',
                    (product_id, field_name, str(value)[:2000], source_type, confidence, status, evidence[:1000]))


def bulk_set_category(product_ids: list[str], category: str) -> int:
    """Set one confirmed owner category across selected active products atomically.

    The compatibility products.category value and provenance-bearing V6 fact row are
    updated together so downstream product views and evidence-aware workflows agree.
    """
    initialise()
    ids=list(dict.fromkeys(str(x or '').strip() for x in (product_ids or []) if str(x or '').strip()))
    if not ids:
        raise ValueError('Select at least one product.')
    if len(ids)>100:
        raise ValueError('Select no more than 100 products at a time.')
    value=re.sub(r'\s+',' ',str(category or '').strip())[:120]
    if not value:
        raise ValueError('Choose or enter a category before applying the bulk change.')
    placeholders=','.join('?' for _ in ids)
    found=m.rows(f'SELECT product_id,status FROM products WHERE product_id IN ({placeholders})',tuple(ids))
    found_map={r['product_id']:r for r in found}
    missing=[x for x in ids if x not in found_map]
    if missing:
        raise ValueError('One or more selected products no longer exist. Refresh the page and try again.')
    archived=[x for x in ids if str(found_map[x].get('status') or '')=='Archived']
    if archived:
        raise ValueError('Archived products cannot be bulk-edited. Restore them first.')
    with m.connect() as con:
        for pid in ids:
            con.execute('UPDATE products SET category=? WHERE product_id=?',(value,pid))
            con.execute('''INSERT INTO v6_product_fields(product_id,field_name,field_value,source_type,confidence,verification_status,evidence)
                VALUES(?,?,?,?,?,?,?) ON CONFLICT(product_id,field_name,source_type) DO UPDATE SET
                field_value=excluded.field_value,confidence=excluded.confidence,verification_status=excluded.verification_status,
                evidence=excluded.evidence,updated_at=CURRENT_TIMESTAMP''',
                (pid,'category',value,'Owner bulk edit',1.0,'Confirmed','Owner applied category through bulk catalogue action'))
    for pid in ids:
        m.audit('product.category_bulk_updated',pid,'Category set by owner bulk action: '+value)
    return len(ids)


def save_content(product_id, data, engine='Local filename engine'):
    with m.connect() as con:
        con.execute('''INSERT INTO v6_product_content(product_id,suggested_name,short_description,b2c_description,b2b_description,seo_title,meta_description,slug,tags_json,collections_json,visual_details_json,warnings_json,engine)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(product_id) DO UPDATE SET suggested_name=excluded.suggested_name,short_description=excluded.short_description,
        b2c_description=excluded.b2c_description,b2b_description=excluded.b2b_description,seo_title=excluded.seo_title,meta_description=excluded.meta_description,
        slug=excluded.slug,tags_json=excluded.tags_json,collections_json=excluded.collections_json,visual_details_json=excluded.visual_details_json,
        warnings_json=excluded.warnings_json,engine=excluded.engine,updated_at=CURRENT_TIMESTAMP''',
                    (product_id, data.get('suggested_name','')[:240], data.get('short_description','')[:2000], data.get('b2c_description','')[:8000],
                     data.get('b2b_description','')[:8000], data.get('seo_title','')[:180], data.get('meta_description','')[:320],
                     v5.slugify(data.get('slug') or data.get('suggested_name','')), json.dumps(data.get('tags',[])), json.dumps(data.get('collections',[])),
                     json.dumps(data.get('visual_details',[])), json.dumps(data.get('warnings',[])), engine))


def file_hash(data):
    return hashlib.sha256(data).hexdigest()


def _safe_image_name(filename):
    return re.sub(r'[^A-Za-z0-9._-]+', '_', Path(filename).name).strip('._') or 'product-image'


def _convert_with_pillow(raw, filename, fmt):
    from PIL import Image, ImageOps
    with Image.open(io.BytesIO(raw)) as im:
        im = ImageOps.exif_transpose(im)
        # Product photography should become a stable RGB JPEG working copy.  The
        # untouched source bytes are stored separately whenever conversion occurs.
        if im.mode not in {'RGB', 'L'}:
            if 'A' in im.mode:
                base = Image.new('RGB', im.size, 'white')
                base.paste(im, mask=im.getchannel('A'))
                im = base
            else:
                im = im.convert('RGB')
        elif im.mode == 'L':
            im = im.convert('RGB')
        out = io.BytesIO()
        im.save(out, format='JPEG', quality=95, optimize=True)
        return out.getvalue(), '.jpg', f'{fmt} converted to JPEG for CRM/channel compatibility'


def _convert_with_macos_sips(raw, filename):
    """Best-effort HEIC/HEIF conversion using macOS' built-in image service."""
    if sys.platform != 'darwin' or not shutil.which('sips'):
        return None
    suffix = Path(filename).suffix.lower() or '.img'
    with tempfile.TemporaryDirectory(prefix='crm-image-') as td:
        src = Path(td) / ('source' + suffix)
        dst = Path(td) / 'working.jpg'
        src.write_bytes(raw)
        try:
            cp = subprocess.run(
                ['sips', '-s', 'format', 'jpeg', str(src), '--out', str(dst)],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=25, check=False,
            )
        except Exception:
            return None
        if cp.returncode != 0 or not dst.exists() or not dst.stat().st_size:
            return None
        return dst.read_bytes(), '.jpg', 'Apple image conversion created a JPEG working copy'


def normalise_product_image(filename, raw):
    """Validate a source photograph and return a safe working copy.

    The source bytes remain untouched.  JPEG/PNG/WebP are kept as-is when their
    extension matches the decoded format.  Common camera/editor formats are
    converted to JPEG for downstream compatibility.
    """
    name = Path(filename).name or 'unnamed image'
    if not raw:
        raise ValueError(f'{name}: the file is empty.')
    if len(raw) > 30 * 1024 * 1024:
        raise ValueError(f'{name}: file is larger than 30 MB.')
    ext = Path(name).suffix.lower()
    if ext not in IMAGE_EXTS:
        raise ValueError(f'{name}: unsupported file extension {ext or "(none)"}. Use JPG, PNG, WEBP, AVIF, HEIC/HEIF, TIFF or BMP.')
    try:
        from PIL import Image
        Image.MAX_IMAGE_PIXELS = 80_000_000
        with Image.open(io.BytesIO(raw)) as probe:
            fmt = (probe.format or '').upper()
            w, h = probe.size
            probe.verify()
    except Exception:
        converted = _convert_with_macos_sips(raw, name)
        if converted:
            work, work_ext, note = converted
            # Validate the converted output too.
            with __import__('PIL.Image', fromlist=['Image']).open(io.BytesIO(work)) as probe:
                w, h = probe.size
                if w < 16 or h < 16 or w * h > 80_000_000:
                    raise ValueError(f'{name}: image dimensions {w}×{h} are outside the safe product-image range.')
            return {'raw': work, 'ext': work_ext, 'format': 'JPEG', 'converted': True, 'note': note, 'width': w, 'height': h}
        raise ValueError(f'{name}: the image bytes cannot be decoded safely. Re-export it as JPG/PNG/WebP or upload the original HEIC/HEIF file.') from None
    if w < 16 or h < 16:
        raise ValueError(f'{name}: image is only {w}×{h}; use a product photo at least 16×16 pixels.')
    if w * h > 80_000_000:
        raise ValueError(f'{name}: image is {w}×{h} ({w*h:,} pixels), above the 80-megapixel safety limit. Export a smaller copy.')
    canonical_ext = CANONICAL_IMAGE_FORMATS.get(fmt)
    if canonical_ext:
        # If bytes and extension disagree, keep the source untouched separately and
        # save the correctly named working copy so browsers/Pillow never guess wrong.
        matching = ext in ({'.jpg', '.jpeg'} if fmt == 'JPEG' else {canonical_ext})
        return {'raw': raw, 'ext': canonical_ext, 'format': fmt, 'converted': not matching,
                'note': '' if matching else f'File extension did not match decoded {fmt}; working copy was renamed safely',
                'width': w, 'height': h}
    if fmt in CONVERTIBLE_IMAGE_FORMATS:
        try:
            work, work_ext, note = _convert_with_pillow(raw, name, fmt)
            return {'raw': work, 'ext': work_ext, 'format': fmt, 'converted': True, 'note': note, 'width': w, 'height': h}
        except Exception:
            converted = _convert_with_macos_sips(raw, name)
            if converted:
                work, work_ext, note = converted
                return {'raw': work, 'ext': work_ext, 'format': fmt, 'converted': True, 'note': note, 'width': w, 'height': h}
    raise ValueError(f'{name}: decoded image format {fmt or "unknown"} is not supported for product photography. Re-export as JPG, PNG or WebP.')


def write_image(product_id, intake_id, filename, raw, role, source_archive, is_primary=False, preflight=None):
    result = preflight or normalise_product_image(filename, raw)
    working_raw = result['raw']
    working_ext = result['ext']
    safe_source = _safe_image_name(filename)
    source_ext = Path(safe_source).suffix.lower()

    folder = UPLOAD_ROOT / product_id / 'originals'
    folder.mkdir(parents=True, exist_ok=True)
    # Preserve the exact user-supplied file whenever a working copy is changed or
    # renamed.  Downstream CRM code uses the normalized working copy.
    if result.get('converted'):
        source_folder = UPLOAD_ROOT / product_id / 'source_originals'
        source_folder.mkdir(parents=True, exist_ok=True)
        source_dest = source_folder / safe_source
        n = 1
        while source_dest.exists():
            source_dest = source_folder / (Path(safe_source).stem + f'_{n}' + (source_ext or '.bin')); n += 1
        source_dest.write_bytes(raw)
        try: media_store.persist(source_dest.relative_to(ROOT).as_posix(), public=False)
        except Exception: pass

    base = re.sub(r'[^A-Za-z0-9._-]+', '_', Path(safe_source).stem).strip('._') or 'image'
    base += working_ext
    dest = folder / base
    n = 1
    while dest.exists():
        dest = folder / (Path(base).stem + f'_{n}' + working_ext); n += 1
    dest.write_bytes(working_raw)
    rel = dest.relative_to(ROOT).as_posix()
    media_store.persist(rel,public=False)
    iid = uid('IMG')
    with m.connect() as con:
        con.execute('INSERT INTO product_images(image_id,product_id,image_role,original_filename,source_archive,relative_path,is_primary) VALUES(?,?,?,?,?,?,?)',
                    (iid, product_id, role, Path(filename).name, source_archive[:500], rel, int(is_primary)))
    if result.get('note'):
        event(product_id, intake_id, 'image.normalized', f'{Path(filename).name}: {result["note"]}')
    return iid, rel


def make_product_record(source_name, facts):
    with m.connect() as con:
        sku = v5.next_sku(con)
        pid = uid('PRD')
        public = safe_public_name(source_name, facts)
        tags = ', '.join(local_content(public, facts)['tags'])
        data = {
            'product_id': pid, 'internal_sku': sku, 'product_code': sku,
            'source_product_name': source_name[:180], 'public_product_name': public,
            'colour': facts.get('colour',''), 'weave_or_motif': facts.get('weave_or_motif',''), 'fabric': facts.get('fabric',''),
            'category': facts.get('category') or 'Saree', 'description': '', 'currency': m.settings().get('default_currency') or 'INR',
            'status': 'Draft', 'tags': tags,
        }
        cols = {r['name'] for r in con.execute('PRAGMA table_info(products)')}
        data = {k:v for k,v in data.items() if k in cols}
        con.execute('INSERT INTO products(' + ','.join(data) + ') VALUES(' + ','.join('?'*len(data)) + ')', tuple(data.values()))
    # A product is not operationally complete until it has canonical inventory,
    # even when its opening balance is zero.  Do not wait for a later migration
    # pass to create that business object.
    import v35_truth as truth
    truth.initialise()
    truth.canonical_inventory(pid,'MAIN')
    for fname in ['source_product_name','colour','fabric','weave_or_motif','category']:
        value = facts.get(fname)
        if value:
            upsert_field(pid, fname, value, 'Filename', 0.98 if fname != 'category' else 0.75, 'Source supplied', 'Extracted from source filename; not independently verified.')
    public = safe_public_name(source_name, facts)
    content = local_content(public, facts)
    save_content(pid, content)
    with m.connect() as con:
        con.execute('UPDATE products SET description=? WHERE product_id=?', (content['b2c_description'][:5000], pid))
    return pid


def groups_from_zip(zf):
    images = [i for i in zf.infolist() if not i.is_dir() and safe_member(i.filename) and Path(i.filename).suffix.lower() in IMAGE_EXTS]
    if not images:
        raise ValueError('No supported product photographs were found in this ZIP. Use JPG, PNG, WEBP, AVIF, HEIC/HEIF, TIFF or BMP.')
    if len(images) > MAX_FILES:
        raise ValueError(f'This ZIP contains more than {MAX_FILES} product images. Split it into smaller uploads.')
    total = sum(i.file_size for i in images)
    if total > MAX_UNCOMPRESSED_BYTES:
        raise ValueError('The uncompressed images are too large for one intake. Split the upload into smaller product ZIPs.')
    groups = {}
    for info in images:
        path = PurePosixPath(info.filename)
        parent = path.parent.as_posix()
        # The nearest folder is the product group. This supports batch ZIPs such as Batch/Product A/*.jpg.
        key = parent if parent not in {'', '.'} else clean_stem(info.filename)
        groups.setdefault(key, []).append(info)
    # Root files are grouped by their cleaned filename stem after removing view-role suffixes.
    if all(PurePosixPath(i.filename).parent.as_posix() in {'', '.'} for i in images):
        groups = {}
        for info in images:
            key = clean_stem(info.filename)
            groups.setdefault(key, []).append(info)
    return groups


def ingest_archive(raw, filename, requested_type='Auto', engine='local', auto_assets=True, recovery_id=''):
    initialise()
    if len(raw) > MAX_ARCHIVE_BYTES:
        raise ValueError('Keep each product ZIP under 180 MB. Split large photography folders into separate product ZIPs.')
    if Path(filename).suffix.lower() != '.zip':
        raise ValueError('Upload a ZIP containing the raw product images and filenames.')
    try:
        zf = zipfile.ZipFile(io.BytesIO(raw))
        bad = zf.testzip()
        if bad: raise ValueError('The ZIP appears damaged. Re-create it and upload again.')
    except zipfile.BadZipFile:
        raise ValueError('That file is not a readable ZIP archive.') from None
    groups = groups_from_zip(zf)
    archive_fingerprint = hashlib.sha256(raw).hexdigest()
    # Preflight every file before creating any intake/product record.  V18.3 could
    # create partial records and then abort when the final image failed validation.
    # V18.3 validates first, processes valid photographs, and records file-level
    # issues without silently discarding them.
    preflight = {}
    issues = []
    for infos in groups.values():
        for info in infos:
            if info.filename in preflight or any(x['filename'] == info.filename for x in issues):
                continue
            try:
                if info.file_size > 30 * 1024 * 1024:
                    raise ValueError(f'{Path(info.filename).name}: file is larger than 30 MB.')
                source_bytes = zf.read(info)
                preflight[info.filename] = (source_bytes, normalise_product_image(info.filename, source_bytes))
            except ValueError as exc:
                issues.append({'filename': info.filename, 'issue': str(exc)})
    valid_groups = {}
    for group_label, infos in groups.items():
        good = [i for i in infos if i.filename in preflight]
        if good:
            valid_groups[group_label] = good
    if not preflight:
        detail = '; '.join(f"{Path(x['filename']).name}: {x['issue'].split(':',1)[-1].strip()}" for x in issues[:8])
        more = f' (+{len(issues)-8} more)' if len(issues) > 8 else ''
        raise ValueError('None of the selected product photographs could be processed. ' + detail + more)

    intake_id = uid('INTAKE')
    product_ids = []
    warnings = len(issues)
    with m.connect() as con:
        con.execute('INSERT INTO v6_product_intakes(id,archive_name,source_label,requested_type,engine,status,product_count,image_count,warning_count) VALUES(?,?,?,?,?,?,?,?,?)',
                    (intake_id, Path(filename).name[:500], clean_stem(filename)[:300], requested_type, 'AI image + filename' if engine == 'ai' else 'Local filename engine', 'Processing', 0, 0, 0))
        if recovery_id:
            con.execute('UPDATE v40_intake_recovery SET intake_id=?,updated_at=CURRENT_TIMESTAMP WHERE recovery_id=?',(intake_id,recovery_id))
        for issue in issues:
            con.execute('INSERT INTO v18_3_intake_file_issues(id,intake_id,filename,issue) VALUES(?,?,?,?)',
                        (uid('ISSUE'), intake_id, issue['filename'][:500], issue['issue'][:2000]))
    for issue in issues:
        event(None, intake_id, 'image.rejected', f"{issue['filename']}: {issue['issue']}")

    reused=0
    for group_label, infos in valid_groups.items():
        names = [i.filename for i in infos]
        source_name = detect_product_name(names, group_label)
        facts = parse_filename_facts(source_name, requested_type)
        # Product identity for intake retry/re-upload is based on the source
        # photograph bytes, not a generated title.  Renaming the ZIP or files
        # therefore cannot create another canonical product from the exact same
        # photography set.
        source_hashes=sorted(hashlib.sha256(preflight[i.filename][0]).hexdigest() for i in infos)
        source_fingerprint=hashlib.sha256('|'.join(source_hashes).encode()).hexdigest()
        prior=m.one('SELECT product_id FROM v40_product_source_fingerprints WHERE fingerprint=?',(source_fingerprint,))
        pid=(prior or {}).get('product_id','')
        if pid and not m.one('SELECT product_id FROM products WHERE product_id=?',(pid,)):
            pid=''
        reused_this=bool(pid)
        if reused_this:
            reused+=1
            with m.connect() as con:
                con.execute('UPDATE v40_product_source_fingerprints SET last_seen_at=CURRENT_TIMESTAMP WHERE fingerprint=?',(source_fingerprint,))
            event(pid,intake_id,'product.reused','The same source photographs were already linked to this product; no duplicate product or image records were created.')
        else:
            pid = make_product_record(source_name, facts)
            with m.connect() as con:
                con.execute('''INSERT INTO v40_product_source_fingerprints(fingerprint,product_id,first_intake_id)
                               VALUES(?,?,?) ON CONFLICT(fingerprint) DO UPDATE SET product_id=excluded.product_id,last_seen_at=CURRENT_TIMESTAMP''',
                            (source_fingerprint,pid,intake_id))
        # A ZIP can contain the exact same photograph set in more than one
        # folder/group. Source identity is canonical, so associate that product
        # with this intake only once instead of violating the intake/product key
        # or manufacturing a duplicate product.
        if pid in product_ids:
            warnings += 1
            event(pid, intake_id, 'product.source_duplicate',
                  'Another group in this intake contained the same source photographs; the existing product was reused once.')
            continue
        product_ids.append(pid)
        with m.connect() as con:
            con.execute('INSERT INTO v6_intake_products(intake_id,product_id,group_label,source_name) VALUES(?,?,?,?)',
                        (intake_id, pid, str(group_label)[:500], source_name[:500]))
        if reused_this:
            # This intake is an idempotent retry/re-upload.  Existing source
            # images/assets remain canonical; do not add duplicate media rows.
            continue
        ordered = sorted(infos, key=lambda i: (0 if image_role(i.filename) == 'Cover' else 1, i.filename.lower()))
        first = True
        for info in ordered:
            source_bytes, checked = preflight[info.filename]
            role = image_role(info.filename)
            write_image(pid, intake_id, info.filename, source_bytes, role, Path(filename).name, first or role == 'Cover', preflight=checked)
            first = False
        refresh_duplicate_groups(pid)
        if auto_assets:
            try: prepare_assets(pid)
            except Exception as ex:
                warnings += 1
                event(pid, intake_id, 'assets.warning', str(ex))
        if engine == 'ai':
            try: ai_analyse_product(pid)
            except ValueError as ex:
                warnings += 1
                event(pid, intake_id, 'ai.warning', str(ex))
        event(pid, intake_id, 'product.created', f'Created from {Path(filename).name}; source naming remains traceability metadata.')
        try:
            import creative_engine as ce
            if ce.setting('creative_auto_queue','1')=='1': ce.queue_default_pack(pid,'product intake')
        except Exception as ex:
            event(pid,intake_id,'creative.queue_warning',str(ex))
    with m.connect() as con:
        con.execute('UPDATE v6_product_intakes SET status=?,product_count=?,image_count=?,warning_count=?,processed_at=CURRENT_TIMESTAMP WHERE id=?',
                    ('Processed with warnings' if warnings else 'Processed', len(product_ids), len(preflight), warnings, intake_id))
        con.execute('''INSERT INTO v40_intake_archive_fingerprints(fingerprint,intake_id) VALUES(?,?)
                       ON CONFLICT(fingerprint) DO UPDATE SET intake_id=excluded.intake_id,last_seen_at=CURRENT_TIMESTAMP''',(archive_fingerprint,intake_id))
    created_count=max(0,len(product_ids)-reused)
    event(None, intake_id, 'intake.completed', f'{created_count} product(s) created and {reused} existing product(s) reused from {len(valid_groups)} valid image group(s); {len(issues)} file issue(s) recorded.')
    try:
        import business_os as bos
        for pid in product_ids:
            eid=bos.emit('product.uploaded','product',pid,{'intake_id':intake_id},'product.uploaded:'+pid)
            bos.enqueue('product.readiness','product',pid,{'intake_id':intake_id},eid)
    except Exception as ex:
        event(None,intake_id,'business_os.warning',str(ex))
    try:
        import operating_core as oc
        for pid in product_ids:
            oc.assign_entity('product',pid)
            oc.emit_event('PRODUCT_CREATED','product',pid,{'intake_id':intake_id,'source':'product_engine'},'v13-product-created:'+pid)
    except Exception as ex:
        event(None,intake_id,'v13.event_warning',str(ex))
    return intake_id, product_ids


def stage_recoverable_archive(raw: bytes, filename: str, requested_type='Auto', engine='local', auto_assets=True) -> str:
    """Persist an owner upload privately before processing so interruption is retryable."""
    initialise()
    if len(raw) > MAX_ARCHIVE_BYTES: raise ValueError('Keep each product ZIP under 180 MB. Split large photography folders into separate product ZIPs.')
    if Path(filename).suffix.lower() != '.zip': raise ValueError('Upload a ZIP containing the raw product images and filenames.')
    rid=uid('REC')
    dest=RECOVERY_ROOT/(rid+'.zip')
    tmp=dest.with_suffix('.tmp')
    tmp.write_bytes(raw);os.replace(tmp,dest)
    rel=str(dest.relative_to(ROOT))
    with m.connect() as con:
        con.execute("""INSERT INTO v40_intake_recovery(recovery_id,archive_name,relative_path,requested_type,engine,auto_assets)
                       VALUES(?,?,?,?,?,?)""",(rid,Path(filename).name[:500],rel,requested_type,engine,1 if auto_assets else 0))
    return rid


def _recovery_path(row):
    try:
        path=(ROOT/str(row.get('relative_path') or '')).resolve()
        root=RECOVERY_ROOT.resolve()
        if root not in path.parents:return None
        return path
    except Exception:return None


def process_recoverable_archive(recovery_id: str):
    """Process a staged archive; retain it only when recovery may be needed."""
    initialise();row=m.one('SELECT * FROM v40_intake_recovery WHERE recovery_id=?',(recovery_id,))
    if not row:raise ValueError('The saved product upload could not be found. Upload the photographs again.')
    path=_recovery_path(row)
    if not path or not path.exists():raise ValueError('The saved product upload is no longer available. Upload the photographs again.')
    try:
        result=ingest_archive(path.read_bytes(),row['archive_name'],row.get('requested_type') or 'Auto',row.get('engine') or 'local',bool(row.get('auto_assets')),recovery_id=recovery_id)
    except Exception as exc:
        current=m.one('SELECT intake_id FROM v40_intake_recovery WHERE recovery_id=?',(recovery_id,)) or {}
        iid=current.get('intake_id') or uid('INTAKE')
        with m.connect() as con:
            if not current.get('intake_id'):
                con.execute("""INSERT INTO v6_product_intakes(id,archive_name,source_label,requested_type,engine,status,product_count,image_count,warning_count)
                               VALUES(?,?,?,?,?,'Failed',0,0,1)""",(iid,row['archive_name'],clean_stem(row['archive_name'])[:300],row.get('requested_type') or 'Auto','AI image + filename' if row.get('engine')=='ai' else 'Local filename engine'))
            else:
                con.execute("UPDATE v6_product_intakes SET status='Failed',warning_count=CASE WHEN warning_count<1 THEN 1 ELSE warning_count END,processed_at=CURRENT_TIMESTAMP WHERE id=?",(iid,))
            con.execute("UPDATE v40_intake_recovery SET intake_id=?,status='Failed',last_error=?,updated_at=CURRENT_TIMESTAMP WHERE recovery_id=?",(iid,str(exc)[:2000],recovery_id))
        event(None,iid,'intake.failed','The product upload was preserved locally for safe retry: '+str(exc))
        raise
    iid,_=result
    with m.connect() as con:con.execute("UPDATE v40_intake_recovery SET intake_id=?,status='Completed',last_error='',updated_at=CURRENT_TIMESTAMP WHERE recovery_id=?",(iid,recovery_id))
    try:path.unlink(missing_ok=True)
    except Exception:pass
    return result


def retry_failed_intake(intake_id: str):
    initialise();row=m.one("SELECT * FROM v40_intake_recovery WHERE intake_id=? AND status='Failed' ORDER BY updated_at DESC LIMIT 1",(intake_id,))
    if not row:raise ValueError('The original upload is not available for automatic retry. Upload the source photographs again.')
    path=_recovery_path(row)
    if not path or not path.exists():raise ValueError('The original upload is not available for automatic retry. Upload the source photographs again.')
    rid=stage_recoverable_archive(path.read_bytes(),row['archive_name'],row.get('requested_type') or 'Auto',row.get('engine') or 'local',bool(row.get('auto_assets')))
    with m.connect() as con:con.execute("UPDATE v40_intake_recovery SET status='Retried',updated_at=CURRENT_TIMESTAMP WHERE recovery_id=?",(row['recovery_id'],))
    return process_recoverable_archive(rid)


def recovery_available(intake_id: str) -> bool:
    row=m.one("SELECT * FROM v40_intake_recovery WHERE intake_id=? AND status='Failed' ORDER BY updated_at DESC LIMIT 1",(intake_id,))
    path=_recovery_path(row or {})
    return bool(path and path.exists())


def normalized_product_key(p):
    text = ' '.join([p.get('public_product_name') or '', p.get('colour') or '', p.get('fabric') or '', p.get('weave_or_motif') or '']).lower()
    text = re.sub(r'\b(premium|saree|sari|suit|product)\b', ' ', text)
    return re.sub(r'[^a-z0-9]+', ' ', text).strip()


def refresh_duplicate_groups(product_id=None):
    """Recompute duplicate candidates from the active catalogue only.

    The earlier incremental implementation cleared only the product being edited,
    which could leave stale duplicate badges on its former matches. Archived
    products could also keep active products flagged even though they are excluded
    from selling/marketing workflows. A full active-catalogue recompute is cheap at
    the expected product scale and makes the duplicate state deterministic.
    ``product_id`` is retained for backward-compatible callers.
    """
    products = m.rows("SELECT product_id,public_product_name,colour,fabric,weave_or_motif FROM products WHERE coalesce(status,'Draft')<>'Archived'")
    buckets = {}
    for p in products:
        key = normalized_product_key(p)
        if key: buckets.setdefault(key, []).append(p['product_id'])
    with m.connect() as con:
        con.execute('UPDATE products SET duplicate_group=NULL')
        for key, ids in buckets.items():
            if len(ids) > 1:
                gid = 'DUP-' + hashlib.sha1(key.encode()).hexdigest()[:8].upper()
                con.executemany('UPDATE products SET duplicate_group=? WHERE product_id=?', [(gid, x) for x in ids])


def _resize_with_pillow(src, dest, max_width, quality=86):
    from PIL import Image, ImageOps
    dest.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(src) as im:
        im = ImageOps.exif_transpose(im)
        if im.width > max_width:
            h = max(1, int(im.height * (max_width / im.width)))
            im = im.resize((max_width, h), Image.Resampling.LANCZOS)
        if im.mode not in {'RGB','L'}: im = im.convert('RGB')
        if dest.suffix.lower() in {'.jpg','.jpeg'}:
            if im.mode != 'RGB': im = im.convert('RGB')
            im.save(dest, 'JPEG', quality=quality, optimize=True)
        elif dest.suffix.lower() == '.webp':
            im.save(dest, 'WEBP', quality=quality, method=6)
        else:
            im.save(dest)
    return 'Pillow'


def _resize_with_sips(src, dest, max_width):
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)
    subprocess.run(['sips', '-Z', str(max_width), str(dest)], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return 'macOS sips'


def resize_image(src, dest, max_width):
    try:
        return _resize_with_pillow(src, dest, max_width)
    except Exception:
        if sys.platform == 'darwin' and shutil.which('sips'):
            return _resize_with_sips(src, dest, max_width)
        raise ValueError('Image resizing needs Pillow or the built-in macOS sips utility. Originals were kept unchanged.')


def prepare_assets(product_id):
    import record_lifecycle as lifecycle
    lifecycle.require_operationally_active_product(product_id)
    imgs = m.rows('SELECT * FROM product_images WHERE product_id=? ORDER BY is_primary DESC,image_role', (product_id,))
    if not imgs: raise ValueError('No product images are available to prepare.')
    made = 0
    for image in imgs:
        src = ROOT / image['relative_path']
        if not src.exists(): continue
        # Prepare lightweight web derivatives for every view; channel cards only need the primary/cover image.
        variants = [('web_large', 1800), ('web_thumbnail', 480)]
        if image.get('is_primary'):
            variants += [('email', 900), ('whatsapp', 1200), ('social_source', 1400)]
        for variant, width in variants:
            # JPEG keeps generated assets compact and much faster to prepare than repeated large PNG derivatives.
            ext = '.jpg'
            dest = ASSET_ROOT / product_id / variant / (Path(image['original_filename']).stem[:80] + ext)
            existing = m.one('SELECT id FROM v6_product_assets WHERE product_id=? AND image_id=? AND variant=?', (product_id,image['image_id'],variant))
            if existing and dest.exists(): continue
            method = resize_image(src, dest, width)
            rel = dest.relative_to(ROOT).as_posix()
            media_store.persist(rel,public=True)
            with m.connect() as con:
                con.execute('''INSERT INTO v6_product_assets(id,product_id,image_id,variant,relative_path,method,status)
                VALUES(?,?,?,?,?,?,?) ON CONFLICT(product_id,image_id,variant) DO UPDATE SET relative_path=excluded.relative_path,method=excluded.method,status=excluded.status''',
                            (uid('ASSET'),product_id,image['image_id'],variant,rel,method,'Ready'))
            made += 1
    event(product_id, None, 'assets.prepared', f'{made} channel derivatives prepared. Originals unchanged.')
    return made


def analysis_copy(path):
    cache = ROOT / '.cache' / 'product_engine_ai'
    cache.mkdir(parents=True, exist_ok=True)
    dest = cache / (hashlib.sha1(str(path).encode()).hexdigest() + '.jpg')
    if not dest.exists():
        try:
            _resize_with_pillow(path, dest, 1400, 82)
        except Exception:
            if sys.platform == 'darwin' and shutil.which('sips'):
                temp = cache / (dest.stem + path.suffix.lower())
                _resize_with_sips(path, temp, 1400)
                if temp.suffix.lower() in {'.jpg','.jpeg'}: shutil.copy2(temp,dest)
                else: return temp
            else:
                if path.stat().st_size > 5*1024*1024: raise ValueError('One image is too large for AI analysis without an image-resize utility.')
                return path
    return dest


def data_url(path):
    mime = mimetypes.guess_type(path.name)[0] or 'image/jpeg'
    return f'data:{mime};base64,' + base64.b64encode(path.read_bytes()).decode('ascii')


def ai_analyse_product(product_id):
    key = m.secret()
    if not key:
        raise ValueError('AI is not connected. Add your API key in Settings & AI, then analyse this product explicitly.')
    import record_lifecycle as lifecycle
    product = lifecycle.require_operationally_active_product(product_id)
    images = m.rows("SELECT * FROM product_images WHERE product_id=? ORDER BY CASE image_role WHEN 'Cover' THEN 0 WHEN 'Overall' THEN 1 WHEN 'Close-up' THEN 2 WHEN 'Border / body' THEN 3 WHEN 'Pallu' THEN 4 WHEN 'Blouse' THEN 5 ELSE 9 END,is_primary DESC LIMIT 6", (product_id,))
    if not images: raise ValueError('Add product images before asking AI to analyse the product.')
    content = [{'type':'input_text','text':json.dumps({
        'source_product_name': product.get('source_product_name'),
        'current_draft': {k:product.get(k) for k in ['public_product_name','colour','fabric','weave_or_motif','category']},
        'image_filenames': [x['original_filename'] for x in images],
        'instruction': 'Source filenames are traceability metadata and any prefix such as Usaya is not the business brand.'
    }, ensure_ascii=False)}]
    for im in images:
        src = ROOT / im['relative_path']
        if src.exists():
            small = analysis_copy(src)
            content.append({'type':'input_image','image_url':data_url(small),'detail':'auto'})
    schema = {
        'type':'object','properties':{
            'suggested_name':{'type':'string'},'category':{'type':'string'},'colour':{'type':'string'},'fabric':{'type':'string'},'weave_or_motif':{'type':'string'},
            'short_description':{'type':'string'},'b2c_description':{'type':'string'},'b2b_description':{'type':'string'},'seo_title':{'type':'string'},'meta_description':{'type':'string'},'slug':{'type':'string'},
            'tags':{'type':'array','items':{'type':'string'}},'collections':{'type':'array','items':{'type':'string'}},'visual_details':{'type':'array','items':{'type':'string'}},'warnings':{'type':'array','items':{'type':'string'}},
            'confidence':{'type':'object','properties':{'category':{'type':'number'},'colour':{'type':'number'},'fabric':{'type':'number'},'weave_or_motif':{'type':'number'}},'required':['category','colour','fabric','weave_or_motif'],'additionalProperties':False}
        },
        'required':['suggested_name','category','colour','fabric','weave_or_motif','short_description','b2c_description','b2b_description','seo_title','meta_description','slug','tags','collections','visual_details','warnings','confidence'],
        'additionalProperties':False
    }
    system = '''You are a product-intake assistant for a Banarasi saree and suit manufacturer. Use the supplied filenames plus visual evidence to prepare a conservative product draft for human review. Source filenames are product metadata, not the business brand. Never infer or assert silk purity, handloom status, GI certification, real gold/silver zari, geographic provenance, dimensions, care instructions, stock, price, delivery, manufacturing method or authenticity from appearance alone. A filename may explicitly supply a material or motif label, but that remains source-supplied rather than verified. Keep uncertain fields empty instead of guessing. Visual details may describe visible colour, border, motif placement or overall appearance. Marketing copy must avoid unverified claims and must remain a draft. Return only the requested schema.'''
    import ai_router
    ai_state=ai_router.preflight('product_understanding',object_type='product',object_id=product_id,default_model=m.routed_model('product_understanding','gpt-6-sol'))
    model=ai_state['model']
    try:
        import operating_core as oc
        oc.guard_ai_call('general')
    except ImportError:
        oc=None
    body = {'model':model,'store':False,'max_output_tokens':4500,
            'input':[{'role':'system','content':system},{'role':'user','content':content}],
            'text':{'format':{'type':'json_schema','name':'product_intake','strict':True,'schema':schema}}}
    try:
        out,ai_attempts,ai_duration_ms=ai_router.request_json('product_understanding',body,timeout=120,object_type='product',object_id=product_id,max_attempts=3)
    except ValueError as ex:
        # request_json/pre-flight may already have persisted a more specific provider
        # state (quota, authentication, rate limit, outage). Do not overwrite it with
        # a generic status from the product workflow.
        if m.ai_health().get('status') in {'Connected','Untested'}:
            m.set_ai_health('Needs attention',str(ex)[:1000],model)
        raise
    if out.get('status') != 'completed':
        m.set_ai_health('Needs attention','The latest product-analysis request did not complete. Existing product data was preserved.',model)
        raise ValueError('AI product analysis did not complete. Existing product data was not replaced.')
    try: data = json.loads(v5.response_text(out))
    except Exception: raise ValueError('AI returned an unusable product response. Existing product data was not replaced.') from None
    save_content(product_id, data, 'OpenAI image + filename analysis')
    for field in ['category','colour','fabric','weave_or_motif']:
        value = data.get(field,'').strip()
        if value:
            upsert_field(product_id, field, value, 'AI inferred', float(data.get('confidence',{}).get(field,0.5)), 'Needs review', 'AI image + filename analysis; not independent verification.')
    # Improve safe descriptive metadata, but never overwrite commercial values or fact-review status.
    with m.connect() as con:
        current = con.execute('SELECT public_product_name,description,tags FROM products WHERE product_id=?',(product_id,)).fetchone()
        con.execute('UPDATE products SET description=?,tags=? WHERE product_id=?',
                    (data.get('b2c_description','')[:5000] or current['description'], ', '.join(data.get('tags',[]))[:1000] or current['tags'], product_id))
    try:
        usage=out.get('usage') or {}
        if oc:ai_router.record_success('product_understanding','OpenAI',model,object_type='product',object_id=product_id,input_units=usage.get('input_tokens',0),output_units=usage.get('output_tokens',0),provider_request_id=str(out.get('id') or ''),attempts=ai_attempts,duration_ms=ai_duration_ms)
    except Exception:pass
    m.set_ai_health('Connected','Latest product analysis completed successfully.',model)
    event(product_id, None, 'ai.product_analysis', 'AI created reviewable product suggestions. No verification status was changed.')
    try:
        if oc:oc.assess_product_copy(product_id)
    except Exception:pass
    return data


def fields(product_id):
    return m.rows('SELECT * FROM v6_product_fields WHERE product_id=? ORDER BY field_name,source_type', (product_id,))


def content(product_id):
    return m.one('SELECT * FROM v6_product_content WHERE product_id=?', (product_id,)) or {}


def readiness(product_id):
    p = m.one('''SELECT p.*,coalesce(r.confirmed,0) confirmed,r.evidence FROM products p LEFT JOIN m4_product_review r USING(product_id) WHERE p.product_id=?''',(product_id,))
    if not p: raise ValueError('Product not found.')
    imgs = m.one('SELECT count(*) n FROM product_images WHERE product_id=?',(product_id,))['n']
    assets = m.one('SELECT count(*) n FROM v6_product_assets WHERE product_id=?',(product_id,))['n']
    c = content(product_id)
    blockers=[]; warnings=[]
    catalogue = 0
    if p['public_product_name']: catalogue += 20
    if p['category']: catalogue += 15
    if p['colour']: catalogue += 10
    if imgs >= 3: catalogue += 25
    elif imgs: catalogue += 10
    if c.get('seo_title') and c.get('meta_description'): catalogue += 15
    if c.get('b2c_description'): catalogue += 15
    if not p['public_product_name']: blockers.append('Product name is missing')
    if imgs == 0: blockers.append('No product images')
    if not p['category']: blockers.append('Product type/category is missing')
    sales = 20 if p['confirmed'] else 0
    if p['retail_price'] is not None: sales += 25
    else: warnings.append('Retail price not recorded')
    if p['wholesale_price'] is not None: sales += 20
    else: warnings.append('Wholesale price not recorded')
    import v35_truth as truth
    available_stock=truth.product_available(product_id)
    if available_stock>0: sales += 20
    else: warnings.append('No available canonical stock')
    if p['currency']: sales += 5
    if p['moq'] is not None: sales += 10
    else: warnings.append('B2B MOQ not recorded')
    marketing = 20 if p['confirmed'] else 0
    if c.get('b2c_description'): marketing += 20
    if c.get('b2b_description'): marketing += 20
    if c.get('seo_title'): marketing += 15
    if assets >= max(1,imgs)*3: marketing += 15
    elif assets: marketing += 8
    if p['tags']: marketing += 10
    if not p['confirmed']: blockers.append('Product facts have not been owner/supplier verified')
    if p['duplicate_group']: warnings.append('Possible duplicate product needs review')
    return {'catalogue':min(100,catalogue),'sales':min(100,sales),'marketing':min(100,marketing),'blockers':blockers,'warnings':warnings,'images':imgs,'assets':assets,'confirmed':bool(p['confirmed'])}


def approve_filename_facts(product_id, evidence):
    evidence = (evidence or '').strip()
    if not evidence: raise ValueError('Add a verification note, such as owner check or supplier specification, before confirming product facts.')
    f = fields(product_id)
    with m.connect() as con:
        con.execute("UPDATE v6_product_fields SET verification_status='Verified',evidence=?,updated_at=CURRENT_TIMESTAMP WHERE product_id=? AND source_type='Filename'", (evidence[:1000],product_id))
        con.execute('''INSERT INTO m4_product_review(product_id,confirmed,evidence) VALUES(?,?,?)
        ON CONFLICT(product_id) DO UPDATE SET confirmed=excluded.confirmed,evidence=excluded.evidence,updated_at=CURRENT_TIMESTAMP''',(product_id,1,evidence[:1000]))
    event(product_id,None,'product.verified','Owner/supplier verification recorded for current product facts.')



def inbox_pending():
    initialise()
    return sorted([p for p in INBOX_ROOT.glob('*.zip') if p.is_file()])


def _unique_move_target(folder, name):
    folder.mkdir(parents=True, exist_ok=True)
    dest=folder/name
    n=1
    while dest.exists():
        dest=folder/(Path(name).stem+f'_{n}'+Path(name).suffix);n+=1
    return dest


def process_inbox_once(limit=20):
    """Process ZIPs dropped into product_inbox using safe local automation; no paid AI calls."""
    initialise(); results=[]
    for src in inbox_pending()[:limit]:
        processing=src.with_suffix(src.suffix+'.processing')
        try:
            os.replace(src,processing)
            iid,pids=ingest_archive(processing.read_bytes(),src.name,'Auto','local',setting('product_auto_assets','1')=='1')
            dest=_unique_move_target(INBOX_ROOT/'processed',src.name);os.replace(processing,dest)
            event(None,iid,'inbox.processed',f'{src.name}: {len(pids)} product(s) created automatically from the watched inbox.')
            results.append({'file':src.name,'status':'Processed','products':len(pids),'intake_id':iid})
        except Exception as ex:
            try:
                if processing.exists():
                    dest=_unique_move_target(INBOX_ROOT/'failed',src.name);os.replace(processing,dest)
            except Exception: pass
            event(None,None,'inbox.failed',f'{src.name}: {ex}')
            results.append({'file':src.name,'status':'Failed','error':str(ex)})
    return results


def watch_inbox_loop(stop_event, interval=60):
    """Daemon loop for local filename processing only. AI is never called from this background watcher."""
    while not stop_event.is_set():
        try: process_inbox_once()
        except Exception: pass
        stop_event.wait(interval)


def open_inbox_folder():
    initialise()
    if sys.platform!='darwin' or not shutil.which('open'):
        raise ValueError('Open the product_inbox folder manually in this V7 folder on this computer.')
    subprocess.Popen(['open',str(INBOX_ROOT)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)

def reconcile_stale_intakes(max_age_minutes: int=60) -> int:
    """Close interrupted local intake records instead of leaving them 'Processing' forever.

    Product intake is synchronous in the local workspace. A Processing row older than
    the threshold therefore means the browser/server was interrupted before completion.
    No product/image records are deleted; the owner is told to upload the source again.
    """
    initialise()
    try:
        cutoff=(dt.datetime.now(dt.timezone.utc)-dt.timedelta(minutes=max(15,int(max_age_minutes)))).replace(tzinfo=None).strftime('%Y-%m-%d %H:%M:%S')
    except Exception:
        cutoff=(dt.datetime.utcnow()-dt.timedelta(hours=1)).strftime('%Y-%m-%d %H:%M:%S')
    rows=m.rows("SELECT id,product_count,image_count FROM v6_product_intakes WHERE status='Processing' AND created_at<?",(cutoff,))
    if rows:
        with m.connect() as con:
            for r in rows:
                con.execute("UPDATE v6_product_intakes SET status='Failed',warning_count=CASE WHEN warning_count<1 THEN 1 ELSE warning_count END,processed_at=CURRENT_TIMESTAMP WHERE id=?",(r['id'],))
    for r in rows:
        event(None,r['id'],'intake.interrupted','The local intake was interrupted before completion. Existing created records were preserved; retry the saved upload where available.')
    staged=m.rows("SELECT * FROM v40_intake_recovery WHERE status='Staged' AND created_at<?",(cutoff,)) if m.one("SELECT 1 ok FROM sqlite_master WHERE type='table' AND name='v40_intake_recovery'") else []
    for rec in staged:
        iid=rec.get('intake_id') or uid('INTAKE')
        with m.connect() as con:
            if not rec.get('intake_id'):
                con.execute("""INSERT INTO v6_product_intakes(id,archive_name,source_label,requested_type,engine,status,product_count,image_count,warning_count)
                               VALUES(?,?,?,?,?,'Failed',0,0,1)""",(iid,rec['archive_name'],clean_stem(rec['archive_name'])[:300],rec.get('requested_type') or 'Auto','AI image + filename' if rec.get('engine')=='ai' else 'Local filename engine'))
            else:
                con.execute("UPDATE v6_product_intakes SET status='Failed',warning_count=CASE WHEN warning_count<1 THEN 1 ELSE warning_count END,processed_at=CURRENT_TIMESTAMP WHERE id=?",(iid,))
            con.execute("UPDATE v40_intake_recovery SET intake_id=?,status='Failed',last_error='Processing was interrupted by a server/browser restart.',updated_at=CURRENT_TIMESTAMP WHERE recovery_id=?",(iid,rec['recovery_id']))
        event(None,iid,'intake.interrupted','The saved product upload was interrupted and can be retried without selecting the files again.')
    return len(rows)+len(staged)


def dismiss_failed_intake(intake_id: str) -> None:
    initialise();row=m.one('SELECT status FROM v6_product_intakes WHERE id=?',(intake_id,))
    if not row:raise ValueError('Product intake not found.')
    if row.get('status') not in {'Failed','Dismissed'}:raise ValueError('Only an interrupted/failed intake can be dismissed.')
    if row.get('status')!='Dismissed':
        with m.connect() as con:con.execute("UPDATE v6_product_intakes SET status='Dismissed',processed_at=CURRENT_TIMESTAMP WHERE id=?",(intake_id,))
        event(None,intake_id,'intake.dismissed','Owner acknowledged the interrupted intake. Existing product/image records remain unchanged.')


def get_intakes():
    reconcile_stale_intakes()
    return m.rows('SELECT * FROM v6_product_intakes ORDER BY created_at DESC LIMIT 100')


def intake(intake_id):
    r = m.one('SELECT * FROM v6_product_intakes WHERE id=?',(intake_id,))
    if not r: raise ValueError('Product intake not found.')
    ps = m.rows('''SELECT p.*,ip.group_label,ip.source_name,(SELECT relative_path FROM product_images i WHERE i.product_id=p.product_id ORDER BY is_primary DESC LIMIT 1) img
    FROM v6_intake_products ip JOIN products p USING(product_id) WHERE ip.intake_id=? ORDER BY p.created_at''',(intake_id,))
    return r, ps


def product_intake(product_id):
    return m.one('SELECT ip.*,i.archive_name,i.engine,i.created_at intake_created FROM v6_intake_products ip JOIN v6_product_intakes i ON i.id=ip.intake_id WHERE ip.product_id=? ORDER BY i.created_at DESC LIMIT 1',(product_id,))
