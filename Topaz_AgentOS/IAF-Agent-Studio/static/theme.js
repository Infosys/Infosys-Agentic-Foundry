/*
 * IAF AgentOS — unified theme controller (Light / Dark only).
 * Single source of truth for theme persistence, cross-tab sync, and toggles.
 *
 * Public API:
 *   window.IAFTheme.get()            -> 'light' | 'dark'
 *   window.IAFTheme.set(theme, opts) -> applies + persists (opts.persist=false to skip)
 *   window.IAFTheme.toggle()         -> flips light/dark
 *   window.IAFTheme.KEY              -> localStorage key
 *
 * Markup hooks (progressive-enhancement, no framework required):
 *   <button data-theme-toggle> ... </button>   (click flips theme; aria kept in sync)
 *   <select data-theme-select> ... </select>   (value drives theme; kept in sync)
 *
 * Events:
 *   window 'iaf:themechange' -> CustomEvent, detail.theme = 'light' | 'dark'
 *
 * Note: the FOUC guard (inline <head> script) applies the theme before first
 * paint. This file re-applies, wires controls, and keeps tabs in sync.
 */
(function (w, d) {
  'use strict';

  var KEY = 'iaf_theme';
  // Older per-page keys are migrated into the shared key on first read.
  var LEGACY_KEYS = ['iaf_dashboard_theme', 'iaf_workstreams_theme', 'iaf_skill_builder_theme', 'rl_theme', 'iaf-theme'];

  function normalize(v) {
    if (v === 'light') return 'light';
    if (v === 'dark') return 'dark';
    if (v === 'hybrid') return 'light'; // retired mode -> light
    return null;
  }

  function readStored() {
    try {
      var v = normalize(w.localStorage.getItem(KEY));
      if (v) return v;
      for (var i = 0; i < LEGACY_KEYS.length; i++) {
        var lv = normalize(w.localStorage.getItem(LEGACY_KEYS[i]));
        if (lv) {
          try { w.localStorage.setItem(KEY, lv); } catch (e) { /* ignore */ }
          return lv;
        }
      }
    } catch (e) { /* storage blocked */ }
    return null;
  }

  function systemPref() {
    try {
      return (w.matchMedia && w.matchMedia('(prefers-color-scheme: light)').matches) ? 'light' : 'dark';
    } catch (e) { return 'dark'; }
  }

  // Stored choice wins; otherwise fall back to OS preference (first visit only).
  function resolve() { return readStored() || systemPref(); }

  var current = normalize(w.localStorage && (function () {
    try { return w.localStorage.getItem(KEY); } catch (e) { return null; }
  })()) || null;

  function apply(theme) {
    var t = normalize(theme) || 'dark';
    var root = d.documentElement;
    root.setAttribute('data-theme', t);
    root.classList.toggle('light-mode', t === 'light');
    root.classList.toggle('dark-mode', t === 'dark');
    if (d.body) {
      d.body.classList.toggle('light-mode', t === 'light');
      d.body.classList.toggle('dark-mode', t === 'dark');
      d.body.classList.remove('hybrid-mode');
    }
    try { root.style.colorScheme = t; } catch (e) { /* ignore */ }
    current = t;
    return t;
  }

  function emit() {
    try {
      w.dispatchEvent(new CustomEvent('iaf:themechange', { detail: { theme: current } }));
    } catch (e) { /* older browsers */ }
  }

  // Keep Chart.js canvases legible in both themes. Sets global defaults
  // (used by charts created afterwards) and recolours any live instances.
  function themeCharts(theme) {
    var C = w.Chart;
    if (!C || !C.defaults) return;
    var light = theme === 'light';
    var text = light ? '#475569' : '#94a3b8';
    var grid = light ? 'rgba(100,116,139,0.16)' : 'rgba(148,163,184,0.12)';
    try {
      C.defaults.color = text;
      C.defaults.borderColor = grid;
    } catch (e) { /* ignore */ }
    var insts = C.instances || {};
    Object.keys(insts).forEach(function (k) {
      var c = insts[k];
      if (!c || !c.options) return;
      try {
        c.options.color = text;
        var pl = c.options.plugins;
        if (pl && pl.legend && pl.legend.labels) pl.legend.labels.color = text;
        if (pl && pl.title) pl.title.color = text;
        var sc = c.options.scales;
        if (sc) {
          Object.keys(sc).forEach(function (key) {
            var s = sc[key];
            if (!s) return;
            if (s.ticks) s.ticks.color = text;
            if (s.grid) s.grid.color = grid;
            if (s.title) s.title.color = text;
            if (s.pointLabels) s.pointLabels.color = text;
            if (s.angleLines) s.angleLines.color = grid;
          });
        }
        c.update('none');
      } catch (e) { /* ignore per-chart */ }
    });
  }

  function reflectControls() {
    var toggles = d.querySelectorAll('[data-theme-toggle]');
    for (var i = 0; i < toggles.length; i++) {
      var el = toggles[i];
      var toDark = current === 'light';
      el.setAttribute('aria-pressed', current === 'dark' ? 'true' : 'false');
      var label = toDark ? 'Switch to dark theme' : 'Switch to light theme';
      el.setAttribute('aria-label', label);
      if (!el.hasAttribute('data-theme-toggle-notitle')) el.setAttribute('title', label);
      el.setAttribute('data-theme-state', current);
    }
    var selects = d.querySelectorAll('[data-theme-select]');
    for (var j = 0; j < selects.length; j++) {
      if (selects[j].value !== current) selects[j].value = current;
    }
  }

  function set(theme, opts) {
    opts = opts || {};
    apply(theme);
    if (opts.persist !== false) {
      try { w.localStorage.setItem(KEY, current); } catch (e) { /* ignore */ }
    }
    reflectControls();
    themeCharts(current);
    emit();
    return current;
  }

  function toggle() { return set(current === 'light' ? 'dark' : 'light'); }
  function get() { return current; }

  // Apply as early as this script runs (backs up the inline head guard).
  apply(current || resolve());

  // Cross-tab sync: another tab changed the shared key.
  w.addEventListener('storage', function (e) {
    if (e.key === KEY) {
      var v = normalize(e.newValue);
      if (v && v !== current) { apply(v); reflectControls(); emit(); }
    }
  });

  function isLoginPage() {
    try {
      var p = (w.location && w.location.pathname) || '';
      return p.toLowerCase().indexOf('login') !== -1;
    } catch (e) { return false; }
  }

  function ensureFloatingToggle() {
    // The floating toggle is reserved for the login page; every other page
    // ships an inline toggle control instead.
    if (!isLoginPage()) return;
    if (d.querySelector('[data-theme-toggle], [data-theme-select]')) return;
    if (!d.body) return;
    var btn = d.createElement('button');
    btn.type = 'button';
    btn.className = 'iaf-theme-toggle iaf-theme-fab';
    btn.setAttribute('data-theme-toggle', '');
    btn.setAttribute('aria-pressed', current === 'dark' ? 'true' : 'false');
    btn.innerHTML =
      '<svg class="iaf-icon-sun" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="4"></circle><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"></path></svg>' +
      '<svg class="iaf-icon-moon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"></path></svg>';
    d.body.appendChild(btn);
  }

  function onReady() {
    apply(current);        // re-apply now that <body> exists (body classes)
    ensureFloatingToggle();
    reflectControls();
    d.addEventListener('click', function (e) {
      var t = e.target && e.target.closest ? e.target.closest('[data-theme-toggle]') : null;
      if (t) { e.preventDefault(); toggle(); }
    });
    d.addEventListener('change', function (e) {
      var s = e.target && e.target.closest ? e.target.closest('[data-theme-select]') : null;
      if (s) { set(s.value); }
    });
    emit();
  }

  if (d.readyState === 'loading') d.addEventListener('DOMContentLoaded', onReady);
  else onReady();

  // Chart.js usually loads after this script; set its defaults once ready.
  w.addEventListener('load', function () { themeCharts(current); });

  w.IAFTheme = { get: get, set: set, toggle: toggle, KEY: KEY };
  // Back-compat shim for legacy workstream pages.
  w.setWorkstreamTheme = function (n) { set(n); };
})(window, document);
