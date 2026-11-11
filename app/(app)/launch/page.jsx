'use client';
import { useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import { useQuery, insertRow, updateRow } from '@/lib/db';
import { uploadImage, deleteImage } from '@/lib/upload';
import { assist, checkKeys, PROVIDERS, NO_KEYS, SECRET_NAME,
  providerLabel, providerOption, providerHint, hasKey, anyKey, firstWithKey } from '@/lib/assist';
import { Page, Badge, Empty, Loading, ErrorNote, when, money } from '@/components/ui';
import Sheet from '@/components/Sheet';
import { PRODUCT_SHEET } from '@/lib/schemas';

const STEPS = ['Photos', 'The piece', 'Imagery', 'Words & price', 'Review'];
const STAGES = ['Photos', 'Imagery', 'Copy', 'Pricing', 'Review', 'Published'];
const STATUS = ['Queued', 'Running', 'Blocked', 'Done', 'Failed'];

const IMAGERY = [
  ['None', 'Keep my photos', 'Use the shots as they are. Nothing generated.'],
  ['Clean', 'Clean cut-outs', 'Same garment, background removed, even lighting.'],
  ['Mannequin', 'AI mannequin', 'Draped on an invisible mannequin. No person.'],
  ['Model', 'AI model', 'Worn by a generated model. Slowest and most expensive.'],
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
  const [words, setWords] = useState({ description: '', tags: '', brief: '', highlights: '' });
  const [keys, setKeys] = useState(null);
  const [thinking, setThinking] = useState('');
  const [research, setResearch] = useState(null);
  const [bulk, setBulk] = useState(false);
  const [made, setMade] = useState([]);
  const [unsure, setUnsure] = useState([]);

  useEffect(() => {
    checkKeys().then((k) => {
      setKeys(k);
      setImagery((im) => (k && !k[im.provider] ? { ...im, provider: firstWithKey(k, im.provider) } : im));
    }).catch(() => setKeys(NO_KEYS));
  }, []);

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
  const storeReady = connected('Wix') || connected('Shopify');
  const keyFor = (p) => hasKey(keys, p);
  const aiReady = anyKey(keys);

  // Pressing Continue past the photos starts the analysis straight away, so the
  // next screen is already filling in rather than waiting for a button press.
  function autoAnalyse() {
    if (thinking !== '' || !shots.length || words.description) return;
    if (!keys) return;
    if (!keys.brand_set) {
      setErr('Add the brand name and what it sells on Settings, then the photos can be read.');
      return;
    }
    if (!keyFor(imagery.provider)) {
      setErr(`No key for ${providerLabel(imagery.provider)}, so the photos were not read. `
        + `Pick a model that has a key on the Imagery step, or add that key.`);
      return;
    }
    runCopy();
  }

  async function runImages() {
    setThinking('images'); setErr('');
    try {
      const out = await assist({
        action: 'images', provider: 'gemini', mode: imagery.mode, count: imagery.count,
        piece, images: shots.map((s) => s.url),
      });
      setMade((m) => [...m, ...(out.images || []).map((i) => ({ ...i, use: true }))]);
      if ((out.failed || []).length) {
        setErr(`${out.images.length} came back, ${out.failed.length} failed: ${out.failed[0]}`);
      }
    } catch (e2) { setErr(e2.message || String(e2)); }
    setThinking('');
  }

  async function dropMade(path) {
    setMade((m) => m.filter((x) => x.path !== path));
    try { await deleteImage(path); } catch { /* the row is gone from the draft either way */ }
  }

  async function runCopy() {
    setThinking('copy'); setErr('');
    try {
      const out = await assist({
        action: 'copy', provider: imagery.provider,
        piece, brief: words.brief, images: shots.map((s) => s.url),
      });
      const r = out.result || {};
      setWords((w) => ({
        ...w,
        description: r.description || w.description,
        tags: (r.tags || []).join(', ') || w.tags,
        highlights: (r.highlights || []).join('\n'),
      }));
      const ob = r.observed || {};
      setPiece((pc) => ({
        ...pc,
        public_product_name: pc.public_product_name || r.title || '',
        category: pc.category || ob.category || '',
        fabric: pc.fabric || ob.fabric || '',
        colour: pc.colour || ob.colour || '',
        weave_or_motif: pc.weave_or_motif || ob.weave_or_motif || '',
      }));
      setUnsure(r.uncertain || []);
    } catch (e2) { setErr(e2.message || String(e2)); }
    setThinking('');
  }

  async function runPrice() {
    setThinking('price'); setErr('');
    try {
      const out = await assist({
        action: 'price', provider: imagery.provider, piece, brief: words.brief,
      });
      setResearch(out.result || null);
    } catch (e2) { setErr(e2.message || String(e2)); }
    setThinking('');
  }

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
      const kept = made.filter((m) => m.use);
      if (shots.length || kept.length) {
        const rows = [
          ...shots.map((s, i) => ({
            product_id: product.product_id, image_role: i === 0 ? 'Primary' : 'Gallery',
            original_filename: s.name, storage_path: s.path, public_url: s.url,
            is_primary: i === 0, bytes: s.bytes, width: s.width, height: s.height,
          })),
          ...kept.map((m) => ({
            product_id: product.product_id, image_role: `Generated (${m.mode})`,
            original_filename: m.path.split('/').pop(), storage_path: m.path, public_url: m.url,
            is_primary: false, bytes: m.bytes,
          })),
        ];
        const { error } = await (await import('@/lib/db')).sb().from('product_images').insert(rows);
        if (error) throw error;
      }
      const note = [
        `${shots.length} photo${shots.length === 1 ? '' : 's'} uploaded.`,
        imagery.mode === 'None' ? 'Using the photos as shot.'
          : kept.length ? `${kept.length} × ${imagery.mode.toLowerCase()} image${kept.length === 1 ? '' : 's'} generated and kept.`
          : `No ${imagery.mode.toLowerCase()} images generated.`,
        words.brief ? `Brief: ${words.brief}` : '',
      ].filter(Boolean).join(' ');
      await insertRow('launch_jobs', {
        product_id: product.product_id,
        stage: imagery.mode === 'None' ? 'Copy' : 'Imagery',
        status: aiReady ? 'Queued' : 'Blocked',
        message: aiReady ? note : `${note} Waiting on an AI key before anything can be generated.`,
      });
      setDone(product);
      setShots([]); setMade([]); setResearch(null); setStep(0);
      setPiece({ public_product_name: '', internal_sku: '', category: 'Banarasi Saree', fabric: '', colour: '',
        weave_or_motif: '', stock_qty: 1, moq: 1, cost_price: '', retail_price: '', wholesale_price: '' });
      setWords({ description: '', tags: '', brief: '', highlights: '' });
      q.reload();
    } catch (e2) { setErr(e2.message || String(e2)); }
    setSaving(false);
  }

  const gaps = [
    !words.description && 'No description. Go back and press "Write the description", or type one in.',
    !piece.retail_price && 'No retail price. "Find comparable prices" suggests one, or set it yourself.',
    !piece.cost_price && 'No agreed cost, so contribution cannot be worked out and the partner payable will be wrong.',
    imagery.mode !== 'None' && made.length === 0
      && `No ${imagery.mode.toLowerCase()} images generated yet — press Generate on the Imagery step.`,
    !aiReady && 'No AI key is set, so none of the generated steps can run at all.',
  ].filter(Boolean);

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
              <div className="card-head"><h3>What is the piece?</h3>
                {thinking === 'copy' && <span className="small faint">Reading your photos…</span>}</div>
              {thinking === 'copy' && (
                <div className="card-body" style={{ paddingBottom: 0 }}>
                  <div className="note plain small">
                    Looking at the {shots.length} photo{shots.length === 1 ? '' : 's'} you uploaded.
                    Anything it can read off them appears in these fields and in the description
                    on the next step. Everything stays editable.
                  </div>
                </div>)}
              {unsure.length > 0 && thinking === '' && (
                <div className="card-body" style={{ paddingBottom: 0 }}>
                  <div className="note small">
                    <strong>Filled in from the photos — check these.</strong> A photograph cannot
                    settle what something is made of, and the model is unsure about:{' '}
                    {unsure.join(', ')}. Correct anything that is wrong before you go on; it ends
                    up in the description and in front of customers.
                  </div>
                </div>)}
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
                        {PROVIDERS.map(([k]) => (
                          <option key={k} value={k}>{providerOption(k, keys)}</option>))}
                      </select>
                      <span className="hint">{providerHint(imagery.provider)}</span></div>
                  </div>)}

                {imagery.mode !== 'None' && (
                  <div style={{ marginTop: 14 }}>
                    <div className="row wrap" style={{ gap: 8 }}>
                      <button className="btn btn-primary btn-sm" onClick={runImages}
                        disabled={thinking !== '' || shots.length === 0 || !keys?.gemini}
                        title={keys?.gemini ? 'Generates from the photos you uploaded' : 'Needs a Gemini key'}>
                        {thinking === 'images'
                          ? 'Generating…'
                          : `Generate ${imagery.count} × ${imagery.mode.toLowerCase()}`}
                      </button>
                      {made.length > 0 && (
                        <span className="small faint">
                          {made.filter((m) => m.use).length} of {made.length} kept
                        </span>)}
                      {shots.length === 0 && <span className="small faint">Upload a photo first.</span>}
                      {keys && !keys.gemini && (
                        <span className="small faint">
                          Generated imagery needs a Gemini key. ChatGPT and Claude do not produce
                          images here, whichever model you picked above for the words.
                        </span>)}
                    </div>

                    {made.length > 0 && (
                      <>
                        <div className="shots" style={{ marginTop: 12 }}>
                          {made.map((m) => (
                            <div className="shot" key={m.path}
                              style={{ opacity: m.use ? 1 : 0.4,
                                       outline: m.use ? '2px solid var(--accent)' : 'none' }}>
                              <img src={m.url} alt="" />
                              <button onClick={() => dropMade(m.path)} title="Delete this one">×</button>
                              <button title={m.use ? 'Keep it out of the listing' : 'Use it in the listing'}
                                onClick={() => setMade((xs) => xs.map((x) =>
                                  x.path === m.path ? { ...x, use: !x.use } : x))}
                                style={{ right: 'auto', left: 4 }}>{m.use ? '✓' : '+'}</button>
                            </div>))}
                        </div>
                        <div className="note plain small" style={{ marginTop: 10 }}>
                          These are renderings made from your photographs, not photographs of the piece.
                          Check each one against the real garment before you keep it — the border, the
                          motifs and the colour are what a customer will expect to receive. Google embeds
                          an invisible SynthID watermark marking them as AI-generated. Your uploaded
                          photos are saved as the main images either way.
                        </div>
                      </>)}
                  </div>)}

                {keys && !aiReady && (
                  <div className="note" style={{ marginTop: 6 }}>
                    No AI key is set yet, so your choice is recorded and the job waits. Add any one of
                    {PROVIDERS.map(([k], i) => (
                      <span key={k}>{i ? ', ' : ' '}<span className="mono">{SECRET_NAME[k]}</span></span>))}
                    {' '}to this project's Edge Function secrets and it runs.
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

                <div className="row wrap" style={{ marginBottom: 10 }}>
                  <button className="btn btn-sm" onClick={runCopy}
                    disabled={!keyFor(imagery.provider) || thinking !== '' || shots.length === 0}
                    title={keyFor(imagery.provider) ? 'Reads your photos and writes the listing' : 'Needs an AI key'}>
                    {thinking === 'copy' ? 'Reading the photos…' : 'Write the description'}
                  </button>
                  <button className="btn btn-sm" onClick={runPrice}
                    disabled={!keyFor(imagery.provider) || thinking !== ''}
                    title={keyFor(imagery.provider) ? 'Searches for comparable pieces' : 'Needs an AI key'}>
                    {thinking === 'price' ? 'Searching…' : 'Find comparable prices'}
                  </button>
                  {keys && !keyFor(imagery.provider) && (
                    <span className="small faint">
                      No key for {providerLabel(imagery.provider)} yet.
                    </span>)}
                  {shots.length === 0 && <span className="small faint">The description needs photos.</span>}
                </div>

                {words.highlights && (
                  <div className="note plain small" style={{ marginBottom: 10, whiteSpace: 'pre-line' }}>
                    {words.highlights}
                  </div>)}

                {research && (
                  <div className="card" style={{ marginBottom: 12 }}>
                    <div className="card-head"><h3>Comparable pieces</h3>
                      <span className="small muted">
                        {money(research.low)} – {money(research.high)}
                      </span></div>
                    <div className="card-body">
                      <div className="row" style={{ marginBottom: 8 }}>
                        <div>
                          <div className="small faint">Suggested retail</div>
                          <div style={{ fontSize: 20, fontWeight: 600, letterSpacing: '-.02em' }}>
                            {money(research.suggested)}</div>
                        </div>
                        <span className="spacer" />
                        <button className="btn btn-sm" type="button"
                          onClick={() => setPiece({ ...piece, retail_price: research.suggested })}>
                          Use this price
                        </button>
                      </div>
                      {research.reasoning && <div className="small muted" style={{ marginBottom: 8 }}>{research.reasoning}</div>}
                      <div className="t-wrap"><table className="table">
                        <thead><tr><th>Piece</th><th>Seller</th><th className="num">Price</th></tr></thead>
                        <tbody>{(research.comparables || []).map((c, i) => (
                          <tr key={i}>
                            <td>{c.url
                              ? <a className="link" href={c.url} target="_blank" rel="noreferrer">{c.name}</a>
                              : c.name}</td>
                            <td className="small muted">{c.seller}</td>
                            <td className="num">{money(c.price)}</td>
                          </tr>))}</tbody></table></div>
                    </div>
                  </div>)}

                <div className="field"><label>Description</label>
                  <textarea value={words.description} style={{ minHeight: 120 }}
                    placeholder="Write it yourself, or let the model draft it from your photos."
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
                {gaps.length > 0 && (
                  <div className="note" style={{ marginTop: 14 }}>
                    <strong>Not done yet.</strong> You can create it anyway and come back to these,
                    but nothing here happens on its own:
                    <ul style={{ margin: '6px 0 0', paddingLeft: 18 }}>
                      {gaps.map((g) => <li key={g} className="small">{g}</li>)}
                    </ul>
                  </div>)}

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
              ? <button className="btn btn-primary btn-sm" disabled={!canNext}
                  onClick={() => { if (step === 0) autoAnalyse(); setStep(step + 1); }}>Continue</button>
              : <button className="btn btn-primary btn-sm" disabled={saving} onClick={finish}>
                  {saving ? 'Creating…' : 'Create the product'}</button>}
          </div>
        </div>

        <div className="stack">
          <div className="card">
            <div className="card-head"><h3>Many at once</h3>
              <button className="btn btn-sm" onClick={() => setBulk((v) => !v)}>
                {bulk ? 'Close' : 'Use a spreadsheet'}</button></div>
            {!bulk
              ? (
                <div className="card-body small muted">
                  The wizard is for one piece with photos. To load a batch from a partner's
                  stock list, import a spreadsheet instead — download the template, fill it in,
                  upload it. Photos get added per piece afterwards.
                </div>)
              : (
                <>
                  <div className="card-body small muted" style={{ paddingBottom: 0 }}>
                    Pieces arrive as <strong>Draft</strong> with no photos. Only the product name
                    is required; anything you leave blank you can fill in later.
                  </div>
                  <Sheet cfg={{ table: 'products', singular: 'product', columns: PRODUCT_SHEET }}
                    onDone={() => { q.reload(); setBulk(false); }} />
                </>)}
          </div>

          <div className="card">
            <div className="card-head"><h3>What happens next</h3></div>
            <div className="card-body stack" style={{ gap: 9 }}>
              {[
                ['Photos', `${shots.length} uploaded`],
                ['Imagery', imagery.mode === 'None' ? 'Skipped' : `${imagery.count} × ${imagery.mode}`],
                ['Copy', words.description ? 'Written' : aiReady ? 'Ready to draft' : 'Waiting on a key'],
                ['Pricing', piece.retail_price ? `Set at ${money(piece.retail_price)}`
                  : research ? `Suggested ${money(research.suggested)}` : 'Not set'],
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
