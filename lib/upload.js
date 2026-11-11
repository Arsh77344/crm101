'use client';
import { sb } from './db';

const BUCKET = 'product-images';

// Phone photos run to several megabytes. They are slow to upload, slow to load
// in a gallery, and — because the AI functions fetch and base64-encode them on
// the server — big enough to blow an Edge Function's CPU budget outright. A
// catalogue shot gains nothing past 1600px, so shrink before anything else sees
// the file. Anything the browser cannot decode (HEIC on some devices) is
// uploaded untouched rather than lost.
const MAX_EDGE = 1600;
const QUALITY = 0.85;

async function shrink(file) {
  if (!file.type?.startsWith('image/')) return { blob: file, name: file.name };
  let bitmap;
  try {
    bitmap = await createImageBitmap(file);
  } catch {
    return { blob: file, name: file.name };
  }
  const { width, height } = bitmap;
  const scale = Math.min(1, MAX_EDGE / Math.max(width, height));
  const w = Math.round(width * scale);
  const h = Math.round(height * scale);
  try {
    const canvas = document.createElement('canvas');
    canvas.width = w; canvas.height = h;
    canvas.getContext('2d').drawImage(bitmap, 0, 0, w, h);
    const blob = await new Promise((res) => canvas.toBlob(res, 'image/jpeg', QUALITY));
    bitmap.close?.();
    // Re-encoding a small PNG can make it bigger; keep whichever is smaller.
    if (!blob || (scale === 1 && blob.size >= file.size)) return { blob: file, name: file.name, w: width, h: height };
    const base = (file.name || 'photo').replace(/\.[^.]+$/, '');
    return { blob, name: `${base}.jpg`, w, h };
  } catch {
    bitmap.close?.();
    return { blob: file, name: file.name, w: width, h: height };
  }
}

export async function uploadImage(file, folder = 'inbox') {
  const small = await shrink(file);
  const ext = (small.name.split('.').pop() || 'jpg').toLowerCase();
  const safe = `${folder}/${Date.now()}-${Math.random().toString(36).slice(2, 8)}.${ext}`;
  const { error } = await sb().storage.from(BUCKET).upload(safe, small.blob, {
    cacheControl: '3600', upsert: false, contentType: small.blob.type || undefined,
  });
  if (error) throw error;
  const { data } = sb().storage.from(BUCKET).getPublicUrl(safe);
  return {
    path: safe, url: data.publicUrl, name: small.name,
    bytes: small.blob.size, width: small.w ?? null, height: small.h ?? null,
    originalBytes: file.size,
  };
}

export async function deleteImage(path) {
  const { error } = await sb().storage.from(BUCKET).remove([path]);
  if (error) throw error;
}
