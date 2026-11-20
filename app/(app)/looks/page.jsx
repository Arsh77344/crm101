'use client';
import { useRef, useState } from 'react';
import { useQuery, insertRow, updateRow, removeRow } from '@/lib/db';
import { uploadImage, deleteImage } from '@/lib/upload';
import { assist, PROVIDERS, NO_KEYS, providerOption, firstWithKey, hasKey } from '@/lib/assist';
import { Page, Badge, Empty, Loading, ErrorNote, when } from '@/components/ui';
import { useLightbox } from '@/components/Lightbox';
import Dictate from '@/components/Dictate';

// What the reading produces. Editable by hand: this text, not the picture, is what
// every future shoot is built from, so a wrong line here spreads.
const READ_FIELDS = [
  ['framing', 'Framing', 'Shot length, orientation, where the subject sits in frame.'],
  ['subject', 'Subject', 'Who or what is in the picture, as a casting note.'],
  ['pose', 'Pose', 'Body, arms, head and gaze.'],
  ['setting', 'Setting', 'The kind of place and what is behind the subject.'],
  ['light', 'Light', 'Direction, hardness, time of day.'],
  ['palette', 'Palette', 'The colours that carry the frame.'],
  ['mood', 'Mood', 'What it should feel like.'],
  ['avoid', 'What would make it wrong', 'The things that would make a recreation look cheap.'],
];

export default function Looks() {
  const fileRef = useRef(null);
  const [sel, setSel] = useState(null);
  const [busy, setBusy] = useState('');
  const [err, setErr] = useState('');
  const [provider, setProvider] = useState('gemini');
  const enlarge = useLightbox();
  const noteRef = useRef(null);

  const q = useQuery(async (c) => {
    const [looks, usage, keys] = await Promise.all([
      c.from('looks').select('*').order('look_no', { ascending: true }),
      c.from('look_usage').select('look_id,products_used_on,images_made,last_image_at,products'),
      assist({ action: 'health' }).catch(() => NO_KEYS),
    ]);
    if (looks.error) throw looks.error;
    const used = {};
    (usage.data || []).forEach((u) => { used[u.look_id] = u; });
    return { looks: looks.data || [], used, keys };
  }, []);

  const looks = q.data?.looks || [];
  const used = q.data?.used || {};
  const keys = q.data?.keys;
  const current = looks.find((l) => l.look_id === sel) || null;

  async function add(e) {
    const files = Array.from(e.target.files || []);
    if (!files.length) return;
    setBusy('upload'); setErr('');
    try {
      for (const f of files) {
        const up = await uploadImage(f, 'looks');
        await insertRow('looks', {
          name: (f.name || 'Reference').replace(/\.[^.]+$/, '').slice(0, 60),
          reference_url: up.url, storage_path: up.path, status: 'Unread',
        });
      }
      q.reload();
    } catch (e2) { setErr(e2.message || String(e2)); }
    setBusy('');
    if (fileRef.current) fileRef.current.value = '';
  }

  // The reading describes a frame in eight fields. This is the one line that
  // identifies it in a dropdown three weeks later.
  function lineFrom(d) {
    const clause = (t, n = 1) => String(t || '').split(/[,;.]/).slice(0, n)
      .join(',').trim().replace(/^[a-z]/, (c) => c.toUpperCase());
    const who = clause(d.subject);
    const doing = clause(d.pose).replace(/^[A-Z]/, (c) => c.toLowerCase());
    const place = clause(d.setting).replace(/^[A-Z]/, (c) => c.toLowerCase());
    const line = [who, doing, place].filter(Boolean).join(', ');
    // Cut on a word, never mid-word, so the fallback still reads as a sentence.
    const cut = line.length <= 150 ? line : line.slice(0, line.lastIndexOf(' ', 150));
    return cut.replace(/[,\s]+$/, '') + '.';
  }

  async function read(look) {
    setBusy(look.look_id); setErr('');
    try {
      const out = await assist({
        action: 'look', provider, look_id: look.look_id, reference_url: look.reference_url,
      });
      const d = out.result || {};
      const patch = {};
      // A file name off a phone or a download is not a name. Take the model's.
      if (d.name && (!look.name || /^(Reference|IMG|DSC|PXL|Screenshot|Gemini|WhatsApp)/i.test(look.name)
        || /^[0-9a-f]{16,}$/i.test(look.name) || /^[-_0-9\s]+$/.test(look.name))) {
        patch.name = d.name;
      }
      if (!look.summary) patch.summary = d.summary || lineFrom(d);
      if (Object.keys(patch).length) {
        await updateRow('looks', 'look_id', look.look_id, patch);
      }
      q.reload();
    } catch (e2) { setErr(e2.message || String(e2)); }
    setBusy('');
  }

  async function save(look, patch) {
    try { await updateRow('looks', 'look_id', look.look_id, patch); q.reload(); }
    catch (e2) { setErr(e2.message || String(e2)); }
  }

  async function drop(look) {
    setBusy(look.look_id);
    try {
      if (look.storage_path) await deleteImage(look.storage_path).catch(() => {});
      await removeRow('looks', 'look_id', look.look_id);
      if (sel === look.look_id) setSel(null);
      q.reload();
    } catch (e2) { setErr(e2.message || String(e2)); }
    setBusy('');
  }

  const ready = looks.filter((l) => l.status === 'Ready').length;

  return (
    <Page title="Look library"
      sub="Reference shots, read once, reused to direct product and campaign imagery."
      actions={<button className="btn btn-primary" disabled={busy === 'upload'}
        onClick={() => fileRef.current?.click()}>
        {busy === 'upload' ? 'Uploading…' : 'Add references'}</button>}>
      <ErrorNote error={q.error || err} />
      <input ref={fileRef} type="file" accept="image/*" multiple onChange={add}
        style={{ display: 'none' }} />

      <div className="note plain small" style={{ marginBottom: 14 }}>
        A reference someone else shot is <strong>direction, not a template</strong>. Looks marked
        “Found” are used for the kind of pose, the light and the sort of place only — the shoot
        deliberately differs in angle, location, styling and the woman in it, so the result is a
        different photograph that shares a mood. Mark a look “Ours” only if you shot it.
      </div>

      {q.loading ? <Loading /> : looks.length === 0
        ? <Empty title="No references yet"
            hint="Add the shots you want your product and campaign imagery to feel like." />
        : (
          <div className="grid" style={{ gridTemplateColumns: current ? '1fr 420px' : '1fr' }}>
            <div className="card">
              <div className="card-head"><h3>References</h3>
                <span className="small faint">{ready} of {looks.length} read</span></div>
              <div className="card-body">
                <div className="look-list">
                  {looks.map((l) => {
                    const u = used[l.look_id] || {};
                    const on = (u.products || []).map((x) => x.name).filter(Boolean);
                    return (
                      <div key={l.look_id}
                        className={`look-row ${sel === l.look_id ? 'on' : ''}`}
                        onClick={() => setSel(l.look_id === sel ? null : l.look_id)}>
                        <div className="look-no">{l.look_no ?? '—'}</div>
                        <img className="look-thumb" src={l.reference_url} alt={l.summary || l.name}
                          onClick={(e) => { e.stopPropagation();
                            enlarge(looks.map((x) => ({ public_url: x.reference_url,
                              image_role: `#${x.look_no} ${x.name}`, shot_angle: x.summary || '' })),
                              looks.indexOf(l)); }} />
                        <div className="look-text">
                          <div className="look-name">{l.name}</div>
                          <div className="small muted look-sum">
                            {l.summary || (l.status === 'Ready'
                              ? 'No one-line description yet — open it and write one.'
                              : 'Not read yet.')}
                          </div>
                          <div className="row wrap" style={{ gap: 5, marginTop: 4 }}>
                            <Badge>{l.status}</Badge>
                            <span className="badge">{l.source === 'Own' ? 'Ours' : 'Found'}</span>
                            {u.images_made > 0
                              ? <span className="badge b-amber" title={on.join(', ')}>
                                  Used on {u.products_used_on} piece{u.products_used_on === 1 ? '' : 's'}
                                </span>
                              : <span className="badge b-green">Unused</span>}
                          </div>
                          {on.length > 0 && (
                            <div className="small faint" style={{ marginTop: 3 }}>
                              {on.slice(0, 3).join(' · ')}{on.length > 3 ? ` · +${on.length - 3} more` : ''}
                              {u.last_image_at ? ` · last ${when(u.last_image_at)}` : ''}
                            </div>)}
                        </div>
                        {l.status !== 'Ready' && (
                          <button className="btn btn-sm" style={{ flexShrink: 0 }}
                            disabled={busy === l.look_id || !hasKey(keys, provider)}
                            onClick={(e) => { e.stopPropagation(); read(l); }}>
                            {busy === l.look_id ? 'Reading…' : 'Read it'}</button>)}
                      </div>);
                  })}
                </div>
                {keys && !hasKey(keys, provider) && (
                  <div className="small faint" style={{ marginTop: 10 }}>
                    No key for the selected model, so references cannot be read yet.
                  </div>)}
                <div className="field" style={{ maxWidth: 260, marginTop: 14 }}>
                  <label>Which model reads them</label>
                  <select value={provider} onChange={(e) => setProvider(e.target.value)}>
                    {PROVIDERS.map(([k]) => (
                      <option key={k} value={k}>{providerOption(k, keys)}</option>))}
                  </select>
                </div>
              </div>
            </div>

            {current && (
              <div className="stack">
                <div className="card">
                  <div className="card-head"><h3>#{current.look_no} · {current.name}</h3>
                    <button className="btn btn-ghost btn-sm" onClick={() => setSel(null)}>Close</button></div>
                  <div className="card-body">
                    <img src={current.reference_url} alt=""
                      style={{ width: '100%', borderRadius: 8, marginBottom: 12 }} />
                    <div className="field"><label>Name</label>
                      <input defaultValue={current.name}
                        onBlur={(e) => save(current, { name: e.target.value })} />
                      <span className="hint">Reference #{current.look_no}. A short label you
                        will recognise in a dropdown.</span></div>
                    <div className="field"><label>In one line</label>
                      <textarea defaultValue={current.summary || ''} style={{ minHeight: 48 }}
                        placeholder="A woman seated on the ghat steps, smoking, river behind her."
                        onBlur={(e) => save(current, { summary: e.target.value })} />
                      <span className="hint">What you would say to describe the shot. This is what
                        shows beside the number everywhere else.</span></div>
                    <div className="grid g2">
                      <div className="field"><label>Whose photograph</label>
                        <select value={current.source}
                          onChange={(e) => save(current, { source: e.target.value })}>
                          <option value="Found">Found — direction only</option>
                          <option value="Own">Ours — may follow closely</option>
                        </select></div>
                      <div className="field"><label>Use it for</label>
                        <select value={current.use_for}
                          onChange={(e) => save(current, { use_for: e.target.value })}>
                          <option value="Both">Products and campaigns</option>
                          <option value="Product">Product shoots only</option>
                          <option value="Campaign">Campaigns only</option>
                        </select></div>
                    </div>
                    <div className="field"><label>Tags</label>
                      <input defaultValue={current.tags || ''} placeholder="ghats, golden hour, seated"
                        onBlur={(e) => save(current, { tags: e.target.value })} /></div>
                    <div className="field"><label>Your own direction</label>
                      <textarea ref={noteRef} defaultValue={current.notes || ''} key={current.look_id}
                        placeholder="Anything the reading missed, or what you want done differently."
                        onBlur={(e) => save(current, { notes: e.target.value })} />
                      <Dictate onText={(f) => {
                        const node = noteRef.current;
                        if (!node) return;
                        node.value = f(node.value);
                        save(current, { notes: node.value });
                      }} /></div>
                    <div className="row" style={{ marginTop: 6 }}>
                      <button className="btn btn-sm" disabled={busy === current.look_id || !hasKey(keys, provider)}
                        onClick={() => read(current)}>
                        {busy === current.look_id ? 'Reading…' : current.status === 'Ready' ? 'Read it again' : 'Read it'}</button>
                      <span className="spacer" />
                      <span className="small faint">
                        {(used[current.look_id]?.images_made || 0) === 0
                          ? 'Not used on any piece yet.'
                          : `${used[current.look_id].images_made} image(s) on `
                            + `${used[current.look_id].products_used_on} piece(s).`}
                      </span>
                    </div>
                  </div>
                </div>

                <div className="card">
                  <div className="card-head"><h3>The reading</h3></div>
                  <div className="card-body">
                    {current.status !== 'Ready'
                      ? <div className="small muted">Not read yet. Read it and these fill in.</div>
                      : READ_FIELDS.map(([k, label, hint]) => (
                        <div className="field" key={k}><label>{label}</label>
                          <textarea defaultValue={current[k] || ''} style={{ minHeight: 54 }}
                            onBlur={(e) => save(current, { [k]: e.target.value })} />
                          <span className="hint">{hint}</span></div>))}
                    <button className="btn btn-sm" style={{ marginTop: 6 }}
                      disabled={busy === current.look_id} onClick={() => drop(current)}>
                      Delete this look</button>
                  </div>
                </div>
              </div>)}
          </div>)}
    </Page>
  );
}
