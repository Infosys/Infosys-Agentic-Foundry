import React, { useEffect, useState, useRef } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import Cookies from "js-cookie";
import useFetch from "../../Hooks/useAxios";
import { useAuth } from "../../context/AuthContext";
import { APIs } from "../../constant";
import { setSessionStart } from "../../Hooks/useAutoLogout";
import useErrorHandler from "../../Hooks/useErrorHandler";
import { useVersion } from "../../context/VersionContext";
import brandlogotwo from "../../Assets/Agentic-Foundry-Logo-Dark-2.png";
import "./app.css";
import "./login.css";

function OAuthCallback() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const { login } = useAuth();
  const { postData, setJwtToken, setRefreshToken } = useFetch();
  const { handleApiError } = useErrorHandler();
  const { combinedVersion } = useVersion();

  const [status, setStatus] = useState("processing");
  const [message, setMessage] = useState("Processing authentication...");

  // Prevent multiple simultaneous executions
  const isProcessing = useRef(false);
  const hasProcessed = useRef(false);

  useEffect(() => {
    // Only run once
    if (isProcessing.current || hasProcessed.current) {
      return;
    }

    isProcessing.current = true;

    const handleOAuthCallback = async () => {
      try {
        // Clear the login attempt flag since we successfully got a code
        sessionStorage.removeItem("oauth_login_attempted");

        // Get authorization code from URL query params
        const code = searchParams.get("code");
        const successParam = searchParams.get("success");
        const error = searchParams.get("error");
        const errorDescription = searchParams.get("error_description");

        // Check for backend-generated error: ?success=false&error=...
        if (successParam === "false") {
          hasProcessed.current = true;
          setStatus("error");
          setMessage(error || "Authentication failed. Please try again.");
          setTimeout(() => navigate("/login"), 3000);
          return;
        }

        // Check for Keycloak OAuth errors: ?error=access_denied&error_description=...
        if (error) {
          hasProcessed.current = true;
          setStatus("error");
          setMessage(errorDescription || error || "Authentication failed");
          setTimeout(() => navigate("/login"), 3000);
          return;
        }

        // Validate authorization code exists
        if (!code) {
          hasProcessed.current = true;
          setStatus("error");
          setMessage("No authorization code received");
          setTimeout(() => navigate("/login"), 3000);
          return;
        }

        // Exchange authorization code for tokens
        setMessage("Exchanging authorization code...");

        const response = await postData(APIs.EXCHANGE_CODE, { code });

        if (!response || !response.approval) {
          console.error("Exchange failed:", response);
          hasProcessed.current = true;
          setStatus("error");
          setMessage(response?.message || "Failed to exchange authorization code. Redirecting to login...");
          setTimeout(() => navigate("/login"), 3000);
          return;
        }

        const {
          token,
          refresh_token: refreshToken,
          id_token: idToken,
          email,
          username,
          role,
          department_name: departmentName,
          expires_in: expiresIn,
        } = response;

        // Check for pending approval (user registered but not approved yet)
        if (!token && email) {
          hasProcessed.current = true;
          navigate(`/pending-approval?email=${encodeURIComponent(email)}`, { replace: true });
          return;
        }

        // Validate required parameters
        if (!token || !email) {
          setStatus("error");
          setMessage("Missing required authentication parameters");
          setTimeout(() => navigate("/login"), 3000);
          return;
        }

        // Store id_token in sessionStorage (sensitive — cleared on browser close).
        // auth_type is non-sensitive and kept in localStorage for cross-tab logout routing.
        sessionStorage.setItem("id_token", idToken || "");
        localStorage.setItem("auth_type", idToken ? "sso" : "local");

        // Store token expiration time
        if (expiresIn) {
          const expirationTime = Date.now() + parseInt(expiresIn) * 1000;
          sessionStorage.setItem("token_expiration", expirationTime.toString());
        }

        // Generate session ID on frontend (backend will validate/regenerate if needed)
        // Don't call /chat/get/new-session-id/ here because JWT token isn't propagated yet
        // and 401 error would trigger logout
        setMessage("Setting up your session...");
        const arr = new Uint8Array(16);
        crypto.getRandomValues(arr);
        const hex = Array.from(arr, (b) => b.toString(16).padStart(2, "0")).join("");
        const sessionIdResponse = `session_${hex}`;

        // Store user data in cookies FIRST (before setting tokens)
        Cookies.set("email", email);
        Cookies.set("userName", username || email.split("@")[0]);
        Cookies.set("role", role || "User");
        if (departmentName) {
          Cookies.set("department_name", departmentName);
        }
        if (refreshToken) {
          Cookies.set("refresh_token", refreshToken);
        }

        // Update auth context
        login({
          userName: username || email.split("@")[0],
          user_session: sessionIdResponse,
          role: role || "User",
          refresh_token: refreshToken,
          department_name: departmentName,
        });

        // Set session start time for auto-logout
        setSessionStart();

        // Clean up session storage
        sessionStorage.removeItem("oauth_state");
        sessionStorage.removeItem("selected_role");

        // Clear authorization code from URL (security best practice)
        window.history.replaceState({}, document.title, window.location.pathname);

        // Set JWT and refresh tokens (THIS MUST BE AFTER cookies/auth context)
        setJwtToken(token);
        if (refreshToken) {
          setRefreshToken(refreshToken);
        }

        // Trigger permissions fetch so PermissionsContext picks up the new role
        window.dispatchEvent(new Event("permissions:updated"));

        // Mark as processed
        hasProcessed.current = true;

        // Show success and redirect
        setStatus("success");
        setMessage("Authentication successful! Redirecting...");

        // Wait longer to ensure JWT token is fully propagated to axios instance
        setTimeout(() => {
          navigate("/", { replace: true });
        }, 1000); // Increased from 1500ms to ensure token propagation

      } catch (error) {
        console.error("OAuth callback error:", error);
        console.error("Error details:", {
          message: error.message,
          stack: error.stack,
          response: error.response
        });
        handleApiError(error, { context: "OAuthCallback.codeExchange" });
        hasProcessed.current = true;
        setStatus("error");
        setMessage("Failed to exchange authorization code. Redirecting to login...");
        setTimeout(() => navigate("/login"), 3000);
      }
    };

    handleOAuthCallback();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []); // Empty deps - run only once on mount

  return (
    <div className="app-container">
      <img src={brandlogotwo} alt="Brandlogo" />
      <div className="version_number" title={combinedVersion}>{combinedVersion}</div>
      <div className="oauthCallbackContainer">
        <div className="oauthCallbackCard">
          {status === "processing" && (
            <>
              <div className="spinner"></div>
              <h3 className="oauthCallbackTitle">{message}</h3>
            </>
          )}
          {status === "success" && (
            <>
              <div className="successIcon">✓</div>
              <h3 className="oauthCallbackTitle successText">{message}</h3>
            </>
          )}
          {status === "pending" && (
            <>
              <div className="pendingIcon">⏳</div>
              <h3 className="oauthCallbackTitle pendingText">{message}</h3>
              <p className="oauthCallbackSubtext">Redirecting to login page...</p>
            </>
          )}
          {status === "error" && (
            <>
              <div className="errorIcon">✕</div>
              <h3 className="oauthCallbackTitle errorText">{message}</h3>
              <p className="oauthCallbackSubtext">
                <button
                  className="submitBtn"
                  onClick={() => window.location.reload()}
                >
                  Refresh Page
                </button>
              </p>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

export default OAuthCallback;