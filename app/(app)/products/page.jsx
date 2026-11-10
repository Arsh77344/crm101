import Link from 'next/link';
import { supabaseServer } from '@/lib/supabase';
import { Page, Badge, money, Empty } from '@/components/ui';
import Flash from '@/components/Flash';

export const dynamic = 'force-dynamic';

export default async function Products({ searchParams }) {
  const sb = supabaseServer();
  const q = searchParams?.q || '';
  const status = searchParams?.status || '';

  let query = sb.from('products').select('*').order('created_at', { ascending: false });
  if (q) query = query.or(`public_product_name.ilike.%${q}%,internal_sku.ilike.%${q}%,colour.ilike.%${q}%,fabric.ilike.%${q}%`);
  if (status) query = query.eq('status', status);
  const { data: rows = [], error } = await query;

  const tabs = ['', 'Draft', 'Review', 'Published', 'Archived'];
  return (
    <Page title="Products" sub={`${rows.length} piece${rows.length === 1 ? '' : 's'} in the catalogue`}
      actions={<Link className="btn btn-primary" href="/products/new">New product</Link>}>
      <Flash params={searchParams} />
      {error && <div className="note warn">{error.message}</div>}

      <form className="toolbar">
        <div className="search"><span className="mag">⌕</span>
          <input name="q" defaultValue={q} placeholder="Search name, SKU, colour, fabric…" /></div>
        {status && <input type="hidden" name="status" value={status} />}
        <button className="btn btn-sm">Search</button>
        <span className="spacer" />
        {tabs.map((t) => (
          <Link key={t || 'all'} className={`chip ${status === t ? 'on' : ''}`}
            href={`/products${t ? `?status=${t}` : ''}`}>{t || 'All'}</Link>
        ))}
      </form>

      <div className="card">
        {rows.length === 0 ? (
          <Empty title="No products here" hint="Add your first piece, or change the filter.">
            <Link className="btn btn-primary" href="/products/new">New product</Link>
          </Empty>
        ) : (
          <div className="t-wrap"><table className="table">
            <thead><tr>
              <th></th><th>Product</th><th>SKU</th><th>Fabric</th>
              <th className="num">Retail</th><th className="num">Wholesale</th><th className="num">Stock</th><th>Status</th>
            </tr></thead>
            <tbody>
              {rows.map((p) => (
                <tr key={p.product_id}>
                  <td><div className="thumb">{(p.colour || '—').slice(0, 3)}</div></td>
                  <td>
                    <Link className="link" href={`/products/${p.product_id}`}>{p.public_product_name}</Link>
                    <div className="small faint">{p.colour}{p.weave_or_motif ? ` · ${p.weave_or_motif}` : ''}</div>
                  </td>
                  <td className="mono">{p.internal_sku || '—'}</td>
                  <td className="small">{p.fabric || '—'}</td>
                  <td className="num">{money(p.retail_price, p.currency)}</td>
                  <td className="num">{money(p.wholesale_price, p.currency)}</td>
                  <td className="num">{p.stock_qty ?? 0}</td>
                  <td><Badge>{p.status}</Badge></td>
                </tr>
              ))}
            </tbody>
          </table></div>
        )}
      </div>
    </Page>
  );
}
