'use client';
import { useState } from 'react';
import { useQuery, updateRow } from '@/lib/db';
import { Page, Stat, Badge, Loading, ErrorNote } from '@/components/ui';

const STATUSES = ['Unknown', 'Allowed', 'OptedIn', 'OptedOut', 'Suppressed', 'DoNotContact'];

export default function Consent() {
  const [err, setErr] = useState('');
  const q = useQuery(async (c) => {
    const { data, error } = await c.from('marketing_permissions')
      .select('*,contacts(contact_id,full_name,email)').order('updated_at', { ascending: false }).limit(400);
    if (error) throw error;
    return data || [];
  }, []);

  async function set(id, status) {
    try { await updateRow('marketing_permissions', 'permission_id', id, { status, updated_at: new Date().toISOString() }); q.reload(); }
    catch (e) { setErr(e.message); }
  }

  const rows = q.data || [];
  const count = (s) => rows.filter((r) => r.status === s).length;

  return (
    <Page title="Consent centre" sub="Who you may contact, on which channel, and why.">
      <ErrorNote error={q.error || err} />
      <div className="kpi-row" style={{ marginBottom: 18 }}>
        <Stat label="Opted in" value={count('OptedIn')} />
        <Stat label="Allowed" value={count('Allowed')} delta="Existing business relationship" />
        <Stat label="Opted out" value={count('OptedOut') + count('DoNotContact')} delta="Do not contact" />
        <Stat label="Unknown" value={count('Unknown')} delta="Needs a lawful basis before sending" />
      </div>
      <div className="note" style={{ marginBottom: 16 }}>
        Campaigns should exclude anyone marked opted out, suppressed or do-not-contact. Keep a note of where each permission came from.
      </div>
      <div className="card">
        <div className="card-head"><h3>Permissions</h3></div>
        {q.loading ? <Loading /> : (
          <div className="t-wrap"><table className="table">
            <thead><tr><th>Person</th><th>Channel</th><th>Basis</th><th>Status</th></tr></thead>
            <tbody>{rows.map((r) => (
              <tr key={r.permission_id}>
                <td>{r.contacts?.full_name}<div className="small faint">{r.contacts?.email}</div></td>
                <td className="small">{r.channel}</td>
                <td className="small">{r.lawful_basis_or_reason || '—'}</td>
                <td><select value={r.status} onChange={(e) => set(r.permission_id, e.target.value)}
                  style={{ padding: '5px 8px', borderRadius: 6, border: '1px solid var(--line)', fontSize: 12.5 }}>
                  {STATUSES.map((s) => <option key={s}>{s}</option>)}</select></td>
              </tr>))}
              {rows.length === 0 && <tr><td colSpan="4" className="small muted">No permissions recorded yet.</td></tr>}
            </tbody></table></div>
        )}
      </div>
    </Page>
  );
}
