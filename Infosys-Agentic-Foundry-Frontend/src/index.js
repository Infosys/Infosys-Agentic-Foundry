import React from "react";
import ReactDOM from "react-dom/client";
import "./index.css";
import "./css_modules/ace-overrides.css"; // Global ACE font override
import { BrowserRouter } from "react-router-dom";
import AppProviders from "./providers/AppProviders";
import App from "./App";
import "./config/axiosInterceptors";
import { patchCookiesForPortScoping } from "./utils/cookieUtils";

// Monkey-patch js-cookie so auth cookies are port-scoped.
// This prevents session leakage between different ports (e.g. 3003 vs 6001).
patchCookiesForPortScoping();

const root = ReactDOM.createRoot(document.getElementById("root"));
root.render(
  <React.StrictMode>
    <BrowserRouter>
      <AppProviders>
        <App />
      </AppProviders>
    </BrowserRouter>
  </React.StrictMode>
);
