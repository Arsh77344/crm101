import Link from 'next/link';
import { supabaseServer } from '@/lib/supabase';
import { Page, Badge, when } from '@/components/ui';
export const dynamic = 'force-dynamic';

const CHAN = { Instagram: 'ig', Email: 'em', WhatsApp: 'wa', Facebook: 'ig', SMS: 'wa' };
const DOW = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];

export default async function Calendar({ searchParams }) {
  const sb = supabaseServer();
  const today = new Date();
  const y = Number(searchParams?.y) || today.getFullYear();
  const m = Number(searchParams?.m ?? today.getMonth());

  const first = new Date(y, m, 1);
  const last = new Date(y, m + 1, 0);
  const lead = (first.getDay() + 6) % 7;
  const cells = [];
  for (let i = 0; i < lead; i++) cells.push(null);
  for (let d = 1; d <= last.getDate(); d++) cells.push(new Date(y, m, d));
  while (cells.length % 7) cells.push(null);

  const { data: posts = [] } = await sb.from('campaign_posts')
    .select('post_id,title,channel,status,scheduled_for,campaign_id,campaigns(campaign_name)')
    .gte('scheduled_for', new Date(y, m, 1).toISOString())
    .lt('scheduled_for', new Date(y, m + 1, 1).toISOString())
    .order('scheduled_for');

  const byDay = {};
  posts.forEach((p) => {
    const k = new Date(p.scheduled_for).getDate();
    (byDay[k] ||= []).push(p);
  });

  const prev = m === 0 ? { y: y - 1, m: 11 } : { y, m: m - 1 };
  const next = m === 11 ? { y: y + 1, m: 0 } : { y, m: m + 1 };
  const label = first.toLocaleDateString('en-GB', { month: 'long', year: 'numeric' });

  return (
    <Page title="Content calendar" sub={`${posts.length} pieces planned in ${label}`}
      actions={<>
        <Link className="btn btn-sm" href={`/calendar?y=${prev.y}&m=${prev.m}`}>‹ Previous</Link>
        <Link className="btn btn-sm" href="/calendar">This month</Link>
        <Link className="btn btn-sm" href={`/calendar?y=${next.y}&m=${next.m}`}>Next ›</Link>
      </>}>
      <div className="cal" style={{ marginBottom: 18 }}>
        {DOW.map((d) => <div className="dow" key={d}>{d}</div>)}
        {cells.map((d, i) => {
          if (!d) return <div className="day out" key={i} />;
          const isToday = d.toDateString() === today.toDateString();
          const items = byDay[d.getDate()] || [];
          return (
            <div className={`day ${isToday ? 'today' : ''}`} key={i}>
              <div className="dnum">{d.getDate()}</div>
              {items.map((p) => (
                <Link key={p.post_id} className={`ev ${CHAN[p.channel] || ''}`} href={`/campaigns/${p.campaign_id}`}
                  title={`${p.title} · ${p.channel} · ${p.status}`}>{p.title}</Link>
              ))}
            </div>
          );
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
                <td className="small"><Link className="link" href={`/campaigns/${p.campaign_id}`}>{p.campaigns?.campaign_name}</Link></td>
                <td className="small">{p.channel}</td>
                <td><Badge>{p.status}</Badge></td>
              </tr>))}
          </tbody></table></div>
      </div>
    </Page>
  );
}
