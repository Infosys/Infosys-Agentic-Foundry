import useFetch from "../Hooks/useAxios";
import { APIs } from "../constant";

/**
 * Knowledge Base Service Hook
 * Provides methods for fetching and managing knowledge bases
 */
export const useKnowledgeBaseService = () => {
  const { fetchData, postData, putData, deleteData } = useFetch();

  /**
   * Map raw KB data to consistent format
   */
  const mapKnowledgeBase = (kb) => ({
    kb_id: kb.kb_id,
    id: kb.kb_id,
    name: kb.kb_name || "Unnamed Knowledge Base",
    kb_name: kb.kb_name,
    documents: kb.list_of_documents || [],
    created_by: kb.created_by || "",
    created_on: kb.created_on || "",
    type: "knowledgebases",
  });

  /**
   * Get knowledge bases with optional search filtering
   * Note: Pagination is handled client-side as the backend API doesn't support it yet.
   * Page and limit parameters are accepted for API consistency but filtering happens after fetch.
   * @param {Object} options - Search and pagination options
   * @param {string} options.search - Search term to filter knowledge bases by name
   * @param {number} options.page - Page number for pagination (client-side)
   * @param {number} options.limit - Number of items per page (client-side)
   * @returns {Promise<{details: Array, count: number}>} Filtered knowledge bases and total count
   */
  const getKnowledgeBasesSearchByPageLimit = async ({ search = "", page = 1, limit = 10 } = {}) => {
    const response = await fetchData(APIs.KB_GET_LIST);
    let knowledgeBases = response?.knowledge_bases || [];

    // Apply client-side search filtering
    if (search?.trim()) {
      const searchLower = search.toLowerCase();
      knowledgeBases = knowledgeBases.filter((kb) =>
        kb.kb_name?.toLowerCase().includes(searchLower)
      );
    }

    // Apply client-side pagination
    // TODO: Move pagination to backend API when supported
    const totalCount = knowledgeBases.length;
    const startIndex = (page - 1) * limit;
    const endIndex = startIndex + limit;
    const paginatedResults = knowledgeBases.slice(startIndex, endIndex);

    return {
      details: paginatedResults.map(mapKnowledgeBase),
      count: totalCount,
    };
  };

  /**
   * Get a single knowledge base by ID
   */
  const getKnowledgeBaseById = async (kbId) => {
    const response = await fetchData(`${APIs.KB_GET_BY_ID}${encodeURIComponent(kbId)}`);
    return response;
  };

  /**
   * Get multiple knowledge bases by IDs using bulk API
   * @param {string[]} kbIds - Array of knowledge base IDs to fetch
   * @returns {Promise<Array>} Array of mapped knowledge bases
   */
  const getKnowledgeBasesByIds = async (kbIds = []) => {
    if (!kbIds || kbIds.length === 0) return [];
    
    const response = await postData(APIs.KB_GET_BY_LIST, kbIds);
    const knowledgeBases = response?.knowledge_bases || response || [];
    return Array.isArray(knowledgeBases) ? knowledgeBases.map(mapKnowledgeBase) : [];
  };

  /**
   * Get knowledge bases associated with an agent by IDs
   * @param {string[]} kbIds - Array of knowledge base IDs to fetch
   * @returns {Promise<Array>} Array of mapped knowledge bases for the agent
   */
  const getKnowledgeBasesForAgent = async (kbIds = []) => {
    if (!kbIds || kbIds.length === 0) return [];

    const response = await postData(APIs.KB_GET_BY_LIST_FOR_AGENT, kbIds);
    const knowledgeBases = response?.knowledgebases || response?.knowledge_bases || response || [];
    return Array.isArray(knowledgeBases) ? knowledgeBases.map(mapKnowledgeBase) : [];
  };

  /**
   * Delete knowledge bases by IDs
   * @param {string[]} kbIds - Array of knowledge base IDs to delete
   * @param {string} userEmail - Email of the user requesting deletion
   */
  const deleteKnowledgeBases = async (kbIds, userEmail) => {
    const payload = {
      kb_ids: kbIds,
      user_email: userEmail,
    };
    return await deleteData(APIs.KB_DELETE, payload);
  };

  /**
   * Update sharing settings (visibility & department sharing) for a knowledge base
   * PUT /utility/knowledge-base/{kb_id}/sharing
   * @param {string} kbId - The knowledge base ID
   * @param {boolean} isPublic - Whether the KB should be publicly accessible to all departments
   * @param {string[]} sharedWithDepartments - List of department names to share with
   * @returns {Promise<Object>} Updated sharing information
   */
  const updateKnowledgeBaseSharing = async (kbId, isPublic, sharedWithDepartments = []) => {
    const url = `${APIs.KB_UPDATE_SHARING}${encodeURIComponent(kbId)}/sharing`;
    const payload = {
      is_public: isPublic,
      shared_with_departments: isPublic ? [] : sharedWithDepartments,
    };
    return await putData(url, payload);
  };

  return {
    getKnowledgeBasesSearchByPageLimit,
    getKnowledgeBaseById,
    getKnowledgeBasesByIds,
    getKnowledgeBasesForAgent,
    deleteKnowledgeBases,
    updateKnowledgeBaseSharing,
  };
};

export default useKnowledgeBaseService;
