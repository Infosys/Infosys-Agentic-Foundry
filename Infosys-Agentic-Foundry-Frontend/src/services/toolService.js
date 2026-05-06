import { APIs } from "../constant";
import useFetch from "../Hooks/useAxios";
import { extractErrorMessage } from "../utils/errorUtils";
import { getRoleFromToken, getEmailFromToken } from "../utils/jwtUtils";

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

  // Fetch all validator tools (no pagination yet). Backend: APIs.GET_VALIDATOR_TOOLS
  const getValidatorTools = async () => {
    try {
      const apiUrl = APIs.GET_VALIDATOR_TOOLS;
      const response = await fetchData(apiUrl);
      return response;
    } catch (error) {
      return extractErrorMessage(error);
    }
  };

  // Get tool details by tool_id
  const getToolById = async (toolId) => {
    try {
      if (!toolId) throw new Error("toolId is required");
      const response = await fetchData(APIs.GET_TOOLS_BY_ID + toolId);
      return response;
    } catch (error) {
      return extractErrorMessage(error);
    }
  };

  // ============ Tool Version Management Services ============

  // Save a code version
  const saveToolVersion = async (payload) => {
    try {
      const response = await postData(APIs.TOOL_VERSION_SAVE, payload);
      return response;
    } catch (error) {
      return extractErrorMessage(error);
    }
  };

  // List all code versions for a session
  const getToolVersions = async (sessionId, includeCode = false) => {
    try {
      if (!sessionId) throw new Error("session_id is required");
      const response = await fetchData(
        `${APIs.TOOL_VERSION_LIST}${encodeURIComponent(sessionId)}?include_code=${includeCode}`
      );
      return response;
    } catch (error) {
      return extractErrorMessage(error);
    }
  };

  // Get a specific version by version number
  const getToolVersionByNumber = async (sessionId, versionNumber) => {
    try {
      if (!sessionId || versionNumber == null) throw new Error("session_id and version_number are required");
      const response = await fetchData(
        `${APIs.TOOL_VERSION_GET}${encodeURIComponent(sessionId)}/${encodeURIComponent(versionNumber)}`
      );
      return response;
    } catch (error) {
      return extractErrorMessage(error);
    }
  };

  // Get the current active version for a session
  const getCurrentToolVersion = async (sessionId) => {
    try {
      if (!sessionId) throw new Error("session_id is required");
      const response = await fetchData(
        `${APIs.TOOL_VERSION_CURRENT}${encodeURIComponent(sessionId)}`
      );
      return response;
    } catch (error) {
      return extractErrorMessage(error);
    }
  };

  // Switch to a different code version
  const switchToolVersion = async (payload) => {
    try {
      const response = await postData(APIs.TOOL_VERSION_SWITCH, payload);
      return response;
    } catch (error) {
      return extractErrorMessage(error);
    }
  };

  // Update a version label
  const updateToolVersionLabel = async (payload) => {
    try {
      const response = await putData(APIs.TOOL_VERSION_LABEL, payload);
      return response;
    } catch (error) {
      return extractErrorMessage(error);
    }
  };

  // Delete a specific code version
  const deleteToolVersion = async (payload) => {
    try {
      const response = await deleteData(APIs.TOOL_VERSION_DELETE, payload);
      return response;
    } catch (error) {
      return extractErrorMessage(error);
    }
  };

  // Clear all versions for a session
  const clearToolVersions = async (sessionId) => {
    try {
      if (!sessionId) throw new Error("session_id is required");
      const response = await deleteData(
        `${APIs.TOOL_VERSION_CLEAR}${encodeURIComponent(sessionId)}`
      );
      return response;
    } catch (error) {
      return extractErrorMessage(error);
    }
  };

  // Get version count for a session
  const getToolVersionCount = async (sessionId) => {
    try {
      if (!sessionId) throw new Error("session_id is required");
      const response = await fetchData(
        `${APIs.TOOL_VERSION_COUNT}${encodeURIComponent(sessionId)}`
      );
      return response;
    } catch (error) {
      return extractErrorMessage(error);
    }
  };

  // Get conversation history for a session
  const getToolConversationHistory = async (sessionId) => {
    try {
      if (!sessionId) throw new Error("session_id is required");
      const response = await fetchData(
        `${APIs.TOOL_CONVERSATION_HISTORY}${encodeURIComponent(sessionId)}`
      );
      return response;
    } catch (error) {
      return extractErrorMessage(error);
    }
  };

  // Get latest code for a session
  const getLatestCode = async (sessionId) => {
    try {
      if (!sessionId) throw new Error("session_id is required");
      const response = await fetchData(
        `${APIs.TOOL_CONVERSATION_LATEST_CODE}${encodeURIComponent(sessionId)}`
      );
      return response;
    } catch (error) {
      return extractErrorMessage(error);
    }
  };

  // Clear conversation history for a session
  const clearConversationHistory = async (sessionId) => {
    try {
      if (!sessionId) throw new Error("session_id is required");
      const response = await deleteData(
        `${APIs.TOOL_CONVERSATION_CLEAR}${encodeURIComponent(sessionId)}`
      );
      return response;
    } catch (error) {
      return extractErrorMessage(error);
    }
  };

  const getToolsAndValidatorsPaginated = async ({ search, page, limit, tags, created_by, show_tools, show_validators }) => {
    try {
      const params = [];
      if (search && search.trim() && search.trim().length > 0) {
        params.push(`search_value=${encodeURIComponent(search)}`);
      }
      params.push(`page_number=${page}`);
      params.push(`page_size=${limit}`);
      if (tags && Array.isArray(tags) && tags.length > 0) {
        tags.forEach((tag) => {
          if (tag && tag.trim()) {
            params.push(`tag_names=${encodeURIComponent(tag)}`);
          }
        });
      }
      // Add show_tools and show_validators parameters for type filtering
      if (typeof show_tools === "boolean") {
        params.push(`show_tools=${show_tools}`);
      }
      if (typeof show_validators === "boolean") {
        params.push(`show_validators=${show_validators}`);
      }
      if (created_by && created_by.trim()) {
        params.push(`created_by=${encodeURIComponent(created_by)}`);
      }
      const apiUrl = `${APIs.GET_TOOLS_AND_VALIDATORS_SEARCH_PAGINATED}?${params.join("&")}`;
      const response = await fetchData(apiUrl);
      return response;
    } catch (error) {
      return extractErrorMessage(error);
    }
  };

  // Deprecated: getValidatorTools. Use getToolsAndValidatorsPaginated instead.

  const getAgentsSearchByPageLimit = async (paramsObj) => {
    try {
      const params = [];
      // Only use agentic_application_type from input, ignore agent_type
      const agentType = paramsObj.agentic_application_type;
      const search = paramsObj.search_value || paramsObj.search;
      const page = paramsObj.page_number || paramsObj.page;
      const limit = paramsObj.page_size || paramsObj.limit;
      const tags = paramsObj.tags;
      const created_by = paramsObj.created_by;

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
      }
      // Add created_by parameter for "Me" filter
      if (created_by && created_by.trim()) {
        params.push(`created_by=${encodeURIComponent(created_by)}`);
      }
      const apiUrl = `${APIs.GET_AGENTS_SEARCH_PAGINATED}?${params.join("&")}`;
      const response = await fetchData(apiUrl);
      return response;
    } catch (error) {
      return extractErrorMessage(error);
    }
  };

  // /tools/add -> JSON body with all fields
  // /tools/add-message-queue -> form-urlencoded with is_validator as query param,
  //   add_tool_request (JSON string), is_public as form fields
  const addTool = async (toolData, useMessageQueue = false) => {
    try {
      if (useMessageQueue) {
        // Build query param for is_validator
        const isValidator = toolData.is_validator ?? false;
        const apiUrl = `${APIs.ADD_TOOLS_MESSAGE_QUEUE}?is_validator=${isValidator}`;

        // Build the add_tool_request JSON object (excludes is_public)
        const { is_public, ...requestBody } = toolData;
        const addToolRequestJson = JSON.stringify(requestBody);

        // Build form-urlencoded body
        const formParams = new URLSearchParams();
        formParams.append("add_tool_request", addToolRequestJson);
        formParams.append("is_public", String(is_public ?? false));

        const response = await postData(apiUrl, formParams, {
          headers: { "Content-Type": "application/x-www-form-urlencoded" },
        });
        return response;
      } else {
        // /tools/add -> plain JSON body
        const apiUrl = APIs.ADD_TOOLS;
        const response = await postData(apiUrl, toolData);
        return response;
      }
    } catch (error) {
      // Preserve the full response body (e.g. error_on_screen, warnings, is_created)
      // so callers can detect verification warnings and show the warning modal
      if (error?.response?.data && typeof error.response.data === "object") {
        return error.response.data;
      }
      return extractErrorMessage(error);
    }
  };

  const updateTools = async (toolData, toolId, force_add) => {
    try {
      const params = [];
      if (force_add) params.push("force_add=true");
      const queryString = params.length > 0 ? `?${params.join("&")}` : "";
      const apiUrl = `${APIs.UPDATE_TOOLS}${toolId}${queryString}`;
      const response = await putData(apiUrl, toolData);
      return response;
    } catch (error) {
      return extractErrorMessage(error);
    }
  };
  /**
   * Delete tool(s) - uses DELETE_TOOLS endpoint
   * For single tool: sends tool_id as path param with version in body
   * For multiple tools: sends tool_ids array in body (bulk delete)
   * @param {Object} toolData - Payload data (user_email_id, is_admin, version)
   * @param {string|string[]} toolIdOrIds - Single toolId or array of toolIds
   */
  const deleteTool = async (toolData, toolIdOrIds) => {
    try {
      const ids = Array.isArray(toolIdOrIds) ? toolIdOrIds : [toolIdOrIds];
      const apiUrl = APIs.DELETE_TOOLS;
      const payload = {
        user_email_id: toolData.user_email_id,
        is_admin: toolData.is_admin,
        tool_ids: ids,
        version: "version" in toolData ? toolData.version : null,
      };
      const response = await deleteData(apiUrl, payload);
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

  const importToolsPreview = async (zipFile) => {
    try {
      const apiUrl = APIs.IMPORT_TOOLS_PREVIEW;
      const formData = new FormData();
      formData.append("zip_file", zipFile);
      const response = await postData(apiUrl, formData);
      return response;
    } catch (error) {
      return extractErrorMessage(error);
    }
  };

  const importTools = async (zipFile, modelName, createdBy, conflictResolution, nameOverrides = null) => {
    try {
      const apiUrl = APIs.IMPORT_TOOLS;
      const formData = new FormData();
      formData.append("zip_file", zipFile);
      formData.append("model_name", modelName || "");
      formData.append("created_by", createdBy || "");
      if (conflictResolution) {
        formData.append("conflict_resolution", conflictResolution);
      }
      if (nameOverrides) {
        formData.append("name_overrides", nameOverrides);
      }
      const response = await postData(apiUrl, formData);
      return response;
    } catch (error) {
      return extractErrorMessage(error);
    }
  };

  const exportTools = async (toolIds) => {
    try {
      const apiUrl = APIs.EXPORT_TOOLS;
      const response = await postData(apiUrl, { tool_ids: toolIds }, {
        responseType: "blob",
      });
      return response;
    } catch (error) {
      // Attempt to parse blob error for structured message
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
  };

  const checkToolEditable = async (tool, setShowForm, addMessage, setLoading) => {
    const userEmailId = getEmailFromToken() || "Guest";
    const role = getRoleFromToken();
    const isAdmin = role && role?.toLowerCase() === "admin";
    const updatedTool = { ...tool, user_email_id: userEmailId, is_admin: isAdmin };
    if (setLoading) setLoading(true);
    const response = await updateTools(updatedTool, tool.tool_id, true);
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
      // Backend expects is_validator as query param (mirror /tools/add pattern)
      const apiUrl = APIs.MCP_ADD_TOOLS;

      const normalizedTagIds = Array.isArray(serverData.tag_ids) ? serverData.tag_ids.map((id) => String(id)) : [];
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
      if (serverData.mcp_command) {
        dataToSend.append("mcp_command", serverData.mcp_command);
      } else if (serverData.command) {
        dataToSend.append("mcp_command", serverData.command);
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
      // Add is_public field
      dataToSend.append("is_public", String(serverData.is_public ?? false));
      const response = await postData(apiUrl, dataToSend);
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
      const apiUrl = `${APIs.MCP_TEST_TOOL}${toolId}`;
      // Use postData with JSON payload
      const response = await postData(apiUrl, payload);
      return response;
    } catch (error) {
      return extractErrorMessage(error);
    }
  };


  /**
   * Delete agent(s) - always use array of agent_ids and DELETE_AGENTS endpoint (no agentId in URL)
   * @param {Object} agentData - Additional payload data (e.g., user_email_id, is_admin)
   * @param {string|string[]} agentIdOrIds - Single agentId or array of agentIds
   */
  const deleteAgent = async (agentData, agentIdOrIds) => {
    try {
      const apiUrl = APIs.DELETE_AGENTS;
      // Accept single ID or array, always send as array
      const ids = Array.isArray(agentIdOrIds) ? agentIdOrIds : [agentIdOrIds];
      const payload = { ...agentData, agent_ids: ids };
      const response = await deleteData(apiUrl, payload);
      return response;
    } catch (error) {
      return extractErrorMessage(error);
    }
  };

  return {
    getToolsSearchByPageLimit,
    getToolsAndValidatorsPaginated,
    getValidatorTools,
    getAgentsSearchByPageLimit,
    addTool,
    updateTools,
    deleteTool,
    deleteAgent,
    exportAgents,
    exportTools,
    importTools,
    importToolsPreview,
    checkToolEditable,
    calculateDivs,
    addServer,
    testServerTool,
    getToolById,
    // Version management
    saveToolVersion,
    getToolVersions,
    getToolVersionByNumber,
    getCurrentToolVersion,
    switchToolVersion,
    updateToolVersionLabel,
    deleteToolVersion,
    clearToolVersions,
    getToolVersionCount,
    getToolConversationHistory,
    getLatestCode,
    clearConversationHistory,
  };
};
