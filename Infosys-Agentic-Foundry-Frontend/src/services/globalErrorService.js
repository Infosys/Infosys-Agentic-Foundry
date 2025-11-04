class GlobalErrorService {
  constructor() {
    this.errorLog = [];
    this.maxLogSize = 100;
    this.messageCallback = null;
    this.subscribers = [];
    this.isInitialized = false;
  }

  initialize(messageCallback) {
    if (this.isInitialized) {
      console.warn("⚠️ Global Error Service already initialized");
      return;
    }

    this.messageCallback = messageCallback;

    // Handle global JavaScript errors
    window.addEventListener("error", this.handleWindowError);

    // Handle unhandled promise rejections
    window.addEventListener("unhandledrejection", this.handlePromiseRejection);

    this.isInitialized = true;
    console.log("✅ Global Error Service initialized");
  }

  handleWindowError = (event) => {
    this.logError({
      type: "Window Error",
      message: event.message,
      filename: event.filename,
      lineno: event.lineno,
      colno: event.colno,
      error: event.error,
      stack: event.error?.stack,
    });

    if (event.message && !event.message.includes("ResizeObserver")) {
      this.notifyUser(event.message);
    }

    // Prevent default error handling in some cases
    // event.preventDefault();
  };

  handlePromiseRejection = (event) => {
    this.logError({
      type: "Unhandled Promise Rejection",
      reason: event.reason,
      promise: event.promise,
    });

    const message = event.reason?.message || String(event.reason);
    this.notifyUser(message);

    // Prevent default handling
    event.preventDefault();
  };

  logError(errorDetails) {
    const enrichedError = {
      ...errorDetails,
      timestamp: new Date().toISOString(),
      url: window.location.href,
      userAgent: navigator.userAgent,
    };

    this.errorLog.push(enrichedError);

    // Keep log size manageable
    if (this.errorLog.length > this.maxLogSize) {
      this.errorLog.shift();
    }

    console.error("🔴 Error Logged:", enrichedError);
    this.notifySubscribers(enrichedError);
  }

  notifyUser(errorMessage) {
    if (this.messageCallback && typeof this.messageCallback === "function") {
      const friendlyMessage = this.getFriendlyMessage(errorMessage);
      this.messageCallback(friendlyMessage, "error");
    }
  }

  getFriendlyMessage(technicalMessage) {
    const errorMappings = {
      "Network Error": "Unable to connect. Please check your internet connection.",
      "Failed to fetch": "Network request failed. Please try again.",
      Unauthorized: "Session expired. Please log in again.",
      401: "Session expired. Please log in again.",
      403: "You don't have permission for this action.",
      404: "Resource not found.",
      500: "Server error. Please try again later.",
      503: "Service temporarily unavailable. Please try again later.",
      "is not defined": "A technical error occurred. Please refresh the page.",
      "Cannot read property": "A technical error occurred. Please refresh the page.",
      "Cannot read properties": "A technical error occurred. Please refresh the page.",
      undefined: "A technical error occurred. Please try again.",
    };

    for (const [key, value] of Object.entries(errorMappings)) {
      if (technicalMessage && technicalMessage.includes(key)) {
        return value;
      }
    }

    // Return a generic message for long technical errors
    return technicalMessage && technicalMessage.length > 100 ? "An unexpected error occurred. Please try again." : technicalMessage || "An unexpected error occurred.";
  }

  subscribe(callback) {
    this.subscribers.push(callback);
    return () => {
      this.subscribers = this.subscribers.filter((cb) => cb !== callback);
    };
  }

  notifySubscribers(error) {
    this.subscribers.forEach((callback) => {
      try {
        callback(error);
      } catch (err) {
        console.error("Error in subscriber:", err);
      }
    });
  }

  getErrorLog() {
    return [...this.errorLog];
  }

  clearLog() {
    this.errorLog = [];
    console.log("✅ Error log cleared");
  }

  cleanup() {
    window.removeEventListener("error", this.handleWindowError);
    window.removeEventListener("unhandledrejection", this.handlePromiseRejection);
    this.isInitialized = false;
    console.log("✅ Global Error Service cleaned up");
  }
}

// Export singleton instance
export const globalErrorService = new GlobalErrorService();
