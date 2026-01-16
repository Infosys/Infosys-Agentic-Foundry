import React, { createContext, useContext, useEffect, useState } from "react";
import Cookies from "js-cookie";
import { APIs } from "../constant";
import useFetch from "../Hooks/useAxios";

const PermissionsContext = createContext({
  permissions: null,
  loading: false,
  error: null,
  refreshPermissions: () => {},
});

export const PermissionsProvider = ({ children }) => {
  const [permissions, setPermissions] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const role = Cookies.get("role");
  const { fetchData } = useFetch();

  const fetchPermissions = React.useCallback(
    async (roleName) => {
      if (!roleName) return;
      setLoading(true);
      setError(null);
      try {
        const url = `${APIs.GET_ROLE_PERMISSIONS}/${encodeURIComponent(roleName)}`;
        const response = await fetchData(url);
        if (response?.success) {
          setPermissions(response.permissions);
        } else {
          setPermissions(null);
          setError(response?.message || "Failed to fetch permissions");
        }
      } catch (err) {
        setPermissions(null);
        setError(err.message || "Error fetching permissions");
      } finally {
        setLoading(false);
      }
    },
    [fetchData]
  );

  useEffect(() => {
    fetchPermissions(role);
    // Listen for cookie/role changes if needed
    // Optionally add event listeners for login/logout
    const handlePermissionsUpdated = () => fetchPermissions(role);
    // Listen for a manual window event (other parts of the app can dispatch this)
    window.addEventListener("permissions:updated", handlePermissionsUpdated);

    // Also listen for a localStorage-based refresh (useful when admin updates permissions in a different tab)
    const handleStorage = (e) => {
      if (e.key === "permissions_refresh") {
        fetchPermissions(role);
      }
    };
    window.addEventListener("storage", handleStorage);

    return () => {
      window.removeEventListener("permissions:updated", handlePermissionsUpdated);
      window.removeEventListener("storage", handleStorage);
    };
  }, [role, fetchPermissions]);

  // Helper to check nested permission keys easily (e.g. 'read_access.tools' or 'vault_access')
  const hasPermission = (keyPath) => {
    if (!permissions || !keyPath) return false;
    const parts = keyPath.split(".");
    let current = permissions;
    for (const p of parts) {
      if (current && Object.prototype.hasOwnProperty.call(current, p)) {
        current = current[p];
      } else {
        return false;
      }
    }
    // If value is explicitly false -> no permission
    if (typeof current === "boolean") return current === true;
    // For nested objects (e.g. read_access: { tools: true }), truthiness indicates permission available
    return Boolean(current);
  };

  return (
    <PermissionsContext.Provider value={{ permissions, loading, error, refreshPermissions: () => fetchPermissions(role), hasPermission }}>{children}</PermissionsContext.Provider>
  );
};

export const usePermissions = () => useContext(PermissionsContext);
