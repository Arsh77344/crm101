'use client';
import { Suspense, useEffect, useState } from 'react';
import Link from 'next/link';
import { useQuery, sb, insertRow } from '@/lib/db';
import { PROVIDERS, NO_KEYS, providerOption, firstWithKey, runSocial } from '@/lib/assist';
import { Page, Badge, Empty, Loading, ErrorNote, when } from '@/components/ui';
import Dictate from '@/components/Dictate';
import { loadOccasions, runUp, spanLabel, worthMentioning } from '@/lib/occasions';

const KIND = { hashtag: 'b-accent', format: 'b-blue', conversation: 'b-amber', timing: 'b-green' };

function Social() {
  const [brief, setBrief] = useState('');
  const [market, setMarket] = useState('');
  const [days, setDays] = useState(7);
  const [startsOn, setStartsOn] = useState(() => new Date().toISOString().slice(0, 10));
  const [provider, setProvider] = useState('openai');
  const [search, setSearch] = useState(true);
  const [busy, setBusy] = useState('');
  const [err, setErr] = useState('');
  const [plan, setPlan] = useState(null);
  const [searched, setSearched] = useState(true);
  const [saved, setSaved] = useState(null);
  const [keys, setKeys] = useState(null);

  const q = useQuery(async (c) => {
    const [plans, occ, health] = await Promise.all([
      c.from('social_plans').select('*').order('starts_on', { ascending: false }).limit(12),
      loadOccasions(c),
      runSocial({ action: 'health' }).catch(() => NO_KEYS),
    ]);
    return { plans: plans.data || [], occasions: occ, health };
  }, []);

  useEffect(() => { if (q.data?.health) setKeys(q.data.health); }, [q.data]);
  useEffect(() => {
    if (keys && !keys[provider]) setProvider(firstWithKey(keys, provider));
  }, [keys]);

  const ready = Boolean(keys && keys[provider]);
  const soon = worthMentioning(q.data?.occasions || [], 3);
  const canSearch = keys?.can_search?.[provider] !== false;

  async function makePlan() {
    setBusy('planning'); setErr(''); setSaved(null);
    try {
      const out = await runSocial({
        action: 'plan', provider, search, days, market, brief,
      });
      setPlan(out.plan || null);
      setSearched(Boolean(out.searched));
    } catch (e) { setErr(e.message || String(e)); }
    setBusy('');
  }

  // Approval is the only thing that writes. Until it is pressed the week is a
  // draft nobody but the owner has seen.
  async function approve() {
    if (!plan) return;
    setBusy('saving'); setErr('');
    try {
      const row = await insertRow('social_plans', {
        title: plan.title || `Week of ${startsOn}`,
        market: market || null, starts_on: startsOn, days,
        status: 'Planned', occasion_id: plan.occasion_id || null,
        say: plan.say || null, research: plan.research || [],
        replies: plan.replies || [], provider, model: null,
      });
      const planId = row?.plan_id || row?.[0]?.plan_id;
      const posts = (plan.posts || []).map((x) => {
        const d = new Date(`${startsOn}T09:00:00`);
        d.setDate(d.getDate() + (Number(x.day_offset) || 0));
        return {
          plan_id: planId, campaign_id: null,
          channel: x.channel || 'Instagram', placement: x.placement || null,
          title: x.title || null, body: x.body || null,
          hashtags: x.hashtags || null, hashtag_note: x.hashtag_note || null,
          cta: x.cta || null, art_direction: x.art_direction || null,
          product_id: x.product_id || null,
          scheduled_for: d.toISOString(), status: 'Idea',
        };
      });
      if (posts.length) {
        const { error } = await sb().from('campaign_posts').insert(posts);
        if (error) throw error;
      }
      setSaved({ planId, posts: posts.length });
      setPlan(null);
      q.reload();
    } catch (e) { setErr(e.message || String(e)); }
    setBusy('');
  }

  return (
    <Page title="Social" sub="The weekly drumbeat between campaigns"
      actions={<>
        <Link className="btn btn-sm" href="/calendar">Content calendar</Link>
        <Link className="btn btn-sm" href="/studio">Campaign studio</Link>
      </>}>
      <ErrorNote error={q.error || err} />

      {keys && !ready && (
        <div className="note warn small" style={{ marginBottom: 14 }}>
          No key for {provider}. Add it in Supabase Edge Function secrets, or pick another below.
        </div>)}

      <div className="grid" style={{ gridTemplateColumns: '1fr 420px', gap: 14 }}>
        <div className="stack">
          <div className="card">
            <div className="card-head"><h3>Plan a week</h3></div>
            <div className="card-body stack" style={{ gap: 10 }}>
              {soon.length > 0 && (
                <div className="note plain small" data-occasions>
                  <strong>Coming up.</strong>{' '}
                  {soon.map((o, i) => (
                    <span key={o.occasion_id}>
                      {i ? ' · ' : ''}
                      <button className="link link-btn" type="button"
                        onClick={() => setBrief((cur) => (cur.trim()
                          ? `${cur.trim()} Build the week around ${o.name}.`
                          : `A week leading into ${o.name}.`))}>
                        {o.name}
                      </button>
                      {' '}{spanLabel(o)}, {runUp(o).text}
                    </span>))}
                  {' · '}
                  <Link className="link" href="/occasions">The calendar</Link>
                </div>)}

              <div className="field" style={{ marginBottom: 0 }}>
                <label>Anything it should know <span className="faint">(optional)</span></label>
                <textarea value={brief} style={{ minHeight: 60 }}
                  placeholder="Push the two blue pieces. Nothing about weddings this week."
                  onChange={(e) => setBrief(e.target.value)} />
                <Dictate compact onText={(f) => setBrief((cur) => f(cur))} />
              </div>

              <div className="field" style={{ marginBottom: 0 }}>
                <label>Which market</label>
                <input value={market} placeholder="South India · Tamil Nadu · Gulf NRI · all of India"
                  onChange={(e) => setMarket(e.target.value)} />
                <span className="hint">
                  Changes what the occasion is called, what the garment is called, and what a buyer
                  there notices first. The copy is in English either way.
                </span>
              </div>

              <div className="row wrap" style={{ gap: 9 }}>
                <div className="field" style={{ marginBottom: 0, width: 130 }}>
                  <label>Starting</label>
                  <input type="date" value={startsOn}
                    onChange={(e) => setStartsOn(e.target.value)} />
                </div>
                <div className="field" style={{ marginBottom: 0, width: 100 }}>
                  <label>Days</label>
                  <input type="number" min="3" max="14" value={days}
                    onChange={(e) => setDays(Number(e.target.value) || 7)} />
                </div>
              </div>

              <div className="row wrap" style={{ gap: 7 }}>
                <label className="row small" style={{ gap: 5, cursor: 'pointer' }}
                  title="Looks up what is actually trending now. Without it you get no hashtags at all.">
                  <input type="checkbox" checked={search} style={{ width: 'auto' }}
                    onChange={(e) => setSearch(e.target.checked)} />
                  Look up what is trending
                </label>
                <select value={provider} style={{ width: 'auto' }}
                  onChange={(e) => setProvider(e.target.value)}>
                  {PROVIDERS.filter(([k]) => k !== 'nvidia').map(([k]) => (
                    <option key={k} value={k}>{providerOption(k, keys)}</option>))}
                </select>
                <span className="spacer" />
                <button className="btn btn-primary btn-sm" onClick={makePlan}
                  disabled={Boolean(busy) || !ready}>
                  {busy === 'planning' ? 'Working…' : 'Plan the week'}
                </button>
              </div>

              {search && !canSearch && (
                <div className="note warn small" data-nosearch>
                  <strong>{provider} cannot search the web.</strong> It will plan the week, but you
                  will get no hashtags at all rather than remembered ones — a tag written from
                  memory puts you in a feed nobody reads. Pick another model for the tags.
                </div>)}
            </div>
          </div>

          {saved && (
            <div className="note good small" data-saved>
              <strong>{saved.posts} post{saved.posts === 1 ? '' : 's'} on the calendar.</strong>{' '}
              They are saved as ideas, so nothing goes out until you move them on.{' '}
              <Link className="link" href="/calendar">Open the calendar</Link>
            </div>)}

          <div className="card">
            <div className="card-head"><h3>Weeks planned</h3>
              <span className="small muted">{(q.data?.plans || []).length}</span></div>
            <div className="card-body">
              {q.loading ? <Loading /> : (q.data?.plans || []).length === 0 ? (
                <Empty title="No weeks planned yet"
                  hint="Plan one and it lands on the content calendar as ideas." />
              ) : (
                <div className="t-wrap"><table className="table">
                  <thead><tr><th>Week</th><th>Starts</th><th>Days</th><th>Market</th><th>Status</th></tr></thead>
                  <tbody>
                    {q.data.plans.map((x) => (
                      <tr key={x.plan_id}>
                        <td>{x.title}</td>
                        <td className="small">{when(x.starts_on)}</td>
                        <td className="num">{x.days}</td>
                        <td className="small">{x.market || <span className="faint">—</span>}</td>
                        <td><Badge>{x.status}</Badge></td>
                      </tr>))}
                  </tbody></table></div>
              )}
            </div>
          </div>
        </div>

        <div className="stack">
          {!plan ? (
            <div className="card"><div className="card-body">
              <Empty title="No week drafted"
                hint="The posts, the captions and the hashtags appear here before anything is saved." />
            </div></div>
          ) : (
            <>
              <div className="card">
                <div className="card-head"><h3>{plan.title || 'The week'}</h3>
                  <Badge>{(plan.posts || []).length} posts</Badge></div>
                <div className="card-body stack" style={{ gap: 9 }}>
                  {plan.say && <div className="small muted">{plan.say}</div>}

                  {!searched && (
                    <div className="note warn small" data-unverified>
                      <strong>No hashtags on this week.</strong> It could not search, so nothing was
                      verified and none were written. Plan again with a model that can search, or
                      add tags yourself before publishing.
                    </div>)}

                  {(plan.research || []).length > 0 && (
                    <div data-research>
                      <div className="small"><strong>What it looked up:</strong></div>
                      <div className="stack" style={{ gap: 5, marginTop: 5 }}>
                        {plan.research.map((r, i) => (
                          <div key={i} className="small" style={{ paddingLeft: 9,
                               borderLeft: '2px solid var(--line)' }}>
                            <span className={`badge ${KIND[r.kind] || ''}`}>{r.kind}</span>{' '}
                            <strong>{r.what}</strong>
                            {r.found ? <div className="muted">{r.found}</div> : null}
                            {r.where ? <div className="faint">{r.where}</div> : null}
                          </div>))}
                      </div>
                    </div>)}

                  {(plan.needs_shooting || []).length > 0 && (
                    <div className="note plain small" data-needs-shooting>
                      <strong>{plan.needs_shooting.length} piece{plan.needs_shooting.length === 1 ? '' : 's'} it
                      wanted but could not use</strong> — no photographs yet:
                      <ul style={{ margin: '5px 0 0', paddingLeft: 18 }}>
                        {plan.needs_shooting.map((x, i) => <li key={i}>{x.why}</li>)}
                      </ul>
                      <Link className="link" href="/launch">Shoot them on the launch page</Link>
                    </div>)}

                  <div className="row" style={{ gap: 7 }}>
                    <button className="btn btn-primary btn-sm" onClick={approve}
                      disabled={Boolean(busy) || !(plan.posts || []).length}>
                      {busy === 'saving' ? 'Saving…' : 'Put it on the calendar'}
                    </button>
                    <button className="btn btn-ghost btn-sm" type="button"
                      onClick={() => setPlan(null)} disabled={Boolean(busy)}>Discard</button>
                  </div>
                  <span className="hint">
                    Saved as ideas on the content calendar. Nothing is published from here — this
                    workspace is not connected to Instagram, so you post it yourself.
                  </span>
                </div>
              </div>

              <div className="card" data-posts>
                <div className="card-head"><h3>The posts</h3></div>
                <div className="card-body stack" style={{ gap: 11 }}>
                  {(plan.posts || []).map((x, i) => (
                    <div key={i} className="group-card" style={{ cursor: 'default' }}>
                      <div className="row wrap" style={{ gap: 6 }}>
                        <span className="badge b-accent">Day {x.day_offset ?? 0}</span>
                        <span className="badge">{x.channel}{x.placement ? ` / ${x.placement}` : ''}</span>
                      </div>
                      <div className="small" style={{ fontWeight: 600, marginTop: 4 }}>{x.title}</div>
                      {x.body && <div className="small" style={{ marginTop: 3 }}>{x.body}</div>}
                      {x.teaches && (
                        <div className="small muted" style={{ marginTop: 3 }}>
                          <strong>Teaches:</strong> {x.teaches}
                        </div>)}
                      {x.art_direction && (
                        <div className="small muted" style={{ marginTop: 3 }}>
                          <strong>Shot:</strong> {x.art_direction}
                        </div>)}
                      {x.hashtags && (
                        <div className="small mono" style={{ marginTop: 4 }}>{x.hashtags}</div>)}
                      {x.hashtag_note && (
                        <div className="small faint" style={{ marginTop: 2 }}>{x.hashtag_note}</div>)}
                      {x.cta && (
                        <div className="small" style={{ marginTop: 3 }}>
                          <strong>Next step:</strong> {x.cta}
                        </div>)}
                    </div>))}
                </div>
              </div>

              {(plan.replies || []).length > 0 && (
                <div className="card" data-replies>
                  <div className="card-head"><h3>When they ask</h3>
                    <span className="small muted">{plan.replies.length}</span></div>
                  <div className="card-body stack" style={{ gap: 8 }}>
                    {plan.replies.map((r, i) => (
                      <div key={i} className="small">
                        <strong>{r.question}</strong>
                        <div className="muted" style={{ marginTop: 2 }}>{r.answer}</div>
                      </div>))}
                  </div>
                </div>)}
            </>
          )}
        </div>
      </div>
    </Page>
  );
}

export default function Wrapped() {
  return <Suspense fallback={<Loading />}><Social /></Suspense>;
}
