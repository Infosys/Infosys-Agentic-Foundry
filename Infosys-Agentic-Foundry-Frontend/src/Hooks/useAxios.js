import { useState, useCallback, useEffect } from "react";
import { APIs, BASE_URL, env } from "../constant";
import Cookies from "js-cookie";
import axios from "axios";
import { registerAxiosInterceptors } from "../config/axiosInterceptors"; // ensure timing/error interceptors on custom instance
import { useErrorHandler } from "./useErrorHandler";

let sessionId = null;

const postMethod = "POST";
const getMethod = "GET";
const deleteMethod = "DELETE";
const putMethod = "PUT";

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
  if (token) {
    jwtToken = token;
    Cookies.set("jwt-token", token);
    return true;
  }
  return false;
};

// Refresh token helpers
export const setRefreshToken = (token) => {
  if (token) {
    refreshToken = token;
    Cookies.set("refresh-token", token, { path: "/" });
  } else {
    refreshToken = null;
    Cookies.remove("refresh-token");
  }
};
export const getRefreshToken = () => {
  if (!refreshToken) {
    refreshToken = Cookies.get("refresh-token") || null;
  }
  return refreshToken;
};
export const clearRefreshToken = () => {
  refreshToken = null;
  Cookies.remove("refresh-token");
};

// Function to get the current JWT token
export const getJwtToken = () => {
  if (!jwtToken) {
    jwtToken = Cookies.get("jwt-token");
  }
  return jwtToken;
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

// Helper to add Authorization header if JWT token is available
const addConfigHeaders = (headers = {}) => {
  const token = getJwtToken();
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
    sessionId = Cookies.get("user_session");
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
const axiosInstance = axios.create({
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

// Request interceptor to attach auth header
axiosInstance.interceptors.request.use(
  (config) => {
    const token = getJwtToken();
    if (token) {
      config.headers = config.headers || {};
      config.headers.Authorization = `Bearer ${token}`;
    }
    return config;
  },
  (error) => Promise.reject(error)
);

// Perform refresh (deduplicated)
const performTokenRefresh = async () => {
  if (isRefreshing && refreshPromise) return refreshPromise;
  isRefreshing = true;
  refreshPromise = (async () => {
    const rToken = getRefreshToken();
    const email = Cookies.get("email");
    const user_session = Cookies.get("user_session");
    if (!email || !user_session) {
      throw new Error("Refresh prerequisites missing (email/session)");
    }
    const isSessionStillActive = () => !!Cookies.get("user_session") && !!Cookies.get("email");
    try {
      if (process.env.NODE_ENV === "development") {
        // eslint-disable-next-line no-console
        console.debug("🔄 Attempting token refresh", { hasRefreshToken: !!rToken });
      }
      const payload = { email, user_session };
      if (rToken) payload.refresh_token = rToken; // include only if present
      const response = await axios.post(`${BASE_URL}${APIs.REFRESH_TOKEN}`, payload);
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
      Cookies.remove("jwt-token");
      throw e;
    } finally {
      isRefreshing = false;
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

  // Check if we have session credentials to attempt refresh
  const email = Cookies.get("email");
  const user_session = Cookies.get("user_session");

  if (!email || !user_session) {
    // No session - emit logout event
    try {
      window.dispatchEvent(
        new CustomEvent("globalAuth401", {
          detail: { error: { status: 401 }, url, method: "STREAM", source: "fetch" },
        })
      );
    } catch (_) {}
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
    // Emit global 401 to trigger logout
    try {
      window.dispatchEvent(
        new CustomEvent("globalAuth401", {
          detail: { error: refreshErr, url, method: "STREAM", source: "fetch" },
        })
      );
    } catch (_) {}
    return null;
  }
};

axiosInstance.interceptors.response.use(
  (resp) => resp,
  async (error) => {
    const status = error?.response?.status;
    const originalConfig = error?.config || {};

    // Use enhanced authentication check that also looks at response body
    const isAuthError = status === 401 || isAuthenticationError(error);

    if (isAuthError && !originalConfig._retry) {
      // Attempt silent refresh first; do NOT logout yet.
      if (Cookies.get("email") && Cookies.get("user_session")) {
        originalConfig._retry = true;
        try {
          if (isRefreshing) {
            // Wait for ongoing refresh
            return await new Promise((resolve, reject) => {
              addSubscriber(async (newToken) => {
                if (!newToken) {
                  reject(error);
                  return;
                }
                originalConfig.headers = originalConfig.headers || {};
                originalConfig.headers.Authorization = `Bearer ${newToken}`;
                try {
                  const replayResp = await axiosInstance(originalConfig);
                  resolve(replayResp);
                } catch (e) {
                  reject(e);
                }
              });
            });
          }
          const newToken = await performTokenRefresh();
          // Guard: if session invalidated during refresh or artifacts missing, do not replay queued requests
          if (sessionInvalidatedDuringRefresh || !Cookies.get("user_session")) {
            sessionInvalidatedDuringRefresh = false; // reset for next cycle
            notifySubscribers(null); // fail fast queued subscribers
            try {
              const evt = new CustomEvent("globalAuth401", {
                detail: { error, url: originalConfig?.url, method: originalConfig?.method, abortedReplay: true },
              });
              window.dispatchEvent(evt);
            } catch (_) {}
            return Promise.reject(error);
          }
          notifySubscribers(newToken);
          if (process.env.NODE_ENV === "development") {
            // eslint-disable-next-line no-console
            console.debug("✅ Token refresh succeeded, replaying original request", originalConfig.url);
          }
          originalConfig.headers = originalConfig.headers || {};
          originalConfig.headers.Authorization = `Bearer ${newToken}`;
          return axiosInstance(originalConfig);
        } catch (refreshErr) {
          notifySubscribers(null);
          if (process.env.NODE_ENV === "development") {
            // eslint-disable-next-line no-console
            console.debug("❌ Token refresh failed", refreshErr);
          }
          // Refresh failed -> now emit global 401 to trigger logout elsewhere
          try {
            const evt = new CustomEvent("globalAuth401", {
              detail: { error: refreshErr, url: originalConfig?.url, method: originalConfig?.method },
            });
            window.dispatchEvent(evt);
          } catch (_) {}
        }
      } else {
        // No refresh possible (missing email/session) -> emit global 401
        try {
          const evt = new CustomEvent("globalAuth401", {
            detail: { error, url: originalConfig?.url, method: originalConfig?.method },
          });
          window.dispatchEvent(evt);
        } catch (_) {}
      }
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
    const headers = addConfigHeaders({
      ...defaultConfig.headers,
      Accept: cfg.accept || "text/event-stream, application/json",
      "Cache-Control": "no-cache",
      Pragma: "no-cache",
      ...cfg.headers,
    });
    const response = await fetch(fullUrl, { method: getMethod, headers, signal: cfg.signal });

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

    if (!response.ok) throw new Error(`Streaming request failed (${response.status})`);
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
    const fullUrl = url.startsWith("http") ? url : `${BASE_URL}${url}`;
    let contentType = "application/json";
    let dataToSend = postData;
    if (postData instanceof FormData) {
      contentType = undefined; // let browser set boundary
    } else if (cfg.headers?.["Content-Type"] === "application/x-www-form-urlencoded") {
      contentType = "application/x-www-form-urlencoded";
      dataToSend = serializeToUrlEncoded(postData);
    } else {
      dataToSend = JSON.stringify(postData);
    }
    const headers = addConfigHeaders({
      ...defaultConfig.headers,
      Accept: cfg.accept || "text/event-stream, application/json",
      "Cache-Control": "no-cache",
      Pragma: "no-cache",
      ...cfg.headers,
      ...(contentType ? { "Content-Type": contentType } : {}),
    });
    const response = await fetch(fullUrl, {
      method: postMethod,
      headers,
      body: dataToSend,
      signal: cfg.signal,
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

    if (!response.ok) throw new Error(`Streaming POST failed (${response.status})`);
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
        const headers = addConfigHeaders({
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
        handleApiError(err, { context: `fetchData: ${url}`, silent: false });

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
          dataToSend = serializeToUrlEncoded(postData);
        } else {
          dataToSend = JSON.stringify(postData);
        }

        const headers = addConfigHeaders({
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
        handleApiError(err, { context: `postData: ${url}`, silent: false });

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
          dataToSend = serializeToUrlEncoded(putData);
        } else {
          dataToSend = JSON.stringify(putData);
        }
        const headers = addConfigHeaders({
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
        handleApiError(err, { context: `putData: ${url}`, silent: false });

        setError((prevError) => ({ ...prevError, put: err }));
        throw err;
      } finally {
        setLoading((prevLoading) => ({ ...prevLoading, put: false }));
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
        const headers = addConfigHeaders({
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
    Cookies.remove("jwt-token");
  }, []);

  return {
    loading: loading?.fetch || loading?.post || loading?.put || loading?.delete,
    error,
    fetchData,
    postData,
    putData,
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
