import React, { useState, useRef, useEffect } from "react";
import "./login.css";
import { useNavigate } from "react-router-dom";
import SVGIcons from "../../Icons/SVGIcons";
import useFetch from "../../Hooks/useAxios";
import Cookies from "js-cookie";
import { useAuth } from "../../context/AuthContext";
import { APIs, roleOptions } from "../../constant";
import { setSessionStart } from "../../Hooks/useAutoLogout";

function LoginScreen() {
  const { login } = useAuth();
  const { postData, fetchData, setJwtToken } = useFetch();
  const [email, setEmail] = useState("");
  const [errEmail, setErrEmail] = useState("");
  // Use a ref instead to avoid storing in state
  const passwordRef = useRef("");
  // Add this state variable with your other state declarations
  const [hasPasswordInput, setHasPasswordInput] = useState(false);

  const [errPass, setErrPass] = useState("");
  const [errSubmit, setErrSubmit] = useState(false);
  const [msgSubmit, setMsgSubmit] = useState("");
  const [showPassword, setShowPassword] = useState(false);

  const navigate = useNavigate();
  const [isOpen, setIsOpen] = useState(false);
  const [selectedOption, setSelectedOption] = useState("Select Role");
  const [validationError, setValidationError] = useState("");
  const dropdownRef = useRef(null);

  // Handle clicking outside the dropdown
  useEffect(() => {
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

  // Check for autofilled values periodically
  useEffect(() => {
    // Check for autofill after component mounts and when page loads
    const timeoutId = setTimeout(checkForAutofill, 100);

    // Add event listeners for when autofill might occur
    const handlePageLoad = () => checkForAutofill();
    const handleFocus = () => setTimeout(checkForAutofill, 50);

    window.addEventListener("load", handlePageLoad);
    document.addEventListener("focusin", handleFocus);

    return () => {
      clearTimeout(timeoutId);
      window.removeEventListener("load", handlePageLoad);
      document.removeEventListener("focusin", handleFocus);
    };
  }, []);

  const togglePasswordVisibility = () => {
    setShowPassword((prev) => !prev);
  };

  const toggleDropdown = () => {
    setIsOpen(!isOpen);
  };
  // Function to check for autofilled values
  const checkForAutofill = () => {
    const emailInput = document.querySelector('input[name="Email"]');
    if (emailInput && emailInput.value && emailInput.value !== email) {
      const emailValue = emailInput.value;
      setEmail(emailValue);

      // Validate the autofilled email without triggering onChange
      const emailRegex = /^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$/;
      if (emailValue) {
        if (!emailRegex.test(emailValue)) {
          setErrEmail("Please enter a valid email address");
        } else {
          setErrEmail("");
        }
      }

      // Clear validation error if email is filled
      if (validationError && emailValue) {
        setValidationError("");
      }
    }
  };

  const handleOptionSelect = (option) => {
    // Check for autofilled values first
    checkForAutofill();

    // Get current password value from ref
    const passwordValue = passwordRef.current;
    // Get actual email value to handle autofill
    const emailInput = document.querySelector('input[name="Email"]');
    const actualEmailValue = emailInput ? emailInput.value : email;

    // Check if email and password are empty
    if (!actualEmailValue && !passwordValue) {
      setValidationError("Please fill all required details or login as guest");
      setSelectedOption(option);
      setIsOpen(false);
      return;
    }

    // Clear any previous validation errors
    setValidationError("");

    setSelectedOption(option);
    setIsOpen(false);
  };
  const emailChange = (value) => {
    const emailRegex = /^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$/;
    setEmail(value);

    // Clear validation error when user starts typing
    if (validationError && value) {
      setValidationError("");
    }

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

  const passwordChange = (value) => {
    const passwordRegex = /^(?=.*[a-zA-Z])(?=.*\d)(?=.*[!@#$%^&*()_+~`|}{[\]:;?><,./])/;
    // Store the password in the ref instead of state to overcome vulnerability
    passwordRef.current = value;

    // Update state to track if password field has content
    setHasPasswordInput(value.length > 0);

    // Clear validation error when user starts typing password
    if (validationError && value) {
      setValidationError("");
    }

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

  const clearError = () => {
    setTimeout(() => {
      setMsgSubmit("");
    }, 3000);
  };
  const onSubmit = async () => {
    try {
      // Clear any validation errors when submitting
      setValidationError("");

      // Get the actual email value from DOM to handle autofill
      const emailInput = document.querySelector('input[name="Email"]');
      const actualEmailValue = emailInput ? emailInput.value : email;

      // Update email state if autofill was used
      if (actualEmailValue && actualEmailValue !== email) {
        setEmail(actualEmailValue);
      }

      if (actualEmailValue === "" || passwordRef.current === "" || selectedOption === "Select Role") {
        setErrSubmit(true);
        setMsgSubmit("Please fill up all the fields");
        clearError();
      } else if (errEmail || errPass) {
        setErrSubmit(true);
        setMsgSubmit("Please enter proper value in input field");
        clearError();
      } else {
        const users = await postData(APIs.LOGIN, {
          email_id: actualEmailValue,
          password: passwordRef.current,
          role: selectedOption,
        });

        // Setting JWT token
        if (users?.token) {
          setJwtToken(users.token);
        }

        if (users.approval) {
          // update context + cookies centrally
          const apiUrl = `${APIs.GET_NEW_SESSION_ID}`;
          let sessionIdResponse = (await fetchData(apiUrl)) || null;

          login({
            userName: users.user_name || users.username,
            user_session: sessionIdResponse,
            role: users.role,
          });
          Cookies.set("email", users.email);
          setSessionStart();
          navigate("/");
          setMsgSubmit("Success");
          clearError();
          setErrSubmit(false);
        } else {
          setErrSubmit(true);
          setMsgSubmit(users.message);
          clearError();
        }

        // Clear the password from memory after use
        // passwordRef.current = "";
      }
    } catch (error) {
      // Clear the password from memory after use
      // passwordRef.current = "";
      setErrSubmit(true);
      setMsgSubmit("An error occurred. Please try again.");
      clearError();
    }
  };
  const handleGuestLogin = async (e) => {
    e.preventDefault();
    // Clear any validation errors when using guest login
    setValidationError("");
    try {
      const users = await fetchData(APIs.GUEST_LOGIN);

      if (users.approval) {
        const apiUrl = `${APIs.GET_NEW_SESSION_ID}`;
        let sessionIdResponse = (await fetchData(apiUrl)) || null;
        login({
          userName: users.user_name || users.username,
          user_session: sessionIdResponse,
          role: users.role || "Guest",
        });
        Cookies.set("email", users.email);
        setSessionStart();

        // Setting JWT token
        if (users?.token) {
          setJwtToken(users.token);
        }

        navigate("/");
        setMsgSubmit(users.message || "Guest login successful");
        clearError();
        setErrSubmit(false);
      } else {
        setErrSubmit(true);
        setMsgSubmit(users.message || "Guest Login Failed");
        clearError();
      }
    } catch (error) {
      console.error("Guest login error:", error); // Log the detailed error
      setErrSubmit(true);
      setMsgSubmit("An error occurred. Please try again.");
      clearError();
    }
  };

  return (
    <form
      className="loginContainer"
      onSubmit={(e) => {
        e.preventDefault();

        // Get the actual email value from DOM to handle autofill
        const emailInput = document.querySelector('input[name="Email"]');
        const actualEmailValue = emailInput ? emailInput.value : email;

        // Update email state if autofill was used
        if (actualEmailValue && actualEmailValue !== email) {
          setEmail(actualEmailValue);
        }

        // Check if validation error exists or fields are empty
        if (validationError || !actualEmailValue || !passwordRef.current || selectedOption === "Select Role") {
          // Show validation error if needed
          if (!actualEmailValue && !passwordRef.current) {
            setValidationError("Please fill all required details or login as guest");
          } else {
            // Normal submit validation
            setErrSubmit(true);
            setMsgSubmit("Please fill up all the fields");
            clearError();
          }
          return;
        }
        // If all is good, submit the form
        onSubmit();
      }}>
      <h3 className="title">Sign In</h3>
      {/* email */}{" "}
      <div className="flexrow">
        <input
          type="text"
          name="Email"
          className="loginPage-input"
          placeholder="Email"
          value={email}
          onChange={(e) => emailChange(e.target.value)}
          onFocus={() => {
            // Check for autofill when field gains focus
            setTimeout(checkForAutofill, 100);
          }}
          onBlur={() => {
            // Check for autofill when field loses focus
            setTimeout(checkForAutofill, 100);
          }}
          tabIndex={1}
          autoComplete="username"
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
            }
          }}
        />
        {errEmail && <span className="error-style">{errEmail}</span>}
      </div>
      <div className="space-devider"></div>
      {/* password */}
      <div className="flexrow password-container">
        <div className="input-wrapper">
          {" "}
          <input
            type={showPassword ? "text" : "password"}
            name="Password"
            className="loginPage-input"
            placeholder="Password"
            autoComplete="current-password"
            onChange={(e) => passwordChange(e.target.value)}
            tabIndex={2}
            onFocus={() => setHasPasswordInput(true)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
              }
            }}
          />{" "}
          {/*  Removed the value prop value={password} modified to ref to overcome vulnerability issue */}
          {hasPasswordInput && (
            <span className="eye-icon" onClick={togglePasswordVisibility}>
              <SVGIcons icon={showPassword ? "eye-slash" : "eye"} fill="#d9d9d9" />
            </span>
          )}
        </div>
        {errPass && <span className="error-style">{errPass}</span>}
      </div>{" "}
      <div className="space-devider"></div>{" "}
      <div className="dropdown" ref={dropdownRef}>
        <button
          type="button"
          className="dropdown-toggle"
          onClick={toggleDropdown}
          tabIndex={3}
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
        </button>
        {isOpen && (
          <ul className="dropdown-menu">
            {roleOptions.map((option) => (
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
            ))}{" "}
          </ul>
        )}
      </div>
      {validationError && <div className="validation-error">{validationError}</div>}
      <div className="space-devider"></div>
      <div>{msgSubmit && <span className={msgSubmit === "Success" ? "success-style" : "error-style"}>{msgSubmit}</span>}</div>
      <div className="submit-style">
        {/* login as guest button */}
        <button type="button" className="button-style" onClick={(e) => handleGuestLogin(e)}>
          <h2 className="signIntext"> Login as Guest </h2>
          <div className="signarrow">
            <SVGIcons icon="rightarrow" width={20} height={18} fill="#fff" />
          </div>
        </button>

        <div className="div-hyperstyle">
          {/* <a href="/infy-agent/service-register" className="hyperlink">
            Register
          </a> */}
          <button type="button" className="button-style" onClick={() => onSubmit()} icon>
            <h2 className="signIntext"> Sign In </h2>
            <div className="signarrow">
              <SVGIcons icon="rightarrow" width={20} height={18} fill="#fff" />
            </div>
          </button>
        </div>
      </div>
    </form>
  );
}

export default LoginScreen;
