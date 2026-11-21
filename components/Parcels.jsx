'use client';
import { useState } from 'react';
import { useQuery } from '@/lib/db';
import { Badge, money, when } from '@/components/ui';

// How this order actually travels, and the one link the customer gets. An order
// holding two vendors' pieces leaves as two parcels from two doors, so the
// order record says so here rather than leaving it to be discovered when half
// of it arrives.
export default function Parcels({ orderId }) {
  const [copied, setCopied] = useState(false);

  const q = useQuery(async (c) => {
    if (!orderId) return null;
    const [order, items, ship] = await Promise.all([
      c.from('orders').select('order_number,track_token').eq('order_id', orderId).maybeSingle(),
      c.from('order_items')
        .select('order_item_id,name,quantity,unit_price,'
          + 'products(public_product_name,brand_id,brands(brand_id,name,pickup_nickname))')
        .eq('order_id', orderId),
      c.from('shipments')
        .select('shipment_id,brand_id,awb,courier,status,tracking_url,delivered_at')
        .eq('order_id', orderId),
    ]);
    return { order: order.data, items: items.data || [], ship: ship.data || [] };
  }, [orderId]);

  if (q.loading || !q.data?.order) return null;
  const { order, items, ship } = q.data;

  const groups = [];
  for (const i of items) {
    const b = i.products?.brands ?? null;
    const id = b?.brand_id ?? 'none';
    let g = groups.find((x) => x.id === id);
    if (!g) {
      g = { id, name: b?.name ?? 'No vendor yet', pickup: b?.pickup_nickname ?? null, items: [] };
      groups.push(g);
    }
    g.items.push(i);
  }
  for (const g of groups) g.ship = ship.find((s) => (s.brand_id ?? 'none') === g.id) ?? null;

  const link = order.track_token
    ? `${typeof window === 'undefined' ? '' : window.location.origin}`
      + `${process.env.NEXT_PUBLIC_BASE_PATH || ''}/track/?t=${order.track_token}`
    : null;

  async function copy() {
    try {
      await navigator.clipboard.writeText(link);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch { setCopied(false); }
  }

  return (
    <div className="card">
      <div className="card-head">
        <h3>How this order travels</h3>
        <span className="small muted">
          {groups.length === 1 ? 'One parcel' : `${groups.length} parcels`}
        </span>
      </div>
      <div className="card-body">
        {groups.length > 1 && (
          <div className="note plain small">
            These pieces come from {groups.length} vendors, so they leave as {groups.length}{' '}
            parcels from {groups.length} addresses and may reach the customer on different
            days. The customer link below says the same thing.
          </div>)}

        <div className="t-wrap"><table className="table">
          <thead><tr>
            <th>Parcel</th><th>From</th><th>Pieces</th><th className="num">Value</th>
            <th>Status</th><th>Tracking</th></tr></thead>
          <tbody>
            {groups.map((g, n) => (
              <tr key={g.id}>
                <td className="small"><strong>{n + 1}</strong></td>
                <td className="small">{g.name}
                  {g.pickup && <div className="faint">{g.pickup}</div>}</td>
                <td className="small">
                  {g.items.map((i) => i.name || i.products?.public_product_name || 'Piece')
                    .join(', ')}</td>
                <td className="num small">
                  {money(g.items.reduce((t, i) =>
                    t + (Number(i.unit_price) || 0) * (Number(i.quantity) || 0), 0))}</td>
                <td><Badge>{g.ship?.status || 'Not booked'}</Badge></td>
                <td className="small">
                  {g.ship?.awb
                    ? (g.ship.tracking_url
                        ? <a href={g.ship.tracking_url} target="_blank" rel="noopener noreferrer">
                            {g.ship.awb}</a>
                        : g.ship.awb)
                    : <span className="muted">—</span>}
                  {g.ship?.delivered_at && (
                    <div className="faint">delivered {when(g.ship.delivered_at)}</div>)}
                </td>
              </tr>))}
            {groups.length === 0 && (
              <tr><td colSpan={6} className="small muted">
                Nothing on this order yet, so there is nothing to send.</td></tr>)}
          </tbody>
        </table></div>

        {link && (
          <div style={{ marginTop: 12 }}>
            <div className="small" style={{ fontWeight: 600, marginBottom: 6 }}>
              The customer's tracking link
            </div>
            <div className="row" style={{ gap: 7 }}>
              <input readOnly value={link} onFocus={(e) => e.target.select()}
                style={{ flex: 1, minWidth: 0 }} />
              <button type="button" className="btn btn-sm" onClick={copy}>
                {copied ? 'Copied' : 'Copy'}</button>
            </div>
            <span className="hint">
              Anyone holding this link sees this order's parcels and nothing else. It shows no
              address, no prices and no vendor names.
            </span>
          </div>)}
      </div>
    </div>
  );
}
