/**
 * Polyfill for crypto.randomUUID()
 * Works in non-secure contexts (HTTP) and older browsers
 * Generates RFC4122 version 4 compliant UUIDs
 */
export const generateUUID = () => {
  // Try native implementation first (works in HTTPS/secure contexts)
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    try {
      return crypto.randomUUID();
    } catch (e) {
      // Fall through to polyfill if it fails
    }
  }

  // Polyfill implementation
  // Uses Math.random() as fallback (less secure but works everywhere)
  return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, function (c) {
    const r = (Math.random() * 16) | 0;
    const v = c === "x" ? r : (r & 0x3) | 0x8;
    return v.toString(16);
  });
};
