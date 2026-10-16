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
  hero_trust: "不存储任何对账单数据。您的 PDF 会上传到我们的服务器进行转换，并在转换后立即删除。",

  feature_accuracy_title: "精确，而非近似",
  feature_accuracy_body:
    "金额按精确小数解析——括号、尾部负号、DR/CR 标记和千位分隔符均可处理。借方与贷方保留正确的正负号。",
  feature_private_title: "不存储对账单数据",
  feature_private_body: "对账单在内存中处理，并在转换后立即删除。您的对账单绝不会发送给第三方 AI API。",
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
  convert_error_timeout:
    "转换耗时过长。请使用较小的对账单重试，或将其拆分为页数更少的文件。",
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
  reconciliation_balanced_deposit: "已核对：期初余额 {opening} + 收入 {money_in} − 支出 {money_out} = 期末余额 {closing}，与您的对账单一致。",
  reconciliation_balanced_card: "已核对：上期余额 {previous} − 还款及退款 {payments_credits} + 消费 {purchases} + 费用 {fees} + 利息 {interest} = 本期余额 {new}，与您的对账单一致。",
  reconciliation_not_balanced: "金额不符：相差 {difference}。请检查突出显示的交易行。",
  reconciliation_cannot_check: "无法核对：未找到此对账单的合计金额。使用前请自行核对数字。",
  row_flag_year_inferred_rollover: "年份根据跨越十二月至一月的账期推断。",
  row_flag_sign_from_balance: "金额正负号根据余额变化推断。",
  row_flag_multiline_description: "摘要由多行文字合并而成。",

  pricing_title: "为企业打造的价格",
  pricing_subtitle:
    "稳定用量可选固定月付套餐；偶尔转换则可选预付点数。",
  pricing_plans_title: "月付套餐",
  pricing_credits_title: "预付点数包",
  pricing_per_month: "/月",
  pricing_included_pages: "页 / 月（含）",
  pricing_overage: "超出包含页数后：每页使用 1 个预付积分。",
  pricing_buy: "购买",
  pricing_choose_plan: "选择套餐",
  pricing_credits_each: "每点数",
  pricing_credit_explainer: "1 点数可转换 1 页对账单。点数永不过期。",

  billing_test_mode: "Stripe 测试模式 — 不会实际付款。",
  billing_manage: "管理订阅和付款方式",
  billing_recovery: "付款归属于此浏览器保存的账户。清除浏览器存储或更换设备将失去访问权限。没有登录或自动恢复功能；如需核对付款，请联系网站所有者。",
  billing_storage_error: "付款前请启用浏览器持久存储。我们无法安全保存您的账户。",
  billing_hold: "付款和转换已暂停，等待付款核对。请联系网站所有者。",
  privacy_title: "隐私与付款",
  privacy_billing: "我们保留匿名浏览器账户、使用量、付款引用和购买幂等记录，以提供付费访问并防止重复发放。转换重试指纹在24小时后过期，并在下一次转换请求时删除。结账和付款管理由Stripe提供。付款记录绝不包含对账单内容。",
  privacy_analytics: "我们使用Umami以及已配置时的Cloudflare Web Analytics衡量匿名使用情况。可选的Google Analytics仅在您允许后使用匿名浏览器标识。这些服务仅接收去除敏感信息的页面信息和有限的使用事件，绝不接收您的PDF、文件名、交易或付款及账户令牌。您可以随时在此更改Google选择。",
  analytics_choice: "可选分析设置",
  analytics_consent: "是否允许可选的Google Analytics帮助我们了解网站使用情况？无论选择哪项，转换和付款均可使用。",
  analytics_allow: "允许Google Analytics",
  analytics_decline: "拒绝Google Analytics",
  checkout_error: "无法打开付款页面，请重试。",

  account_title: "您的账户",
  account_plan: "套餐",
  account_credits: "点数",
  account_included_remaining: "本周期剩余含页数",
  account_buy_credits: "购买点数",

  footer_tagline: "从银行对账单 PDF 到表格，最快的方式。",
  footer_rights: "保留所有权利。",
};
