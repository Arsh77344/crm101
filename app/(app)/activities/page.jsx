'use client';
import CrudPage from '@/components/CrudPage';

export default function Activities() {
  return <CrudPage cfg={{
    table: 'activities', pk: 'activity_id', title: 'Activities', singular: 'note',
    select: '*,contacts(full_name)',
    sub: (r) => `${r.length} calls, emails and notes`,
    order: ['created_at', false],
    search: ['summary', 'activity_type', 'contacts.full_name'],
    searchHint: 'Search notes and people…',
    filter: { col: 'activity_type', values: ['Note', 'Call', 'Email', 'Meeting', 'WhatsApp', 'Visit'] },
    emptyTitle: 'Nothing logged yet', emptyHint: 'Write down what was said while it is fresh.',
    columns: [
      { key: 'created_at', label: 'When', fmt: 'datetime' },
      { key: 'contacts.full_name', label: 'Who' },
      { key: 'activity_type', label: 'Type' },
      { key: 'summary', label: 'What happened' },
      { key: 'follow_up_at', label: 'Follow up', fmt: 'date' },
    ],
    sheet: [
      { key: 'activity_type', label: 'Type', example: 'Call' },
      { key: 'channel', label: 'Channel', example: 'Phone' },
      { key: 'direction', label: 'Direction', example: 'Outbound' },
      { key: 'summary', label: 'What happened', required: true, example: 'Discussed pricing' },
      { key: 'follow_up_at', label: 'Follow up on', example: '2026-11-20' },
    ],
    fields: [
      { name: 'contact_id', label: 'Contact', lookup: { table: 'contacts', pk: 'contact_id', label: 'full_name' } },
      { name: 'activity_type', label: 'Type', options: ['Note', 'Call', 'Email', 'Meeting', 'WhatsApp', 'Visit'] },
      { name: 'channel', label: 'Channel', options: ['Phone', 'Email', 'WhatsApp', 'Instagram', 'In person', 'Other'] },
      { name: 'direction', label: 'Direction', options: ['Outbound', 'Inbound'] },
      { name: 'summary', label: 'What happened', type: 'textarea', required: true },
      { name: 'follow_up_at', label: 'Follow up on', type: 'date' },
    ],
  }} />;
}
