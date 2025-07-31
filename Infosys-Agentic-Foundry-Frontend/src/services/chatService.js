import axios from "axios";
import { APIs, BASE_URL } from "../constant";
import { getCsrfToken, getSessionId } from "../Hooks/useAxios";


let postMethod = "POST";
let getMethod = "GET";

export const resetChat = async (data) => {
  try {
    const apiUrl = `${BASE_URL}/react-agent${APIs.CLEAR_CHAT_HISTORY}`;
    const response = await axios.request({
      method: "DELETE",
      url: apiUrl,
      data: data,
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

export const getChatQueryResponse = async (chatData, url) => {
  try {
    const apiUrl = `${BASE_URL}${url}`;
    const response = await axios.request({
      method: postMethod,
      url: apiUrl,
      data: chatData,
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

export const getChatHistory = async (chatData) => {
  try {
    const apiUrl = `${BASE_URL}/react-agent${APIs.GET_CHAT_HISTORY}`;
    const response = await axios.request({
      method: postMethod,
      url: apiUrl,
      data: chatData,
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

export const fetchFeedback = async (data, feedback) => {
  try {
    const apiUrl = `${BASE_URL}/react-agent/get-feedback-response/${feedback}`;
    const response = await axios.request({
      method: postMethod,
      url: apiUrl,
      data: data,
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

export const fetchOldChats = async (data) => {
  try {
    const apiUrl = `${BASE_URL}${APIs.FETCH_OLD_CHATS}`;
    const response = await axios.request({
      method: postMethod,
      url: apiUrl,
      data: data,
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

export const fetchNewChats = async (userEmail) => {
  try {
    const apiUrl = `${BASE_URL}${APIs.NEW_CHAT}${userEmail}`;
    const response = await axios.request({
      method: getMethod,
      url: apiUrl,
      headers: {
        "Content-Type": "application/json",
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
