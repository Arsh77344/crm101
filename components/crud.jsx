'use client';
import { useState } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import { useQuery, insertRow, updateRow, removeRow, formValues } from '@/lib/db';
import Sheet from './Sheet';
import { useSession, canManage } from '@/lib/session';
import { Page, Badge, Empty, Loading, ErrorNote, Stat, money, when } from './ui';

function cell(row, col) {
  const raw = col.key.split('.').reduce((o, k) => (o ? o[k] : undefined), row);
  if (col.render) return col.render(row);
  if (col.fmt === 'money') return money(raw, row.currency);
  if (col.fmt === 'date') return when(raw);
  if (col.fmt === 'datetime') return when(raw, true);
  if (col.fmt === 'badge') return <Badge>{raw}</Badge>;
  return raw === null || raw === undefined || raw === '' ? <span className="faint">—</span> : String(raw);
}

export default function Crud({ cfg }) {
  const router = useRouter();
  const sp = useSearchParams();
  const { profile } = useSession();
  const manager = canManage(profile?.role);
  const id = sp.get('id');
  const filterValue = sp.get('f') || '';
  const [q, setQ] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');
  const [sheetOpen, setSheetOpen] = useState(false);

  const main = useQuery(async (c) => {
    let query = c.from(cfg.table).select(cfg.select || '*');
    if (cfg.order) query = query.order(cfg.order[0], { ascending: cfg.order[1] ?? false });
    if (cfg.filter && filterValue) query = query.eq(cfg.filter.col, filterValue);
    const { data, error } = await query.limit(500);
    if (error) throw error;
    return data || [];
  }, [filterValue]);

  const lookupDefs = (cfg.fields || []).filter((f) => f.lookup);
  const lookups = useQuery(async (c) => {
    const out = {};
    for (const f of lookupDefs) {
      const { data } = await c.from(f.lookup.table).select(`${f.lookup.pk},${f.lookup.label}`).order(f.lookup.label);
      out[f.name] = data || [];
    }
    return out;
  }, [lookupDefs.length]);

  const all = main.data || [];
  const term = q.trim().toLowerCase();
  const list = !term ? all : all.filter((r) =>
    (cfg.search || []).some((k) => String(k.split('.').reduce((o, kk) => (o ? o[kk] : ''), r) ?? '').toLowerCase().includes(term)));

  const editing = id ? (id === 'new' ? {} : all.find((r) => r[cfg.pk] === id) || {}) : null;

  function go(nextId) {
    const base = window.location.pathname;
    router.replace(nextId ? `${base}?id=${nextId}` : base, { scroll: false });
  }

  async function onSubmit(e) {
    e.preventDefault();
    setBusy(true); setErr('');
    try {
      const values = formValues(e.target);
      if (id === 'new') await insertRow(cfg.table, values);
      else await updateRow(cfg.table, cfg.pk, id, values);
      main.reload(); go(null);
    } catch (e2) { setErr(e2.message || String(e2)); }
    setBusy(false);
  }

  async function onDelete() {
    setBusy(true); setErr('');
    try { await removeRow(cfg.table, cfg.pk, id); main.reload(); go(null); }
    catch (e2) { setErr(e2.message || String(e2)); }
    setBusy(false);
  }

  const kpis = cfg.kpis ? cfg.kpis(all) : null;

  return (
    <Page title={cfg.title} sub={cfg.sub ? cfg.sub(all) : `${all.length} records`}
      actions={<>
        {cfg.sheet && (
          <button className="btn" onClick={() => setSheetOpen((v) => !v)}>
            {sheetOpen ? 'Hide import' : 'Import / export'}
          </button>)}
        <button className="btn btn-primary" onClick={() => go('new')}>New {cfg.singular}</button>
      </>}>
      <ErrorNote error={main.error || err} />

      {cfg.sheet && sheetOpen && (
        <div style={{ marginBottom: 16 }}>
          <Sheet cfg={{ table: cfg.table, singular: cfg.singular, columns: cfg.sheet }}
            onDone={() => { main.reload(); setSheetOpen(false); }} />
        </div>)}

      {kpis && <div className="kpi-row" style={{ marginBottom: 16 }}>
        {kpis.map((k) => <Stat key={k.label} {...k} />)}
      </div>}

      <div className="toolbar">
        {cfg.search && (
          <div className="search"><span className="mag">⌕</span>
            <input value={q} onChange={(e) => setQ(e.target.value)} placeholder={cfg.searchHint || 'Search…'} /></div>
        )}
        <span className="spacer" />
        {cfg.filter && (
          <div className="pill-row">
            <button className={`chip ${!filterValue ? 'on' : ''}`} onClick={() => router.replace(window.location.pathname)}>All</button>
            {cfg.filter.values.map((v) => (
              <button key={v} className={`chip ${filterValue === v ? 'on' : ''}`}
                onClick={() => router.replace(`${window.location.pathname}?f=${encodeURIComponent(v)}`)}>{v}</button>
            ))}
          </div>
        )}
      </div>

      <div className="grid" style={{ gridTemplateColumns: editing ? '1fr 360px' : '1fr' }}>
        <div className="card">
          {main.loading ? <Loading /> : list.length === 0 ? (
            <Empty title={cfg.emptyTitle || 'Nothing here yet'} hint={cfg.emptyHint}>
              <button className="btn btn-primary" onClick={() => go('new')}>New {cfg.singular}</button>
            </Empty>
          ) : (
            <div className="t-wrap"><table className="table">
              <thead><tr>{cfg.columns.map((c) => <th key={c.key} className={c.num ? 'num' : ''}>{c.label}</th>)}<th></th></tr></thead>
              <tbody>
                {list.map((r) => (
                  <tr key={r[cfg.pk]}>
                    {cfg.columns.map((c) => <td key={c.key} className={c.num ? 'num' : ''}>{cell(r, c)}</td>)}
                    <td style={{ textAlign: 'right' }}>
                      <button className="btn btn-sm" onClick={() => go(r[cfg.pk])}>Open</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table></div>
          )}
        </div>

        {editing && (
          <div className="panel">
            <form className="card" onSubmit={onSubmit}>
              <div className="card-head"><h3>{id === 'new' ? `New ${cfg.singular}` : `Edit ${cfg.singular}`}</h3>
                <button type="button" className="btn btn-ghost btn-sm" onClick={() => go(null)}>Close</button></div>
              <div className="card-body">
                {cfg.fields.map((f) => (
                  <div className="field" key={f.name}>
                    <label>{f.label}</label>
                    {f.type === 'textarea' ? (
                      <textarea name={f.name} defaultValue={editing[f.name] ?? ''} placeholder={f.placeholder} />
                    ) : f.lookup ? (
                      <select name={f.name} defaultValue={editing[f.name] ?? ''}>
                        <option value="">—</option>
                        {(lookups.data?.[f.name] || []).map((o) => (
                          <option key={o[f.lookup.pk]} value={o[f.lookup.pk]}>{o[f.lookup.label]}</option>
                        ))}
                      </select>
                    ) : f.options ? (
                      <select name={f.name} defaultValue={editing[f.name] ?? f.options[0]}>
                        {f.options.map((o) => <option key={o} value={o}>{o}</option>)}
                      </select>
                    ) : (
                      <input name={f.name} type={f.type || 'text'} step={f.step}
                        defaultValue={f.type === 'date' ? (editing[f.name] || '').slice(0, 10) : editing[f.name] ?? ''}
                        placeholder={f.placeholder} required={f.required} />
                    )}
                    {f.hint && <span className="hint">{f.hint}</span>}
                  </div>
                ))}
              </div>
              <div className="card-foot row">
                <button className="btn btn-primary" disabled={busy}>{busy ? 'Saving…' : 'Save'}</button>
                <button type="button" className="btn btn-ghost" onClick={() => go(null)}>Cancel</button>
                <span className="spacer" />
                {id !== 'new' && manager && (
                  <button type="button" className="btn btn-danger btn-sm" onClick={onDelete} disabled={busy}>Delete</button>
                )}
              </div>
            </form>
            {cfg.sidePanel && editing[cfg.pk] && <div style={{ marginTop: 14 }}>{cfg.sidePanel(editing)}</div>}
          </div>
        )}
      </div>
    </Page>
  );
}
