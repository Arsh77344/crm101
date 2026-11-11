'use client';
import CrudPage from '@/components/CrudPage';
import Children from '@/components/Children';

export default function Collections() {
  return <CrudPage cfg={{
    table: 'collections', pk: 'collection_id', title: 'Collections', singular: 'collection',
    sub: (r) => `${r.length} ways to group what you sell`,
    order: ['sort_order', true],
    search: ['name', 'kind', 'description'],
    searchHint: 'Search collections…',
    filter: { col: 'kind', values: ['Collection', 'Material', 'Occasion', 'Season', 'Price band', 'Audience'] },
    emptyTitle: 'No collections yet',
    emptyHint: 'Group pieces by material, occasion or season, then build a campaign for the whole group at once.',
    sidePanel: (row) => (
      <Children parentId={row.collection_id} cfg={{
        table: 'product_collections', pk: 'product_id', pkCols: ['collection_id', 'product_id'],
        parentKey: 'collection_id', title: 'Pieces in this collection',
        select: '*,products(public_product_name,retail_price,status)',
        columns: [
          { key: 'products.public_product_name', label: 'Product' },
          { key: 'products.status', label: 'Status' },
          { key: 'products.retail_price', label: 'Retail', fmt: 'money', num: true },
        ],
        fields: [
          { name: 'product_id', label: 'Add a piece', required: true, width: 230,
            lookup: { table: 'products', pk: 'product_id', label: 'public_product_name' } },
        ],
      }} />),
    columns: [
      { key: 'name', label: 'Collection' },
      { key: 'kind', label: 'Kind' },
      { key: 'description', label: 'What it is' },
      { key: 'status', label: 'Status', fmt: 'badge' },
      { key: 'sort_order', label: 'Order', num: true },
    ],
    fields: [
      { name: 'name', label: 'Name', required: true, placeholder: 'Festive' },
      { name: 'slug', label: 'Link name', placeholder: 'festive', hint: 'Used in public links.' },
      { name: 'kind', label: 'Kind', options: ['Collection', 'Material', 'Occasion', 'Season', 'Price band', 'Audience', 'Other'],
        hint: 'Material groups by what it is made of; Occasion by when it is worn.' },
      { name: 'description', label: 'What it is', type: 'textarea' },
      { name: 'story', label: 'The story behind it', type: 'textarea',
        hint: 'The AI uses this when it writes campaigns for the collection.' },
      { name: 'status', label: 'Status', options: ['Active', 'Draft', 'Retired'] },
      { name: 'sort_order', label: 'Sort order', type: 'number' },
    ],
  }} />;
}
