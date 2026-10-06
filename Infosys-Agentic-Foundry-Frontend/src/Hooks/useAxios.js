import { useState, useCallback, useEffect } from "react";
import { APIs, BASE_URL, env } from "../constant";
import axios from "axios";
import authStorage from "../utils/authStorage";
import { registerAxiosInterceptors } from "../config/axiosInterceptors"; // ensure timing/error interceptors on custom instance
import { useErrorHandler } from "./useErrorHandler";
import { getEmailFromToken } from "../utils/jwtUtils";
import { msalInstance, loginRequest } from "../auth/msalConfig";
import {
  dispatchGlobalAuth401,
  isDeletedAccountError,
} from "../auth/authSessionUtils";
// [MANUAL_TOKEN_MODE] — remove this import when removing the feature
import { MANUAL_TOKEN_MODE, requestTokenFromUser } from "../utils/manualTokenBridge";

let sessionId = null;

const postMethod = "POST";
const getMethod = "GET";
// Backend was consolidated to accept only POST/GET (Akamai gateway restriction).
// PUT / PATCH / DELETE are aliased to POST — putData/patchData/deleteData helpers
// keep their original names for backwards compatibility with existing call sites,
// but they all issue POST requests under the hood. For endpoints whose URL was
// ALSO changed (see "List 2" in the migration doc), update the URL at the call
// site (e.g. `${SCHEDULER_BASE}/update/${jobId}` instead of `${SCHEDULER_BASE}/${jobId}`).
const deleteMethod = "POST";
const putMethod = "POST";
const patchMethod = "POST";

/**
 * Read error message from a failed fetch Response body.
 * @param {Response} response
 * @param {string} fallback
 * @returns {Promise<string>}
 */
const readFetchErrorMessage = async (response, fallback) => {
  const fallbackMessage = fallback || `Request failed (${response.status})`;
  try {
    const text = await response.text();
    if (!text?.trim()) return fallbackMessage;
    try {
      const data = JSON.parse(text);
      if (typeof data === "string") return data;
      return data.error || data.detail || data.message || fallbackMessage;
    } catch {
      return text.trim();
    }
  } catch {
    return fallbackMessage;
  }
};

/**
 * Throw an Error enriched with response metadata for extractErrorMessage().
 * @param {Response} response
 * @param {string} fallback
 */
const throwFetchStreamError = async (response, fallback) => {
  const message = await readFetchErrorMessage(response, fallback);
  const err = new Error(message);
  err.response = { status: response.status, data: { error: message } };
  throw err;
};

// JWT token storage
let jwtToken = null;
// Refresh token cache (non-HTTP-only fallback). If backend sets httpOnly cookie you can ignore.
let refreshToken = null;
let isRefreshing = false;
let refreshPromise = null; // shared promise for in-flight refresh
// Flag to detect if session artifacts disappeared during an in‑flight refresh so we don't resurrect a logged out user
let sessionInvalidatedDuringRefresh = false;

// Global API call tracking to prevent loops
let isApiBlocked = false;
const apiCallHistory = new Map();
const blockedEndpointsLogged = new Set(); // Track which endpoints we've already logged
const MAX_CALLS_PER_ENDPOINT = 5;
const TIME_WINDOW = 10000; // 10 seconds

// Function to set the JWT token (to be called after login/signup)
export const setJwtToken = (token) => {
  if (token && token !== "undefined" && token !== "null") {
    jwtToken = token;
    authStorage.setJwt(token);
    return true;
  }
  return false;
};

// Refresh token helpers
export const setRefreshToken = (token) => {
  if (token) {
    refreshToken = token;
    authStorage.setRefresh(token);
  } else {
    refreshToken = null;
    authStorage.removeRefresh();
  }
};
export const getRefreshToken = () => {
  if (!refreshToken) {
    refreshToken = authStorage.getRefresh();
  }
  return refreshToken;
};
export const clearRefreshToken = () => {
  refreshToken = null;
  authStorage.removeRefresh();
};

// Function to get the current JWT token
export const getJwtToken = () => {
  // Guard against string coercion bugs ("undefined" / "null" as literal strings)
  if (!jwtToken || jwtToken === "undefined" || jwtToken === "null") {
    jwtToken = authStorage.getJwt();
  }
  return jwtToken && jwtToken !== "undefined" && jwtToken !== "null" ? jwtToken : null;
};

/**
 * Resolve the best available Bearer token: MSAL silent acquire (when accounts exist),
 * then stored JWT. Used by axios interceptors and fetch-based streaming calls.
 */
export const resolveBearerToken = async () => {
  const accounts = msalInstance.getAllAccounts();
  if (accounts.length > 0) {
    try {
      const result = await msalInstance.acquireTokenSilent({
        ...loginRequest,
        account: accounts[0],
      });
      if (result?.accessToken) {
        jwtToken = result.accessToken;
        authStorage.setJwt(result.accessToken);
        return result.accessToken;
      }
    } catch (msalErr) {
      if (process.env.NODE_ENV === "development") {
        // eslint-disable-next-line no-console
        console.warn("[useAxios] MSAL silent token acquire failed:", msalErr?.message);
      }
    }
  }
  return getJwtToken();
};

// Function to check if API calls should be blocked
const shouldBlockApiCall = (endpoint) => {
  const now = Date.now();

  if (isApiBlocked) {
    // Only log once per endpoint while blocked
    if (!blockedEndpointsLogged.has(`global_${endpoint}`)) {
      blockedEndpointsLogged.add(`global_${endpoint}`);
      console.warn(`🚫 API call to ${endpoint} blocked due to error loop protection`);
    }
    return true;
  }

  // Check call frequency for this endpoint
  const endpointHistory = apiCallHistory.get(endpoint) || [];
  const recentCalls = endpointHistory.filter((timestamp) => now - timestamp < TIME_WINDOW);

  if (recentCalls.length >= MAX_CALLS_PER_ENDPOINT) {
    // Only log once per endpoint when rate limited
    if (!blockedEndpointsLogged.has(`rate_${endpoint}`)) {
      blockedEndpointsLogged.add(`rate_${endpoint}`);
      console.warn(`🚫 API call to ${endpoint} blocked - too many calls (${recentCalls.length}) in time window. Check for useEffect dependency issues.`);
    }
    return true;
  }

  // Update history
  recentCalls.push(now);
  apiCallHistory.set(endpoint, recentCalls);

  return false;
};

// Function to temporarily block API calls
const blockApiCalls = (duration = 5000) => {
  if (isApiBlocked) return;

  isApiBlocked = true;
  console.warn("🚫 All API calls temporarily blocked due to error loop detection");

  setTimeout(() => {
    isApiBlocked = false;
    apiCallHistory.clear();
    blockedEndpointsLogged.clear(); // Reset logged endpoints so future blocks will log again
    console.info("✅ API calls unblocked");
  }, duration);
};

// Helper to add Authorization header — used by fetch-based streaming calls.
const addConfigHeaders = async (headers = {}) => {
  const token = await resolveBearerToken();
  if (token) {
    return {
      ...headers,
      Authorization: `Bearer ${token}`,
    };
  }
  return headers;
};

// Function to get the current session ID
export const getSessionId = () => {
  if (!sessionId) {
    sessionId = authStorage.getSession();
  }
  return sessionId;
};

const REQUEST_TIMEOUT_MS = Number(env.REACT_APP_API_TIMEOUT || process.env.REACT_APP_API_TIMEOUT) || (20 * 60 * 1000); // If not declared in ENV , it will be 20 minutes

const defaultConfig = {
  headers: {
    accept: "application/json",
  },
  timeout: REQUEST_TIMEOUT_MS,
};

// Create a centralized axios instance so interceptors fire uniformly
// Exported so non-hook utilities (e.g. downloadUtils) can reuse it.
export const axiosInstance = axios.create({
  baseURL: BASE_URL,
  ...defaultConfig,
});
// Flag used by shared interceptors to know refresh logic is present
axiosInstance.__supportsTokenRefresh = true;

// Attach shared timing + standardization interceptors (idempotent)
try {
  registerAxiosInterceptors(axiosInstance);
} catch (e) {
  if (process.env.NODE_ENV === "development") {
    // eslint-disable-next-line no-console
    console.warn("[useAxios] Failed to attach shared interceptors", e);
  }
}

// Request interceptor to attach auth header (MSAL or JWT).
axiosInstance.interceptors.request.use(
  async (config) => {
    if (config.headers?.Authorization) {
      return config;
    }
    const token = await resolveBearerToken();
    if (token) {
      config.headers = config.headers || {};
      config.headers.Authorization = `Bearer ${token}`;
    }
    return config;
  },
  (error) => Promise.reject(error)
);

// Dedicated axios instance for the refresh call — no interceptors attached
// so it cannot trigger globalAuth401 or create infinite retry loops.
const refreshAxios = axios.create({ timeout: REQUEST_TIMEOUT_MS });

// Perform refresh (deduplicated)
const performTokenRefresh = async () => {
  if (isRefreshing && refreshPromise) return refreshPromise;
  isRefreshing = true;
  refreshPromise = (async () => {
    // [MANUAL_TOKEN_MODE] — remove this block to restore normal refresh-token behavior
    // Only prompt for a pasted token when the user actually logged in via manual token.
    // The env flag alone enables the login-page button; it must not hijack SSO/local refresh.
    if (MANUAL_TOKEN_MODE && localStorage.getItem("auth_type") === "manual_token") {
      const token = await requestTokenFromUser();
      setJwtToken(token);
      return token;
    }
    const rToken = getRefreshToken();
    const email = getEmailFromToken();
    const user_session = authStorage.getSession();
    if (!email || !user_session) {
      throw new Error("Refresh prerequisites missing (email/session)");
    }
    const isSessionStillActive = () => Boolean(authStorage.getSession()) && Boolean(getEmailFromToken());
    try {
      if (process.env.NODE_ENV === "development") {
        // eslint-disable-next-line no-console
        console.debug("🔄 Attempting token refresh", { hasRefreshToken: Boolean(rToken), email });
      }
      const payload = { email, user_session };
      if (rToken) payload.refresh_token = rToken; // include only if present
      // Include the (possibly expired) JWT so the backend can extract user info
      // even though it's expired — many backends require this for refresh validation.
      const currentJwt = await resolveBearerToken();
      const refreshHeaders = {};
      if (currentJwt) {
        refreshHeaders.Authorization = `Bearer ${currentJwt}`;
      }
      // Use refreshAxios (no interceptors) to avoid globalAuth401 on failure
      const response = await refreshAxios.post(`${BASE_URL}${APIs.REFRESH_TOKEN}`, payload, { headers: refreshHeaders });
      // If user logged out while we were refreshing, abort and mark invalidation
      if (!isSessionStillActive()) {
        sessionInvalidatedDuringRefresh = true;
        throw new Error("Session terminated during token refresh");
      }
      const newAccess = response?.data?.token || response?.data?.jwt_token || response?.data?.access_token;
      const newRefresh = response?.data?.refresh_token || response?.data?.refreshToken;
      if (!newAccess) throw new Error("No access token in refresh response");
      setJwtToken(newAccess);
      if (newRefresh) setRefreshToken(newRefresh);
      return newAccess;
    } catch (e) {
      clearRefreshToken();
      authStorage.removeJwt();
      throw e;
    } finally {
      isRefreshing = false;
      refreshPromise = null; // reset so next call creates a fresh promise
    }
  })();
  return refreshPromise;
};

// URL encoding helper - defined at module level for use in streaming functions
const serializeToUrlEncoded = (data) => {
  return Object.entries(data)
    .map(([key, value]) => `${encodeURIComponent(key)}=${encodeURIComponent(value)}`)
    .join("&");
};

// Queue to hold requests while refreshing
const subscriberQueue = [];
const addSubscriber = (callback) => subscriberQueue.push(callback);
const notifySubscribers = (newToken) => {
  while (subscriberQueue.length) {
    const cb = subscriberQueue.shift();
    try {
      cb(newToken);
    } catch (_) {}
  }
};

// Helper to check if an error/response indicates authentication failure
// This handles various 401 response formats from backend including {"detail":"Authentication required"}
const isAuthenticationError = (error) => {
  const status = error?.response?.status || error?.status;
  if (status === 401) return true;

  // Check for common authentication failure patterns in response body
  const errorData = error?.response?.data || error?.data;
  if (errorData) {
    const detail = typeof errorData === "string" ? errorData : errorData?.detail || errorData?.message || errorData?.error;
    if (typeof detail === "string") {
      const lowerDetail = detail.toLowerCase();
      if (
        lowerDetail.includes("authentication required") ||
        lowerDetail.includes("token expired") ||
        lowerDetail.includes("invalid token") ||
        lowerDetail.includes("jwt expired") ||
        lowerDetail.includes("unauthorized") ||
        lowerDetail.includes("not authenticated")
      ) {
        return true;
      }
    }
  }

  return false;
};

// Wrapper to handle 401 in fetch-based streaming calls
// Returns the new token if refresh was needed and succeeded, null otherwise
const handleFetch401 = async (response, url) => {
  if (response.status !== 401) return null;

  // MSAL / JWT: refresh via resolveBearerToken (includes MSAL silent acquire).
  if (localStorage.getItem("auth_type") === "msal") {
    try {
      const newToken = await resolveBearerToken();
      if (newToken) {
        return newToken;
      }
    } catch (_) {}
    dispatchGlobalAuth401({
      error: { status: 401 },
      url,
      method: "STREAM",
      source: "fetch",
      reason: "session-expired",
    });
    return null;
  }

  // Check if we have session credentials to attempt refresh
  const email = getEmailFromToken();
  const user_session = authStorage.getSession();

  if (!email || !user_session) {
    dispatchGlobalAuth401({
      error: { status: 401 },
      url,
      method: "STREAM",
      source: "fetch",
      reason: "session-expired",
    });
    return null;
  }

  try {
    // Attempt token refresh
    if (isRefreshing && refreshPromise) {
      // Wait for ongoing refresh
      return await refreshPromise;
    }
    const newToken = await performTokenRefresh();
    if (process.env.NODE_ENV === "development") {
      // eslint-disable-next-line no-console
      console.debug("✅ Token refresh succeeded for streaming request", url);
    }
    return newToken;
  } catch (refreshErr) {
    if (process.env.NODE_ENV === "development") {
      // eslint-disable-next-line no-console
      console.debug("❌ Token refresh failed for streaming request", refreshErr);
    }
    dispatchGlobalAuth401({
      error: refreshErr,
      url,
      method: "STREAM",
      source: "fetch",
      reason: "session-expired",
    });
    return null;
  }
};

axiosInstance.interceptors.response.use(
  (resp) => resp,
  async (error) => {
    const status = error?.response?.status;
    const originalConfig = error?.config || {};

    // Deleted/deactivated account — logout immediately (no token refresh).
    if (isDeletedAccountError(error)) {
      dispatchGlobalAuth401({ reason: "account-deactivated" });
      return Promise.reject(error);
    }

    // Use enhanced authentication check that also looks at response body
    const isAuthError = status === 401 || isAuthenticationError(error);

    if (isAuthError && !originalConfig._retry) {
      originalConfig._retry = true;

      // MSAL: refresh via resolveBearerToken; never call the backend refresh endpoint.
      if (localStorage.getItem("auth_type") === "msal") {
        try {
          const newToken = await resolveBearerToken();
          if (newToken) {
            originalConfig.headers = originalConfig.headers || {};
            originalConfig.headers.Authorization = `Bearer ${newToken}`;
            return axiosInstance(originalConfig);
          }
        } catch (_) {}
        dispatchGlobalAuth401({
          error,
          url: originalConfig?.url,
          method: originalConfig?.method,
          reason: "session-expired",
        });
        return Promise.reject(error);
      }

      // Non-MSAL: attempt backend token refresh.
      if (getEmailFromToken() && authStorage.getSession()) {
        // Case 1: another refresh is already in-flight — queue up and wait for it.
        // NOTE: We DO NOT wrap the replay in the same try/catch as the refresh call.
        // Replay errors (e.g. legitimate 404s from the actual API) must NOT trigger logout.
        if (isRefreshing) {
          return new Promise((resolve, reject) => {
            addSubscriber(async (newToken) => {
              if (!newToken) {
                // Refresh failed elsewhere; reject silently — the refresh path already dispatched globalAuth401
                reject(error);
                return;
              }
              originalConfig.headers = originalConfig.headers || {};
              originalConfig.headers.Authorization = `Bearer ${newToken}`;
              try {
                const replayResp = await axiosInstance(originalConfig);
                resolve(replayResp);
              } catch (e) {
                // Replay error (404, 500, business error, etc.) — reject as-is, no logout
                reject(e);
              }
            });
          });
        }

        // Case 2: kick off a new refresh. ONLY the refresh call itself is guarded — replay is separate.
        let newToken;
        try {
          newToken = await performTokenRefresh();
        } catch (refreshErr) {
          notifySubscribers(null);
          if (process.env.NODE_ENV === "development") {
            // eslint-disable-next-line no-console
            console.debug("❌ Token refresh failed", refreshErr);
          }
          // Genuine refresh failure -> emit global 401 to trigger logout
          dispatchGlobalAuth401({
            error: refreshErr,
            url: originalConfig?.url,
            method: originalConfig?.method,
            reason: "session-expired",
          });
          return Promise.reject(error);
        }

        // Guard: session invalidated (user logged out) or artifacts cleared during refresh window
        if (sessionInvalidatedDuringRefresh || !authStorage.getSession()) {
          sessionInvalidatedDuringRefresh = false; // reset for next cycle
          notifySubscribers(null); // fail fast queued subscribers
          dispatchGlobalAuth401({
            error,
            url: originalConfig?.url,
            method: originalConfig?.method,
            abortedReplay: true,
            reason: "session-expired",
          });
          return Promise.reject(error);
        }

        // Refresh succeeded — release queued subscribers and replay the original request.
        // Replay is OUTSIDE any try/catch here: if it fails with a non-auth error (404, 500, …)
        // that rejection bubbles up naturally to the caller and MUST NOT trigger logout.
        notifySubscribers(newToken);
        if (process.env.NODE_ENV === "development") {
          // eslint-disable-next-line no-console
          console.debug("✅ Token refresh succeeded, replaying original request", originalConfig.url);
        }
        originalConfig.headers = originalConfig.headers || {};
        originalConfig.headers.Authorization = `Bearer ${newToken}`;
        return axiosInstance(originalConfig);
      } else {
        dispatchGlobalAuth401({
          error,
          url: originalConfig?.url,
          method: originalConfig?.method,
          reason: "session-expired",
        });
      }
    } else if (status === 401 && originalConfig._retry) {
      // Refresh was attempted but the replayed request still returned 401.
      dispatchGlobalAuth401({
        error,
        url: originalConfig?.url,
        method: originalConfig?.method,
        postRefresh: true,
        reason: "session-expired",
      });
    }
    return Promise.reject(error);
  }
);

const useFetch = () => {
  const fetchDataStream = async (url, configOrCallback = {}, maybeCallback, _isRetry = false) => {
    const isFn = typeof configOrCallback === "function";
    const onChunk = isFn ? configOrCallback : typeof maybeCallback === "function" ? maybeCallback : configOrCallback.onChunk;
    const cfg = isFn ? {} : configOrCallback || {};
    const fullUrl = url.startsWith("http") ? url : `${BASE_URL}${url}`;
    const headers = await addConfigHeaders({
      ...defaultConfig.headers,
      Accept: cfg.accept || "text/event-stream, application/json",
      ...cfg.headers,
    });
    const response = await fetch(fullUrl, {
      method: getMethod,
      headers,
      signal: cfg.signal,
      cache: "no-store",
    });

    // Handle 401 with token refresh retry
    if (response.status === 401 && !_isRetry) {
      if (process.env.NODE_ENV === "development") {
        // eslint-disable-next-line no-console
        console.debug("🔄 401 received in fetchDataStream, attempting token refresh", url);
      }
      const newToken = await handleFetch401(response, url);
      if (newToken) {
        // Retry with new token
        return fetchDataStream(url, configOrCallback, maybeCallback, true);
      }
      throw new Error(`Streaming request failed (${response.status}) - Authentication failed`);
    }

    if (!response.ok) {
      await throwFetchStreamError(response, `Streaming request failed (${response.status})`);
    }
    if (!response.body) throw new Error("No response body for streaming");
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    const results = [];

    const processLine = (rawLine) => {
      let line = rawLine.trim();
      if (!line) return;
      // SSE prefix handling
      if (line.startsWith("event:")) return; // ignore named events for now
      if (line.startsWith("id:")) return; // ignore id lines
      if (line.startsWith("retry:")) return; // ignore retry hints
      if (line.startsWith("data:")) line = line.slice(5).trim();
      if (!line) return;
      try {
        const obj = JSON.parse(line);
        results.push(obj);
        if (onChunk) {
          try {
            onChunk(obj);
          } catch (_) {}
        }
      } catch (e) {
        if (cfg.emitRaw && onChunk) {
          try {
            onChunk({ __raw: line });
          } catch (_) {}
        }
      }
    };

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split(/\r?\n/);
      buffer = lines.pop(); // retain incomplete tail
      for (const l of lines) processLine(l);
    }
    if (buffer.trim()) processLine(buffer);
    return results;
  };

  // Enhanced streaming POST: supports callback overload like GET
  // Usage:
  //   postDataStream(url, body, { onChunk })
  //   postDataStream(url, body, {}, onChunkFn)
  //   postDataStream(url, body, onChunkFn)
  const postDataStream = async (url, postData, configOrCallback = {}, maybeCallback, _isRetry = false) => {
    const isFn = typeof configOrCallback === "function";
    const onChunk = isFn ? configOrCallback : typeof maybeCallback === "function" ? maybeCallback : configOrCallback.onChunk;
    const cfg = isFn ? {} : configOrCallback || {};
    // Normalize URL: remove trailing slash from BASE_URL and ensure url has leading slash
    const normalizedBase = BASE_URL.replace(/\/$/, "");
    const normalizedPath = url.startsWith("/") ? url : `/${url}`;
    const fullUrl = url.startsWith("http") ? url : `${normalizedBase}${normalizedPath}`;
    let contentType = "application/json";
    let dataToSend = postData;
    const skipBody = postData === null || postData === undefined;
    if (postData instanceof FormData) {
      contentType = undefined; // let browser set boundary
    } else if (cfg.headers?.["Content-Type"] === "application/x-www-form-urlencoded") {
      contentType = "application/x-www-form-urlencoded";
      dataToSend = postData instanceof URLSearchParams
        ? postData.toString()
        : serializeToUrlEncoded(postData);
    } else if (!skipBody) {
      dataToSend = JSON.stringify(postData);
    }
    const headers = await addConfigHeaders({
      ...defaultConfig.headers,
      Accept: cfg.accept || "text/event-stream, application/json",
      ...cfg.headers,
      ...(contentType && !skipBody ? { "Content-Type": contentType } : {}),
    });
    const response = await fetch(fullUrl, {
      method: postMethod,
      headers,
      ...(skipBody ? {} : { body: dataToSend }),
      signal: cfg.signal,
      cache: "no-store",
    });

    // Handle 401 with token refresh retry
    if (response.status === 401 && !_isRetry) {
      if (process.env.NODE_ENV === "development") {
        // eslint-disable-next-line no-console
        console.debug("🔄 401 received in postDataStream, attempting token refresh", url);
      }
      const newToken = await handleFetch401(response, url);
      if (newToken) {
        // Retry with new token
        return postDataStream(url, postData, configOrCallback, maybeCallback, true);
      }
      throw new Error(`Streaming POST failed (${response.status}) - Authentication failed`);
    }

    if (!response.ok) {
      await throwFetchStreamError(response, `Streaming POST failed (${response.status})`);
    }
    if (!response.body) throw new Error("No response body for streaming");
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    const results = [];

    const processLine = (rawLine) => {
      let line = rawLine.trim();
      if (!line) return;
      if (line.startsWith("event:")) return;
      if (line.startsWith("id:")) return;
      if (line.startsWith("retry:")) return;
      if (line.startsWith("data:")) line = line.slice(5).trim();
      if (!line) return;
      if (process.env.NODE_ENV === "development") {
        // eslint-disable-next-line no-console
        console.debug("[stream][POST] raw line", line);
      }
      try {
        const obj = JSON.parse(line);
        results.push(obj);
        if (process.env.NODE_ENV === "development") {
          // eslint-disable-next-line no-console
          console.debug("[stream][POST] parsed object", obj);
        }
        if (onChunk) {
          try {
            onChunk(obj);
          } catch (_) {}
        }
      } catch (e) {
        if (cfg.emitRaw && onChunk) {
          try {
            onChunk({ __raw: line });
          } catch (_) {}
        }
      }
    };

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split(/\r?\n/);
      buffer = lines.pop();
      for (const l of lines) processLine(l);
    }
    if (buffer.trim()) processLine(buffer);
    return results;
  };
  const [loading, setLoading] = useState({});
  const [error, setError] = useState({});
  const { handleApiError } = useErrorHandler();

  // Listen for error loop events from ErrorBoundary
  useEffect(() => {
    const handleErrorLoop = () => {
      blockApiCalls(10000); // Block for 10 seconds
    };

    const handleErrorLoopCleared = () => {
      // Could add logic here if needed when loop is cleared
    };

    window.addEventListener("errorLoopDetected", handleErrorLoop);
    window.addEventListener("errorLoopCleared", handleErrorLoopCleared);

    return () => {
      window.removeEventListener("errorLoopDetected", handleErrorLoop);
      window.removeEventListener("errorLoopCleared", handleErrorLoopCleared);
    };
  }, []);

  const fetchData = useCallback(
    async (url, config = {}) => {
      // Check if this API call should be blocked
      if (shouldBlockApiCall(url)) {
        const error = new Error(`API call blocked: ${url}`);
        error.isBlocked = true;
        throw error;
      }

      setLoading((prevLoading) => ({ ...prevLoading, fetch: true }));
      try {
        // Add token to headers for GET requests
        const headers = await addConfigHeaders({
          ...defaultConfig.headers,
          ...config.headers,
        });

        const response = await axiosInstance.request({
          url,
          method: getMethod,
          ...config,
          headers,
        });
        const data = response.data;

        // Setting JWT token
        if (url.includes(APIs.GUEST_LOGIN) && data?.token) {
          setJwtToken(data.token);
        }

        setError((prevError) => ({ ...prevError, fetch: null }));
        return data;
      } catch (err) {
        // If this is a blocked call, don't treat it as a real error
        if (err.isBlocked) {
          console.warn("API call was blocked by error loop protection");
          return { error: "API temporarily unavailable", blocked: true };
        }

        // Use existing error handler for consistent 401 handling and messaging
        // Support silent option from config to suppress error popups (e.g., for health checks)
        handleApiError(err, { context: `fetchData: ${url}`, silent: config.silent || false });

        setError((prevError) => ({ ...prevError, fetch: err }));
        throw err;
      } finally {
        setLoading((prevLoading) => ({ ...prevLoading, fetch: false }));
      }
    },
    [handleApiError]
  );

  const postData = useCallback(
    async (url, postData, config = {}) => {
      // Check if this API call should be blocked
      if (shouldBlockApiCall(url)) {
        const error = new Error(`API call blocked: ${url}`);
        error.isBlocked = true;
        throw error;
      }

      setLoading((prevLoading) => ({ ...prevLoading, post: true }));
      try {
        let contentType = "application/json";
        let dataToSend = postData;
        if (postData instanceof FormData) {
          contentType = undefined;
        } else if (config.headers?.["Content-Type"] === "application/x-www-form-urlencoded") {
          contentType = "application/x-www-form-urlencoded";
          // Support both URLSearchParams (already serializable) and plain objects
          dataToSend = postData instanceof URLSearchParams
            ? postData.toString()
            : serializeToUrlEncoded(postData);
        } else {
          dataToSend = JSON.stringify(postData);
        }

        const headers = await addConfigHeaders({
          ...defaultConfig.headers,
          ...config.headers,
          ...(contentType ? { "Content-Type": contentType } : {}),
        });

        const response = await axiosInstance.request({
          url,
          method: postMethod,
          data: dataToSend,
          ...config,
          headers,
        });
        const data = response.data;

        // Check if this is a login or signup response and extract token if present
        if ((url.includes(APIs.LOGIN) || url.includes(APIs.REGISTER)) && data?.token) {
          setJwtToken(data.token);
        }

        setError((prevError) => ({ ...prevError, post: null }));
        return data;
      } catch (err) {
        // If this is a blocked call, don't treat it as a real error
        if (err.isBlocked) {
          console.warn("API call was blocked by error loop protection");
          return { error: "API temporarily unavailable", blocked: true };
        }

        // Use existing error handler for consistent 401 handling and messaging
        handleApiError(err, { context: `postData: ${url}`, silent: config.silent || false });

        setError((prevError) => ({ ...prevError, post: err }));
        throw err;
      } finally {
        setLoading((prevLoading) => ({ ...prevLoading, post: false }));
      }
    },
    [handleApiError]
  );

  const putData = useCallback(
    async (url, putData, config = {}) => {
      // Check if this API call should be blocked
      if (shouldBlockApiCall(url)) {
        const error = new Error(`API call blocked: ${url}`);
        error.isBlocked = true;
        throw error;
      }

      setLoading((prevLoading) => ({ ...prevLoading, put: true }));
      try {
        let contentType = "application/json";
        let dataToSend = putData;

        if (putData instanceof FormData) {
          contentType = undefined;
        } else if (config.headers?.["Content-Type"] === "application/x-www-form-urlencoded") {
          contentType = "application/x-www-form-urlencoded";
          dataToSend = putData instanceof URLSearchParams
            ? putData.toString()
            : serializeToUrlEncoded(putData);
        } else {
          dataToSend = JSON.stringify(putData);
        }
        const headers = await addConfigHeaders({
          ...defaultConfig.headers,
          ...config.headers,
          ...(contentType ? { "Content-Type": contentType } : {}),
        });

        const response = await axiosInstance.request({
          url,
          method: putMethod,
          data: dataToSend,
          ...config,
          headers,
        });
        const data = response.data;
        setError((prevError) => ({ ...prevError, put: null }));
        return data;
      } catch (err) {
        // If this is a blocked call, don't treat it as a real error
        if (err.isBlocked) {
          console.warn("API call was blocked by error loop protection");
          return { error: "API temporarily unavailable", blocked: true };
        }

        // Use existing error handler for consistent 401 handling and messaging
        handleApiError(err, { context: `putData: ${url}`, silent: config.silent || false });

        setError((prevError) => ({ ...prevError, put: err }));
        throw err;
      } finally {
        setLoading((prevLoading) => ({ ...prevLoading, put: false }));
      }
    },
    [handleApiError]
  );

  const patchData = useCallback(
    async (url, patchPayload, config = {}) => {
      // Check if this API call should be blocked
      if (shouldBlockApiCall(url)) {
        const error = new Error(`API call blocked: ${url}`);
        error.isBlocked = true;
        throw error;
      }

      setLoading((prevLoading) => ({ ...prevLoading, patch: true }));
      try {
        let contentType = "application/json";
        let dataToSend = patchPayload;

        if (patchPayload instanceof FormData) {
          contentType = undefined;
        } else if (config.headers?.["Content-Type"] === "application/x-www-form-urlencoded") {
          contentType = "application/x-www-form-urlencoded";
          dataToSend = serializeToUrlEncoded(patchPayload);
        } else {
          dataToSend = JSON.stringify(patchPayload);
        }
        const headers = await addConfigHeaders({
          ...defaultConfig.headers,
          ...config.headers,
          ...(contentType ? { "Content-Type": contentType } : {}),
        });

        const response = await axiosInstance.request({
          url,
          method: patchMethod,
          data: dataToSend,
          ...config,
          headers,
        });
        const data = response.data;
        setError((prevError) => ({ ...prevError, patch: null }));
        return data;
      } catch (err) {
        // If this is a blocked call, don't treat it as a real error
        if (err.isBlocked) {
          console.warn("API call was blocked by error loop protection");
          return { error: "API temporarily unavailable", blocked: true };
        }

        // Use existing error handler for consistent 401 handling and messaging
        handleApiError(err, { context: `patchData: ${url}`, silent: false });

        setError((prevError) => ({ ...prevError, patch: err }));
        throw err;
      } finally {
        setLoading((prevLoading) => ({ ...prevLoading, patch: false }));
      }
    },
    [handleApiError]
  );

  const deleteData = useCallback(
    async (url, deleteData, config = {}) => {
      // Check if this API call should be blocked
      if (shouldBlockApiCall(url)) {
        const error = new Error(`API call blocked: ${url}`);
        error.isBlocked = true;
        throw error;
      }

      setLoading((prevLoading) => ({ ...prevLoading, delete: true }));
      try {
        let contentType = "application/json";
        let dataToSend = deleteData;
        if (deleteData instanceof FormData) {
          contentType = undefined;
        } else {
          dataToSend = JSON.stringify(deleteData);
        }
        const headers = await addConfigHeaders({
          ...defaultConfig.headers,
          ...config.headers,
          ...(contentType ? { "Content-Type": contentType } : {}),
        });

        const response = await axiosInstance.request({
          url,
          method: deleteMethod,
          data: dataToSend,
          ...config,
          headers,
        });
        const data = response.data;
        setError((prevError) => ({ ...prevError, delete: null }));
        return data;
      } catch (err) {
        // If this is a blocked call, don't treat it as a real error
        if (err.isBlocked) {
          console.warn("API call was blocked by error loop protection");
          return { error: "API temporarily unavailable", blocked: true };
        }

        // Use existing error handler for consistent 401 handling and messaging
        handleApiError(err, { context: `deleteData: ${url}`, silent: false });

        setError((prevError) => ({ ...prevError, delete: err }));
        throw err;
      } finally {
        setLoading((prevLoading) => ({ ...prevLoading, delete: false }));
      }
    },
    [handleApiError]
  );

  // Clear token (for logout)
  const clearJwtToken = useCallback(() => {
    jwtToken = null;
    authStorage.removeJwt();
  }, []);

  return {
    loading: loading?.fetch || loading?.post || loading?.put || loading?.patch || loading?.delete,
    error,
    fetchData,
    postData,
    putData,
    patchData,
    deleteData,
    setJwtToken,
    clearJwtToken,
    getSessionId,
    getJwtToken,
    setRefreshToken,
    getRefreshToken,
    clearRefreshToken,
    fetchDataStream,
    postDataStream,
  };
};

export default useFetch;
