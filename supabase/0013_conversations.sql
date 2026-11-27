-- The customer conversation store, for the agent that answers on WhatsApp.
--
-- Three things in here that are not obvious:
--
-- 1. `wa_message_id` is unique. A provider retries a webhook whenever it does
--    not get a 200 back fast enough, so the same customer message arrives two
--    or three times. Without the unique index the agent answers it two or three
--    times, which is the single most visible way this can embarrass the brand.
--    Idempotency belongs in the database, not in the function's memory.
--
-- 2. The 24-hour window is computed in a view, not in the browser and not in
--    the function. Both read `conversation_state`, so they cannot disagree
--    about whether a free-text reply is still allowed -- the same reason the
--    occasions calendar carries its own run-up.
--
-- 3. `is_test` exists because the owner needs to tune the escalation list
--    before a real number is attached, and test traffic must never be counted
--    as a real customer or shown in a real total.
--
-- Nothing here removes or rewrites anything, so it applies without a prompt.

create table if not exists conversations (
  conversation_id uuid primary key default gen_random_uuid(),
  channel         text not null default 'WhatsApp',
  -- The customer's number as the provider gives it, digits only, with country
  -- code. Not a foreign key: someone can message before they are a contact.
  wa_phone        text not null,
  -- The name on their WhatsApp profile. Theirs, not ours, and not to be trusted
  -- as a real name.
  wa_name         text,
  contact_id      uuid references contacts (contact_id),
  -- Open | Needs you | Waiting on customer | Closed
  status          text not null default 'Open',
  -- What this conversation is about, in the agent's own words, one line.
  topic           text,
  escalated       boolean not null default false,
  -- Which rule sent it to the owner. Null when the agent is handling it.
  escalation_rule text,
  escalation_note text,
  escalated_at    timestamptz,
  last_in_at      timestamptz,
  last_out_at     timestamptz,
  -- How many inbound messages have arrived with no answer out. Two of these on
  -- the same question is itself a reason to escalate.
  unanswered      int not null default 0,
  is_test         boolean not null default false,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now()
);

create unique index if not exists conversations_phone_idx
  on conversations (wa_phone, channel, is_test);
create index if not exists conversations_status_idx
  on conversations (escalated desc, last_in_at desc);

create table if not exists conversation_messages (
  message_id      uuid primary key default gen_random_uuid(),
  conversation_id uuid not null references conversations (conversation_id) on delete cascade,
  -- 'in' from the customer, 'out' from us.
  direction       text not null,
  body            text not null,
  -- The provider's own id for an inbound message. Unique, so a retried webhook
  -- cannot produce a second answer. Null for anything we wrote.
  wa_message_id   text unique,
  -- Received | Drafted | Ready to send | Sent | Held | Failed
  status          text not null default 'Received',
  -- Why an outbound message was not sent: no transport attached yet, the window
  -- had closed, or the draft broke one of the rails.
  held_reason     text,
  -- Who wrote it: a model name, or 'owner' when the owner answered himself.
  written_by      text,
  -- The product ids and recorded facts the draft was built from, so a wrong
  -- answer can be traced to what it was reading rather than guessed at.
  grounded_on     jsonb not null default '{}'::jsonb,
  -- Which escalation rule this message tripped, if any.
  rule_hit        text,
  sent_at         timestamptz,
  created_at      timestamptz not null default now()
);

create index if not exists conversation_messages_thread_idx
  on conversation_messages (conversation_id, created_at);

-- What the agent must hand to the owner rather than answer. Seeded with the
-- list the owner agreed, each editable: `patterns` is a list of lowercase
-- substrings, any one of which fires the rule.
--
-- This decides WHO answers. It does not decide what may be said -- the rails on
-- prices, dates and promises live in the function and apply even to a message
-- the agent is allowed to send, because a rule list cannot catch a confident
-- invention.
create table if not exists escalation_topics (
  topic_id   uuid primary key default gen_random_uuid(),
  label      text not null,
  patterns   text[] not null default '{}',
  active     boolean not null default true,
  -- Why this one is here, so a later reader knows what it is protecting.
  note       text,
  sort_order int not null default 100,
  created_at timestamptz not null default now()
);

alter table conversations        enable row level security;
alter table conversation_messages enable row level security;
alter table escalation_topics    enable row level security;

create policy conversations_rw on conversations
  for all to authenticated using (true) with check (true);
create policy conversation_messages_rw on conversation_messages
  for all to authenticated using (true) with check (true);
create policy escalation_topics_rw on escalation_topics
  for all to authenticated using (true) with check (true);

-- One place that answers "is the free-text window still open", so the page and
-- the function cannot drift apart. WhatsApp allows a free-form reply only within
-- 24 hours of the customer's own last message; after that it takes an approved
-- template.
create or replace view conversation_state as
select
  c.*,
  c.last_in_at + interval '24 hours'                           as window_until,
  (c.last_in_at is not null
    and c.last_in_at > now() - interval '24 hours')            as window_open,
  greatest(0, floor(extract(epoch from
    (c.last_in_at + interval '24 hours' - now())) / 60)::int)  as window_minutes_left,
  (select count(*) from conversation_messages m
     where m.conversation_id = c.conversation_id)              as message_count,
  (select m.body from conversation_messages m
     where m.conversation_id = c.conversation_id
     order by m.created_at desc limit 1)                       as last_message,
  (select m.direction from conversation_messages m
     where m.conversation_id = c.conversation_id
     order by m.created_at desc limit 1)                       as last_direction
from conversations c;
