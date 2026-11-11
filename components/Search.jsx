'use client';
import { useEffect, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import { sb } from '@/lib/db';

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
          placeholder="Search products, people, orders, campaigns…"
          style={{ width: '100%', border: 0, borderBottom: '1px solid var(--line)', padding: '13px 15px',
            fontSize: 14.5, outline: 'none', background: 'var(--panel)', color: 'var(--ink)' }} />
        <div style={{ maxHeight: 340, overflowY: 'auto' }}>
          {term.trim().length < 2 && <div className="small faint" style={{ padding: 15 }}>Type at least two letters.</div>}
          {term.trim().length >= 2 && !busy && hits.length === 0 &&
            <div className="small faint" style={{ padding: 15 }}>Nothing matches “{term}”.</div>}
          {busy && <div className="small faint" style={{ padding: 15 }}>Searching…</div>}
          {hits.map((h) => (
            <button key={`${h.kind}-${h.id}`} onClick={() => goTo(h)}
              style={{ display: 'block', width: '100%', textAlign: 'left', border: 0, background: 'transparent',
                padding: '9px 15px', cursor: 'pointer', borderBottom: '1px solid var(--line-2)' }}>
              <span className="badge" style={{ marginRight: 8 }}>{h.kind}</span>
              <span style={{ fontWeight: 500 }}>{h.label}</span>
              {h.sub && <span className="small faint"> · {h.sub}</span>}
            </button>))}
        </div>
      </div>
    </div>
  );
}
