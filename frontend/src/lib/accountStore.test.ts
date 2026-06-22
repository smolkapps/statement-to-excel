import { describe, expect, it } from "vitest";
import {
  deserializeAccount,
  loadAccount,
  saveAccount,
  serializeAccount,
} from "./accountStore";
import { newAccount } from "./pricing";

function fakeStorage() {
  const map = new Map<string, string>();
  return {
    getItem: (k: string) => map.get(k) ?? null,
    setItem: (k: string, v: string) => {
      map.set(k, v);
    },
  };
}

describe("accountStore", () => {
  it("round-trips an account through serialize/deserialize", () => {
    const acct = { planId: "business", credits: 42, pagesUsedThisCycle: 7 };
    const back = deserializeAccount(serializeAccount(acct));
    expect(back).toEqual(acct);
  });

  it("returns a fresh free account for null/garbage", () => {
    expect(deserializeAccount(null)).toEqual(newAccount());
    expect(deserializeAccount("not json")).toEqual(newAccount());
  });

  it("coerces missing/invalid fields to safe defaults", () => {
    const back = deserializeAccount(JSON.stringify({ credits: "oops" }));
    expect(back.planId).toBe("free");
    expect(back.credits).toBe(0);
    expect(back.pagesUsedThisCycle).toBe(0);
  });

  it("persists and loads via an injected storage", () => {
    const store = fakeStorage();
    const acct = { planId: "firm", credits: 1000, pagesUsedThisCycle: 1 };
    saveAccount(acct, store);
    expect(loadAccount(store)).toEqual(acct);
  });

  it("is a no-op when storage is unavailable", () => {
    expect(() => saveAccount(newAccount(), null)).not.toThrow();
    expect(loadAccount(null)).toEqual(newAccount());
  });
});
