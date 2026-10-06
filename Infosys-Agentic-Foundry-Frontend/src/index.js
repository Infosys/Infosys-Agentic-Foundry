import React from "react";
import ReactDOM from "react-dom/client";
import "./index.css";
import "./css_modules/ace-overrides.css"; // Global ACE font override
import { BrowserRouter } from "react-router-dom";
import { MsalProvider } from "@azure/msal-react";
import { msalInstance } from "./auth/msalConfig";
import AppProviders from "./providers/AppProviders";
import App from "./App";
import "./config/axiosInterceptors";
import { patchCookiesForPortScoping } from "./utils/cookieUtils";

// Enforce HTTPS in production before any rendering starts (defense-in-depth;
// primary enforcement is nginx's HTTP→HTTPS redirect + HSTS header).
// Localhost is excluded so local development is unaffected.
if (
  window.location.protocol === "http:" &&
  window.location.hostname !== "localhost" &&
  window.location.hostname !== "127.0.0.1"
) {
  window.location.replace("https:" + window.location.href.slice("http:".length));
}

// Monkey-patch js-cookie so auth cookies are port-scoped.
// This prevents session leakage between different ports (e.g. 3003 vs 6001).
patchCookiesForPortScoping();

const root = ReactDOM.createRoot(document.getElementById("root"));

// MSAL v3+ requires initialize() before any other API (handleRedirectPromise, etc.)
msalInstance.initialize().then(() => {
  root.render(
    <React.StrictMode>
      <MsalProvider instance={msalInstance}>
        <BrowserRouter>
          <AppProviders>
            <App />
          </AppProviders>
        </BrowserRouter>
      </MsalProvider>
    </React.StrictMode>
  );
});
