import { supabaseServer, currentUser, canManage } from '@/lib/supabase';
import { quickUpdate } from '@/lib/actions';
import { Page, Badge, when } from '@/components/ui';
import Flash from '@/components/Flash';
export const dynamic = 'force-dynamic';

const STATUS = ['Disconnected', 'Configured', 'Connected', 'Error'];

export default async function Integrations({ searchParams }) {
  const sb = supabaseServer();
  const user = await currentUser();
  const manager = canManage(user.profile?.role);
  const { data: rows = [] } = await sb.from('integrations').select('*').order('category').order('provider');
  const update = quickUpdate.bind(null, 'integrations', 'integration_id', '/integrations');

  const groups = rows.reduce((acc, r) => { (acc[r.category || 'Other'] ||= []).push(r); return acc; }, {});

  return (
    <Page title="Integrations" sub="The outside services this workspace talks to.">
      <Flash params={searchParams} />
      <div className="note" style={{ marginBottom: 18 }}>
        API keys are not stored in this table. They go in the deployment's environment settings, so they never sit in the database
        or appear on a screen. Mark a service Connected here once its key is in place and a test call has worked.
      </div>
      {!manager && <div className="note warn" style={{ marginBottom: 16 }}>Only an Owner or Admin can change these.</div>}

      <div className="stack">
        {Object.entries(groups).map(([cat, items]) => (
          <div className="card" key={cat}>
            <div className="card-head"><h3>{cat}</h3></div>
            <div className="t-wrap"><table className="table">
              <thead><tr><th>Service</th><th>What it does</th><th>Last checked</th><th>Status</th>{manager && <th></th>}</tr></thead>
              <tbody>{items.map((r) => (
                <tr key={r.integration_id}>
                  <td><strong className="small">{r.provider}</strong></td>
                  <td className="small muted">{r.notes}</td>
                  <td className="small faint">{r.last_checked_at ? when(r.last_checked_at) : '—'}</td>
                  <td><Badge>{r.status}</Badge></td>
                  {manager && (
                    <td><form action={update} className="row" style={{ gap: 6 }}>
                      <input type="hidden" name="_id" value={r.integration_id} />
                      <select name="status" defaultValue={r.status}
                        style={{ padding: '5px 8px', borderRadius: 6, border: '1px solid var(--line)', fontSize: 12.5 }}>
                        {STATUS.map((s) => <option key={s}>{s}</option>)}</select>
                      <button className="btn btn-sm">Save</button>
                    </form></td>)}
                </tr>))}</tbody></table></div>
          </div>))}
      </div>
    </Page>
  );
}
