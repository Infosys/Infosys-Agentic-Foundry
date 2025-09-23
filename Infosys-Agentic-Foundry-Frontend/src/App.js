import "./App.css";
import ListOfAgents from "./components/ListOfAgents/ListOfAgents";
import AskAssistant from "./components/AskAssistant/AskAssistant";
import { Navigate, Route, Routes } from "react-router-dom";
import Layout from "./components/Layout";
import AvailableTools from "./components/AvailableTools/AvailableTools";
import Login from "./components/Login";
import { MessageProvider } from "./Hooks/MessageContext";
import MessagePopup from "./components/MessagePopup/MessagePopup";
import { GlobalComponentProvider } from "./Hooks/GlobalComponentContext";
import GlobalComponent from "./Hooks/GlobalComponent";
import Register from "./components/Register/Index";
import { useAuth } from "./context/AuthContext";
import ProtectedRoute from "./ProtectedRoute";
import AdminScreen from "./components/AdminScreen/AdminScreen";
import { ApiUrlProvider } from "./context/ApiUrlContext";
import { VersionProvider } from "./context/VersionContext";
import SecretKeys from "./components/Vault/Vault";
import GroundTruth from "./components/GroundTruth/GroundTruth";
import DataConnectors from "./components/DataConnectors/DataConnectors";
import EvaluationPage from "./components/EvaluationPage/EvaluationPage";
import useAutoLogout from "./Hooks/useAutoLogout";

function App() {
  const { isAuthenticated, loading } = useAuth();
  // install 6-hour absolute session auto logout
  useAutoLogout();
  const PublicRoute = ({ children }) => {
    if (loading) return null; // wait until auth hydrated
    if (isAuthenticated) {
      return <Navigate to="/" />;
    }
    return children;
  };

  return (
    <>
      <GlobalComponentProvider>
        <GlobalComponent />
        <MessageProvider>
          <MessagePopup />
          <VersionProvider>
            <ApiUrlProvider>
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
                        <ListOfAgents />
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
                        <SecretKeys />
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
                {/* default Route */}
                <Route path="*" element={<Navigate to="/login" />} />
                <Route
                  path="/admin"
                  element={
                    <ProtectedRoute requiredRole="ADMIN">
                      <Layout>
                        <AdminScreen />
                      </Layout>
                    </ProtectedRoute>
                  }
                />
                <Route
                  path="/evaluation"
                  element={
                    <ProtectedRoute requiredRole="ADMIN">
                      <Layout>
                        <EvaluationPage />
                      </Layout>
                    </ProtectedRoute>
                  }
                />
              </Routes>
            </ApiUrlProvider>
          </VersionProvider>
        </MessageProvider>
      </GlobalComponentProvider>
    </>
  );
}

export default App;
