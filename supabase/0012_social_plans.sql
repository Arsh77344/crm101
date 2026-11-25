-- The always-on social plan.
--
-- Distinct from a campaign on purpose. A campaign has a spine, a window, a
-- budget and an end; this is the weekly drumbeat between campaigns, and the
-- thing that keeps the content calendar from being empty. They share the same
-- `campaign_posts` table so the calendar shows both, which is why `plan_id`
-- goes there rather than this table holding its own copy of a post.
--
-- Nothing here removes or rewrites anything, so it applies without a prompt.

create table if not exists social_plans (
  plan_id     uuid primary key default gen_random_uuid(),
  title       text not null,
  market      text,
  starts_on   date not null default current_date,
  days        int  not null default 7,
  status      text not null default 'Draft',
  -- A plan may be built around something on the occasions calendar.
  occasion_id uuid references occasions (occasion_id),
  -- What the agent told the owner in its own words.
  say         text,
  -- What it found by searching, each with where it came from. Kept because a
  -- hashtag or a format is only worth anything if it was looked up rather than
  -- remembered, and the owner has to be able to see which.
  research    jsonb not null default '[]'::jsonb,
  -- Drafted answers to the questions that actually arrive under a post.
  replies     jsonb not null default '[]'::jsonb,
  provider    text,
  model       text,
  created_at  timestamptz not null default now(),
  created_by  uuid references auth.users (id)
);

create index if not exists social_plans_starts_idx on social_plans (starts_on desc);

alter table social_plans enable row level security;

create policy social_plans_rw on social_plans
  for all to authenticated using (true) with check (true);

-- A post belongs to a campaign, or to a plan, or to neither. `campaign_id` was
-- already nullable, so an always-on post lands on the content calendar with no
-- campaign behind it.
alter table campaign_posts add column if not exists plan_id uuid references social_plans (plan_id);
-- Why these hashtags and not others: the size of the tag, who is in it. Without
-- this the owner cannot tell a researched tag from an invented one.
alter table campaign_posts add column if not exists hashtag_note text;

create index if not exists campaign_posts_plan_idx on campaign_posts (plan_id);
