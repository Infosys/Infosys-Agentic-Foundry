import { msalInstance } from "./msalConfig";
import authStorage from "../utils/authStorage";

export const MSAL_MANUAL_LOGOUT_KEY = "manual_logout";
export const MSAL_AUTH_IN_PROGRESS_KEY = "msal_auth_in_progress";

// In-memory flag: true only when suppressMsalAutoLogin() was called in THIS
// JavaScript execution context (this page load). Resets to false on any fresh
// page load or tab open, so a stale sessionStorage "manual_logout" value from a
// previous session is ignored — letting auto-SSO fire again on fresh visits.
let _suppressedThisSession = false;

export const isMsalAutoLoginSuppressed = () => _suppressedThisSession;

export const suppressMsalAutoLogin = () => {
  const directSso =
    (window._env_ && window._env_.REACT_APP_DIRECT_SSO_LOGIN) ||
    process.env.REACT_APP_DIRECT_SSO_LOGIN;
  if (directSso === "true") return;
  _suppressedThisSession = true;
  sessionStorage.setItem(MSAL_MANUAL_LOGOUT_KEY, "true");
};

export const clearMsalAutoLoginSuppression = () => {
  _suppressedThisSession = false;
  sessionStorage.removeItem(MSAL_MANUAL_LOGOUT_KEY);
};

export const markMsalAuthInProgress = () => {
  sessionStorage.setItem(MSAL_AUTH_IN_PROGRESS_KEY, "true");
};

export const clearMsalAuthInProgress = () => {
  sessionStorage.removeItem(MSAL_AUTH_IN_PROGRESS_KEY);
};

export const isMsalAuthInProgress = () =>
  sessionStorage.getItem(MSAL_AUTH_IN_PROGRESS_KEY) === "true";

/** True when MSAL redirect response is in the URL or being processed. */
export const isMsalLoginPending = () => {
  if (isMsalAuthInProgress()) return true;
  // Ignore stale URL params once MSAL session artifacts exist (prevents blank page after login)
  if (localStorage.getItem("auth_type") === "msal" && authStorage.hasAuthArtifacts(false)) {
    return false;
  }
  return hasPendingMsalRedirect();
};

/** True when the URL still contains an MSAL authorization redirect response. */
export const hasPendingMsalRedirect = () => {
  if (typeof window === "undefined") return false;
  const combined = `${window.location.search}${window.location.hash}`;
  return /(?:^|[?#&])(code|error|state|session_state)=/i.test(combined);
};

/** Clear cached MSAL tokens/accounts without a full app logout redirect. */
export async function clearMsalSession() {
  clearMsalAuthInProgress();
  try {
    if (typeof msalInstance.setActiveAccount === "function") {
      msalInstance.setActiveAccount(null);
    }
  } catch (_) {}

  try {
    if (typeof msalInstance.clearCache === "function") {
      await msalInstance.clearCache();
    }
  } catch (_) {}

  try {
    const accounts = msalInstance.getAllAccounts();
    for (const account of accounts) {
      await msalInstance.clearCache({ account });
    }
  } catch (_) {
    // Non-critical — local onboarding exit should still proceed
  }

  // Fallback: remove MSAL keys left in sessionStorage after clearCache
  try {
    Object.keys(sessionStorage)
      .filter((key) => key.startsWith("msal") || key.includes(".authority"))
      .forEach((key) => sessionStorage.removeItem(key));
  } catch (_) {}
}

/** Leave SSO onboarding (pending approval / department selection) and show login. */
export async function exitSsoOnboardingToLogin() {
  suppressMsalAutoLogin();
  await clearMsalSession();
  localStorage.removeItem("auth_type");
}
