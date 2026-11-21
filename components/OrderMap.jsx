'use client';
import { useMemo, useState } from 'react';
import { locate, project, BOX } from '@/lib/places';
import { money } from '@/components/ui';
import { Bars } from '@/components/Charts';

// Where the orders come from. Each dot is a place, sized by how much has been
// bought there and shaded by how recent it is. Drawn from coordinates, with the
// grid standing in for a coastline: a borrowed map image would be prettier and
// would not be ours to use.
const W = 520, H = 560;

export default function OrderMap({ orders = [], shipments = [] }) {
  const [hover, setHover] = useState(null);

  const { dots, unplaced, byState, total } = useMemo(() => {
    const places = new Map();
    const states = new Map();
    let missed = 0, sum = 0;

    for (const o of orders) {
      const city = o.ship_city || o.shipments?.[0]?.address_city || null;
      const state = o.ship_state || null;
      const value = Number(o.total || 0);
      sum += value;
      if (state) {
        const s = states.get(state) || { label: state, value: 0, orders: 0 };
        s.value += value; s.orders += 1; states.set(state, s);
      }
      const found = locate(city, state);
      if (!found) { missed += 1; continue; }
      const name = city || state;
      const k = `${found.at[0]},${found.at[1]}`;
      const p = places.get(k) || { name, at: found.at, how: found.how, orders: 0, value: 0, last: null };
      p.orders += 1; p.value += value;
      const when = o.ordered_at ? new Date(o.ordered_at).getTime() : null;
      if (when && (!p.last || when > p.last)) p.last = when;
      places.set(k, p);
    }
    return {
      dots: [...places.values()].sort((a, b) => b.value - a.value),
      unplaced: missed, total: sum,
      byState: [...states.values()].sort((a, b) => b.value - a.value).slice(0, 8),
    };
  }, [orders]);

  const moving = shipments.filter((s) =>
    ['Booked', 'Pickup scheduled', 'Picked up', 'In transit', 'Out for delivery']
      .includes(s.status));

  const biggest = Math.max(...dots.map((d) => d.value), 1);
  const now = Date.now();
  const heat = (d) => {
    if (!d.last) return 0.35;
    const days = (now - d.last) / 86400000;
    return days < 14 ? 1 : days < 45 ? 0.72 : days < 120 ? 0.5 : 0.32;
  };

  if (!orders.length) {
    return <div className="small faint" style={{ padding: 24, textAlign: 'center' }}>
      No orders yet, so there is nowhere to put on the map.</div>;
  }

  return (
    <div className="map-wrap">
      <div className="map-plot">
        <svg viewBox={`0 0 ${W} ${H}`} className="chart-svg" role="img"
          aria-label={`Orders from ${dots.length} places`}>
          <rect x="0" y="0" width={W} height={H} rx="10" className="map-bg" />
          {/* Degrees of latitude and longitude, so a dot can be read as a place. */}
          {[10, 15, 20, 25, 30, 35].map((lat) => {
            const [, y] = project(lat, BOX.west, W, H);
            return (<g key={lat}>
              <line x1="0" y1={y} x2={W} y2={y} className="map-grid" />
              <text x="4" y={y - 3} className="map-tick">{lat}°N</text>
            </g>);
          })}
          {[70, 75, 80, 85, 90, 95].map((lon) => {
            const [x] = project(BOX.north, lon, W, H);
            return (<g key={lon}>
              <line x1={x} y1="0" x2={x} y2={H} className="map-grid" />
              <text x={x + 3} y={H - 5} className="map-tick">{lon}°E</text>
            </g>);
          })}
          {dots.map((d) => {
            const [x, y] = project(d.at[0], d.at[1], W, H);
            const r = 5 + Math.sqrt(d.value / biggest) * 22;
            const on = hover === d.name;
            return (
              <g key={d.name} onMouseEnter={() => setHover(d.name)}
                 onMouseLeave={() => setHover(null)}>
                <circle cx={x} cy={y} r={r} className="map-dot"
                  style={{ opacity: heat(d), strokeWidth: on ? 2 : 1 }} />
                <circle cx={x} cy={y} r="2" className="map-core" />
                {(on || d.value > biggest * 0.25) && (
                  <text x={x} y={y - r - 5} textAnchor="middle" className="map-name">
                    {d.name}</text>)}
                <title>{`${d.name}: ${d.orders} order${d.orders === 1 ? '' : 's'}, `
                  + `${money(d.value)}${d.how === 'state' ? ' (placed by state)' : ''}`}</title>
              </g>);
          })}
        </svg>
        <div className="row small faint wrap" style={{ gap: 10, marginTop: 6 }}>
          <span>Dot size is money spent there.</span>
          <span>Fainter means longer since the last order.</span>
          {unplaced > 0 && (
            <span style={{ color: 'var(--warn)' }}>
              {unplaced} order{unplaced === 1 ? '' : 's'} had no city we could place.
            </span>)}
        </div>
      </div>

      <div className="stack" style={{ gap: 14 }}>
        <div>
          <div className="small" style={{ fontWeight: 600, marginBottom: 7 }}>
            Where the money comes from
          </div>
          <Bars data={byState.map((s) => ({
            label: s.label, value: s.value, display: money(s.value),
            note: `${s.orders} order${s.orders === 1 ? '' : 's'}`,
          }))} caption={byState.length ? `${money(total)} across ${orders.length} orders.` : ''} />
        </div>
        <div>
          <div className="small" style={{ fontWeight: 600, marginBottom: 7 }}>
            On the road right now
          </div>
          {moving.length === 0
            ? <div className="small faint">Nothing in transit.</div>
            : <div className="stack" style={{ gap: 6 }}>
                {moving.slice(0, 6).map((s) => (
                  <div key={s.shipment_id} className="row small" style={{ gap: 8 }}>
                    <span className="badge b-amber">{s.status}</span>
                    <span className="legend-name">{s.address_city || 'Unknown city'}</span>
                    {s.awb && <span className="mono faint">{s.awb}</span>}
                  </div>))}
                {moving.length > 6 && (
                  <div className="small faint">and {moving.length - 6} more.</div>)}
              </div>}
        </div>
      </div>
    </div>
  );
}
