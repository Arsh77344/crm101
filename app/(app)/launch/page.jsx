'use client';
import { useState } from 'react';
import Link from 'next/link';
import { useQuery, insertRow, updateRow, formValues } from '@/lib/db';
import { Page, Badge, Empty, Loading, ErrorNote, when } from '@/components/ui';

const STAGES = ['Photos', 'Imagery', 'Copy', 'Pricing', 'Review', 'Published'];
const STATUS = ['Queued', 'Running', 'Blocked', 'Done', 'Failed'];
const WHAT = {
  Photos: 'Phone photos collected and sorted for the piece.',
  Imagery: 'Clean cut-outs and model shots made from the raw photos.',
  Copy: 'Name, description and highlights drafted in the brand voice.',
  Pricing: 'Cost, retail and wholesale set, with margin checked.',
  Review: 'A person checks the listing before anything goes public.',
  Published: 'Listing pushed to the storefront and the social kit prepared.',
};

export default function Launch() {
  const [err, setErr] = useState('');
  const q = useQuery(async (c) => {
    const [jobs, products, integrations] = await Promise.all([
      c.from('launch_jobs').select('*,products(product_id,public_product_name,internal_sku)').order('created_at', { ascending: false }),
      c.from('products').select('product_id,public_product_name').order('public_product_name'),
      c.from('integrations').select('provider,status'),
    ]);
    if (jobs.error) throw jobs.error;
    return { jobs: jobs.data || [], products: products.data || [], integrations: integrations.data || [] };
  }, []);

  async function start(e) {
    e.preventDefault();
    try { await insertRow('launch_jobs', formValues(e.target)); e.target.reset(); q.reload(); }
    catch (e2) { setErr(e2.message); }
  }
  async function set(id, patch) {
    try { await updateRow('launch_jobs', 'job_id', id, patch); q.reload(); }
    catch (e2) { setErr(e2.message); }
  }

  if (q.loading) return <Page title="Product launch desk"><Loading /></Page>;
  const jobs = q.data?.jobs || [];
  const ints = q.data?.integrations || [];
  const aiReady = ints.some((i) => i.provider === 'Image generation' && i.status === 'Connected');
  const storeReady = ints.some((i) => ['Wix', 'Shopify'].includes(i.provider) && i.status === 'Connected');

  return (
    <Page title="Product launch desk" sub="Take a piece from phone photos to a live listing."
      actions={<Link className="btn" href="/products?id=new">New product</Link>}>
      <ErrorNote error={q.error || err} />
      {(!aiReady || !storeReady) && (
        <div className="note" style={{ marginBottom: 16 }}>
          {!aiReady && <>Image generation is not connected, so cut-outs and model shots are done by hand for now. </>}
          {!storeReady && <>No storefront is connected, so publishing records the step without pushing to the website. </>}
          <Link className="link" href="/integrations">Connect them →</Link>
        </div>
      )}

      <div className="kpi-row" style={{ marginBottom: 18 }}>
        {STAGES.map((s) => (
          <div className="card" key={s} style={{ padding: 14 }}>
            <div className="row"><strong className="small">{s}</strong><span className="spacer" />
              <span className="badge">{jobs.filter((j) => j.stage === s && j.status !== 'Done').length}</span></div>
            <div className="small muted" style={{ marginTop: 4 }}>{WHAT[s]}</div>
          </div>))}
      </div>

      <div className="grid" style={{ gridTemplateColumns: '1fr 330px' }}>
        <div className="card">
          <div className="card-head"><h3>Launches in progress</h3></div>
          {jobs.length === 0 ? <Empty title="Nothing in the pipeline" hint="Start a launch on the right." /> : (
            <div className="t-wrap"><table className="table">
              <thead><tr><th>Product</th><th>Stage</th><th>Status</th><th>Note</th><th>Started</th></tr></thead>
              <tbody>{jobs.map((j) => (
                <tr key={j.job_id}>
                  <td>{j.products?.public_product_name || '—'}
                    <div className="small faint mono">{j.products?.internal_sku}</div></td>
                  <td><select value={j.stage} onChange={(e) => set(j.job_id, { stage: e.target.value })}
                    style={{ padding: '4px 6px', fontSize: 12, borderRadius: 6, border: '1px solid var(--line)' }}>
                    {STAGES.map((s) => <option key={s}>{s}</option>)}</select></td>
                  <td><select value={j.status} onChange={(e) => set(j.job_id, { status: e.target.value })}
                    style={{ padding: '4px 6px', fontSize: 12, borderRadius: 6, border: '1px solid var(--line)' }}>
                    {STATUS.map((s) => <option key={s}>{s}</option>)}</select></td>
                  <td className="small">{j.message || '—'}</td>
                  <td className="small faint">{when(j.created_at)}</td>
                </tr>))}</tbody></table></div>
          )}
        </div>

        <form className="card" onSubmit={start}>
          <div className="card-head"><h3>Start a launch</h3></div>
          <div className="card-body">
            <div className="field"><label>Product</label>
              <select name="product_id" required defaultValue=""><option value="">Choose a product…</option>
                {(q.data?.products || []).map((p) => <option key={p.product_id} value={p.product_id}>{p.public_product_name}</option>)}
              </select><span className="hint">Add the product first if it is not listed.</span></div>
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
