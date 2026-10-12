# Statement→Excel

## Product

This monorepo converts text-based bank-statement PDFs to Excel, CSV or JSON.
`frontend/` is Vite/React/TypeScript; `backend/` is Python/FastAPI, pdfplumber,
Decimal transaction parsing and in-memory output writers. It supports a free
page allowance, paid plans and prepaid credits. The bank accuracy corpus is
programmatically generated, synthetic and bank-inspired; it is not a claim of
compatibility with every real statement from those banks.

## Build and verification

From the repository root:

```sh
python3 -m venv backend/.venv
backend/.venv/bin/python -m pip install -e './backend[test,server]'
cd frontend && npm ci && cd ..
(cd backend && .venv/bin/python -m pytest)
(cd backend && .venv/bin/python -m tests.accuracy_harness --output ../work/accuracy)
(cd frontend && npm run build && npm test)
node frontend/scripts/test-api-routing.mjs
(cd frontend && npx playwright install --with-deps chromium && npm run test:e2e)
```

The routing regression starts the real API and Vite dev/production-preview
servers. Playwright starts the API and a built frontend, uploads synthetic
statements, verifies real workbook downloads and checks error paths. CI runs
backend, frontend, accuracy, routing and browser tests. Use
`STX_CHROMIUM_PATH=/usr/bin/chromium` when using a system browser.

## Deploy model and API routing

The frontend is published by an external autodeploy job to
https://statement-to-excel.apps.smolkin.org/. GitHub CI tests builds; it does not
deploy either service. Vite produces static `frontend/dist/`; publishing those
files does not start Python or install an API reverse proxy.

The backend must run as a separately supervised ASGI service. The repository's
README specifies port 8000. The local command, run from `backend/`, is:

```sh
.venv/bin/uvicorn statement_to_excel.api:app --host 127.0.0.1 --port 8000
```

The frontend defaults to same-origin `/api/*`. Vite dev and preview forward these
paths unchanged to `STX_API_TARGET`, default `http://127.0.0.1:8000`.
For production, the hosting reverse proxy must forward `/api/*` to the API
**before** its SPA fallback, retaining `/api/convert`. A deployable example is
`frontend/deploy/nginx.conf.example`; its document root and upstream require the
operator's actual paths. If services use separate origins, build with
`VITE_API_BASE` and configure the API's allowed origins appropriately.

The repository does not identify the actual backend machine, process manager,
service unit, TLS termination, active reverse-proxy configuration or the external
autodeploy job's settings. Do not guess or claim this example is installed.
A safe synthetic production check on 2026-10-12 observed `/api/health` returning
JSON with `billing: mock` and `/api/convert` successfully returning five rows.
The historical July SPA fallthrough is not currently reproducible there.

## Privacy

Preserve the site's **"No data is stored"** statement-data promise in all locales
and its disclosure that the hosted UI uploads PDFs to this app's server.
Process uploads and outputs in memory. Multipart temporary files must be closed
and deleted in a `finally` block immediately after processing, including parse,
validation, quota and writer failures; tests exercise actual rolled disk files.
The proxy must disable request/response disk buffering for `/api/*`. Never log,
persist, send to analytics or include in payment metadata PDF contents, filenames,
transaction rows, balances or descriptions. Never commit real statements,
customer information, secrets or generated runtime databases.

Only anonymous account IDs, usage counters, opaque idempotency keys, one-way
conversion fingerprints and payment/entitlement metadata enter the billing
SQLite database. No document bytes or extracted transactions are saved. The
existing single Umami tag receives only `file-selected`, `convert-success`,
`convert-error`, `upgrade-click`, `checkout-opened`, without document/account data.

Password-protected files require an unlocked copy. Image-only and mixed scanned
transaction pages require OCR first. Statements with detected distinct account
headers must be split by account; never silently merge account balance chains.
The accuracy suite checks exact complete ordered rows, including missing/extra
rows and signs, and requires 100% for its known synthetic ground truth.

## Billing

Billing stays in **Stripe test mode until Michael approves live charges**.
This implementation rejects live keys and live webhook events; no configuration
switch enables live payments. Default checkout fails closed until test credentials
and webhook settings exist. Mock billing is only an explicitly injected test
double, not a supported deployment provider.

The anonymous cryptographic account ID is a bearer capability: possession permits
using its allowance. The implementation supports one host with a durable SQLite
database shared by its API workers. Multiple hosts require a transactional shared
backend before enabling checkout; ephemeral or separate databases break durable
idempotency. Never log account IDs or include them in analytics.

Configure `STX_BILLING_DATABASE` on durable storage outside the public web root,
`STX_BILLING_PROVIDER=stripe`, `STX_STRIPE_SECRET_KEY` with a test key,
`STX_STRIPE_WEBHOOK_SECRET`, and `STX_CHECKOUT_ORIGIN`; see `.env.example`.
Do not store key values in this repository. Checkout creation must reserve a
persistent idempotency key before requesting Stripe. Signed paid webhooks grant
entitlements atomically once per session. Browser redirects never grant Pro.
Duplicate events, concurrent requests, ambiguous provider failures and process
restarts must remain safe. Ambiguous requests beyond Stripe's idempotency-retention
window fail closed for owner reconciliation. Monthly lifecycle events reset paid
cycle allowance and revoke cancelled subscription access.

## Working policy

**Work on branches and open PRs; never push to main.** Keep work scoped to the
requested goals. Run all applicable suites before opening a PR. Do not merge,
deploy, alter production configuration or enable live charges without the user's
explicit authorization. Preserve the SEO canonical/indexing contract, favicons,
brand, locales and the existing single analytics destination.
