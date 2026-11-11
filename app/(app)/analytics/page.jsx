'use client';
import Link from 'next/link';
import { useQuery } from '@/lib/db';
import { Page, Stat, Loading, ErrorNote, money, when } from '@/components/ui';

export default function Analytics() {
  const q = useQuery(async (c) => {
    const [settings, links, clicks, events] = await Promise.all([
      c.from('settings').select('setting_key,setting_value'),
      c.from('links').select('link_id,label,clicks,campaign_id,campaigns(campaign_name)'),
      c.from('link_clicks').select('clicked_at,referrer'),
      c.from('journey_events').select('kind,source,occurred_at,value'),
    ]);
    const s = {};
    (settings.data || []).forEach((r) => { s[r.setting_key] = r.setting_value || ''; });
    return { s, links: links.data || [], clicks: clicks.data || [], events: events.data || [] };
  }, []);

  if (q.loading) return <Page title="Website analytics"><Loading /></Page>;
  const { s, links, clicks, events } = q.data;
  const propertySet = Boolean(s.ga4_property_id);
  const embed = s.looker_embed_url;

  const now = Date.now();
  const last30 = clicks.filter((c) => new Date(c.clicked_at).getTime() > now - 30 * 864e5);
  const bySource = {};
  events.forEach((e) => { bySource[e.source || 'Unknown'] = (bySource[e.source || 'Unknown'] || 0) + 1; });
  const peak = Math.max(1, ...Object.values(bySource));
  const topLinks = links.slice().sort((a, b) => (b.clicks || 0) - (a.clicks || 0)).slice(0, 6);

  return (
    <Page title="Website analytics" sub="Your own numbers here, with GA4 alongside."
      actions={propertySet
        ? <a className="btn" href={`https://analytics.google.com/analytics/web/#/p${s.ga4_property_id}/reports/intelligenthome`}
            target="_blank" rel="noreferrer">Open GA4</a>
        : <Link className="btn" href="/settings">Add your GA4 property</Link>}>
      <ErrorNote error={q.error} />

      <div className="note" style={{ marginBottom: 16 }}>
        Google blocks GA4 from being shown inside another site, so there is no way to frame the GA4 screens
        themselves. What works instead: the figures below come from this workspace, the button above opens
        GA4 in a tab, and a Looker Studio report built on GA4 <em>can</em> be embedded — paste its link
        on <Link className="link" href="/settings">Settings</Link> and it appears here.
      </div>

      <div className="kpi-row" style={{ marginBottom: 16 }}>
        <Stat label="Link clicks · 30 days" value={last30.length} delta={`${clicks.length} all time`} />
        <Stat label="Tracked links" value={links.length} />
        <Stat label="Journey events" value={events.length} delta="every signal we hold" />
        <Stat label="Attributed value" value={money(events.reduce((a, e) => a + Number(e.value || 0), 0))}
          delta="orders and payments on the journey" />
      </div>

      {embed && (
        <div className="card" style={{ marginBottom: 16 }}>
          <div className="card-head"><h3>Your Looker Studio report</h3>
            <a className="link small" href={embed} target="_blank" rel="noreferrer">Open full size</a></div>
          <iframe src={embed} title="Looker Studio" style={{ width: '100%', height: 620, border: 0,
            borderRadius: '0 0 10px 10px' }} allowFullScreen />
        </div>)}

      <div className="grid g2">
        <div className="card">
          <div className="card-head"><h3>Where people come from</h3></div>
          <div className="card-body stack">
            {Object.keys(bySource).length === 0 && <div className="small muted">No events recorded yet.</div>}
            {Object.entries(bySource).sort((a, b) => b[1] - a[1]).map(([src, n]) => (
              <div key={src}>
                <div className="row small"><span>{src}</span><span className="spacer" /><span className="muted">{n}</span></div>
                <div className="bar"><span style={{ width: `${(n / peak) * 100}%` }} /></div>
              </div>))}
          </div>
        </div>

        <div className="card">
          <div className="card-head"><h3>Best links</h3><Link className="link small" href="/links">All links</Link></div>
          <div className="t-wrap"><table className="table">
            <thead><tr><th>Link</th><th>Campaign</th><th className="num">Clicks</th></tr></thead>
            <tbody>
              {topLinks.length === 0 && <tr><td colSpan="3" className="small muted">No links yet.</td></tr>}
              {topLinks.map((l) => (
                <tr key={l.link_id}><td className="small">{l.label}</td>
                  <td className="small muted">{l.campaigns?.campaign_name || '—'}</td>
                  <td className="num">{l.clicks || 0}</td></tr>))}
            </tbody></table></div>
        </div>
      </div>
    </Page>
  );
}
