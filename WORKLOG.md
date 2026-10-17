# Worklog

## 2026-10-16 — Studio CI migration

Goal: move the current open PR workflow source to Studio without altering its application changes or checks.

Changed workflow runner profiles to the existing per-repository local defaults with JSON hosted rollback. Keep this PR's provider-SDK downloads, STX_PROVIDER_SDK_DIR, synthetic PDF fixtures, accuracy, routing and browser assertions unchanged. Studio-only browser provisioning uses the exact previously reviewed ubuntu24.04-arm64 override plus browser-only Chromium install against centrally installed dependencies; hosted keeps --with-deps. No billing, analytics, fixtures, app code or guidance is changed. Branch/PR-only policy remains respected; no main push or merge.

Verification during preparation: parsed before/after comparison permits only the documented runner/Xcode/signing-opt-in/Studio-browser setup differences; all other job fields, triggers, steps and commands remain identical. Profile JSON resolution and added shell syntax verified. Closest branch AGENTS.md/.github/AGENTS.md/.github/workflows/AGENTS.md were read where present. No app tests, compilation, dependency install, workflow dispatch, publication or GitHub mutation executed. Parent owns source review/application and actual CI verification.

Hosted rollback: STUDIO_CI_UBUNTU_LATEST = "ubuntu-latest".

## 2026-10-16 — PR8 correction B

Continue the same branch/PR from reviewed b23; preserve parent's 8b9 Studio CI
change. Root Codex owns implementation and AGENTS; exact device policy remains
once. Retain a distinct paid current invoice/usage on older-cycle reversal;
keep renewal tombstones/outbox and genuine reconciliation holds. Only signed
paid events can recover strictly proved pre-stop service. Dispute cutoff uses
its immutable creation time. Different-SKU choices require owned provider-confirmed
Session expiry, preserving keys/history and payment races. Recover initially
unsaved browser capability on explicit safe storage retry.

Map Google event underscores without changing Umami. Both optional providers
require new persisted/read-back consent; old Google-only yes is insufficient.
Stop before persistence, handle stale yes/removal failure and cross-tab clear.
Actual sampled Google diagnostics required a disposable SDK frame and exit guard;
CF uses tested SRI/accessor/lifetime retirement. Scope cookies to this host/stream.
Track empty public production identity slots in frontend/.env.production; narrow
CI push to main without changing parent runner ownership. No provider operation,
real statement, secret, purchase/refund, deployment or main push occurred.

Evidence and complete file/family tables: docs/codex-live-billing-2026-10-16.md.

Follow-up: retaining raw SDK receipts exposed a synthetic-HTTPS proxy teardown
race after page closure. Guard only closed-page cancellation, keep all provider
routes installed, and rerun browser suites. Product code is unchanged. Final CI
awaits parent-owned Studio runner assignment; no runner setting was changed.

Final contract follow-up: Stripe allows an open unpaid Checkout Session to have
a PaymentIntent. Replace the overly restrictive absence guard with owned
customer/mode/app/purchase/USD and unpaid/zero-received/capturable checks before
and after Session expiry. Session expiry is the provider authority; never cancel
the PI directly. Preserve reservations on processing, paid or conflicting races.
Cover both modes, choice changes, expiry response loss/restart and late PI state
changes using synthetic objects. Revalidate required suites before one follow-up
push; previous final-head browser/backend CI jobs passed, frontend still queued.

Final local candidate: 521 backend, 208 frontend, build/SEO/TypeScript, 2 routing,
22 synthetic statements/14 families/372 exact rows, zero silent errors/false
alarms; 29 Chromium and 29 agent-owned Camoufox passed. Actual blocked SDK
receipts and desktop/narrow layouts inspected; two downloaded Checks workbooks
independently calculate printed closing figures (stored formula caches blank).
No genuine provider, device/simulator or real-bank verification is claimed.
