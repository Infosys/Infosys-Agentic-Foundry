import React from 'react';
import { Navigate } from 'react-router-dom';
import Cookies from 'js-cookie';

const ProtectedRoute = ({ children, requiredRole }) => {
  const username = Cookies.get("userName");
  const session_id = Cookies.get("session_id");
  const role = Cookies.get("role");

  if (!username || !session_id) {
    return <Navigate to="/login" />;
  }

  if (requiredRole && (!role || role.toUpperCase() !== requiredRole.toUpperCase())) {
    // Redirect users without the required role
    return <Navigate to="/" />;
  }

  return children;
};

export default ProtectedRoute;