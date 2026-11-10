'use client';
import { createClient } from '@supabase/supabase-js';
import { useCallback, useEffect, useState } from 'react';

let client;
export function sb() {
  if (!client) {
    client = createClient(
      process.env.NEXT_PUBLIC_SUPABASE_URL,
      process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY,
      { auth: { persistSession: true, autoRefreshToken: true, detectSessionInUrl: true } }
    );
  }
  return client;
}

/** Run a Supabase query and track loading/error. fn receives the client. */
export function useQuery(fn, deps = []) {
  const [state, setState] = useState({ data: null, error: null, loading: true });
  const [tick, setTick] = useState(0);
  useEffect(() => {
    let alive = true;
    (async () => {
      setState((s) => ({ ...s, loading: true }));
      try {
        const data = await fn(sb());
        if (alive) setState({ data, error: null, loading: false });
      } catch (e) {
        if (alive) setState({ data: null, error: e.message || String(e), loading: false });
      }
    })();
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick]);
  const reload = useCallback(() => setTick((t) => t + 1), []);
  return { ...state, reload };
}

export async function rows(table, build = (q) => q, select = '*') {
  const { data, error } = await build(sb().from(table).select(select));
  if (error) throw error;
  return data || [];
}

export function clean(obj) {
  const out = {};
  Object.entries(obj).forEach(([k, v]) => {
    if (k.startsWith('_')) return;
    if (v === '' || v === undefined) out[k] = null;
    else if (v === 'true') out[k] = true;
    else if (v === 'false') out[k] = false;
    else out[k] = v;
  });
  return out;
}

export async function insertRow(table, row) {
  const { data, error } = await sb().from(table).insert(clean(row)).select().maybeSingle();
  if (error) throw error;
  return data;
}
export async function updateRow(table, pk, id, row) {
  const { error } = await sb().from(table).update(clean(row)).eq(pk, id);
  if (error) throw error;
}
export async function upsertRow(table, row, onConflict) {
  const { error } = await sb().from(table).upsert(clean(row), onConflict ? { onConflict } : undefined);
  if (error) throw error;
}
export async function removeRow(table, pk, id) {
  const { error } = await sb().from(table).delete().eq(pk, id);
  if (error) throw error;
}

export function formValues(form) {
  const fd = new FormData(form);
  const out = {};
  for (const [k, v] of fd.entries()) {
    if (out[k] !== undefined) { out[k] = [].concat(out[k], v); } else out[k] = v;
  }
  return out;
}

export async function removeWhere(table, match) {
  const { error } = await sb().from(table).delete().match(match);
  if (error) throw error;
}
