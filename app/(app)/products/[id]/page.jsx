import Link from 'next/link';
import { supabaseServer, currentUser, canManage } from '@/lib/supabase';
import { upsertRow, deleteRow } from '@/lib/actions';
import { Page, money, when, Badge } from '@/components/ui';
import Flash from '@/components/Flash';

export const dynamic = 'force-dynamic';

const STATUS = ['Draft', 'Review', 'Published', 'Archived'];
const CURRENCIES = ['INR', 'USD', 'GBP', 'EUR'];

export default async function ProductDetail({ params, searchParams }) {
  const isNew = params.id === 'new';
  const sb = supabaseServer();
  const user = await currentUser();

  const p = isNew ? {} : (await sb.from('products').select('*').eq('product_id', params.id).maybeSingle()).data || {};
  const jobs = isNew ? [] : (await sb.from('launch_jobs').select('*').eq('product_id', params.id).order('created_at', { ascending: false })).data || [];
  const inOrders = isNew ? [] : (await sb.from('order_items')
    .select('quantity,unit_price,orders(order_number,order_status,ordered_at)').eq('product_id', params.id)).data || [];

  const save = upsertRow.bind(null, 'products', 'product_id', isNew ? '/products' : `/products/${params.id}`);
  const remove = deleteRow.bind(null, 'products', 'product_id', '/products');
  const sold = inOrders.reduce((s, i) => s + Number(i.quantity || 0), 0);

  return (
    <Page title={isNew ? 'New product' : p.public_product_name || 'Product'}
      sub={isNew ? 'Add a piece to the catalogue.' : `${p.internal_sku || 'No SKU'} · added ${when(p.created_at)}`}
      actions={<Link className="btn" href="/products">Back to products</Link>}>
      <Flash params={searchParams} />

      <div className="grid" style={{ gridTemplateColumns: '1fr 320px' }}>
        <form action={save} className="card">
          <div className="card-head"><h3>{isNew ? 'Details' : 'Edit product'}</h3>
            {!isNew && <Badge>{p.status}</Badge>}</div>
          <div className="card-body">
            {!isNew && <input type="hidden" name="_id" value={p.product_id} />}
            <div className="form-grid">
              <div className="field full"><label>Product name</label>
                <input name="public_product_name" defaultValue={p.public_product_name || ''} required /></div>
              <div className="field"><label>SKU</label>
                <input name="internal_sku" defaultValue={p.internal_sku || ''} placeholder="USY-MS-001" /></div>
              <div className="field"><label>Category</label>
                <input name="category" defaultValue={p.category || 'Banarasi Saree'} /></div>
              <div className="field"><label>Fabric</label>
                <input name="fabric" defaultValue={p.fabric || ''} placeholder="Mashru Satin Silk" /></div>
              <div className="field"><label>Colour</label>
                <input name="colour" defaultValue={p.colour || ''} /></div>
              <div className="field"><label>Weave or motif</label>
                <input name="weave_or_motif" defaultValue={p.weave_or_motif || ''} placeholder="Jangla floral" /></div>
              <div className="field"><label>Tags</label>
                <input name="tags" defaultValue={p.tags || ''} placeholder="wedding, silk, handloom" /></div>
              <div className="field full"><label>Description</label>
                <textarea name="description" defaultValue={p.description || ''}
                  placeholder="What it is, how it is woven, who it suits." /></div>
              <div className="field"><label>Cost price</label>
                <input name="cost_price" type="number" step="0.01" defaultValue={p.cost_price ?? ''} /></div>
              <div className="field"><label>Currency</label>
                <select name="currency" defaultValue={p.currency || 'INR'}>
                  {CURRENCIES.map((c) => <option key={c}>{c}</option>)}</select></div>
              <div className="field"><label>Retail price</label>
                <input name="retail_price" type="number" step="0.01" defaultValue={p.retail_price ?? ''} /></div>
              <div className="field"><label>Wholesale price</label>
                <input name="wholesale_price" type="number" step="0.01" defaultValue={p.wholesale_price ?? ''} /></div>
              <div className="field"><label>Stock quantity</label>
                <input name="stock_qty" type="number" defaultValue={p.stock_qty ?? 0} /></div>
              <div className="field"><label>Minimum order quantity</label>
                <input name="moq" type="number" defaultValue={p.moq ?? 1} /></div>
              <div className="field"><label>Status</label>
                <select name="status" defaultValue={p.status || 'Draft'}>
                  {STATUS.map((s) => <option key={s}>{s}</option>)}</select>
                <span className="hint">Published pieces can appear in showrooms and on the storefront.</span></div>
            </div>
          </div>
          <div className="card-foot row">
            <button className="btn btn-primary">{isNew ? 'Create product' : 'Save changes'}</button>
            <Link className="btn btn-ghost" href="/products">Cancel</Link>
          </div>
        </form>

        <div className="stack">
          {!isNew && (
            <>
              <div className="card"><div className="card-head"><h3>Margin</h3></div>
                <div className="card-body stack" style={{ gap: 8 }}>
                  <div className="row"><span className="muted small">Retail margin</span><span className="spacer" />
                    <strong>{p.retail_price && p.cost_price
                      ? `${Math.round(((p.retail_price - p.cost_price) / p.retail_price) * 100)}%` : '—'}</strong></div>
                  <div className="row"><span className="muted small">Wholesale margin</span><span className="spacer" />
                    <strong>{p.wholesale_price && p.cost_price
                      ? `${Math.round(((p.wholesale_price - p.cost_price) / p.wholesale_price) * 100)}%` : '—'}</strong></div>
                  <div className="row"><span className="muted small">Units sold</span><span className="spacer" />
                    <strong>{sold}</strong></div>
                </div></div>

              <div className="card"><div className="card-head"><h3>Launch activity</h3>
                <Link className="link small" href="/launch">Launch desk →</Link></div>
                <div className="card-body stack" style={{ gap: 10 }}>
                  {jobs.length === 0 && <div className="small muted">No launch runs for this piece yet.</div>}
                  {jobs.map((j) => (
                    <div key={j.job_id}>
                      <div className="row"><strong className="small">{j.stage}</strong><span className="spacer" /><Badge>{j.status}</Badge></div>
                      <div className="small muted">{j.message}</div>
                    </div>
                  ))}
                </div></div>

              {canManage(user.profile?.role) && (
                <form action={remove} className="card">
                  <input type="hidden" name="_id" value={p.product_id} />
                  <div className="card-body">
                    <div className="small muted" style={{ marginBottom: 10 }}>
                      Deleting removes this product from showrooms and campaign posts. Order history keeps its own record.
                    </div>
                    <button className="btn btn-danger btn-sm">Delete product</button>
                  </div>
                </form>
              )}
            </>
          )}
        </div>
      </div>
    </Page>
  );
}
