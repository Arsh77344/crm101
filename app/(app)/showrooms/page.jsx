import Link from 'next/link';
import { supabaseServer } from '@/lib/supabase';
import { upsertRow } from '@/lib/actions';
import { Page, Badge, when, Empty } from '@/components/ui';
import Flash from '@/components/Flash';
export const dynamic = 'force-dynamic';

export default async function Showrooms({ searchParams }) {
  const sb = supabaseServer();
  const [rows, contacts, picks, views] = await Promise.all([
    sb.from('showrooms').select('*,contacts(full_name)').order('created_at', { ascending: false }).then((r) => r.data || []),
    sb.from('contacts').select('contact_id,full_name').order('full_name').then((r) => r.data || []),
    sb.from('showroom_products').select('showroom_id').then((r) => r.data || []),
    sb.from('showroom_views').select('showroom_id').then((r) => r.data || []),
  ]);
  const create = upsertRow.bind(null, 'showrooms', 'showroom_id', '/showrooms/[id]');

  return (
    <Page title="Showrooms" sub="A private page of selected pieces you can send to one buyer.">
      <Flash params={searchParams} />
      <div className="grid" style={{ gridTemplateColumns: '1fr 330px' }}>
        <div className="card">
          <div className="card-head"><h3>All showrooms</h3></div>
          {rows.length === 0 ? <Empty title="No showrooms yet" hint="Create one for a buyer and add pieces to it." /> : (
            <div className="t-wrap"><table className="table">
              <thead><tr><th>Title</th><th>For</th><th>Pricing</th><th className="num">Pieces</th>
                <th className="num">Views</th><th>Status</th></tr></thead>
              <tbody>{rows.map((s) => (
                <tr key={s.showroom_id}>
                  <td><Link className="link" href={`/showrooms/${s.showroom_id}`}>{s.title}</Link>
                    <div className="small faint mono">/s/{s.slug}</div></td>
                  <td className="small">{s.contacts?.full_name || '—'}</td>
                  <td className="small">{s.pricing_mode}</td>
                  <td className="num">{picks.filter((p) => p.showroom_id === s.showroom_id).length}</td>
                  <td className="num">{views.filter((v) => v.showroom_id === s.showroom_id).length}</td>
                  <td><Badge>{s.status}</Badge></td>
                </tr>))}</tbody></table></div>
          )}
        </div>
        <form action={create} className="card">
          <div className="card-head"><h3>New showroom</h3></div>
          <div className="card-body">
            <div className="field"><label>Title</label><input name="title" required placeholder="Festive capsule for Meher Boutique" /></div>
            <div className="field"><label>Link name</label><input name="slug" required placeholder="meher-festive-2026" />
              <span className="hint">Used in the private link you share.</span></div>
            <div className="field"><label>For</label>
              <select name="contact_id" defaultValue=""><option value="">—</option>
                {contacts.map((c) => <option key={c.contact_id} value={c.contact_id}>{c.full_name}</option>)}</select></div>
            <div className="field"><label>Pricing shown</label>
              <select name="pricing_mode" defaultValue="Hidden"><option>Hidden</option><option>Retail</option><option>Wholesale</option></select></div>
            <div className="field"><label>Intro</label><textarea name="intro_text" placeholder="A line for the buyer when they open it." /></div>
          </div>
          <div className="card-foot"><button className="btn btn-primary">Create showroom</button></div>
        </form>
      </div>
    </Page>
  );
}
