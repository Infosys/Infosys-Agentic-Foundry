/**
 * auth-refresh.js — coordinated access-token refresh (single-flight + cross-tab lock).
 * Funnels every POST /auth/refresh through one coordinator so parallel 401s don't
 * each rotate the refresh token and get each other revoked. Never stores the access
 * token in localStorage (only a timestamp). A tab that finds another tab just
 * refreshed drops its stale in-memory bearer so requests use the fresh httponly
 * cookie (the server prefers a non-empty bearer, so a stale one would 401).
 * Order-independent: pages call window.__iafCoordinatedRefresh() at runtime on a 401.
 */
(function () {
  'use strict';

  if (window.__iafAuthRefreshInstalled) return;
  window.__iafAuthRefreshInstalled = true;

  var RECENT_MS = 8000;              // dedup window for a COMPLETED refresh burst
  var PENDING_TTL_MS = 10000;        // a pending marker older than this => a dead/crashed refresh
  var POLL_MS = 100;
  var LS_KEY = 'iaf_last_refresh';        // "a refresh COMPLETED" marker (timestamp only)
  var PENDING_KEY = 'iaf_refresh_pending'; // "a refresh is IN FLIGHT" marker (timestamp only)

  var priorFetch = window.fetch.bind(window);
  var inFlight = null;
  var cacheBody = null;
  var lastLocalRefreshAt = 0;
  var HAS_WEB_LOCKS = !!(navigator.locks && navigator.locks.request);

  function clearToken() {
    try { if (window.__iafAuth) window.__iafAuth.clear(); } catch (e) {}
  }
  function markLocal() {   // completed
    try { localStorage.setItem(LS_KEY, String(Date.now())); } catch (e) {}
  }
  function markPending() {
    try { localStorage.setItem(PENDING_KEY, String(Date.now())); } catch (e) {}
  }
  function clearPending() {
    try { localStorage.removeItem(PENDING_KEY); } catch (e) {}
  }
  function otherTabRecent(now) {
    try { return (now - parseInt(localStorage.getItem(LS_KEY) || '0', 10)) < RECENT_MS; }
    catch (e) { return false; }
  }
  function otherTabPending(now) {
    try {
      var t = parseInt(localStorage.getItem(PENDING_KEY) || '0', 10);
      return t > 0 && (now - t) < PENDING_TTL_MS;
    } catch (e) { return false; }
  }

  // A deferring tab waits for the leader's in-flight refresh to actually COMPLETE — its
  // completed marker updating — rather than reporting success while the shared cookie is
  // still expired (which would make this tab retry its request and get another 401).
  //
  // Takeover is gated on the leader's OWNERSHIP, not on a fixed waiter timeout: resolve
  // false (take over) only once the leader no longer owns the window — its pending marker
  // was cleared (failed refresh) or has aged past PENDING_TTL_MS (dead/crashed leader).
  // Treating a short waiter timeout as permission to refresh would start a SECOND
  // POST /auth/refresh while the leader is still legitimately mid-flight, rotating the
  // token and getting one of the two revoked — the exact race this coordinator prevents.
  // otherTabPending() ages out at PENDING_TTL_MS so the poll is bounded; the explicit cap
  // is belt-and-braces. (round-6 #4; supersedes round-4 #3)
  function waitForCompletion() {
    return new Promise(function (resolve) {
      var start = Date.now();
      (function poll() {
        var now = Date.now();
        if (otherTabRecent(now)) return resolve(true);       // leader finished
        if (!otherTabPending(now)) return resolve(false);    // leader gone/failed/expired -> take over
        if (now - start >= PENDING_TTL_MS + POLL_MS) return resolve(false);  // safety cap
        setTimeout(poll, POLL_MS);
      })();
    });
  }

  function doFetch(input, init) {
    // Without Web Locks (older Safari / some webviews), claim the refresh window BEFORE the
    // request so a racing tab sees the PENDING marker and waits on us, instead of sending a
    // competing refresh that token rotation would revoke (forcing a logout). Web Locks already
    // serialize this across tabs, so only mark early on the fallback path.
    if (!HAS_WEB_LOCKS) markPending();
    return priorFetch(input || '/auth/refresh', init || { method: 'POST', credentials: 'include' })
      .then(function (r) {
        if (r && r.ok) {
          return r.json().catch(function () { return {}; }).then(function (b) {
            cacheBody = b; lastLocalRefreshAt = Date.now(); markLocal(); clearPending();
            return { ok: true, status: 200, body: b };
          });
        }
        clearPending();   // failed refresh: release the window so a deferring tab can take over
        return { ok: false, status: (r && r.status) || 401, body: null };
      })
      .catch(function () { clearPending(); return { ok: false, status: 401, body: null }; });
  }

  function refreshOnce(input, init) {
    var now = Date.now();
    if (cacheBody && (now - lastLocalRefreshAt) < RECENT_MS) {
      return Promise.resolve({ ok: true, status: 200, body: cacheBody });
    }
    if (otherTabRecent(now)) {
      clearToken();
      return Promise.resolve({ ok: true, status: 200, body: {} });
    }
    // Another tab is mid-refresh: wait for it to COMPLETE before reporting success, so this tab
    // doesn't immediately retry against a still-expired cookie and 401. (round-4 #3)
    if (otherTabPending(now)) {
      return waitForCompletion().then(function (done) {
        if (done) { clearToken(); return { ok: true, status: 200, body: {} }; }
        return doFetch(input, init);
      });
    }
    return doFetch(input, init);
  }

  function withLock(fn) {
    try {
      if (navigator.locks && navigator.locks.request) {
        return navigator.locks.request('iaf-token-refresh', fn);
      }
    } catch (e) {}
    return fn();
  }

  function coordinate(input, init) {
    if (!inFlight) {
      inFlight = Promise.resolve(withLock(function () { return refreshOnce(input, init); }))
        .then(function (res) { inFlight = null; return res; })
        .catch(function () { inFlight = null; return { ok: false, status: 401, body: null }; });
    }
    return inFlight;
  }

  // Returns a fresh Response per caller; shape matches page wrappers (.ok, .json()).
  window.__iafCoordinatedRefresh = function (input, init) {
    return coordinate(input, init).then(function (res) {
      var payload = res.body == null ? '' : JSON.stringify(res.body);
      return new Response(payload, { status: res.status, headers: { 'Content-Type': 'application/json' } });
    });
  };
})();
