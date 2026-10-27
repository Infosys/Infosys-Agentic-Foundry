// MSAL config + instance
export { msalInstance, msalConfig, loginRequest, logoutRequest } from "./msalConfig";

// Token acquisition
export { getAccessToken } from "./tokenProvider";

// Session state management
export {
  MSAL_MANUAL_LOGOUT_KEY,
  MSAL_AUTH_IN_PROGRESS_KEY,
  isMsalAutoLoginSuppressed,
  suppressMsalAutoLogin,
  clearMsalAutoLoginSuppression,
  markMsalAuthInProgress,
  clearMsalAuthInProgress,
  isMsalAuthInProgress,
  hasPendingMsalRedirect,
  isMsalLoginPending,
  clearMsalSession,
  exitSsoOnboardingToLogin,
} from "./msalSessionUtils";

// Backend SSO exchange + error formatting
export {
  getMsalAuthErrorMessage,
  formatMsalLoginErrorMessage,
  buildLoginMsalErrorPath,
  isAuthMeSuccessStatus,
  getAuthMeResponseErrorMessage,
  checkUserStatus,
} from "./authApi";

// HTTP error classification
export { isDeletedAccountError, dispatchGlobalAuth401 } from "./authSessionUtils";

// Storage utilities
export { hasAuthArtifacts, setAuthType, getAuthType, clearAuthType } from "./authStorage";
