'use client';
import { useState } from 'react';
import { useQuery, insertRow, removeRow, removeWhere, formValues } from '@/lib/db';
import { Loading, ErrorNote, money } from './ui';

/**
 * A list of child records belonging to one parent, with a small add form.
 * cfg: { table, pk, parentKey, title, select, columns, fields, order }
 */
export default function Children({ cfg, parentId }) {
  const [err, setErr] = useState('');
  const q = useQuery(async (c) => {
    let query = c.from(cfg.table).select(cfg.select || '*').eq(cfg.parentKey, parentId);
    if (cfg.order) query = query.order(cfg.order);
    const { data, error } = await query;
    if (error) throw error;
    return data || [];
  }, [parentId]);

  async function add(e) {
    e.preventDefault();
    try { await insertRow(cfg.table, { ...formValues(e.target), [cfg.parentKey]: parentId }); e.target.reset(); q.reload(); }
    catch (e2) { setErr(e2.message); }
  }
  async function drop(row) {
    try {
      if (cfg.pkCols) {
        const match = {};
        cfg.pkCols.forEach((k) => { match[k] = row[k]; });
        await removeWhere(cfg.table, match);
      } else {
        await removeRow(cfg.table, cfg.pk, row[cfg.pk]);
      }
      q.reload();
    } catch (e2) { setErr(e2.message); }
  }

  const rows = q.data || [];
  return (
    <div className="card">
      <div className="card-head"><h3>{cfg.title}</h3><span className="small muted">{rows.length}</span></div>
      <ErrorNote error={q.error || err} />
      {q.loading ? <Loading /> : (
        <div className="t-wrap"><table className="table">
          <thead><tr>{cfg.columns.map((c) => <th key={c.key} className={c.num ? 'num' : ''}>{c.label}</th>)}<th></th></tr></thead>
          <tbody>
            {rows.length === 0 && <tr><td colSpan={cfg.columns.length + 1} className="small muted">Nothing added yet.</td></tr>}
            {rows.map((r, ri) => (
              <tr key={r[cfg.pk] || ri}>
                {cfg.columns.map((c) => (
                  <td key={c.key} className={c.num ? 'num' : ''}>
                    {c.render ? c.render(r)
                      : c.fmt === 'money' ? money(c.key.split('.').reduce((o, k) => (o ? o[k] : null), r))
                        : (c.key.split('.').reduce((o, k) => (o ? o[k] : null), r) ?? '—')}
                  </td>))}
                <td style={{ textAlign: 'right' }}>
                  <button className="btn btn-sm btn-ghost" onClick={() => drop(r)}>Remove</button></td>
              </tr>))}
          </tbody></table></div>
      )}
      <form className="card-foot row" style={{ gap: 8, flexWrap: 'wrap' }} onSubmit={add}>
        {cfg.fields.map((f) => (
          f.lookup ? <LookupSelect key={f.name} field={f} />
          : f.options ? (
            <select key={f.name} name={f.name} required={f.required}
              style={{ minWidth: f.width || 130, padding: '7px 10px', borderRadius: 8, border: '1px solid var(--line)' }}>
              {f.options.map((o) => <option key={o} value={o}>{o}</option>)}
            </select>
          ) : (
            <input key={f.name} name={f.name} type={f.type || 'text'} step={f.step} placeholder={f.label}
              required={f.required} style={{ width: f.width || 120, padding: '7px 10px', borderRadius: 8, border: '1px solid var(--line)' }} />
          )))}
        <button className="btn btn-sm btn-primary">Add</button>
      </form>
    </div>
  );
}

function LookupSelect({ field }) {
  const q = useQuery(async (c) => {
    const { data } = await c.from(field.lookup.table).select(`${field.lookup.pk},${field.lookup.label}`).order(field.lookup.label);
    return data || [];
  }, []);
  return (
    <select name={field.name} required={field.required}
      style={{ minWidth: field.width || 200, padding: '7px 10px', borderRadius: 8, border: '1px solid var(--line)' }}>
      <option value="">{field.label}…</option>
      {(q.data || []).map((o) => <option key={o[field.lookup.pk]} value={o[field.lookup.pk]}>{o[field.lookup.label]}</option>)}
    </select>
  );
}
