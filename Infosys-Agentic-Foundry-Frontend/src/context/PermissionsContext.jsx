import React, { createContext, useContext, useEffect, useState, useCallback, useRef } from "react";
import Cookies from "js-cookie";
import { APIs, BASE_URL } from "../constant";
import axios from "axios";

/**
 * PermissionsContext - Dynamic permissions management
 * 
 * Permission structure is determined by API response.
 * Expected format from API:
 * {
 *   read_access: { tools: boolean, agents: boolean, ... },
 *   add_access: { tools: boolean, agents: boolean, ... },
 *   update_access: { tools: boolean, agents: boolean, ... },
 *   delete_access: { tools: boolean, agents: boolean, ... },
 *   execute_access: { tools: boolean, agents: boolean, ... },
 *   vault_access: boolean,
 *   data_connector_access: boolean,
 *   evaluation_access: boolean,
 *   ... any other boolean permissions
 * }
 */

// Known nested access categories (contain entity sub-objects)
const NESTED_ACCESS_KEYS = ["read_access", "add_access", "update_access", "delete_access", "execute_access"];

/**
 * Dynamically merge API permissions with safe defaults
 * Handles any permission structure returned by API
 */
const mergePermissions = (apiPermissions) => {
  if (!apiPermissions || typeof apiPermissions !== "object") {
    return {};
  }

  const merged = {};

  Object.entries(apiPermissions).forEach(([key, value]) => {
    if (NESTED_ACCESS_KEYS.includes(key)) {
      // Handle nested access objects (e.g., read_access: { tools: true, agents: false })
      if (value && typeof value === "object") {
        merged[key] = {};
        Object.entries(value).forEach(([entity, entityValue]) => {
          merged[key][entity] = Boolean(entityValue);
        });
      } else {
        merged[key] = {};
      }
    } else if (typeof value === "boolean") {
      // Handle standalone boolean permissions
      merged[key] = value;
    } else if (value != null) {
      // Handle any other non-null/undefined values as boolean
      merged[key] = Boolean(value);
    }
  });

  return merged;
};

const PermissionsContext = createContext({
  permissions: {},
  loading: true,
  error: null,
  refreshPermissions: () => {},
  hasPermission: () => false,
});

export const PermissionsProvider = ({ children }) => {
  const [permissions, setPermissions] = useState({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const fetchedRoleRef = useRef(null); // Track which role we've already fetched

  const fetchPermissions = useCallback(async (forceRefresh = false) => {
    const role = Cookies.get("role");
    if (!role) {
      // No role means not logged in or guest - use empty permissions
      setPermissions({});
      fetchedRoleRef.current = null;
      setLoading(false);
      return;
    }

    // Skip if we already fetched for this role (unless forced)
    if (!forceRefresh && fetchedRoleRef.current === role) {
      setLoading(false);
      return;
    }

    // Only skip API call for SuperAdmin - they always have full access
    // Admin users should fetch permissions from API to respect configured permissions
    const roleLower = role.toLowerCase();
    if (roleLower === "superadmin" || roleLower === "super admin" || roleLower === "super_admin") {
      // SuperAdmin gets all permissions - will be handled by hasPermission returning true
      fetchedRoleRef.current = role;
      setLoading(false);
      return;
    }

    setLoading(true);
    setError(null);
    try {
      // Get user's department
      const department = Cookies.get("department") || "";

      // Use POST request with request body as per API spec
      const url = `${BASE_URL}${APIs.GET_ROLE_PERMISSIONS}`;

      const response = await axios.post(url, {
        role_name: role,
        department_name: department
      }, {
        headers: {
          Authorization: `Bearer ${Cookies.get("jwt-token")}`
        }
      });
      const data = response.data;

      if (data?.success && data?.permissions) {
        // Dynamically merge permissions from API
        const mergedPermissions = mergePermissions(data.permissions);
        setPermissions(mergedPermissions);
      } else if (data?.permissions) {
        // Response has permissions but no success flag
        const mergedPermissions = mergePermissions(data.permissions);
        setPermissions(mergedPermissions);
      } else {
        // API didn't return permissions - use empty object
        setPermissions({});
      }
      fetchedRoleRef.current = role;
    } catch (err) {
      // On error (including 404), use empty permissions
      setPermissions({});
      setError(err.message || "Error fetching permissions");
      fetchedRoleRef.current = role; // Mark as fetched to prevent retries
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    const role = Cookies.get("role");
    if (role) {
      fetchPermissions();
    } else {
      // No role - set loading to false
      setLoading(false);
    }

    // Listen for permission updates (triggered after login)
    const handlePermissionsUpdated = () => {
      const currentRole = Cookies.get("role");
      if (currentRole) {
        fetchedRoleRef.current = null; // Reset to force refresh
        fetchPermissions(true);
      }
    };

    window.addEventListener("permissions:updated", handlePermissionsUpdated);

    // Also listen for a localStorage-based refresh (useful when admin updates permissions in a different tab)
    const handleStorage = (e) => {
      if (e.key === "permissions_refresh") {
        fetchedRoleRef.current = null;
        fetchPermissions(true);
      }
    };
    window.addEventListener("storage", handleStorage);

    return () => {
      window.removeEventListener("permissions:updated", handlePermissionsUpdated);
      window.removeEventListener("storage", handleStorage);
    };
  }, [fetchPermissions]);

  /**
   * Check if user has a specific permission
   * Supports dot notation for nested permissions (e.g., 'read_access.tools')
   * SuperAdmin always returns true for all permissions
   * @param {string} keyPath - The permission key path (e.g., 'read_access.tools' or 'vault_access')
   * @param {boolean} defaultValue - Value to return if permission key is not found (default: false)
   * @returns {boolean} - true if permission granted, false if denied, defaultValue if not found
   */
  const hasPermission = useCallback((keyPath, defaultValue = false) => {
    if (!keyPath) return defaultValue;

    // SuperAdmin always has all permissions
    const role = Cookies.get("role");
    if (role) {
      const roleLower = role.toLowerCase();
      if (roleLower === "superadmin" || roleLower === "super admin" || roleLower === "super_admin") {
        return true;
      }
    }

    // Navigate through the permissions object using dot notation
    const parts = keyPath.split(".");
    let current = permissions;

    for (const p of parts) {
      if (current && Object.prototype.hasOwnProperty.call(current, p)) {
        current = current[p];
      } else {
        // Key not found - return defaultValue (show by default if true, hide if false)
        return defaultValue;
      }
    }

    // Return the boolean value directly
    if (typeof current === "boolean") return current;
    // For nested objects, return defaultValue as we expect a boolean
    return defaultValue;
  }, [permissions]);

  return (
    <PermissionsContext.Provider value={{
      permissions,
      loading,
      error,
      refreshPermissions: fetchPermissions,
      hasPermission
    }}>
      {children}
    </PermissionsContext.Provider>
  );
};

export const usePermissions = () => useContext(PermissionsContext);