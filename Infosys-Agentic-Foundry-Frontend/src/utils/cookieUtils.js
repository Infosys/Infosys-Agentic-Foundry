import Cookies from "js-cookie";

/**
 * Port-scoped cookie patch.
 *
 * Problem: Browsers share cookies across all ports on the same domain.
 * Logging into localhost:3003 also authenticates localhost:6001.
 *
 * Solution: Monkey-patch js-cookie's get/set/remove so that every
 * auth-related cookie name is transparently prefixed with the port
 * (e.g. "role" → "p3003_role"). This is done ONCE at app startup
 * and requires zero changes in any other file.
 */

// Auth cookie names that must be port-isolated
const SCOPED_COOKIE_NAMES = new Set([
  "userName",
  "jwt-token",
  "user_session",
  "role",
  "email",
  "department",
  "refresh-token",
  "login_timestamp",
]);

/** Build a port prefix like "p3003_" */
const getPortPrefix = () => {
  try {
    const port = window.location.port;
    return port ? `p${port}_` : "";
  } catch (_) {
    return "";
  }
};

/** Prefix a cookie name if it's an auth cookie */
const toScopedName = (name) => {
  if (SCOPED_COOKIE_NAMES.has(name)) {
    return `${getPortPrefix()}${name}`;
  }
  return name; // non-auth cookies pass through unchanged
};

/**
 * Call this ONCE before the app renders (in index.js).
 * It replaces Cookies.get / Cookies.set / Cookies.remove with
 * port-aware versions so every file that uses `Cookies.get("role")`
 * automatically reads/writes the port-scoped cookie.
 *
 * Safe to call multiple times — the patch is applied only once.
 */
let _patched = false;

export const patchCookiesForPortScoping = () => {
  if (_patched) return; // idempotent
  _patched = true;
  const originalGet = Cookies.get.bind(Cookies);
  const originalSet = Cookies.set.bind(Cookies);
  const originalRemove = Cookies.remove.bind(Cookies);

  // Patch get — when called with a specific name, scope it
  Cookies.get = function (name, ...rest) {
    if (name === undefined) {
      // Cookies.get() with no args returns all cookies — pass through
      return originalGet();
    }
    return originalGet(toScopedName(name), ...rest);
  };

  // Patch set
  Cookies.set = function (name, value, options) {
    return originalSet(toScopedName(name), value, options);
  };

  // Patch remove
  Cookies.remove = function (name, options) {
    return originalRemove(toScopedName(name), options);
  };
};
