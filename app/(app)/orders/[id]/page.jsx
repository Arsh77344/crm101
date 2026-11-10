import Link from 'next/link';
import { supabaseServer } from '@/lib/supabase';
import { upsertRow } from '@/lib/actions';
import { Page, money, when, Badge } from '@/components/ui';
import Flash from '@/components/Flash';
export const dynamic = 'force-dynamic';

const STATUS = ['Draft', 'Pending Payment', 'Processing', 'Fulfilled', 'Cancelled'];

export default async function OrderDetail({ params, searchParams }) {
  const isNew = params.id === 'new';
  const sb = supabaseServer();
  const o = isNew ? {} : (await sb.from('orders').select('*,contacts(full_name),companies(company_name)').eq('order_id', params.id).maybeSingle()).data || {};
  const items = isNew ? [] : (await sb.from('order_items').select('*,products(public_product_name,internal_sku)').eq('order_id', params.id)).data || [];
  const { data: contacts = [] } = await sb.from('contacts').select('contact_id,full_name').order('full_name');
  const { data: products = [] } = await sb.from('products').select('product_id,public_product_name,retail_price').order('public_product_name');

  const save = upsertRow.bind(null, 'orders', 'order_id', isNew ? '/orders' : `/orders/${params.id}`);
  const addItem = upsertRow.bind(null, 'order_items', 'order_item_id', `/orders/${params.id}`);

  return (
    <Page title={isNew ? 'New order' : `Order ${o.order_number || ''}`}
      sub={isNew ? 'Record a sale by hand.' : `${o.contacts?.full_name || o.companies?.company_name || '—'} · ${when(o.ordered_at)}`}
      actions={<Link className="btn" href="/orders">Back to orders</Link>}>
      <Flash params={searchParams} />
      <div className="grid" style={{ gridTemplateColumns: '1fr 320px' }}>
        <div className="stack">
          <form action={save} className="card">
            <div className="card-head"><h3>{isNew ? 'Order details' : 'Edit order'}</h3>{!isNew && <Badge>{o.order_status}</Badge>}</div>
            <div className="card-body"><div className="form-grid">
              {!isNew && <input type="hidden" name="_id" value={o.order_id} />}
              <div className="field"><label>Order number</label><input name="order_number" defaultValue={o.order_number || ''} placeholder="USY-1046" /></div>
              <div className="field"><label>Customer</label>
                <select name="contact_id" defaultValue={o.contact_id || ''}><option value="">—</option>
                  {contacts.map((c) => <option key={c.contact_id} value={c.contact_id}>{c.full_name}</option>)}</select></div>
              <div className="field"><label>Type</label><select name="order_type" defaultValue={o.order_type || 'B2C'}><option>B2C</option><option>B2B</option></select></div>
              <div className="field"><label>Status</label><select name="order_status" defaultValue={o.order_status || 'Draft'}>{STATUS.map((s) => <option key={s}>{s}</option>)}</select></div>
              <div className="field"><label>Subtotal</label><input name="subtotal" type="number" step="0.01" defaultValue={o.subtotal ?? ''} /></div>
              <div className="field"><label>Discount</label><input name="discount" type="number" step="0.01" defaultValue={o.discount ?? 0} /></div>
              <div className="field"><label>Shipping</label><input name="shipping" type="number" step="0.01" defaultValue={o.shipping ?? 0} /></div>
              <div className="field"><label>Total</label><input name="total" type="number" step="0.01" defaultValue={o.total ?? ''} /></div>
              <div className="field"><label>External reference</label><input name="external_order_reference" defaultValue={o.external_order_reference || ''} placeholder="Wix / Shopify order id" /></div>
            </div></div>
            <div className="card-foot"><button className="btn btn-primary">{isNew ? 'Create order' : 'Save order'}</button></div>
          </form>

          {!isNew && (
            <div className="card">
              <div className="card-head"><h3>Items</h3></div>
              <div className="t-wrap"><table className="table">
                <thead><tr><th>Product</th><th className="num">Qty</th><th className="num">Unit</th><th className="num">Line</th></tr></thead>
                <tbody>{items.map((i) => (
                  <tr key={i.order_item_id}><td>{i.products?.public_product_name || '—'}
                    <div className="small faint mono">{i.products?.internal_sku}</div></td>
                    <td className="num">{i.quantity}</td><td className="num">{money(i.unit_price)}</td>
                    <td className="num">{money(i.quantity * i.unit_price)}</td></tr>))}
                  {items.length === 0 && <tr><td colSpan="4" className="small muted">No items on this order.</td></tr>}
                </tbody></table></div>
              <form action={addItem} className="card-foot row" style={{ gap: 8, flexWrap: 'wrap' }}>
                <input type="hidden" name="order_id" value={o.order_id} />
                <select name="product_id" required style={{ padding: '7px 10px', borderRadius: 8, border: '1px solid var(--line)', minWidth: 220 }}>
                  <option value="">Choose a product…</option>
                  {products.map((p) => <option key={p.product_id} value={p.product_id}>{p.public_product_name}</option>)}
                </select>
                <input name="quantity" type="number" defaultValue="1" min="1" style={{ width: 80, padding: '7px 10px', borderRadius: 8, border: '1px solid var(--line)' }} />
                <input name="unit_price" type="number" step="0.01" placeholder="Unit price" required style={{ width: 130, padding: '7px 10px', borderRadius: 8, border: '1px solid var(--line)' }} />
                <button className="btn btn-sm btn-primary">Add item</button>
              </form>
            </div>
          )}
        </div>

        {!isNew && (
          <div className="card"><div className="card-head"><h3>Summary</h3></div>
            <div className="card-body stack" style={{ gap: 8 }}>
              <div className="row"><span className="muted small">Subtotal</span><span className="spacer" />{money(o.subtotal)}</div>
              <div className="row"><span className="muted small">Discount</span><span className="spacer" />−{money(o.discount)}</div>
              <div className="row"><span className="muted small">Shipping</span><span className="spacer" />{money(o.shipping)}</div>
              <div className="row" style={{ borderTop: '1px solid var(--line-soft)', paddingTop: 8 }}>
                <strong>Total</strong><span className="spacer" /><strong>{money(o.total)}</strong></div>
            </div></div>
        )}
      </div>
    </Page>
  );
}
