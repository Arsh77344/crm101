import Link from 'next/link';
import { supabaseServer } from '@/lib/supabase';
import { Page, when, Empty, initials } from '@/components/ui';
export const dynamic = 'force-dynamic';

export default async function Activities() {
  const sb = supabaseServer();
  const { data: rows = [] } = await sb.from('activities')
    .select('*,contacts(contact_id,full_name)').order('created_at', { ascending: false }).limit(100);
  const due = rows.filter((a) => a.follow_up_at && new Date(a.follow_up_at) <= new Date(Date.now() + 7 * 864e5));

  return (
    <Page title="Activities" sub="Every call, email and note across the team.">
      <div className="grid" style={{ gridTemplateColumns: '1fr 320px' }}>
        <div className="card">
          <div className="card-head"><h3>Recent</h3></div>
          {rows.length === 0 ? <Empty title="Nothing logged yet" hint="Log calls and notes from a contact's page." /> : (
            <div className="card-body stack">
              {rows.map((a) => (
                <div key={a.activity_id} className="row" style={{ alignItems: 'flex-start', gap: 10 }}>
                  <div className="avatar">{initials(a.activity_type || 'N')}</div>
                  <div style={{ flex: 1 }}>
                    <div className="row">
                      <Link className="link small" href={`/contacts/${a.contacts?.contact_id}`}>{a.contacts?.full_name || 'Unknown'}</Link>
                      <span className="small muted"> · {a.activity_type}</span>
                      <span className="spacer" /><span className="small faint">{when(a.created_at, true)}</span>
                    </div>
                    <div className="small">{a.summary}</div>
                  </div>
                </div>))}
            </div>
          )}
        </div>
        <div className="card">
          <div className="card-head"><h3>Follow ups due</h3></div>
          <div className="card-body stack" style={{ gap: 10 }}>
            {due.length === 0 && <div className="small muted">Nothing due in the next week.</div>}
            {due.map((a) => (
              <div key={a.activity_id}>
                <Link className="link small" href={`/contacts/${a.contacts?.contact_id}`}>{a.contacts?.full_name}</Link>
                <div className="small muted">{a.summary?.slice(0, 70)}</div>
                <div className="small faint">Due {when(a.follow_up_at)}</div>
              </div>))}
          </div>
        </div>
      </div>
    </Page>
  );
}
