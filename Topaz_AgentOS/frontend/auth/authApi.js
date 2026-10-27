/**
 * MSAL auth API helpers.
 *
 * checkUserStatus() exchanges an MSAL access token for an IAF session by
 * calling POST /auth/sso/microsoft on the backend. All other exports are
 * pure formatting / classification utilities that carry no side-effects.
 */

const _env = (key) =>
  (typeof window !== "undefined" && window._env_ && window._env_[key]) ||
  process.env[key] ||
  "";

// Strip trailing slash so callers can freely write `${API_BASE}/path`.
const API_BASE = _env("REACT_APP_API_BASE_URL").replace(/\/$/, "");


const parseApiDetail = (detail) => {
  if (!detail) return null;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((item) => (typeof item === "string" ? item : item?.msg || item?.message))
      .filter(Boolean)
      .join("; ");
  }
  if (typeof detail === "object" && (detail.message || detail.msg)) {
    return detail.message || detail.msg;
  }
  return null;
};

const extractApiErrorMessage = (data) => {
  if (!data) return null;
  if (typeof data === "string") return data.trim() || null;
  if (typeof data === "object") {
    return (
      parseApiDetail(data.detail) ||
      data.error ||
      data.message ||
      data.msg ||
      null
    );
  }
  return null;
};


/** Human-readable message for an MSAL error object or string. */
export const getMsalAuthErrorMessage = (error) => {
  if (!error) return "Microsoft sign-in failed. Please try again.";
  if (typeof error === "string") return formatMsalLoginErrorMessage(error);
  if (error.message) return formatMsalLoginErrorMessage(error.message);
  return "Microsoft sign-in failed. Please try again.";
};

/** Map known error patterns to user-facing strings. */
export const formatMsalLoginErrorMessage = (raw) => {
  const message = String(raw || "").trim();
  if (!message) return "Microsoft sign-in failed. Please try again.";
  if (/account deactivated|user deactivated|deactivated/i.test(message)) {
    return "Your account has been deactivated. Please contact your administrator.";
  }
  if (/504|gateway timeout/i.test(message)) {
    return "Authentication service timed out. Please try again later.";
  }
  if (/502|503/.test(message)) {
    return "Authentication service is temporarily unavailable. Please try again.";
  }
  const statusMatch = message.match(/status code (\d{3})/i);
  if (statusMatch) {
    const status = statusMatch[1];
    if (status === "504") return "Authentication service timed out. Please try again later.";
    if (status === "502" || status === "503") {
      return "Authentication service is temporarily unavailable. Please try again.";
    }
    return `Sign-in failed (${status}). Please try again.`;
  }
  return message;
};

/** Build /login route with an encoded MSAL error for banner/toast handling. */
export const buildLoginMsalErrorPath = (message) =>
  `/login?msalError=${encodeURIComponent(formatMsalLoginErrorMessage(message))}`;


const AUTH_ME_SUCCESS_STATUSES = new Set([
  "USER_EXISTS",
  "NEEDS_DEPARTMENT_SELECTION",
  "PENDING_APPROVAL",
]);

/** True when the backend provisioning status indicates a non-error login outcome. */
export const isAuthMeSuccessStatus = (status) =>
  AUTH_ME_SUCCESS_STATUSES.has((status || "").toUpperCase());

/** Extract error text from a 200 /auth/sso/microsoft body when status indicates failure. */
export const getAuthMeResponseErrorMessage = (
  me,
  fallback = "Microsoft sign-in failed. Please try again."
) => {
  if (me?.message && String(me.message).trim()) return String(me.message).trim();
  return fallback;
};


/**
 * Exchange an MSAL access token for an IAF session.
 *
 * Calls POST /auth/sso/microsoft with the MSAL token as Bearer. The backend
 * validates the token via Azure AD JWKS, provisions the user if needed, and
 * returns IAF session cookies + a JSON body:
 *   { status, email, username, access_token?, user?, must_change_password? }
 *
 * @param {string} accessToken - MSAL access token from getAccessToken()
 * @returns {Promise<{status: string, email: string, username: string, [key: string]: any}>}
 */
export async function checkUserStatus(accessToken) {
  let res;
  try {
    res = await fetch(`${API_BASE}/auth/sso/microsoft`, {
      method: "POST",
      credentials: "include",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${accessToken}`,
      },
    });
  } catch (networkErr) {
    throw new Error("Authentication service unreachable. Please try again.");
  }

  if (!res.ok) {
    let errData;
    try { errData = await res.json(); } catch (_) {}
    const apiMessage = extractApiErrorMessage(errData);
    const fallback =
      res.status === 504
        ? "Authentication service timed out. Please try again later."
        : `HTTP ${res.status}`;
    throw new Error(formatMsalLoginErrorMessage(apiMessage || fallback));
  }

  return res.json();
}
