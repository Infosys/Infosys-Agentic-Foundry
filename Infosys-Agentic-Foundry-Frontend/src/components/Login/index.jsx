import React from "react";
import "./app.css";
import brandlogotwo from "../../Assets/Agentic-Foundry-Logo-Dark-2.png";
import LoginScreen from "./LoginScreen";
import {useVersion} from "../../context/VersionContext"; // Import version context hook

function Login() {
  const { combinedVersion } = useVersion(); // Properly extract the combinedVersion from the hook
  
  return (
    <div className="app-container">
      <img src={brandlogotwo} alt="Brandlogo" />
      <div className="version_number" title={combinedVersion}>{combinedVersion}</div>
      <div className="div-login">
        <LoginScreen />
      </div>
    </div>
  );
}

export default Login;
