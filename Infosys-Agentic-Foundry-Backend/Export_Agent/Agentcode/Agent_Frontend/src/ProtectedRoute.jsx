// import React from 'react';
// import { Navigate } from 'react-router-dom';
// import Cookies from 'js-cookie';

// const ProtectedRoute = ({ children, requiredRole }) => {
//   const username = Cookies.get("userName");
//   const session_id = Cookies.get("session_id");
//   const role = Cookies.get("role");

//   if (!username || !session_id) {
//     return <Navigate to="/login" />;
//   }

//   if (requiredRole && (!role || role.toUpperCase() !== requiredRole.toUpperCase())) {
//     // Redirect users without the required role
//     return <Navigate to="/" />;
//   }

//   return children;
// };

// export default ProtectedRoute;

import React, { useState, useEffect } from 'react';
import { Navigate, useNavigate } from 'react-router-dom';
import CookiesJS from 'js-cookie'; // Using the alias to avoid conflicts
import useFetch from './Hooks/useAxios'; // Corrected path

const ProtectedRoute = ({ children, requiredRole }) => {
  const { fetchData, setCsrfToken } = useFetch();
  const navigate = useNavigate();

  // State to manage loading status while checking/fetching cookies
  const [isLoading, setIsLoading] = useState(true);
  // State to manage potential errors during the fetch
  const [fetchError, setFetchError] = useState(null);

  useEffect(() => {
    const checkAndSetCookies = async () => {
      const userName = CookiesJS.get("userName");
      const session_id = CookiesJS.get("session_id"); // Get session_id
      const email = CookiesJS.get("email");
      const role = CookiesJS.get("role");

      if (userName && session_id && email && role) {
        setIsLoading(false); // Cookies are already here, no need to fetch
        return;
      }
      try {
        const users = await fetchData("/fetchuser");

        if (users && users.approval) {
          CookiesJS.set("userName", users.user_name || users.username);
          CookiesJS.set("session_id", users.session_id); // Set session_id
          CookiesJS.set("email", users.email);
          CookiesJS.set("role", users.role);
          
          if (users?.csrf_token) {
            setCsrfToken(users.csrf_token);
          }
          setIsLoading(false); // Data fetched and cookies set
        } else {
          // Handle cases where API call was successful but approval is false
          console.error("Failed to fetch user data (approval: false):", users.message);
          setFetchError(users.message || "Failed to initialize session.");
          setIsLoading(false); // Stop loading, but indicate error
        }
      } catch (error) {
        console.error("Error fetching user data in ProtectedRoute:", error);
        setFetchError("Network error or server issue during session initialization.");
        setIsLoading(false); // Stop loading, but indicate error
      }
    };

    checkAndSetCookies();
  }, [fetchData, setCsrfToken, navigate]); // Dependencies: fetchData, setCsrfToken, navigate
  if (isLoading) {
    return (
      <div style={{
        display: 'flex',
        justifyContent: 'center',
        alignItems: 'center',
        height: '100vh',
        fontSize: '24px',
        color: '#333',
        flexDirection: 'column'
      }}>
        <p>Loading application...</p>
        {fetchError && <p style={{ color: 'red', fontSize: '16px', marginTop: '10px' }}>Error: {fetchError}</p>}
      </div>
    );
  }
  const currentUserName = CookiesJS.get("userName");
  const currentSessionId = CookiesJS.get("session_id"); // Get current session_id
  const currentEmail = CookiesJS.get("email");
  const currentRole = CookiesJS.get("role");
  const isAuthenticated = currentUserName && currentSessionId && currentEmail && currentRole;

  if (!isAuthenticated) {
    console.warn("ProtectedRoute: Not authenticated after cookie check/fetch. Redirecting to root.");
    return <Navigate to="/" replace />;
  }
  if (requiredRole && (!currentRole || currentRole.toUpperCase() !== requiredRole.toUpperCase())) {
    console.warn(`ProtectedRoute: User role '${currentRole}' does not meet required role '${requiredRole}'. Redirecting.`);
    return <Navigate to="/" replace />;
  }
  return children;
};

export default ProtectedRoute;