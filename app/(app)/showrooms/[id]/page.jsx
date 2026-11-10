import Link from 'next/link';
import { supabaseServer } from '@/lib/supabase';
import { upsertRow, deleteRow } from '@/lib/actions';
import { Page, Badge, money, when } from '@/components/ui';
import Flash from '@/components/Flash';
export const dynamic = 'force-dynamic';

export default async function ShowroomDetail({ params, searchParams }) {
  const sb = supabaseServer();
  const id = params.id;
  const s = (await sb.from('showrooms').select('*,contacts(full_name)').eq('showroom_id', id).maybeSingle()).data;
  if (!s) return <Page title="Showroom not found"><Link className="btn" href="/showrooms">Back</Link></Page>;

  const [picks, products, views] = await Promise.all([
    sb.from('showroom_products').select('*,products(product_id,public_product_name,internal_sku,retail_price,wholesale_price)')
      .eq('showroom_id', id).order('sort_order').then((r) => r.data || []),
    sb.from('products').select('product_id,public_product_name').eq('status', 'Published').order('public_product_name').then((r) => r.data || []),
    sb.from('showroom_views').select('*').eq('showroom_id', id).order('viewed_at', { ascending: false }).then((r) => r.data || []),
  ]);
  const save = upsertRow.bind(null, 'showrooms', 'showroom_id', `/showrooms/${id}`);
  const addPiece = upsertRow.bind(null, 'showroom_products', 'showroom_id', `/showrooms/${id}`);
  const chosen = new Set(picks.map((p) => p.products?.product_id));

  return (
    <Page title={s.title} sub={`For ${s.contacts?.full_name || 'anyone with the link'} · ${picks.length} pieces · ${views.length} views`}
      actions={<><a className="btn" href={`/s/${s.slug}`} target="_blank" rel="noreferrer">Open public page</a>
        <Link className="btn" href="/showrooms">Back</Link></>}>
      <Flash params={searchParams} />
      <div className="grid" style={{ gridTemplateColumns: '1fr 330px' }}>
        <div className="stack">
          <div className="card">
            <div className="card-head"><h3>Pieces in this showroom</h3></div>
            <div className="t-wrap"><table className="table">
              <thead><tr><th>Product</th><th className="num">Retail</th><th className="num">Wholesale</th><th className="num">Custom price</th></tr></thead>
              <tbody>{picks.map((p) => (
                <tr key={p.product_id}><td>{p.products?.public_product_name}
                  <div className="small faint mono">{p.products?.internal_sku}</div></td>
                  <td className="num">{money(p.products?.retail_price)}</td>
                  <td className="num">{money(p.products?.wholesale_price)}</td>
                  <td className="num">{p.custom_price ? money(p.custom_price) : '—'}</td></tr>))}
                {picks.length === 0 && <tr><td colSpan="4" className="small muted">Nothing added yet.</td></tr>}
              </tbody></table></div>
            <form action={addPiece} className="card-foot row" style={{ gap: 8 }}>
              <input type="hidden" name="showroom_id" value={id} />
              <select name="product_id" required style={{ padding: '7px 10px', borderRadius: 8, border: '1px solid var(--line)', minWidth: 240 }}>
                <option value="">Add a published piece…</option>
                {products.filter((p) => !chosen.has(p.product_id)).map((p) => (
                  <option key={p.product_id} value={p.product_id}>{p.public_product_name}</option>))}
              </select>
              <input name="custom_price" type="number" step="0.01" placeholder="Custom price"
                style={{ width: 150, padding: '7px 10px', borderRadius: 8, border: '1px solid var(--line)' }} />
              <button className="btn btn-sm btn-primary">Add</button>
            </form>
          </div>

          <div className="card">
            <div className="card-head"><h3>Who looked</h3></div>
            <div className="card-body stack" style={{ gap: 6 }}>
              {views.length === 0 && <div className="small muted">No views yet. Share the link to find out.</div>}
              {views.slice(0, 10).map((v) => (
                <div key={v.view_id} className="row small">
                  <span>{when(v.viewed_at, true)}</span><span className="spacer" />
                  <span className="faint">{(v.user_agent || '').slice(0, 40)}</span>
                </div>))}
            </div>
          </div>
        </div>

        <form action={save} className="card">
          <div className="card-head"><h3>Settings</h3><Badge>{s.status}</Badge></div>
          <div className="card-body">
            <input type="hidden" name="_id" value={id} />
            <div className="field"><label>Title</label><input name="title" defaultValue={s.title} /></div>
            <div className="field"><label>Link name</label><input name="slug" defaultValue={s.slug} /></div>
            <div className="field"><label>Pricing shown</label>
              <select name="pricing_mode" defaultValue={s.pricing_mode}>
                <option>Hidden</option><option>Retail</option><option>Wholesale</option></select></div>
            <div className="field"><label>Status</label>
              <select name="status" defaultValue={s.status}><option>Draft</option><option>Published</option><option>Closed</option></select>
              <span className="hint">Only a Published showroom opens for the buyer.</span></div>
            <div className="field"><label>Visible to anyone with the link</label>
              <select name="public_enabled" defaultValue={String(s.public_enabled)}>
                <option value="true">Yes</option><option value="false">No</option></select></div>
            <div className="field"><label>Intro</label><textarea name="intro_text" defaultValue={s.intro_text || ''} /></div>
            <div className="field"><label>Call to action</label><input name="cta_text" defaultValue={s.cta_text || ''} /></div>
          </div>
          <div className="card-foot"><button className="btn btn-primary">Save showroom</button></div>
        </form>
      </div>
    </Page>
  );
}
