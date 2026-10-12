# Statement→Excel

## Product

This monorepo converts text-based bank-statement PDFs to Excel, CSV or JSON.
`frontend/` is Vite/React/TypeScript; `backend/` is Python/FastAPI, pdfplumber,
Decimal transaction parsing and in-memory output writers. It supports a free
page allowance, paid plans and prepaid credits when checkout is configured;
otherwise conversion is unmetered. The bank accuracy corpus is
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

Production nginx **must match** the example's `/api/*` privacy settings:
`client_body_buffer_size 21m`, `proxy_request_buffering off` and
`proxy_buffering off`, for both HTTP/1.1 and HTTP/2. The 21 MiB
`client_max_body_size` accommodates the multipart envelope; the API's file limit
remains **20 MiB**, with HTTP 413 for larger PDFs. Do not install an additional
proxy that writes accepted request bodies or conversion responses to disk.

The repository does not identify the actual backend machine, process manager,
service unit, TLS termination, active reverse-proxy configuration or the external
autodeploy job's settings. Do not guess or claim this example is installed.
A safe synthetic production check on 2026-10-12 observed `/api/health` returning
JSON with `billing: mock` and `/api/convert` successfully returning five rows.
The historical July SPA fallthrough is not currently reproducible there.

## Privacy

Preserve the site's **"No statement data is stored. Your PDF is uploaded to our
server for conversion and deleted right after."** privacy copy in all locales.
Account/credit records and limited idempotency metadata are stored; never claim
that no data of any kind is stored.
Process accepted uploads and outputs in memory. This app sets Starlette's
multipart spool threshold to **21 MiB**, above its **20 MiB** file limit, so
accepted uploads never roll onto disk. Excel worksheet XML and the resulting
workbook also stay in memory. Close uploads in a `finally` block immediately
after processing, including parse, validation, quota and writer failures; any
oversized rejected or forcibly spooled upload must be deleted. Tests verify
real 5 MiB multipart uploads in every format create no temporary file, the
20 MiB boundary, and deletion of deliberately rolled files. Never log,
persist, send to analytics or include in payment metadata PDF contents, filenames,
transaction rows, balances or descriptions. Never commit real statements,
customer information, secrets or generated runtime databases.

Only anonymous account IDs, usage counters, opaque idempotency keys, one-way
conversion fingerprints and payment/entitlement metadata enter the billing
SQLite database in configured billing mode. Unmetered conversion writes no
account, conversion-idempotency or checkout rows. Conversion idempotency rows include a SHA-256 fingerprint
of the upload and conversion options and a fixed creation timestamp. Their
retention window is **24 hours**; replays do not extend it. Every conversion
POST opportunistically deletes rows older than 24 hours, including rejected
requests. With no conversion traffic, removal of expired rows waits for the
next request; expired keys nevertheless behave as new conversions and can debit usage again.
The migration discards legacy fingerprint rows whose creation time is unknown,
without changing account/credit balances or previous usage; those keys also
behave as new requests. Checkout and payment entitlement records have independent
retention and keep their existing durable idempotency guarantees.

No document bytes or extracted transactions are saved. The
existing single Umami tag receives only `file-selected`, `convert-success`,
`convert-error`, `upgrade-click`, `checkout-opened`, without document/account data.

Password-protected files require an unlocked copy. Image-only and mixed scanned
transaction pages require OCR first. Statements with detected distinct account
headers must be split by account; never silently merge account balance chains.
The accuracy suite checks exact complete ordered rows, including missing/extra
rows and signs, and requires 100% for its known synthetic ground truth.
The API rejects statements over **100 pages** with HTTP 413 before transaction
extraction, in both billing modes. Page counting, PDF parsing, output writing
and serialization run in a worker thread so a conversion does not block health
requests on the event loop.

## Billing

Billing stays in **Stripe test mode until Michael approves live charges**.
This implementation rejects live keys and live webhook events; no configuration
switch enables live payments. Mock billing is only an explicitly injected test
double, not a supported deployment provider.

The service has two modes, controlled by the Stripe provider's single
`checkout_available` configuration rule. Both `GET /api/pricing` and
`GET /api/health` expose that boolean without exposing credentials.

- **Checkout unavailable:** production runs with `STX_BILLING_PROVIDER=stripe`
  and remains **unmetered until Stripe test credentials and the webhook are
  configured**. Missing either an `sk_test_` secret key or a `whsec_` webhook
  secret makes `checkout_available=false`. Valid statements up to 100 pages
  convert with the same 20 MiB upload limit, PDF validation, output formats and
  upload deletion.
  Conversion returns `charge: {"metered": false, "pages": N}` and never consumes
  allowance/credits or returns 402. Requests write no account, conversion-charge
  or checkout rows; cleanup of previously expired fingerprints may still run.
  The frontend reads `/api/pricing` on load, treating failure as unavailable;
  it hides pricing navigation, the hero pricing button, Pricing and the account
  chip, and makes no account or checkout requests.
- **Checkout available:** both credentials satisfy the existing Stripe test
  configuration rule. `checkout_available=true` enables the existing three-page
  free allowance, plan/credit metering, 24-hour conversion idempotency and 402
  responses when allowance/credits are exhausted. Checkout creation and paid
  webhooks retain their durable purchase/Pro idempotency guarantees. Frontend
  checkout failures use the localized `checkout_error` copy, never raw backend
  billing text. Availability indicates configuration, not a successful remote
  Stripe connectivity test.

Do not add marketing promises about this temporary configuration mode.

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
