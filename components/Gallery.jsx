'use client';
import { useRef, useState } from 'react';
import { useQuery, sb, removeRow, updateRow } from '@/lib/db';
import { uploadImage, deleteImage } from '@/lib/upload';
import { Loading, ErrorNote } from './ui';

export default function Gallery({ productId }) {
  const fileRef = useRef(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');

  const q = useQuery(async (c) => {
    const { data, error } = await c.from('product_images').select('*')
      .eq('product_id', productId).order('is_primary', { ascending: false });
    if (error) throw error;
    return data || [];
  }, [productId]);

  async function add(e) {
    const files = Array.from(e.target.files || []);
    if (!files.length) return;
    setBusy(true); setErr('');
    try {
      const existing = (q.data || []).length;
      for (let i = 0; i < files.length; i++) {
        const up = await uploadImage(files[i], `product/${productId}`);
        const { error } = await sb().from('product_images').insert({
          product_id: productId, storage_path: up.path, public_url: up.url,
          original_filename: up.name, bytes: up.bytes, width: up.width, height: up.height,
          is_primary: existing === 0 && i === 0, image_role: existing === 0 && i === 0 ? 'Primary' : 'Gallery',
        });
        if (error) throw error;
      }
      q.reload();
    } catch (e2) { setErr(e2.message || String(e2)); }
    setBusy(false);
    if (fileRef.current) fileRef.current.value = '';
  }

  async function drop(img) {
    setBusy(true);
    try {
      if (img.storage_path) await deleteImage(img.storage_path).catch(() => {});
      await removeRow('product_images', 'image_id', img.image_id);
      q.reload();
    } catch (e2) { setErr(e2.message || String(e2)); }
    setBusy(false);
  }

  async function makePrimary(img) {
    setBusy(true);
    try {
      for (const other of q.data || []) {
        if (other.is_primary && other.image_id !== img.image_id) {
          await updateRow('product_images', 'image_id', other.image_id, { is_primary: false, image_role: 'Gallery' });
        }
      }
      await updateRow('product_images', 'image_id', img.image_id, { is_primary: true, image_role: 'Primary' });
      q.reload();
    } catch (e2) { setErr(e2.message || String(e2)); }
    setBusy(false);
  }

  const imgs = q.data || [];
  return (
    <div className="card">
      <div className="card-head"><h3>Photos</h3><span className="small faint">{imgs.length}</span></div>
      <ErrorNote error={q.error || err} />
      <div className="card-body">
        {q.loading ? <Loading /> : imgs.length === 0
          ? <div className="small muted" style={{ marginBottom: 10 }}>No photos yet.</div>
          : (
            <div className="shots" style={{ marginBottom: 10 }}>
              {imgs.map((im) => (
                <div className="shot" key={im.image_id} title={im.is_primary ? 'Main image' : 'Click the star to make this the main image'}>
                  <img src={im.public_url} alt="" />
                  <button onClick={() => drop(im)} disabled={busy} title="Remove">×</button>
                  {!im.is_primary && (
                    <button onClick={() => makePrimary(im)} disabled={busy} title="Make main"
                      style={{ right: 'auto', left: 4 }}>★</button>)}
                  {im.is_primary && <span className="badge b-accent"
                    style={{ position: 'absolute', bottom: 4, left: 4, fontSize: 10 }}>Main</span>}
                </div>))}
            </div>)}
        <button className="btn btn-sm" onClick={() => fileRef.current?.click()} disabled={busy}>
          {busy ? 'Working…' : 'Add photos'}</button>
        <input ref={fileRef} type="file" accept="image/*" multiple onChange={add} style={{ display: 'none' }} />
      </div>
    </div>
  );
}
