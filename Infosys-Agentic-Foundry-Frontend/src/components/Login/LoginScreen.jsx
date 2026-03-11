import React, { useState, useRef, useEffect, useCallback } from "react";
import { createPortal } from "react-dom";
import { useNavigate } from "react-router-dom";
import SVGIcons from "../../Icons/SVGIcons";
import useFetch from "../../Hooks/useAxios";
import Cookies from "js-cookie";
import { useAuth, getActiveUser } from "../../context/AuthContext";
import { APIs, BASE_URL } from "../../constant";
import { setSessionStart } from "../../Hooks/useAutoLogout";
import useErrorHandler from "../../Hooks/useErrorHandler";
import axios from "axios";
import NewCommonDropdown from "../commonComponents/NewCommonDropdown";
import ContactModal from "./ContactModal";
import "./login.css";

function LoginScreen() {
  const { login, forceReplaceLogin, syncFromCookies, isAuthenticated, user } = useAuth();
  const { postData, fetchData, setJwtToken, setRefreshToken } = useFetch();
  const { handleApiError } = useErrorHandler(); // centralized handlers

  // numeric constants to avoid magic-number lint errors
  const AUTOFILL_TIMEOUT_MS = 100;
  const AUTOFILL_FOCUS_TIMEOUT_MS = 50;
  const PASSWORD_MIN = 6;
  const PASSWORD_MAX = 15;
  const CLEAR_MSG_TIMEOUT_MS = 3000;

  const [email, setEmail] = useState("");
  const [errEmail, setErrEmail] = useState("");
  // Use a ref instead to avoid storing in state
  const passwordRef = useRef("");
  // Add this state variable with your other state declarations
  const [hasPasswordInput, setHasPasswordInput] = useState(false);

  // navigation
  const navigate = useNavigate();

  // departments state
  const [departments, setDepartments] = useState([]);
  const [deptLoading, setDeptLoading] = useState(false);
  const [selectedDepartment, setSelectedDepartment] = useState("");

  // UI / form state
  const [showPassword, setShowPassword] = useState(false);
  const [validationError, setValidationError] = useState("");
  const [errPass, setErrPass] = useState("");
  const [msgSubmit, setMsgSubmit] = useState("");
  const [, setErrSubmit] = useState(false);

  // conflict / pending credentials
  const [pendingCredentials, setPendingCredentials] = useState(null);
  const [showConflictModal, setShowConflictModal] = useState(false);

  // contact modal state
  const [showContactModal, setShowContactModal] = useState(false);

  // Password change modal state (when must_change_password is true)
  const [showChangePasswordModal, setShowChangePasswordModal] = useState(false);
  const [changePasswordEmail, setChangePasswordEmail] = useState("");
  const [currentPasswordInput, setCurrentPasswordInput] = useState("");
  const [newPasswordInput, setNewPasswordInput] = useState("");
  const [confirmPasswordInput, setConfirmPasswordInput] = useState("");
  const [showCurrentPwd, setShowCurrentPwd] = useState(false);
  const [showNewPwd, setShowNewPwd] = useState(false);
  const [showConfirmPwd, setShowConfirmPwd] = useState(false);
  const [changePasswordLoading, setChangePasswordLoading] = useState(false);
  const [changePasswordError, setChangePasswordError] = useState("");
  const [changePasswordSuccess, setChangePasswordSuccess] = useState("");
  // Temporary token for change-password API call (not stored in cookies to prevent auto-login)
  const tempAuthTokenRef = useRef(null);

  // Function to check for autofilled values (stable via useCallback)
  const checkForAutofill = useCallback(() => {
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
  }, [email, validationError]);

  // Fetch departments (domains) for the dropdown using direct axios to avoid auth interceptor issues
  useEffect(() => {
    let mounted = true;
    const loadDepartments = async () => {
      setDeptLoading(true);
      try {
        // Use direct axios call to avoid auth interceptor issues on login page
        const response = await axios.get(`${BASE_URL}${APIs.GET_DEPARTMENTS}`);
        const resp = response.data;
        // backend may return { success: true, departments: [...] } or { domains: [...] } or an array directly
        let items = [];
        if (resp) {
          if (Array.isArray(resp)) {
            items = resp;
          } else if (resp.success && Array.isArray(resp.departments)) {
            items = resp.departments;
          } else if (Array.isArray(resp.departments)) {
            items = resp.departments;
          } else if (Array.isArray(resp.domains)) {
            items = resp.domains;
          } else if (Array.isArray(resp.data)) {
            items = resp.data;
          }
        }
        // map to simple names if objects provided
        const mapped = items.map((d) => (typeof d === "string" ? d : d.department_name || d.domain_name || d.name || String(d)));
        // Do NOT fallback to static roleOptions. If API returns empty array, keep departments empty and show 'No departments found'
        if (mounted) setDepartments(Array.isArray(mapped) ? mapped : []);
      } catch (err) {
        // API failed - departments will show 'No departments found'
        if (mounted) setDepartments([]);
      } finally {
        if (mounted) setDeptLoading(false);
      }
    };
    loadDepartments();
    return () => {
      mounted = false;
    };
  }, []);

  // Check for autofilled values periodically
  // (effect depends on stable checkForAutofill via useCallback)
  useEffect(() => {
    // Check for autofill after component mounts and when page loads
    const timeoutId = setTimeout(checkForAutofill, AUTOFILL_TIMEOUT_MS);

    // Add event listeners for when autofill might occur
    const handlePageLoad = () => checkForAutofill();
    const handleFocus = () => setTimeout(checkForAutofill, AUTOFILL_FOCUS_TIMEOUT_MS);

    window.addEventListener("load", handlePageLoad);
    document.addEventListener("focusin", handleFocus);

    return () => {
      clearTimeout(timeoutId);
      window.removeEventListener("load", handlePageLoad);
      document.removeEventListener("focusin", handleFocus);
    };
  }, [checkForAutofill]);

  const togglePasswordVisibility = () => {
    setShowPassword((prev) => !prev);
  };

  // Handle department selection
  const handleDepartmentSelect = (option) => {
    // Check for autofilled values first
    checkForAutofill();

    // Clear any previous validation errors
    setValidationError("");

    setSelectedDepartment(option);
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
      if (value?.length < PASSWORD_MIN) {
        setErrPass(`Password must be atleast ${PASSWORD_MIN} characters long`);
      } else if (value?.length > PASSWORD_MAX) {
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
    }, CLEAR_MSG_TIMEOUT_MS);
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

      if (actualEmailValue === "" || passwordRef.current === "" || !selectedDepartment) {
        setErrSubmit(true);
        setMsgSubmit("Please fill up all the fields");
        clearError();
      } else if (errEmail || errPass) {
        setErrSubmit(true);
        setMsgSubmit("Please enter proper value in input field");
        clearError();
      } else {
        // Send selected department to backend using correct payload
        const users = await postData(APIs.LOGIN, {
          email_id: actualEmailValue,
          password: passwordRef.current,
          department_name: selectedDepartment,
        });

        // Check if user must change password (set by admin via reset-password)
        if (users.must_change_password === true) {
          // Store token temporarily for the change-password API call only
          const tempToken = users?.token || users?.jwt_token || users?.access_token;
          tempAuthTokenRef.current = tempToken || null;
          // Show password change modal instead of logging in
          // Do NOT set JWT/refresh tokens in cookies - user must login again after changing password
          setChangePasswordEmail(actualEmailValue);
          setShowChangePasswordModal(true);
          setMsgSubmit("");
          return; // Don't proceed with login
        }

        // Setting JWT & refresh tokens - handle multiple possible key names from backend
        const jwtTokenValue = users?.token || users?.jwt_token || users?.access_token;
        const refreshTokenValue = users?.refresh_token || users?.refreshToken || users?.refresh;

        if (jwtTokenValue) setJwtToken(jwtTokenValue);
        if (refreshTokenValue) setRefreshToken(refreshTokenValue);

        if (users.approval) {
          // update context + cookies centrally
          const apiUrl = `${APIs.GET_NEW_SESSION_ID}`;
          const sessionIdResponse = (await fetchData(apiUrl)) || null;

          login({
            userName: users.user_name || users.username,
            user_session: sessionIdResponse,
            role: users.role || selectedDepartment,
            refresh_token: refreshTokenValue,
          });
          Cookies.set("email", users.email);
          Cookies.set("department", selectedDepartment);
          setSessionStart();
          // Trigger permissions refresh after login
          window.dispatchEvent(new Event("permissions:updated"));

          // Navigate to home - all screens are accessible regardless of permissions
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
      // Let global handler decide final toast (connection refused / no response / backend detail)
      handleApiError(error, { context: "LoginScreen.onSubmit" });
      setErrSubmit(true);
      // Do NOT overwrite with generic text; leave msgSubmit blank so only toast shows
      setMsgSubmit("");
      clearError();
    }
  };

  // Password change handler (when must_change_password is true)
  const handleChangePassword = async (e) => {
    e.preventDefault();

    // Validate passwords
    const passwordRegex = /^(?=.*[A-Z])(?=.*\d)(?=.*[!@#$%^&*()_+[\]{};':"\\|,.<>/?]).{8,}$/;

    if (!currentPasswordInput || !newPasswordInput || !confirmPasswordInput) {
      setChangePasswordError("All fields are required");
      return;
    }

    if (!passwordRegex.test(newPasswordInput)) {
      setChangePasswordError("Password must be at least 8 characters, include one uppercase, one number, and one special character");
      return;
    }

    if (newPasswordInput !== confirmPasswordInput) {
      setChangePasswordError("New passwords do not match");
      return;
    }

    setChangePasswordLoading(true);
    setChangePasswordError("");
    setChangePasswordSuccess("");

    try {
      // Use direct axios call to bypass axiosInstance interceptors (no session/refresh on login page)
      const token = tempAuthTokenRef.current;
      const headers = { "Content-Type": "application/json", accept: "application/json" };
      if (token) headers.Authorization = `Bearer ${token}`;
      const res = await axios.post(`${BASE_URL}${APIs.CHANGE_PASSWORD}`, { current_password: currentPasswordInput, new_password: newPasswordInput }, { headers });
      const response = res?.data;

      setChangePasswordSuccess(response?.message || response?.detail || "Password changed successfully! Please login with your new password.");

      // Reset form and close modal after delay
      setTimeout(() => {
        setShowChangePasswordModal(false);
        setCurrentPasswordInput("");
        setNewPasswordInput("");
        setConfirmPasswordInput("");
        setChangePasswordSuccess("");
        // Clear the password field so user can enter new password
        passwordRef.current = "";
        setHasPasswordInput(false);
        // Clear temporary auth token
        tempAuthTokenRef.current = null;
      }, 1000);
    } catch (err) {
      const apiError = err?.response?.data?.detail ||
        err?.response?.data?.message ||
        err?.message ||
        "Failed to change password. Please try again.";
      setChangePasswordError(apiError);
    } finally {
      setChangePasswordLoading(false);
    }
  };

  // Guest login handler preserved for future use (commented out to avoid unused warnings)
  /*
  const _handleGuestLogin = async (e) => {
    e.preventDefault();
    // Clear any validation errors when using guest login
    setValidationError("");
    try {
      const users = await fetchData(APIs.GUEST_LOGIN);

      if (users.approval) {
        const apiUrl = `${APIs.GET_NEW_SESSION_ID}`;
        const sessionIdResponse = (await fetchData(apiUrl)) || null;
        login({
          userName: users.user_name || users.username,
          user_session: sessionIdResponse,
          role: users.role || "Guest",
          refresh_token: users.refresh_token,
        });
        Cookies.set("email", users.email);
        setSessionStart();

        // Setting JWT & refresh tokens
        if (users?.token) setJwtToken(users.token);
        if (users?.refresh_token) setRefreshToken(users.refresh_token);

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
      handleApiError(error, { context: "LoginScreen.guestLogin" });
      setErrSubmit(true);
      setMsgSubmit("");
      clearError();
    }
  };
  */

  // Pre-login guard: if already authenticated, navigate away (optional UX improvement)
  useEffect(() => {
    if (isAuthenticated && user?.name) {
      // Already logged in; stay or redirect - we leave as-is to allow forced replacement if user clears something.
    }
  }, [isAuthenticated, user]);

  // Cross-tab logout / replace-session listener via storage fallback (BroadcastChannel handled in context)
  // NOTE: Removed aggressive focus-based cookie check — AuthContext.validate() already
  // handles this with proper debouncing. The raw document.cookie check was unreliable
  // and could trigger false logouts during token refresh or tab switching.

  const attemptLoginWithConflictCheck = () => {
    // Acquire credentials from current form state
    const emailInput = document.querySelector('input[name="Email"]');
    const actualEmailValue = emailInput ? emailInput.value : email;
    const attemptedUserName = actualEmailValue; // assuming email is used as userName OR backend returns user_name later
    const attemptedRole = selectedDepartment;
    const active = getActiveUser();
    // If there is an active user different from attempted OR role differs while active session exists
    if (active && active !== attemptedUserName) {
      setPendingCredentials({ email: attemptedUserName, password: passwordRef.current, role: attemptedRole, department_name: selectedDepartment });
      setShowConflictModal(true);
      return;
    }
    // proceed normally
    onSubmit();
  };

  const handleForceLogin = () => {
    if (!pendingCredentials) return;
    const creds = pendingCredentials;
    setShowConflictModal(false);
    // Use existing onSubmit pipeline but with forceReplace pre step
    // We'll call the same API manually to respect existing backend flow
    (async () => {
      try {
        const users = await postData(APIs.LOGIN, {
          email_id: creds.email,
          password: creds.password,
          department_name: creds.department_name || selectedDepartment,
        });
        if (users?.approval) {
          // Handle multiple possible key names for tokens
          const jwtTokenValue = users?.token || users?.jwt_token || users?.access_token;
          const refreshTokenValue = users?.refresh_token || users?.refreshToken || users?.refresh;

          const apiUrl = `${APIs.GET_NEW_SESSION_ID}`;
          const sessionIdResponse = (await fetchData(apiUrl)) || null;
          forceReplaceLogin({
            userName: users.user_name || users.username,
            user_session: sessionIdResponse,
            role: users.role || creds.role || selectedDepartment,
            refresh_token: refreshTokenValue,
          });
          Cookies.set("email", users.email);
          Cookies.set("department", creds.department_name || selectedDepartment);
          setSessionStart();
          // Trigger permissions refresh after login
          window.dispatchEvent(new Event("permissions:updated"));
          if (jwtTokenValue) setJwtToken(jwtTokenValue);
          if (refreshTokenValue) setRefreshToken(refreshTokenValue);

          // Navigate to home - all screens are accessible regardless of permissions
          navigate("/");
        } else {
          setErrSubmit(true);
          setMsgSubmit(users.message || "Force login failed");
          clearError();
        }
      } catch (error) {
        handleApiError(error, { context: "LoginScreen.forceReplaceLogin" });
        setErrSubmit(true);
        setMsgSubmit("Force login error");
        clearError();
      }
    })();
  };

  const handleRefreshExisting = () => {
    setShowConflictModal(false);
    // Rehydrate from cookies and reload state (no new login)
    syncFromCookies();
    // Optionally force a soft reload to ensure app-level contexts catch up
    navigate("/", { replace: true });
  };

  return (
    <form
      className="loginCard authCardDark"
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
        if (validationError || !actualEmailValue || !passwordRef.current || !selectedDepartment) {
          // Show validation error if needed
          if (!actualEmailValue && !passwordRef.current) {
            setValidationError("Please fill all required details");
          } else {
            // Normal submit validation
            setErrSubmit(true);
            setMsgSubmit("Please fill up all the fields");
            clearError();
          }
          return;
        }
        // If all is good, submit the form
        attemptLoginWithConflictCheck();
      }}>

      {/* Title Section */}
      <h3 className="loginTitle">Login</h3>

      {/* Validation Error Banner */}
      {validationError && (
        <div className="validationBanner">
          <SVGIcons icon="exclamation" width={16} height={16} fill="currentColor" />
          <span>{validationError}</span>
        </div>
      )}

      {/* Email Input */}
      <div className="inputGroup">
        <div className="inputWrapper">
          <span className="inputIcon">
            <SVGIcons icon="at-sign" width={16} height={16} fill="currentColor" />
          </span>
          <input
            type="text"
            name="Email"
            className="input inputWithIcon"
            placeholder="Email"
            value={email}
            onChange={(e) => emailChange(e.target.value)}
            onFocus={() => setTimeout(checkForAutofill, AUTOFILL_TIMEOUT_MS)}
            onBlur={() => setTimeout(checkForAutofill, AUTOFILL_TIMEOUT_MS)}
            tabIndex={1}
            autoComplete="username"
            onKeyDown={(e) => {
              if (e.key === "Enter") e.preventDefault();
            }}
          />
        </div>
        {errEmail && (
          <span className="errorText">
            <SVGIcons icon="exclamation" width={12} height={12} fill="currentColor" />
            {errEmail}
          </span>
        )}
      </div>

      {/* Password Input */}
      <div className="inputGroup">
        <div className="inputWrapper">
          <span className="inputIcon">
            <SVGIcons icon="vault-lock" width={16} height={16} fill="currentColor" />
          </span>
          <input
            type={showPassword ? "text" : "password"}
            name="Password"
            className="input inputWithIcon inputPassword"
            placeholder="Password"
            autoComplete="current-password"
            maxLength={18}
            onChange={(e) => passwordChange(e.target.value)}
            tabIndex={2}
            onFocus={() => setHasPasswordInput(true)}
            onKeyDown={(e) => {
              if (e.key === "Enter") e.preventDefault();
            }}
          />
          {hasPasswordInput && (
            <span className="eyeIcon" onClick={togglePasswordVisibility}>
              <SVGIcons icon={showPassword ? "eye-slash" : "eye"} width={16} height={16} fill="currentColor" />
            </span>
          )}
        </div>
        {errPass && (
          <span className="errorText">
            <SVGIcons icon="exclamation" width={12} height={12} fill="currentColor" />
            {errPass}
          </span>
        )}
      </div>

      {/* Department Dropdown */}
      <div className="inputGroup">
        <NewCommonDropdown
          options={departments}
          selected={selectedDepartment}
          onSelect={handleDepartmentSelect}
          placeholder={deptLoading ? "Loading departments..." : "Select Department"}
          showSearch={true}
          width="100%"
          disabled={deptLoading}
          prefixIcon={<SVGIcons icon="fa-user" width={16} height={16} fill="#9ca3af" />}
          forceDirection="down"
        />
      </div>

      {/* Submit Message */}
      {msgSubmit && (
        <span className={msgSubmit === "Success" ? "successText" : "errorText"}>
          <SVGIcons
            icon={msgSubmit === "Success" ? "circle-check" : "exclamation"}
            width={12}
            height={12}
            fill="currentColor"
          />
          {msgSubmit}
        </span>
      )}

      {/* Footer: Register button + Contact button + Submit Button */}
      <div className="formFooter">
        <div className="footerButtons">
          <button
            type="button"
            className="secondaryBtn"
            onClick={() => navigate("/infy-agent/service-register")}
            tabIndex={4}
          >
            Register
          </button>
          <button
            type="button"
            className="secondaryBtn"
            onClick={() => setShowContactModal(true)}
            tabIndex={5}
          >
            Contact
          </button>
        </div>
        <button type="submit" className="submitBtn" tabIndex={6}>
          Sign In
          <SVGIcons icon="arrow-right" width={12} height={10} stroke="currentColor" />
        </button>
      </div>

      {/* Conflict Modal */}
      {showConflictModal && (
        <div className="modalOverlay" role="dialog" aria-modal="true">
          <div className="conflictModalContent">
            <h2 className="conflictModalTitle">Existing Session Detected</h2>
            <p className="conflictModalText">
              You're currently logged in as <strong>{getActiveUser()}</strong>. Choose Refresh to keep that session
              or Force Login to replace it across all tabs.
            </p>
            <div className="conflictModalActions">
              <button
                type="button"
                className="modalBtn modalBtnSecondary"
                onClick={handleRefreshExisting}>
                Refresh
              </button>
              <button
                type="button"
                className="modalBtn modalBtnPrimary"
                onClick={handleForceLogin}>
                Force Login
              </button>
              <button
                type="button"
                className="modalBtn modalBtnCancel"
                onClick={() => setShowConflictModal(false)}>
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Contact Modal */}
      <ContactModal
        isOpen={showContactModal}
        onClose={() => setShowContactModal(false)}
      />

      {/* Change Password Modal (when must_change_password is true) - rendered via portal */}
      {showChangePasswordModal && createPortal(
        <div className="changePasswordOverlay" role="dialog" aria-modal="true">
          <div className="changePasswordModal">
            <h2 className="changePasswordTitle">Reset Your Password</h2>

            <form onSubmit={handleChangePassword} className="changePasswordForm">
              {/* Current Password */}
              <div className="changePasswordInputGroup">
                <div className="changePasswordInputWrapper">
                  <input
                    type={showCurrentPwd ? "text" : "password"}
                    className="changePasswordInput"
                    value={currentPasswordInput}
                    onChange={(e) => setCurrentPasswordInput(e.target.value)}
                    placeholder="Current Password"
                    autoComplete="current-password"
                  />
                  <button
                    type="button"
                    className="changePasswordEyeBtn"
                    onClick={() => setShowCurrentPwd(!showCurrentPwd)}
                  >
                    <SVGIcons icon={showCurrentPwd ? "eye-off" : "eye"} width={18} height={18} stroke="var(--muted)" />
                  </button>
                </div>
              </div>

              {/* New Password */}
              <div className="changePasswordInputGroup">
                <div className="changePasswordInputWrapper">
                  <input
                    type={showNewPwd ? "text" : "password"}
                    className="changePasswordInput"
                    value={newPasswordInput}
                    onChange={(e) => { setNewPasswordInput(e.target.value); setChangePasswordError(""); }}
                    placeholder="New Password"
                    autoComplete="new-password"
                  />
                  <button
                    type="button"
                    className="changePasswordEyeBtn"
                    onClick={() => setShowNewPwd(!showNewPwd)}
                  >
                    <SVGIcons icon={showNewPwd ? "eye-off" : "eye"} width={18} height={18} stroke="var(--muted)" />
                  </button>
                </div>
                {newPasswordInput && !/^(?=.*[A-Z])(?=.*\d)(?=.*[!@#$%^&*()_+[\]{};':"\\|,.<>/?]).{8,}$/.test(newPasswordInput) && (
                  <span className="changePasswordFieldError">Must be at least 8 characters, include one uppercase letter, one number, and one special character</span>
                )}
              </div>

              {/* Confirm Password */}
              <div className="changePasswordInputGroup">
                <div className="changePasswordInputWrapper">
                  <input
                    type={showConfirmPwd ? "text" : "password"}
                    className="changePasswordInput"
                    value={confirmPasswordInput}
                    onChange={(e) => { setConfirmPasswordInput(e.target.value); setChangePasswordError(""); }}
                    placeholder="Confirm New Password"
                    autoComplete="new-password"
                  />
                  <button
                    type="button"
                    className="changePasswordEyeBtn"
                    onClick={() => setShowConfirmPwd(!showConfirmPwd)}
                  >
                    <SVGIcons icon={showConfirmPwd ? "eye-off" : "eye"} width={18} height={18} stroke="var(--muted)" />
                  </button>
                </div>
                {confirmPasswordInput && confirmPasswordInput !== newPasswordInput && (
                  <span className="changePasswordFieldError">Passwords do not match</span>
                )}
              </div>

              {/* Error/Success Messages */}
              {changePasswordError && <div className="changePasswordError">{changePasswordError}</div>}
              {changePasswordSuccess && <div className="changePasswordSuccess">{changePasswordSuccess}</div>}

              {/* Submit Button */}
              <button
                type="submit"
                className="changePasswordSubmitBtn"
                disabled={changePasswordLoading || !currentPasswordInput || !newPasswordInput || !confirmPasswordInput}
              >
                {changePasswordLoading ? "Updating..." : "Update Password"}
              </button>
            </form>
          </div>
        </div>,
        document.body
      )}
    </form>
  );
}

export default LoginScreen;
