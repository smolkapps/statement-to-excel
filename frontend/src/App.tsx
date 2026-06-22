import { useEffect, useState } from "react";
import { Header } from "./components/Header";
import { Hero } from "./components/Hero";
import { Features, HowItWorks } from "./components/Features";
import { Converter } from "./components/Converter";
import { Pricing } from "./components/Pricing";
import { AccountChip } from "./components/AccountChip";
import { useI18n } from "./i18n/I18nContext";
import { loadAccount, saveAccount } from "./lib/accountStore";
import {
  addCredits,
  charge,
  getPack,
  setPlan,
  type AccountState,
} from "./lib/pricing";

// A stable anonymous account id for the demo (lets the backend meter usage).
function getAccountId(): string {
  const KEY = "stx_account_id";
  try {
    let id = localStorage.getItem(KEY);
    if (!id) {
      id = "web_" + Math.random().toString(36).slice(2, 12);
      localStorage.setItem(KEY, id);
    }
    return id;
  } catch {
    return "anon";
  }
}

export default function App() {
  const { t } = useI18n();
  const [account, setAccount] = useState<AccountState>(() => loadAccount());
  const accountId = getAccountId();

  useEffect(() => {
    saveAccount(account);
  }, [account]);

  const handleBuyPack = (packId: string) => {
    const pack = getPack(packId);
    if (pack) setAccount((a) => addCredits(a, pack.credits));
  };

  const handleChoosePlan = (planId: string) => {
    setAccount((a) => setPlan(a, planId));
  };

  const handleCharged = (pages: number) => {
    // Mirror the backend charge locally so the account chip stays in sync.
    setAccount((a) => (a && quoteOk(a, pages) ? charge(a, pages) : a));
  };

  return (
    <div className="app" id="top">
      <Header />
      <AccountChip account={account} />
      <main>
        <Hero />
        <Features />
        <HowItWorks />
        <Converter accountId={accountId} onCharged={handleCharged} />
        <Pricing onBuyPack={handleBuyPack} onChoosePlan={handleChoosePlan} />
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

function quoteOk(a: AccountState, pages: number): boolean {
  try {
    charge(a, pages);
    return true;
  } catch {
    return false;
  }
}
