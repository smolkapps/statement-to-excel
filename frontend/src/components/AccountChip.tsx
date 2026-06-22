import { useI18n } from "../i18n/I18nContext";
import { AccountState, getPlan, includedRemaining } from "../lib/pricing";

export function AccountChip({ account }: { account: AccountState }) {
  const { t } = useI18n();
  const plan = getPlan(account.planId) ?? getPlan("free")!;
  return (
    <div className="account-chip" aria-label={t.account_title}>
      <span>
        {t.account_plan}: <strong>{plan.name}</strong>
      </span>
      <span>
        {t.account_credits}: <strong>{account.credits}</strong>
      </span>
      <span>
        {t.account_included_remaining}:{" "}
        <strong>{includedRemaining(account)}</strong>
      </span>
    </div>
  );
}
