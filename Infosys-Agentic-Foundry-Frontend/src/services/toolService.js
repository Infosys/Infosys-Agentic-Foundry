import { APIs } from "../constant";
import useFetch from "../Hooks/useAxios";

export const useToolsAgentsService = () => {
  const { fetchData, postData, putData, deleteData } = useFetch();

  const extractErrorMessage = (error) => {
    const responseError = { message: null };
    if (error.response?.data?.detail) {
      responseError.message = error.response.data.detail;
    }
    if (error.response?.data?.message) {
      responseError.message = error.response.data.message;
    }
    return responseError.message ? responseError : null;
  };

  const getToolsSearchByPageLimit = async ({ search, page, limit, tags }) => {
    try {
      const params = [];
      if (search && search.trim() && search.trim().length > 0) {
        params.push(`search_value=${encodeURIComponent(search)}`);
      }
      params.push(`page_number=${page}`);
      params.push(`page_size=${limit}`);
      if (tags && Array.isArray(tags) && tags.length > 0) {
        // Add separate tag_names parameter for each tag
        tags.forEach(tag => {
          if (tag && tag.trim()) {
            params.push(`tag_names=${encodeURIComponent(tag)}`);
          }
        });
      }
      const apiUrl = `${APIs.GET_TOOLS_SEARCH_PAGINATED}?${params.join('&')}`;
      const response = await fetchData(apiUrl);
      return response;
    } catch (error) {
      return extractErrorMessage(error);
    }
  };

  const getAgentsSearchByPageLimit = async (paramsObj) => {
    try {
      const params = [];
      // Only use agentic_application_type from input, ignore agent_type
      const agentType = paramsObj.agentic_application_type;
      const search = paramsObj.search_value || paramsObj.search;
      const page = paramsObj.page_number || paramsObj.page;
      const limit = paramsObj.page_size || paramsObj.limit;
      const tags = paramsObj.tags;
      
      // Only add agentic_application_type if valid
      if (agentType && agentType.trim() && agentType.trim().toLowerCase() !== "all") {
        params.push(`agentic_application_type=${encodeURIComponent(agentType)}`);
      }
      
      // Only add search_value if valid
      if (search && search.trim()) {
        params.push(`search_value=${encodeURIComponent(search)}`);
      }
      
      // Add page and limit parameters
      params.push(`page_number=${page}`);
      params.push(`page_size=${limit}`);
      
      // Add tag_names parameter if tags are provided
      if (tags && Array.isArray(tags) && tags.length > 0) {
        // Add separate tag_names parameter for each tag
        tags.forEach(tag => {
          if (tag && tag.trim()) {
            params.push(`tag_names=${encodeURIComponent(tag)}`);
          }
        });
      } else {
      }
      const apiUrl = `${APIs.GET_AGENTS_SEARCH_PAGINATED}?${params.join("&")}`;
      const response = await fetchData(apiUrl);
      return response;
    } catch (error) {
      return extractErrorMessage(error);
    }
  };

  const addTool = async (toolData, force_add) => {
    try {
      const apiUrl = force_add ? `${APIs.ADD_TOOLS}?force_add=true` : APIs.ADD_TOOLS;
      const response = await postData(apiUrl, toolData);
      return response;
    } catch (error) {
      return extractErrorMessage(error);
    }
  };

  const updateTools = async (toolData, toolId,force_add) => {
    try {
      const apiUrl = force_add ? `${APIs.UPDATE_TOOLS}${toolId}?force_add=true` : `${APIs.UPDATE_TOOLS}${toolId}`;
      const response = await putData(apiUrl, toolData);
      return response;
    } catch (error) {
      return extractErrorMessage(error);
    }
  };
  const deleteTool = async (toolData, toolId) => {
    try {
      const apiUrl = `${APIs.DELETE_TOOLS}${toolId}`;
      const response = await deleteData(apiUrl, toolData);
      return response;
    } catch (error) {
      return extractErrorMessage(error);
    }
  };

  const exportAgents = async (agentIds, userEmail) => {
    try {
      // Build URL with multiple agent_ids params and user email
      const params = agentIds.map((id) => `agent_ids=${encodeURIComponent(id)}`).join("&");
      const emailParam = userEmail ? `&user_email=${encodeURIComponent(userEmail)}` : "";
      const apiUrl = `${APIs.EXPORT_AGENTS}?${params}${emailParam}`;
      const response = await fetchData(apiUrl, { responseType: "blob" });
      if (response) {
        return response;
      } else {
        // Try to parse error from blob if possible
        const errorText = await response.data.text();
        let errorJson;
        try {
          errorJson = JSON.parse(errorText);
        } catch {
          errorJson = { detail: errorText };
        }
        const error = new Error(errorJson.detail || "Export failed!");
        error.response = { data: errorJson };
        throw error;
      }
    } catch (error) {
      // If error is an Axios error with a blob response, try to parse it
      if (error.response && error.response.data instanceof Blob) {
        try {
          const errorText = await error.response.data.text();
          let errorJson;
          try {
            errorJson = JSON.parse(errorText);
          } catch {
            errorJson = { detail: errorText };
          }
          error.response.data = errorJson;
        } catch {}
      }
      throw error;
    }
  };

  const checkToolEditable = async (tool, setShowForm, addMessage, setLoading) => {
    let response;
    const updatedTool = { ...tool, user_email_id: tool.created_by };
    if (setLoading) setLoading(true);
    response = await updateTools(updatedTool, tool.tool_id, true);
    if (setLoading) setLoading(false);
    if (response?.is_update) {
      setShowForm(true);
      return true;
    } else {
      if (response?.status && response?.response?.status !== 200) {
        addMessage(response?.response?.data?.detail, "error");
      } else {
        addMessage(response?.message, "error");
      }
      return false;
    }
  };

  const calculateDivs = (containerRef, cardWidth, cardHeight, flexGap) => {
    if (containerRef.current) {
      const containerWidth = containerRef.current.offsetWidth;
      const containerHeight = containerRef.current.offsetHeight;

      const maxDivsInRow = Math.ceil((containerWidth + flexGap) / (cardWidth + flexGap));

      const maxDivsInColumn = Math.ceil((containerHeight + flexGap) / (cardHeight + flexGap));

      const totalDivs = maxDivsInRow * maxDivsInColumn;
      return totalDivs;
    }
  };

  const addServer = async (serverData) => {
    try {
      const apiUrl = `${APIs.MCP_ADD_TOOLS}`;

      const normalizedTagIds = Array.isArray(serverData.tag_ids)
        ? serverData.tag_ids.map((id) => String(id))
        : [];
      const dataToSend = new FormData();
      dataToSend.append("tool_name", serverData.tool_name || serverData.model_name || "");
      dataToSend.append("tool_description", serverData.tool_description || "");
      dataToSend.append("mcp_type", serverData.mcp_type || "");
      dataToSend.append("created_by", serverData.created_by || serverData.user_email_id || "");
      dataToSend.append("user_email_id", serverData.user_email_id || serverData.created_by || "");
      dataToSend.append("mcp_module_name", serverData.mcp_module_name || "");
      dataToSend.append("mcp_url", serverData.mcp_url || "");
      dataToSend.append("code_content", serverData.code_content || serverData.code_snippet || "");
      dataToSend.append("code_snippet", serverData.code_snippet || serverData.code_content || "");
      try {
        if (serverData.mcp_file instanceof Blob && serverData.mcp_file.name) {
          dataToSend.append("mcp_file", serverData.mcp_file, serverData.mcp_file.name);
        } else if (serverData.mcp_file) {
          dataToSend.append("mcp_file", serverData.mcp_file);
        } else {
          dataToSend.append("mcp_file", "");
        }
      } catch (e) {
        dataToSend.append("mcp_file", "");
      }

      normalizedTagIds.forEach((id) => {
        dataToSend.append("tag_ids", id);
      });
      try {
        if (typeof window !== "undefined" && window && window.console && console.debug) {
          console.debug("[toolService.addServer] FormData preview (keys/vals):");
          for (const pair of dataToSend.entries()) {
            const k = pair[0];
            const v = pair[1];
            if (v instanceof File) console.debug(k, `${v.name} (file)`);
            else console.debug(k, v);
          }
        }
      } catch (e) {}

      const response = await postData(apiUrl, dataToSend);
      return response || null;
    } catch (error) {
      try {
        if (typeof window !== "undefined" && window && window.console && console.error) {
          console.error("[toolService.addServer] request failed:", error?.response?.data || error?.message || error);
        }
      } catch (e) {}
      return error?.response?.data || error;
    }
  };

  return {
    getToolsSearchByPageLimit,
    getAgentsSearchByPageLimit,
    addTool,
    updateTools,
    deleteTool,
    exportAgents,
    checkToolEditable,
    calculateDivs,
    addServer,
  };
};
