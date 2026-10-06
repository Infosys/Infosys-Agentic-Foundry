/**
 * Centralized auth token storage using localStorage.
 *
 * localStorage persists across browser restarts, PC shutdowns, and has no
 * expiration — unlike cookies which expire and get cleared.
 *
 * All auth keys (jwt-token, refresh-token, user_session, userName, role, email)
 * are stored here instead of cookies.
 */

const AUTH_KEYS = {
  JWT: "jwt-token",
  REFRESH: "refresh-token",
  SESSION: "user_session",
  USERNAME: "userName",
  ROLE: "role",
  EMAIL: "email",
  DEPARTMENT: "department",
  LOGIN_TIMESTAMP: "login_timestamp",
};

// ─── Core helpers ────────────────────────────────────────────────────────────
// Sensitive auth data is stored in sessionStorage (tab-scoped, cleared on
// browser close) rather than localStorage to limit persistent exposure.
// On first read, any stale localStorage entry is migrated and removed.
//
// Each storage access is wrapped in its own try/catch so a failure on one
// storage (e.g. sessionStorage disabled by browser policy or private-mode
// quotas) never hides a valid value in the other storage. A previous version
// grouped both into a single try/catch, which meant a sessionStorage failure
// during migration would return null even though the JWT was still present
// in localStorage — silently breaking authenticated requests.

const isBadStringValue = (v) => v === "undefined" || v === "null" || v === "";

const readSession = (key) => {
  try {
    return sessionStorage.getItem(key);
  } catch (_) {
    return null;
  }
};

const readLocal = (key) => {
  try {
    return localStorage.getItem(key);
  } catch (_) {
    return null;
  }
};

const writeSession = (key, value) => {
  try {
    sessionStorage.setItem(key, value);
    return true;
  } catch (_) {
    return false;
  }
};

const clearLocal = (key) => {
  try {
    localStorage.removeItem(key);
  } catch (_) {}
};

const clearSession = (key) => {
  try {
    sessionStorage.removeItem(key);
  } catch (_) {}
};

const get = (key) => {
  // 1. Prefer sessionStorage (current source of truth)
  const sessionValue = readSession(key);
  if (sessionValue !== null && !isBadStringValue(sessionValue)) {
    return sessionValue;
  }

  // 2. Fallback to legacy localStorage entry (read-only).
  //    Do NOT write the localStorage value into sessionStorage — that would
  //    allow persistent cross-session data to contaminate the tab-scoped
  //    session (Fortify: Cross-Session Contamination).
  //    The legacy entry is cleaned up the next time set() or remove() is
  //    called for this key (e.g. on login or logout).
  const legacy = readLocal(key);
  if (legacy !== null && !isBadStringValue(legacy)) {
    return legacy;
  }

  return null;
};

const set = (key, value) => {
  if (value === null || value === void 0 || isBadStringValue(String(value))) {
    clearSession(key);
    clearLocal(key);
    return;
  }
  writeSession(key, value);
  clearLocal(key); // ensure no stale copy in localStorage
};

const remove = (key) => {
  clearSession(key);
  clearLocal(key); // clean up any legacy localStorage entry
};

// ─── JWT Token ───────────────────────────────────────────────────────────────

export const getJwt = () => get(AUTH_KEYS.JWT);
export const setJwt = (token) => set(AUTH_KEYS.JWT, token);
export const removeJwt = () => remove(AUTH_KEYS.JWT);

// ─── Refresh Token ───────────────────────────────────────────────────────────

export const getRefresh = () => get(AUTH_KEYS.REFRESH);
export const setRefresh = (token) => set(AUTH_KEYS.REFRESH, token);
export const removeRefresh = () => remove(AUTH_KEYS.REFRESH);

// ─── Session ─────────────────────────────────────────────────────────────────

export const getSession = () => get(AUTH_KEYS.SESSION);
export const setSession = (id) => set(AUTH_KEYS.SESSION, id);
export const removeSession = () => remove(AUTH_KEYS.SESSION);

// ─── User info ───────────────────────────────────────────────────────────────

export const getUserName = () => get(AUTH_KEYS.USERNAME) || get("active_user_name");
export const setUserName = (name) => {
  set(AUTH_KEYS.USERNAME, name);
  set("active_user_name", name);
};
export const removeUserName = () => {
  remove(AUTH_KEYS.USERNAME);
  remove("active_user_name");
};

export const getRole = () => get(AUTH_KEYS.ROLE);
export const setRole = (role) => set(AUTH_KEYS.ROLE, role);
export const removeRole = () => remove(AUTH_KEYS.ROLE);

export const getEmail = () => get(AUTH_KEYS.EMAIL);
export const setEmail = (email) => set(AUTH_KEYS.EMAIL, email);
export const removeEmail = () => remove(AUTH_KEYS.EMAIL);

export const getDepartment = () => get(AUTH_KEYS.DEPARTMENT);
export const setDepartment = (dept) => set(AUTH_KEYS.DEPARTMENT, dept);
export const removeDepartment = () => remove(AUTH_KEYS.DEPARTMENT);

// ─── Bulk operations ─────────────────────────────────────────────────────────

/**
 * Clear all auth-related keys from localStorage.
 */
export const clearAll = () => {
  removeJwt();
  removeRefresh();
  removeSession();
  removeUserName();
  removeRole();
  removeEmail();
  removeDepartment();
  remove(AUTH_KEYS.LOGIN_TIMESTAMP);
};

/**
 * Check if essential auth artifacts exist.
 * @param {boolean} strict - If true, also requires JWT. If false, only userName + session.
 */
export const hasAuthArtifacts = (strict = true) => {
  const userName = getUserName();
  const session = getSession();
  const jwt = getJwt();
  if (!strict) return Boolean(userName && session);
  return Boolean(userName && session && jwt);
};

const authStorageApi = {
  getJwt, setJwt, removeJwt,
  getRefresh, setRefresh, removeRefresh,
  getSession, setSession, removeSession,
  getUserName, setUserName, removeUserName,
  getRole, setRole, removeRole,
  getEmail, setEmail, removeEmail,
  getDepartment, setDepartment, removeDepartment,
  clearAll, hasAuthArtifacts,
  AUTH_KEYS,
};

export default authStorageApi;
