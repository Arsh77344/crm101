// The occasions calendar, read the same way everywhere.
//
// Two pages and one agent need the same three things: which occasions are
// coming, when the run-up to each one starts, and how to say that in a line.
// Putting the arithmetic here means the month grid and the studio cannot drift
// apart on what "coming up" means.
//
// `promote_from` and `days_away` come from the `occasions_upcoming` view rather
// than being worked out in the browser, so the database and the edge function
// agree without either of them trusting a clock in a browser.

// Every dated occasion. The whole table is two dozen rows and will stay that
// size -- a year has a fixed number of festivals in it -- so it is fetched
// whole and filtered here. That avoids building an `or` filter for the spans,
// which is the fragile part of this query.
export async function loadOccasions(c) {
  const { data, error } = await c.from('occasions_upcoming')
    .select('*').order('occasion_date');
  if (error) throw error;
  return data || [];
}

// An occasion covers one day, or a span where it has an end.
export function covers(o, day) {
  const from = o.occasion_date;
  const to = o.until_date || o.occasion_date;
  const d = typeof day === 'string' ? day : iso(day);
  return Boolean(from) && d >= from && d <= to;
}

export function iso(d) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

// What is worth putting in front of someone writing a brief: the occasions
// whose run-up has started or starts soon, nearest first.
export function worthMentioning(list, withinDays = 75) {
  return list
    .filter((o) => o.days_away !== null && o.days_away >= 0 && o.days_until_promote <= withinDays)
    .sort((a, b) => a.days_away - b.days_away);
}

// The run-up, said plainly. The owner's rule is that promotion starts about
// three weeks out, so this is the number that actually decides a campaign.
export function leadLabel(o) {
  const n = o.days_until_promote;
  if (n === null || n === undefined) return '';
  if (n <= 0) return o.days_away === 0 ? 'today' : `run-up is on, ${o.days_away} days to go`;
  if (n === 1) return 'run-up starts tomorrow';
  return `run-up starts in ${n} days`;
}

// A date the owner has not checked is never printed as fact to a customer, so
// the UI says which ones are approximate and the agent is told the same.
export function dateNote(o) {
  return o.date_basis === 'Approximate' ? 'date approximate' : '';
}

export function spanLabel(o) {
  const opts = { day: 'numeric', month: 'short' };
  const a = new Date(`${o.occasion_date}T00:00:00`).toLocaleDateString('en-GB', opts);
  if (!o.until_date || o.until_date === o.occasion_date) return a;
  const b = new Date(`${o.until_date}T00:00:00`).toLocaleDateString('en-GB', opts);
  return `${a} – ${b}`;
}

// The same arithmetic as the `occasions_upcoming` view, for a row read straight
// off the `occasions` table -- the list page writes to that table, and a view
// with computed columns and a WHERE is no place to insert into. The two
// definitions must agree; `qa/occasions.py` checks that they do against a real
// row rather than trusting this comment.
export function promoteFrom(o) {
  if (!o.occasion_date) return null;
  const d = new Date(`${o.occasion_date}T00:00:00`);
  d.setDate(d.getDate() - (o.lead_weeks ?? 3) * 7);
  return iso(d);
}

export function daysBetween(fromIso, toIso) {
  const a = new Date(`${fromIso}T00:00:00`);
  const b = new Date(`${toIso}T00:00:00`);
  return Math.round((b - a) / 86400000);
}

// What the list page shows in its "Run-up" column, computed from the row it
// already has rather than from a second query.
export function runUp(o, today = iso(new Date())) {
  if (!o.occasion_date) return { text: 'no date yet', state: 'none' };
  const away = daysBetween(today, o.occasion_date);
  if (away < 0) return { text: 'past', state: 'past' };
  const untilPromote = daysBetween(today, promoteFrom(o));
  if (away === 0) return { text: 'today', state: 'on' };
  if (untilPromote <= 0) return { text: `on now, ${away} days to go`, state: 'on' };
  if (untilPromote <= 14) return { text: `starts in ${untilPromote} days`, state: 'soon' };
  return { text: `starts ${promoteFrom(o).slice(8)}/${promoteFrom(o).slice(5, 7)}`, state: 'later' };
}
