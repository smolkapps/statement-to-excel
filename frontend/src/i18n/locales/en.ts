import type { Translation } from "../types";

export const en: Translation = {
  locale_name: "English",
  nav_product: "Product",
  nav_pricing: "Pricing",
  nav_convert: "Convert",

  hero_eyebrow: "Bank statement converter",
  hero_title: "Turn bank-statement PDFs into clean Excel — in seconds",
  hero_subtitle:
    "Accountants, bookkeepers and finance teams: stop retyping transactions. Drop a statement PDF, get a tidy, exact spreadsheet with every date, description, amount and balance.",
  hero_cta: "Convert a statement",
  hero_secondary_cta: "See pricing",
  hero_trust:
    "Text-based PDFs only; scanned statements need OCR. Exact decimals, never rounded.",

  feature_accuracy_title: "Exact, not approximate",
  feature_accuracy_body:
    "Amounts are parsed as precise decimals — parentheses, trailing minus, DR/CR markers and thousands separators all handled. Debits and credits keep their correct sign.",
  feature_private_title: "No third-party AI required",
  feature_private_body:
    "The converter extracts transaction dates, descriptions, amounts and balances without sending your statement to a third-party AI API.",
  feature_formats_title: "Excel, CSV or JSON",
  feature_formats_body:
    "Get a formatted .xlsx with a summary sheet, a plain CSV for imports, or JSON for your own pipeline. Your accounting software will thank you.",

  how_title: "How it works",
  how_step1: "1. Upload your statement PDF",
  how_step2: "2. We detect the transaction table automatically",
  how_step3: "3. Download a clean spreadsheet",

  convert_title: "Convert a statement",
  convert_drop: "Drop a PDF here, or click to choose",
  convert_drop_hint: "Text-based statements only (scanned images need OCR first).",
  convert_format: "Output format",
  convert_currency: "Currency",
  convert_button: "Convert",
  convert_processing: "Processing…",
  convert_download: "Download",
  convert_error_generic:
    "We couldn't read transactions from that file. It may be image-only or an unusual layout.",
  convert_error_insufficient:
    "You're out of included pages and credits. Buy a credit pack to continue.",
  convert_results_title: "Preview",
  col_date: "Date",
  col_description: "Description",
  col_amount: "Amount",
  col_balance: "Balance",
  summary_count: "Transactions",
  summary_debit: "Total debit",
  summary_credit: "Total credit",
  summary_net: "Net",

  pricing_title: "Pricing built for businesses",
  pricing_subtitle:
    "Flat monthly plans for steady volume, or prepaid credits when you only convert now and then.",
  pricing_plans_title: "Monthly plans",
  pricing_credits_title: "Prepaid credit packs",
  pricing_per_month: "/mo",
  pricing_included_pages: "pages / month included",
  pricing_overage: "per extra page",
  pricing_buy: "Buy",
  pricing_choose_plan: "Choose plan",
  pricing_credits_each: "per credit",
  pricing_credit_explainer: "1 credit converts 1 statement page. Credits never expire.",

  account_title: "Your account",
  account_plan: "Plan",
  account_credits: "Credits",
  account_included_remaining: "Included pages left this cycle",
  account_buy_credits: "Buy credits",

  footer_tagline: "The fastest way from bank-statement PDF to spreadsheet.",
  footer_rights: "All rights reserved.",
};
