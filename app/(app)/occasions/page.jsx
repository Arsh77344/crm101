'use client';
import CrudPage from '@/components/CrudPage';
import { runUp, spanLabel } from '@/lib/occasions';

const KINDS = ['Festival', 'Wedding season', 'Retail moment', 'Brand moment'];
const BADGE = { on: 'b-green', soon: 'b-amber', later: '', past: '', none: 'b-red' };

export default function Occasions() {
  return <CrudPage cfg={{
    table: 'occasions', pk: 'occasion_id', title: 'Occasions', singular: 'occasion',
    sub: (r) => {
      const live = r.filter((o) => runUp(o).state === 'on').length;
      return live ? `${live} in their run-up now, ${r.length} on the calendar`
                  : `${r.length} on the calendar`;
    },
    order: ['occasion_date', true],
    search: ['name', 'region', 'meaning', 'kind'],
    searchHint: 'Search occasions…',
    filter: { col: 'kind', values: KINDS },
    emptyTitle: 'No occasions yet',
    emptyHint: 'The festivals, wedding seasons and retail moments worth selling into. The campaign studio reads this to know what is coming.',
    kpis: (r) => {
      const state = (o) => runUp(o).state;
      return [
        { label: 'In their run-up', value: r.filter((o) => state(o) === 'on').length,
          delta: 'promote these now' },
        { label: 'Starting soon', value: r.filter((o) => state(o) === 'soon').length,
          delta: 'within a fortnight' },
        { label: 'Dates to confirm', value: r.filter((o) => o.date_basis === 'Approximate').length,
          delta: 'lunar, so published differently' },
        { label: 'No date yet', value: r.filter((o) => !o.occasion_date).length },
      ];
    },
    sheet: [
      { key: 'name', label: 'Occasion', required: true, example: 'Diwali' },
      { key: 'occasion_date', label: 'Date', example: '2027-10-29' },
      { key: 'until_date', label: 'Ends', example: '' },
      { key: 'date_basis', label: 'How sure', example: 'Approximate' },
      { key: 'lead_weeks', label: 'Weeks of run-up', example: '3' },
      { key: 'kind', label: 'Kind', example: 'Festival' },
      { key: 'region', label: 'Where it matters', example: 'Pan-India' },
      { key: 'meaning', label: 'What it means', example: '' },
      { key: 'what_sells', label: 'What sells', example: '' },
      { key: 'avoid', label: 'What to avoid', example: '' },
      { key: 'note', label: 'Note', example: '' },
    ],
    matchOn: 'name',
    columns: [
      { key: 'name', label: 'Occasion' },
      { key: 'occasion_date', label: 'When',
        render: (r) => (r.occasion_date
          ? <span>{spanLabel(r)}{r.date_basis === 'Approximate'
              ? <span className="faint small"> approx</span> : null}</span>
          : <span className="faint">—</span>) },
      { key: 'run_up', label: 'Run-up',
        render: (r) => {
          const u = runUp(r);
          return <span className={`badge ${BADGE[u.state]}`}>{u.text}</span>;
        } },
      { key: 'lead_weeks', label: 'Weeks', num: true },
      { key: 'kind', label: 'Kind' },
      { key: 'region', label: 'Where it matters' },
    ],
    fields: [
      { name: 'name', label: 'Occasion', required: true, placeholder: 'Diwali',
        section: 'The occasion' },
      { name: 'kind', label: 'Kind', options: KINDS,
        hint: 'A wedding season or a retail moment is a window rather than a day. Give it an end date below.' },
      { name: 'region', label: 'Where it matters', placeholder: 'Tamil Nadu, or Pan-India',
        hint: 'Written however you think of it. The campaign agent reads this to decide casting and who the campaign is aimed at.' },
      { name: 'occasion_date', label: 'Date', type: 'date', section: 'When',
        hint: 'The day itself, or the first day where it runs for longer. Leave empty if you have not confirmed it yet.' },
      { name: 'until_date', label: 'Ends', type: 'date',
        hint: 'Only for a season or a month-long moment. Leave empty for a single day.' },
      { name: 'date_basis', label: 'How sure is the date',
        options: ['Approximate', 'Confirmed', 'Fixed'],
        hint: 'Fixed means solar, the same date most years. Approximate means lunar, and published differently by different panchangs. Mark it Confirmed once you have checked it against one you trust — until then the agent will not print the date in anything a customer reads.' },
      { name: 'lead_weeks', label: 'Weeks of run-up', type: 'number',
        hint: 'How long before it the promotion starts. Three is the default, and this is the number the campaign is actually planned against.' },
      { name: 'meaning', label: 'What it means', type: 'textarea',
        section: 'What to say about it',
        hint: 'What the occasion is and why it carries weight. This is the storytelling material, so it is the field worth filling properly — the agent builds the campaign from it.' },
      { name: 'what_sells', label: 'What sells, and what to show', type: 'textarea',
        hint: 'What people buy for it, who buys it, and what is worth photographing.' },
      { name: 'avoid', label: 'What would be wrong', type: 'textarea',
        hint: 'The thing that would make the campaign land badly. A bridal pitch aimed into Aadi is the clearest example: weddings are deliberately avoided in that month.' },
      { name: 'note', label: 'Note', type: 'textarea', section: 'Admin' },
      { name: 'active', label: 'On the calendar', options: ['true', 'false'],
        hint: 'Turn an occasion off rather than deleting it, so last year’s campaigns keep their link to it.' },
    ],
  }} />;
}
