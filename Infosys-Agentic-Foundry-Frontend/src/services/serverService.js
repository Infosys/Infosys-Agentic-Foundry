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

  // const getAllServers = useCallback(async () => {
  //   try {
  //     const apiUrl = `${APIs.MCP_GET_ALL_SERVERS}`;
  //     const response = await fetchData(apiUrl);
  //     if (response) {
  //       return response;
  //     }
  //     return [];
  //   } catch (error) {
  //     return extractErrorMessage(error);
  //   }
  // }, [fetchData]);

  const getServersSearchByPageLimit = useCallback(
    async ({ search, page, limit, tags }) => {
      try {
        const params = [];
        if (search && search.trim() && search.trim().length > 0) {
          params.push(`search_value=${encodeURIComponent(search)}`);
        }
        params.push(`page_number=${page}`);
        params.push(`page_size=${limit}`);

        // Add tag_names parameter if tags are provided (same as tools/agents)
        if (tags && Array.isArray(tags) && tags.length > 0) {
          // Process all selected type filters
          const typeFilters = tags.filter(tag => ["REMOTE", "LOCAL", "EXTERNAL"].includes(tag));
          typeFilters.forEach(typeFilter => {
            if (typeFilter === "REMOTE") {
              params.push(`mcp_type=${encodeURIComponent("url")}`);
            } else if (typeFilter === "LOCAL") {
              params.push(`mcp_type=${encodeURIComponent("file")}`);
            } else if (typeFilter === "EXTERNAL") {
              params.push(`mcp_type=${encodeURIComponent("module")}`);
            }
          });
          // Then process regular tags
          const regularTags = tags.filter(tag => !["REMOTE", "LOCAL", "EXTERNAL"].includes(tag));
          regularTags.forEach(tag => {
            if (tag && tag.trim()) {
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
        if (
          patchedPayload.mcp_type === "url" &&
          patchedPayload.vaultValue &&
          typeof patchedPayload.vaultValue === "string" &&
          patchedPayload.vaultValue.trim().length > 0
        ) {
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

  return useMemo(
    () => ({
      deleteServer,
      // getAllServers,
      getServersSearchByPageLimit,
      updateServer,
      getLiveToolDetails,
    }),
    [deleteServer, getServersSearchByPageLimit, updateServer, getLiveToolDetails]
  );
};
