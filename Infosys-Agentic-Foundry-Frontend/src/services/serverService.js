import { useCallback, useMemo } from "react";
import { APIs } from "../constant";
import useFetch from "../Hooks/useAxios";
import { extractErrorMessage } from "../utils/errorUtils";

export const useMcpServerService = () => {
  const { fetchData, putData, deleteData } = useFetch();

  const deleteServer = useCallback(
    async (data, serverId) => {
      try {
        const apiUrl = `${APIs.MCP_DELETE_TOOLS}${serverId}`;
        const payload = { ...data, tool_id: serverId };
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

  return useMemo(
    () => ({
      deleteServer,
      getAllServers,
      getServersSearchByPageLimit,
      updateServer,
      getLiveToolDetails,
      getServerById,
    }),
    [deleteServer, getServersSearchByPageLimit, updateServer, getLiveToolDetails, getServerById]
  );
};
