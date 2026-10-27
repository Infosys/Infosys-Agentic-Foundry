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
    if (banner) banner.style.display = 'none';
    clearTimeout(warnTimer);
    clearTimeout(logoutTimer);
    warnTimer = setTimeout(function () {
      if (banner) banner.style.display = 'block';
    }, WARN_MS);
    logoutTimer = setTimeout(function () { logout(); }, LOGOUT_MS);
  }

  function teardownIdle() {
    clearTimeout(warnTimer);
    clearTimeout(logoutTimer);
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
    resetIdle();
  }


  function start() {
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
  };
})();
