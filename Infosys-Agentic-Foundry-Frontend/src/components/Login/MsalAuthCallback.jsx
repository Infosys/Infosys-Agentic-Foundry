import React, { useEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { msalInstance, loginRequest } from "../../auth/msalConfig";
import { checkUserStatus, buildLoginMsalErrorPath, getAuthMeResponseErrorMessage, getMsalAuthErrorMessage, isAuthMeSuccessStatus } from "../../auth/authApi";
import { setJwtToken } from "../../Hooks/useAxios";
import { useAuth } from "../../context/AuthContext";
import { setSessionStart } from "../../Hooks/useAutoLogout";
import {
  clearMsalAuthInProgress,
  markMsalAuthInProgress,
} from "../../auth/msalSessionUtils";
import MsalAuthLoader from "../commonComponents/MsalAuthLoader";

/**
 * MsalAuthCallback — handles the redirect back from Microsoft after MSAL login.
 *
 * Flow:
 *   1. handleRedirectPromise() processes the redirect and returns tokens.
 *   2. acquireTokenSilent() gets a fresh access token from MSAL's cache.
 *   3. GET /auth/me determines the user's provisioning state.
 *   4. Route to dashboard / select-department / pending-approval accordingly.
 */
function MsalAuthCallback() {
  const navigate = useNavigate();
  const { login } = useAuth();

  const isProcessing = useRef(false);
  const hasProcessed = useRef(false);

  useEffect(() => {
    if (isProcessing.current || hasProcessed.current) return;
    isProcessing.current = true;
    markMsalAuthInProgress();

    const handleMsalCallback = async () => {
      try {
        await msalInstance.initialize();
        const result = await msalInstance.handleRedirectPromise();

        const account = result?.account ?? msalInstance.getAllAccounts()[0];
        if (!account) {
          hasProcessed.current = true;
          clearMsalAuthInProgress();
          navigate("/login", { replace: true });
          return;
        }

        const tokenResult = await msalInstance.acquireTokenSilent({
          ...loginRequest,
          account,
        });

        const me = await checkUserStatus(tokenResult.accessToken);

        if (!isAuthMeSuccessStatus(me.status)) {
          hasProcessed.current = true;
          clearMsalAuthInProgress();
          const fallback =
            (me.status || "").toUpperCase() === "ACCOUNT_DEACTIVATED"
              ? "Account deactivated"
              : "Unable to complete sign-in. Please try again.";
          navigate(buildLoginMsalErrorPath(getAuthMeResponseErrorMessage(me, fallback)), { replace: true });
          return;
        }

        switch (me.status) {
          case "USER_EXISTS": {
            setJwtToken(tokenResult.accessToken);
            localStorage.setItem("auth_type", "msal");
            sessionStorage.removeItem("id_token");

            const arr = new Uint8Array(16);
            crypto.getRandomValues(arr);
            const sessionId = `session_${Array.from(arr, (b) => b.toString(16).padStart(2, "0")).join("")}`;

            login({
              userName: me.username,
              user_session: sessionId,
              role: me.role,
              email: me.email,
              department_name: me.department_name,
            });

            setSessionStart();
            window.dispatchEvent(new Event("permissions:updated"));

            hasProcessed.current = true;
            clearMsalAuthInProgress();
            navigate("/", { replace: true });
            break;
          }

          case "NEEDS_DEPARTMENT_SELECTION":
            hasProcessed.current = true;
            clearMsalAuthInProgress();
            navigate(
              `/select-department?email=${encodeURIComponent(me.email)}&username=${encodeURIComponent(me.username)}`,
              { replace: true }
            );
            break;

          case "PENDING_APPROVAL":
            hasProcessed.current = true;
            clearMsalAuthInProgress();
            navigate(
              `/pending-approval?email=${encodeURIComponent(me.email)}`,
              { replace: true }
            );
            break;

          default:
            break;
        }
      } catch (err) {
        console.error("MSAL callback error:", err);
        hasProcessed.current = true;
        clearMsalAuthInProgress();
        navigate(buildLoginMsalErrorPath(getMsalAuthErrorMessage(err)), { replace: true });
      }
    };

    handleMsalCallback();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return <MsalAuthLoader />;
}

export default MsalAuthCallback;