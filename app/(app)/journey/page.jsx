'use client';
import { useState } from 'react';
import Link from 'next/link';
import { useQuery, updateRow, insertRow, formValues } from '@/lib/db';
import { Page, Stat, Badge, Loading, ErrorNote, when, money } from '@/components/ui';

const STAGES = ['New', 'Engaged', 'Lead', 'Opportunity', 'Customer', 'Repeat', 'Dormant'];
const KINDS = ['link_click', 'whatsapp_in', 'whatsapp_out', 'ig_dm', 'showroom_view',
  'enquiry', 'order_placed', 'payment', 'repeat_order', 'return'];

export default function Journey() {
  const [err, setErr] = useState('');
  const q = useQuery(async (c) => {
    const [contacts, rules, events] = await Promise.all([
      c.from('contacts').select('contact_id,full_name,lifecycle_stage,lead_score'),
      c.from('journey_rules').select('*').order('priority'),
      c.from('journey_events').select('*,contacts(full_name)').order('occurred_at', { ascending: false }).limit(40),
    ]);
    if (contacts.error) throw contacts.error;
    return { contacts: contacts.data || [], rules: rules.data || [], events: events.data || [] };
  }, []);

  async function setRule(id, patch) {
    try { await updateRow('journey_rules', 'rule_id', id, patch); q.reload(); }
    catch (e) { setErr(e.message); }
  }
  async function addRule(e) {
    e.preventDefault();
    try { await insertRow('journey_rules', formValues(e.target)); e.target.reset(); q.reload(); }
    catch (e2) { setErr(e2.message); }
  }

  if (q.loading) return <Page title="Customer journey"><Loading /></Page>;
  const d = q.data;
  const at = (s) => d.contacts.filter((c) => c.lifecycle_stage === s).length;
  const funnelStages = STAGES.filter((s) => s !== 'Dormant');
  const peak = Math.max(1, ...funnelStages.map(at));

  return (
    <Page title="Customer journey"
      sub="Where everyone stands, and the rules that move them. Nobody has to update this by hand."
      actions={<Link className="btn" href="/contacts">Contacts</Link>}>
      <ErrorNote error={q.error || err} />

      <div className="kpi-row" style={{ marginBottom: 16 }}>
        <Stat label="People" value={d.contacts.length} />
        <Stat label="Warm" value={d.contacts.filter((c) => ['Engaged', 'Lead', 'Opportunity'].includes(c.lifecycle_stage)).length}
          delta="Engaged, Lead or Opportunity" />
        <Stat label="Customers" value={at('Customer') + at('Repeat')} delta={`${at('Repeat')} have ordered twice or more`} />
        <Stat label="Gone quiet" value={at('Dormant')} />
        <Stat label="Rules running" value={d.rules.filter((r) => r.enabled).length} delta={`of ${d.rules.length}`} />
      </div>

      <div className="grid" style={{ gridTemplateColumns: '1fr 380px' }}>
        <div className="stack">
          <div className="card">
            <div className="card-head"><h3>The funnel</h3>
              <span className="small muted">live, from the contact list</span></div>
            <div className="card-body stack">
              {funnelStages.map((s) => (
                <div key={s}>
                  <div className="row small"><strong style={{ width: 104 }}>{s}</strong>
                    <span className="muted">{at(s)} {at(s) === 1 ? 'person' : 'people'}</span>
                    <span className="spacer" />
                    <span className="faint">{d.contacts.length ? Math.round((at(s) / d.contacts.length) * 100) : 0}%</span>
                  </div>
                  <div className="bar" style={{ marginTop: 3 }}><span style={{ width: `${(at(s) / peak) * 100}%` }} /></div>
                </div>))}
              {at('Dormant') > 0 && (
                <div className="note plain small">
                  {at('Dormant')} {at('Dormant') === 1 ? 'person has' : 'people have'} gone quiet.
                  A win-back campaign is the usual answer.
                </div>)}
            </div>
          </div>

          <div className="card">
            <div className="card-head"><h3>What just happened</h3>
              <span className="small muted">{d.events.length} most recent</span></div>
            {d.events.length === 0
              ? <div className="card-body small muted">
                  Nothing yet. Events arrive when someone clicks a tracked link, messages you,
                  opens a showroom, orders or pays.
                </div>
              : (<div className="t-wrap"><table className="table">
                  <thead><tr><th>When</th><th>Who</th><th>What</th><th>Detail</th><th className="num">Value</th></tr></thead>
                  <tbody>{d.events.map((e) => (
                    <tr key={e.event_id}>
                      <td className="small faint">{when(e.occurred_at, true)}</td>
                      <td className="small">
                        <Link className="link" href={`/contacts?id=${e.contact_id}`}>{e.contacts?.full_name || '—'}</Link>
                      </td>
                      <td><Badge>{e.kind.replace(/_/g, ' ')}</Badge></td>
                      <td className="small muted">{e.detail}</td>
                      <td className="num">{e.value ? money(e.value) : ''}</td>
                    </tr>))}</tbody></table></div>)}
          </div>
        </div>

        <div className="stack">
          <div className="card">
            <div className="card-head"><h3>Rules</h3>
              <span className="small muted">edit these yourself</span></div>
            <div className="card-body stack" style={{ gap: 11 }}>
              {d.rules.map((r) => (
                <div key={r.rule_id} style={{ opacity: r.enabled ? 1 : 0.5 }}>
                  <div className="row">
                    <strong className="small" style={{ flex: 1 }}>{r.name}</strong>
                    <button className="btn btn-sm btn-ghost"
                      onClick={() => setRule(r.rule_id, { enabled: !r.enabled })}>
                      {r.enabled ? 'On' : 'Off'}</button>
                  </div>
                  <div className="small muted">
                    {r.on_kind
                      ? <>When <span className="mono">{r.on_kind.replace(/_/g, ' ')}</span> happens</>
                      : <>After {r.inactivity_days} days of nothing</>}
                    {r.set_stage && <> → move to <strong>{r.set_stage}</strong></>}
                    {r.add_score !== 0 && <> · score {r.add_score > 0 ? '+' : ''}{r.add_score}</>}
                  </div>
                  {r.note && <div className="small faint">{r.note}</div>}
                  <div className="row" style={{ gap: 6, marginTop: 4 }}>
                    <select value={r.set_stage || ''} onChange={(e) => setRule(r.rule_id, { set_stage: e.target.value || null })}
                      style={{ padding: '3px 6px', fontSize: 11.5, borderRadius: 5, border: '1px solid var(--line)' }}>
                      <option value="">no stage change</option>
                      {STAGES.map((s) => <option key={s}>{s}</option>)}
                    </select>
                    <input type="number" defaultValue={r.add_score} style={{ width: 62, padding: '3px 6px', fontSize: 11.5,
                      borderRadius: 5, border: '1px solid var(--line)' }}
                      onBlur={(e) => setRule(r.rule_id, { add_score: Number(e.target.value) })} />
                    <span className="small faint">score</span>
                  </div>
                </div>))}
            </div>
            <form className="card-foot" onSubmit={addRule}>
              <div className="field"><label>Add a rule</label>
                <input name="name" required placeholder="Opened three emails" /></div>
              <div className="row" style={{ gap: 7 }}>
                <select name="on_kind" style={{ flex: 1, padding: '6px 8px', borderRadius: 7, border: '1px solid var(--line)' }}>
                  {KINDS.map((k) => <option key={k} value={k}>{k.replace(/_/g, ' ')}</option>)}
                </select>
                <select name="set_stage" style={{ flex: 1, padding: '6px 8px', borderRadius: 7, border: '1px solid var(--line)' }}>
                  <option value="">no stage change</option>
                  {STAGES.map((s) => <option key={s}>{s}</option>)}
                </select>
                <input name="add_score" type="number" defaultValue="5" style={{ width: 64, padding: '6px 8px',
                  borderRadius: 7, border: '1px solid var(--line)' }} />
              </div>
              <button className="btn btn-sm btn-primary" style={{ marginTop: 8 }}>Add rule</button>
            </form>
          </div>
        </div>
      </div>
    </Page>
  );
}
