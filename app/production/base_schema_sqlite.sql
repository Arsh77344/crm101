CREATE TABLE activities (
          activity_id TEXT PRIMARY KEY, contact_id TEXT, company_id TEXT, opportunity_id TEXT,
          activity_type TEXT, channel TEXT, direction TEXT, summary TEXT,
          follow_up_at TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP,
          FOREIGN KEY(contact_id) REFERENCES contacts(contact_id));
CREATE TABLE campaign_members (
          campaign_id TEXT NOT NULL, contact_id TEXT NOT NULL, member_status TEXT DEFAULT 'Planned',
          added_at TEXT DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY(campaign_id, contact_id),
          FOREIGN KEY(campaign_id) REFERENCES campaigns(campaign_id),
          FOREIGN KEY(contact_id) REFERENCES contacts(contact_id));
CREATE TABLE campaigns (
  campaign_id TEXT PRIMARY KEY,
  campaign_name TEXT,
  audience_type TEXT,
  channel TEXT,
  status TEXT DEFAULT 'Draft',
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE companies (
  company_id TEXT PRIMARY KEY,
  company_name TEXT,
  website TEXT,
  country TEXT,
  company_type TEXT,
  wholesale_tier TEXT,
  notes TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE contact_companies (
  contact_id TEXT,
  company_id TEXT,
  role_title TEXT,
  is_primary INTEGER DEFAULT 0,
  PRIMARY KEY(contact_id,company_id),
  FOREIGN KEY(contact_id) REFERENCES contacts(contact_id),
  FOREIGN KEY(company_id) REFERENCES companies(company_id)
);
CREATE TABLE contacts (
  contact_id TEXT PRIMARY KEY,
  contact_type TEXT CHECK(contact_type IN ('B2B','B2C','Both','Unknown')) DEFAULT 'Unknown',
  username TEXT,
  first_name TEXT,
  full_name TEXT,
  email TEXT,
  phone_number TEXT,
  phone_country_code TEXT,
  website TEXT,
  biography TEXT,
  country TEXT,
  language TEXT,
  niche TEXT,
  entity_type TEXT,
  followers INTEGER,
  following INTEGER,
  source_name TEXT,
  source_type TEXT,
  source_reference TEXT,
  qualification_status TEXT DEFAULT 'Unreviewed',
  lifecycle_stage TEXT DEFAULT 'New',
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
, lead_score INTEGER DEFAULT 0, business_category TEXT, relevance_reason TEXT, data_quality TEXT DEFAULT "Unknown", next_follow_up TEXT);
CREATE TABLE interactions (
  interaction_id TEXT PRIMARY KEY,
  contact_id TEXT NOT NULL,
  campaign_id TEXT,
  channel TEXT,
  interaction_type TEXT,
  direction TEXT,
  subject_or_summary TEXT,
  occurred_at TEXT,
  metadata_json TEXT,
  FOREIGN KEY(contact_id) REFERENCES contacts(contact_id),
  FOREIGN KEY(campaign_id) REFERENCES campaigns(campaign_id)
);
CREATE TABLE marketing_permissions (
  permission_id TEXT PRIMARY KEY,
  contact_id TEXT NOT NULL,
  channel TEXT NOT NULL CHECK(channel IN ('Email','WhatsApp','SMS','Phone','Other')),
  status TEXT NOT NULL DEFAULT 'Unknown' CHECK(status IN ('Unknown','Allowed','OptedIn','OptedOut','Suppressed','DoNotContact')),
  lawful_basis_or_reason TEXT,
  evidence_reference TEXT,
  jurisdiction TEXT,
  updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY(contact_id) REFERENCES contacts(contact_id)
);
CREATE TABLE opportunities (
  opportunity_id TEXT PRIMARY KEY,
  contact_id TEXT,
  company_id TEXT,
  name TEXT,
  stage TEXT DEFAULT 'New',
  estimated_value REAL,
  currency TEXT,
  expected_close_date TEXT,
  notes TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP, showroom_id TEXT,
  FOREIGN KEY(contact_id) REFERENCES contacts(contact_id),
  FOREIGN KEY(company_id) REFERENCES companies(company_id)
);
CREATE TABLE order_items (
  order_item_id TEXT PRIMARY KEY,
  order_id TEXT NOT NULL,
  product_id TEXT NOT NULL,
  quantity INTEGER NOT NULL,
  unit_price REAL NOT NULL,
  FOREIGN KEY(order_id) REFERENCES orders(order_id),
  FOREIGN KEY(product_id) REFERENCES products(product_id)
);
CREATE TABLE orders (
  order_id TEXT PRIMARY KEY,
  contact_id TEXT,
  company_id TEXT,
  order_type TEXT CHECK(order_type IN ('B2B','B2C')),
  order_status TEXT DEFAULT 'Draft',
  subtotal REAL,
  discount REAL,
  shipping REAL,
  total REAL,
  currency TEXT,
  external_order_reference TEXT,
  ordered_at TEXT,
  FOREIGN KEY(contact_id) REFERENCES contacts(contact_id),
  FOREIGN KEY(company_id) REFERENCES companies(company_id)
);
CREATE TABLE product_images (
  image_id TEXT PRIMARY KEY,
  product_id TEXT NOT NULL,
  image_role TEXT,
  original_filename TEXT,
  source_archive TEXT,
  relative_path TEXT,
  is_primary INTEGER DEFAULT 0,
  FOREIGN KEY(product_id) REFERENCES products(product_id)
);
CREATE TABLE products (
  product_id TEXT PRIMARY KEY,
  internal_sku TEXT UNIQUE,
  source_product_name TEXT,
  public_product_name TEXT,
  colour TEXT,
  weave_or_motif TEXT,
  fabric TEXT,
  category TEXT DEFAULT 'Banarasi Saree',
  description TEXT,
  cost_price REAL,
  retail_price REAL,
  wholesale_price REAL,
  currency TEXT,
  stock_qty INTEGER,
  moq INTEGER,
  status TEXT DEFAULT 'Draft',
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
, tags TEXT, published_at TEXT, product_code TEXT, duplicate_group TEXT);
CREATE TABLE settings (
          setting_key TEXT PRIMARY KEY, setting_value TEXT);
CREATE TABLE showroom_events (
          event_id TEXT PRIMARY KEY, showroom_id TEXT NOT NULL, product_id TEXT,
          event_type TEXT NOT NULL, event_at TEXT DEFAULT CURRENT_TIMESTAMP, user_agent TEXT,
          FOREIGN KEY(showroom_id) REFERENCES showrooms(showroom_id),
          FOREIGN KEY(product_id) REFERENCES products(product_id));
CREATE TABLE showroom_products (
  showroom_id TEXT,
  product_id TEXT,
  sort_order INTEGER DEFAULT 0,
  custom_price REAL,
  PRIMARY KEY(showroom_id,product_id),
  FOREIGN KEY(showroom_id) REFERENCES showrooms(showroom_id),
  FOREIGN KEY(product_id) REFERENCES products(product_id)
);
CREATE TABLE showroom_views (
          view_id TEXT PRIMARY KEY, showroom_id TEXT NOT NULL, viewed_at TEXT DEFAULT CURRENT_TIMESTAMP,
          user_agent TEXT, FOREIGN KEY(showroom_id) REFERENCES showrooms(showroom_id));
CREATE TABLE showrooms (
  showroom_id TEXT PRIMARY KEY,
  contact_id TEXT,
  company_id TEXT,
  slug TEXT UNIQUE,
  title TEXT,
  pricing_mode TEXT CHECK(pricing_mode IN ('Retail','Wholesale','Hidden')) DEFAULT 'Hidden',
  status TEXT DEFAULT 'Draft',
  created_at TEXT DEFAULT CURRENT_TIMESTAMP, intro_text TEXT, cta_text TEXT, public_enabled INTEGER DEFAULT 1,
  FOREIGN KEY(contact_id) REFERENCES contacts(contact_id),
  FOREIGN KEY(company_id) REFERENCES companies(company_id)
);
CREATE INDEX idx_contacts_email ON contacts(email);
CREATE INDEX idx_contacts_phone ON contacts(phone_number);
CREATE INDEX idx_contacts_type ON contacts(contact_type);