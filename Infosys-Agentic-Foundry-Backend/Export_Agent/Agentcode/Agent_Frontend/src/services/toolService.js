import axios from "axios";
import { BASE_URL ,APIs} from "../constant"
import { getCsrfToken, getSessionId} from "../Hooks/useAxios";
import Cookies from "js-cookie";
let postMethod = "POST";
let getMethod = "GET";

export const getToolsSearchByPageLimit = async ({search, page, limit}) => {
  try {
    let apiUrl;
    if (search && search.trim() && search.trim().length > 0) {
      apiUrl = `${BASE_URL}/get-tools-search-paginated/?search_value=${encodeURIComponent(search)}&page_number=${page}&page_size=${limit}`;
    } else {
      apiUrl = `${BASE_URL}/get-tools-search-paginated/?page_number=${page}&page_size=${limit}`;
    }
    const response = await axios.request({
      method: getMethod,
      url: apiUrl,
      headers: {
        "Content-Type": "application/json",
        "csrf-token": getCsrfToken(),
        "session-id": getSessionId(), // added for CSRF token implementation
      },
    });
    if (response?.status === 200) {
      return response?.data;
    } else {
      return null;
    }
  } catch (error) {
    return null;
  }
}

export const getAgentsSearchByPageLimit = async ({search, page, limit, agent_type}) => {
  try {
    let apiUrl;
    // If both search and agent_type are empty, use default API URL
    if ((!search || !search.trim()) && (!agent_type || !agent_type.trim())) {
      apiUrl = `${BASE_URL}/get-agents-search-paginated/?page_number=${page}&page_size=${limit}`;
    } else if (agent_type && agent_type.trim() && agent_type.trim().length > 0) {
      apiUrl = `${BASE_URL}/get-agents-search-paginated/?agentic_application_type=${encodeURIComponent(agent_type)}&page_number=${page}&page_size=${limit}`;
    } else if (search && search.trim() && search.trim().length > 0) {
      apiUrl = `${BASE_URL}/get-agents-search-paginated/?search_value=${encodeURIComponent(search)}&page_number=${page}&page_size=${limit}`;
    }
    const response = await axios.request({
      method: getMethod,
      url: apiUrl,
      headers: {
        "Content-Type": "application/json",
        "csrf-token": getCsrfToken(),
        "session-id": getSessionId(), // added for CSRF token implementation
      },
    });
    if (response?.status === 200) {
      return response?.data;
    } else {
      return null;
    }
  } catch (error) {
    return null;
  }
}

export const addTool = async (toolData,force_add) => {
  try {
    const apiUrl = force_add ? `${BASE_URL}/add-tool?force_add=true` : `${BASE_URL}/add-tool`;
    const response = await axios.request({
      method: postMethod,
      url: apiUrl,
      data: toolData,
      headers: {
        "Content-Type": "application/json",
        "csrf-token": getCsrfToken(),
        "session-id": getSessionId(), // added for CSRF token implementation
      },
    });

    if (response?.status === 200) {
      return response?.data;
    } else {
      return null;
    }
  } catch (error) {
    return null;
  }
};

export const updateTools = async (toolData, toolId) => {
  try {
    const apiUrl = `${BASE_URL}/update-tool/${toolId}`;
    const response = await axios.request({
      method: "PUT",
      url: apiUrl,
      data: toolData,
      headers: {
        "Content-Type": "application/json",
        "csrf-token": getCsrfToken(),
        "session-id": getSessionId(), // added for CSRF token implementation
      },
    });

    if (response?.status === 200) {
      return response?.data;
    } else {
      return response;
    }
  } catch (error) {
    return error;
  }
};

export const RecycleTools = async (toolData, toolId,selectedType) => {
  try {
    const apiUrl = `${BASE_URL}${APIs.RESTORE_TOOL}${selectedType}?item_id=${toolId}&user_email_id=${encodeURIComponent(
            Cookies?.get("email")
          )}`;
    const response = await axios.request({
      method: "POST",
      url: apiUrl,
      data: toolData,
      headers: {
        "Content-Type": "application/json",
        "csrf-token": getCsrfToken(),
        "session-id": getSessionId(), // added for CSRF token implementation
      },
    });

    if (response?.status === 200) {
      return response?.data;
    } else {
      return response;
    }
  } catch (error) {
    return error;
  }
};

export const deletedTools = async (toolData, toolId,selectedType) => {
  try {
    const apiUrl = `${BASE_URL}${APIs.DELETE_TOOL}${selectedType}?item_id=${toolId}&user_email_id=${encodeURIComponent(
            Cookies?.get("email")
          )}`;          
    const response = await axios.request({
      method: "DELETE",
      url: apiUrl,
      // data: toolData,
      headers: {
        "Content-Type": "application/json",
        "csrf-token": getCsrfToken(),
        "session-id": getSessionId(), // added for CSRF token implementation
      },
    });

    if (response?.status === 200) {
      return response?.data;
    } else {
      return response;
    }
  } catch (error) {
    return error;
  }
};
export const deleteTool = async (toolData, toolId) => {
  try {
    const apiUrl = `${BASE_URL}/delete-tool/${toolId}`;
    const response = await axios.request({
      method: "DELETE",
      url: apiUrl,
      data: toolData,
      headers: {
        "Content-Type": "application/json",
        "csrf-token": getCsrfToken(),
        "session-id": getSessionId(), // added for CSRF token implementation
      },
    });

    if (response?.status === 200) {
      return response?.data;
    } else {
      return null;
    }
  } catch (error) {
    return null;
  }
};

export const exportAgents = async (agentIds, userEmail) => {
  try {
    // Build URL with multiple agent_ids params and user email
    const params = agentIds.map(id => `agent_ids=${encodeURIComponent(id)}`).join('&');
    const emailParam = userEmail ? `&user_email=${encodeURIComponent(userEmail)}` : '';
    const apiUrl = `${BASE_URL}/export-agents?${params}${emailParam}`;
    const response = await axios.request({
      method: "GET",
      url: apiUrl,
      headers: {
        "Content-Type": "application/json",
        "csrf-token": getCsrfToken(),
        "session-id": getSessionId(),
      },
      responseType: 'blob',
    });
    if (response?.status === 200) {
      return response.data;
    } else {
      // Try to parse error from blob if possible
      const errorText = await response.data.text();
      let errorJson;
      try {
        errorJson = JSON.parse(errorText);
      } catch {
        errorJson = { detail: errorText };
      }
      const error = new Error(errorJson.detail || 'Export failed!');
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