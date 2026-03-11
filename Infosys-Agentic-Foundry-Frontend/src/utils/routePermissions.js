import Cookies from "js-cookie";

/**
 * Route permission configuration
 * Maps each route to its permission check function
 * Using hasPermission(key, true) - if permission not in API response, show by default
 */
export const getAvailableRoutes = (hasPermission) => {
  const role = Cookies.get("role");
  const isAdminRole = role && (role.toUpperCase() === "ADMIN" || role.toUpperCase() === "SUPERADMIN");
  const isSuperAdmin = role && role.toUpperCase() === "SUPERADMIN";

  return [
    { path: "/", permission: hasPermission("execute_access.agents", true), label: "Chat" },
    { path: "/tools", permission: hasPermission("read_access.tools", true), label: "Tools" },
    { path: "/servers", permission: hasPermission("read_access.tools", true), label: "Servers" },
    { path: "/agent", permission: hasPermission("read_access.agents", true), label: "Agents" },
    { path: "/pipeline", permission: hasPermission("read_access.agents", true), label: "Pipeline" },
    { path: "/secret", permission: hasPermission("vault_access", true), label: "Vault" },
    { path: "/dataconnector", permission: hasPermission("data_connector_access", true), label: "Data Connectors" },
    { path: "/knowledge-base", permission: hasPermission("knowledgebase_access", true), label: "Knowledge Base" },
    { path: "/groundtruth", permission: hasPermission("ground_truth_access", true), label: "Ground Truth" },
    { path: "/evaluation", permission: hasPermission("evaluation_access", true), label: "Evaluation" },
    // Routes without permission toggles - always accessible as default screens
    { path: "/chat", permission: true, label: "Chat" },
    { path: "/files", permission: true, label: "Files" },
    { path: "/admin", permission: isAdminRole, label: "Admin" },
    { path: "/super-admin", permission: isSuperAdmin, label: "Super Admin" },
  ];
};

/**
 * Find the first available route that the user has permission to access
 * @param {Function} hasPermission - Permission check function from usePermissions hook
 * @param {string} excludePath - Current path to exclude from search (optional)
 * @returns {Object|null} - First available route object or null if none found
 */
export const getFirstAvailableRoute = (hasPermission, excludePath = null) => {
  const routes = getAvailableRoutes(hasPermission);
  return routes.find(route => route.path !== excludePath && route.permission) || null;
};

/**
 * Check if user has access to a specific route
 * @param {Function} hasPermission - Permission check function from usePermissions hook
 * @param {string} path - Route path to check
 * @returns {boolean} - Whether user has access to the route
 */
export const hasRouteAccess = (hasPermission, path) => {
  const routes = getAvailableRoutes(hasPermission);
  const route = routes.find(r => r.path === path);
  return route ? route.permission : false;
};
