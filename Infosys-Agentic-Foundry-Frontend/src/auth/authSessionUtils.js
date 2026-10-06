const getErrorDetail = (error) => {
  const detail = error?.response?.data?.detail ?? error?.response?.data?.message ?? "";
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((item) => (typeof item === "string" ? item : item?.msg || ""))
      .filter(Boolean)
      .join(" ");
  }
  return "";
};

/** Deleted/deactivated SSO user — backend returns this specific 403 detail. */
export const isDeletedAccountError = (error) => {
  if (error?.response?.status !== 403) return false;
  const detail = getErrorDetail(error);
  return detail.includes("Access restricted") && detail.includes("unregistered");
};

export const dispatchGlobalAuth401 = (detail = {}) => {
  try {
    window.dispatchEvent(new CustomEvent("globalAuth401", { detail }));
  } catch (_) {}
};
