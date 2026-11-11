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
      { label: 'Return shipping borne', value: money(r.reduce((s, x) => s + Number(x.reverse_logistics_cost || 0), 0)),
        delta: 'your cost, not the partner\'s' },
    ],
    columns: [
      { key: 'orders.order_number', label: 'Order' },
      { key: 'contacts.full_name', label: 'Customer' },
      { key: 'reason', label: 'Reason' },
      { key: 'amount', label: 'Amount', fmt: 'money', num: true },
      { key: 'resolution', label: 'Resolution', fmt: 'badge' },
      { key: 'opened_on', label: 'Opened', fmt: 'date' },
    ],
    sheet: [
      { key: 'reason', label: 'Reason', required: true, example: 'Colour looked different' },
      { key: 'resolution', label: 'Resolution', example: 'Pending' },
      { key: 'amount', label: 'Amount', example: 2600 },
      { key: 'opened_on', label: 'Opened on', example: '2026-11-05' },
      { key: 'notes', label: 'Notes', example: '' },
    ],
    fields: [
      { name: 'order_id', label: 'Order', lookup: { table: 'orders', pk: 'order_id', label: 'order_number' } },
      { name: 'contact_id', label: 'Customer', lookup: { table: 'contacts', pk: 'contact_id', label: 'full_name' } },
      { name: 'reason', label: 'Reason', type: 'textarea' },
      { name: 'amount', label: 'Amount refunded', type: 'number', step: '0.01' },
      { name: 'reverse_logistics_cost', label: 'Return shipping you paid', type: 'number', step: '0.01',
        hint: 'You bear this, not the partner.' },
      { name: 'brand_refunded', label: 'Partner refunded you', options: ['false', 'true'] },
      { name: 'resolution', label: 'Resolution', options: ['Pending', 'Exchange', 'Refund', 'Rejected', 'Closed'] },
      { name: 'opened_on', label: 'Opened on', type: 'date' },
      { name: 'closed_on', label: 'Closed on', type: 'date' },
      { name: 'notes', label: 'Notes', type: 'textarea' },
    ],
  }} />;
}
