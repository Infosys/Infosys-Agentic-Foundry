import { APIs } from "../constant";
import { axiosInstance } from "../Hooks/useAxios";

/**
 * Check if a URL is a download link that requires authentication
 * @param {string} url - The URL to check
 * @returns {boolean} - True if the URL is a download link
 */
export const isAuthenticatedDownloadLink = (url) => {
  if (!url) return false;
  
  // Check if it's a download file API link
  const downloadPatterns = [
    APIs.DOWNLOAD_FILE,
    "/download",
    "/files/download",
  ];
  
  return downloadPatterns.some((pattern) => url.includes(pattern));
};

/**
 * Extract filename from URL or Content-Disposition header
 * @param {string} url - The download URL
 * @param {Object} headers - Axios response headers (optional)
 * @returns {string} - The filename
 */
const extractFilename = (url, headers = null) => {
  // Try to get from Content-Disposition header
  if (headers) {
    const contentDisposition = headers["content-disposition"];
    if (contentDisposition) {
      const filenameMatch = contentDisposition.match(/filename[^;=\n]*=((['"]).*?\2|[^;\n]*)/);
      if (filenameMatch && filenameMatch[1]) {
        return filenameMatch[1].replace(/['"]/g, "");
      }
    }
  }
  
  // Try to extract from URL query parameter
  try {
    const urlObj = new URL(url, window.location.origin);
    const filenameParam = urlObj.searchParams.get("filename");
    if (filenameParam) {
      // Extract just the filename from a potential path
      return filenameParam.split("/").pop();
    }
  } catch {
    // URL parsing failed, continue
  }
  
  // Fallback: extract from URL path
  const pathParts = url.split("/");
  const lastPart = pathParts[pathParts.length - 1];
  if (lastPart && !lastPart.includes("?")) {
    return lastPart;
  }
  
  return "download";
};

/**
 * Handle authenticated file download using the shared axiosInstance.
 * axiosInstance already has baseURL and auth interceptors configured,
 * so we don't need to manually build URLs or attach tokens.
 *
 * @param {string} url - The download URL (relative or absolute)
 * @param {Function} onError - Optional error callback (receives error message string)
 * @returns {Promise<void>}
 */
export const handleAuthenticatedDownload = async (url, onError = null) => {
  try {
    const response = await axiosInstance.get(url, {
      responseType: "blob",
    });

    const blob = response.data;
    if (!blob) throw new Error("Failed to download file");

    // Get filename from headers or URL
    const filename = extractFilename(url, response.headers);

    // Create download link and trigger download
    const downloadUrl = window.URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = downloadUrl;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);

    // Clean up the blob URL
    setTimeout(() => {
      window.URL.revokeObjectURL(downloadUrl);
    }, 100);

  } catch (error) {
    console.error("Authenticated download failed:", error);
    // Try to extract a readable message from axios error shape
    const errMsg =
      error?.response?.data?.detail ||
      error?.response?.data?.message ||
      error?.response?.data?.error ||
      error?.message ||
      "Download failed";
    if (onError) {
      onError(errMsg);
    }
  }
};
