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
after processing, including parse, validation, quota and writer failures.
Shield cleanup from request cancellation; any oversized rejected or forcibly
spooled upload must be deleted. Tests verify
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
`convert-error`, `upgrade-click`, `checkout-opened`. Only `convert-success` has
properties: `balanced` (`yes`, `no`, `unknown`) and `layout` (a coarse allowlisted
ID: `deposit_table`, `deposit_lines`, `card_table`, `card_lines`, `unknown`). Never
send amounts, dates, names, descriptions, file names or account IDs.

## Reconciliation

Each conversion carries one reconciliation status. `balanced` requires exact
Decimal agreement between parsed rows and the printed statement evidence:
opening + money in - money out = closing for deposits, or previous - payments
and credits + purchases + fees + interest = new balance for cards. Deposit
opening/closing and every supplied subtotal must agree; card checks require all
six printed terms. Missing figures are never guessed as zero. `not_balanced`
includes a signed calculated-minus-printed difference and individual check
differences; `cannot_check` means required printed totals were not found.
This arithmetic checks the extraction against totals; it cannot certify every
description/date or rule out equal and opposite mistakes.

Keep reconciliation a pure function of rows plus extracted totals. Track row
provenance for inferred December-to-January years, balance-derived signs and
joined descriptions. Failed checks expose these flags in preview highlights and
Excel cell notes. Preserve the six-column CSV. JSON and preview include the
reconciliation and coarse layout; XLSX includes a `Checks` sheet with live
row-linked formulas and printed comparison values. Keep every workbook part
in memory and pin `openpyxl>=3.1,<3.2` for the internal writer API.

The synthetic harness reports per family balance rate, exact ordered rows,
missing/extra rows, silent errors (`balanced` with any wrong row), and false
alarms (correct rows shown `not_balanced`). Required gates: all ten existing
layouts and added card/edge families have 100% exact rows, zero silent errors,
and zero false alarms. Synthetic coverage is not a real-bank accuracy estimate.
Never commit or upload real statements. Verify backend, frontend/build, harness,
routing and browser suites; open a generated XLSX and evaluate its Checks
formulas against printed closing totals before finishing.

Password-protected files require an unlocked copy. Image-only and mixed scanned
transaction pages require OCR first. Statements with detected distinct account
headers must be split by account; never silently merge account balance chains.
The accuracy suite checks exact complete ordered rows, including missing/extra
rows and signs, and requires 100% for its known synthetic ground truth.
The API rejects statements over **100 pages** with HTTP 413 before transaction
extraction, in both billing modes. The current owner requires a real bounded
conversion deadline, superseding the former thread-only conversion boundary.
Page counting, PDF parsing, reconciliation, output writing, preview/base64 and
JSON serialization now run in a fresh disposable subprocess. The default
wall-clock deadline is **30 seconds**, including process startup, IPC and exit;
`STX_CONVERSION_TIMEOUT_SECONDS` may set a finite value greater than zero and at
most 120 seconds. Timeout returns recoverable HTTP 504. Timeout and cancellation
kill the worker's process group and reap it before releasing capacity or closing
the upload. No abandoned parsing thread continues running. The event loop uses
asynchronous memory pipes, leaving health requests responsive.

At most **two conversions per ASGI process** are admitted at once, including
parent billing, response assembly and upload cleanup; excess requests fail
promptly with HTTP 503 rather than queueing statement bytes. A separate child
process cap also bounds direct supervisor calls. Total host
capacity is ASGI worker count multiplied by two. Workers use a **512 MiB address
space limit**, a CPU-time backstop and disabled core dumps on the supported Linux
host. Responses are framed and capped at **64 MiB**; oversized output is rejected
before billing. All PDF, transaction, worksheet and response bytes remain in
memory; workers import neither API nor ledger/provider modules. Only after a
complete successful output and worker exit may the parent commit the existing
retry-safe debit and add the small charge envelope. Timeout, resource failure,
cancellation during document work and worker crash must not create conversion
charges or retry rows. Once completed work enters the existing parent billing
commit, cancellation waits for that commit; a lost response uses the same-key
retry contract rather than issuing another debit.
Retain tests that verify the actual child PID is gone, cleanup/capacity recovery,
health responsiveness, no disk output, and same-key successful retry.

## Billing

The owner explicitly authorized implementation of live/test billing on October
16, 2026, superseding the former test-only prohibition. Parent retains credentials,
provider/account settings, independent review, merge and deployment authority.
Agents open PRs only; no live purchases/refunds or provider/configuration changes.

`STX_STRIPE_MODE=test` is the default; `live` requires a matching `sk_live_` key.
Both modes require matching secret and signed webhook configuration. Missing
credentials preserve unmetered conversion and hidden billing. Invalid/mismatched
configuration fails closed at startup. Both secrets also require an app-specific
hosted portal configuration; subscription checkout validates its features before
creating a payable session. `/api/health` and `/api/pricing` advertise
`checkout_available` and `billing_mode`; availability means configuration, not a
successful provider connectivity test. Mock billing is an injected test double.

Preserve all catalog numbers: Free 3 pages, Starter $29/month/120 pages, Business
$79/500 and Firm $199/2000; packs 50/$30, 200/$100, 1000/$400. After included
pages, debit **one prepaid credit per page**. Stored cash-overage fields are
unused compatibility catalog data; never advertise them as actual charges or
introduce postpaid billing. No trials, coupons, annual plans or new fees.

The cryptographic browser account is a bearer capability. Require successful
persistent browser storage/readback before checkout or management; an explicit
payment retry may persist the same retained capability after initial storage
failure only when no different stored account exists. Disclose
browser-only access and no automatic/cross-device recovery. Use fixed POST URLs
for account, Checkout status and portal requests; capabilities/payment tokens
belong in bodies, never analytics or access URLs. Legacy GET routes exist only
for compatibility and must have operational log suppression.

Use a single durable SQLite database shared by API workers on one host, with
**separate mode-bound database paths for test and live**. Multiple hosts need a
shared transactional backend first. Additive stx_* tables retain owned Customer,
opaque purchase references, subscription paid-through/terminal state, invoice
cycles, payment reversals, FIFO credit lots, consumed history and reconciliation
holds. Existing rows/balances survive migration; unowned legacy purchases cannot
be attributed by account_id metadata. Never copy test balances into live billing.
Back up billing metadata before rollout; never roll back by deleting it.

Pin stripe-python 14.4.1 and request/webhook snapshot API
`2026-02-25.clover`. Requests and signed objects must match configured livemode.
Namespace new metadata `app=statement-to-excel` plus opaque purchase/binding
references; never send browser account capabilities to Stripe metadata.
Resolve events through owned durable references; valid foreign-app events are
acknowledged without ledger/receipt mutation. Conflicting owned evidence fails
closed. Use actual invoice.parent.subscription_details, InvoicePayments and
subscription.items periods; do not restore removed legacy invoice fields.

Customer and Checkout idempotency references commit before network calls. Reuse
owned Customers and pending requests across concurrency/restarts. Ambiguous
requests beyond 23 hours require owner reconciliation. Block duplicate initial
subscriptions, including retained paid service after an older-invoice reversal.
Different-SKU checkout may replace an old choice only after retrieving its
recorded app/account/customer/mode/purchase-owned Session and provider-confirmed
unpaid expiry. Preserve all original keys/rows/aliases; never trust cancel URLs,
expire completed/processing/foreign payments or discard an ambiguous creation.
An open Session may already have an unpaid PaymentIntent. Verify its owned
reference/customer/mode/USD amount, zero received/capturable amounts and unpaid
state before and after expiring that Session. Only Checkout expiry prevents its
completion; never cancel its PaymentIntent directly. Reject conflicting,
processing, settled or capturable evidence and retain the original reservation.
Stripe-hosted portal derives its Customer solely from the account
binding, validates app ownership/mode and uses only the canonical app return URL
(localhost permitted only for test). Parent supplies a dedicated portal
configuration per mode with payment-method updates and period-end cancellation,
without plan-change controls.

Paid Checkout/paid invoice evidence grants once; redirects and active subscription
objects never grant. A matching newer paid cycle resets allowance once. Enforce
paid-through on reads/debits, even without webhooks. Period-end cancellation keeps
paid access until expiry; terminal cancellation/unpaid expiry removes recurring
access while preserving separate packs. Stale events never revive terminal or
reversed access. Full refunds revoke unused purchase credits/access atomically;
consumed, partial or disputed reversals create a durable owner-reconciliation
hold, preserving unrelated credits and consumed history without negative balances.
Reverse the affected invoice cycle separately from the renewal stop. Refunding
an older invoice preserves a different, newer, already-paid current invoice and
its usage through its paid end, even after provider cancellation/deletion or a
restart. Retain a durable invoice reference; its own reversal or expiry ends
that service. Verified pre-stop paid invoices may recover out-of-order delivery
once; missing/equal-second/conflicting ordering creates an explicit unresolved
owner hold. Never revive an unrelated terminal subscription or grant a future
cycle after the renewal stop. Cancellation confirmation must not resolve those
reconciliation holds.
Subscription reversals atomically queue verified immediate cancellation with no
proration or new invoice, preventing future Stripe renewal. Provider I/O occurs
after commit; durable leases/backoff and startup/30-second retries recover lost
responses without another customer request. Replacement purchases stay blocked
until cancellation is confirmed. An unused full-refund cancellation hold clears
after confirmation; consumed/partial/disputed holds require owner reconciliation.
`payments.resolve_hold` is a trusted owner-only database operation after manual
reconciliation; it never restores a revoked purchase or subscription. No public
admin/recovery API is introduced. Retain focused concurrent/restart, signature,
mode, foreign-event, cycle, failure/recovery and reversal tests.

## Tracking and consent

Keep exactly one Umami destination `0ee0e19b-b29b-4c98-b3f6-a92a43b4ba5a`
and the five existing funnel events/allowlisted conversion enums above. The
blocking privacy bootstrap strips all query/hash/history state before any SDK;
return reconciliation is drained into a private module cache first. Missing
bootstrap prevents SDK loading. Umami automatic tracking/performance is disabled;
manual pageviews/events pass a fresh sanitized payload boundary. Fixed page URL,
title and empty referrer prevent statement/payment/account/search disclosure.

Optional public build configuration: `VITE_GA_MEASUREMENT_ID` and
`VITE_CF_WEB_ANALYTICS_TOKEN`; unset means no corresponding SDK. Parent supplies
verified values, never guessed IDs. The public-only tracked
frontend/.env.production survives fresh-clone nested frontend builds; leave its
two values empty until verified identities are supplied. Never put secrets there. Google and Cloudflare both default OFF until explicit optional
consent. A versioned joint choice names both services; old Google-only acceptance
must not enable either. Validate preference write/readback, stop SDKs before
fallible denial persistence, remove stale acceptance when possible, and report
unsaved withdrawal honestly without automatic reload. Handle cross-tab revocation
and storage.clear(). Choice is localized in all five languages. Ads/Signals/User-ID features stay off. Parent must disable all GA
Enhanced Measurement in the actual data stream before configuring its ID; source
uses sanitized manual pageviews/funnel events only. Preserve Umami's hyphenated
names; Google's five names use underscores. Google cookies use host-only
cookie_domain:none and app-owned stx prefix. Delete only this host's stx_ga and
this stream's stx_ga_<ID>, never sibling/parent-domain cookies. Google can create anonymous
browser/session identifiers; never confuse these with app capabilities/payment
session tokens. Conversion/checkout cannot depend on tracking, consent or ads.

Load Cloudflare's manual beacon once after consent with spa:false; it may emit multiple
lifecycle/vitals packets. Suppress BOTH optional SDKs on sensitive original navigation URLs,
visible query/hash/path or document referrers because SDK navigation timing can
retain the original URL after replaceState. Google diagnostics can bypass manual
page metadata and ga-disable. Use a disposable same-origin Google frame receiving
only sanitized commands; stop its exit handlers before disposal on withdrawal,
including pending SDK loads and diagnostics timers. This is lifecycle isolation,
not a security boundary against a trusted same-origin SDK. Direct frame visits
remain inert; recheck consent/current frame before initialization.
The pinned CF 2026.10.1 beacon uses a consent-controlled global accessor; SRI
fails closed on changed bytes. Retire its listeners for this document after
withdrawal; reallow can require an explicit next visit/reload without discarding
in-memory conversion automatically. No DNS/proxy/TLS changes. Enable
owner QA before navigation with localStorage stx_owner_qa='on', then reload;
all providers are suppressed and QA evidence stays local. Never generate fake
provider ingestion or call synthetic visits genuine acquisition. Inspect actual
SDK serialized bodies with synthetic canaries, not callback counts alone.

Preserve the exact document-memory/deletion promises in all locales while
accurately disclosing retained billing/idempotency metadata, anonymous usage and
optional Google/Cloudflare analytics. Parent handles app-specific nginx/uvicorn URL log
suppression; do not claim it is installed from this repository. See
`docs/codex-live-billing-2026-10-16.md` for provider setup and verification limits.

## Working policy

**Work on branches and open PRs; never push to main.** Keep work scoped to the
requested goals. Run all applicable suites before opening a PR. Do not merge,
deploy, alter production configuration or enable live charges without the user's
explicit authorization. Preserve the SEO canonical/indexing contract, favicons,
brand, locales and the existing single analytics destination.

Physical-device and simulator testing: Whenever a task needs or would benefit from a physical iPhone, first check whether Michael's N759MS iPhone is connected and available on the host doing the testing, using xcrun devicectl list devices (or xcrun xctrace list devices when appropriate). If N759MS is connected, agents may use it for relevant testing without asking again. Preserve existing device data and unrelated apps; do not erase/reset it. A connected but locked/unpaired device is not usable until that actual condition is resolved. On a host with sufficient measured capacity, especially the Mac Studio, agents may freely use iOS and Android simulators/emulators for relevant tests without additional permission. Inspect host load and memory first, use conservative concurrency, and distinguish simulator checks from real physical-device checks. Cloud environments without device access must report that limitation, never claim a phone test occurred. Existing App Store publication gates still apply.
