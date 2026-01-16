import React, { useEffect, useRef, useState, useCallback } from "react";

// Global parser & buffer helpers (must exist before early suppression block to avoid ReferenceError on fast refresh)
if (typeof window !== "undefined") {
  if (!window.__earlyDevProblemsBuffer) window.__earlyDevProblemsBuffer = [];
}

const pushEarly = (entry) => {
  try {
    if (window.__earlyDevProblemsBuffer) window.__earlyDevProblemsBuffer.push(entry);
  } catch (_) {}
};

// Extracts "Line X:Y: 'Ident' is not defined" plus preceding file path lines
const parseOverlayRaw = (text) => {
  if (!text) return [];
  const rawLines = text.split(/\n+/);
  const lines = rawLines.map((l) => l.replace(/\r/g, "")).filter((l) => l.trim());
  const undefRe = /^Line\s+(\d+)(?::(\d+))?:\s+'([^']+)'\s+is not defined/i;
  let lastFile = null;
  const fileRe = /(src\\[^:]+|src\/[^:]+)\s*$/i;
  const out = [];
  lines.forEach((l) => {
    const fm = l.match(fileRe);
    if (fm) lastFile = fm[1];
    const m = l.match(undefRe);
    if (m) {
      const line = m[1];
      const col = m[2] || "?";
      const ident = m[3];
      out.push({
        type: "error",
        variable: ident,
        file: lastFile || null,
        line: Number(line),
        col: col === "?" ? null : Number(col),
        simplified: `${ident} @ ${lastFile ? lastFile + ":" : ""}${line}${col === "?" ? "" : ":" + col}`,
      });
    }
  });
  return out;
};

// Early (module-load) suppression so CRA/Webpack overlay never flashes before React mounts.
// Runs only in development and only once (guarded by window flag).
if (typeof window !== "undefined" && process.env.NODE_ENV === "development" && !window.__compileIssuesOverlayPatched) {
  window.__compileIssuesOverlayPatched = true;
  const forceHideCss = document.createElement("style");
  forceHideCss.setAttribute("data-dev-overlay-hide", "true");
  forceHideCss.textContent = `#webpack-dev-server-client-overlay, #webpack-dev-server-client-overlay-div { display:none !important; visibility:hidden !important; opacity:0 !important; }`;
  document.head.appendChild(forceHideCss);
  const immediateHide = () => {
    ["webpack-dev-server-client-overlay", "webpack-dev-server-client-overlay-div"].forEach((id) => {
      const el = document.getElementById(id);
      if (el) {
        const captured = el.textContent || "";
        parseOverlayRaw(captured).forEach((r) => pushEarly(r));
        el.style.display = "none";
        el.style.visibility = "hidden";
        el.style.opacity = 0;
      }
    });
  };
  immediateHide();
  let earlyTries = 0;
  const earlyInt = setInterval(() => {
    immediateHide();
    earlyTries++;
    if (earlyTries > 8) clearInterval(earlyInt);
  }, 250);
  try {
    const mo = new MutationObserver(() => immediateHide());
    mo.observe(document.documentElement, { childList: true, subtree: true });
    setTimeout(() => mo.disconnect(), 15000);
  } catch (_) {}
}

// Dev-only overlay to show recent console errors & warnings nicely.
// It monkey-patches console.error/warn (non-destructively) and stores last N entries.
// Shows only when there is at least 1 error or warning and process.env.NODE_ENV === 'development'.

const MAX_ENTRIES = 25;

const styles = {
  container: {
    position: "fixed",
    bottom: 12,
    right: 12,
    width: 420,
    maxHeight: 360,
    fontFamily: "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', monospace",
    fontSize: 12,
    background: "rgba(15,23,42,0.92)",
    color: "#e2e8f0",
    border: "1px solid #334155",
    borderRadius: 8,
    boxShadow: "0 8px 28px -4px rgba(0,0,0,.55)",
    backdropFilter: "blur(4px)",
    display: "flex",
    flexDirection: "column",
    zIndex: 4000,
  },
  header: {
    padding: "6px 10px",
    display: "flex",
    alignItems: "center",
    gap: 8,
    borderBottom: "1px solid #334155",
    background: "linear-gradient(90deg,#0f172a,#1e293b)",
  },
  list: { listStyle: "none", margin: 0, padding: "6px 0", overflowY: "auto" },
  item: { padding: "4px 10px", lineHeight: 1.35, whiteSpace: "pre-wrap", wordBreak: "break-word" },
  badge: (bg) => ({ display: "inline-block", fontSize: 10, padding: "2px 6px", borderRadius: 12, fontWeight: 600, background: bg, color: "#fff", letterSpacing: 0.5 }),
  footer: { padding: "4px 8px", borderTop: "1px solid #334155", display: "flex", gap: 6 },
};

export const CompileIssuesOverlay = () => {
  const [open, setOpen] = useState(true);
  const [entries, setEntries] = useState([]);
  const original = useRef({ error: null, warn: null });
  const autoClearTimer = useRef(null);
  const suppressionRef = useRef(false); // Add this to prevent infinite loops
  const pushRef = useRef(null); // Ref to hold the push function

  // Memoize the push function to prevent recreating it on every render
  const push = useCallback((type, args, isParsed = false) => {
    if (!isParsed || suppressionRef.current) return;

    const time = new Date().toISOString().split("T")[1].replace("Z", "");
    const text = args
      .map((a) => {
        if (a instanceof Error) return a.stack || a.message;
        if (typeof a === "object") {
          try {
            return JSON.stringify(a);
          } catch {
            return String(a);
          }
        }
        return String(a);
      })
      .join(" ");

    setEntries((prev) => {
      if (prev.some((e) => e.text === text && e.type === type)) return prev; // dedupe
      const next = [{ id: `${Date.now()}_${crypto.randomUUID()}`, type, text, time }, ...prev];
      return next.slice(0, MAX_ENTRIES);
    });
  }, []); // Empty dependency array since it doesn't depend on any props/state

  // Update the ref whenever push changes
  pushRef.current = push;

  useEffect(() => {
    if (process.env.NODE_ENV !== "development") return; // no-op in prod
    original.current.error = console.error;
    original.current.warn = console.warn;

    // Inline suppression of CRA / Webpack overlay so only this panel shows.
    const parseOverlayRawLater = (text) => parseOverlayRaw(text);

    const suppress = () => {
      if (suppressionRef.current) return; // Prevent recursive calls
      suppressionRef.current = true;

      try {
        const ids = ["webpack-dev-server-client-overlay", "webpack-dev-server-client-overlay-div"];
        ids.forEach((id) => {
          const el = document.getElementById(id);
          if (el) {
            const captured = el.textContent || "";
            parseOverlayRawLater(captured).forEach((r) => pushRef.current?.(r.type, [r.simplified], true));
            el.style.display = "none";
            el.style.visibility = "hidden";
            el.style.opacity = 0;
            el.style.pointerEvents = "none";
            el.textContent = "";
            el.dataset.devSuppressed = "1";
          }
        });
        Array.from(document.body.children).forEach((el) => {
          if (el.dataset.devSuppressed === "1") return;
          const style = window.getComputedStyle(el);
          const full =
            (style.position === "fixed" || style.position === "absolute") &&
            parseInt(style.zIndex || "0", 10) >= 1000 &&
            el.offsetWidth / window.innerWidth > 0.6 &&
            el.offsetHeight / window.innerHeight > 0.6;
          if (!full) return;
          const text = (el.textContent || "").toLowerCase();
          if (text.includes("compiled with problems") || text.includes("[eslint]") || text.includes("webpack compiled")) {
            el.style.display = "none";
            el.style.visibility = "hidden";
            el.style.opacity = 0;
            el.style.pointerEvents = "none";
            el.textContent = "";
            el.dataset.devSuppressed = "1";
          }
        });
      } finally {
        suppressionRef.current = false;
      }
    };
    suppress();
    let tries = 0;
    const max = 15;
    const int = setInterval(() => {
      suppress();
      tries++;
      if (tries >= max) clearInterval(int);
    }, 600);
    let mo;
    try {
      mo = new MutationObserver(() => suppress());
      mo.observe(document.documentElement, { childList: true, subtree: true });
      setTimeout(() => mo.disconnect(), 30000);
    } catch (_) {}

    // Do not capture generic console output anymore (runtime issues handled elsewhere)
    console.error = (...a) => {
      original.current.error?.(...a);
    };
    console.warn = (...a) => {
      original.current.warn?.(...a);
    };
    return () => {
      console.error = original.current.error;
      console.warn = original.current.warn;
      clearInterval(int);
      mo && mo.disconnect();
      suppressionRef.current = false;
    };
  }, []); // Remove push from dependencies to prevent circular updates

  // Auto-clear when there are no real problems (only warnings) after some time, or when empty.
  useEffect(() => {
    const hasError = entries.some((e) => e.type === "error");
    if (!hasError && entries.length > 0) {
      // Only warnings: show for 5s then clear
      clearTimeout(autoClearTimer.current);
      autoClearTimer.current = setTimeout(() => setEntries([]), 5000);
    } else if (entries.length === 0) {
      clearTimeout(autoClearTimer.current);
    } else if (hasError) {
      clearTimeout(autoClearTimer.current); // keep visible until resolved
    }
    return () => clearTimeout(autoClearTimer.current);
  }, [entries]);

  const hasProblems = entries.length > 0;
  if (process.env.NODE_ENV !== "development") return null;
  if (!hasProblems) return null;

  return (
    <div style={styles.container}>
      <div style={styles.header}>
        <span style={{ fontWeight: 600, fontSize: 12 }}>Compile Issues ({entries.length})</span>
        <button
          onClick={() => setOpen((o) => !o)}
          style={{ marginLeft: "auto", background: "#334155", color: "#e2e8f0", border: 0, fontSize: 11, padding: "4px 8px", borderRadius: 4, cursor: "pointer" }}>
          {open ? "Minimise" : "Expand"}
        </button>
        <button onClick={() => setEntries([])} style={{ background: "#475569", color: "#fff", border: 0, fontSize: 11, padding: "4px 8px", borderRadius: 4, cursor: "pointer" }}>
          Clear
        </button>
      </div>
      {open && (
        <>
          <ul style={styles.list}>
            {entries.map((e) => (
              <li key={e.id} style={{ ...styles.item, background: e.type === "error" ? "#431520" : "#2f2e17", padding: "6px 10px" }}>
                <code style={{ fontSize: 12, fontWeight: 500 }}>{e.text}</code>
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
};

export default CompileIssuesOverlay;
