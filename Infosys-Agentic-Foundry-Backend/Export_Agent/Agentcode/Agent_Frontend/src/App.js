import "./App.css";
import ListOfAgents from "./components/ListOfAgents/ListOfAgents";
import AskAssistant from "./components/AskAssistant/AskAssistant";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import Layout from "./components/Layout";
import AvailableTools from "./components/AvailableTools/AvailableTools";
import Login from "./components/Login";
import { MessageProvider } from "./Hooks/MessageContext";
import MessagePopup from "./components/MessagePopup/MessagePopup";
import { GlobalComponentProvider } from "./Hooks/GlobalComponentContext";
import GlobalComponent from "./Hooks/GlobalComponent";
import Register from "./components/Register/Index";
import Cookies from "js-cookie";
import ProtectedRoute from "./ProtectedRoute";
import AdminScreen from "./components/AdminScreen/AdminScreen";
import { ApiUrlProvider } from "./context/ApiUrlContext";
import { VersionProvider } from "./context/VersionContext";
import SecretKeys from "./components/Vault/Vault";
import GroundTruth from "./components/GroundTruth/GroundTruth";
import DataConnectors from "./components/DataConnectors/DataConnectors";
import EvaluationPage from "./components/EvaluationPage/EvaluationPage";

function App() {
  const PublicRoute = ({ children }) => {
    const username = Cookies.get("userName");
    const session_id = Cookies.get("session_id");

    if (username && session_id) {
      return <Navigate to="/" />;
    }

    return children;
  };

  return (
    <>
      <BrowserRouter>
        <GlobalComponentProvider>
          <GlobalComponent />
          <MessageProvider>
            <MessagePopup />
            <VersionProvider>
              <ApiUrlProvider>
                <Routes>
                  
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
              <Route path="*" element={<Navigate to="/chat" />} />
              <Route
                path="/admin"
                element={
                  <ProtectedRoute requiredRole="ADMIN">
                    <Layout>
                      <AdminScreen />
                    </Layout>
                  </ProtectedRoute>
              }/>
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
      </BrowserRouter>
    </>
  );
}

export default App;
