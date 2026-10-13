# statement-to-excel

Turn **bank-statement PDFs into clean, exact Excel** (or CSV / JSON) — a focused
web app for accountants, bookkeepers and finance teams who are tired of retyping
transactions by hand.

It does **one** boring-but-painful job extremely well: take a text-based
statement PDF, auto-detect the transaction table, and emit a tidy spreadsheet
with every **date, description, amount and balance** — amounts parsed as exact
decimals (never rounded), debits and credits correctly signed.

```
┌─────────────────────┐      ┌──────────────────────┐      ┌────────────────────┐
│  React + TS frontend │ ───▶ │  FastAPI backend      │ ───▶ │  .xlsx / .csv / .json │
│  (localized landing, │ POST │  parse → normalize →  │      │  exact transactions   │
│   drag-drop, pricing)│ /api │  meter (credits/plan) │      │  + summary sheet      │
└─────────────────────┘      └──────────────────────┘      └────────────────────┘
```

- **No external parsing service.** The parsing engine makes no outbound network
  calls and uses no API keys. The hosted web UI uploads the selected PDF to this
  app's backend; the CLI can run entirely on your machine.
- **Business pricing, by design.** Monthly plans for steady volume **and**
  prepaid credit packs ($30–$400) for occasional use. 1 credit = 1 statement
  page. (No ads, no affiliate.)
- **Localized.** The storefront ships in **English, 中文, 日本語, Español, Italiano**
  with a compile-time-enforced translation contract.

This repo is a monorepo: a Python `backend/` and a Vite/React/TypeScript
`frontend/`.

---

## Repository layout

```
statement-to-excel/
├── backend/                     # Python: parsing engine + FastAPI + CLI
│   ├── statement_to_excel/
│   │   ├── parsers.py           # robust date / amount parsing
│   │   ├── transaction.py       # the normalized Transaction model (Decimal)
│   │   ├── engine.py            # PDF/text -> transactions (table + line strategies)
│   │   ├── reconciliation.py    # pure Decimal checks against printed totals
│   │   ├── writers.py           # CSV / JSON / XLSX (Summary + Checks sheets)
│   │   ├── billing.py           # durable metering + Stripe test Checkout
│   │   ├── api.py               # FastAPI app (upload -> metered conversion)
│   │   └── cli.py               # `stx statement.pdf -o out.xlsx`
│   └── tests/                   # pytest, incl. synthetic PDF fixtures + error paths
├── frontend/                    # Vite + React + TS web app
│   └── src/
│       ├── i18n/                # 5 locales + typed contract + parity tests
│       ├── lib/                 # pricing math, account store, API client (all tested)
│       ├── components/          # Header, Hero, Features, Converter, Pricing, …
│       └── pricing.json         # pricing source of truth (parity-tested vs backend)
├── IDEAS.md                     # 10 adjacent "boring data problem" tools
├── LICENSE                      # MIT
└── .env.example
```

---

## Quick start

### Backend (API + engine)

```bash
cd backend
python3 -m venv .venv && . .venv/bin/activate
pip install -e ".[server]"        # core + uvicorn
uvicorn statement_to_excel.api:app --reload    # http://127.0.0.1:8000
```

Endpoints (see `api.py` for the full list):

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/api/convert` | multipart PDF upload → metered conversion (xlsx/csv/json) |
| `GET`  | `/api/pricing` | plan + credit-pack catalog |
| `GET`  | `/api/account/{id}` | account metering state |
| `POST` | `/api/account/{id}/quote` | cost of processing N pages (no charge) |
| `POST` | `/api/checkout` | idempotent Stripe test Checkout |
| `POST` | `/api/stripe/webhook` | signed paid event → exactly-once entitlement |

### Backend (CLI)

The same engine is scriptable:

```bash
stx statement.pdf -o transactions.xlsx     # Excel with a summary sheet
stx statement.pdf --format json            # JSON to stdout
stx statement.pdf -o out.csv               # CSV
```

### Frontend

```bash
cd frontend
npm install
npm run dev        # http://localhost:5173  (set VITE_API_BASE to point at the API)
npm run build      # type-check + production build to dist/
```

---

## How conversion works

Two complementary strategies run and the better result wins
(`engine._choose_strategy`):

1. **Ruled tables** (`_from_tables`) — uses pdfplumber's table extraction, then
   scores each column for "date-ness" and "amount-ness" to locate the
   transaction columns. Recognises separate **Debit/Credit** columns and signs
   amounts correctly (debit → negative). This is *authoritative when it parses*,
   because it captures column semantics the line scanner cannot.
2. **Borderless text lines** (`_from_lines`) — a fallback for statements with no
   ruling, where each row is `<date> <description…> <amount> [balance]` and
   continuation lines are folded into the previous description.

Dates and amounts go through conservative parsers that return `None` rather than
guess, so a successful parse is itself the signal that a cell is a date/amount.
The year and day-first/month-first order are inferred from the statement header
when not given. Everything is `decimal.Decimal` end-to-end — JSON/CSV preserve
exact values; XLSX uses real numeric/date cells.

**Out of scope:** scanned / image-only PDFs. The tool raises a clear error
(rather than emitting garbage) so you know to run OCR first.

### Reconciliation status

Results show one status in English, Chinese, Japanese, Spanish or Italian:

- **Balanced:** parsed rows agree exactly in Decimal with the printed totals.
  Deposit accounts use opening + money in - money out = closing; cards use
  previous - payments and credits + purchases + fees + interest = new balance.
  Every printed subtotal found must agree too. Deposit checks require opening
  and closing; card checks require all six terms, including explicitly printed
  zero fees or interest.
- **Doesn't balance:** a check fails. JSON includes the signed
  calculated-minus-printed closing difference and individual check differences.
  Review the highlighted rows: their year crossed December/January, their sign
  came from a balance change, or their description joined several lines.
- **Can't check:** required totals could not be found. Compare the numbers
  before using the output. Missing printed figures never become assumed zeros.

The reconciliation function takes only parsed rows and extracted totals, so it
can be reused outside PDF parsing. JSON downloads and API previews include
`reconciliation` (`status`, `account_type`, `terms`, `printed_totals`,
`difference`, `check_differences`, `row_flags`) and a coarse `layout` ID. Row
indices are zero-based. CSV retains its original six columns. XLSX adds a
`Checks` sheet with live formulas referencing transaction cells and printed
comparison figures; flagged rows carry cell notes. Excel recalculates these
formulas when opened. Workbook generation remains entirely in memory, with
`openpyxl>=3.1,<3.2` pinned for its internal writer API.

A balanced equation supports checking extracted cash flow, but cannot prove
every date or description is right or detect all equal and opposite mistakes.
The corpus gates below compare every row independently of reconciliation.

---

## Monetization model

Implemented as a pure, deterministic core in `backend/statement_to_excel/billing.py`
and mirrored client-side in `frontend/src/lib/pricing.ts` (kept in sync by
`tests/test_pricing_parity.py`).

- **Subscriptions** — each plan grants an included page allowance per cycle
  (Free 3, Starter 120, Business 500, Firm 2000); overage spends prepaid credits.
- **Prepaid credits** — `pack_50` ($30), `pack_200` ($100), `pack_1000` ($400);
  1 credit converts 1 page; volume discounts the per-credit price.

The service has two configuration modes. **Production runs unmetered until
Stripe test credentials and the webhook are configured**, with
`STX_BILLING_PROVIDER=stripe` and both keys unset initially.

- **Checkout unavailable:** missing either an `sk_test_` secret key or a `whsec_`
  webhook secret means `checkout_available=false`. Conversion accepts any valid
  statement up to 100 pages under the 20 MiB limit, with all PDF validation and
  deletion intact.
  It consumes no allowance/credits, never returns 402, writes no account,
  conversion-charge or checkout rows, and returns
  `charge: {"metered": false, "pages": N}`. Expired-fingerprint cleanup may still
  run. The UI hides the Pricing section and links, hero pricing button and
  account chip, and makes no account or checkout calls. A failed pricing request
  is treated as unavailable.
- **Configured Stripe test billing:** both credentials satisfy the existing
  provider configuration rule, making `checkout_available=true`. The existing
  three-page free allowance, plan/credit metering, 24-hour conversion retry
  protection, 402 errors and idempotent checkout/Pro grants apply. Checkout errors
  display localized copy rather than backend configuration text.

Both `GET /api/pricing` and `GET /api/health` expose `checkout_available`; the
Stripe provider is its single source of truth. The flag describes configuration
readiness, not remote Stripe connectivity. Live keys and events are rejected.
Checkout requests require a stable `Idempotency-Key`; a durable SQLite
ledger reserves purchases before contacting Stripe and grants Pro only once from
verified paid webhooks. Browser redirects and localStorage never grant access.
Mock billing exists only as an explicitly injected unit-test double.

See [AGENTS.md](AGENTS.md) for the deploy model, privacy contract and full
verification commands. The external frontend autodeploy job does not start the
backend: production must route `/api/*` to a separately supervised ASGI service
before the SPA fallback. The repository contains an nginx example, not the
operator's actual production configuration.

Both billing modes reject PDFs over **100 pages** with HTTP 413 before extracting
transactions. Counting, parsing and output serialization run in a worker thread
so a long conversion does not block the API's health endpoint.

### Privacy

No statement data is stored. Your PDF is uploaded to our server for conversion
and deleted right after. Accepted uploads, converted rows and Excel worksheet
XML/workbooks are processed in memory. The app's **21 MiB multipart spool
threshold** exceeds its unchanged **20 MiB file limit**, so accepted PDFs never
create temporary disk files. Uploads are closed immediately in all success and
failure paths, with cleanup shielded from request cancellation; oversized
rejected or deliberately spooled files are deleted.
Statement bytes and extracted rows are never persisted or sent to analytics.
The existing Umami `convert-success` event receives only `balanced`
(`yes` / `no` / `unknown`) and coarse `layout` (`deposit_table`, `deposit_lines`,
`card_table`, `card_lines`, `unknown`) properties. Amounts, dates, names,
descriptions, file names and account IDs are never analytics properties.

Production nginx must match `frontend/deploy/nginx.conf.example`: use
`client_body_buffer_size 21m`, `proxy_request_buffering off` and
`proxy_buffering off` for `/api/*`, including HTTP/1.1 and HTTP/2. Its
`client_max_body_size 21m` allows multipart overhead around a 20 MiB PDF; the API
still returns HTTP 413 for any file over 20 MiB. These settings must also be
respected by any other production proxy.

Account/credit records and payment metadata are stored in configured billing
mode. Unmetered conversion creates no billing rows. For metered conversion
retries, the service also stores a SHA-256 fingerprint of the upload and conversion
options in an idempotency row with a **24-hour retention window**, measured from
its creation; replaying it does not refresh the window. Every conversion POST
purges rows older than 24 hours, including rejected requests. Cleanup is
opportunistic: without conversion traffic, removal of expired rows waits for the
next request. An expired key is treated as a new conversion and can consume usage
again. On migration, legacy fingerprint rows with unknown creation times are
discarded, while account/credit balances and historical usage remain unchanged.
These expiry rules apply only to conversion retry records, not payment or Pro
entitlement idempotency.

---

## Testing

Tests use synthetic statements and fake Stripe transports; conversion makes no outbound calls. Fixtures are **synthetic** statements generated with
reportlab (`backend/tests/make_fixtures.py`) — no private data.

```bash
# Backend
cd backend && . .venv/bin/activate
pip install -e ".[test]"
python tests/make_fixtures.py     # (re)generate fixtures (also auto-built by conftest)
pytest
python -m tests.accuracy_harness --output ../work/accuracy

# Frontend
cd frontend && npm install
npm test                          # Vitest suites
npm run build
npm run test:routing               # real dev and production-preview HTTP paths
npm run test:e2e                   # headless Chromium against real API
```

What's covered: exact-equality parsing on a clean ruled fixture; field-accuracy
on messier borderless/credit-card fixtures; the OCR-only error path; every output
writer; durable metering, signed webhooks, duplicate/concurrent/restarted checkout and purchase flows; the API end-to-end via
Starlette's `TestClient` (including 402 insufficient-credits and 422 unparseable
paths); bank-inspired synthetic layouts with a strict 100% complete-row gate; and on the frontend, locale parity (no missing/stray/empty keys, real
translations), pricing math, the localStorage account store, the API form
builder, and a React component render + interaction test.

The harness keeps the ten original deposit layouts and adds Chase, Citi,
Capital One and American Express-inspired card families. All data is invented.
It exercises posting and transaction dates, separate payments/fees/interest,
December-to-January periods, joined descriptions, repeated headers across page
breaks, no activity, overdrafts, million-dollar amounts and a 40-page statement
under the unchanged 100-page cap.

Its per-family report includes balance rate, exact ordered rows (including
dates, signed amounts and balances), missing/extra rows, **silent errors**
(`balanced` while any extracted row is wrong), and **false alarms** (correct
statements shown `not_balanced`). Required gates are 100% exact rows for every
synthetic layout, **0 silent errors** and **0 false alarms**. These figures measure
synthetic regression coverage, not accuracy on customers' real statements.
The verification record for this change is
[docs/codex-run-2026-10-13.md](docs/codex-run-2026-10-13.md).

> Build & test are run on a Linux host; see the offload note in development.

---

## Roadmap

Per-bank layout profiles, batch (folder) conversion, auto-categorization, and the
ten adjacent extraction tools in [IDEAS.md](IDEAS.md) — all of which reuse this
exact engine and storefront, swapping only the document profile.

## License

MIT — see [LICENSE](LICENSE).
