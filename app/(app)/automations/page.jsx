'use client';
import CrudPage from '@/components/CrudPage';

export default function Automations() {
  return <CrudPage cfg={{
    table: 'automations', pk: 'automation_id', title: 'Automations', singular: 'automation',
    sub: (r) => `${r.filter((a) => a.enabled).length} switched on of ${r.length}`,
    order: ['created_at', true],
    search: ['name', 'trigger_event', 'action'],
    searchHint: 'Search automations…',
    emptyTitle: 'No automations', emptyHint: 'Write the rules you want the system to follow.',
    note: true,
    columns: [
      { key: 'name', label: 'Rule' },
      { key: 'trigger_event', label: 'When' },
      { key: 'action', label: 'Then' },
      { key: 'channel', label: 'Channel' },
      { key: 'enabled', label: 'On', render: (r) => (r.enabled ? <span className="badge b-green">On</span> : <span className="badge">Off</span>) },
    ],
    fields: [
      { name: 'name', label: 'Rule name', required: true },
      { name: 'trigger_event', label: 'When this happens', required: true, placeholder: 'Shipment marked Delivered' },
      { name: 'action', label: 'Do this', required: true, placeholder: 'Send a thank you and ask for a photo review' },
      { name: 'channel', label: 'Channel', options: ['Internal', 'WhatsApp', 'Email', 'SMS', 'Instagram'] },
      { name: 'template', label: 'Message template', type: 'textarea',
        hint: 'Use {first_name}, {product}, {link} as placeholders.' },
      { name: 'enabled', label: 'Switched on', options: ['false', 'true'],
        hint: 'Rules only fire once the matching integration is connected.' },
    ],
  }} />;
}
