'use client';
import { Suspense, useState } from 'react';
import Link from 'next/link';
import { useQuery } from '@/lib/db';
import { Page, Badge, Loading, ErrorNote, when } from '@/components/ui';
import { loadOccasions, covers, runUp, spanLabel, worthMentioning } from '@/lib/occasions';

const CHAN = { Instagram: 'ig', Email: 'em', WhatsApp: 'wa', Facebook: 'ig', SMS: 'wa' };
const DOW = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];

function Calendar() {
  const today = new Date();
  const [cursor, setCursor] = useState({ y: today.getFullYear(), m: today.getMonth() });
  const first = new Date(cursor.y, cursor.m, 1);
  const last = new Date(cursor.y, cursor.m + 1, 0);

  const q = useQuery(async (c) => {
    const { data, error } = await c.from('campaign_posts')
      .select('*,campaigns(campaign_name)')
      .gte('scheduled_for', new Date(cursor.y, cursor.m, 1).toISOString())
      .lt('scheduled_for', new Date(cursor.y, cursor.m + 1, 1).toISOString())
      .order('scheduled_for');
    if (error) throw error;
    return data || [];
  }, [cursor.y, cursor.m]);

  // The occasions calendar, so the grid shows what is coming as well as what
  // has been scheduled. The whole table is two dozen rows, so it is fetched
  // once and filtered per cell rather than queried per month.
  const occ = useQuery(async (c) => loadOccasions(c), []);
  const occasions = occ.data || [];
  const posts = q.data || [];
  const byDay = {};
  posts.forEach((p) => { const k = new Date(p.scheduled_for).getDate(); (byDay[k] ||= []).push(p); });

  const lead = (first.getDay() + 6) % 7;
  const cells = [];
  for (let i = 0; i < lead; i++) cells.push(null);
  for (let d = 1; d <= last.getDate(); d++) cells.push(new Date(cursor.y, cursor.m, d));
  while (cells.length % 7) cells.push(null);

  const label = first.toLocaleDateString('en-GB', { month: 'long', year: 'numeric' });
  const shift = (n) => setCursor(({ y, m }) => {
    const d = new Date(y, m + n, 1); return { y: d.getFullYear(), m: d.getMonth() };
  });

  return (
    <Page title="Content calendar" sub={`${posts.length} pieces planned in ${label}`}
      actions={<>
        <button className="btn btn-sm" onClick={() => shift(-1)}>‹ Previous</button>
        <button className="btn btn-sm" onClick={() => setCursor({ y: today.getFullYear(), m: today.getMonth() })}>This month</button>
        <button className="btn btn-sm" onClick={() => shift(1)}>Next ›</button>
      </>}>
      <ErrorNote error={q.error || occ.error} />
      {q.loading ? <Loading /> : (
        <>
          {(() => {
            // What to act on, rather than what merely falls in view: an
            // occasion whose run-up has started or starts within the fortnight.
            const soon = worthMentioning(occasions);
            if (!soon.length) return null;
            return (
              <div className="note plain small" style={{ marginBottom: 14 }}>
                <strong>Coming up.</strong>{' '}
                {soon.map((o, i) => (
                  <span key={o.occasion_id}>
                    {i ? ' · ' : ''}
                    <Link className="link" href={`/occasions?id=${o.occasion_id}`}>{o.name}</Link>
                    {' '}{spanLabel(o)}, {runUp(o).text}
                  </span>))}
                {' · '}
                <Link className="link" href="/studio">Build a campaign for one</Link>
              </div>);
          })()}

          <div className="cal" style={{ marginBottom: 18 }}>
            {DOW.map((d) => <div className="dow" key={d}>{d}</div>)}
            {cells.map((d, i) => {
              if (!d) return <div className="day out" key={i} />;
              const isToday = d.toDateString() === today.toDateString();
              const items = byDay[d.getDate()] || [];
              return (
                <div className={`day ${isToday ? 'today' : ''}`} key={i}>
                  <div className="dnum">{d.getDate()}</div>
                  {occasions.filter((o) => covers(o, d)).map((o) => (
                    <Link key={o.occasion_id} className="ev occ"
                      href={`/occasions?id=${o.occasion_id}`}
                      title={`${o.name} \u00b7 ${o.kind}${o.region ? ` \u00b7 ${o.region}` : ''}${
                        o.date_basis === 'Approximate' ? ' \u00b7 date approximate' : ''}`}>
                      {o.name}
                    </Link>))}
                  {items.map((p) => (
                    <Link key={p.post_id} className={`ev ${CHAN[p.channel] || ''}`}
                      href={`/campaigns?id=${p.campaign_id}`} title={`${p.title} · ${p.channel} · ${p.status}`}>
                      {p.title}
                    </Link>))}
                </div>);
            })}
          </div>

          <div className="card">
            <div className="card-head"><h3>Everything scheduled this month</h3></div>
            <div className="t-wrap"><table className="table">
              <thead><tr><th>When</th><th>Post</th><th>Campaign</th><th>Channel</th><th>Status</th></tr></thead>
              <tbody>
                {posts.length === 0 && <tr><td colSpan="5" className="small muted">Nothing planned. Add posts from a campaign.</td></tr>}
                {posts.map((p) => (
                  <tr key={p.post_id}>
                    <td className="small">{when(p.scheduled_for, true)}</td>
                    <td>{p.title}</td>
                    <td className="small"><Link className="link" href={`/campaigns?id=${p.campaign_id}`}>{p.campaigns?.campaign_name}</Link></td>
                    <td className="small">{p.channel}</td>
                    <td><Badge>{p.status}</Badge></td>
                  </tr>))}
              </tbody></table></div>
          </div>
        </>
      )}
    </Page>
  );
}
export default function Wrapped() { return <Suspense fallback={<Loading />}><Calendar /></Suspense>; }
