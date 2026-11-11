'use client';
import CrudPage from '@/components/CrudPage';
import { money } from '@/components/ui';

export default function Broadcasts() {
  return <CrudPage cfg={{
    table: 'broadcasts', pk: 'broadcast_id', title: 'Broadcasts', singular: 'broadcast',
    select: '*,campaigns(campaign_name),message_templates(name,category)',
    sub: (r) => `${r.filter((b) => b.status === 'Sent').length} sent of ${r.length}`,
    order: ['created_at', false],
    search: ['audience_note', 'campaigns.campaign_name'],
    searchHint: 'Search broadcasts…',
    filter: { col: 'status', values: ['Draft', 'Scheduled', 'Sending', 'Sent', 'Paused', 'Failed'] },
    emptyTitle: 'No broadcasts yet',
    emptyHint: 'Once WhatsApp is connected, a broadcast sends an approved template to a consented audience.',
    kpis: (r) => [
      { label: 'Delivered', value: r.reduce((s, b) => s + (b.delivered || 0), 0) },
      { label: 'Read', value: r.reduce((s, b) => s + (b.read_count || 0), 0) },
      { label: 'Held back', value: r.reduce((s, b) => s + (b.held_back || 0), 0), delta: 'no consent, or a guardrail' },
      { label: 'Spent', value: money(r.reduce((s, b) => s + Number(b.estimated_cost || 0), 0)) },
    ],
    columns: [
      { key: 'campaigns.campaign_name', label: 'Campaign' },
      { key: 'message_templates.name', label: 'Template' },
      { key: 'channel', label: 'Channel' },
      { key: 'scheduled_for', label: 'When', fmt: 'datetime' },
      { key: 'recipients', label: 'To', num: true },
      { key: 'delivered', label: 'Delivered', num: true },
      { key: 'read_count', label: 'Read', num: true },
      { key: 'status', label: 'Status', fmt: 'badge' },
    ],
    fields: [
      { name: 'campaign_id', label: 'Campaign', lookup: { table: 'campaigns', pk: 'campaign_id', label: 'campaign_name' } },
      { name: 'template_id', label: 'Template', lookup: { table: 'message_templates', pk: 'template_id', label: 'name' } },
      { name: 'channel', label: 'Channel', options: ['WhatsApp', 'SMS', 'Email'] },
      { name: 'scheduled_for', label: 'Send at', type: 'datetime-local' },
      { name: 'audience_note', label: 'Who it goes to', type: 'textarea',
        hint: 'Anyone without consent on this channel is held back automatically.' },
      { name: 'status', label: 'Status', options: ['Draft', 'Scheduled', 'Sending', 'Sent', 'Paused', 'Failed'] },
    ],
  }} />;
}
