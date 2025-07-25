import React from "react";
import "./Index.css";
import brandlogotwo from "../../Assets/Agentic-Foundry-Logo-Dark-2.png";
import SignUp from "./SignUp";
import { useVersion } from "../../context/VersionContext"; // Import version context hook

const Register = ({ isAdminScreen = false }) => {
  const { combinedVersion } = useVersion(); // Properly extract the combinedVersion from the hook
  
  return (
    <div className="app-container">
      <img src={brandlogotwo} alt="Brandlogo" />
      <div className="version_number" title={combinedVersion}>{combinedVersion}</div>
      <div className="div-login">
        <SignUp isAdminScreen={isAdminScreen} />
      </div>
    </div>
  );
}

export default Register;
