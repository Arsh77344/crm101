'use client';
import CrudPage from '@/components/CrudPage';
import { money } from '@/components/ui';

export default function Returns() {
  return <CrudPage cfg={{
    table: 'returns', pk: 'return_id', title: 'Returns & exchanges', singular: 'return',
    select: '*,orders(order_number),contacts(full_name)',
    sub: (r) => `${r.filter((x) => x.resolution === 'Pending').length} open · ${r.length} all time`,
    order: ['opened_on', false],
    search: ['reason', 'orders.order_number', 'contacts.full_name'],
    searchHint: 'Search reason, order, customer…',
    filter: { col: 'resolution', values: ['Pending', 'Exchange', 'Refund', 'Rejected', 'Closed'] },
    emptyTitle: 'No returns', emptyHint: 'Log one here when a piece comes back.',
    kpis: (r) => [
      { label: 'Open', value: r.filter((x) => x.resolution === 'Pending').length },
      { label: 'Value at risk', value: money(r.filter((x) => x.resolution === 'Pending').reduce((s, x) => s + Number(x.amount || 0), 0)) },
      { label: 'Refunded', value: money(r.filter((x) => x.resolution === 'Refund').reduce((s, x) => s + Number(x.amount || 0), 0)) },
      { label: 'Exchanged', value: r.filter((x) => x.resolution === 'Exchange').length },
    ],
    columns: [
      { key: 'orders.order_number', label: 'Order' },
      { key: 'contacts.full_name', label: 'Customer' },
      { key: 'reason', label: 'Reason' },
      { key: 'amount', label: 'Amount', fmt: 'money', num: true },
      { key: 'resolution', label: 'Resolution', fmt: 'badge' },
      { key: 'opened_on', label: 'Opened', fmt: 'date' },
    ],
    fields: [
      { name: 'order_id', label: 'Order', lookup: { table: 'orders', pk: 'order_id', label: 'order_number' } },
      { name: 'contact_id', label: 'Customer', lookup: { table: 'contacts', pk: 'contact_id', label: 'full_name' } },
      { name: 'reason', label: 'Reason', type: 'textarea' },
      { name: 'amount', label: 'Amount', type: 'number', step: '0.01' },
      { name: 'resolution', label: 'Resolution', options: ['Pending', 'Exchange', 'Refund', 'Rejected', 'Closed'] },
      { name: 'opened_on', label: 'Opened on', type: 'date' },
      { name: 'closed_on', label: 'Closed on', type: 'date' },
      { name: 'notes', label: 'Notes', type: 'textarea' },
    ],
  }} />;
}
