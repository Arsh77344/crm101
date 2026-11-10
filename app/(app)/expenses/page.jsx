'use client';
import CrudPage from '@/components/CrudPage';
import { money } from '@/components/ui';

const CATS = ['Raw material', 'Weaving', 'Finishing', 'Packaging', 'Shipping', 'Marketing', 'Photography', 'Platform', 'Salaries', 'Other'];

export default function Expenses() {
  return <CrudPage cfg={{
    table: 'expenses', pk: 'expense_id', title: 'Expenses', singular: 'expense',
    select: '*,campaigns(campaign_name),suppliers(name)',
    sub: (r) => `${money(r.reduce((s, e) => s + Number(e.amount || 0), 0))} recorded across ${r.length} entries`,
    order: ['spent_on', false],
    search: ['vendor', 'category', 'notes'],
    searchHint: 'Search vendor, category, note…',
    filter: { col: 'category', values: CATS },
    emptyTitle: 'Nothing recorded', emptyHint: 'Log what the business spends so the profit figure means something.',
    kpis: (r) => {
      const d30 = Date.now() - 30 * 864e5;
      const recent = r.filter((e) => new Date(e.spent_on).getTime() >= d30);
      const byCat = {};
      r.forEach((e) => { byCat[e.category] = (byCat[e.category] || 0) + Number(e.amount || 0); });
      const top = Object.entries(byCat).sort((a, b) => b[1] - a[1])[0];
      return [
        { label: 'Last 30 days', value: money(recent.reduce((s, e) => s + Number(e.amount || 0), 0)), delta: `${recent.length} entries` },
        { label: 'All time', value: money(r.reduce((s, e) => s + Number(e.amount || 0), 0)) },
        { label: 'Biggest line', value: top ? top[0] : '—', delta: top ? money(top[1]) : '' },
        { label: 'Marketing', value: money(byCat['Marketing'] || 0) },
      ];
    },
    columns: [
      { key: 'spent_on', label: 'Date', fmt: 'date' },
      { key: 'category', label: 'Category' },
      { key: 'vendor', label: 'Vendor' },
      { key: 'campaigns.campaign_name', label: 'Campaign' },
      { key: 'amount', label: 'Amount', fmt: 'money', num: true },
    ],
    fields: [
      { name: 'spent_on', label: 'Date', type: 'date' },
      { name: 'category', label: 'Category', options: CATS },
      { name: 'vendor', label: 'Paid to' },
      { name: 'amount', label: 'Amount', type: 'number', step: '0.01', required: true },
      { name: 'campaign_id', label: 'Against campaign', lookup: { table: 'campaigns', pk: 'campaign_id', label: 'campaign_name' } },
      { name: 'supplier_id', label: 'Against supplier', lookup: { table: 'suppliers', pk: 'supplier_id', label: 'name' } },
      { name: 'notes', label: 'Notes', type: 'textarea' },
    ],
  }} />;
}
