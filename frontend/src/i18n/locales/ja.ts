import type { Translation } from "../types";

export const ja: Translation = {
  locale_name: "日本語",
  nav_product: "製品",
  nav_pricing: "料金",
  nav_convert: "変換",

  hero_eyebrow: "銀行明細コンバーター",
  hero_title: "銀行明細のPDFを、数秒できれいなExcelに",
  hero_subtitle:
    "会計士・経理担当・財務チームへ。取引の手入力はもう不要です。明細PDFをドロップすれば、日付・摘要・金額・残高がそろった正確な表が手に入ります。",
  hero_cta: "明細を変換する",
  hero_secondary_cta: "料金を見る",
  hero_trust: "PDFを当社のサーバーにアップロードして変換します。テキスト形式のPDFのみ対応。スキャン画像にはOCRが必要です。",

  feature_accuracy_title: "概算ではなく、正確に",
  feature_accuracy_body:
    "金額は正確な小数として解析します。括弧、末尾のマイナス、DR/CR表記、桁区切りにも対応。借方・貸方の符号も正しく保持します。",
  feature_private_title: "外部のAIは不要",
  feature_private_body: "外部のAI APIに明細を送信せず、取引日、摘要、金額、残高を抽出します。",
  feature_formats_title: "Excel・CSV・JSON",
  feature_formats_body:
    "集計シート付きの整形済み.xlsx、取り込み用のCSV、独自処理向けのJSONを出力。お使いの会計ソフトもきっと喜びます。",

  how_title: "使い方",
  how_step1: "1. 明細PDFをアップロード",
  how_step2: "2. 取引テーブルを自動で検出",
  how_step3: "3. きれいな表をダウンロード",

  convert_title: "明細を変換",
  convert_drop: "ここにPDFをドロップ、またはクリックして選択",
  convert_drop_hint: "テキスト形式の明細のみ対応（スキャン画像は先にOCRが必要です）。",
  convert_format: "出力形式",
  convert_currency: "通貨",
  convert_button: "変換",
  convert_processing: "処理中…",
  convert_download: "ダウンロード",
  convert_error_generic:
    "そのファイルから取引を読み取れませんでした。画像のみ、または特殊なレイアウトの可能性があります。",
  convert_error_insufficient:
    "含まれるページ数とクレジットを使い切りました。続けるにはクレジットパックをご購入ください。",
  convert_results_title: "プレビュー",
  col_date: "日付",
  col_description: "摘要",
  col_amount: "金額",
  col_balance: "残高",
  summary_count: "取引件数",
  summary_debit: "借方合計",
  summary_credit: "貸方合計",
  summary_net: "差引",

  pricing_title: "ビジネス向けの料金",
  pricing_subtitle:
    "安定した利用には月額プラン、たまに変換する方には前払いクレジットを。",
  pricing_plans_title: "月額プラン",
  pricing_credits_title: "前払いクレジットパック",
  pricing_per_month: "/月",
  pricing_included_pages: "ページ/月 込み",
  pricing_overage: "追加1ページあたり",
  pricing_buy: "購入",
  pricing_choose_plan: "プランを選ぶ",
  pricing_credits_each: "1クレジットあたり",
  pricing_credit_explainer: "1クレジットで明細1ページを変換。クレジットに有効期限はありません。",

  account_title: "アカウント",
  account_plan: "プラン",
  account_credits: "クレジット",
  account_included_remaining: "今期の残り込みページ数",
  account_buy_credits: "クレジットを購入",

  footer_tagline: "銀行明細PDFから表へ、最速の方法。",
  footer_rights: "無断転載を禁じます。",
};
