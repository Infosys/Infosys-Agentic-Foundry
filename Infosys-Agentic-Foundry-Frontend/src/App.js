import "./App.css";
import { useCallback, useEffect, useRef } from "react";
import Cookies from "js-cookie";
import AvailableAgents from "./components/AvailableAgents/AvailableAgents";
import AskAssistant from "./components/AskAssistant/AskAssistant";
import { Navigate, Route, Routes, useNavigate, useLocation, useSearchParams } from "react-router-dom";
import Layout from "./components/Layout";
import AvailableTools from "./components/AvailableTools/AvailableTools";
import AvailableServers from "./components/AvailableTools/AvailableServers";
import Login from "./components/Login";
import OAuthCallback from "./components/Login/OAuthCallback";
import MsalAuthCallback from "./components/Login/MsalAuthCallback";
import SelectDepartment from "./components/Login/SelectDepartment";
import PendingApproval from "./components/Login/PendingApproval";
import { useMessage } from "./Hooks/MessageContext";
import MessagePopup from "./components/MessagePopup/MessagePopup";
import GlobalComponent from "./Hooks/GlobalComponent";
import Register from "./components/Register/Index";
import { useAuth, hasAuthArtifacts } from "./context/AuthContext";
import { usePermissions } from "./context/PermissionsContext";
import ProtectedRoute from "./ProtectedRoute";
import { msalInstance, loginRequest } from "./auth/msalConfig";
import { checkUserStatus, buildLoginMsalErrorPath, getAuthMeResponseErrorMessage, getMsalAuthErrorMessage, isAuthMeSuccessStatus } from "./auth/authApi";
import {
  clearMsalAutoLoginSuppression,
  clearMsalAuthInProgress,
  hasPendingMsalRedirect,
  isMsalAuthInProgress,
  isMsalAutoLoginSuppressed,
  isMsalLoginPending,
  markMsalAuthInProgress,
} from "./auth/msalSessionUtils";
import MsalAuthLoader from "./components/commonComponents/MsalAuthLoader";
import { setJwtToken } from "./Hooks/useAxios";
import { setSessionStart } from "./Hooks/useAutoLogout";
import AdminScreenNew from "./components/AdminScreen/AdminScreenNew";
import SuperAdminControl from "./components/AdminScreen/SuperAdminControl";
import TokenUsagePage from "./components/AdminScreen/TokenUsagePage";
import VaultScreen from "./components/Vault/Vault";
import GroundTruth from "./components/GroundTruth/GroundTruth";
import DataConnectors from "./components/DataConnectors/DataConnectors";
import ResourceDashboard from "./components/ResourceDashboard/ResourceDashboard";
import EvaluationPageNew from "./components/EvaluationPage/EvaluationPageNew";
import KnowledgeBase from "./components/KnowledgeBase/KnowledgeBase";
import FilesPage from "./components/AskAssistant/FilesPage";
import useAutoLogout from "./Hooks/useAutoLogout";
import useIdleTimeout from "./Hooks/useIdleTimeout";
import useErrorHandler from "./Hooks/useErrorHandler";
import { globalErrorService } from "./services/globalErrorService";
import Workflow from "./components/Workflow";
// [MANUAL_TOKEN_MODE] — remove this import when removing the feature
import ManualTokenModal from "./components/ManualToken/ManualTokenModal";
import Requests from "./components/Requests/Requests";
import HookRepository from "./components/HookRepository/HookRepository";
import Scheduler from "./components/Scheduler/Scheduler";
import LLMTracker from "./components/LLMTracker";

// Handles the MSAL redirect response that lands at the root redirectUri (localhost:3003/).
// MsalProvider calls handleRedirectPromise() automatically when the page loads.
// Afterwards MsalProvider may fire LOGIN_SUCCESS for cached accounts — we intentionally
// do not handle that event to avoid sign-out auto-login loops.
// Defined outside App to keep a stable component reference across re-renders.
const MsalEventHandler = () => {
  const navigate = useNavigate();
  const location = useLocation();
  const { login } = useAuth();
  const processingRef = useRef(false);

  const shouldAbortMsalAutoLogin = useCallback(
    (fromRedirect = false) => {
      // Only bypass suppression for an active Microsoft redirect round-trip
      if (fromRedirect && (isMsalAuthInProgress() || hasPendingMsalRedirect())) {
        return false;
      }
      if (isMsalAutoLoginSuppressed()) return true;
      if (location.pathname === "/login") return true;
      return false;
    },
    [location.pathname]
  );

  const abortIfNeeded = useCallback(
    (fromRedirect) => {
      if (!shouldAbortMsalAutoLogin(fromRedirect)) return false;
      if (fromRedirect) clearMsalAuthInProgress();
      return true;
    },
    [shouldAbortMsalAutoLogin]
  );

  const handleAccount = useCallback(
    async (account, preFetchedAccessToken = null, { fromRedirect = false } = {}) => {
      // Guard: skip if already in progress or app is already authenticated via MSAL
      if (processingRef.current) return;
      if (localStorage.getItem("auth_type") === "msal" && hasAuthArtifacts(false)) return;

      // Respect explicit sign-out / back-to-login — only process fresh Microsoft redirects
      if (shouldAbortMsalAutoLogin(fromRedirect)) return;

      processingRef.current = true;
      if (fromRedirect) markMsalAuthInProgress();
      try {
        const tokenResult = preFetchedAccessToken
          ? { accessToken: preFetchedAccessToken }
          : await msalInstance.acquireTokenSilent({ ...loginRequest, account });

        if (abortIfNeeded(fromRedirect)) return;

        const me = await checkUserStatus(tokenResult.accessToken);

        if (abortIfNeeded(fromRedirect)) return;

        if (!isAuthMeSuccessStatus(me.status)) {
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
            if (abortIfNeeded(fromRedirect)) return;

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
            window.history.replaceState({}, document.title, window.location.pathname);
            clearMsalAuthInProgress();
            navigate("/", { replace: true });
            break;
          }
          case "NEEDS_DEPARTMENT_SELECTION":
            clearMsalAuthInProgress();
            navigate(
              `/select-department?email=${encodeURIComponent(me.email)}&username=${encodeURIComponent(me.username)}`,
              { replace: true }
            );
            break;
          case "PENDING_APPROVAL":
            clearMsalAuthInProgress();
            navigate(`/pending-approval?email=${encodeURIComponent(me.email)}`, { replace: true });
            break;
          default:
            break;
        }
      } catch (err) {
        console.error("[MsalEventHandler] error:", err);
        clearMsalAuthInProgress();
        navigate(buildLoginMsalErrorPath(getMsalAuthErrorMessage(err)), { replace: true });
      } finally {
        processingRef.current = false;
      }
    },
    [navigate, login, shouldAbortMsalAutoLogin, abortIfNeeded]
  );

  const redirectHandledRef = useRef(false);

  useEffect(() => {
    const processRedirect = async () => {
      // handleRedirectPromise must run once per page load (MSAL consumes the response once)
      if (!redirectHandledRef.current) {
        redirectHandledRef.current = true;
        try {
          const result = await msalInstance.handleRedirectPromise();
          if (result?.account) {
            clearMsalAutoLoginSuppression();
            markMsalAuthInProgress();
            window.history.replaceState({}, document.title, window.location.pathname);
            await handleAccount(result.account, result.accessToken, { fromRedirect: true });
            return;
          }

          // msal-browser v5: handleRedirectPromise() returns null when the interaction
          // status key is missing from sessionStorage (e.g. cleared during the cross-origin
          // redirect), even though a real SSO redirect just happened.  Detect this case via
          // our own flag or the hash fragment that Microsoft put in the URL, clear any stuck
          // state, and fall back to processing whatever MSAL has in its cache.
          if (isMsalAuthInProgress() || hasPendingMsalRedirect()) {
            window.history.replaceState({}, document.title, window.location.pathname);
            // Clear BEFORE calling handleAccount so any early return inside it (e.g.
            // auth_type=msal && hasAuthArtifacts) does not leave the flag stuck.
            clearMsalAuthInProgress();
            const accounts = msalInstance.getAllAccounts();
            if (accounts.length > 0) {
              if (localStorage.getItem("auth_type") === "msal" && hasAuthArtifacts(false)) {
                // MSAL already has a valid cached session — AuthContext hydrated it on
                // mount, nothing more to do.
                return;
              }
              clearMsalAutoLoginSuppression();
              markMsalAuthInProgress();
              await handleAccount(accounts[0], null, { fromRedirect: true });
              return;
            }
            // Hash was present but MSAL has no cached account — redirect to login.
            // Include msalError so the auto-SSO effect does not immediately re-fire.
            navigate(
              buildLoginMsalErrorPath("SSO redirect could not be completed. Please try again."),
              { replace: true }
            );
            return;
          }
        } catch (err) {
          console.error("[MsalEventHandler] handleRedirectPromise error:", err);
          clearMsalAuthInProgress();
          navigate(buildLoginMsalErrorPath(getMsalAuthErrorMessage(err)), { replace: true });
        }
      }

      // Silent cached-account login only — never after sign-out or on the login page
      if (localStorage.getItem("auth_type") === "msal" && hasAuthArtifacts(false)) return;
      if (isMsalAutoLoginSuppressed()) return;
      if (location.pathname === "/login") return;
      const accounts = msalInstance.getAllAccounts();
      if (accounts.length > 0) {
        handleAccount(accounts[0]);
      }
    };
    processRedirect();
  }, [handleAccount, location.pathname]);

  return null;
};

// Defined OUTSIDE App so React never sees it as a new component type on re-renders.
// Placing it inside App caused Login to unmount/remount on every App state change,
// triggering all Login effects (superadmin check, dept fetch, etc.) repeatedly.
const DefaultRoute = () => {
  if (isMsalLoginPending()) return <MsalAuthLoader />;
  return <Navigate to="/login" replace />;
};

const PublicRoute = ({ children }) => {
  const { isAuthenticated, loading } = useAuth();
  const { hasPermission } = usePermissions();
  const [searchParams] = useSearchParams();
  const msalError = searchParams.get("msalError");
  const canExecuteAgents = hasPermission("execute_access.agents", true);

  if (!msalError && isMsalLoginPending()) return <MsalAuthLoader />;
  if (loading) return <MsalAuthLoader />;
  // Only skip login when fully authenticated — partial stale cookies must not redirect to app routes
  if (isAuthenticated) {
    return <Navigate to={canExecuteAgents ? "/" : "/tools"} replace />;
  }
  return children;
};

function App() {
  useErrorHandler(); // Calling error handler hook to catch errors from API calls across the application
  const { addMessage } = useMessage();

  // Initialize global error service
  useEffect(() => {
    globalErrorService.initialize(addMessage);
    return () => {
      globalErrorService.cleanup();
    };
  }, [addMessage]);

  // Absolute session timeout (14 days since login)
  useAutoLogout();
  // Idle timeout: log out after 20 minutes of no user activity
  useIdleTimeout();

  const { hasPermission } = usePermissions();
  const canExecuteAgents = hasPermission("execute_access.agents", true);

  const RuntimeErrorListener = () => {
    const { addMessage } = useMessage();
    useEffect(() => {
      const onError = (e) => {
        try {
          addMessage && addMessage("A runtime error occurred. Some data may not have loaded properly.", "error");
        } catch (_) {}
      };
      const onRejection = (e) => {
        try {
          addMessage && addMessage("An unexpected promise rejection occurred.", "error");
        } catch (_) {}
      };
      window.addEventListener("error", onError);
      window.addEventListener("unhandledrejection", onRejection);
      return () => {
        window.removeEventListener("error", onError);
        window.removeEventListener("unhandledrejection", onRejection);
      };
    }, [addMessage]);
    return null;
  };

  return (
    <>
      <GlobalComponent />
      <MessagePopup />
      <RuntimeErrorListener />
      <MsalEventHandler />
      {/* [MANUAL_TOKEN_MODE] — remove this line when removing the feature */}
      <ManualTokenModal />
      <Routes>
        <Route
          path="/login"
          element={
            <PublicRoute>
              <Login />
            </PublicRoute>
          }
        />
        <Route
          path="/auth/callback"
          element={<MsalAuthCallback />}
        />
        <Route
          path="/auth/callback/legacy"
          element={<OAuthCallback />}
        />
        <Route
          path="/select-department"
          element={<SelectDepartment />}
        />
        <Route
          path="/pending-approval"
          element={<PendingApproval />}
        />
        <Route
          path="/infy-agent/service-register"
          element={
            <PublicRoute>
              <Register />
            </PublicRoute>
          }
        />
        <Route
          path="/"
          element={
            <ProtectedRoute>
              {canExecuteAgents ? (
                <Layout>
                  <AskAssistant />
                </Layout>
              ) : (
                <Navigate to="/tools" replace />
              )}
            </ProtectedRoute>
          }
        />
        <Route
          path="/tools"
          element={
            <ProtectedRoute>
              <Layout>
                <AvailableTools />
              </Layout>
            </ProtectedRoute>
          }
        />
        <Route
          path="/agent"
          element={
            <ProtectedRoute>
              <Layout>
                <AvailableAgents />
              </Layout>
            </ProtectedRoute>
          }
        />
        <Route
          path="/workflows"
          element={
            <ProtectedRoute>
              <Layout>
                <Workflow />
              </Layout>
            </ProtectedRoute>
          }
        />
        <Route
          path="/servers"
          element={
            <ProtectedRoute>
              <Layout>
                <AvailableServers />
              </Layout>
            </ProtectedRoute>
          }
        />
        <Route
          path="/chat"
          element={
            <ProtectedRoute>
              {canExecuteAgents ? (
                <Layout>
                  <AskAssistant />
                </Layout>
              ) : (
                <Navigate to="/tools" replace />
              )}
            </ProtectedRoute>
          }
        />
        <Route
          path="/secret"
          element={
            <ProtectedRoute>
              <Layout>
                <VaultScreen />
              </Layout>
            </ProtectedRoute>
          }
        />
        <Route
          path="/groundtruth"
          element={
            <ProtectedRoute>
              <Layout>
                <GroundTruth />
              </Layout>
            </ProtectedRoute>
          }
        />
        <Route
          path="/dataconnector"
          element={
            <ProtectedRoute>
              <Layout>
                <DataConnectors />
              </Layout>
            </ProtectedRoute>
          }
        />
        <Route
          path="/resource-dashboard"
          element={
            <ProtectedRoute>
              <Layout>
                <ResourceDashboard />
              </Layout>
            </ProtectedRoute>
          }
        />
        <Route
          path="/files"
          element={
            <ProtectedRoute>
              <Layout>
                <FilesPage />
              </Layout>
            </ProtectedRoute>
          }
        />
        <Route
          path="/knowledge-base"
          element={
            <ProtectedRoute>
              <Layout>
                <KnowledgeBase />
              </Layout>
            </ProtectedRoute>
          }
        />
        <Route
          path="/hooks"
          element={
            <ProtectedRoute>
              <Layout>
                <HookRepository />
              </Layout>
            </ProtectedRoute>
          }
        />
        <Route
          path="/requests"
          element={
            <ProtectedRoute>
              <Layout>
                <Requests />
              </Layout>
            </ProtectedRoute>
          }
        />
        <Route
          path="/scheduler"
          element={
            <ProtectedRoute>
              <Layout>
                <Scheduler />
              </Layout>
            </ProtectedRoute>
          }
        />
        {/* default Route */}
        <Route path="*" element={<DefaultRoute />} />
        <Route
          path="/token-usage"
          element={
            <ProtectedRoute requiredRole={["USER", "DEVELOPER"]}>
              <Layout>
                <TokenUsagePage />
              </Layout>
            </ProtectedRoute>
          }
        />
        <Route
          path="/admin"
          element={
            <ProtectedRoute requiredRole="ADMIN">
              <Layout>
                <AdminScreenNew />
              </Layout>
            </ProtectedRoute>
          }
        />
        <Route
          path="/super-admin"
          element={
            <ProtectedRoute requiredRole="SUPERADMIN">
              <Layout>
                <SuperAdminControl />
              </Layout>
            </ProtectedRoute>
          }
        />
        <Route
          path="/evaluation"
          element={
            <ProtectedRoute>
              <Layout>
                <EvaluationPageNew />
              </Layout>
            </ProtectedRoute>
          }
        />
        <Route
          path="/llm-tracker"
          element={
            <ProtectedRoute>
              <Layout>
                <LLMTracker />
              </Layout>
            </ProtectedRoute>
          }
        />
      </Routes>
    </>
  );
}

export default App;