'use client';
import { useState } from 'react';
import Link from 'next/link';
import { useQuery, insertRow, removeRow, formValues } from '@/lib/db';
import { Page, Stat, Loading, ErrorNote, Empty, when } from '@/components/ui';

const BASE = `${process.env.NEXT_PUBLIC_SUPABASE_URL}/functions/v1/go`;

export default function Links() {
  const [err, setErr] = useState('');
  const [copied, setCopied] = useState('');

  const q = useQuery(async (c) => {
    const [links, products, collections, campaigns, settings] = await Promise.all([
      c.from('links').select('*,products(public_product_name),collections(name),campaigns(campaign_name)')
        .order('created_at', { ascending: false }),
      c.from('products').select('product_id,public_product_name,internal_sku').order('public_product_name'),
      c.from('collections').select('collection_id,name').order('name'),
      c.from('campaigns').select('campaign_id,campaign_name').order('campaign_name'),
      c.from('settings').select('setting_key,setting_value').eq('setting_key', 'whatsapp_number'),
    ]);
    if (links.error) throw links.error;
    return { links: links.data || [], products: products.data || [], collections: collections.data || [],
      campaigns: campaigns.data || [], number: settings.data?.[0]?.setting_value || '' };
  }, []);

  const d = q.data;

  async function create(e) {
    e.preventDefault();
    const v = formValues(e.target);
    setErr('');
    try {
      const code = Math.random().toString(36).slice(2, 8);
      const product = d.products.find((p) => p.product_id === v.product_id);
      const prefill = v.prefill || (product ? `Hi, I'd like to know more about ${product.public_product_name}` : 'Hi, I have a question');
      const target = v.kind === 'whatsapp'
        ? `https://wa.me/${(d.number || '').replace(/[^0-9]/g, '')}?text=${encodeURIComponent(prefill)}`
        : v.target;
      if (v.kind === 'whatsapp' && !d.number) throw new Error('Set the WhatsApp number on Settings first.');
      await insertRow('links', {
        code, label: v.label, kind: v.kind, target, prefill,
        product_id: v.product_id || null, collection_id: v.collection_id || null,
        campaign_id: v.campaign_id || null,
      });
      e.target.reset(); q.reload();
    } catch (e2) { setErr(e2.message || String(e2)); }
  }

  async function drop(id) {
    try { await removeRow('links', 'link_id', id); q.reload(); } catch (e2) { setErr(e2.message); }
  }

  function copy(code) {
    navigator.clipboard?.writeText(`${BASE}/${code}`);
    setCopied(code); setTimeout(() => setCopied(''), 1600);
  }

  if (q.loading) return <Page title="Tracked links"><Loading /></Page>;
  const total = d.links.reduce((s, l) => s + (l.clicks || 0), 0);

  return (
    <Page title="Tracked links"
      sub="Every click is counted and attached to the person and the campaign.">
      <ErrorNote error={q.error || err} />

      {!d.number && (
        <div className="note" style={{ marginBottom: 14 }}>
          Add your WhatsApp number on <Link className="link" href="/settings">Settings</Link> to make
          click-to-WhatsApp links. Plain web links work without it.
        </div>)}

      <div className="kpi-row" style={{ marginBottom: 16 }}>
        <Stat label="Links" value={d.links.length} />
        <Stat label="Clicks" value={total} />
        <Stat label="Best link" value={d.links.length ? Math.max(0, ...d.links.map((l) => l.clicks || 0)) : 0}
          delta={d.links.length ? d.links.slice().sort((a, b) => (b.clicks || 0) - (a.clicks || 0))[0]?.label : ''} />
      </div>

      <div className="grid" style={{ gridTemplateColumns: '1fr 330px' }}>
        <div className="card">
          <div className="card-head"><h3>Your links</h3></div>
          {d.links.length === 0
            ? <Empty title="No links yet" hint="Make one for a piece and put it in a post or a story." />
            : (<div className="t-wrap"><table className="table">
                <thead><tr><th>Label</th><th>Goes to</th><th>Attached to</th>
                  <th className="num">Clicks</th><th></th></tr></thead>
                <tbody>{d.links.map((l) => (
                  <tr key={l.link_id}>
                    <td><strong className="small">{l.label || l.code}</strong>
                      <div className="small faint mono">/go/{l.code}</div></td>
                    <td className="small muted">{l.kind === 'whatsapp' ? 'WhatsApp chat' : 'Web page'}
                      {l.prefill && <div className="small faint">“{l.prefill.slice(0, 44)}…”</div>}</td>
                    <td className="small">{l.products?.public_product_name || l.collections?.name
                      || l.campaigns?.campaign_name || '—'}</td>
                    <td className="num">{l.clicks || 0}</td>
                    <td style={{ textAlign: 'right' }}>
                      <button className="btn btn-sm" onClick={() => copy(l.code)}>
                        {copied === l.code ? 'Copied' : 'Copy'}</button>
                      <button className="btn btn-sm btn-ghost" onClick={() => drop(l.link_id)}>Delete</button>
                    </td>
                  </tr>))}</tbody></table></div>)}
        </div>

        <form className="card" onSubmit={create}>
          <div className="card-head"><h3>New link</h3></div>
          <div className="card-body">
            <div className="field"><label>Label</label>
              <input name="label" required placeholder="Festive reel — magenta" /></div>
            <div className="field"><label>Kind</label>
              <select name="kind" defaultValue="whatsapp">
                <option value="whatsapp">Opens a WhatsApp chat</option>
                <option value="url">Opens a web page</option></select></div>
            <div className="field"><label>Web address</label>
              <input name="target" placeholder="https://… (web links only)" /></div>
            <div className="field"><label>About which piece</label>
              <select name="product_id" defaultValue=""><option value="">—</option>
                {d.products.map((p) => (
                  <option key={p.product_id} value={p.product_id}>{p.public_product_name}</option>))}</select>
              <span className="hint">The chat opens with a message already written about it.</span></div>
            <div className="field"><label>Or a collection</label>
              <select name="collection_id" defaultValue=""><option value="">—</option>
                {d.collections.map((c) => (
                  <option key={c.collection_id} value={c.collection_id}>{c.name}</option>))}</select></div>
            <div className="field"><label>Count it towards</label>
              <select name="campaign_id" defaultValue=""><option value="">no campaign</option>
                {d.campaigns.map((c) => (
                  <option key={c.campaign_id} value={c.campaign_id}>{c.campaign_name}</option>))}</select></div>
            <div className="field"><label>Opening message</label>
              <textarea name="prefill" placeholder="Leave empty and it writes one from the piece." /></div>
          </div>
          <div className="card-foot"><button className="btn btn-primary">Make the link</button></div>
        </form>
      </div>
    </Page>
  );
}
