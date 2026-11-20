'use client';
import { useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import { useQuery, sb, insertRow, updateRow } from '@/lib/db';
import { PROVIDERS, NO_KEYS, providerOption, firstWithKey, hasKey } from '@/lib/assist';
import { Page, Badge, Empty, Loading, ErrorNote, money, when } from '@/components/ui';

async function agent(body) {
  const { data: { session } } = await sb().auth.getSession();
  const url = `${process.env.NEXT_PUBLIC_SUPABASE_URL}/functions/v1/campaign-agent`;
  const res = await fetch(url, {
    method: 'POST',
    headers: { Authorization: `Bearer ${session?.access_token}`, 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  const out = await res.json();
  if (!res.ok) throw new Error(out.error || `The agent returned ${res.status}.`);
  return out;
}

const MODES = [
  ['Quick', 'Quick draft', 'Takes what you said, assumes the rest, shows a whole campaign now.'],
  ['Interview', 'Take the brief', 'Asks you one thing at a time, then drafts once it has the picture.'],
];

export default function Studio() {
  const [sel, setSel] = useState(null);
  const [draft, setDraft] = useState('');
  const [mode, setMode] = useState('Quick');
  const [provider, setProvider] = useState('gemini');
  const [search, setSearch] = useState(true);
  const [busy, setBusy] = useState('');
  const [err, setErr] = useState('');
  const [keys, setKeys] = useState(null);
  const endRef = useRef(null);

  useEffect(() => {
    agent({ action: 'health' })
      .then((k) => { setKeys(k); setProvider((p) => (k[p] ? p : firstWithKey(k, 'gemini'))); })
      .catch(() => setKeys(NO_KEYS));
  }, []);

  const q = useQuery(async (c) => {
    const { data, error } = await c.from('campaign_threads').select('*')
      .order('updated_at', { ascending: false }).limit(30);
    if (error) throw error;
    return { threads: data || [] };
  }, []);

  const threads = q.data?.threads || [];
  const thread = threads.find((t) => t.thread_id === sel) || null;

  const m = useQuery(async (c) => {
    if (!sel) return { messages: [] };
    const { data, error } = await c.from('campaign_messages').select('*')
      .eq('thread_id', sel).order('created_at');
    if (error) throw error;
    return { messages: data || [] };
  }, [sel]);

  const messages = m.data?.messages || [];
  const proposal = thread?.proposal || null;

  useEffect(() => { endRef.current?.scrollIntoView({ behavior: 'smooth' }); },
    [messages.length, busy]);

  async function send() {
    const text = draft.trim();
    if (!text || busy) return;
    setBusy('thinking'); setErr(''); setDraft('');
    try {
      let id = sel;
      if (!id) {
        const t = await insertRow('campaign_threads', {
          title: text.slice(0, 60), mode, objective: text.slice(0, 200),
        });
        id = t.thread_id; setSel(id); await q.reload();
      }
      await insertRow('campaign_messages', { thread_id: id, role: 'owner', body: text });
      await m.reload();
      const history = [...messages.map((x) => ({ role: x.role, body: x.body })),
                       { role: 'owner', body: text }];
      const out = await agent({ action: 'reply', provider, mode, search,
                               thread_id: id, messages: history });
      await insertRow('campaign_messages', {
        thread_id: id, role: 'agent', body: [out.say, out.ask].filter(Boolean).join('\n\n'),
        proposal: out.proposal || null, model: out.model,
      });
      await updateRow('campaign_threads', 'thread_id', id, {
        proposal: out.proposal || thread?.proposal || null,
        mode, updated_at: new Date().toISOString(),
        ...(out.proposal?.campaign_name ? { title: out.proposal.campaign_name } : {}),
      });
      await Promise.all([m.reload(), q.reload()]);
    } catch (e) { setErr(e.message || String(e)); }
    setBusy('');
  }

  // Nothing is written to the calendar until this is pressed.
  async function approve() {
    if (!proposal || !thread) return;
    setBusy('approve'); setErr('');
    try {
      const start = proposal.start_date || new Date().toISOString().slice(0, 10);
      const campaign = await insertRow('campaigns', {
        campaign_name: proposal.campaign_name || thread.title,
        objective: proposal.objective || 'Sales',
        audience_type: 'B2C', channel: proposal.channel || 'Instagram',
        status: 'Draft', budget: proposal.budget ?? null, spend: 0,
        start_date: start, end_date: proposal.end_date || null,
        brief: proposal.brief || null, offer: proposal.offer || null,
        thread_id: thread.thread_id, art_direction: proposal.art_direction || null,
        audience_note: proposal.audience_note || null, ad_plan: proposal.ad_plan || null,
      });
      const posts = (proposal.posts || []).map((x) => {
        const day = new Date(start);
        day.setDate(day.getDate() + Number(x.day_offset || 0));
        return {
          campaign_id: campaign.campaign_id, channel: x.channel || 'Instagram',
          title: x.title || '', body: x.body || '', hashtags: x.hashtags || '',
          scheduled_for: day.toISOString().slice(0, 10), status: 'Idea',
          product_id: x.product_id || null, art_direction: x.art_direction || null,
          cta: x.cta || null, placement: x.placement || null,
        };
      });
      if (posts.length) {
        const { error } = await sb().from('campaign_posts').insert(posts);
        if (error) throw error;
      }
      await updateRow('campaign_threads', 'thread_id', thread.thread_id,
        { status: 'Approved', campaign_id: campaign.campaign_id });
      await q.reload();
    } catch (e) { setErr(e.message || String(e)); }
    setBusy('');
  }

  const ready = keys && hasKey(keys, provider);

  return (
    <Page title="Campaign studio"
      sub="Design a campaign in conversation. Nothing is scheduled until you approve it."
      actions={<>
        <button className="btn btn-sm" onClick={() => { setSel(null); setDraft(''); }}>New campaign</button>
        <Link className="btn btn-sm" href="/campaigns">All campaigns</Link>
      </>}>
      <ErrorNote error={q.error || err} />

      {keys && !keys.brand_set && (
        <div className="note warn small" style={{ marginBottom: 14 }}>
          <strong>The brand is not described yet.</strong> Fill in what Zarivia sells and who buys
          it on <Link className="link" href="/settings">Settings</Link>, or the agent has nothing
          true to work from.
        </div>)}

      <div className="grid" style={{ gridTemplateColumns: '220px 1fr 380px', gap: 14 }}>
        <div className="card">
          <div className="card-head"><h3>Campaigns</h3></div>
          <div className="card-body" style={{ padding: 8 }}>
            {q.loading ? <Loading /> : threads.length === 0
              ? <div className="small faint" style={{ padding: 8 }}>
                  Nothing yet. Say what you want to sell and to whom.</div>
              : threads.map((t) => (
                <button key={t.thread_id} onClick={() => setSel(t.thread_id)}
                  className={`thread-row ${sel === t.thread_id ? 'on' : ''}`}>
                  <div className="thread-name">{t.title}</div>
                  <div className="row" style={{ gap: 4, marginTop: 3 }}>
                    <Badge>{t.status}</Badge>
                    <span className="small faint">{when(t.updated_at)}</span>
                  </div>
                </button>))}
          </div>
        </div>

        <div className="card" style={{ display: 'flex', flexDirection: 'column', minHeight: 560 }}>
          <div className="card-head">
            <h3>{thread ? thread.title : 'New campaign'}</h3>
            {thread?.status === 'Approved' && thread.campaign_id && (
              <Link className="link small" href={`/campaigns?id=${thread.campaign_id}`}>
                Open the campaign</Link>)}
          </div>
          <div className="card-body" style={{ flex: 1, overflowY: 'auto', maxHeight: 520 }}>
            {messages.length === 0 && (
              <div className="stack" style={{ gap: 10 }}>
                <div className="small muted">
                  Tell it what you are trying to do. It knows your catalogue, your stock, your
                  looks and what you have run before.
                </div>
                <div className="note plain small">
                  <strong>Try:</strong>
                  <ul>
                    <li>Push the blue pieces before wedding season, ₹15,000, two weeks.</li>
                    <li>We have slow stock in the lighter sarees. Move it without discounting hard.</li>
                    <li>Build awareness for Zarivia in Delhi. No sales target yet.</li>
                  </ul>
                </div>
              </div>)}
            {messages.map((x) => (
              <div key={x.message_id} className={`chat ${x.role}`}>
                <div className="chat-who">{x.role === 'owner' ? 'You' : 'Campaign lead'}</div>
                <div className="chat-body">{x.body}</div>
                {x.proposal && <div className="small faint" style={{ marginTop: 4 }}>
                  Draft updated beside this.</div>}
              </div>))}
            {busy === 'thinking' && (
              <div className="chat agent"><div className="chat-who">Campaign lead</div>
                <div className="chat-body muted">
                  {search ? 'Reading your workspace and checking what is on…' : 'Thinking…'}
                </div></div>)}
            <div ref={endRef} />
          </div>
          <div className="card-foot stack" style={{ gap: 8 }}>
            <textarea value={draft} onChange={(e) => setDraft(e.target.value)}
              placeholder={thread ? 'Reply, or tell it what to change…'
                : 'What are you trying to sell, and to whom?'}
              style={{ minHeight: 64, width: '100%', padding: '8px 10px',
                       border: '1px solid var(--line)', borderRadius: 'var(--r-sm)',
                       background: 'var(--panel)' }}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) { e.preventDefault(); send(); }
              }} />
            <div className="row wrap" style={{ gap: 7 }}>
              {MODES.map(([k, label, blurb]) => (
                <button key={k} className={`chip ${mode === k ? 'on' : ''}`} title={blurb}
                  onClick={() => setMode(k)}>{label}</button>))}
              <label className="row small" style={{ gap: 5, cursor: 'pointer' }}
                title="Lets it search the web for dates, festivals and what is working now.">
                <input type="checkbox" checked={search} style={{ width: 'auto' }}
                  onChange={(e) => setSearch(e.target.checked)} />
                Check what is on
              </label>
              <select value={provider} style={{ width: 'auto' }}
                onChange={(e) => setProvider(e.target.value)}>
                {PROVIDERS.map(([k]) => (
                  <option key={k} value={k}>{providerOption(k, keys)}</option>))}
              </select>
              <span className="spacer" />
              <button className="btn btn-primary btn-sm" onClick={send}
                disabled={!draft.trim() || Boolean(busy) || !ready}>
                {busy === 'thinking' ? 'Working…' : 'Send'}</button>
            </div>
            {keys && !ready && (
              <div className="small faint">
                No key for {provider}. Add it in Supabase Edge Function secrets, or pick another.
              </div>)}
            {search && keys?.can_search && !keys.can_search[provider] && (
              <div className="small faint">
                {provider} cannot search the web, so this draft works from your workspace alone.
              </div>)}
          </div>
        </div>

        <div className="stack">
          {!proposal
            ? <div className="card"><div className="card-body">
                <Empty title="No draft yet"
                  hint="The campaign appears here as soon as the agent has one." />
              </div></div>
            : <>
              <div className="card">
                <div className="card-head"><h3>The campaign</h3>
                  <Badge>{thread?.status}</Badge></div>
                <div className="card-body stack" style={{ gap: 9 }}>
                  <div style={{ fontWeight: 600 }}>{proposal.campaign_name}</div>
                  <div className="small muted">{proposal.brief}</div>
                  <div className="row wrap" style={{ gap: 5 }}>
                    <span className="badge">{proposal.objective}</span>
                    <span className="badge">{proposal.channel}</span>
                    {proposal.budget ? <span className="badge">{money(proposal.budget)}</span> : null}
                    <span className="badge">{proposal.start_date} → {proposal.end_date}</span>
                  </div>
                  {proposal.offer && <div className="small"><strong>Offer:</strong> {proposal.offer}</div>}
                  <div className="small"><strong>Who it is for:</strong> {proposal.audience_note}</div>
                  <div className="small"><strong>Art direction:</strong> {proposal.art_direction}</div>
                  {thread?.status !== 'Approved' && (
                    <button className="btn btn-primary btn-sm" onClick={approve}
                      disabled={Boolean(busy)}>
                      {busy === 'approve' ? 'Saving…'
                        : `Approve — write ${(proposal.posts || []).length} posts to the calendar`}
                    </button>)}
                </div>
              </div>

              <div className="card">
                <div className="card-head"><h3>Posts</h3>
                  <span className="small faint">{(proposal.posts || []).length}</span></div>
                <div className="card-body stack" style={{ gap: 10 }}>
                  {(proposal.posts || []).map((x, i) => (
                    <div key={i} style={{ borderLeft: '2px solid var(--line)', paddingLeft: 9 }}>
                      <div className="row" style={{ gap: 5 }}>
                        <span className="badge b-accent">Day {x.day_offset}</span>
                        <span className="small faint">{x.channel} · {x.placement}</span>
                      </div>
                      <div className="small" style={{ fontWeight: 600, marginTop: 3 }}>{x.title}</div>
                      <div className="small muted" style={{ marginTop: 2 }}>{x.body}</div>
                      {x.art_direction && <div className="small faint" style={{ marginTop: 3 }}>
                        Shot: {x.art_direction}</div>}
                      {x.cta && <div className="small faint">CTA: {x.cta}</div>}
                    </div>))}
                </div>
              </div>

              {proposal.ad_plan && (
                <div className="card">
                  <div className="card-head"><h3>Meta ads</h3>
                    <span className="badge b-amber">Draft only</span></div>
                  <div className="card-body stack" style={{ gap: 10 }}>
                    <div className="note warn small">
                      <strong>Nothing here is live.</strong> This workspace is not connected to
                      Meta, so no campaign has been created and no money has moved. Copy it into
                      Ads Manager yourself.
                    </div>
                    {proposal.ad_plan.daily_budget ? (
                      <div className="small"><strong>Daily budget:</strong> {money(proposal.ad_plan.daily_budget)}</div>) : null}
                    {(proposal.ad_plan.ad_sets || []).map((a, i) => (
                      <div key={i} style={{ borderLeft: '2px solid var(--line)', paddingLeft: 9 }}>
                        <div className="small" style={{ fontWeight: 600 }}>{a.name}</div>
                        <div className="small faint">{a.platforms} · {a.placements} · {a.budget_share}</div>
                        <div className="small muted" style={{ marginTop: 3 }}>
                          {[a.audience, a.age, a.geography].filter(Boolean).join(' · ')}
                        </div>
                        {a.interests && <div className="small faint">Interests: {a.interests}</div>}
                        <div className="small" style={{ marginTop: 4 }}>{a.primary_text}</div>
                        <div className="small faint">{a.headline}{a.cta_button ? ` · ${a.cta_button}` : ''}</div>
                      </div>))}
                    {proposal.ad_plan.measurement && (
                      <div className="small"><strong>Watch:</strong> {proposal.ad_plan.measurement}</div>)}
                  </div>
                </div>)}
            </>}
        </div>
      </div>
    </Page>
  );
}
