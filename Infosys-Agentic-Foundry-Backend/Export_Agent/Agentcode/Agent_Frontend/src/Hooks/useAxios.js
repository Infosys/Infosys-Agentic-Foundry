import { useState, useCallback } from "react";
import {BASE_URL } from "../constant";
import Cookies from "js-cookie";
import axios from "axios";

// CSRF token storage
let csrfToken = null;
let sessionId = null;

let postMethod = "POST";
let getMethod = "GET";
let deleteMethod = "DELETE";
let putMethod = "PUT";

// Function to set the CSRF token (to be called after login/signup)
export const setCsrfToken = (token) => {
  if (token) {
    csrfToken = token;
    Cookies.set("csrf-token", token); // Store in cookie
    return true;
  }
  return false;
};

// Function to get the current CSRF token
export const getCsrfToken = () => {
  if (!csrfToken) {
    csrfToken = Cookies.get("csrf-token");
  }
  return csrfToken;
};

// Function to get the current session ID
export const getSessionId = () => {
  if (!sessionId) {
    sessionId = Cookies.get("session_id");
  }
  return sessionId;
};

// Helper to add CSRF token to headers if available
const addCsrfHeader = (headers = {}) => {
  if (getCsrfToken()) {
    return {
      ...headers,
      "csrf-token": getCsrfToken(),
      "session-id": getSessionId(), // added for CSRF token implementation
    };
  }
  return headers;
};

const defaultConfig = {
  headers: {
    "accept": "application/json",
  },
  timeout: 20000, // 20 seconds timeout
};

const useFetch = () => {
  const [loading, setLoading] = useState({});
  const [error, setError] = useState({});

  const fetchData = useCallback(async (url, config = {}) => {
    setLoading((prevLoading) => ({ ...prevLoading, fetch: true }));
    try {
      // Add CSRF token to headers for POST requests
      const headers = addCsrfHeader({
        ...defaultConfig.headers,
        ...config.headers
      });
      // Check if login_guest then add csrf and session id temporarirly to validate the Fortify fix
      let tempHeaders = {};
      if(url.includes("/login_guest")){
        tempHeaders = {
          ...defaultConfig,
          ...config,
          headers
        }
      }
      else{
        tempHeaders = {
          ...defaultConfig,
          ...config,
        }
      }
      const response = await axios.request({
        url: BASE_URL + url,
        method: getMethod,
        ...tempHeaders
      });
      const data = response.data;

      // Check if this is a login or signup response and extract CSRF token if present
      if (url.includes('/login_guest') && data?.csrf_token) {
        setCsrfToken(data.csrf_token);
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
      const headers = addCsrfHeader({
        ...defaultConfig.headers,
        ...config.headers,
        ...(contentType ? { "Content-Type": contentType } : {})
      });

      const response = await axios.request({
        url: BASE_URL + url,
        method: postMethod,
        data: dataToSend,
        ...defaultConfig,
        ...config,
        headers
      });
      const data = response.data;

      // Check if this is a login or signup response and extract CSRF token if present
      if ((url.includes('/login') || url.includes('/registration')) && data?.csrf_token) {
        setCsrfToken(data.csrf_token);
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
      const headers = addCsrfHeader({
        ...defaultConfig.headers,
        ...config.headers,
        ...(contentType ? { "Content-Type": contentType } : {})
      });

      const response = await axios.request({
        url: BASE_URL + url,
        method: putMethod,
        data: dataToSend,
        ...defaultConfig,
        ...config,
        headers
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
      const headers = addCsrfHeader({
        ...defaultConfig.headers,
        ...config.headers,
        ...(contentType ? { "Content-Type": contentType } : {})
      });

      const response = await axios.request({
        url: BASE_URL + url,
        method: deleteMethod,
        data: dataToSend,
        ...defaultConfig,
        ...config,
        headers
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

  // Clear CSRF token (for logout)
  const clearCsrfToken = useCallback(() => {
    csrfToken = null;
    Cookies.remove("csrf-token");
  }, []);

  return {
    loading: loading?.fetch || loading?.post || loading?.put || loading?.delete,
    error,
    fetchData,
    postData,
    putData,
    deleteData,
    setCsrfToken,
    clearCsrfToken,
    getCsrfToken,
    getSessionId
  };
};

export default useFetch;
