import { analyticsReady, ownerQA } from './privacy';

export type AnalyticsEvent = 'file-selected' | 'convert-success' | 'convert-error' | 'upgrade-click' | 'checkout-opened';
export type ConversionLayout = 'deposit_table' | 'deposit_lines' | 'card_table' | 'card_lines' | 'unknown';
export interface ConversionAnalyticsProperties { balanced: 'yes' | 'no' | 'unknown'; layout: ConversionLayout }
const EVENTS = ['file-selected', 'convert-success', 'convert-error', 'upgrade-click', 'checkout-opened'];
const WEBSITE = '0ee0e19b-b29b-4c98-b3f6-a92a43b4ba5a';
const PAGE = 'https://statement-to-excel.apps.smolkin.org/';
const TITLE = 'Statement to Excel';
export const ANALYTICS_CONSENT_KEY = 'stx_optional_analytics_v1';
const DENIED_SESSION_KEY = 'stx_optional_analytics_denied';
const COOKIE_PREFIX = 'stx';
const GOOGLE_EVENTS: Record<AnalyticsEvent, string> = {
  'file-selected': 'file_selected', 'convert-success': 'convert_success', 'convert-error': 'convert_error',
  'upgrade-click': 'upgrade_click', 'checkout-opened': 'checkout_opened',
};
let started = false;
let googleId = '';
let googleAllowed = false;
let googleStarted = false;
let googleRetired = false;
let googleFrame: HTMLIFrameElement | undefined;
let cloudflareStarted = false;
let cloudflareRetired = false;
let currentChoice: boolean | null | undefined;
export interface ConsentResult { allowed: boolean | null; saved: boolean; nextVisit: boolean }

declare global {
  interface Window {
    umami?: { track: (event?: AnalyticsEvent, properties?: ConversionAnalyticsProperties) => void };
    stxBeforeSend?: (type: string, payload: Record<string, unknown>) => Record<string, unknown> | false;
    stxGoogleFrame?: { start: (id: string) => void; event: (name: string, data: Record<string, unknown>) => void; stop: () => void };
    __cfBeacon?: { token: string; spa: boolean };
    dataLayer?: unknown[];
    gtag?: (...args: unknown[]) => void;
  }
}

export function conversionLayout(value: unknown): ConversionLayout {
  return typeof value === 'string' && ['deposit_table', 'deposit_lines', 'card_table', 'card_lines'].includes(value) ? value as ConversionLayout : 'unknown';
}
function properties(input?: { balanced?: unknown; layout?: unknown }): ConversionAnalyticsProperties {
  return { balanced: input?.balanced === 'yes' || input?.balanced === 'no' ? input.balanced : 'unknown', layout: conversionLayout(input?.layout) };
}

/** Fresh payload, including pageviews: never forward arbitrary SDK/caller fields. */
export function sanitizedUmami(type: string, input: Record<string, unknown>): Record<string, unknown> | false {
  if (ownerQA() || type !== 'event' || input.name !== undefined && !EVENTS.includes(String(input.name))) return false;
  const payload: Record<string, unknown> = { website: WEBSITE, hostname: new URL(PAGE).hostname,
    url: PAGE, title: TITLE, referrer: '', language: 'en' };
  if (typeof input.screen === 'string' && /^\d{1,5}x\d{1,5}$/.test(input.screen)) payload.screen = input.screen;
  if (input.name !== undefined) {
    payload.name = input.name;
    if (input.name === 'convert-success') payload.data = properties(input.data as ConversionAnalyticsProperties);
  }
  return payload;
}

function safeGooglePage() { return { page_location: PAGE, page_title: TITLE, page_referrer: '' }; }
export function analyticsConsent(): boolean | null {
  if (currentChoice !== undefined) return currentChoice;
  try {
    if (sessionStorage.getItem(DENIED_SESSION_KEY) === 'yes') return false;
    const saved = localStorage.getItem(ANALYTICS_CONSENT_KEY);
    // Old Google-only acceptance deliberately does not authorize Cloudflare.
    return saved === 'yes' ? true : saved === 'no' ? false : null;
  } catch { return null; }
}
export function googleConfigured(): boolean { return /^G-[A-Z0-9]{5,20}$/.test(import.meta.env.VITE_GA_MEASUREMENT_ID ?? ''); }
export function optionalAnalyticsConfigured(): boolean {
  return googleConfigured() || /^[a-f0-9]{32}$/i.test(import.meta.env.VITE_CF_WEB_ANALYTICS_TOKEN ?? '');
}
function optionalReady(): boolean {
  return analyticsReady() && !!window.stxPrivacy && !window.stxPrivacy.sensitiveEntry && !ownerQA();
}
function googleLoad() {
  if (!googleAllowed || !googleId || googleRetired || !optionalReady() || googleStarted) return;
  googleStarted = true;
  (window as unknown as Record<string, unknown>)[`ga-disable-${googleId}`] = false;
  const pending: [string, Record<string, unknown>][] = [];
  let ready = false;
  window.dataLayer = [];
  window.gtag = (...args) => {
    if (!googleAllowed || googleRetired || args[0] !== 'event') return;
    const name = String(args[1]);
    if (name !== 'page_view' && !Object.values(GOOGLE_EVENTS).includes(name)) return;
    const data = { ...safeGooglePage(), ...(name === 'convert_success' ? properties(args[2] as ConversionAnalyticsProperties) : {}) };
    window.dataLayer!.push(['event', name, data]);
    if (ready) googleFrame?.contentWindow?.stxGoogleFrame?.event(name, data);
    else pending.push([name, data]);
  };
  const frame = document.createElement('iframe');
  frame.id = 'stx-google'; frame.hidden = true; frame.title = 'Optional analytics';
  frame.setAttribute('sandbox', 'allow-scripts allow-same-origin');
  frame.referrerPolicy = 'no-referrer'; frame.src = '/google-frame.html';
  frame.onload = () => {
    if (!googleAllowed || googleRetired || googleFrame !== frame || !optionalReady()) return;
    const sdk = frame.contentWindow?.stxGoogleFrame;
    if (!sdk) return;
    sdk.start(googleId);
    ready = true;
    for (const [name, data] of pending.splice(0)) sdk.event(name, data);
  };
  googleFrame = frame;
  document.head.appendChild(frame);
  window.gtag('event', 'page_view', safeGooglePage());
}
function stopOptionalAnalytics(): void {
  googleAllowed = false;
  if (googleStarted) googleRetired = true;
  // ga-disable does not stop Google's diagnostic timers. Stop the frame's exit
  // handlers synchronously, then dispose its entire SDK context before storage.
  try { googleFrame?.contentWindow?.stxGoogleFrame?.stop(); } catch { /* optional blocked frame */ }
  googleFrame?.remove(); googleFrame = undefined; googleStarted = false;
  if (googleId) (window as unknown as Record<string, unknown>)[`ga-disable-${googleId}`] = true;
  // Tested CF 2026.10.1 checks this guard at every send, including visibility.
  // SRI pins those semantics. Retire its observers for this document lifetime.
  if (cloudflareStarted) cloudflareRetired = true;
  // The accessor below remains installed so a late SDK response cannot
  // recreate the beacon after withdrawal.
  document.getElementById('stx-cloudflare')?.remove();
  try { for (const cookie of document.cookie.split(';')) {
    const name = cookie.split('=')[0].trim();
    if (name === `${COOKIE_PREFIX}_ga` || name === `${COOKIE_PREFIX}_ga_${googleId.slice(2)}`)
      document.cookie = `${name}=; Max-Age=0; Path=/; SameSite=Lax; Secure`;
  } } catch { /* blocked cookies */ }
}
function cloudflareLoad(): void {
  const token = import.meta.env.VITE_CF_WEB_ANALYTICS_TOKEN ?? '';
  if (!googleAllowed || !optionalReady() || cloudflareStarted || cloudflareRetired || !/^[a-f0-9]{32}$/i.test(token)) return;
  let beacon: Window['__cfBeacon'];
  Object.defineProperty(window, '__cfBeacon', { configurable: true,
    get: () => googleAllowed && !cloudflareRetired ? beacon : undefined,
    set: (value: Window['__cfBeacon']) => { if (googleAllowed && !cloudflareRetired) beacon = value; },
  });
  cloudflareStarted = true;
  const script = document.createElement('script');
  script.id = 'stx-cloudflare'; script.async = true; script.referrerPolicy = 'no-referrer';
  script.type = 'module'; script.crossOrigin = 'anonymous';
  script.integrity = 'sha384-DSBfgE0somecFTMgit0M4sNXN8O0JQ/LGM3DGGPVvgXIPZvW+H1zSYjc6O83LLBv';
  script.src = 'https://static.cloudflareinsights.com/beacon.min.js';
  script.setAttribute('data-cf-beacon', JSON.stringify({ token, spa: false }));
  // Set before loading: a revoke during download clears it, and the pinned SDK
  // will not initialize from a removed descriptor when execution arrives late.
  window.__cfBeacon = { token, spa: false };
  document.head.appendChild(script);
}
function loadOptionalAnalytics(): void {
  try { googleLoad(); cloudflareLoad(); } catch { /* never affect conversion/payment */ }
}
export function setAnalyticsConsent(allowed: boolean): ConsentResult {
  // Stop before fallible persistence; stale acceptance must not keep collecting.
  if (!allowed) stopOptionalAnalytics();
  currentChoice = false;
  let saved = false;
  try {
    localStorage.setItem(ANALYTICS_CONSENT_KEY, allowed ? 'yes' : 'no');
    saved = localStorage.getItem(ANALYTICS_CONSENT_KEY) === (allowed ? 'yes' : 'no');
  } catch { /* readback below remains fail closed */ }
  if (!saved && !allowed) {
    try {
      localStorage.removeItem(ANALYTICS_CONSENT_KEY);
      saved = localStorage.getItem(ANALYTICS_CONSENT_KEY) === null;
    } catch { /* UI must report this denial could not be saved */ }
  }
  try {
    if (allowed && saved) {
      sessionStorage.removeItem(DENIED_SESSION_KEY);
      saved = sessionStorage.getItem(DENIED_SESSION_KEY) === null;
    } else sessionStorage.setItem(DENIED_SESSION_KEY, 'yes');
  } catch {
    if (allowed) saved = false;
    // No automatic reload into a possibly stale acceptance.
  }
  currentChoice = allowed && saved;
  googleAllowed = currentChoice;
  if (googleAllowed) loadOptionalAnalytics();
  else stopOptionalAnalytics();
  const result = { allowed: currentChoice, saved, nextVisit: googleAllowed && (cloudflareRetired || googleRetired) };
  window.dispatchEvent(new CustomEvent('stx-analytics-choice', { detail: result }));
  return result;
}

/** Called once after bootstrap; unset provider IDs make no provider requests. */
export function initializeAnalytics(): void {
  if (started || ownerQA() || !analyticsReady()) return;
  started = true;
  window.stxBeforeSend = sanitizedUmami;
  const descriptor = document.getElementById('stx-umami');
  if (descriptor?.getAttribute('data-src')) {
    const script = document.createElement('script');
    script.id = 'stx-umami'; script.async = true; script.referrerPolicy = 'no-referrer';
    script.src = descriptor.getAttribute('data-src')!;
    script.setAttribute('data-website-id', WEBSITE);
    script.setAttribute('data-auto-track', 'false');
    script.setAttribute('data-exclude-search', 'true'); script.setAttribute('data-exclude-hash', 'true');
    script.setAttribute('data-before-send', 'stxBeforeSend');
    script.onload = () => { try { if (!ownerQA()) window.umami?.track(); } catch { /* optional */ } };
    descriptor.replaceWith(script);
  }
  googleId = googleConfigured() ? import.meta.env.VITE_GA_MEASUREMENT_ID! : '';
  googleAllowed = analyticsConsent() === true;
  loadOptionalAnalytics();
  window.addEventListener('storage', (event) => {
    if (event.key === ANALYTICS_CONSENT_KEY || event.key === null) {
      // A clear/revocation in another tab takes effect immediately. Do not
      // rewrite storage from a storage event or revive a retired CF instance.
      if (event.key === null || event.newValue !== 'yes') {
        currentChoice = false;
        stopOptionalAnalytics();
      } else {
        currentChoice = undefined;
        googleAllowed = analyticsConsent() === true;
        if (googleAllowed) loadOptionalAnalytics();
      }
      window.dispatchEvent(new CustomEvent('stx-analytics-choice'));
    }
  });
}

export function track(event: 'convert-success', input: ConversionAnalyticsProperties): void;
export function track(event: Exclude<AnalyticsEvent, 'convert-success'>): void;
export function track(event: AnalyticsEvent, input?: { balanced: unknown; layout: unknown }): void {
  if (ownerQA() || !EVENTS.includes(event)) return;
  const data = event === 'convert-success' ? properties(input) : undefined;
  try { if (data) window.umami?.track(event, data); else window.umami?.track(event); } catch { /* optional */ }
  try { if (googleAllowed && googleStarted) window.gtag?.('event', GOOGLE_EVENTS[event], { ...safeGooglePage(), ...(data ?? {}) }); } catch { /* optional */ }
}
