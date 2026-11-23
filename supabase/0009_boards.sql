-- Look categories and mood boards.
--
-- The first attempt at this migration stalled on a confirmation prompt: it
-- carried `drop policy if exists`, which counts as destructive. Both tables
-- here are new, so there is no policy to drop and the drops are gone. Nothing
-- in this file removes or rewrites anything that already exists.

-- ALREADY APPLIED, on its own, as the `look_category` migration: the owner
-- asked for the category directly and nothing else depends on the board tables,
-- so it was split out rather than held behind them. Kept here, idempotent, so
-- this file still reads as the whole change.
-- What kind of reference this is, as the reader names it. Free text on purpose:
-- the owner chose invented categories over a fixed list. The reader is handed
-- the categories already in use and told to reuse one where it fits, so the
-- library converges on its own vocabulary instead of sprawling into
-- "riverside" beside "river location".
alter table looks add column if not exists category text;
create index if not exists looks_category_idx on looks (category);

-- A mood board is a named, ordered set of references. It lives in its own
-- library rather than inside one campaign, so one board can feed several.
create table if not exists boards (
  board_id    uuid primary key default gen_random_uuid(),
  name        text not null,
  intent      text,
  note        text,
  status      text not null default 'Open',
  created_at  timestamptz not null default now(),
  created_by  uuid references auth.users (id)
);

-- Every item on a board is a look. That is the whole point: an image is read
-- once, ever, and both the board and the campaign agent work from the stored
-- breakdown rather than sending the picture to a model a second time.
create table if not exists board_items (
  board_id    uuid not null references boards (board_id) on delete cascade,
  look_id     uuid not null references looks (look_id) on delete cascade,
  sort_order  int  not null default 0,
  note        text,
  added_at    timestamptz not null default now(),
  primary key (board_id, look_id)
);
create index if not exists board_items_board_idx on board_items (board_id, sort_order);

-- A campaign conversation can be built against a board.
alter table campaign_threads add column if not exists board_id uuid references boards (board_id);
alter table campaigns       add column if not exists board_id uuid references boards (board_id);

alter table boards      enable row level security;
alter table board_items enable row level security;

create policy boards_rw on boards
  for all to authenticated using (true) with check (true);
create policy board_items_rw on board_items
  for all to authenticated using (true) with check (true);

-- What a board holds, ready to read in one query.
create or replace view board_contents as
select b.board_id, b.name as board_name, b.intent, b.status,
       i.sort_order, i.note as item_note,
       l.look_id, l.look_no, l.name as look_name, l.summary, l.category,
       l.source, l.use_for, l.status as look_status, l.reference_url,
       l.setting, l.light, l.palette, l.mood, l.subject, l.framing, l.pose, l.tags
from boards b
left join board_items i on i.board_id = b.board_id
left join looks l       on l.look_id  = i.look_id;
