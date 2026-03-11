import React, { useEffect } from "react";
import { Navigate, useLocation } from "react-router-dom";
import { useAuth, hasAuthArtifacts, getActiveUser } from "./context/AuthContext";
import { usePermissions } from "./context/PermissionsContext";

const ProtectedRoute = ({ children, requiredRole }) => {
  const { isAuthenticated, role, loading, logout, user } = useAuth();
  const { hasPermission, loading: permissionsLoading } = usePermissions();
  const location = useLocation();

  // Note: USER role access is now controlled by permissions from API (routePermissionMap below)
  // instead of hardcoded route restrictions. If backend grants USER a permission, they can access that route.

  // Routes that SuperAdmin should NOT access (redirect to /super-admin)
  const restrictedForSuperAdmin = ["/", "/agent", "/chat", "/secret", "/groundtruth", "/dataconnector", "/evaluation", "/admin", "/servers", "/pipeline", "/knowledge-base", "/files", "/resource-dashboard"];

  // Permission mapping for routes - defines which permission is needed for each route
  // /files is intentionally NOT listed here — it has no permission toggle
  // and should always be accessible as the default fallback screen.
  // Routes with read_access (tools, servers, agents, pipeline) are intentionally excluded.
  // Users can always navigate to these pages; card-level access control handles
  // clickability and edit permissions based on read_access and update_access.
  // "/" and "/chat" are excluded so users always land on the home screen after login.
  const routePermissionMap = {
    "/secret": "vault_access",
    "/dataconnector": "data_connector_access",
    "/groundtruth": "evaluation_access",
    "/evaluation": "evaluation_access",
    "/knowledge-base": "knowledgebase_access",
  };

  useEffect(() => {
    if (loading) return;
    const active = getActiveUser();

    // Only check core artifacts (userName + session), NOT the JWT cookie.
    // If JWT has expired the axios interceptor will silently refresh it
    // on the next API call. Calling logout here would wipe email/session
    // and make the refresh impossible.
    if (!hasAuthArtifacts(false)) {
      logout("protected-route-check");
      return;
    }

    if (user?.name && active && user.name !== active) {
      // Allow Guest -> real user transition without forced logout
      if (user.name === "Guest") {
        // Soft redirect to trigger contexts to re-evaluate if necessary
        return;
      }
      logout("protected-route-mismatch");
    }
  }, [loading, logout, user]);

  // Wait for both auth and permissions to load
  if (loading || permissionsLoading) return null;

  if (!isAuthenticated || !hasAuthArtifacts(false)) {
    return <Navigate to="/login" replace />;
  }

  // Redirect SuperAdmin to /super-admin when accessing restricted routes
  if (role && role.toUpperCase() === "SUPERADMIN" && restrictedForSuperAdmin.includes(location.pathname)) {
    return <Navigate to="/super-admin" replace />;
  }

  // Check required role if specified
  if (requiredRole) {
    if (Array.isArray(requiredRole)) {
      const allowedRoles = requiredRole.map((r) => r.toUpperCase());
      if (!role || !allowedRoles.includes(role.toUpperCase())) {
        return <Navigate to="/" replace />;
      }
    } else {
      if (!role || role.toUpperCase() !== requiredRole.toUpperCase()) {
        return <Navigate to="/" replace />;
      }
    }
  }

  // Check permission for the route (skip for Admin/SuperAdmin as they have full access)
  const normalizedRole = role ? role.toUpperCase() : "";
  const isAdmin = normalizedRole === "ADMIN";
  const isAdminOrSuperAdmin = normalizedRole === "ADMIN" || normalizedRole === "SUPERADMIN";

  // Ordered list of nav items matching the NavBar rendering order.
  // Each entry: { path, permission (null = always visible), roleCheck (optional) }
  const navItems = [
    { path: "/", permission: "execute_access.agents" },
    { path: "/tools", permission: null },
    { path: "/servers", permission: null },
    { path: "/agent", permission: null },
    { path: "/pipeline", permission: null },
    { path: "/secret", permission: "vault_access" },
    { path: "/dataconnector", permission: "data_connector_access" },
    { path: "/knowledge-base", permission: "knowledgebase_access" },
    { path: "/resource-dashboard", permission: "add_access.tools" },
    { path: "/evaluation", permission: "evaluation_access" },
    { path: "/admin", permission: null, roleOnly: "ADMIN" },
    { path: "/files", permission: null },
  ];

  // Helper: find the first nav item visible to this user
  const getFirstVisibleRoute = () => {
    for (const item of navItems) {
      if (item.roleOnly && normalizedRole !== item.roleOnly) continue;
      if (item.permission && !hasPermission(item.permission, false)) continue;
      return item.path;
    }
    return "/files"; // ultimate fallback
  };

  if (!isAdminOrSuperAdmin && !requiredRole) {
    // Check if user is on a route that requires a permission they don't have
    const currentItem = navItems.find((item) => item.path === location.pathname);
    const requiredPermission = routePermissionMap[location.pathname];

    // If the current route is "/" (Chat) and user lacks execute_access.agents,
    // or if the route has a permission in routePermissionMap that the user lacks,
    // redirect to the first visible nav screen.
    if (
      (location.pathname === "/" && !hasPermission("execute_access.agents", false)) ||
      (requiredPermission && !hasPermission(requiredPermission, false))
    ) {
      return <Navigate to={getFirstVisibleRoute()} replace />;
    }
  }

  return children;
};

export default ProtectedRoute;
