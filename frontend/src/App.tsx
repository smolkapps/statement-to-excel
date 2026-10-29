import { useCallback, useEffect, useRef, useState } from "react";
import { Header } from "./components/Header";
import { Hero } from "./components/Hero";
import { Features, HowItWorks } from "./components/Features";
import { Converter } from "./components/Converter";
import { Pricing } from "./components/Pricing";
import { AccountChip } from "./components/AccountChip";
import { useI18n } from "./i18n/I18nContext";
import { fetchAccount, fetchCheckoutAvailability, fetchCheckoutStatus, navigateCheckout, openCheckout, openPortal, billingMode } from "./lib/api";
import { track } from "./lib/analytics";
import { newAccount, type AccountState } from "./lib/pricing";
import { captureCheckoutReturn, persistentAccount } from "./lib/privacy";
import { PrivacyControls } from "./components/PrivacyControls";

// The anonymous account id is a capability: possession permits using its
// allowance. Never use a shared fallback id or guessable Math.random id.
function getAccountId(): string {
  const key = "stx_account_id";
  let id: string | null = null;
  try { id = localStorage.getItem(key); } catch { /* storage may be unavailable */ }
  if (!id || !/^web_[0-9a-f-]{36}$/.test(id)) {
    id = `web_${crypto.randomUUID()}`;
    try { localStorage.setItem(key, id); } catch { /* stable for this App session */ }
  }
  return id;
}

// Keep a checkout intent stable across network failures and page refreshes.
// This contains opaque ids only; no statement or payment-card data is stored.
function checkoutRequestId(accountId: string, sku: string): string {
  const key = `stx_checkout_${accountId}_${sku}`;
  try {
    const saved = localStorage.getItem(key);
    if (saved && /^[0-9a-f-]{36}$/.test(saved)) return saved;
  } catch { /* still protected by the server's pending-session deduplication */ }
  const id = crypto.randomUUID();
  try { localStorage.setItem(key, id); } catch { /* storage may be unavailable */ }
  return id;
}

interface SavedCheckout {
  requestId: string;
  sessionId: string;
}

function savedCheckout(accountId: string, sku: string): SavedCheckout | null {
  try {
    const raw = localStorage.getItem(`stx_checkout_session_${accountId}_${sku}`);
    if (!raw) return null;
    const saved = JSON.parse(raw) as SavedCheckout;
    return typeof saved.requestId === "string" && typeof saved.sessionId === "string" ? saved : null;
  } catch { return null; }
}

function rememberCheckout(accountId: string, sku: string, saved: SavedCheckout): void {
  try { localStorage.setItem(`stx_checkout_session_${accountId}_${sku}`, JSON.stringify(saved)); }
  catch { /* the backend also deduplicates pending sessions */ }
}

export default function App() {
  const { t } = useI18n();
  const [account, setAccount] = useState<AccountState>(() => newAccount());
  const [accountId] = useState(getAccountId);
  const [checkoutAvailable, setCheckoutAvailable] = useState(false);
  const [availabilityKnown, setAvailabilityKnown] = useState(false);
  const [checkoutBusy, setCheckoutBusy] = useState(false);
  const [checkoutError, setCheckoutError] = useState(false);
  const [storageError, setStorageError] = useState(false);
  const [mode, setMode] = useState("test");
  const [returning] = useState(captureCheckoutReturn);
  const [managementAvailable, setManagementAvailable] = useState(false);
  const [billingHold, setBillingHold] = useState(false);
  const billingActive = useRef(false);
  const checkoutPending = useRef(false);
  const accountRequestSequence = useRef(0);
  const checkoutIntents = useRef(new Map<string, string>());
  const checkoutSessions = useRef(new Map<string, SavedCheckout>());

  useEffect(() => {
    let cancelled = false;
    void fetchCheckoutAvailability().then((available) => {
      if (cancelled) return;
      setAvailabilityKnown(true);
      if (available) {
        billingActive.current = true;
        setCheckoutAvailable(true);
        setMode(billingMode);
      }
    }).catch(() => {
      // A failed availability request leaves billing hidden and conversion usable.
    });
    return () => {
      cancelled = true;
      billingActive.current = false;
    };
  }, []);

  const reconcileCheckout = useCallback(async (sessionId: string) => {
    if (!billingActive.current || !accountId) return;
    const status = await fetchCheckoutStatus(accountId, sessionId);
    if (!billingActive.current) return;
    if (!["fulfilled", "expired", "cancelled", "reversed"].includes(status.status)) return;
    const saved = checkoutSessions.current.get(status.sku) ?? savedCheckout(accountId, status.sku);
    // A replayed URL for an older paid session must not clear a newer intent.
    if (!saved || saved.sessionId !== status.session_id) return;
    if (checkoutIntents.current.get(status.sku) === saved.requestId) checkoutIntents.current.delete(status.sku);
    checkoutSessions.current.delete(status.sku);
    try {
      if (localStorage.getItem(`stx_checkout_${accountId}_${status.sku}`) === saved.requestId) {
        localStorage.removeItem(`stx_checkout_${accountId}_${status.sku}`);
      }
      const persisted = savedCheckout(accountId, status.sku);
      if (persisted?.requestId === saved.requestId && persisted.sessionId === saved.sessionId) {
        localStorage.removeItem(`stx_checkout_session_${accountId}_${status.sku}`);
      }
    } catch { /* in-memory intent already cleared */ }
  }, [accountId]);

  const refreshAccount = useCallback(async () => {
    if (!billingActive.current || !accountId) return;
    const sequence = ++accountRequestSequence.current;
    const state = await fetchAccount(accountId);
    if (!billingActive.current || sequence !== accountRequestSequence.current) return;
    setAccount({
      pro: state.pro,
      planId: state.plan,
      credits: state.credits,
      pagesUsedThisCycle: state.pages_used_this_cycle,
    });
    setManagementAvailable(state.management_available === true);
    setBillingHold(state.billing_hold === true);
  }, [accountId]);

  useEffect(() => {
    if (!checkoutAvailable || !accountId) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const returningSession = returning.sessionId;
    let attempts = returning.returning ? 10 : 1;
    const refresh = async () => {
      try {
        if (returningSession) await reconcileCheckout(returningSession).catch(() => {});
        if (cancelled || !billingActive.current) return;
        const sequence = ++accountRequestSequence.current;
        const state = await fetchAccount(accountId);
        if (!cancelled && billingActive.current && sequence === accountRequestSequence.current) {
          setManagementAvailable(state.management_available === true);
          setBillingHold(state.billing_hold === true);
          setAccount({
          pro: state.pro,
          planId: state.plan,
          credits: state.credits,
          pagesUsedThisCycle: state.pages_used_this_cycle,
          });
        }
      } catch { /* conversion/checkout show their own actionable service errors */ }
      if (!cancelled && billingActive.current && --attempts > 0) timer = setTimeout(refresh, 2000);
    };
    void refresh();
    const onFocus = () => void refreshAccount().catch(() => {});
    window.addEventListener("focus", onFocus);
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
      window.removeEventListener("focus", onFocus);
    };
  }, [accountId, checkoutAvailable, refreshAccount, reconcileCheckout, returning]);

  const handleCheckout = async (sku: string) => {
    if (!billingActive.current || !accountId || sku === "free" || checkoutPending.current) return;
    if (!persistentAccount(accountId)) { setStorageError(true); return; }
    setStorageError(false);
    checkoutPending.current = true;
    setCheckoutBusy(true);
    setCheckoutError(false);
    track("upgrade-click");
    try {
      const saved = checkoutSessions.current.get(sku) ?? savedCheckout(accountId, sku);
      if (saved) await reconcileCheckout(saved.sessionId);
      if (!billingActive.current) return;
      let requestId = checkoutIntents.current.get(sku);
      if (!requestId) {
        requestId = checkoutRequestId(accountId, sku);
        checkoutIntents.current.set(sku, requestId);
      }
      const session = await openCheckout(accountId, sku, requestId);
      if (!billingActive.current) return;
      const opened = { requestId, sessionId: session.session_id };
      checkoutSessions.current.set(sku, opened);
      rememberCheckout(accountId, sku, opened);
      track("checkout-opened");
      navigateCheckout(session.checkout_url);
    } catch {
      if (billingActive.current) setCheckoutError(true);
    } finally {
      checkoutPending.current = false;
      setCheckoutBusy(false);
    }
  };

  return (
    <div className="app" id="top">
      <Header showPricing={checkoutAvailable} />
      {checkoutAvailable && <AccountChip account={account} />}
      {checkoutAvailable && mode === "test" && <p className="billing-notice">{t.billing_test_mode}</p>}
      {checkoutAvailable && managementAvailable && <button className="btn btn-outline manage-payment" disabled={checkoutBusy} onClick={async () => {
        if (!persistentAccount(accountId)) { setStorageError(true); return; }
        setCheckoutBusy(true); setCheckoutError(false);
        try { navigateCheckout(await openPortal(accountId)); } catch { setCheckoutError(true); } finally { setCheckoutBusy(false); }
      }}>{t.billing_manage}</button>}
      {checkoutAvailable && billingHold && <p className="convert-error" role="alert">{t.billing_hold}</p>}
      <main>
        <Hero showPricing={checkoutAvailable} unmetered={availabilityKnown && !checkoutAvailable} />
        <Features />
        <HowItWorks />
        <Converter accountId={accountId} onCharged={() => void refreshAccount().catch(() => {})} />
        {checkoutAvailable && (
          <Pricing onBuyPack={handleCheckout} onChoosePlan={handleCheckout} busy={checkoutBusy} />
        )}
        {checkoutAvailable && checkoutError && <p className="convert-error" role="alert">{t.checkout_error}</p>}
        {checkoutAvailable && storageError && <p className="convert-error" role="alert">{t.billing_storage_error}</p>}
      </main>
      <footer className="site-footer">
        <PrivacyControls />
        <p>{t.footer_tagline}</p>
        <p className="muted">
          © {new Date().getFullYear()} statement-to-excel. {t.footer_rights}
        </p>
      </footer>
    </div>
  );
}
