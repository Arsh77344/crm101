// The occasions calendar, read the same way everywhere.
//
// Two pages and one agent need the same three things: which occasions are
// coming, when the run-up to each one starts, and how to say that in a line.
// Putting the arithmetic here means the month grid and the studio cannot drift
// apart on what "coming up" means.
//
// The lead arithmetic exists twice on purpose: the `occasions_upcoming` view
// computes it for the campaign agent, and `promoteFrom` below computes it in the
// browser, because the list page writes to the `occasions` table and a view with
// computed columns and a WHERE is no place to insert into. `qa/occasions.py`
// implements the same rule a third time and holds the browser to it, so the two
// cannot drift apart quietly.

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

// What is worth putting in front of someone writing a brief: the occasions whose
// run-up has started or starts within the fortnight, nearest first.
//
// Both the month grid and the studio composer show this line, and they showed
// four and three items from two hand-written copies of this filter before it
// lived here. One definition, one count.
export function worthMentioning(list, limit = 4, today = iso(new Date())) {
  return list
    .filter((o) => o.occasion_date && ['on', 'soon'].includes(runUp(o, today).state))
    .sort((a, b) => a.occasion_date.localeCompare(b.occasion_date))
    .slice(0, limit);
}

// A date the owner has not checked is never printed as fact to a customer, so
// every place that shows one says it is approximate, in the same words.
export const APPROX = 'date approximate';
export function dateNote(o) {
  return o.date_basis === 'Approximate' ? APPROX : '';
}

// The shared `when()` prints the year on every other date column in the app, so
// a date here without one reads as undated -- and most of this calendar is next
// year. The year is shown only when it is not the current one, which keeps the
// near dates short without losing the far ones.
// One date, in words. The year shows only when it is not the current one, which
// keeps the near dates short without leaving the far ones looking undated.
export function dayLabel(isoDate, today = new Date()) {
  const year = Number(isoDate.slice(0, 4));
  const now = typeof today === 'string' ? Number(today.slice(0, 4)) : today.getFullYear();
  return new Date(`${isoDate}T00:00:00`).toLocaleDateString('en-GB', {
    day: 'numeric', month: 'short', ...(year !== now ? { year: 'numeric' } : {}),
  });
}

export function spanLabel(o, today = new Date()) {
  const year = (iso) => Number(iso.slice(0, 4));
  const far = year(o.occasion_date) !== today.getFullYear()
    || (o.until_date && year(o.until_date) !== today.getFullYear());
  const opts = { day: 'numeric', month: 'short', ...(far ? { year: 'numeric' } : {}) };
  const a = new Date(`${o.occasion_date}T00:00:00`).toLocaleDateString('en-GB', opts);
  if (!o.until_date || o.until_date === o.occasion_date) return a;
  const b = new Date(`${o.until_date}T00:00:00`).toLocaleDateString('en-GB', opts);
  return `${a} – ${b}`;
}

// The same arithmetic as the `occasions_upcoming` view, for a row read straight
// off the `occasions` table -- the list page writes to that table, and a view
// with computed columns and a WHERE is no place to insert into. The two
// definitions must agree; `qa/occasions.py` checks that they do against a rule
// implemented a third time in Python, rather than trusting this comment.
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
  // Said the way every other date in the app is said -- "17 Aug 2027", not
  // 17/08. A run-up this far out is almost always in another year, and a date
  // with no year on it reads as no date at all.
  return { text: `starts ${dayLabel(promoteFrom(o), today)}`, state: 'later' };
}
