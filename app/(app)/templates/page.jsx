'use client';
import CrudPage from '@/components/CrudPage';

export default function Templates() {
  return <CrudPage cfg={{
    table: 'message_templates', pk: 'template_id', title: 'Message templates', singular: 'template',
    sub: (r) => `${r.filter((t) => t.provider_status === 'Approved').length} approved of ${r.length}`,
    order: ['created_at', false],
    search: ['name', 'body', 'category'],
    searchHint: 'Search templates…',
    filter: { col: 'provider_status', values: ['Draft', 'Submitted', 'Approved', 'Rejected', 'Paused'] },
    emptyTitle: 'No templates yet',
    emptyHint: 'WhatsApp needs every business-initiated message approved in advance. Write them here first.',
    kpis: (r) => [
      { label: 'Approved', value: r.filter((t) => t.provider_status === 'Approved').length },
      { label: 'Waiting', value: r.filter((t) => t.provider_status === 'Submitted').length },
      { label: 'Marketing', value: r.filter((t) => t.category === 'Marketing').length, delta: 'the paid ones' },
      { label: 'Utility', value: r.filter((t) => t.category === 'Utility').length, delta: 'far cheaper' },
    ],
    columns: [
      { key: 'name', label: 'Name' },
      { key: 'channel', label: 'Channel' },
      { key: 'category', label: 'Category' },
      { key: 'body', label: 'Message' },
      { key: 'provider_status', label: 'Status', fmt: 'badge' },
    ],
    fields: [
      { name: 'name', label: 'Name', required: true, placeholder: 'festive_launch_v1',
        hint: 'Lowercase with underscores, the way the provider wants it.' },
      { name: 'channel', label: 'Channel', options: ['WhatsApp', 'SMS', 'Email'] },
      { name: 'category', label: 'Category', options: ['Marketing', 'Utility', 'Authentication', 'Service'],
        hint: 'Marketing costs the most. Utility is for order updates and is far cheaper.' },
      { name: 'language', label: 'Language', placeholder: 'en' },
      { name: 'header', label: 'Header' },
      { name: 'body', label: 'Message', type: 'textarea',
        hint: 'Use {{1}}, {{2}} for the bits that change, as the provider expects.' },
      { name: 'buttons', label: 'Buttons', placeholder: 'Shop now | Stop promotions' },
      { name: 'provider_status', label: 'Approval status',
        options: ['Draft', 'Submitted', 'Approved', 'Rejected', 'Paused'] },
      { name: 'provider_name', label: 'Name at the provider' },
    ],
  }} />;
}
