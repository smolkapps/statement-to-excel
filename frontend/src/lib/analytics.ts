// The page's existing Umami script owns analytics. Never send file names,
// statement content, account ids, payment ids, or additional event names.
export type AnalyticsEvent =
  | "file-selected"
  | "convert-success"
  | "convert-error"
  | "upgrade-click"
  | "checkout-opened";

export type ConversionLayout = "deposit_table" | "deposit_lines" | "card_table" | "card_lines" | "unknown";
export interface ConversionAnalyticsProperties {
  balanced: "yes" | "no" | "unknown";
  layout: ConversionLayout;
}

export function conversionLayout(value: unknown): ConversionLayout {
  return typeof value === "string" && ["deposit_table", "deposit_lines", "card_table", "card_lines"].includes(value)
    ? value as ConversionLayout : "unknown";
}

declare global {
  interface Window {
    umami?: { track: (event: AnalyticsEvent, properties?: ConversionAnalyticsProperties) => void };
  }
}

export function track(event: "convert-success", properties: ConversionAnalyticsProperties): void;
export function track(event: Exclude<AnalyticsEvent, "convert-success">): void;
export function track(event: AnalyticsEvent, properties?: { balanced: unknown; layout: unknown }): void {
  try {
    if (event === "convert-success") {
      // Build a fresh allowlisted object. Even an accidental caller passing
      // an entire conversion response cannot disclose statement data.
      const balanced = properties?.balanced === "yes" || properties?.balanced === "no"
        ? properties.balanced : "unknown";
      const layout = conversionLayout(properties?.layout);
      window.umami?.track(event, { balanced, layout });
    } else if (["file-selected", "convert-error", "upgrade-click", "checkout-opened"].includes(event)) {
      window.umami?.track(event);
    }
  } catch {
    // Analytics must never interrupt conversion or checkout.
  }
}
