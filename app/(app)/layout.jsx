'use client';
import { useEffect, useState } from 'react';
import { useRouter, usePathname } from 'next/navigation';
import Link from 'next/link';
import { useSession, canManage } from '@/lib/session';
import { sb } from '@/lib/db';
import { initials } from '@/components/ui';
import { LightboxProvider } from '@/components/Lightbox';
import { HOME, NAV, sectionOf } from '@/lib/nav';

export default function WorkspaceLayout({ children }) {
  const { loading, user, profile } = useSession();
  const router = useRouter();
  const path = usePathname();
  const [theme, setTheme] = useState('light');
  const [navOpen, setNavOpen] = useState(false);
  // Which sections stand open. Remembered the way the theme already is, so the
  // rail looks the same on the next visit.
  const [open, setOpen] = useState([]);

  useEffect(() => {
    try { setTheme(localStorage.getItem('cos-theme') || 'light'); } catch { /* ignore */ }
    try {
      const kept = JSON.parse(localStorage.getItem('cos-nav') || 'null');
      if (Array.isArray(kept)) setOpen(kept.filter((x) => NAV.some(([g]) => g === x)));
    } catch { /* ignore */ }
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

  function toggleSection(group) {
    setOpen((cur) => {
      const next = cur.includes(group) ? cur.filter((g) => g !== group) : [...cur, group];
      try { localStorage.setItem('cos-nav', JSON.stringify(next)); } catch { /* ignore */ }
      return next;
    });
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
  const current = sectionOf(here);

  return (
    <LightboxProvider>
    <div className="shell">
      <aside className="sidebar">
        <Link href="/" className="brand" onClick={() => setNavOpen(false)}>
          <div className="brand-mark">Z</div>
          <div><span className="brand-name">Zarivia</span><span className="brand-sub">Business workspace</span></div>
        </Link>
        <button className="menu-btn" onClick={() => setNavOpen((v) => !v)} aria-label="Menu">☰ Menu</button>
        <nav className={`nav ${navOpen ? 'show' : ''}`}>
          <Link href={HOME[0]} className={`nav-home ${here === '/' ? 'on' : ''}`}
            onClick={() => setNavOpen(false)}>
            <span className="ico">{HOME[2]}</span>{HOME[1]}
          </Link>

          {NAV.map(([group, items]) => {
            // The section holding the page you are on is open whether or not you
            // opened it, so you can always see where you are.
            const live = group === current;
            const shown = live || open.includes(group);
            return (
              <div className="nav-sec" key={group}>
                <button type="button" className={`nav-sec-head ${shown ? 'open' : ''}`}
                  aria-expanded={shown} onClick={() => toggleSection(group)}>
                  <span className="caret" aria-hidden="true">{shown ? '▾' : '▸'}</span>
                  <span className="nav-sec-name">{group}</span>
                  {!shown && <span className="nav-sec-n">{items.length}</span>}
                  {!shown && live && <span className="nav-dot" aria-hidden="true" />}
                </button>
                {shown && (
                  <div className="nav-sec-body">
                    {items.map(([href, label, ico]) => (
                      <Link key={href} href={href} className={here.startsWith(href) ? 'on' : ''}
                        onClick={() => setNavOpen(false)}>
                        <span className="ico">{ico}</span>{label}
                      </Link>
                    ))}
                  </div>)}
              </div>
            );
          })}
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
          <div className="foot-acts">
            <button className="theme-btn" onClick={toggleTheme}>
              {theme === 'dark' ? 'Light mode' : 'Dark mode'}
            </button>
            <button className="theme-btn" onClick={signOut}>Sign out</button>
          </div>
        </div>
      </aside>
      <main className="main">
        {children}
      </main>
    </div>
    </LightboxProvider>
  );
}
