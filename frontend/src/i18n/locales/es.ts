import type { Translation } from "../types";

export const es: Translation = {
  locale_name: "Español",
  nav_product: "Producto",
  nav_pricing: "Precios",
  nav_convert: "Convertir",

  hero_eyebrow: "Conversor de extractos bancarios",
  hero_title: "Convierte extractos bancarios en PDF a Excel limpio, en segundos",
  hero_subtitle:
    "Contables, gestores y equipos financieros: dejen de teclear transacciones a mano. Suelten un PDF del extracto y obtengan una hoja de cálculo ordenada y exacta con cada fecha, concepto, importe y saldo.",
  hero_cta: "Convertir un extracto",
  hero_secondary_cta: "Ver precios",
  hero_trust:
    "Solo PDF con texto; los extractos escaneados necesitan OCR. Decimales exactos, sin redondeos.",

  feature_accuracy_title: "Exacto, no aproximado",
  feature_accuracy_body:
    "Los importes se analizan como decimales exactos: paréntesis, signo menos al final, marcas DR/CR y separadores de miles, todo gestionado. Los cargos y abonos conservan su signo correcto.",
  feature_private_title: "No requiere IA de terceros",
  feature_private_body:
    "El conversor extrae fechas, descripciones, importes y saldos sin enviar tu extracto a una API de IA de terceros.",
  feature_formats_title: "Excel, CSV o JSON",
  feature_formats_body:
    "Obtén un .xlsx con formato y una hoja de resumen, un CSV simple para importaciones o JSON para tu propio flujo. Tu software contable lo agradecerá.",

  how_title: "Cómo funciona",
  how_step1: "1. Sube el PDF de tu extracto",
  how_step2: "2. Detectamos la tabla de transacciones automáticamente",
  how_step3: "3. Descarga una hoja de cálculo limpia",

  convert_title: "Convertir un extracto",
  convert_drop: "Suelta un PDF aquí o haz clic para elegir",
  convert_drop_hint: "Solo extractos en texto (las imágenes escaneadas requieren OCR primero).",
  convert_format: "Formato de salida",
  convert_currency: "Moneda",
  convert_button: "Convertir",
  convert_processing: "Procesando…",
  convert_download: "Descargar",
  convert_error_generic:
    "No pudimos leer transacciones de ese archivo. Puede ser solo imagen o tener un formato inusual.",
  convert_error_insufficient:
    "Te has quedado sin páginas incluidas ni créditos. Compra un paquete de créditos para continuar.",
  convert_results_title: "Vista previa",
  col_date: "Fecha",
  col_description: "Concepto",
  col_amount: "Importe",
  col_balance: "Saldo",
  summary_count: "Transacciones",
  summary_debit: "Total cargos",
  summary_credit: "Total abonos",
  summary_net: "Neto",

  pricing_title: "Precios pensados para empresas",
  pricing_subtitle:
    "Planes mensuales fijos para volumen constante, o créditos prepago cuando solo conviertes de vez en cuando.",
  pricing_plans_title: "Planes mensuales",
  pricing_credits_title: "Paquetes de créditos prepago",
  pricing_per_month: "/mes",
  pricing_included_pages: "páginas / mes incluidas",
  pricing_overage: "por página extra",
  pricing_buy: "Comprar",
  pricing_choose_plan: "Elegir plan",
  pricing_credits_each: "por crédito",
  pricing_credit_explainer: "1 crédito convierte 1 página de extracto. Los créditos no caducan.",

  account_title: "Tu cuenta",
  account_plan: "Plan",
  account_credits: "Créditos",
  account_included_remaining: "Páginas incluidas restantes este ciclo",
  account_buy_credits: "Comprar créditos",

  footer_tagline: "La forma más rápida de pasar de un extracto en PDF a una hoja de cálculo.",
  footer_rights: "Todos los derechos reservados.",
};
