# 10 adjacent "boring data problem" tools from the same engine

`statement-to-excel` is one instance of a general pattern: **a painful, recurring,
manual document-to-structured-data extraction that a business will gladly pay
$30–$100+ to stop doing by hand.** The same core — *PDF/text in → detect the
table/records → normalize → exact spreadsheet out, metered by page* — drops
straight onto each idea below. Every one targets a buyer with a budget and a
deadline, not a consumer hunting for free.

Reuse map for each: the parsing layer (`engine.py`), the writers
(`writers.py`), the metering/credits model (`billing.py`), the FastAPI shell
(`api.py`), and the localized React storefront. Only the *profile* (which
columns/records to expect, validation rules) changes.

| # | Tool | Source document | Output | Who pays & why | Engine delta |
|---|------|-----------------|--------|----------------|--------------|
| 1 | **invoice-to-excel** | Vendor invoices / bills (PDF) | Line-item table + totals, ready for AP import | Bookkeepers, AP clerks doing manual entry into QuickBooks/Xero | Add an invoice profile (line items, tax, total) + total-reconciliation check |
| 2 | **brokerage-1099-extractor** | 1099-B / consolidated brokerage tax PDFs | Per-lot proceeds/cost-basis sheet for Schedule D | Tax preparers in filing season; wash-sale reconciliation | Section detection (1099-B vs -DIV vs -INT); per-lot rows |
| 3 | **paystub-to-excel** | Payroll stubs (PDF) | Earnings/deductions/YTD table across periods | HR/payroll auditors, loan underwriters verifying income | Stub profile + multi-period roll-up + gross→net validation |
| 4 | **rent-roll-normalizer** | Property-manager rent rolls (PDF/varied) | Unit-level rent/occupancy/lease-end sheet | CRE analysts, lenders underwriting multifamily loans | Wide-table detection; per-unit records; occupancy summary |
| 5 | **utility-bill-extractor** | Electric/gas/water bills (PDF) | Usage + cost time series per meter | ESG/sustainability teams, energy consultants | Meter/period parsing; kWh & cost columns; per-account grouping |
| 6 | **insurance-loss-run-parser** | Carrier loss-run reports (PDF) | Claim-level table (date, type, paid, reserved) | Commercial insurance brokers quoting renewals | Claim record profile + paid/reserved/incurred reconciliation |
| 7 | **shipping-manifest-to-excel** | BOL / packing lists / customs docs (PDF) | SKU/qty/weight/HS-code line table | Freight forwarders, customs brokers, 3PLs | Manifest profile; HS-code validation; weight/qty totals |
| 8 | **medical-eob-extractor** | Insurer EOBs / remittance advice (PDF) | Service-line table (CPT, billed, allowed, patient resp.) | Medical billing companies reconciling payments | EOB/ERA profile; CPT + adjustment-code columns |
| 9 | **lab-report-digitizer** | Clinical/industrial lab result PDFs | Analyte → value/unit/reference-range table | Clinics, environmental & food-testing labs | Result-row profile; out-of-range flagging; unit normalization |
| 10 | **credit-card-portfolio-merger** | Many statements, many banks (PDF) | One unified, categorized transaction ledger | Small-business owners, fractional CFOs at month-end close | Multi-file batch + the existing bank profiles + auto-categorization |

## Why this set, specifically

- **Same buyer psychology as statement conversion.** Each is a task currently
  done by a human retyping numbers from a PDF into Excel for hours — high enough
  pain and high enough hourly value that $30–$100/mo or per-credit pricing is a
  rounding error against the labor saved.
- **No new moat required.** They differ only in the *profile* (expected
  columns/records + a domain validation rule). The hard parts — robust
  date/amount parsing, table auto-detection, exact-decimal XLSX output, metering,
  i18n storefront — are already built and tested here.
- **Compliance-adjacent = stickier + higher willingness to pay.** Tax (1099),
  insurance (loss runs), medical (EOB), and lending (paystub, rent roll) docs are
  recurring, deadline-driven, and error-sensitive, which justifies business
  pricing and recurring subscriptions over one-off consumer use.

## Productization notes (shared)

- **Validation as a feature, not an afterthought.** Each profile should ship a
  reconciliation check (e.g. invoice line items sum to the stated total; paystub
  gross − deductions = net). A visible "✓ totals reconciled" badge is a strong
  trust and conversion lever for a paid B2B tool.
- **Batch is the upsell.** Single-file is the free/trial hook; "drop a folder of
  120 statements" is what a Business/Firm plan is actually bought for.
- **Privacy is the wedge against incumbents.** "Processed locally / nothing
  stored" is a real differentiator for finance, legal, and healthcare buyers who
  cannot upload client PII to a random web tool.
