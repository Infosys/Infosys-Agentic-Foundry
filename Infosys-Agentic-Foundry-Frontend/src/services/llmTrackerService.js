import { APIs } from "../constant";
import useFetch from "../Hooks/useAxios";

/**
 * LLM Tracker Service
 *
 * Wraps the /llm-tracking read-only drill-down endpoints.
 * Uses { silent: true } so the component handles errors inline
 * instead of showing global toasts.
 *
 * Follows the same service-hook pattern as schedulerService.js,
 * hookRepositoryService.js, etc.
 */
export const useLlmTrackerService = () => {
  const { fetchData } = useFetch();

  /**
   * List all users visible to the authenticated user.
   * SuperAdmin → all users; Admin → department users; User/Dev → self only.
   * GET /llm-tracking/users
   */
  const getUsers = () =>
    fetchData(APIs.LLM_TRACKING_USERS, { silent: true });

  /**
   * List all sessions for a given user.
   * GET /llm-tracking/users/{userId}/sessions
   */
  const getSessions = (userId) =>
    fetchData(
      `${APIs.LLM_TRACKING_SESSIONS_BASE}/${encodeURIComponent(userId)}/sessions`,
      { silent: true }
    );

  /**
   * List all requests in a session.
   * GET /llm-tracking/sessions/{sessionId}/requests?user_id={userId}
   * userId scopes the result to a specific user (required by the backend).
   */
  const getRequests = (sessionId, userId) => {
    const params = new URLSearchParams();
    if (userId) params.set("user_id", userId);
    const query = params.toString() ? `?${params}` : "";
    return fetchData(
      `${APIs.LLM_TRACKING_REQUESTS_BASE}/${encodeURIComponent(sessionId)}/requests${query}`,
      { silent: true }
    );
  };

  /**
   * List all LLM calls made within a request.
   * GET /llm-tracking/requests/{requestId}/llm-calls?user_id={userId}&session_id={sessionId}
   * userId + sessionId scope the result to the correct context.
   */
  const getLlmCalls = (requestId, userId, sessionId) => {
    const params = new URLSearchParams();
    if (userId) params.set("user_id", userId);
    if (sessionId) params.set("session_id", sessionId);
    const query = params.toString() ? `?${params}` : "";
    return fetchData(
      `${APIs.LLM_TRACKING_CALLS_BASE}/${encodeURIComponent(requestId)}/llm-calls${query}`,
      { silent: true }
    );
  };

  return { getUsers, getSessions, getRequests, getLlmCalls };
};
