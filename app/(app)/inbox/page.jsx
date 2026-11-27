'use client';
import { useEffect, useState } from 'react';
import Link from 'next/link';
import { useQuery, sb, updateRow } from '@/lib/db';
import { runWhatsapp } from '@/lib/assist';
import { Page, Badge, Empty, Loading, ErrorNote, when } from '@/components/ui';
import Dictate from '@/components/Dictate';

// A number nobody owns, so a test conversation never lands on a real customer's
// thread. It is a field rather than a constant so two test people can be tried.
const TEST_FROM = '910000000001';

// How long a free reply is still allowed. The number comes from the view, so
// this only has to read it -- the page and the agent cannot drift apart about
// whether the window is open.
function windowLabel(c) {
  if (!c?.last_in_at) return 'They have not written yet';
  if (!c.window_open) return 'Window closed — a reply needs an approved template';
  const m = Number(c.window_minutes_left || 0);
  if (m < 60) return `${m} min left to reply freely`;
  return `${Math.floor(m / 60)}h left to reply freely`;
}

export default function Inbox() {
  const [sel, setSel] = useState(null);
  const [onlyMine, setOnlyMine] = useState(false);
  const [answer, setAnswer] = useState('');
  const [tryFrom, setTryFrom] = useState(TEST_FROM);
  const [tryText, setTryText] = useState('');
  const [busy, setBusy] = useState('');
  const [err, setErr] = useState('');
  const [last, setLast] = useState(null);
  const [health, setHealth] = useState(null);

  const q = useQuery(async (c) => {
    const [convos, rules, h] = await Promise.all([
      c.from('conversation_state').select('*')
        .order('escalated', { ascending: false })
        .order('last_in_at', { ascending: false, nullsFirst: false }).limit(60),
      c.from('escalation_topics').select('*').order('sort_order'),
      runWhatsapp({ action: 'health' }).catch(() => null),
    ]);
    return { convos: convos.data || [], rules: rules.data || [], health: h };
  }, []);

  useEffect(() => { if (q.data?.health) setHealth(q.data.health); }, [q.data]);

  const convos = q.data?.convos || [];
  const shown = onlyMine ? convos.filter((c) => c.escalated) : convos;
  const convo = convos.find((c) => c.conversation_id === sel) || null;
  const waiting = convos.filter((c) => c.escalated).length;

  const m = useQuery(async (c) => {
    if (!sel) return { messages: [] };
    const { data } = await c.from('conversation_messages').select('*')
      .eq('conversation_id', sel).order('created_at');
    return { messages: data || [] };
  }, [sel]);
  const messages = m.data?.messages || [];

  async function sendAnswer() {
    if (!convo || !answer.trim()) return;
    setBusy('answering'); setErr('');
    try {
      await runWhatsapp({ action: 'answer', conversation_id: convo.conversation_id,
                          body: answer.trim() });
      setAnswer('');
      q.reload(); m.reload();
    } catch (e) { setErr(e.message || String(e)); }
    setBusy('');
  }

  async function closeIt() {
    if (!convo) return;
    setBusy('closing'); setErr('');
    try {
      await runWhatsapp({ action: 'close', conversation_id: convo.conversation_id });
      q.reload();
    } catch (e) { setErr(e.message || String(e)); }
    setBusy('');
  }

  // Runs the real path -- the same rules, the same rails, the same drafting --
  // against a conversation marked as a test, so the list can be tuned before a
  // customer is on the other end.
  async function tryOne() {
    if (!tryText.trim()) return;
    setBusy('trying'); setErr(''); setLast(null);
    try {
      const out = await runWhatsapp({
        action: 'test', from: tryFrom, name: 'Test', text: tryText.trim(),
      });
      setLast(out);
      setTryText('');
      setSel(out.conversation_id || null);
      q.reload(); m.reload();
    } catch (e) { setErr(e.message || String(e)); }
    setBusy('');
  }

  async function toggleRule(r) {
    setErr('');
    try {
      await updateRow('escalation_topics', 'topic_id', r.topic_id, { active: !r.active });
      q.reload();
    } catch (e) { setErr(e.message || String(e)); }
  }

  return (
    <Page title="Inbox" sub="What customers asked, and what was answered"
      actions={<>
        <Link className="btn btn-sm" href="/templates">Message templates</Link>
        <Link className="btn btn-sm" href="/contacts">Contacts</Link>
      </>}>
      <ErrorNote error={q.error || m.error || err} />

      {health && health.transport !== 'connected' && (
        <div className="note warn small" data-transport style={{ marginBottom: 14 }}>
          <strong>No WhatsApp number is connected yet,</strong> so nothing here has actually been
          sent. Everything below is what would have gone out. Attach a number and the same replies
          start sending on their own.
        </div>)}

      <div className="grid" style={{ gridTemplateColumns: '320px 1fr', gap: 14 }}>
        <div className="card">
          <div className="card-head">
            <h3>Conversations</h3>
            {waiting > 0
              ? <Badge>Needs you</Badge>
              : <span className="small muted">{convos.length}</span>}
          </div>
          <div className="card-body" style={{ padding: 8 }}>
            <label className="row small" style={{ gap: 5, cursor: 'pointer', padding: '0 4px 8px' }}>
              <input type="checkbox" checked={onlyMine} style={{ width: 'auto' }}
                onChange={(e) => setOnlyMine(e.target.checked)} />
              Only the ones waiting on you{waiting > 0 ? ` (${waiting})` : ''}
            </label>
            {q.loading ? <Loading /> : shown.length === 0 ? (
              <div className="small faint" style={{ padding: 8 }}>
                {onlyMine ? 'Nothing is waiting on you.' : 'Nobody has written yet.'}
              </div>
            ) : shown.map((c) => (
              <button key={c.conversation_id} onClick={() => setSel(c.conversation_id)}
                className={`thread-row ${sel === c.conversation_id ? 'on' : ''}`}>
                <div className="thread-name">
                  {c.wa_name || c.wa_phone}
                  {c.is_test && <span className="faint"> · test</span>}
                </div>
                <div className="row" style={{ gap: 4, marginTop: 3 }}>
                  <Badge>{c.status}</Badge>
                  <span className="small faint">{when(c.last_in_at, true)}</span>
                </div>
                {c.topic && <div className="small muted" style={{ marginTop: 2 }}>{c.topic}</div>}
              </button>))}
          </div>
        </div>

        <div className="stack">
          {!convo ? (
            <div className="card"><div className="card-body">
              <Empty title="No conversation picked"
                hint="Pick one on the left to read it, or try a message below to see what the agent does with it." />
            </div></div>
          ) : (
            <div className="card">
              <div className="card-head">
                <h3>{convo.wa_name || convo.wa_phone}</h3>
                <div className="row" style={{ gap: 6 }}>
                  <Badge>{convo.status}</Badge>
                  {convo.contact_id && (
                    <Link className="link small" href={`/contacts?id=${convo.contact_id}`}>
                      Their record</Link>)}
                </div>
              </div>
              <div className="card-body stack" style={{ gap: 10 }}>
                <div className="small faint" data-window>{windowLabel(convo)}</div>

                {convo.escalated && (
                  <div className="note warn small" data-escalated>
                    <strong>{convo.escalation_rule}</strong>
                    {convo.escalation_note ? <div>{convo.escalation_note}</div> : null}
                  </div>)}

                {m.loading ? <Loading /> : messages.map((x) => (
                  <div key={x.message_id} className={`chat ${x.direction === 'out' ? 'owner' : ''}`}>
                    <div className="chat-who">
                      {x.direction === 'in' ? 'Customer'
                        : x.written_by === 'owner' ? 'You' : 'The agent'}
                      <span className="faint"> · {when(x.created_at, true)}</span>
                    </div>
                    <div className="chat-body">{x.body}</div>
                    {/* The status sits under the message, not in the name line:
                        .chat-who uppercases everything inside it, and a badge
                        reading READY TO SEND is the only uppercase badge in the
                        project. It also has to be legible — a reply that never
                        went out must not read like one that did. */}
                    {x.direction === 'out' && x.status !== 'Sent' && (
                      <div style={{ marginTop: 4 }}><Badge>{x.status}</Badge></div>)}
                    {x.held_reason && (
                      <div className="small faint" style={{ marginTop: 3 }}>{x.held_reason}</div>)}
                    {x.rule_hit && (
                      <div className="small faint" style={{ marginTop: 3 }}>
                        Matched your {x.rule_hit} rule.
                      </div>)}
                  </div>))}
              </div>
              <div className="card-foot stack" style={{ gap: 8 }}>
                <div className="field" style={{ marginBottom: 0 }}>
                  <label>Your reply</label>
                  <textarea value={answer} style={{ minHeight: 64 }}
                    placeholder="Answer them yourself…"
                    onChange={(e) => setAnswer(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
                        e.preventDefault(); sendAnswer();
                      }
                    }} />
                  <Dictate compact onText={(f) => setAnswer((cur) => f(cur))} />
                </div>
                <div className="row" style={{ gap: 7 }}>
                  <button className="btn btn-primary btn-sm" onClick={sendAnswer}
                    disabled={Boolean(busy) || !answer.trim()}>
                    {busy === 'answering' ? 'Saving…' : 'Reply'}
                  </button>
                  <button className="btn btn-ghost btn-sm" type="button" onClick={closeIt}
                    disabled={Boolean(busy) || convo.status === 'Closed'}>
                    {busy === 'closing' ? 'Closing…' : 'Close it'}
                  </button>
                </div>
              </div>
            </div>
          )}

          <div className="card" data-try>
            <div className="card-head"><h3>Try a message</h3></div>
            <div className="card-body stack" style={{ gap: 10 }}>
              <div className="small muted">
                Type what a customer might say and watch what happens to it. It runs the real
                rules and the real rails against a conversation marked as a test, so no real
                conversation is touched and nothing is sent.
              </div>
              <div className="field" style={{ marginBottom: 0 }}>
                <label>What they say</label>
                <textarea value={tryText} style={{ minHeight: 56 }}
                  placeholder="Is this one still available? · Can you give me a discount?"
                  onChange={(e) => setTryText(e.target.value)} />
              </div>
              <div className="row wrap" style={{ gap: 9 }}>
                <div className="field" style={{ marginBottom: 0, width: 190 }}>
                  <label>From</label>
                  <input value={tryFrom} onChange={(e) => setTryFrom(e.target.value)} />
                </div>
                <span className="spacer" />
                <button className="btn btn-primary btn-sm" onClick={tryOne}
                  disabled={Boolean(busy) || !tryText.trim()}>
                  {busy === 'trying' ? 'Working…' : 'Try it'}
                </button>
              </div>

              {last && (
                <div className={`note ${last.escalated ? 'warn' : 'good'} small`} data-outcome>
                  {last.escalated ? (
                    <>
                      <strong>Sent to you: {last.rule}.</strong>{' '}
                      {last.matched ? `It matched "${last.matched}".` : ''}
                      {last.why ? ` ${last.why}` : ''}
                      {last.draft ? <div style={{ marginTop: 4 }}>
                        It had written: {last.draft}</div> : null}
                    </>
                  ) : (
                    <>
                      <strong>The agent answered it.</strong>{' '}
                      {last.status === 'Sent' ? 'Sent.' : 'Written, not sent — no number attached.'}
                      {last.draft ? <div style={{ marginTop: 4 }}>{last.draft}</div> : null}
                    </>
                  )}
                </div>)}
            </div>
          </div>

          <div className="card" data-rules>
            <div className="card-head">
              <h3>What goes to you</h3>
              <span className="small muted">
                {(q.data?.rules || []).filter((r) => r.active).length} on
              </span>
            </div>
            <div className="card-body stack" style={{ gap: 8 }}>
              <div className="small muted">
                Checked before the agent is asked anything, so a message on this list never gets
                an automatic answer. Turn one off and the agent starts handling it itself.
              </div>
              {(q.data?.rules || []).map((r) => (
                <div key={r.topic_id} className="small">
                  <label className="row" style={{ gap: 6, cursor: 'pointer' }}>
                    <input type="checkbox" checked={r.active} style={{ width: 'auto' }}
                      onChange={() => toggleRule(r)} />
                    <strong>{r.label}</strong>
                    <span className="faint">{(r.patterns || []).length} words</span>
                  </label>
                  {r.note && (
                    <div className="muted" style={{ paddingLeft: 22, marginTop: 2 }}>{r.note}</div>)}
                </div>))}
              <div className="small faint">
                Whatever is turned off here, the agent still never states a price that is not
                recorded against a piece, never promises a date, and never guarantees anything.
                Those are not a list — they are checked on every reply it writes.
              </div>
            </div>
          </div>
        </div>
      </div>
    </Page>
  );
}
