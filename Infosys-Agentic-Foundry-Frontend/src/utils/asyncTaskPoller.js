import { APIs, ASYNC_RESPONSE_MODE } from "../constant";
import { axiosInstance } from "../Hooks/useAxios";
import { normalizeInferenceResult } from "./messageUtils";

const POLL_INTERVAL_MS = 2500;
const MAX_POLL_DURATION_MS = 5 * 60 * 1000; // 5 minutes

/**
 * Check if async response mode is enabled via env config.
 */
export const isAsyncModeEnabled = () => {
  const val = (ASYNC_RESPONSE_MODE || "").trim().toLowerCase();
  return val === "true" || val === "1" || val === "yes" || val === "on";
};

/**
 * Append ?async_response_mode=<env value> to a URL.
 * The value always comes from REACT_APP_ASYNC_RESPONSE_MODE in .env.
 */
export const withAsyncFlag = (url) => {
  const val = (ASYNC_RESPONSE_MODE || "false").trim().toLowerCase();
  const separator = url.includes("?") ? "&" : "?";
  return `${url}${separator}async_response_mode=${encodeURIComponent(val)}`;
};

/**
 * Poll a task until completed or failed.
 * @param {string} taskId - The task_id from the 202 response
 * @param {object} options
 * @param {function} options.onStatusChange - Called with (status, taskData) on each poll
 * @param {number} options.pollInterval - Polling interval in ms (default 2500)
 * @param {number} options.timeout - Max polling duration in ms (default 5 min)
 * @param {AbortSignal} options.signal - Optional abort signal to cancel polling
 * @returns {Promise<object>} - The result field from the completed task
 */
export const pollAsyncTask = async (taskId, options = {}) => {
  const {
    onStatusChange,
    pollInterval = POLL_INTERVAL_MS,
    timeout = MAX_POLL_DURATION_MS,
    signal,
  } = options;

  const startTime = Date.now();

  while (true) {
    if (signal?.aborted) {
      throw new Error("Polling cancelled");
    }

    if (Date.now() - startTime > timeout) {
      throw new Error("Async task timed out. The operation may still be running in the background.");
    }

    await new Promise((resolve) => setTimeout(resolve, pollInterval));

    try {
      const response = await axiosInstance.get(`${APIs.ASYNC_TASK_STATUS}${encodeURIComponent(taskId)}`);
      const task = response.data;

      if (onStatusChange) {
        onStatusChange(task.status, task);
      }

      if (task.status === "completed") {
        return normalizeInferenceResult(task.result);
      }

      if (task.status === "failed") {
        throw new Error(task.error || "Async task failed");
      }
      // queued or processing — continue polling
    } catch (err) {
      if (err.response?.status === 404) {
        throw new Error("Task not found or expired");
      }
      if (err.response?.status === 403) {
        throw new Error("Not authorized to view this task");
      }
      // Re-throw if it's our own error (timeout, failed, cancelled)
      if (err.message && !err.response) {
        throw err;
      }
      // Network error during poll — continue polling (transient)
    }
  }
};

/**
 * Submit a request in async mode and poll for the result.
 * Handles the full flow: submit → 202 → poll → result.
 *
 * @param {function} submitFn - The original API call function (postData/putData etc.)
 * @param {string} url - The API endpoint URL
 * @param {object} data - The request body
 * @param {object} options
 * @param {function} options.onStatusChange - Called with (status, taskData) on each poll
 * @param {number} options.pollInterval - Polling interval in ms
 * @param {number} options.timeout - Max polling duration in ms
 * @param {AbortSignal} options.signal - Optional abort signal
 * @returns {Promise<object>} - The result (same as sync response)
 */
export const submitAndPollAsync = async (submitFn, url, data, options = {}) => {
  const asyncUrl = withAsyncFlag(url);
  const response = await submitFn(asyncUrl, data);

  // If server returned a task_id (202 Accepted), poll for result
  if (response?.task_id) {
    return pollAsyncTask(response.task_id, options);
  }

  // If server didn't return a task_id, it processed synchronously — return as-is
  return response;
};