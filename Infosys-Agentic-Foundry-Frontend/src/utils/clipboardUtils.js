/**
 * Clipboard Utilities
 *
 * Provides reliable clipboard operations with fallback support.
 *
 * Why navigator.clipboard can be undefined:
 * 1. Non-HTTPS context (API only works on HTTPS or localhost)
 * 2. Browser window/tab lost focus
 * 3. Running inside iframe without clipboard-write permission
 * 4. Older browser without Clipboard API support
 * 5. User denied clipboard permissions
 */

/**
 * Copy text to clipboard with fallback support
 * @param {string} text - The text to copy
 * @returns {Promise<boolean>} - Whether the copy was successful
 */
export const copyToClipboard = async (text) => {
  // Modern async clipboard API (requires HTTPS or localhost)
  if (navigator.clipboard && typeof navigator.clipboard.writeText === "function") {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch (err) {
      // Fall through to legacy method if permission denied or focus lost
      console.warn("Clipboard API failed, trying fallback:", err);
    }
  }

  // Legacy fallback using execCommand (works in more contexts)
  try {
    const textArea = document.createElement("textarea");
    textArea.value = text;
    // Prevent scrolling and make invisible
    textArea.style.position = "fixed";
    textArea.style.top = "-9999px";
    textArea.style.left = "-9999px";
    textArea.style.opacity = "0";
    textArea.setAttribute("readonly", ""); // Prevent mobile keyboard popup
    document.body.appendChild(textArea);
    textArea.focus();
    textArea.select();
    const success = document.execCommand("copy");
    document.body.removeChild(textArea);
    return success;
  } catch (err) {
    console.error("Fallback copy failed:", err);
    return false;
  }
};

/**
 * Check if clipboard API is available in current context
 * @returns {boolean}
 */
export const isClipboardAvailable = () => {
  return Boolean(navigator.clipboard && typeof navigator.clipboard.writeText === "function");
};

/**
 * Read text from clipboard (with fallback not possible for security)
 * @returns {Promise<string|null>} - The clipboard text or null if failed
 */
export const readFromClipboard = async () => {
  if (navigator.clipboard && typeof navigator.clipboard.readText === "function") {
    try {
      return await navigator.clipboard.readText();
    } catch (err) {
      console.error("Failed to read from clipboard:", err);
      return null;
    }
  }
  console.warn("Clipboard read API not available");
  return null;
};
