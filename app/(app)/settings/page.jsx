import { supabaseServer, currentUser, canManage } from '@/lib/supabase';
import { quickUpdate } from '@/lib/actions';
import { Page } from '@/components/ui';
import Flash from '@/components/Flash';
export const dynamic = 'force-dynamic';

const LABELS = {
  brand_name: 'Brand name',
  brand_tagline: 'Tagline',
  default_currency: 'Default currency',
  storefront_url: 'Storefront address',
};

export default async function Settings({ searchParams }) {
  const sb = supabaseServer();
  const user = await currentUser();
  const manager = canManage(user.profile?.role);
  const { data: rows = [] } = await sb.from('settings').select('*').order('setting_key');
  const update = quickUpdate.bind(null, 'settings', 'setting_key', '/settings');

  return (
    <Page title="Settings" sub="Brand details used across listings, showrooms and campaigns.">
      <Flash params={searchParams} />
      {!manager && <div className="note warn" style={{ marginBottom: 16 }}>Only an Owner or Admin can change settings.</div>}
      <div className="grid g2">
        <div className="card">
          <div className="card-head"><h3>Workspace</h3></div>
          <div className="card-body stack">
            {rows.map((s) => (
              <form action={update} key={s.setting_key} className="field" style={{ marginBottom: 0 }}>
                <label>{LABELS[s.setting_key] || s.setting_key}</label>
                <input type="hidden" name="_id" value={s.setting_key} />
                <div className="row" style={{ gap: 8 }}>
                  <input name="setting_value" defaultValue={s.setting_value || ''} disabled={!manager} />
                  {manager && <button className="btn btn-sm">Save</button>}
                </div>
              </form>))}
            {rows.length === 0 && <div className="small muted">No settings recorded.</div>}
          </div>
        </div>
        <div className="card">
          <div className="card-head"><h3>Your account</h3></div>
          <div className="card-body stack" style={{ gap: 8 }}>
            <div className="row"><span className="muted small">Signed in as</span><span className="spacer" />{user.email}</div>
            <div className="row"><span className="muted small">Name</span><span className="spacer" />{user.profile?.full_name || '—'}</div>
            <div className="row"><span className="muted small">Role</span><span className="spacer" style={{ textTransform: 'capitalize' }} />{user.profile?.role}</div>
          </div>
        </div>
      </div>
    </Page>
  );
}
