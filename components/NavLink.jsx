'use client';
import Link from 'next/link';
import { usePathname } from 'next/navigation';

export default function NavLink({ href, label, ico }) {
  const path = usePathname();
  const on = href === '/' ? path === '/' : path.startsWith(href);
  return (
    <Link className={on ? 'on' : ''} href={href}>
      <span className="ico">{ico}</span>{label}
    </Link>
  );
}
