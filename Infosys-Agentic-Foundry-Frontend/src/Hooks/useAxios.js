import { useState, useCallback } from "react";
import { APIs, BASE_URL } from "../constant";
import Cookies from "js-cookie";
import axios from "axios";

let sessionId = null;

let postMethod = "POST";
let getMethod = "GET";
let deleteMethod = "DELETE";
let putMethod = "PUT";

// JWT token storage
let jwtToken = null;

// Function to set the JWT token (to be called after login/signup)
export const setJwtToken = (token) => {
  if (token) {
    jwtToken = token;
    Cookies.set("jwt-token", token); // Store in localStorage for persistence
    return true;
  }
  return false;
};

// Function to get the current JWT token
export const getJwtToken = () => {
  if (!jwtToken) {
    jwtToken = Cookies.get("jwt-token");
  }
  return jwtToken;
};

// Helper to add Authorization header if JWT token is available
const addConfigHeaders = (headers = {}) => {
  const token = getJwtToken();
  if (token) {
    return {
      ...headers,
      Authorization: `Bearer ${token}`,
    };
  }
  return headers;
};

// Function to get the current session ID
export const getSessionId = () => {
  if (!sessionId) {
    sessionId = Cookies.get("user_session");
  }
  return sessionId;
};

const REQUEST_TIMEOUT_MS = Number(process.env.REACT_APP_API_TIMEOUT ?? 20 * 60 * 1000); // If not declared in ENV , it will be 20 minutes

const defaultConfig = {
  headers: {
    accept: "application/json",
  },
  timeout: REQUEST_TIMEOUT_MS,
};

const useFetch = () => {
  const [loading, setLoading] = useState({});
  const [error, setError] = useState({});

  const fetchData = useCallback(async (url, config = {}) => {
    setLoading((prevLoading) => ({ ...prevLoading, fetch: true }));
    try {
      // Add token to headers for POST requests
      const headers = addConfigHeaders({
        ...defaultConfig.headers,
        ...config.headers,
      });

      const response = await axios.request({
        url: BASE_URL + url,
        method: getMethod,
        ...defaultConfig,
        ...config,
        headers,
      });
      const data = response.data;

      // Setting JWT token
      if (url.includes(APIs.GUEST_LOGIN) && data?.token) {
        setJwtToken(data.token);
      }

      setError((prevError) => ({ ...prevError, fetch: null }));
      return data;
    } catch (err) {
      setError((prevError) => ({ ...prevError, fetch: err }));
      throw err;
    } finally {
      setLoading((prevLoading) => ({ ...prevLoading, fetch: false }));
    }
  }, []);

  const postData = useCallback(async (url, postData, config = {}) => {
    setLoading((prevLoading) => ({ ...prevLoading, post: true }));
    try {
      let contentType = "application/json";
      let dataToSend = postData;
      if (postData instanceof FormData) {
        contentType = undefined;
      } else {
        dataToSend = JSON.stringify(postData);
      }
      const headers = addConfigHeaders({
        ...defaultConfig.headers,
        ...config.headers,
        ...(contentType ? { "Content-Type": contentType } : {}),
      });

      const response = await axios.request({
        url: BASE_URL + url,
        method: postMethod,
        data: dataToSend,
        ...defaultConfig,
        ...config,
        headers,
      });
      const data = response.data;

      // Check if this is a login or signup response and extract token if present
      if ((url.includes(APIs.LOGIN) || url.includes(APIs.REGISTER)) && data?.token) {
        setJwtToken(data.token);
      }

      setError((prevError) => ({ ...prevError, post: null }));
      return data;
    } catch (err) {
      setError((prevError) => ({ ...prevError, post: err }));
      throw err;
    } finally {
      setLoading((prevLoading) => ({ ...prevLoading, post: false }));
    }
  }, []);

  const putData = useCallback(async (url, putData, config = {}) => {
    setLoading((prevLoading) => ({ ...prevLoading, put: true }));
    try {
      let contentType = "application/json";
      let dataToSend = putData;
      if (putData instanceof FormData) {
        contentType = undefined;
      } else {
        dataToSend = JSON.stringify(putData);
      }
      const headers = addConfigHeaders({
        ...defaultConfig.headers,
        ...config.headers,
        ...(contentType ? { "Content-Type": contentType } : {}),
      });

      const response = await axios.request({
        url: BASE_URL + url,
        method: putMethod,
        data: dataToSend,
        ...defaultConfig,
        ...config,
        headers,
      });
      const data = response.data;
      setError((prevError) => ({ ...prevError, put: null }));
      return data;
    } catch (err) {
      setError((prevError) => ({ ...prevError, put: err }));
      throw err;
    } finally {
      setLoading((prevLoading) => ({ ...prevLoading, put: false }));
    }
  }, []);

  const deleteData = useCallback(async (url, deleteData, config = {}) => {
    setLoading((prevLoading) => ({ ...prevLoading, delete: true }));
    try {
      let contentType = "application/json";
      let dataToSend = deleteData;
      if (deleteData instanceof FormData) {
        contentType = undefined;
      } else {
        dataToSend = JSON.stringify(deleteData);
      }
      const headers = addConfigHeaders({
        ...defaultConfig.headers,
        ...config.headers,
        ...(contentType ? { "Content-Type": contentType } : {}),
      });

      const response = await axios.request({
        url: BASE_URL + url,
        method: deleteMethod,
        data: dataToSend,
        ...defaultConfig,
        ...config,
        headers,
      });
      const data = response.data;
      setError((prevError) => ({ ...prevError, delete: null }));
      return data;
    } catch (err) {
      setError((prevError) => ({ ...prevError, delete: err }));
      throw err;
    } finally {
      setLoading((prevLoading) => ({ ...prevLoading, delete: false }));
    }
  }, []);

  // Clear token (for logout)
  const clearJwtToken = useCallback(() => {
    jwtToken = null;
    Cookies.remove("jwt-token");
  }, []);

  return {
    loading: loading?.fetch || loading?.post || loading?.put || loading?.delete,
    error,
    fetchData,
    postData,
    putData,
    deleteData,
    setJwtToken,
    clearJwtToken,
    getSessionId,
    getJwtToken,
  };
};

export default useFetch;
