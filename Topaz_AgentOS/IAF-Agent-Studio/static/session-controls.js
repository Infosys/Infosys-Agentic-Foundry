/**
 * Shared session controls (WS-3) — user menu + SEC-7 idle timeout.
 *
 * Include on any authenticated page with a single tag:
 *     <script src="/static/session-controls.js"></script>
 *
 * The idle timer installs unconditionally. The user menu renders only if the page
 * provides a mount point:
 *     <div data-session-controls></div>
 *
 * Why this is a shared module and not copied per page: before WS-3 the SEC-7 idle
 * timeout lived inside index.html's Alpine component, so an operator parked on the
 * Workstreams, Studio, Twin, or detail pages was never signed out — SEC-7 was only
 * partly satisfied. Six divergent copies of a security control is the failure mode
 * this file exists to prevent.
 *
 * Framework-free by design (same idiom as ask-twin.js / privacy-gate.js) so it can
 * be dropped onto Alpine and non-Alpine pages alike.
 *
 * SEC-6: identity comes from the readable `iaf_user` cookie; the access token lives
 * in an httponly cookie this script cannot and must not read.
 */
(function () {
  'use strict';

  if (window.__iafSessionControlsInstalled) return;
  window.__iafSessionControlsInstalled = true;

  // Fallback defaults if GET /auth/session-policy is unreachable; keep in sync with shared/config.py.
  var WARN_MS = 15 * 60 * 1000;
  var LOGOUT_MS = 20 * 60 * 1000;
  var LOGIN_URL = '/static/login.html';

  // ── SEC-7 idle hardening: run-gating, cross-tab activity sync, cross-tab logout (Bugs 1,2,4) ──
  var activeRuns = 0;
  var ABSOLUTE_MAX_MS = LOGOUT_MS * 6;      // absolute cap so a wedged run can't hold a session forever
  var idleSince = Date.now();

  var ACTIVITY_KEY = 'iaf_last_activity';   // cross-tab idle-activity sync (Bug 2)
  var LOGOUT_KEY = 'iaf_logout';            // cross-tab logout broadcast (Bug 4)
  var _lastBroadcast = 0;
  var _applyingRemote = false;

  // Frames that are NOT the user's active agent run: keep-alive pings plus unsolicited
  // background broadcasts (dashboard snapshots, HITL-queue / task / ingestion / deployment
  // events) that arrive on an idle page. These must not reset the idle timer or keep sibling
  // tabs signed in. Genuine run frames (response/status/routing/token/tool_*/text/progress…)
  // are NOT listed, so they still count — and an unknown type counts too, so a real run is
  // never force-logged-out by mistake. (#8, preserving Bug 1)
  // Only UNAMBIGUOUS dashboard data-refresh broadcasts. Deliberately NOT listing hitl_* /
  // task_* / approval frames: a user's own agent run can legitimately emit those (e.g. a run
  // pausing on a HITL approval), and ignoring them could let a genuine run time out. Better to
  // keep an unattended dashboard alive a bit longer than to log a user out mid-run.
  var IDLE_IGNORE_TYPES = {
    ping: 1, pong: 1, heartbeat: 1,
    snapshot: 1, directory: 1, deployment: 1, taxonomy: 1, hierarchy: 1, demo_seeded: 1,
    item_created: 1, item_updated: 1, items_ingested: 1, overdue_risk: 1, debit_balance: 1
  };

  // Treat streamed WebSocket frames (agent runs, silent tool output) as activity so a
  // long, silent run is not force-logged-out mid-task. Wrap window.WebSocket once, globally.
  function installWsHook() {
    if (typeof window.WebSocket !== 'function' || window.__iafWsIdleHooked) return;
    window.__iafWsIdleHooked = true;
    var NativeWS = window.WebSocket;
    function WrappedWS(url, protocols) {
      var ws = protocols === undefined ? new NativeWS(url) : new NativeWS(url, protocols);
      ws.addEventListener('message', function (ev) {
        var t;
        try { t = JSON.parse(ev.data).type; } catch (e) { resetIdle(); return; }  // non-JSON frame — treat as activity
        // Ignore keep-alive + unsolicited background broadcasts (see IDLE_IGNORE_TYPES);
        // everything else (the user's streamed run) counts as activity. (#8)
        if (IDLE_IGNORE_TYPES[t]) return;
        resetIdle();
      });
      return ws;
    }
    WrappedWS.prototype = NativeWS.prototype;
    ['CONNECTING', 'OPEN', 'CLOSING', 'CLOSED'].forEach(function (k) {
      try { WrappedWS[k] = NativeWS[k]; } catch (e) {}
    });
    window.WebSocket = WrappedWS;
  }
  installWsHook();

  function broadcastActivity() {
    var now = Date.now();
    if (now - _lastBroadcast < 5000) return;      // throttle writes
    _lastBroadcast = now;
    try { localStorage.setItem(ACTIVITY_KEY, String(now)); } catch (e) {}
  }

  // A remote broadcast resets this tab WITHOUT echoing back (Bug 2).
  function onRemoteActivity() {
    _applyingRemote = true;
    try { resetIdle(); } finally { _applyingRemote = false; }
  }

  function broadcastLogout() {
    try { localStorage.setItem(LOGOUT_KEY, String(Date.now())); } catch (e) {}
  }

  // Another tab already cleared the cookie/IdP session: tear down locally only
  // (no second /auth/logout — that would double-trigger RP-initiated Keycloak logout).
  function remoteLogout() {
    if (loggingOut) return;
    loggingOut = true;
    teardownIdle();
    try { if (window.__iafAuth) window.__iafAuth.clear(); } catch (e) {}
    window.location.href = (window.__BASE_PATH__ || '') + LOGIN_URL;
  }

  // Cross-tab run lease: a tab with an active run publishes a short lease so sibling
  // tabs defer their idle logout too (#9/#10). Bounded — it expires LEASE_MS after the
  // last write, and the absolute cap below still applies, so a wedged run can't hold on.
  var RUN_LEASE_KEY = 'iaf_run_lease';
  var LEASE_MS = 45 * 1000;
  var _leaseRenewTimer = null;
  function writeRunLease() { try { localStorage.setItem(RUN_LEASE_KEY, String(Date.now())); } catch (e) {} }
  function runLeaseActive() {
    try { return (Date.now() - parseInt(localStorage.getItem(RUN_LEASE_KEY) || '0', 10)) < LEASE_MS; }
    catch (e) { return false; }
  }
  // Renew the lease well within LEASE_MS so a silent run never lets it lapse and a sibling
  // tab sign both out mid-run (#7). Stops when no run is active or the absolute cap is hit.
  function startLeaseRenew() {
    if (_leaseRenewTimer) return;
    _leaseRenewTimer = setInterval(function () {
      if (activeRuns <= 0 || (Date.now() - idleSince) >= ABSOLUTE_MAX_MS) { stopLeaseRenew(); return; }
      writeRunLease();
    }, 20 * 1000);
  }
  function stopLeaseRenew() {
    if (_leaseRenewTimer) { clearInterval(_leaseRenewTimer); _leaseRenewTimer = null; }
  }

  // Pages bracket a run (HTTP or WebSocket) with these so it counts as activity across its
  // whole lifecycle — completion, error and cancellation must all call endRun().
  function beginRun() { activeRuns++; writeRunLease(); startLeaseRenew(); resetIdle(); }
  function endRun() { if (activeRuns > 0) activeRuns--; if (activeRuns === 0) stopLeaseRenew(); resetIdle(); }

  // The idle timeout fires this, not logout() directly: defer while a run is in flight
  // in THIS tab (activeRuns) or ANY tab (the cross-tab lease), bounded by ABSOLUTE_MAX_MS
  // so a wedged run can't hold the session open forever.
  function maybeLogout() {
    if (loggingOut) return;
    if ((activeRuns > 0 || runLeaseActive()) && (Date.now() - idleSince) < ABSOLUTE_MAX_MS) {
      if (activeRuns > 0) writeRunLease();   // keep the lease fresh for sibling tabs
      logoutTimer = setTimeout(maybeLogout, 30 * 1000);   // re-check, don't log out yet
      return;
    }
    logout();
  }

  var STYLE_ID = 'iaf-session-controls-css';
  var CSS = [
    '.iaf-session{position:relative;display:inline-flex;align-items:center;gap:8px;}',
    '.iafsc-trigger{display:inline-flex;align-items:center;gap:6px;background:transparent;',
    'border:1px solid rgba(127,127,127,.35);border-radius:6px;color:inherit;',
    'font:inherit;font-size:12px;padding:4px 10px;cursor:pointer;}',
    '.iafsc-dot{width:6px;height:6px;border-radius:999px;background:#3fb950;}',
    '.iafsc-menu{position:absolute;right:0;top:calc(100% + 6px);min-width:200px;z-index:9999;',
    'background:#161b22;border:1px solid rgba(127,127,127,.35);border-radius:8px;',
    'box-shadow:0 8px 24px rgba(0,0,0,.45);overflow:hidden;}',
    '.iafsc-menu-head{padding:8px 12px;border-bottom:1px solid rgba(127,127,127,.25);}',
    '.iafsc-menu-name{font:600 12px/1.4 system-ui,sans-serif;color:#e6edf3;}',
    '.iafsc-menu-email{font:11px/1.4 system-ui,sans-serif;color:#8b949e;}',
    '.iafsc-menu-item{width:100%;text-align:left;background:transparent;border:0;color:#e6edf3;',
    'font:12px/1.4 system-ui,sans-serif;padding:9px 12px;cursor:pointer;}',
    '.iafsc-menu-item.iafsc-danger{color:#f85149;}',
    '.iafsc-dialog{width:100%;max-width:560px;max-height:80vh;overflow:auto;background:#161b22;',
    'border:1px solid rgba(127,127,127,.35);border-radius:10px;padding:16px;',
    'font:12px/1.5 system-ui,sans-serif;color:#e6edf3;}',
    '.iafsc-dialog-head{display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;}',
    '.iafsc-dialog-title{font-weight:600;font-size:14px;}',
    '.iafsc-close{background:transparent;border:0;color:#8b949e;font-size:18px;cursor:pointer;}',
    '.iafsc-dialog-foot{margin-top:12px;text-align:right;}',
    '.iafsc-danger-btn{background:transparent;border:1px solid rgba(248,81,73,.5);color:#f85149;',
    'border-radius:6px;font:inherit;padding:4px 12px;cursor:pointer;}',
    '.iafsc-row{display:flex;gap:12px;align-items:flex-start;justify-content:space-between;',
    'padding:10px 0;border-bottom:1px solid rgba(127,127,127,.2);}',
    '.iafsc-row-main{min-width:0;}',
    '.iafsc-ua{color:#e6edf3;word-break:break-word;}',
    '.iafsc-current{color:#3fb950;font-weight:600;}',
    '.iafsc-meta{color:#8b949e;font-size:11px;}',
    '.iafsc-revoke{flex:none;background:transparent;border:1px solid rgba(248,81,73,.5);',
    'color:#f85149;border-radius:6px;font:inherit;font-size:11px;padding:3px 10px;cursor:pointer;}',
    '.iafsc-muted{color:#8b949e;}',
    '.iafsc-error{color:#f85149;}',
    '.iafsc-dismiss{background:rgba(255,255,255,.2);border:1px solid rgba(255,255,255,.4);',
    'color:#fff;border-radius:6px;padding:2px 10px;cursor:pointer;}',
  ].join('');

  function injectStyles() {
    if (document.getElementById(STYLE_ID)) return;
    var el = document.createElement('style');
    el.id = STYLE_ID;
    if (window.__CSP_NONCE__) el.setAttribute('nonce', window.__CSP_NONCE__);
    el.textContent = CSS;
    (document.head || document.documentElement).appendChild(el);
  }

  function loadSessionPolicy() {
    return fetch('/auth/session-policy', { credentials: 'include' })
      .then(function (r) { return r && r.ok ? r.json() : null; })
      .then(function (p) {
        var warnMin = Number(p && p.idle_warn_minutes);
        var logoutMin = Number(p && p.idle_logout_minutes);
        if (warnMin > 0 && logoutMin > 0 && warnMin < logoutMin) {
          WARN_MS = warnMin * 60 * 1000;
          LOGOUT_MS = logoutMin * 60 * 1000;
          // Recompute the run cap from the policy's logout timeout (it was seeded from the
          // fallback at load). Otherwise a 60-min idle policy would still cap silent runs at
          // 120 min here while index.html derives 360 min, and the shared logout broadcast
          // would then sign out the running index tab too. (#8-cap)
          ABSOLUTE_MAX_MS = LOGOUT_MS * 6;
        }
      })
      .catch(function () { /* keep built-in defaults above */ });
  }


  function readUser() {
    try {
      var row = document.cookie.split('; ').find(function (r) {
        return r.indexOf('iaf_user=') === 0;
      });
      if (!row) return null;
      return JSON.parse(decodeURIComponent(row.replace(/^iaf_user=/, '')));
    } catch (e) {
      return null;
    }
  }

  function escapeHtml(value) {
    return String(value == null ? '' : value)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }


  var loggingOut = false;

  function logout() {
    // Guard against the idle timer and a user click racing each other.
    if (loggingOut) return;
    loggingOut = true;
    broadcastLogout();          // sign out every other open tab (Bug 4)
    teardownIdle();

    // A hard location.href assignment is not shimmed by shared/base_path.py, so apply window.__BASE_PATH__ here.
    var done = function () {
      window.location.href = (window.__BASE_PATH__ || '') + LOGIN_URL;
    };

    try {
      var p = fetch('/auth/logout', { method: 'POST', credentials: 'include' });
      if (p && typeof p.then === 'function') {
        p.then(function (r) {
          return r && r.ok ? r.json().catch(function () { return {}; }) : {};
        })
          .then(function (data) {
            // Honour an IdP front-channel logout when the server asks for one,
            // otherwise fall back to the local login page.
            if (data && data.keycloak_logout_url) {
              window.location.href = data.keycloak_logout_url;
              return;
            }
            done();
          })
          .catch(done);
        return;
      }
    } catch (e) { /* fall through to local redirect */ }

    done();
  }

  // The server owns the session rules (auth/session_registry.py); this only calls the API and renders.

  function signOutEverywhere() {
    if (!window.confirm('Sign out of all devices, including this one?')) return;
    fetch('/auth/logout-all', { method: 'POST', credentials: 'include' })
      .then(function (r) {
        if (r && r.ok) {
          return r.json().catch(function () { return {}; }).then(function (data) {
            // Server already cleared the cookies; honour an IdP logout if asked.
            if (data && data.keycloak_logout_url) {
              loggingOut = true;
              teardownIdle();
              window.location.href = data.keycloak_logout_url;
              return;
            }
            logout();
          });
        }
        // 401: this session had already ended; the normal logout still clears it.
        if (r && r.status === 401) { logout(); return; }
        window.alert('Could not sign out of all devices. Please try again.');
      })
      .catch(function () {
        window.alert('Could not sign out of all devices. Please try again.');
      });
  }

  function formatTime(iso) {
    if (!iso) return '';
    var d = new Date(iso);
    return isNaN(d.getTime()) ? '' : d.toLocaleString();
  }

  var sessionsModal = null;

  function closeSessions() {
    if (sessionsModal) { sessionsModal.remove(); sessionsModal = null; }
  }

  function renderSessions(body, sessions) {
    if (!sessions.length) {
      body.innerHTML = '<div class="iafsc-muted">No active sessions found.</div>';
      return;
    }
    body.innerHTML = sessions.map(function (s) {
      return '<div class="iafsc-row">' +
          '<div class="iafsc-row-main">' +
            '<div class="iafsc-ua">' + escapeHtml(s.user_agent || 'Unknown browser') +
              (s.current ? ' <span class="iafsc-current">(this device)</span>' : '') + '</div>' +
            '<div class="iafsc-meta">' +
              escapeHtml(s.ip || 'unknown IP') +
              ' · signed in ' + escapeHtml(formatTime(s.created_at)) +
              ' · last active ' + escapeHtml(formatTime(s.last_seen_at)) +
            '</div>' +
          '</div>' +
          (s.current ? '' :
            '<button type="button" class="iafsc-revoke" data-session-revoke="' + escapeHtml(s.id) + '">Sign out</button>') +
        '</div>';
    }).join('');
  }

  function loadSessions(body) {
    body.innerHTML = '<div class="iafsc-muted">Loading…</div>';
    fetch('/auth/sessions', { credentials: 'include' })
      .then(function (r) {
        if (!r.ok) throw new Error('HTTP ' + r.status);
        return r.json();
      })
      .then(function (d) { renderSessions(body, (d && d.sessions) || []); })
      .catch(function () {
        body.innerHTML = '<div class="iafsc-error">Could not load sessions.</div>';
      });
  }

  function openSessions() {
    closeSessions();
    var overlay = document.createElement('div');
    overlay.setAttribute('role', 'dialog');
    overlay.setAttribute('aria-modal', 'true');
    overlay.setAttribute('aria-label', 'Active sessions');
    overlay.style.cssText = 'position:fixed;inset:0;z-index:10001;background:rgba(0,0,0,.55);' +
      'display:flex;align-items:center;justify-content:center;padding:16px;';
    overlay.innerHTML =
      '<div class="iafsc-dialog">' +
        '<div class="iafsc-dialog-head">' +
          '<div class="iafsc-dialog-title">Active sessions</div>' +
          '<button type="button" class="iafsc-close" data-sessions-close aria-label="Close">&times;</button>' +
        '</div>' +
        '<div data-sessions-body></div>' +
        '<div class="iafsc-dialog-foot">' +
          '<button type="button" class="iafsc-danger-btn" data-sessions-all>Sign out of all devices</button>' +
        '</div>' +
      '</div>';
    document.body.appendChild(overlay);
    sessionsModal = overlay;

    var body = overlay.querySelector('[data-sessions-body]');
    overlay.addEventListener('click', function (e) {
      if (e.target === overlay || e.target.closest('[data-sessions-close]')) { closeSessions(); return; }
      if (e.target.closest('[data-sessions-all]')) { signOutEverywhere(); return; }
      var revoke = e.target.closest('[data-session-revoke]');
      if (!revoke) return;
      revoke.disabled = true;
      fetch('/auth/sessions/' + encodeURIComponent(revoke.getAttribute('data-session-revoke')), {
        method: 'DELETE', credentials: 'include',
      })
        .then(function (r) {
          if (!r.ok) window.alert('Could not sign out that session.');
          loadSessions(body);
        })
        .catch(function () { revoke.disabled = false; });
    });
    loadSessions(body);
  }


  function renderMenu(mount, user) {
    var name = (user && (user.display_name || user.email || user.user_id)) || 'Signed in';
    var email = (user && user.email) || '';

    mount.innerHTML =
      '<div class="iaf-session">' +
        '<button type="button" class="iafsc-trigger" data-session-menu-trigger' +
          ' aria-haspopup="true" aria-expanded="false">' +
          '<span class="iafsc-dot"></span>' +
          '<span data-session-user-name>' + escapeHtml(name) + '</span>' +
        '</button>' +
        '<div class="iafsc-menu" data-session-menu hidden>' +
          '<div class="iafsc-menu-head">' +
            '<div class="iafsc-menu-name">' + escapeHtml(name) + '</div>' +
            '<div class="iafsc-menu-email" data-session-user-email>' + escapeHtml(email) + '</div>' +
          '</div>' +
          '<button type="button" class="iafsc-menu-item" data-session-list>' +
            'Active sessions' +
          '</button>' +
          '<button type="button" class="iafsc-menu-item" data-session-logout-all>' +
            'Sign out of all devices' +
          '</button>' +
          '<button type="button" class="iafsc-menu-item iafsc-danger" data-session-logout>' +
            'Sign Out' +
          '</button>' +
        '</div>' +
      '</div>';

    var trigger = mount.querySelector('[data-session-menu-trigger]');
    var menu = mount.querySelector('[data-session-menu]');

    function setOpen(open) {
      menu.hidden = !open;
      trigger.setAttribute('aria-expanded', open ? 'true' : 'false');
    }

    trigger.addEventListener('click', function (e) {
      e.stopPropagation();
      setOpen(menu.hidden);
    });
    mount.querySelector('[data-session-logout]').addEventListener('click', function (e) {
      e.preventDefault();
      logout();
    });
    mount.querySelector('[data-session-list]').addEventListener('click', function (e) {
      e.preventDefault();
      setOpen(false);
      openSessions();
    });
    mount.querySelector('[data-session-logout-all]').addEventListener('click', function (e) {
      e.preventDefault();
      setOpen(false);
      signOutEverywhere();
    });
    document.addEventListener('click', function (e) {
      if (!mount.contains(e.target)) setOpen(false);
    });
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') { setOpen(false); closeSessions(); }
    });
  }

  function mountMenu() {
    var mount = document.querySelector('[data-session-controls]');
    if (!mount) return;              // page opted out of the menu; timer still runs
    renderMenu(mount, readUser());
  }


  var warnTimer = null;
  var logoutTimer = null;
  var banner = null;
  var idleListenerTargets = [];
  var ACTIVITY = ['mousemove', 'keydown', 'click', 'touchstart', 'scroll'];

  function buildBanner() {
    var el = document.getElementById('idle-warn-banner');
    if (el) return el;

    el = document.createElement('div');
    el.id = 'idle-warn-banner';
    // The banner is inserted hidden then shown; role=alert plus aria-live make assistive tech announce it.
    el.setAttribute('role', 'alert');
    el.setAttribute('aria-live', 'assertive');
    el.style.cssText = 'display:none;position:fixed;top:0;left:0;right:0;z-index:10000;' +
      'background:#b45309;color:#fff;text-align:center;padding:10px 16px;' +
      'font:600 13px/1.4 system-ui,sans-serif;box-shadow:0 2px 8px rgba(0,0,0,.4);';
    el.innerHTML = 'Your session will expire in 2 minutes due to inactivity. ' +
      '<button type="button" class="iafsc-dismiss" id="idle-dismiss-btn">Dismiss</button>';
    document.body.appendChild(el);
    el.querySelector('#idle-dismiss-btn').addEventListener('click', function () {
      el.style.display = 'none';
    });
    return el;
  }

  function resetIdle() {
    if (loggingOut) return;
    idleSince = Date.now();
    if (banner) banner.style.display = 'none';
    clearTimeout(warnTimer);
    clearTimeout(logoutTimer);
    warnTimer = setTimeout(function () {
      if (banner) banner.style.display = 'block';
    }, WARN_MS);
    logoutTimer = setTimeout(maybeLogout, LOGOUT_MS);
    if (!_applyingRemote) broadcastActivity();   // tell other tabs we're active (Bug 2)
    if (activeRuns > 0) writeRunLease();          // keep a run lease fresh for sibling tabs (#9)
  }

  function teardownIdle() {
    clearTimeout(warnTimer);
    clearTimeout(logoutTimer);
    stopLeaseRenew();
    idleListenerTargets.forEach(function (t) {
      document.removeEventListener(t, resetIdle);
    });
    idleListenerTargets = [];
    if (banner) banner.style.display = 'none';
  }

  function installIdle() {
    banner = buildBanner();
    ACTIVITY.forEach(function (evt) {
      document.addEventListener(evt, resetIdle, { passive: true });
      idleListenerTargets.push(evt);
    });
    // Cross-tab coordination: another tab's activity resets us (Bug 2); its logout
    // tears us down locally (Bug 4). storage events fire only in OTHER tabs — no self-echo.
    window.addEventListener('storage', function (e) {
      if (!e) return;
      if (e.key === ACTIVITY_KEY) onRemoteActivity();
      else if (e.key === LOGOUT_KEY) remoteLogout();
    });
    resetIdle();
  }


  function start() {
    installWsHook();
    injectStyles();
    mountMenu();
    // Install the timer with built-in defaults first, then re-arm if the server returns different values.
    installIdle();
    loadSessionPolicy().then(function () {
      if (!loggingOut) resetIdle();
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', start);
  } else {
    start();
  }

  // Narrow surface for pages that need to trigger logout themselves.
  window.IafSessionControls = {
    logout: logout,
    showSessions: openSessions,
    signOutEverywhere: signOutEverywhere,
    resetIdle: resetIdle,
    beginRun: beginRun,
    endRun: endRun,
  };
})();
