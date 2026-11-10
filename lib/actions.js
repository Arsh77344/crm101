'use server';
import { revalidatePath } from 'next/cache';
import { redirect } from 'next/navigation';
import { supabaseServer } from './supabase';

function collect(formData) {
  const row = {};
  for (const [k, v] of formData.entries()) {
    if (k.startsWith('_')) continue;
    row[k] = v === '' ? null : v;
  }
  return row;
}

export async function upsertRow(table, pk, backTo, formData) {
  const sb = supabaseServer();
  const id = formData.get('_id');
  const row = collect(formData);
  const res = id
    ? await sb.from(table).update(row).eq(pk, id).select(pk).maybeSingle()
    : await sb.from(table).insert(row).select(pk).maybeSingle();
  if (res.error) redirect(`${backTo}?error=${encodeURIComponent(res.error.message)}`);
  revalidatePath('/', 'layout');
  const target = backTo.includes('[id]') ? backTo.replace('[id]', res.data?.[pk]) : backTo;
  redirect(`${target}${target.includes('?') ? '&' : '?'}saved=1`);
}

export async function deleteRow(table, pk, backTo, formData) {
  const sb = supabaseServer();
  const { error } = await sb.from(table).delete().eq(pk, formData.get('_id'));
  if (error) redirect(`${backTo}?error=${encodeURIComponent(error.message)}`);
  revalidatePath('/', 'layout');
  redirect(`${backTo}?deleted=1`);
}

export async function quickUpdate(table, pk, backTo, formData) {
  const sb = supabaseServer();
  const id = formData.get('_id');
  const row = collect(formData);
  const { error } = await sb.from(table).update(row).eq(pk, id);
  if (error) redirect(`${backTo}?error=${encodeURIComponent(error.message)}`);
  revalidatePath('/', 'layout');
  redirect(backTo);
}

export async function addMembers(campaignId, formData) {
  const sb = supabaseServer();
  const ids = formData.getAll('contact_id');
  if (ids.length) {
    await sb.from('campaign_members').upsert(
      ids.map((contact_id) => ({ campaign_id: campaignId, contact_id, member_status: 'Planned' })),
      { onConflict: 'campaign_id,contact_id' }
    );
  }
  revalidatePath(`/campaigns/${campaignId}`);
  redirect(`/campaigns/${campaignId}`);
}
