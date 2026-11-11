# Commerce Business OS

One workspace for a handloom D2C brand: products, customers, orders, fulfilment,
campaigns, the people who weave the pieces, and the money.

**Live site:** https://arsh77344.github.io/crm101/

## Branches

| Branch | What is on it |
| --- | --- |
| `main` | This readme and the deploy workflow. Pushing here publishes the site. |
| `commerce-os` | The application: Next.js static front end on Supabase. |
| `python-legacy` | The original Python build, kept for reference. No longer used. |

The workflow on `main` checks out `commerce-os`, builds it, and publishes to GitHub Pages.

## The app

Static Next.js talking to Supabase (Postgres, auth, row level security) straight from the
browser. No server to run or pay for.

**Sell** — dashboard, products, product launch desk, orders, showrooms with a public buyer page
**Fulfil** — shipments, payments, returns and exchanges
**Customers** — contacts, companies, pipeline, activities
**Marketing** — campaigns with audience and content plan, content calendar, performance, consent centre
**Make & spend** — weavers and suppliers, expenses, profit and loss
**Run** — tasks, automations, integrations, team and roles, settings

Light and dark mode, switched from the bottom of the sidebar.

## Roles

`owner` · everything, including roles and settings
`admin` · everything day to day, plus settings and deletes
`sales` · create and edit records; cannot delete or change settings

The first account created becomes the Owner. Roles are enforced by Postgres row level
security, not only by the interface.

## Secrets

The Supabase anon key is public by design and the database is protected by row level
security. API keys for Wix, Instagram, WhatsApp, Razorpay and Shiprocket belong in the
deployment environment, never in the database.
