import React, { useEffect } from "react";
import { Navigate } from "react-router-dom";
import { useAuth, hasAuthArtifacts, getActiveUser } from "./context/AuthContext";

const ProtectedRoute = ({ children, requiredRole }) => {
  const { isAuthenticated, role, loading, logout, user } = useAuth();
  const restrictedForUser = ["/", "/agent", "/secret", "/dataconnector","/evaluation"];

  useEffect(() => {
    if (loading) return;
    const active = getActiveUser();

    if (!hasAuthArtifacts()) {
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

  if (role && role.toLowerCase() === "user" && restrictedForUser.includes(window.location.pathname)) {
    return <Navigate to="/chat" replace />;
  }

  if (loading) return null;

  if (!isAuthenticated || !hasAuthArtifacts()) {
    return <Navigate to="/login" replace />;
  }

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

  return children;
};

export default ProtectedRoute;
