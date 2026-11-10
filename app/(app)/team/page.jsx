import { supabaseServer, currentUser, canManage } from '@/lib/supabase';
import { quickUpdate } from '@/lib/actions';
import { Page, Badge, when, initials } from '@/components/ui';
import Flash from '@/components/Flash';
export const dynamic = 'force-dynamic';

const ROLES = ['owner', 'admin', 'sales'];
const WHAT = {
  owner: 'Everything, including roles, settings and deleting records.',
  admin: 'Everything day to day, plus settings and deleting records.',
  sales: 'Create and edit products, contacts, orders and campaigns. Cannot delete or change settings.',
};

export default async function Team({ searchParams }) {
  const sb = supabaseServer();
  const me = await currentUser();
  const manager = canManage(me.profile?.role);
  const { data: rows = [] } = await sb.from('profiles').select('*').order('created_at');
  const update = quickUpdate.bind(null, 'profiles', 'id', '/team');

  return (
    <Page title="Team & roles" sub={`${rows.length} ${rows.length === 1 ? 'person' : 'people'} in this workspace`}>
      <Flash params={searchParams} />
      <div className="grid" style={{ gridTemplateColumns: '1fr 320px' }}>
        <div className="card">
          <div className="card-head"><h3>People</h3></div>
          <div className="t-wrap"><table className="table">
            <thead><tr><th>Name</th><th>Email</th><th>Role</th><th>Joined</th>{manager && <th></th>}</tr></thead>
            <tbody>{rows.map((p) => (
              <tr key={p.id}>
                <td><div className="row" style={{ gap: 8 }}><div className="avatar">{initials(p.full_name || p.email)}</div>
                  <span>{p.full_name || '—'}{p.id === me.id && <span className="small faint"> · you</span>}</span></div></td>
                <td className="small">{p.email}</td>
                <td><Badge>{p.role}</Badge></td>
                <td className="small faint">{when(p.created_at)}</td>
                {manager && (
                  <td><form action={update} className="row" style={{ gap: 6 }}>
                    <input type="hidden" name="_id" value={p.id} />
                    <select name="role" defaultValue={p.role}
                      style={{ padding: '5px 8px', borderRadius: 6, border: '1px solid var(--line)', fontSize: 12.5 }}>
                      {ROLES.map((r) => <option key={r}>{r}</option>)}</select>
                    <button className="btn btn-sm">Save</button>
                  </form></td>)}
              </tr>))}</tbody></table></div>
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
