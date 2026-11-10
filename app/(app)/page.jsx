'use client';
import Link from 'next/link';
import { useQuery } from '@/lib/db';
import { Page, Stat, Badge, Empty, Loading, ErrorNote, money, when } from '@/components/ui';

export default function Dashboard() {
  const q = useQuery(async (c) => {
    const [orders, deals, products, campaigns, posts, jobs, contacts, shipments, payments, expenses, tasks] =
      await Promise.all([
        c.from('orders').select('*,contacts(full_name)').order('ordered_at', { ascending: false }).limit(50),
        c.from('opportunities').select('*'),
        c.from('products').select('product_id,status,stock_qty,public_product_name,retail_price'),
        c.from('campaigns').select('*'),
        c.from('campaign_posts').select('*').gte('scheduled_for', new Date().toISOString()).order('scheduled_for').limit(5),
        c.from('launch_jobs').select('*,products(public_product_name)').neq('status', 'Done').limit(5),
        c.from('contacts').select('contact_id,created_at,lifecycle_stage'),
        c.from('shipments').select('*,orders(order_number)'),
        c.from('payments').select('amount,fee,status,created_at'),
        c.from('expenses').select('amount,spent_on,category'),
        c.from('tasks').select('*').neq('status', 'Done').order('due_on').limit(6),
      ]);
    const first = [orders, deals, products, campaigns, posts, jobs, contacts, shipments, payments, expenses, tasks]
      .find((r) => r.error);
    if (first) throw first.error;
    return {
      orders: orders.data || [], deals: deals.data || [], products: products.data || [],
      campaigns: campaigns.data || [], posts: posts.data || [], jobs: jobs.data || [],
      contacts: contacts.data || [], shipments: shipments.data || [], payments: payments.data || [],
      expenses: expenses.data || [], tasks: tasks.data || [],
    };
  }, []);

  if (q.loading) return <Page title="Business control centre"><Loading /></Page>;
  if (q.error) return <Page title="Business control centre"><ErrorNote error={q.error} /></Page>;

  const d = q.data;
  const since = Date.now() - 30 * 864e5;
  const paid = d.payments.filter((p) => ['Paid', 'Settled'].includes(p.status));
  const revenue30 = paid.filter((p) => new Date(p.created_at).getTime() >= since)
    .reduce((s, p) => s + Number(p.amount || 0), 0);
  const spend30 = d.expenses.filter((e) => new Date(e.spent_on).getTime() >= since)
    .reduce((s, e) => s + Number(e.amount || 0), 0);
  const openDeals = d.deals.filter((o) => !['Won', 'Lost'].includes(o.stage));
  const inTransit = d.shipments.filter((s) => ['Booked', 'Picked up', 'In transit', 'Out for delivery'].includes(s.status));
  const live = d.campaigns.filter((c) => ['Running', 'Scheduled'].includes(c.status));
  const lowStock = d.products.filter((p) => p.status === 'Published' && (p.stock_qty ?? 0) <= 2);
  const overdue = d.tasks.filter((t) => t.due_on && new Date(t.due_on) < new Date());

  return (
    <Page title="Business control centre" sub="Where the money, the making and the marketing stand today."
      actions={<Link className="btn btn-primary" href="/launch">Launch a product</Link>}>
      <div className="kpi-row" style={{ marginBottom: 18 }}>
        <Stat label="Collected · 30 days" value={money(revenue30)} delta={`${paid.length} payments all time`} />
        <Stat label="Spent · 30 days" value={money(spend30)} delta={revenue30 ? `${Math.round((spend30 / revenue30) * 100)}% of income` : ''} />
        <Stat label="Open pipeline" value={money(openDeals.reduce((s, o) => s + Number(o.estimated_value || 0), 0))} delta={`${openDeals.length} deals`} />
        <Stat label="Parcels moving" value={inTransit.length} delta={`${d.shipments.filter((s) => s.status === 'Not booked').length} not booked`} />
        <Stat label="Open tasks" value={d.tasks.length} delta={overdue.length ? `${overdue.length} overdue` : 'nothing overdue'} />
      </div>

      <div className="grid g2">
        <div className="card">
          <div className="card-head"><h3>Recent orders</h3><Link className="link small" href="/orders">All orders →</Link></div>
          {d.orders.length === 0 ? <Empty title="No orders yet" /> : (
            <div className="t-wrap"><table className="table">
              <thead><tr><th>Order</th><th>Customer</th><th>Status</th><th className="num">Total</th></tr></thead>
              <tbody>{d.orders.slice(0, 6).map((o) => (
                <tr key={o.order_id}>
                  <td>{o.order_number}<div className="small faint">{when(o.ordered_at)}</div></td>
                  <td>{o.contacts?.full_name || '—'}</td>
                  <td><Badge>{o.order_status}</Badge></td>
                  <td className="num">{money(o.total)}</td>
                </tr>))}</tbody></table></div>
          )}
        </div>

        <div className="card">
          <div className="card-head"><h3>Campaigns in flight</h3><Link className="link small" href="/campaigns">All campaigns →</Link></div>
          <div className="card-body stack">
            {live.length === 0 && <Empty title="Nothing running" hint="Build a campaign to reach your list." />}
            {live.map((c) => {
              const pct = c.budget ? Math.min(100, Math.round((Number(c.spend || 0) / Number(c.budget)) * 100)) : 0;
              return (
                <div key={c.campaign_id}>
                  <div className="row" style={{ marginBottom: 5 }}>
                    <Link className="link" href={`/campaigns?id=${c.campaign_id}`}>{c.campaign_name}</Link>
                    <span className="spacer" /><Badge>{c.status}</Badge>
                  </div>
                  <div className="bar"><span style={{ width: `${pct}%` }} /></div>
                  <div className="small muted" style={{ marginTop: 4 }}>
                    {c.channel} · {money(c.spend)} of {money(c.budget)} · ends {when(c.end_date)}
                  </div>
                </div>);
            })}
          </div>
        </div>

        <div className="card">
          <div className="card-head"><h3>Needs you today</h3><Link className="link small" href="/tasks">All tasks →</Link></div>
          <div className="card-body stack" style={{ gap: 10 }}>
            {d.tasks.length === 0 && <Empty title="All clear" hint="Nothing is waiting on you." />}
            {d.tasks.map((t) => (
              <div key={t.task_id} className="row" style={{ alignItems: 'flex-start' }}>
                <div style={{ flex: 1 }}>
                  <div style={{ fontWeight: 600, fontSize: 13.5 }}>{t.title}</div>
                  <div className="small muted">{t.detail?.slice(0, 80)}</div>
                </div>
                <div style={{ textAlign: 'right' }}>
                  <Badge>{t.priority}</Badge>
                  <div className="small faint">{t.due_on ? when(t.due_on) : ''}</div>
                </div>
              </div>))}
            {lowStock.length > 0 && (
              <div className="note small">
                Low stock: {lowStock.map((p) => p.public_product_name).join(', ')}.{' '}
                <Link className="link" href="/suppliers">Commission a restock →</Link>
              </div>)}
          </div>
        </div>

        <div className="card">
          <div className="card-head"><h3>Scheduled content</h3><Link className="link small" href="/calendar">Calendar →</Link></div>
          {d.posts.length === 0 ? <Empty title="Nothing scheduled" hint="Plan posts from a campaign." /> : (
            <div className="t-wrap"><table className="table">
              <thead><tr><th>Post</th><th>Channel</th><th>When</th><th>Status</th></tr></thead>
              <tbody>{d.posts.map((p) => (
                <tr key={p.post_id}><td>{p.title}</td><td className="small muted">{p.channel}</td>
                  <td className="small">{when(p.scheduled_for, true)}</td><td><Badge>{p.status}</Badge></td></tr>))}
              </tbody></table></div>
          )}
        </div>
      </div>
    </Page>
  );
}
