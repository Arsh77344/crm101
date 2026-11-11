'use client';
import { useQuery } from '@/lib/db';
import { Page, Stat, Loading, ErrorNote, money } from '@/components/ui';

export default function Finance() {
  const q = useQuery(async (c) => {
    const [payments, expenses, orders, shipments, margin, payables, returns] = await Promise.all([
      c.from('payments').select('amount,fee,status,created_at,paid_at'),
      c.from('expenses').select('amount,category,spent_on'),
      c.from('orders').select('total,order_status,ordered_at'),
      c.from('shipments').select('shipping_cost'),
      c.from('line_margin').select('revenue,payable,contribution,order_status,ordered_at,brand_name'),
      c.from('payables').select('amount,status'),
      c.from('returns').select('amount,reverse_logistics_cost,resolution'),
    ]);
    if (payments.error) throw payments.error;
    return { payments: payments.data || [], expenses: expenses.data || [],
      orders: orders.data || [], shipments: shipments.data || [],
      margin: margin.data || [], payables: payables.data || [], returns: returns.data || [] };
  }, []);

  if (q.loading) return <Page title="Profit & loss"><Loading /></Page>;
  if (q.error) return <Page title="Profit & loss"><ErrorNote error={q.error} /></Page>;
  const d = q.data;

  const months = [];
  for (let i = 5; i >= 0; i--) {
    const dt = new Date(); dt.setDate(1); dt.setMonth(dt.getMonth() - i);
    months.push({ key: `${dt.getFullYear()}-${dt.getMonth()}`, label: dt.toLocaleDateString('en-GB', { month: 'short' }), y: dt.getFullYear(), m: dt.getMonth() });
  }
  const inMonth = (dstr, mo) => {
    if (!dstr) return false;
    const dt = new Date(dstr);
    return dt.getFullYear() === mo.y && dt.getMonth() === mo.m;
  };

  const collected = d.payments.filter((p) => ['Paid', 'Settled'].includes(p.status));
  const income = collected.reduce((s, p) => s + Number(p.amount || 0), 0);
  const fees = d.payments.reduce((s, p) => s + Number(p.fee || 0), 0);
  const spend = d.expenses.reduce((s, e) => s + Number(e.amount || 0), 0);
  const courier = d.shipments.reduce((s, x) => s + Number(x.shipping_cost || 0), 0);
  const sold = (d.margin || []).filter((m) => ['Fulfilled', 'Processing'].includes(m.order_status));
  const grossRevenue = sold.reduce((s, m) => s + Number(m.revenue || 0), 0);
  const owedOnSold = sold.reduce((s, m) => s + Number(m.payable || 0), 0);
  const contribution = sold.reduce((s, m) => s + Number(m.contribution || 0), 0);
  const contribPct = grossRevenue ? Math.round((contribution / grossRevenue) * 100) : null;
  const owedNow = (d.payables || []).filter((p) => ['Accrued', 'Approved'].includes(p.status))
    .reduce((s, p) => s + Number(p.amount || 0), 0);
  const returnShipping = (d.returns || []).reduce((s, r) => s + Number(r.reverse_logistics_cost || 0), 0);
  const profit = income - fees - spend - returnShipping;

  const byBrand = {};
  sold.forEach((m) => {
    const k = m.brand_name || 'Unassigned';
    byBrand[k] = byBrand[k] || { revenue: 0, contribution: 0 };
    byBrand[k].revenue += Number(m.revenue || 0);
    byBrand[k].contribution += Number(m.contribution || 0);
  });
  const brandPeak = Math.max(1, ...Object.values(byBrand).map((b) => b.revenue));

  const byCat = {};
  d.expenses.forEach((e) => { byCat[e.category] = (byCat[e.category] || 0) + Number(e.amount || 0); });
  const maxCat = Math.max(1, ...Object.values(byCat));

  const rowsByMonth = months.map((mo) => {
    const inc = collected.filter((p) => inMonth(p.paid_at || p.created_at, mo)).reduce((s, p) => s + Number(p.amount || 0), 0);
    const out = d.expenses.filter((e) => inMonth(e.spent_on, mo)).reduce((s, e) => s + Number(e.amount || 0), 0);
    return { ...mo, inc, out, net: inc - out };
  });
  const peak = Math.max(1, ...rowsByMonth.map((r) => Math.max(r.inc, r.out)));

  return (
    <Page title="Profit & loss" sub="Money in against money out, from the records in this workspace.">
      <div className="kpi-row" style={{ marginBottom: 12 }}>
        <Stat label="Money collected" value={money(income)} delta={`${collected.length} payments`} />
        <Stat label="Owed to partners" value={money(owedNow)} delta="accrued, not yet paid" />
        <Stat label="Contribution" value={money(contribution)}
          delta={contribPct === null ? 'sales less what partners are owed' : `${contribPct}% of what you charged`} />
        <Stat label="Gateway fees" value={money(fees)} />
        <Stat label="Return shipping" value={money(returnShipping)} delta="borne by you" />
        <Stat label="Net" value={money(profit)}
          delta={income ? `${Math.round((profit / income) * 100)}% of collections` : ''} />
      </div>

      <div className="note plain small" style={{ marginBottom: 16 }}>
        You hold no stock, so nothing is tied up in inventory. A partner is owed only once a piece is
        fulfilled, and a return reverses it — though the return shipping stays with you.
      </div>

      <div className="grid g2">
        <div className="card">
          <div className="card-head"><h3>Last six months</h3></div>
          <div className="card-body stack">
            {rowsByMonth.map((r) => (
              <div key={r.key}>
                <div className="row small"><strong>{r.label}</strong><span className="spacer" />
                  <span className="muted">in {money(r.inc)} · out {money(r.out)}</span>
                  <strong style={{ marginLeft: 10, color: r.net >= 0 ? 'var(--green)' : 'var(--red)' }}>{money(r.net)}</strong>
                </div>
                <div className="bar" style={{ marginTop: 4 }}><span style={{ width: `${(r.inc / peak) * 100}%`, background: 'var(--green)' }} /></div>
                <div className="bar" style={{ marginTop: 3 }}><span style={{ width: `${(r.out / peak) * 100}%`, background: 'var(--accent)' }} /></div>
              </div>))}
          </div>
        </div>

        <div className="card">
          <div className="card-head"><h3>Contribution by brand</h3></div>
          <div className="card-body stack">
            {Object.keys(byBrand).length === 0 && <div className="small muted">No fulfilled sales yet.</div>}
            {Object.entries(byBrand).sort((a, b) => b[1].revenue - a[1].revenue).map(([name, v]) => (
              <div key={name}>
                <div className="row small"><span style={{ flex: 1 }}>{name}</span>
                  <span className="muted">{money(v.revenue)} in</span>
                  <strong style={{ marginLeft: 10, color: 'var(--pos)' }}>{money(v.contribution)} kept</strong></div>
                <div className="bar" style={{ marginTop: 3 }}>
                  <span style={{ width: `${(v.revenue / brandPeak) * 100}%` }} /></div>
              </div>))}
          </div>
        </div>

        <div className="card">
          <div className="card-head"><h3>Where the money goes</h3></div>
          <div className="card-body stack">
            {Object.keys(byCat).length === 0 && <div className="small muted">No expenses recorded yet.</div>}
            {Object.entries(byCat).sort((a, b) => b[1] - a[1]).map(([cat, amt]) => (
              <div key={cat}>
                <div className="row small"><span>{cat}</span><span className="spacer" />
                  <span className="muted">{money(amt)}</span></div>
                <div className="bar"><span style={{ width: `${(amt / maxCat) * 100}%` }} /></div>
              </div>))}
            {courier > 0 && <div className="small faint" style={{ marginTop: 6 }}>Courier costs logged on shipments: {money(courier)}</div>}
          </div>
        </div>
      </div>
    </Page>
  );
}
