import { APIs } from "../constant";
import useFetch from "../Hooks/useAxios";
import { useSSE } from "../context/SSEContext";
import React from "react";
import Cookies from "js-cookie";

export const useChatServices = () => {
  const { fetchData, postData, deleteData } = useFetch();
  const { sseMessages, connectionStatus } = useSSE();

  // Persist callback across renders using ref so parent can register once
  const sseMessageCallbackRef = React.useRef(null);

  const setSseMessageCallback = (callback) => {
    // Allow null to clear
    sseMessageCallbackRef.current = callback;
  };

  // Listen for new SSE messages and pass to callback + log
  React.useEffect(() => {
    if (sseMessages && sseMessages.length > 0) {
      const lastMsg = sseMessages[sseMessages.length - 1];
      if (sseMessageCallbackRef.current) {
        try {
          sseMessageCallbackRef.current(lastMsg);
        } catch (err) {
        }
      }
    }
  }, [sseMessages]);

  const resetChat = async (data) => {
    try {
      const apiUrl = APIs.CLEAR_CHAT_HISTORY;
      const response = await deleteData(apiUrl, data);

      if (response) {
        return response;
      } else {
        return null;
      }
    } catch (error) {
      return null;
    }
  };

  const getChatQueryResponse = async (chatData, url) => {
    try {
      const response = await postData(url, chatData);

      if (response) {
        return response;
      } else {
        return null;
      }
    } catch (error) {
      return null;
    }
  };

  // Remove getDebugStepsAsSSE, SSE is handled globally

  const getChatHistory = async (chatData) => {
    try {
      const apiUrl = APIs.GET_CHAT_HISTORY;
      const response = await postData(apiUrl, chatData);

      if (response) {
        return response;
      } else {
        return null;
      }
    } catch (error) {
      return null;
    }
  };

  const fetchFeedback = async (data, feedback) => {
    try {
      const apiUrl = `${APIs.GET_FEEDBACK_RESPONSE}${feedback}`;
      const response = await postData(apiUrl, data);
      if (response) {
        return response;
      } else {
        return null;
      }
    } catch (error) {
      return null;
    }
  };

  const fetchOldChats = async (data) => {
    try {
      const apiUrl = APIs.GET_OLD_CONVERSATIONS;
      const response = await postData(apiUrl, data);
      if (response) {
        return response;
      } else {
        return null;
      }
    } catch (error) {
      return null;
    }
  };

  const fetchNewChats = async (userEmail) => {
    try {
      const apiUrl = `${APIs.GET_NEW_SESSION_ID}`;
      const response = await fetchData(apiUrl);
      if (response) {
        Cookies.set("user_session", response, { path: "/" });
        return response;
      } else {
        return null;
      }
    } catch (error) {
      return null;
    }
  };

  const getQuerySuggestions = async (data) => {
    try {
      const apiUrl = `${APIs.SUGGESTIONS}?agentic_application_id=${data.agentic_application_id}&user_email=${data.user_email}`;
      const response = await fetchData(apiUrl);
      if (response) {
        return response;
      } else {
        return null;
      }
    } catch (error) {
      return null;
    }
  };

  // Store memory example (positive/negative label examples)
  const storeMemoryExample = async (data) => {
    try {
      const apiUrl = APIs.MEMORY_STORE_EXAMPLE;
      const response = await postData(apiUrl, data);
      if (response) {
        return response;
      } else {
        return null;
      }
    } catch (error) {
      return null;
    }
  };

  return {
    resetChat,
    getChatQueryResponse,
    getChatHistory,
    fetchFeedback,
    fetchOldChats,
    fetchNewChats,
    getQuerySuggestions,
    setSseMessageCallback,
    sseMessages,
    connectionStatus,
    storeMemoryExample,
  };
};
