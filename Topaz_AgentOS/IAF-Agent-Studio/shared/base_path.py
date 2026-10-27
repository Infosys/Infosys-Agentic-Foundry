"""Base-path (sub-path) helpers for serving Studio behind a gateway prefix.

When the app is deployed under a path prefix (e.g. ``https://host/qlabs/``) the
frontend still emits root-absolute API/WS calls (``fetch("/api/...")``,
``new WebSocket("wss://host/ws/chat")``). The browser resolves those against the
ORIGIN root, so they bypass the prefix and 404 at the gateway.

Rather than rewrite the hundreds of scattered call sites, the server injects a
tiny inline bootstrap into the ``<head>`` of every served HTML page. The
bootstrap records the base path and transparently shims ``fetch`` /
``WebSocket`` / ``window.open`` to prefix same-origin absolute paths, and also
exposes ``window.apiUrl()`` / ``window.wsUrl()`` / ``window.navigate()`` helpers.

Two classes of references are NOT interceptable by the runtime shim and are
handled by a server-side attribute rewrite performed in :func:`inject_base_path`:

* **Static assets in ``<head>``** — ``<script src="/static/...">`` and
  ``<link href="/static/...">`` are fetched by the browser during HTML parse,
  *before* any inline script runs, so a runtime shim can never intercept them.
  Left unprefixed they 404 at the gateway and the whole page's JS/CSS dies.
* **Declarative navigations** — ``<a href="/...">`` / ``<form action="/...">``
  present in the served markup.

The server-side rewrite prefixes same-origin root-absolute ``src``/``href``/
``action`` attribute values. The runtime bootstrap additionally handles
navigations added dynamically at runtime: it rewrites root-absolute
``<a>``/``<form>``/``<img>`` on DOMContentLoaded and intercepts anchor clicks in
the capture phase. Hard JS navigations (``location.href = '/...'``) cannot be
intercepted and are fixed per page using ``window.__BASE_PATH__``.

This module is intentionally dependency-free and side-effect-free so it is cheap
to import (it is pulled in by ``shared.config`` at boot) and unit-testable in
isolation. When the base path is empty (root deployment) nothing is injected or
rewritten and callers serve pages byte-for-byte as before.
"""
from __future__ import annotations

import json
import re

_HEAD_TAG_RE = re.compile(r"<head[^>]*>", re.IGNORECASE)

# Same-origin root-absolute src/href/action value; the leading whitespace avoids xlink:href and data-src.
_ATTR_RE = re.compile(r"""(\s(?:src|href|action)\s*=\s*)(["'])(/[^"']*)\2""", re.IGNORECASE)


def rewrite_root_absolute_attrs(html: str, root_path: str) -> str:
    """Prefix same-origin root-absolute ``src``/``href``/``action`` attributes.

    Skips protocol-relative (``//host/...``) values and anything already carrying
    the prefix, so it is idempotent. Returns ``html`` unchanged when ``root_path``
    is empty (root deployment).
    """
    if not root_path:
        return html

    def _sub(match: "re.Match[str]") -> str:
        prefix, quote, value = match.group(1), match.group(2), match.group(3)
        # Protocol-relative URL (//host/path) — leave the origin to the browser.
        if value.startswith("//"):
            return match.group(0)
        # Already prefixed — keep idempotent (no double prefix).
        if value == root_path or value.startswith(root_path + "/"):
            return match.group(0)
        return f"{prefix}{quote}{root_path}{value}{quote}"

    return _ATTR_RE.sub(_sub, html)


def normalize_root_path(raw: str | None) -> str:
    """Normalize a raw base path to ``""`` or a single-leading-slash prefix.

    Examples: ``""``/``"/"`` -> ``""``; ``"qlabs"``/``"/qlabs/"`` -> ``"/qlabs"``.
    """
    raw = (raw or "").strip()
    if raw in ("", "/"):
        return ""
    return "/" + raw.strip("/")


def base_path_bootstrap(root_path: str) -> str:
    """Return the inline ``<script>`` that teaches the browser about ``root_path``."""
    bp = json.dumps(root_path)
    return (
        "<script>(function(){"
        "var BP=" + bp + ";"
        "window.__BASE_PATH__=BP;"
        "function withBase(p){"
        "if(typeof p!=='string'||!BP)return p;"
        "if(p.charAt(0)!=='/')return p;"
        "if(p.charAt(1)==='/')return p;"
        "if(p===BP||p.indexOf(BP+'/')===0)return p;"
        "return BP+p;}"
        "window.apiUrl=withBase;"
        "window.wsUrl=function(p){try{var u=new URL(p,window.location.href);"
        "if(u.host===window.location.host){u.pathname=withBase(u.pathname);}"
        "return u.toString();}catch(e){return withBase(p);}};"
        "window.navigate=function(p){var t=withBase(p);"
        "try{window.location.assign(t);}catch(e){window.location.href=t;}};"
        "if(!BP)return;"
        "var _f=window.fetch;"
        "if(_f){window.fetch=function(input,init){try{"
        "if(typeof input==='string'){input=withBase(input);}"
        "else if(typeof URL!=='undefined'&&input instanceof URL){"
        "if(input.host===window.location.host){"
        "input=new URL(withBase(input.pathname)+input.search+input.hash,input.origin);}}"
        "else if(input&&typeof Request!=='undefined'&&input instanceof Request){"
        "var ru=new URL(input.url);"
        "if(ru.host===window.location.host&&!(ru.pathname===BP||ru.pathname.indexOf(BP+'/')===0)){"
        "ru.pathname=withBase(ru.pathname);input=new Request(ru.toString(),input);}}"
        "}catch(e){}return _f.call(this,input,init);};}"
        "var _WS=window.WebSocket;"
        "if(_WS){var WS=function(url,protocols){var u=window.wsUrl(url);"
        "return protocols===undefined?new _WS(u):new _WS(u,protocols);};"
        "WS.prototype=_WS.prototype;WS.CONNECTING=_WS.CONNECTING;WS.OPEN=_WS.OPEN;"
        "WS.CLOSING=_WS.CLOSING;WS.CLOSED=_WS.CLOSED;window.WebSocket=WS;}"
        "var _open=window.open;"
        "if(_open){window.open=function(url){var a=Array.prototype.slice.call(arguments);"
        "if(typeof url==='string'){a[0]=withBase(url);}return _open.apply(this,a);};}"
        # Rewrite root-absolute links added after load and intercept anchor clicks (capture phase).
        "function fix(el,attr){var v=el.getAttribute(attr);"
        "if(!v||v.charAt(0)!=='/'||v.charAt(1)==='/')return;"
        "if(v===BP||v.indexOf(BP+'/')===0)return;el.setAttribute(attr,BP+v);}"
        "function sweep(root){try{var n=root.querySelectorAll("
        "'a[href^=\"/\"],form[action^=\"/\"],img[src^=\"/\"]'),i;"
        "for(i=0;i<n.length;i++){var e=n[i],t=e.tagName;"
        "if(t==='FORM')fix(e,'action');else if(t==='IMG')fix(e,'src');else fix(e,'href');}}catch(e){}}"
        "if(document.readyState==='loading'){"
        "document.addEventListener('DOMContentLoaded',function(){sweep(document);});}"
        "else{sweep(document);}"
        "document.addEventListener('click',function(ev){try{"
        "var a=ev.target&&ev.target.closest?ev.target.closest('a[href]'):null;"
        "if(a)fix(a,'href');}catch(e){}},true);"
        "})();</script>"
    )


def inject_base_path(html: str, root_path: str) -> str:
    """Rewrite root-absolute asset/link attributes and insert the bootstrap.

    The attribute rewrite runs first (on the original markup) so the injected
    bootstrap ``<script>`` is never scanned by the rewrite regex. Returns
    ``html`` unchanged when ``root_path`` is empty (root deployment).
    """
    if not root_path:
        return html
    html = rewrite_root_absolute_attrs(html, root_path)
    snippet = base_path_bootstrap(root_path)
    match = _HEAD_TAG_RE.search(html)
    if match:
        idx = match.end()
        return html[:idx] + snippet + html[idx:]
    return snippet + html
