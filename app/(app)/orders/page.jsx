'use client';
import CrudPage from '@/components/CrudPage';
import { money } from '@/components/ui';

export default function Orders() {
  return <CrudPage cfg={{
    table: 'orders', pk: 'order_id', title: 'Orders', singular: 'order',
    select: '*,contacts(full_name),companies(company_name)',
    sub: (r) => `${r.length} orders`,
    order: ['ordered_at', false],
    search: ['order_number', 'contacts.full_name', 'order_status', 'external_order_reference'],
    searchHint: 'Search order number or customer…',
    filter: { col: 'order_status', values: ['Draft', 'Pending Payment', 'Processing', 'Fulfilled', 'Cancelled'] },
    emptyTitle: 'No orders', emptyHint: 'Record a sale or sync one from the storefront.',
    kpis: (r) => {
      const paid = r.filter((o) => ['Fulfilled', 'Processing'].includes(o.order_status));
      const total = paid.reduce((s, o) => s + Number(o.total || 0), 0);
      return [
        { label: 'Booked value', value: money(total), delta: `${paid.length} paid or processing` },
        { label: 'Average order', value: money(paid.length ? total / paid.length : 0) },
        { label: 'Awaiting action', value: r.filter((o) => ['Draft', 'Pending Payment', 'Processing'].includes(o.order_status)).length },
        { label: 'Wholesale share', value: `${r.length ? Math.round((r.filter((o) => o.order_type === 'B2B').length / r.length) * 100) : 0}%` },
      ];
    },
    columns: [
      { key: 'order_number', label: 'Order' },
      { key: 'contacts.full_name', label: 'Customer' },
      { key: 'order_type', label: 'Type' },
      { key: 'order_status', label: 'Status', fmt: 'badge' },
      { key: 'ordered_at', label: 'Date', fmt: 'date' },
      { key: 'total', label: 'Total', fmt: 'money', num: true },
    ],
    fields: [
      { name: 'order_number', label: 'Order number', placeholder: 'USY-1046' },
      { name: 'contact_id', label: 'Customer', lookup: { table: 'contacts', pk: 'contact_id', label: 'full_name' } },
      { name: 'company_id', label: 'Company', lookup: { table: 'companies', pk: 'company_id', label: 'company_name' } },
      { name: 'order_type', label: 'Type', options: ['B2C', 'B2B'] },
      { name: 'order_status', label: 'Status', options: ['Draft', 'Pending Payment', 'Processing', 'Fulfilled', 'Cancelled'] },
      { name: 'subtotal', label: 'Subtotal', type: 'number', step: '0.01' },
      { name: 'discount', label: 'Discount', type: 'number', step: '0.01' },
      { name: 'shipping', label: 'Shipping', type: 'number', step: '0.01' },
      { name: 'total', label: 'Total', type: 'number', step: '0.01' },
      { name: 'external_order_reference', label: 'External reference', placeholder: 'Wix or Shopify order id' },
    ],
  }} />;
}
