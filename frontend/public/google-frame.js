// Disposable SDK lifecycle, not an authentication/security boundary. No app
// capability, return URL, filename or transaction is passed into this context.
(() => {
  let allowed = false;
  let measurement = '';
  const names = new Set(['page_view', 'file_selected', 'convert_success', 'convert_error', 'upgrade_click', 'checkout_opened']);
  const page = { page_location: 'https://statement-to-excel.apps.smolkin.org/', page_title: 'Statement to Excel', page_referrer: '' };
  // Register before the SDK. Disposing a frame can fire exit events; block its
  // SDK's flush handlers after withdrawal, then removal kills pending timers.
  const exit = event => { if (!allowed) event.stopImmediatePropagation(); };
  for (const target of [window, document]) for (const name of ['visibilitychange', 'pagehide', 'beforeunload', 'unload']) target.addEventListener(name, exit, true);
  const gtag = function () { window.dataLayer.push(arguments); };
  window.stxGoogleFrame = Object.freeze({
    start(id) {
      if (window.parent === window || location.pathname !== '/google-frame.html' || location.search || location.hash || window.frameElement?.id !== 'stx-google') return;
      if (measurement || !/^G-[A-Z0-9]{5,20}$/.test(id)) return;
      measurement = id; allowed = true;
      window.dataLayer = [];
      window.gtag = gtag;
      window['ga-disable-' + id] = false;
      gtag('consent', 'default', { analytics_storage: 'granted', ad_storage: 'denied', ad_user_data: 'denied', ad_personalization: 'denied' });
      gtag('js', new Date());
      gtag('set', 'ads_data_redaction', true);
      const cookies = { cookie_domain: 'none', cookie_prefix: 'stx', cookie_path: '/', cookie_flags: location.protocol === 'https:' ? 'SameSite=Lax;Secure' : 'SameSite=Lax' };
      gtag('set', cookies);
      gtag('config', id, { ...cookies, send_page_view: false, allow_google_signals: false, allow_ad_personalization_signals: false, ...page });
      const script = document.createElement('script');
      script.async = true; script.referrerPolicy = 'no-referrer';
      script.src = 'https://www.googletagmanager.com/gtag/js?id=' + id;
      script.onload = () => { if (allowed) window.frameElement?.setAttribute('data-sdk-loaded', 'yes'); };
      document.head.appendChild(script);
    },
    event(name, input) {
      if (!allowed || !names.has(name)) return;
      const data = { ...page };
      if (name === 'convert_success') {
        data.balanced = input?.balanced === 'yes' || input?.balanced === 'no' ? input.balanced : 'unknown';
        data.layout = ['deposit_table','deposit_lines','card_table','card_lines'].includes(input?.layout) ? input.layout : 'unknown';
      }
      gtag('event', name, data);
    },
    stop() {
      allowed = false;
      if (measurement) window['ga-disable-' + measurement] = true;
    },
  });
})();
