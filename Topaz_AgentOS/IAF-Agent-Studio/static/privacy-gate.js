/*
 * privacy-gate.js — App-shell Data Privacy acknowledgement gate.
 *
 * Complements login.html's gateThenRedirect(): that flow only covers users who
 * arrive through the post-login redirect. This module covers users who reach an
 * authenticated app page directly (deep-link, bookmark, refresh) with a
 * valid-but-unaccepted token, who would otherwise get opaque 403
 * {"detail":"PRIVACY_ACK_REQUIRED"} from /api/* with no way to accept.
 *
 * Behaviour is entirely driven by GET /auth/privacy/status: the blocking overlay
 * only renders when it reports {required:true, accepted:false}, which the server
 * only returns when PRIVACY_ACK_REQUIRED=true. With the flag off (default) this
 * module makes one status request that returns {required:false} and does nothing
 * — no visible change and no interaction blocking.
 *
 * SEC-6: identity lives in an httponly `iaf_access_token` cookie this script
 * cannot and must not read; requests are authenticated via `credentials:
 * 'include'`, same as dashboard_v2.html and session-controls.js.
 *
 * Dependency-free (no Alpine/Tailwind), idempotent, and fully wrapped in
 * try/catch so a script error can never break the host page.
 */
(function () {
  "use strict";

  var OVERLAY_ID = "iaf-privacy-gate-overlay";
  var USER_KEY = "iaf_user";

  // Prefix same-origin absolute paths with the deployment base path, exactly
  // like the rest of the app (see shared/base_path.py). withBase is idempotent,
  // so this is safe even when the base-path fetch shim is also active.
  function base() {
    try {
      return window.__BASE_PATH__ || "";
    } catch (e) {
      return "";
    }
  }

  function url(path) {
    return base() + path;
  }

  function signOut() {
    var done = function () {
      try {
        window.location.href = url("/login");
      } catch (e) {
        window.location.href = "/login";
      }
    };
    try {
      // SEC-6: httponly cookie is sent automatically; the server clears it.
      fetch(url("/auth/logout"), { method: "POST", credentials: "include" })
        .catch(function () {
          /* ignore network errors — still redirect below */
        })
        .then(done);
    } catch (e) {
      done();
    }
    try {
      localStorage.removeItem(USER_KEY);
    } catch (e) {
      /* ignore */
    }
  }

  function removeOverlay() {
    var el = document.getElementById(OVERLAY_ID);
    if (el && el.parentNode) {
      el.parentNode.removeChild(el);
    }
    try {
      document.documentElement.style.overflow = "";
      document.body.style.overflow = "";
    } catch (e) {
      /* ignore */
    }
  }

  function injectStyle() {
    if (document.getElementById(OVERLAY_ID + "-style")) return;
    var style = document.createElement("style");
    style.id = OVERLAY_ID + "-style";
    if (window.__CSP_NONCE__) style.setAttribute("nonce", window.__CSP_NONCE__);
    style.textContent =
      "#" + OVERLAY_ID + "{position:fixed;inset:0;z-index:2147483000;" +
      "background:rgba(3,7,18,0.92);display:flex;align-items:center;" +
      "justify-content:center;padding:24px;" +
      "font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;}" +
      "#" + OVERLAY_ID + " .iaf-pg-panel{width:100%;max-width:640px;max-height:90vh;" +
      "display:flex;flex-direction:column;background:#0f172a;color:#e2e8f0;" +
      "border:1px solid #1e293b;border-radius:12px;box-shadow:0 20px 60px rgba(0,0,0,0.6);overflow:hidden;}" +
      "#" + OVERLAY_ID + " .iaf-pg-head{padding:20px 24px 12px;border-bottom:1px solid #1e293b;}" +
      "#" + OVERLAY_ID + " .iaf-pg-title{margin:0;font-size:18px;font-weight:600;color:#f8fafc;}" +
      "#" + OVERLAY_ID + " .iaf-pg-sub{margin:6px 0 0;font-size:12px;color:#94a3b8;}" +
      "#" + OVERLAY_ID + " .iaf-pg-body{padding:16px 24px;overflow:auto;flex:1;}" +
      "#" + OVERLAY_ID + " .iaf-pg-notice{margin:0;white-space:pre-wrap;word-break:break-word;" +
      "font-size:13px;line-height:1.5;color:#cbd5e1;" +
      "font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;}" +
      "#" + OVERLAY_ID + " .iaf-pg-foot{padding:16px 24px 20px;border-top:1px solid #1e293b;}" +
      "#" + OVERLAY_ID + " .iaf-pg-check{display:flex;gap:8px;align-items:flex-start;" +
      "font-size:13px;color:#e2e8f0;cursor:pointer;}" +
      "#" + OVERLAY_ID + " .iaf-pg-check input{margin-top:2px;}" +
      "#" + OVERLAY_ID + " .iaf-pg-err{margin:10px 0 0;font-size:12px;color:#f87171;}" +
      "#" + OVERLAY_ID + " .iaf-pg-actions{display:flex;gap:10px;justify-content:flex-end;" +
      "margin-top:16px;flex-wrap:wrap;}" +
      "#" + OVERLAY_ID + " button{font:inherit;border-radius:8px;padding:9px 16px;cursor:pointer;border:1px solid transparent;}" +
      "#" + OVERLAY_ID + " .iaf-pg-accept{background:#2563eb;color:#fff;border-color:#2563eb;}" +
      "#" + OVERLAY_ID + " .iaf-pg-accept:disabled{opacity:0.5;cursor:not-allowed;}" +
      "#" + OVERLAY_ID + " .iaf-pg-signout{background:transparent;color:#94a3b8;border-color:#334155;}";
    document.head.appendChild(style);
  }

  function renderOverlay(notice) {
    if (document.getElementById(OVERLAY_ID)) return; // idempotent
    injectStyle();

    var title = (notice && notice.title) || "Data Privacy Notice";
    var version = (notice && notice.version) || "";
    var markdown =
      (notice && notice.markdown) ||
      "Unable to load the privacy notice. Please contact your administrator.";

    var overlay = document.createElement("div");
    overlay.id = OVERLAY_ID;
    overlay.setAttribute("role", "dialog");
    overlay.setAttribute("aria-modal", "true");

    // Build DOM with textContent only — never inject the notice as HTML.
    var panel = document.createElement("div");
    panel.className = "iaf-pg-panel";

    var head = document.createElement("div");
    head.className = "iaf-pg-head";
    var h = document.createElement("h2");
    h.className = "iaf-pg-title";
    h.textContent = title;
    var sub = document.createElement("p");
    sub.className = "iaf-pg-sub";
    sub.textContent =
      (version ? "Version " + version + " · " : "") +
      "You must accept to continue.";
    head.appendChild(h);
    head.appendChild(sub);

    var body = document.createElement("div");
    body.className = "iaf-pg-body";
    var pre = document.createElement("pre");
    pre.className = "iaf-pg-notice";
    pre.textContent = markdown; // text, not HTML
    body.appendChild(pre);

    var foot = document.createElement("div");
    foot.className = "iaf-pg-foot";

    var label = document.createElement("label");
    label.className = "iaf-pg-check";
    var checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    var checkText = document.createElement("span");
    checkText.textContent =
      "I have read and understood the data privacy notice and declaration.";
    label.appendChild(checkbox);
    label.appendChild(checkText);

    var err = document.createElement("div");
    err.className = "iaf-pg-err";
    err.style.display = "none";

    var actions = document.createElement("div");
    actions.className = "iaf-pg-actions";
    var signout = document.createElement("button");
    signout.type = "button";
    signout.className = "iaf-pg-signout";
    signout.textContent = "Sign out";
    var accept = document.createElement("button");
    accept.type = "button";
    accept.className = "iaf-pg-accept";
    accept.textContent = "I have read and accept";
    accept.disabled = true;

    actions.appendChild(signout);
    actions.appendChild(accept);

    foot.appendChild(label);
    foot.appendChild(err);
    foot.appendChild(actions);

    panel.appendChild(head);
    panel.appendChild(body);
    panel.appendChild(foot);
    overlay.appendChild(panel);
    document.body.appendChild(overlay);

    // Lock scrolling of the page behind the overlay.
    try {
      document.documentElement.style.overflow = "hidden";
      document.body.style.overflow = "hidden";
    } catch (e) {
      /* ignore */
    }

    checkbox.addEventListener("change", function () {
      accept.disabled = !checkbox.checked;
    });

    signout.addEventListener("click", function () {
      signOut();
    });

    accept.addEventListener("click", function () {
      if (checkbox.checked === false) return;
      err.style.display = "none";
      accept.disabled = true;
      accept.textContent = "Recording…";
      fetch(url("/auth/privacy/accept"), {
        method: "POST",
        credentials: "include",
        headers: {
          "Content-Type": "application/json",
        },
      })
        .then(function (r) {
          if (!r.ok) {
            return r
              .json()
              .catch(function () {
                return {};
              })
              .then(function (d) {
                throw new Error(
                  (d && d.detail) ||
                    "Could not record acceptance. Please try again."
                );
              });
          }
          removeOverlay();
          window.location.reload();
        })
        .catch(function (e) {
          err.textContent =
            (e && e.message) ||
            "Network error recording acceptance. Please try again.";
          err.style.display = "block";
          accept.disabled = !checkbox.checked;
          accept.textContent = "I have read and accept";
        });
    });
  }

  function runGate() {
    try {
      if (document.getElementById(OVERLAY_ID)) return; // already up

      // SEC-6: no client-readable token to pre-check; the httponly cookie is
      // sent automatically. An unauthenticated caller gets a non-ok response
      // below, which fails open (no gate), same as before.
      fetch(url("/auth/privacy/status"), { credentials: "include" })
        .then(function (r) {
          if (!r.ok) return null; // fail-open
          return r.json();
        })
        .then(function (status) {
          // Fail-open: only gate on an explicit required && !accepted.
          if (!status || !status.required || status.accepted) return;
          return fetch(url("/auth/privacy/notice"))
            .then(function (r) {
              return r.ok ? r.json() : null;
            })
            .catch(function () {
              return null;
            })
            .then(function (notice) {
              renderOverlay(notice);
            });
        })
        .catch(function () {
          // Never block the app on a network/status hiccup.
        });
    } catch (e) {
      // A gate error must never break the host page.
    }
  }

  try {
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", runGate);
    } else {
      runGate();
    }
  } catch (e) {
    /* ignore */
  }
})();
