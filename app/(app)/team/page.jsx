'use client';
import { useState } from 'react';
import { useQuery, updateRow } from '@/lib/db';
import { useSession, canManage } from '@/lib/session';
import { Page, Badge, Loading, ErrorNote, when, initials } from '@/components/ui';

const ROLES = ['owner', 'admin', 'sales'];
const WHAT = {
  owner: 'Everything, including roles, settings and deleting records.',
  admin: 'Everything day to day, plus settings and deleting records.',
  sales: 'Create and edit products, contacts, orders and campaigns. Cannot delete or change settings.',
};

export default function Team() {
  const { user, profile } = useSession();
  const manager = canManage(profile?.role);
  const [err, setErr] = useState('');
  const q = useQuery(async (c) => {
    const { data, error } = await c.from('profiles').select('*').order('created_at');
    if (error) throw error;
    return data || [];
  }, []);

  async function setRole(id, role) {
    try { await updateRow('profiles', 'id', id, { role }); q.reload(); }
    catch (e) { setErr(e.message); }
  }

  const rows = q.data || [];
  return (
    <Page title="Team & roles" sub={`${rows.length} ${rows.length === 1 ? 'person' : 'people'} in this workspace`}>
      <ErrorNote error={q.error || err} />
      <div className="grid" style={{ gridTemplateColumns: '1fr 320px' }}>
        <div className="card">
          <div className="card-head"><h3>People</h3></div>
          {q.loading ? <Loading /> : (
            <div className="t-wrap"><table className="table">
              <thead><tr><th>Name</th><th>Email</th><th>Role</th><th>Joined</th></tr></thead>
              <tbody>{rows.map((p) => (
                <tr key={p.id}>
                  <td><div className="row" style={{ gap: 8 }}><div className="avatar">{initials(p.full_name || p.email)}</div>
                    <span>{p.full_name || '—'}{p.id === user?.id && <span className="small faint"> · you</span>}</span></div></td>
                  <td className="small">{p.email}</td>
                  <td>{manager ? (
                    <select value={p.role} onChange={(e) => setRole(p.id, e.target.value)}
                      style={{ padding: '5px 8px', borderRadius: 6, border: '1px solid var(--line)', fontSize: 12.5 }}>
                      {ROLES.map((r) => <option key={r}>{r}</option>)}</select>
                  ) : <Badge>{p.role}</Badge>}</td>
                  <td className="small faint">{when(p.created_at)}</td>
                </tr>))}</tbody></table></div>
          )}
        </div>
        <div className="card">
          <div className="card-head"><h3>What each role can do</h3></div>
          <div className="card-body stack">
            {ROLES.map((r) => (
              <div key={r}><Badge>{r}</Badge><div className="small muted" style={{ marginTop: 4 }}>{WHAT[r]}</div></div>))}
            <div className="note small" style={{ marginTop: 6 }}>
              To add someone, send them the sign-in page and ask them to create an account. They arrive as Sales; promote them here.
            </div>
          </div>
        </div>
      </div>
    </Page>
  );
}
