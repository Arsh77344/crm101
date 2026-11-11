'use client';
import CrudPage from '@/components/CrudPage';
import Gallery from '@/components/Gallery';
import Children from '@/components/Children';
import { money } from '@/components/ui';

export default function Products() {
  return <CrudPage cfg={{
    table: 'products', pk: 'product_id', title: 'Products', singular: 'product',
    sub: (r) => `${r.length} pieces in the catalogue · ${r.filter((p) => p.status === 'Published').length} live`,
    select: '*,product_images(public_url,is_primary),brands(name)',
    order: ['created_at', false],
    sidePanel: (row) => (
      <div className="stack">
        <Gallery productId={row.product_id} />
        <Children parentId={row.product_id} cfg={{
          table: 'product_collections', pk: 'collection_id', pkCols: ['product_id', 'collection_id'],
          parentKey: 'product_id', title: 'Collections it belongs to',
          select: '*,collections(name,kind)',
          columns: [
            { key: 'collections.name', label: 'Collection' },
            { key: 'collections.kind', label: 'Kind' },
          ],
          fields: [
            { name: 'collection_id', label: 'Add to collection', required: true, width: 210,
              lookup: { table: 'collections', pk: 'collection_id', label: 'name' } },
          ],
        }} />
        <Children parentId={row.product_id} cfg={{
          table: 'stock_moves', pk: 'move_id', parentKey: 'product_id',
          title: 'Availability log', order: 'created_at',
          columns: [
            { key: 'created_at', label: 'When', render: (r) => new Date(r.created_at).toLocaleDateString('en-GB') },
            { key: 'reason', label: 'Reason' },
            { key: 'change', label: 'Change', num: true,
              render: (r) => <span style={{ color: r.change < 0 ? 'var(--neg)' : 'var(--pos)' }}>
                {r.change > 0 ? '+' : ''}{r.change}</span> },
            { key: 'note', label: 'Note' },
          ],
          fields: [
            { name: 'change', label: 'Change', type: 'number', required: true, width: 90 },
            { name: 'reason', label: 'Reason', width: 130,
              options: ['Received', 'Adjustment', 'Return', 'Damage', 'Sample'] },
            { name: 'note', label: 'Note', width: 150 },
          ],
        }} />
      </div>),
    search: ['public_product_name', 'internal_sku', 'colour', 'fabric', 'tags'],
    searchHint: 'Search name, SKU, colour, fabric…',
    filter: { col: 'availability', values: ['In stock', 'Limited', 'Reserved', 'Unavailable'] },
    emptyTitle: 'No products here', emptyHint: 'Add your first piece, or clear the filter.',
    kpis: (r) => [
      { label: 'Live', value: r.filter((p) => p.status === 'Published').length },
      { label: 'Available', value: r.filter((p) => p.availability === 'In stock').length,
        delta: `${r.filter((p) => p.availability === 'Unavailable').length} unavailable` },
      { label: 'Average contribution',
        value: (() => {
          const live = r.filter((p) => p.retail_price && p.cost_price != null);
          if (!live.length) return '—';
          const pctv = live.reduce((s, p) => s + (p.retail_price - p.cost_price) / p.retail_price, 0) / live.length;
          return `${Math.round(pctv * 100)}%`;
        })(), delta: 'what you keep per piece' },
      { label: 'Brands', value: new Set(r.map((p) => p.brand_id).filter(Boolean)).size },
    ],
    columns: [
      { key: 'product_images', label: '', render: (r) => {
        const img = (r.product_images || []).find((i) => i.is_primary) || (r.product_images || [])[0];
        return <div className="thumb">{img ? <img src={img.public_url} alt="" /> : (r.colour || '—').slice(0, 3)}</div>;
      } },
      { key: 'public_product_name', label: 'Product' },
      { key: 'internal_sku', label: 'SKU' },
      { key: 'brands.name', label: 'Brand' },
      { key: 'cost_price', label: 'You owe', fmt: 'money', num: true },
      { key: 'retail_price', label: 'You charge', fmt: 'money', num: true },
      { key: 'contribution', label: 'Contribution', num: true,
        render: (r) => {
          if (!r.retail_price || r.cost_price == null) return <span className="faint">—</span>;
          const c = Number(r.retail_price) - Number(r.cost_price);
          const pctv = Math.round((c / Number(r.retail_price)) * 100);
          return <span style={{ color: c > 0 ? 'var(--pos)' : 'var(--neg)' }}>
            {money(c)} <span className="faint">({pctv}%)</span></span>;
        } },
      { key: 'availability', label: 'Availability', fmt: 'badge' },
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
      { name: 'brand_id', label: 'Brand partner',
        lookup: { table: 'brands', pk: 'brand_id', label: 'name' },
        hint: 'Whose piece this is. They are paid only when it sells.' },
      { name: 'cost_price', label: 'Agreed cost to you', type: 'number', step: '0.01',
        hint: 'What the partner is owed per piece. Payable on sale, not up front.' },
      { name: 'retail_price', label: 'Retail price', type: 'number', step: '0.01' },
      { name: 'wholesale_price', label: 'Wholesale price', type: 'number', step: '0.01' },
      { name: 'currency', label: 'Currency', options: ['INR', 'USD', 'GBP', 'EUR'] },
      { name: 'availability', label: 'Availability',
        options: ['In stock', 'Limited', 'Reserved', 'Unavailable'],
        hint: 'What the partner says. You hold none of it yourself.' },
      { name: 'stock_qty', label: 'Units the partner holds', type: 'number',
        hint: 'Advisory only. Nothing is deducted when you sell.' },
      { name: 'moq', label: 'Minimum order quantity', type: 'number' },
      { name: 'status', label: 'Status', options: ['Draft', 'Review', 'Published', 'Archived'],
        hint: 'Published pieces can appear in showrooms and on the storefront.' },
    ],
  }} />;
}
