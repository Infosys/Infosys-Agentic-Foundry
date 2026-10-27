/**
 * Lightweight auth-state helpers for localStorage/sessionStorage.
 *
 * Used by msalSessionUtils to detect whether a valid MSAL session already
 * exists so the redirect-pending check doesn't trigger on a stale URL.
 */

const AUTH_TYPE_KEY = "auth_type";

/**
 * Returns true when auth artifacts are present in storage.
 * @param {boolean} checkSessionStorage - also scan sessionStorage for MSAL keys
 */
export const hasAuthArtifacts = (checkSessionStorage = true) => {
  try {
    if (localStorage.getItem(AUTH_TYPE_KEY)) return true;
  } catch (_) {}

  if (!checkSessionStorage) {
    try {
      return Object.keys(sessionStorage).some(
        (k) => k.startsWith("msal") || k.includes(".authority")
      );
    } catch (_) {}
  }
  return false;
};

export const setAuthType = (type) => {
  try { localStorage.setItem(AUTH_TYPE_KEY, type); } catch (_) {}
};

export const getAuthType = () => {
  try { return localStorage.getItem(AUTH_TYPE_KEY); } catch (_) { return null; }
};

export const clearAuthType = () => {
  try { localStorage.removeItem(AUTH_TYPE_KEY); } catch (_) {}
};

export default { hasAuthArtifacts, setAuthType, getAuthType, clearAuthType };
