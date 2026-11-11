'use client';
import CrudPage from '@/components/CrudPage';
import { money } from '@/components/ui';

const STATUS = ['Not booked', 'Booked', 'Picked up', 'In transit', 'Out for delivery', 'Delivered', 'RTO', 'Lost'];

export default function Shipments() {
  return <CrudPage cfg={{
    table: 'shipments', pk: 'shipment_id', title: 'Shipments', singular: 'shipment',
    select: '*,orders(order_number,contacts(full_name))',
    sub: (r) => `${r.filter((s) => !['Delivered', 'RTO', 'Lost'].includes(s.status)).length} in motion · ${r.length} total`,
    order: ['created_at', false],
    search: ['awb', 'courier', 'address_city', 'orders.order_number'],
    searchHint: 'Search AWB, courier, city…',
    filter: { col: 'status', values: STATUS },
    emptyTitle: 'No shipments yet', emptyHint: 'Book a courier against an order and track it here.',
    kpis: (r) => [
      { label: 'In transit', value: r.filter((s) => ['Booked', 'Picked up', 'In transit', 'Out for delivery'].includes(s.status)).length },
      { label: 'Delivered', value: r.filter((s) => s.status === 'Delivered').length },
      { label: 'Not booked', value: r.filter((s) => s.status === 'Not booked').length, delta: 'waiting on you' },
      { label: 'Courier spend', value: money(r.reduce((s, x) => s + Number(x.shipping_cost || 0), 0)) },
    ],
    columns: [
      { key: 'orders.order_number', label: 'Order' },
      { key: 'orders.contacts.full_name', label: 'Customer' },
      { key: 'courier', label: 'Courier' },
      { key: 'awb', label: 'AWB',
        render: (r) => (r.tracking_url
          ? <a className="link mono" href={r.tracking_url} target="_blank" rel="noreferrer">{r.awb}</a>
          : <span className="mono">{r.awb || '—'}</span>) },
      { key: 'address_city', label: 'Destination' },
      { key: 'status', label: 'Status', fmt: 'badge' },
      { key: 'shipping_cost', label: 'Cost', fmt: 'money', num: true },
    ],
    sheet: [
      { key: 'courier', label: 'Courier', example: 'Delhivery' },
      { key: 'awb', label: 'AWB', example: 'DL2984471188' },
      { key: 'tracking_url', label: 'Tracking link', example: '' },
      { key: 'status', label: 'Status', example: 'In transit' },
      { key: 'address_city', label: 'Destination city', example: 'Pune' },
      { key: 'address_country', label: 'Destination country', example: 'India' },
      { key: 'shipping_cost', label: 'Courier cost', example: 150 },
    ],
    fields: [
      { name: 'order_id', label: 'Order', lookup: { table: 'orders', pk: 'order_id', label: 'order_number' } },
      { name: 'courier', label: 'Courier', placeholder: 'Delhivery, Blue Dart, DHL' },
      { name: 'awb', label: 'AWB / tracking number' },
      { name: 'tracking_url', label: 'Tracking link', placeholder: 'https://shiprocket.co/tracking/…' },
      { name: 'status', label: 'Status', options: STATUS },
      { name: 'address_city', label: 'Destination city' },
      { name: 'address_country', label: 'Destination country' },
      { name: 'weight_kg', label: 'Weight (kg)', type: 'number', step: '0.01' },
      { name: 'shipping_cost', label: 'Courier cost', type: 'number', step: '0.01' },
      { name: 'shipped_at', label: 'Shipped on', type: 'date' },
      { name: 'delivered_at', label: 'Delivered on', type: 'date' },
      { name: 'notes', label: 'Notes', type: 'textarea' },
    ],
  }} />;
}
