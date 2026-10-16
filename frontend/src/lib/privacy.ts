export interface CheckoutReturn { returning: boolean; sessionId: string | null }
declare global {
  interface Window {
    stxPrivacy?: { qa: boolean; sensitiveEntry: boolean; takeReturn: () => CheckoutReturn };
  }
}

// Drain before main.tsx loads any third-party script. StrictMode reads this
// module-private value twice; trackers can no longer read the global return.
const checkoutReturn = window.stxPrivacy?.takeReturn();
export function analyticsReady(): boolean {
  return !!checkoutReturn && location.pathname === '/' && !location.search && !location.hash;
}
let fallbackReturn: CheckoutReturn | undefined;

/** Fallback for isolated component tests; production runs the blocking bootstrap. */
export function captureCheckoutReturn(): CheckoutReturn {
  if (checkoutReturn) return checkoutReturn;
  if (fallbackReturn) return fallbackReturn;
  const params = new URLSearchParams(location.search);
  const session = params.get("session_id");
  const result = { returning: params.get("checkout") === "success", sessionId: session && /^cs_(test_|live_)?[A-Za-z0-9_]{1,240}$/.test(session) ? session : null };
  history.replaceState(null, "", "/");
  // StrictMode repeats initialization synchronously. Preserve the private
  // capture for this render, then leave lifetime ownership in App state.
  fallbackReturn = result;
  queueMicrotask(() => { fallbackReturn = undefined; });
  return result;
}

export function ownerQA(): boolean {
  try { return window.stxPrivacy?.qa === true || localStorage.getItem("stx_owner_qa") === "on"; }
  catch { return false; }
}

export function persistentAccount(accountId: string): boolean {
  try {
    if (localStorage.getItem("stx_account_id") !== accountId) return false;
    const probe = crypto.randomUUID();
    localStorage.setItem("stx_storage_check", probe);
    const durable = localStorage.getItem("stx_storage_check") === probe;
    localStorage.removeItem("stx_storage_check");
    return durable;
  } catch { return false; }
}
