// localStorage-backed persistence for the demo account's metering state, so a
// visitor's remaining free pages / purchased credits survive a refresh without
// requiring login. Pure (de)serialization is unit-tested with a fake storage.

import { AccountState, newAccount } from "./pricing";

const KEY = "stx_account";

type StorageLike = Pick<Storage, "getItem" | "setItem">;

function getStorage(): StorageLike | null {
  try {
    return typeof localStorage !== "undefined" ? localStorage : null;
  } catch {
    return null;
  }
}

export function serializeAccount(acct: AccountState): string {
  return JSON.stringify(acct);
}

export function deserializeAccount(raw: string | null): AccountState {
  if (!raw) return newAccount();
  try {
    const obj = JSON.parse(raw) as Partial<AccountState>;
    return {
      planId: typeof obj.planId === "string" ? obj.planId : "free",
      credits: Number.isFinite(obj.credits) ? Number(obj.credits) : 0,
      pagesUsedThisCycle: Number.isFinite(obj.pagesUsedThisCycle)
        ? Number(obj.pagesUsedThisCycle)
        : 0,
    };
  } catch {
    return newAccount();
  }
}

export function loadAccount(storage: StorageLike | null = getStorage()): AccountState {
  if (!storage) return newAccount();
  return deserializeAccount(storage.getItem(KEY));
}

export function saveAccount(
  acct: AccountState,
  storage: StorageLike | null = getStorage(),
): void {
  if (!storage) return;
  storage.setItem(KEY, serializeAccount(acct));
}
