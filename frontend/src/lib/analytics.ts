import { analyticsReady, ownerQA } from './privacy';

export type AnalyticsEvent = 'file-selected' | 'convert-success' | 'convert-error' | 'upgrade-click' | 'checkout-opened';
export type ConversionLayout = 'deposit_table' | 'deposit_lines' | 'card_table' | 'card_lines' | 'unknown';
export interface ConversionAnalyticsProperties { balanced: 'yes' | 'no' | 'unknown'; layout: ConversionLayout }
const EVENTS = ['file-selected', 'convert-success', 'convert-error', 'upgrade-click', 'checkout-opened'];
const WEBSITE = '0ee0e19b-b29b-4c98-b3f6-a92a43b4ba5a';
const PAGE = 'https://statement-to-excel.apps.smolkin.org/';
const TITLE = 'Statement to Excel';
export const GOOGLE_CONSENT_KEY = 'stx_google_consent';
let started = false;
let googleId = '';
let googleAllowed = false;
let googleStarted = false;

declare global {
  interface Window {
    umami?: { track: (event?: AnalyticsEvent, properties?: ConversionAnalyticsProperties) => void };
    stxBeforeSend?: (type: string, payload: Record<string, unknown>) => Record<string, unknown> | false;
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
export function googleConsent(): boolean | null {
  try { const saved = localStorage.getItem(GOOGLE_CONSENT_KEY); return saved === 'yes' ? true : saved === 'no' ? false : null; }
  catch { return null; }
}
export function googleConfigured(): boolean { return /^G-[A-Z0-9]{5,20}$/.test(import.meta.env.VITE_GA_MEASUREMENT_ID ?? ''); }
function googleLoad() {
  if (!googleAllowed || !googleId || ownerQA() || !analyticsReady()) return;
  (window as unknown as Record<string, unknown>)[`ga-disable-${googleId}`] = false;
  if (googleStarted) {
    window.gtag?.('consent', 'update', { analytics_storage: 'granted', ad_storage: 'denied', ad_user_data: 'denied', ad_personalization: 'denied' });
    return;
  }
  googleStarted = true;
  window.dataLayer = window.dataLayer || [];
  window.gtag = function () { window.dataLayer!.push(arguments); };
  window.gtag('consent', 'default', { analytics_storage: 'granted', ad_storage: 'denied', ad_user_data: 'denied', ad_personalization: 'denied' });
  window.gtag('js', new Date());
  window.gtag('set', 'ads_data_redaction', true);
  window.gtag('config', googleId, { send_page_view: false, allow_google_signals: false, allow_ad_personalization_signals: false,
    ...safeGooglePage() });
  const script = document.createElement('script');
  script.id = 'stx-google'; script.async = true; script.referrerPolicy = 'no-referrer';
  script.src = `https://www.googletagmanager.com/gtag/js?id=${googleId}`;
  document.head.appendChild(script);
  window.gtag('event', 'page_view', safeGooglePage());
}
export function setGoogleConsent(allowed: boolean): void {
  try { localStorage.setItem(GOOGLE_CONSENT_KEY, allowed ? 'yes' : 'no'); } catch { /* session-only choice */ }
  googleAllowed = allowed;
  if (allowed) { try { googleLoad(); } catch { /* analytics cannot affect payment/conversion */ } }
  else {
    if (googleId) (window as unknown as Record<string, unknown>)[`ga-disable-${googleId}`] = true;
    try { window.gtag?.('consent', 'update', { analytics_storage: 'denied', ad_storage: 'denied', ad_user_data: 'denied', ad_personalization: 'denied' }); } catch { /* optional */ }
    // Remove this site's Google cookies, including common parent-domain scope.
    try { for (const cookie of document.cookie.split(';')) {
      const name = cookie.split('=')[0].trim();
      if (!/^_ga(?:_|$)/.test(name)) continue;
      document.cookie = `${name}=; Max-Age=0; Path=/`;
      const parts = location.hostname.split('.');
      for (let i = 0; i < parts.length - 1; i++) document.cookie = `${name}=; Max-Age=0; Path=/; Domain=.${parts.slice(i).join('.')}`;
    } } catch { /* cookie access can be blocked */ }
  }
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
  googleAllowed = googleConsent() === true;
  googleLoad();
  window.addEventListener('storage', (event) => {
    if (event.key === GOOGLE_CONSENT_KEY) setGoogleConsent(event.newValue === 'yes');
  });
  const token = import.meta.env.VITE_CF_WEB_ANALYTICS_TOKEN ?? '';
  if (/^[a-f0-9]{32}$/i.test(token) && window.stxPrivacy && !window.stxPrivacy.sensitiveEntry) {
    const script = document.createElement('script');
    script.id = 'stx-cloudflare'; script.async = true; script.referrerPolicy = 'no-referrer';
    script.type = 'module';
    script.src = 'https://static.cloudflareinsights.com/beacon.min.js';
    script.setAttribute('data-cf-beacon', JSON.stringify({ token, spa: false }));
    document.head.appendChild(script);
  }
}

export function track(event: 'convert-success', input: ConversionAnalyticsProperties): void;
export function track(event: Exclude<AnalyticsEvent, 'convert-success'>): void;
export function track(event: AnalyticsEvent, input?: { balanced: unknown; layout: unknown }): void {
  if (ownerQA() || !EVENTS.includes(event)) return;
  const data = event === 'convert-success' ? properties(input) : undefined;
  try { if (data) window.umami?.track(event, data); else window.umami?.track(event); } catch { /* optional */ }
  try { if (googleAllowed && googleStarted) window.gtag?.('event', event, { ...safeGooglePage(), ...(data ?? {}) }); } catch { /* optional */ }
}
