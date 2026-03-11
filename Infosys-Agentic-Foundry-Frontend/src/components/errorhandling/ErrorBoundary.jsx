import React from "react";
import { useMessage } from "../../Hooks/MessageContext";
import { lastApiError } from "../../config/axiosInterceptors";
import { generateUUID } from "../../utils/uuidPolyfill";

// Global error tracking to prevent API loops across all ErrorBoundary instances
let globalErrorCount = 0;
let lastGlobalError = 0;
let apiCallsBlocked = false;
const ERROR_THRESHOLD = 3;
const ERROR_WINDOW = 5000; // 5 seconds
const BLOCK_DURATION = 10000; // 10 seconds
const ERROR_COUNT_LIMIT = 2;

// Global function to block API calls
const blockApiCalls = () => {
  if (apiCallsBlocked) return;

  apiCallsBlocked = true;
  console.warn("🚫 API calls blocked due to error loop detection");

  // Dispatch global event to notify useFetch hooks
  window.dispatchEvent(
    new CustomEvent("errorLoopDetected", {
      detail: { blocked: true, timestamp: Date.now() },
    }),
  );

  // Unblock after duration
  setTimeout(() => {
    apiCallsBlocked = false;
    globalErrorCount = 0;
    window.dispatchEvent(
      new CustomEvent("errorLoopCleared", {
        detail: { blocked: false, timestamp: Date.now() },
      }),
    );
  }, BLOCK_DURATION);
};

// Check if we should block API calls globally
export const shouldBlockApiCalls = () => {
  const now = Date.now();

  // Clean old errors outside window
  if (now - lastGlobalError > ERROR_WINDOW) {
    globalErrorCount = 0;
  }

  return apiCallsBlocked;
};

// Functional wrapper to inject hook into class boundary
export const ErrorBoundaryWrapper = ({ children }) => {
  const { addMessage } = useMessage();
  return <ErrorBoundary addMessage={addMessage}>{children}</ErrorBoundary>;
};

class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = {
      hasError: false,
      errorCount: 0,
      lastErrorTime: null,
      errorId: null,
      errorMessage: null,
    };
  }

  static getDerivedStateFromError(error) {
    // IMPORTANT: This static method cannot access the component instance (no 'this').
    // Only mark hasError as true to trigger componentDidCatch, but don't show fallback UI
    // unless it's a critical rendering error. Most errors should just show as toast messages.
    const now = Date.now();
    const recentApiError = lastApiError && now - lastApiError.timestamp < 2000 ? lastApiError.message : null;

    // Check if this is a critical rendering error (e.g., cannot render children at all)
    const isCritical = error?.name === "ChunkLoadError" || error?.message?.includes("Loading chunk");

    return {
      hasError: isCritical, // Only show fallback UI for critical errors
      errorCount: 0,
      lastErrorTime: now,
      errorId: `error_${Date.now()}_${generateUUID()}`,
      errorMessage: recentApiError || error?.message || "An unexpected error occurred",
    };
  }

  componentDidCatch(error, errorInfo) {
    const now = Date.now();

    // Development logging
    if (process.env.NODE_ENV === "development") {
      // eslint-disable-next-line no-console
      console.error("ErrorBoundary caught: ", error, errorInfo);
    }

    // ----- Global tracking (shared across all boundaries) -----
    globalErrorCount++;
    lastGlobalError = now;
    if (globalErrorCount >= ERROR_THRESHOLD && now - lastGlobalError < ERROR_WINDOW) {
      blockApiCalls();
    }

    // ----- Instance (component-level) tracking -----
    const isRapidError = this.state.lastErrorTime && now - this.state.lastErrorTime < 1000;
    const nextCount = isRapidError ? (this.state.errorCount || 0) + 1 : 1;
    const recentApiError = lastApiError && now - lastApiError.timestamp < 2000 ? lastApiError.message : null;
    const errorMessage = recentApiError || error?.standardizedMessage || error?.message || "An unexpected error occurred";

    // Check if this is becoming a critical error loop
    const isCriticalLoop = nextCount > ERROR_COUNT_LIMIT;

    this.setState(
      {
        hasError: isCriticalLoop, // Only show fallback UI if error loop detected
        errorCount: nextCount,
        lastErrorTime: now,
        errorMessage: errorMessage,
      },
      () => {
        if (this.state.errorCount > 2) {
          console.warn("🔄 Rapid error loop detected in component, showing fallback UI");
        }
      },
    );

    // ----- User messaging (show toast for non-critical errors) -----
    try {
      const { addMessage } = this.props;
      if (!isCriticalLoop && !apiCallsBlocked && addMessage) {
        // Show a concise error message as toast
        addMessage(errorMessage, "error");
      }
    } catch (_) {
      /* swallow */
    }
  }

  render() {
    if (this.state.hasError) {
      // If in rapid error loop or API calls are blocked, show static fallback
      if (this.state.errorCount > ERROR_COUNT_LIMIT || apiCallsBlocked) {
        return (
          <div
            style={{
              padding: "20px",
              textAlign: "center",
              border: "1px solid #f5c6cb",
              borderRadius: "4px",
              backgroundColor: "#f8d7da",
              color: "#721c24",
              margin: "10px",
            }}>
            <h3>⚠️ Component Error</h3>
            <p>This section encountered an error and has been temporarily disabled.</p>
            <button
              onClick={() => window.location.reload()}
              style={{
                padding: "8px 16px",
                backgroundColor: "#007bff",
                color: "white",
                border: "none",
                borderRadius: "4px",
                cursor: "pointer",
              }}>
              Refresh Page
            </button>
          </div>
        );
      }

      // For first few errors, show retry option
      return (
        <div
          style={{
            padding: "20px",
            textAlign: "center",
            border: "1px solid #ffeaa7",
            borderRadius: "4px",
            backgroundColor: "#ffeaa7",
            color: "#2d3436",
            margin: "10px",
          }}>
          <h3>Something went wrong</h3>
          <p>Error ID: {this.state.errorId}</p>
          {this.state.errorMessage && (
            <p style={{ fontSize: "14px", color: "#636e72", marginBlock: "10px" }}>
              <strong>Details:</strong> {this.state.errorMessage}
            </p>
          )}
          <button
            onClick={() => this.setState({ hasError: false, errorCount: 0 })}
            style={{
              padding: "8px 16px",
              backgroundColor: "#00b894",
              color: "white",
              border: "none",
              borderRadius: "4px",
              cursor: "pointer",
              marginRight: "8px",
            }}>
            Try Again
          </button>
          <button
            onClick={() => window.location.reload()}
            style={{
              padding: "8px 16px",
              backgroundColor: "#636e72",
              color: "white",
              border: "none",
              borderRadius: "4px",
              cursor: "pointer",
            }}>
            Refresh Page
          </button>
        </div>
      );
    }

    return this.props.children;
  }
}

export default ErrorBoundaryWrapper;
