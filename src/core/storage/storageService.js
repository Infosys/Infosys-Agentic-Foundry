/**
 * Centralized Storage Service
 *
 * Provides a unified interface for all storage operations (cookies, localStorage, sessionStorage)
 * with error handling, type safety, and consistent behavior across the application.
 *
 * Benefits:
 * - No direct document.cookie access in components
 * - Consistent error handling
 * - Easy to mock for testing
 * - SSR-safe (checks for window)
 * - Type coercion and validation
 */

import Cookies from "js-cookie";

const COOKIE_OPTIONS = {
  path: "/",
  expires: 0.25, // 6 hours (matches session timeout)
  sameSite: "Lax",
};

class StorageService {
  // ==================== COOKIE METHODS ====================

  /**
   * Set a cookie with default options
   * @param {string} key - Cookie name
   * @param {string} value - Cookie value
   * @param {object} options - Additional cookie options (overrides defaults)
   * @returns {boolean} - Success status
   */
  setCookie(key, value, options = {}) {
    try {
      Cookies.set(key, value, { ...COOKIE_OPTIONS, ...options });
      return true;
    } catch (error) {
      console.error(`[StorageService] Failed to set cookie: ${key}`, error);
      return false;
    }
  }

  /**
   * Get a cookie value
   * @param {string} key - Cookie name
   * @param {*} defaultValue - Value to return if cookie doesn't exist
   * @returns {string|null} - Cookie value or default
   */
  getCookie(key, defaultValue = null) {
    try {
      const value = Cookies.get(key);
      return value !== undefined ? value : defaultValue;
    } catch (error) {
      console.error(`[StorageService] Failed to get cookie: ${key}`, error);
      return defaultValue;
    }
  }

  /**
   * Remove a cookie
   * @param {string} key - Cookie name
   * @returns {boolean} - Success status
   */
  removeCookie(key) {
    try {
      Cookies.remove(key, { path: "/" });
      return true;
    } catch (error) {
      console.error(`[StorageService] Failed to remove cookie: ${key}`, error);
      return false;
    }
  }

  /**
   * Check if a cookie exists
   * @param {string} key - Cookie name
   * @returns {boolean}
   */
  hasCookie(key) {
    return Cookies.get(key) !== undefined;
  }

  // ==================== LOCAL STORAGE METHODS ====================

  /**
   * Set an item in localStorage (auto-serializes objects)
   * @param {string} key - Storage key
   * @param {*} value - Value to store (will be JSON stringified)
   * @returns {boolean} - Success status
   */
  setLocal(key, value) {
    if (typeof window === "undefined") return false;
    try {
      const serialized = typeof value === "string" ? value : JSON.stringify(value);
      window.localStorage.setItem(key, serialized);
      return true;
    } catch (error) {
      console.error(`[StorageService] Failed to set localStorage: ${key}`, error);
      return false;
    }
  }

  /**
   * Get an item from localStorage (auto-parses JSON)
   * @param {string} key - Storage key
   * @param {*} defaultValue - Value to return if key doesn't exist
   * @returns {*} - Parsed value or default
   */
  getLocal(key, defaultValue = null) {
    if (typeof window === "undefined") return defaultValue;
    try {
      const item = window.localStorage.getItem(key);
      if (item === null) return defaultValue;

      // Try to parse as JSON, fallback to raw string
      try {
        return JSON.parse(item);
      } catch {
        return item;
      }
    } catch (error) {
      console.error(`[StorageService] Failed to get localStorage: ${key}`, error);
      return defaultValue;
    }
  }

  /**
   * Remove an item from localStorage
   * @param {string} key - Storage key
   * @returns {boolean} - Success status
   */
  removeLocal(key) {
    if (typeof window === "undefined") return false;
    try {
      window.localStorage.removeItem(key);
      return true;
    } catch (error) {
      console.error(`[StorageService] Failed to remove localStorage: ${key}`, error);
      return false;
    }
  }

  /**
   * Check if a key exists in localStorage
   * @param {string} key - Storage key
   * @returns {boolean}
   */
  hasLocal(key) {
    if (typeof window === "undefined") return false;
    return window.localStorage.getItem(key) !== null;
  }

  /**
   * Clear all localStorage
   * @returns {boolean} - Success status
   */
  clearLocal() {
    if (typeof window === "undefined") return false;
    try {
      window.localStorage.clear();
      return true;
    } catch (error) {
      console.error("[StorageService] Failed to clear localStorage", error);
      return false;
    }
  }

  // ==================== SESSION STORAGE METHODS ====================

  /**
   * Set an item in sessionStorage (auto-serializes objects)
   * @param {string} key - Storage key
   * @param {*} value - Value to store
   * @returns {boolean} - Success status
   */
  setSession(key, value) {
    if (typeof window === "undefined") return false;
    try {
      const serialized = typeof value === "string" ? value : JSON.stringify(value);
      window.sessionStorage.setItem(key, serialized);
      return true;
    } catch (error) {
      console.error(`[StorageService] Failed to set sessionStorage: ${key}`, error);
      return false;
    }
  }

  /**
   * Get an item from sessionStorage (auto-parses JSON)
   * @param {string} key - Storage key
   * @param {*} defaultValue - Value to return if key doesn't exist
   * @returns {*} - Parsed value or default
   */
  getSession(key, defaultValue = null) {
    if (typeof window === "undefined") return defaultValue;
    try {
      const item = window.sessionStorage.getItem(key);
      if (item === null) return defaultValue;

      try {
        return JSON.parse(item);
      } catch {
        return item;
      }
    } catch (error) {
      console.error(`[StorageService] Failed to get sessionStorage: ${key}`, error);
      return defaultValue;
    }
  }

  /**
   * Remove an item from sessionStorage
   * @param {string} key - Storage key
   * @returns {boolean} - Success status
   */
  removeSession(key) {
    if (typeof window === "undefined") return false;
    try {
      window.sessionStorage.removeItem(key);
      return true;
    } catch (error) {
      console.error(`[StorageService] Failed to remove sessionStorage: ${key}`, error);
      return false;
    }
  }

  /**
   * Clear all sessionStorage
   * @returns {boolean} - Success status
   */
  clearSession() {
    if (typeof window === "undefined") return false;
    try {
      window.sessionStorage.clear();
      return true;
    } catch (error) {
      console.error("[StorageService] Failed to clear sessionStorage", error);
      return false;
    }
  }

  // ==================== AUTH-SPECIFIC METHODS ====================

  /**
   * Get all authentication-related data
   * @returns {object} - Auth data object
   */
  getAuthData() {
    return {
      userName: this.getCookie("userName"),
      jwtToken: this.getCookie("jwt-token"),
      refreshToken: this.getCookie("refresh-token"),
      userSession: this.getCookie("user_session"),
      role: this.getCookie("role"),
      email: this.getCookie("email"),
      loginTimestamp: this.getLocal("login_timestamp"),
    };
  }

  /**
   * Set authentication data
   * @param {object} authData - Authentication data
   */
  setAuthData(authData) {
    if (authData.userName) this.setCookie("userName", authData.userName);
    if (authData.jwtToken) this.setCookie("jwt-token", authData.jwtToken);
    if (authData.refreshToken) this.setCookie("refresh-token", authData.refreshToken);
    if (authData.userSession) this.setCookie("user_session", authData.userSession);
    if (authData.role) this.setCookie("role", authData.role);
    if (authData.email) this.setCookie("email", authData.email);
    if (authData.loginTimestamp) this.setLocal("login_timestamp", authData.loginTimestamp);
  }

  /**
   * Clear all authentication-related storage
   */
  clearAuth() {
    const authKeys = ["userName", "jwt-token", "user_session", "role", "refresh-token", "email"];
    authKeys.forEach((key) => this.removeCookie(key));

    this.removeLocal("active_user_name");
    this.removeLocal("user_session");
    this.removeLocal("login_timestamp");
  }

  /**
   * Check if user has valid auth artifacts
   * @param {boolean} strict - If true, requires JWT token
   * @returns {boolean}
   */
  hasAuthArtifacts(strict = true) {
    const userName = this.getCookie("userName");
    const session = this.getCookie("user_session");
    const jwt = this.getCookie("jwt-token");

    if (!strict) {
      return !!(userName && session);
    }

    return !!(userName && session && jwt);
  }
}

// Export singleton instance
export const storageService = new StorageService();
export default storageService;
