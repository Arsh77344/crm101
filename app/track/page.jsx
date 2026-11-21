'use client';
import { Suspense, useEffect, useState } from 'react';
import { useSearchParams } from 'next/navigation';
import { Loading, when } from '@/components/ui';

// A customer holds this link; nobody is signed in. Everything shown comes back
// from the `track` function, which reads with the service key and hands over
// only what a customer may see — so no table is opened to anonymous readers.
async function look(token) {
  let res;
  try {
    res = await fetch(`${process.env.NEXT_PUBLIC_SUPABASE_URL}/functions/v1/track`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ token }),
    });
  } catch {
    // A customer should never be shown the browser's own words for this.
    throw new Error('We could not reach the tracking service just now. '
      + 'Check your connection and refresh the page.');
  }
  const out = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(out.error || 'That tracking link is not valid.');
  return out;
}

const DONE = (s) => /delivered/i.test(s || '');
const MOVING = (s) => /on its way|out for delivery|picked/i.test(s || '');

function Parcel({ p, many }) {
  const tone = DONE(p.status) ? 'var(--pos)' : MOVING(p.status) ? 'var(--accent)' : 'var(--ink-3)';
  return (
    <div className="card">
      <div className="card-head">
        <h3>{many ? `Parcel ${p.parcel} of this order` : 'Your parcel'}</h3>
        <span className="small" style={{ color: tone, fontWeight: 600 }}>{p.status}</span>
      </div>
      <div className="card-body">
        <ul style={{ margin: 0, paddingLeft: 17 }}>
          {p.pieces.map((x, i) => (
            <li key={i} className="small" style={{ marginBottom: 3 }}>
              {x.name}{x.quantity > 1 ? ` × ${x.quantity}` : ''}
            </li>))}
        </ul>

        {p.awb
          ? <div className="small muted" style={{ marginTop: 10 }}>
              {p.courier || 'Courier'} · {p.awb}
              {p.tracking_url && <>{' · '}
                <a href={p.tracking_url} target="_blank" rel="noopener noreferrer">
                  Track it with the courier</a></>}
            </div>
          : <div className="small muted" style={{ marginTop: 10 }}>
              A courier has not collected this one yet. The tracking number appears here
              once it has.
            </div>}

        {p.steps?.length > 0 && (
          <div style={{ marginTop: 12 }}>
            {p.steps.map((s, i) => (
              <div key={i} className="small" style={{ display: 'flex', gap: 10, marginBottom: 4 }}>
                <span className="faint" style={{ minWidth: 112 }}>{when(s.at) || '—'}</span>
                <span>{s.what}{s.where ? ` — ${s.where}` : ''}</span>
              </div>))}
          </div>)}
      </div>
    </div>
  );
}

function Track() {
  const token = useSearchParams().get('t');
  const [state, setState] = useState({ loading: true });

  useEffect(() => {
    if (!token) { setState({ error: 'This link is missing its tracking code.' }); return; }
    let live = true;
    look(token)
      .then((d) => live && setState({ data: d }))
      .catch((e) => live && setState({ error: e.message }));
    return () => { live = false; };
  }, [token]);

  if (state.loading) return <Loading />;

  if (state.error) {
    return (
      <div className="auth"><div className="auth-card">
        <h1>Not available</h1>
        <p className="sub">{state.error}</p>
      </div></div>);
  }

  const d = state.data;
  return (
    <div style={{ background: 'var(--bg)', minHeight: '100vh' }}>
      <div style={{ maxWidth: 640, margin: '0 auto', padding: '56px 24px 80px' }}>
        <div style={{ fontSize: 11, letterSpacing: '.18em', textTransform: 'uppercase',
                      color: 'var(--ink-3)' }}>{d.brand}</div>
        <h1 style={{ fontSize: 30, margin: '8px 0 6px' }}>
          {d.name ? `${d.name}, here is your order` : 'Your order'}
        </h1>
        <p className="muted" style={{ fontSize: 14, margin: 0 }}>
          {d.order_number}{d.ordered_at ? ` · placed ${when(d.ordered_at)}` : ''}
          {d.to ? ` · going to ${d.to}` : ''}
        </p>

        {d.split && (
          <div className="note plain small" style={{ marginTop: 20 }}>
            Your pieces come from {d.parcels.length} different weavers, so they travel as{' '}
            {d.parcels.length} parcels and may arrive on different days. Each one is tracked
            on its own below.
          </div>)}

        <div className="stack" style={{ marginTop: d.split ? 14 : 24 }}>
          {d.parcels.map((p) => (
            <Parcel key={p.parcel} p={p} many={d.split} />))}
          {d.parcels.length === 0 && (
            <div className="card"><div className="card-body">
              <div className="small muted">
                This order is being put together. Tracking appears here once it is packed.
              </div>
            </div></div>)}
        </div>

        <p className="small faint" style={{ marginTop: 26 }}>
          This page updates itself as the courier scans each parcel. Keep the link — it is
          only for this order.
        </p>
      </div>
    </div>
  );
}

export default function Wrapped() {
  return <Suspense fallback={<Loading />}><Track /></Suspense>;
}
