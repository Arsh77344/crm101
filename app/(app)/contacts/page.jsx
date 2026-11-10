'use client';
import CrudPage from '@/components/CrudPage';

export default function Contacts() {
  return <CrudPage cfg={{
    table: 'contacts', pk: 'contact_id', title: 'Contacts', singular: 'contact',
    sub: (r) => `${r.length} people · ${r.filter((c) => c.lifecycle_stage === 'Customer').length} customers`,
    order: ['created_at', false],
    search: ['full_name', 'email', 'phone_number', 'business_category', 'country'],
    searchHint: 'Search name, email, phone, country…',
    filter: { col: 'lifecycle_stage', values: ['New', 'Lead', 'Opportunity', 'Customer', 'Dormant'] },
    emptyTitle: 'No contacts match', emptyHint: 'Try another filter, or add someone new.',
    kpis: (r) => [
      { label: 'Customers', value: r.filter((c) => c.lifecycle_stage === 'Customer').length },
      { label: 'Open leads', value: r.filter((c) => ['Lead', 'Opportunity'].includes(c.lifecycle_stage)).length },
      { label: 'Wholesale', value: r.filter((c) => c.contact_type === 'B2B').length, delta: 'B2B contacts' },
      { label: 'Need review', value: r.filter((c) => c.qualification_status === 'Unreviewed').length },
    ],
    columns: [
      { key: 'full_name', label: 'Name' },
      { key: 'contact_type', label: 'Type' },
      { key: 'lifecycle_stage', label: 'Stage', fmt: 'badge' },
      { key: 'email', label: 'Email' },
      { key: 'phone_number', label: 'Phone' },
      { key: 'country', label: 'Country' },
      { key: 'lead_score', label: 'Score', num: true },
    ],
    fields: [
      { name: 'full_name', label: 'Full name', required: true },
      { name: 'contact_type', label: 'Type', options: ['B2C', 'B2B', 'Both', 'Unknown'] },
      { name: 'email', label: 'Email', type: 'email' },
      { name: 'phone_number', label: 'Phone' },
      { name: 'country', label: 'Country' },
      { name: 'business_category', label: 'Business category', placeholder: 'Boutique, Distributor, Individual' },
      { name: 'lifecycle_stage', label: 'Lifecycle stage', options: ['New', 'Lead', 'Opportunity', 'Customer', 'Dormant'] },
      { name: 'qualification_status', label: 'Qualification', options: ['Unreviewed', 'Qualified', 'Disqualified', 'On hold'] },
      { name: 'lead_score', label: 'Lead score', type: 'number' },
      { name: 'next_follow_up', label: 'Next follow up', type: 'date' },
      { name: 'source_name', label: 'Source', placeholder: 'Instagram DM, Trade fair' },
      { name: 'website', label: 'Instagram or website' },
      { name: 'relevance_reason', label: 'Notes', type: 'textarea',
        hint: 'Why they matter, what they buy, what to remember.' },
    ],
  }} />;
}
