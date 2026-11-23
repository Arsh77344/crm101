-- The occasions calendar: what is coming up, and what it means for the brand.
--
-- Nothing here removes or rewrites anything that already exists, so it applies
-- without a confirmation prompt.
--
-- Why a table rather than letting the agent search the web each time: the dates
-- of a lunar festival disagree between panchangs -- Holi 2027 is published as
-- both 22 and 23 March, Akshaya Tritiya as both 8 and 9 May, Diwali as both 27
-- and 29 October -- so a search result is no more trustworthy than a stored
-- date. The owner's answer settles it: promotion starts about three weeks
-- before, so the lead window is what the campaign is planned against and the
-- exact day matters much less. `lead_weeks` carries that, and `date_basis`
-- keeps the calendar honest about which dates are approximate.

create table if not exists occasions (
  occasion_id   uuid primary key default gen_random_uuid(),
  name          text not null,
  -- The day it falls on, or the first day where it is a season.
  occasion_date date,
  -- Set only for a season or a month-long moment; null for a single day.
  until_date    date,
  -- Fixed: solar, the same Gregorian date most years. Approximate: lunar, and
  -- published differently by different panchangs. Confirmed: the owner has
  -- checked this one against a panchang they trust.
  date_basis    text not null default 'Approximate',
  -- How long before it the promotion starts. The owner's default is three weeks.
  lead_weeks    int  not null default 3,
  kind          text not null default 'Festival',
  -- Free text, the way look categories are: the owner chose invented
  -- vocabulary over a fixed list, and regions do not sort into one anyway.
  region        text,
  -- What the occasion actually is and why it carries weight. This is the
  -- storytelling material, so it is the field worth filling properly.
  meaning       text,
  -- What people buy for it and what is worth showing.
  what_sells    text,
  -- What would be wrong to say or sell. Aadi is the clearest case: it is a
  -- heavy shopping month in Tamil Nadu and a month in which weddings are
  -- avoided, so a bridal campaign aimed there lands badly.
  avoid         text,
  note          text,
  active        boolean not null default true,
  created_at    timestamptz not null default now()
);

create index if not exists occasions_date_idx on occasions (occasion_date);

alter table occasions enable row level security;

create policy occasions_rw on occasions
  for all to authenticated using (true) with check (true);

-- The calendar with the promotion window worked out, so the month grid, the
-- campaign agent and the studio all read the same dates rather than each
-- doing the arithmetic. `promote_from` is the day the run-up starts.
create or replace view occasions_upcoming as
select o.*,
       (o.occasion_date - (o.lead_weeks * 7))                      as promote_from,
       (o.occasion_date - current_date)                            as days_away,
       ((o.occasion_date - (o.lead_weeks * 7)) - current_date)      as days_until_promote
from occasions o
where o.active and o.occasion_date is not null;

-- A campaign can be built against an occasion.
alter table campaign_threads add column if not exists occasion_id uuid references occasions (occasion_id);
alter table campaigns        add column if not exists occasion_id uuid references occasions (occasion_id);
