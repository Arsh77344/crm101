'use client';
import { useState } from 'react';
import Link from 'next/link';
import { useQuery, updateRow } from '@/lib/db';
import { Page, Stat, Badge, Loading, ErrorNote, Empty, money, when } from '@/components/ui';

export default function Payables() {
  const [err, setErr] = useState('');
  const [busy, setBusy] = useState(false);

  const q = useQuery(async (c) => {
    const [balances, rows] = await Promise.all([
      c.from('brand_balances').select('*').order('owed', { ascending: false }),
      c.from('payables').select('*,brands(name),products(public_product_name),orders(order_number)')
        .order('accrued_on', { ascending: false }).limit(400),
    ]);
    if (rows.error) throw rows.error;
    return { balances: balances.data || [], rows: rows.data || [] };
  }, []);

  async function mark(ids, status) {
    setBusy(true); setErr('');
    try {
      for (const id of ids) {
        await updateRow('payables', 'payable_id', id,
          { status, paid_on: status === 'Paid' ? new Date().toISOString().slice(0, 10) : null });
      }
      q.reload();
    } catch (e) { setErr(e.message || String(e)); }
    setBusy(false);
  }

  if (q.loading) return <Page title="What you owe"><Loading /></Page>;
  const { balances, rows } = q.data;
  const owed = balances.reduce((s, b) => s + Number(b.owed || 0), 0);
  const paid = balances.reduce((s, b) => s + Number(b.paid_to_date || 0), 0);
  const reversed = balances.reduce((s, b) => s + Number(b.reversed || 0), 0);
  const unpaid = rows.filter((r) => r.status === 'Accrued');

  return (
    <Page title="What you owe" sub="Money owed to brand partners, accrued when a piece is fulfilled."
      actions={<Link className="btn" href="/brands">Brand partners</Link>}>
      <ErrorNote error={q.error || err} />

      <div className="kpi-row" style={{ marginBottom: 16 }}>
        <Stat label="Owed right now" value={money(owed)} delta={`${unpaid.length} lines unpaid`} />
        <Stat label="Paid to date" value={money(paid)} />
        <Stat label="Reversed by returns" value={money(reversed)} />
        <Stat label="Partners with a balance" value={balances.filter((b) => Number(b.owed) > 0).length} />
      </div>

      <div className="grid" style={{ gridTemplateColumns: '1fr 1fr' }}>
        <div className="card">
          <div className="card-head"><h3>By partner</h3></div>
          {balances.length === 0 ? <Empty title="No partners yet" /> : (
            <div className="t-wrap"><table className="table">
              <thead><tr><th>Brand</th><th>Terms</th><th className="num">Owed</th><th></th></tr></thead>
              <tbody>{balances.map((b) => {
                const theirs = rows.filter((r) => r.brand_id === b.brand_id && r.status === 'Accrued');
                return (
                  <tr key={b.brand_id}>
                    <td><strong className="small">{b.name}</strong>
                      <div className="small faint">{b.city}</div></td>
                    <td className="small muted">{b.payout_terms}</td>
                    <td className="num">{money(b.owed)}</td>
                    <td style={{ textAlign: 'right' }}>
                      {theirs.length > 0 && (
                        <button className="btn btn-sm" disabled={busy}
                          onClick={() => mark(theirs.map((r) => r.payable_id), 'Paid')}>
                          Mark {theirs.length} paid</button>)}
                    </td>
                  </tr>);
              })}</tbody></table></div>
          )}
        </div>

        <div className="card">
          <div className="card-head"><h3>Every line</h3>
            <span className="small muted">{rows.length}</span></div>
          {rows.length === 0
            ? <Empty title="Nothing accrued yet"
                hint="A line appears here the moment an order is marked Fulfilled." />
            : (<div className="t-wrap" style={{ maxHeight: 460, overflowY: 'auto' }}><table className="table">
                <thead><tr><th>Accrued</th><th>Brand</th><th>Piece</th>
                  <th className="num">Amount</th><th>Status</th><th></th></tr></thead>
                <tbody>{rows.map((r) => (
                  <tr key={r.payable_id}>
                    <td className="small faint">{when(r.accrued_on)}</td>
                    <td className="small">{r.brands?.name || '—'}</td>
                    <td className="small">{r.products?.public_product_name || '—'}
                      <div className="small faint">{r.orders?.order_number}</div></td>
                    <td className="num">{money(r.amount)}</td>
                    <td><Badge>{r.status}</Badge></td>
                    <td style={{ textAlign: 'right' }}>
                      {r.status === 'Accrued' && (
                        <button className="btn btn-sm" disabled={busy}
                          onClick={() => mark([r.payable_id], 'Paid')}>Paid</button>)}
                    </td>
                  </tr>))}</tbody></table></div>)}
        </div>
      </div>
    </Page>
  );
}
