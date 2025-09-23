import React from "react";
import ReactDOM from "react-dom/client";
import "./index.css";
import { BrowserRouter } from "react-router-dom";
import { SSEProvider } from "./context/SSEContext";
import { AuthProvider } from "./context/AuthContext";
import App from "./App";

const root = ReactDOM.createRoot(document.getElementById("root"));
root.render(
  <React.StrictMode>
    <BrowserRouter>
      <AuthProvider>
        {/* <SSEProvider> */}
        <App />
        {/* </SSEProvider> */}
      </AuthProvider>
    </BrowserRouter>
  </React.StrictMode>
);
