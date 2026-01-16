import React from "react";
import ReactDOM from "react-dom/client";
import "./index.css";
import "./css_modules/ace-overrides.css"; // Global ACE font override
import { BrowserRouter } from "react-router-dom";
import AppProviders from "./providers/AppProviders";
import App from "./App";
import "./config/axiosInterceptors";

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
