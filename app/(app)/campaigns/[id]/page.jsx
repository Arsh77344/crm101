import Link from 'next/link';
import { supabaseServer, currentUser, canManage } from '@/lib/supabase';
import { upsertRow, deleteRow, addMembers } from '@/lib/actions';
import { Page, Badge, money, when, Stat, Empty } from '@/components/ui';
import Flash from '@/components/Flash';
export const dynamic = 'force-dynamic';

const CHANNELS = ['Email', 'Instagram', 'WhatsApp', 'SMS', 'Facebook', 'Google Ads', 'Offline'];
const OBJECTIVES = ['Awareness', 'Lead generation', 'Sales', 'Retention', 'Launch'];
const STATUS = ['Draft', 'Scheduled', 'Running', 'Paused', 'Completed', 'Archived'];
const POST_STATUS = ['Idea', 'Draft', 'Approved', 'Scheduled', 'Published'];

export default async function CampaignDetail({ params, searchParams }) {
  const sb = supabaseServer();
  const user = await currentUser();
  const id = params.id;

  const c = (await sb.from('campaigns').select('*').eq('campaign_id', id).maybeSingle()).data;
  if (!c) return <Page title="Campaign not found"><Link className="btn" href="/campaigns">Back to campaigns</Link></Page>;

  const [members, posts, pool, products] = await Promise.all([
    sb.from('campaign_members').select('member_status,contacts(contact_id,full_name,email,contact_type,lifecycle_stage)').eq('campaign_id', id).then((r) => r.data || []),
    sb.from('campaign_posts').select('*,products(public_product_name)').eq('campaign_id', id).order('scheduled_for').then((r) => r.data || []),
    sb.from('contacts').select('contact_id,full_name,contact_type,email').order('full_name').limit(300).then((r) => r.data || []),
    sb.from('products').select('product_id,public_product_name').order('public_product_name').then((r) => r.data || []),
  ]);

  const save = upsertRow.bind(null, 'campaigns', 'campaign_id', `/campaigns/${id}`);
  const addPost = upsertRow.bind(null, 'campaign_posts', 'post_id', `/campaigns/${id}`);
  const remove = deleteRow.bind(null, 'campaigns', 'campaign_id', '/campaigns');
  const addPeople = addMembers.bind(null, id);

  const memberIds = new Set(members.map((m) => m.contacts?.contact_id));
  const candidates = pool.filter((p) => !memberIds.has(p.contact_id) &&
    (c.audience_type === 'All' || p.contact_type === c.audience_type || p.contact_type === 'Both'));
  const pct = c.budget ? Math.min(100, Math.round((Number(c.spend || 0) / Number(c.budget)) * 100)) : 0;

  return (
    <Page title={c.campaign_name} sub={`${c.objective} · ${c.channel} · ${c.audience_type} audience`}
      actions={<><Link className="btn" href="/calendar">Calendar</Link><Link className="btn" href="/campaigns">All campaigns</Link></>}>
      <Flash params={searchParams} />

      <div className="grid g4" style={{ marginBottom: 18 }}>
        <Stat label="Status" value={<Badge>{c.status}</Badge>} />
        <Stat label="Audience" value={members.length} delta={`${candidates.length} more available`} />
        <Stat label="Content" value={posts.length} delta={`${posts.filter((p) => p.status === 'Published').length} published`} />
        <Stat label="Spend" value={money(c.spend)} delta={c.budget ? `${pct}% of ${money(c.budget)}` : 'No budget set'} />
      </div>

      <div className="grid" style={{ gridTemplateColumns: '1fr 360px' }}>
        <div className="stack">
          <div className="card">
            <div className="card-head"><h3>Content plan</h3>
              <span className="small muted">{posts.filter((p) => p.scheduled_for).length} scheduled</span></div>
            {posts.length === 0 ? <Empty title="No posts planned" hint="Add the first piece of content below." /> : (
              <div className="t-wrap"><table className="table">
                <thead><tr><th>Post</th><th>Channel</th><th>Product</th><th>When</th><th>Status</th></tr></thead>
                <tbody>{posts.map((p) => (
                  <tr key={p.post_id}>
                    <td><strong className="small">{p.title}</strong>
                      <div className="small faint">{p.body?.slice(0, 80)}</div></td>
                    <td className="small">{p.channel}</td>
                    <td className="small">{p.products?.public_product_name || '—'}</td>
                    <td className="small">{when(p.scheduled_for, true)}</td>
                    <td><Badge>{p.status}</Badge></td>
                  </tr>))}</tbody></table></div>
            )}
            <form action={addPost} className="card-foot">
              <input type="hidden" name="campaign_id" value={id} />
              <div className="form-grid">
                <div className="field"><label>Title</label><input name="title" required placeholder="Reel — Magenta jangla close-up" /></div>
                <div className="field"><label>Channel</label>
                  <select name="channel" defaultValue={c.channel}>{CHANNELS.map((o) => <option key={o}>{o}</option>)}</select></div>
                <div className="field"><label>Product</label>
                  <select name="product_id" defaultValue=""><option value="">—</option>
                    {products.map((p) => <option key={p.product_id} value={p.product_id}>{p.public_product_name}</option>)}</select></div>
                <div className="field"><label>Scheduled for</label><input name="scheduled_for" type="datetime-local" /></div>
                <div className="field full"><label>Copy</label><textarea name="body" placeholder="The hook, the body, the call to action." /></div>
                <div className="field"><label>Hashtags</label><input name="hashtags" placeholder="#banarasi #handloom" /></div>
                <div className="field"><label>Status</label>
                  <select name="status" defaultValue="Idea">{POST_STATUS.map((s) => <option key={s}>{s}</option>)}</select></div>
              </div>
              <button className="btn btn-primary btn-sm">Add to plan</button>
            </form>
          </div>

          <div className="card">
            <div className="card-head"><h3>Audience</h3><span className="small muted">{members.length} people</span></div>
            {members.length === 0 ? <Empty title="No one added yet" hint="Pick people from the list on the right." /> : (
              <div className="t-wrap"><table className="table">
                <thead><tr><th>Name</th><th>Type</th><th>Email</th><th>Stage</th><th>Status</th></tr></thead>
                <tbody>{members.map((m, i) => (
                  <tr key={i}>
                    <td><Link className="link" href={`/contacts/${m.contacts?.contact_id}`}>{m.contacts?.full_name}</Link></td>
                    <td className="small">{m.contacts?.contact_type}</td>
                    <td className="small">{m.contacts?.email || '—'}</td>
                    <td><Badge>{m.contacts?.lifecycle_stage}</Badge></td>
                    <td><Badge>{m.member_status}</Badge></td>
                  </tr>))}</tbody></table></div>
            )}
          </div>
        </div>

        <div className="stack">
          <form action={save} className="card">
            <div className="card-head"><h3>Campaign settings</h3></div>
            <div className="card-body">
              <input type="hidden" name="_id" value={id} />
              <div className="field"><label>Name</label><input name="campaign_name" defaultValue={c.campaign_name} /></div>
              <div className="field"><label>Status</label>
                <select name="status" defaultValue={c.status}>{STATUS.map((s) => <option key={s}>{s}</option>)}</select></div>
              <div className="field"><label>Objective</label>
                <select name="objective" defaultValue={c.objective}>{OBJECTIVES.map((s) => <option key={s}>{s}</option>)}</select></div>
              <div className="field"><label>Channel</label>
                <select name="channel" defaultValue={c.channel}>{CHANNELS.map((s) => <option key={s}>{s}</option>)}</select></div>
              <div className="field"><label>Audience</label>
                <select name="audience_type" defaultValue={c.audience_type}>
                  <option>All</option><option>B2C</option><option>B2B</option></select></div>
              <div className="row" style={{ gap: 10 }}>
                <div className="field" style={{ flex: 1 }}><label>Budget</label>
                  <input name="budget" type="number" step="0.01" defaultValue={c.budget ?? ''} /></div>
                <div className="field" style={{ flex: 1 }}><label>Spend</label>
                  <input name="spend" type="number" step="0.01" defaultValue={c.spend ?? 0} /></div>
              </div>
              <div className="row" style={{ gap: 10 }}>
                <div className="field" style={{ flex: 1 }}><label>Starts</label>
                  <input name="start_date" type="date" defaultValue={c.start_date || ''} /></div>
                <div className="field" style={{ flex: 1 }}><label>Ends</label>
                  <input name="end_date" type="date" defaultValue={c.end_date || ''} /></div>
              </div>
              <div className="field"><label>Offer</label><input name="offer" defaultValue={c.offer || ''} /></div>
              <div className="field"><label>The brief</label><textarea name="brief" defaultValue={c.brief || ''} /></div>
            </div>
            <div className="card-foot"><button className="btn btn-primary">Save campaign</button></div>
          </form>

          <form action={addPeople} className="card">
            <div className="card-head"><h3>Add people</h3>
              <span className="small muted">{c.audience_type} audience</span></div>
            <div className="card-body" style={{ maxHeight: 280, overflowY: 'auto' }}>
              {candidates.length === 0 && <div className="small muted">Everyone matching this audience is already in.</div>}
              {candidates.map((p) => (
                <label key={p.contact_id} className="row" style={{ gap: 8, padding: '5px 0', cursor: 'pointer' }}>
                  <input type="checkbox" name="contact_id" value={p.contact_id} />
                  <span className="small">{p.full_name}</span>
                  <span className="spacer" /><span className="small faint">{p.contact_type}</span>
                </label>))}
            </div>
            <div className="card-foot"><button className="btn btn-sm">Add selected</button></div>
          </form>

          {canManage(user.profile?.role) && (
            <form action={remove} className="card"><input type="hidden" name="_id" value={id} />
              <div className="card-body"><button className="btn btn-danger btn-sm">Delete campaign</button></div></form>
          )}
        </div>
      </div>
    </Page>
  );
}
