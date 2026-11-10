# Updated Commerce Business OS — 1 November 2026

This folder contains the full updated project, including the latest uncommitted fixes from the working copy. You do not need to merge separate update files.

## Start

Python 3.12 or newer is required. Follow README.md to install dependencies. On macOS, open START_APP.command; on Windows use START_APP.bat; on Linux use START_APP.sh. First-launch sign-in details are created in data/FIRST_RUN_CREDENTIALS.txt.

## Included updates

- Product launch workspace with uploads, brand preferences, titles, descriptions, SEO and image alt text.
- Colour/size variants, photo mapping, pricing research, listing review and social kits.
- Uploaded drafts immediately appear in Products; edits update the same linked draft.
- Connect AI page, combined Generate with AI action, progress messages and previews as results arrive.
- Studio edits followed by optional mannequin or AI-model photography; originals and completed results are preserved.
- Reviewed publication adapters for Shopify and Wix, with duplicate-delivery protection.

## Connection status and validation

No API key or website connection is included. AI generation requires your own OpenAI API key and available API usage. Website publication requires a configured store and publicly reachable product images. The local team-test mode keeps external store writes disabled by default. Nothing has been published.

All 35 product-launch acceptance checks passed using simulated provider responses. Live AI generation and live Shopify/Wix publication have not been verified. See docs/PRODUCT_LAUNCH.md for details and limits.

## Data in this download

This is a clean project package with the original sample data. It excludes personal uploads, the active database, API keys, local login credentials, backups, logs, Git history and installed dependencies. Your existing working folder and its data remain unchanged.

CHECKSUMS.txt contains SHA-256 hashes for every other packaged file.
