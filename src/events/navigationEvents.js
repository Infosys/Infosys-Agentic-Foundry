import React from "react";

// Global event utilities for handling clicks on an already-active navigation link.
// Lightweight pub/sub with a React hook for page-level opt-in behavior.
// Future pages can subscribe via useActiveNavClick([paths], handler).

const activeClickListeners = new Set();

export function emitActiveNavClick(path) {
  activeClickListeners.forEach((fn) => {
    try {
      fn(path);
    } catch (e) {
      // isolate listener failures
    }
  });
}

export function onActiveNavClick(handler) {
  activeClickListeners.add(handler);
  return () => activeClickListeners.delete(handler);
}

export function useActiveNavClick(targetPaths, handler) {
  const normalized = React.useMemo(
    () => (Array.isArray(targetPaths) ? targetPaths : [targetPaths]),
    [targetPaths]
  );
  React.useEffect(() => {
    const off = onActiveNavClick((path) => {
      if (normalized.includes(path)) {
        handler(path);
      }
    });
    return off;
  }, [handler, normalized]);
}
