# Statement to Excel — five-persona launch QA, 2026-10-29 UTC

Local conversion first success is verified for **5/5 personas** on implementation
`04e34661e78ab8bf3b47b7b893bf8fba8a0b67aa`, branch
`qa/five-persona-20261029`, based on `d9fa685`. This is local browser evidence;
production first success is **blocked for 5/5** by the environment's Chromium TLS
trust error. This report does not mark the whole app or production as passed.

## Scope and existing work

Before starting, inspected AGENTS.md, WORKLOG.md, existing October 11–17 QA and
billing reports, git status/worktrees/branches, local processes, and open GitHub
PRs. The checkout was clean. No running five-persona pass or equivalent current
report was found. The only open PR was unrelated CI-runner PR #9; it was left
untouched. Exactly five persona agents ran independent real Chromium browser
contexts, with distinct copies of a generated synthetic statement. No real
financial document was used. Browser owner-QA mode was set before navigation to
suppress analytics. Production attempts were read-only navigation only.

Write journeys used the actual local Vite production preview and Python API at
http://127.0.0.1:4173 with unconfigured, unmetered billing and isolated ephemeral
state. No signup was present or required. No production/customer account or
statement was written; no email/message, purchase, credential/security change,
provider operation, production configuration, merge, or deployment occurred.
The existing configured-billing regression suite uses synthetic accounts and
intercepts payment navigation/provider failures; it is not payment proof.

## Ranked findings

Counts are **distinct personas that actually reported the issue**, not a claim
of population prevalence. Equal counts are ordered by practical impact.
Screenshots below are relative to the downloadable evidence bundle's root.

| Rank | Finding | Personas | Count | Outcome | Evidence |
| --- | --- | --- | ---: | --- | --- |
| 1 | Production browser navigation fails `net::ERR_CERT_AUTHORITY_INVALID` through the inherited HTTPS proxy. | All five | 5/5 | Access blocked; TLS verification retained; not diagnosed as a production certificate defect. | `impatient/baseline/production-blocked.png`, `skeptic/baseline/production-blocked.png`, `mobile/baseline/production-blocker.png`, `literal/baseline-production-blocked.png`, `breaker/production-blocker.png` |
| 2 | Tapping the primary CTA hides the converter heading/upper dropzone behind the sticky mobile header. | Mobile | 1/5 | Fixed with measured header height and anchor scroll margin. | `mobile/baseline/after-cta.png` → `mobile/final/after-cta.png` |
| 3 | An obvious `.txt` upload appears accepted and enables Convert; rejection comes only after sending it to the API. | Breaker | 1/5 | Fixed immediate localized type/empty/20 MiB validation, disabled Convert and valid-file recovery. Corrupt `.pdf` still receives authoritative server validation. | `breaker/baseline/03-text-file-selected.png` → `breaker/final/validation-junk-en.png` |
| 4 | How it works omits the required Convert click; literal reader waits after selecting a PDF. | Literal Spanish | 1/5 | Fixed in all five locales: click Convert, wait, download. | `literal/baseline/04-selected-awaiting-convert.png` → `literal/final/02-spanish-landing.png` |
| 5 | With billing disabled, pricing disappears and no explicit current cost is shown. | Skeptic | 1/5 | Fixed no-payment/no-sign-in note after successful API availability confirmation only; hidden while pending, failed or paid. | `skeptic/baseline/local-01-landing.png` → `skeptic/final/local-01-landing.png` |
| 6 | Mobile language/format/currency selects are 42/39/39 px high. | Mobile | 1/5 | Fixed all three to at least 44 px. | `mobile/final/after-cta.png`, `mobile/final/findings.json` |
| 7 | Spanish reconciliation uses comma decimals while totals/table use point decimals. | Literal Spanish | 1/5 | Fixed locale formatting while retaining exact integer/fraction digits, negative subunits and unchanged export values. | `literal/baseline/05-first-success.png` → `literal/final/05-first-success.png` |
| 8 | No owner-approved legal Terms page/link is available for the skeptic's requested review. | Skeptic | 1/5 | **Unresolved owner content.** Added product use/limits plus a discoverable privacy link; these are not represented as legal Terms. | `skeptic/final/local-02-use-and-limits.png`, `skeptic/final/report.json` |
| 9 | Initial new limits wording “one PDF per account” could imply a browser-account upload limit. | Skeptic, fixed-preview follow-up | 1/5 | Corrected to one bank account per PDF in all locales, then reran all five on the final candidate. | `skeptic/fixed/local-02-use-and-limits.png` → `skeptic/final/local-02-use-and-limits.png` |

## Final five-persona proof

Each final journey used a fresh real browser context at the final implementation,
selected its own synthetic PDF, received HTTP 200, downloaded an actual XLSX,
and showed two exact transaction rows. Downloaded workbooks contain
Transactions/Summary/Checks. Independent Decimal arithmetic verifies opening
100 + money in 20 − money out 10 = printed closing 110, with running balances
120 and 110. The stored row-linked Checks formulas were inspected and evaluated
independently; openpyxl does not calculate spreadsheet formula caches, so no
Excel-engine recalculation is claimed.

| Persona | Local first success | Additional proof | Final evidence |
| --- | --- | --- | --- |
| Impatient | Passed | First CTA works; heading top 126.22 px, sticky header bottom 81 px; no page errors. | `impatient/final/report.json`, `impatient/final/workbook-verification.json`, `impatient/final/04-first-result.png` |
| Skeptic | Passed | Real pricing response deliberately held: cost note absent pending, visible after actual `checkout_available=false`; use/limits and privacy link work. Terms remain unavailable. | `skeptic/final/report.json`, `skeptic/final/local-02-use-and-limits.png`, `skeptic/final/local-05-first-success.png` |
| Mobile | Passed | 375×812, touch, CDP Slow 3G: 400 ms latency, 50,000 bytes/s each direction. Header bottom 138.59 px, heading top 183.5 px (44.91 px clear gap), all selects 44 px, document width 375 px. Native file chooser opened by touch. No overflow/page errors. | `mobile/final/findings.json`, `mobile/final/after-cta.png`, `mobile/final/success-full.png` |
| Literal Spanish | Passed | Literal instructions match the required Convertir step; Spanish decimal punctuation agrees in equation, totals and table; localized junk-file guidance and corrected limits verified. | `literal/final/result.json`, `literal/final/05-first-success.png`, `literal/final/06-use-limits-spanish.png` |
| Breaker | Passed | `.txt` rejected in all five locales with zero conversion requests; empty and 20 MiB+1-byte UI-only File also rejected without upload. Corrupt PDF double click sends one request/422. Valid double click plus Back during a bounded 800 ms delay sends one request and preserves real download. | `breaker/final/report.json`, `breaker/final/validation.json`, `breaker/final/09-first-success-after-back.png` |

Production first-success result for every persona: **blocked before landing**.
The inherited proxy and TLS validation were preserved, and no trust-store
modification or ignore-HTTPS-errors flag was used. Separate local loopback
browser sessions do not use the external proxy. These results cannot prove the
published site has these fixes or that its real conversion flow works.

The host is Linux with no `xcrun`; a connected N759MS iPhone could not be queried
or used. Mobile proof is browser/device/network emulation only.

## Verification

All code changes are frontend-only. Backend, privacy/analytics implementation,
production config, pricing catalog and unrelated CI work are unchanged.

- Frontend: **231 tests passed in 13 files**, including new localized rejection,
  no-network recovery, cost-visibility and exact Spanish-number regressions.
- SEO/TypeScript/Vite production build passed. Built asset hashes retained.
- Routing: **2 passed**, real dev/preview HTTP to the Python API.
- Playwright Chromium: **18 passed, 13 skipped, 0 failed**. The 13 existing
  optional provider-SDK privacy cases require captured official SDK fixtures via
  `STX_PROVIDER_SDK_DIR`; those fixture files were unavailable. No fake SDK or
  external provider ingestion was substituted. Applicable conversion, error,
  billing-UI, all-locale and viewport journeys passed; new 375 px anchor/touch-size
  and limits/privacy checks passed.
- Backend canonical command `(cd backend && .venv/bin/python -m pytest -q)`:
  **579 tests passed**, 119 existing deprecation warnings. An initial invocation
  from the repository root failed 24 tests because subprocess test helpers use
  `python -m tests.deadline_worker` and require the documented backend working
  directory. That output is preserved separately, not hidden; the canonical run
  passed without backend edits.
- Synthetic accuracy: **22 statements / 14 families / 372 exact ordered rows**,
  100% exact rows and balance gates; zero missing/extra rows, silent errors or
  false alarms. This is synthetic regression coverage, not real-bank accuracy.
- All five final downloaded workbooks opened and arithmetic independently checked.
- `git diff --check` passed.

Raw logs and reports: `verification/`. Baseline, initial fixed-preview and final
candidate screenshots/reports are preserved in separate persona folders. The
bundle contains 124 PNG screenshots, reusable journey scripts, synthetic fixtures,
actual downloads and an evidence index. Source commit remains above; subsequent
report-only commits do not change the built application.

## Remaining blockers and handoff

1. Production browser action: navigate to
   `https://statement-to-excel.apps.smolkin.org/` using Chromium with inherited
   proxy. Outcome **blocked**, reason `net::ERR_CERT_AUTHORITY_INVALID` for all
   five personas. Local first success and fixes completed independently. Runtime
   browser trust must be resolved by the environment owner before production
   landing/conversion proof; no user financial upload is needed.
2. Legal-content action: review the site's Terms. Outcome **unavailable**, target
   owner-approved Terms content/link absent from the tested UI. Product limits
   and privacy are available, but cannot establish legal readiness.
3. Optional analytics regression action: run 13 actual-provider-SDK tests.
   Outcome **skipped**, required captured official SDK fixtures unavailable.
   Analytics unit/consent tests passed; analytics source was not changed.
4. Device action: inspect/use N759MS iPhone. Outcome **unavailable**, no Apple
   host tooling/device access in this Linux environment; emulated mobile proof
   completed instead and explicitly labeled.

No merge or deployment is authorized by this task. Review the draft PR and
resolve production access/owner content separately; do not call this a complete
production launch pass.

## Draft PR delivery blocker

The feature branch push succeeded. Creating a **draft** PR in
`smolkapps/statement-to-excel` (head `qa/five-persona-20261029`, base `main`)
was **denied by automatic approval review**. Its stated reason: creating and
publishing the draft PR is an external repository commitment, and no trusted
user message explicitly authorizes opening it. No PR was created, and the denied
action was not retried or routed through another tool. The prepared title/body
are included as `draft-pr.md` in the evidence bundle. Explicit user approval is
needed to perform that remaining publication action. The implementation,
verification, branch push and evidence package are complete independently.
