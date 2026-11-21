'use client';
import { useState } from 'react';

// Hand-drawn SVG rather than a charting library: the app is a static export and
// a chart library would cost more download than every page put together. Each
// chart reads the theme, so both modes work without a second palette.
const HUES = ['var(--accent)', 'var(--pos)', 'var(--warn)', 'var(--info)', 'var(--neg)',
              '#8b5cf6', '#06b6d4', '#f59e0b'];

function Tip({ at, children }) {
  if (!at) return null;
  return (
    <div className="chart-tip" style={{ left: at.x, top: at.y }}>{children}</div>
  );
}

// A share of a whole, when the whole is what matters. Slices under a twentieth
// are folded into "other" rather than drawn as unreadable slivers.
export function Donut({ data = [], size = 168, thickness = 26, centre, caption }) {
  const [hover, setHover] = useState(null);
  const clean = data.filter((d) => Number(d.value) > 0);
  const total = clean.reduce((s, d) => s + Number(d.value), 0);
  if (!total) {
    return <div className="small faint" style={{ padding: 20, textAlign: 'center' }}>
      Nothing to show yet.</div>;
  }
  const big = clean.filter((d) => d.value / total >= 0.05);
  const rest = clean.filter((d) => d.value / total < 0.05);
  const slices = rest.length
    ? [...big, { label: `Other (${rest.length})`, value: rest.reduce((s, d) => s + d.value, 0) }]
    : big;

  const r = (size - thickness) / 2;
  const c = size / 2;
  let angle = -Math.PI / 2;
  const arcs = slices.map((d, i) => {
    const share = d.value / total;
    const sweep = share * Math.PI * 2;
    const x1 = c + r * Math.cos(angle), y1 = c + r * Math.sin(angle);
    angle += sweep;
    const x2 = c + r * Math.cos(angle), y2 = c + r * Math.sin(angle);
    return { d, i, share,
      path: `M ${x1} ${y1} A ${r} ${r} 0 ${sweep > Math.PI ? 1 : 0} 1 ${x2} ${y2}` };
  });

  return (
    <div className="chart-donut">
      <svg width={size} height={size} role="img"
        aria-label={slices.map((s) => `${s.label}: ${s.value}`).join(', ')}>
        {arcs.map(({ d, i, path, share }) => (
          <path key={i} d={path} fill="none" strokeWidth={hover === i ? thickness + 4 : thickness}
            stroke={d.colour || HUES[i % HUES.length]} strokeLinecap="butt"
            onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)}
            style={{ transition: 'stroke-width .15s var(--ease)', cursor: 'default' }}>
            <title>{`${d.label}: ${d.display ?? d.value} (${Math.round(share * 100)}%)`}</title>
          </path>))}
        {centre && (
          <>
            <text x={c} y={c - 2} textAnchor="middle" className="donut-value">{centre.value}</text>
            <text x={c} y={c + 15} textAnchor="middle" className="donut-label">{centre.label}</text>
          </>)}
      </svg>
      <div className="chart-legend">
        {arcs.map(({ d, i, share }) => (
          <div key={i} className={`legend-row ${hover === i ? 'on' : ''}`}
            onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)}>
            <b style={{ background: d.colour || HUES[i % HUES.length] }} />
            <span className="legend-name">{d.label}</span>
            <span className="legend-val">{d.display ?? d.value}</span>
            <span className="legend-pct">{Math.round(share * 100)}%</span>
          </div>))}
      </div>
      {caption && <div className="small faint" style={{ marginTop: 6 }}>{caption}</div>}
    </div>
  );
}

// A line over time, with the area under it filled so a flat stretch still reads
// as a quantity rather than an empty chart.
export function Trend({ points = [], height = 150, format = (n) => n, caption }) {
  const [at, setAt] = useState(null);
  if (points.length < 2) {
    return <div className="small faint" style={{ padding: 20, textAlign: 'center' }}>
      Not enough history yet — this fills in as orders come through.</div>;
  }
  const w = 560, pad = 8;
  const max = Math.max(...points.map((p) => p.value), 1);
  const step = (w - pad * 2) / (points.length - 1);
  const y = (v) => height - pad - (v / max) * (height - pad * 2 - 14);
  const xs = points.map((_, i) => pad + i * step);
  const line = points.map((p, i) => `${i ? 'L' : 'M'} ${xs[i]} ${y(p.value)}`).join(' ');
  const area = `${line} L ${xs[xs.length - 1]} ${height - pad} L ${xs[0]} ${height - pad} Z`;

  return (
    <div className="chart-wrap">
      <svg viewBox={`0 0 ${w} ${height}`} className="chart-svg" role="img"
        aria-label={`${points.length} points, highest ${format(max)}`}
        onMouseLeave={() => setAt(null)}>
        <defs>
          <linearGradient id="trendfill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="var(--accent)" stopOpacity=".22" />
            <stop offset="100%" stopColor="var(--accent)" stopOpacity="0" />
          </linearGradient>
        </defs>
        <path d={area} fill="url(#trendfill)" />
        <path d={line} fill="none" stroke="var(--accent)" strokeWidth="2"
          strokeLinejoin="round" strokeLinecap="round" />
        {points.map((p, i) => (
          <g key={i}>
            <circle cx={xs[i]} cy={y(p.value)} r={at?.i === i ? 4 : 2.5}
              fill="var(--accent)" style={{ transition: 'r .12s var(--ease)' }} />
            <rect x={xs[i] - step / 2} y="0" width={step} height={height} fill="transparent"
              onMouseEnter={() => setAt({ i, x: xs[i], y: y(p.value) })} />
          </g>))}
        {at && <line x1={at.x} y1={pad} x2={at.x} y2={height - pad}
          stroke="var(--line)" strokeDasharray="3 3" />}
      </svg>
      <div className="row small faint" style={{ justifyContent: 'space-between', marginTop: 2 }}>
        <span>{points[0].label}</span>
        {at && <span style={{ color: 'var(--ink)', fontWeight: 600 }}>
          {points[at.i].label}: {format(points[at.i].value)}</span>}
        <span>{points[points.length - 1].label}</span>
      </div>
      {caption && <div className="small faint" style={{ marginTop: 4 }}>{caption}</div>}
    </div>
  );
}

// Ranked bars. Better than a pie whenever the order matters more than the share.
export function Bars({ data = [], format = (n) => n, caption, max: given }) {
  const rows = data.filter((d) => d.value != null);
  if (!rows.length) {
    return <div className="small faint" style={{ padding: 16, textAlign: 'center' }}>
      Nothing to rank yet.</div>;
  }
  const max = given ?? Math.max(...rows.map((d) => Number(d.value)), 1);
  return (
    <div className="stack" style={{ gap: 7 }}>
      {rows.map((d, i) => (
        <div key={d.label + i}>
          <div className="row small" style={{ justifyContent: 'space-between', marginBottom: 2 }}>
            <span className="legend-name">{d.label}</span>
            <span style={{ fontWeight: 600 }}>{d.display ?? format(d.value)}</span>
          </div>
          <div className="bar"><span style={{
            width: `${Math.max(2, (Number(d.value) / max) * 100)}%`,
            background: d.colour || 'var(--accent)' }} /></div>
          {d.note && <div className="small faint" style={{ marginTop: 1 }}>{d.note}</div>}
        </div>))}
      {caption && <div className="small faint">{caption}</div>}
    </div>
  );
}
