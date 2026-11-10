'use client';
import { useState } from 'react';
import { useQuery, updateRow } from '@/lib/db';
import { useSession, canManage } from '@/lib/session';
import { Page, Badge, Loading, ErrorNote, when } from '@/components/ui';

const STATUS = ['Disconnected', 'Configured', 'Connected', 'Error'];

export default function Integrations() {
  const { profile } = useSession();
  const manager = canManage(profile?.role);
  const [err, setErr] = useState('');
  const q = useQuery(async (c) => {
    const { data, error } = await c.from('integrations').select('*').order('category').order('provider');
    if (error) throw error;
    return data || [];
  }, []);

  async function set(id, patch) {
    try { await updateRow('integrations', 'integration_id', id, { ...patch, last_checked_at: new Date().toISOString() }); q.reload(); }
    catch (e) { setErr(e.message); }
  }

  const rows = q.data || [];
  const groups = rows.reduce((acc, r) => { (acc[r.category || 'Other'] ||= []).push(r); return acc; }, {});

  return (
    <Page title="Integrations" sub="The outside services this workspace talks to.">
      <ErrorNote error={q.error || err} />
      <div className="note" style={{ marginBottom: 18 }}>
        API keys are not stored in this database. They belong in the deployment's environment settings, so they never sit in a
        table or appear on a screen. Mark a service Connected once its key is in place and a test call has worked.
      </div>
      {!manager && <div className="note warn" style={{ marginBottom: 16 }}>Only an Owner or Admin can change these.</div>}
      {q.loading ? <Loading /> : (
        <div className="stack">
          {Object.entries(groups).map(([cat, items]) => (
            <div className="card" key={cat}>
              <div className="card-head"><h3>{cat}</h3></div>
              <div className="t-wrap"><table className="table">
                <thead><tr><th>Service</th><th>What it does</th><th>Last checked</th><th>Status</th></tr></thead>
                <tbody>{items.map((r) => (
                  <tr key={r.integration_id}>
                    <td><strong className="small">{r.provider}</strong></td>
                    <td className="small muted">{r.notes}</td>
                    <td className="small faint">{r.last_checked_at ? when(r.last_checked_at) : '—'}</td>
                    <td>{manager ? (
                      <select value={r.status} onChange={(e) => set(r.integration_id, { status: e.target.value })}
                        style={{ padding: '5px 8px', borderRadius: 6, border: '1px solid var(--line)', fontSize: 12.5 }}>
                        {STATUS.map((s) => <option key={s}>{s}</option>)}</select>
                    ) : <Badge>{r.status}</Badge>}</td>
                  </tr>))}</tbody></table></div>
            </div>))}
        </div>
      )}
    </Page>
  );
}
