'use client';
import { useEffect, useState } from 'react';
import { sb, useQuery } from '@/lib/db';
import { Badge, money, when } from '@/components/ui';

export async function courier(body) {
  const { data: { session } } = await sb().auth.getSession();
  const res = await fetch(`${process.env.NEXT_PUBLIC_SUPABASE_URL}/functions/v1/shiprocket`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${session?.access_token}`, 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  const out = await res.json();
  if (!res.ok) throw new Error(out.error || `Shiprocket returned ${res.status}.`);
  return out;
}

// What a parcel needs before any courier will take it. Checked here as well as
// in the function, so the gap is visible before a button is pressed.
function gaps(o, items) {
  const out = [];
  if (!o.ship_name) out.push('a name');
  if (!o.ship_phone) out.push('a phone');
  if (!o.ship_line1) out.push('an address');
  if (!o.ship_city) out.push('a city');
  if (!o.ship_state) out.push('a state');
  if (!/^\d{6}$/.test(String(o.ship_pincode || ''))) out.push('a pincode');
  if (!items) out.push('line items');
  if (!o.weight_kg) out.push('a weight');
  return out;
}

export default function Shiprocket({ onChange }) {
  const [health, setHealth] = useState(null);
  const [busy, setBusy] = useState('');
  const [err, setErr] = useState('');
  const [note, setNote] = useState('');
  const [rates, setRates] = useState(null);
  const [open, setOpen] = useState(null);

  useEffect(() => {
    courier({ action: 'health' }).then(setHealth)
      .catch((e) => setHealth({ configured: false, error: e.message }));
  }, []);

  const q = useQuery(async (c) => {
    const [orders, ship] = await Promise.all([
      c.from('orders').select('*,order_items(item_id),contacts(full_name)')
        .in('order_status', ['Draft', 'Pending Payment', 'Processing'])
        .order('ordered_at', { ascending: false }).limit(25),
      c.from('shipments').select('order_id,awb,status').not('awb', 'is', null),
    ]);
    if (orders.error) throw orders.error;
    const booked = new Set((ship.data || []).map((s) => s.order_id));
    return { orders: (orders.data || []).filter((o) => !booked.has(o.order_id)) };
  }, []);

  const waiting = q.data?.orders || [];

  async function quote(o) {
    setBusy(o.order_id); setErr(''); setRates(null); setOpen(o.order_id);
    try { setRates(await courier({ action: 'rates', order_id: o.order_id })); }
    catch (e) { setErr(e.message); }
    setBusy('');
  }

  async function book(o, courierId) {
    setBusy(o.order_id); setErr(''); setNote('');
    try {
      const out = await courier({ action: 'book', order_id: o.order_id, courier_id: courierId });
      setNote(out.partial
        ? `Partly booked. ${out.error}`
        : `Booked with ${out.courier}. AWB ${out.awb}.`
          + (out.pickup ? ' Pickup scheduled.' : '')
          + (out.label_url ? ' Label ready.' : ''));
      setOpen(null); setRates(null);
      await q.reload(); onChange?.();
    } catch (e) { setErr(e.message); }
    setBusy('');
  }

  async function syncAll() {
    setBusy('sync'); setErr(''); setNote('');
    try {
      const out = await courier({ action: 'sync' });
      setNote(out.checked
        ? `Checked ${out.checked} shipment${out.checked === 1 ? '' : 's'} with the courier.`
        : 'Nothing in motion to check.');
      onChange?.();
    } catch (e) { setErr(e.message); }
    setBusy('');
  }

  if (!health) return null;

  if (!health.configured) {
    return (
      <div className="note warn small" style={{ marginBottom: 14 }}>
        <strong>Shiprocket is not connected.</strong>
        <ul>
          <li>In Shiprocket: Settings → API → Configure → Create an API User. The password is
            emailed to your registered address.</li>
          <li>In Supabase Edge Function secrets, add <span className="mono">SHIPROCKET_EMAIL</span>,
            <span className="mono"> SHIPROCKET_PASSWORD</span>,
            <span className="mono"> SHIPROCKET_PICKUP_PINCODE</span> and, if your pickup point is
            not called Primary, <span className="mono">SHIPROCKET_PICKUP_LOCATION</span>.</li>
        </ul>
      </div>);
  }

  return (
    <div className="card" style={{ marginBottom: 14 }}>
      <div className="card-head">
        <h3>Shiprocket</h3>
        <div className="row" style={{ gap: 7 }}>
          <Badge>{health.connected ? 'Connected' : 'Not connected'}</Badge>
          <button className="btn btn-sm" onClick={syncAll} disabled={Boolean(busy)}>
            {busy === 'sync' ? 'Checking…' : 'Update tracking'}</button>
        </div>
      </div>
      <div className="card-body">
        {!health.connected && (
          <div className="note warn small">{health.error || 'Could not sign in to Shiprocket.'}</div>)}
        {err && <div className="note warn small">{err}</div>}
        {note && <div className="note good small">{note}</div>}

        {waiting.length === 0
          ? <div className="small muted">Every order that can be shipped has been booked.</div>
          : (
            <>
              <div className="small muted" style={{ marginBottom: 8 }}>
                {waiting.length} order{waiting.length === 1 ? '' : 's'} not yet with a courier.
              </div>
              <div className="t-wrap"><table className="table">
                <thead><tr>
                  <th>Order</th><th>To</th><th>Where</th><th className="num">Value</th>
                  <th>Paid</th><th /></tr></thead>
                <tbody>
                  {waiting.map((o) => {
                    const missing = gaps(o, (o.order_items || []).length);
                    return (
                      <tr key={o.order_id}>
                        <td><strong className="small">{o.order_number}</strong></td>
                        <td className="small">{o.ship_name || o.contacts?.full_name || '—'}</td>
                        <td className="small">
                          {o.ship_city ? `${o.ship_city} ${o.ship_pincode || ''}` : '—'}</td>
                        <td className="num small">{money(o.total, o.currency)}</td>
                        <td><Badge>{o.payment_method || 'Prepaid'}</Badge></td>
                        <td style={{ textAlign: 'right' }}>
                          {missing.length
                            ? <span className="small" style={{ color: 'var(--neg)' }}
                                title="Add these on the order before booking">
                                Needs {missing.join(', ')}</span>
                            : <button className="btn btn-sm" disabled={Boolean(busy)}
                                onClick={() => quote(o)}>
                                {busy === o.order_id ? 'Asking…' : 'Rates'}</button>}
                        </td>
                      </tr>);
                  })}
                </tbody>
              </table></div>

              {open && rates && (
                <div style={{ marginTop: 12 }}>
                  <div className="small" style={{ fontWeight: 600, marginBottom: 6 }}>
                    Couriers that will carry it, cheapest first
                  </div>
                  {(rates.couriers || []).length === 0
                    ? <div className="note warn small">
                        No courier serves that pincode at this weight.</div>
                    : <div className="t-wrap"><table className="table">
                        <thead><tr><th>Courier</th><th className="num">Rate</th>
                          <th>Delivery</th><th>Rating</th><th /></tr></thead>
                        <tbody>
                          {rates.couriers.slice(0, 8).map((c) => (
                            <tr key={c.courier_id}>
                              <td className="small">{c.name}</td>
                              <td className="num small">{money(c.rate)}</td>
                              <td className="small">{c.etd || `${c.days} days`}</td>
                              <td className="small">{c.rating ?? '—'}</td>
                              <td style={{ textAlign: 'right' }}>
                                <button className="btn btn-primary btn-sm" disabled={Boolean(busy)}
                                  onClick={() => book(waiting.find((x) => x.order_id === open), c.courier_id)}>
                                  Book</button></td>
                            </tr>))}
                        </tbody>
                      </table></div>}
                  <div className="small faint" style={{ marginTop: 6 }}>
                    Booking creates the order in Shiprocket, assigns the AWB, asks for a pickup and
                    pulls the label back. It spends real money with the courier.
                  </div>
                </div>)}
            </>)}
      </div>
    </div>
  );
}
