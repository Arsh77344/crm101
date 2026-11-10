'use client';
import CrudPage from '@/components/CrudPage';

export default function Suppliers() {
  return <CrudPage cfg={{
    table: 'suppliers', pk: 'supplier_id', title: 'Weavers & suppliers', singular: 'supplier',
    sub: (r) => `${r.filter((s) => s.status === 'Active').length} active of ${r.length}`,
    order: ['created_at', false],
    search: ['name', 'cluster', 'specialty', 'kind'],
    searchHint: 'Search name, cluster, speciality…',
    filter: { col: 'kind', values: ['Weaver', 'Dyer', 'Finisher', 'Packaging', 'Photographer', 'Other'] },
    emptyTitle: 'No suppliers yet', emptyHint: 'The people who actually make the pieces belong here.',
    kpis: (r) => [
      { label: 'Weavers', value: r.filter((s) => s.kind === 'Weaver').length },
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
