import { existsSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { expect, test, type Page } from '@playwright/test';

// Optional captured OFFICIAL SDKs, never fake provider ingestion. No SDK/vendor
// request escapes these routes. GA is a named mock transport, not Google SDK.
const sdkDir = process.env.STX_PROVIDER_SDK_DIR;
const realSDKs = !!sdkDir && existsSync(resolve(sdkDir, 'umami-script.js')) && existsSync(resolve(sdkDir, 'cf-beacon.js'));
const canary = 'SYNTHETIC_PRIVATE_CANARY';
const cors = { 'Access-Control-Allow-Origin': '*', 'Access-Control-Allow-Headers': '*', 'Access-Control-Allow-Methods': 'GET,POST,OPTIONS' };

async function providers(page: Page) {
  const bodies: { provider: string; body: string; url: string; referrer: string; headers?: string }[] = [];
  const loads: string[] = [];
  const polls: string[] = [];
  await page.route('**/*', async route => {
    const request = route.request();
    const url = new URL(request.url());
    if (request.method() === 'OPTIONS') return route.fulfill({ status: 204, headers: cors });
    if (url.pathname === '/__sdk/visibility-flush.js') {
      // A headless Chromium navigation need not expose visibility=hidden
      // before the old document/route is destroyed. Exercise the actual SDK's
      // visibility handler while its transport is still observable.
      return route.fulfill({ contentType: 'application/javascript', body: `
        Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => 'hidden' });
        document.dispatchEvent(new Event('visibilitychange'));
      ` });
    }
    if (url.pathname === '/privacy-bootstrap.js') {
      const bootstrap = readFileSync(resolve('public/privacy-bootstrap.js'), 'utf8');
      return route.fulfill({ contentType: 'application/javascript', body: bootstrap + `
        // Inject a local HTTP transport for SDK fetch calls. SDK dispatch stays local; observe the real SDK's serialized
        // body without sending synthetic traffic to any provider.
        (() => {
          const nativeFetch = window.fetch.bind(window);
          window.fetch = (input, init) => {
            if (typeof input === 'string' && (input === 'https://umami.smolkin.org/api/send' || input === 'https://analytics.test.invalid/collect')) {
              return nativeFetch(location.origin + '/__sdk/receipt', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ destination: input, body: init?.body, headers: init?.headers }) });
            }
            return nativeFetch(input, init);
          };
        })();
      ` });
    }
    if (url.pathname === '/__sdk/receipt') {
      const receipt = request.postDataJSON();
      bodies.push({ provider: receipt.destination.includes('umami') ? 'umami' : 'google-mock', body: receipt.body, url: receipt.destination, headers: JSON.stringify(receipt.headers ?? {}), referrer: request.headers().referer ?? '' });
      return route.fulfill({ json: {} });
    }
    if (url.pathname === '/api/checkout/status') {
      polls.push(request.postDataJSON().session_id);
      return route.fulfill({ json: { session_id: request.postDataJSON().session_id, sku: 'pack_50', status: 'fulfilled' } });
    }
    if (url.hostname === 'umami.smolkin.org' && url.pathname === '/script.js') {
      loads.push('umami');
      return route.fulfill({ headers: cors, contentType: 'application/javascript', body: readFileSync(resolve(sdkDir!, 'umami-script.js'), 'utf8') });
    }
    if (url.hostname === 'static.cloudflareinsights.com') {
      loads.push('cf');
      return route.fulfill({ headers: cors, contentType: 'application/javascript', body: readFileSync(resolve(sdkDir!, 'cf-beacon.js'), 'utf8') });
    }
    if (url.hostname === 'www.googletagmanager.com') {
      loads.push('google-mock');
      return route.fulfill({ headers: cors, contentType: 'application/javascript', body: `
        // Explicit mock GA command->network serialization, not a provider SDK.
        const send = command => { if (command[0] === 'event') fetch('https://analytics.test.invalid/collect', { method: 'POST', body: JSON.stringify(Array.from(command)), keepalive: true }); };
        window.dataLayer.forEach(send);
        const original = window.dataLayer.push.bind(window.dataLayer);
        window.dataLayer.push = (...items) => { items.forEach(send); return original(...items); };
      ` });
    }
    if (url.pathname === '/__sdk/umami/api/send' || url.hostname === 'umami.smolkin.org' || url.hostname === 'analytics.test.invalid' || url.hostname.includes('cloudflareinsights.com') || url.pathname === '/cdn-cgi/rum') {
      bodies.push({ provider: url.hostname === 'umami.smolkin.org' || url.pathname === '/__sdk/umami/api/send' ? 'umami' : url.hostname === 'analytics.test.invalid' ? 'google-mock' : 'cf', body: request.postData() ?? '', url: request.url(), referrer: request.headers().referer ?? '' });
      return route.fulfill({ status: 200, headers: cors, contentType: 'application/json', body: '{}' });
    }
    if (url.hostname !== '127.0.0.1') return route.abort();
    return route.continue();
  });
  return { bodies, loads, polls };
}

for (const size of [{ width: 1365, height: 900 }, { width: 390, height: 844 }]) {
  test(`actual Umami/CF SDK payload privacy and mock GA consent at ${size.width}x${size.height}`, async ({ page }) => {
    test.skip(!realSDKs, 'Set STX_PROVIDER_SDK_DIR to captured official Umami/CF SDKs; no external ingestion allowed.');
    await page.setViewportSize(size);
    const captured = await providers(page);
    await page.goto('/');
    await expect.poll(() => captured.loads).toContain('umami');
    await expect.poll(() => captured.loads).toContain('cf');
    expect(captured.loads).not.toContain('google-mock');
    await expect.poll(() => captured.bodies.filter(p => p.provider === 'umami').length).toBeGreaterThan(0);
    await page.getByRole('button', { name: 'Allow Google Analytics', exact: true }).click();
    await expect.poll(() => captured.loads).toContain('google-mock');
    // Synthetically selected filename, parsed description/account/amount must
    // never be copied into any SDK or serialized request payload.
    let capability = '';
    page.on('request', request => { if (new URL(request.url()).pathname === '/api/account') capability = request.postDataJSON().account_id; });
    await page.route('**/api/convert', route => route.fulfill({ json: {
      transactions: [{ date: '2026-01-01', description: canary, amount: '9876543.21', balance: '9876543.21', currency: 'USD', type: 'credit' }],
      summary: { count: 1, total_credit: '9876543.21', total_debit: '0', net: '9876543.21', currency: 'USD', start_date: '2026-01-01', end_date: '2026-01-01' },
      reconciliation: { status: 'cannot_check', account_type: 'unknown', terms: {}, printed_totals: {}, difference: null, row_flags: [] }, layout: 'deposit_lines',
    } }));
    await page.locator('input[type=file]').setInputFiles({ name: `${canary}.pdf`, mimeType: 'application/pdf', buffer: Buffer.from('%PDF-synthetic') });
    await page.getByLabel('Output format').selectOption('json');
    const download = page.waitForEvent('download');
    await page.locator('.convert-controls button').click(); await download;
    await expect(page.locator('.results')).toContainText(canary);
    await expect.poll(() => captured.bodies.filter(p => p.provider === 'umami' && p.body.includes('convert-success')).length).toBe(1);
    await page.getByRole('button', { name: 'Decline Google Analytics', exact: true }).click();
    // Explicit lifecycle simulation exercises CF's real timing/vitals payload;
    // actual navigation below independently checks return URL exclusion.
    const cfBeforeReturn = captured.bodies.filter(p => p.provider === 'cf').length;
    await page.locator('head').evaluate(head => {
      const script = document.createElement('script'); script.src = '/__sdk/visibility-flush.js'; head.appendChild(script);
    });
    await expect.poll(() => captured.bodies.filter(p => p.provider === 'cf').length).toBeGreaterThan(cfBeforeReturn);
    await page.goto('/?checkout=success&session_id=cs_test_' + canary + '#' + canary);
    await expect.poll(() => captured.polls.length).toBeGreaterThan(0);
    expect(captured.polls[0]).toBe('cs_test_' + canary);
    expect(new URL(page.url()).search).toBe(''); expect(new URL(page.url()).hash).toBe('');
    expect(captured.loads.filter(p => p === 'cf')).toHaveLength(1); // return page excluded
    const serialized = JSON.stringify(captured.bodies);
    expect(serialized).not.toContain(canary); expect(serialized).not.toContain('9876543.21'); expect(serialized).not.toContain('2026-01-01');
    if (capability) expect(serialized).not.toContain(capability);
    expect(serialized).not.toContain('session_id');
  });
}

test('owner QA reload suppresses all providers and consent is localized in all five locales', async ({ page }) => {
  test.skip(!realSDKs, 'Captured official SDK directory required.');
  const captured = await providers(page);
  await page.goto('/');
  // Camoufox does not share evaluate globals with the page, but localStorage is
  // origin storage and this explicit nonsensitive owner control survives reload.
  await page.evaluate(() => localStorage.setItem('stx_owner_qa', 'on'));
  await page.reload();
  const before = captured.loads.length;
  for (const locale of ['en', 'zh', 'ja', 'es', 'it']) {
    await page.getByLabel('Select language').selectOption(locale);
    await expect(page.locator('.privacy-controls section button')).toHaveCount(2);
    await page.locator('.privacy-controls section button').first().click();
    expect(await page.locator('.privacy-controls section').innerText()).not.toContain('undefined');
  }
  expect(captured.loads).toHaveLength(before);
});


test('missing bootstrap suppresses SDKs while conversion and private return recovery work', async ({ page }) => {
  test.skip(!realSDKs, 'Captured official SDK directory required.');
  const captured = await providers(page);
  await page.route('**/privacy-bootstrap.js', route => route.abort());
  await page.goto('/?checkout=success&session_id=cs_test_' + canary);
  await expect(page.locator('.account-chip')).toBeVisible();
  await expect.poll(() => captured.polls.length).toBeGreaterThan(0);
  expect(captured.polls[0]).toBe('cs_test_' + canary);
  await page.getByRole('button', { name: 'Allow Google Analytics', exact: true }).click();
  await page.locator('input[type=file]').setInputFiles(resolve('../backend/tests/fixtures/acmebank.pdf'));
  await page.getByLabel('Output format').selectOption('json');
  const downloaded = page.waitForEvent('download');
  await page.locator('.convert-controls button').click(); await downloaded;
  await expect(page.locator('.results tbody tr')).toHaveCount(5);
  expect(captured.loads).toEqual([]); expect(captured.bodies).toEqual([]);
  expect(new URL(page.url()).search).toBe('');
});

test('sensitive original referrer suppresses CF and never enters SDK payloads', async ({ page }) => {
  test.skip(!realSDKs, 'Captured official SDK directory required.');
  const captured = await providers(page);
  await page.route('**/referral?*', route => route.fulfill({ contentType: 'text/html', body: '<a href="/">Continue</a>' }));
  await page.goto('/referral?account=' + canary);
  await page.getByRole('link', { name: 'Continue' }).click();
  await expect(page.locator('.account-chip')).toBeVisible();
  await expect.poll(() => captured.bodies.filter(p => p.provider === 'umami').length).toBeGreaterThan(0);
  expect(captured.loads).not.toContain('cf');
  expect(JSON.stringify(captured.bodies)).not.toContain(canary);
});
