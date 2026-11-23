'use client';
import { useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import { useQuery, sb, insertRow, updateRow } from '@/lib/db';
import { PROVIDERS, NO_KEYS, providerOption, firstWithKey, hasKey } from '@/lib/assist';
import { Page, Badge, Empty, Loading, ErrorNote, money, when } from '@/components/ui';
import Dictate from '@/components/Dictate';
import { executeCampaign } from '@/lib/execute';
import { loadOccasions, runUp, spanLabel, worthMentioning } from '@/lib/occasions';

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
  // The market the campaign is for. It changes the copy, the language and the
  // casting more than anything else, so it is asked for up front.
  const [market, setMarket] = useState('');
  const [busy, setBusy] = useState('');
  const [err, setErr] = useState('');
  const [step, setStep] = useState('');
  const [ran, setRan] = useState(null);
  const [perPost, setPerPost] = useState(2);
  const [keys, setKeys] = useState(null);

  // What is coming up, shown beside the brief box. The agent reads the same
  // calendar from the database, so what the owner sees here is what it sees.
  const occ = useQuery(async (c) => loadOccasions(c), []);
  const soon = worthMentioning(occ.data || [], 3);
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
  // A thread carries its own market once set; the box follows it.
  const marketOf = thread?.market ?? '';

  useEffect(() => { endRef.current?.scrollIntoView({ behavior: 'smooth' }); },
    [messages.length, busy]);

  async function send(said) {
    const text = String(said ?? draft).trim();
    if (!text || busy) return;
    setBusy('thinking'); setErr(''); setDraft('');
    try {
      let id = sel;
      if (!id) {
        const t = await insertRow('campaign_threads', {
          title: text.slice(0, 60), mode, objective: text.slice(0, 200),
          market: market || null,
        });
        id = t.thread_id; setSel(id); await q.reload();
      }
      await insertRow('campaign_messages', { thread_id: id, role: 'owner', body: text });
      await m.reload();
      const history = [...messages.map((x) => ({ role: x.role, body: x.body })),
                       { role: 'owner', body: text }];
      const out = await agent({ action: 'reply', provider, mode, search,
                               thread_id: id, market, messages: history });
      await insertRow('campaign_messages', {
        thread_id: id, role: 'agent', body: [out.say, out.ask].filter(Boolean).join('\n\n'),
        proposal: out.proposal || null, model: out.model,
      });
      await updateRow('campaign_threads', 'thread_id', id, {
        proposal: out.proposal
          ? { ...out.proposal, options: out.options || [] }
          : thread?.proposal || null,
        mode, market: market || thread?.market || null,
        updated_at: new Date().toISOString(),
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
      let saved = [];
      if (posts.length) {
        const { data, error } = await sb().from('campaign_posts').insert(posts).select();
        if (error) throw error;
        saved = data || [];
      }
      await updateRow('campaign_threads', 'thread_id', thread.thread_id,
        { status: 'Approved', campaign_id: campaign.campaign_id });
      await q.reload();

      // Everything the CRM can do on its own. Meta is where it stops.
      setBusy('executing');
      const withIds = {
        ...proposal,
        posts: (proposal.posts || []).map((x, i) => ({ ...x, post_id: saved[i]?.post_id || null })),
      };
      const result = await executeCampaign({
        proposal: withIds, campaign, thread, perPost, onStep: setStep,
      });
      setRan(result); setStep('');
    } catch (e) { setErr(e.message || String(e)); }
    setBusy(''); setStep('');
  }

  const ready = keys && hasKey(keys, provider);
  const pieces = new Set((proposal?.posts || []).map((x) => x.product_id).filter(Boolean)).size;

  return (
    <Page title="Campaign studio"
      sub="Design a campaign in conversation. Nothing is scheduled until you approve it."
      actions={<>
        <button className="btn btn-sm" onClick={() => { setSel(null); setDraft(''); }}>New campaign</button>
        <Link className="btn btn-sm" href="/campaigns">All campaigns</Link>
      </>}>
      <ErrorNote error={q.error || occ.error || err} />

      {keys && !keys.brand_set && (
        <div className="note warn small" style={{ marginBottom: 14 }}>
          <strong>The brand is not described yet.</strong> Fill in what Zarivia sells and who buys
          it on <Link className="link" href="/settings">Settings</Link>, or the agent has nothing
          true to work from.
        </div>)}

      <div className="grid studio-grid" style={{ gridTemplateColumns: '220px 1fr 380px', gap: 14 }}>
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
            <Dictate onText={(f) => setDraft((cur) => f(cur))} label="Say it instead" />
            {soon.length > 0 && (
              <div className="note plain small" data-occasions>
                <strong>Coming up.</strong>{' '}
                {soon.map((o, i) => (
                  <span key={o.occasion_id}>
                    {i ? ' · ' : ''}
                    <button className="link link-btn" type="button"
                      onClick={() => setDraft((cur) => (cur.trim()
                        ? `${cur.trim()} Build it around ${o.name}.`
                        : `A campaign for ${o.name}.`))}>
                      {o.name}
                    </button>
                    {' '}{spanLabel(o)}, {runUp(o).text}
                  </span>))}
                {' · '}
                <Link className="link" href="/occasions">The calendar</Link>
              </div>)}
            <div className="field" style={{ marginBottom: 9 }}>
              <label>Which market is this for</label>
              <input value={market || marketOf} placeholder="South India · Tamil Nadu · Gulf NRI · all of India"
                onChange={(e) => setMarket(e.target.value)} />
              <span className="hint">
                The single thing that most changes a campaign: the festival it is timed to, the
                language the copy is written in, and who is cast in the pictures. Leave it empty
                and it will ask.
              </span>
            </div>
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
              <button className="btn btn-primary btn-sm" onClick={() => send()}
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
              {(proposal.options || []).length > 1 && (
                <div className="card" style={{ marginBottom: 14 }}>
                  <div className="card-head"><h3>Directions it considered</h3>
                    <span className="small muted">{proposal.options.length}</span></div>
                  <div className="card-body stack" style={{ gap: 9 }}>
                    {proposal.options.map((o, i) => (
                      <div key={i} className={`group-card${o.recommended ? ' on' : ''}`}
                        style={{ padding: '9px 11px', borderRadius: 8,
                                 border: '1px solid var(--line)' }}>
                        <div className="row wrap" style={{ gap: 6 }}>
                          <strong className="small">{o.name}</strong>
                          {o.recommended && <span className="badge b-green">Its pick</span>}
                        </div>
                        {o.spine && <div className="small" style={{ marginTop: 3 }}>{o.spine}</div>}
                        {o.why && <div className="small muted" style={{ marginTop: 3 }}>{o.why}</div>}
                        {o.trade_off && (
                          <div className="small faint" style={{ marginTop: 3 }}>
                            Costs: {o.trade_off}</div>)}
                        {!o.recommended && thread?.status !== 'Approved' && (
                          <button className="btn btn-sm" style={{ marginTop: 7 }}
                            disabled={Boolean(busy)}
                            onClick={() => send(`Build "${o.name}" instead. `
                              + `Keep everything else you can.`)}>
                            Build this one instead</button>)}
                      </div>))}
                  </div>
                </div>)}

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
                  {proposal.spine && (
                    <div className="note small" data-spine>
                      <strong>The spine.</strong> {proposal.spine}
                    </div>)}
                  {proposal.occasion?.name && (
                    <div className="small"><strong>Built on:</strong> {proposal.occasion.name}
                      {proposal.occasion.why ? ` \u2014 ${proposal.occasion.why}` : ''}</div>)}
                  {proposal.offer && <div className="small"><strong>Offer:</strong> {proposal.offer}</div>}
                  <div className="small"><strong>Who it is for:</strong> {proposal.audience_note}</div>
                  <div className="small"><strong>Art direction:</strong> {proposal.art_direction}</div>
                  {proposal.casting && (
                    <div className="small"><strong>Casting:</strong> {proposal.casting}</div>)}
                  {(proposal.channel_plan || []).length > 0 && (
                    <div data-channel-plan>
                      <div className="small"><strong>Across the channels:</strong></div>
                      <div className="stack" style={{ gap: 6, marginTop: 5 }}>
                        {proposal.channel_plan.map((ch, i) => (
                          <div key={i} className="small" style={{ paddingLeft: 9,
                               borderLeft: '2px solid var(--line)' }}>
                            <strong>{ch.channel}</strong>
                            {ch.cadence ? <span className="faint"> · {ch.cadence}</span> : null}
                            {ch.role ? <div className="muted">{ch.role}</div> : null}
                            {ch.first_move ? <div>First move: {ch.first_move}</div> : null}
                            {ch.hands_off_to
                              ? <div className="faint">Hands off to {ch.hands_off_to}</div> : null}
                          </div>))}
                      </div>
                    </div>)}
                  {(proposal.six_cs || []).length > 0 && (
                    <div data-six-cs>
                      <div className="small"><strong>Its own check, the six C’s:</strong></div>
                      <div className="row wrap" style={{ gap: 5, marginTop: 5 }}>
                        {proposal.six_cs.map((x, i) => (
                          <span key={i}
                            className={`badge ${x.verdict === 'met' ? 'b-green' : 'b-amber'}`}
                            title={x.note || ''}>{x.c}</span>))}
                      </div>
                      {proposal.six_cs.filter((x) => x.verdict !== 'met').map((x, i) => (
                        <div key={i} className="small muted" style={{ marginTop: 4 }}>
                          <strong>{x.c}:</strong> {x.note}
                        </div>))}
                    </div>)}
                  {(proposal.pieces || []).length > 0 && (
                    <div className="small">
                      <strong>Pieces it sells:</strong>{' '}
                      {proposal.pieces.filter((x) => x.imagery !== 'ready').length} of{' '}
                      {proposal.pieces.length} still need a shoot
                    </div>)}
                  {thread?.status !== 'Approved' && (
                    <>
                      <div className="field" style={{ marginBottom: 0 }}>
                        <label>Creatives per post</label>
                        <select value={perPost} style={{ width: 90 }}
                          onChange={(e) => setPerPost(Number(e.target.value))}>
                          {[0, 1, 2, 3].map((n) => <option key={n} value={n}>{n}</option>)}
                        </select>
                        <span className="hint">
                          {pieces === 0
                            ? 'No post names a piece from the catalogue, so none can be generated.'
                            : `${perPost * pieces} image${perPost * pieces === 1 ? '' : 's'} across `
                              + `${pieces} piece${pieces === 1 ? '' : 's'}. This is the part that costs.`}
                        </span>
                      </div>
                      <button className="btn btn-primary btn-sm" onClick={approve}
                        disabled={Boolean(busy)}>
                        {busy === 'approve' ? 'Saving…' : busy === 'executing' ? 'Building it…'
                          : 'Approve and build it'}
                      </button>
                      <div className="small faint">
                        Writes the campaign and {(proposal.posts || []).length} posts, groups the
                        pieces into a collection, makes the tracked links, raises the tasks and
                        generates the creatives. It stops at Meta.
                      </div>
                    </>)}
                  {busy === 'executing' && step && (
                    <div className="note small"><strong>{step}</strong></div>)}
                  {ran && (
                    <div className={`note small ${ran.trouble.length ? 'warn' : 'good'}`}>
                      <strong>{ran.trouble.length ? 'Built, with some gaps.' : 'Built.'}</strong>
                      <ul>
                        {ran.done.map((d) => <li key={d}>{d}</li>)}
                        {ran.trouble.map((t) => <li key={t}><strong>{t}</strong></li>)}
                      </ul>
                      Nothing was sent to Meta or posted anywhere.
                    </div>)}
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
