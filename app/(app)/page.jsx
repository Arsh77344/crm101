'use client';
import { useState } from 'react';
import Link from 'next/link';
import { useQuery } from '@/lib/db';
import { Page, Stat, Badge, Empty, Loading, ErrorNote, Spark, money, when } from '@/components/ui';

const DAY = 864e5;

export default function Dashboard() {
  const [range, setRange] = useState(30);
  const q = useQuery(async (c) => {
    const r = await Promise.all([
      c.from('orders').select('*,contacts(full_name)').order('ordered_at', { ascending: false }).limit(300),
      c.from('order_items').select('quantity,unit_price,order_id,products(cost_price,public_product_name)'),
      c.from('opportunities').select('stage,estimated_value'),
      c.from('products').select('product_id,status,stock_qty,public_product_name,retail_price,cost_price'),
      c.from('campaigns').select('*'),
      c.from('campaign_posts').select('*').gte('scheduled_for', new Date().toISOString()).order('scheduled_for').limit(5),
      c.from('contacts').select('contact_id,created_at,lifecycle_stage'),
      c.from('shipments').select('status,shipped_at,orders(order_number)'),
      c.from('payments').select('amount,fee,status,paid_at,created_at'),
      c.from('expenses').select('amount,spent_on,category'),
      c.from('tasks').select('*').neq('status', 'Done').order('due_on').limit(6),
      c.from('returns').select('resolution,amount,opened_on'),
      c.from('payables').select('amount,status'),
    ]);
    const bad = r.find((x) => x.error);
    if (bad) throw bad.error;
    const [orders, items, deals, products, campaigns, posts, contacts, shipments, payments, expenses, tasks, returns, payables] = r;
    return {
      orders: orders.data || [], items: items.data || [], deals: deals.data || [], products: products.data || [],
      campaigns: campaigns.data || [], posts: posts.data || [], contacts: contacts.data || [],
      shipments: shipments.data || [], payments: payments.data || [], expenses: expenses.data || [],
      tasks: tasks.data || [], returns: returns.data || [], payables: payables.data || [],
    };
  }, []);

  if (q.loading) return <Page title="Today"><Loading /></Page>;
  if (q.error) return <Page title="Today"><ErrorNote error={q.error} /></Page>;
  const d = q.data;

  const now = Date.now();
  const sold = d.orders.filter((o) => ['Fulfilled', 'Processing'].includes(o.order_status));
  const win = (list, field, from, to) => list.filter((x) => {
    const t = new Date(x[field]).getTime();
    return t >= from && t < to;
  });

  const R = range * DAY;
  const rev30 = win(sold, 'ordered_at', now - R, now).reduce((s, o) => s + Number(o.total || 0), 0);
  const revPrev = win(sold, 'ordered_at', now - 2 * R, now - R).reduce((s, o) => s + Number(o.total || 0), 0);
  const ord30 = win(sold, 'ordered_at', now - R, now).length;
  const aov = ord30 ? rev30 / ord30 : 0;

  // "Cost" here is what the brand partner is owed on each line, not stock you bought.
  const cogsByOrder = {};
  d.items.forEach((i) => {
    cogsByOrder[i.order_id] = (cogsByOrder[i.order_id] || 0) + Number(i.products?.cost_price || 0) * Number(i.quantity || 0);
  });
  const soldRecent = win(sold, 'ordered_at', now - R, now);
  const cogs30 = soldRecent.reduce((s, o) => s + (cogsByOrder[o.order_id] || 0), 0);
  const margin = rev30 ? Math.round(((rev30 - cogs30) / rev30) * 100) : null;

  const byCustomer = {};
  sold.forEach((o) => { if (o.contact_id) byCustomer[o.contact_id] = (byCustomer[o.contact_id] || 0) + 1; });
  const buyers = Object.keys(byCustomer).length;
  const repeat = buyers ? Math.round((Object.values(byCustomer).filter((n) => n > 1).length / buyers) * 100) : 0;

  const spend30 = win(d.expenses, 'spent_on', now - R, now).reduce((s, e) => s + Number(e.amount || 0), 0);
  const collected = d.payments.filter((p) => ['Paid', 'Settled'].includes(p.status));
  const awaiting = d.payments.filter((p) => ['Created', 'Link sent'].includes(p.status))
    .reduce((s, p) => s + Number(p.amount || 0), 0);

  const openDeals = d.deals.filter((o) => !['Won', 'Lost'].includes(o.stage));
  const owedNow = (d.payables || []).filter((p) => ['Accrued', 'Approved'].includes(p.status))
    .reduce((s, p) => s + Number(p.amount || 0), 0);
  const lowStock = d.products.filter((p) => p.status === 'Published'
    && ['Limited', 'Unavailable'].includes(p.availability));
  const moving = d.shipments.filter((s) => ['Booked', 'Picked up', 'In transit', 'Out for delivery'].includes(s.status));
  const unbooked = d.shipments.filter((s) => s.status === 'Not booked');
  const openReturns = d.returns.filter((r) => r.resolution === 'Pending');
  const overdue = d.tasks.filter((t) => t.due_on && new Date(t.due_on) < new Date());
  const live = d.campaigns.filter((c) => ['Running', 'Scheduled'].includes(c.status));

  const bucket = Math.max(1, Math.round(range / 8));
  const weeks = Array.from({ length: 8 }, (_, i) => {
    const to = now - i * bucket * DAY;
    return win(sold, 'ordered_at', to - bucket * DAY, to).reduce((s, o) => s + Number(o.total || 0), 0);
  }).reverse();

  const change = revPrev ? Math.round(((rev30 - revPrev) / revPrev) * 100) : null;

  const unitsByProduct = {};
  d.items.forEach((i) => {
    const n = i.products?.public_product_name;
    if (n) unitsByProduct[n] = (unitsByProduct[n] || 0) + Number(i.quantity || 0) * Number(i.unit_price || 0);
  });
  const top = Object.entries(unitsByProduct).sort((a, b) => b[1] - a[1]).slice(0, 5);
  const topMax = Math.max(1, ...top.map((t) => t[1]));

  return (
    <Page title="Today" sub="The numbers that decide what to do next."
      actions={<>
        <div className="pill-row">
          {[7, 30, 90].map((n) => (
            <button key={n} className={`chip ${range === n ? 'on' : ''}`} onClick={() => setRange(n)}>{n}d</button>))}
        </div>
        <Link className="btn btn-primary" href="/launch">Launch a product</Link>
      </>}>

      <div className="kpi-row" style={{ marginBottom: 12 }}>
        <Stat label={`Revenue · ${range} days`} value={money(rev30)} spark={weeks}
          delta={change === null ? `${ord30} orders` : `${change >= 0 ? '+' : ''}${change}% vs previous ${range}`}
          tone={change === null ? '' : change >= 0 ? 'up' : 'down'} />
        <Stat label="Average order" value={money(aov)} delta={`${ord30} orders in ${range} days`} />
        <Stat label="Contribution" value={margin === null ? '—' : `${margin}%`}
          delta={cogs30 ? `${money(rev30 - cogs30)} after partner costs` : 'Add agreed costs to see this'} />
        <Stat label="Repeat buyers" value={`${repeat}%`} delta={`${buyers} customers have ordered`} />
        <Stat label={`Spent · ${range} days`} value={money(spend30)}
          delta={rev30 ? `${Math.round((spend30 / rev30) * 100)}% of revenue` : ''} />
        <Stat label="Awaiting payment" value={money(awaiting)}
          delta={`${d.payments.filter((p) => p.status === 'Link sent').length} links unpaid`} />
      </div>

      <div className="kpi-row" style={{ marginBottom: 16 }}>
        <Stat label="Open pipeline" value={money(openDeals.reduce((s, o) => s + Number(o.estimated_value || 0), 0))}
          delta={`${openDeals.length} deals`} />
        <Stat label="Owed to partners" value={money(owedNow)} delta="accrued on sales, unpaid" />
        <Stat label="Parcels moving" value={moving.length}
          delta={unbooked.length ? `${unbooked.length} still unbooked` : 'all booked'}
          tone={unbooked.length ? 'down' : ''} />
        <Stat label="Open returns" value={openReturns.length}
          delta={openReturns.length ? money(openReturns.reduce((s, r) => s + Number(r.amount || 0), 0)) : 'none'} />
        <Stat label="Tasks open" value={d.tasks.length}
          delta={overdue.length ? `${overdue.length} overdue` : 'nothing overdue'}
          tone={overdue.length ? 'down' : ''} />
        <Stat label="Hard to get" value={lowStock.length}
          delta={lowStock.length ? 'check with the partner' : 'all available'}
          tone={lowStock.length ? 'down' : ''} />
      </div>

      <div className="grid g2">
        <div className="card">
          <div className="card-head"><h3>Recent orders</h3><Link className="link small" href="/orders">All orders</Link></div>
          {d.orders.length === 0 ? <Empty title="No orders yet" /> : (
            <div className="t-wrap"><table className="table">
              <thead><tr><th>Order</th><th>Customer</th><th>Status</th><th className="num">Total</th></tr></thead>
              <tbody>{d.orders.slice(0, 6).map((o) => (
                <tr key={o.order_id}>
                  <td>{o.order_number}<div className="small faint">{when(o.ordered_at)}</div></td>
                  <td>{o.contacts?.full_name || '—'}</td>
                  <td><Badge>{o.order_status}</Badge></td>
                  <td className="num">{money(o.total)}</td>
                </tr>))}</tbody></table></div>)}
        </div>

        <div className="card">
          <div className="card-head"><h3>Best sellers</h3><Link className="link small" href="/products">Products</Link></div>
          <div className="card-body stack">
            {top.length === 0 && <div className="small muted">No sales recorded yet.</div>}
            {top.map(([name, value]) => (
              <div key={name}>
                <div className="row small"><span style={{ flex: 1 }}>{name}</span>
                  <span className="muted num">{money(value)}</span></div>
                <div className="bar" style={{ marginTop: 3 }}><span style={{ width: `${(value / topMax) * 100}%` }} /></div>
              </div>))}
          </div>
        </div>

        <div className="card">
          <div className="card-head"><h3>Needs you</h3><Link className="link small" href="/tasks">All tasks</Link></div>
          <div className="card-body stack" style={{ gap: 10 }}>
            {d.tasks.length === 0 && <div className="small muted">Nothing waiting on you.</div>}
            {d.tasks.map((t) => (
              <div key={t.task_id} className="row" style={{ alignItems: 'flex-start' }}>
                <div style={{ flex: 1 }}>
                  <div style={{ fontWeight: 500 }}>{t.title}</div>
                  <div className="small faint">{t.detail?.slice(0, 70)}</div>
                </div>
                <div style={{ textAlign: 'right' }}>
                  <Badge>{t.priority}</Badge>
                  <div className="small faint">{t.due_on ? when(t.due_on) : ''}</div>
                </div>
              </div>))}
            {lowStock.length > 0 && (
              <div className="note small">
                Limited or unavailable: {lowStock.map((p) => p.public_product_name).join(', ')}.{' '}
                <Link className="link" href="/brands">Check with the partner</Link>
              </div>)}
            {unbooked.length > 0 && (
              <div className="note warn small">
                {unbooked.length} order{unbooked.length === 1 ? '' : 's'} paid but not booked with a courier.{' '}
                <Link className="link" href="/shipments">Book them</Link>
              </div>)}
          </div>
        </div>

        <div className="card">
          <div className="card-head"><h3>Marketing</h3><Link className="link small" href="/campaigns">Campaigns</Link></div>
          <div className="card-body stack">
            {live.length === 0 && <div className="small muted">No campaign is running.</div>}
            {live.map((c) => {
              const pct = c.budget ? Math.min(100, Math.round((Number(c.spend || 0) / Number(c.budget)) * 100)) : 0;
              return (
                <div key={c.campaign_id}>
                  <div className="row"><Link className="link small" href={`/campaigns?id=${c.campaign_id}`}>{c.campaign_name}</Link>
                    <span className="spacer" /><span className="small muted">{money(c.spend)} / {money(c.budget)}</span></div>
                  <div className="bar" style={{ marginTop: 3 }}><span style={{ width: `${pct}%` }} /></div>
                </div>);
            })}
            {d.posts.length > 0 && (
              <>
                <div className="small faint" style={{ marginTop: 4 }}>Next out the door</div>
                {d.posts.slice(0, 3).map((p) => (
                  <div className="row small" key={p.post_id}>
                    <span style={{ flex: 1 }}>{p.title}</span>
                    <span className="faint">{when(p.scheduled_for)}</span>
                  </div>))}
              </>)}
          </div>
        </div>
      </div>
    </Page>
  );
}
