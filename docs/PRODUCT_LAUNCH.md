# Product launch workspace

Open **Sell → Launch a product** (`/launch`). This workspace turns phone photos into a reviewed product listing and a matching social kit.

## Owner workflow

1. Use **Connect AI** (`/launch/ai`) once to save a private server-side API key and check model access. Then upload up to 20 JPG, PNG, WebP or HEIC photos (20 MB each, 80 MB per batch). Add an optional name and a few known facts. Choose product-only, mannequin or AI-model photography. **Generate product preview** runs listing copy, studio edits and the selected shoot in sequence. Without a key, **Save product draft** saves and resizes locally and clearly labels AI as disconnected. Either path immediately creates one linked draft in **Products**, with its photos. Initial edits and preparation results update that same draft.
2. Review suggested copy, search title, search description and image alt text. Confirm product facts rather than assuming AI can identify material or certification. Enter colours and sizes separated by commas, then confirm available combinations, prices and opening stock. Sizes share photos with their colour.
3. Use **Check market prices** for current, linked comparable listings. At least three sourced listings in the same currency are required for a suggestion. The suggested price is the larger of the comparison median and the cost/margin floor. Exclude poor comparisons yourself. Research expires after seven days or a change to the product facts or market. Prices remain the owner's decision.
4. Review photos. Existing uploads have a **Generate with AI** action to prepare copy and photography together. Progress messages identify the current step, and completed copy and photos appear while later images are still processing. **Prepare all photos** runs photography alone. Both preserve completed edits if a later step fails. Individual edits are also available. Original photos remain available, and **Keep both in the listing** lets an original accompany an edit. Check colour, construction and image descriptions before approving.
5. Review and approve the listing. Approval confirms the existing product's variant records, selected images and opening inventory. Before approval, stock is not released for sale. Changes to an already approved product stay in the launch draft until reapproval, protecting the reviewed catalogue snapshot. Download a portable listing kit, save a hidden store draft, or explicitly publish to a connected store.
6. Create the social kit from the approved product. Review/edit the Instagram, Facebook and WhatsApp captions, approve them, and download the feed, square and story images. A supplied live product link adds a QR code. Social posting is a manual handoff; the app does not silently post to accounts.

Brand voice, audience, prohibited claims, image style and selling market can be saved once on the launch homepage. Existing drafts keep their brand snapshot.

## Connections and honest limits

- Local image resizing, draft editing, variant handling, review and downloads work without AI. Install `app/requirements-team.txt` for imaging support. Original uploads remain in the private product inbox; published JPEG copies have metadata removed.
- Writing, visual analysis, web price research and generated photography use the existing OpenAI connection, model router and usage controls. They require an account with the relevant capabilities and available API usage. Connection checking verifies model visibility; it does not prove image-generation access, billing or output quality. The first real generation must also succeed. API key setup is restricted to settings administrators, and saved keys are never included in page output, draft documents or job payloads. No live model call was used during automated acceptance tests.
- Shopify uses Admin GraphQL **2026-10**: `productSet` creates a hidden product with variants, images, alt text and inventory. Publication waits for image processing, activates the product, then uses `publishablePublish` on the selected channel. The store's currency must match. The connection needs product, inventory, location, file and publication access as applicable.
- Wix uses **Stores Catalog V3**, `POST /stores/v3/products-with-inventory`, followed by a revision-checked visibility update when requested. Colour choices link to their photos. Inventory failures leave the product hidden. The owner confirms the store currency; older Wix catalog versions are not supported by this adapter.
- Public HTTPS media hosting is required for store imports. Configure the existing media settings/CDN. Local-only photos cannot be fetched by Shopify or Wix.
- The team-test launcher keeps real provider writes disabled unless an administrator explicitly sets `CRM_ALLOW_EXTERNAL_WRITES=1`. Building this feature does not enable that switch.
- Other platforms receive the ZIP listing kit with `product.json`, images/alt text and an HTML catalogue. An arbitrary custom server needs its own adapter; this feature does not pretend to support every API.
- Generated imagery can alter detail or fit. Nothing guarantees exact relighting, hidden angles or colour fidelity. Original comparison and owner review are required.
- This is a product preparation and initial publication flow. Store revisions are not silently overwritten after local edits. A recorded delivery prevents another product being created for the same store. An ambiguous request outcome must be reconciled in the store before another create attempt.
- Opening stock is copied into the existing canonical inventory. Later sales must not be overwritten by old listing quantities. Variant records describe the launch; full variant-aware order fulfilment and continuous two-way inventory synchronisation are separate work.

## Persistence and recovery

Drafts, immutable saved versions, jobs, variant records and delivery receipts are additive tables. Editing invalidates listing approval. Social assets carry a fingerprint of the product so outdated prices or photos cannot be exported as a newly approved kit. Archived products cannot be published through this flow.

Existing uploads made before immediate catalogue linking are repaired at startup, without requiring another upload. Saving a launch draft and its initial product record is atomic. The draft page distinguishes saved local records from AI preparation and website delivery, including missing connections.

Local jobs run in the existing single app process. Interrupted work becomes a visible failure and is not automatically replayed. Production jobs use the separate durable worker, with one attempt and a longer lease for image batches. Start the existing production worker service alongside the web app. An expired launch lease requires review; an uncertain provider creation is never automatically retried.

## Validation

Run the isolated suite from the project root:

```sh
.venv/bin/python -m unittest discover -s app -p test_launch_studio.py -v
```

The tests copy the sample database into a temporary directory and simulate external API responses. They cover combinations, approval invalidation, stock safety, stale edits, sourced pricing, image selection, exports, queue recovery and delivery idempotency. Live AI/store behaviour still requires a connected test account and a publicly reachable media host. PostgreSQL deployment and real Wix/Shopify publication are not claimed as validated by these local tests.

API references used for the adapters:

- [OpenAI image generation](https://developers.openai.com/api/docs/guides/image-generation)
- [OpenAI web search](https://developers.openai.com/api/docs/guides/tools-web-search)
- [Shopify productSet](https://shopify.dev/docs/api/admin-graphql/2026-10/mutations/productSet)
- [Shopify publishablePublish](https://shopify.dev/docs/api/admin-graphql/2026-10/mutations/publishablePublish)
- [Wix Create Product With Inventory](https://dev.wix.com/docs/api-reference/business-solutions/stores/catalog-v3/products-v3/create-product-with-inventory)
- [Wix Update Product With Inventory](https://dev.wix.com/docs/api-reference/business-solutions/stores/catalog-v3/products-v3/update-product-with-inventory)
