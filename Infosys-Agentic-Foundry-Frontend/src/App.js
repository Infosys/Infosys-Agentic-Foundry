import "./App.css";
import { useEffect } from "react";
import AvailableAgents from "./components/AvailableAgents/AvailableAgents";
import AskAssistant from "./components/AskAssistant/AskAssistant";
import { Navigate, Route, Routes } from "react-router-dom";
import Layout from "./components/Layout";
import AvailableTools from "./components/AvailableTools/AvailableTools";
import AvailableServers from "./components/AvailableTools/AvailableServers";
import Login from "./components/Login";
import { useMessage } from "./Hooks/MessageContext";
import MessagePopup from "./components/MessagePopup/MessagePopup";
import GlobalComponent from "./Hooks/GlobalComponent";
import Register from "./components/Register/Index";
import { useAuth } from "./context/AuthContext";
import ProtectedRoute from "./ProtectedRoute";
import AdminScreenNew from "./components/AdminScreen/AdminScreenNew";
import SuperAdminControl from "./components/AdminScreen/SuperAdminControl";
import VaultScreen from "./components/Vault/Vault";
import GroundTruth from "./components/GroundTruth/GroundTruth";
import DataConnectors from "./components/DataConnectors/DataConnectors";
import ResourceDashboard from "./components/ResourceDashboard/ResourceDashboard";
import EvaluationPageNew from "./components/EvaluationPage/EvaluationPageNew";
import KnowledgeBase from "./components/KnowledgeBase/KnowledgeBase";
import FilesPage from "./components/AskAssistant/FilesPage";
import useAutoLogout from "./Hooks/useAutoLogout";
import useErrorHandler from "./Hooks/useErrorHandler";
import { globalErrorService } from "./services/globalErrorService";
import Pipeline from "./components/Pipeline";

function App() {
  useErrorHandler(); // Calling error handler hook to catch errors from API calls across the application
  const { isAuthenticated, loading } = useAuth();
  const { addMessage } = useMessage();

  // Initialize global error service
  useEffect(() => {
    globalErrorService.initialize(addMessage);
    return () => {
      globalErrorService.cleanup();
    };
  }, [addMessage]);

  // install 6-hour absolute session auto logout
  useAutoLogout();

  const PublicRoute = ({ children }) => {
    if (loading) return null; // wait until auth hydrated
    if (isAuthenticated) {
      return <Navigate to="/" />;
    }
    return children;
  };

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
              <Layout>
                <AskAssistant />
              </Layout>
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
          path="/pipeline"
          element={
            <ProtectedRoute>
              <Layout>
                <Pipeline />
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
              <Layout>
                <AskAssistant />
              </Layout>
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
        {/* default Route */}
        <Route path="*" element={<Navigate to="/login" />} />
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
      </Routes>
    </>
  );
}

export default App;
