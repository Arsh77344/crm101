'use client';
import { useEffect, useState } from 'react';
import { sb } from '@/lib/db';
import { Loading } from './ui';

export default function TwoFactor() {
  const [factors, setFactors] = useState(null);
  const [aal, setAal] = useState(null);
  const [enrolling, setEnrolling] = useState(null);
  const [code, setCode] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');
  const [msg, setMsg] = useState('');

  async function load() {
    // A broken or expired session can make these throw rather than return an error.
    // The rest of Settings must stay usable either way.
    try {
      const [{ data: f, error: fe }, { data: a }] = await Promise.all([
        sb().auth.mfa.listFactors(),
        sb().auth.mfa.getAuthenticatorAssuranceLevel(),
      ]);
      if (fe) setErr(fe.message);
      setFactors(f?.totp || []);
      setAal(a || null);
    } catch (e) {
      setErr('Could not read your sign-in settings. Sign out and back in, then try again.');
      setFactors([]);
    }
  }
  useEffect(() => { load(); }, []);

  async function startEnrol() {
    setBusy(true); setErr(''); setMsg('');
    try {
      const { data, error } = await sb().auth.mfa.enroll({
        factorType: 'totp', friendlyName: `Authenticator ${new Date().toLocaleDateString('en-GB')}`,
      });
      if (error) throw error;
      setEnrolling(data);
    } catch (e) { setErr(e.message || String(e)); }
    setBusy(false);
  }

  async function confirm(e) {
    e.preventDefault();
    setBusy(true); setErr('');
    try {
      const { data: ch, error: ce } = await sb().auth.mfa.challenge({ factorId: enrolling.id });
      if (ce) throw ce;
      const { error: ve } = await sb().auth.mfa.verify({
        factorId: enrolling.id, challengeId: ch.id, code: code.trim(),
      });
      if (ve) throw ve;
      setEnrolling(null); setCode('');
      setMsg('Two-factor is on. You will be asked for a code every time you sign in.');
      await load();
    } catch (e2) { setErr(e2.message || String(e2)); }
    setBusy(false);
  }

  async function remove(id) {
    setBusy(true); setErr('');
    try {
      const { error } = await sb().auth.mfa.unenroll({ factorId: id });
      if (error) throw error;
      setMsg('Two-factor removed.');
      await load();
    } catch (e) { setErr(e.message || String(e)); }
    setBusy(false);
  }

  if (factors === null) return <div className="card"><Loading /></div>;
  const live = factors.filter((f) => f.status === 'verified');

  return (
    <div className="card">
      <div className="card-head"><h3>Two-factor sign-in</h3>
        {live.length > 0
          ? <span className="badge b-green">On</span>
          : <span className="badge b-amber">Off</span>}</div>
      <div className="card-body">
        {err && <div className="err">{err}</div>}
        {msg && <div className="ok">{msg}</div>}

        {live.length > 0 ? (
          <>
            <div className="small muted" style={{ marginBottom: 10 }}>
              A code from your authenticator app is required at every sign-in. Your password alone
              is not enough to get in.
            </div>
            {live.map((f) => (
              <div className="row" key={f.id} style={{ marginBottom: 7 }}>
                <div>
                  <div className="small" style={{ fontWeight: 500 }}>{f.friendly_name || 'Authenticator app'}</div>
                  <div className="small faint">Added {new Date(f.created_at).toLocaleDateString('en-GB')}</div>
                </div>
                <span className="spacer" />
                <button className="btn btn-sm btn-danger" disabled={busy} onClick={() => remove(f.id)}>Remove</button>
              </div>))}
            {aal && (
              <div className="small faint" style={{ marginTop: 8 }}>
                This session is at {aal.currentLevel === 'aal2' ? 'the higher assurance level' : 'password-only level'}.
              </div>)}
          </>
        ) : enrolling ? (
          <form onSubmit={confirm}>
            <div className="small muted" style={{ marginBottom: 10 }}>
              Scan this with Google Authenticator, Authy, 1Password or any authenticator app,
              then type the six-digit code it shows.
            </div>
            <div style={{ display: 'flex', gap: 16, alignItems: 'flex-start', flexWrap: 'wrap' }}>
              <div style={{ background: '#fff', padding: 10, borderRadius: 8, border: '1px solid var(--line)' }}>
                <img src={enrolling.totp.qr_code} alt="Scan this code" width={168} height={168} />
              </div>
              <div style={{ flex: 1, minWidth: 190 }}>
                <div className="field"><label>Or type this key in by hand</label>
                  <input readOnly value={enrolling.totp.secret} className="mono"
                    onFocus={(e) => e.target.select()} /></div>
                <div className="field"><label>Six-digit code</label>
                  <input value={code} onChange={(e) => setCode(e.target.value)} inputMode="numeric"
                    autoComplete="one-time-code" maxLength={6} placeholder="000000" required /></div>
                <div className="row">
                  <button className="btn btn-primary btn-sm" disabled={busy || code.length < 6}>
                    {busy ? 'Checking…' : 'Turn it on'}</button>
                  <button type="button" className="btn btn-sm btn-ghost"
                    onClick={() => { setEnrolling(null); setCode(''); }}>Cancel</button>
                </div>
              </div>
            </div>
          </form>
        ) : (
          <>
            <div className="small muted" style={{ marginBottom: 10 }}>
              Right now your password is the only thing between anyone and every customer record,
              order and payment in here. An authenticator app fixes that, and it is free.
            </div>
            <button className="btn btn-primary btn-sm" onClick={startEnrol} disabled={busy}>
              {busy ? 'Setting up…' : 'Set up two-factor'}</button>
          </>
        )}
      </div>
    </div>
  );
}
