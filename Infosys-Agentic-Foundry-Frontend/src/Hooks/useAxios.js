import { useState, useCallback } from "react";
import { BASE_URL } from "../constant";
import Cookies from "js-cookie";

// CSRF token storage
let csrfToken = null;
let sessionId = null;

let postMethod = "POST";

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
  if (csrfToken) {
    return {
      ...headers,
      "csrf-token": csrfToken,
      "session-id": sessionId, // added for CSRF token implementation
    };
  }
  return headers;
};

const defaultConfig = {
  headers: {
    "Content-Type": "application/json",
    Accept: "application/json",
  },
  timeout: 5000, // 5 seconds timeout
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
      const response = await fetch(BASE_URL + url, tempHeaders);
      if (!response.ok) throw new Error("Network response was not ok");
      const data = await response.json();

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
      // Add CSRF token to headers for POST requests
      const headers = addCsrfHeader({
        ...defaultConfig.headers,
        ...config.headers
      });

      const response = await fetch(BASE_URL + url, {
        method: postMethod,
        body: JSON.stringify(postData),
        ...defaultConfig,
        ...config,
        headers
      });
      if (!response.ok) throw new Error("Network response was not ok");
      const data = await response.json();

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
      // Add CSRF token to headers for PUT requests
      const headers = addCsrfHeader({
        ...defaultConfig.headers,
        ...config.headers
      });

      const response = await fetch(BASE_URL + url, {
        method: "PUT",
        body: JSON.stringify(putData),
        ...defaultConfig,
        ...config,
        headers
      });
      // if (!response.ok) throw new Error("Network response was not ok");
      const data = await response.json();
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
      // Add CSRF token to headers for DELETE requests
      const headers = addCsrfHeader({
        ...defaultConfig.headers,
        ...config.headers
      });

      const response = await fetch(BASE_URL + url, {
        method: "DELETE",
        body: JSON.stringify(deleteData),
        ...defaultConfig,
        ...config,
        headers
      });
      if (!response.ok) throw new Error("Network response was not ok");
      setError((prevError) => ({ ...prevError, delete: null }));
      return null;
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
