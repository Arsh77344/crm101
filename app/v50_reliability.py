from __future__ import annotations

"""V50 reconstruction reliability layer.

Re-applies the missing V48 recovery/financial-truth contracts on top of the last
complete source tree (V47).  The module is intentionally additive so a real V48/V49
workspace can be imported without destructive rewrites.
"""

import datetime as dt
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import uuid
import zipfile
from pathlib import Path
from typing import Any

import db_layer
import marketing as m
import v35_truth as truth
import runtime_config as rc

SCHEMA = r'''
CREATE TABLE IF NOT EXISTS v50_campaign_requests(
  request_key TEXT PRIMARY KEY,
  campaign_id TEXT NOT NULL,
  flow TEXT NOT NULL DEFAULT '',
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS v50_campaign_requests_campaign ON v50_campaign_requests(campaign_id);
'''

METRIC_DICTIONARY = {
    'recorded_orders': 'Orders recorded in the period regardless of commercial state. This is workload, not revenue.',
    'recognized_orders': 'Orders in Paid/Fulfilled state, plus Refunded orders only when canonical refund evidence exists.',
    'gross_order_value': 'Order total before canonical refunds, only for recognized orders.',
    'refunds': 'Provider cumulative refund amount when available, otherwise completed local refund records; never both for the same order.',
    'net_revenue': 'Recognized gross order value less canonical refunds.',
    'cogs': 'Immutable sale-time line cost snapshots less cost reversed only for physically restocked return quantities.',
    'gross_profit': 'Net revenue less canonical COGS. Currencies remain separate; no implicit FX conversion is performed.',
}


def initialise() -> None:
    with m.connect() as con:
        con.executescript(SCHEMA)


def request_key(value: str | None = None) -> str:
    raw = str(value or '').strip()
    if raw:
        if len(raw) > 160:
            raise ValueError('The request identity is invalid. Refresh and try again.')
        return raw
    return 'REQ-' + uuid.uuid4().hex


def existing_campaign_for_request(key: str) -> str:
    initialise()
    row = m.one('SELECT campaign_id FROM v50_campaign_requests WHERE request_key=?', (key,))
    return str((row or {}).get('campaign_id') or '')


def remember_campaign_request(con, key: str, campaign_id: str, flow: str) -> None:
    con.execute(
        'INSERT INTO v50_campaign_requests(request_key,campaign_id,flow) VALUES(?,?,?)',
        (key, campaign_id, str(flow or '')[:80]),
    )


def _refund_evidence(order_id: str) -> dict[str, Any]:
    provider = 0.0
    provider_currency = ''
    if m.table_exists('v40_external_order_meta'):
        row = m.one('SELECT provider_refund_total,provider_refund_currency FROM v40_external_order_meta WHERE order_id=?', (order_id,)) or {}
        try:
            provider = max(0.0, float(row.get('provider_refund_total') or 0))
        except (TypeError, ValueError):
            provider = 0.0
        provider_currency = str(row.get('provider_refund_currency') or '')
    local = 0.0
    if m.table_exists('v17_return_cases'):
        row = m.one("SELECT coalesce(sum(refund_amount),0) v FROM v17_return_cases WHERE order_id=? AND status='Completed'", (order_id,)) or {'v': 0}
        try:
            local = max(0.0, float(row.get('v') or 0))
        except (TypeError, ValueError):
            local = 0.0
    # Provider cumulative refund truth wins when present to avoid double counting.
    amount = provider if provider > 0 else local
    return {'amount': amount, 'provider_amount': provider, 'local_amount': local, 'provider_currency': provider_currency, 'complete': amount > 0}


def recognized_order_financials(order_id: str) -> dict[str, Any]:
    truth.initialise()
    order = m.one('SELECT * FROM orders WHERE order_id=?', (order_id,))
    if not order:
        raise ValueError('Order not found.')
    status = str(order.get('order_status') or 'Draft')
    base = {
        'order_id': order_id,
        'status': status,
        'currency': str(order.get('currency') or ''),
        'recorded': True,
        'recognized': False,
        'incomplete': False,
        'reason': '',
        'gross_order_value': 0.0,
        'refunds': 0.0,
        'net_revenue': 0.0,
        'cogs': 0.0,
        'gross_profit': 0.0,
        'cost_complete': True,
        'missing_cost_products': [],
    }
    if status not in {'Paid', 'Fulfilled', 'Refunded'}:
        base['reason'] = f'{status} orders are recorded workload, not recognized revenue.'
        return base
    refund = _refund_evidence(order_id)
    if status == 'Refunded' and not refund['complete']:
        base['incomplete'] = True
        base['cost_complete'] = False
        base['reason'] = 'Order is marked Refunded but no completed local refund or provider-confirmed refund amount exists.'
        return base
    calc = truth.order_profitability(order_id)
    # For Refunded status, order_profitability already prefers provider cumulative refund truth.
    base.update({
        'recognized': True,
        'gross_order_value': float(calc.get('revenue') or 0),
        'refunds': float(calc.get('refunds') or 0),
        'net_revenue': float(calc.get('net_revenue') or 0),
        'cogs': float(calc.get('cogs') or 0),
        'gross_profit': float(calc.get('gross_profit') or 0),
        'cost_complete': bool(calc.get('cost_complete')),
        'missing_cost_products': list(calc.get('missing_cost_products') or []),
        'reason': 'Recognized from canonical paid/fulfilled/refund evidence.',
    })
    return base


def financial_summary(start_date: str = '', end_date: str = '') -> dict[str, Any]:
    truth.initialise()
    clauses = ['1=1']
    args: list[Any] = []
    if start_date:
        clauses.append('date(coalesce(ordered_at,created_at))>=date(?)')
        args.append(start_date)
    if end_date:
        clauses.append('date(coalesce(ordered_at,created_at))<=date(?)')
        args.append(end_date)
    # Some historical orders do not have created_at; ordered_at is the supported canonical date.
    sql = 'SELECT order_id FROM orders WHERE ' + ' AND '.join(x.replace('created_at','ordered_at') for x in clauses) + ' ORDER BY ordered_at,order_id'
    order_ids = [r['order_id'] for r in m.rows(sql, tuple(args))] if m.table_exists('orders') else []
    by_currency: dict[str, dict[str, Any]] = {}
    incomplete: list[dict[str, Any]] = []
    recognized = 0
    for oid in order_ids:
        row = recognized_order_financials(oid)
        curr = row.get('currency') or 'Unspecified'
        b = by_currency.setdefault(curr, {'currency': curr, 'recognized_orders': 0, 'gross_order_value': 0.0, 'refunds': 0.0, 'net_revenue': 0.0, 'cogs': 0.0, 'gross_profit': 0.0, 'cost_complete': True, 'missing_cost_products': []})
        if row['incomplete']:
            incomplete.append(row)
        if not row['recognized']:
            continue
        recognized += 1
        b['recognized_orders'] += 1
        for k in ('gross_order_value', 'refunds', 'net_revenue', 'cogs', 'gross_profit'):
            b[k] += float(row.get(k) or 0)
        b['cost_complete'] = bool(b['cost_complete'] and row.get('cost_complete'))
        for pid in row.get('missing_cost_products') or []:
            if pid not in b['missing_cost_products']:
                b['missing_cost_products'].append(pid)
    return {
        'recorded_orders': len(order_ids),
        'recognized_orders': recognized,
        'currency_breakdown': sorted(by_currency.values(), key=lambda x: x['currency']),
        'incomplete_orders': incomplete,
        'metric_dictionary': dict(METRIC_DICTIONARY),
    }


def archive_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def _setting(key: str) -> str:
    row = m.one('SELECT setting_value FROM settings WHERE setting_key=?', (key,)) or {}
    return str(row.get('setting_value') or '')


def _save_settings(values: dict[str, str]) -> None:
    with m.connect() as con:
        for key, value in values.items():
            con.execute('INSERT INTO settings(setting_key,setting_value) VALUES(?,?) ON CONFLICT(setting_key) DO UPDATE SET setting_value=excluded.setting_value', (key, value))


def latest_full_backup(root: Path) -> Path | None:
    folder = rc.BACKUP_DIR if rc.TEAM_TEST_MODE else Path(root) / 'backups'
    if not folder.exists():
        return None
    patterns = ['team_full_*.zip','v50_full_*.zip','v9_full_*.zip'] if rc.TEAM_TEST_MODE else ['v50_full_*.zip','v9_full_*.zip']
    files=[]
    for pattern in patterns:
        files = sorted(folder.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
        if files: break
    return files[0] if files else None


def create_local_full_backup(root: Path) -> Path:
    if db_layer.USING_POSTGRES:
        raise ValueError('Local SQLite full-backup helper cannot validate PostgreSQL. Use the production backup/restore workflow.')
    initialise()
    root = Path(root).resolve()
    folder = rc.BACKUP_DIR if rc.TEAM_TEST_MODE else root / 'backups'
    folder.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now(dt.timezone.utc).strftime('%Y%m%d_%H%M%S_%f')
    final = folder / (f'team_full_{stamp}.zip' if rc.TEAM_TEST_MODE else f'v50_full_{stamp}.zip')
    tmp_zip = folder / f'.v50_backup_{uuid.uuid4().hex}.zip.tmp'
    tmp_db = folder / f'.v50_backup_{uuid.uuid4().hex}.sqlite.tmp'
    try:
        with m.connect() as src, sqlite3.connect(tmp_db) as dst:
            src.backup(dst)
        os.chmod(tmp_db, 0o600)
        with sqlite3.connect(tmp_db) as con:
            con.row_factory = sqlite3.Row
            quick = con.execute('PRAGMA quick_check').fetchone()[0]
            counts = {}
            for table in ('contacts', 'products', 'orders', 'order_items', 'campaigns', 'v10_unified_campaigns'):
                try:
                    counts[table] = int(con.execute(f'SELECT count(*) FROM {table}').fetchone()[0])
                except sqlite3.Error:
                    counts[table] = None
        static = rc.STATIC_ROOT if rc.TEAM_TEST_MODE else root / 'static'
        media_files = [p for p in static.rglob('*') if p.is_file()] if static.is_dir() else []
        manifest = {
            'created_at_utc': stamp,
            'release': (__import__('release_info').BUILD_ID if rc.TEAM_TEST_MODE else 'V50'),
            'database': 'sqlite',
            'db_quick_check': quick,
            'counts': counts,
            'media_count': len(media_files),
            'includes': ['database', 'static media', 'backup manifest'],
            'excludes': ['API keys', 'provider secrets', 'environment secrets'],
        }
        with zipfile.ZipFile(tmp_zip, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as z:
            z.write(tmp_db, 'commerce_crm.sqlite')
            for path in media_files:
                z.write(path, 'static/' + path.relative_to(static).as_posix())
            z.writestr('backup_manifest.json', json.dumps(manifest, indent=2))
            bad = z.testzip()
            if bad:
                raise ValueError('Backup ZIP verification failed while writing ' + bad)
        os.replace(tmp_zip, final)
        os.chmod(final, 0o600)
        # A new archive invalidates evidence bound to the older digest.
        _save_settings({'last_restore_verified_sha256': '', 'last_restore_verified_at': '', 'last_restore_verified_archive': '', 'last_restore_verified_detail': 'Latest backup has not been restore-tested yet.'})
        return final
    finally:
        tmp_db.unlink(missing_ok=True)
        tmp_zip.unlink(missing_ok=True)


def _safe_zip_members(z: zipfile.ZipFile) -> None:
    for info in z.infolist():
        name = info.filename.replace('\\', '/')
        if name.startswith('/') or '..' in Path(name).parts:
            raise ValueError('Backup contains an unsafe archive path.')


def verify_backup_restore(root: Path, archive: Path | None = None) -> dict[str, Any]:
    """Restore-test the exact local SQLite archive in isolation.

    This never points application globals at the live workspace and never writes the
    disposable smoke record into the owner's database.
    """
    if db_layer.USING_POSTGRES:
        raise ValueError('PostgreSQL recovery must be verified in the deployed recovery environment; the local SQLite verifier cannot certify it.')
    root = Path(root).resolve()
    archive = Path(archive) if archive else latest_full_backup(root)
    if not archive or not archive.is_file():
        raise ValueError('Create a full backup before running a restore verification.')
    digest = archive_sha256(archive)
    with tempfile.TemporaryDirectory(prefix='v50-restore-drill-') as td:
        td = Path(td)
        with zipfile.ZipFile(archive) as z:
            _safe_zip_members(z)
            if z.testzip():
                raise ValueError('The backup ZIP is corrupt.')
            names = set(z.namelist())
            if 'commerce_crm.sqlite' not in names or 'backup_manifest.json' not in names:
                raise ValueError('Backup is missing its database or manifest.')
            z.extractall(td)
        manifest = json.loads((td / 'backup_manifest.json').read_text())
        db = td / 'commerce_crm.sqlite'
        with sqlite3.connect(db) as con:
            con.row_factory = sqlite3.Row
            if con.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
                raise ValueError('Restored SQLite database failed integrity check.')
            fk = con.execute('PRAGMA foreign_key_check').fetchall()
            if fk:
                raise ValueError('Restored database contains foreign-key violations.')
            required = {'contacts', 'products', 'orders', 'settings'}
            existing = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            missing = required - existing
            if missing:
                raise ValueError('Restored database is missing required tables: ' + ', '.join(sorted(missing)))
            for table, expected in (manifest.get('counts') or {}).items():
                if expected is None or table not in existing:
                    continue
                actual = int(con.execute(f'SELECT count(*) FROM {table}').fetchone()[0])
                if actual != int(expected):
                    raise ValueError(f'Restored count mismatch for {table}: expected {expected}, found {actual}.')
            # Business smoke write/update inside the isolated database only.
            smoke = 'V50-RESTORE-SMOKE-' + uuid.uuid4().hex[:8]
            con.execute("CREATE TABLE IF NOT EXISTS v50_restore_smoke(id TEXT PRIMARY KEY, note TEXT)")
            con.execute('INSERT INTO v50_restore_smoke(id,note) VALUES(?,?)', (smoke, 'created'))
            con.execute('UPDATE v50_restore_smoke SET note=? WHERE id=?', ('updated', smoke))
            if con.execute('SELECT note FROM v50_restore_smoke WHERE id=?', (smoke,)).fetchone()[0] != 'updated':
                raise ValueError('Restored database failed the disposable write/update smoke test.')
            con.rollback()
        media = [p for p in (td / 'static').rglob('*') if p.is_file()] if (td / 'static').exists() else []
        expected_media = int(manifest.get('media_count') or 0)
        if len(media) != expected_media:
            raise ValueError(f'Restored media count mismatch: expected {expected_media}, found {len(media)}.')
        # Start the core application/domain layer in a separate process against the
        # restored copy. This proves the archive is more than a readable SQLite file
        # while keeping all migrations/smoke work away from the owner's live DB.
        env=dict(os.environ)
        env['CRM_DB_PATH']=str(db)
        env['CRM_SKIP_VENV']='1'
        env.pop('DATABASE_URL',None)
        smoke_code=(
            "import marketing as m, integration_layer as il, process_orchestrator as po, v35_truth as truth; "
            "m.initialise(); il.initialise(); po.initialise(); truth.initialise(); "
            "assert m.one('SELECT count(*) n FROM settings') is not None; print('V50_RESTORE_APP_OK')"
        )
        app_root=Path(__file__).resolve().parent
        proc=subprocess.run([sys.executable,'-c',smoke_code],cwd=str(app_root),env=env,capture_output=True,text=True,timeout=60)
        if proc.returncode!=0 or 'V50_RESTORE_APP_OK' not in proc.stdout:
            raise ValueError('Restored workspace could not initialize the application core: '+(proc.stderr or proc.stdout or 'unknown startup error')[:1000])
    now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')
    detail = f'Verified isolated restore of {archive.name}; SQLite integrity, relationships, manifest counts, media, disposable write/update and core application initialization passed.'
    _save_settings({
        'last_restore_verified_sha256': digest,
        'last_restore_verified_at': now,
        'last_restore_verified_archive': archive.name,
        'last_restore_verified_detail': detail,
    })
    return {'ok': True, 'archive': archive.name, 'sha256': digest, 'verified_at': now, 'detail': detail}


def backup_readiness(root: Path) -> dict[str, Any]:
    latest = latest_full_backup(Path(root))
    if not latest:
        return {'status': 'NOT_CREATED', 'display_status':'First backup required', 'detail': 'Create and verify your first backup to complete recovery setup.', 'latest': ''}
    digest = archive_sha256(latest)
    verified = _setting('last_restore_verified_sha256')
    if not verified or verified != digest:
        return {'status': 'CREATED_NOT_VERIFIED', 'display_status':'Backup created — verification required', 'detail': f'Latest backup {latest.name} exists but this exact archive has not passed a restore drill.', 'latest': str(latest)}
    return {'status': 'VERIFIED', 'display_status':'Backup recovery verified', 'detail': _setting('last_restore_verified_detail') or f'Latest backup {latest.name} passed restore verification.', 'latest': str(latest), 'verified_at': _setting('last_restore_verified_at')}
