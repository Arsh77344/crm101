'use client';
import { useEffect, useState } from 'react';
import { sb, useQuery } from '@/lib/db';
import { Badge, money } from '@/components/ui';

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

// What the parcel's destination needs before any courier will take it. Checked
// here as well as in the function, so the gap is visible before a button is
// pressed. What the *sender* needs is per vendor and comes back from the
// function, because only it knows which addresses Shiprocket has registered.
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

const key = (v) => v.brand_id || 'none';

// One vendor's parcel: what is in it, whether it can leave, and the couriers
// that would carry it from that vendor's own door.
function VendorBlock({ v, rate, chosen, busy, onQuote, onPick, onRegister, onBook }) {
  const blocked = (v.gaps || []).length > 0;
  return (
    <div className="card">
      <div className="card-head">
        <h3>{v.brand_name}</h3>
        <div className="row" style={{ gap: 7 }}>
          <Badge>{v.registered ? 'Pickup ready' : 'No pickup yet'}</Badge>
          <span className="small muted">{v.lines} line{v.lines === 1 ? '' : 's'}</span>
          {v.brand_id && !v.registered && (
            <button className="btn btn-sm" disabled={Boolean(busy)}
              onClick={() => onRegister(v)}>
              {busy === `reg:${v.brand_id}` ? 'Registering…' : 'Register pickup'}</button>)}
          {!blocked && (
            <button className="btn btn-sm" disabled={Boolean(busy)}
              onClick={() => onQuote(v)}>
              {busy === `rate:${key(v)}` ? 'Asking…' : 'Rates'}</button>)}
        </div>
      </div>
      <div className="card-body">
        {blocked
          ? <div className="note warn small">
              {v.gaps.join('. ')}.
              {v.brand_id
                ? ' Fill the pickup fields on that brand, then register the address.'
                : ' Put the pieces against a brand on the order.'}
            </div>
          : <div className="small muted">
              {money(v.value)} of pieces, leaving from <strong>{v.pickup}</strong>,
              {' '}{v.pickup_pincode}.
            </div>}

        {rate?.error && <div className="note warn small">{rate.error}</div>}

        {rate && !rate.error && (
          (rate.couriers || []).length === 0
            ? <div className="note warn small">
                No courier runs from {v.pickup_pincode} to that pincode at this weight.</div>
            : <>
                <div className="small" style={{ fontWeight: 600, margin: '10px 0 6px' }}>
                  Couriers that will carry it, cheapest first
                </div>
                <div className="t-wrap"><table className="table">
                  <thead><tr><th>Courier</th><th className="num">Rate</th>
                    <th>Delivery</th><th>Rating</th><th /></tr></thead>
                  <tbody>
                    {rate.couriers.slice(0, 6).map((c) => (
                      <tr key={c.courier_id}>
                        <td className="small">{c.name}</td>
                        <td className="num small">{money(c.rate)}</td>
                        <td className="small">{c.etd || `${c.days} days`}</td>
                        <td className="small">{c.rating ?? '—'}</td>
                        <td style={{ textAlign: 'right' }}>
                          <button
                            className={`btn btn-sm${chosen === c.courier_id ? ' on' : ''}`}
                            disabled={Boolean(busy)}
                            onClick={() => onPick(v, c.courier_id)}>
                            {chosen === c.courier_id ? 'Chosen' : 'Choose'}</button></td>
                      </tr>))}
                  </tbody>
                </table></div>
                {chosen && (
                  <div className="row" style={{ marginTop: 10 }}>
                    <button className="btn btn-primary btn-sm" disabled={Boolean(busy)}
                      onClick={() => onBook(v)}>
                      {busy === `book:${key(v)}` ? 'Booking…' : 'Book this parcel'}</button>
                  </div>)}
              </>)}
      </div>
    </div>
  );
}

export default function Shiprocket({ onChange }) {
  const [health, setHealth] = useState(null);
  const [busy, setBusy] = useState('');
  const [err, setErr] = useState('');
  const [parcels, setParcels] = useState([]);
  const [note, setNote] = useState('');
  const [open, setOpen] = useState(null);
  const [vendors, setVendors] = useState(null);
  const [rates, setRates] = useState({});
  const [chosen, setChosen] = useState({});

  useEffect(() => {
    courier({ action: 'health' }).then(setHealth)
      .catch((e) => setHealth({ configured: false, error: e.message }));
  }, []);

  const q = useQuery(async (c) => {
    const [orders, ship] = await Promise.all([
      c.from('orders').select('*,order_items(order_item_id),contacts(full_name)')
        .in('order_status', ['Draft', 'Pending Payment', 'Processing'])
        .order('ordered_at', { ascending: false }).limit(25),
      c.from('shipments').select('order_id,brand_id,awb').not('awb', 'is', null),
    ]);
    if (orders.error) throw orders.error;
    // An order is only done with when every vendor in it has an AWB, so the
    // count of booked parcels is kept per order rather than as a flag.
    const booked = {};
    for (const s of ship.data || []) {
      booked[s.order_id] = (booked[s.order_id] || 0) + 1;
    }
    return { orders: orders.data || [], booked };
  }, []);

  const waiting = q.data?.orders || [];
  const bookedFor = q.data?.booked || {};

  async function look(o) {
    setBusy(`look:${o.order_id}`); setErr(''); setVendors(null);
    setRates({}); setChosen({}); setParcels([]); setOpen(o.order_id);
    try { setVendors(await courier({ action: 'vendors', order_id: o.order_id })); }
    catch (e) { setErr(e.message); setOpen(null); }
    setBusy('');
  }

  async function quote(v) {
    setBusy(`rate:${key(v)}`); setErr('');
    try {
      const out = await courier({ action: 'rates', order_id: open, brand_id: v.brand_id });
      const mine = (out.vendors || []).find((x) => key(x) === key(v)) || out;
      setRates((r) => ({ ...r, [key(v)]: mine }));
    } catch (e) { setRates((r) => ({ ...r, [key(v)]: { error: e.message } })); }
    setBusy('');
  }

  function pick(v, courierId) {
    setChosen((c) => ({ ...c, [key(v)]: courierId }));
  }

  async function register(v) {
    setBusy(`reg:${v.brand_id}`); setErr('');
    try {
      const out = await courier({ action: 'add_pickup', brand_id: v.brand_id });
      setVendors((s) => ({ ...s,
        vendors: (s?.vendors || []).map((x) => x.brand_id === v.brand_id
          ? { ...x, registered: true, pickup: out.nickname, gaps: [] } : x) }));
    } catch (e) { setErr(e.message); }
    setBusy('');
  }

  async function book(v) {
    setBusy(`book:${key(v)}`); setErr('');
    try {
      const out = await courier({ action: 'book', order_id: open,
        brand_id: v.brand_id, couriers: chosen });
      setParcels((p) => [...p, ...(out.parcels || [])]);
      setVendors(await courier({ action: 'vendors', order_id: open }));
      await q.reload(); onChange?.();
    } catch (e) { setErr(e.message); }
    setBusy('');
  }

  async function bookAll() {
    setBusy('book:all'); setErr('');
    try {
      const out = await courier({ action: 'book', order_id: open, couriers: chosen });
      setParcels(out.parcels || []);
      setVendors(await courier({ action: 'vendors', order_id: open }));
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
          <li>In Supabase Edge Function secrets, add <span className="mono">SHIPROCKET_EMAIL</span>
            and <span className="mono"> SHIPROCKET_PASSWORD</span>.</li>
          <li>Each vendor's pickup address is entered on that brand, not here, because every
            vendor ships from their own door.</li>
        </ul>
      </div>);
  }

  const ready = health.pickups || {};
  const live = vendors?.vendors || [];
  const bookable = live.filter((v) => !(v.gaps || []).length);

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

        {parcels.map((d, i) => (
          <div key={i} className={`note ${d.awb ? 'good' : 'warn'} small`}>
            <strong>{d.brand_name}</strong>{' — '}
            {(d.awb
              ? `${d.courier || 'Booked'}, AWB ${d.awb}.`
                + (d.pickup ? ' Pickup scheduled.' : ' Pickup not scheduled.')
                + (d.label_url ? ' Label ready.' : '')
                + (d.from ? ` Leaves from ${d.from}.` : '')
              : d.error)}
          </div>))}

        {ready.vendors > 0 && ready.registered < ready.vendors && (
          <div className="note plain small">
            {ready.registered} of {ready.vendors} vendors have a pickup address registered with
            Shiprocket.{ready.waiting?.length
              ? ` Still waiting: ${ready.waiting.join(', ')}.`
              : ''}
          </div>)}

        {waiting.length === 0
          ? <div className="small muted">Every order that can be shipped has been booked.</div>
          : (
            <>
              <div className="small muted" style={{ marginBottom: 8 }}>
                {waiting.length} order{waiting.length === 1 ? '' : 's'} with parcels still to send.
              </div>
              <div className="t-wrap"><table className="table">
                <thead><tr>
                  <th>Order</th><th>To</th><th>Where</th><th className="num">Value</th>
                  <th>Paid</th><th>Parcels</th><th /></tr></thead>
                <tbody>
                  {waiting.map((o) => {
                    const missing = gaps(o, (o.order_items || []).length);
                    const done = bookedFor[o.order_id] || 0;
                    return (
                      <tr key={o.order_id}>
                        <td><strong className="small">{o.order_number}</strong></td>
                        <td className="small">{o.ship_name || o.contacts?.full_name || '—'}</td>
                        <td className="small">
                          {o.ship_city ? `${o.ship_city} ${o.ship_pincode || ''}` : '—'}</td>
                        <td className="num small">{money(o.total, o.currency)}</td>
                        <td><Badge>{o.payment_method || 'Prepaid'}</Badge></td>
                        <td className="small">{done ? `${done} booked` : '—'}</td>
                        <td style={{ textAlign: 'right' }}>
                          {missing.length
                            ? <span className="small muted"
                                title="Add these on the order before booking">
                                Still needs {missing.join(', ')}</span>
                            : <button className="btn btn-sm" disabled={Boolean(busy)}
                                onClick={() => look(o)}>
                                {busy === `look:${o.order_id}` ? 'Looking…'
                                  : open === o.order_id ? 'Parcels below' : 'Parcels'}</button>}
                        </td>
                      </tr>);
                  })}
                </tbody>
              </table></div>

              {open && live.length > 0 && (
                <div style={{ marginTop: 12 }}>
                  <div className="small" style={{ fontWeight: 600, marginBottom: 6 }}>
                    {live.length === 1
                      ? 'One parcel, from one vendor'
                      : `${live.length} parcels — one per vendor, each from its own address`}
                  </div>
                  <div className="stack">
                    {live.map((v) => (
                      <VendorBlock key={key(v)} v={v} rate={rates[key(v)]}
                        chosen={chosen[key(v)]} busy={busy}
                        onQuote={quote} onPick={pick} onRegister={register} onBook={book} />
                    ))}
                  </div>
                  {bookable.length > 1
                    && bookable.every((v) => chosen[key(v)]) && (
                    <div className="row" style={{ marginTop: 12 }}>
                      <button className="btn btn-primary btn-sm" disabled={Boolean(busy)}
                        onClick={bookAll}>
                        {busy === 'book:all'
                          ? 'Booking…'
                          : `Book all ${bookable.length} parcels`}</button>
                    </div>)}
                  <div className="small faint" style={{ marginTop: 6 }}>
                    Booking creates each parcel in Shiprocket, assigns its AWB, asks for a pickup at
                    that vendor's address and pulls the label back. It spends real money with the
                    courier. A vendor that cannot be booked does not stop the others.
                  </div>
                </div>)}
            </>)}
      </div>
    </div>
  );
}
