import Link from 'next/link';
import { supabaseServer, currentUser, canManage } from '@/lib/supabase';
import { upsertRow, deleteRow } from '@/lib/actions';
import { Page, Badge, money, when, initials } from '@/components/ui';
import Flash from '@/components/Flash';

export const dynamic = 'force-dynamic';
const STAGES = ['New', 'Lead', 'Opportunity', 'Customer', 'Dormant'];
const TYPES = ['B2C', 'B2B', 'Both', 'Unknown'];
const QUAL = ['Unreviewed', 'Qualified', 'Disqualified', 'On hold'];

export default async function ContactDetail({ params, searchParams }) {
  const isNew = params.id === 'new';
  const sb = supabaseServer();
  const user = await currentUser();

  const c = isNew ? {} : (await sb.from('contacts').select('*').eq('contact_id', params.id).maybeSingle()).data || {};
  const [acts, orders, perms, camps] = isNew ? [[], [], [], []] : await Promise.all([
    sb.from('activities').select('*').eq('contact_id', params.id).order('created_at', { ascending: false }).limit(20).then((r) => r.data || []),
    sb.from('orders').select('order_id,order_number,total,order_status,ordered_at').eq('contact_id', params.id).order('ordered_at', { ascending: false }).then((r) => r.data || []),
    sb.from('marketing_permissions').select('*').eq('contact_id', params.id).then((r) => r.data || []),
    sb.from('campaign_members').select('member_status,campaigns(campaign_id,campaign_name,channel,status)').eq('contact_id', params.id).then((r) => r.data || []),
  ]);

  const save = upsertRow.bind(null, 'contacts', 'contact_id', isNew ? '/contacts' : `/contacts/${params.id}`);
  const remove = deleteRow.bind(null, 'contacts', 'contact_id', '/contacts');
  const addActivity = upsertRow.bind(null, 'activities', 'activity_id', `/contacts/${params.id}`);
  const spend = orders.filter((o) => o.order_status === 'Fulfilled').reduce((s, o) => s + Number(o.total || 0), 0);

  return (
    <Page title={isNew ? 'New contact' : c.full_name || 'Contact'}
      sub={isNew ? 'Add someone to the book.' : `${c.contact_type || 'Unknown'} · ${c.country || 'No country'} · added ${when(c.created_at)}`}
      actions={<Link className="btn" href="/contacts">Back to contacts</Link>}>
      <Flash params={searchParams} />

      <div className="grid" style={{ gridTemplateColumns: '1fr 330px' }}>
        <div className="stack">
          <form action={save} className="card">
            <div className="card-head"><h3>{isNew ? 'Details' : 'Edit contact'}</h3>
              {!isNew && <Badge>{c.lifecycle_stage}</Badge>}</div>
            <div className="card-body"><div className="form-grid">
              {!isNew && <input type="hidden" name="_id" value={c.contact_id} />}
              <div className="field"><label>Full name</label>
                <input name="full_name" defaultValue={c.full_name || ''} required /></div>
              <div className="field"><label>Type</label>
                <select name="contact_type" defaultValue={c.contact_type || 'Unknown'}>
                  {TYPES.map((t) => <option key={t}>{t}</option>)}</select></div>
              <div className="field"><label>Email</label>
                <input name="email" type="email" defaultValue={c.email || ''} /></div>
              <div className="field"><label>Phone</label>
                <input name="phone_number" defaultValue={c.phone_number || ''} /></div>
              <div className="field"><label>Country</label>
                <input name="country" defaultValue={c.country || ''} /></div>
              <div className="field"><label>Business category</label>
                <input name="business_category" defaultValue={c.business_category || ''} placeholder="Boutique, Distributor, Individual" /></div>
              <div className="field"><label>Lifecycle stage</label>
                <select name="lifecycle_stage" defaultValue={c.lifecycle_stage || 'New'}>
                  {STAGES.map((s) => <option key={s}>{s}</option>)}</select></div>
              <div className="field"><label>Qualification</label>
                <select name="qualification_status" defaultValue={c.qualification_status || 'Unreviewed'}>
                  {QUAL.map((s) => <option key={s}>{s}</option>)}</select></div>
              <div className="field"><label>Lead score</label>
                <input name="lead_score" type="number" min="0" max="100" defaultValue={c.lead_score ?? 0} /></div>
              <div className="field"><label>Next follow up</label>
                <input name="next_follow_up" type="date" defaultValue={c.next_follow_up || ''} /></div>
              <div className="field"><label>Source</label>
                <input name="source_name" defaultValue={c.source_name || ''} placeholder="Instagram DM, Trade fair" /></div>
              <div className="field"><label>Instagram / website</label>
                <input name="website" defaultValue={c.website || ''} /></div>
              <div className="field full"><label>Notes</label>
                <textarea name="relevance_reason" defaultValue={c.relevance_reason || ''}
                  placeholder="Why they matter, what they buy, what to remember." /></div>
            </div></div>
            <div className="card-foot row">
              <button className="btn btn-primary">{isNew ? 'Create contact' : 'Save changes'}</button>
              <Link className="btn btn-ghost" href="/contacts">Cancel</Link>
            </div>
          </form>

          {!isNew && (
            <div className="card">
              <div className="card-head"><h3>Activity</h3></div>
              <form action={addActivity} className="card-body" style={{ borderBottom: '1px solid var(--line-soft)' }}>
                <input type="hidden" name="contact_id" value={c.contact_id} />
                <div className="form-grid">
                  <div className="field"><label>Type</label>
                    <select name="activity_type" defaultValue="Note">
                      {['Note', 'Call', 'Email', 'Meeting', 'WhatsApp', 'Visit'].map((t) => <option key={t}>{t}</option>)}
                    </select></div>
                  <div className="field"><label>Follow up on</label><input name="follow_up_at" type="date" /></div>
                  <div className="field full"><label>What happened</label>
                    <textarea name="summary" required placeholder="Short note so the next person knows where things stand." /></div>
                </div>
                <button className="btn btn-sm btn-primary">Log activity</button>
              </form>
              <div className="card-body stack">
                {acts.length === 0 && <div className="small muted">Nothing logged yet.</div>}
                {acts.map((a) => (
                  <div key={a.activity_id} className="row" style={{ alignItems: 'flex-start', gap: 10 }}>
                    <div className="avatar">{initials(a.activity_type || 'N')}</div>
                    <div style={{ flex: 1 }}>
                      <div className="row"><strong className="small">{a.activity_type}</strong>
                        <span className="spacer" /><span className="small faint">{when(a.created_at, true)}</span></div>
                      <div className="small">{a.summary}</div>
                      {a.follow_up_at && <div className="small faint">Follow up {when(a.follow_up_at)}</div>}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>

        {!isNew && (
          <div className="stack">
            <div className="card"><div className="card-head"><h3>Value</h3></div>
              <div className="card-body stack" style={{ gap: 8 }}>
                <div className="row"><span className="muted small">Lifetime spend</span><span className="spacer" /><strong>{money(spend)}</strong></div>
                <div className="row"><span className="muted small">Orders</span><span className="spacer" /><strong>{orders.length}</strong></div>
                <div className="row"><span className="muted small">Lead score</span><span className="spacer" /><strong>{c.lead_score ?? 0}</strong></div>
              </div></div>

            <div className="card"><div className="card-head"><h3>Orders</h3><Link className="link small" href="/orders">All →</Link></div>
              <div className="card-body stack" style={{ gap: 8 }}>
                {orders.length === 0 && <div className="small muted">No orders yet.</div>}
                {orders.map((o) => (
                  <div key={o.order_id} className="row">
                    <div><div className="small" style={{ fontWeight: 600 }}>{o.order_number}</div>
                      <div className="small faint">{when(o.ordered_at)}</div></div>
                    <span className="spacer" />
                    <div style={{ textAlign: 'right' }}><div className="small">{money(o.total)}</div><Badge>{o.order_status}</Badge></div>
                  </div>
                ))}
              </div></div>

            <div className="card"><div className="card-head"><h3>Marketing consent</h3>
              <Link className="link small" href="/consent">Centre →</Link></div>
              <div className="card-body stack" style={{ gap: 8 }}>
                {perms.length === 0 && <div className="small muted">No consent recorded.</div>}
                {perms.map((p) => (
                  <div key={p.permission_id} className="row">
                    <span className="small">{p.channel}</span><span className="spacer" /><Badge>{p.status}</Badge>
                  </div>
                ))}
              </div></div>

            <div className="card"><div className="card-head"><h3>Campaigns</h3></div>
              <div className="card-body stack" style={{ gap: 8 }}>
                {camps.length === 0 && <div className="small muted">Not in any campaign.</div>}
                {camps.map((m, i) => (
                  <div key={i} className="row">
                    <Link className="link small" href={`/campaigns/${m.campaigns?.campaign_id}`}>{m.campaigns?.campaign_name}</Link>
                    <span className="spacer" /><Badge>{m.member_status}</Badge>
                  </div>
                ))}
              </div></div>

            {canManage(user.profile?.role) && (
              <form action={remove} className="card"><input type="hidden" name="_id" value={c.contact_id} />
                <div className="card-body"><button className="btn btn-danger btn-sm">Delete contact</button></div></form>
            )}
          </div>
        )}
      </div>
    </Page>
  );
}
