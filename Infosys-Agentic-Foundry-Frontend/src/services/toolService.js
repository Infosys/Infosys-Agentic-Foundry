import axios from "axios";
import { BASE_URL } from "../constant"
import { getCsrfToken, getSessionId} from "../Hooks/useAxios";

let postMethod = "POST";
let getMethod = "GET";

export const getTools = async () => {
  try {
    const apiUrl = `${BASE_URL}/get-tools`;
    const response = await axios.request({
      method: getMethod,
      url: apiUrl,
      headers: {
        "Content-Type": "application/json",
      },
    });
    console.log("sttaus", response?.status);
    if (response?.status === 200) {
      return response?.data;
    } else {
      return null;
    }
  } catch (error) {
    return null;
  }
};

export const getToolsByPageLimit = async ({page, limit}) => {
  try {
    const apiUrl = `${BASE_URL}/get-tools-by-pages/${page}?limit=${limit}`;
    const response = await axios.request({
      method: getMethod,
      url: apiUrl,
      headers: {
        "Content-Type": "application/json",
      },
    });
    console.log(response)
    if (response?.status === 200) {
      return response?.data;
    } else {
      return null;
    }
  } catch (error) {
    return null;
  }
}

export const addTool = async (toolData) => {
  try {
    const apiUrl = `${BASE_URL}/add-tool`;
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

