import { useCallback, useMemo } from "react";
import { APIs } from "../constant";
import useFetch from "../Hooks/useAxios";

const extractErrorMessage = (error) => {
  const responseError = { message: null };
  if (error?.response?.data?.detail) {
    responseError.message = error.response.data.detail;
  }
  if (error?.response?.data?.message) {
    responseError.message = error.response.data.message;
  }
  return responseError.message ? responseError : null;
};

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
      const apiUrl = `${APIs.MCP_GET_ALL_SERVERS}`;
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
          // Add separate tag_names parameter for each tag
          tags.forEach((tag) => {
            if (tag && tag.trim()) {
              if (tag === "REMOTE") {
                params.push(`mcp_type=${encodeURIComponent("url")}`);
              } else if (tag === "LOCAL") {
                params.push(`mcp_type=${encodeURIComponent("file")}`);
              } else {
                params.push(`tag_names=${encodeURIComponent(tag)}`);
              }
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
        const apiUrl = `${APIs.MCP_UPDATE_SERVER}${toolId}`;
        const response = await putData(apiUrl, payload);
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
      getAllServers,
      getServersSearchByPageLimit,
      updateServer,
      getLiveToolDetails,
    }),
    [deleteServer, getAllServers, getServersSearchByPageLimit, updateServer, getLiveToolDetails]
  );
};
