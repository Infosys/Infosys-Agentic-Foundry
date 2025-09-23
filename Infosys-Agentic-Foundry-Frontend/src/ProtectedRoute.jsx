import React from "react";
import { Navigate } from "react-router-dom";
import { useAuth } from "./context/AuthContext";

const ProtectedRoute = ({ children, requiredRole }) => {
  const { isAuthenticated, role, loading } = useAuth();

  if (loading) {
    return null; // Could add a spinner here if desired
  }

  if (!isAuthenticated) {
    return <Navigate to="/login" />;
  }

  if (
    requiredRole &&
    (!role || role.toUpperCase() !== requiredRole.toUpperCase())
  ) {
    return <Navigate to="/" />;
  }

  return children;
};

export default ProtectedRoute;
