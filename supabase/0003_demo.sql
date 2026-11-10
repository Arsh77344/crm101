-- Demo content so every screen has something to work with. Safe to delete later.
insert into products (internal_sku, public_product_name, colour, weave_or_motif, fabric, category,
  description, tags, cost_price, retail_price, wholesale_price, stock_qty, moq, status, published_at)
values
 ('USY-MS-001','Mashru Silk Banarasi — Deep Magenta','Magenta','Jangla floral','Mashru Satin Silk','Banarasi Saree','Handwoven Mashru satin silk with a dense jangla floral jaal and a broad zari border.','wedding,silk,handloom',4200,11900,8200,6,2,'Published', now() - interval '20 days'),
 ('USY-MS-002','Mashru Silk Banarasi — Midnight Blue','Midnight Blue','Shikargah','Mashru Satin Silk','Banarasi Saree','Shikargah motif woven in antique zari across a midnight blue field.','wedding,silk,festive',4600,13500,9400,3,2,'Published', now() - interval '14 days'),
 ('USY-KD-004','Kota Doria Cotton — Ivory Buti','Ivory','Scattered buti','Kota Doria Cotton','Cotton Saree','Feather-light Kota Doria in ivory with hand-placed zari buti. Everyday drape.','summer,cotton,daily',900,2600,1750,18,5,'Published', now() - interval '9 days'),
 ('USY-KD-005','Kota Doria Cotton — Sage Checks','Sage','Kota checks','Kota Doria Cotton','Cotton Saree','Classic Kota square checks in a soft sage wash.','summer,cotton,office',850,2400,1600,22,5,'Published', now() - interval '6 days'),
 ('USY-MS-007','Katan Silk Banarasi — Rani Pink','Rani Pink','Kadhua booti','Katan Silk','Banarasi Saree','Kadhua booti woven one motif at a time; takes about forty days on the loom.','bridal,heritage,silk',8800,24500,17800,2,1,'Review', null),
 ('USY-OG-009','Organza Banarasi — Powder Blue','Powder Blue','Tissue border','Silk Organza','Banarasi Saree','Sheer organza with a tissue border and scattered silver buti.','festive,lightweight',3100,8900,6200,0,2,'Draft', null);

insert into companies (company_name, website, country, company_type, wholesale_tier, notes) values
 ('Meher Boutique','meherboutique.in','India','Boutique','Tier 1','Repeat wholesale buyer in Hyderabad. Prefers bridal weaves.'),
 ('Sari House London','sarihouse.co.uk','United Kingdom','Retailer','Tier 2','Stocks lightweight cottons for summer. Pays in GBP.'),
 ('Anaya Exports','anayaexports.com','India','Distributor','Tier 1','Bulk buyer, 20+ pieces per order, slow payer.');

insert into contacts (full_name, first_name, contact_type, email, phone_number, country, lifecycle_stage,
  qualification_status, lead_score, business_category, source_name, source_type, niche, followers)
values
 ('Meher Siddiqui','Meher','B2B','meher@meherboutique.in','+91 98490 11223','India','Customer','Qualified',82,'Boutique','Instagram DM','Social','Bridal wear',18400),
 ('Priya Raghavan','Priya','B2C','priya.r@example.com','+91 99000 55441','India','Customer','Qualified',64,'Individual','Website','Organic',null,null),
 ('Alice Chen','Alice','B2B','alice@sarihouse.co.uk','+44 7700 900123','United Kingdom','Opportunity','Qualified',71,'Retailer','Trade fair','Event','South Asian fashion',9200),
 ('Rohit Mehra','Rohit','B2B','rohit@anayaexports.com','+91 98110 44556','India','Lead','Unreviewed',45,'Distributor','Referral','Referral',null,null),
 ('Sneha Kulkarni','Sneha','B2C','sneha.k@example.com','+91 90040 22118','India','Lead','Unreviewed',38,'Individual','Instagram','Social',null,null),
 ('Fatima Noor','Fatima','B2C','fatima.noor@example.com','+971 50 123 4567','UAE','New','Unreviewed',29,'Individual','WhatsApp','Social',null,null);

insert into contact_companies (contact_id, company_id, role_title, is_primary)
select c.contact_id, co.company_id, 'Owner', true from contacts c join companies co
  on (c.full_name='Meher Siddiqui' and co.company_name='Meher Boutique')
     or (c.full_name='Alice Chen' and co.company_name='Sari House London')
     or (c.full_name='Rohit Mehra' and co.company_name='Anaya Exports');

insert into marketing_permissions (contact_id, channel, status, lawful_basis_or_reason)
select contact_id, 'Email', case when lifecycle_stage in ('Customer','Opportunity') then 'OptedIn' else 'Unknown' end,
       'Signed up at checkout' from contacts;
insert into marketing_permissions (contact_id, channel, status, lawful_basis_or_reason)
select contact_id, 'WhatsApp', case when contact_type='B2B' then 'Allowed' else 'Unknown' end,
       'Existing business relationship' from contacts;

insert into opportunities (contact_id, company_id, name, stage, estimated_value, expected_close_date, notes)
select c.contact_id, cc.company_id, o.name, o.stage, o.val, o.close_date, o.notes
from (values
  ('Alice Chen','Spring cotton order — 40 pieces','Proposal',68000::numeric, current_date + 18,'Wants Kota Doria in sage and ivory. Sent lookbook.'),
  ('Rohit Mehra','Bulk bridal restock','Qualified',240000::numeric, current_date + 45,'Asked for Tier 1 pricing on katan silk.'),
  ('Meher Siddiqui','Festive capsule — 12 pieces','Negotiation',126000::numeric, current_date + 9,'Haggling on shipping. Close to yes.')
) as o(person,name,stage,val,close_date,notes)
join contacts c on c.full_name = o.person
left join contact_companies cc on cc.contact_id = c.contact_id;

insert into orders (order_number, contact_id, order_type, order_status, subtotal, discount, shipping, total, ordered_at)
select o.num, c.contact_id, o.otype, o.ostatus, o.sub, o.disc, o.ship, o.sub - o.disc + o.ship, o.when_at
from (values
 ('USY-1041','Meher Siddiqui','B2B','Fulfilled',82000::numeric,4000::numeric,0::numeric, now() - interval '26 days'),
 ('USY-1042','Priya Raghavan','B2C','Fulfilled',11900::numeric,0::numeric,250::numeric, now() - interval '18 days'),
 ('USY-1043','Priya Raghavan','B2C','Fulfilled',2600::numeric,0::numeric,150::numeric, now() - interval '11 days'),
 ('USY-1044','Alice Chen','B2B','Processing',31500::numeric,1500::numeric,2400::numeric, now() - interval '4 days'),
 ('USY-1045','Sneha Kulkarni','B2C','Pending Payment',2400::numeric,0::numeric,150::numeric, now() - interval '1 day')
) as o(num,person,otype,ostatus,sub,disc,ship,when_at)
join contacts c on c.full_name = o.person;

insert into order_items (order_id, product_id, quantity, unit_price)
select o.order_id, p.product_id, 1, p.retail_price
from orders o join products p on p.internal_sku = case
  when o.order_number='USY-1041' then 'USY-MS-001'
  when o.order_number='USY-1042' then 'USY-MS-002'
  when o.order_number='USY-1043' then 'USY-KD-004'
  when o.order_number='USY-1044' then 'USY-KD-005'
  else 'USY-KD-005' end;

insert into campaigns (campaign_name, objective, audience_type, channel, status, budget, spend, start_date, end_date, brief, offer)
values
 ('Festive Edit — Instagram','Sales','B2C','Instagram','Running',25000,11400, current_date - 12, current_date + 10,
  'Push the Mashru silk festive pieces to warm B2C audience ahead of the wedding season. Reels led, three posts a week.','Free shipping over Rs 10,000'),
 ('Wholesale Spring Outreach','Lead generation','B2B','Email','Scheduled',8000,0, current_date + 3, current_date + 33,
  'Email the Tier 1 and Tier 2 boutique list with the Kota Doria summer range and a tiered price sheet.','10% off first 20-piece order'),
 ('Bridal Waitlist — WhatsApp','Retention','B2C','WhatsApp','Draft',5000,0, null, null,
  'Warm the bridal waitlist with behind-the-loom content for the kadhua katan piece.','Early access 48 hours before launch');

insert into campaign_members (campaign_id, contact_id, member_status)
select ca.campaign_id, c.contact_id,
       case when ca.status='Running' then 'Sent' else 'Planned' end
from campaigns ca join contacts c on
  (ca.audience_type='B2C' and c.contact_type='B2C') or (ca.audience_type='B2B' and c.contact_type='B2B');

insert into campaign_posts (campaign_id, channel, title, body, hashtags, scheduled_for, status, product_id)
select ca.campaign_id, p.channel, p.title, p.body, p.tags, p.sched, p.status, pr.product_id
from (values
 ('Festive Edit — Instagram','Instagram','Reel — Magenta jangla close-up','Slow pan across the jangla jaal, then the full drape. Hook: "Forty days on the loom."','#banarasi #handloom #usaya', now() + interval '1 day', 'Scheduled','USY-MS-001'),
 ('Festive Edit — Instagram','Instagram','Carousel — How to spot real zari','Five checks, one per slide. Ends on the magenta piece.','#handloom #zari #sareelove', now() + interval '3 days','Approved','USY-MS-001'),
 ('Festive Edit — Instagram','Instagram','Story — Midnight blue styling','Three ways to style shikargah for a reception.','#styling #banarasi', now() + interval '5 days','Draft','USY-MS-002'),
 ('Festive Edit — Instagram','Instagram','Reel — Loom to doorstep','Weaver hands, folding, packing, courier. No face, hands only.','#madeinvaranasi', now() - interval '2 days','Published','USY-MS-002'),
 ('Wholesale Spring Outreach','Email','Email 1 — Summer cotton price sheet','Short intro, three hero pieces, link to the tiered sheet.','', now() + interval '4 days','Draft','USY-KD-004'),
 ('Wholesale Spring Outreach','Email','Email 2 — Follow up with lookbook','Reply-to-thread follow up seven days later for non-openers.','', now() + interval '11 days','Idea','USY-KD-005'),
 ('Bridal Waitlist — WhatsApp','WhatsApp','Broadcast — Kadhua progress','Photo of the loom at week three with a one-line caption.','', now() + interval '8 days','Idea','USY-MS-007')
) as p(camp,channel,title,body,tags,sched,status,sku)
join campaigns ca on ca.campaign_name = p.camp
left join products pr on pr.internal_sku = p.sku;

insert into activities (contact_id, activity_type, channel, direction, summary, follow_up_at)
select c.contact_id, a.atype, a.channel, a.dir, a.summary, a.follow
from (values
 ('Meher Siddiqui','Call','Phone','Outbound','Walked through festive capsule pricing. Wants shipping absorbed.', now() + interval '2 days'),
 ('Alice Chen','Email','Email','Outbound','Sent spring lookbook and tiered price sheet.', now() + interval '5 days'),
 ('Rohit Mehra','Meeting','Phone','Inbound','Asked for Tier 1 terms. Needs credit period of 30 days.', now() + interval '7 days'),
 ('Priya Raghavan','Note','Other','Inbound','Loved the Kota Doria. Asked about matching blouse fabric.', null)
) as a(person,atype,channel,dir,summary,follow)
join contacts c on c.full_name = a.person;

insert into showrooms (contact_id, slug, title, intro_text, cta_text, pricing_mode, status, public_enabled)
select c.contact_id, 'meher-festive-2026','Festive Capsule for Meher Boutique',
 'Twelve pieces chosen for your festive window. Wholesale pricing shown.',
 'Reply on WhatsApp to confirm your picks.','Wholesale','Published', true
from contacts c where c.full_name='Meher Siddiqui';

insert into showroom_products (showroom_id, product_id, sort_order)
select s.showroom_id, p.product_id, row_number() over (order by p.retail_price desc)
from showrooms s cross join products p where s.slug='meher-festive-2026' and p.status='Published';

insert into launch_jobs (product_id, stage, status, message)
select product_id, 'Review','Blocked','Waiting on final pricing approval before publishing.'
from products where internal_sku='USY-MS-007';
insert into launch_jobs (product_id, stage, status, message)
select product_id, 'Imagery','Queued','Phone photos uploaded. Model shoot generation not yet run.'
from products where internal_sku='USY-OG-009';

insert into integrations (provider, category, status, notes) values
 ('Wix','Storefront','Disconnected','Connect to publish listings to usayabanaras.com'),
 ('Shopify','Storefront','Disconnected','Alternative storefront sync'),
 ('Instagram','Social','Disconnected','Needed to schedule reels and carousels'),
 ('WhatsApp Business','Messaging','Disconnected','Broadcasts and order updates'),
 ('Email (Resend)','Messaging','Disconnected','Transactional and campaign email'),
 ('Razorpay','Payments','Disconnected','Payment links and reconciliation'),
 ('Shiprocket','Logistics','Disconnected','Label printing and tracking'),
 ('OpenAI','AI','Disconnected','Product copy, descriptions and campaign drafts'),
 ('Image generation','AI','Disconnected','Clean product cut-outs and model shoots'),
 ('Google Analytics','Analytics','Disconnected','Site traffic and attribution')
on conflict (provider) do nothing;

insert into settings (setting_key, setting_value) values
 ('brand_name','USAYA'),
 ('brand_tagline','Handwoven Banarasi, made in Varanasi'),
 ('default_currency','INR'),
 ('storefront_url','https://usayabanaras.com')
on conflict (setting_key) do nothing;
