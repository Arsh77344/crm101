import Link from 'next/link';
import { supabaseServer, currentUser, canManage } from '@/lib/supabase';
import { upsertRow, deleteRow } from '@/lib/actions';
import { Page, money, Badge } from '@/components/ui';
import Flash from '@/components/Flash';
export const dynamic = 'force-dynamic';

export default async function CompanyDetail({ params, searchParams }) {
  const isNew = params.id === 'new';
  const sb = supabaseServer();
  const user = await currentUser();
  const c = isNew ? {} : (await sb.from('companies').select('*').eq('company_id', params.id).maybeSingle()).data || {};
  const people = isNew ? [] : (await sb.from('contact_companies')
    .select('role_title,contacts(contact_id,full_name,email,lifecycle_stage)').eq('company_id', params.id)).data || [];
  const deals = isNew ? [] : (await sb.from('opportunities').select('*').eq('company_id', params.id)).data || [];
  const save = upsertRow.bind(null, 'companies', 'company_id', isNew ? '/companies' : `/companies/${params.id}`);
  const remove = deleteRow.bind(null, 'companies', 'company_id', '/companies');

  return (
    <Page title={isNew ? 'New company' : c.company_name || 'Company'} sub={c.company_type || 'Account'}
      actions={<Link className="btn" href="/companies">Back</Link>}>
      <Flash params={searchParams} />
      <div className="grid" style={{ gridTemplateColumns: '1fr 320px' }}>
        <form action={save} className="card">
          <div className="card-head"><h3>{isNew ? 'Details' : 'Edit company'}</h3></div>
          <div className="card-body"><div className="form-grid">
            {!isNew && <input type="hidden" name="_id" value={c.company_id} />}
            <div className="field full"><label>Company name</label><input name="company_name" defaultValue={c.company_name || ''} required /></div>
            <div className="field"><label>Type</label><input name="company_type" defaultValue={c.company_type || ''} placeholder="Boutique, Distributor" /></div>
            <div className="field"><label>Wholesale tier</label><input name="wholesale_tier" defaultValue={c.wholesale_tier || ''} placeholder="Tier 1" /></div>
            <div className="field"><label>Country</label><input name="country" defaultValue={c.country || ''} /></div>
            <div className="field"><label>Website</label><input name="website" defaultValue={c.website || ''} /></div>
            <div className="field full"><label>Notes</label><textarea name="notes" defaultValue={c.notes || ''} /></div>
          </div></div>
          <div className="card-foot"><button className="btn btn-primary">{isNew ? 'Create company' : 'Save changes'}</button></div>
        </form>
        {!isNew && (
          <div className="stack">
            <div className="card"><div className="card-head"><h3>People</h3></div>
              <div className="card-body stack" style={{ gap: 8 }}>
                {people.length === 0 && <div className="small muted">No contacts linked.</div>}
                {people.map((p, i) => (
                  <div key={i} className="row">
                    <Link className="link small" href={`/contacts/${p.contacts?.contact_id}`}>{p.contacts?.full_name}</Link>
                    <span className="spacer" /><span className="small faint">{p.role_title}</span>
                  </div>))}
              </div></div>
            <div className="card"><div className="card-head"><h3>Open deals</h3></div>
              <div className="card-body stack" style={{ gap: 8 }}>
                {deals.length === 0 && <div className="small muted">No deals.</div>}
                {deals.map((d) => (
                  <div key={d.opportunity_id} className="row">
                    <span className="small">{d.name}</span><span className="spacer" />
                    <span className="small">{money(d.estimated_value)}</span><Badge>{d.stage}</Badge>
                  </div>))}
              </div></div>
            {canManage(user.profile?.role) && (
              <form action={remove} className="card"><input type="hidden" name="_id" value={c.company_id} />
                <div className="card-body"><button className="btn btn-danger btn-sm">Delete company</button></div></form>)}
          </div>
        )}
      </div>
    </Page>
  );
}
