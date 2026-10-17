import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const CANARY = 'canarySecretPDFRowAccountPayment';
async function fresh(configured = true) {
  vi.resetModules();
  vi.stubEnv('VITE_GA_MEASUREMENT_ID', configured ? 'G-SYNTHETIC1' : '');
  vi.stubEnv('VITE_CF_WEB_ANALYTICS_TOKEN', configured ? '0123456789abcdef0123456789abcdef' : '');
  return import('./analytics');
}
function commands() { return (window.dataLayer ?? []).map((x) => Array.from(x as ArrayLike<unknown>)); }

describe('provider loading and serialized privacy contracts (synthetic configuration)', () => {
  beforeEach(() => { history.replaceState(null, '', '/'); Object.defineProperty(window, 'stxPrivacy', { configurable: true, value: { qa: false, sensitiveEntry: false, takeReturn: () => ({ returning: false, sessionId: null }) } }); localStorage.clear(); sessionStorage.clear(); vi.stubGlobal('fetch', vi.fn(() => new Promise(() => {})));  delete window.__cfBeacon; document.head.innerHTML = ''; delete window.dataLayer; delete window.gtag; delete window.umami; });
  afterEach(() => { delete window.stxPrivacy; vi.unstubAllEnvs(); vi.unstubAllGlobals(); vi.restoreAllMocks(); });
  it('does not load unset providers or request Google before optional consent', async () => {
    const a = await fresh(false); a.initializeAnalytics(); a.setAnalyticsConsent(true);
    expect(document.querySelectorAll('script')).toHaveLength(0);
    localStorage.clear();
    const b = await fresh(); b.initializeAnalytics();
    expect(document.querySelector('#stx-google')).toBeNull();
    b.setAnalyticsConsent(false);
    expect(document.querySelector('#stx-google')).toBeNull();
  });
  it('serializes only sanitized manual Google page/funnel data and handles revoke/reallow', async () => {
    const a = await fresh(); a.initializeAnalytics(); a.setAnalyticsConsent(true);
    // Synthetic identifier; script is never fetched in jsdom.
    expect(document.querySelector('#stx-google')).not.toBeNull();
    a.track('convert-success', { balanced: 'yes', layout: 'card_table', filename: CANARY, amount: CANARY, account: CANARY } as never);
    const serialized = JSON.stringify(commands());
    expect(serialized).not.toContain(CANARY);
    expect(serialized).toContain('"page_location":"https://statement-to-excel.apps.smolkin.org/"');
    a.setAnalyticsConsent(false);
    const before = commands().length;
    a.track('checkout-opened');
    expect(commands()).toHaveLength(before);
    expect((window as unknown as Record<string, unknown>)['ga-disable-G-SYNTHETIC1']).toBe(true);
    a.setAnalyticsConsent(true);
    expect(a.setAnalyticsConsent(true).nextVisit).toBe(true);
    expect(document.querySelectorAll('#stx-google')).toHaveLength(0);
  });
  it('serializes fresh Umami network bodies without SDK page, referrer, id or extra fields', async () => {
    const a = await fresh();
    const send = vi.fn();
    const sdkPayload = { website: CANARY, url: `https://example.org/?account=${CANARY}#${CANARY}`, title: CANARY, referrer: CANARY, id: CANARY, filename: CANARY };
    window.umami = { track: (name, data) => send(JSON.stringify({ type: 'event', payload: a.sanitizedUmami('event', { ...sdkPayload, name, data }) })) };
    a.track('convert-success', { balanced: 'no', layout: 'deposit_table', filename: CANARY } as never);
    const parsed = JSON.parse(send.mock.calls[0][0]);
    expect(send.mock.calls[0][0]).not.toContain(CANARY);
    expect(parsed.payload.data).toEqual({ balanced: 'no', layout: 'deposit_table' });
    expect(a.sanitizedUmami('identify', sdkPayload)).toBe(false);
    expect(a.sanitizedUmami('event', { name: CANARY })).toBe(false);
  });
  it('fails closed for trackers when bootstrap is missing, retaining conversion independence', async () => {
    delete window.stxPrivacy;
    history.replaceState(null, '', '/?session_id=cs_test_canary#private');
    const a = await fresh(); a.initializeAnalytics(); a.setAnalyticsConsent(true);
    expect(document.querySelectorAll('script')).toHaveLength(0);
  });
  it('owner QA prevents every provider load and event fanout', async () => {
    localStorage.setItem('stx_owner_qa', 'on');
    const a = await fresh(); const send = vi.fn(); window.umami = { track: send };
    a.initializeAnalytics(); a.setAnalyticsConsent(true); a.track('file-selected');
    expect(document.querySelectorAll('script')).toHaveLength(0);
    expect(send).not.toHaveBeenCalled();
  });
  it('throwing tracker cannot prevent a reversible local consent choice', async () => {
    const a = await fresh(); a.initializeAnalytics(); a.setAnalyticsConsent(true);
    window.gtag = () => { throw new Error('blocked'); };
    expect(() => a.setAnalyticsConsent(false)).not.toThrow();
    expect(a.analyticsConsent()).toBe(false);
  });
  it.each([
    ['file-selected', 'file_selected'], ['convert-success', 'convert_success'], ['convert-error', 'convert_error'],
    ['upgrade-click', 'upgrade_click'], ['checkout-opened', 'checkout_opened'],
  ])('preserves Umami %s and maps Google to %s', async (umami, google) => {
    const a = await fresh(); a.initializeAnalytics(); a.setAnalyticsConsent(true);
    const send = vi.fn(); window.umami = { track: send };
    a.track(umami as 'convert-success', { balanced: 'no', layout: 'card_table' });
    expect(send.mock.calls[0][0]).toBe(umami);
    expect(commands().at(-1)?.slice(0, 2)).toEqual(['event', google]);
  });
  it('keeps both optional providers off for legacy Google-only acceptance and saved denial', async () => {
    localStorage.setItem('stx_google_consent', 'yes');
    const a = await fresh(); a.initializeAnalytics();
    expect(document.querySelectorAll('script')).toHaveLength(0);
    a.setAnalyticsConsent(false);
    expect(localStorage.getItem(a.ANALYTICS_CONSENT_KEY)).toBe('no');
    expect(document.querySelectorAll('script')).toHaveLength(0);
  });
  it('stops before failed denial persistence, removes stale acceptance when possible and reports failure otherwise', async () => {
    const a = await fresh(); a.initializeAnalytics(); a.setAnalyticsConsent(true);
    const write = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('blocked'); });
    expect(a.setAnalyticsConsent(false)).toEqual({ allowed: false, saved: true, nextVisit: false });
    expect(localStorage.getItem(a.ANALYTICS_CONSENT_KEY)).toBeNull();
    write.mockRestore();
    // Stale acceptance cannot be removed either. Current SDK remains disabled,
    // UI gets an explicit unsaved result rather than a false durable decline.
    localStorage.setItem(a.ANALYTICS_CONSENT_KEY, 'yes');
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('blocked'); });
    vi.spyOn(Storage.prototype, 'removeItem').mockImplementation(() => { throw new Error('blocked'); });
    expect(a.setAnalyticsConsent(false).saved).toBe(false);
    expect(a.analyticsConsent()).toBe(false);
    expect((window as unknown as Record<string, unknown>)['ga-disable-G-SYNTHETIC1']).toBe(true);
    expect(window.__cfBeacon).toBeUndefined();
    const count = commands().length; a.track('file-selected'); expect(commands()).toHaveLength(count);
  });
  it('handles cross-tab clear/revocation without reviving retired CF observers', async () => {
    const a = await fresh(); a.initializeAnalytics(); a.setAnalyticsConsent(true);
    expect(window.__cfBeacon).toBeDefined();
    localStorage.clear();
    window.dispatchEvent(new StorageEvent('storage', { key: null }));
    expect(a.analyticsConsent()).toBe(false); expect(window.__cfBeacon).toBeUndefined();
    window.__cfBeacon = { token: 'late-sdk-attempt', spa: false };
    expect(window.__cfBeacon).toBeUndefined();
    expect(a.setAnalyticsConsent(true).nextVisit).toBe(true);
    expect(document.querySelector('#stx-cloudflare')).toBeNull();
  });
  it('uses host-only owned cookies and preserves unrelated analytics cookies', async () => {
    document.cookie = '_ga=foreign; Path=/'; document.cookie = '_ga_OTHER=sibling; Path=/';
    document.cookie = 'stx_ga=owned; Path=/'; document.cookie = 'stx_ga_SYNTHETIC1=owned; Path=/';
    const a = await fresh(); a.initializeAnalytics(); a.setAnalyticsConsent(true);
    a.setAnalyticsConsent(false);
    expect(document.cookie).toContain('_ga=foreign'); expect(document.cookie).toContain('_ga_OTHER=sibling');
    expect(document.cookie).not.toMatch(/(?:^|; )stx_ga/);
  });

  it('does not claim saved acceptance when a session denial cannot be removed/read back', async () => {
    const a = await fresh(); a.initializeAnalytics(); a.setAnalyticsConsent(false);
    const remove = Storage.prototype.removeItem;
    vi.spyOn(Storage.prototype, 'removeItem').mockImplementation(function(this: Storage, key: string) {
      if (this === sessionStorage) throw new Error('session storage unavailable');
      return remove.call(this, key);
    });
    const result = a.setAnalyticsConsent(true);
    expect(result.allowed).toBe(false); expect(result.saved).toBe(false);
    expect(a.analyticsConsent()).toBe(false);
    expect(document.querySelector('#stx-google')).toBeNull();
    expect(document.querySelector('#stx-cloudflare')).toBeNull();
  });

});
