// The complete translation shape. Every locale dictionary must implement this
// exactly — a compile error here (or the i18n parity test) catches a missing or
// stray key before it ships a half-translated page.

export interface Translation {
  // chrome
  locale_name: string;
  nav_product: string;
  nav_pricing: string;
  nav_convert: string;

  // hero (landing)
  hero_eyebrow: string;
  hero_title: string;
  hero_subtitle: string;
  hero_cta: string;
  hero_secondary_cta: string;
  hero_trust: string;

  // value props
  feature_accuracy_title: string;
  feature_accuracy_body: string;
  feature_private_title: string;
  feature_private_body: string;
  feature_formats_title: string;
  feature_formats_body: string;

  // how it works
  how_title: string;
  how_step1: string;
  how_step2: string;
  how_step3: string;

  // converter
  convert_title: string;
  convert_drop: string;
  convert_drop_hint: string;
  convert_format: string;
  convert_currency: string;
  convert_button: string;
  convert_processing: string;
  convert_download: string;
  convert_error_generic: string;
  convert_error_insufficient: string;
  convert_results_title: string;
  col_date: string;
  col_description: string;
  col_amount: string;
  col_balance: string;
  summary_count: string;
  summary_debit: string;
  summary_credit: string;
  summary_net: string;

  // pricing
  pricing_title: string;
  pricing_subtitle: string;
  pricing_plans_title: string;
  pricing_credits_title: string;
  pricing_per_month: string;
  pricing_included_pages: string;
  pricing_overage: string;
  pricing_buy: string;
  pricing_choose_plan: string;
  pricing_credits_each: string;
  pricing_credit_explainer: string;

  // account
  account_title: string;
  account_plan: string;
  account_credits: string;
  account_included_remaining: string;
  account_buy_credits: string;

  // footer
  footer_tagline: string;
  footer_rights: string;
}

export type LocaleCode = "en" | "zh" | "ja" | "es" | "it";
