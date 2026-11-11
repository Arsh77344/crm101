'use client';
import { useRef, useState } from 'react';
import Link from 'next/link';
import { useQuery, insertRow, updateRow } from '@/lib/db';
import { uploadImage, deleteImage } from '@/lib/upload';
import { Page, Badge, Empty, Loading, ErrorNote, Stat, when, money } from '@/components/ui';

const STEPS = ['Photos', 'The piece', 'Imagery', 'Words & price', 'Review'];
const STAGES = ['Photos', 'Imagery', 'Copy', 'Pricing', 'Review', 'Published'];
const STATUS = ['Queued', 'Running', 'Blocked', 'Done', 'Failed'];

const IMAGERY = [
  ['None', 'Keep my photos', 'Use the shots as they are. Nothing generated.'],
  ['Clean', 'Clean cut-outs', 'Same garment, background removed, even lighting.'],
  ['Mannequin', 'AI mannequin', 'Draped on an invisible mannequin. No person.'],
  ['Model', 'AI model', 'Worn by a generated model. Slowest and most expensive.'],
];
const PROVIDERS = [
  ['openai', 'OpenAI (GPT)', 'Strong at copy. Image editing through its image model.'],
  ['gemini', 'Google (Gemini)', 'Strong at reading photos and at grounded web search for prices.'],
];

export default function Launch() {
  const [err, setErr] = useState('');
  const [step, setStep] = useState(0);
  const [shots, setShots] = useState([]);
  const [uploading, setUploading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [done, setDone] = useState(null);
  const fileRef = useRef(null);

  const [piece, setPiece] = useState({
    public_product_name: '', internal_sku: '', category: 'Banarasi Saree',
    fabric: '', colour: '', weave_or_motif: '', stock_qty: 1, moq: 1,
    cost_price: '', retail_price: '', wholesale_price: '',
  });
  const [imagery, setImagery] = useState({ mode: 'Clean', count: 3, provider: 'openai' });
  const [words, setWords] = useState({ description: '', tags: '', brief: '' });

  const q = useQuery(async (c) => {
    const [jobs, integrations] = await Promise.all([
      c.from('launch_jobs').select('*,products(product_id,public_product_name,internal_sku)')
        .order('created_at', { ascending: false }).limit(25),
      c.from('integrations').select('provider,status'),
    ]);
    if (jobs.error) throw jobs.error;
    return { jobs: jobs.data || [], integrations: integrations.data || [] };
  }, []);

  const ints = q.data?.integrations || [];
  const connected = (name) => ints.some((i) => i.provider === name && i.status === 'Connected');
  const aiReady = connected('OpenAI') || connected('Image generation');
  const storeReady = connected('Wix') || connected('Shopify');

  async function addFiles(e) {
    const files = Array.from(e.target.files || []);
    if (!files.length) return;
    setUploading(true); setErr('');
    try {
      for (const f of files) {
        const up = await uploadImage(f, 'inbox');
        setShots((s) => [...s, up]);
      }
    } catch (e2) { setErr(e2.message || String(e2)); }
    setUploading(false);
    if (fileRef.current) fileRef.current.value = '';
  }

  async function dropShot(path) {
    try { await deleteImage(path); setShots((s) => s.filter((x) => x.path !== path)); }
    catch (e2) { setErr(e2.message || String(e2)); }
  }

  async function finish() {
    setSaving(true); setErr('');
    try {
      const product = await insertRow('products', {
        ...piece,
        description: words.description || null,
        tags: words.tags || null,
        status: 'Review',
      });
      if (shots.length) {
        const rows = shots.map((s, i) => ({
          product_id: product.product_id, image_role: i === 0 ? 'Primary' : 'Gallery',
          original_filename: s.name, storage_path: s.path, public_url: s.url,
          is_primary: i === 0, bytes: s.bytes,
        }));
        const { error } = await (await import('@/lib/db')).sb().from('product_images').insert(rows);
        if (error) throw error;
      }
      const note = [
        `${shots.length} photo${shots.length === 1 ? '' : 's'} uploaded.`,
        imagery.mode === 'None' ? 'Using the photos as shot.'
          : `${imagery.count} × ${imagery.mode.toLowerCase()} images requested via ${imagery.provider === 'openai' ? 'OpenAI' : 'Gemini'}.`,
        words.brief ? `Brief: ${words.brief}` : '',
      ].filter(Boolean).join(' ');
      await insertRow('launch_jobs', {
        product_id: product.product_id,
        stage: imagery.mode === 'None' ? 'Copy' : 'Imagery',
        status: aiReady ? 'Queued' : 'Blocked',
        message: aiReady ? note : `${note} Waiting on an AI key before anything can be generated.`,
      });
      setDone(product);
      setShots([]); setStep(0);
      setPiece({ public_product_name: '', internal_sku: '', category: 'Banarasi Saree', fabric: '', colour: '',
        weave_or_motif: '', stock_qty: 1, moq: 1, cost_price: '', retail_price: '', wholesale_price: '' });
      setWords({ description: '', tags: '', brief: '' });
      q.reload();
    } catch (e2) { setErr(e2.message || String(e2)); }
    setSaving(false);
  }

  const canNext = [
    shots.length > 0,
    piece.public_product_name.trim().length > 1,
    true,
    true,
    true,
  ][step];

  return (
    <Page title="Product launch" sub="Photos in one end, a reviewed listing out the other."
      actions={<Link className="btn" href="/products">All products</Link>}>
      <ErrorNote error={q.error || err} />

      {done && (
        <div className="ok" style={{ marginBottom: 14 }}>
          Created <strong>{done.public_product_name}</strong> as a draft in Review.{' '}
          <Link className="link" href={`/products?id=${done.product_id}`}>Open it</Link> ·{' '}
          <button className="btn btn-sm" style={{ marginLeft: 6 }} onClick={() => setDone(null)}>Launch another</button>
        </div>)}

      <div className="steps">
        {STEPS.map((s, i) => (
          <button key={s} className={`step ${i === step ? 'on' : ''} ${i < step ? 'done' : ''}`}
            onClick={() => i <= step && setStep(i)} style={{ textAlign: 'left', cursor: i <= step ? 'pointer' : 'default' }}>
            <span className="n">Step {i + 1}</span>{s}
          </button>))}
      </div>

      <div className="grid" style={{ gridTemplateColumns: '1fr 320px' }}>
        <div className="card">
          {step === 0 && (
            <>
              <div className="card-head"><h3>Upload the photos</h3>
                <span className="small faint">{shots.length} added</span></div>
              <div className="card-body">
                <div className="drop" onClick={() => fileRef.current?.click()}>
                  <div style={{ fontWeight: 600, marginBottom: 3 }}>
                    {uploading ? 'Uploading…' : 'Choose photos from your phone or computer'}</div>
                  <div className="small faint">JPEG, PNG, WebP or HEIC. The first one becomes the main image.</div>
                </div>
                <input ref={fileRef} type="file" accept="image/*" multiple onChange={addFiles} style={{ display: 'none' }} />
                {shots.length > 0 && (
                  <div className="shots" style={{ marginTop: 14 }}>
                    {shots.map((s) => (
                      <div className="shot" key={s.path}>
                        <img src={s.url} alt={s.name} />
                        <button onClick={() => dropShot(s.path)} title="Remove">×</button>
                      </div>))}
                  </div>)}
              </div>
            </>
          )}

          {step === 1 && (
            <>
              <div className="card-head"><h3>What is the piece?</h3></div>
              <div className="card-body"><div className="form-grid">
                <div className="field full"><label>Product name</label>
                  <input value={piece.public_product_name} placeholder="Mashru Silk Banarasi — Deep Magenta"
                    onChange={(e) => setPiece({ ...piece, public_product_name: e.target.value })} /></div>
                <div className="field"><label>SKU</label>
                  <input value={piece.internal_sku} placeholder="USY-MS-012"
                    onChange={(e) => setPiece({ ...piece, internal_sku: e.target.value })} /></div>
                <div className="field"><label>Category</label>
                  <input value={piece.category} onChange={(e) => setPiece({ ...piece, category: e.target.value })} /></div>
                <div className="field"><label>Fabric</label>
                  <input value={piece.fabric} placeholder="Mashru Satin Silk"
                    onChange={(e) => setPiece({ ...piece, fabric: e.target.value })} /></div>
                <div className="field"><label>Colour</label>
                  <input value={piece.colour} placeholder="Deep magenta"
                    onChange={(e) => setPiece({ ...piece, colour: e.target.value })} /></div>
                <div className="field"><label>Weave or motif</label>
                  <input value={piece.weave_or_motif} placeholder="Jangla floral"
                    onChange={(e) => setPiece({ ...piece, weave_or_motif: e.target.value })} /></div>
                <div className="field"><label>Cost price</label>
                  <input type="number" value={piece.cost_price}
                    onChange={(e) => setPiece({ ...piece, cost_price: e.target.value })} />
                  <span className="hint">Used to check the margin on whatever price we land on.</span></div>
                <div className="field"><label>Stock</label>
                  <input type="number" value={piece.stock_qty}
                    onChange={(e) => setPiece({ ...piece, stock_qty: e.target.value })} /></div>
                <div className="field"><label>Minimum order quantity</label>
                  <input type="number" value={piece.moq}
                    onChange={(e) => setPiece({ ...piece, moq: e.target.value })} /></div>
              </div></div>
            </>
          )}

          {step === 2 && (
            <>
              <div className="card-head"><h3>What images do you want made?</h3></div>
              <div className="card-body">
                <div className="grid g2" style={{ marginBottom: 14 }}>
                  {IMAGERY.map(([key, title, blurb]) => (
                    <button key={key} onClick={() => setImagery({ ...imagery, mode: key })}
                      className="card" style={{
                        padding: 12, textAlign: 'left', cursor: 'pointer',
                        borderColor: imagery.mode === key ? 'var(--accent)' : 'var(--line)',
                        background: imagery.mode === key ? 'var(--accent-wash)' : 'var(--panel)',
                      }}>
                      <div style={{ fontWeight: 600, fontSize: 13 }}>{title}</div>
                      <div className="small muted" style={{ marginTop: 2 }}>{blurb}</div>
                    </button>))}
                </div>

                {imagery.mode !== 'None' && (
                  <div className="form-grid">
                    <div className="field"><label>How many images</label>
                      <select value={imagery.count} onChange={(e) => setImagery({ ...imagery, count: Number(e.target.value) })}>
                        {[1, 2, 3, 4, 6, 8].map((n) => <option key={n} value={n}>{n}</option>)}
                      </select>
                      <span className="hint">More images cost more and take longer.</span></div>
                    <div className="field"><label>Which model does the work</label>
                      <select value={imagery.provider} onChange={(e) => setImagery({ ...imagery, provider: e.target.value })}>
                        {PROVIDERS.map(([k, label]) => <option key={k} value={k}>{label}</option>)}
                      </select>
                      <span className="hint">{PROVIDERS.find((p) => p[0] === imagery.provider)?.[2]}</span></div>
                  </div>)}

                {!aiReady && (
                  <div className="note" style={{ marginTop: 6 }}>
                    No AI key is connected yet, so your choice is recorded and the job waits.
                    Add a key on <Link className="link" href="/integrations">Integrations</Link> and it runs.
                  </div>)}
              </div>
            </>
          )}

          {step === 3 && (
            <>
              <div className="card-head"><h3>Words and price</h3></div>
              <div className="card-body">
                <div className="field"><label>Anything the description must say</label>
                  <textarea value={words.brief} placeholder="Forty days on the loom. Azo-free dyes. Blouse piece included."
                    onChange={(e) => setWords({ ...words, brief: e.target.value })} />
                  <span className="hint">Facts only. The write-up gets built from these plus the photos.</span></div>

                <div className="row" style={{ marginBottom: 10 }}>
                  <button className="btn btn-sm" disabled={!aiReady} title={aiReady ? '' : 'Needs an AI key'}>
                    Write the description
                  </button>
                  <button className="btn btn-sm" disabled={!aiReady} title={aiReady ? '' : 'Needs an AI key'}>
                    Find comparable prices
                  </button>
                  {!aiReady && <span className="small faint">Both need a key on Integrations.</span>}
                </div>

                <div className="field"><label>Description</label>
                  <textarea value={words.description} style={{ minHeight: 120 }}
                    placeholder="Write it yourself for now, or let the model draft it once a key is in."
                    onChange={(e) => setWords({ ...words, description: e.target.value })} /></div>
                <div className="field"><label>Tags</label>
                  <input value={words.tags} placeholder="wedding, silk, handloom"
                    onChange={(e) => setWords({ ...words, tags: e.target.value })} /></div>

                <div className="grid g3">
                  <div className="field"><label>Retail price</label>
                    <input type="number" value={piece.retail_price}
                      onChange={(e) => setPiece({ ...piece, retail_price: e.target.value })} /></div>
                  <div className="field"><label>Wholesale price</label>
                    <input type="number" value={piece.wholesale_price}
                      onChange={(e) => setPiece({ ...piece, wholesale_price: e.target.value })} /></div>
                  <div className="field"><label>Margin at retail</label>
                    <input disabled value={piece.retail_price && piece.cost_price
                      ? `${Math.round(((piece.retail_price - piece.cost_price) / piece.retail_price) * 100)}%` : '—'} /></div>
                </div>
              </div>
            </>
          )}

          {step === 4 && (
            <>
              <div className="card-head"><h3>Review before it is created</h3></div>
              <div className="card-body">
                <div className="row wrap" style={{ alignItems: 'flex-start', gap: 16 }}>
                  <div className="shots" style={{ width: 230 }}>
                    {shots.slice(0, 4).map((s) => (
                      <div className="shot" key={s.path}><img src={s.url} alt="" /></div>))}
                  </div>
                  <div style={{ flex: 1, minWidth: 220 }}>
                    <div style={{ fontWeight: 600, fontSize: 15 }}>{piece.public_product_name || 'Untitled piece'}</div>
                    <div className="small muted">
                      {[piece.fabric, piece.colour, piece.weave_or_motif].filter(Boolean).join(' · ') || 'No detail given'}
                    </div>
                    <div className="small" style={{ marginTop: 8 }}>{words.description || 'No description yet.'}</div>
                    <div className="row wrap" style={{ marginTop: 10, gap: 6 }}>
                      <span className="badge">{shots.length} photos</span>
                      <span className="badge">{imagery.mode === 'None' ? 'No generated imagery'
                        : `${imagery.count} × ${imagery.mode}`}</span>
                      <span className="badge">Retail {money(piece.retail_price)}</span>
                      <span className="badge">Stock {piece.stock_qty}</span>
                    </div>
                  </div>
                </div>
                <div className="note plain small" style={{ marginTop: 14 }}>
                  It is created with status <strong>Review</strong>, so nothing reaches the storefront until you publish it.
                  {!storeReady && ' No storefront is connected yet in any case.'}
                </div>
              </div>
            </>
          )}

          <div className="card-foot row">
            {step > 0 && <button className="btn btn-sm" onClick={() => setStep(step - 1)}>Back</button>}
            <span className="spacer" />
            {step < 4
              ? <button className="btn btn-primary btn-sm" disabled={!canNext} onClick={() => setStep(step + 1)}>Continue</button>
              : <button className="btn btn-primary btn-sm" disabled={saving} onClick={finish}>
                  {saving ? 'Creating…' : 'Create the product'}</button>}
          </div>
        </div>

        <div className="stack">
          <div className="card">
            <div className="card-head"><h3>What happens next</h3></div>
            <div className="card-body stack" style={{ gap: 9 }}>
              {[
                ['Photos', `${shots.length} uploaded`],
                ['Imagery', imagery.mode === 'None' ? 'Skipped' : `${imagery.count} × ${imagery.mode}`],
                ['Copy', words.description ? 'Written by you' : aiReady ? 'Drafted by the model' : 'Waiting on a key'],
                ['Pricing', piece.retail_price ? `Set at ${money(piece.retail_price)}` : 'Not set'],
                ['Review', 'You approve before anything is published'],
              ].map(([k, v]) => (
                <div className="row small" key={k}>
                  <strong style={{ width: 66 }}>{k}</strong>
                  <span className="muted">{v}</span>
                </div>))}
            </div>
          </div>

          <div className="card">
            <div className="card-head"><h3>In progress</h3>
              <span className="small faint">{(q.data?.jobs || []).filter((j) => j.status !== 'Done').length}</span></div>
            {q.loading ? <Loading /> : (q.data?.jobs || []).length === 0
              ? <Empty title="Nothing running" hint="Launches you start appear here." />
              : (
                <div className="card-body stack" style={{ gap: 11 }}>
                  {q.data.jobs.slice(0, 6).map((j) => (
                    <div key={j.job_id}>
                      <div className="row">
                        <Link className="link small" href={`/products?id=${j.products?.product_id}`}>
                          {j.products?.public_product_name || 'Untitled'}</Link>
                        <span className="spacer" /><Badge>{j.status}</Badge>
                      </div>
                      <div className="small faint">{j.stage} · {when(j.created_at)}</div>
                      {j.message && <div className="small muted" style={{ marginTop: 2 }}>{j.message}</div>}
                      <div className="row" style={{ gap: 5, marginTop: 5 }}>
                        <select value={j.stage} onChange={(e) => updateRow('launch_jobs', 'job_id', j.job_id,
                          { stage: e.target.value }).then(q.reload)}
                          style={{ padding: '3px 6px', fontSize: 11.5, borderRadius: 5, border: '1px solid var(--line)' }}>
                          {STAGES.map((s) => <option key={s}>{s}</option>)}</select>
                        <select value={j.status} onChange={(e) => updateRow('launch_jobs', 'job_id', j.job_id,
                          { status: e.target.value }).then(q.reload)}
                          style={{ padding: '3px 6px', fontSize: 11.5, borderRadius: 5, border: '1px solid var(--line)' }}>
                          {STATUS.map((s) => <option key={s}>{s}</option>)}</select>
                      </div>
                    </div>))}
                </div>)}
          </div>
        </div>
      </div>
    </Page>
  );
}
