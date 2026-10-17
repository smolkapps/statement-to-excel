import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { captureCheckoutReturn, persistentAccount } from './privacy';

function bootstrap(url: string, referrer = '', qa = false, originalURL = url) {
  const target: Record<string, unknown> = {};
  const parsed = new URL(url);
  const history = { replaceState: vi.fn() };
  vm.runInNewContext(readFileSync('public/privacy-bootstrap.js', 'utf8'), {
    URL, URLSearchParams, Object, window: target, location: parsed, document: { referrer }, history,
    localStorage: { getItem: () => qa ? 'on' : null }, performance: { getEntriesByType: () => [{ name: originalURL }] },
  });
  return { target: target.stxPrivacy as { sensitiveEntry: boolean; qa: boolean; takeReturn: () => unknown }, history };
}

describe('before-tracker URL privacy', () => {
  it('preserves a fallback return across StrictMode initialization without globally retaining its token', async () => {
    history.replaceState(null, '', '/?checkout=success&session_id=cs_test_canary');
    const first = captureCheckoutReturn();
    expect(captureCheckoutReturn()).toEqual(first);
    expect(first.sessionId).toBe('cs_test_canary');
    expect(location.search).toBe('');
    await Promise.resolve();
    expect(captureCheckoutReturn()).toEqual({ returning: false, sessionId: null });
    await Promise.resolve();
  });
  it('captures return privately and removes query, hash, history state before any tracker', () => {
    const { target, history } = bootstrap('https://statement-to-excel.apps.smolkin.org/?checkout=success&session_id=cs_test_canaryPayment&account=canaryAccount#canaryRows');
    expect(history.replaceState).toHaveBeenCalledTimes(1);
    expect(history.replaceState).toHaveBeenCalledWith(null, '', '/');
    expect(target.sensitiveEntry).toBe(true);
    expect(target.takeReturn()).toEqual({ returning: true, sessionId: 'cs_test_canaryPayment' });
    expect(target.takeReturn()).toEqual({ returning: false, sessionId: null }); // drained before trackers
    expect(JSON.stringify(target)).not.toMatch(/canary/);
  });
  it.each(['https://example.org/?account=canary', 'https://example.org/privateAccount', 'https://example.org/#canary'])('suppresses CF for sensitive original referrer %s', (ref) => {
    expect(bootstrap('https://statement-to-excel.apps.smolkin.org/', ref).target.sensitiveEntry).toBe(true);
  });
  it('permits clean entry and explicitly isolates owner QA', () => {
    expect(bootstrap('https://statement-to-excel.apps.smolkin.org/').target.sensitiveEntry).toBe(false);
    expect(bootstrap('https://statement-to-excel.apps.smolkin.org/', '', true).target.qa).toBe(true);
  });
  it('suppresses CF when original navigation timing retained a secret after URL rewrite', () => {
    expect(bootstrap('https://statement-to-excel.apps.smolkin.org/', '', false, 'https://statement-to-excel.apps.smolkin.org/?payment=canary').target.sensitiveEntry).toBe(true);
  });
  it('does not accept arbitrary return tokens', () => {
    expect(bootstrap('https://statement-to-excel.apps.smolkin.org/?session_id=canary.pdf').target.takeReturn()).toEqual({ returning: false, sessionId: null });
  });
  afterEach(() => { vi.restoreAllMocks(); localStorage.clear(); });
  it('recovers the retained capability on an explicit retry after initial save failure', () => {
    const blocked = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('blocked'); });
    expect(persistentAccount('web_retained')).toBe(false);
    blocked.mockRestore();
    expect(persistentAccount('web_retained')).toBe(true);
    expect(localStorage.getItem('stx_account_id')).toBe('web_retained');
    localStorage.setItem('stx_account_id', 'web_other');
    expect(persistentAccount('web_retained')).toBe(false);
    expect(localStorage.getItem('stx_account_id')).toBe('web_other');
  });
  it('requires durable readback before taking payment', () => {
    localStorage.setItem('stx_account_id', 'web_capability');
    expect(persistentAccount('web_capability')).toBe(true);
    expect(persistentAccount('other')).toBe(false);
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('blocked'); });
    expect(persistentAccount('web_capability')).toBe(false);
  });
});
