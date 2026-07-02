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

- **Runs offline.** The conversion path makes zero network calls and uses no API
  keys. No ads, no data resale — you pay for the tool, not with your data.
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
│   │   ├── writers.py           # CSV / JSON / styled XLSX (+ summary sheet)
│   │   ├── billing.py           # credits + subscription metering (mock provider)
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
| `POST` | `/api/checkout` + `/api/checkout/{sid}/fulfill` | (mock) buy credits / plan |

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

---

## Monetization model

Implemented as a pure, deterministic core in `backend/statement_to_excel/billing.py`
and mirrored client-side in `frontend/src/lib/pricing.ts` (kept in sync by
`tests/test_pricing_parity.py`).

- **Subscriptions** — each plan grants an included page allowance per cycle
  (Free 3, Starter 120, Business 500, Firm 2000); overage spends prepaid credits.
- **Prepaid credits** — `pack_50` ($30), `pack_200` ($100), `pack_1000` ($400);
  1 credit converts 1 page; volume discounts the per-credit price.

Real payment capture is **stubbed behind `STX_BILLING_PROVIDER`** (default
`mock`): the mock provider records purchase intents in memory and grants
credits/plans on fulfilment, so the whole buy→grant flow runs and is unit-tested
with **no Stripe key**. Wiring a real provider is a single `BillingProvider`
subclass.

---

## Testing

All tests run offline. Fixtures are **synthetic** statements generated with
reportlab (`backend/tests/make_fixtures.py`) — no private data.

```bash
# Backend
cd backend && . .venv/bin/activate
pip install -e ".[test]"
python tests/make_fixtures.py     # (re)generate fixtures (also auto-built by conftest)
pytest                            # 79 tests

# Frontend
cd frontend && npm install
npm test                          # 29 tests (vitest)
```

What's covered: exact-equality parsing on a clean ruled fixture; field-accuracy
on messier borderless/credit-card fixtures; the OCR-only error path; every output
writer; the full metering math and the mock purchase flow; the API end-to-end via
Starlette's `TestClient` (including 402 insufficient-credits and 422 unparseable
paths); and on the frontend, locale parity (no missing/stray/empty keys, real
translations), pricing math, the localStorage account store, the API form
builder, and a React component render + interaction test.

> Build & test are run on a Linux host; see the offload note in development.

---

## Roadmap

Per-bank layout profiles, batch (folder) conversion, auto-categorization, and the
ten adjacent extraction tools in [IDEAS.md](IDEAS.md) — all of which reuse this
exact engine and storefront, swapping only the document profile.

## License

MIT — see [LICENSE](LICENSE).
