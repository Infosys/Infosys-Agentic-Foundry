import React, { useState, useRef } from "react";
import { useNavigate } from "react-router-dom";
import SVGIcons from "../../Icons/SVGIcons";
import "./SignUp.css";
import useFetch from "../../Hooks/useAxios";
import { APIs, roleOptions } from "../../constant";

const SignUp = ({ isAdminScreen = false }) => {
  const { postData, setJwtToken } = useFetch();

  const [email, setEmail] = useState("");
  const [errEmail, setErrEmail] = useState("");
  const [username, setUsername] = useState("");
  const [errUser, setErrUser] = useState("");

  // Use a ref instead to avoid storing in state
  const passwordRef = useRef("");
  const confirmPasswordRef = useRef("");

  // Add refs for the input fields
  const passwordInputRef = useRef(null);
  const confirmPasswordInputRef = useRef(null);

  // Add this state variable with your other state declarations
  const [hasPasswordInput, setHasPasswordInput] = useState(false);
  const [hasConfirmPasswordInput, setHasConfirmPasswordInput] = useState(false);

  const [errPass, setErrPass] = useState("");
  const [errConfirmPass, setErrConfirmPass] = useState("");
  const [msgSubmit, setMsgSubmit] = useState("");
  const [msgSubmitApproval, setMsgSubmitApproval] = useState(false);
  const [showPassword, setShowPassword] = useState(false);
  const [showConfirmPassword, setShowConfirmPassword] = useState(false);
  const [isOpen, setIsOpen] = useState(false);
  const [selectedOption, setSelectedOption] = useState("Select Role");

  const navigate = useNavigate();

  const togglePasswordVisibility = () => {
    setShowPassword((prev) => !prev);
  };
  const toggleConfirmPwdVisibility = () => {
    setShowConfirmPassword((prev) => !prev);
  };
  // Create a ref for the dropdown
  const dropdownRef = useRef(null);

  // Handle clicking outside the dropdown to close it
  React.useEffect(() => {
    function handleClickOutside(event) {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target)) {
        setIsOpen(false);
      }
    }

    // Add event listener when dropdown is open
    if (isOpen) {
      document.addEventListener("mousedown", handleClickOutside);
    }

    // Clean up
    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
    };
  }, [isOpen]);

  const toggleDropdown = () => {
    setIsOpen(!isOpen);
  };

  const handleOptionSelect = (option) => {
    setSelectedOption(option);
    setIsOpen(false);
  };

  const emailChange = (value) => {
    // Write a most commonly used Regex for email validation that validates most commonly used and possible email formats
    const emailRegex = /^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$/;

    setEmail(value);
    if (value) {
      if (!emailRegex.test(value)) {
        setErrEmail("Please enter a valid email address");
      } else {
        setErrEmail("");
      }
    } else {
      setErrEmail("");
    }
  };

  const usernameChange = (value) => {
    setUsername(value);
    // Allow only letters, numbers and spaces (no special characters)
    const UsernameRegex = /^[A-Za-z0-9 ]+$/;

    if (value) {
     if (!UsernameRegex.test(value)) {
        setErrUser("Username can only contain letters, numbers and spaces");
     } else if (value?.length < 3) {
        setErrUser("Username must be at least 3 characters long");
      } else {
        setErrUser("");
      }
    } else {
      setErrUser("");
    }
  };

  const passwordChange = (value) => {
    const passwordRegex = /^(?=.*[a-zA-Z])(?=.*\d)(?=.*[!@#$%^&*()_+~`|}{[\]:;?><,./])/;
    // Store the password in the ref instead of state to overcome vulnerability
    passwordRef.current = value;

    // Update state to track if password field has content
    setHasPasswordInput(value.length > 0);

    if (value) {
      if (value?.length < 6) {
        setErrPass("Password must be atleast 6 characters long");
      } else if (value?.length > 15) {
        setErrPass("Password is too long");
      } else if (!passwordRegex.test(value)) {
        setErrPass("Password must have 1 letter,1 number and 1 special character");
      } else {
        setErrPass("");
      }
    } else {
      setErrPass("");
    }
  };
  const confirmPasswordChange = (value) => {
    // setConfirmPassword(value);
    // Store the password in the ref instead of state to overcome vulnerability
    confirmPasswordRef.current = value;

    // Update state to track if password field has content
    setHasConfirmPasswordInput(value.length > 0);

    if (value !== passwordRef.current) {
      setErrConfirmPass("Passwords do not match");
    } else {
      setErrConfirmPass("");
    }
  };

  // Helper to pull any autofilled values (password manager / browser) into refs just-in-time
  const syncAutofilledPasswords = () => {
    if (passwordInputRef.current) {
      const val = passwordInputRef.current.value;
      if (val && !passwordRef.current) {
        passwordRef.current = val;
        setHasPasswordInput(true);
      }
    }
    if (confirmPasswordInputRef.current) {
      const val2 = confirmPasswordInputRef.current.value;
      if (val2 && !confirmPasswordRef.current) {
        confirmPasswordRef.current = val2;
        setHasConfirmPasswordInput(true);
      }
    }
  };

  const onSubmit = async (e) => {
    e.preventDefault();

    // Ensure refs reflect any browser‑autofilled values before validation
    syncAutofilledPasswords();

    if (email && username && passwordRef.current && selectedOption !== "Select Role") {
      if (passwordRef.current !== confirmPasswordRef.current) {
        setErrConfirmPass("Passwords do not match");
        return;
      }
      if (errEmail || errUser || errPass || errConfirmPass) {
        return;
      }

      try {
        const user = await postData(APIs.REGISTER, {
          email_id: email,
          password: passwordRef.current,
          role: selectedOption,
          user_name: username,
        });

        // Set JWT Token
        if (user?.token) {
          setJwtToken(user.token);
        }

        if (user.approval) {
          setMsgSubmit(user.message);
          setMsgSubmitApproval(user.approval);

          if (isAdminScreen) {
            // If registration happens from AdminScreen, just show a success message
            setMsgSubmit("User created successfully!");

            // Clear the input fields
            setEmail("");
            setUsername("");

            // Clear the password fields
            passwordRef.current = "";
            confirmPasswordRef.current = "";

            // Reset the actual input elements
            if (passwordInputRef.current) passwordInputRef.current.value = "";
            if (confirmPasswordInputRef.current) confirmPasswordInputRef.current.value = "";

            setShowPassword(false);
            setShowConfirmPassword(false);
            clearError();
            setSelectedOption("Select Role");
          } else {
            // If registration happens from the regular signup page, navigate to login
            setTimeout(() => {
              navigate("/login");
            }, 3000);
          }
        } else {
          setMsgSubmit(user.message);
          setMsgSubmitApproval(user.approval);
          clearError();
        }
        // Clear the password from memory after use
        passwordRef.current = "";
        confirmPasswordRef.current = "";
      } catch (error) {
        setMsgSubmit("Something went wrong");
        setMsgSubmitApproval(false);
        clearError();
      }
    } else {
      setMsgSubmit("Please fill all the fields");
      setMsgSubmitApproval(false);
      clearError();
    }
  };

  const clearError = () => {
    setTimeout(() => {
      setMsgSubmit("");
      setMsgSubmitApproval(false);
    }, 3000);
  };
  
  const formContent = (
    <div className="loginContainer" style={isAdminScreen ? { maxWidth: "450px" } : {}}>
      {!isAdminScreen && <h3 className="title">Register</h3>}
      <form onSubmit={onSubmit}>
        {/* Email */}
        <div className="flexrow">
          <input
            type="email"
            name="Email"
            className="login-input"
            placeholder="Email"
            value={email}
            onChange={(e) => emailChange(e.target.value)}
            autoComplete="email"
            tabIndex={1}
          />
          {errEmail && <span className="error-style">{errEmail}</span>}
        </div>
        <div className="space-devider"></div>
        <div className="flexrow">
          <input
            type="text"
            name="Username"
            className="login-input"
            placeholder="User name"
            value={username}
            onChange={(e) => usernameChange(e.target.value)}
            autoComplete="username"
            tabIndex={2}
          />
          {errUser && <span className="error-style">{errUser}</span>}
        </div>
        <div className="space-devider"></div>
        {/* password */}
        <div className="flexrow password-container">
          <div className="input-wrapper">
            <input
              type={showPassword ? "text" : "password"}
              name="Password"
              className="login-input"
              placeholder="Password"
              onChange={(e) => passwordChange(e.target.value)}
              ref={passwordInputRef}
              autoComplete="new-password"
              tabIndex={3}
              onFocus={() => setHasPasswordInput(true)}
              maxLength={18}
            />
            {hasPasswordInput && (
              <span className="eye-icon" onClick={togglePasswordVisibility}>
                <SVGIcons icon={showPassword ? "eye-slash" : "eye"} fill="#d9d9d9" />
              </span>
            )}
          </div>
          {errPass && <span className="error-style">{errPass}</span>}
        </div>
        <div className="space-devider"></div>
        {/* confirm password */}
        <div className="flexrow password-container">
          <div className="input-wrapper">
            <input
              type={showConfirmPassword ? "text" : "password"}
              name="ConfirmPassword"
              className="login-input"
              placeholder="Confirm Password"
              onChange={(e) => confirmPasswordChange(e.target.value)}
              ref={confirmPasswordInputRef}
              autoComplete="new-password"
              tabIndex={4}
              onFocus={() => setHasConfirmPasswordInput(true)}
              maxLength={18}
            />
            {hasPasswordInput && hasConfirmPasswordInput && (
              <span className="eye-icon" onClick={toggleConfirmPwdVisibility}>
                <SVGIcons icon={showConfirmPassword ? "eye-slash" : "eye"} fill="#d9d9d9" />
              </span>
            )}
          </div>
          {errConfirmPass && <span className="error-style">{errConfirmPass}</span>}
        </div>
        <div className="space-devider"></div>{" "}
        <div className="dropdown" ref={dropdownRef}>
          <button
            type="button"
            className="dropdown-toggle"
            onClick={toggleDropdown}
            tabIndex={5}
            onBlur={(e) => {
              // Only close if focus is moving outside the dropdown
              if (!dropdownRef.current.contains(e.relatedTarget)) {
                setTimeout(() => setIsOpen(false), 100);
              }
            }}
            onKeyDown={(e) => {
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                toggleDropdown();
              } else if (e.key === "Escape") {
                setIsOpen(false);
              }
            }}>
            {selectedOption}
            <div className="downbox">
              <SVGIcons icon="downarrow" width={20} height={18} fill="#000000" />
            </div>
          </button>{" "}
          {isOpen && (
            <ul className="dropdown-menu">
              {roleOptions.map((option, index) => (
                <li
                  key={option}
                  onClick={() => handleOptionSelect(option)}
                  tabIndex={0}
                  onBlur={(e) => {
                    // Close if focus is moving outside the dropdown
                    if (!dropdownRef.current.contains(e.relatedTarget)) {
                      setTimeout(() => setIsOpen(false), 100);
                    }
                  }}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === " ") {
                      e.preventDefault();
                      handleOptionSelect(option);
                    } else if (e.key === "Tab" && option === roleOptions[roleOptions.length - 1] && !e.shiftKey) {
                      // Close dropdown when tabbing from the last item
                      setTimeout(() => setIsOpen(false), 100);
                    }
                  }}>
                  {option}
                </li>
              ))}
            </ul>
          )}
        </div>
        <div className="space-devider"></div>
        <div>{msgSubmit && <span className={msgSubmitApproval === true ? "success-style" : "error-style"}>{msgSubmit}</span>}</div>
        {isAdminScreen ? (
          // Admin screen layout - just the button
          <div className="div-hyperstyle">
            <button
              type="submit"
              className="button-style"
              tabIndex={8}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault();
                  onSubmit(e);
                }
              }}>
              <h2 className="signIntext"> Sign Up </h2>
              <div className="signarrow">
                <SVGIcons icon="rightarrow" width={20} height={18} fill="#fff" />
              </div>{" "}
            </button>
          </div>
        ) : (
          // Regular page layout - with remember me and login link
          <div className="submit-style">
            <div className="remember-style">
              <input type="checkbox" name="Remember me" className="checkbox" tabIndex={6} />
              <span style={{ fontSize: 12, marginLeft: 8, bottom: 5 }}>Remember me </span>
            </div>
            <div className="div-hyperstyle">
              <a href="/login" className="hyperlink" tabIndex={7}>
                Login
              </a>{" "}
              <button
                type="submit"
                className="button-style"
                tabIndex={8}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    onSubmit(e);
                  }
                }}>
                <h2 className="signIntext"> Sign Up </h2>
                <div className="signarrow">
                  <SVGIcons icon="rightarrow" width={20} height={18} fill="#fff" />
                </div>{" "}
              </button>
            </div>
          </div>
        )}
      </form>
    </div>
  );
  
  // Wrap in a flex container when in admin screen to match UpdatePassword layout
  return isAdminScreen ? <div style={{ display: "flex" }}>{formContent}</div> : formContent;
};

export default SignUp;
