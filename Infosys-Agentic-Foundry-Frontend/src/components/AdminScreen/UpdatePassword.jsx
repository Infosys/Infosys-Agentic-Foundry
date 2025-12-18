import { useState, useEffect, useRef } from "react";
import styles from "./UpdatePassword.module.css";
import SVGIcons from "../../Icons/SVGIcons";
import { APIs } from "../../constant";
import Loader from "../commonComponents/Loader";
import useFetch from "../../Hooks/useAxios";
import "../Register/SignUp.css";

const roleOptions = ["Admin", "Developer", "User"];

const UpdatePassword = () => {
  const [email, setEmail] = useState("");
  const [pwd, setPwd] = useState("");
  const [retypePwd, setretypePwd] = useState("");
  const [selectedOption, setSelectedOption] = useState("Select role");

  const [response, setResponse] = useState(null);
  const [errors, setErrors] = useState({
    pwd: "",
    newPwd: "",
    confirmPwd: "",
    api: "",
    form: "",
  });
  const [touched, setTouched] = useState({});
  const [isOpen, setIsOpen] = useState(false);
  const [showLoader, setShowLoader] = useState(false);
  const [isSubmitDisabled, setIsSubmitDisabled] = useState(true);
  const [showPassword, setShowPassword] = useState(false);
  const [showConfirmPassword, setShowConfirmPassword] = useState(false);
  const [hasPasswordInput, setHasPasswordInput] = useState(false);
  const [hasConfirmPasswordInput, setHasConfirmPasswordInput] = useState(false);
  const { postData } = useFetch();

  const dropdownRef = useRef(null);

  const togglePasswordVisibility = () => {
    setShowPassword((prev) => !prev);
  };
  const toggleConfirmPwdVisibility = () => {
    setShowConfirmPassword((prev) => !prev);
  };

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

    // SECURITY NOTE: This is a validation error message, not a hardcoded credential
    if (touched.pwd && pwd && !passwordRegex.test(pwd)) {
      newErrors.pwd = "Must be at least 8 characters, include one uppercase letter, one number, and one special character";
    }
    if (touched.retypePwd) {
      if (!retypePwd && pwd) {
        newErrors.retypePwd = "Please confirm your password";
      } else if (retypePwd && pwd !== retypePwd) {
        newErrors.retypePwd = "Passwords do not match";
      }
    }
    if ((touched.pwd || touched.selectedOption) && !pwd && selectedOption === "Select role") {
      newErrors.form = "At least one of Password or Role must be provided";
    }

    setErrors(newErrors);
    const isFormValid = Object.keys(newErrors).length === 0 && (pwd || selectedOption !== "Select role");

    setIsSubmitDisabled(!isFormValid); // Disable submit if there are errors or no pwd/role selected
    // Disable submit if there are errors or no pwd or no role selected
    return isFormValid;
  };

  useEffect(() => {
    validate();
  }, [email, pwd, retypePwd, selectedOption, touched]);

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
      pwd: true,
      retypePwd: true,
      selectedOption: true,
    });

    if (!validate()) return;
    // Create request body object
    const requestBody = {
      email_id: email,
      ...(pwd && { new_password: pwd }),
      ...(selectedOption !== "Select role" && { role: selectedOption }),
    };

    const url = APIs.UPDATE_PASSWORD_ROLE;

    try {
      const response = await postData(url, requestBody);
      const data = await response;
      setResponse(data?.message);
      setErrors({ pwd: "", newPwd: "", confirmPwd: "", api: "", form: "" });
      setShowLoader(false);
      setTimeout(() => setResponse(null), 5000);

      setEmail("");
      setPwd("");
      setretypePwd("");
      setSelectedOption("Select role");
      setShowPassword(false);
      setShowConfirmPassword(false);
      setHasPasswordInput(false);
      setHasConfirmPasswordInput(false);
      setTouched({});
    } catch (err) {
      console.error(err);
      setErrors({ ...errors, api: err.message });
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
          <div className="flexrow password-container">
            <div className="input-wrapper">
              <input
                type={showPassword ? "text" : "password"}
                value={pwd}
                placeholder="New Password"
                className="login-input"
                autoComplete="new-password"
                onChange={(e) => {
                  setPwd(e.target.value);
                  setHasPasswordInput(e.target.value.length > 0);
                }}
                onBlur={() => handleBlur("pwd")}
                onFocus={() => setHasPasswordInput(true)}
              />
              {hasPasswordInput && (
                <span className="eye-icon" onClick={togglePasswordVisibility}>
                  <SVGIcons icon={showPassword ? "eye-slash" : "eye"} fill="#d9d9d9" />
                </span>
              )}
            </div>
            {touched.pwd && errors.pwd && <span className={styles.error}>{errors.pwd}</span>}
          </div>
          <div className="space-devider"></div>
          <div className="flexrow password-container">
            <div className="input-wrapper">
              <input
                type={showConfirmPassword ? "text" : "password"}
                value={retypePwd}
                placeholder="Confirm Password"
                className="login-input"
                autoComplete="new-password"
                onChange={(e) => {
                  setretypePwd(e.target.value);
                  setHasConfirmPasswordInput(e.target.value.length > 0);
                }}
                onBlur={() => handleBlur("retypePwd")}
                onFocus={() => setHasConfirmPasswordInput(true)}
                maxLength={18}
              />
              {hasPasswordInput && hasConfirmPasswordInput && (
                <span className="eye-icon" onClick={toggleConfirmPwdVisibility}>
                  <SVGIcons icon={showConfirmPassword ? "eye-slash" : "eye"} fill="#d9d9d9" />
                </span>
              )}
            </div>
            {touched.retypePwd && errors.retypePwd && <span className={styles.error}>{errors.retypePwd}</span>}
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
          </div>
          {errors.form && <div className={styles.errorBox}>{errors.form}</div>}
          {errors.api && <div className={styles.errorBox}>{errors.api}</div>}
          {response && <div className={styles.successBox}>{response}</div>}
          <div className="submit-style">
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
