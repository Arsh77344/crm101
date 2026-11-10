'use client';
import { useQuery } from '@/lib/db';
import { Page, Stat, Loading, ErrorNote, money } from '@/components/ui';

export default function Finance() {
  const q = useQuery(async (c) => {
    const [payments, expenses, orders, shipments] = await Promise.all([
      c.from('payments').select('amount,fee,status,created_at,paid_at'),
      c.from('expenses').select('amount,category,spent_on'),
      c.from('orders').select('total,order_status,ordered_at'),
      c.from('shipments').select('shipping_cost'),
    ]);
    if (payments.error) throw payments.error;
    return { payments: payments.data || [], expenses: expenses.data || [],
      orders: orders.data || [], shipments: shipments.data || [] };
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
  const profit = income - fees - spend;

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
      <div className="kpi-row" style={{ marginBottom: 18 }}>
        <Stat label="Money collected" value={money(income)} delta={`${collected.length} payments`} />
        <Stat label="Money spent" value={money(spend)} delta={`${d.expenses.length} expenses`} />
        <Stat label="Gateway fees" value={money(fees)} />
        <Stat label="Net" value={money(profit)} delta={income ? `${Math.round((profit / income) * 100)}% margin` : ''} />
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
