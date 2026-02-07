import React from "react";
import { useMessage } from "../../Hooks/MessageContext";

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
    })
  );

  // Unblock after duration
  setTimeout(() => {
    apiCallsBlocked = false;
    globalErrorCount = 0;
    window.dispatchEvent(
      new CustomEvent("errorLoopCleared", {
        detail: { blocked: false, timestamp: Date.now() },
      })
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
    };
  }

  static getDerivedStateFromError(error) {
    // IMPORTANT: This static method cannot access the component instance (no 'this').
    // Only derive minimal state needed to trigger fallback UI. All side effects &
    // instance state updates (counters, timers, etc.) are handled in componentDidCatch.
    return {
      hasError: true,
      // Provide an errorId early so the UI can show something deterministic on first render
      errorId: `error_${Date.now()}_${crypto.randomUUID()}`,
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
    this.setState((prev) => {
      const isRapidError = prev.lastErrorTime && now - prev.lastErrorTime < 1000;
      const nextCount = isRapidError ? (prev.errorCount || 0) + 1 : 1;
      return {
        errorCount: nextCount,
        lastErrorTime: now,
      };
    });

    if (this.state.errorCount > 2) {
      console.warn("🔄 Rapid error loop detected in component, preventing re-renders");
    }

    // ----- User messaging (avoid spamming) -----
    try {
      const { addMessage } = this.props;
      if (this.state.errorCount <= 2 && !apiCallsBlocked) {
        addMessage && addMessage("Something went wrong rendering this page. Please refresh.", "error");
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