'use client';
import { useMemo, useState } from 'react';
import Link from 'next/link';
import { useQuery, sb, insertRow } from '@/lib/db';
import { Page, Badge, Empty, Loading, ErrorNote, money, when } from '@/components/ui';
import { Bars } from '@/components/Charts';
import Dictate from '@/components/Dictate';

// Who is worth a message today, and why. Each group is a reason to write, not a
// segment to blast: the reason decides what the message should say, which is
// what makes it read as useful rather than as spam.
const DAY = 86400000;

const GROUPS = [
  {
    id: 'cart',
    title: 'Left something in the cart',
    why: 'They chose a piece and stopped. One reminder, with a reason to come back.',
    tone: 'b-amber',
    pick: (p) => p.open_carts > 0 && !p.reminded_recently,
    draft: (p, brand) =>
      `Hi ${p.first}, the ${p.cart_item || 'piece'} you were looking at is still here`
      + `${p.cart_value ? ` — ${money(p.cart_value)}` : ''}. We hold one of each, so it is yours `
      + `if you want it. Shall I keep it aside? — ${brand}`,
  },
  {
    id: 'enquired',
    title: 'Asked and never answered',
    why: 'They enquired more than three days ago and have not ordered.',
    tone: 'b-blue',
    pick: (p) => p.enquired && !p.orders_made && p.days_since_event > 3,
    draft: (p, brand) =>
      `Hi ${p.first}, you had asked about one of our pieces. Happy to answer anything — the weave, `
      + `the blouse, how it drapes. No obligation either way. — ${brand}`,
  },
  {
    id: 'repeat',
    title: 'Bought before, gone quiet',
    why: 'A customer who has not ordered in sixty days. The cheapest sale there is.',
    tone: 'b-green',
    pick: (p) => p.orders_made > 0 && p.days_since_order > 60,
    draft: (p, brand) =>
      `Hi ${p.first}, new pieces are on the loom this month. You bought from us `
      + `${p.days_since_order ? `${Math.round(p.days_since_order)} days ago` : 'before'} — want me `
      + `to send you what is coming before it goes up? — ${brand}`,
  },
  {
    id: 'warm',
    title: 'Watched but never bought',
    why: 'They clicked or looked at a piece and did nothing. Worth one nudge.',
    tone: '',
    pick: (p) => !p.orders_made && p.clicks > 0 && p.days_since_event > 2,
    draft: (p, brand) =>
      `Hi ${p.first}, saw you had a look at our pieces. Tell me the occasion and I will send two `
      + `or three that would suit, rather than the whole catalogue. — ${brand}`,
  },
];

export default function Outreach() {
  const [group, setGroup] = useState('cart');
  const [chosen, setChosen] = useState({});
  const [text, setText] = useState('');
  const [err, setErr] = useState('');

  const q = useQuery(async (c) => {
    const [people, carts, events, orders, settings] = await Promise.all([
      c.from('contacts').select('*').limit(500),
      c.from('carts').select('*,products(public_product_name,retail_price)').eq('status', 'Open'),
      c.from('journey_events').select('contact_id,kind,occurred_at').limit(2000),
      c.from('orders').select('contact_id,total,order_status,ordered_at'),
      c.from('settings').select('setting_key,setting_value'),
    ]);
    if (people.error) throw people.error;
    const s = {};
    (settings.data || []).forEach((r) => { s[r.setting_key] = r.setting_value; });
    return { people: people.data || [], carts: carts.data || [], events: events.data || [],
             orders: orders.data || [], settings: s };
  }, []);

  const brand = q.data?.settings?.brand_name || 'us';

  // One row per person with the few facts a message needs, worked out once, so
  // the rules above read as rules rather than as queries.
  const profiles = useMemo(() => {
    if (!q.data) return [];
    const now = Date.now();
    const cartsBy = {}, eventsBy = {}, ordersBy = {};
    q.data.carts.forEach((k) => { (cartsBy[k.contact_id] ||= []).push(k); });
    q.data.events.forEach((e) => { (eventsBy[e.contact_id] ||= []).push(e); });
    q.data.orders.filter((o) => ['Processing', 'Fulfilled'].includes(o.order_status))
      .forEach((o) => { (ordersBy[o.contact_id] ||= []).push(o); });

    return q.data.people.map((c) => {
      const carts = cartsBy[c.contact_id] || [];
      const evs = eventsBy[c.contact_id] || [];
      const ords = ordersBy[c.contact_id] || [];
      const lastEvent = evs.reduce((t, e) =>
        Math.max(t, new Date(e.occurred_at).getTime() || 0), 0);
      const lastOrder = ords.reduce((t, o) =>
        Math.max(t, new Date(o.ordered_at).getTime() || 0), 0);
      return {
        ...c,
        first: (c.full_name || '').split(' ')[0] || 'there',
        open_carts: carts.length,
        cart_value: carts.reduce((n, k) =>
          n + Number(k.value ?? k.products?.retail_price ?? 0), 0),
        cart_item: carts[0]?.products?.public_product_name,
        reminded_recently: carts.some((k) => k.reminded_at
          && now - new Date(k.reminded_at).getTime() < 7 * DAY),
        clicks: evs.filter((e) => /click/i.test(e.kind)).length,
        enquired: evs.some((e) => /enquir|whatsapp_in|ig_dm/i.test(e.kind)),
        orders_made: ords.length,
        spent: ords.reduce((n, o) => n + Number(o.total || 0), 0),
        days_since_event: lastEvent ? (now - lastEvent) / DAY : 999,
        days_since_order: lastOrder ? (now - lastOrder) / DAY : null,
      };
    });
  }, [q.data]);

  const active = GROUPS.find((g) => g.id === group);
  const matched = profiles.filter((p) => active.pick(p));
  const reachable = matched.filter((p) => p.whatsapp_opt_in && p.phone_number);
  const blocked = matched.length - reachable.length;
  const picked = reachable.filter((p) => chosen[p.contact_id]);

  function body(p) {
    return (text || active.draft(p, brand))
      .replace(/\{name\}/g, p.first)
      .replace(/\{piece\}/g, p.cart_item || 'the piece');
  }

  function waLink(p) {
    const phone = String(p.phone_number).replace(/\D/g, '');
    return `https://wa.me/${phone.length === 10 ? `91${phone}` : phone}`
      + `?text=${encodeURIComponent(body(p))}`;
  }

  // Opening WhatsApp is the sending. Recording it is what stops the same person
  // being chased twice next week.
  async function markSent(p) {
    try {
      await insertRow('journey_events', {
        contact_id: p.contact_id, kind: 'whatsapp_out', source: 'Outreach',
        detail: active.title, occurred_at: new Date().toISOString(),
      });
      if (active.id === 'cart' && p.open_carts) {
        await sb().from('carts')
          .update({ reminded_at: new Date().toISOString(), reminders_sent: 1 })
          .eq('contact_id', p.contact_id).eq('status', 'Open');
      }
      q.reload();
    } catch (e) { setErr(e.message || String(e)); }
  }

  return (
    <Page title="Outreach"
      sub="Who is worth a message today, and what to say to each of them."
      actions={<Link className="btn btn-sm" href="/contacts">Contacts</Link>}>
      <ErrorNote error={q.error || err} />

      <div className="note plain small" style={{ marginBottom: 14 }}>
        Each group is a <strong>reason to write</strong>, not a list to blast. Only people who
        agreed to WhatsApp appear here; the rest are counted and left alone, because messaging
        without consent is what gets a number blocked.
      </div>

      {q.loading ? <Loading /> : (
        <div className="grid outreach-grid" style={{ gridTemplateColumns: '300px 1fr', gap: 14 }}>
          <div className="stack" style={{ gap: 10 }}>
            {GROUPS.map((g) => {
              const all = profiles.filter(g.pick).length;
              const ok = profiles.filter(
                (p) => g.pick(p) && p.whatsapp_opt_in && p.phone_number).length;
              return (
                <button key={g.id} onClick={() => { setGroup(g.id); setChosen({}); setText(''); }}
                  className={`card group-card ${group === g.id ? 'on' : ''}`}>
                  <div className="row" style={{ justifyContent: 'space-between' }}>
                    <strong className="small">{g.title}</strong>
                    <span className={`badge ${g.tone}`}>{ok}</span>
                  </div>
                  <div className="small muted" style={{ marginTop: 3 }}>{g.why}</div>
                  {all > ok && (
                    <div className="small faint" style={{ marginTop: 3 }}>
                      {all - ok} more without WhatsApp consent.
                    </div>)}
                </button>);
            })}
          </div>

          <div className="stack" style={{ gap: 14 }}>
            <div className="card">
              <div className="card-head"><h3>{active.title}</h3>
                <span className="small faint">{reachable.length} to write to</span></div>
              <div className="card-body">
                <div className="field">
                  <label>The message</label>
                  <textarea value={text} style={{ minHeight: 86 }}
                    placeholder={reachable[0] ? active.draft(reachable[0], brand) : active.draft(
                      { first: 'Asha', cart_item: 'Midnight Blue', cart_value: 13500 }, brand)}
                    onChange={(e) => setText(e.target.value)} />
                  <Dictate onText={(f) => setText((cur) => f(cur))} />
                  <span className="hint">
                    Leave it empty and each person gets the draft above, written for them.
                    <span className="mono"> {'{name}'}</span> and
                    <span className="mono"> {'{piece}'}</span> are filled in per person.
                  </span>
                </div>
                {blocked > 0 && (
                  <div className="note warn small">
                    <strong>{blocked} {blocked === 1 ? 'person fits' : 'people fit'} this reason
                    but cannot be messaged.</strong> No WhatsApp consent, or no number on file.
                    Ask them when they next write to you; do not tick it on their behalf.
                  </div>)}
              </div>
            </div>

            <div className="card">
              <div className="card-head"><h3>Who</h3>
                {picked.length > 0 && (
                  <span className="small faint">{picked.length} ticked</span>)}</div>
              <div className="card-body">
                {reachable.length === 0
                  ? <Empty title="Nobody right now"
                      hint="Good news for the cart list, less good for the quiet-customer one." />
                  : <div className="t-wrap"><table className="table">
                      <thead><tr><th /><th>Name</th><th>Why them</th>
                        <th className="num">Spent</th><th /></tr></thead>
                      <tbody>
                        {reachable.slice(0, 40).map((p) => (
                          <tr key={p.contact_id}>
                            <td><input type="checkbox" checked={Boolean(chosen[p.contact_id])}
                              onChange={(e) => setChosen((c) =>
                                ({ ...c, [p.contact_id]: e.target.checked }))} /></td>
                            <td className="small"><strong>{p.full_name}</strong>
                              <div className="faint">{p.city || p.country || ''}</div></td>
                            <td className="small muted">
                              {active.id === 'cart'
                                ? `${p.cart_item || 'A piece'} · ${money(p.cart_value)}`
                                : active.id === 'repeat'
                                  ? `${p.orders_made} orders · last ${Math.round(p.days_since_order)} days ago`
                                  : active.id === 'enquired'
                                    ? `asked ${Math.round(p.days_since_event)} days ago`
                                    : `${p.clicks} clicks, no order`}</td>
                            <td className="num small">{money(p.spent)}</td>
                            <td style={{ textAlign: 'right' }}>
                              <a className="btn btn-sm" href={waLink(p)} target="_blank"
                                rel="noreferrer" onClick={() => markSent(p)}>
                                Open WhatsApp</a></td>
                          </tr>))}
                      </tbody>
                    </table></div>}
                {reachable.length > 40 && (
                  <div className="small faint" style={{ marginTop: 8 }}>
                    Showing 40 of {reachable.length}.</div>)}
              </div>
            </div>

            <div className="card">
              <div className="card-head"><h3>Reachable in each group</h3></div>
              <div className="card-body">
                <Bars data={GROUPS.map((g) => ({
                  label: g.title,
                  value: profiles.filter(
                    (p) => g.pick(p) && p.whatsapp_opt_in && p.phone_number).length,
                }))} caption="People you may write to right now, by reason." />
              </div>
            </div>
          </div>
        </div>)}
    </Page>
  );
}
