import { redirect } from 'next/navigation';
import { currentUser, supabaseServer, canManage } from '@/lib/supabase';
import { initials } from '@/components/ui';
import NavLink from '@/components/NavLink';

const NAV = [
  ['Sell', [
    ['/', 'Dashboard', '◉'],
    ['/products', 'Products', '▣'],
    ['/launch', 'Product launch', '✦'],
    ['/orders', 'Orders', '⊞'],
    ['/showrooms', 'Showrooms', '◫'],
  ]],
  ['Customers', [
    ['/contacts', 'Contacts', '◐'],
    ['/companies', 'Companies', '⌂'],
    ['/pipeline', 'Pipeline', '⇄'],
    ['/activities', 'Activities', '✎'],
  ]],
  ['Marketing', [
    ['/campaigns', 'Campaigns', '◈'],
    ['/calendar', 'Content calendar', '▦'],
    ['/performance', 'Performance', '◢'],
    ['/consent', 'Consent centre', '⚖'],
  ]],
  ['Setup', [
    ['/integrations', 'Integrations', '⚯'],
    ['/team', 'Team & roles', '☰'],
    ['/settings', 'Settings', '⚙'],
  ]],
];

async function signOut() {
  'use server';
  const sb = supabaseServer();
  await sb.auth.signOut();
  redirect('/login');
}

export default async function WorkspaceLayout({ children }) {
  const user = await currentUser();
  if (!user) redirect('/login');
  const role = user.profile?.role || 'sales';

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark">C</div>
          <div>
            <span className="brand-name">Commerce OS</span>
            <span className="brand-sub">Business workspace</span>
          </div>
        </div>
        <nav className="nav">
          {NAV.map(([group, items]) => (
            <div key={group}>
              <div className="nav-group">{group}</div>
              {items.map(([href, label, ico]) => (
                <NavLink key={href} href={href} ico={ico} label={label} />
              ))}
            </div>
          ))}
        </nav>
        <div className="side-foot">
          <div className="row" style={{ gap: 8 }}>
            <div className="avatar">{initials(user.profile?.full_name || user.email)}</div>
            <div style={{ minWidth: 0 }}>
              <div className="who" style={{ overflow: 'hidden', textOverflow: 'ellipsis' }}>
                {user.profile?.full_name || user.email}
              </div>
              <div style={{ fontSize: 11, textTransform: 'capitalize' }}>{role}{canManage(role) ? '' : ' · limited'}</div>
            </div>
          </div>
          <form action={signOut}><button>Sign out</button></form>
        </div>
      </aside>
      <main className="main">{children}</main>
    </div>
  );
}
