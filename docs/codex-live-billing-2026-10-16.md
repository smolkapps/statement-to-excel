# Live billing and analytics — October 16, 2026

Repository: smolkapps/statement-to-excel. Branch:
`codex/live-billing-analytics-20261016`. Refreshed base:
`575d0e4c15f24cf6ce87e6496c7c3be19ead986a` (merged PR #7).
Correction B continues reviewed delivery b23cfc04996ab83acbeb4079df30c7149231f460.
Refreshed parent commit 8b9dbda64904db0eb4427dc3dfeb09c559a552a4 was fast-forwarded
and preserved (Studio Linux runners and WORKLOG). Verified corrective code head:
8e0519fd9e120deb7b217c911cad13b86f0a6395.
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

## PR8 correction B — paid service, checkout and privacy

An old-only invoice refund now reverses that payment/cycle and stops renewal
without deleting another known paid current invoice. A durable
`retained_invoice_id` keeps its paid-through and existing usage after provider
cancellation/deletion and restart. Starter A unused / B used 3 retains B's 117
pages; unused B retains 120. Reversing B or reaching its paid end removes that
service. Separate packs and consumed history remain intact. Genuine consumed,
partial or disputed reversal holds remain unresolved after cancellation and keep
usage for owner reconciliation; an unused old-only refund does not invent such
a hold merely because cancellation is pending.

New allowance still requires a signed paid webhook. A delayed paid B can recover
once only when the full owned paid invoice/PI/charge evidence proves its current
period was paid before the stored renewal stop and provider termination. Use
Invoice.status_transitions.paid_at, the signed refund event's created timestamp,
Dispute.created (not a later update/closed event timestamp), and Subscription.ended_at
(not scheduling-time canceled_at). Missing/equal-second/conflicting evidence
creates durable `paid_cycle_after_renewal_stop` reconciliation instead of silently
acknowledging lost service or granting a future cycle. No refund, return, active
object, outbox cancellation or read grants new pages. An unrelated prior terminal
cancellation cannot acquire retained service. Duplicate deliveries do not reset
usage or reopen an owner-resolved hold.

Changing SKU after cancel/back now retrieves the recorded old app/account/mode/
purchase/customer-owned Session. Only open+unpaid with no PaymentIntent or
Subscription may be expired, using its own deterministic key; retrieval must
confirm expired+unpaid before replacing the reservation. Same-SKU resumes.
Completed/processing/foreign/conflicting or ID-unknown creation remains protected.
Lost expiry responses retrieve the same Session after restart; original purchase
rows, request keys and aliases remain. Active or retained paid plans still block
another initial subscription. A cancel query is never financial evidence.

The retained browser capability can now be persisted/read back on an explicit
payment-button retry after an initial storage-save failure, only when no different
stored account exists. Free conversion remains usable without storage.

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
also checks original navigation-timing URLs and referrers. Both optional SDKs are suppressed
on sensitive entries because replaceState cannot erase those originals.

Tracked, public-only `frontend/.env.production` contains empty
`VITE_GA_MEASUREMENT_ID=` and `VITE_CF_WEB_ANALYTICS_TOKEN=`. Parent supplies
verified public values there; fresh nested frontend builds need no forwarding.
No secrets or guessed production identities are included. Optional Google AND
Cloudflare default OFF behind a new versioned joint choice naming both services
in all five locales. Legacy `stx_google_consent=yes` does not authorize either.
Allow/deny require write/readback. Withdrawal stops the SDKs before persistence,
removes stale acceptance when possible, and reports unsaved denial honestly if
both write/removal fail. A same-tab session denial is an additional fallback;
allowing again also requires clearing/readback of that marker. Cross-tab
revocation and storage.clear() stop collection. No automatic reload loses results
or re-enables stale acceptance. Retired SDKs reallow on the next visit via an
explicit reload control.

Google's five approved names use underscores; historical Umami names stay
hyphenated. Only convert_success has the same balanced/layout enums. No new
funnel event, property, destination or analytics backend/proxy was added. Actual
Google diagnostics were observed bypassing ga-disable during pending startup.
Google now executes official unmodified bytes inside a small disposable
same-origin frame with a clean static URL/no referrer, receiving only sanitized
commands. Before removal, its stop control blocks SDK exit handlers; removal
terminates pending loads and diagnostic timers. This is lifecycle isolation,
not a security boundary against a trusted same-origin SDK. Direct helper visits
are inert. Parent/current-frame/consent checks guard initialization. Cookies use
host-only cookie_domain:none, prefix stx, path / and Secure on HTTPS. Withdrawal
deletes only this host's stx_ga and current-stream cookie; parent/sibling and
other-property sentinels survive. Ads/Signals/User-ID remain off. Parent must
disable all Enhanced Measurement in the actual Google stream before providing ID.

Cloudflare's 2026.10.1 SDK is SRI-pinned; changed bytes fail optional loading closed
until re-audited. Its consent-controlled global accessor rejects late initialization
and stops lifecycle sends after withdrawal. Listeners remain retired for this
document so reallow cannot revive old observers. The beacon uses spa:false; one
load can send several legitimate lifecycle packets. No DNS/proxy/TLS setting was
changed. Both optional SDKs exclude lifetime-sensitive original URL/referrer/path
contexts, including sanitized payment returns. Owner QA uses localStorage
stx_owner_qa=on before reload and suppresses all providers. QA receipts stay local.

The exact document-memory/deletion promise is unchanged in all locales. Retained
account/usage/customer/payment/idempotency metadata is accurately disclosed.
Document bytes, filenames, rows, descriptions, dates, balances and statement
amounts never enter analytics or billing metadata. Conversion fingerprints retain
the existing opportunistic 24-hour expiry; payment idempotency/history is durable.
No real/customer statement, runtime database, credential or generated workbook
is committed.

## Verification

Final local verification finished October 17 UTC (October 16 in the owner
timezone); the requested October 16 report path is retained.

| Check | Current result |
| --- | --- |
| Full backend | **479 passed**, 0 failures/skips (13 SDK/Starlette deprecation warnings) |
| Frontend | **208 passed**, 12 files, 0 failures/skips |
| Production build | TypeScript, SEO contract and Vite build passed |
| HTTP routing | **2 passed** (dev and production preview) |
| Synthetic corpus | **22 statements, 14 families, 372/372 exact rows** |
| Silent errors / false alarms | **0 / 0** |
| Browser e2e | **29 passed** in agent-owned Chromium and **29 passed** in agent-owned Camoufox; 0 final failures/skips |
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

Actual current official Umami, Cloudflare and Google SDK bytes execute with
all provider collection intercepted. Google's script was obtained from the
official gtag endpoint with the explicitly synthetic G-SYNTHETIC1 fixture ID;
this is actual SDK serialization, not a valid-property/ingestion claim. Umami's
serialized bodies use the existing local HTTP fixture transport because native
external SDK fetch did not dispatch in Camoufox. Camoufox likewise suppresses
native Google keepalive collection, so its fixture redirects the actual SDK's
serialized fetch/beacon payload to local HTTP; no Google command serializer is
mocked. Chromium uses native intercepted Google transport. CF packets and sampled
Google /a diagnostics are captured at the browser network boundary. Math.random
is forced to zero only in the test fixture to exercise sampled diagnostics.

Actual SDK tests prove all five Google mappings, no optional load before consent,
saved denial/reload, legacy-consent isolation, pending script withdrawal, loaded
500ms diagnostic-timer disposal, cross-tab clear, owner QA, bootstrap failure and
all-five-locale choices. Withdrawal timing is measured from BEFORE disposal,
including exit; the older b23 explicit visibility flush plus subsequent real
navigation and payload canaries remain. Filename/row/account/amount/date/payment
query/hash and search-input canaries are absent from serialized SDK bodies, URLs,
headers and referrers; the account canary is required nonempty. The cookie test
uses a synthetic HTTPS app subdomain served only from the loopback app, with
parent-domain/other-property sentinels and actual SDK cookies. The initial Camoufox native-transport event case failed; the HTTPS parent-cookie
fixture plus local serialized keepalive receipt resolved it, preserving all five
actual-SDK name/cookie assertions. Both final browser suites pass all 29 cases.
Fixture traffic
is not provider acceptance, genuine acquisition or hosted financial testing.

Captured SDK SHA-256 (ignored work artifacts; CI downloads official public SDKs):

- Umami: 1ad1145d19d4558c20f5469ca4a5fc50a1a46f860858c9c91bfcd56fd29a522a
- Cloudflare: 637381256384554e1cc3309a62fb238a51b83e7f10b2a56d8ba15dbc73ca762e
- Google: 8f1ca70f4564094099261eb0d201003a4a1c7b988be9c8a05035b4c81282aa47

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
synthetic work artifacts, under work/playwright-20261016-B-chromium-final and
work/playwright-20261016-B-camoufox-final.
Independent calculation: work/download-formula-results-20261016-B.json.

The 30-second parsing wall deadline, kill/reap, two-conversion admission, memory
limits, 20 MiB upload and 100-page cap are unchanged. The full suite verifies
health responsiveness, actual dead worker PIDs, cleanup, no temporary accepted
statement/output files, no failed-conversion debit and same-key retry correctness.
The corpus includes December/January, multiline/repeated headers, no activity,
overdraft, million-unit values and a 40-page statement; page-limit tests reject
101 pages before extraction. Real-bank accuracy remains unverified. Equation
balance does not certify every date/description or detect offsetting row errors.

### CI and production-build durability

Parent confirmed reviewed b23's actual-head CI green; its earlier Chromium
visibility failure was already resolved. The StrictMode fallback-return capture
and lifecycle/canary assertions remain intact. Parent's 8b9 Studio Linux runner
configuration is preserved. Push now filters to main; pull_request remains, so
branch updates run one required Linux pipeline rather than duplicate push/PR
pipelines. No spending/account settings, shared poller or CI framework changed.

Fresh detached tracked clone of 8e0519fd9e120deb7b217c911cad13b86f0a6395
verified frontend/.env.production is tracked. npm ci used an in-workspace cache
(the cloud default home cache was unavailable). With both VITE variables explicitly
unset, nested frontend production build succeeded and contained no synthetic
identity. Replacing only the clone's file with temporary public fixture identities
then rebuilding without forwarding put both values into its production bundle.
The real repository's tracked file remains empty. Two fresh-clone builds passed;
no configured bundle was published and no provider request was made by this check.

Final local checks precede one consolidated branch push. Final-head Linux CI
status is recorded on PR8, not inferred from fixtures. Parent owns independent
review and genuine provider verification.

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
   VITE_CF_WEB_ANALYTICS_TOKEN in tracked frontend/.env.production (public only). First disable all Google
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
purchase state. Correction B adds only retained_invoice_id and renewal_stop_at
columns to stx_subscriptions; it does not rewrite balances or historical decisions.
Already-processed broken reversals from an earlier binary require owner review;
do not guess an automatic historical restoration. Legacy test purchases lack owned references and need owner
reconciliation rather than attribution from account_id metadata. Back up metadata
before rollout; preserve durable idempotency, consumed history and pending
cancellations across releases. Do not delete/recreate the ledger or copy test
allowances into live mode. Roll back only to a build compatible with the mode/
metadata and retained-paid-service behavior; an older build that ignores retained
invoice service is not a safe financial rollback. The old test-only binary also
cannot serve live configuration. Removing
credentials restores the explicitly documented unmetered behavior, so parent
must treat that as a billing-mode decision, not silently use it as rollback.

### Limits and skipped/blocked external checks

No actual Stripe credentials, hosted TEST payment, unpaid LIVE checkout,
production webhook/portal setting, GA/CF verified identities or real provider
arrival was available/performed here. Google property settings/acceptance and Enhanced Measurement
require parent's actual stream; the real SDK fixture audit does not prove those
external settings. Production CSP, if configured, must permit the same-origin
frame/helper and the explicitly opted-in Google script/connect destinations; no
CSP/production setting was changed here. Both optional SDKs intentionally exclude sensitive entry contexts. CF SRI updates
require another source/payload/withdrawal audit before changing the pin.
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
- [Google valid event names](https://support.google.com/analytics/answer/13316687), [cookie scope](https://developers.google.com/analytics/devguides/collection/ga4/reference/config#cookie_domain), [cookie prefix](https://developers.google.com/tag-platform/security/guides/customize-cookies#rename_cookies)
- [Checkout expiry](https://docs.stripe.com/api/checkout/sessions/expire), [invoice object](https://docs.stripe.com/api/invoices/object), [dispute object](https://docs.stripe.com/api/disputes/object)
- [Cloudflare manual beacon](https://developers.cloudflare.com/speed/observatory/rum-beacon/), [SPA behavior](https://developers.cloudflare.com/web-analytics/get-started/web-analytics-spa/)

## Every changed file

50 files relative to refreshed main:

- `.env.example`
- `.github/workflows/ci.yml`
- `.gitignore`
- `AGENTS.md`
- `README.md`
- `WORKLOG.md`
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
- `backend/tests/test_payment_recovery.py`
- `backend/tests/test_upload_limits.py`
- `docs/codex-live-billing-2026-10-16.md`
- `frontend/.env.production`
- `frontend/deploy/nginx.conf.example`
- `frontend/e2e/analytics.spec.ts`
- `frontend/e2e/conversion.spec.ts`
- `frontend/e2e/servers.mjs`
- `frontend/e2e/start-stack.mjs`
- `frontend/index.html`
- `frontend/playwright.config.ts`
- `frontend/public/google-frame.html`
- `frontend/public/google-frame.js`
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
