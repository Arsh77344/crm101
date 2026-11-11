// Column definitions shared by every place a spreadsheet of products is read
// or written: the Products page importer and the bulk path in Product launch.
// The downloadable template is generated from this, so the template and the
// importer can never drift apart.
export const PRODUCT_SHEET = [
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
];
