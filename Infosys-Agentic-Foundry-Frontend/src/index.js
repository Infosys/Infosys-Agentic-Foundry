import React from "react";
import ReactDOM from "react-dom/client";
import "./index.css";
import "./css_modules/ace-overrides.css"; // Global ACE font override
import { BrowserRouter } from "react-router-dom";
import { SSEProvider } from "./context/SSEContext";
import { AuthProvider } from "./context/AuthContext";
import { VersionProvider } from "./context/VersionContext";
import { ApiUrlProvider } from "./context/ApiUrlContext";
import { MessageProvider } from "./Hooks/MessageContext";
import { GlobalComponentProvider } from "./Hooks/GlobalComponentContext";
import RobustErrorBoundary from "./components/ErrorBoundary/RobustErrorBoundary";
import App from "./App";
import "./config/axiosInterceptors"; // TEMPORARILY DISABLED FOR DEBUGGING

const root = ReactDOM.createRoot(document.getElementById("root"));
root.render(
  <React.StrictMode>
    <BrowserRouter>
      <AuthProvider>
        <VersionProvider>
          <ApiUrlProvider>
            <MessageProvider>
              <GlobalComponentProvider>
                <RobustErrorBoundary>
                  {/* <SSEProvider> */}
                  <App />
                  {/* </SSEProvider> */}
                </RobustErrorBoundary>
              </GlobalComponentProvider>
            </MessageProvider>
          </ApiUrlProvider>
        </VersionProvider>
      </AuthProvider>
    </BrowserRouter>
  </React.StrictMode>
);
