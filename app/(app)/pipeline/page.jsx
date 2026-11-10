import Link from 'next/link';
import { supabaseServer } from '@/lib/supabase';
import { quickUpdate, upsertRow } from '@/lib/actions';
import { Page, money, when } from '@/components/ui';
import Flash from '@/components/Flash';
export const dynamic = 'force-dynamic';

const STAGES = ['New', 'Qualified', 'Proposal', 'Negotiation', 'Won', 'Lost'];

export default async function Pipeline({ searchParams }) {
  const sb = supabaseServer();
  const { data: deals = [] } = await sb.from('opportunities')
    .select('*,contacts(full_name),companies(company_name)').order('estimated_value', { ascending: false });
  const { data: contacts = [] } = await sb.from('contacts').select('contact_id,full_name').order('full_name');
  const move = quickUpdate.bind(null, 'opportunities', 'opportunity_id', '/pipeline');
  const create = upsertRow.bind(null, 'opportunities', 'opportunity_id', '/pipeline');
  const open = deals.filter((d) => !['Won', 'Lost'].includes(d.stage));

  return (
    <Page title="Pipeline" sub={`${open.length} open deals worth ${money(open.reduce((s, d) => s + Number(d.estimated_value || 0), 0))}`}>
      <Flash params={searchParams} />
      <div className="board" style={{ marginBottom: 18 }}>
        {STAGES.map((stage) => {
          const col = deals.filter((d) => d.stage === stage);
          return (
            <div className="col" key={stage}>
              <h4>{stage}<span>{col.length}</span></h4>
              {col.map((d) => (
                <div className="deal" key={d.opportunity_id}>
                  <div className="name">{d.name}</div>
                  <div className="small muted">{d.companies?.company_name || d.contacts?.full_name || '—'}</div>
                  <div className="val">{money(d.estimated_value, d.currency)}</div>
                  {d.expected_close_date && <div className="small faint">Close {when(d.expected_close_date)}</div>}
                  <form action={move} style={{ marginTop: 8 }}>
                    <input type="hidden" name="_id" value={d.opportunity_id} />
                    <select name="stage" defaultValue={d.stage} style={{ width: '100%', fontSize: 12, padding: '4px 6px', borderRadius: 6, border: '1px solid var(--line)' }}>
                      {STAGES.map((s) => <option key={s}>{s}</option>)}
                    </select>
                    <button className="btn btn-sm" style={{ width: '100%', marginTop: 6, justifyContent: 'center' }}>Move</button>
                  </form>
                </div>
              ))}
            </div>
          );
        })}
      </div>

      <form action={create} className="card">
        <div className="card-head"><h3>Add a deal</h3></div>
        <div className="card-body"><div className="form-grid">
          <div className="field"><label>Deal name</label><input name="name" required placeholder="Spring cotton order — 40 pieces" /></div>
          <div className="field"><label>Contact</label>
            <select name="contact_id" defaultValue=""><option value="">—</option>
              {contacts.map((c) => <option key={c.contact_id} value={c.contact_id}>{c.full_name}</option>)}</select></div>
          <div className="field"><label>Estimated value</label><input name="estimated_value" type="number" step="0.01" /></div>
          <div className="field"><label>Stage</label><select name="stage" defaultValue="New">{STAGES.map((s) => <option key={s}>{s}</option>)}</select></div>
          <div className="field"><label>Expected close</label><input name="expected_close_date" type="date" /></div>
          <div className="field full"><label>Notes</label><textarea name="notes" /></div>
        </div></div>
        <div className="card-foot"><button className="btn btn-primary">Add deal</button></div>
      </form>
    </Page>
  );
}
