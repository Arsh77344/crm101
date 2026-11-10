-- Row level security
do $$
declare t text;
begin
  foreach t in array array['profiles','companies','contacts','contact_companies','products','product_images',
    'orders','order_items','opportunities','activities','marketing_permissions','campaigns','campaign_members',
    'campaign_posts','interactions','showrooms','showroom_products','showroom_views','launch_jobs',
    'integrations','settings','audit_log']
  loop
    execute format('alter table %I enable row level security', t);
  end loop;
end $$;

-- Everyone signed in can read everything in the workspace.
do $$
declare t text;
begin
  foreach t in array array['profiles','companies','contacts','contact_companies','products','product_images',
    'orders','order_items','opportunities','activities','marketing_permissions','campaigns','campaign_members',
    'campaign_posts','interactions','showrooms','showroom_products','showroom_views','launch_jobs',
    'integrations','settings','audit_log']
  loop
    execute format('drop policy if exists read_all on %I', t);
    execute format('create policy read_all on %I for select to authenticated using (true)', t);
  end loop;
end $$;

-- Day-to-day tables: any signed-in team member can create and edit.
do $$
declare t text;
begin
  foreach t in array array['companies','contacts','contact_companies','products','product_images',
    'orders','order_items','opportunities','activities','marketing_permissions','campaigns','campaign_members',
    'campaign_posts','interactions','showrooms','showroom_products','launch_jobs','audit_log']
  loop
    execute format('drop policy if exists write_team on %I', t);
    execute format('create policy write_team on %I for insert to authenticated with check (true)', t);
    execute format('drop policy if exists update_team on %I', t);
    execute format('create policy update_team on %I for update to authenticated using (true) with check (true)', t);
    execute format('drop policy if exists delete_managers on %I', t);
    execute format($f$create policy delete_managers on %I for delete to authenticated
                      using (current_role_name() in ('owner','admin'))$f$, t);
  end loop;
end $$;

-- Settings and integrations: managers only.
do $$
declare t text;
begin
  foreach t in array array['integrations','settings']
  loop
    execute format('drop policy if exists manage_config on %I', t);
    execute format($f$create policy manage_config on %I for all to authenticated
                      using (current_role_name() in ('owner','admin'))
                      with check (current_role_name() in ('owner','admin'))$f$, t);
  end loop;
end $$;

-- Profiles: you can edit your own name; owners and admins manage roles.
drop policy if exists update_own_profile on profiles;
create policy update_own_profile on profiles for update to authenticated
  using (id = auth.uid()) with check (id = auth.uid());
drop policy if exists manage_profiles on profiles;
create policy manage_profiles on profiles for all to authenticated
  using (current_role_name() in ('owner','admin'))
  with check (current_role_name() in ('owner','admin'));

-- Public showrooms: anonymous visitors may read an enabled showroom and log a view.
drop policy if exists public_showroom_read on showrooms;
create policy public_showroom_read on showrooms for select to anon
  using (public_enabled = true and status = 'Published');
drop policy if exists public_showroom_products on showroom_products;
create policy public_showroom_products on showroom_products for select to anon using (true);
drop policy if exists public_showroom_product_rows on products;
create policy public_showroom_product_rows on products for select to anon
  using (exists (select 1 from showroom_products sp
                  join showrooms s on s.showroom_id = sp.showroom_id
                 where sp.product_id = products.product_id
                   and s.public_enabled = true and s.status = 'Published'));
drop policy if exists public_showroom_images on product_images;
create policy public_showroom_images on product_images for select to anon using (true);
drop policy if exists public_showroom_view_log on showroom_views;
create policy public_showroom_view_log on showroom_views for insert to anon with check (true);
