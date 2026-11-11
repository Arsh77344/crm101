'use client';
export function money(n, currency = 'INR') {
  if (n === null || n === undefined || n === '') return '—';
  const v = Number(n);
  if (Number.isNaN(v)) return '—';
  const sym = { INR: '₹', USD: '$', GBP: '£', EUR: '€' }[currency] || '';
  return sym + v.toLocaleString('en-IN', { maximumFractionDigits: 0 });
}
export function when(d, withTime = false) {
  if (!d) return '—';
  const dt = new Date(d);
  if (Number.isNaN(dt.getTime())) return '—';
  return dt.toLocaleDateString('en-GB', {
    day: 'numeric', month: 'short', year: 'numeric',
    ...(withTime ? { hour: '2-digit', minute: '2-digit' } : {}),
  });
}
const TONE = {
  Published: 'b-green', Fulfilled: 'b-green', Won: 'b-green', Connected: 'b-green', Delivered: 'b-green',
  OptedIn: 'b-green', Allowed: 'b-green', Approved: 'b-green', Running: 'b-green', Done: 'b-green',
  Customer: 'b-green', Paid: 'b-green', Settled: 'b-green', Active: 'b-green', Received: 'b-green',
  Review: 'b-amber', Processing: 'b-amber', Negotiation: 'b-amber', Scheduled: 'b-amber', Doing: 'b-amber',
  'Pending Payment': 'b-amber', Blocked: 'b-amber', Queued: 'b-amber', Paused: 'b-amber', 'Link sent': 'b-amber',
  'In transit': 'b-amber', 'Out for delivery': 'b-amber', 'On loom': 'b-amber', Finishing: 'b-amber', Exchange: 'b-amber',
  Draft: '', Idea: '', Unknown: '', 'To do': '', 'Not booked': '', Pending: '', Normal: '', Low: '',
  New: 'b-blue', Lead: 'b-blue', Qualified: 'b-blue', Proposal: 'b-blue', Opportunity: 'b-blue',
  Configured: 'b-blue', Completed: 'b-blue', Booked: 'b-blue', 'Picked up': 'b-blue', Created: 'b-blue',
  Commissioned: 'b-blue', High: 'b-amber', Urgent: 'b-red',
  Lost: 'b-red', Failed: 'b-red', Error: 'b-red', OptedOut: 'b-red', DoNotContact: 'b-red',
  Cancelled: 'b-red', RTO: 'b-red', Refunded: 'b-red', Rejected: 'b-red', Archived: '', Disconnected: '',
};
export function Badge({ children }) {
  if (children === null || children === undefined || children === '') return <span className="faint">—</span>;
  return <span className={`badge ${TONE[children] ?? ''}`}>{children}</span>;
}
export function Stat({ label, value, delta, tone, spark }) {
  return (
    <div className="card stat">
      <div className="label">{label}</div>
      <div className="value">{value}</div>
      {delta && <div className={`delta ${tone || ''}`}>{delta}</div>}
      {spark && <Spark values={spark} />}
    </div>
  );
}

export function Spark({ values = [] }) {
  const max = Math.max(1, ...values);
  return (
    <div className="spark" style={{ marginTop: 8 }}>
      {values.map((v, i) => (
        <i key={i} className={i === values.length - 1 ? 'hi' : ''}
           style={{ height: `${Math.max(4, (v / max) * 100)}%` }} />
      ))}
    </div>
  );
}

export function pct(now, before) {
  if (!before) return null;
  const change = Math.round(((now - before) / before) * 100);
  return { text: `${change >= 0 ? '+' : ''}${change}% vs previous`, tone: change >= 0 ? 'up' : 'down' };
}
export function Empty({ title, hint, children }) {
  return (
    <div className="empty">
      <div className="big">{title}</div>
      {hint && <div className="small">{hint}</div>}
      {children && <div style={{ marginTop: 14 }}>{children}</div>}
    </div>
  );
}
export function Page({ title, sub, actions, children }) {
  return (
    <>
      <div className="topbar">
        <div><h1 className="page-title">{title}</h1>{sub && <div className="page-sub">{sub}</div>}</div>
        <div className="row">{actions}</div>
      </div>
      <div className="content">{children}</div>
    </>
  );
}
export function initials(name = '') {
  return (name || '').split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0]).join('').toUpperCase() || '?';
}
export function Loading() { return <div className="loading">Loading…</div>; }
export function ErrorNote({ error }) {
  if (!error) return null;
  return <div className="note warn" style={{ marginBottom: 14 }}>{error}</div>;
}
