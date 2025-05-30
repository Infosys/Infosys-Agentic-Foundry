import React from "react";
import "./Index.css";
import brandlogotwo from "../../Assets/brandlogo2.png";
import SignUp from "./SignUp";

const Register = () => {
  return (
    <div className="app-container">
      <img src={brandlogotwo} alt="Brandlogo" />
      <div className="div-login">
        <SignUp />
      </div>
    </div>
  );
}

export default Register;
