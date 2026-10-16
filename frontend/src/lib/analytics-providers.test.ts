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
  beforeEach(() => { history.replaceState(null, '', '/'); Object.defineProperty(window, 'stxPrivacy', { configurable: true, value: { qa: false, sensitiveEntry: false, takeReturn: () => ({ returning: false, sessionId: null }) } }); localStorage.clear(); document.head.innerHTML = ''; delete window.dataLayer; delete window.gtag; delete window.umami; });
  afterEach(() => { delete window.stxPrivacy; vi.unstubAllEnvs(); vi.restoreAllMocks(); });
  it('does not load unset providers or request Google before optional consent', async () => {
    const a = await fresh(false); a.initializeAnalytics(); a.setGoogleConsent(true);
    expect(document.querySelectorAll('script')).toHaveLength(0);
    localStorage.clear();
    const b = await fresh(); b.initializeAnalytics();
    expect(document.querySelector('#stx-google')).toBeNull();
    b.setGoogleConsent(false);
    expect(document.querySelector('#stx-google')).toBeNull();
  });
  it('serializes only sanitized manual Google page/funnel data and handles revoke/reallow', async () => {
    const a = await fresh(); a.initializeAnalytics(); a.setGoogleConsent(true);
    // Synthetic identifier; script is never fetched in jsdom.
    expect(document.querySelector('#stx-google')).not.toBeNull();
    a.track('convert-success', { balanced: 'yes', layout: 'card_table', filename: CANARY, amount: CANARY, account: CANARY } as never);
    const serialized = JSON.stringify(commands());
    expect(serialized).not.toContain(CANARY);
    expect(serialized).toContain('"send_page_view":false');
    expect(serialized).toContain('"allow_google_signals":false');
    expect(serialized).toContain('"ad_storage":"denied"');
    expect(serialized).toContain('"page_location":"https://statement-to-excel.apps.smolkin.org/"');
    a.setGoogleConsent(false);
    const before = commands().length;
    a.track('checkout-opened');
    expect(commands()).toHaveLength(before);
    expect((window as unknown as Record<string, unknown>)['ga-disable-G-SYNTHETIC1']).toBe(true);
    a.setGoogleConsent(true);
    expect(commands()[commands().length - 1]).toEqual(['consent', 'update', expect.objectContaining({ analytics_storage: 'granted', ad_storage: 'denied' })]);
    expect(document.querySelectorAll('#stx-google')).toHaveLength(1);
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
    const a = await fresh(); a.initializeAnalytics(); a.setGoogleConsent(true);
    expect(document.querySelectorAll('script')).toHaveLength(0);
  });
  it('owner QA prevents every provider load and event fanout', async () => {
    localStorage.setItem('stx_owner_qa', 'on');
    const a = await fresh(); const send = vi.fn(); window.umami = { track: send };
    a.initializeAnalytics(); a.setGoogleConsent(true); a.track('file-selected');
    expect(document.querySelectorAll('script')).toHaveLength(0);
    expect(send).not.toHaveBeenCalled();
  });
  it('throwing tracker cannot prevent a reversible local consent choice', async () => {
    const a = await fresh(); a.initializeAnalytics(); a.setGoogleConsent(true);
    window.gtag = () => { throw new Error('blocked'); };
    expect(() => a.setGoogleConsent(false)).not.toThrow();
    expect(a.googleConsent()).toBe(false);
  });
});
