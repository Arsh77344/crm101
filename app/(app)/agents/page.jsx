'use client';
import { useState, useEffect } from 'react';
import Link from 'next/link';
import { useQuery, insertRow } from '@/lib/db';
import { runAgent, PROVIDERS, NO_KEYS, providerLabel, providerOption,
  providerHint, hasKey, firstWithKey } from '@/lib/assist';
import { Page, Badge, Loading, ErrorNote, Empty, when } from '@/components/ui';

const DEPARTMENTS = [
  ['sales', 'Sales', '⇄', 'Pipeline, follow-ups and who to call back.'],
  ['marketing', 'Marketing', '◈', 'Campaigns, content gaps, the list and what worked.'],
  ['operations', 'Operations', '⚒', 'Stock, commissions, parcels and launches.'],
  ['finance', 'Finance', '◪', 'Margins, unpaid links, spend and returns.'],
  ['customers', 'Customers', '◎', 'Who went quiet, who to turn into a repeat buyer.'],
];
const TONE = { high: 'b-red', medium: 'b-amber', low: '' };

export default function Agents() {
  const [dept, setDept] = useState('sales');
  const [provider, setProvider] = useState('openai');
  const [running, setRunning] = useState(false);
  const [report, setReport] = useState(null);
  const [err, setErr] = useState('');
  const [added, setAdded] = useState([]);

  const q = useQuery(async (c) => {
    const [runs, keys] = await Promise.all([
      c.from('agent_runs').select('*').order('created_at', { ascending: false }).limit(20),
      runAgent({ action: 'health' }).catch(() => NO_KEYS),
    ]);
    return { runs: runs.data || [], keys };
  }, []);

  const keys = q.data?.keys;
  useEffect(() => {
    if (keys && !keys[provider]) setProvider(firstWithKey(keys, provider));
  }, [keys]);
  const keyFor = (p) => hasKey(keys, p);
  const meta = DEPARTMENTS.find((d) => d[0] === dept);

  async function run() {
    setRunning(true); setErr(''); setReport(null); setAdded([]);
    try {
      const out = await runAgent({ action: 'run', department: dept, provider });
      setReport(out.result);
      q.reload();
    } catch (e) { setErr(e.message || String(e)); }
    setRunning(false);
  }

  async function accept(action, i) {
    try {
      await insertRow('tasks', {
        title: action.title,
        detail: `${action.detail}\n\nRaised by the ${meta[1]} agent.`,
        priority: ['Low', 'Normal', 'High', 'Urgent'].includes(action.priority) ? action.priority : 'Normal',
        due_on: action.due_in_days != null
          ? new Date(Date.now() + Number(action.due_in_days) * 864e5).toISOString().slice(0, 10)
          : null,
        status: 'To do',
        raised_by: `${meta[1]} agent`,
      });
      setAdded((a) => [...a, i]);
    } catch (e) { setErr(e.message || String(e)); }
  }

  const past = (q.data?.runs || []).filter((r) => r.department === dept);

  return (
    <Page title="Department agents"
      sub="Each one reads its own part of the business and tells you what needs doing."
      actions={<Link className="btn" href="/tasks">Tasks</Link>}>
      <ErrorNote error={q.error || err} />

      <div className="kpi-row" style={{ marginBottom: 16 }}>
        {DEPARTMENTS.map(([key, title, ico, blurb]) => (
          <button key={key} className="card stat" onClick={() => { setDept(key); setReport(null); }}
            style={{ textAlign: 'left', cursor: 'pointer',
              borderColor: dept === key ? 'var(--accent)' : 'var(--line)',
              background: dept === key ? 'var(--accent-wash)' : 'var(--panel)' }}>
            <div className="label">{ico} {title}</div>
            <div className="small muted" style={{ marginTop: 5, lineHeight: 1.4 }}>{blurb}</div>
          </button>))}
      </div>

      <div className="grid" style={{ gridTemplateColumns: '1fr 320px' }}>
        <div className="stack">
          {report ? (
            <>
              <div className="card">
                <div className="card-head"><h3>{meta[1]} — what it found</h3>
                  <span className="small faint">just now</span></div>
                <div className="card-body">
                  <div style={{ marginBottom: 14 }}>{report.summary}</div>
                  <div className="stack" style={{ gap: 11 }}>
                    {(report.findings || []).map((f, i) => (
                      <div key={i} className="row" style={{ alignItems: 'flex-start', gap: 10 }}>
                        <span className={`badge ${TONE[f.severity] ?? ''}`}>{f.severity || 'note'}</span>
                        <div style={{ flex: 1 }}>
                          <div style={{ fontWeight: 500 }}>{f.title}</div>
                          <div className="small muted">{f.detail}</div>
                        </div>
                      </div>))}
                    {(report.findings || []).length === 0 && (
                      <div className="small muted">Nothing worth flagging in this department right now.</div>)}
                  </div>
                </div>
              </div>

              <div className="card">
                <div className="card-head"><h3>What it suggests doing</h3>
                  <span className="small muted">{(report.actions || []).length} actions</span></div>
                <div className="t-wrap"><table className="table">
                  <thead><tr><th>Action</th><th>Priority</th><th>By</th><th></th></tr></thead>
                  <tbody>
                    {(report.actions || []).map((a, i) => (
                      <tr key={i}>
                        <td><strong className="small">{a.title}</strong>
                          <div className="small muted">{a.detail}</div></td>
                        <td><Badge>{a.priority}</Badge></td>
                        <td className="small faint">
                          {a.due_in_days != null
                            ? when(new Date(Date.now() + Number(a.due_in_days) * 864e5)) : '—'}</td>
                        <td style={{ textAlign: 'right' }}>
                          <button className="btn btn-sm" disabled={added.includes(i)}
                            onClick={() => accept(a, i)}>
                            {added.includes(i) ? 'Added' : 'Add as task'}</button></td>
                      </tr>))}
                    {(report.actions || []).length === 0 && (
                      <tr><td colSpan="4" className="small muted">Nothing to do right now.</td></tr>)}
                  </tbody></table></div>
              </div>
            </>
          ) : (
            <div className="card">
              <div className="card-head"><h3>{meta[1]} agent</h3></div>
              <Empty title={running ? 'Reading the records…' : `Run the ${meta[1].toLowerCase()} agent`}
                hint={running
                  ? 'It is going through this department now.'
                  : meta[3] + ' It reads only this department, and only what is in the database.'} />
            </div>)}

          <div className="card">
            <div className="card-head"><h3>Earlier runs</h3>
              <span className="small faint">{meta[1]}</span></div>
            {q.loading ? <Loading /> : past.length === 0
              ? <div className="card-body small muted">No runs yet.</div>
              : (<div className="t-wrap"><table className="table">
                  <thead><tr><th>When</th><th>Summary</th><th>Found</th><th>Status</th></tr></thead>
                  <tbody>{past.map((r) => (
                    <tr key={r.run_id}>
                      <td className="small faint">{when(r.created_at, true)}</td>
                      <td className="small" style={{ maxWidth: 380 }}>{r.summary || r.error || '—'}</td>
                      <td className="num">{(r.findings || []).length}</td>
                      <td><Badge>{r.status}</Badge></td>
                    </tr>))}</tbody></table></div>)}
          </div>
        </div>

        <div className="panel">
          <div className="card">
            <div className="card-head"><h3>Run</h3></div>
            <div className="card-body">
              <div className="field"><label>Department</label>
                <select value={dept} onChange={(e) => { setDept(e.target.value); setReport(null); }}>
                  {DEPARTMENTS.map(([k, t]) => <option key={k} value={k}>{t}</option>)}</select></div>
              <div className="field"><label>Which model</label>
                <select value={provider} onChange={(e) => setProvider(e.target.value)}>
                  {PROVIDERS.map(([k]) => (
                    <option key={k} value={k}>{providerOption(k, keys)}</option>))}
                </select>
                <span className="hint">{providerHint(provider)}</span></div>
              <div className="small faint">
                The agent reads this department's records on the server and never sees anything outside it.
                It is told to use only what is in the data.
              </div>
            </div>
            <div className="card-foot">
              <button className="btn btn-primary" style={{ width: '100%' }}
                onClick={run} disabled={running || !keyFor(provider)}>
                {running ? 'Working…' : `Run the ${meta[1].toLowerCase()} agent`}</button>
              {keys && !keyFor(provider) && (
                <div className="small faint" style={{ marginTop: 6 }}>
                  No key for {providerLabel(provider)} yet.</div>)}
            </div>
          </div>
        </div>
      </div>
    </Page>
  );
}
