import Link from 'next/link';
import { supabaseServer } from '@/lib/supabase';
import { Page, Badge, Empty, when } from '@/components/ui';
import Flash from '@/components/Flash';

export const dynamic = 'force-dynamic';
const STAGES = ['', 'New', 'Lead', 'Opportunity', 'Customer', 'Dormant'];

export default async function Contacts({ searchParams }) {
  const sb = supabaseServer();
  const q = searchParams?.q || '';
  const stage = searchParams?.stage || '';
  const type = searchParams?.type || '';

  let query = sb.from('contacts').select('*').order('created_at', { ascending: false }).limit(500);
  if (q) query = query.or(`full_name.ilike.%${q}%,email.ilike.%${q}%,phone_number.ilike.%${q}%,business_category.ilike.%${q}%`);
  if (stage) query = query.eq('lifecycle_stage', stage);
  if (type) query = query.eq('contact_type', type);
  const { data: rows = [], error } = await query;

  return (
    <Page title="Contacts" sub={`${rows.length} people in the book`}
      actions={<Link className="btn btn-primary" href="/contacts/new">New contact</Link>}>
      <Flash params={searchParams} />
      {error && <div className="note warn">{error.message}</div>}

      <form className="toolbar">
        <div className="search"><span className="mag">⌕</span>
          <input name="q" defaultValue={q} placeholder="Search name, email, phone…" /></div>
        <select name="type" defaultValue={type} style={{ padding: '8px 10px', borderRadius: 8, border: '1px solid var(--line)' }}>
          <option value="">All types</option><option>B2B</option><option>B2C</option><option>Both</option>
        </select>
        <button className="btn btn-sm">Filter</button>
        <span className="spacer" />
        {STAGES.map((s) => (
          <Link key={s || 'all'} className={`chip ${stage === s ? 'on' : ''}`}
            href={`/contacts${s ? `?stage=${s}` : ''}`}>{s || 'All'}</Link>
        ))}
      </form>

      <div className="card">
        {rows.length === 0 ? (
          <Empty title="No contacts match" hint="Try a different filter, or add someone new.">
            <Link className="btn btn-primary" href="/contacts/new">New contact</Link>
          </Empty>
        ) : (
          <div className="t-wrap"><table className="table">
            <thead><tr><th>Name</th><th>Type</th><th>Stage</th><th>Contact</th><th>Country</th>
              <th className="num">Score</th><th>Added</th></tr></thead>
            <tbody>{rows.map((c) => (
              <tr key={c.contact_id}>
                <td><Link className="link" href={`/contacts/${c.contact_id}`}>{c.full_name || 'Unnamed'}</Link>
                  <div className="small faint">{c.business_category || c.niche || ''}</div></td>
                <td className="small">{c.contact_type}</td>
                <td><Badge>{c.lifecycle_stage}</Badge></td>
                <td className="small">{c.email || '—'}<div className="faint">{c.phone_number || ''}</div></td>
                <td className="small">{c.country || '—'}</td>
                <td className="num">{c.lead_score ?? 0}</td>
                <td className="small faint">{when(c.created_at)}</td>
              </tr>))}
            </tbody></table></div>
        )}
      </div>
    </Page>
  );
}
