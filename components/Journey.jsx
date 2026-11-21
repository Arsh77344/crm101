'use client';
import { useQuery } from '@/lib/db';
import { Badge, money, when } from '@/components/ui';
import { Bars } from '@/components/Charts';

// What a person has actually done with us, read from the events rather than
// typed in, so it cannot drift from the truth.
const STEPS = [
  [['Saw ad', 'impression'], 'Saw an ad'],
  [['Clicked', 'click', 'link_click'], 'Clicked through'],
  [['Viewed product', 'showroom_view', 'product_view'], 'Looked at a piece'],
  [['Added to cart', 'cart'], 'Put one aside'],
  [['Enquired', 'enquiry', 'whatsapp_in', 'ig_dm'], 'Asked about it'],
  [['Ordered', 'order'], 'Bought'],
  [['Delivered', 'delivered'], 'Received it'],
];

// The same thing gets written under different names depending on what wrote it.
const countFor = (counts, kinds) =>
  kinds.reduce((n, k) => n + (counts[k] || 0), 0);

const KIND_TONE = {
  Ordered: 'b-green', Delivered: 'b-green', 'Added to cart': 'b-amber',
  Enquired: 'b-blue', Unsubscribed: 'b-red', Returned: 'b-red',
};

export default function Journey({ contactId }) {
  const q = useQuery(async (c) => {
    if (!contactId) return null;
    const [person, events, carts, orders] = await Promise.all([
      c.from('contacts')
        .select('contact_id,lifecycle_stage,whatsapp_opt_in,email_opt_in,city,state')
        .eq('contact_id', contactId).maybeSingle(),
      c.from('journey_events')
        .select('*,products(public_product_name),campaigns(campaign_name)')
        .eq('contact_id', contactId).order('occurred_at', { ascending: false }).limit(40),
      c.from('carts').select('*,products(public_product_name,retail_price)')
        .eq('contact_id', contactId).eq('status', 'Open').order('added_at'),
      c.from('orders').select('total,order_status,ordered_at').eq('contact_id', contactId),
    ]);
    const paid = (orders.data || []).filter((o) =>
      ['Processing', 'Fulfilled'].includes(o.order_status));
    return {
      profile: {
        ...(person.data || {}),
        orders_made: paid.length,
        spent: paid.reduce((n, o) => n + Number(o.total || 0), 0),
        last_event_at: (events.data || [])[0]?.occurred_at || null,
      },
      events: events.data || [], carts: carts.data || [],
    };
  }, [contactId]);

  if (!contactId) return null;
  if (q.loading) return <div className="small faint" style={{ padding: 12 }}>Reading the journey…</div>;

  const p = q.data?.profile;
  const events = q.data?.events || [];
  const carts = q.data?.carts || [];
  const counts = events.reduce((acc, e) => { acc[e.kind] = (acc[e.kind] || 0) + 1; return acc; }, {});
  const reached = STEPS.filter(([kinds]) => countFor(counts, kinds)).length;
  const seen = countFor(counts, STEPS[0][0]);
  const clicked = countFor(counts, STEPS[1][0]);

  return (
    <div className="stack" style={{ gap: 14 }}>
      <div className="card">
        <div className="card-head"><h3>Where they are</h3>
          {p?.lifecycle_stage && <Badge>{p.lifecycle_stage}</Badge>}</div>
        <div className="card-body">
          <div className="journey">
            {STEPS.map(([kinds, label], i) => {
              const n = countFor(counts, kinds);
              return (
                <div key={label} className={`journey-step ${n ? 'done' : ''}`}>
                  <div className="journey-dot">{n > 1 ? n : ''}</div>
                  <div className="journey-label">{label}</div>
                  {i < STEPS.length - 1 && <div className="journey-line" />}
                </div>);
            })}
          </div>
          <div className="small muted" style={{ marginTop: 10 }}>
            {reached === 0
              ? 'Nothing recorded yet. Events arrive from tracked links, orders and anything logged by hand.'
              : `Reached ${reached} of ${STEPS.length} steps. `
                + (p?.last_event_at ? `Last activity ${when(p.last_event_at)}.` : '')}
          </div>
          {p && (
            <div className="grid g2" style={{ gap: 8, marginTop: 12 }}>
              <div className="small"><strong>{p.orders_made || 0}</strong> orders
                {' · '}<strong>{money(p.spent || 0)}</strong> spent</div>
              <div className="small"><strong>{seen}</strong> ads seen
                {' · '}<strong>{clicked}</strong> clicks</div>
            </div>)}
          <div className="row wrap small" style={{ gap: 6, marginTop: 10 }}>
            <span className={`badge ${p?.whatsapp_opt_in ? 'b-green' : ''}`}>
              WhatsApp {p?.whatsapp_opt_in ? 'allowed' : 'not allowed'}</span>
            <span className={`badge ${p?.email_opt_in ? 'b-green' : ''}`}>
              Email {p?.email_opt_in ? 'allowed' : 'not allowed'}</span>
          </div>
        </div>
      </div>

      {carts.length > 0 && (
        <div className="card">
          <div className="card-head"><h3>Left in the cart</h3>
            <Badge className="b-amber">{carts.length}</Badge></div>
          <div className="card-body stack" style={{ gap: 7 }}>
            {carts.map((c) => (
              <div key={c.cart_id} className="row small" style={{ justifyContent: 'space-between' }}>
                <span className="legend-name">
                  {c.products?.public_product_name || 'A piece that has since gone'}</span>
                <span className="faint">{when(c.added_at)}</span>
                <strong>{money(c.value ?? c.products?.retail_price ?? 0)}</strong>
              </div>))}
            <div className="small faint">
              {carts.some((c) => c.reminders_sent > 0)
                ? 'Already reminded. A second reminder usually annoys more than it sells.'
                : 'Worth one reminder, with a reason to come back.'}
            </div>
          </div>
        </div>)}

      <div className="card">
        <div className="card-head"><h3>What they did</h3>
          <span className="small faint">{events.length}</span></div>
        <div className="card-body">
          {events.length === 0
            ? <div className="small faint">Nothing recorded against this person yet.</div>
            : <div className="stack" style={{ gap: 6 }}>
                {events.slice(0, 12).map((e) => (
                  <div key={e.event_id} className="row small" style={{ gap: 8, alignItems: 'baseline' }}>
                    <span className={`badge ${KIND_TONE[e.kind] || ''}`}>{e.kind}</span>
                    <span className="legend-name">
                      {e.products?.public_product_name || e.campaigns?.campaign_name
                        || e.detail || e.channel || '—'}</span>
                    <span className="faint">{when(e.occurred_at, true)}</span>
                  </div>))}
                {events.length > 12 && (
                  <div className="small faint">and {events.length - 12} older.</div>)}
              </div>}
        </div>
      </div>
    </div>
  );
}
