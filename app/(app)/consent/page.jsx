import Link from 'next/link';
import { supabaseServer } from '@/lib/supabase';
import { quickUpdate } from '@/lib/actions';
import { Page, Badge, Stat } from '@/components/ui';
import Flash from '@/components/Flash';
export const dynamic = 'force-dynamic';

const STATUSES = ['Unknown', 'Allowed', 'OptedIn', 'OptedOut', 'Suppressed', 'DoNotContact'];

export default async function Consent({ searchParams }) {
  const sb = supabaseServer();
  const { data: rows = [] } = await sb.from('marketing_permissions')
    .select('*,contacts(contact_id,full_name,email)').order('updated_at', { ascending: false }).limit(400);
  const update = quickUpdate.bind(null, 'marketing_permissions', 'permission_id', '/consent');
  const count = (s) => rows.filter((r) => r.status === s).length;

  return (
    <Page title="Consent centre" sub="Who you may contact, on which channel, and why.">
      <Flash params={searchParams} />
      <div className="grid g4" style={{ marginBottom: 18 }}>
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
        <div className="t-wrap"><table className="table">
          <thead><tr><th>Person</th><th>Channel</th><th>Basis</th><th>Status</th><th></th></tr></thead>
          <tbody>{rows.map((r) => (
            <tr key={r.permission_id}>
              <td><Link className="link" href={`/contacts/${r.contacts?.contact_id}`}>{r.contacts?.full_name}</Link>
                <div className="small faint">{r.contacts?.email}</div></td>
              <td className="small">{r.channel}</td>
              <td className="small">{r.lawful_basis_or_reason || '—'}</td>
              <td><Badge>{r.status}</Badge></td>
              <td>
                <form action={update} className="row" style={{ gap: 6 }}>
                  <input type="hidden" name="_id" value={r.permission_id} />
                  <select name="status" defaultValue={r.status}
                    style={{ padding: '5px 8px', borderRadius: 6, border: '1px solid var(--line)', fontSize: 12.5 }}>
                    {STATUSES.map((s) => <option key={s}>{s}</option>)}</select>
                  <button className="btn btn-sm">Update</button>
                </form>
              </td>
            </tr>))}
            {rows.length === 0 && <tr><td colSpan="5" className="small muted">No permissions recorded yet.</td></tr>}
          </tbody></table></div>
      </div>
    </Page>
  );
}
