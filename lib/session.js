'use client';
import { useEffect, useState } from 'react';
import { sb } from './db';

export function useSession() {
  const [state, setState] = useState({ loading: true, user: null, profile: null });

  useEffect(() => {
    let alive = true;
    async function load(user) {
      if (!user) { if (alive) setState({ loading: false, user: null, profile: null }); return; }
      const { data } = await sb().from('profiles').select('*').eq('id', user.id).maybeSingle();
      if (alive) setState({ loading: false, user, profile: data || { role: 'sales', full_name: user.email } });
    }
    sb().auth.getSession().then(({ data }) => load(data.session?.user || null));
    const { data: sub } = sb().auth.onAuthStateChange((_e, session) => load(session?.user || null));
    return () => { alive = false; sub.subscription.unsubscribe(); };
  }, []);

  return state;
}

export const canManage = (role) => role === 'owner' || role === 'admin';
