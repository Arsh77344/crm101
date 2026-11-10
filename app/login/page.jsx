'use client';
import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { supabaseBrowser } from '@/lib/browser';

export default function Login() {
  const router = useRouter();
  const [mode, setMode] = useState('in');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [name, setName] = useState('');
  const [err, setErr] = useState('');
  const [ok, setOk] = useState('');
  const [busy, setBusy] = useState(false);

  async function submit(e) {
    e.preventDefault();
    setErr(''); setOk(''); setBusy(true);
    const sb = supabaseBrowser();
    if (mode === 'in') {
      const { error } = await sb.auth.signInWithPassword({ email, password });
      if (error) { setErr(error.message); setBusy(false); return; }
      router.push('/'); router.refresh();
    } else {
      const { data, error } = await sb.auth.signUp({
        email, password, options: { data: { full_name: name } },
      });
      if (error) { setErr(error.message); setBusy(false); return; }
      if (data.session) { router.push('/'); router.refresh(); }
      else { setOk('Account created. Check your email to confirm, then sign in.'); setBusy(false); setMode('in'); }
    }
  }

  return (
    <div className="auth">
      <form className="auth-card" onSubmit={submit}>
        <div className="row" style={{ marginBottom: 18 }}>
          <div className="brand-mark">C</div>
          <div>
            <div style={{ fontFamily: 'var(--serif)', fontSize: 15 }}>Commerce Business OS</div>
            <div className="faint" style={{ fontSize: 11, letterSpacing: '.12em', textTransform: 'uppercase' }}>Workspace</div>
          </div>
        </div>
        <h1>{mode === 'in' ? 'Sign in' : 'Create your account'}</h1>
        <p className="sub">{mode === 'in' ? 'Products, customers and campaigns in one place.' : 'The first account created becomes the Owner.'}</p>

        {err && <div className="err">{err}</div>}
        {ok && <div className="ok">{ok}</div>}

        {mode === 'up' && (
          <div className="field">
            <label>Full name</label>
            <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Mohammad Arsh" required />
          </div>
        )}
        <div className="field">
          <label>Email</label>
          <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="username" required />
        </div>
        <div className="field">
          <label>Password</label>
          <input type="password" value={password} onChange={(e) => setPassword(e.target.value)}
                 autoComplete={mode === 'in' ? 'current-password' : 'new-password'} minLength={8} required />
        </div>
        <button className="btn btn-primary" disabled={busy}>
          {busy ? 'Working…' : mode === 'in' ? 'Sign in' : 'Create account'}
        </button>
        <p className="small muted" style={{ marginTop: 16, textAlign: 'center' }}>
          {mode === 'in' ? 'First time here? ' : 'Already have an account? '}
          <a className="link" href="#" onClick={(e) => { e.preventDefault(); setErr(''); setMode(mode === 'in' ? 'up' : 'in'); }}>
            {mode === 'in' ? 'Create an account' : 'Sign in'}
          </a>
        </p>
      </form>
    </div>
  );
}
