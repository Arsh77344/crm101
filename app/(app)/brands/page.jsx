'use client';
import CrudPage from '@/components/CrudPage';
import Children from '@/components/Children';
import { money } from '@/components/ui';

export default function Brands() {
  return <CrudPage cfg={{
    table: 'brands', pk: 'brand_id', title: 'Brand partners', singular: 'brand',
    sub: (r) => `${r.filter((b) => b.status === 'Active').length} active of ${r.length}`,
    order: ['created_at', true],
    search: ['name', 'city', 'contact_person'],
    searchHint: 'Search brands…',
    filter: { col: 'status', values: ['Active', 'Paused', 'Ended'] },
    emptyTitle: 'No brand partners yet',
    emptyHint: 'The brands whose pieces you sell. You hold none of their stock; you owe them only once a piece sells.',
    sheet: [
      { key: 'name', label: 'Brand', required: true, example: 'Partner Brand A' },
      { key: 'contact_person', label: 'Contact person', example: 'Name' },
      { key: 'phone', label: 'Phone', example: '+91 90000 00001' },
      { key: 'email', label: 'Email', example: '' },
      { key: 'city', label: 'City', example: 'Varanasi' },
      { key: 'pickup_address', label: 'Pickup address', example: 'Shop address for courier pickup' },
      { key: 'gst_number', label: 'GST number', example: '' },
      { key: 'payout_terms', label: 'Payout terms', example: 'On sale' },
      { key: 'status', label: 'Status', example: 'Active' },
    ],
    sidePanel: (row) => (
      <div className="stack">
        <Children parentId={row.brand_id} cfg={{
          table: 'products', pk: 'product_id', parentKey: 'brand_id',
          title: 'Their pieces', order: 'public_product_name',
          columns: [
            { key: 'public_product_name', label: 'Piece' },
            { key: 'cost_price', label: 'You owe', fmt: 'money', num: true },
            { key: 'retail_price', label: 'You charge', fmt: 'money', num: true },
            { key: 'availability', label: 'Availability' },
          ],
          fields: [
            { name: 'public_product_name', label: 'Piece name', required: true, width: 190 },
            { name: 'cost_price', label: 'Agreed cost', type: 'number', step: '0.01', width: 120, required: true },
            { name: 'retail_price', label: 'Your price', type: 'number', step: '0.01', width: 120 },
          ],
        }} />
        <Children parentId={row.brand_id} cfg={{
          table: 'payables', pk: 'payable_id', parentKey: 'brand_id',
          title: 'What you owe them', order: 'accrued_on',
          columns: [
            { key: 'accrued_on', label: 'Accrued' },
            { key: 'note', label: 'Against' },
            { key: 'amount', label: 'Amount', fmt: 'money', num: true },
            { key: 'status', label: 'Status' },
          ],
          fields: [
            { name: 'amount', label: 'Amount', type: 'number', step: '0.01', required: true, width: 120 },
            { name: 'status', label: 'Status', width: 130, options: ['Accrued', 'Approved', 'Paid', 'Reversed'] },
            { name: 'note', label: 'Note', width: 170 },
          ],
        }} />
      </div>),
    columns: [
      { key: 'name', label: 'Brand' },
      { key: 'contact_person', label: 'Contact' },
      { key: 'city', label: 'City' },
      { key: 'payout_terms', label: 'Pays out' },
      { key: 'status', label: 'Status', fmt: 'badge' },
    ],
    fields: [
      { name: 'name', label: 'Brand name', required: true },
      { name: 'contact_person', label: 'Contact person' },
      { name: 'phone', label: 'Phone' },
      { name: 'email', label: 'Email', type: 'email' },
      { name: 'city', label: 'City' },
      { name: 'pickup_address', label: 'Pickup address', type: 'textarea',
        hint: 'Where the courier collects. Shipments from this brand use it.' },
      { name: 'gst_number', label: 'GST number' },
      { name: 'payout_terms', label: 'Payout terms', options: ['On sale', 'Weekly', 'Fortnightly', 'Monthly', 'On invoice'] },
      { name: 'agreement_note', label: 'What was agreed', type: 'textarea',
        hint: 'Pricing basis, returns, anything worth remembering.' },
      { name: 'status', label: 'Status', options: ['Active', 'Paused', 'Ended'] },
    ],
  }} />;
}
