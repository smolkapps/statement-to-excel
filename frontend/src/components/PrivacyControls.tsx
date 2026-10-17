import { useEffect, useState } from 'react';
import { useI18n } from '../i18n/I18nContext';
import { optionalAnalyticsConfigured, analyticsConsent, setAnalyticsConsent } from '../lib/analytics';

export function PrivacyControls() {
  const { t } = useI18n();
  const [allowed, setAllowed] = useState(analyticsConsent);
  const [saveFailed, setSaveFailed] = useState(false);
  const [nextVisit, setNextVisit] = useState(false);
  useEffect(() => {
    const refresh = () => setAllowed(analyticsConsent());
    window.addEventListener('stx-analytics-choice', refresh);
    return () => window.removeEventListener('stx-analytics-choice', refresh);
  }, []);
  const choose = (value: boolean) => { const result = setAnalyticsConsent(value); setAllowed(result.allowed); setSaveFailed(!result.saved); setNextVisit(result.nextVisit); };
  return <div className="privacy-controls">
    <details><summary>{t.privacy_title}</summary><p>{t.hero_trust}</p><p>{t.privacy_billing}</p><p>{t.privacy_analytics}</p></details>
    {optionalAnalyticsConfigured() && <section aria-label={t.analytics_choice}>
      <p>{t.analytics_consent}</p>
      <button className="btn btn-outline" aria-pressed={allowed === true} onClick={() => choose(true)}>{t.analytics_allow}</button>{' '}
      <button className="btn btn-outline" aria-pressed={allowed === false} onClick={() => choose(false)}>{t.analytics_decline}</button>
      {saveFailed && <p role="alert">{t.analytics_save_error}</p>}
      {nextVisit && <p>{t.analytics_next_visit} <button className="btn btn-outline" onClick={() => location.reload()}>{t.analytics_reload}</button></p>}
    </section>}
  </div>;
}
