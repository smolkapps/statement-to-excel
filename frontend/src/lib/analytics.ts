// The page's existing Umami script owns analytics. Never send file names,
// statement content, account ids, payment ids, or additional event names.
export type AnalyticsEvent =
  | "file-selected"
  | "convert-success"
  | "convert-error"
  | "upgrade-click"
  | "checkout-opened";

declare global {
  interface Window {
    umami?: { track: (event: AnalyticsEvent) => void };
  }
}

export function track(event: AnalyticsEvent): void {
  try {
    window.umami?.track(event);
  } catch {
    // Analytics must never interrupt conversion or checkout.
  }
}
