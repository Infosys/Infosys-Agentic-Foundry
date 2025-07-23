import "./App.css";
import AskAssistant from "./components/AskAssistant/AskAssistant";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import Layout from "./components/Layout";
import { MessageProvider } from "./Hooks/MessageContext";
import MessagePopup from "./components/MessagePopup/MessagePopup";
import { GlobalComponentProvider } from "./Hooks/GlobalComponentContext";
import GlobalComponent from "./Hooks/GlobalComponent";
import Cookies from "js-cookie";
import { ApiUrlProvider } from "./context/ApiUrlContext";
import { VersionProvider } from "./context/VersionContext";
import { AuditProvider } from "./context/AuditContext";


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
              <Route
                path="/chat"
                element={
                  // <ProtectedRoute>
                    <Layout>
                      <AskAssistant />
                    </Layout>
                  // </ProtectedRoute>
                }
              />
              <Route
                path="/new-chat"
                element={
                  
                    <Layout>
                      <AuditProvider>
                      </AuditProvider>
                    </Layout>
                }
              />
            
              {/* default Route */}
              <Route path="*" element={<Navigate to="/chat" />} />

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
