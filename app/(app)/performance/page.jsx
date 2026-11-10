import { supabaseServer } from '@/lib/supabase';
import { Page, Stat, money, Badge } from '@/components/ui';
export const dynamic = 'force-dynamic';

export default async function Performance() {
  const sb = supabaseServer();
  const [camps, members, posts, orders] = await Promise.all([
    sb.from('campaigns').select('*').then((r) => r.data || []),
    sb.from('campaign_members').select('campaign_id,member_status').then((r) => r.data || []),
    sb.from('campaign_posts').select('campaign_id,status,channel').then((r) => r.data || []),
    sb.from('orders').select('total,order_status,ordered_at').then((r) => r.data || []),
  ]);

  const spend = camps.reduce((s, c) => s + Number(c.spend || 0), 0);
  const revenue = orders.filter((o) => ['Fulfilled', 'Processing'].includes(o.order_status))
    .reduce((s, o) => s + Number(o.total || 0), 0);
  const reached = members.filter((m) => m.member_status !== 'Planned').length;

  const byChannel = {};
  posts.forEach((p) => { byChannel[p.channel] = (byChannel[p.channel] || 0) + 1; });
  const maxCh = Math.max(1, ...Object.values(byChannel));

  return (
    <Page title="Marketing performance" sub="What the campaigns cost and what they touched.">
      <div className="grid g4" style={{ marginBottom: 18 }}>
        <Stat label="Total spend" value={money(spend)} delta={`${camps.length} campaigns`} />
        <Stat label="Revenue booked" value={money(revenue)} delta="Fulfilled and processing orders" />
        <Stat label="Return on spend" value={spend ? `${(revenue / spend).toFixed(1)}×` : '—'} delta="Revenue ÷ campaign spend" />
        <Stat label="People reached" value={reached} delta={`${members.length} in audiences`} />
      </div>

      <div className="grid g2">
        <div className="card">
          <div className="card-head"><h3>Campaign by campaign</h3></div>
          <div className="t-wrap"><table className="table">
            <thead><tr><th>Campaign</th><th className="num">Audience</th><th className="num">Posts</th>
              <th className="num">Budget</th><th className="num">Spend</th><th>Status</th></tr></thead>
            <tbody>{camps.map((c) => (
              <tr key={c.campaign_id}>
                <td>{c.campaign_name}<div className="small faint">{c.channel}</div></td>
                <td className="num">{members.filter((m) => m.campaign_id === c.campaign_id).length}</td>
                <td className="num">{posts.filter((p) => p.campaign_id === c.campaign_id).length}</td>
                <td className="num">{money(c.budget)}</td>
                <td className="num">{money(c.spend)}</td>
                <td><Badge>{c.status}</Badge></td>
              </tr>))}
              {camps.length === 0 && <tr><td colSpan="6" className="small muted">No campaigns yet.</td></tr>}
            </tbody></table></div>
        </div>

        <div className="card">
          <div className="card-head"><h3>Content by channel</h3></div>
          <div className="card-body stack">
            {Object.keys(byChannel).length === 0 && <div className="small muted">No content planned yet.</div>}
            {Object.entries(byChannel).sort((a, b) => b[1] - a[1]).map(([ch, n]) => (
              <div key={ch}>
                <div className="row small"><span>{ch}</span><span className="spacer" /><span className="muted">{n}</span></div>
                <div className="bar"><span style={{ width: `${(n / maxCh) * 100}%` }} /></div>
              </div>))}
          </div>
        </div>
      </div>
    </Page>
  );
}
