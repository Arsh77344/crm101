# Commerce Business OS

Products, customers, campaigns and launches for a handloom D2C brand.
Rebuilt in JavaScript: Next.js (App Router) + Supabase (Postgres, auth, storage), deployed on Vercel.

## Screens
Dashboard · Products · Product launch desk · Orders · Showrooms (with a public buyer page)
Contacts · Companies · Pipeline · Activities
Campaigns (audience + content plan) · Content calendar · Performance · Consent centre
Integrations · Team & roles · Settings

## Roles
- **owner** — everything, including roles and settings
- **admin** — everything day to day, plus settings and deletes
- **sales** — create and edit records; cannot delete or change settings

The first account created becomes the Owner. Everyone after arrives as Sales and is promoted from Team & roles.

## Environment
    NEXT_PUBLIC_SUPABASE_URL=...
    NEXT_PUBLIC_SUPABASE_ANON_KEY=...

API keys for Wix, Instagram, WhatsApp, OpenAI and the rest belong in the deployment's
environment settings, never in the database.

## Database
Apply in order against the Supabase project:
1. `supabase/0001_schema.sql` — tables
2. `supabase/0002_policies.sql` — row level security
3. `supabase/0003_demo.sql` — demo content (safe to delete later)

## Local
    npm install && npm run dev
