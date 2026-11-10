import { createServerClient } from '@supabase/ssr';
import { cookies } from 'next/headers';

export function supabaseServer() {
  const store = cookies();
  return createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY,
    {
      cookies: {
        getAll: () => store.getAll(),
        setAll: (list) => {
          try { list.forEach(({ name, value, options }) => store.set(name, value, options)); }
          catch { /* called from a Server Component; middleware refreshes instead */ }
        },
      },
    }
  );
}

export async function currentUser() {
  const sb = supabaseServer();
  const { data: { user } } = await sb.auth.getUser();
  if (!user) return null;
  const { data: profile } = await sb.from('profiles').select('*').eq('id', user.id).maybeSingle();
  return { ...user, profile: profile || { role: 'sales', full_name: user.email } };
}

export function canManage(role) { return role === 'owner' || role === 'admin'; }
