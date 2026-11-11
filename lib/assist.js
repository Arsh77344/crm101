'use client';
import { sb } from './db';

const ENDPOINT = `${process.env.NEXT_PUBLIC_SUPABASE_URL}/functions/v1/launch-assist`;

export async function assist(body) {
  const { data: { session } } = await sb().auth.getSession();
  if (!session) throw new Error('Sign in again, your session expired.');
  const res = await fetch(ENDPOINT, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${session.access_token}`,
      apikey: process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(body),
  });
  const out = await res.json().catch(() => ({ error: `The assistant returned ${res.status}.` }));
  if (!res.ok) throw new Error(out.error || `The assistant returned ${res.status}.`);
  return out;
}

export const checkKeys = () => assist({ action: 'health' });
