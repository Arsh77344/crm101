import Link from 'next/link';
import { supabaseServer } from '@/lib/supabase';
import { Page, Empty, when } from '@/components/ui';
import Flash from '@/components/Flash';
export const dynamic = 'force-dynamic';

export default async function Companies({ searchParams }) {
  const sb = supabaseServer();
  const { data: rows = [] } = await sb.from('companies').select('*').order('created_at', { ascending: false });
  return (
    <Page title="Companies" sub={`${rows.length} accounts`}
      actions={<Link className="btn btn-primary" href="/companies/new">New company</Link>}>
      <Flash params={searchParams} />
      <div className="card">
        {rows.length === 0 ? <Empty title="No companies yet" hint="Boutiques, distributors and retailers live here." /> : (
          <div className="t-wrap"><table className="table">
            <thead><tr><th>Company</th><th>Type</th><th>Tier</th><th>Country</th><th>Website</th><th>Added</th></tr></thead>
            <tbody>{rows.map((c) => (
              <tr key={c.company_id}>
                <td><Link className="link" href={`/companies/${c.company_id}`}>{c.company_name}</Link>
                  <div className="small faint">{c.notes?.slice(0, 60)}</div></td>
                <td className="small">{c.company_type || '—'}</td>
                <td className="small">{c.wholesale_tier || '—'}</td>
                <td className="small">{c.country || '—'}</td>
                <td className="small">{c.website || '—'}</td>
                <td className="small faint">{when(c.created_at)}</td>
              </tr>))}</tbody></table></div>
        )}
      </div>
    </Page>
  );
}
