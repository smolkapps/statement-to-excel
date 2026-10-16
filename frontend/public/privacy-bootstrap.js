/* Runs synchronously before any tracker. Payment tokens stay in this closure. */
(() => {
  const query = new URLSearchParams(location.search);
  const session = query.get("session_id");
  const returning = query.get("checkout") === "success";
  let result = { returning, sessionId: session && /^cs_(test_|live_)?[A-Za-z0-9_]{1,240}$/.test(session) ? session : null };
  let qa = false;
  try { qa = localStorage.getItem("stx_owner_qa") === "on"; } catch { /* no storage required to convert */ }
  let unsafeReferrer = false;
  try {
    const ref = document.referrer && new URL(document.referrer);
    unsafeReferrer = !!ref && (!!ref.search || !!ref.hash || ref.pathname !== "/");
  } catch { unsafeReferrer = true; }
  let unsafeNavigation = false;
  try { unsafeNavigation = performance.getEntriesByType("navigation").some(entry => {
    const url = new URL(entry.name); return !!url.search || !!url.hash || url.pathname !== "/";
  }); } catch { unsafeNavigation = true; }
  const sensitiveEntry = !!location.search || !!location.hash || location.pathname !== "/" || unsafeReferrer || unsafeNavigation;
  // CF can read the ORIGINAL navigation timing URL and document.referrer. It
  // must not load on a sensitive entry, even after replaceState cleans the UI.
  history.replaceState(null, "", "/");
  Object.defineProperty(window, "stxPrivacy", { value: Object.freeze({
    qa, sensitiveEntry,
    takeReturn() { const value = result; result = { returning: false, sessionId: null }; return value; },
  }), configurable: false });
})();
