'use client';
import { useEffect, useState } from 'react';
import { useRouter, usePathname } from 'next/navigation';
import Link from 'next/link';
import { useSession, canManage } from '@/lib/session';
import { sb } from '@/lib/db';
import { initials } from '@/components/ui';

const NAV = [
  ['Sell', [
    ['/', 'Dashboard', '◉'],
    ['/products', 'Products', '▣'],
    ['/launch', 'Product launch', '✦'],
    ['/orders', 'Orders', '⊞'],
    ['/showrooms', 'Showrooms', '◫'],
  ]],
  ['Fulfil', [
    ['/shipments', 'Shipments', '➤'],
    ['/payments', 'Payments', '₹'],
    ['/returns', 'Returns', '↩'],
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
  ['Make & spend', [
    ['/suppliers', 'Weavers & suppliers', '⚒'],
    ['/expenses', 'Expenses', '⊟'],
    ['/finance', 'Profit & loss', '◪'],
  ]],
  ['Run', [
    ['/tasks', 'Tasks', '✓'],
    ['/automations', 'Automations', '⟳'],
    ['/integrations', 'Integrations', '⚯'],
    ['/team', 'Team & roles', '☰'],
    ['/settings', 'Settings', '⚙'],
  ]],
];

export default function WorkspaceLayout({ children }) {
  const { loading, user, profile } = useSession();
  const router = useRouter();
  const path = usePathname();
  const [theme, setTheme] = useState('light');

  useEffect(() => {
    try { setTheme(localStorage.getItem('cos-theme') || 'light'); } catch { /* ignore */ }
  }, []);

  useEffect(() => {
    if (!loading && !user) router.replace('/login');
  }, [loading, user, router]);

  function toggleTheme() {
    const next = theme === 'dark' ? 'light' : 'dark';
    setTheme(next);
    document.documentElement.setAttribute('data-theme', next);
    try { localStorage.setItem('cos-theme', next); } catch { /* ignore */ }
  }

  async function signOut() {
    await sb().auth.signOut();
    router.replace('/login');
  }

  if (loading) return <div className="loading" style={{ paddingTop: 120 }}>Loading your workspace…</div>;
  if (!user) return <div className="loading" style={{ paddingTop: 120 }}>Taking you to the sign-in page…</div>;

  const role = profile?.role || 'sales';
  const clean = (p) => (p.length > 1 ? p.replace(/\/$/, '') : p);
  const here = clean(path || '/');

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark">C</div>
          <div><span className="brand-name">Commerce OS</span><span className="brand-sub">Business workspace</span></div>
        </div>
        <nav className="nav">
          {NAV.map(([group, items]) => (
            <div key={group}>
              <div className="nav-group">{group}</div>
              {items.map(([href, label, ico]) => {
                const on = href === '/' ? here === '/' : here.startsWith(href);
                return (
                  <Link key={href} href={href} className={on ? 'on' : ''}>
                    <span className="ico">{ico}</span>{label}
                  </Link>
                );
              })}
            </div>
          ))}
        </nav>
        <div className="side-foot">
          <div className="row" style={{ gap: 8 }}>
            <div className="avatar">{initials(profile?.full_name || user.email)}</div>
            <div style={{ minWidth: 0 }}>
              <div className="who" style={{ overflow: 'hidden', textOverflow: 'ellipsis' }}>
                {profile?.full_name || user.email}
              </div>
              <div className="role">
                {role}{canManage(role) ? '' : ' · limited'}
              </div>
            </div>
          </div>
          <button className="theme-btn" onClick={toggleTheme}>
            {theme === 'dark' ? '☀ Light mode' : '☾ Dark mode'}
          </button>
          <div><button className="theme-btn" onClick={signOut}>Sign out</button></div>
        </div>
      </aside>
      <main className="main">{children}</main>
    </div>
  );
}
