'use client';
import CrudPage from '@/components/CrudPage';
import Children from '@/components/Children';

export default function Suppliers() {
  return <CrudPage cfg={{
    table: 'suppliers', pk: 'supplier_id', title: 'Service vendors', singular: 'vendor',
    sub: (r) => `${r.filter((s) => s.status === 'Active').length} active of ${r.length}`,
    order: ['created_at', false],
    search: ['name', 'cluster', 'specialty', 'kind'],
    searchHint: 'Search name, cluster, speciality…',
    filter: { col: 'kind', values: ['Weaver', 'Dyer', 'Finisher', 'Packaging', 'Photographer', 'Other'] },
    emptyTitle: 'No suppliers yet', emptyHint: 'Photographers, packaging, couriers and anyone else you pay for a service. The brands whose pieces you sell live under Brand partners.',
    kpis: (r) => [
      { label: 'Vendors', value: r.length },
      { label: 'Active', value: r.filter((s) => s.status === 'Active').length },
      { label: 'Average lead time',
        value: r.length ? `${Math.round(r.reduce((s, x) => s + (x.lead_time_days || 0), 0) / r.length)} days` : '—' },
      { label: 'Clusters', value: new Set(r.map((s) => s.cluster).filter(Boolean)).size },
    ],
    columns: [
      { key: 'name', label: 'Name' },
      { key: 'kind', label: 'Kind' },
      { key: 'cluster', label: 'Cluster' },
      { key: 'specialty', label: 'Speciality' },
      { key: 'lead_time_days', label: 'Lead days', num: true },
      { key: 'status', label: 'Status', fmt: 'badge' },
    ],
    sidePanel: (row) => (
      <Children parentId={row.supplier_id} cfg={{
        table: 'supplier_orders', pk: 'supplier_order_id', parentKey: 'supplier_id',
        title: 'Commissions with this supplier', order: 'expected_on',
        select: '*,products(public_product_name)',
        columns: [
          { key: 'reference', label: 'Ref' },
          { key: 'products.public_product_name', label: 'Piece' },
          { key: 'pieces', label: 'No.', num: true },
          { key: 'agreed_cost', label: 'Cost', fmt: 'money', num: true },
          { key: 'status', label: 'Status' },
        ],
        fields: [
          { name: 'reference', label: 'Reference', width: 110 },
          { name: 'product_id', label: 'Piece', width: 180,
            lookup: { table: 'products', pk: 'product_id', label: 'public_product_name' } },
          { name: 'pieces', label: 'Pieces', type: 'number', width: 80 },
          { name: 'agreed_cost', label: 'Agreed cost', type: 'number', step: '0.01', width: 120 },
          { name: 'expected_on', label: 'Expected', type: 'date', width: 140 },
        ],
      }} />),
    sheet: [
      { key: 'name', label: 'Name', required: true, example: 'Ustad Shakeel Ansari' },
      { key: 'kind', label: 'Kind', example: 'Weaver' },
      { key: 'cluster', label: 'Cluster', example: 'Madanpura, Varanasi' },
      { key: 'phone', label: 'Phone', example: '+91 94150 22187' },
      { key: 'specialty', label: 'Speciality', example: 'Kadhua booti on katan silk' },
      { key: 'lead_time_days', label: 'Lead time days', example: 42 },
      { key: 'rate_note', label: 'How they charge', example: 'Per piece' },
      { key: 'status', label: 'Status', example: 'Active' },
      { key: 'notes', label: 'Notes', example: '' },
    ],
    fields: [
      { name: 'name', label: 'Name', required: true },
      { name: 'kind', label: 'Kind', options: ['Weaver', 'Dyer', 'Finisher', 'Packaging', 'Photographer', 'Other'] },
      { name: 'cluster', label: 'Cluster or area', placeholder: 'Madanpura, Varanasi' },
      { name: 'phone', label: 'Phone' },
      { name: 'email', label: 'Email', type: 'email' },
      { name: 'specialty', label: 'Speciality', placeholder: 'Kadhua booti on katan silk' },
      { name: 'lead_time_days', label: 'Typical lead time (days)', type: 'number' },
      { name: 'rate_note', label: 'How they charge', placeholder: 'Per piece, per metre, per kg' },
      { name: 'status', label: 'Status', options: ['Active', 'Paused', 'Ended'] },
      { name: 'notes', label: 'Notes', type: 'textarea' },
    ],
  }} />;
}
