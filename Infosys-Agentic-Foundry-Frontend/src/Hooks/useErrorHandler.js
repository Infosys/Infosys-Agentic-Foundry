import { useCallback, useEffect } from "react";
import { useAuth } from "../context/AuthContext";
import { useMessage } from "./MessageContext"; // assumes MessageContext exports useMessage
import { extractErrorMessage, extractErrorWithFriendlyMessage } from "../utils/errorUtils";

// dynamic suppression support (module scoped) ---
let suppressedStatusCodes = new Set();

/**
 * Programmatically set which HTTP status codes should NOT trigger toast popups.
 * How to enable ERROR popup suppression
 * Option A:
 * Add to your .env.local:
 * REACT_APP_SUPPRESS_404_TOASTS = "true"
 *
 * Option B: (runtime toggle anywhere after app mounts)
 * In the file or screen or service where you want to suppress an error  import the hook ->
 * import { setSuppressedErrorStatuses } from "../Hooks/useErrorHandler";
 * Then call it with an array of integer status codes to suppress:
 * Example: setSuppressedErrorStatuses([404, 409])
 *
 * Option C: - Pass silent flag conditionally in call site when you know a 404 is an expected probe:
 * try {
 *  await fetchData(url);
 * } catch (e) {
 *   useErrorHandler().handleApiError(e, { silent: e?.response?.status === 404 });
 * }
 */
export const setSuppressedErrorStatuses = (codes = []) => {
  try {
    suppressedStatusCodes = new Set((codes || [404]).filter((c) => Number.isInteger(c)));
  } catch {
    suppressedStatusCodes = new Set();
  }
};

/**
 * Suppressed Error propagation chain:
 * Component → ErrorBoundary → global events → useAxios loop blocking → useErrorHandler normalization (via errorUtils) → user toast via MessageContext → optional layering via apiErrorHandler.safeApiCall.
 */

/**
 * Consistent error handling hook.
 * handleError: generic
 * handleApiError: opinionated defaults for API calls
 * extractError: raw extraction only
 */
export const useErrorHandler = () => {
  const { addMessage } = useMessage?.() || { addMessage: null };
  const { logout } = useAuth?.() || { logout: () => {} };

  // Listen for global 401 events from axios interceptor
  useEffect(() => {
    const handle401Event = (event) => {
      const { error, url, method } = event.detail;

      if (addMessage) {
        addMessage("Session expired. Logging out...", "error");
      }

      // Clear all auth data and logout
      setTimeout(() => {
        try {
          logout && logout();
        } catch (_) {
          // If logout fails, force redirect
          window.location.href = "/login";
        }
      }, 100);
    };

    window.addEventListener("globalAuth401", handle401Event);

    return () => {
      window.removeEventListener("globalAuth401", handle401Event);
    };
  }, [addMessage, logout]);

  // Extract a backend provided success or info message from a response-like object
  const extractSuccessMessage = useCallback((response) => {
    if (!response) return null;
    // Prioritize explicit 'detail' from backend (nested or top-level) before generic messages
    const candidates = [
      // Common backend success keys (include singular + plural + generic variants)
      response.detail,
      response?.data?.detail,
      response.details,
      response?.data?.details,
      response.status_message,
      response?.data?.status_message,
      response.message,
      response?.data?.message,
      response?.data?.statusMessage,
      response.statusMessage,
    ];
    const msg = candidates.find((m) => typeof m === "string" && m.trim().length > 0);
    return msg || null;
  }, []);

  const handleError = useCallback(
    (error, options = {}) => {
      const { showToast = true, userFriendly = true, customMessage = null, logError = true } = options;

      const extractedError = userFriendly ? extractErrorWithFriendlyMessage(error) : extractErrorMessage(error);

      // Suppression logic (generic errors that might carry status)
      const status = error?.response?.status || error?.statusCode || error?.status;
      const suppress404Env = process.env.REACT_APP_SUPPRESS_404_TOASTS === "true";
      const isSuppressed = (status && suppressedStatusCodes.has(status)) || (suppress404Env && status === 404);

      if (logError && process.env.NODE_ENV === "development") {
        // eslint-disable-next-line no-console
        console.error("Error occured - check error handler");
      }

      if (showToast && addMessage && !isSuppressed) {
        const messageToShow = customMessage || (userFriendly ? extractedError.userMessage || extractedError.message : extractedError.message);
        addMessage(messageToShow, "error");
      }

      // NOTE: Do NOT auto-logout on first 401 here anymore.
      // The axios interceptor attempts a token refresh; only after refresh failure
      // does it dispatch the globalAuth401 event which this app listens for to logout.
      // This preserves user state while a silent refresh is in progress.

      return extractedError;
    },
    [addMessage, logout]
  );

  const handleApiError = useCallback(
    (rawError, options = {}) => {
      const { customMessage, context, severity = "error", silent = false } = options || {};

      const statusCode = rawError?.response?.status || rawError?.statusCode || rawError?.status;
      // ...existing extraction code...
      const backendMessage =
        rawError?.response?.data?.detail ||
        rawError?.response?.data?.details ||
        rawError?.response?.data?.message ||
        rawError?.response?.data?.error ||
        rawError?.response?.data?.error_message ||
        rawError?.message;
      const friendlyHttpMessage = statusCode ? `HTTP Error ${statusCode}` : null;
      const rawMsg = String(rawError?.message || "");
      const url = rawError?.config?.url || "";

      // Detect no-response (request made, no response object)
      const noResponse = !statusCode && !rawError?.response && !!rawError?.request;

      // Detect explicit connection refused or network unreachable indicators
      let connRefused = /(?:ERR_CONNECTION_REFUSED|connection refused)/i.test(rawMsg) || /net::ERR_CONNECTION_REFUSED/i.test(rawMsg);
      // Axios sometimes only gives 'Network Error'; treat it as connection issue if online and no response

      if (!connRefused && /Network Error/i.test(rawMsg) && navigator.onLine && noResponse) connRefused = true;
      if (!connRefused && rawError?.code === "ERR_NETWORK" && navigator.onLine && !statusCode) connRefused = true;

      const authRoute = /\/(login|logout)/i.test(url);

      let overrideConnMessage = null;

      // Precedence: offline > connection refused > generic no-response
      if (!navigator.onLine && noResponse) {
        overrideConnMessage = authRoute ? "You are offline. Reconnect and retry signing in ." : "You appear offline. Please check your network connection.";
      } else if (connRefused) {
        overrideConnMessage = authRoute ? "Cannot reach server. Please retry logging in after sometime." : "Cannot reach server right now. Please try again shortly.";
      } else if (noResponse) {
        overrideConnMessage = authRoute ? "No response from server. Please retry after sometime." : "No response received from server. Please try again after sometime.";
      }

      // Decide final user message (do not override explicit backend detail)
      let userMessage = customMessage || overrideConnMessage || backendMessage || friendlyHttpMessage || rawMsg || "Unexpected error";

      // 401: Do NOT logout here; allow refresh flow to decide. Still show a gentle message unless suppressed.
      if (statusCode === 401) {
        userMessage = customMessage || backendMessage || userMessage || "Authentication required";
      }

      const suppress404Env = process.env.REACT_APP_SUPPRESS_404_TOASTS === "true";
      const isSuppressed = (statusCode && suppressedStatusCodes.has(statusCode)) || (suppress404Env && statusCode === 404);

      const finalErrorObject = {
        statusCode,
        message: userMessage,
        originalMessage: rawMsg,
        context,
        severity,
        isConnectionRefused: !!connRefused,
        noResponse,
        suppressed: isSuppressed,
      };

      if (!silent && !isSuppressed) {
        addMessage && addMessage(userMessage, "error");
      }

      // Removed automatic logout on 401 (handled via globalAuth401 after failed refresh)

      return finalErrorObject;
    },
    [addMessage, logout]
  );

  const extractError = useCallback((error) => extractErrorMessage(error), []);

  /**
   * Unified success handler so all create/update/delete flows show backend message first.
   * Falls back to provided fallbackMessage (or generic) only when backend did not send one.
   */
  const handleApiSuccess = useCallback(
    (response, { fallbackMessage = "Operation successful", showToast = true, toastType = "success" } = {}) => {
      const message = extractSuccessMessage(response) || fallbackMessage;
      if (showToast && addMessage) {
        addMessage(message, toastType);
      }
      return message;
    },
    [addMessage, extractSuccessMessage]
  );

  return { handleError, handleApiError, extractError, handleApiSuccess, extractSuccessMessage };
};

export default useErrorHandler;
