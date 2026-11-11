'use client';
import { useState } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import { useQuery, insertRow, sb } from '@/lib/db';
import { assist } from '@/lib/assist';
import { Page, Badge, Loading, ErrorNote, money, when } from '@/components/ui';

const CHANNELS = ['Instagram', 'WhatsApp', 'Email', 'Facebook'];
const OBJECTIVES = ['Launch', 'Sales', 'Awareness', 'Lead generation', 'Retention'];

export default function Generate() {
  const router = useRouter();
  const [err, setErr] = useState('');
  const [busy, setBusy] = useState(false);
  const [plan, setPlan] = useState(null);
  const [picked, setPicked] = useState([]);
  const [collectionId, setCollectionId] = useState('');
  const [opts, setOpts] = useState({
    objective: 'Launch', channels: ['Instagram', 'WhatsApp'], audience: 'B2C',
    days: 14, post_count: 6, budget: '', offer: '', brief: '',
    start: new Date().toISOString().slice(0, 10), provider: 'openai',
  });

  const q = useQuery(async (c) => {
    const [products, collections, members, keys] = await Promise.all([
      c.from('products').select('*,product_images(public_url,is_primary)').order('created_at', { ascending: false }),
      c.from('collections').select('*').eq('status', 'Active').order('sort_order'),
      c.from('product_collections').select('*'),
      assist({ action: 'health' }).catch(() => ({ openai: false, gemini: false, brand_set: false })),
    ]);
    if (products.error) throw products.error;
    return { products: products.data || [], collections: collections.data || [],
      members: members.data || [], keys };
  }, []);

  const d = q.data;
  const keyFor = (p) => (p === 'gemini' ? d?.keys?.gemini : d?.keys?.openai);
  const brandSet = d?.keys?.brand_set;

  const inCollection = collectionId
    ? new Set((d?.members || []).filter((m) => m.collection_id === collectionId).map((m) => m.product_id))
    : null;
  const shown = (d?.products || []).filter((p) => !inCollection || inCollection.has(p.product_id));
  const chosen = (d?.products || []).filter((p) => picked.includes(p.product_id));

  function toggle(id) {
    setPicked((s) => (s.includes(id) ? s.filter((x) => x !== id) : [...s, id]));
  }
  function toggleChannel(ch) {
    setOpts((o) => ({ ...o, channels: o.channels.includes(ch)
      ? o.channels.filter((c) => c !== ch) : [...o.channels, ch] }));
  }

  async function generate() {
    setBusy(true); setErr(''); setPlan(null);
    try {
      const collection = d.collections.find((c) => c.collection_id === collectionId);
      const images = chosen.flatMap((p) => {
        const im = (p.product_images || []).find((i) => i.is_primary) || (p.product_images || [])[0];
        return im ? [im.public_url] : [];
      });
      const out = await assist({
        action: 'campaign', provider: opts.provider,
        products: chosen.map((p) => ({
          public_product_name: p.public_product_name, fabric: p.fabric, colour: p.colour,
          weave_or_motif: p.weave_or_motif, retail_price: p.retail_price, description: p.description,
        })),
        collection: collection ? { name: collection.name, description: collection.story || collection.description } : null,
        objective: opts.objective, channels: opts.channels, audience: opts.audience,
        days: Number(opts.days), post_count: Number(opts.post_count),
        budget: opts.budget, offer: opts.offer, brief: opts.brief,
        images: images.slice(0, 4),
      });
      setPlan(out.result);
    } catch (e) { setErr(e.message || String(e)); }
    setBusy(false);
  }

  async function createCampaign() {
    setBusy(true); setErr('');
    try {
      const start = new Date(opts.start);
      const end = new Date(start.getTime() + Number(opts.days) * 864e5);
      const campaign = await insertRow('campaigns', {
        campaign_name: plan.campaign_name,
        objective: opts.objective,
        audience_type: opts.audience,
        channel: opts.channels[0] || 'Instagram',
        status: 'Draft',
        budget: opts.budget || null,
        start_date: opts.start,
        end_date: end.toISOString().slice(0, 10),
        brief: plan.brief,
        offer: plan.offer || opts.offer || null,
      });
      const byName = {};
      (d.products || []).forEach((p) => { byName[(p.public_product_name || '').toLowerCase()] = p.product_id; });
      const posts = (plan.posts || []).map((post) => ({
        campaign_id: campaign.campaign_id,
        channel: post.channel || opts.channels[0] || 'Instagram',
        title: post.title,
        body: post.body,
        hashtags: post.hashtags || null,
        status: 'Draft',
        product_id: byName[(post.product || '').toLowerCase()] || null,
        scheduled_for: new Date(start.getTime() + (Number(post.day_offset) || 0) * 864e5 + 10 * 3600e3).toISOString(),
      }));
      if (posts.length) {
        const { error } = await sb().from('campaign_posts').insert(posts);
        if (error) throw error;
      }
      router.push(`/campaigns?id=${campaign.campaign_id}`);
    } catch (e) { setErr(e.message || String(e)); }
    setBusy(false);
  }

  if (q.loading) return <Page title="Build a campaign"><Loading /></Page>;

  return (
    <Page title="Build a campaign"
      sub="Pick the pieces or a whole collection, say what it is for, and get a plan you can edit."
      actions={<Link className="btn" href="/campaigns">All campaigns</Link>}>
      <ErrorNote error={q.error || err} />

      {!brandSet && (
        <div className="note" style={{ marginBottom: 14 }}>
          Fill in the brand name and what it sells on <Link className="link" href="/settings">Settings</Link> first.
          Everything written here follows that, so nothing gets invented.
        </div>)}

      <div className="grid" style={{ gridTemplateColumns: '1fr 330px' }}>
        <div className="stack">
          <div className="card">
            <div className="card-head"><h3>What is this campaign about?</h3>
              <span className="small muted">{picked.length} selected</span></div>
            <div className="card-body">
              <div className="row wrap" style={{ marginBottom: 12 }}>
                <button className={`chip ${!collectionId ? 'on' : ''}`} onClick={() => setCollectionId('')}>
                  Everything
                </button>
                {(d.collections || []).map((c) => (
                  <button key={c.collection_id} className={`chip ${collectionId === c.collection_id ? 'on' : ''}`}
                    onClick={() => setCollectionId(c.collection_id)}>{c.name}</button>))}
                <span className="spacer" />
                <button className="btn btn-sm" onClick={() => setPicked(shown.map((p) => p.product_id))}>
                  Select all shown</button>
                {picked.length > 0 && (
                  <button className="btn btn-sm btn-ghost" onClick={() => setPicked([])}>Clear</button>)}
              </div>

              <div className="shots" style={{ gridTemplateColumns: 'repeat(auto-fill,minmax(132px,1fr))' }}>
                {shown.map((p) => {
                  const im = (p.product_images || []).find((i) => i.is_primary) || (p.product_images || [])[0];
                  const on = picked.includes(p.product_id);
                  return (
                    <button key={p.product_id} onClick={() => toggle(p.product_id)}
                      className="card" style={{ padding: 0, overflow: 'hidden', textAlign: 'left', cursor: 'pointer',
                        borderColor: on ? 'var(--accent)' : 'var(--line)',
                        boxShadow: on ? '0 0 0 2px var(--accent-wash)' : 'var(--shadow)' }}>
                      <div style={{ aspectRatio: '3/4', background: 'var(--line-2)', display: 'grid',
                        placeItems: 'center', color: 'var(--ink-3)', fontSize: 11, overflow: 'hidden' }}>
                        {im ? <img src={im.public_url} alt=""
                          style={{ width: '100%', height: '100%', objectFit: 'cover' }} /> : (p.colour || 'No photo')}
                      </div>
                      <div style={{ padding: '7px 8px' }}>
                        <div style={{ fontSize: 12, fontWeight: 500, lineHeight: 1.3 }}>{p.public_product_name}</div>
                        <div className="small faint">{money(p.retail_price)}</div>
                      </div>
                    </button>);
                })}
                {shown.length === 0 && <div className="small muted">Nothing in this collection yet.</div>}
              </div>
            </div>
          </div>

          {plan && (
            <div className="card">
              <div className="card-head"><h3>{plan.campaign_name}</h3>
                <span className="small muted">{(plan.posts || []).length} posts</span></div>
              <div className="card-body">
                <div className="small" style={{ marginBottom: 8 }}>{plan.brief}</div>
                {plan.offer && <div className="note small" style={{ marginBottom: 10 }}>Offer: {plan.offer}</div>}
                <div className="t-wrap"><table className="table">
                  <thead><tr><th>Day</th><th>Shot</th><th>Caption</th><th>Channel</th></tr></thead>
                  <tbody>{(plan.posts || []).map((post, i) => (
                    <tr key={i}>
                      <td className="small faint">
                        {when(new Date(new Date(opts.start).getTime() + (Number(post.day_offset) || 0) * 864e5))}
                      </td>
                      <td><strong className="small">{post.title}</strong>
                        {post.product && <div className="small faint">{post.product}</div>}</td>
                      <td className="small" style={{ maxWidth: 320 }}>{post.body}
                        {post.hashtags && <div className="small faint">{post.hashtags}</div>}</td>
                      <td><Badge>{post.channel}</Badge></td>
                    </tr>))}</tbody></table></div>
              </div>
              <div className="card-foot row">
                <button className="btn btn-primary btn-sm" onClick={createCampaign} disabled={busy}>
                  {busy ? 'Creating…' : 'Create this campaign'}</button>
                <button className="btn btn-sm" onClick={generate} disabled={busy}>Try again</button>
                <span className="spacer" />
                <span className="small faint">You can edit every post afterwards.</span>
              </div>
            </div>)}
        </div>

        <div className="panel">
          <div className="card">
            <div className="card-head"><h3>The plan</h3></div>
            <div className="card-body">
              <div className="field"><label>What is it for</label>
                <select value={opts.objective} onChange={(e) => setOpts({ ...opts, objective: e.target.value })}>
                  {OBJECTIVES.map((o) => <option key={o}>{o}</option>)}</select></div>

              <div className="field"><label>Channels</label>
                <div className="row wrap" style={{ gap: 5 }}>
                  {CHANNELS.map((ch) => (
                    <button key={ch} type="button" onClick={() => toggleChannel(ch)}
                      className={`chip ${opts.channels.includes(ch) ? 'on' : ''}`}>{ch}</button>))}
                </div></div>

              <div className="field"><label>Audience</label>
                <select value={opts.audience} onChange={(e) => setOpts({ ...opts, audience: e.target.value })}>
                  <option>B2C</option><option>B2B</option><option>All</option></select></div>

              <div className="row" style={{ gap: 10 }}>
                <div className="field" style={{ flex: 1 }}><label>Starts</label>
                  <input type="date" value={opts.start} onChange={(e) => setOpts({ ...opts, start: e.target.value })} /></div>
                <div className="field" style={{ flex: 1 }}><label>Runs for</label>
                  <select value={opts.days} onChange={(e) => setOpts({ ...opts, days: e.target.value })}>
                    {[7, 14, 21, 30, 45].map((n) => <option key={n} value={n}>{n} days</option>)}</select></div>
              </div>

              <div className="row" style={{ gap: 10 }}>
                <div className="field" style={{ flex: 1 }}><label>How many posts</label>
                  <select value={opts.post_count} onChange={(e) => setOpts({ ...opts, post_count: e.target.value })}>
                    {[3, 4, 6, 8, 10, 12].map((n) => <option key={n} value={n}>{n}</option>)}</select></div>
                <div className="field" style={{ flex: 1 }}><label>Budget</label>
                  <input type="number" value={opts.budget} placeholder="optional"
                    onChange={(e) => setOpts({ ...opts, budget: e.target.value })} /></div>
              </div>

              <div className="field"><label>Offer</label>
                <input value={opts.offer} placeholder="Leave empty and it decides"
                  onChange={(e) => setOpts({ ...opts, offer: e.target.value })} /></div>

              <div className="field"><label>Anything it must know</label>
                <textarea value={opts.brief} placeholder="The shoot is done. Launch before the wedding season."
                  onChange={(e) => setOpts({ ...opts, brief: e.target.value })} /></div>

              <div className="field"><label>Which model</label>
                <select value={opts.provider} onChange={(e) => setOpts({ ...opts, provider: e.target.value })}>
                  <option value="openai">OpenAI (GPT){d.keys && !d.keys.openai ? ' — no key yet' : ''}</option>
                  <option value="gemini">Google (Gemini){d.keys && !d.keys.gemini ? ' — no key yet' : ''}</option>
                </select></div>
            </div>
            <div className="card-foot">
              <button className="btn btn-primary" style={{ width: '100%' }} onClick={generate}
                disabled={busy || picked.length === 0 || !keyFor(opts.provider) || !brandSet}>
                {busy ? 'Thinking…' : `Build a campaign for ${picked.length || 'no'} piece${picked.length === 1 ? '' : 's'}`}
              </button>
              {picked.length === 0 && <div className="small faint" style={{ marginTop: 6 }}>Pick at least one piece.</div>}
              {d.keys && !keyFor(opts.provider) && (
                <div className="small faint" style={{ marginTop: 6 }}>
                  No key for {opts.provider === 'gemini' ? 'Gemini' : 'OpenAI'} yet.
                </div>)}
            </div>
          </div>
        </div>
      </div>
    </Page>
  );
}
