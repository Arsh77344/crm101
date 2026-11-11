'use client';
import CrudPage from '@/components/CrudPage';
import Gallery from '@/components/Gallery';
import { money } from '@/components/ui';

export default function Products() {
  return <CrudPage cfg={{
    table: 'products', pk: 'product_id', title: 'Products', singular: 'product',
    sub: (r) => `${r.length} pieces in the catalogue · ${r.filter((p) => p.status === 'Published').length} live`,
    select: '*,product_images(public_url,is_primary)',
    order: ['created_at', false],
    sidePanel: (row) => <Gallery productId={row.product_id} />,
    search: ['public_product_name', 'internal_sku', 'colour', 'fabric', 'tags'],
    searchHint: 'Search name, SKU, colour, fabric…',
    filter: { col: 'status', values: ['Draft', 'Review', 'Published', 'Archived'] },
    emptyTitle: 'No products here', emptyHint: 'Add your first piece, or clear the filter.',
    kpis: (r) => [
      { label: 'Live', value: r.filter((p) => p.status === 'Published').length },
      { label: 'In stock', value: r.reduce((s, p) => s + (p.stock_qty || 0), 0), delta: 'pieces across the catalogue' },
      { label: 'Catalogue value', value: money(r.reduce((s, p) => s + (p.retail_price || 0) * (p.stock_qty || 0), 0)), delta: 'at retail' },
      { label: 'Out of stock', value: r.filter((p) => !p.stock_qty).length },
    ],
    columns: [
      { key: 'product_images', label: '', render: (r) => {
        const img = (r.product_images || []).find((i) => i.is_primary) || (r.product_images || [])[0];
        return <div className="thumb">{img ? <img src={img.public_url} alt="" /> : (r.colour || '—').slice(0, 3)}</div>;
      } },
      { key: 'public_product_name', label: 'Product' },
      { key: 'internal_sku', label: 'SKU' },
      { key: 'fabric', label: 'Fabric' },
      { key: 'retail_price', label: 'Retail', fmt: 'money', num: true },
      { key: 'wholesale_price', label: 'Wholesale', fmt: 'money', num: true },
      { key: 'stock_qty', label: 'Stock', num: true },
      { key: 'status', label: 'Status', fmt: 'badge' },
    ],
    sheet: [
      { key: 'public_product_name', label: 'Product name', required: true, example: 'Mashru Silk Banarasi — Deep Magenta' },
      { key: 'internal_sku', label: 'SKU', example: 'USY-MS-001' },
      { key: 'category', label: 'Category', example: 'Banarasi Saree' },
      { key: 'fabric', label: 'Fabric', example: 'Mashru Satin Silk' },
      { key: 'colour', label: 'Colour', example: 'Magenta' },
      { key: 'weave_or_motif', label: 'Weave or motif', example: 'Jangla floral' },
      { key: 'description', label: 'Description', example: 'Handwoven with a dense floral jaal.' },
      { key: 'tags', label: 'Tags', example: 'wedding, silk' },
      { key: 'cost_price', label: 'Cost price', example: 4200 },
      { key: 'retail_price', label: 'Retail price', example: 11900 },
      { key: 'wholesale_price', label: 'Wholesale price', example: 8200 },
      { key: 'stock_qty', label: 'Stock', example: 6 },
      { key: 'moq', label: 'Minimum order quantity', example: 2 },
      { key: 'status', label: 'Status', example: 'Draft', hint: 'Draft, Review, Published or Archived' },
    ],
    fields: [
      { name: 'public_product_name', label: 'Product name', required: true },
      { name: 'internal_sku', label: 'SKU', placeholder: 'USY-MS-001' },
      { name: 'category', label: 'Category', placeholder: 'Banarasi Saree' },
      { name: 'fabric', label: 'Fabric', placeholder: 'Mashru Satin Silk' },
      { name: 'colour', label: 'Colour' },
      { name: 'weave_or_motif', label: 'Weave or motif', placeholder: 'Jangla floral' },
      { name: 'description', label: 'Description', type: 'textarea' },
      { name: 'tags', label: 'Tags', placeholder: 'wedding, silk, handloom' },
      { name: 'cost_price', label: 'Cost price', type: 'number', step: '0.01' },
      { name: 'retail_price', label: 'Retail price', type: 'number', step: '0.01' },
      { name: 'wholesale_price', label: 'Wholesale price', type: 'number', step: '0.01' },
      { name: 'currency', label: 'Currency', options: ['INR', 'USD', 'GBP', 'EUR'] },
      { name: 'stock_qty', label: 'Stock quantity', type: 'number' },
      { name: 'moq', label: 'Minimum order quantity', type: 'number' },
      { name: 'status', label: 'Status', options: ['Draft', 'Review', 'Published', 'Archived'],
        hint: 'Published pieces can appear in showrooms and on the storefront.' },
    ],
  }} />;
}
