import "./App.css";
import ListOfAgents from "./components/ListOfAgents/ListOfAgents";
import AskAssistant from "./components/AskAssistant/AskAssistant";
// import AgenticChat from "./components/AgenticChat/AgenticChat";
import { AuditProvider } from "./context/AuditContext";
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
import SecretKeys from "./components/AskAssistant/SecretKeys";
import GroundTruth from "./components/GroundTruth/GroundTruth";
import DataConnectors from "./components/DataConnectors/DataConnectors";


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
          <GlobalComponent />          <MessageProvider>
            <MessagePopup />
            <VersionProvider>
              <ApiUrlProvider>
                <Routes>
                <Route path="/login" element={<PublicRoute><Login /></PublicRoute>} />
                <Route path="/infy-agent/service-register" element={<PublicRoute><Register /></PublicRoute>} />
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
                      {/* <AskAssistant /> */}
                      <SecretKeys />
                      </Layout>
                        </ProtectedRoute>
                }/>
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
                  <ProtectedRoute >
                    <Layout>
                      <DataConnectors/>
                    </Layout>
                  </ProtectedRoute>
                }/>
              {/* <Route
                path="/new-chat"
                element={
                  <ProtectedRoute>
                    <Layout>
                      <AuditProvider>
                        <AgenticChat />
                      </AuditProvider>
                    </Layout>
                  </ProtectedRoute>
                }
              /> */}
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
              }/></Routes>
              </ApiUrlProvider>
            </VersionProvider>
          </MessageProvider>
        </GlobalComponentProvider>
      </BrowserRouter>
    </>
  );
}

export default App;
