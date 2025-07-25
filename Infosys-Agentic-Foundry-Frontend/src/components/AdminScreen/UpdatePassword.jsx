import React, { useState, useEffect, useRef } from "react";
import styles from "./UpdatePassword.module.css";
import SVGIcons from "../../Icons/SVGIcons";
import Cookies from "js-cookie";
import { BASE_URL, APIs } from "../../constant";
import Loader from "../commonComponents/Loader";

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
    const passwordRegex =
      /^(?=.*[A-Z])(?=.*\d)(?=.*[!@#$%^&*()_+[\]{};':"\\|,.<>/?]).{8,}$/;

    if (touched.password && password && !passwordRegex.test(password)) {
      newErrors.password =
        "Password must be at least 8 characters, include one uppercase letter, one number, and one special character";
    }
    if (touched.retypePassword) {
      if (!retypePassword && password) {
        newErrors.retypePassword = "Please confirm your password";
      } else if (retypePassword && password !== retypePassword) {
        newErrors.retypePassword = "Passwords do not match";
      }
    }
    if (
      (touched.password || touched.selectedOption) &&
      !password &&
      selectedOption === "Select role"
    ) {
      newErrors.form = "At least one of Password or Role must be provided";
    }

    setErrors(newErrors);
    const isFormValid = Object.keys(newErrors).length === 0 &&
                        (password || selectedOption !== "Select role");
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

    const queryParams = new URLSearchParams({ email_id: email });

    if (password) {
      queryParams.append("new_password", password);
    }

    if (selectedOption !== "Select role") {
      queryParams.append("role", selectedOption);
    }

    const url = `${BASE_URL}${APIs.UPDATE_PASWORD_ROLE}?${queryParams.toString()}`;

    try {
      const response = await fetch(url, {
        method: "POST",
        headers: { accept: "application/json" },
      });
      if (!response.ok) throw new Error("Failed to update password and role");

      const data = await response.json();
      setResponse(data?.message);
      setError(null);
      setShowLoader(false);
      setTimeout(() => setResponse(null), 5000);

      setEmail(Cookies?.get("email") || "");
      setPassword("");
      setRetypePassword("");
      setSelectedOption("Select role");
      setTouched({});
    } catch (err) {
      console.error(err);
      setError(err.message);
      setResponse(null);
    }
  };

  return (
    <div className={styles.rootWrapper}>
      <div className={styles.updatePasswordContainers}>
        {showLoader ? <Loader /> : ""}
        <form onSubmit={handleSubmit} className={styles.forms}>
          <h3>Update User</h3>
          <div className={styles.inputGroups}>
            <input
              type="email"
              value={email}
              placeholder="Email"
              onChange={(e) => setEmail(e.target.value)}
              onBlur={() => handleBlur("email")}
            />
            {touched.email && errors.email && (
              <span className={styles.error}>{errors.email}</span>
            )}
          </div>
          <div className={styles.inputGroups}>
            <input
              type="password"
              value={password}
              placeholder="New Password"
              onChange={(e) => setPassword(e.target.value)}
              onBlur={() => handleBlur("password")}
            />
            {touched.password && errors.password && (
              <span className={styles.error}>{errors.password}</span>
            )}
          </div>
          <div className={styles.inputGroups}>
            <input
              type="password"
              value={retypePassword}
              placeholder="Confirm Password"
              onChange={(e) => setRetypePassword(e.target.value)}
              onBlur={() => handleBlur("retypePassword")}
            />
            {touched.retypePassword && errors.retypePassword && (
              <span className={styles.error}>{errors.retypePassword}</span>
            )}
          </div>

          {/* Role Dropdown */}
          <div className={styles.inputGroups}>
            <div className={styles.dropdowns} ref={dropdownRef}>
              <button
                type="button"
                className={styles.dropdownToggle}
                onClick={toggleDropdown}
                onBlur={(e) => {
                  if (!dropdownRef.current.contains(e.relatedTarget)) {
                    setTimeout(() => setIsOpen(false), 100);
                  }
                }}
              >
                {selectedOption}
                <div className={styles.downbox}>
                  <SVGIcons
                    icon="downarrow"
                    width={20}
                    height={18}
                    fill="#000000"
                  />
                </div>
              </button>

              {isOpen && (
                <ul className={styles.dropdownMenu}>
                  {roleOptions.map((option) => (
                    <li
                      key={option}
                      tabIndex={0}
                      onClick={() => handleOptionSelect(option)}
                    >
                      {option}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>
          {errors.form && <div className={styles.errorBox}>{errors.form}</div>}
          {error && <div className={styles.errorBox}>{error}</div>}
          {response && <div className={styles.successBox}>{response}</div>}
          <button
            type="submit"
            className={styles.submitButn}
            disabled={isSubmitDisabled} // Disable submit based on form validity
          >
            Submit
          </button>
        </form>
      </div>
    </div>
  );
};

export default UpdatePassword;
