import React, { useEffect } from "react";
import { Navigate, useLocation } from "react-router-dom";
import { useAuth, hasAuthArtifacts, getActiveUser } from "./context/AuthContext";

const ProtectedRoute = ({ children, requiredRole }) => {
  const { isAuthenticated, role, loading, logout, user } = useAuth();
  const location = useLocation();

  // Routes that SuperAdmin should NOT access (redirect to /super-admin)
  const restrictedForSuperAdmin = ["/", "/agent", "/chat", "/tools", "/secret", "/groundtruth", "/dataconnector", "/evaluation", "/admin", "/servers", "/workflows", "/knowledge-base", "/files", "/resource-dashboard", "/requests"];

  // Routes that Admin should NOT access (redirect to /tools)
  const restrictedForAdmin = [];


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

  // Wait for auth to load
  if (loading) return null;

  if (!isAuthenticated || !hasAuthArtifacts(false)) {
    return <Navigate to="/login" replace />;
  }

  // Redirect SuperAdmin to /super-admin when accessing restricted routes
  if (role && role.toUpperCase() === "SUPERADMIN" && restrictedForSuperAdmin.includes(location.pathname)) {
    return <Navigate to="/super-admin" replace />;
  }

  // Redirect Admin to /tools when accessing restricted routes
  if (role && role.toUpperCase() === "ADMIN" && restrictedForAdmin.includes(location.pathname)) {
    return <Navigate to="/tools" replace />;
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

  // Permission-based route protection is no longer enforced at the route level.
  // Nav items are always shown, and pages handle read_access internally
  // (cards become non-clickable when read_access is false).

  return children;
};

export default ProtectedRoute;
