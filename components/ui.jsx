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
  Published: 'b-green', Fulfilled: 'b-green', Won: 'b-green', Connected: 'b-green',
  OptedIn: 'b-green', Allowed: 'b-green', Approved: 'b-green', Running: 'b-green', Done: 'b-green', Customer: 'b-green',
  Review: 'b-amber', Processing: 'b-amber', Negotiation: 'b-amber', Scheduled: 'b-amber',
  'Pending Payment': 'b-amber', Blocked: 'b-amber', Queued: 'b-amber', Paused: 'b-amber',
  Draft: '', Idea: '', Unknown: '', New: 'b-blue', Lead: 'b-blue', Qualified: 'b-blue',
  Proposal: 'b-blue', Opportunity: 'b-blue', Configured: 'b-blue',
  Lost: 'b-red', Failed: 'b-red', Error: 'b-red', OptedOut: 'b-red', DoNotContact: 'b-red', Cancelled: 'b-red',
  Archived: '', Disconnected: '', Completed: 'b-blue',
};
export function Badge({ children }) {
  if (!children) return <span className="faint">—</span>;
  return <span className={`badge ${TONE[children] ?? ''}`}>{children}</span>;
}

export function Stat({ label, value, delta }) {
  return (
    <div className="card stat">
      <div className="label">{label}</div>
      <div className="value">{value}</div>
      {delta && <div className="delta">{delta}</div>}
    </div>
  );
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
        <div>
          <h1 className="page-title">{title}</h1>
          {sub && <div className="page-sub">{sub}</div>}
        </div>
        <div className="row">{actions}</div>
      </div>
      <div className="content">{children}</div>
    </>
  );
}

export function initials(name = '') {
  return name.split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0]).join('').toUpperCase() || '?';
}
