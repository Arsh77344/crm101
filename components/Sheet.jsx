'use client';
import { useRef, useState } from 'react';
import * as XLSX from 'xlsx';
import { sb, clean } from '@/lib/db';

/**
 * Import from and export to Excel or CSV.
 * cfg: { table, singular, columns: [{ key, label, required, example, hint }], select }
 */
const YES = /^(y|yes|true|1|✓|opted in)$/i;
const NO = /^(n|no|false|0|-|opted out)$/i;

function coerce(row, columns) {
  const out = { ...row };
  columns.forEach((c) => {
    const v = out[c.key];
    if (v === undefined || v === null || v === '') return;
    if (c.type === 'boolean') {
      const text = String(v).trim();
      out[c.key] = YES.test(text) ? true : NO.test(text) ? false : null;
    }
    if (c.type === 'number') {
      const n = Number(String(v).replace(/[^\d.-]/g, ''));
      out[c.key] = Number.isFinite(n) ? n : null;
    }
    // Digits held as text: a pincode or a phone. Excel hands these back as
    // numbers when the cell was formatted as one, and "221001" arriving as
    // 221001.0 fails every six-digit check downstream.
    if (c.type === 'digits') {
      // A trailing .0 goes first: stripping every non-digit from "221001.0"
      // would otherwise yield 2210010, which is worse than what came in.
      const d = String(v).trim().replace(/\.0+$/, '').replace(/\D/g, '');
      out[c.key] = d || null;
    }
    if (c.type === 'date') {
      const d = new Date(v);
      out[c.key] = Number.isNaN(d.getTime()) ? null : d.toISOString();
    }
  });
  return out;
}

export default function Sheet({ cfg, onDone }) {
  const fileRef = useRef(null);
  const [preview, setPreview] = useState(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState('');
  const [err, setErr] = useState('');

  function downloadTemplate() {
    const headers = cfg.columns.map((c) => c.label);
    const example = cfg.columns.map((c) => c.example ?? '');
    const notes = cfg.columns.map((c) => (c.required ? 'required' : c.hint || 'optional'));
    const ws = XLSX.utils.aoa_to_sheet([headers, example, notes]);
    ws['!cols'] = headers.map((h) => ({ wch: Math.max(14, h.length + 4) }));
    const wb = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(wb, ws, cfg.singular);
    XLSX.writeFile(wb, `${cfg.table}-template.xlsx`);
  }

  async function exportAll() {
    setBusy(true); setErr(''); setMsg('');
    try {
      const { data, error } = await sb().from(cfg.table).select(cfg.select || '*').limit(5000);
      if (error) throw error;
      const rows = (data || []).map((r) => {
        const o = {};
        cfg.columns.forEach((c) => { o[c.label] = r[c.key] ?? ''; });
        return o;
      });
      const ws = XLSX.utils.json_to_sheet(rows, { header: cfg.columns.map((c) => c.label) });
      ws['!cols'] = cfg.columns.map((c) => ({ wch: Math.max(14, c.label.length + 4) }));
      const wb = XLSX.utils.book_new();
      XLSX.utils.book_append_sheet(wb, ws, cfg.singular);
      XLSX.writeFile(wb, `${cfg.table}-${new Date().toISOString().slice(0, 10)}.xlsx`);
      setMsg(`Exported ${rows.length} rows.`);
    } catch (e) { setErr(e.message || String(e)); }
    setBusy(false);
  }

  async function pick(e) {
    const file = e.target.files?.[0];
    if (!file) return;
    setErr(''); setMsg('');
    try {
      const buf = await file.arrayBuffer();
      const wb = XLSX.read(buf);
      const ws = wb.Sheets[wb.SheetNames[0]];
      const raw = XLSX.utils.sheet_to_json(ws, { defval: '' });
      if (!raw.length) throw new Error('That sheet has no rows under the header.');

      const byLabel = {};
      cfg.columns.forEach((c) => { byLabel[c.label.toLowerCase().trim()] = c.key; });
      const mapped = [];
      const skipped = [];
      raw.forEach((line, i) => {
        const row = {};
        Object.entries(line).forEach(([k, v]) => {
          const key = byLabel[String(k).toLowerCase().trim()];
          if (key && String(v).trim() !== '') row[key] = typeof v === 'string' ? v.trim() : v;
        });
        const missing = cfg.columns.filter((c) => c.required && !row[c.key]).map((c) => c.label);
        const isNote = Object.values(line).every((v) => ['required', 'optional'].includes(String(v).trim()));
        if (isNote) return;
        if (missing.length) skipped.push(`Row ${i + 2}: missing ${missing.join(', ')}`);
        else {
          const tidy = coerce(row, cfg.columns);
          mapped.push(cfg.transform ? cfg.transform(tidy) : tidy);
        }
      });

      const unknown = Object.keys(raw[0]).filter((k) => !byLabel[String(k).toLowerCase().trim()]);
      setPreview({ rows: mapped, skipped, unknown, fileName: file.name });
    } catch (e2) { setErr(e2.message || String(e2)); }
    if (fileRef.current) fileRef.current.value = '';
  }

  async function confirmImport() {
    if (!preview?.rows.length) return;
    setBusy(true); setErr('');
    try {
      let added = 0, updated = 0;
      for (let i = 0; i < preview.rows.length; i += 100) {
        const chunk = preview.rows.slice(i, i + 100).map(clean);
        if (cfg.matchOn) {
          // Update the row that is already there rather than making a second
          // copy of the same person.
          for (const row of chunk) {
            const key = cfg.matchOn.find((k) => row[k]);
            let existing = null;
            if (key) {
              const { data } = await sb().from(cfg.table).select(cfg.pk)
                .eq(key, row[key]).limit(1).maybeSingle();
              existing = data;
            }
            if (existing) {
              const { error } = await sb().from(cfg.table).update(row)
                .eq(cfg.pk, existing[cfg.pk]);
              if (error) throw error;
              updated += 1;
            } else {
              const { error } = await sb().from(cfg.table).insert(row);
              if (error) throw error;
              added += 1;
            }
          }
        } else {
          const { error } = await sb().from(cfg.table).insert(chunk);
          if (error) throw error;
          added += chunk.length;
        }
      }
      setMsg(cfg.matchOn
        ? `${added} new, ${updated} already here and updated.`
        : `Imported ${preview.rows.length} rows.`);
      setPreview(null);
      onDone?.();
    } catch (e) { setErr(e.message || String(e)); }
    setBusy(false);
  }

  return (
    <div className="card">
      <div className="card-head"><h3>Import and export</h3>
        <span className="small faint">Excel or CSV</span></div>
      <div className="card-body">
        <div className="row wrap" style={{ gap: 7 }}>
          <button className="btn btn-sm" onClick={downloadTemplate} disabled={busy}>Download template</button>
          <button className="btn btn-sm" onClick={() => fileRef.current?.click()} disabled={busy}>Choose a file…</button>
          <button className="btn btn-sm" onClick={exportAll} disabled={busy}>Export all</button>
          <input ref={fileRef} type="file" accept=".xlsx,.xls,.csv" onChange={pick} style={{ display: 'none' }} />
        </div>
        <div className="small faint" style={{ marginTop: 8 }}>
          The template carries the exact column names accepted here. Extra columns are ignored, so you can
          paste from an existing sheet and only the matching ones come across.
        </div>
        {err && <div className="note warn" style={{ marginTop: 10 }}>{err}</div>}
        {msg && <div className="ok" style={{ marginTop: 10, marginBottom: 0 }}>{msg}</div>}
      </div>

      {preview && (
        <>
          <div className="card-body" style={{ borderTop: '1px solid var(--line-2)' }}>
            <div className="row" style={{ marginBottom: 9 }}>
              <strong className="small">{preview.fileName}</strong>
              <span className="spacer" />
              <span className="small muted">{preview.rows.length} ready
                {preview.skipped.length ? ` · ${preview.skipped.length} skipped` : ''}</span>
            </div>
            {preview.unknown.length > 0 && (
              <div className="note plain small" style={{ marginBottom: 9 }}>
                Ignored columns: {preview.unknown.join(', ')}
              </div>)}
            {preview.skipped.length > 0 && (
              <div className="note warn small" style={{ marginBottom: 9 }}>
                {preview.skipped.slice(0, 4).join(' · ')}{preview.skipped.length > 4 ? ' …' : ''}
              </div>)}
            <div className="t-wrap" style={{ maxHeight: 240, overflowY: 'auto' }}>
              <table className="table">
                <thead><tr>{cfg.columns.slice(0, 6).map((c) => <th key={c.key}>{c.label}</th>)}</tr></thead>
                <tbody>{preview.rows.slice(0, 8).map((r, i) => (
                  <tr key={i}>{cfg.columns.slice(0, 6).map((c) => (
                    <td key={c.key} className="small">{String(r[c.key] ?? '—')}</td>))}</tr>))}
                </tbody></table>
            </div>
          </div>
          <div className="card-foot row">
            <button className="btn btn-primary btn-sm" onClick={confirmImport} disabled={busy || !preview.rows.length}>
              {busy ? 'Importing…' : `Import ${preview.rows.length} rows`}
            </button>
            <button className="btn btn-ghost btn-sm" onClick={() => setPreview(null)} disabled={busy}>Cancel</button>
          </div>
        </>
      )}
    </div>
  );
}
