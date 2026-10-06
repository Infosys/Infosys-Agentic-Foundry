import { axiosInstance } from "../Hooks/useAxios";

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

export const getMsalAuthErrorMessage = (error) => {
  if (!error) return "Microsoft sign-in failed. Please try again.";
  if (typeof error === "string") return formatMsalLoginErrorMessage(error);
  if (error.message) return formatMsalLoginErrorMessage(error.message);
  return "Microsoft sign-in failed. Please try again.";
};

const extractApiErrorMessage = (data) => {
  if (!data) return null;
  if (typeof data === "string") {
    const trimmed = data.trim();
    return trimmed || null;
  }
  if (typeof data === "object") {
    const parsed = parseApiDetail(data.detail) || data.error || data.message || data.msg;
    if (parsed) return parsed;
    const keys = Object.keys(data);
    if (keys.length === 1 && typeof keys[0] === "string" && keys[0].trim()) {
      return keys[0].trim();
    }
  }
  return null;
};

/** User-facing message for MSAL login failures surfaced on /login. */
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

/** Build /login route with an encoded MSAL error for toast + banner handling. */
export const buildLoginMsalErrorPath = (message) =>
  `/login?msalError=${encodeURIComponent(formatMsalLoginErrorMessage(message))}`;

const AUTH_ME_SUCCESS_STATUSES = new Set([
  "USER_EXISTS",
  "NEEDS_DEPARTMENT_SELECTION",
  "PENDING_APPROVAL",
]);

/** Provisioning statuses that complete MSAL login (not error screens). */
export const isAuthMeSuccessStatus = (status) =>
  AUTH_ME_SUCCESS_STATUSES.has((status || "").toUpperCase());

/** Error text from a 200 /auth/me body when status is ERROR or another failure state. */
export const getAuthMeResponseErrorMessage = (me, fallback = "Microsoft sign-in failed. Please try again.") => {
  if (me?.message && String(me.message).trim()) {
    return String(me.message).trim();
  }
  return fallback;
};

/**
 * Calls GET /auth/me with the MSAL access token to determine the user's
 * provisioning state. Called once per login in MsalAuthCallback.
 *
 * @param {string} accessToken - MSAL access token
 * @returns {Promise<{email, username, status, message}>}
 */
export async function checkUserStatus(accessToken) {
  try {
    const res = await axiosInstance.get("/auth/me", {
      headers: {
        Authorization: `Bearer ${accessToken}`,
      },
    });
    return res.data;
  } catch (err) {
    const errData = err?.response?.data;
    const status = err?.response?.status;
    const apiMessage = extractApiErrorMessage(errData);
    const fallback =
      status === 504
        ? "Authentication service timed out. Please try again later."
        : err?.message || `HTTP ${status || "error"}`;
    throw new Error(formatMsalLoginErrorMessage(apiMessage || fallback));
  }
}
