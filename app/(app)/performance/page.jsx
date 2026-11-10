'use client';
import { useQuery } from '@/lib/db';
import { Page, Stat, Badge, Loading, ErrorNote, money } from '@/components/ui';

export default function Performance() {
  const q = useQuery(async (c) => {
    const [camps, members, posts, payments] = await Promise.all([
      c.from('campaigns').select('*'),
      c.from('campaign_members').select('campaign_id,member_status'),
      c.from('campaign_posts').select('campaign_id,status,channel'),
      c.from('payments').select('amount,status'),
    ]);
    if (camps.error) throw camps.error;
    return { camps: camps.data || [], members: members.data || [], posts: posts.data || [], payments: payments.data || [] };
  }, []);

  if (q.loading) return <Page title="Marketing performance"><Loading /></Page>;
  if (q.error) return <Page title="Marketing performance"><ErrorNote error={q.error} /></Page>;
  const d = q.data;

  const spend = d.camps.reduce((s, c) => s + Number(c.spend || 0), 0);
  const revenue = d.payments.filter((p) => ['Paid', 'Settled'].includes(p.status))
    .reduce((s, p) => s + Number(p.amount || 0), 0);
  const reached = d.members.filter((m) => m.member_status !== 'Planned').length;
  const byChannel = {};
  d.posts.forEach((p) => { byChannel[p.channel] = (byChannel[p.channel] || 0) + 1; });
  const maxCh = Math.max(1, ...Object.values(byChannel));

  return (
    <Page title="Marketing performance" sub="What the campaigns cost and what they touched.">
      <div className="kpi-row" style={{ marginBottom: 18 }}>
        <Stat label="Total spend" value={money(spend)} delta={`${d.camps.length} campaigns`} />
        <Stat label="Revenue collected" value={money(revenue)} delta="All payments marked paid" />
        <Stat label="Return on spend" value={spend ? `${(revenue / spend).toFixed(1)}×` : '—'} delta="Revenue ÷ campaign spend" />
        <Stat label="People reached" value={reached} delta={`${d.members.length} in audiences`} />
      </div>

      <div className="grid g2">
        <div className="card">
          <div className="card-head"><h3>Campaign by campaign</h3></div>
          <div className="t-wrap"><table className="table">
            <thead><tr><th>Campaign</th><th className="num">Audience</th><th className="num">Posts</th>
              <th className="num">Budget</th><th className="num">Spend</th><th>Status</th></tr></thead>
            <tbody>{d.camps.map((c) => (
              <tr key={c.campaign_id}>
                <td>{c.campaign_name}<div className="small faint">{c.channel}</div></td>
                <td className="num">{d.members.filter((m) => m.campaign_id === c.campaign_id).length}</td>
                <td className="num">{d.posts.filter((p) => p.campaign_id === c.campaign_id).length}</td>
                <td className="num">{money(c.budget)}</td>
                <td className="num">{money(c.spend)}</td>
                <td><Badge>{c.status}</Badge></td>
              </tr>))}
              {d.camps.length === 0 && <tr><td colSpan="6" className="small muted">No campaigns yet.</td></tr>}
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
