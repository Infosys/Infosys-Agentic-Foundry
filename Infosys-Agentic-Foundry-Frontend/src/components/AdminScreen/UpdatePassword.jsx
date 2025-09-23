import React, { useState, useEffect, useRef } from "react";
import styles from "./UpdatePassword.module.css";
import SVGIcons from "../../Icons/SVGIcons";
import Cookies from "js-cookie";
import { APIs } from "../../constant";
import Loader from "../commonComponents/Loader";
import useFetch from "../../Hooks/useAxios";
import "../Register/SignUp.css";

const roleOptions = ["Admin", "Developer", "User"];

const UpdatePassword = () => {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [retypePassword, setRetypePassword] = useState("");
  const [selectedOption, setSelectedOption] = useState("Select role");

  const [response, setResponse] = useState(null);
  const [error, setError] = useState(null);
  const [errors, setErrors] = useState({});
  const [touched, setTouched] = useState({});
  const [isOpen, setIsOpen] = useState(false);
  const [showLoader, setShowLoader] = useState(false);
  const [isSubmitDisabled, setIsSubmitDisabled] = useState(true);
  const { postData } = useFetch();

  const dropdownRef = useRef(null);

  useEffect(() => {
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = "auto";
    };
  }, []);
  const validate = () => {
    const newErrors = {};

    if (touched.email && !email) {
      newErrors.email = "Email is required";
    }
    const passwordRegex = /^(?=.*[A-Z])(?=.*\d)(?=.*[!@#$%^&*()_+[\]{};':"\\|,.<>/?]).{8,}$/;

    if (touched.password && password && !passwordRegex.test(password)) {
      newErrors.password = "Password must be at least 8 characters, include one uppercase letter, one number, and one special character";
    }
    if (touched.retypePassword) {
      if (!retypePassword && password) {
        newErrors.retypePassword = "Please confirm your password";
      } else if (retypePassword && password !== retypePassword) {
        newErrors.retypePassword = "Passwords do not match";
      }
    }
    if ((touched.password || touched.selectedOption) && !password && selectedOption === "Select role") {
      newErrors.form = "At least one of Password or Role must be provided";
    }

    setErrors(newErrors);
    const isFormValid = Object.keys(newErrors).length === 0 && (password || selectedOption !== "Select role");
    setIsSubmitDisabled(!isFormValid); // Disable submit if there are errors or no password/role selected

    return isFormValid;
  };

  useEffect(() => {
    validate();
  }, [email, password, retypePassword, selectedOption, touched]);

  const handleBlur = (field) => {
    setTouched((prev) => ({ ...prev, [field]: true }));
  };

  const handleOptionSelect = (option) => {
    setSelectedOption(option);
    setIsOpen(false);
    setTouched((prev) => ({ ...prev, selectedOption: true }));
  };

  const toggleDropdown = () => setIsOpen((prev) => !prev);

  const handleSubmit = async (e) => {
    setShowLoader(true);
    e.preventDefault();
    setTouched({
      email: true,
      password: true,
      retypePassword: true,
      selectedOption: true,
    });

    if (!validate()) return;
    // Create request body object
    const requestBody = {
      email_id: email,
      ...(password && { new_password: password }),
      ...(selectedOption!== "Select role" && { role: selectedOption }),
    };

    const url = APIs.UPDATE_PASSWORD_ROLE;

    try {
      const response = await postData(url, requestBody);
      const data = await response;
      setResponse(data?.message);
      setError(null);
      setShowLoader(false);
      setTimeout(() => setResponse(null), 5000);

      setEmail("");
      setPassword("");
      setRetypePassword("");
      setSelectedOption("Select role");
      setTouched({});
    } catch (err) {
      console.error(err);
      setError(err.message);
      setResponse(null);
      setShowLoader(false);
    }
  };

  return (
    <div className={styles.rootWrapper}>
      <div className={styles.updatePasswordContainers}>
        {showLoader ? <Loader /> : ""}
        <form onSubmit={handleSubmit} className="loginContainer">
          <div className="flexrow">
            <input type="email" value={email} placeholder="Email" className="login-input" onChange={(e) => setEmail(e.target.value)} onBlur={() => handleBlur("email")} />
            {touched.email && errors.email && <span className={styles.error}>{errors.email}</span>}
          </div>
          <div className="space-devider"></div>
          <div className="flexrow">
            <input
              type="password"
              value={password}
              placeholder="New Password"
              className="login-input"
              onChange={(e) => setPassword(e.target.value)}
              onBlur={() => handleBlur("password")}
            />
            {touched.password && errors.password && <span className={styles.error}>{errors.password}</span>}
          </div>
          <div className="space-devider"></div>
          <div className="flexrow">
            <input
              type="password"
              value={retypePassword}
              placeholder="Confirm Password"
              className="login-input"
              onChange={(e) => setRetypePassword(e.target.value)}
              onBlur={() => handleBlur("retypePassword")}
            />
            {touched.retypePassword && errors.retypePassword && <span className={styles.error}>{errors.retypePassword}</span>}
          </div>
          <div className="space-devider"></div>
          {/* Role Dropdown */}
          <div className="flexrow">
            <div className="dropdown" ref={dropdownRef}>
              <button
                type="button"
                className="dropdown-toggle"
                onClick={toggleDropdown}
                onBlur={(e) => {
                  if (!dropdownRef.current.contains(e.relatedTarget)) {
                    setTimeout(() => setIsOpen(false), 100);
                  }
                }}>
                {selectedOption}
                <div className="downbox">
                  <SVGIcons icon="downarrow" width={20} height={18} fill="#000000" />
                </div>
              </button>

              {isOpen && (
                <ul className="dropdown-menu">
                  {roleOptions.map((option) => (
                    <li key={option} tabIndex={0} onClick={() => handleOptionSelect(option)}>
                      {option}
                    </li>
                  ))}
                </ul>
              )}
            </div>
            <div className="space-devider"></div>
          </div>
          {errors.form && <div className={styles.errorBox}>{errors.form}</div>}
          {error && <div className={styles.errorBox}>{error}</div>}
          {response && <div className={styles.successBox}>{response}</div>}
          <div className="div-hyperstyle">
            <button type="submit" className="button-style" tabIndex={8} disabled={isSubmitDisabled}>
              <h2 className="signIntext"> Update User </h2>
              <div className="signarrow">
                <SVGIcons icon="rightarrow" width={20} height={18} fill="#fff" />
              </div>{" "}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};

export default UpdatePassword;
