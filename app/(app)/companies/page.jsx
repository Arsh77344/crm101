'use client';
import CrudPage from '@/components/CrudPage';

export default function Companies() {
  return <CrudPage cfg={{
    table: 'companies', pk: 'company_id', title: 'Companies', singular: 'company',
    sub: (r) => `${r.length} accounts`,
    order: ['created_at', false],
    search: ['company_name', 'country', 'company_type', 'wholesale_tier'],
    searchHint: 'Search company, country, tier…',
    emptyTitle: 'No companies yet', emptyHint: 'Boutiques, distributors and retailers live here.',
    columns: [
      { key: 'company_name', label: 'Company' },
      { key: 'company_type', label: 'Type' },
      { key: 'wholesale_tier', label: 'Tier' },
      { key: 'country', label: 'Country' },
      { key: 'website', label: 'Website' },
    ],
    fields: [
      { name: 'company_name', label: 'Company name', required: true },
      { name: 'company_type', label: 'Type', placeholder: 'Boutique, Distributor' },
      { name: 'wholesale_tier', label: 'Wholesale tier', placeholder: 'Tier 1' },
      { name: 'country', label: 'Country' },
      { name: 'website', label: 'Website' },
      { name: 'notes', label: 'Notes', type: 'textarea' },
    ],
  }} />;
}
