import Link from 'next/link';
import { supabaseServer } from '@/lib/supabase';
import { upsertRow, quickUpdate } from '@/lib/actions';
import { Page, Badge, when, Empty, money } from '@/components/ui';
import Flash from '@/components/Flash';
export const dynamic = 'force-dynamic';

const STAGES = ['Photos', 'Imagery', 'Copy', 'Pricing', 'Review', 'Published'];
const STATUS = ['Queued', 'Running', 'Blocked', 'Done', 'Failed'];
const WHAT = {
  Photos: 'Phone photos collected and sorted for the piece.',
  Imagery: 'Clean cut-outs and model shots generated from the raw photos.',
  Copy: 'Product name, description and highlights drafted in the brand voice.',
  Pricing: 'Cost, retail and wholesale prices set, with margin checked.',
  Review: 'A person checks the listing before it goes anywhere public.',
  Published: 'Listing pushed to the storefront and the social kit prepared.',
};

export default async function Launch({ searchParams }) {
  const sb = supabaseServer();
  const [jobs, products, integrations] = await Promise.all([
    sb.from('launch_jobs').select('*,products(product_id,public_product_name,internal_sku,status,retail_price)')
      .order('created_at', { ascending: false }).then((r) => r.data || []),
    sb.from('products').select('product_id,public_product_name,status').order('public_product_name').then((r) => r.data || []),
    sb.from('integrations').select('provider,status').in('provider', ['Image generation', 'OpenAI', 'Wix', 'Shopify']).then((r) => r.data || []),
  ]);
  const start = upsertRow.bind(null, 'launch_jobs', 'job_id', '/launch');
  const advance = quickUpdate.bind(null, 'launch_jobs', 'job_id', '/launch');
  const aiReady = integrations.some((i) => i.provider === 'Image generation' && i.status === 'Connected');
  const storeReady = integrations.some((i) => ['Wix', 'Shopify'].includes(i.provider) && i.status === 'Connected');

  return (
    <Page title="Product launch desk" sub="Take a piece from phone photos to a live listing."
      actions={<Link className="btn" href="/products/new">New product</Link>}>
      <Flash params={searchParams} />

      {(!aiReady || !storeReady) && (
        <div className="note" style={{ marginBottom: 16 }}>
          {!aiReady && <>Image generation is not connected, so model shots and clean cut-outs run by hand for now. </>}
          {!storeReady && <>No storefront is connected, so publishing records the step without pushing to the website. </>}
          <Link className="link" href="/integrations">Connect them →</Link>
        </div>
      )}

      <div className="grid g3" style={{ marginBottom: 18 }}>
        {STAGES.slice(0, 6).map((s) => (
          <div className="card" key={s} style={{ padding: 14 }}>
            <div className="row"><strong className="small">{s}</strong><span className="spacer" />
              <span className="badge">{jobs.filter((j) => j.stage === s && j.status !== 'Done').length}</span></div>
            <div className="small muted" style={{ marginTop: 4 }}>{WHAT[s]}</div>
          </div>))}
      </div>

      <div className="grid" style={{ gridTemplateColumns: '1fr 330px' }}>
        <div className="card">
          <div className="card-head"><h3>Launches in progress</h3></div>
          {jobs.length === 0 ? <Empty title="Nothing in the pipeline" hint="Start a launch for a product on the right." /> : (
            <div className="t-wrap"><table className="table">
              <thead><tr><th>Product</th><th>Stage</th><th>Note</th><th>Started</th><th>Move on</th></tr></thead>
              <tbody>{jobs.map((j) => (
                <tr key={j.job_id}>
                  <td><Link className="link" href={`/products/${j.products?.product_id}`}>{j.products?.public_product_name || '—'}</Link>
                    <div className="small faint mono">{j.products?.internal_sku}</div></td>
                  <td><Badge>{j.stage}</Badge><div style={{ marginTop: 4 }}><Badge>{j.status}</Badge></div></td>
                  <td className="small">{j.message || '—'}</td>
                  <td className="small faint">{when(j.created_at)}</td>
                  <td>
                    <form action={advance} className="row" style={{ gap: 5 }}>
                      <input type="hidden" name="_id" value={j.job_id} />
                      <select name="stage" defaultValue={j.stage} style={{ padding: '4px 6px', fontSize: 12, borderRadius: 6, border: '1px solid var(--line)' }}>
                        {STAGES.map((s) => <option key={s}>{s}</option>)}</select>
                      <select name="status" defaultValue={j.status} style={{ padding: '4px 6px', fontSize: 12, borderRadius: 6, border: '1px solid var(--line)' }}>
                        {STATUS.map((s) => <option key={s}>{s}</option>)}</select>
                      <button className="btn btn-sm">Save</button>
                    </form>
                  </td>
                </tr>))}</tbody></table></div>
          )}
        </div>

        <form action={start} className="card">
          <div className="card-head"><h3>Start a launch</h3></div>
          <div className="card-body">
            <div className="field"><label>Product</label>
              <select name="product_id" required defaultValue="">
                <option value="">Choose a product…</option>
                {products.map((p) => <option key={p.product_id} value={p.product_id}>{p.public_product_name}</option>)}
              </select>
              <span className="hint">Add the product first if it is not in the list.</span></div>
            <div className="field"><label>Starting stage</label>
              <select name="stage" defaultValue="Photos">{STAGES.map((s) => <option key={s}>{s}</option>)}</select></div>
            <div className="field"><label>Status</label>
              <select name="status" defaultValue="Queued">{STATUS.map((s) => <option key={s}>{s}</option>)}</select></div>
            <div className="field"><label>Note</label>
              <textarea name="message" placeholder="What is waiting to happen, and on whom." /></div>
          </div>
          <div className="card-foot"><button className="btn btn-primary">Start launch</button></div>
        </form>
      </div>
    </Page>
  );
}
