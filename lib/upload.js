'use client';
import { sb } from './db';

const BUCKET = 'product-images';

export async function uploadImage(file, folder = 'inbox') {
  const ext = (file.name.split('.').pop() || 'jpg').toLowerCase();
  const safe = `${folder}/${Date.now()}-${Math.random().toString(36).slice(2, 8)}.${ext}`;
  const { error } = await sb().storage.from(BUCKET).upload(safe, file, {
    cacheControl: '3600', upsert: false, contentType: file.type || undefined,
  });
  if (error) throw error;
  const { data } = sb().storage.from(BUCKET).getPublicUrl(safe);
  return { path: safe, url: data.publicUrl, name: file.name, bytes: file.size };
}

export async function deleteImage(path) {
  const { error } = await sb().storage.from(BUCKET).remove([path]);
  if (error) throw error;
}
