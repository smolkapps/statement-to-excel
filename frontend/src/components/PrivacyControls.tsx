import { useEffect, useState } from 'react';
import { useI18n } from '../i18n/I18nContext';
import { googleConfigured, googleConsent, setGoogleConsent } from '../lib/analytics';

export function PrivacyControls() {
  const { t } = useI18n();
  const [allowed, setAllowed] = useState(googleConsent);
  useEffect(() => {
    const refresh = () => setAllowed(googleConsent());
    window.addEventListener('storage', refresh);
    return () => window.removeEventListener('storage', refresh);
  }, []);
  const choose = (value: boolean) => { setGoogleConsent(value); setAllowed(value); };
  return <div className="privacy-controls">
    <details><summary>{t.privacy_title}</summary><p>{t.hero_trust}</p><p>{t.privacy_billing}</p><p>{t.privacy_analytics}</p></details>
    {googleConfigured() && <section aria-label={t.analytics_choice}>
      <p>{t.analytics_consent}</p>
      <button className="btn btn-outline" aria-pressed={allowed === true} onClick={() => choose(true)}>{t.analytics_allow}</button>{' '}
      <button className="btn btn-outline" aria-pressed={allowed === false} onClick={() => choose(false)}>{t.analytics_decline}</button>
    </section>}
  </div>;
}
