(function () {
  const STORAGE_PREFIX = "iaf_ask_twin_messages:";
  const MAX_MESSAGES = 24;

  const MAX_STORED_CONTENT = 20000;
  const MAX_STORED_KEYS = 12;
  const STORED_ROLES = ["user", "assistant"];

  const CHAT_ENDPOINT = "/api/chat";

  function twinIcon(size) {
    return (
      `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" ` +
      `xmlns="http://www.w3.org/2000/svg" aria-hidden="true" focusable="false">` +
      `<path d="M12 2.5l1.7 4.6 4.6 1.7-4.6 1.7L12 15.1l-1.7-4.6L5.7 8.8l4.6-1.7L12 2.5z" fill="currentColor"/>` +
      `<path d="M18.6 13.5l.85 2.3 2.3.85-2.3.85-.85 2.3-.85-2.3-2.3-.85 2.3-.85.85-2.3z" fill="currentColor"/>` +
      `</svg>`
    );
  }

  const state = {
    open: false,
    ws: null,
    wsConnected: false,
    typing: false,
    typingStatus: "Thinking...",
    messages: [],
    streamingIndex: -1,
    docked: false,
  };

  const els = {};

  function storageKey() {
    return `${STORAGE_PREFIX}shared`;
  }

  function escapeHtml(value) {
    return String(value || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function sanitizeHtml(html) {
    const template = document.createElement("template");
    template.innerHTML = html;
    template.content.querySelectorAll("script, style, iframe, object, embed").forEach((node) => node.remove());
    template.content.querySelectorAll("*").forEach((node) => {
      [...node.attributes].forEach((attr) => {
        const name = attr.name.toLowerCase();
        const value = String(attr.value || "").trim().toLowerCase();
        if (name.startsWith("on") || value.startsWith("javascript:") || value.startsWith("data:") || value.startsWith("vbscript:")) {
          node.removeAttribute(attr.name);
        }
      });
      if (node.tagName === "A") {
        node.setAttribute("target", "_blank");
        node.setAttribute("rel", "noopener noreferrer");
      }
    });
    return template.innerHTML;
  }

  function renderMarkdown(text) {
    const raw = String(text || "");
    let html;
    if (window.marked && typeof window.marked.parse === "function") {
      html = window.marked.parse(raw, { breaks: true, gfm: true });
    } else {
      html = escapeHtml(raw).replace(/\n/g, "<br>");
    }
    return sanitizeHtml(html);
  }

  function compactValue(value, depth = 0) {
    if (depth > 3) return "...";
    if (value == null || typeof value === "boolean" || typeof value === "number") return value;
    if (typeof value === "string") {
      const trimmed = value.trim();
      return trimmed.length > 450 ? `${trimmed.slice(0, 450)}...` : trimmed;
    }
    if (Array.isArray(value)) return value.slice(0, 12).map((item) => compactValue(item, depth + 1));
    if (typeof value === "object") {
      const result = {};
      Object.entries(value).slice(0, 35).forEach(([key, item]) => {
        result[String(key).slice(0, 80)] = compactValue(item, depth + 1);
      });
      return result;
    }
    return String(value).slice(0, 300);
  }

  function getPageContext() {
    let pageContext = {};
    if (typeof window.AgentProPageContext === "function") {
      try {
        pageContext = window.AgentProPageContext() || {};
      } catch (err) {
        pageContext = { context_error: err.message };
      }
    }
    return compactValue(pageContext);
  }

  function resolveIdentity(context) {
    const cfg = context.config || {};
    let authUser = {};
    try {
      authUser = _getIafUser();
    } catch {}
    return {
      tenant_id: context.tenant_id || context.tenantId || cfg.tenant_id || "company",
      agent_id: context.agent_id || context.agentId || context.selectedAgentId || cfg.agent_id || "enterprise_agent",
      user_id: context.user_id || context.userId || cfg.user_id || authUser.user_id || authUser.email || "demo",
    };
  }

  function sourcePage(context) {
    return (
      context.source_page ||
      context.sourcePage ||
      context.page_id ||
      context.pageId ||
      "home"
    );
  }

  function safeSessionPart(value) {
    return String(value || "")
      .toLowerCase()
      .replace(/[^a-z0-9_.:-]+/g, "_")
      .replace(/^_+|_+$/g, "")
      .slice(0, 80) || "default";
  }

  function safeUrlPart(value, maxLength) {
    return String(value || "")
      // eslint-disable-next-line no-control-regex
      .replace(/[\u0000-\u001F\u007F<>"'`\\]+/g, "")
      .slice(0, maxLength);
  }

  function rebuildText(value) {
    const out = [];
    for (const ch of String(value || "")) {
      const cp = ch.codePointAt(0);
      const isControl = (cp < 32 && cp !== 9 && cp !== 10 && cp !== 13) || cp === 127;
      if (!isControl) out.push(String.fromCodePoint(cp));
    }
    return out.join("").slice(0, MAX_STORED_CONTENT);
  }

  function sessionIdFor(context) {
    const source = safeSessionPart(sourcePage(context));
    const page = safeSessionPart(context.page || context.currentPage || context.tab || "");
    const route = safeSessionPart(context.route || context.source_page || context.sourcePage || context.page_id || context.pageId || "");
    const hash = safeSessionPart(context.hash || context.currentTab || context.tab || "");
    return ["asktwin", source, page, route, hash].filter(Boolean).join(":");
  }

  function sanitizeStoredMessages(list) {
    if (!Array.isArray(list)) return [];
    return list
      .filter((msg) => msg && typeof msg === "object" && !Array.isArray(msg))
      .map((msg) => ({
        role: STORED_ROLES.indexOf(msg.role) === -1 ? "assistant" : msg.role,
        content: String(msg.content == null ? "" : msg.content)
          // eslint-disable-next-line no-control-regex
          .replace(/[\u0000-\u0008\u000B\u000C\u000E-\u001F\u007F]+/g, "")
          .slice(0, MAX_STORED_CONTENT),
      }))
      .slice(-MAX_MESSAGES);
  }

  function pruneStorageKeys(currentKey) {
    try {
      const keys = [];
      for (let i = 0; i < sessionStorage.length; i += 1) {
        const key = sessionStorage.key(i);
        if (key && key.indexOf(STORAGE_PREFIX) === 0 && key !== currentKey) keys.push(key);
      }
      const excess = keys.length - (MAX_STORED_KEYS - 1);
      if (excess > 0) keys.slice(0, excess).forEach((key) => sessionStorage.removeItem(key));
    } catch {}
  }

  function saveMessages() {}

  function loadMessages() {
    state.messages = [];
    try { sessionStorage.removeItem("iaf_ask_twin_messages:shared"); } catch {}
  }

  function clearMessages() {
    state.messages = [];
    state.streamingIndex = -1;
    state.typing = false;
    render();
    if (els.input) els.input.focus();
  }

  function setDocked(next) {
    state.docked = Boolean(next);
    document.body.classList.toggle("apt-docked-open", state.open && state.docked);
  }

  function setOpen(next) {
    state.open = Boolean(next);
    if (els.panel) els.panel.hidden = !state.open;
    if (els.fab) {
      els.fab.classList.toggle("apt-fab-open", state.open);
      els.fab.style.display = state.open ? "none" : "";
    }
    if (els.fabText) els.fabText.textContent = state.open ? "Close" : "Ask Twin";
    document.body.classList.toggle("apt-docked-open", state.open && state.docked);
    if (state.open) {
      connect();
      setTimeout(() => els.input && els.input.focus(), 60);
    } else {
      setDocked(false);
    }
  }

  function setTyping(next, status) {
    state.typing = Boolean(next);
    if (status) state.typingStatus = status;
    render();
  }

  function statusText(data) {
    return data.message || data.status || data.content || "Thinking...";
  }

  function appendMessage(message) {
    state.messages.push(message);
    state.messages = state.messages.slice(-MAX_MESSAGES);
    saveMessages();
    render();
  }

  function handleMessage(data) {
    const type = data.type || data.event;
    if (type === "status" || type === "routing" || type === "progress" || type === "heartbeat") {
      setTyping(true, statusText(data));
      return;
    }
    if (type === "token") {
      if (state.streamingIndex < 0) {
        state.messages.push({ role: "assistant", content: "" });
        state.streamingIndex = state.messages.length - 1;
      }
      state.messages[state.streamingIndex].content += data.token || "";
      setTyping(false);
      saveMessages();
      render();
      return;
    }
    if (type === "response" || type === "message") {
      const content = data.content || data.response || data.message || "";
      if (state.streamingIndex >= 0 && !content) {
        state.streamingIndex = -1;
      } else {
        appendMessage({ role: "assistant", content });
        state.streamingIndex = -1;
      }
      setTyping(false);
      return;
    }
    if (type === "error") {
      appendMessage({ role: "assistant", content: `Warning: ${data.content || data.message || "AskTwin failed."}` });
      state.streamingIndex = -1;
      setTyping(false);
    }
  }

  function _sanitizeWsToken(raw) {
    if (typeof raw !== "string" || raw.length === 0 || raw.length > 8192) {
      return "";
    }
    const allowed = /^[A-Za-z0-9._~+/=\-]+$/;
    if (!allowed.test(raw)) {
      return "";
    }
    let out = "";
    for (let i = 0; i < raw.length; i++) {
      const ch = raw.charAt(i);
      if (/[A-Za-z0-9._~+/=\-]/.test(ch)) {
        out += ch;
      } else {
        return "";
      }
    }
    return out;
  }

  function _buildChatWsUrl(proto, host, token) {
    const safeProto = proto === "wss" ? "wss" : "ws";
    const safeHost = typeof host === "string" && /^[A-Za-z0-9.:\-]+$/.test(host) ? host : location.host;
    const safeToken = _sanitizeWsToken(token);
    const base = safeProto + "://" + safeHost + "/ws/chat";
    if (!safeToken) {
      return base;
    }
    return base + "?token=" + encodeURIComponent(safeToken);
  }

  function connect() {
    if (state.ws && state.ws.readyState === WebSocket.OPEN) return;
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const rawToken = ""; // SEC-6: httponly cookie sent on WS upgrade
    const wsUrl = _buildChatWsUrl(proto, location.host, rawToken);
    try {
      state.ws = new WebSocket(wsUrl);
      state.ws.onopen = () => {
        state.wsConnected = true;
        updateStatusDot();
      };
      state.ws.onclose = () => {
        state.wsConnected = false;
        state.ws = null;
        updateStatusDot();
        if (state.open) setTimeout(connect, 3000);
      };
      state.ws.onerror = () => {
        state.wsConnected = false;
        updateStatusDot();
      };
      state.ws.onmessage = (event) => {
        try {
          handleMessage(JSON.parse(event.data));
        } catch (err) {
          handleMessage({ type: "error", message: `Could not parse response: ${err.message}` });
        }
      };
    } catch {
      state.wsConnected = false;
      updateStatusDot();
    }
  }

  function payloadFor(text) {
    const pageContext = getPageContext();
    const identity = resolveIdentity(pageContext);
    return {
      content: text,
      ...identity,
      skill_name: "iaf_guide",
      session_id: sessionIdFor(pageContext),
      source_page: sourcePage(pageContext),
      page_context: pageContext,
      human_approval: false,
      render_ui: false,
      light_mode: true,
    };
  }

  async function send(text) {
    const content = rebuildText(text != null ? text : (els.input?.value || "")).trim();
    if (!content || state.typing) return;
    appendMessage({ role: "user", content });
    if (els.input) {
      els.input.value = "";
      autoSizeInput();
    }
    setTyping(true, "Thinking...");

    const payload = payloadFor(content);
    if (state.ws && state.ws.readyState === WebSocket.OPEN) {
      state.ws.send(JSON.stringify(payload));
      return;
    }

    try {
      const headers = { "Content-Type": "application/json" };
      const rawToken = ""; // SEC-6: httponly cookie sent on WS upgrade
      const safeToken = _sanitizeWsToken(rawToken);
      if (safeToken) headers.Authorization = "Bearer " + safeToken;
      const resp = await fetch(CHAT_ENDPOINT, {
        method: "POST",
        headers,
        body: JSON.stringify(payload),
      });
      const data = await resp.json();
      handleMessage({ type: "response", content: data.content || data.response || data.message || JSON.stringify(data) });
    } catch (err) {
      handleMessage({ type: "error", message: err.message });
    }
  }

  function updateStatusDot() {
    if (!els.status) return;
    els.status.className = `apt-status ${state.wsConnected ? "apt-status-on" : "apt-status-off"}`;
    els.status.title = state.wsConnected ? "WebSocket connected" : "Using HTTP fallback";
  }

  function scrollMessages() {
    if (els.messages) els.messages.scrollTop = els.messages.scrollHeight;
  }

  function render() {
    if (!els.messages) return;
    if (!state.messages.length && !state.typing) {
      els.messages.innerHTML = `
        <div class="apt-empty">
          <div class="apt-empty-icon">${twinIcon(22)}</div>
          <div class="apt-empty-title">Ask Twin</div>
          <div class="apt-empty-copy">Ask about this page, the selected item, metrics, policies, or how to use AgentPro.</div>
        </div>
      `;
      return;
    }

    const rows = state.messages.map((msg) => {
      const role = msg.role === "user" ? "user" : "assistant";
      const body = role === "assistant"
        ? `<div class="apt-prose">${renderMarkdown(msg.content)}</div>`
        : `<div>${escapeHtml(msg.content)}</div>`;
      return `<div class="apt-row apt-row-${role}"><div class="apt-bubble apt-bubble-${role}">${body}</div></div>`;
    });

    if (state.typing) {
      rows.push(`
        <div class="apt-row apt-row-assistant">
          <div class="apt-bubble apt-bubble-assistant apt-typing">
            <span class="apt-dot"></span><span class="apt-dot"></span><span class="apt-dot"></span>
            <span class="apt-typing-text">${escapeHtml(state.typingStatus)}</span>
          </div>
        </div>
      `);
    }
    els.messages.innerHTML = rows.join("");
    requestAnimationFrame(scrollMessages);
  }

  function autoSizeInput() {
    if (!els.input) return;
    els.input.style.height = "auto";
    els.input.style.height = `${Math.min(110, els.input.scrollHeight)}px`;
  }

  var FAB_POS_KEY = "ask-twin-fab-pos";

  // Clamp the FAB inside the viewport and pin it via left/top (overriding the
  // default right/bottom anchoring) so it never sits off-screen after a resize.
  function applyFabPosition(left, top) {
    var fab = els.fab;
    if (!fab) return;
    var w = fab.offsetWidth || 120;
    var h = fab.offsetHeight || 44;
    var maxLeft = window.innerWidth - w - 6;
    var maxTop = window.innerHeight - h - 6;
    left = Math.max(6, Math.min(left, Math.max(6, maxLeft)));
    top = Math.max(6, Math.min(top, Math.max(6, maxTop)));
    fab.style.left = left + "px";
    fab.style.top = top + "px";
    fab.style.right = "auto";
    fab.style.bottom = "auto";
  }

  function restoreFabPosition() {
    try {
      var pos = JSON.parse(localStorage.getItem(FAB_POS_KEY) || "null");
      if (pos && typeof pos.left === "number" && typeof pos.top === "number") {
        applyFabPosition(pos.left, pos.top);
      }
    } catch (e) {}
  }

  // The FAB is draggable so it can be moved off any button it happens to cover.
  // A small movement threshold distinguishes a drag from a click (which opens
  // the panel); the post-drag click is swallowed in the capture phase.
  function makeFabDraggable() {
    var fab = els.fab;
    if (!fab) return;
    var dragging = false, moved = false;
    var startX = 0, startY = 0, originLeft = 0, originTop = 0;
    var THRESH = 4;

    fab.addEventListener("pointerdown", function (e) {
      if (e.button !== 0) return;
      dragging = true; moved = false;
      startX = e.clientX; startY = e.clientY;
      var rect = fab.getBoundingClientRect();
      originLeft = rect.left; originTop = rect.top;
      try { fab.setPointerCapture(e.pointerId); } catch (err) {}
    });
    fab.addEventListener("pointermove", function (e) {
      if (!dragging) return;
      var dx = e.clientX - startX, dy = e.clientY - startY;
      if (!moved && Math.hypot(dx, dy) > THRESH) {
        moved = true;
        fab.classList.add("apt-fab-dragging");
      }
      if (moved) applyFabPosition(originLeft + dx, originTop + dy);
    });
    function endDrag(e) {
      if (!dragging) return;
      dragging = false;
      try { fab.releasePointerCapture(e.pointerId); } catch (err) {}
      if (moved) {
        fab.classList.remove("apt-fab-dragging");
        var rect = fab.getBoundingClientRect();
        try { localStorage.setItem(FAB_POS_KEY, JSON.stringify({ left: rect.left, top: rect.top })); } catch (err) {}
      }
    }
    fab.addEventListener("pointerup", endDrag);
    fab.addEventListener("pointercancel", endDrag);
    // Swallow the click synthesized after a drag so it does not open the panel.
    fab.addEventListener("click", function (e) {
      if (moved) { e.stopImmediatePropagation(); e.preventDefault(); moved = false; }
    }, true);
    // Keep it on-screen if the window is resized.
    window.addEventListener("resize", function () {
      if (fab.style.left) {
        var rect = fab.getBoundingClientRect();
        applyFabPosition(rect.left, rect.top);
      }
    });
  }

  function injectStyles() {
    if (document.getElementById("ask-twin-styles")) return;
    const style = document.createElement("style");
    style.id = "ask-twin-styles";
    if (window.__CSP_NONCE__) style.setAttribute("nonce", window.__CSP_NONCE__);
    style.textContent = `
      .apt-fab { position: fixed; right: 24px; bottom: 24px; z-index: 70; display: inline-flex; align-items: center; gap: 8px; border: 0; border-radius: 999px; padding: 12px 16px; background: #7c3aed; color: #fff; font: 700 13px/1 system-ui, -apple-system, Segoe UI, sans-serif; box-shadow: 0 16px 40px rgba(15,23,42,.34); cursor: grab; touch-action: none; user-select: none; transition: transform .16s ease, background .16s ease; }
      .apt-fab-dragging { cursor: grabbing; opacity: .85; transition: none; }
      .apt-fab:hover { background: #8b5cf6; transform: translateY(-1px); }
      .apt-fab-icon, .apt-title-icon { display: inline-flex; align-items: center; }
      .apt-empty-icon svg { display: block; }
      /* TC-205: while the panel is open, hide the FAB so it can't overlap the Send button. */
      .apt-fab-open { display: none; }
      .apt-panel { position: fixed; top: 0; right: 0; z-index: 75; width: min(430px, calc(100vw - 18px)); height: 100vh; display: flex; flex-direction: column; background: #030712; color: #e5e7eb; border-left: 1px solid rgba(75,85,99,.75); box-shadow: -24px 0 70px rgba(0,0,0,.42); }
      .apt-panel[hidden] { display: none !important; }
      .apt-header { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 13px 14px; background: #111827; border-bottom: 1px solid rgba(75,85,99,.75); }
      .apt-title { display: flex; align-items: center; gap: 8px; min-width: 0; font: 700 14px/1 system-ui, -apple-system, Segoe UI, sans-serif; color: #fff; }
      .apt-subtitle { margin-top: 3px; color: #9ca3af; font: 500 11px/1.2 system-ui, -apple-system, Segoe UI, sans-serif; }
      .apt-status { width: 8px; height: 8px; border-radius: 999px; flex: 0 0 auto; }
      .apt-status-on { background: #34d399; box-shadow: 0 0 0 3px rgba(52,211,153,.13); }
      .apt-status-off { background: #6b7280; }
      .apt-close { border: 0; background: transparent; color: #9ca3af; cursor: pointer; font-size: 18px; line-height: 1; padding: 3px 6px; border-radius: 8px; }
      .apt-close:hover { color: #fff; background: rgba(255,255,255,.06); }
      .apt-actions { display: flex; align-items: center; gap: 6px; }
      .apt-newchat { border: 1px solid rgba(139,92,246,.5); background: transparent; color: #c4b5fd; cursor: pointer; font: 600 12px/1 system-ui, -apple-system, Segoe UI, sans-serif; padding: 5px 9px; border-radius: 8px; white-space: nowrap; }
      .apt-newchat:hover { color: #fff; background: rgba(139,92,246,.22); }
      .apt-messages { flex: 1; overflow-y: auto; padding: 14px; display: flex; flex-direction: column; gap: 12px; }
      .apt-empty { min-height: 100%; display: flex; flex-direction: column; justify-content: center; align-items: center; text-align: center; color: #8b95a7; gap: 8px; padding: 24px; }
      .apt-empty-icon { width: 42px; height: 42px; border-radius: 14px; display: grid; place-items: center; color: #c4b5fd; background: rgba(124,58,237,.12); border: 1px solid rgba(124,58,237,.25); font-weight: 800; }
      .apt-empty-title { color: #f8fafc; font-weight: 800; font-size: 14px; }
      .apt-empty-copy { font-size: 12px; line-height: 1.45; max-width: 280px; }
      .apt-row { display: flex; }
      .apt-row-user { justify-content: flex-end; }
      .apt-row-assistant { justify-content: flex-start; }
      .apt-bubble { max-width: 90%; border-radius: 16px; padding: 9px 11px; font: 500 12px/1.45 system-ui, -apple-system, Segoe UI, sans-serif; overflow-wrap: anywhere; }
      .apt-bubble-user { background: #6d28d9; color: #fff; border-bottom-right-radius: 5px; }
      .apt-bubble-assistant { background: #1f2937; color: #dbe4f0; border: 1px solid rgba(148,163,184,.10); border-bottom-left-radius: 5px; }
      .apt-prose :is(h1,h2,h3,h4) { color: #fff; margin: .15rem 0 .35rem; font-weight: 800; line-height: 1.22; }
      .apt-prose h1 { font-size: 1rem; }
      .apt-prose h2 { font-size: .92rem; }
      .apt-prose h3, .apt-prose h4 { font-size: .84rem; }
      .apt-prose p { margin: 0 0 .55rem; }
      .apt-prose p:last-child { margin-bottom: 0; }
      .apt-prose ul, .apt-prose ol { margin: .25rem 0 .55rem; padding-left: 1.05rem; }
      .apt-prose li { margin: .16rem 0; padding-left: .1rem; }
      .apt-prose strong { color: #f8fafc; font-weight: 800; }
      .apt-prose a { color: #a5b4fc; text-decoration: none; border-bottom: 1px solid rgba(165,180,252,.35); }
      .apt-prose code { background: rgba(2,6,23,.72); color: #dbeafe; border: 1px solid rgba(148,163,184,.14); border-radius: 5px; padding: 1px 4px; font: 600 11px/1.4 ui-monospace, SFMono-Regular, Menlo, monospace; word-break: break-word; }
      .apt-prose pre { margin: .45rem 0; padding: 9px; max-width: 100%; overflow-x: auto; white-space: pre-wrap; background: #020617; border: 1px solid rgba(148,163,184,.16); border-radius: 10px; }
      .apt-prose pre code { border: 0; background: transparent; padding: 0; color: #dbeafe; }
      .apt-prose blockquote { margin: .45rem 0; padding: .45rem .6rem; border-left: 3px solid #8b5cf6; background: rgba(139,92,246,.10); color: #d1d5db; border-radius: 8px; }
      .apt-prose table { display: block; max-width: 100%; overflow-x: auto; border-collapse: collapse; margin: .5rem 0; font-size: 11px; }
      .apt-prose th, .apt-prose td { border: 1px solid rgba(148,163,184,.20); padding: 5px 7px; text-align: left; white-space: nowrap; }
      .apt-prose th { color: #fff; background: rgba(255,255,255,.06); }
      .apt-prose hr { border: 0; border-top: 1px solid rgba(148,163,184,.18); margin: .7rem 0; }
      .apt-typing { display: inline-flex; align-items: center; gap: 5px; color: #9ca3af; }
      .apt-dot { width: 5px; height: 5px; border-radius: 50%; background: #a78bfa; animation: aptBounce 1s infinite ease-in-out; }
      .apt-dot:nth-child(2) { animation-delay: .15s; }
      .apt-dot:nth-child(3) { animation-delay: .3s; }
      .apt-typing-text { margin-left: 3px; max-width: 220px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
      @keyframes aptBounce { 0%, 80%, 100% { transform: translateY(0); opacity: .45; } 40% { transform: translateY(-3px); opacity: 1; } }
      .apt-inputbar { display: flex; align-items: flex-end; gap: 8px; padding: 12px; background: #111827; border-top: 1px solid rgba(75,85,99,.75); }
      .apt-input { flex: 1; min-height: 38px; max-height: 110px; resize: none; outline: none; border: 1px solid #374151; border-radius: 13px; background: #1f2937; color: #e5e7eb; padding: 9px 10px; font: 500 12px/1.35 system-ui, -apple-system, Segoe UI, sans-serif; }
      .apt-input:focus { border-color: #8b5cf6; box-shadow: 0 0 0 3px rgba(139,92,246,.14); }
      .apt-send { border: 0; border-radius: 12px; padding: 10px 12px; background: #7c3aed; color: #fff; font: 800 12px/1 system-ui, -apple-system, Segoe UI, sans-serif; cursor: pointer; }
      .apt-send:hover { background: #8b5cf6; }
      .apt-send:disabled { opacity: .45; cursor: not-allowed; }
      body.hybrid-mode .apt-panel, body.light-mode .apt-panel { background: #0b1120; color: #e5e7eb; }
      @media (max-width: 520px) { .apt-panel { width: 100vw; } .apt-fab { right: 16px; bottom: 16px; } }
    `;
    document.head.appendChild(style);
  }

  function mount() {
    if (document.getElementById("ask-twin-root")) return;
    injectStyles();
    loadMessages();
    const root = document.createElement("div");
    root.id = "ask-twin-root";
    root.innerHTML = `
      <button type="button" class="apt-fab" aria-label="Ask Twin">
        <span class="apt-fab-icon" aria-hidden="true">${twinIcon(16)}</span>
        <span class="apt-fab-text">Ask Twin</span>
      </button>
      <section class="apt-panel" hidden aria-label="Ask Twin chat">
        <header class="apt-header">
          <div>
            <div class="apt-title"><span class="apt-title-icon" aria-hidden="true">${twinIcon(16)}</span><span>Ask Twin</span><span class="apt-status apt-status-off"></span></div>
            <div class="apt-subtitle">Page-aware help for the screen you are on</div>
          </div>
          <div class="apt-actions">
            <button type="button" class="apt-newchat" aria-label="New conversation" title="New conversation (clears history)">+ New</button>
            <button type="button" class="apt-close" aria-label="Close Ask Twin">×</button>
          </div>
        </header>
        <div class="apt-messages" role="log" aria-live="polite"></div>
        <div class="apt-inputbar">
          <textarea class="apt-input" rows="1" placeholder="Ask about this page..."></textarea>
          <button type="button" class="apt-send">Send</button>
        </div>
      </section>
    `;
    document.body.appendChild(root);
    els.root = root;
    els.fab = root.querySelector(".apt-fab");
    els.fabText = root.querySelector(".apt-fab-text");
    els.panel = root.querySelector(".apt-panel");
    els.close = root.querySelector(".apt-close");
    els.newChat = root.querySelector(".apt-newchat");
    els.status = root.querySelector(".apt-status");
    els.messages = root.querySelector(".apt-messages");
    els.input = root.querySelector(".apt-input");
    els.send = root.querySelector(".apt-send");

    els.fab.addEventListener("click", () => setOpen(!state.open));
    els.fab.title = "Ask Twin — drag to move";
    makeFabDraggable();
    restoreFabPosition();
    els.close.addEventListener("click", () => setOpen(false));
    if (els.newChat) els.newChat.addEventListener("click", () => clearMessages());
    els.send.addEventListener("click", () => send());
    els.input.addEventListener("input", autoSizeInput);
    els.input.addEventListener("keydown", (event) => {
      if (event.key === "Enter" && !event.shiftKey) {
        event.preventDefault();
        send();
      }
    });
    // Escape closes the panel (standard keyboard-accessibility pattern).
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && state.open) {
        setOpen(false);
      }
    });
    render();
    updateStatusDot();
  }

  window.AgentProAskTwin = {
    init: mount,
    open(prefill) {
      mount();
      setOpen(true);
      if (prefill && els.input) {
        els.input.value = String(prefill);
        autoSizeInput();
        els.input.focus();
      }
    },
    send(text) {
      mount();
      setOpen(true);
      return send(text);
    },
    openAndAsk(text, options = {}) {
      mount();
      setDocked(Boolean(options.docked));
      setOpen(true);
      return send(text);
    },
    context: getPageContext,
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", mount);
  } else {
    mount();
  }
})();
