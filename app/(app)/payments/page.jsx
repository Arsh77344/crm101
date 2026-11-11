'use client';
import CrudPage from '@/components/CrudPage';
import { money } from '@/components/ui';

const STATUS = ['Created', 'Link sent', 'Paid', 'Failed', 'Refunded', 'Settled'];

export default function Payments() {
  return <CrudPage cfg={{
    table: 'payments', pk: 'payment_id', title: 'Payments', singular: 'payment',
    select: '*,orders(order_number),contacts(full_name)',
    sub: (r) => `${r.filter((p) => ['Paid', 'Settled'].includes(p.status)).length} collected · ${r.filter((p) => p.status === 'Link sent').length} awaiting payment`,
    order: ['created_at', false],
    search: ['reference', 'method', 'provider', 'orders.order_number', 'contacts.full_name'],
    searchHint: 'Search reference, method, customer…',
    filter: { col: 'status', values: STATUS },
    emptyTitle: 'No payments recorded', emptyHint: 'Log a payment link or a transfer against an order.',
    kpis: (r) => {
      const got = r.filter((p) => ['Paid', 'Settled'].includes(p.status));
      return [
        { label: 'Collected', value: money(got.reduce((s, p) => s + Number(p.amount || 0), 0)), delta: `${got.length} payments` },
        { label: 'Gateway fees', value: money(r.reduce((s, p) => s + Number(p.fee || 0), 0)) },
        { label: 'Awaiting', value: money(r.filter((p) => ['Created', 'Link sent'].includes(p.status)).reduce((s, p) => s + Number(p.amount || 0), 0)) },
        { label: 'Refunded', value: money(r.filter((p) => p.status === 'Refunded').reduce((s, p) => s + Number(p.amount || 0), 0)) },
      ];
    },
    columns: [
      { key: 'orders.order_number', label: 'Order' },
      { key: 'contacts.full_name', label: 'Customer' },
      { key: 'provider', label: 'Provider' },
      { key: 'method', label: 'Method' },
      { key: 'amount', label: 'Amount', fmt: 'money', num: true },
      { key: 'fee', label: 'Fee', fmt: 'money', num: true },
      { key: 'status', label: 'Status', fmt: 'badge' },
    ],
    sheet: [
      { key: 'provider', label: 'Provider', example: 'Razorpay' },
      { key: 'method', label: 'Method', example: 'UPI' },
      { key: 'amount', label: 'Amount', required: true, example: 12150 },
      { key: 'fee', label: 'Gateway fee', example: 239 },
      { key: 'status', label: 'Status', example: 'Paid' },
      { key: 'reference', label: 'Reference', example: 'pay_abc123' },
    ],
    fields: [
      { name: 'order_id', label: 'Order', lookup: { table: 'orders', pk: 'order_id', label: 'order_number' } },
      { name: 'contact_id', label: 'Customer', lookup: { table: 'contacts', pk: 'contact_id', label: 'full_name' } },
      { name: 'provider', label: 'Provider', options: ['Razorpay', 'Bank transfer', 'Cash', 'PayPal', 'Stripe', 'Other'] },
      { name: 'method', label: 'Method', placeholder: 'UPI, Card, NEFT, Payment link' },
      { name: 'amount', label: 'Amount', type: 'number', step: '0.01', required: true },
      { name: 'fee', label: 'Gateway fee', type: 'number', step: '0.01' },
      { name: 'status', label: 'Status', options: STATUS },
      { name: 'reference', label: 'Reference', placeholder: 'pay_… or UTR' },
      { name: 'link_url', label: 'Payment link' },
      { name: 'paid_at', label: 'Paid on', type: 'date' },
    ],
  }} />;
}
