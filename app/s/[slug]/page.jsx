import { supabaseServer } from '@/lib/supabase';
import { money } from '@/components/ui';
export const dynamic = 'force-dynamic';

export default async function PublicShowroom({ params }) {
  const sb = supabaseServer();
  const s = (await sb.from('showrooms').select('*').eq('slug', params.slug).maybeSingle()).data;
  if (!s) {
    return <div className="auth"><div className="auth-card"><h1>Not available</h1>
      <p className="sub">This showroom link is closed or does not exist.</p></div></div>;
  }
  const picks = (await sb.from('showroom_products')
    .select('custom_price,sort_order,products(public_product_name,colour,fabric,weave_or_motif,description,retail_price,wholesale_price,currency)')
    .eq('showroom_id', s.showroom_id).order('sort_order')).data || [];
  await sb.from('showroom_views').insert({ showroom_id: s.showroom_id });

  const priceOf = (p) => {
    if (p.custom_price) return money(p.custom_price);
    if (s.pricing_mode === 'Retail') return money(p.products?.retail_price, p.products?.currency);
    if (s.pricing_mode === 'Wholesale') return money(p.products?.wholesale_price, p.products?.currency);
    return null;
  };

  return (
    <div style={{ background: 'var(--canvas)', minHeight: '100vh' }}>
      <div style={{ maxWidth: 940, margin: '0 auto', padding: '56px 24px 80px' }}>
        <div style={{ fontSize: 11, letterSpacing: '.18em', textTransform: 'uppercase', color: 'var(--faint)' }}>Private selection</div>
        <h1 style={{ fontFamily: 'var(--serif)', fontSize: 34, margin: '8px 0 10px' }}>{s.title}</h1>
        {s.intro_text && <p style={{ color: 'var(--muted)', maxWidth: 560, fontSize: 15 }}>{s.intro_text}</p>}

        <div className="grid g3" style={{ marginTop: 34 }}>
          {picks.map((p, i) => (
            <div className="card" key={i}>
              <div style={{ height: 210, background: 'linear-gradient(140deg,#f1e7dd,#e6d8ec)', borderRadius: '12px 12px 0 0',
                display: 'grid', placeItems: 'center', color: 'var(--faint)', fontFamily: 'var(--serif)' }}>
                {p.products?.colour || 'Piece'}
              </div>
              <div className="card-body">
                <div style={{ fontFamily: 'var(--serif)', fontSize: 16 }}>{p.products?.public_product_name}</div>
                <div className="small muted" style={{ marginTop: 3 }}>
                  {[p.products?.fabric, p.products?.weave_or_motif].filter(Boolean).join(' · ')}
                </div>
                {p.products?.description && <p className="small" style={{ marginTop: 8 }}>{p.products.description}</p>}
                {priceOf(p) && <div style={{ fontFamily: 'var(--serif)', fontSize: 18, color: 'var(--accent)', marginTop: 8 }}>{priceOf(p)}</div>}
              </div>
            </div>))}
          {picks.length === 0 && <p className="muted">No pieces have been added to this selection yet.</p>}
        </div>

        {s.cta_text && (
          <div className="card" style={{ marginTop: 32, padding: 22, textAlign: 'center' }}>
            <div style={{ fontFamily: 'var(--serif)', fontSize: 18 }}>{s.cta_text}</div>
          </div>)}
      </div>
    </div>
  );
}
