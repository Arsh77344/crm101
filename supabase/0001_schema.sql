-- Commerce Business OS — core schema
create extension if not exists pgcrypto;

-- ---------- people & access ----------
create table if not exists profiles (
  id uuid primary key references auth.users(id) on delete cascade,
  email text,
  full_name text,
  role text not null default 'sales' check (role in ('owner','admin','sales')),
  created_at timestamptz default now()
);

create or replace function current_role_name() returns text
language sql stable security definer set search_path = public as $$
  select coalesce((select role from profiles where id = auth.uid()), 'none');
$$;

create or replace function handle_new_user() returns trigger
language plpgsql security definer set search_path = public as $$
begin
  insert into public.profiles (id, email, full_name, role)
  values (new.id, new.email,
          coalesce(new.raw_user_meta_data->>'full_name', split_part(new.email,'@',1)),
          coalesce(new.raw_user_meta_data->>'role',
                   case when (select count(*) from public.profiles) = 0 then 'owner' else 'sales' end))
  on conflict (id) do nothing;
  return new;
end; $$;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created after insert on auth.users
  for each row execute function handle_new_user();

-- ---------- commerce ----------
create table if not exists companies (
  company_id uuid primary key default gen_random_uuid(),
  company_name text not null,
  website text, country text, company_type text, wholesale_tier text, notes text,
  created_at timestamptz default now()
);

create table if not exists contacts (
  contact_id uuid primary key default gen_random_uuid(),
  contact_type text default 'Unknown' check (contact_type in ('B2B','B2C','Both','Unknown')),
  full_name text, first_name text, username text,
  email text, phone_number text, phone_country_code text,
  website text, biography text, country text, language text, niche text,
  entity_type text, followers int, following int,
  source_name text, source_type text, source_reference text,
  qualification_status text default 'Unreviewed',
  lifecycle_stage text default 'New',
  lead_score int default 0,
  business_category text, relevance_reason text,
  data_quality text default 'Unknown',
  next_follow_up date,
  created_at timestamptz default now()
);
create index if not exists idx_contacts_email on contacts(email);
create index if not exists idx_contacts_stage on contacts(lifecycle_stage);

create table if not exists contact_companies (
  contact_id uuid references contacts(contact_id) on delete cascade,
  company_id uuid references companies(company_id) on delete cascade,
  role_title text, is_primary boolean default false,
  primary key (contact_id, company_id)
);

create table if not exists products (
  product_id uuid primary key default gen_random_uuid(),
  internal_sku text unique,
  public_product_name text not null,
  source_product_name text,
  colour text, weave_or_motif text, fabric text,
  category text default 'Banarasi Saree',
  description text, tags text,
  cost_price numeric, retail_price numeric, wholesale_price numeric,
  currency text default 'INR',
  stock_qty int default 0, moq int default 1,
  status text default 'Draft' check (status in ('Draft','Review','Published','Archived')),
  published_at timestamptz,
  created_at timestamptz default now()
);
create index if not exists idx_products_status on products(status);

create table if not exists product_images (
  image_id uuid primary key default gen_random_uuid(),
  product_id uuid references products(product_id) on delete cascade,
  image_role text default 'Gallery',
  original_filename text, storage_path text, public_url text,
  is_primary boolean default false,
  created_at timestamptz default now()
);

create table if not exists orders (
  order_id uuid primary key default gen_random_uuid(),
  order_number text,
  contact_id uuid references contacts(contact_id) on delete set null,
  company_id uuid references companies(company_id) on delete set null,
  order_type text check (order_type in ('B2B','B2C')) default 'B2C',
  order_status text default 'Draft',
  subtotal numeric default 0, discount numeric default 0,
  shipping numeric default 0, total numeric default 0,
  currency text default 'INR',
  external_order_reference text,
  ordered_at timestamptz default now()
);

create table if not exists order_items (
  order_item_id uuid primary key default gen_random_uuid(),
  order_id uuid references orders(order_id) on delete cascade,
  product_id uuid references products(product_id) on delete set null,
  quantity int not null default 1,
  unit_price numeric not null default 0
);

create table if not exists opportunities (
  opportunity_id uuid primary key default gen_random_uuid(),
  contact_id uuid references contacts(contact_id) on delete set null,
  company_id uuid references companies(company_id) on delete set null,
  name text not null,
  stage text default 'New' check (stage in ('New','Qualified','Proposal','Negotiation','Won','Lost')),
  estimated_value numeric, currency text default 'INR',
  expected_close_date date, notes text,
  created_at timestamptz default now()
);

create table if not exists activities (
  activity_id uuid primary key default gen_random_uuid(),
  contact_id uuid references contacts(contact_id) on delete cascade,
  company_id uuid references companies(company_id) on delete set null,
  opportunity_id uuid references opportunities(opportunity_id) on delete set null,
  activity_type text, channel text, direction text, summary text,
  follow_up_at timestamptz,
  created_at timestamptz default now()
);

create table if not exists marketing_permissions (
  permission_id uuid primary key default gen_random_uuid(),
  contact_id uuid references contacts(contact_id) on delete cascade,
  channel text not null check (channel in ('Email','WhatsApp','SMS','Phone','Other')),
  status text not null default 'Unknown'
    check (status in ('Unknown','Allowed','OptedIn','OptedOut','Suppressed','DoNotContact')),
  lawful_basis_or_reason text, evidence_reference text, jurisdiction text,
  updated_at timestamptz default now()
);

-- ---------- marketing ----------
create table if not exists campaigns (
  campaign_id uuid primary key default gen_random_uuid(),
  campaign_name text not null,
  objective text default 'Awareness',
  audience_type text default 'All',
  channel text default 'Email',
  status text default 'Draft' check (status in ('Draft','Scheduled','Running','Paused','Completed','Archived')),
  budget numeric, spend numeric default 0,
  start_date date, end_date date,
  brief text, offer text,
  created_at timestamptz default now()
);

create table if not exists campaign_members (
  campaign_id uuid references campaigns(campaign_id) on delete cascade,
  contact_id uuid references contacts(contact_id) on delete cascade,
  member_status text default 'Planned',
  added_at timestamptz default now(),
  primary key (campaign_id, contact_id)
);

create table if not exists campaign_posts (
  post_id uuid primary key default gen_random_uuid(),
  campaign_id uuid references campaigns(campaign_id) on delete cascade,
  channel text default 'Instagram',
  title text,
  body text,
  hashtags text,
  scheduled_for timestamptz,
  status text default 'Idea' check (status in ('Idea','Draft','Approved','Scheduled','Published')),
  product_id uuid references products(product_id) on delete set null,
  created_at timestamptz default now()
);
create index if not exists idx_posts_sched on campaign_posts(scheduled_for);

create table if not exists interactions (
  interaction_id uuid primary key default gen_random_uuid(),
  contact_id uuid references contacts(contact_id) on delete cascade,
  campaign_id uuid references campaigns(campaign_id) on delete set null,
  channel text, interaction_type text, direction text,
  subject_or_summary text,
  occurred_at timestamptz default now()
);

-- ---------- showrooms ----------
create table if not exists showrooms (
  showroom_id uuid primary key default gen_random_uuid(),
  contact_id uuid references contacts(contact_id) on delete set null,
  company_id uuid references companies(company_id) on delete set null,
  slug text unique, title text,
  intro_text text, cta_text text,
  pricing_mode text default 'Hidden' check (pricing_mode in ('Retail','Wholesale','Hidden')),
  status text default 'Draft',
  public_enabled boolean default true,
  created_at timestamptz default now()
);

create table if not exists showroom_products (
  showroom_id uuid references showrooms(showroom_id) on delete cascade,
  product_id uuid references products(product_id) on delete cascade,
  sort_order int default 0, custom_price numeric,
  primary key (showroom_id, product_id)
);

create table if not exists showroom_views (
  view_id uuid primary key default gen_random_uuid(),
  showroom_id uuid references showrooms(showroom_id) on delete cascade,
  viewed_at timestamptz default now(), user_agent text
);

-- ---------- operations ----------
create table if not exists launch_jobs (
  job_id uuid primary key default gen_random_uuid(),
  product_id uuid references products(product_id) on delete cascade,
  stage text default 'Photos' check (stage in ('Photos','Imagery','Copy','Pricing','Review','Published')),
  status text default 'Queued' check (status in ('Queued','Running','Blocked','Done','Failed')),
  message text,
  created_at timestamptz default now(),
  finished_at timestamptz
);

create table if not exists integrations (
  integration_id uuid primary key default gen_random_uuid(),
  provider text unique not null,
  category text,
  status text default 'Disconnected' check (status in ('Disconnected','Configured','Connected','Error')),
  config jsonb default '{}'::jsonb,
  last_checked_at timestamptz,
  notes text
);

create table if not exists settings (
  setting_key text primary key,
  setting_value text
);

create table if not exists audit_log (
  log_id uuid primary key default gen_random_uuid(),
  actor uuid references auth.users(id) on delete set null,
  action text, entity text, entity_id text, detail text,
  created_at timestamptz default now()
);
