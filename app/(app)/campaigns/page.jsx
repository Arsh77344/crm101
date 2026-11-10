import Link from 'next/link';
import { supabaseServer } from '@/lib/supabase';
import { upsertRow } from '@/lib/actions';
import { Page, Badge, money, when, Empty, Stat } from '@/components/ui';
import Flash from '@/components/Flash';
export const dynamic = 'force-dynamic';

const CHANNELS = ['Email', 'Instagram', 'WhatsApp', 'SMS', 'Facebook', 'Google Ads', 'Offline'];
const OBJECTIVES = ['Awareness', 'Lead generation', 'Sales', 'Retention', 'Launch'];

export default async function Campaigns({ searchParams }) {
  const sb = supabaseServer();
  const { data: rows = [] } = await sb.from('campaigns').select('*').order('created_at', { ascending: false });
  const counts = (await sb.from('campaign_members').select('campaign_id')).data || [];
  const posts = (await sb.from('campaign_posts').select('campaign_id,status')).data || [];
  const create = upsertRow.bind(null, 'campaigns', 'campaign_id', '/campaigns/[id]');
  const live = rows.filter((c) => ['Running', 'Scheduled'].includes(c.status));

  return (
    <Page title="Campaigns" sub="Plan the audience, the offer and the content in one place.">
      <Flash params={searchParams} />
      <div className="grid g3" style={{ marginBottom: 18 }}>
        <Stat label="In flight" value={live.length} delta={`${rows.length} campaigns total`} />
        <Stat label="Budget committed" value={money(rows.reduce((s, c) => s + Number(c.budget || 0), 0))} />
        <Stat label="Spent so far" value={money(rows.reduce((s, c) => s + Number(c.spend || 0), 0))} />
      </div>

      <div className="grid" style={{ gridTemplateColumns: '1fr 340px' }}>
        <div className="card">
          <div className="card-head"><h3>All campaigns</h3></div>
          {rows.length === 0 ? <Empty title="No campaigns yet" hint="Start one on the right." /> : (
            <div className="t-wrap"><table className="table">
              <thead><tr><th>Campaign</th><th>Channel</th><th>Audience</th><th className="num">People</th>
                <th className="num">Posts</th><th>Dates</th><th>Status</th></tr></thead>
              <tbody>{rows.map((c) => (
                <tr key={c.campaign_id}>
                  <td><Link className="link" href={`/campaigns/${c.campaign_id}`}>{c.campaign_name}</Link>
                    <div className="small faint">{c.objective}</div></td>
                  <td className="small">{c.channel}</td>
                  <td className="small">{c.audience_type}</td>
                  <td className="num">{counts.filter((m) => m.campaign_id === c.campaign_id).length}</td>
                  <td className="num">{posts.filter((p) => p.campaign_id === c.campaign_id).length}</td>
                  <td className="small faint">{c.start_date ? when(c.start_date) : '—'}</td>
                  <td><Badge>{c.status}</Badge></td>
                </tr>))}</tbody></table></div>
          )}
        </div>

        <form action={create} className="card">
          <div className="card-head"><h3>New campaign</h3></div>
          <div className="card-body">
            <div className="field"><label>Campaign name</label>
              <input name="campaign_name" required placeholder="Festive Edit — Instagram" /></div>
            <div className="field"><label>Objective</label>
              <select name="objective" defaultValue="Sales">{OBJECTIVES.map((o) => <option key={o}>{o}</option>)}</select></div>
            <div className="field"><label>Channel</label>
              <select name="channel" defaultValue="Instagram">{CHANNELS.map((o) => <option key={o}>{o}</option>)}</select></div>
            <div className="field"><label>Audience</label>
              <select name="audience_type" defaultValue="B2C">
                <option>All</option><option>B2C</option><option>B2B</option></select></div>
            <div className="field"><label>Budget</label><input name="budget" type="number" step="0.01" placeholder="25000" /></div>
            <div className="field"><label>Starts</label><input name="start_date" type="date" /></div>
            <div className="field"><label>Ends</label><input name="end_date" type="date" /></div>
            <div className="field"><label>The brief</label>
              <textarea name="brief" placeholder="Who it is for, what it says, what it should achieve." /></div>
          </div>
          <div className="card-foot"><button className="btn btn-primary">Create campaign</button></div>
        </form>
      </div>
    </Page>
  );
}
