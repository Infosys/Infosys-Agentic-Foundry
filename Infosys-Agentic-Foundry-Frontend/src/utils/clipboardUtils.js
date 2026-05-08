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

// Max safe size for clipboard copy (100KB) to prevent browser freeze/crash
// Even the modern clipboard API can cause memory pressure and crash tabs with very large text
const MAX_COPY_SIZE = 100 * 1024;

/**
 * Copy text to clipboard with fallback support
 * @param {string} text - The text to copy
 * @returns {Promise<"success"|"too_large"|"failed">} - Result of the copy operation
 */
export const copyToClipboard = async (text) => {
  // Guard: block ALL clipboard methods for very large text to prevent browser crash
  if (text && text.length > MAX_COPY_SIZE) {
    console.warn(`Text too large to copy (${(text.length / 1024).toFixed(0)}KB). Limit is ${MAX_COPY_SIZE / 1024}KB. Use download instead.`);
    return "too_large";
  }

  // Modern async clipboard API (requires HTTPS or localhost)
  if (navigator.clipboard && typeof navigator.clipboard.writeText === "function") {
    try {
      await navigator.clipboard.writeText(text);
      return "success";
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
    return success ? "success" : "failed";
  } catch (err) {
    console.error("Fallback copy failed:", err);
    return "failed";
  }
};

/**
 * Download text content as a file — fallback when clipboard copy is not possible
 * @param {string} text - The text content to download
 * @param {string} [filename="code.py"] - The filename for the download
 */
export const downloadAsFile = (text, filename = "code.py") => {
  try {
    const blob = new Blob([text], { type: "text/plain;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
  } catch (err) {
    console.error("Download failed:", err);
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