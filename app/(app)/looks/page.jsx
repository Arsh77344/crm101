'use client';
import { useRef, useState } from 'react';
import { useQuery, insertRow, updateRow, removeRow } from '@/lib/db';
import { uploadImage, deleteImage } from '@/lib/upload';
import { assist, PROVIDERS, NO_KEYS, providerOption, firstWithKey, hasKey } from '@/lib/assist';
import { Page, Badge, Empty, Loading, ErrorNote, when } from '@/components/ui';

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

  const q = useQuery(async (c) => {
    const [looks, keys] = await Promise.all([
      c.from('looks').select('*').order('created_at', { ascending: false }),
      assist({ action: 'health' }).catch(() => NO_KEYS),
    ]);
    if (looks.error) throw looks.error;
    return { looks: looks.data || [], keys };
  }, []);

  const looks = q.data?.looks || [];
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

  async function read(look) {
    setBusy(look.look_id); setErr('');
    try {
      const out = await assist({
        action: 'look', provider, look_id: look.look_id, reference_url: look.reference_url,
      });
      const d = out.result || {};
      if (d.name && /^Reference/i.test(look.name)) {
        await updateRow('looks', 'look_id', look.look_id, { name: d.name });
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
                <div className="shots" style={{ gap: 12 }}>
                  {looks.map((l) => (
                    <div key={l.look_id} style={{ width: 150 }}>
                      <div className="shot" style={{
                        width: 150, height: 190, cursor: 'pointer',
                        outline: sel === l.look_id ? '2px solid var(--accent)' : 'none',
                      }} onClick={() => setSel(l.look_id === sel ? null : l.look_id)}>
                        <img src={l.reference_url} alt="" />
                      </div>
                      <div className="small" style={{ marginTop: 4, fontWeight: 600 }}>{l.name}</div>
                      <div className="row" style={{ gap: 4, marginTop: 2 }}>
                        <Badge className={l.status === 'Ready' ? 'b-accent' : ''}>{l.status}</Badge>
                        <span className="small faint">{l.source === 'Own' ? 'Ours' : 'Found'}</span>
                      </div>
                      {l.status !== 'Ready' && (
                        <button className="btn btn-sm" style={{ marginTop: 5, width: '100%' }}
                          disabled={busy === l.look_id || !hasKey(keys, provider)}
                          onClick={() => read(l)}>
                          {busy === l.look_id ? 'Reading…' : 'Read it'}</button>)}
                    </div>))}
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
                  <div className="card-head"><h3>{current.name}</h3>
                    <button className="btn btn-ghost btn-sm" onClick={() => setSel(null)}>Close</button></div>
                  <div className="card-body">
                    <img src={current.reference_url} alt=""
                      style={{ width: '100%', borderRadius: 8, marginBottom: 12 }} />
                    <div className="field"><label>Name</label>
                      <input defaultValue={current.name}
                        onBlur={(e) => save(current, { name: e.target.value })} /></div>
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
                      <textarea defaultValue={current.notes || ''}
                        placeholder="Anything the reading missed, or what you want done differently."
                        onBlur={(e) => save(current, { notes: e.target.value })} /></div>
                    <div className="row" style={{ marginTop: 6 }}>
                      <button className="btn btn-sm" disabled={busy === current.look_id || !hasKey(keys, provider)}
                        onClick={() => read(current)}>
                        {busy === current.look_id ? 'Reading…' : current.status === 'Ready' ? 'Read it again' : 'Read it'}</button>
                      <span className="spacer" />
                      <span className="small faint">
                        Used {current.times_used || 0}×{current.last_used_at ? ` · ${when(current.last_used_at)}` : ''}
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
