'use client';
import CrudPage from '@/components/CrudPage';
import Children from '@/components/Children';

export default function Contacts() {
  return <CrudPage cfg={{
    table: 'contacts', pk: 'contact_id', title: 'Contacts', singular: 'contact',
    sub: (r) => `${r.length} people · ${r.filter((c) => c.lifecycle_stage === 'Customer').length} customers`,
    order: ['created_at', false],
    sidePanel: (row) => (
      <div className="stack">
        <Children parentId={row.contact_id} cfg={{
          table: 'activities', pk: 'activity_id', parentKey: 'contact_id',
          title: 'Activity', order: 'created_at',
          columns: [
            { key: 'created_at', label: 'When', render: (r) => new Date(r.created_at).toLocaleDateString('en-GB') },
            { key: 'activity_type', label: 'Type' },
            { key: 'summary', label: 'What happened' },
          ],
          fields: [
            { name: 'activity_type', label: 'Type', width: 110,
              options: ['Note', 'Call', 'Email', 'Meeting', 'WhatsApp', 'Visit'] },
            { name: 'summary', label: 'What happened', required: true, width: 220 },
            { name: 'follow_up_at', label: 'Follow up', type: 'date', width: 140 },
          ],
        }} />
        <Children parentId={row.contact_id} cfg={{
          table: 'marketing_permissions', pk: 'permission_id', parentKey: 'contact_id',
          title: 'Marketing consent',
          columns: [
            { key: 'channel', label: 'Channel' },
            { key: 'status', label: 'Status' },
            { key: 'lawful_basis_or_reason', label: 'Basis' },
          ],
          fields: [
            { name: 'channel', label: 'Channel', width: 120, options: ['Email', 'WhatsApp', 'SMS', 'Phone', 'Other'] },
            { name: 'status', label: 'Status', width: 140,
              options: ['OptedIn', 'Allowed', 'Unknown', 'OptedOut', 'Suppressed', 'DoNotContact'] },
            { name: 'lawful_basis_or_reason', label: 'Basis', width: 170 },
          ],
        }} />
      </div>),
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
    sheet: [
      { key: 'full_name', label: 'Full name', required: true, example: 'Meher Siddiqui' },
      { key: 'contact_type', label: 'Type', example: 'B2B', hint: 'B2C, B2B, Both or Unknown' },
      { key: 'email', label: 'Email', example: 'meher@example.com' },
      { key: 'phone_number', label: 'Phone', example: '+91 98490 11223' },
      { key: 'country', label: 'Country', example: 'India' },
      { key: 'business_category', label: 'Business category', example: 'Boutique' },
      { key: 'lifecycle_stage', label: 'Stage', example: 'Lead', hint: 'New, Lead, Opportunity, Customer, Dormant' },
      { key: 'qualification_status', label: 'Qualification', example: 'Unreviewed' },
      { key: 'lead_score', label: 'Lead score', example: 50 },
      { key: 'source_name', label: 'Source', example: 'Instagram DM' },
      { key: 'website', label: 'Instagram or website', example: 'instagram.com/meher' },
      { key: 'relevance_reason', label: 'Notes', example: 'Repeat wholesale buyer' },
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
