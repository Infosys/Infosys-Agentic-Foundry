import Cookies from "js-cookie";

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

/**
 * Get the department_name from the JWT bearer token.
 * Falls back to the "department" cookie if the token is missing or invalid.
 * @returns {string} The department name, or empty string if unavailable
 */
export const getDepartmentFromToken = () => {
  const token = Cookies.get("jwt-token");
  const payload = decodeJwtPayload(token);
  return payload?.department_name || Cookies.get("department") || "";
};

/**
 * Get the role from the JWT bearer token.
 * Falls back to the "role" cookie if the token is missing or invalid.
 * @returns {string} The role, or empty string if unavailable
 */
export const getRoleFromToken = () => {
  const token = Cookies.get("jwt-token");
  const payload = decodeJwtPayload(token);
  return payload?.role || Cookies.get("role") || "";
};

/**
 * Get the email (mail_id) from the JWT bearer token.
 * Falls back to the "email" cookie if the token is missing or invalid.
 * @returns {string} The user email, or empty string if unavailable
 */
export const getEmailFromToken = () => {
  const token = Cookies.get("jwt-token");
  const payload = decodeJwtPayload(token);
  return payload?.mail_id || Cookies.get("email") || "";
};

/**
 * Get the user name from the JWT bearer token.
 * Falls back to the "userName" cookie if the token is missing or invalid.
 * @returns {string} The user name, or empty string if unavailable
 */
export const getUserNameFromToken = () => {
  const token = Cookies.get("jwt-token");
  const payload = decodeJwtPayload(token);
  return payload?.user_name || Cookies.get("userName") || "";
};
