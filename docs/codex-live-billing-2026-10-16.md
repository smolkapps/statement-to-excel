# Live billing and analytics — October 16, 2026

Repository: smolkapps/statement-to-excel. Branch:
`codex/live-billing-analytics-20261016`. Refreshed base:
`575d0e4c15f24cf6ce87e6496c7c3be19ead986a` (merged PR #7).
Correction B continues reviewed delivery b23cfc04996ab83acbeb4079df30c7149231f460.
Refreshed parent commit 8b9dbda64904db0eb4427dc3dfeb09c559a552a4 was fast-forwarded
and preserved (Studio Linux runners and WORKLOG). Initial corrective code:
8e0519fd9e120deb7b217c911cad13b86f0a6395. B verified implementation head:
11a6d5981946c6315cde7ac286f2d33209d6f279 (owned unpaid PI recovery).
The PR records the exact current delivery head including correction D.
PRs #5/#6/#7 and their branches/reports are preserved. No other open PR owned this work at the initial or final remote
check. Nothing was pushed to main, merged or deployed.

## PR8 correction D — independent webhook delivery pin

Preserved starting head: `60bcceb74a0588750a4d97fb0d95e02e85d53d27`.
Verified D implementation: `6d4ea66144faf9c19a830d9ca84e6698c8b8b526`; the PR records the final
documentation delivery head.
Verification date: October 16 America/New_York / October 17 UTC. Parent reports
Stripe's LIVE endpoint creation hit its three-unique-version cap, with no Statement
LIVE endpoint/secret/live.env created; production remains 575d0e4/unmetered. This
source-only correction does not change another endpoint or the account default.

| Boundary | Exact contract |
| --- | --- |
| Installed stripe-python | **14.4.1**, unchanged |
| Outgoing HTTP / `API_VERSION` | **2026-02-25.clover**, unchanged |
| Incoming signed snapshot / `WEBHOOK_API_VERSION` | **2026-08-26.dahlia** only |

Both verify_event and the direct handler reject Clover, earlier Dahlia, missing,
malformed or any other delivery version before financial mutation. Existing
signature/mode/ownership/amount guards and the exact twelve events below remain.
No runtime override, prefix matching, accept-both fallback, SDK upgrade, thin-event
migration or financial/data migration is introduced. Parent configures only
Statement's endpoint to this exact delivery version after genuine target-version
TEST verification; shared endpoints/defaults/keys/security stay untouched.

### D compatibility review and required fields

Official [API versioning](https://docs.stripe.com/api/versioning) and
[webhook versioning](https://docs.stripe.com/webhooks/versioning) distinguish an
endpoint's snapshot version from the HTTP Stripe-Version override. Monthly Dahlia
releases are documented additive; Clover to Dahlia crosses a major boundary and
is not assumed compatible. The [Dahlia changelog](https://docs.stripe.com/changelog/dahlia)
was inspected, including its March major/August 26 overview. The
[decimal quantity change](https://docs.stripe.com/changelog/dahlia/2026-03-25/invoice-items-decimal-quantity)
adds quantity_decimal but explicitly retains deprecated integer quantity. This
app continues its existing quantity 1/catalog checks and does not add decimal billing.

Installed SDK 14.4.1 Webhook.construct_event verifies HMAC/time, JSON-decodes and
constructs a generic Event without enforcing its generated HTTP version on the
envelope. StripeObject refresh iterates incoming keys; to_dict_recursive preserves
nested dictionaries/lists and unknown fields. Tests use actual event/resource/list/
line-item object tags and assert exact signed JSON-to-dictionary round trips.
The existing deprecation warnings remain; no replacement deserializer is needed.

| Path consumed by existing handlers | D review / synthetic coverage |
| --- | --- |
| Envelope id/type/created/livemode/api_version | Real signature verification; strict version/mode rejection, real clock; expired-signature negative case |
| Checkout customer/metadata, mode/currency/amount_total/payment_status, payment_intent/subscription/invoice | Owned durable references, paid grant once, terminal/no-payment events, duplicate replay |
| Invoice parent.subscription_details.subscription/metadata and lines.data[].parent.subscription_item_details | Real SDK nested conversion, subscription/item/proration/period/quantity/amount validation; invoice-before-checkout and renewal |
| Invoice status/amount_due/amount_paid/currency/status_transitions.paid_at | Existing paid evidence and out-of-order ordering checks preserved; retrieved InvoicePayments/PI/Charge remain Clover HTTP |
| Subscription items.data[].current_period_start/end, quantity, price.unit_amount/currency/recurring; status/cancel_at_period_end/ended_at | Signed deleted snapshots exercise Dahlia dictionary path; updated/current subscriptions are retrieved through Clover |
| Charge: customer/metadata/payment_intent/currency/amount/amount_refunded/disputed; Dispute: charge/payment_intent/currency/amount/created | Signed refund/dispute types, non-revival/replay and retained newer paid service; current resource evidence retrieved through Clover |

No concrete incompatible required-field change or SDK field loss was found in
this source/docs/synthetic review. Missing/conflicting required evidence keeps
existing fail-closed/reconciliation behavior. These are synthetic objects, not
private target-version payloads or genuine delivery proof. Parent compares actual
required fields and proves signed 2026-08-26.dahlia on the intended runtime before
LIVE. Immutable Event API snapshots rendered 2026-04-22.dahlia remain distinct from
prior signed Clover delivery and are not relabelled as target-version evidence.

### D verification and identity

- Focused version/HTTP suite: **60 passed**.
- Full backend: **579 passed**, 119 SDK/Starlette deprecation warnings; 0 failures/skips.
- Synthetic corpus: **22 statements / 14 families / 372 exact ordered rows**, 100% per family; 0 missing/extra,0 silent errors,0 false alarms (table below).
- All twelve signed event types in both modes use real SDK conversion; rejection snapshots prove no ledger/provider-call mutation. Renewal, old-invoice-only refund, restart and delayed/duplicate deliveries preserve 117 owed Starter pages and separate 200-credit pack in the fixture.
- Actual StripeClient construction/HTTP serialization still sends 2026-02-25.clover with SDK 14.4.1; transport is synthetic and no provider API is contacted.

**125 protected tracked files are byte-identical** to 60bcceb, including every
frontend/public SDK/bootstrap/config/catalog/dependency/CI input. Combined SHA-256:
`362fa6a376a95e2719bdeda7d3e2ccdf128f6c439f77ddb156da5f34c08e095e`.
Normalizing only the new delivery constant, the two incoming comparisons and the
module docstring makes payments.py byte-identical to 60bcceb: all financial
functions/HTTP client/outbox/retention/deadline/parser/exporter behavior remains.
The exact N759MS/device/capacity paragraph remains once unchanged; root AGENTS
changes only version guidance. .env.example corrects one operator comment only,
with all assignments unchanged. GA/CF public slots stay empty/off.

D changes only these eight paths (plus no generated artifacts): .env.example,
AGENTS.md, README.md, WORKLOG.md, backend/statement_to_excel/payments.py,
backend/tests/test_billing_stripe.py, backend/tests/test_webhook_versions.py, and
this runbook. Complete cumulative file list is below. No current-head/parent-owned
CI was canceled; no runner/routing/settings changes. Parent owns one final exact-head
CI check; queued jobs are not reported as passes, and idle CI polling stops at delivery.

Frontend 215/build/routing 2/Chromium 31 and Camoufox 30 passed/1 unchanged SDK-capture
failure plus focused 1 pass are **old 60b unchanged-input evidence**, not rerun or
claimed universal for D. The earlier backend 521 baseline is superseded by the
new 579 synthetic/backend run, without changing the provenance of prior provider tests.
No new physical-device/simulator, real-bank, genuine provider or LIVE test occurred.

Parent reports the older genuine TEST matrix at 2d/60b covers all six offers, hosted
pack/monthly, XLSX/CSV/JSON, paid renewal, old-only refund preserving newer owed
service, restart/expiry, failure/recovery, period-end terminal behavior, unused/
consumed refunds, genuine dispute/closure, and a **separately labelled local
duplicate replay**. That evidence remains earlier Clover delivery and is not Dahlia delivery
proof. Genuine target-version TEST and LIVE-unpaid proofs remain pending parent;
no real self-charge or cloud provider operation is authorized/performed.

## PR8 correction C — truthful Free allowance and notices

Starting preserved head: `2d514169e4ae73533981f26abdcebe13fbfa0100`.
C implementation: `49e093baad08106b07dfb459d0c958238afee836`; the PR records
the exact delivery head including this report update.
The October 17 UTC / October 16 owner-timezone follow-up is frontend-only:
Free displays the catalog's 3 total pages per saved browser account and explicitly
says there is no automatic replenishment. Free has no monthly price suffix. The
plan-group heading includes Free; the account label is generic. Applied the exact
approved copy in English, Spanish, Italian, Japanese and Chinese. Paid monthly
prices/allowances, all pack terms, extra-page credit debit, browser recovery
disclosure and unconfigured/unmetered behavior remain unchanged. No reset feature
or storage-clearing workaround is introduced.

PrivacyControls refreshes obsolete save-error/next-visit notices with the changed
choice. Cross-tab revoke/clear removes a stale acceptance/reload notice; a later
successful choice removes the old persistence error. The exact current local
choice notices remain. All stop-before-persist/SDK-withdrawal logic stays in the
unchanged analytics module; no consent architecture, payload/cookie/frame/SDK
change is included.

Raw Git blob checks prove **118 protected tracked files byte-identical** to 2d514169:
all backend source/tests, pricing.json, analytics/privacy libraries, all public
SDK/frame/bootstrap files, public provider/build/dependency/CI configuration, and
root AGENTS including the exact once-present device/capacity policy. Combined
SHA-256: `7c51aeb870a6cb6bf323aa784726bce64a4f25ab0b1dfbe9c98cad3011d09fb7`.
The only C paths are the 12 frontend source/test files listed below plus this
report and WORKLOG.md.

C validation: focused **11 passed**; full frontend **215 passed in 13 files**;
SEO/TypeScript/Vite production build and **2 routing checks passed**. Initial
new test-query typing and a Playwright JSON import-attribute collection error
were corrected before final verification; neither changed product behavior or
configuration. Agent-owned Chromium: **31 passed, 0 failed/skipped**. Agent-owned
Camoufox full run: **30 passed, 1 failed, 0 skipped**; the unchanged Google SDK
mapping/cookie test did not capture checkout_opened within its bound (and teardown
reached its timeout). One focused rerun of that same case **passed** with no source
change. Preserve the full-run failure as intermittent capture evidence; do not
claim a completely green Camoufox full run for C. Its test body/transport fixture,
analytics module and SDK bytes match 2d514169. All new C cases passed in both
browsers. No SDK repair or weakened assertion was introduced for this result.

Both viewport cases check Free versus all three paid cards and the account label
in all five locales, with ten locale/viewport screenshots per browser. Desktop
1365x900 and narrow 390x844 English captures were visually inspected at original
resolution; text wraps and no horizontal overflow is observed/asserted. Existing
console/network journeys show no page exceptions/failed local requests; expected
unsupported-input HTTP 422 is retained. SDK transport remains intercepted using
synthetic fixtures, not genuine provider acceptance. Screenshots, raw browser
reports and byte-identity proof remain ignored under work/. No physical device,
iOS simulator or Android emulator was available/used on this Linux host.

No current final-head CI run was canceled. No CI/runner/account setting changed;
parent-owned 8b runs/settings remain preserved. Parent may perform one final
exact-head run after the final push; subsequent status is reported once in PR8
without idle polling or inferring CI success from local tests.
Backend **521**, the **22/14/372** synthetic corpus with zero silent errors/false
alarms, and workbook/financial evidence below belong to the unchanged B code;
unchanged financial suites or genuine transactions were not repeated for C.
Parent reports an independently verified original-Clover-signed TEST pack purchase
with one 50-credit grant at 2d514169. That is parent evidence, not a cloud purchase
or proof of other genuine lifecycle scenarios. Parent retains source acceptance,
genuine financial/analytics setup, final exact-head CI and live cutover. No merge,
deployment, provider/credential operation or runner setting change occurred here.

C changed paths:

- `WORKLOG.md`
- `docs/codex-live-billing-2026-10-16.md`
- `frontend/e2e/analytics.spec.ts`
- `frontend/e2e/conversion.spec.ts`
- `frontend/src/components/Pricing.tsx`
- `frontend/src/components/Pricing.test.tsx`
- `frontend/src/components/PrivacyControls.tsx`
- `frontend/src/components/PrivacyControls.test.tsx`
- `frontend/src/i18n/types.ts`
- `frontend/src/i18n/locales/en.ts`
- `frontend/src/i18n/locales/es.ts`
- `frontend/src/i18n/locales/it.ts`
- `frontend/src/i18n/locales/ja.ts`
- `frontend/src/i18n/locales/zh.ts`

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
purchase/customer-owned Session. Only open+unpaid without an already-created
Subscription may be expired, using its own deterministic key; retrieval must
confirm expired+unpaid before replacing the reservation. An unpaid linked
PaymentIntent is allowed only after verifying its ID/customer/mode/app/purchase,
server-owned USD amount, zero received/capturable amounts and one of
requires_payment_method/requires_confirmation/requires_action/canceled. Recheck
it after expiry, including a newly linked PI or a previously linked PI whose
reference disappeared. Changed IDs, paid/processing/capturable/conflicting
evidence retain the original reservation. Stripe's documented authority is the
expired Session, which cannot be completed; immediate PI cancellation propagation
is not assumed. Never call PaymentIntent.cancel. Same-SKU resumes.
Completed/processing/foreign/conflicting or ID-unknown creation remains protected.
Lost expiry responses retrieve the same Session after restart; original purchase
rows, request keys and aliases remain. Active or retained paid plans still block
another initial subscription. A cancel query is never financial evidence.

This follow-on was identified during final official-contract inspection:
[Checkout expiration](https://docs.stripe.com/api/checkout/sessions/expire)
permits an open Session even when it already has an unpaid PaymentIntent, and
the pinned official SDK directs Checkout-linked PI cancellation to Session
expiry. Regressions exercise both modes, pack-to-pack/plan changes, unpaid PI
states, response loss/restart, conflicting ownership/amounts, and payment races.
Only synthetic provider objects were used; genuine hosted back/cancel remains
parent verification.

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
hyphenated. Only convert_success has the same balanced/layout enums. No additional
Umami destination, custom funnel event/property or analytics backend/proxy was added. Actual
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

## B verification (unchanged backend/provider baseline)

Final local verification finished October 17 UTC; the requested October 16
report path is retained.

| Check | Current result |
| --- | --- |
| Full backend | **521 passed**, 0 failures/skips (13 SDK/Starlette deprecation warnings) |
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
The final linked-PI follow-up adds 42 intent/state/race cases: full backend
increased from 479 to 521. Its focused checkout/billing run passed 163 tests.
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

The consolidated product/report push was followed by a fixture-only teardown
repair discovered while retaining the final raw SDK receipt report: closing the
synthetic HTTPS page can cancel an in-flight loopback proxy. Only page-closed
cancellation is ignored; live failures still throw and every provider route stays
installed through teardown, so no synthetic ingestion escapes. Product code,
financial tests and build behavior are unchanged. Both browser suites were
replayed after the repair.

The preceding 50edf84 workflow completed browser-end-to-end and python-backend
successfully on the parent-owned Studio Linux ARM64 runner; node-frontend was
still awaiting a runner when the official-contract PI follow-up was prepared.
That follow-up passed the full local suites again before pushing. Final delivery
head and Linux job results are recorded in PR8/checks, separately from these
local results. Superseded task-owned queued jobs are canceled to conserve
minutes; parent-owned runs/settings remain untouched. Raw GitHub job-log download
was blocked by its storage host here; job/step metadata remained available.
Parent owns independent review and genuine provider verification.

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
2. Configure only this app's snapshot webhook endpoint at `/api/stripe/webhook`
   with exact delivery API version **2026-08-26.dahlia** (`WEBHOOK_API_VERSION`).
   Keep stripe-python **14.4.1** and outgoing HTTP **2026-02-25.clover**
   (`API_VERSION`). The independent pins are intentional; every other incoming
   version, including Clover/earlier Dahlia, is rejected. Do not change other
   endpoints, account defaults or keys to work around the shared version cap.
   Parent first proves genuine signed target-version TEST delivery, separately
   from the older Clover evidence, before creating only Statement's LIVE endpoint.
   Subscribe
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

- [API versioning](https://docs.stripe.com/api/versioning), [webhook versioning](https://docs.stripe.com/webhooks/versioning), [Dahlia changes](https://docs.stripe.com/changelog/dahlia), [retained integer quantity](https://docs.stripe.com/changelog/dahlia/2026-03-25/invoice-items-decimal-quantity)
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

53 files relative to refreshed main:

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
- `backend/tests/test_webhook_versions.py`
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
- `frontend/src/components/Pricing.test.tsx`
- `frontend/src/components/PrivacyControls.tsx`
- `frontend/src/components/PrivacyControls.test.tsx`
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
