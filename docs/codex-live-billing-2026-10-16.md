# Live billing and analytics — October 16, 2026

Repository: smolkapps/statement-to-excel. Branch:
`codex/live-billing-analytics-20261016`. Refreshed base:
`575d0e4c15f24cf6ce87e6496c7c3be19ead986a` (merged PR #7).
Verified implementation head: 3803d2a87d355ef9b7acd0d4ffcd436c0ba9fa08.
This report is a documentation-only follow-up to that implementation commit;
the PR records its current delivery head. PRs #5/#6/#7 and their branches/reports
are preserved. No other open PR owned this work at the initial or final remote
check. Nothing was pushed to main, merged or deployed.

## Authority and changes

The October 16 owner instruction authorizes implementation of the full existing
six-SKU catalog in test/live modes and configurable tracking. It supersedes the
old test-only/unmetered implementation restriction. Parent owns credentials,
provider/account/environment changes, independent review, merge and deployment.
No keys were received, no live/test hosted payments or refunds were performed,
and no external provider/account configuration was changed here.

Root AGENTS.md is owned and updated by this Codex task. It now records current
billing/analytics authority and invariants; the exact physical-device/simulator
paragraph from PR #7 remains present once and unchanged. Existing document,
capacity, deadline, reconciliation and branch/PR policies are retained.

| SKU | Server-owned USD price | Entitlement |
| --- | ---: | ---: |
| free | $0 | 3 pages |
| starter | $29/month | 120 pages/cycle |
| business | $79/month | 500 pages/cycle |
| firm | $199/month | 2,000 pages/cycle |
| pack_50 | $30 | 50 prepaid credits |
| pack_200 | $100 | 200 prepaid credits |
| pack_1000 | $400 | 1,000 prepaid credits |

One prepaid credit covers one page after included pages. No cash overage is
charged. The compatibility .30/.20/.12 catalog fields and all prices/quantities
remain unchanged; all five locales describe the actual prepaid-credit debit.
No trial, coupon, annual price, automatic postpaid charge or new SKU was added.

`STX_STRIPE_MODE` defaults to test; explicit live requires matching credentials.
Signed event/object modes and the mode-bound database must match. Missing either
secret preserves unmetered conversion, hidden pricing and no conversion/account
writes. Invalid/mismatched settings fail closed. With both secrets, an
app-specific hosted portal configuration is required; subscription checkout
validates its mode and cancellation/payment-method features before creating a
payable session. Pricing/health expose truthful mode/configuration availability,
not a claim of provider connectivity. All six paid SKUs have initial purchase
paths once configured.

New additive durable tables bind a cryptographic browser capability to an owned
Customer, opaque purchase reference, subscription and mode. No account capability
enters Stripe metadata. Customer and Checkout idempotency reservations commit
before provider I/O, including the Customer/purchase binding before a potentially
ambiguous Checkout result. Pending/concurrent/restarted requests reuse references;
ambiguous creation beyond 23 hours requires owner reconciliation. Duplicate
active subscriptions are blocked. Persistent browser storage/readback is required
before payment/management. Browser-only recovery/support limits are disclosed.

Paid Checkout/invoice evidence grants once; redirects/active objects cannot grant.
Actual invoice parent/InvoicePayment associations and subscription-item periods
are checked. A matching newer paid cycle resets pages once. Paid invoice delivery
before provider subscription propagation returns a recoverable error so retry can
grant later. Reads/debits enforce paid-through expiry without depending on webhook
arrival. Period-end cancellation preserves paid access until that end; terminal
deletion/unpaid expiry removes recurring access and preserves independent packs.
Old cycles, duplicate/stale events, active updates and paid recovery cannot revive
a terminal/reversed subscription or reset usage twice.

Valid foreign-app events on the shared account are acknowledged without ledger
or receipt mutations. Conflicting owned customer/mode/amount/currency/SKU evidence
fails closed. Full pack refunds revoke only that lot's remaining credits. FIFO
lots and cycles retain consumed history. Consumed/partial/disputed reversals use
an owner-reconciliation hold, never a negative balance or unrelated-credit debit.
Hold reasons escalate monotonically; late duplicate events cannot reopen an
owner-resolved hold or revive reversed access. Held conversions return a safe
409 with localized guidance in every format/locale and create no debit/retry row.

Subscription reversals atomically queue immediate provider cancellation, with
`invoice_now=false`, `prorate=false`, so refunds do not leave renewals running.
Provider I/O happens after local commit, outside SQLite locks/event loop. Durable
60-second leases and bounded backoff (5–300 seconds) coordinate workers; ASGI
startup and a 30-second loop retry without another customer request. Each pass
claims at most four actions; a webhook attempts one. Verify owned Customer,
subscription metadata and mode again before cancellation. An ambiguous response
recovers by retrieving resource state, not POST idempotency assumptions. Block
replacement purchases until cancellation is confirmed. An unused full-refund
cancellation hold clears on confirmation; consumed/partial/disputed holds need
trusted owner reconciliation. `payments.resolve_hold` never revives a purchase or
discards a pending cancellation. There is no public admin/recovery endpoint.

Hosted management derives the Customer from the stored capability binding;
caller-supplied Customer IDs are rejected. Return URLs use the canonical app
origin (localhost only in test). Management remains available to an owned Customer
after subscription expiry. Webhook provider I/O runs in the thread pool; health
runs directly on the event loop.

## Tracking and privacy

The single existing Umami destination remains
`0ee0e19b-b29b-4c98-b3f6-a92a43b4ba5a`. Only the five existing named funnel events
fan out: file-selected, convert-success, convert-error, upgrade-click,
checkout-opened. Only convert-success has balanced=yes/no/unknown and coarse
allowlisted layout. Automatic Umami history/click/performance collection is off.
Manual pageviews/events use fresh payloads with a fixed page URL/title and empty
referrer; arbitrary SDK/caller fields are discarded.

A blocking bootstrap captures payment returns, removes all query/hash/history
state, then drains the return into a private module cache before any tracker.
Polling uses POST bodies, as do account/portal requests. Missing bootstrap prevents
all SDK loading; conversion and private return recovery still work. The bootstrap
also checks original navigation-timing URLs and referrers. Cloudflare is suppressed
on sensitive entries because replaceState cannot erase those originals.

Public build configuration `VITE_GA_MEASUREMENT_ID` and
`VITE_CF_WEB_ANALYTICS_TOKEN` are unset by default. No guessed production IDs or
second Umami tag were added. Google requires explicit optional consent before
any Google request; a local choice is reversible and synchronized across tabs,
with all copy/controls in five locales. Manual sanitized pageviews and approved
funnel events only; Ads/Signals/User-ID features are off. Parent must disable
Enhanced Measurement in the actual Google data stream before setting its verified
ID. Google may create anonymous browser/session identifiers; app capability and
payment-session tokens are excluded.

Cloudflare loads one manual SDK with spa:false when a verified token is supplied
on a safe entry. Its normal lifecycle may send multiple timing/vitals packets.
No DNS/proxy/TLS changes were made. Owner QA uses nonsensitive localStorage
`stx_owner_qa=on` before navigation plus reload, suppressing every provider. Remove
the value and reload to resume normal tracking. QA receipts stay local.

The exact document-memory/deletion promise is unchanged in all locales. Retained
account/usage/customer/payment/idempotency metadata is accurately disclosed.
Document bytes, filenames, rows, descriptions, dates, balances and statement
amounts never enter analytics or billing metadata. Conversion fingerprints retain
the existing opportunistic 24-hour expiry; payment idempotency/history is durable.
No real/customer statement, runtime database, credential or generated workbook
is committed.

## Verification

| Check | Current result |
| --- | --- |
| Full backend | **449 passed**, 0 failures/skips (13 SDK/Starlette deprecation warnings) |
| Frontend | **196 passed**, 12 files, 0 failures/skips |
| Production build | TypeScript, SEO contract and Vite build passed |
| HTTP routing | **2 passed** (dev and production preview) |
| Synthetic corpus | **22 statements, 14 families, 372/372 exact rows** |
| Silent errors / false alarms | **0 / 0** |
| Browser e2e | **21 passed** in agent-owned Camoufox; **21 passed** in agent-owned Chromium; 5 focused Camoufox follow-up cases passed; 0 current failures/skips |
| Workbook calculation | 2 downloaded deposit/card workbooks independently calculated |
| Source checks | git diff --check; exact device paragraph once; icons/SEO unchanged |

All backend/provider fixtures are synthetic. Real Stripe signature verification
and SDK HTTP serialization execute locally against synthetic HTTP responses;
both provider modes and all six paid SKUs are exercised. Lifecycle tests cover
invoice-before-checkout, renewal/replay, cancellation now/period end,
failure/expiry/paid recovery, shared-account isolation, portal ownership,
refund/dispute/partial/consumed reversals, cancellation lost responses/startup,
monotonic holds, restarts/concurrency, preserved packs and legacy mode migration.
No actual hosted Stripe payment/checkout arrival is claimed.

The actual captured Umami and Cloudflare JavaScript SDKs execute in an
agent-owned Camoufox browser; all ingestion is intercepted. Umami fetch uses a
local HTTP transport shim to observe its real serialized body; an unmodified
external SDK fetch did not dispatch in this browser. Cloudflare's actual network
bodies include an explicit visibility-lifecycle flush after conversion,
followed by actual navigation and return-URL exclusion checks. Google uses an
explicitly mocked command-to-network serializer, not a genuine Google SDK/property.
Synthetic filename/row/account/statement amount/date/payment-query canaries are
absent from captured SDK/request bodies, URLs, headers and referrers. Consent,
revocation/reallow, owner QA, original sensitive referrers, bootstrap failure and
five-locale controls are tested. This proves local serialization behavior, not
provider ingestion or real-user acquisition.

Captured SDK SHA-256 (ignored work artifacts; CI downloads official public SDKs):

- Umami: 1ad1145d19d4558c20f5469ca4a5fc50a1a46f860858c9c91bfcd56fd29a522a
- Cloudflare: 637381256384554e1cc3309a62fb238a51b83e7f10b2a56d8ba15dbc73ca762e

Browser journeys replay actual upload → subprocess conversion → preview and all
three reconciliation states → XLSX/CSV/JSON downloads. They cover OCR/password/
multi-account errors, timeout/retry, two-page extraction, metered/unmetered modes,
private hosted-management requests/failure and localized payment holds. Viewports
1365x900 and 390x844 have no horizontal overflow; relevant console/network checks
pass (deliberate HTTP error paths are expected). Screenshots were inspected for
desktop balanced results and mobile highlighted/not-balanced results. These are
browser viewport checks, not an iPhone or simulator test.

Actual downloaded XLSX artifacts were reopened and every tested transaction/date/
signed amount/balance checked. The deposit Checks B7 formula calculates 110.00;
the card Checks B9 formula calculates 2716.55, matching printed synthetic closing
figures. `formulas` 1.3.4 independently evaluates the live workbook references and
changes status to not_balanced after an amount edit. openpyxl data_only caches are
blank: these are stored formulas plus independent calculation, **not an Excel
application recalculation claim**. XLSX/CSV/JSON and screenshots remain ignored
synthetic work artifacts, under work/playwright-results-20261016-delivery.

The 30-second parsing wall deadline, kill/reap, two-conversion admission, memory
limits, 20 MiB upload and 100-page cap are unchanged. The full suite verifies
health responsiveness, actual dead worker PIDs, cleanup, no temporary accepted
statement/output files, no failed-conversion debit and same-key retry correctness.
The corpus includes December/January, multiline/repeated headers, no activity,
overdraft, million-unit values and a 40-page statement; page-limit tests reject
101 pages before extraction. Real-bank accuracy remains unverified. Equation
balance does not certify every date/description or detect offsetting row errors.

### CI follow-through

The first GitHub Chromium run passed 19 cases and exposed two SDK test failures:
it did not deliver the old page's visibility beacon before navigation destroyed
that page/route. The test now explicitly exercises the actual SDK's visibility
handler while its HTTP transport is observable, retains the serialized canary
assertions, then separately navigates and checks sensitive-return exclusion.
No payload assertion was removed. The stronger blocked-bootstrap test also
found a real StrictMode fallback-return loss; a short-lived module-private cache
preserves initialization without keeping the token in a global or enabling SDKs.
Frontend now passes 196 tests, affected Camoufox cases pass 5/5, and the full
agent-owned Chromium suite passes 21/21. Backend and frontend GitHub jobs passed
on the initial head; updated remote CI is tracked on the PR rather than assumed
from fixtures. No provider ingestion/payment claim follows from these checks.

### Per-family synthetic corpus

| Family (synthetic inspired layout) | Statements | Balance rate | Expected | Extracted | Exact ordered rows | Accuracy | Missing | Extra | Silent errors | False alarms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Chase | 2 | 100.0% | 24 | 24 | 24 | 100.0% | 0 | 0 | 0 | 0 |
| Bank of America | 1 | 100.0% | 12 | 12 | 12 | 100.0% | 0 | 0 | 0 | 0 |
| Wells Fargo | 2 | 100.0% | 24 | 24 | 24 | 100.0% | 0 | 0 | 0 | 0 |
| Citi | 2 | 100.0% | 24 | 24 | 24 | 100.0% | 0 | 0 | 0 | 0 |
| U.S. Bank | 1 | 100.0% | 12 | 12 | 12 | 100.0% | 0 | 0 | 0 | 0 |
| PNC | 1 | 100.0% | 12 | 12 | 12 | 100.0% | 0 | 0 | 0 | 0 |
| Capital One | 1 | 100.0% | 12 | 12 | 12 | 100.0% | 0 | 0 | 0 | 0 |
| Truist | 1 | 100.0% | 12 | 12 | 12 | 100.0% | 0 | 0 | 0 | 0 |
| TD Bank | 1 | 100.0% | 12 | 12 | 12 | 100.0% | 0 | 0 | 0 | 0 |
| BMO | 1 | 100.0% | 12 | 12 | 12 | 100.0% | 0 | 0 | 0 | 0 |
| Chase credit card | 3 | 100.0% | 24 | 24 | 24 | 100.0% | 0 | 0 | 0 | 0 |
| Citi credit card | 2 | 100.0% | 16 | 16 | 16 | 100.0% | 0 | 0 | 0 | 0 |
| Capital One credit card | 2 | 100.0% | 168 | 168 | 168 | 100.0% | 0 | 0 | 0 | 0 |
| American Express credit card | 2 | 100.0% | 8 | 8 | 8 | 100.0% | 0 | 0 | 0 | 0 |

22 statements / 14 families / 372 expected and exact ordered rows.
Silent errors: **0**. False alarms: **0**. Missing/extra rows: **0/0**.
All ten existing layouts remain at 100%; this is synthetic regression coverage.

## Parent configuration and operations (not performed here)

1. Keep a durable database outside the web root, shared only by this app's ASGI
   workers on one host. Use separate test/live paths and keep ASGI lifespan
   enabled (Uvicorn auto/on) so cancellation retry starts automatically. Install
   the pinned dependencies. Parent supplies matching Stripe mode/key/webhook
   secrets from its existing secret store, never source or command output.
2. Configure this app's snapshot webhook endpoint at `/api/stripe/webhook` with
   API version **2026-02-25.clover**, matching stripe-python **14.4.1**. Subscribe
   to exactly the following app-relevant event types (shared-account foreign
   events are inert):

   - checkout.session.completed
   - checkout.session.async_payment_succeeded
   - checkout.session.async_payment_failed
   - checkout.session.expired
   - invoice.paid
   - invoice.payment_failed
   - customer.subscription.updated
   - customer.subscription.deleted
   - charge.refunded
   - charge.dispute.created
   - charge.dispute.updated
   - charge.dispute.closed

   Subscription service periods come from items.data; invoice subscription
   references/metadata come from parent.subscription_details. InvoicePayments
   establish PaymentIntent associations; removed invoice.payment_intent/charge
   and legacy root subscription period fields are not assumed.
3. Create/verify a dedicated hosted portal configuration **in each mode**:
   payment_method_update enabled, subscription_cancel enabled with
   mode=at_period_end, subscription_update disabled. Supply its public bpc_ ID as
   STX_STRIPE_PORTAL_CONFIGURATION. Do not add annual plans, coupons or new prices.
   STX_CHECKOUT_ORIGIN is the canonical HTTPS app origin. All plans are available
   as initial subscriptions. Cancellation after reversal uses verified immediate
   cancellation with no proration/new invoice, independent of portal settings.
4. Monitor counts of pending stx_actions and unresolved stx_holds without
   exporting purchase/customer/account IDs. Provider failure keeps durable retry
   and holds; if cancellation remains unconfirmed near renewal, parent must
   reconcile in Stripe. Never delete actions or release holds to force a retry.
   Owner resolves a consumed/ambiguous hold only after financial reconciliation;
   no public automated account recovery or cross-device login is provided.
5. Supply only verified public VITE_GA_MEASUREMENT_ID and
   VITE_CF_WEB_ANALYTICS_TOKEN at frontend build time. First disable all Google
   Enhanced Measurement (history/page changes, forms, search, downloads and
   other automatic collection) and Ads/Signals/User-ID features in the actual
   property/stream. Keep the single existing Umami destination. Avoid automatic
   Cloudflare tag injection in addition to this manual beacon; no DNS/proxy/TLS
   changes are required. Verify genuine provider arrival separately after parent
   deployment; no synthetic acquisition traffic is sent here.
6. Suppress/redact this app's secret-bearing nginx/uvicorn/access/error/APM URLs
   before payment traffic. Prefer no access logs for this app's ASGI service
   (`--no-access-log`) and an app-specific nginx log format containing only method,
   a coarse route enum and status. Never log $request, $request_uri, $args,
   referrers, request/response bodies or arbitrary path segments. Plain $uri is
   insufficient for legacy capability-bearing GET routes. Payment-return GETs
   reach nginx before client cleanup; sanitize/suppress error logs too. Do not
   alter other apps' auth/logging. Verify with nonsensitive synthetic canaries
   without printing secret-bearing URLs/IDs; this repository does not prove the
   production proxy/service logging settings are installed.
7. Parent performs real hosted TEST payments and unpaid LIVE checkout inspection,
   webhook/portal/configuration checks and genuine analytics arrival. No live
   purchase, refund, deploy, account setting or secret transfer was performed in
   this environment.

### Migration and rollback

Initialization adds mode/customer/subscription/payment/cycle/lot/hold/action
metadata and checkout reference columns; existing metering/purchase history is
preserved. A live database cannot import nonempty unbound legacy/test account or
purchase state. Legacy test purchases lack owned references and need owner
reconciliation rather than attribution from account_id metadata. Back up metadata
before rollout; preserve durable idempotency, consumed history and pending
cancellations across releases. Do not delete/recreate the ledger or copy test
allowances into live mode. Roll back only to a build compatible with the mode/
metadata; the old test-only binary cannot serve live configuration. Removing
credentials restores the explicitly documented unmetered behavior, so parent
must treat that as a billing-mode decision, not silently use it as rollback.

### Limits and skipped/blocked external checks

No actual Stripe credentials, hosted TEST payment, unpaid LIVE checkout,
production webhook/portal setting, GA/CF verified identities or real provider
arrival was available/performed here. Google SDK delivery and Enhanced Measurement
settings require parent's actual stream; mocked serialization is not proof of
those external settings. CF intentionally excludes sensitive entry contexts.
Other site's tracking/configuration and genuine human acquisition were not
performed: this task is scoped to this repository and forbids unrelated projects,
outreach, ads and deployment. No fabricated acquisition or ingestion is claimed.

The Linux cloud host has no xcrun/device/simulator access. Host capacity was
measured (~18 GiB RAM, ~17 GiB available, low load before browser work), using one
browser worker. N759MS's availability on a separate physical host cannot be
established here. **No physical iPhone, iOS simulator or Android emulator test
occurred.** Real-bank statements were neither requested nor used. Password-locked,
image/mixed-scanned and multiple-account inputs retain their existing safe
rejections; OCR/account splitting is outside this change. Unsupported tax,
proration, multi-payment/partial-settlement invoices or conflicting financial
catalog evidence fail closed for owner reconciliation; no new pricing features
were introduced. Remote CI results/independent review belong to the PR/parent;
local suite results above are the evidence recorded here.

### Official contracts inspected

- [Stripe SDK pinned version](https://github.com/stripe/stripe-python/blob/v14.4.1/stripe/_api_version.py)
- [Subscription item periods](https://docs.stripe.com/changelog/basil/2025-03-31/deprecate-subscription-current-period-start-and-end)
- [Invoice](https://docs.stripe.com/api/invoices/object), [line item](https://docs.stripe.com/api/invoice-line-item/object), [InvoicePayment](https://docs.stripe.com/api/invoice-payment/object)
- [Metadata copying](https://docs.stripe.com/metadata#copy-metadata-to-another-object), [webhook ordering](https://docs.stripe.com/webhooks#event-ordering), [idempotency](https://docs.stripe.com/api/idempotent_requests)
- [Charges](https://docs.stripe.com/api/charges/object), [disputes](https://docs.stripe.com/api/disputes/object), [subscription cancellation](https://docs.stripe.com/api/subscriptions/cancel)
- [Hosted portal](https://docs.stripe.com/customer-management/configure-portal), [portal sessions](https://docs.stripe.com/api/customer_portal/sessions/create)
- [Umami configuration](https://docs.umami.is/docs/tracker-configuration), [functions](https://docs.umami.is/docs/tracker-functions)
- [Google consent](https://developers.google.com/tag-platform/security/guides/consent), [privacy](https://developers.google.com/tag-platform/security/guides/privacy), [manual pageviews](https://developers.google.com/analytics/devguides/collection/ga4/views#disable_page_changes_based_on_browser_history_events)
- [Cloudflare manual beacon](https://developers.cloudflare.com/speed/observatory/rum-beacon/), [SPA behavior](https://developers.cloudflare.com/web-analytics/get-started/web-analytics-spa/)

## Every changed file

- `.env.example`
- `.github/workflows/ci.yml`
- `AGENTS.md`
- `README.md`
- `backend/pyproject.toml`
- `backend/statement_to_excel/api.py`
- `backend/statement_to_excel/billing.py`
- `backend/statement_to_excel/payments.py`
- `backend/tests/conftest.py`
- `backend/tests/test_api.py`
- `backend/tests/test_billing.py`
- `backend/tests/test_billing_regression.py`
- `backend/tests/test_billing_stripe.py`
- `backend/tests/test_checkout_availability.py`
- `backend/tests/test_upload_limits.py`
- `docs/codex-live-billing-2026-10-16.md`
- `frontend/deploy/nginx.conf.example`
- `frontend/e2e/analytics.spec.ts`
- `frontend/e2e/conversion.spec.ts`
- `frontend/e2e/servers.mjs`
- `frontend/e2e/start-stack.mjs`
- `frontend/index.html`
- `frontend/playwright.config.ts`
- `frontend/public/privacy-bootstrap.js`
- `frontend/src/App.test.tsx`
- `frontend/src/App.tsx`
- `frontend/src/components/Converter.test.tsx`
- `frontend/src/components/Converter.tsx`
- `frontend/src/components/Pricing.tsx`
- `frontend/src/components/PrivacyControls.tsx`
- `frontend/src/i18n/locales/en.ts`
- `frontend/src/i18n/locales/es.ts`
- `frontend/src/i18n/locales/it.ts`
- `frontend/src/i18n/locales/ja.ts`
- `frontend/src/i18n/locales/zh.ts`
- `frontend/src/i18n/types.ts`
- `frontend/src/lib/analytics-providers.test.ts`
- `frontend/src/lib/analytics.ts`
- `frontend/src/lib/api.test.ts`
- `frontend/src/lib/api.ts`
- `frontend/src/lib/privacy.test.ts`
- `frontend/src/lib/privacy.ts`
- `frontend/src/main.tsx`
- `frontend/src/styles.css`
