'use client';
import CrudPage from '@/components/CrudPage';

export default function Tasks() {
  return <CrudPage cfg={{
    table: 'tasks', pk: 'task_id', title: 'Tasks', singular: 'task',
    select: '*,profiles(full_name)',
    sub: (r) => `${r.filter((t) => t.status !== 'Done').length} open · ${r.filter((t) => t.due_on && new Date(t.due_on) < new Date() && t.status !== 'Done').length} overdue`,
    order: ['due_on', true],
    search: ['title', 'detail'],
    searchHint: 'Search tasks…',
    filter: { col: 'status', values: ['To do', 'Doing', 'Blocked', 'Done'] },
    emptyTitle: 'Nothing on the list', emptyHint: 'Add what needs doing so nothing slips.',
    kpis: (r) => [
      { label: 'Open', value: r.filter((t) => t.status !== 'Done').length },
      { label: 'Overdue', value: r.filter((t) => t.due_on && new Date(t.due_on) < new Date() && t.status !== 'Done').length },
      { label: 'Due this week',
        value: r.filter((t) => t.due_on && t.status !== 'Done' && new Date(t.due_on) <= new Date(Date.now() + 7 * 864e5)).length },
      { label: 'Urgent', value: r.filter((t) => t.priority === 'Urgent' && t.status !== 'Done').length },
    ],
    columns: [
      { key: 'title', label: 'Task' },
      { key: 'priority', label: 'Priority', fmt: 'badge' },
      { key: 'due_on', label: 'Due', fmt: 'date' },
      { key: 'profiles.full_name', label: 'Owner' },
      { key: 'status', label: 'Status', fmt: 'badge' },
    ],
    sheet: [
      { key: 'title', label: 'Task', required: true, example: 'Approve the pricing' },
      { key: 'detail', label: 'Detail', example: '' },
      { key: 'due_on', label: 'Due on', example: '2026-11-20' },
      { key: 'priority', label: 'Priority', example: 'High' },
      { key: 'status', label: 'Status', example: 'To do' },
    ],
    fields: [
      { name: 'title', label: 'Task', required: true },
      { name: 'detail', label: 'Detail', type: 'textarea' },
      { name: 'due_on', label: 'Due on', type: 'date' },
      { name: 'priority', label: 'Priority', options: ['Normal', 'Low', 'High', 'Urgent'] },
      { name: 'status', label: 'Status', options: ['To do', 'Doing', 'Blocked', 'Done'] },
      { name: 'assignee', label: 'Owner', lookup: { table: 'profiles', pk: 'id', label: 'full_name' } },
      { name: 'contact_id', label: 'About contact', lookup: { table: 'contacts', pk: 'contact_id', label: 'full_name' } },
      { name: 'product_id', label: 'About product', lookup: { table: 'products', pk: 'product_id', label: 'public_product_name' } },
    ],
  }} />;
}
