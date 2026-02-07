/**
 * Pipeline Service Module
 *
 * Provides API methods for managing pipelines in the application.
 * Follows the existing service pattern used throughout the project.
 */

import useFetch from "../Hooks/useAxios";
import { APIs } from "../constant";

/**
 * Custom hook for pipeline-related API operations
 * @returns {Object} Pipeline service methods
 */
export const usePipelineService = () => {
  const { fetchData, postData, putData, deleteData } = useFetch();

  /**
   * Get all pipelines with optional filtering
   * @param {Object} params - Query parameters
   * @param {string} [params.created_by] - Filter by creator email
   * @param {boolean} [params.is_active] - Filter by active status
   * @returns {Promise<Object>} Pipeline list response
   */
  const getAllPipelines = async (params = {}) => {
    const queryParams = new URLSearchParams();
    if (params.created_by) queryParams.append("created_by", params.created_by);
    if (params.is_active !== undefined) queryParams.append("is_active", params.is_active);

    const queryString = queryParams.toString();
    const url = queryString ? `${APIs.PIPELINE_GET_ALL}?${queryString}` : APIs.PIPELINE_GET_ALL;

    return await fetchData(url);
  };

  /**
   * Get paginated pipelines with search
   * @param {Object} params - Query parameters
   * @param {number} [params.page=1] - Page number
   * @param {number} [params.limit=20] - Items per page
   * @param {string} [params.search] - Search term
   * @param {string} [params.created_by] - Filter by creator
   * @param {boolean} [params.is_active] - Filter by active status
   * @returns {Promise<Object>} Paginated pipeline response
   */
  const getPipelinesPaginated = async ({ page = 1, limit = 20, search = "", created_by, is_active } = {}) => {
    const queryParams = new URLSearchParams();
    queryParams.append("page_number", page);
    queryParams.append("page_size", limit);
    if (search) queryParams.append("search_value", search);
    if (created_by) queryParams.append("created_by", created_by);
    if (is_active !== undefined) queryParams.append("is_active", is_active);

    const url = `${APIs.PIPELINE_GET_PAGINATED}?${queryParams.toString()}`;
    return await fetchData(url);
  };

  /**
   * Get a single pipeline by ID
   * @param {string} pipelineId - Pipeline ID
   * @returns {Promise<Object>} Pipeline details
   */
  const getPipelineById = async (pipelineId) => {
    if (!pipelineId) throw new Error("Pipeline ID is required");
    const url = `${APIs.PIPELINE_GET_BY_ID}${encodeURIComponent(pipelineId)}`;
    return await fetchData(url);
  };

  /**
   * Create a new pipeline
   * @param {Object} pipelineData - Pipeline creation data
   * @param {string} pipelineData.pipeline_name - Pipeline name
   * @param {string} [pipelineData.pipeline_description] - Pipeline description
   * @param {Object} pipelineData.pipeline_definition - Pipeline definition (nodes & edges)
   * @param {string} pipelineData.created_by - Creator email
   * @returns {Promise<Object>} Creation response
   */
  const createPipeline = async (pipelineData) => {
    return await postData(APIs.PIPELINE_CREATE, pipelineData);
  };

  /**
   * Update an existing pipeline
   * @param {string} pipelineId - Pipeline ID
   * @param {Object} updateData - Fields to update
   * @returns {Promise<Object>} Update response
   */
  const updatePipeline = async (pipelineId, updateData) => {
    if (!pipelineId) throw new Error("Pipeline ID is required");
    const url = `${APIs.PIPELINE_UPDATE}${encodeURIComponent(pipelineId)}`;
    return await putData(url, updateData);
  };

  /**
   * Delete a pipeline
   * @param {string} pipelineId - Pipeline ID
   * @returns {Promise<Object>} Deletion response
   */
  const deletePipeline = async (pipelineId) => {
    if (!pipelineId) throw new Error("Pipeline ID is required");
    const url = `${APIs.PIPELINE_DELETE}${encodeURIComponent(pipelineId)}`;
    return await deleteData(url);
  };

  /**
   * Get available agents for pipeline builder
   * @returns {Promise<Object>} Available agents list
   */
  const getAvailableAgents = async () => {
    return await fetchData(APIs.PIPELINE_AVAILABLE_AGENTS);
  };

  /**
   * Execute a pipeline
   * @param {string} pipelineId - Pipeline ID
   * @param {Object} executeData - Execution parameters
   * @returns {Promise<Object>} Execution response
   */
  const executePipeline = async (pipelineId, executeData) => {
    if (!pipelineId) throw new Error("Pipeline ID is required");
    const url = APIs.PIPELINE_EXECUTE.replace("{pipeline_id}", encodeURIComponent(pipelineId));
    return await postData(url, executeData);
  };

  /**
   * Get pipeline execution history
   * @param {string} pipelineId - Pipeline ID
   * @param {number} [limit=50] - Maximum executions to return
   * @returns {Promise<Object>} Execution history
   */
  const getPipelineExecutions = async (pipelineId, limit = 50) => {
    if (!pipelineId) throw new Error("Pipeline ID is required");
    const url = `${APIs.PIPELINE_GET_EXECUTIONS.replace("{pipeline_id}", encodeURIComponent(pipelineId))}?limit=${limit}`;
    return await fetchData(url);
  };

  return {
    getAllPipelines,
    getPipelinesPaginated,
    getPipelineById,
    createPipeline,
    updatePipeline,
    deletePipeline,
    getAvailableAgents,
    executePipeline,
    getPipelineExecutions,
  };
};

export default usePipelineService;