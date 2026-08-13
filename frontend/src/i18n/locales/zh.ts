import type { Translation } from "../types";

export const zh: Translation = {
  locale_name: "中文",
  nav_product: "产品",
  nav_pricing: "价格",
  nav_convert: "转换",

  hero_eyebrow: "银行对账单转换器",
  hero_title: "几秒钟，把银行对账单 PDF 变成干净的 Excel",
  hero_subtitle:
    "会计、记账与财务团队：不必再手工录入交易。上传一份对账单 PDF，即可得到整洁、精确的表格，包含每一笔的日期、摘要、金额和余额。",
  hero_cta: "转换对账单",
  hero_secondary_cta: "查看价格",
  hero_trust:
    "仅支持文本型 PDF；扫描件需要先进行 OCR。金额保持精确，不做四舍五入。",

  feature_accuracy_title: "精确，而非近似",
  feature_accuracy_body:
    "金额按精确小数解析——括号、尾部负号、DR/CR 标记和千位分隔符均可处理。借方与贷方保留正确的正负号。",
  feature_private_title: "无需第三方 AI",
  feature_private_body:
    "转换器无需将对账单发送给第三方 AI API，即可提取交易日期、说明、金额和余额。",
  feature_formats_title: "Excel、CSV 或 JSON",
  feature_formats_body:
    "可获得带汇总表的格式化 .xlsx、便于导入的纯 CSV，或供您自有流程使用的 JSON。您的会计软件会更省心。",

  how_title: "使用方法",
  how_step1: "1. 上传您的对账单 PDF",
  how_step2: "2. 我们自动识别交易表格",
  how_step3: "3. 下载干净的表格",

  convert_title: "转换对账单",
  convert_drop: "将 PDF 拖到此处，或点击选择",
  convert_drop_hint: "仅支持文本型对账单（扫描图片需先进行 OCR）。",
  convert_format: "输出格式",
  convert_currency: "货币",
  convert_button: "转换",
  convert_processing: "处理中…",
  convert_download: "下载",
  convert_error_generic:
    "无法从该文件读取交易。它可能仅为图片，或版式异常。",
  convert_error_insufficient:
    "您的免费页数和点数已用完。请购买点数包以继续。",
  convert_results_title: "预览",
  col_date: "日期",
  col_description: "摘要",
  col_amount: "金额",
  col_balance: "余额",
  summary_count: "交易笔数",
  summary_debit: "借方合计",
  summary_credit: "贷方合计",
  summary_net: "净额",

  pricing_title: "为企业打造的价格",
  pricing_subtitle:
    "稳定用量可选固定月付套餐；偶尔转换则可选预付点数。",
  pricing_plans_title: "月付套餐",
  pricing_credits_title: "预付点数包",
  pricing_per_month: "/月",
  pricing_included_pages: "页 / 月（含）",
  pricing_overage: "每多一页",
  pricing_buy: "购买",
  pricing_choose_plan: "选择套餐",
  pricing_credits_each: "每点数",
  pricing_credit_explainer: "1 点数可转换 1 页对账单。点数永不过期。",

  account_title: "您的账户",
  account_plan: "套餐",
  account_credits: "点数",
  account_included_remaining: "本周期剩余含页数",
  account_buy_credits: "购买点数",

  footer_tagline: "从银行对账单 PDF 到表格，最快的方式。",
  footer_rights: "保留所有权利。",
};
