import axios from "axios";
import { extractErrorMessage } from "../utils/errorUtils";

// Module-level counter for request IDs
let requestIdCounter = 0;

// Exported registration function so we can attach timing + standardization logic to any axios instance (global or custom)
export function registerAxiosInterceptors(instance = axios) {
  const FLAG = "__IAF_INTERCEPTORS_REGISTERED__";
  if (instance[FLAG]) return; // idempotent
  instance[FLAG] = true;
  // Debounce for global 401 event spam (multiple concurrent 401s)
  let lastGlobal401Ts = 0;
  const GLOBAL401_DEBOUNCE_MS = 1000;

  const canPerf = typeof performance !== "undefined" && typeof performance.now === "function" && typeof performance.getEntriesByType === "function";
  const mkId = () => `req-${++requestIdCounter}`;
  const VERBOSE = process.env.REACT_APP_API_TIMING_VERBOSE === "true";
  const DRIFT_WARN_THRESHOLD_MS = 80;

  const findResourceTiming = (url, startNow, prevResCount, reqId) => {
    try {
      const absUrl = (() => {
        try {
          return new URL(url, window.location.origin).href;
        } catch {
          return url;
        }
      })();
      const all = performance.getEntriesByType("resource");
      const fresh = all.slice(prevResCount);
      let candidates = fresh.filter(
        (e) => (e.initiatorType === "xmlhttprequest" || e.initiatorType === "fetch") && (e.name === absUrl || e.name.endsWith(url) || absUrl.endsWith(e.name))
      );
      if (!candidates.length) {
        candidates = all.filter((e) => e.name === absUrl && (e.initiatorType === "xmlhttprequest" || e.initiatorType === "fetch"));
      }
      if (!candidates.length) {
        if (VERBOSE) console.warn(`[${reqId}] No PerformanceResourceTiming match for ${url}`);
        return null;
      }
      let best = null;
      for (const e of candidates) {
        const score = Math.abs(e.startTime - startNow);
        if (!best || score < best.score) best = { entry: e, score };
      }
      if (VERBOSE) {
        // eslint-disable-next-line no-console
      }
      return best?.entry || null;
    } catch (e) {
      if (VERBOSE) console.warn("findResourceTiming error", e);
      return null;
    }
  };

  const buildPhaseBreakdown = (r) => {
    if (!r) return null;
    const dns = r.domainLookupEnd - r.domainLookupStart;
    const tcp = r.connectEnd - r.connectStart;
    const ssl = r.secureConnectionStart > 0 ? r.connectEnd - r.secureConnectionStart : 0;
    const ttfb = r.responseStart - r.requestStart;
    const download = r.responseEnd - r.responseStart;
    return { dns, tcp, ssl, ttfb, download };
  };

  // Request interceptor (metadata + id header). Avoid logging sensitive headers.
  instance.interceptors.request.use((config) => {
    const reqId = mkId();
    const metadata = { reqId };
    if (process.env.NODE_ENV === "development" && canPerf) {
      metadata.startNow = performance.now();
      metadata.prevResCount = performance.getEntriesByType("resource").length;
    }
    config.metadata = metadata;
    config.headers = config.headers || {};
    if (!config.headers["x-request-id"]) config.headers["x-request-id"] = reqId;
    // Propagate instance support for silent token refresh so error interceptor can decide whether to auto logout
    if (instance.__supportsTokenRefresh) config.__supportsTokenRefresh = true;
    return config;
  });

  instance.interceptors.response.use(
    (response) => {
      const { reqId, startNow, prevResCount } = response.config?.metadata || {};
      const method = (response.config?.method || "").toUpperCase();
      const url = response.config?.url;
      const status = response.status;
      let netDur = null;
      let appDur = null;
      let phases = null;
      if (process.env.NODE_ENV === "development" && canPerf && typeof startNow === "number") {
        const endNow = performance.now();
        appDur = endNow - startNow;
        const resEntry = findResourceTiming(url, startNow, prevResCount, reqId);
        if (resEntry) {
          netDur = resEntry.duration;
          phases = buildPhaseBreakdown(resEntry);
        }
      }
      if (process.env.NODE_ENV === "development") {
        const parts = [];
        if (netDur != null) parts.push(`net=${Math.round(netDur)}ms`);
        if (appDur != null) parts.push(`app=${Math.round(appDur)}ms`);
        const baseMsg = `API Timing [${reqId}]: ${method} ${url} -> ${status} { ${parts.join(", ")} }`;
        if (VERBOSE && phases) {
          const phaseStr = Object.entries(phases)
            .map(([k, v]) => `${k}=${Math.max(0, Math.round(v))}ms`)
            .join(" ");
          // eslint-disable-next-line no-console
        } else {
          // eslint-disable-next-line no-console
        }
        if (!VERBOSE && netDur != null && appDur != null && appDur - netDur > DRIFT_WARN_THRESHOLD_MS) {
          // eslint-disable-next-line no-console
          console.warn(`API Timing Drift Warning [${reqId}] ${method} ${url}: drift=${Math.round(appDur - netDur)}ms (app-overhead)`);
        }
      }
      return response;
    },
    (error) => {
      const { reqId, startNow, prevResCount } = error.config?.metadata || {};
      const method = (error.config?.method || "").toUpperCase();
      const url = error.config?.url;
      const status = error.response?.status || "ERR";
      let netDur = null;
      let appDur = null;
      let phases = null;
      if (process.env.NODE_ENV === "development" && canPerf && typeof startNow === "number") {
        const endNow = performance.now();
        appDur = endNow - startNow;
        const resEntry = findResourceTiming(url, startNow, prevResCount, reqId);
        if (resEntry) {
          netDur = resEntry.duration;
          phases = buildPhaseBreakdown(resEntry);
        }
      }
      if (process.env.NODE_ENV === "development") {
        const parts = [];
        if (netDur != null) parts.push(`net=${Math.round(netDur)}ms`);
        if (appDur != null) parts.push(`app=${Math.round(appDur)}ms`);
        if (netDur != null && appDur != null) parts.push(`drift=${Math.round(appDur - netDur)}ms`);
        const baseMsg = `API Timing: ${method} ${url} -> ${status} { ${parts.join(", ")} }`;
        if (VERBOSE && phases) {
          const phaseStr = Object.entries(phases)
            .map(([k, v]) => `${k}=${Math.max(0, Math.round(v))}ms`)
            .join(" ");
          // eslint-disable-next-line no-console
        } else {
          // eslint-disable-next-line no-console
        }
        if (!VERBOSE && netDur != null && appDur != null && appDur - netDur > DRIFT_WARN_THRESHOLD_MS) {
          // eslint-disable-next-line no-console
          console.warn(`API Timing Drift Warning [${reqId}] ${method} ${url}: drift=${Math.round(appDur - netDur)}ms (app-overhead)`);
        }
      }
      try {
        const standardized = extractErrorMessage(error);
        error.standardizedMessage = standardized.message;
        error.statusCode = standardized.statusCode;
        // Avoid double global dispatch if a retry flag exists (e.g., refresh logic) to reduce event noise
        if (status === 401) {
          const supportsRefresh = !!error.config?.__supportsTokenRefresh;
          const isRefreshEndpoint = /refresh-token/i.test(url || "");
          const isRetry = !!error.config?._retry;
          // Fire global logout ONLY when:
          // 1) Request does NOT support refresh (legacy direct axios usage), OR
          // 2) It is the refresh endpoint itself failing, OR
          // 3) The original request already retried (_retry true) and still 401.
          if (!supportsRefresh || isRefreshEndpoint || isRetry) {
            const now = Date.now();
            if (now - lastGlobal401Ts > GLOBAL401_DEBOUNCE_MS) {
              lastGlobal401Ts = now;
              try {
                // eslint-disable-next-line no-console
                window.dispatchEvent(
                  new CustomEvent("globalAuth401", {
                    detail: { error: standardized, url, method, timestamp: now, postRefresh: isRetry || isRefreshEndpoint },
                  })
                );
              } catch (_) {}
            }
          } else {
            if (process.env.NODE_ENV === "development") {
              // eslint-disable-next-line no-console
              console.debug("🔄 401 received (silent refresh in progress) - suppressing immediate logout", { url, method });
            }
          }
        }
        if (process.env.NODE_ENV === "development") {
          // eslint-disable-next-line no-console
          console.error("API Error:", { url, method, status, message: standardized.message });
        }
      } catch (e) {
        // eslint-disable-next-line no-console
        console.warn("Failed to standardize error", e);
      }
      return Promise.reject(error);
    }
  );
}

// Auto-register on the global default axios instance (side effect for existing import usage)
registerAxiosInterceptors();
