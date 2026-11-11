'use client';
import { Suspense, useState } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import Link from 'next/link';
import { useQuery, insertRow, updateRow, upsertRow, formValues } from '@/lib/db';
import { Page, Stat, Badge, Empty, Loading, ErrorNote, money, when } from '@/components/ui';

const CHANNELS = ['Email', 'Instagram', 'WhatsApp', 'SMS', 'Facebook', 'Google Ads', 'Offline'];
const OBJECTIVES = ['Awareness', 'Lead generation', 'Sales', 'Retention', 'Launch'];
const STATUS = ['Draft', 'Scheduled', 'Running', 'Paused', 'Completed', 'Archived'];
const POST_STATUS = ['Idea', 'Draft', 'Approved', 'Scheduled', 'Published'];

function Campaigns() {
  const router = useRouter();
  const sp = useSearchParams();
  const id = sp.get('id');
  const [err, setErr] = useState('');

  const q = useQuery(async (c) => {
    const [camps, members, posts, contacts, products] = await Promise.all([
      c.from('campaigns').select('*').order('created_at', { ascending: false }),
      c.from('campaign_members').select('campaign_id,member_status,contacts(contact_id,full_name,email,contact_type,lifecycle_stage)'),
      c.from('campaign_posts').select('*,products(public_product_name)').order('scheduled_for'),
      c.from('contactable').select('*').order('full_name'),
      c.from('products').select('product_id,public_product_name').order('public_product_name'),
    ]);
    if (camps.error) throw camps.error;
    return { camps: camps.data || [], members: members.data || [], posts: posts.data || [],
      contacts: contacts.data || [], products: products.data || [] };
  }, []);

  async function createCampaign(e) {
    e.preventDefault();
    try { const row = await insertRow('campaigns', formValues(e.target)); e.target.reset(); q.reload();
      if (row) router.replace(`/campaigns?id=${row.campaign_id}`); }
    catch (e2) { setErr(e2.message); }
  }
  async function saveCampaign(e, cid) {
    e.preventDefault();
    try { await updateRow('campaigns', 'campaign_id', cid, formValues(e.target)); q.reload(); }
    catch (e2) { setErr(e2.message); }
  }
  async function addPost(e, cid) {
    e.preventDefault();
    try { await insertRow('campaign_posts', { ...formValues(e.target), campaign_id: cid }); e.target.reset(); q.reload(); }
    catch (e2) { setErr(e2.message); }
  }
  async function addPeople(e, cid) {
    e.preventDefault();
    const picked = [].concat(formValues(e.target).contact_id || []);
    try {
      for (const cid2 of picked) {
        await upsertRow('campaign_members', { campaign_id: cid, contact_id: cid2, member_status: 'Planned' }, 'campaign_id,contact_id');
      }
      q.reload();
    } catch (e2) { setErr(e2.message); }
  }

  if (q.loading) return <Page title="Campaigns"><Loading /></Page>;
  const d = q.data;
  const current = id ? d.camps.find((c) => c.campaign_id === id) : null;

  if (current) {
    const members = d.members.filter((m) => m.campaign_id === id);
    const posts = d.posts.filter((p) => p.campaign_id === id);
    const memberIds = new Set(members.map((m) => m.contacts?.contact_id));
    const channelKey = current.channel === 'WhatsApp' ? 'whatsapp_ok' : current.channel === 'Email' ? 'email_ok' : null;
    const audienceFit = (p) => current.audience_type === 'All'
      || p.contact_type === current.audience_type || p.contact_type === 'Both';
    const pool = d.contacts.filter((p) => !memberIds.has(p.contact_id) && audienceFit(p));
    const candidates = pool.filter((p) => !p.blocked && (!channelKey || p[channelKey]));
    const withheld = pool.length - candidates.length;
    const pct = current.budget ? Math.min(100, Math.round((Number(current.spend || 0) / Number(current.budget)) * 100)) : 0;

    return (
      <Page title={current.campaign_name} sub={`${current.objective} · ${current.channel} · ${current.audience_type} audience`}
        actions={<button className="btn" onClick={() => router.replace('/campaigns')}>All campaigns</button>}>
        <ErrorNote error={err} />
        <div className="kpi-row" style={{ marginBottom: 18 }}>
          <Stat label="Status" value={<Badge>{current.status}</Badge>} />
          <Stat label="Audience" value={members.length} delta={`${candidates.length} more available`} />
          <Stat label="Content" value={posts.length} delta={`${posts.filter((p) => p.status === 'Published').length} published`} />
          <Stat label="Spend" value={money(current.spend)} delta={current.budget ? `${pct}% of ${money(current.budget)}` : 'No budget set'} />
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
                      <td><strong className="small">{p.title}</strong><div className="small faint">{p.body?.slice(0, 80)}</div></td>
                      <td className="small">{p.channel}</td>
                      <td className="small">{p.products?.public_product_name || '—'}</td>
                      <td className="small">{when(p.scheduled_for, true)}</td>
                      <td><Badge>{p.status}</Badge></td>
                    </tr>))}</tbody></table></div>
              )}
              <form className="card-foot" onSubmit={(e) => addPost(e, id)}>
                <div className="form-grid">
                  <div className="field"><label>Title</label><input name="title" required placeholder="Reel — magenta jangla close-up" /></div>
                  <div className="field"><label>Channel</label>
                    <select name="channel" defaultValue={current.channel}>{CHANNELS.map((o) => <option key={o}>{o}</option>)}</select></div>
                  <div className="field"><label>Product</label>
                    <select name="product_id" defaultValue=""><option value="">—</option>
                      {d.products.map((p) => <option key={p.product_id} value={p.product_id}>{p.public_product_name}</option>)}</select></div>
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
              {members.length === 0 ? <Empty title="No one added yet" hint="Pick people on the right." /> : (
                <div className="t-wrap"><table className="table">
                  <thead><tr><th>Name</th><th>Type</th><th>Email</th><th>Stage</th><th>Status</th></tr></thead>
                  <tbody>{members.map((m, i) => (
                    <tr key={i}><td>{m.contacts?.full_name}</td><td className="small">{m.contacts?.contact_type}</td>
                      <td className="small">{m.contacts?.email || '—'}</td>
                      <td><Badge>{m.contacts?.lifecycle_stage}</Badge></td>
                      <td><Badge>{m.member_status}</Badge></td></tr>))}</tbody></table></div>
              )}
            </div>
          </div>

          <div className="stack">
            <form className="card" onSubmit={(e) => saveCampaign(e, id)}>
              <div className="card-head"><h3>Campaign settings</h3></div>
              <div className="card-body">
                <div className="field"><label>Name</label><input name="campaign_name" defaultValue={current.campaign_name} /></div>
                <div className="field"><label>Status</label>
                  <select name="status" defaultValue={current.status}>{STATUS.map((s) => <option key={s}>{s}</option>)}</select></div>
                <div className="field"><label>Objective</label>
                  <select name="objective" defaultValue={current.objective}>{OBJECTIVES.map((s) => <option key={s}>{s}</option>)}</select></div>
                <div className="field"><label>Channel</label>
                  <select name="channel" defaultValue={current.channel}>{CHANNELS.map((s) => <option key={s}>{s}</option>)}</select></div>
                <div className="field"><label>Audience</label>
                  <select name="audience_type" defaultValue={current.audience_type}>
                    <option>All</option><option>B2C</option><option>B2B</option></select></div>
                <div className="row" style={{ gap: 10 }}>
                  <div className="field" style={{ flex: 1 }}><label>Budget</label>
                    <input name="budget" type="number" step="0.01" defaultValue={current.budget ?? ''} /></div>
                  <div className="field" style={{ flex: 1 }}><label>Spend</label>
                    <input name="spend" type="number" step="0.01" defaultValue={current.spend ?? 0} /></div>
                </div>
                <div className="row" style={{ gap: 10 }}>
                  <div className="field" style={{ flex: 1 }}><label>Starts</label>
                    <input name="start_date" type="date" defaultValue={current.start_date || ''} /></div>
                  <div className="field" style={{ flex: 1 }}><label>Ends</label>
                    <input name="end_date" type="date" defaultValue={current.end_date || ''} /></div>
                </div>
                <div className="field"><label>Offer</label><input name="offer" defaultValue={current.offer || ''} /></div>
                <div className="field"><label>The brief</label><textarea name="brief" defaultValue={current.brief || ''} /></div>
              </div>
              <div className="card-foot"><button className="btn btn-primary">Save campaign</button></div>
            </form>

            <form className="card" onSubmit={(e) => addPeople(e, id)}>
              <div className="card-head"><h3>Add people</h3><span className="small muted">{current.audience_type}</span></div>
              {withheld > 0 && (
                <div className="card-body" style={{ paddingBottom: 0 }}>
                  <div className="note plain small">
                    {withheld} {withheld === 1 ? 'person is' : 'people are'} held back: no consent for
                    {' '}{current.channel.toLowerCase()}, or opted out.{' '}
                    <Link className="link" href="/consent">Consent centre</Link>
                  </div>
                </div>)}
              <div className="card-body" style={{ maxHeight: 280, overflowY: 'auto' }}>
                {candidates.length === 0 && <div className="small muted">
                  No one left who may be contacted on {current.channel.toLowerCase()}.</div>}
                {candidates.map((p) => (
                  <label key={p.contact_id} className="row" style={{ gap: 8, padding: '5px 0', cursor: 'pointer' }}>
                    <input type="checkbox" name="contact_id" value={p.contact_id} />
                    <span className="small">{p.full_name}</span>
                    <span className="spacer" /><span className="small faint">{p.contact_type}</span>
                  </label>))}
              </div>
              <div className="card-foot"><button className="btn btn-sm">Add selected</button></div>
            </form>
          </div>
        </div>
      </Page>
    );
  }

  const live = d.camps.filter((c) => ['Running', 'Scheduled'].includes(c.status));
  return (
    <Page title="Campaigns" sub="Plan the audience, the offer and the content in one place.">
      <ErrorNote error={q.error || err} />
      <div className="kpi-row" style={{ marginBottom: 18 }}>
        <Stat label="In flight" value={live.length} delta={`${d.camps.length} campaigns total`} />
        <Stat label="Budget committed" value={money(d.camps.reduce((s, c) => s + Number(c.budget || 0), 0))} />
        <Stat label="Spent so far" value={money(d.camps.reduce((s, c) => s + Number(c.spend || 0), 0))} />
        <Stat label="Content planned" value={d.posts.length} />
      </div>

      <div className="grid" style={{ gridTemplateColumns: '1fr 340px' }}>
        <div className="card">
          <div className="card-head"><h3>All campaigns</h3></div>
          {d.camps.length === 0 ? <Empty title="No campaigns yet" hint="Start one on the right." /> : (
            <div className="t-wrap"><table className="table">
              <thead><tr><th>Campaign</th><th>Channel</th><th>Audience</th><th className="num">People</th>
                <th className="num">Posts</th><th>Status</th><th></th></tr></thead>
              <tbody>{d.camps.map((c) => (
                <tr key={c.campaign_id}>
                  <td><strong>{c.campaign_name}</strong><div className="small faint">{c.objective}</div></td>
                  <td className="small">{c.channel}</td>
                  <td className="small">{c.audience_type}</td>
                  <td className="num">{d.members.filter((m) => m.campaign_id === c.campaign_id).length}</td>
                  <td className="num">{d.posts.filter((p) => p.campaign_id === c.campaign_id).length}</td>
                  <td><Badge>{c.status}</Badge></td>
                  <td style={{ textAlign: 'right' }}>
                    <button className="btn btn-sm" onClick={() => router.replace(`/campaigns?id=${c.campaign_id}`)}>Open</button></td>
                </tr>))}</tbody></table></div>
          )}
        </div>

        <form className="card" onSubmit={createCampaign}>
          <div className="card-head"><h3>New campaign</h3></div>
          <div className="card-body">
            <div className="field"><label>Campaign name</label><input name="campaign_name" required placeholder="Festive Edit — Instagram" /></div>
            <div className="field"><label>Objective</label>
              <select name="objective" defaultValue="Sales">{OBJECTIVES.map((o) => <option key={o}>{o}</option>)}</select></div>
            <div className="field"><label>Channel</label>
              <select name="channel" defaultValue="Instagram">{CHANNELS.map((o) => <option key={o}>{o}</option>)}</select></div>
            <div className="field"><label>Audience</label>
              <select name="audience_type" defaultValue="B2C"><option>All</option><option>B2C</option><option>B2B</option></select></div>
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

export default function Wrapped() {
  return <Suspense fallback={<Loading />}><Campaigns /></Suspense>;
}
