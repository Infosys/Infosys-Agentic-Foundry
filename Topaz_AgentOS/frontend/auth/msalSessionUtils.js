import { msalInstance } from "./msalConfig";
import { hasAuthArtifacts } from "./authStorage";

export const MSAL_MANUAL_LOGOUT_KEY    = "manual_logout";
export const MSAL_AUTH_IN_PROGRESS_KEY = "msal_auth_in_progress";

// In-memory flag; resets on every page load so a stale sessionStorage "manual_logout" is ignored.
let _suppressedThisSession = false;

export const isMsalAutoLoginSuppressed = () => _suppressedThisSession;

export const suppressMsalAutoLogin = () => {
  const directSso =
    (typeof window !== "undefined" && window._env_?.REACT_APP_DIRECT_SSO_LOGIN) ||
    process.env.REACT_APP_DIRECT_SSO_LOGIN;
  if (directSso === "true") return;
  _suppressedThisSession = true;
  try { sessionStorage.setItem(MSAL_MANUAL_LOGOUT_KEY, "true"); } catch (_) {}
};

export const clearMsalAutoLoginSuppression = () => {
  _suppressedThisSession = false;
  try { sessionStorage.removeItem(MSAL_MANUAL_LOGOUT_KEY); } catch (_) {}
};

export const markMsalAuthInProgress = () => {
  try { sessionStorage.setItem(MSAL_AUTH_IN_PROGRESS_KEY, "true"); } catch (_) {}
};

export const clearMsalAuthInProgress = () => {
  try { sessionStorage.removeItem(MSAL_AUTH_IN_PROGRESS_KEY); } catch (_) {}
};

export const isMsalAuthInProgress = () => {
  try { return sessionStorage.getItem(MSAL_AUTH_IN_PROGRESS_KEY) === "true"; } catch (_) { return false; }
};

/** True when the URL still contains an MSAL authorization redirect response. */
export const hasPendingMsalRedirect = () => {
  if (typeof window === "undefined") return false;
  const combined = `${window.location.search}${window.location.hash}`;
  return /(?:^|[?#&])(code|error|state|session_state)=/i.test(combined);
};

/** True when MSAL redirect response is in the URL or is being processed. */
export const isMsalLoginPending = () => {
  if (isMsalAuthInProgress()) return true;
  // Ignore stale URL params when a valid MSAL session already exists
  if (
    localStorage.getItem("auth_type") === "msal" &&
    hasAuthArtifacts(false)
  ) {
    return false;
  }
  return hasPendingMsalRedirect();
};

/** Clear cached MSAL tokens/accounts without triggering a full logout redirect. */
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
  } catch (_) {}

  // Fallback: remove residual MSAL sessionStorage keys
  try {
    Object.keys(sessionStorage)
      .filter((k) => k.startsWith("msal") || k.includes(".authority"))
      .forEach((k) => sessionStorage.removeItem(k));
  } catch (_) {}
}

/** Leave SSO onboarding flow (pending approval / dept selection) and show login page. */
export async function exitSsoOnboardingToLogin() {
  suppressMsalAutoLogin();
  await clearMsalSession();
  try { localStorage.removeItem("auth_type"); } catch (_) {}
}
