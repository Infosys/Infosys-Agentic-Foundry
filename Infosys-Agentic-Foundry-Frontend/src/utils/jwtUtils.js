import Cookies from "js-cookie";
import authStorage from "./authStorage";

/**
 * Decode the payload of a JWT token without verifying the signature.
 * @param {string} token - The JWT token string
 * @returns {object|null} Decoded payload object or null on failure
 */
export const decodeJwtPayload = (token) => {
  try {
    if (!token) return null;
    const base64Url = token.split(".")[1];
    const base64 = base64Url.replace(/-/g, "+").replace(/_/g, "/");
    const jsonPayload = decodeURIComponent(
      atob(base64)
        .split("")
        .map((c) => "%" + ("00" + c.charCodeAt(0).toString(16)).slice(-2))
        .join("")
    );
    return JSON.parse(jsonPayload);
  } catch {
    return null;
  }
};

const getAppAuthType = () => {
  try {
    return localStorage.getItem("auth_type");
  } catch {
    return null;
  }
};

const getStoredDepartment = () =>
  authStorage.getDepartment() ||
  Cookies.get("department_name") ||
  Cookies.get("department") ||
  (typeof window !== "undefined" ? window.localStorage.getItem("user_department") : null) ||
  "";

/**
 * Get the department_name from the JWT bearer token.
 * Falls back to stored auth artifacts when the token is missing or invalid.
 * MSAL sessions store a Microsoft access token — not the app JWT — so always use storage fallbacks.
 * @returns {string} The department name, or empty string if unavailable
 */
export const getDepartmentFromToken = () => {
  if (getAppAuthType() === "msal") {
    return getStoredDepartment();
  }

  const token = authStorage.getJwt();
  const payload = decodeJwtPayload(token);
  return payload?.department_name || getStoredDepartment();
};

/**
 * Get the role from the JWT bearer token.
 * Falls back to stored auth artifacts when the token is missing or invalid.
 * MSAL sessions store a Microsoft access token — not the app JWT — so always use storage fallbacks.
 * @returns {string} The role, or empty string if unavailable
 */
export const getRoleFromToken = () => {
  if (getAppAuthType() === "msal") {
    return authStorage.getRole() || Cookies.get("role") || "";
  }

  const token = authStorage.getJwt();
  const payload = decodeJwtPayload(token);
  return payload?.role || authStorage.getRole() || Cookies.get("role") || "";
};

/**
 * Get the email (mail_id) from the JWT bearer token.
 * Falls back to the "email" cookie if the token is missing or invalid.
 * @returns {string} The user email, or empty string if unavailable
 */
export const getEmailFromToken = () => {
  if (getAppAuthType() === "msal") {
    return authStorage.getEmail() || Cookies.get("email") || "";
  }

  const token = authStorage.getJwt();
  const payload = decodeJwtPayload(token);
  return payload?.mail_id || authStorage.getEmail() || Cookies.get("email") || "";
};

/**
 * Get the user name from the JWT bearer token.
 * Falls back to the "userName" cookie if the token is missing or invalid.
 * @returns {string} The user name, or empty string if unavailable
 */
export const getUserNameFromToken = () => {
  if (getAppAuthType() === "msal") {
    return authStorage.getUserName() || Cookies.get("userName") || "";
  }

  const token = authStorage.getJwt();
  const payload = decodeJwtPayload(token);
  return payload?.user_name || authStorage.getUserName() || Cookies.get("userName") || "";
};
