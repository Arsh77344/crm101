'use client';
import { useState } from 'react';
import { useQuery, insertRow, updateRow, formValues } from '@/lib/db';
import { Page, money, when, Loading, ErrorNote } from '@/components/ui';

const STAGES = ['New', 'Qualified', 'Proposal', 'Negotiation', 'Won', 'Lost'];

export default function Pipeline() {
  const [err, setErr] = useState('');
  const q = useQuery(async (c) => {
    const [deals, contacts] = await Promise.all([
      c.from('opportunities').select('*,contacts(full_name),companies(company_name)').order('estimated_value', { ascending: false }),
      c.from('contacts').select('contact_id,full_name').order('full_name'),
    ]);
    if (deals.error) throw deals.error;
    return { deals: deals.data || [], contacts: contacts.data || [] };
  }, []);

  async function move(id, stage) {
    try { await updateRow('opportunities', 'opportunity_id', id, { stage }); q.reload(); }
    catch (e) { setErr(e.message); }
  }
  async function create(e) {
    e.preventDefault();
    try { await insertRow('opportunities', formValues(e.target)); e.target.reset(); q.reload(); }
    catch (e2) { setErr(e2.message); }
  }

  if (q.loading) return <Page title="Pipeline"><Loading /></Page>;
  const deals = q.data?.deals || [];
  const open = deals.filter((d) => !['Won', 'Lost'].includes(d.stage));
  const won = deals.filter((d) => d.stage === 'Won');

  return (
    <Page title="Pipeline"
      sub={`${open.length} open deals worth ${money(open.reduce((s, d) => s + Number(d.estimated_value || 0), 0))} · ${money(won.reduce((s, d) => s + Number(d.estimated_value || 0), 0))} won`}>
      <ErrorNote error={q.error || err} />
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
                  <select value={d.stage} onChange={(e) => move(d.opportunity_id, e.target.value)}
                    style={{ width: '100%', marginTop: 8, fontSize: 12, padding: '4px 6px', borderRadius: 6, border: '1px solid var(--line)' }}>
                    {STAGES.map((s) => <option key={s}>{s}</option>)}
                  </select>
                </div>))}
            </div>);
        })}
      </div>

      <form className="card" onSubmit={create}>
        <div className="card-head"><h3>Add a deal</h3></div>
        <div className="card-body"><div className="form-grid">
          <div className="field"><label>Deal name</label><input name="name" required placeholder="Spring cotton order — 40 pieces" /></div>
          <div className="field"><label>Contact</label>
            <select name="contact_id" defaultValue=""><option value="">—</option>
              {(q.data?.contacts || []).map((c) => <option key={c.contact_id} value={c.contact_id}>{c.full_name}</option>)}</select></div>
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
