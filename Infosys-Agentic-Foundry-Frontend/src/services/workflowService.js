
/**
 * Workflow Service Module
 *
 * Provides API methods for managing workflows in the application.
 * Follows the existing service pattern used throughout the project.
 */
import useFetch from "../Hooks/useAxios";
import { APIs } from "../constant";
import { getEmailFromToken, getRoleFromToken } from "../utils/jwtUtils";

export const isWorkflowAdminUser = () => {
  const role = (getRoleFromToken() || "").toLowerCase().replace(/[\s_-]/g, "");
  return role === "admin" || role === "superadmin";
};

export const resolveWorkflowId = (workflow, fallbackId = "") =>
  workflow?.workflow_id || workflow?.pipeline_id || workflow?.id || fallbackId || "";

export const buildWorkflowDeletePayload = (workflowIds, overrides = {}) => ({
  workflow_ids: Array.isArray(workflowIds) ? workflowIds : [workflowIds],
  is_admin: overrides.is_admin ?? isWorkflowAdminUser(),
  user_email_id: overrides.user_email_id ?? getEmailFromToken(),
});

export const normalizeWorkflowRecord = (raw, fallbackId = "") => {
  const workflow = raw?.workflow || raw || {};
  return {
    ...workflow,
    workflow_id: resolveWorkflowId(workflow, fallbackId),
  };
};

const isWorkflowDeleteSuccess = (item) =>
  item?.is_deleted === true || item?.is_delete === true;

const isWorkflowDeleteFailure = (item) =>
  item?.is_deleted === false || item?.is_delete === false;

export const parseWorkflowDeleteResponse = (response) => {
  if (!response || typeof response === "string") {
    return { ok: false, message: "Failed to delete workflow" };
  }

  const message = response.status_message || response.message || "Workflow deleted successfully";
  const results = Array.isArray(response.results) ? response.results : [];
  const hasExplicitFailure = results.some(isWorkflowDeleteFailure);
  const hasExplicitSuccess = results.some(isWorkflowDeleteSuccess);
  const statusSuccess = String(response.status || "").toLowerCase() === "success";

  const ok = hasExplicitFailure ? false : hasExplicitSuccess || statusSuccess || results.length === 0;

  return { ok, message };
};

/**
 * Custom hook for workflow-related API operations
 * @returns {Object} Workflow service methods
 */
export const useWorkflowService = () => {
  const { fetchData, postData, putData, deleteData } = useFetch();

  /**
   * Bulk delete workflows
   * @param {Object} payload - { workflow_ids: string[], is_admin: boolean, user_email_id: string }
   * @returns {Promise<Object>} Bulk deletion response
   */
  const deleteWorkflowsBulk = async (payload) => {
    const workflowIds = payload?.workflow_ids;
    if (!Array.isArray(workflowIds) || workflowIds.length === 0) {
      throw new Error("At least one workflow ID is required");
    }
    const requestPayload = buildWorkflowDeletePayload(workflowIds, payload);
    return await postData(APIs.WORKFLOW_DELETE, requestPayload);
  };

  /**
   * Get all workflows with optional filtering
   * @param {Object} params - Query parameters
   * @param {string} [params.created_by] - Filter by creator email
   * @param {boolean} [params.is_active] - Filter by active status
   * @returns {Promise<Object>} Workflow list response
   */
  const getAllWorkflows = async (params = {}) => {
    const queryParams = new URLSearchParams();
    if (params.created_by) queryParams.append("created_by", params.created_by);
    if (params.is_active !== undefined) queryParams.append("is_active", params.is_active);

    const queryString = queryParams.toString();
    const url = queryString ? `${APIs.WORKFLOW_GET_ALL}?${queryString}` : APIs.WORKFLOW_GET_ALL;

    return await fetchData(url);
  };

  /**
   * Get paginated workflows with search
   * @param {Object} params - Query parameters
   * @param {number} [params.page=1] - Page number
   * @param {number} [params.limit=20] - Items per page
   * @param {string} [params.search] - Search term
   * @param {string} [params.created_by] - Filter by creator
   * @param {boolean} [params.is_active] - Filter by active status
   * @returns {Promise<Object>} Paginated workflow response
   */
  const getWorkflowsPaginated = async ({ page = 1, limit = 20, search = "", created_by, is_active } = {}) => {
    const queryParams = new URLSearchParams();
    queryParams.append("page_number", page);
    queryParams.append("page_size", limit);
    if (search) queryParams.append("search_value", search);
    if (created_by) queryParams.append("created_by", created_by);
    if (is_active !== undefined) queryParams.append("is_active", is_active);

    const url = `${APIs.WORKFLOW_GET_PAGINATED}?${queryParams.toString()}`;
    return await fetchData(url);
  };

  /**
   * Get a single workflow by ID
   * @param {string} workflowId - Workflow ID
   * @returns {Promise<Object>} Workflow details
   */
  const getWorkflowById = async (workflowId) => {
    if (!workflowId) throw new Error("Workflow ID is required");
    const url = `${APIs.WORKFLOW_GET_BY_ID}/${encodeURIComponent(workflowId)}`;
    return await fetchData(url);
  };

  /**
   * Create a new workflow
   * @param {Object} workflowData - Workflow creation data
   * @param {string} workflowData.workflow_name - Workflow name
   * @param {string} [workflowData.workflow_description] - Workflow description
   * @param {Object} workflowData.workflow_definition - Workflow definition (nodes & edges)
   * @param {string} workflowData.created_by - Creator email
   * @returns {Promise<Object>} Creation response
   */
  const createWorkflow = async (workflowData) => {
    return await postData(APIs.WORKFLOW_CREATE, workflowData);
  };

  /**
   * Update an existing workflow
   * @param {string} workflowId - Workflow ID
   * @param {Object} updateData - Fields to update
   * @returns {Promise<Object>} Update response
   */
  const updateWorkflow = async (workflowId, updateData) => {
    if (!workflowId) throw new Error("Workflow ID is required");
    const url = `${APIs.WORKFLOW_UPDATE}/${encodeURIComponent(workflowId)}`;
    return await putData(url, updateData);
  };

  /**
   * Delete a workflow (single delete now uses bulk endpoint)
   * @param {string} workflowId - Workflow ID
   * @returns {Promise<Object>} Deletion response
   */
  const deleteWorkflow = async (workflowId) => {
    if (!workflowId) throw new Error("Workflow ID is required");
    return await deleteWorkflowsBulk({ workflow_ids: [workflowId] });
  };

  /**
   * Get available agents for workflow builder
   * @returns {Promise<Object>} Available agents list
   */
  const getAvailableAgents = async () => {
    return await fetchData(APIs.WORKFLOW_AVAILABLE_AGENTS);
  };

  /**
   * Execute a workflow
   * @param {string} workflowId - Workflow ID
   * @param {Object} executeData - Execution parameters
   * @returns {Promise<Object>} Execution response
   */
  const executeWorkflow = async (workflowId, executeData) => {
    if (!workflowId) throw new Error("Workflow ID is required");
    const url = APIs.WORKFLOW_EXECUTE.replace("{workflow_id}", encodeURIComponent(workflowId));
    return await postData(url, executeData);
  };

  /**
   * Get workflow execution history
   * @param {string} workflowId - Workflow ID
   * @param {number} [limit=50] - Maximum executions to return
   * @returns {Promise<Object>} Execution history
   */
  const getWorkflowExecutions = async (workflowId, limit = 50) => {
    if (!workflowId) throw new Error("Workflow ID is required");
    const url = `${APIs.WORKFLOW_GET_EXECUTIONS.replace("{workflow_id}", encodeURIComponent(workflowId))}?limit=${limit}`;
    return await fetchData(url);
  };

  return {
    getAllWorkflows,
    getWorkflowsPaginated,
    getWorkflowById,
    createWorkflow,
    updateWorkflow,
    deleteWorkflow,
    deleteWorkflowsBulk,
    getAvailableAgents,
    executeWorkflow,
    getWorkflowExecutions,
  };
};

export default useWorkflowService;