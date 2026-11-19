'use client';
import { useEffect, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import { sb } from '@/lib/db';
import { PAGES } from '@/lib/nav';

const SOURCES = [
  { table: 'products', pk: 'product_id', label: 'public_product_name', sub: 'internal_sku',
    cols: 'public_product_name,internal_sku,colour,fabric', href: '/products', kind: 'Product' },
  { table: 'contacts', pk: 'contact_id', label: 'full_name', sub: 'email',
    cols: 'full_name,email,phone_number,business_category', href: '/contacts', kind: 'Contact' },
  { table: 'orders', pk: 'order_id', label: 'order_number', sub: 'order_status',
    cols: 'order_number,order_status,external_order_reference', href: '/orders', kind: 'Order' },
  { table: 'campaigns', pk: 'campaign_id', label: 'campaign_name', sub: 'channel',
    cols: 'campaign_name,channel,objective', href: '/campaigns', kind: 'Campaign' },
  { table: 'companies', pk: 'company_id', label: 'company_name', sub: 'country',
    cols: 'company_name,country,company_type', href: '/companies', kind: 'Company' },
  { table: 'suppliers', pk: 'supplier_id', label: 'name', sub: 'cluster',
    cols: 'name,cluster,specialty', href: '/suppliers', kind: 'Supplier' },
];

export default function Search() {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [term, setTerm] = useState('');
  const [hits, setHits] = useState([]);
  const [busy, setBusy] = useState(false);
  const box = useRef(null);

  useEffect(() => {
    const onKey = (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); setOpen((v) => !v); }
      if (e.key === 'Escape') setOpen(false);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  useEffect(() => { if (open) setTimeout(() => box.current?.focus(), 30); }, [open]);

  const q = term.trim();
  const pageHits = q.length < 1 ? [] : PAGES
    .filter((p) => p.label.toLowerCase().includes(q.toLowerCase())
      || p.group.toLowerCase().startsWith(q.toLowerCase()))
    .slice(0, 6);

  useEffect(() => {
    const q = term.trim();
    if (q.length < 2) { setHits([]); return; }
    let alive = true;
    setBusy(true);
    const t = setTimeout(async () => {
      const found = [];
      for (const s of SOURCES) {
        const or = s.cols.split(',').map((c) => `${c}.ilike.%${q}%`).join(',');
        const { data } = await sb().from(s.table).select(`${s.pk},${s.cols}`).or(or).limit(4);
        (data || []).forEach((row) => found.push({
          id: row[s.pk], kind: s.kind, href: `${s.href}?id=${row[s.pk]}`,
          label: row[s.label] || '—', sub: row[s.sub] || '',
        }));
      }
      if (alive) { setHits(found); setBusy(false); }
    }, 180);
    return () => { alive = false; clearTimeout(t); };
  }, [term]);

  function goTo(h) { setOpen(false); setTerm(''); router.push(h.href); }

  // Enter with nothing chosen goes to the first page that matched, which is the
  // common case: open, type three letters of a page name, Enter.
  function onKeyDown(e) {
    if (e.key === 'Enter' && pageHits.length) { e.preventDefault(); goTo(pageHits[0]); }
  }

  if (!open) {
    return (
      <button className="btn btn-sm" onClick={() => setOpen(true)} title="Search (Ctrl K)">
        ⌕ Search <span className="faint" style={{ fontSize: 11 }}>Ctrl K</span>
      </button>
    );
  }

  return (
    <div onClick={() => setOpen(false)}
      style={{ position: 'fixed', inset: 0, background: 'rgba(16,16,20,.45)', zIndex: 60,
        display: 'flex', alignItems: 'flex-start', justifyContent: 'center', paddingTop: '12vh' }}>
      <div className="card" onClick={(e) => e.stopPropagation()}
        style={{ width: 'min(540px,92vw)', boxShadow: 'var(--shadow-lg)', overflow: 'hidden' }}>
        <input ref={box} value={term} onChange={(e) => setTerm(e.target.value)}
          onKeyDown={onKeyDown}
          placeholder="Go to a page, or search products, people, orders…"
          style={{ width: '100%', border: 0, borderBottom: '1px solid var(--line)', padding: '13px 15px',
            fontSize: 14.5, outline: 'none', background: 'var(--panel)', color: 'var(--ink)' }} />
        <div style={{ maxHeight: 340, overflowY: 'auto' }}>
          {pageHits.map((p) => (
            <button key={p.href} onClick={() => goTo(p)} className="hit">
              <span className="badge b-accent" style={{ marginRight: 8 }}>Page</span>
              <span style={{ fontWeight: 500 }}>{p.label}</span>
              <span className="small faint"> · {p.group}</span>
            </button>))}
          {q.length < 1 && <div className="small faint" style={{ padding: 15 }}>
            Type a page name to jump to it, or two letters to search your records.</div>}
          {q.length >= 2 && !busy && hits.length === 0 && pageHits.length === 0 &&
            <div className="small faint" style={{ padding: 15 }}>Nothing matches “{term}”.</div>}
          {busy && <div className="small faint" style={{ padding: 15 }}>Searching…</div>}
          {hits.map((h) => (
            <button key={`${h.kind}-${h.id}`} onClick={() => goTo(h)} className="hit">
              <span className="badge" style={{ marginRight: 8 }}>{h.kind}</span>
              <span style={{ fontWeight: 500 }}>{h.label}</span>
              {h.sub && <span className="small faint"> · {h.sub}</span>}
            </button>))}
        </div>
      </div>
    </div>
  );
}
