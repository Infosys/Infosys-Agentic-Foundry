// Centralized error normalization and formatting utilities
// Goal: Produce a consistent shape so UI surfaces and logs errors uniformly
// Fun dev-friendly vibe preserved.
import React from "react";
/**
 * Canonical error object shape consumed by UI
 * {
 *   type: 'API' | 'NETWORK' | 'VALIDATION' | 'AUTH' | 'ROUTE' | 'TIMEOUT' | 'CANCEL' | 'UNKNOWN' | 'RUNTIME'
 *   code: string | null
 *   status: number | null            // HTTP status if applicable
 *   message: string                  // Safe user-facing message
 *   devMessage?: string              // Extra context for devs (not always shown to end users)
 *   details?: any                    // Raw extra details (only for logging)
 *   original?: any                   // Original error reference (kept for debugging)
 *   timestamp: number
 * }
 */

const FALLBACK_MESSAGE = "Something went sideways. Please try again.";

// Map common HTTP status codes to friendly messages (can be i18n-later)
const HTTP_MESSAGE_MAP = {
  400: "Bad request. Double‑check your input.",
  401: "You need to sign in again.",
  403: "You don't have permission for that.",
  404: "Not found.",
  408: "Request timed out.",
  413: "Payload too large.",
  429: "Too many requests. Slow down a tad.",
  500: "Server had a meltdown.",
  502: "Bad gateway upstream.",
  503: "Service temporarily unavailable.",
  504: "Server timeout.",
};

// Derive a coarse type based on axios-ish error signature or generic error
function classifyError(err) {
  if (!err) return "UNKNOWN";
  if (err.__CANCEL__) return "CANCEL"; // axios cancel token legacy
  if (err.code === "ERR_CANCELED") return "CANCEL";
  if (err.name === "AbortError") return "CANCEL";

  if (err.isAxiosError || err.config) {
    if (err.response) return "API";
    if (err.request && !err.response) return "NETWORK"; // likely network / CORS / DNS
  }

  if (err.name === "TypeError" || err.name === "ReferenceError" || err.name === "RangeError") return "RUNTIME";

  return "UNKNOWN";
}

function extractFromAxios(err) {
  if (!err || !err.response) return {};
  const { status, data } = err.response;
  let code = null;
  let message = null;
  let details = undefined;

  if (data) {
    if (typeof data === "string") {
      message = data;
    } else if (typeof data === "object") {
      code = data.code || data.errorCode || data.error_code || null;
      message = data.message || data.error || data.errorMessage || null;
      details = data.details || data.errors || data.data || undefined;
    }
  }

  return { status, code, message, details };
}

export function normalizeError(err, opts = {}) {
  try {
    if (err && err.__normalized) return err; // idempotent
    const type = classifyError(err);
    let status = null,
      code = null,
      message = null,
      details = undefined;

    if (type === "API" && err.response) {
      const extracted = extractFromAxios(err);
      status = extracted.status;
      code = extracted.code;
      message = extracted.message;
      details = extracted.details;
    }

    if (!message && status && HTTP_MESSAGE_MAP[status]) {
      message = HTTP_MESSAGE_MAP[status];
    }

    if (!message && err && typeof err.message === "string" && err.message.trim()) {
      message = err.message;
    }

    if (!message) message = FALLBACK_MESSAGE;

    const norm = {
      __normalized: true,
      type,
      code,
      status,
      message,
      devMessage: opts.includeStack && err && err.stack ? err.stack.split("\n")[0] : undefined,
      details,
      original: opts.keepOriginal ? err : undefined,
      timestamp: Date.now(),
    };
    return norm;
  } catch (boom) {
    return {
      __normalized: true,
      type: "UNKNOWN",
      code: null,
      status: null,
      message: FALLBACK_MESSAGE,
      devMessage: boom.message,
      timestamp: Date.now(),
    };
  }
}

// Produce a human friendly short line for toast banners
export function summarizeError(norm) {
  if (!norm) return FALLBACK_MESSAGE;
  if (!norm.__normalized) norm = normalizeError(norm);
  const prefix = norm.type && norm.type !== "UNKNOWN" ? `[${norm.type}] ` : "";
  return `${prefix}${norm.message}`;
}

// Decide if we show retry action
export function isRetryable(norm) {
  if (!norm) return false;
  if (!norm.__normalized) norm = normalizeError(norm);
  if (norm.type === "CANCEL") return false;
  if (norm.type === "NETWORK") return true;
  if (norm.status && [408, 429, 500, 502, 503, 504].includes(norm.status)) return true;
  return false;
}

// Attach a logger adapter (can be swapped later)
export function logError(normOrRaw, logger = console) {
  const norm = normOrRaw.__normalized ? normOrRaw : normalizeError(normOrRaw, { keepOriginal: true });
  try {
    logger.error(`[ERROR] ${norm.type} ${norm.status || ""} ${norm.code || ""} :: ${norm.message}`, {
      code: norm.code,
      status: norm.status,
      details: norm.details,
      original: norm.original,
    });
  } catch (_) {
    // swallow
  }
  return norm;
}

// Helper to wrap async calls
export async function withErrorBoundary(promiseFn, { onError, rethrow = false } = {}) {
  try {
    return await promiseFn();
  } catch (e) {
    const norm = normalizeError(e);
    if (onError) onError(norm);
    if (rethrow) throw norm;
    return undefined;
  }
}

export const ErrorUtils = {
  normalizeError,
  summarizeError,
  isRetryable,
  logError,
  withErrorBoundary,
};

export default ErrorUtils;

// ---------------------------------------------------------------------------
// Additional extraction helpers (legacy-friendly) requested for broad adoption
// ---------------------------------------------------------------------------

/**
 * Safely dig into an object using dot + bracket notation like: a.b[0].c
 */
const getNestedValue = (obj, path) => {
  return path.split(".").reduce((current, key) => {
    if (!current) return undefined;
    if (key.includes("[")) {
      const [arrayKey, indexStr] = key.split("[");
      const index = parseInt(indexStr.replace("]", ""), 10);
      return current?.[arrayKey]?.[index];
    }
    return current?.[key];
  }, obj);
};

/**
 * Extracts error messages from various error response formats
 * Returns a slim structure for simpler consumers migrating toward normalizeError
 */
export const extractErrorMessage = (error) => {
  if (process.env.NODE_ENV === "development") {
    // comment left for dev opt‑in; avoid auto pause
  }

  const responseError = { message: null, code: null, statusCode: null };
  if (!error) {
    responseError.message = "An unknown error occurred";
    return responseError;
  }

  const errorPaths = [
    "response.data.detail",
    "response.data.message",
    "response.data.error",
    "response.data.errors[0].message",
    "data.detail",
    "data.message",
    "data.error",
    "detail",
    "message",
    "error",
    "response.statusText",
    "code",
  ];

  for (const path of errorPaths) {
    const value = getNestedValue(error, path);
    if (value && typeof value === "string") {
      responseError.message = value;
      break;
    }
    // Special handling: validation detail array (e.g. FastAPI/Pydantic) -> synthesize human readable message
    if (path === "response.data.detail" && Array.isArray(value) && value.length > 0) {
      try {
        const issues = value;
        const missingFields = [];
        const otherIssues = [];
        issues.forEach((issue) => {
          if (!issue || !Array.isArray(issue.loc)) return;
          // Typically ['body','field_name'] or ['body','nested','field']
          const loc = issue.loc.filter(Boolean);
          let field = loc[loc.length - 1];
          // If last segment is 'body' but there is more, take second
          if ((field === "body" || field === "query" || field === "path") && loc.length > 1) {
            field = loc[1];
          }
          if (issue.type === "missing" || /required/i.test(issue.msg || "")) {
            if (field) missingFields.push(field);
          } else if (field) {
            otherIssues.push(`${field}: ${issue.msg || issue.type || "invalid"}`);
          }
        });
        const uniqueMissing = [...new Set(missingFields)];
        if (uniqueMissing.length) {
          responseError.message = `Missing required field${uniqueMissing.length > 1 ? "s" : ""}: ${uniqueMissing.join(", ")}`;
        } else if (otherIssues.length) {
          responseError.message = otherIssues.slice(0, 3).join("; "); // cap to avoid giant toast
        }
        if (responseError.message) break; // stop scanning paths once we formed a message
      } catch (_) {
        /* swallow parsing issues */
      }
    }
  }

  responseError.statusCode = error?.response?.status || error?.status || null;
  responseError.code = error?.code || error?.response?.data?.code || null;

  if (!responseError.message) {
    if (typeof error === "string") {
      responseError.message = error;
    } else if (error?.toString && typeof error.toString === "function") {
      responseError.message = error.toString();
    } else {
      responseError.message = "An unexpected error occurred";
    }
  }
  return responseError;
};

/**
 * Map HTTP status codes to friendlier copy (can be replaced by i18n later)
 */
export const getHttpErrorMessage = (statusCode) => {
  const errorMessages = {
    400: "Invalid request. Please check your input and try again.",
    401: "You are not authorized. Please log in and try again.",
    403: "Access denied. You don't have permission for this action.",
    404: "The requested resource was not found.",
    408: "Request timeout. Please try again.",
    409: "Conflict occurred. The resource may already exist.",
    422: "Validation failed. Please check your input data.",
    429: "Too many requests. Please wait a moment and try again.",
    500: "Internal server error. Please try again later.",
    502: "Service temporarily unavailable. Please try again later.",
    503: "Service unavailable. Please try again later.",
    504: "Request timeout. Please try again later.",
  };
  return errorMessages[statusCode] || "An error occurred. Please try again.";
};

/**
 * Enhanced extractor with optional user-friendly message layering
 */
export const extractErrorWithFriendlyMessage = (error, userFriendly = true) => {
  const extractedError = extractErrorMessage(error);
  if (!userFriendly) return extractedError;
  // If backend already supplied a specific detail/message we prefer that as primary
  const hasBackendSpecific = !!extractedError.message && !/^(Invalid request|An error occurred)/i.test(extractedError.message);
  const friendlyMessage = extractedError.statusCode ? getHttpErrorMessage(extractedError.statusCode) : null;
  // We expose both so UI can choose; keep existing shape for backwards compat
  return {
    ...extractedError,
    userMessage: hasBackendSpecific ? extractedError.message : friendlyMessage || extractedError.message,
    originalMessage: extractedError.message,
    friendlyHttpMessage: friendlyMessage,
  };
};

// Backwards compat bundle
ErrorUtils.extractErrorMessage = extractErrorMessage;
ErrorUtils.getHttpErrorMessage = getHttpErrorMessage;
ErrorUtils.extractErrorWithFriendlyMessage = extractErrorWithFriendlyMessage;

// ---------------------------------------------------------------------------
// Resilience helpers (non-breaking additions)
// ---------------------------------------------------------------------------

// Throttle repeated identical error log lines to avoid console spam
const _logCache = new Map();
export function throttleLogs(key, fn, intervalMs = 5000) {
  const now = Date.now();
  const last = _logCache.get(key) || 0;
  if (now - last > intervalMs) {
    _logCache.set(key, now);
    fn();
  }
}
ErrorUtils.throttleLogs = throttleLogs;

// Safely invoke a function; returns [result, error]
export function safeInvoke(fn, ...args) {
  try {
    return [fn?.(...args), null];
  } catch (e) {
    const norm = normalizeError(e);
    throttleLogs(`safeInvoke:${norm.message}`, () => console.error("safeInvoke error", norm));
    return [undefined, norm];
  }
}
ErrorUtils.safeInvoke = safeInvoke;

// Safe lazy loader for optional modules; supplies fallback component if import fails
export function safeLazy(importer, { Fallback = () => null, onError } = {}) {
  return React.lazy(() =>
    importer()
      .then((mod) => ({ default: mod.default || mod }))
      .catch((err) => {
        const norm = normalizeError(err);
        if (onError) {
          try {
            onError(norm);
          } catch (_) {
            /* swallow */
          }
        } else {
          throttleLogs(`safeLazy:${norm.message}`, () => console.error("safeLazy load failed", norm));
        }
        return { default: Fallback };
      })
  );
}
ErrorUtils.safeLazy = safeLazy;
