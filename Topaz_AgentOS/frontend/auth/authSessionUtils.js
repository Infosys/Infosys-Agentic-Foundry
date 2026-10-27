/**
 * Session-level auth error helpers.
 *
 * isDeletedAccountError — detects the specific 403 the backend returns when
 * a deactivated SSO user tries to access a protected resource.
 *
 * dispatchGlobalAuth401 — fires a custom DOM event so any registered listener
 * (e.g. a global interceptor) can trigger an app-level logout/redirect.
 */

const getErrorDetail = (error) => {
  const detail =
    error?.response?.data?.detail ??
    error?.response?.data?.message ??
    "";
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((item) => (typeof item === "string" ? item : item?.msg || ""))
      .filter(Boolean)
      .join(" ");
  }
  return "";
};

/** True when the backend returned 403 with the deactivated-SSO-user detail. */
export const isDeletedAccountError = (error) => {
  if (error?.response?.status !== 403) return false;
  const detail = getErrorDetail(error);
  return detail.includes("Access restricted") && detail.includes("unregistered");
};

/** Dispatch a globalAuth401 custom event so app-level interceptors can react. */
export const dispatchGlobalAuth401 = (detail = {}) => {
  try {
    window.dispatchEvent(new CustomEvent("globalAuth401", { detail }));
  } catch (_) {}
};
