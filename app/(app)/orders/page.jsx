import Link from 'next/link';
import { supabaseServer } from '@/lib/supabase';
import { Page, Badge, money, when, Empty, Stat } from '@/components/ui';
import Flash from '@/components/Flash';
export const dynamic = 'force-dynamic';

export default async function Orders({ searchParams }) {
  const sb = supabaseServer();
  const status = searchParams?.status || '';
  let q = sb.from('orders').select('*,contacts(full_name),companies(company_name)').order('ordered_at', { ascending: false });
  if (status) q = q.eq('order_status', status);
  const { data: rows = [] } = await q;
  const paid = rows.filter((o) => ['Fulfilled', 'Processing'].includes(o.order_status));
  const tabs = ['', 'Draft', 'Pending Payment', 'Processing', 'Fulfilled', 'Cancelled'];

  return (
    <Page title="Orders" sub={`${rows.length} orders`}
      actions={<Link className="btn btn-primary" href="/orders/new">New order</Link>}>
      <Flash params={searchParams} />
      <div className="grid g3" style={{ marginBottom: 16 }}>
        <Stat label="Booked value" value={money(paid.reduce((s, o) => s + Number(o.total || 0), 0))} delta={`${paid.length} paid or processing`} />
        <Stat label="Average order" value={money(paid.length ? paid.reduce((s, o) => s + Number(o.total || 0), 0) / paid.length : 0)} />
        <Stat label="Awaiting action" value={rows.filter((o) => ['Draft', 'Pending Payment', 'Processing'].includes(o.order_status)).length} delta="Draft, unpaid or processing" />
      </div>
      <div className="toolbar">
        {tabs.map((t) => <Link key={t || 'all'} className={`chip ${status === t ? 'on' : ''}`}
          href={`/orders${t ? `?status=${encodeURIComponent(t)}` : ''}`}>{t || 'All'}</Link>)}
      </div>
      <div className="card">
        {rows.length === 0 ? <Empty title="No orders" hint="Record a sale or sync from your storefront." /> : (
          <div className="t-wrap"><table className="table">
            <thead><tr><th>Order</th><th>Customer</th><th>Type</th><th>Status</th><th>Date</th><th className="num">Total</th></tr></thead>
            <tbody>{rows.map((o) => (
              <tr key={o.order_id}>
                <td><Link className="link" href={`/orders/${o.order_id}`}>{o.order_number || o.order_id.slice(0, 8)}</Link></td>
                <td>{o.contacts?.full_name || o.companies?.company_name || '—'}</td>
                <td className="small">{o.order_type}</td>
                <td><Badge>{o.order_status}</Badge></td>
                <td className="small faint">{when(o.ordered_at)}</td>
                <td className="num">{money(o.total, o.currency)}</td>
              </tr>))}</tbody></table></div>
        )}
      </div>
    </Page>
  );
}
