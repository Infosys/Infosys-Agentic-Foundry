import { useCallback, useMemo } from "react";
import { APIs } from "../constant";
import useFetch from "../Hooks/useAxios";
import { extractErrorMessage } from "../utils/errorUtils";

export const useMcpServerService = () => {
  const { fetchData, putData, deleteData, postData } = useFetch();

  /**
   * Delete MCP server(s) - always use array of tool_ids and MCP_DELETE_TOOLS endpoint (no serverId in URL)
   * @param {Object} data - Additional payload data (e.g., user_email_id, is_admin)
   * @param {string|string[]} serverIdOrIds - Single serverId or array of serverIds
   */
  const deleteServer = useCallback(
    async (data, serverIdOrIds) => {
      try {
        const apiUrl = APIs.MCP_DELETE_TOOLS;
        // Accept single ID or array, always send as array
        const ids = Array.isArray(serverIdOrIds) ? serverIdOrIds : [serverIdOrIds];
        const payload = { ...data, tool_ids: ids };
        const response = await deleteData(apiUrl, payload);
        if (response) return response;
        return null;
      } catch (error) {
        return extractErrorMessage(error);
      }
    },
    [deleteData]
  );

  const getAllServers = useCallback(async () => {
    try {
      
      const params = [];
      params.push(`page_number=1`);
      params.push(`page_size=20`);
      const apiUrl = `${APIs.MCP_GET_ALL_SERVERS}?${params.join("&")}`;
      
      const response = await fetchData(apiUrl);
      if (response) {
        return response;
      }
      return [];
    } catch (error) {
      return extractErrorMessage(error);
    }
  }, [fetchData]);

  const getServersSearchByPageLimit = useCallback(
    async ({ search, page, limit, tags, types, created_by }) => {
      try {
        const params = [];
        if (search && search.trim() && search.trim().length > 0) {
          params.push(`search_value=${encodeURIComponent(search)}`);
        }
        params.push(`page_number=${page}`);
        params.push(`page_size=${limit}`);
        if (created_by && created_by.trim()) {
          params.push(`created_by=${encodeURIComponent(created_by)}`);
        }

        // Process types if provided - ensure it's an array
        const typesArray = Array.isArray(types) ? types : types ? [types] : [];
        if (typesArray.length > 0) {
          typesArray.forEach((type) => {
            const typeUpper = String(type).toUpperCase();
            if (typeUpper === "REMOTE") {
              params.push(`mcp_type=${encodeURIComponent("url")}`);
            } else if (typeUpper === "LOCAL") {
              params.push(`mcp_type=${encodeURIComponent("file")}`);
            } else if (typeUpper === "EXTERNAL") {
              params.push(`mcp_type=${encodeURIComponent("module")}`);
            }
          });
        }

        // Process regular tags - ensure it's an array
        const tagsArray = Array.isArray(tags) ? tags : tags ? [tags] : [];
        if (tagsArray.length > 0) {
          tagsArray.forEach((tag) => {
            if (tag && String(tag).trim()) {
              params.push(`tag_names=${encodeURIComponent(tag)}`);
            }
          });
        }
        const apiUrl = `${APIs.MCP_GET_ALL_SERVERS}?${params.join("&")}`;
        const response = await fetchData(apiUrl);
        return response;
      } catch (error) {
        return extractErrorMessage(error);
      }
    },
    [fetchData]
  );

  const updateServer = useCallback(
    async (toolId, payload) => {
      try {
        // Patch: Ensure REMOTE server update always includes Authorization header
        const patchedPayload = { ...payload };
        if (patchedPayload.mcp_type === "url" && patchedPayload.vaultValue && typeof patchedPayload.vaultValue === "string" && patchedPayload.vaultValue.trim().length > 0) {
          patchedPayload.mcp_config = patchedPayload.mcp_config || {};
          patchedPayload.mcp_config.headers = patchedPayload.mcp_config.headers || {};
          patchedPayload.mcp_config.headers.Authorization = `VAULT::${patchedPayload.vaultValue}`;
        }
        const apiUrl = `${APIs.MCP_UPDATE_SERVER}${toolId}`;
        const response = await putData(apiUrl, patchedPayload);
        if (response) return response;
        return null;
      } catch (error) {
        return extractErrorMessage(error);
      }
    },
    [putData]
  );

  /** Catalog remote MCP tools (`tool_id` prefix `mcp_url_`): update stored URL and/or headers only. */
  const updateRemoteMcpUrl = useCallback(
    async (toolId, body) => {
      try {
        const apiUrl = `${APIs.MCP_UPDATE_REMOTE_URL}${toolId}`;
        const response = await putData(apiUrl, body);
        if (response) return response;
        return null;
      } catch (error) {
        return extractErrorMessage(error);
      }
    },
    [putData]
  );

  /** External (module) servers: update module name and command. */
  const updateModuleConfig = useCallback(
    async (toolId, body) => {
      try {
        const apiUrl = `${APIs.MCP_UPDATE_MODULE_CONFIG}${toolId}`;
        const response = await putData(apiUrl, body);
        if (response) return response;
        return null;
      } catch (error) {
        return extractErrorMessage(error);
      }
    },
    [putData]
  );

  const getLiveToolDetails = useCallback(
    async (toolId) => {
      try {
        const apiUrl = `${APIs.MCP_LIVE_TOOL_DETAIL}${toolId}`;
        const response = await fetchData(apiUrl);
        if (response && Array.isArray(response)) {
          return response;
        }
        return [];
      } catch (error) {
        return extractErrorMessage(error);
      }
    },
    [fetchData]
  );

  /**
   * Check server health status by attempting to fetch live tool details
   * Returns health status with tool count for remote/URL-based servers
   * @param {string} serverId - The server/tool ID to check
   * @param {number} timeoutMs - Timeout in milliseconds (default: 60000 - MCP connections can be slow)
   * @returns {Object} { isHealthy: boolean, toolCount: number, status: 'healthy' | 'unhealthy' | 'unknown' }
   */
  const checkServerHealth = useCallback(
    async (serverId, timeoutMs = 60000) => {
      try {
        const apiUrl = `${APIs.MCP_LIVE_TOOL_DETAIL}${serverId}`;

        // Create a timeout promise (60 seconds default - MCP connections can be slow)
        const timeoutPromise = new Promise((_, reject) => {
          setTimeout(() => reject(new Error("HEALTH_CHECK_TIMEOUT")), timeoutMs);
        });

        // Race between the actual fetch and timeout
        // Use silent: true to suppress error popups during health checks
        const response = await Promise.race([
          fetchData(apiUrl, { silent: true }),
          timeoutPromise,
        ]);

        // Debug log in development
        if (process.env.NODE_ENV === "development") {
          console.log(`[HealthCheck] Server ${serverId}:`, { response, type: typeof response, isArray: Array.isArray(response) });
        }

        // Handle different response formats
        // Response could be: array of tools, { details: [...] }, { tools: [...] }, or error object
        let tools = [];
        
        if (Array.isArray(response)) {
          tools = response;
        } else if (response && typeof response === "object") {
          // Check for nested array structures
          if (Array.isArray(response.details)) {
            tools = response.details;
          } else if (Array.isArray(response.tools)) {
            tools = response.tools;
          } else if (Array.isArray(response.data)) {
            tools = response.data;
          }
        }

        // Check if we have valid tools
        if (tools.length > 0) {
          // Check for error messages in the first element
          if (tools[0] && typeof tools[0] === "object" && "error" in tools[0]) {
            return { isHealthy: false, toolCount: 0, status: "unhealthy" };
          }
          return { isHealthy: true, toolCount: tools.length, status: "healthy" };
        }

        // No tools returned - but if we got a valid response, it's reachable but empty
        // Check if we got an error response
        if (response && typeof response === "object" && ("error" in response || "message" in response)) {
          return { isHealthy: false, toolCount: 0, status: "unhealthy" };
        }

        // Server reachable but no tools
        return { isHealthy: false, toolCount: 0, status: "unhealthy" };
      } catch (error) {
        // Debug log errors in development
        if (process.env.NODE_ENV === "development") {
          console.warn(`[HealthCheck] Error for ${serverId}:`, error?.message || error);
        }
        
        // Check if it's a timeout error
        if (error?.message === "HEALTH_CHECK_TIMEOUT") {
          return { isHealthy: false, toolCount: 0, status: "unknown" };
        }
        // Check for blocked API calls (error loop protection)
        if (error?.isBlocked || error?.message?.includes("blocked")) {
          return { isHealthy: false, toolCount: 0, status: "unknown" };
        }
        // HTTP 500 errors - server is configured but MCP endpoint is unreachable
        if (error?.response?.status === 500) {
          return { isHealthy: false, toolCount: 0, status: "unhealthy" };
        }
        // Other errors - server unreachable
        return { isHealthy: false, toolCount: 0, status: "unhealthy" };
      }
    },
    [fetchData]
  );

  /**
   * Get server details by ID
   * @param {string} serverId - The server/tool ID to fetch
   * @returns {Object|null} Server details or null if not found
   */
  const getServerById = useCallback(
    async (serverId) => {
      try {
        const apiUrl = `${APIs.MCP_GET_SERVER_BY_ID}${serverId}`;
        const response = await fetchData(apiUrl);
        if (response) {
          return response;
        }
        return null;
      } catch (error) {
        return extractErrorMessage(error);
      }
    },
    [fetchData]
  );

  const exportServers = useCallback(
    async (toolIds) => {
      try {
        const apiUrl = APIs.MCP_EXPORT_SERVERS;
        const response = await postData(apiUrl, { tool_ids: toolIds }, {
          responseType: "blob",
        });
        return response;
      } catch (error) {
        try {
          const blob = error?.response?.data;
          if (blob instanceof Blob && ((blob.type && blob.type.includes("json")) || blob.size < 8192)) {
            const text = await blob.text();
            const trimmed = text.trim();
            if (trimmed.startsWith("{") || trimmed.startsWith("[")) {
              const parsed = JSON.parse(trimmed);
              if (parsed && (parsed.detail || parsed.message || parsed.error)) {
                error.message = parsed.detail || parsed.message || parsed.error;
              }
            }
          }
        } catch (_) {
          // ignore parse issues
        }
        throw error;
      }
    },
    [postData]
  );

  const importServers = useCallback(
    async (zipFile, createdBy) => {
      try {
        const apiUrl = APIs.MCP_IMPORT_SERVERS;
        const formData = new FormData();
        formData.append("zip_file", zipFile);
        formData.append("created_by", createdBy || "");
        const response = await postData(apiUrl, formData);
        return response;
      } catch (error) {
        return extractErrorMessage(error);
      }
    },
    [postData]
  );

  return useMemo(
    () => ({
      deleteServer,
      getAllServers,
      getServersSearchByPageLimit,
      updateServer,
      updateRemoteMcpUrl,
      updateModuleConfig,
      getLiveToolDetails,
      checkServerHealth,
      getServerById,
      exportServers,
      importServers,
    }),
    [deleteServer, getServersSearchByPageLimit, updateServer, updateRemoteMcpUrl, updateModuleConfig, getLiveToolDetails, checkServerHealth, getServerById, exportServers, importServers]
  );
};
