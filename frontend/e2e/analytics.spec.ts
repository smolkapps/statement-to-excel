import { existsSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { expect, test, type Page } from '@playwright/test';

// Optional captured OFFICIAL SDKs, never fake provider ingestion. No SDK/vendor
// request escapes these routes. Google uses actual current official SDK bytes
// requested with a synthetic test ID; this is not property acceptance/ingestion.
const sdkDir = process.env.STX_PROVIDER_SDK_DIR;
const realSDKs = !!sdkDir && existsSync(resolve(sdkDir, 'umami-script.js')) && existsSync(resolve(sdkDir, 'cf-beacon.js')) && existsSync(resolve(sdkDir, 'google-gtag.js'));
const canary = 'SYNTHETIC_PRIVATE_CANARY';
const consentKey = 'stx_optional_analytics_v1';
const corsDefaults = { 'Access-Control-Allow-Origin': 'http://127.0.0.1:4175', 'Access-Control-Allow-Credentials': 'true', 'Access-Control-Allow-Headers': '*', 'Access-Control-Allow-Methods': 'GET,POST,OPTIONS' };

async function providers(page: Page, appOrigin = 'http://127.0.0.1:4175') {
  const cors = { ...corsDefaults, 'Access-Control-Allow-Origin': appOrigin };
  const bodies: { provider: string; body: string; url: string; referrer: string; headers?: string; started?: number }[] = [];
  const loads: string[] = [];
  const polls: string[] = [];
  await page.route('**/*', async route => {
    const request = route.request();
    const url = new URL(request.url());
    if (request.method() === 'OPTIONS') return route.fulfill({ status: 204, headers: cors });
    if (url.pathname === '/google-frame.js') {
      const transport = page.context().browser()?.browserType().name() === 'firefox' ? `
        // Camoufox's native external keepalive transport can be suppressed.
        // Preserve real SDK serialization and observe it over local HTTP only.
        const nativeFetch = window.fetch.bind(window);
        const receipt = (destination, body, headers) => {
          const started = Date.now();
          Promise.resolve(body instanceof Blob ? body.text() : body ?? '').then(body =>
            nativeFetch(location.origin + '/__sdk/receipt', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ destination, body, headers, started }) }));
        };
        window.fetch = (input, init) => {
          if (typeof input === 'string' && /google-analytics\\.com|analytics\\.google\\.com/.test(input)) { receipt(input, init?.body, init?.headers); return Promise.resolve(new Response(null, { status: 204 })); }
          return nativeFetch(input, init);
        };
        const beacon = navigator.sendBeacon.bind(navigator);
        navigator.sendBeacon = (destination, body) => {
          if (/google-analytics\\.com|analytics\\.google\\.com/.test(String(destination))) { receipt(String(destination), body, {}); return true; }
          return beacon(destination, body);
        };
      ` : '';
      return route.fulfill({ contentType: 'application/javascript', body: 'Math.random = () => 0;\n' + transport + readFileSync(resolve('public/google-frame.js'), 'utf8') });
    }
    if (url.pathname === '/__sdk/visibility-flush.js') {
      // A headless Chromium navigation need not expose visibility=hidden
      // before the old document/route is destroyed. Exercise the actual SDK's
      // visibility handler while its transport is still observable.
      return route.fulfill({ contentType: 'application/javascript', body: `
        Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => 'hidden' });
        document.dispatchEvent(new Event('visibilitychange'));
        window.dispatchEvent(new Event('pagehide'));
        for (const frame of document.querySelectorAll('iframe')) {
          const child = frame.contentWindow;
          if (child) { Object.defineProperty(child.document, 'visibilityState', { configurable: true, get: () => 'hidden' }); child.document.dispatchEvent(new child.Event('visibilitychange')); child.dispatchEvent(new child.Event('pagehide')); }
        }
      ` });
    }
    if (url.pathname === '/privacy-bootstrap.js') {
      const bootstrap = readFileSync(resolve('public/privacy-bootstrap.js'), 'utf8');
      return route.fulfill({ contentType: 'application/javascript', body: bootstrap + `
        // Inject a local HTTP transport for SDK fetch calls. SDK dispatch stays local; observe the real SDK's serialized
        // body without sending synthetic traffic to any provider.
        (() => {
          // Force sampled diagnostics in this synthetic SDK audit, not in the app.
          Math.random = () => 0;
          const nativeFetch = window.fetch.bind(window);
          window.fetch = (input, init) => {
            if (typeof input === 'string' && input === 'https://umami.smolkin.org/api/send') {
              return nativeFetch(location.origin + '/__sdk/receipt', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ destination: input, body: init?.body, headers: init?.headers }) });
            }
            return nativeFetch(input, init);
          };
        })();
      ` });
    }
    if (url.pathname === '/__sdk/receipt') {
      const receipt = request.postDataJSON();
      bodies.push({ provider: receipt.destination.includes('umami') ? 'umami' : 'google', started: receipt.started, body: receipt.body, url: receipt.destination, headers: JSON.stringify(receipt.headers ?? {}), referrer: request.headers().referer ?? '' });
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
    if (url.hostname === 'www.googletagmanager.com' && url.pathname === '/gtag/js') {
      loads.push('google');
      return route.fulfill({ headers: cors, contentType: 'application/javascript', body: readFileSync(resolve(sdkDir!, 'google-gtag.js'), 'utf8') });
    }
    if (url.pathname === '/__sdk/umami/api/send' || url.hostname === 'umami.smolkin.org' || url.hostname.includes('cloudflareinsights.com') || url.pathname === '/cdn-cgi/rum') {
      bodies.push({ provider: url.hostname === 'umami.smolkin.org' || url.pathname === '/__sdk/umami/api/send' ? 'umami' : 'cf', body: request.postData() ?? '', url: request.url(), referrer: request.headers().referer ?? '' });
      return route.fulfill({ status: 200, headers: cors, contentType: 'application/json', body: '{}' });
    }
    if (url.origin === appOrigin && url.hostname !== '127.0.0.1') {
      try {
        const response = await route.fetch({ url: 'http://127.0.0.1:4175' + url.pathname + url.search, headers: { ...request.headers(), host: '127.0.0.1:4175' } });
        if (!page.isClosed()) await route.fulfill({ response });
      } catch (error) {
        // Keep all routes installed through teardown so no provider traffic can
        // escape. Page closure legitimately cancels a pending local HTTP proxy.
        if (!page.isClosed()) throw error;
      }
      return;
    }
    if (url.hostname !== '127.0.0.1') {
      bodies.push({ provider: 'google', started: request.timing().startTime, body: request.postData() ?? '', url: request.url(), headers: JSON.stringify(request.headers()), referrer: request.headers().referer ?? '' });
      return route.fulfill({ status: 204, headers: cors, body: '' });
    }
    return route.continue();
  });
  return { bodies, loads, polls };
}

for (const size of [{ width: 1365, height: 900 }, { width: 390, height: 844 }]) {
  test(`actual Umami/CF/Google SDK payload privacy and optional consent at ${size.width}x${size.height}`, async ({ page }) => {
    test.skip(!realSDKs, 'Set STX_PROVIDER_SDK_DIR to captured official Umami/CF/Google SDKs; no external ingestion allowed.');
    await page.setViewportSize(size);
    const captured = await providers(page);
    let capability = '';
    page.on('request', request => { if (new URL(request.url()).pathname === '/api/account') capability = request.postDataJSON().account_id; });
    await page.goto('/');
    await expect.poll(() => captured.loads).toContain('umami');
    expect(captured.loads).not.toContain('cf');
    expect(captured.loads).not.toContain('google');
    await expect.poll(() => captured.bodies.filter(p => p.provider === 'umami').length).toBeGreaterThan(0);
    await page.getByRole('button', { name: 'Allow optional analytics', exact: true }).click();
    await expect.poll(() => captured.loads).toContain('google');
    await expect.poll(() => captured.loads).toContain('cf');
    await expect.poll(() => captured.bodies.filter(p => p.provider === 'google').length).toBeGreaterThan(0);
    // Synthetically selected filename, parsed description/account/amount must
    // never be copied into any SDK or serialized request payload.
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
    await page.locator('body').evaluate((body, value) => { const form=document.createElement('form'); const input=document.createElement('input'); input.name=value; input.id=value; input.value=value; form.appendChild(input); body.appendChild(form); input.dispatchEvent(new Event('input', { bubbles:true })); }, canary);
    await expect.poll(() => captured.bodies.filter(p => p.provider === 'umami' && p.body.includes('convert-success')).length).toBe(1);
    // Explicit lifecycle simulation exercises CF's real timing/vitals payload;
    // actual navigation below independently checks return URL exclusion.
    const cfBeforeReturn = captured.bodies.filter(p => p.provider === 'cf').length;
    await page.locator('head').evaluate(head => {
      const script = document.createElement('script'); script.src = '/__sdk/visibility-flush.js'; head.appendChild(script);
    });
    await expect.poll(() => captured.bodies.filter(p => p.provider === 'cf').length).toBeGreaterThan(cfBeforeReturn);
    await page.getByRole('button', { name: 'Decline optional analytics', exact: true }).click();
    const afterDecline = captured.bodies.filter(p => p.provider !== 'umami').length;
    await page.locator('head').evaluate(head => {
      const script = document.createElement('script'); script.src = '/__sdk/visibility-flush.js'; head.appendChild(script);
    });
    await page.waitForTimeout(350);
    expect(captured.bodies.filter(p => p.provider !== 'umami')).toHaveLength(afterDecline);

    await page.goto('/?checkout=success&session_id=cs_test_' + canary + '#' + canary);
    await expect.poll(() => captured.polls.length).toBeGreaterThan(0);
    expect(captured.polls[0]).toBe('cs_test_' + canary);
    expect(new URL(page.url()).search).toBe(''); expect(new URL(page.url()).hash).toBe('');
    expect(captured.loads.filter(p => p === 'cf')).toHaveLength(1); // return page excluded
    expect(captured.loads.filter(p => p === 'google')).toHaveLength(1);
    await page.screenshot({ path: test.info().outputPath('optional-consent-' + size.width + '.png'), fullPage: true });
    const serialized = decodeURIComponent(JSON.stringify(captured.bodies));
    await test.info().attach('actual-sdk-serialized-requests', { body: JSON.stringify(captured.bodies, null, 2), contentType: 'application/json' });
    expect(serialized).not.toContain(canary); expect(serialized).not.toContain('9876543.21'); expect(serialized).not.toContain('2026-01-01');
    expect(capability).toMatch(/^web_/);
    expect(serialized).not.toContain(capability);
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
  await page.getByRole('button', { name: 'Allow optional analytics', exact: true }).click();
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
  await page.getByRole('button', { name: 'Allow optional analytics', exact: true }).click();
  expect(captured.loads).not.toContain('cf');
  expect(captured.loads).not.toContain('google');
  expect(JSON.stringify(captured.bodies)).not.toContain(canary);
});


test('saved denial and legacy Google-only acceptance do not enable either optional SDK', async ({ page }) => {
  test.skip(!realSDKs, 'Captured official SDK directory required.');
  const captured = await providers(page); await page.goto('/');
  await page.evaluate(() => localStorage.setItem('stx_google_consent', 'yes'));
  await page.reload();
  expect(captured.loads.filter(p => p !== 'umami')).toEqual([]);
  await page.getByRole('button', { name: 'Decline optional analytics', exact: true }).click();
  await page.reload();
  expect(captured.loads.filter(p => p !== 'umami')).toEqual([]);
  expect(await page.evaluate(key => localStorage.getItem(key), consentKey)).toBe('no');
});

test('actual Google SDK preserves unrelated cookies and emits valid mapped events', async ({ page, context }) => {
  test.skip(!realSDKs, 'Captured official SDK directory required.');
  // HTTPS synthetic subdomain, fulfilled only from the local app. This lets
  // the actual SDK prove host-only cookie ownership against parent sentinels.
  const origin = 'https://statement.example.test';
  const captured = await providers(page, origin);
  await context.addCookies([
    { name: '_ga', value: 'sibling-sentinel', domain: '.example.test', path: '/', secure: true },
    { name: '_ga_OTHER', value: 'other-property-sentinel', domain: '.example.test', path: '/', secure: true },
    { name: 'stx_ga_PARENT', value: 'prefixed-parent-sentinel', domain: '.example.test', path: '/', secure: true },
  ]);
  await page.goto(origin + '/');
  await page.getByRole('button', { name: 'Allow optional analytics', exact: true }).click();
  await expect.poll(() => captured.bodies.filter(p => p.provider === 'google').length).toBeGreaterThan(0);
  // Page-owned script, not evaluate's isolated world in Camoufox.
  await page.route('**/__sdk/funnel.js', route => route.fulfill({ contentType: 'application/javascript', body: `
    import { track } from '/src/lib/analytics.ts';
    for (const event of ['file-selected','convert-error','upgrade-click','checkout-opened']) track(event);
    track('convert-success', { balanced: 'no', layout: 'card_table', filename: '${canary}' });
    document.documentElement.setAttribute('data-funnel-sent', 'yes');

  ` }));
  await page.locator('head').evaluate(head => { const s = document.createElement('script'); s.type='module'; s.src='/__sdk/funnel.js'; head.appendChild(s); });
  await expect(page.locator('html')).toHaveAttribute('data-funnel-sent', 'yes');
  await page.locator('head').evaluate(head => { const s=document.createElement('script'); s.src='/__sdk/visibility-flush.js'; head.appendChild(s); });
  await expect.poll(() => captured.bodies.filter(p => p.provider === 'google').map(p => decodeURIComponent(p.url + '\n' + p.body)).join('\n'), { timeout: 15000 }).toContain('en=checkout_opened');
  const all = captured.bodies.filter(p => p.provider === 'google').map(p => decodeURIComponent(p.url + '\n' + p.body)).join('\n');
  for (const name of ['file_selected','convert_success','convert_error','upgrade_click','checkout_opened']) expect(all).toContain('en=' + name);
  expect(all).not.toContain(canary);
  const cookies = await context.cookies();
  expect(cookies.some(c => c.name === 'stx_ga')).toBe(true);
  expect(cookies.filter(c => c.name.startsWith('stx_ga') && c.name !== 'stx_ga_PARENT').every(c => c.domain === 'statement.example.test' && c.secure)).toBe(true);
  await page.getByRole('button', { name: 'Decline optional analytics', exact: true }).click();
  const remaining = await context.cookies();
  expect(remaining.find(c => c.name === '_ga')?.value).toBe('sibling-sentinel');
  expect(remaining.find(c => c.name === '_ga_OTHER')?.value).toBe('other-property-sentinel');
  expect(remaining.find(c => c.name === 'stx_ga_PARENT')?.value).toBe('prefixed-parent-sentinel');
  expect(remaining.some(c => c.domain === 'statement.example.test' && c.name.startsWith('stx_ga'))).toBe(false);
  await page.reload();
  expect(captured.loads.filter(p => p === 'google')).toHaveLength(1);
  expect(captured.loads.filter(p => p === 'cf')).toHaveLength(1);
  await test.info().attach('actual-google-payloads', { body: JSON.stringify(captured.bodies, null, 2), contentType: 'application/json' });
});

test('withdrawal before actual SDK delivery blocks late collection and observer revival', async ({ page }) => {
  test.skip(!realSDKs, 'Captured official SDK directory required.');
  const captured = await providers(page);
  let release!: () => void;
  const ready = new Promise<void>(resolve => { release = resolve; });
  let waiting = 0;
  await page.route(/(googletagmanager\.com\/gtag\/js|static\.cloudflareinsights\.com\/beacon)/, async route => {
    waiting++;
    await ready;
    await route.fallback();
  });
  await page.goto('/');
  await page.getByRole('button', { name: 'Allow optional analytics', exact: true }).click();
  await expect.poll(() => waiting).toBe(2);
  await page.getByRole('button', { name: 'Decline optional analytics', exact: true }).click();
  release();
  await expect.poll(() => captured.loads.filter(p => p !== 'umami').length).toBe(2);
  await page.locator('head').evaluate(head => { const s=document.createElement('script'); s.src='/__sdk/visibility-flush.js'; head.appendChild(s); });
  await page.waitForTimeout(500);
  expect(captured.bodies.filter(p => p.provider !== 'umami')).toEqual([]);
  await page.getByRole('button', { name: 'Allow optional analytics', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Reload page', exact: true })).toBeVisible();
  expect(captured.loads.filter(p => p === 'cf')).toHaveLength(1);
});

test('failed persisted withdrawal truthfully stops real SDKs and does not reload stale acceptance', async ({ page }) => {
  test.skip(!realSDKs, 'Captured official SDK directory required.');
  const captured = await providers(page); await page.goto('/');
  await page.getByRole('button', { name: 'Allow optional analytics', exact: true }).click();
  await expect.poll(() => captured.bodies.filter(p => p.provider === 'google').length).toBeGreaterThan(0);
  await page.route('**/__sdk/storage-denial.js', route => route.fulfill({ contentType: 'application/javascript', body: `
    const set = Storage.prototype.setItem; const remove = Storage.prototype.removeItem;
    Storage.prototype.setItem = function(key, value) { if(key === '${consentKey}') throw Error('synthetic unavailable storage'); return set.call(this, key, value); };
    Storage.prototype.removeItem = function(key) { if(key === '${consentKey}') throw Error('synthetic unavailable storage'); return remove.call(this, key); };
  ` }));
  const storagePatched = page.waitForResponse('**/__sdk/storage-denial.js');
  await page.locator('head').evaluate(head => { const s=document.createElement('script'); s.src='/__sdk/storage-denial.js'; head.appendChild(s); });
  await storagePatched;
  await page.getByRole('button', { name: 'Decline optional analytics', exact: true }).click();
  await expect(page.getByRole('alert')).toContainText('could not save your choice');
  const count = captured.bodies.filter(p => p.provider !== 'umami').length;
  await page.locator('head').evaluate(head => { const s=document.createElement('script'); s.src='/__sdk/visibility-flush.js'; head.appendChild(s); });
  await page.waitForTimeout(350);
  expect(captured.bodies.filter(p => p.provider !== 'umami')).toHaveLength(count);
  expect(await page.evaluate(key => localStorage.getItem(key), consentKey)).toBe('yes');
  // Explicit test navigation, never automatic reload by the product. The
  // session denial is an additional fail-closed fallback for this same tab.
  await page.reload();
  expect(captured.loads.filter(p => p === 'google')).toHaveLength(1);
  expect(captured.loads.filter(p => p === 'cf')).toHaveLength(1);
});

test('cross-tab storage.clear revokes real optional SDKs immediately', async ({ page, context }) => {
  test.skip(!realSDKs, 'Captured official SDK directory required.');
  const captured = await providers(page); await page.goto('/');
  await page.getByRole('button', { name: 'Allow optional analytics', exact: true }).click();
  await expect.poll(() => captured.bodies.filter(p => p.provider === 'google').length).toBeGreaterThan(0);
  const other = await context.newPage();
  await other.route('**/*', route => route.fulfill({ contentType: 'text/html', body: '<p>Local storage control</p>' }));
  await other.goto('http://127.0.0.1:4175/'); await other.evaluate(() => localStorage.clear());
  await expect(page.getByRole('button', { name: 'Decline optional analytics', exact: true })).toHaveAttribute('aria-pressed', 'true');
  const count = captured.bodies.filter(p => p.provider !== 'umami').length;
  await page.locator('head').evaluate(head => { const s=document.createElement('script'); s.src='/__sdk/visibility-flush.js'; head.appendChild(s); });
  await page.waitForTimeout(350);
  expect(captured.bodies.filter(p => p.provider !== 'umami')).toHaveLength(count);
  // Reallowing retired SDKs requires a later visit. A subsequent cross-tab
  // revocation must also retire that stale acceptance/reload notice.
  await page.getByRole('button', { name: 'Allow optional analytics', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Reload page', exact: true })).toBeVisible();
  await other.evaluate(() => localStorage.clear());
  await expect(page.getByRole('button', { name: 'Decline optional analytics', exact: true })).toHaveAttribute('aria-pressed', 'true');
  await expect(page.getByRole('button', { name: 'Reload page', exact: true })).toHaveCount(0);
  await other.close();
});

test('saved opt-in never loads optional SDKs for sensitive return navigation or referrer', async ({ page }) => {
  test.skip(!realSDKs, 'Captured official SDK directory required.');
  const captured = await providers(page); await page.goto('/');
  await page.getByRole('button', { name: 'Allow optional analytics', exact: true }).click();
  await expect.poll(() => captured.loads.filter(p => p === 'google').length).toBe(1);
  await page.goto('/?checkout=success&session_id=cs_test_' + canary + '&account=' + canary + '#' + canary);
  await expect.poll(() => captured.polls.length).toBeGreaterThan(0);
  await page.getByRole('button', { name: 'Allow optional analytics', exact: true }).click();
  expect(captured.loads.filter(p => p === 'google')).toHaveLength(1);
  expect(captured.loads.filter(p => p === 'cf')).toHaveLength(1);
  expect(decodeURIComponent(JSON.stringify(captured.bodies))).not.toContain(canary);
});

test('loaded Google diagnostics are terminated before their timer and withdrawal exit', async ({ page }) => {
  test.skip(!realSDKs, 'Captured official SDK directory required.');
  const captured = await providers(page); await page.goto('/');
  await page.route('**/__sdk/withdraw-loaded.js', route => route.fulfill({ contentType: 'application/javascript', body: `
    import { setAnalyticsConsent } from '/src/lib/analytics.ts';
    const observer = new MutationObserver(() => {
      if (!document.querySelector('#stx-google[data-sdk-loaded="yes"]')) return;
      observer.disconnect();
      document.documentElement.setAttribute('data-withdrawal-at', String(Date.now()));
      setAnalyticsConsent(false);
    });
    observer.observe(document, { attributes: true, childList: true, subtree: true });
    document.documentElement.setAttribute('data-withdrawal-ready', 'yes');
  ` }));
  await page.locator('head').evaluate(head => { const s=document.createElement('script'); s.type='module'; s.src='/__sdk/withdraw-loaded.js'; head.appendChild(s); });
  await expect(page.locator('html')).toHaveAttribute('data-withdrawal-ready', 'yes');
  await page.getByRole('button', { name: 'Allow optional analytics', exact: true }).click();
  await expect(page.locator('html')).toHaveAttribute('data-withdrawal-at', /^\d+$/);
  const boundary = Number(await page.locator('html').getAttribute('data-withdrawal-at'));
  await expect(page.locator('#stx-google')).toHaveCount(0);
  // Actual Google diagnostics use a 500ms timer, even with ga-disable. Count
  // from the boundary BEFORE disposal, not after the decline click returns.
  await page.waitForTimeout(900);
  await page.locator('head').evaluate(head => { const s=document.createElement('script'); s.src='/__sdk/visibility-flush.js'; head.appendChild(s); });
  await page.waitForTimeout(250);
  expect(captured.bodies.filter(p => p.provider === 'google' && (p.started ?? 0) >= boundary)).toEqual([]);
  await test.info().attach('loaded-sdk-withdrawal', { body: JSON.stringify({ boundary, packets: captured.bodies }, null, 2), contentType: 'application/json' });
});

test('direct analytics-frame entry stays inert without the app consent boundary', async ({ page }) => {
  test.skip(!realSDKs, 'Captured official SDK directory required.');
  const captured = await providers(page); await page.goto('/google-frame.html');
  await page.waitForTimeout(200);
  expect(captured.loads).toEqual([]); expect(captured.bodies).toEqual([]);
});
