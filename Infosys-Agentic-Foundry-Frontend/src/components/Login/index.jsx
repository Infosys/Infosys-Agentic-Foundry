import React from "react";
import "./app.css";
import brandlogotwo from "../../Assets/brandlogo2.png";
import LoginScreen from "./LoginScreen";
function Login() {
  return (
    <div className="app-container">
      <img src={brandlogotwo} alt="Brandlogo" />
      {/* <h2 className="page-title">Agentic <span className="page-subtitle">Workflow</span></h2> */}
      {/* LoginScrren */}
      <div className="div-login">
        <LoginScreen />
      </div>
    </div>
  );
}

export default Login;
