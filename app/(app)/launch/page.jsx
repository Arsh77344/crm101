'use client';
import { useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import { useQuery, insertRow, updateRow } from '@/lib/db';
import { uploadImage, deleteImage, renameImage, altFor, nameFor } from '@/lib/upload';
import { assist, checkKeys, PROVIDERS, NO_KEYS, SECRET_NAME,
  providerLabel, providerOption, providerHint, hasKey, anyKey, firstWithKey } from '@/lib/assist';
import { Page, Badge, Empty, Loading, ErrorNote, when, money } from '@/components/ui';
import Sheet from '@/components/Sheet';
import { PRODUCT_SHEET } from '@/lib/schemas';
import { useLightbox } from '@/components/Lightbox';
import Dictate from '@/components/Dictate';
import { partFromName, partGaps, PART_OPTIONS } from '@/lib/parts';

const STEPS = ['Photos', 'The piece', 'Imagery', 'Words & price', 'Review'];
const STAGES = ['Photos', 'Imagery', 'Copy', 'Pricing', 'Review', 'Published'];
const STATUS = ['Queued', 'Running', 'Blocked', 'Done', 'Failed'];

// What is happening right now, in order, so the wait is legible rather than a spinner.
const STAGE = {
  copy: ['Reading the photographs', 'Working out what the piece is and drafting the words.'],
  price: ['Searching comparable pieces', 'Looking up what similar pieces sell for right now.'],
  rewrite: ['Writing the description', 'Rewriting it now that the market is known.'],
  images: ['Generating images', 'Rendering the shots from your photographs.'],
};

const IMAGERY = [
  ['Clean', 'Studio still', 'The piece itself, styled on the set. White cut-out optional.'],
  ['Mannequin', 'AI mannequin', 'Draped on a plain dress form that holds its shape. No person.'],
  ['Model', 'AI model', 'Worn by a generated model. Slower and dearer.'],
  ['Detail', 'Close-up of the cloth', 'A macro of the border or pallu, on the set. Always included.'],
  ['Editorial', 'Editorial shoot', 'Built from a look in your library. Needs a look chosen.'],
];
// A close-up proves the cloth, so a run never goes out without one.
const NO_COUNTS = { Clean: 0, Mannequin: 0, Model: 0, Detail: 1, Editorial: 0 };

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
  const [imagery, setImagery] = useState({
    counts: { ...NO_COUNTS }, provider: 'openai', look_id: '', tweak: '',
    set_id: '', cutout_on_white: false, check: true,
  });
  const [words, setWords] = useState({ description: '', tags: '', brief: '', highlights: '' });
  const [keys, setKeys] = useState(null);
  const [thinking, setThinking] = useState('');
  const [research, setResearch] = useState(null);
  const [bulk, setBulk] = useState(false);
  const [made, setMade] = useState([]);
  const [unsure, setUnsure] = useState([]);
  const enlarge = useLightbox();

  useEffect(() => {
    checkKeys().then((k) => {
      setKeys(k);
      setImagery((im) => (k && !k[im.provider] ? { ...im, provider: firstWithKey(k, im.provider) } : im));
    }).catch(() => setKeys(NO_KEYS));
  }, []);

  const q = useQuery(async (c) => {
    const [jobs, integrations, looks, lookUse] = await Promise.all([
      c.from('launch_jobs').select('*,products(product_id,public_product_name,internal_sku)')
        .order('created_at', { ascending: false }).limit(25),
      c.from('integrations').select('provider,status'),
      c.from('looks').select('look_id,look_no,name,summary,source,use_for,status,reference_url')
        .eq('status', 'Ready').order('look_no', { ascending: true }),
      c.from('look_usage').select('look_id,products_used_on,images_made,products'),
    ]);
    if (jobs.error) throw jobs.error;
    const byLook = {};
    (lookUse.data || []).forEach((u) => { byLook[u.look_id] = u; });
    return { jobs: jobs.data || [], integrations: integrations.data || [], lookUse: byLook,
             looks: (looks.data || []).filter((l) => l.use_for !== 'Campaign') };
  }, []);

  const ints = q.data?.integrations || [];
  const connected = (name) => ints.some((i) => i.provider === name && i.status === 'Connected');
  const storeReady = connected('Wix') || connected('Shopify');
  const keyFor = (p) => hasKey(keys, p);
  const aiReady = anyKey(keys);

  // Pressing Continue past the photos runs the whole reading in order: look at the
  // photographs, search what comparable pieces sell for, then write the description
  // knowing both. Each stage shows while it runs, and a later stage failing never
  // throws away what an earlier one produced.
  async function runPipeline() {
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
    setErr('');
    const urls = shots.map((x) => x.url);
    let current = { ...piece };

    const applyWords = (r) => setWords((w) => ({
      ...w,
      description: r.description || w.description,
      tags: (r.tags || []).join(', ') || w.tags,
      highlights: (r.highlights || []).join('\n'),
    }));

    try {
      setThinking('copy');
      const out = await assist({ action: 'copy', provider: imagery.provider,
        piece: current, brief: words.brief, images: urls,
        parts: shots.map((x) => x.part || 'Unlabelled') });
      const r = out.result || {};
      const ob = r.observed || {};
      current = {
        ...current,
        public_product_name: current.public_product_name || r.title || '',
        category: current.category || ob.category || '',
        fabric: current.fabric || ob.fabric || '',
        colour: current.colour || ob.colour || '',
        weave_or_motif: current.weave_or_motif || ob.weave_or_motif || '',
      };
      setPiece(current);
      setUnsure(r.uncertain || []);
      applyWords(r);
    } catch (e2) {
      setErr(e2.message || String(e2)); setThinking(''); return;
    }

    let found = null;
    try {
      setThinking('price');
      const out = await assist({ action: 'price', provider: imagery.provider,
        piece: current, brief: words.brief });
      found = out.result || null;
      setResearch(found);
    } catch (e2) {
      setErr(`The description is written, but the price search failed: ${e2.message || e2}`);
    }

    if (found?.comparables?.length) {
      try {
        setThinking('rewrite');
        const out = await assist({ action: 'copy', provider: imagery.provider,
          piece: current, brief: words.brief, images: urls, research: found,
          parts: shots.map((x) => x.part || 'Unlabelled') });
        const r = out.result || {};
        applyWords(r);
        if (r.uncertain) setUnsure(r.uncertain);
      } catch { /* the first description stands */ }
    }
    setThinking('');
  }

  // One pass over every style the owner asked for, rather than one style per
  // visit to this step. Each runs on its own so a failure in one does not cost
  // the others, and whatever did come back is kept.
  async function runImages() {
    const wanted = IMAGERY.map(([k]) => k).filter((k) => (imagery.counts[k] || 0) > 0);
    if (!wanted.length) return;
    // The close-up is the frame that proves the cloth, so a run always has one.
    const runCounts = { ...imagery.counts };
    if (!wanted.includes('Detail')) { wanted.push('Detail'); runCounts.Detail = 1; }
    // One set for the whole run. Picked here, not per style, so the frames look
    // like one shoot even though each style is its own call.
    const sets = (keys?.sets || []).map((x) => x.id);
    const setId = imagery.set_id
      || (sets.length ? sets[Math.floor(Math.random() * sets.length)] : '');
    // Start the prop rotation somewhere new, so the second run of a piece is not
    // the first one again.
    const propFrom = Math.floor(Math.random() * 6);
    if (!imagery.set_id && setId) setImagery((im) => ({ ...im, set_id: setId }));
    setThinking('images'); setErr('');
    const trouble = [];
    for (const mode of wanted) {
      try {
        const out = await assist({
          action: 'images', provider: 'gemini', mode, count: runCounts[mode],
          look_id: mode === 'Editorial' ? imagery.look_id : null,
          set_id: mode === 'Editorial' ? null : setId,
          cutout_on_white: imagery.cutout_on_white, check: imagery.check, prop_from: propFrom,
          tweak: imagery.tweak, piece,
          images: shots.map((s) => s.url), parts: shots.map((s) => s.part || 'Unlabelled'),
        });
        setMade((m) => [...m, ...(out.images || []).map((i) => ({ ...i, use: true }))]);
        (out.failed || []).forEach((f) => trouble.push(`${mode}: ${f}`));
      } catch (e2) {
        trouble.push(`${mode}: ${e2.message || e2}`);
      }
    }
    if (trouble.length) setErr(trouble.join(' · '));
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
        parts: shots.map((s) => s.part || 'Unlabelled'),
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
        setShots((s) => [...s, { ...up, part: partFromName(f.name) }]);
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
        // The piece has a name at last, so the files get one too, and every row
        // gets the sentence a screen reader will read out.
        const all = [
          ...shots.map((x, i) => ({ ...x, generated: false, primary: i === 0 })),
          ...kept.map((x) => ({ ...x, generated: true, primary: false })),
        ];
        const seen = {};
        const renamed = [];
        for (const img of all) {
          const kind = img.generated ? (img.look_name ? 'editorial' : img.mode) : (img.part || 'photo');
          seen[kind] = (seen[kind] || 0) + 1;
          const target = nameFor(piece, img, seen[kind]);
          const moved = await renameImage(img.path, target);
          renamed.push({ ...img, path: moved.path, url: moved.url });
        }

        const rows = renamed.map((x) => (x.generated ? {
          product_id: product.product_id,
          image_role: x.look_name ? `Editorial (${x.look_name})` : `Generated (${x.mode})`,
          original_filename: x.path.split('/').pop(), storage_path: x.path, public_url: x.url,
          is_primary: false, bytes: x.bytes, width: null, height: null,
          generated: true, shot_angle: x.shot_angle || null, source_look_id: x.look_id || null,
          part: null, alt_text: altFor(piece, x),
        } : {
          product_id: product.product_id, image_role: x.primary ? 'Primary' : 'Gallery',
          original_filename: x.path.split('/').pop(), storage_path: x.path, public_url: x.url,
          is_primary: x.primary, bytes: x.bytes, width: x.width, height: x.height,
          generated: false, shot_angle: null, source_look_id: null,
          part: x.part || null, alt_text: altFor(piece, x),
        }));
        const { error } = await (await import('@/lib/db')).sb().from('product_images').insert(rows);
        if (error) throw error;
      }
      const byMode = kept.reduce((acc, m) => {
        acc[m.mode] = (acc[m.mode] || 0) + 1; return acc;
      }, {});
      const madeLine = Object.entries(byMode).map(([m, n]) => `${n} × ${m.toLowerCase()}`).join(', ');
      const note = [
        `${shots.length} photo${shots.length === 1 ? '' : 's'} uploaded`
          + (shots.some((x) => x.part && x.part !== 'Unlabelled')
            ? ` (${shots.map((x) => x.part).filter(Boolean).join(', ')}).` : '.'),
        madeLine ? `Kept ${madeLine}.` : 'No images generated.',
        words.brief ? `Brief: ${words.brief}` : '',
      ].filter(Boolean).join(' ');
      await insertRow('launch_jobs', {
        product_id: product.product_id,
        stage: kept.length ? 'Copy' : 'Imagery',
        status: aiReady ? 'Queued' : 'Blocked',
        message: aiReady ? note : `${note} Waiting on an AI key before anything can be generated.`,
      });
      setDone(product);
      setShots([]); setMade([]); setResearch(null); setStep(0);
      setImagery((im) => ({ ...im, tweak: '', look_id: '', set_id: '',
        counts: { ...NO_COUNTS } }));
      setPiece({ public_product_name: '', internal_sku: '', category: 'Banarasi Saree', fabric: '', colour: '',
        weave_or_motif: '', stock_qty: 1, moq: 1, cost_price: '', retail_price: '', wholesale_price: '' });
      setWords({ description: '', tags: '', brief: '', highlights: '' });
      q.reload();
    } catch (e2) { setErr(e2.message || String(e2)); }
    setSaving(false);
  }

  const wantedTotal = IMAGERY.reduce((n, [k]) => n + (imagery.counts[k] || 0), 0);
  const gaps = [
    !words.description && 'No description. Go back and press "Write the description", or type one in.',
    !piece.retail_price && 'No retail price. "Find comparable prices" suggests one, or set it yourself.',
    !piece.cost_price && 'No agreed cost, so contribution cannot be worked out and the partner payable will be wrong.',
    wantedTotal > 0 && made.length === 0
      && `${wantedTotal} image${wantedTotal === 1 ? '' : 's'} asked for but none generated yet — press Generate on the Imagery step.`,
    shots.some((x) => x.part === 'Unlabelled')
      && 'Some photos are not labelled with the part they show, so the model has to guess.',
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

      {thinking !== '' && STAGE[thinking] && (
        <div className="note" style={{ marginBottom: 12 }}>
          <strong>{STAGE[thinking][0]}…</strong> {STAGE[thinking][1]}
          {' '}Everything it produces lands in the fields below, editable, before anything is created.
        </div>)}

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

                <div className="field" style={{ marginTop: 14, maxWidth: 340 }}>
                  <label>Which model reads these photos</label>
                  <select value={imagery.provider}
                    onChange={(e) => setImagery({ ...imagery, provider: e.target.value })}>
                    {PROVIDERS.map(([k]) => (
                      <option key={k} value={k}>{providerOption(k, keys)}</option>))}
                  </select>
                  <span className="hint">
                    {providerHint(imagery.provider)} Continue starts the reading, so pick before
                    you press it. Generated imagery always uses Gemini, whichever you choose here.
                  </span>
                </div>
                {shots.length > 0 && (
                  <>
                    <div className="shots" style={{ marginTop: 14, gap: 12 }}>
                      {shots.map((sh) => (
                        <div key={sh.path} style={{ width: 132 }}>
                          <div className="shot clickable" style={{ width: 132, height: 150 }}>
                            <img src={sh.url} alt={sh.name} title={sh.name}
                              onClick={() => enlarge(shots.map((x) => ({
                                public_url: x.url, image_role: x.part || 'Photo',
                              })), shots.indexOf(sh))} />
                            <button onClick={() => dropShot(sh.path)} title="Remove">×</button>
                          </div>
                          <select value={sh.part || 'Unlabelled'} style={{ marginTop: 5, width: '100%' }}
                            onChange={(e) => setShots((xs) => xs.map((x) =>
                              x.path === sh.path ? { ...x, part: e.target.value } : x))}>
                            {[...new Set([...PART_OPTIONS, sh.part || 'Unlabelled'])].map((o) => (
                              <option key={o} value={o}>{o}</option>))}
                          </select>
                        </div>))}
                    </div>

                    {(() => {
                      const holes = partGaps(shots.map((x) => x.part || 'Unlabelled'));
                      return holes.length === 0
                        ? (
                          <div className="note plain small" style={{ marginTop: 12 }}>
                            Every photo is labelled and the set covers the whole piece. The model is
                            told which photograph is which part, so it assembles the real garment
                            rather than inventing the parts it cannot see.
                          </div>)
                        : (
                          <div className="note small" style={{ marginTop: 12 }}>
                            <strong>Worth fixing before you generate.</strong> Read from the file
                            names; correct any that are wrong.
                            <ul style={{ margin: '6px 0 0', paddingLeft: 18 }}>
                              {holes.map((h) => <li key={h}>{h}</li>)}
                            </ul>
                          </div>);
                    })()}
                  </>)}
              </div>
            </>
          )}

          {step === 1 && (
            <>
              <div className="card-head"><h3>What is the piece?</h3>
                {thinking !== '' && STAGE[thinking] && (
                  <span className="small faint">{STAGE[thinking][0]}…</span>)}</div>
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
                <div className="stack" style={{ gap: 8, marginBottom: 14 }}>
                  {IMAGERY.map(([key, title, blurb]) => (
                    <div key={key} className="row" style={{
                      gap: 12, padding: '10px 12px', border: '1px solid var(--line)',
                      borderRadius: 8,
                      borderColor: (imagery.counts[key] || 0) > 0 ? 'var(--accent)' : 'var(--line)',
                    }}>
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <div style={{ fontWeight: 600, fontSize: 13 }}>{title}</div>
                        <div className="small muted" style={{ marginTop: 2 }}>{blurb}</div>
                      </div>
                      <select value={imagery.counts[key] || 0} style={{ width: 78 }}
                        onChange={(e) => setImagery({
                          ...imagery,
                          counts: { ...imagery.counts, [key]: Number(e.target.value) },
                        })}>
                        {[0, 1, 2, 3, 4].map((n) => <option key={n} value={n}>{n}</option>)}
                      </select>
                    </div>))}
                </div>

                <div className="row small wrap" style={{ marginBottom: 12, gap: 6 }}>
                  <strong>{wantedTotal} image{wantedTotal === 1 ? '' : 's'}</strong>
                  <span className="muted">
                    in this run{wantedTotal === 0 ? ' — set a number above' : '. Each one costs.'}
                  </span>
                  {wantedTotal > 0 && (imagery.counts.Detail || 0) === 0 && (
                    <span className="note warn small" style={{ padding: '2px 8px' }}>
                      No close-up. One will be added anyway — it is what proves the cloth.
                    </span>)}
                </div>

                <div className="form-grid">
                  <div className="field"><label>The set they all share</label>
                    <select value={imagery.set_id}
                      onChange={(e) => setImagery({ ...imagery, set_id: e.target.value })}>
                      <option value="">Pick one for me</option>
                      {(keys?.sets || []).map((x) => (
                        <option key={x.id} value={x.id}>{x.name}</option>))}
                    </select>
                    <span className="hint">
                      Every frame in the run but the editorial ones shares this room and this light.
                      The camera and the placement move; the background does not. Say what to change
                      about it in the box below.
                    </span></div>
                  <div className="field"><label>The studio stills</label>
                    <select value={imagery.cutout_on_white ? 'white' : 'set'}
                      onChange={(e) => setImagery({ ...imagery,
                        cutout_on_white: e.target.value === 'white' })}>
                      <option value="set">Styled on the set — over a chair, a ledge, a stool</option>
                      <option value="white">Flat cut-out on pure white, for marketplace listings</option>
                    </select>
                    <span className="hint">
                      Styled is a photograph: the piece over something plain that belongs to the
                      set, lit like a catalogue shoot, a different arrangement each frame. Pick the
                      cut-out when a marketplace demands a white background.
                    </span></div>
                </div>

                <label className="row small" style={{ gap: 7, marginBottom: 12, cursor: 'pointer' }}>
                  <input type="checkbox" checked={imagery.check} style={{ width: 'auto' }}
                    onChange={(e) => setImagery({ ...imagery, check: e.target.checked })} />
                  <span>Check every image against your photos before showing it to me
                    <span className="faint"> — one extra read per image; flags a colour, border or
                    motif that drifted</span></span>
                </label>

                <div className="field" style={{ maxWidth: 340 }}>
                  <label>Which model writes the words</label>
                  <select value={imagery.provider}
                    onChange={(e) => setImagery({ ...imagery, provider: e.target.value })}>
                    {PROVIDERS.map(([k]) => (
                      <option key={k} value={k}>{providerOption(k, keys)}</option>))}
                  </select>
                  <span className="hint">{providerHint(imagery.provider)} Images always use Gemini.</span>
                </div>

                {(imagery.counts.Editorial || 0) > 0 && (
                  <div className="field" style={{ marginTop: 12 }}>
                    <label>Which look for the editorial frames</label>
                    {(q.data?.looks || []).length === 0
                      ? (
                        <div className="note small">
                          No readable looks yet. Add references on the <strong>Look library</strong> page
                          and read one, then it appears here.
                        </div>)
                      : (
                        <>
                          <select value={imagery.look_id}
                            onChange={(e) => setImagery({ ...imagery, look_id: e.target.value })}>
                            <option value="">Choose a look…</option>
                            {(q.data?.looks || []).map((l) => {
                              const u = (q.data?.lookUse || {})[l.look_id];
                              return (
                                <option key={l.look_id} value={l.look_id}>
                                  {`#${l.look_no} · ${l.name}`}
                                  {l.summary ? ` — ${l.summary}` : ''}
                                  {u?.images_made
                                    ? ` [used on ${u.products_used_on} piece${u.products_used_on === 1 ? '' : 's'}]`
                                    : ' [unused]'}
                                </option>);
                            })}
                          </select>
                          <span className="hint">
                            Each frame is a different angle of the same scene. The first sets the
                            woman and the location; the rest are given that frame so the set holds
                            together — faces still drift between takes, so expect to regenerate.
                          </span>
                        </>)}
                  </div>)}

                {wantedTotal > 0 && (
                  <div className="field" style={{ marginTop: 12 }}>
                    <label>Anything to change about these shots <span className="faint">(optional)</span></label>
                    <textarea value={imagery.tweak} style={{ minHeight: 64 }}
                      placeholder="Warmer light, late afternoon. Plain stone wall behind her instead. Marigolds rather than roses. Make it more dramatic."
                      onChange={(e) => setImagery({ ...imagery, tweak: e.target.value })} />
                    <Dictate onText={(f) => setImagery((im) => ({ ...im, tweak: f(im.tweak) }))} />
                    <span className="hint">
                      A line or two in your own words, applied to every frame in this run. It can
                      change the setting, background, props, styling, mood, light and camera — but
                      not the garment: colour, weave, border and motifs stay matched to your photos,
                      and anything asking otherwise is ignored.
                    </span>
                  </div>)}

                {wantedTotal > 0 && (
                  <div style={{ marginTop: 14 }}>
                    <div className="row wrap" style={{ gap: 8 }}>
                      <button className="btn btn-primary btn-sm" onClick={runImages}
                        disabled={thinking !== '' || shots.length === 0 || !keys?.gemini
                          || ((imagery.counts.Editorial || 0) > 0 && !imagery.look_id)}
                        title={keys?.gemini ? 'Generates from the photos you uploaded' : 'Needs a Gemini key'}>
                        {thinking === 'images'
                          ? 'Generating…'
                          : `Generate all ${wantedTotal} image${wantedTotal === 1 ? '' : 's'}`}
                      </button>
                      {made.length > 0 && (
                        <span className="small faint">
                          {made.filter((m) => m.use).length} of {made.length} kept
                        </span>)}
                      {shots.length === 0 && <span className="small faint">Upload a photo first.</span>}
                      {(imagery.counts.Editorial || 0) > 0 && !imagery.look_id && (q.data?.looks || []).length > 0
                        && <span className="small faint">Choose a look for the editorial frames first.</span>}
                      {keys && !keys.gemini && (
                        <span className="small faint">
                          Generated imagery needs a Gemini key. ChatGPT, Claude and Groq do not
                          produce images at all, whichever you picked above for the words.
                        </span>)}
                    </div>

                    {made.length > 0 && (
                      <>
                        <div className="shots" style={{ marginTop: 12 }}>
                          {made.map((m) => (
                            <div className="shot clickable" key={m.path}
                              style={{ opacity: m.use ? 1 : 0.4,
                                       outline: m.use ? '2px solid var(--accent)' : 'none' }}>
                              <img src={m.url} alt="" title="Click to enlarge"
                                onClick={() => enlarge(made.map((x) => ({
                                  public_url: x.url, generated: true,
                                  image_role: x.look_name ? `Editorial (${x.look_name})` : `Generated (${x.mode})`,
                                  shot_angle: x.shot_angle,
                                })), made.indexOf(m))} />
                              <button onClick={() => dropMade(m.path)} title="Delete this one">×</button>
                              <button title={m.use ? 'Keep it out of the listing' : 'Use it in the listing'}
                                onClick={() => setMade((xs) => xs.map((x) =>
                                  x.path === m.path ? { ...x, use: !x.use } : x))}
                                style={{ right: 'auto', left: 4 }}>{m.use ? '✓' : '+'}</button>
                              {m.check && !m.check.match && (
                                <span className="shot-flag" title={m.check.differences.join(' · ')}>
                                  Does not match
                                </span>)}
                            </div>))}
                        </div>

                        {made.some((m) => m.check && !m.check.match) && (
                          <div className="note warn small" style={{ marginTop: 10 }}>
                            <strong>Some of these do not match your photographs.</strong> They were
                            read back against the piece and the garment came out wrong:
                            <ul style={{ margin: '6px 0 0', paddingLeft: 18 }}>
                              {made.filter((m) => m.check && !m.check.match).map((m) => (
                                <li key={m.path}>
                                  {m.mode}: {m.check.differences.join('; ') || 'the garment differs'}
                                </li>))}
                            </ul>
                            Drop them and generate again rather than selling from them.
                          </div>)}
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
                  <Dictate onText={(f) => setWords((w) => ({ ...w, brief: f(w.brief) }))} />
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
                      <span className="badge">{made.length === 0 ? 'No generated imagery'
                        : `${made.filter((m) => m.use).length} generated kept`}</span>
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
                  onClick={() => { if (step === 0) runPipeline(); setStep(step + 1); }}>Continue</button>
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
                ['Imagery', wantedTotal === 0 ? 'Skipped'
                  : IMAGERY.map(([k]) => [k, imagery.counts[k] || 0]).filter(([, n]) => n > 0)
                    .map(([k, n]) => `${n} × ${k.toLowerCase()}`).join(', ')],
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
                          className="mini">
                          {STAGES.map((s) => <option key={s}>{s}</option>)}</select>
                        <select value={j.status} onChange={(e) => updateRow('launch_jobs', 'job_id', j.job_id,
                          { status: e.target.value }).then(q.reload)}
                          className="mini">
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
