'use client';
import CrudPage from '@/components/CrudPage';
import Children from '@/components/Children';

export default function Showrooms() {
  return <CrudPage cfg={{
    table: 'showrooms', pk: 'showroom_id', title: 'Showrooms', singular: 'showroom',
    select: '*,contacts(full_name)',
    sub: (r) => `${r.filter((s) => s.status === 'Published').length} live of ${r.length}`,
    order: ['created_at', false],
    search: ['title', 'slug', 'contacts.full_name'],
    searchHint: 'Search showrooms…',
    emptyTitle: 'No showrooms yet',
    emptyHint: 'A private page of selected pieces you can send to one buyer.',
    columns: [
      { key: 'title', label: 'Title' },
      { key: 'contacts.full_name', label: 'For' },
      { key: 'pricing_mode', label: 'Pricing' },
      { key: 'status', label: 'Status', fmt: 'badge' },
      { key: 'slug', label: 'Link',
        render: (r) => <a className="link mono" href={`/s/?slug=${r.slug}`} target="_blank" rel="noreferrer">/s/{r.slug}</a> },
    ],
    sidePanel: (row) => (
      <Children parentId={row.showroom_id} cfg={{
        table: 'showroom_products', pk: 'product_id', pkCols: ['showroom_id', 'product_id'],
        parentKey: 'showroom_id', title: 'Pieces in this showroom', order: 'sort_order',
        select: '*,products(public_product_name,retail_price,wholesale_price)',
        columns: [
          { key: 'products.public_product_name', label: 'Product' },
          { key: 'products.retail_price', label: 'Retail', fmt: 'money', num: true },
          { key: 'custom_price', label: 'Custom', fmt: 'money', num: true },
        ],
        fields: [
          { name: 'product_id', label: 'Published piece', required: true, width: 200,
            lookup: { table: 'products', pk: 'product_id', label: 'public_product_name' } },
          { name: 'custom_price', label: 'Custom price', type: 'number', step: '0.01', width: 120 },
          { name: 'sort_order', label: 'Order', type: 'number', width: 70 },
        ],
      }} />),
    fields: [
      { name: 'title', label: 'Title', required: true, placeholder: 'Festive capsule for Meher Boutique' },
      { name: 'slug', label: 'Link name', required: true, placeholder: 'meher-festive-2026',
        hint: 'Used in the private link you share.' },
      { name: 'contact_id', label: 'For', lookup: { table: 'contacts', pk: 'contact_id', label: 'full_name' } },
      { name: 'pricing_mode', label: 'Pricing shown', options: ['Hidden', 'Retail', 'Wholesale'] },
      { name: 'status', label: 'Status', options: ['Draft', 'Published', 'Closed'],
        hint: 'Only a Published showroom opens for the buyer.' },
      { name: 'public_enabled', label: 'Anyone with the link can view', options: ['true', 'false'] },
      { name: 'intro_text', label: 'Intro', type: 'textarea' },
      { name: 'cta_text', label: 'Call to action' },
    ],
  }} />;
}
