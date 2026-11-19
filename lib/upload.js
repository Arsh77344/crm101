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

// A file called 1764... or IMG_8842 tells nobody anything, and alt="" tells a
// screen reader and a search engine nothing either. Both are fixed at the one
// moment the piece finally has a name: when it is saved.
export function slug(text, fallback = 'piece') {
  const out = String(text || '').toLowerCase()
    .normalize('NFD').replace(/[̀-ͯ]/g, '')
    .replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 60);
  return out || fallback;
}

// Storage has no rename, so this is a move. It returns the new path and url, or
// the old ones if the move fails — a tidy name is never worth losing a photo.
export async function renameImage(from, to) {
  if (!from || from === to) return { path: from, url: publicUrl(from) };
  const { error } = await sb().storage.from(BUCKET).move(from, to);
  if (error) return { path: from, url: publicUrl(from), error: error.message };
  return { path: to, url: publicUrl(to) };
}

export function publicUrl(path) {
  if (!path) return null;
  return sb().storage.from(BUCKET).getPublicUrl(path).data.publicUrl;
}

const PART_ALT = {
  Overall: 'the whole piece',
  Pallu: 'the pallu',
  Border: 'the border',
  Body: 'the body of the cloth',
  Blouse: 'the blouse piece',
  'Close-up': 'a close view of the weave',
  Draped: 'the piece draped',
};
const MADE_ALT = {
  Clean: 'cut out on a white background',
  Mannequin: 'draped on a dress form',
  Model: 'worn by a model',
  Detail: 'a close view of the weave',
};

// What a screen reader reads out, and what a search engine indexes.
export function altFor(piece, img) {
  const name = String(piece?.public_product_name || 'Piece').trim();
  const what = [piece?.colour, piece?.fabric].filter(Boolean).join(' ');
  if (img.generated) {
    const how = img.look_name ? `in the ${img.look_name} setting` : MADE_ALT[img.mode] || 'generated';
    return `${name} — ${how}${what ? `, ${what}` : ''}.`;
  }
  const part = PART_ALT[img.part] || (img.part && img.part !== 'Unlabelled'
    ? img.part.toLowerCase() : 'the piece');
  return `${name} — ${part}${what ? `, ${what}` : ''}.`;
}

// products/<piece>/<piece>-pallu-1.jpg — readable in a storage listing, in a
// browser tab, and in a URL a customer might see.
export function nameFor(piece, img, n) {
  const base = slug(piece?.public_product_name);
  const kind = img.generated
    ? slug(img.look_name ? `editorial-${img.look_name}` : img.mode, 'shot')
    : slug(img.part && img.part !== 'Unlabelled' ? img.part : 'photo', 'photo');
  const ext = (String(img.path || '').split('.').pop() || 'jpg').toLowerCase();
  return `products/${base}/${base}-${kind}-${n}.${ext}`;
}
