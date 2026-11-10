import Link from 'next/link';
import { supabaseServer } from '@/lib/supabase';
import { Page, Stat, Badge, money, when, Empty } from '@/components/ui';

export const dynamic = 'force-dynamic';

export default async function Dashboard() {
  const sb = supabaseServer();
  const since = new Date(Date.now() - 30 * 864e5).toISOString();

  const [orders, pipeline, products, campaigns, posts, jobs, contacts] = await Promise.all([
    sb.from('orders').select('order_id,order_number,total,order_status,ordered_at,contact_id,contacts(full_name)').order('ordered_at', { ascending: false }).limit(40),
    sb.from('opportunities').select('opportunity_id,name,stage,estimated_value,expected_close_date'),
    sb.from('products').select('product_id,status'),
    sb.from('campaigns').select('campaign_id,campaign_name,status,channel,budget,spend,start_date,end_date'),
    sb.from('campaign_posts').select('post_id,title,channel,scheduled_for,status').gte('scheduled_for', new Date().toISOString()).order('scheduled_for').limit(6),
    sb.from('launch_jobs').select('job_id,stage,status,message,products(public_product_name)').neq('status', 'Done').limit(6),
    sb.from('contacts').select('contact_id,created_at,lifecycle_stage'),
  ]);

  const allOrders = orders.data || [];
  const paid = allOrders.filter((o) => ['Fulfilled', 'Processing'].includes(o.order_status));
  const revenue30 = paid.filter((o) => o.ordered_at >= since).reduce((s, o) => s + Number(o.total || 0), 0);
  const openPipeline = (pipeline.data || []).filter((o) => !['Won', 'Lost'].includes(o.stage));
  const pipelineValue = openPipeline.reduce((s, o) => s + Number(o.estimated_value || 0), 0);
  const published = (products.data || []).filter((p) => p.status === 'Published').length;
  const live = (campaigns.data || []).filter((c) => ['Running', 'Scheduled'].includes(c.status));
  const newContacts = (contacts.data || []).filter((c) => c.created_at >= since).length;

  return (
    <Page title="Business control centre" sub="Everything that moved in the last 30 days."
      actions={<Link className="btn btn-primary" href="/launch">Launch a product</Link>}>
      <div className="grid g4" style={{ marginBottom: 18 }}>
        <Stat label="Revenue · 30 days" value={money(revenue30)} delta={`${paid.filter((o) => o.ordered_at >= since).length} paid orders`} />
        <Stat label="Open pipeline" value={money(pipelineValue)} delta={`${openPipeline.length} active deals`} />
        <Stat label="Live products" value={published} delta={`${(products.data || []).length} in catalogue`} />
        <Stat label="New contacts" value={newContacts} delta={`${(contacts.data || []).length} total`} />
      </div>

      <div className="grid g2">
        <div className="card">
          <div className="card-head"><h3>Recent orders</h3><Link className="link small" href="/orders">All orders →</Link></div>
          {allOrders.length === 0 ? <Empty title="No orders yet" hint="Orders you take or sync will appear here." /> : (
            <div className="t-wrap"><table className="table">
              <thead><tr><th>Order</th><th>Customer</th><th>Status</th><th className="num">Total</th></tr></thead>
              <tbody>{allOrders.slice(0, 6).map((o) => (
                <tr key={o.order_id}>
                  <td><Link className="link" href="/orders">{o.order_number || o.order_id.slice(0, 8)}</Link>
                    <div className="small faint">{when(o.ordered_at)}</div></td>
                  <td>{o.contacts?.full_name || '—'}</td>
                  <td><Badge>{o.order_status}</Badge></td>
                  <td className="num">{money(o.total)}</td>
                </tr>))}
              </tbody></table></div>
          )}
        </div>

        <div className="card">
          <div className="card-head"><h3>Campaigns in flight</h3><Link className="link small" href="/campaigns">All campaigns →</Link></div>
          <div className="card-body stack">
            {live.length === 0 && <Empty title="Nothing running" hint="Build a campaign to start reaching your list." />}
            {live.map((c) => {
              const pct = c.budget ? Math.min(100, Math.round((Number(c.spend || 0) / Number(c.budget)) * 100)) : 0;
              return (
                <div key={c.campaign_id}>
                  <div className="row" style={{ marginBottom: 5 }}>
                    <Link className="link" href={`/campaigns/${c.campaign_id}`}>{c.campaign_name}</Link>
                    <span className="spacer" /><Badge>{c.status}</Badge>
                  </div>
                  <div className="bar"><span style={{ width: `${pct}%` }} /></div>
                  <div className="small muted" style={{ marginTop: 4 }}>
                    {c.channel} · {money(c.spend)} of {money(c.budget)} spent · ends {when(c.end_date)}
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        <div className="card">
          <div className="card-head"><h3>Scheduled content</h3><Link className="link small" href="/calendar">Calendar →</Link></div>
          {(posts.data || []).length === 0 ? <Empty title="Nothing scheduled" hint="Plan posts on the content calendar." /> : (
            <div className="t-wrap"><table className="table">
              <thead><tr><th>Post</th><th>Channel</th><th>When</th><th>Status</th></tr></thead>
              <tbody>{posts.data.map((p) => (
                <tr key={p.post_id}><td>{p.title}</td><td className="small muted">{p.channel}</td>
                  <td className="small">{when(p.scheduled_for, true)}</td><td><Badge>{p.status}</Badge></td></tr>))}
              </tbody></table></div>
          )}
        </div>

        <div className="card">
          <div className="card-head"><h3>Needs your attention</h3><Link className="link small" href="/launch">Launch desk →</Link></div>
          {(jobs.data || []).length === 0 ? <Empty title="All clear" hint="No product launches are waiting on you." /> : (
            <div className="card-body stack">
              {jobs.data.map((j) => (
                <div key={j.job_id} className="row" style={{ alignItems: 'flex-start' }}>
                  <div style={{ flex: 1 }}>
                    <div style={{ fontWeight: 600, fontSize: 13.5 }}>{j.products?.public_product_name || 'Untitled product'}</div>
                    <div className="small muted">{j.message}</div>
                  </div>
                  <Badge>{j.status}</Badge>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </Page>
  );
}
