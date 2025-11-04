import { APIs } from "../constant";
import useFetch from "../Hooks/useAxios";
import { extractErrorMessage } from "../utils/errorUtils";
import Cookies from "js-cookie";

export const useToolsAgentsService = () => {
  const { fetchData, postData, putData, deleteData } = useFetch();

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
        tags.forEach((tag) => {
          if (tag && tag.trim()) {
            params.push(`tag_names=${encodeURIComponent(tag)}`);
          }
        });
      }
      const apiUrl = `${APIs.GET_TOOLS_SEARCH_PAGINATED}?${params.join("&")}`;
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
        tags.forEach((tag) => {
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

  const updateTools = async (toolData, toolId, force_add) => {
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

  const exportAgents = async (agentIds, userEmail, selectedFiles = [], configData = {}, exportAndDeploy) => {
    // Helper to attempt blob -> structured error object
    const tryParseBlobError = async (blob) => {
      if (!(blob instanceof Blob)) return null;
      // Heuristic: treat as potential JSON if content-type json OR size < 8KB
      const isLikelyJson = (blob.type && blob.type.includes("json")) || blob.size < 8192;
      if (!isLikelyJson) return null;
      try {
        const text = await blob.text();
        const trimmed = text.trim();
        if (trimmed.startsWith("{") || trimmed.startsWith("[")) {
          try {
            const parsed = JSON.parse(trimmed);
            if (parsed && (parsed.detail || parsed.message || parsed.error)) {
              return parsed;
            }
          } catch (_) {
            // fall through to wrap raw text
          }
        }
        // If plain text treat as detail
        if (trimmed.length > 0 && trimmed.length < 2000) {
          return { detail: trimmed };
        }
      } catch (_) {
        // ignore parse issues
      }
      return null;
    };
    try {
      // Build URL with multiple agent_ids params and user email
      const params = agentIds.map((id) => `agent_ids=${encodeURIComponent(id)}`).join("&");
      const emailParam = userEmail ? `&user_email=${encodeURIComponent(userEmail)}` : "";

      // Process selectedFiles to exclude __files__ key and extract only filenames (no paths)
      const processedFiles = selectedFiles
        .filter((file) => file !== "__files__")
        .map((file) => (typeof file === "string" && file.includes("/") ? file.split("/").pop() : file))
        .filter((file) => file && file.trim());

      const fileNamesParam = processedFiles.length > 0 ? `&${processedFiles.map((file) => `file_names=${encodeURIComponent(file)}`).join("&")}` : "";

      // Convert configData to URL-encoded format
      const configParams = Object.entries(configData)
        .filter(([_, value]) => value !== "" && value !== null && value !== undefined)
        .map(([key, value]) => `${encodeURIComponent(key)}=${encodeURIComponent(value)}`)
        .join("&");

      // Add export_and_deploy as a query param if provided as argument
      let exportAndDeployParam = "";
      if (typeof exportAndDeploy !== "undefined") {
        exportAndDeployParam = `&export_and_deploy=${encodeURIComponent(exportAndDeploy)}`;
      }

      const apiUrl = `${APIs.EXPORT_AGENTS}?${params}${emailParam}${fileNamesParam}${exportAndDeployParam}`;
      // Send URL-encoded data in POST request body
      const response = await postData(apiUrl, configParams, {
        responseType: "blob", // Ensure the response is treated as a Blob
      });

      return response; // Return the Blob response for further handling
    } catch (error) {
      // Attempt to unwrap blob based error
      try {
        const blob = error?.response?.data;
        const parsed = await tryParseBlobError(blob);
        if (parsed) {
          const normalized = {
            detail: parsed.detail || parsed.message || parsed.error || JSON.stringify(parsed),
          };
          // Mutate existing error to keep original context
          if (!error.response) error.response = { data: normalized };
          else error.response.data = normalized;
          error.message = normalized.detail;
        }
      } catch (parseError) {
        console.error("Failed to parse error response:", parseError);
      }

      console.error("Export failed with error:", error);
      throw error;
    }
  };

  const checkToolEditable = async (tool, setShowForm, addMessage, setLoading) => {
    let response;
    const userEmailId = Cookies.get("email") || "Guest";
    const role = Cookies.get("role");
    const isAdmin = role && role?.toUpperCase() === "ADMIN";
    const updatedTool = { ...tool, user_email_id: userEmailId, is_admin:isAdmin };
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
    // SAFE FIX: Always return a positive integer. Previously returned undefined when ref not ready (e.g. during resize)
    const el = containerRef && containerRef.current ? containerRef.current : null;
    let containerWidth;
    let containerHeight;
    if (el) {
      containerWidth = el.offsetWidth || cardWidth;
      containerHeight = el.offsetHeight || cardHeight;
    } else {
      // Fallback to viewport-based approximation to avoid undefined during transient layout states
      if (typeof window !== "undefined") {
        containerWidth = Math.max(cardWidth, (window.innerWidth || cardWidth) - 64); // subtract rough padding
        containerHeight = Math.max(cardHeight, (window.innerHeight || cardHeight) - 240); // subtract header/toolbars
      } else {
        containerWidth = cardWidth;
        containerHeight = cardHeight;
      }
    }

    const maxDivsInRow = Math.max(1, Math.ceil((containerWidth + flexGap) / (cardWidth + flexGap)));
    const maxDivsInColumn = Math.max(1, Math.ceil((containerHeight + flexGap) / (cardHeight + flexGap)));
    const totalDivs = Math.max(1, maxDivsInRow * maxDivsInColumn);
    return totalDivs;
  };

  const addServer = async (serverData) => {
    try {
      console.debug("[addServer] Step 1: Received serverData:", serverData);
      // Extra: Log header value directly
      console.debug("[addServer] Step 1.1: serverData.headers:", serverData.headers);
      const apiUrl = `${APIs.MCP_ADD_TOOLS}`;

      const normalizedTagIds = Array.isArray(serverData.tag_ids) ? serverData.tag_ids.map((id) => String(id)) : [];
      const dataToSend = new FormData();
      console.debug("[addServer] Step 2: Created FormData instance");
      dataToSend.append("tool_name", serverData.tool_name || serverData.model_name || "");
      dataToSend.append("tool_description", serverData.tool_description || "");
      dataToSend.append("mcp_type", serverData.mcp_type || "");
      dataToSend.append("created_by", serverData.created_by || serverData.user_email_id || "");
      dataToSend.append("user_email_id", serverData.user_email_id || serverData.created_by || "");
      dataToSend.append("mcp_module_name", serverData.mcp_module_name || "");
      dataToSend.append("mcp_url", serverData.mcp_url || "");
      dataToSend.append("code_content", serverData.code_content || serverData.code_snippet || "");
      dataToSend.append("code_snippet", serverData.code_snippet || serverData.code_content || "");
      if (serverData.command) {
        dataToSend.append("command", serverData.command);
      }
      if (serverData.externalArgs) {
        dataToSend.append("externalArgs", serverData.externalArgs);
      }
      // PATCH: Add headers to FormData if present (from mcp_config.headers or top-level headers)
      let headersObj = null;
      if (serverData.headers && typeof serverData.headers === "object" && Object.keys(serverData.headers).length > 0) {
        headersObj = serverData.headers;
      } else if (
        serverData.mcp_config &&
        serverData.mcp_config.headers &&
        typeof serverData.mcp_config.headers === "object" &&
        Object.keys(serverData.mcp_config.headers).length > 0
      ) {
        headersObj = serverData.mcp_config.headers;
      }
      if (headersObj) {
        dataToSend.append("headers", JSON.stringify(headersObj));
      }
      // DEBUG: Print payload before hitting endpoint
      if (typeof window !== "undefined" && window && window.console && console.debug) {
        console.debug("[addServer] Step 4: Final FormData payload before POST:");
        for (const pair of dataToSend.entries()) {
          const k = pair[0];
          const v = pair[1];
          if (v instanceof File) console.debug(k, `${v.name} (file)`);
          else console.debug(k, v);
        }
      }
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
          console.debug("[addServer] Step 6: FormData preview (keys/vals):");
          for (const pair of dataToSend.entries()) {
            const k = pair[0];
            const v = pair[1];
            if (v instanceof File) console.debug(k, `${v.name} (file)`);
            else console.debug(k, v);
          }
        }
      } catch (e) {}
      // Extra: Log FormData as object for inspection
      if (typeof window !== "undefined" && window && window.console && console.debug) {
        const formObj = {};
        for (const pair of dataToSend.entries()) {
          formObj[pair[0]] = pair[1];
        }
        console.debug("[addServer] Step 7.1: FormData as object:", formObj);
      }
      const response = await postData(apiUrl, dataToSend);
      console.debug("[addServer] Step 8: Response from backend:", response);
      return response || null;
    } catch (error) {
      try {
        if (typeof window !== "undefined" && window && window.console && console.error) {
          console.error("[addServer] Step 9: request failed:", error?.response?.data || error?.message || error);
        }
      } catch (e) {}
      return error?.response?.data || error;
    }
  };

  // Test server tool (play button) - send JSON, not FormData
  const testServerTool = async (toolId, payload) => {
    try {
      const apiUrl = `/tools/mcp/test/${toolId}`;
      // Use postData with JSON payload
      const response = await postData(apiUrl, payload);
      return response;
    } catch (error) {
      return extractErrorMessage(error);
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
    testServerTool, // <-- add new function to export
  };
};
