import React from 'react';
import { Navigate } from 'react-router-dom';
import Cookies from 'js-cookie';

const ProtectedRoute = ({ children }) => {
  const username = Cookies.get("userName");
  const session_id = Cookies.get("session_id");

  if (!username && !session_id) {
    return <Navigate to="/login" />;
  }

  return children;
};

export default ProtectedRoute;