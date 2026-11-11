'use client';
import { useState } from 'react';
import { useQuery, updateRow, sb } from '@/lib/db';
import { useSession, canManage } from '@/lib/session';
import { Page, Loading, ErrorNote } from '@/components/ui';

const LABELS = {
  brand_name: 'Brand name', brand_tagline: 'Tagline',
  default_currency: 'Default currency', storefront_url: 'Storefront address',
};

export default function Settings() {
  const { user, profile } = useSession();
  const manager = canManage(profile?.role);
  const [err, setErr] = useState('');
  const [saved, setSaved] = useState('');
  const [pwMsg, setPwMsg] = useState('');
  const q = useQuery(async (c) => {
    const { data, error } = await c.from('settings').select('*').order('setting_key');
    if (error) throw error;
    return data || [];
  }, []);

  async function save(e, key) {
    e.preventDefault();
    const value = new FormData(e.target).get('setting_value');
    try { await updateRow('settings', 'setting_key', key, { setting_value: value }); setSaved(key); q.reload(); }
    catch (e2) { setErr(e2.message); }
  }

  async function changePassword(e) {
    e.preventDefault();
    setPwMsg('');
    const form = new FormData(e.target);
    const next = form.get('password');
    if (String(next).length < 8) { setPwMsg('Use at least 8 characters.'); return; }
    if (next !== form.get('confirm')) { setPwMsg('The two passwords do not match.'); return; }
    const { error } = await sb().auth.updateUser({ password: next });
    setPwMsg(error ? error.message : 'Password changed. It applies from your next sign-in.');
    if (!error) e.target.reset();
  }

  return (
    <Page title="Settings" sub="Brand details used across listings, showrooms and campaigns.">
      <ErrorNote error={q.error || err} />
      {!manager && <div className="note warn" style={{ marginBottom: 16 }}>Only an Owner or Admin can change settings.</div>}
      <div className="grid g2">
        <div className="card">
          <div className="card-head"><h3>Workspace</h3></div>
          <div className="card-body stack">
            {q.loading ? <Loading /> : (q.data || []).map((s) => (
              <form key={s.setting_key} className="field" style={{ marginBottom: 0 }} onSubmit={(e) => save(e, s.setting_key)}>
                <label>{LABELS[s.setting_key] || s.setting_key}</label>
                <div className="row" style={{ gap: 8 }}>
                  <input name="setting_value" defaultValue={s.setting_value || ''} disabled={!manager} />
                  {manager && <button className="btn btn-sm">{saved === s.setting_key ? 'Saved' : 'Save'}</button>}
                </div>
              </form>))}
          </div>
        </div>
        <div className="card">
          <div className="card-head"><h3>Your account</h3></div>
          <div className="card-body stack" style={{ gap: 8 }}>
            <div className="row"><span className="muted small">Signed in as</span><span className="spacer" />{user?.email}</div>
            <div className="row"><span className="muted small">Name</span><span className="spacer" />{profile?.full_name || '—'}</div>
            <div className="row"><span className="muted small">Role</span><span className="spacer" />
              <span style={{ textTransform: 'capitalize' }}>{profile?.role}</span></div>
            <div className="small faint" style={{ marginTop: 6 }}>
              Switch between light and dark from the bottom of the sidebar.
            </div>
          </div>
          <form className="card-foot" onSubmit={changePassword}>
            <div className="field"><label>New password</label>
              <input name="password" type="password" minLength={8} autoComplete="new-password" required /></div>
            <div className="field"><label>Confirm new password</label>
              <input name="confirm" type="password" minLength={8} autoComplete="new-password" required /></div>
            <button className="btn btn-primary btn-sm">Change password</button>
            {pwMsg && <div className="small" style={{ marginTop: 8 }}>{pwMsg}</div>}
          </form>
        </div>
      </div>
    </Page>
  );
}
