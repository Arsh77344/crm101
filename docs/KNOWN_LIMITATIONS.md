# Known Limitations — Commerce Business OS 1.0.0-beta.6

**Build:** TEAM-TEST-006  
**Schema:** 58

- Python **3.12+** remains an explicit tester prerequisite. This release is not claimed to contain a self-contained bundled macOS/Windows Python runtime.
- Live external-provider acceptance is not part of the default offline team package. Wix, Shopify, Meta, Google, Microsoft 365, WhatsApp, Stripe, external AI and MCP require eligible accounts, credentials, permissions and public callback/webhook setup where applicable.
- Roadmap-only providers remain **Planning only** and deliberately expose no fake connection success.
- Stripe provides validation/reconciliation foundations rather than a complete general checkout/capture/refund implementation.
- Local video preparation works without an AI provider; optional generative motion requires separate provider validation.
- The team build is local-first SQLite. Production HTTPS, managed secrets, production database/object storage, load testing and deployment operations remain separate production-readiness work.
- Windows launcher logic is statically reviewed in this Linux verification environment; native Windows execution requires Windows acceptance.
