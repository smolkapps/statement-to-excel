import { useCallback, useEffect, useRef, useState } from "react";
import { Header } from "./components/Header";
import { Hero } from "./components/Hero";
import { Features, HowItWorks } from "./components/Features";
import { Converter } from "./components/Converter";
import { Pricing } from "./components/Pricing";
import { AccountChip } from "./components/AccountChip";
import { useI18n } from "./i18n/I18nContext";
import { fetchAccount, fetchCheckoutStatus, navigateCheckout, openCheckout } from "./lib/api";
import { track } from "./lib/analytics";
import { newAccount, type AccountState } from "./lib/pricing";

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
  const [checkoutBusy, setCheckoutBusy] = useState(false);
  const [checkoutError, setCheckoutError] = useState<string | null>(null);
  const checkoutPending = useRef(false);
  const accountRequestSequence = useRef(0);
  const checkoutIntents = useRef(new Map<string, string>());
  const checkoutSessions = useRef(new Map<string, SavedCheckout>());

  const reconcileCheckout = useCallback(async (sessionId: string) => {
    const status = await fetchCheckoutStatus(accountId, sessionId);
    if (status.status !== "fulfilled" && status.status !== "expired" && status.status !== "cancelled") return;
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
    const sequence = ++accountRequestSequence.current;
    const state = await fetchAccount(accountId);
    if (sequence !== accountRequestSequence.current) return;
    setAccount({
      pro: state.pro,
      planId: state.plan,
      credits: state.credits,
      pagesUsedThisCycle: state.pages_used_this_cycle,
    });
  }, [accountId]);

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const params = new URLSearchParams(window.location.search);
    const returning = params.get("checkout") === "success";
    const returningSession = params.get("session_id");
    let attempts = returning ? 10 : 1;
    const refresh = async () => {
      try {
        if (returningSession) await reconcileCheckout(returningSession).catch(() => {});
        const sequence = ++accountRequestSequence.current;
        const state = await fetchAccount(accountId);
        if (!cancelled && sequence === accountRequestSequence.current) setAccount({
          pro: state.pro,
          planId: state.plan,
          credits: state.credits,
          pagesUsedThisCycle: state.pages_used_this_cycle,
        });
      } catch { /* conversion/checkout show their own actionable service errors */ }
      if (!cancelled && --attempts > 0) timer = setTimeout(refresh, 2000);
    };
    void refresh();
    const onFocus = () => void refreshAccount().catch(() => {});
    window.addEventListener("focus", onFocus);
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
      window.removeEventListener("focus", onFocus);
    };
  }, [accountId, refreshAccount, reconcileCheckout]);

  const handleCheckout = async (sku: string) => {
    if (sku === "free" || checkoutPending.current) return;
    checkoutPending.current = true;
    setCheckoutBusy(true);
    setCheckoutError(null);
    track("upgrade-click");
    try {
      const saved = checkoutSessions.current.get(sku) ?? savedCheckout(accountId, sku);
      if (saved) await reconcileCheckout(saved.sessionId);
      let requestId = checkoutIntents.current.get(sku);
      if (!requestId) {
        requestId = checkoutRequestId(accountId, sku);
        checkoutIntents.current.set(sku, requestId);
      }
      const session = await openCheckout(accountId, sku, requestId);
      const opened = { requestId, sessionId: session.session_id };
      checkoutSessions.current.set(sku, opened);
      rememberCheckout(accountId, sku, opened);
      track("checkout-opened");
      navigateCheckout(session.checkout_url);
    } catch (error) {
      setCheckoutError(error instanceof Error ? error.message : t.checkout_error);
    } finally {
      checkoutPending.current = false;
      setCheckoutBusy(false);
    }
  };

  return (
    <div className="app" id="top">
      <Header />
      <AccountChip account={account} />
      <main>
        <Hero />
        <Features />
        <HowItWorks />
        <Converter accountId={accountId} onCharged={() => void refreshAccount().catch(() => {})} />
        <Pricing onBuyPack={handleCheckout} onChoosePlan={handleCheckout} busy={checkoutBusy} />
        {checkoutError && <p className="convert-error" role="alert">{checkoutError}</p>}
      </main>
      <footer className="site-footer">
        <p>{t.footer_tagline}</p>
        <p className="muted">
          © {new Date().getFullYear()} statement-to-excel. {t.footer_rights}
        </p>
      </footer>
    </div>
  );
}
