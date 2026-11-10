# Commerce Business OS

One workspace for a handloom D2C brand: products, customers, orders, fulfilment,
campaigns, the people who weave the pieces, and the money.

Static Next.js front end + Supabase (Postgres, auth, row level security).
Deployed to GitHub Pages; no server to run or pay for.

## Screens
**Sell** — dashboard, products, product launch desk, orders, showrooms (with a public buyer page)
**Fulfil** — shipments, payments, returns and exchanges
**Customers** — contacts, companies, pipeline, activities
**Marketing** — campaigns (audience + content plan), content calendar, performance, consent centre
**Make & spend** — weavers and suppliers, expenses, profit and loss
**Run** — tasks, automations, integrations, team and roles, settings

Light and dark mode, switched from the bottom of the sidebar.

## Roles
- **owner** — everything, including roles and settings
- **admin** — everything day to day, plus settings and deletes
- **sales** — create and edit records; cannot delete or change settings

The first account created becomes the Owner. Everyone after arrives as Sales and is promoted from Team & roles.
Roles are enforced by Postgres row level security, not only by the interface.

## Environment
    NEXT_PUBLIC_SUPABASE_URL=...
    NEXT_PUBLIC_SUPABASE_ANON_KEY=...
    NEXT_PUBLIC_BASE_PATH=/crm101   # only when served from a repo subpath

The anon key is public by design; the database is protected by row level security.
API keys for Wix, Instagram, WhatsApp, Razorpay, Shiprocket and the rest belong in
the deployment environment, never in the database.

## Local
    npm install && npm run dev
