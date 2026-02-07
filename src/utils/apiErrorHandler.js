// Utility functions for handling API errors and preventing loops

// Global error tracking
let consecutiveErrors = 0;
let lastErrorTime = 0;
const ERROR_RESET_TIME = 30000; // 30 seconds

export const handleApiError = (error, context = "") => {
  const now = Date.now();

  // Reset counter if enough time has passed
  if (now - lastErrorTime > ERROR_RESET_TIME) {
    consecutiveErrors = 0;
  }

  consecutiveErrors++;
  lastErrorTime = now;

  console.warn(`API Error ${consecutiveErrors} in ${context}:`, error);

  // If too many consecutive errors, suggest page refresh
  if (consecutiveErrors >= 5) {
    console.error("Too many consecutive API errors. Consider refreshing the page.");

    // Dispatch custom event for components to handle
    window.dispatchEvent(
      new CustomEvent("tooManyApiErrors", {
        detail: { count: consecutiveErrors, context, error },
      })
    );

    return { shouldStop: true, message: "Too many errors. Please refresh the page." };
  }

  return { shouldStop: false, message: null };
};

export const resetApiErrorCount = () => {
  consecutiveErrors = 0;
  lastErrorTime = 0;
};

// Safe API call wrapper
export const safeApiCall = async (apiFunction, fallbackValue = null, context = "") => {
  try {
    const result = await apiFunction();
    resetApiErrorCount(); // Reset on success
    return { success: true, data: result, error: null };
  } catch (error) {
    const errorResult = handleApiError(error, context);

    return {
      success: false,
      data: fallbackValue,
      error: error.message || "Unknown error",
      shouldStop: errorResult.shouldStop,
      message: errorResult.message,
    };
  }
};

// Debounce function to prevent rapid API calls
export const debounce = (func, wait) => {
  let timeout;
  return function executedFunction(...args) {
    const later = () => {
      clearTimeout(timeout);
      func(...args);
    };
    clearTimeout(timeout);
    timeout = setTimeout(later, wait);
  };
};
