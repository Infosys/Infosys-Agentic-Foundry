/**
 * Base64-encode a pwd before sending it in an API payload.
 * Uses btoa with a Unicode-safe fallback (TextEncoder → binary string).
 * Returns an empty string if the input is falsy.
 *
 * @param {string} pwd - The plaintext pwd to encode.
 * @returns {string} Base64-encoded pwd.
 */
export const encodePassword = (pwd) => {
  if (!pwd) return "";
  try {
    // Handle Unicode characters safely
    const bytes = new TextEncoder().encode(pwd);
    const binary = Array.from(bytes, (b) => String.fromCharCode(b)).join("");
    return btoa(binary);
  } catch {
    return btoa(pwd);
  }
};
