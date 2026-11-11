'use client';
import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { sb } from '@/lib/db';

export default function Login() {
  const router = useRouter();
  const [mode, setMode] = useState('in');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [name, setName] = useState('');
  const [err, setErr] = useState('');
  const [ok, setOk] = useState('');
  const [busy, setBusy] = useState(false);
  const [needCode, setNeedCode] = useState(null);
  const [code, setCode] = useState('');

  useEffect(() => {
    sb().auth.getSession().then(({ data }) => { if (data.session) router.replace('/'); });
  }, [router]);

  async function submit(e) {
    e.preventDefault();
    setErr(''); setOk(''); setBusy(true);
    try {
      if (mode === 'in') {
        const { error } = await sb().auth.signInWithPassword({ email, password });
        if (error) throw error;
        // If the second-factor check itself fails, never strand the person at a blank
        // screen: let them in on the password and surface the problem in Settings.
        try {
          const { data: aal } = await sb().auth.mfa.getAuthenticatorAssuranceLevel();
          if (aal?.nextLevel === 'aal2' && aal.currentLevel !== 'aal2') {
            const { data: f } = await sb().auth.mfa.listFactors();
            const factor = (f?.totp || []).find((x) => x.status === 'verified');
            if (factor) {
              const { data: ch, error: ce } = await sb().auth.mfa.challenge({ factorId: factor.id });
              if (ce) throw ce;
              setNeedCode({ factorId: factor.id, challengeId: ch.id });
              setBusy(false);
              return;
            }
          }
        } catch { /* fall through to the workspace */ }
        router.replace('/');
      } else {
        const { data, error } = await sb().auth.signUp({ email, password, options: { data: { full_name: name } } });
        if (error) throw error;
        if (data.session) router.replace('/');
        else { setOk('Account created. Check your email for the confirmation link, then sign in.'); setMode('in'); }
      }
    } catch (e2) { setErr(e2.message || String(e2)); }
    setBusy(false);
  }

  async function submitCode(e) {
    e.preventDefault();
    setErr(''); setBusy(true);
    const { error } = await sb().auth.mfa.verify({
      factorId: needCode.factorId, challengeId: needCode.challengeId, code: code.trim(),
    });
    if (error) { setErr(error.message); setBusy(false); return; }
    router.replace('/');
  }

  function toggleTheme() {
    const now = document.documentElement.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
    document.documentElement.setAttribute('data-theme', now);
    try { localStorage.setItem('cos-theme', now); } catch { /* ignore */ }
  }

  if (needCode) {
    return (
      <div className="auth">
        <form className="auth-card" onSubmit={submitCode}>
          <h1>One more step</h1>
          <p className="sub">Enter the six-digit code from your authenticator app.</p>
          {err && <div className="err">{err}</div>}
          <div className="field"><label>Code</label>
            <input value={code} onChange={(e) => setCode(e.target.value)} inputMode="numeric"
              autoComplete="one-time-code" maxLength={6} placeholder="000000" autoFocus required /></div>
          <button className="btn btn-primary" disabled={busy || code.length < 6}>
            {busy ? 'Checking…' : 'Sign in'}</button>
          <p className="small muted" style={{ marginTop: 14, textAlign: 'center' }}>
            <a className="link" href="#" onClick={(e) => {
              e.preventDefault(); sb().auth.signOut(); setNeedCode(null); setCode(''); setErr('');
            }}>Start again</a>
          </p>
        </form>
      </div>
    );
  }

  return (
    <div className="auth">
      <form className="auth-card" onSubmit={submit}>
        <div className="row" style={{ marginBottom: 18 }}>
          <div className="brand-mark">C</div>
          <div>
            <div style={{ fontSize: 14, fontWeight: 600 }}>Commerce Business OS</div>
            <div className="faint" style={{ fontSize: 11, letterSpacing: '.12em', textTransform: 'uppercase' }}>Workspace</div>
          </div>
          <span className="spacer" />
          <button type="button" className="btn btn-ghost btn-sm" onClick={toggleTheme} title="Light or dark">☾</button>
        </div>
        <h1>{mode === 'in' ? 'Sign in' : 'Create your account'}</h1>
        <p className="sub">{mode === 'in'
          ? 'Products, customers, orders and campaigns in one place.'
          : 'The first account created becomes the Owner.'}</p>

        {err && <div className="err">{err}</div>}
        {ok && <div className="ok">{ok}</div>}

        {mode === 'up' && (
          <div className="field"><label>Full name</label>
            <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Your name" required /></div>
        )}
        <div className="field"><label>Email</label>
          <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="username" required /></div>
        <div className="field"><label>Password</label>
          <input type="password" value={password} onChange={(e) => setPassword(e.target.value)}
            autoComplete={mode === 'in' ? 'current-password' : 'new-password'} minLength={8} required /></div>
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
