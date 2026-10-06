import React, { useState, useRef, useEffect, useCallback } from "react";
import { createPortal } from "react-dom";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useMsal } from "@azure/msal-react";
import { InteractionStatus } from "@azure/msal-browser";
import SVGIcons from "../../Icons/SVGIcons";
import useFetch, { axiosInstance } from "../../Hooks/useAxios";
import Cookies from "js-cookie";
import { useAuth, getActiveUser } from "../../context/AuthContext";
import { APIs, BASE_URL, DIRECT_SSO_LOGIN } from "../../constant";
import { loginRequest } from "../../auth/msalConfig";
import { clearMsalAutoLoginSuppression, clearMsalAuthInProgress, isMsalAutoLoginSuppressed, isMsalLoginPending, markMsalAuthInProgress, suppressMsalAutoLogin } from "../../auth/msalSessionUtils";
import { setSessionStart } from "../../Hooks/useAutoLogout";
import useErrorHandler from "../../Hooks/useErrorHandler";
import axios from "axios";
import NewCommonDropdown from "../commonComponents/NewCommonDropdown";
import { encodePassword } from "../../utils/encodeUtils";
import MsalAuthLoader from "../commonComponents/MsalAuthLoader";
// [MANUAL_TOKEN_MODE] — remove these two imports when removing the feature
import { MANUAL_TOKEN_MODE, requestTokenFromUser } from "../../utils/manualTokenBridge";
import { checkUserStatus, formatMsalLoginErrorMessage } from "../../auth/authApi";
import { useMessage } from "../../Hooks/MessageContext";
import { useVersion } from "../../context/VersionContext";
import "./login.css";

function LoginScreen() {
  const { login, forceReplaceLogin, syncFromCookies, isAuthenticated, user } = useAuth();
  const { postData, fetchData, setJwtToken, setRefreshToken } = useFetch();
  const { handleApiError } = useErrorHandler();
  const { addMessage } = useMessage();
  const { instance: msalInstance, inProgress } = useMsal();
  const { refreshVersion } = useVersion();

  // numeric constants to avoid magic-number lint errors
  const PASSWORD_MIN = 6;
  const PASSWORD_MAX = 50;
  const CLEAR_MSG_TIMEOUT_MS = 3000;

  const [email, setEmail] = useState("");
  const [errEmail, setErrEmail] = useState("");
  // Use a ref instead to avoid storing in state
  const passwordRef = useRef("");
  const [hasPasswordInput, setHasPasswordInput] = useState(false);

  // navigation
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();

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

  // SSO login state — full-page loader until Microsoft auth completes
  const [ssoLoading, setSsoLoading] = useState(() => isMsalLoginPending() && !searchParams.get("msalError"));
  // Ensures auto-SSO fires at most once per LoginScreen mount, regardless of
  // how many times inProgress cycles through None during MSAL v5 initialization.
  const autoLoginFiredRef = useRef(false);
  const msalErrorHandledRef = useRef(false);

  // conflict / pending credentials
  const [pendingCredentials, setPendingCredentials] = useState(null);
  const [showConflictModal, setShowConflictModal] = useState(false);
  const [showChangePasswordModal, setShowChangePasswordModal] = useState(false);
  const [changePasswordEmail, setChangePasswordEmail] = useState("");
  const [currentPwdInput, setCurrentPwdInput] = useState("");
  const [newPwdInput, setNewPwdInput] = useState("");
  const [confirmPwdInput, setConfirmPwdInput] = useState("");
  const [showCurrentPwd, setShowCurrentPwd] = useState(false);
  const [showNewPwd, setShowNewPwd] = useState(false);
  const [showConfirmPwd, setShowConfirmPwd] = useState(false);
  const [changePasswordLoading, setChangePasswordLoading] = useState(false);
  const [changePasswordError, setChangePasswordError] = useState("");
  const [changePasswordSuccess, setChangePasswordSuccess] = useState("");
  const tempAuthTokenRef = useRef(null);

  // Function to check for autofilled values (stable via useCallback)
  const checkForAutofill = useCallback(() => {
    const emailInput = document.querySelector('input[name="Email"]');
    if (!emailInput || !emailInput.value || emailInput.value === email) return;

    const emailAllowlist = /^[a-zA-Z0-9._%+@-]+$/;
    const rawValue = String(emailInput.value).substring(0, 254).trim();
    if (!rawValue || !emailAllowlist.test(rawValue)) return;

    setEmail(rawValue);

    const emailRegex = /^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$/;
    if (!emailRegex.test(rawValue)) {
      setErrEmail("Please enter a valid email address");
    } else {
      setErrEmail("");
    }

    if (validationError && rawValue) {
      setValidationError("");
    }
  }, [email, validationError]);

  // Check if superadmin exists — if not, redirect to register page
  useEffect(() => {
    let mounted = true;
    const checkSuperadmin = async () => {
      try {
        const response = await axiosInstance.get(APIs.SUPERADMIN_EXISTS);
        if (mounted && response.data?.superadmin_exists === false) {
          navigate("/infy-agent/service-register", { replace: true });
        }
      } catch (err) {
        console.error("Failed to check superadmin existence:", err);
      }
    };
    checkSuperadmin();
    return () => { mounted = false; };
  }, [navigate]);

  // Auto-trigger SSO when REACT_APP_DIRECT_SSO_LOGIN="true" — same code path
  // as the manual SSO button, but fired automatically once MSAL is idle.
  // Waits for inProgress === None to avoid the interaction_in_progress error
  // that msal-browser v5 throws when loginRedirect is called during
  // initialization or while a previous redirect lock is still held.
  useEffect(() => {
    if (
      DIRECT_SSO_LOGIN !== "true" ||
      isAuthenticated ||
      autoLoginFiredRef.current ||
      isMsalAutoLoginSuppressed() ||
      inProgress !== InteractionStatus.None ||
      isMsalLoginPending() ||
      searchParams.get("msalError")
    ) return;

    autoLoginFiredRef.current = true;
    handleSsoLogin();
  }, [inProgress]); // eslint-disable-line react-hooks/exhaustive-deps

  // Show MSAL /auth/me errors returned after Microsoft sign-in (e.g. gateway timeout)
  useEffect(() => {
    const msalError = searchParams.get("msalError");
    if (!msalError || msalErrorHandledRef.current) return;

    msalErrorHandledRef.current = true;
    const friendlyMessage = formatMsalLoginErrorMessage(msalError);

    // Suppress auto-login to prevent redirect loop after SSO failure
    suppressMsalAutoLogin();
    clearMsalAuthInProgress();
    setSsoLoading(false);
    setValidationError(friendlyMessage);
    addMessage(friendlyMessage, "error");
    setSearchParams({}, { replace: true });
  }, [searchParams, setSearchParams, addMessage]);

  // Fetch departments (domains) for the dropdown
  useEffect(() => {
    let mounted = true;
    const loadDepartments = async () => {
      setDeptLoading(true);
      try {
        const response = await axiosInstance.get(APIs.GET_DEPARTMENTS);
        const resp = response.data;
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
        const mapped = items.map((d) => (typeof d === "string" ? d : d.department_name || d.domain_name || d.name || String(d)));
        if (mounted) setDepartments(Array.isArray(mapped) ? mapped : []);
      } catch (err) {
        if (mounted) setDepartments([]);
      } finally {
        if (mounted) setDeptLoading(false);
      }
    };
    loadDepartments();
    return () => { mounted = false; };
  }, []);

  // Check for autofilled values periodically
  useEffect(() => {
    let rafId = requestAnimationFrame(() => {
      rafId = requestAnimationFrame(checkForAutofill);
    });
    let focusTimerId = null;

    const handlePageLoad = () => checkForAutofill();
    const handleFocus = () => {
      if (focusTimerId) cancelAnimationFrame(focusTimerId);
      focusTimerId = requestAnimationFrame(checkForAutofill);
    };

    window.addEventListener("load", handlePageLoad);
    document.addEventListener("focusin", handleFocus);

    return () => {
      cancelAnimationFrame(rafId);
      if (focusTimerId) cancelAnimationFrame(focusTimerId);
      window.removeEventListener("load", handlePageLoad);
      document.removeEventListener("focusin", handleFocus);
    };
  }, [checkForAutofill]);

  const togglePasswordVisibility = () => {
    setShowPassword((prev) => !prev);
  };

  const handleDepartmentSelect = (option) => {
    checkForAutofill();
    setValidationError("");
    setSelectedDepartment(option);
  };

  const emailChange = (value) => {
    const emailRegex = /^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$/;
    setEmail(value);

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
    passwordRef.current = value;
    setHasPasswordInput(value.length > 0);

    if (validationError && value) {
      setValidationError("");
    }

    if (value) {
      if (value?.length < PASSWORD_MIN) {
        setErrPass(`Password must be atleast ${PASSWORD_MIN} characters long`);
      } else if (value?.length > PASSWORD_MAX) {
        setErrPass(`Password must be at most ${PASSWORD_MAX} characters long`);
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
      setValidationError("");

      const emailInput = document.querySelector('input[name="Email"]');
      const actualEmailValue = emailInput ? emailInput.value : email;

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
        const users = await postData(APIs.LOGIN, {
          email_id: actualEmailValue,
          password: encodePassword(passwordRef.current),
          department_name: selectedDepartment,
        });

        if (users.must_change_password === true) {
          const tempToken = users?.token || users?.jwt_token || users?.access_token;
          if (!tempToken || tempToken === "undefined" || tempToken === "null") {
            setValidationError(
              "Your account requires a password change, but the login response did not include a session token. Please try again or contact your administrator."
            );
            setErrSubmit(true);
            setMsgSubmit("");
            tempAuthTokenRef.current = null;
            return;
          }
          tempAuthTokenRef.current = tempToken;
          setChangePasswordEmail(actualEmailValue);
          setShowChangePasswordModal(true);
          setMsgSubmit("");
          return;
        }

        const jwtTokenValue = users?.token || users?.jwt_token || users?.access_token;
        const refreshTokenValue = users?.refresh_token || users?.refreshToken || users?.refresh;

        if (jwtTokenValue) setJwtToken(jwtTokenValue);
        if (refreshTokenValue) setRefreshToken(refreshTokenValue);

        if (users.approval) {
          const apiUrl = `${APIs.GET_NEW_SESSION_ID}`;
          const sessionIdResponse = (await fetchData(apiUrl)) || null;

          login({
            userName: users.user_name || users.username,
            user_session: sessionIdResponse,
            role: users.role || selectedDepartment,
            refresh_token: refreshTokenValue,
            department_name: users.department_name || selectedDepartment,
          });
          Cookies.set("email", users.email);
          Cookies.set("department_name", selectedDepartment);
          setSessionStart();
          // Local login — no SSO session to terminate at logout
          localStorage.setItem("auth_type", "local");
          sessionStorage.removeItem("id_token");
          window.dispatchEvent(new Event("permissions:updated"));

          navigate("/");
          setMsgSubmit("Success");
          clearError();
          setErrSubmit(false);
        } else {
          setErrSubmit(true);
          setMsgSubmit(users.message);
          clearError();
        }
      }
    } catch (error) {
      handleApiError(error, { context: "LoginScreen.onSubmit" });
      setErrSubmit(true);
      setMsgSubmit("");
      clearError();
    }
  };

  // Login with Microsoft SSO via MSAL redirect
  const handleSsoLogin = () => {
    setMsgSubmit("");
    clearMsalAutoLoginSuppression();
    markMsalAuthInProgress();
    setSsoLoading(true);
    msalInstance.loginRedirect(loginRequest).catch((err) => {
      clearMsalAuthInProgress();
      handleApiError(err, { context: "LoginScreen.msalLoginRedirect" });
      setMsgSubmit("SSO authentication failed. Please try again.");
      setSsoLoading(false);
    });
  };

  const handleChangePassword = async (e) => {
    e.preventDefault();

    const passwordRegex = /^(?=.*[A-Z])(?=.*\d)(?=.*[!@#$%^&*()_+[\]{};':"\\|,.<>/?]).{8,}$/;

    if (!currentPwdInput || !newPwdInput || !confirmPwdInput) {
      setChangePasswordError("All fields are required");
      return;
    }

    if (!passwordRegex.test(newPwdInput)) {
      setChangePasswordError("Password must be at least 8 characters, include one uppercase, one number, and one special character");
      return;
    }

    if (newPwdInput !== confirmPwdInput) {
      setChangePasswordError("New passwords do not match");
      return;
    }

    setChangePasswordLoading(true);
    setChangePasswordError("");
    setChangePasswordSuccess("");

    try {
      const token = tempAuthTokenRef.current;
      if (!token || token === "undefined" || token === "null") {
        setChangePasswordError("Session expired. Please log in again.");
        setShowChangePasswordModal(false);
        tempAuthTokenRef.current = null;
        setChangePasswordLoading(false);
        return;
      }

      const headers = {
        "Content-Type": "application/json",
        accept: "application/json",
        Authorization: `Bearer ${token}`,
      };
      const res = await axios.post(
        `${BASE_URL}${APIs.CHANGE_PASSWORD}`,
        { current_password: encodePassword(currentPwdInput), new_password: encodePassword(newPwdInput) },
        { headers }
      );
      const response = res?.data;

      setChangePasswordSuccess(response?.message || response?.detail || "Password changed successfully! Please login with your new password.");

      setTimeout(() => {
        setShowChangePasswordModal(false);
        setCurrentPwdInput("");
        setNewPwdInput("");
        setConfirmPwdInput("");
        setChangePasswordSuccess("");
        passwordRef.current = "";
        setHasPasswordInput(false);
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

  // Pre-login guard: if already authenticated, navigate away
  useEffect(() => {
    if (isAuthenticated && user?.name) {
      // Already logged in; stay or redirect
    }
  }, [isAuthenticated, user]);

  const attemptLoginWithConflictCheck = () => {
    const emailInput = document.querySelector('input[name="Email"]');
    const actualEmailValue = emailInput ? emailInput.value : email;
    const attemptedUserName = actualEmailValue;
    const attemptedRole = selectedDepartment;
    const active = getActiveUser();
    if (active && active !== attemptedUserName) {
      setPendingCredentials({ email: attemptedUserName, password: passwordRef.current, role: attemptedRole, department_name: selectedDepartment });
      setShowConflictModal(true);
      return;
    }
    onSubmit();
  };

  const handleForceLogin = () => {
    if (!pendingCredentials) return;
    const creds = pendingCredentials;
    setShowConflictModal(false);
    (async () => {
      try {
        const users = await postData(APIs.LOGIN, {
          email_id: creds.email,
          password: encodePassword(creds.password),
          department_name: creds.department_name || selectedDepartment,
        });
        if (users?.approval) {
          const jwtTokenValue = users?.token || users?.jwt_token || users?.access_token;
          const refreshTokenValue = users?.refresh_token || users?.refreshToken || users?.refresh;

          const apiUrl = `${APIs.GET_NEW_SESSION_ID}`;
          const sessionIdResponse = (await fetchData(apiUrl)) || null;
          forceReplaceLogin({
            userName: users.user_name || users.username,
            user_session: sessionIdResponse,
            role: users.role || creds.role || selectedDepartment,
            refresh_token: refreshTokenValue,
            department_name: users.department_name || creds.department_name || selectedDepartment,
          });
          Cookies.set("email", users.email);
          Cookies.set("department_name", creds.department_name || selectedDepartment);
          setSessionStart();
          // Local login — no SSO session to terminate at logout
          localStorage.setItem("auth_type", "local");
          sessionStorage.removeItem("id_token");
          window.dispatchEvent(new Event("permissions:updated"));
          if (jwtTokenValue) setJwtToken(jwtTokenValue);
          if (refreshTokenValue) setRefreshToken(refreshTokenValue);

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
    syncFromCookies();
    navigate("/", { replace: true });
  };

  // [MANUAL_TOKEN_MODE] — remove this handler when removing the feature
  const handleManualTokenLogin = async () => {
    try {
      const token = await requestTokenFromUser();
      // Same pattern as MSAL SSO: store token, then ask backend for user details
      setJwtToken(token);
      const me = await checkUserStatus(token);
      const apiUrl = `${APIs.GET_NEW_SESSION_ID}`;
      const sessionIdResponse = (await fetchData(apiUrl)) || null;
      login({
        userName: me.username,
        user_session: sessionIdResponse,
        role: me.role,
        email: me.email,
        department_name: me.department_name,
      });
      Cookies.set("email", me.email || "");
      Cookies.set("department_name", me.department_name || "");
      setSessionStart();
      localStorage.setItem("auth_type", "manual_token");
      sessionStorage.removeItem("id_token");
      window.dispatchEvent(new Event("permissions:updated"));
      refreshVersion();
      navigate("/");
    } catch (_) {
      // user cancelled, token invalid, or /auth/me failed — do nothing
    }
  };

  if ((ssoLoading || isMsalLoginPending()) && !searchParams.get("msalError") && !msalErrorHandledRef.current) {
    return <MsalAuthLoader />;
  }

  return (
    <form
      className="loginCard authCardDark"
      onSubmit={(e) => {
        e.preventDefault();

        const emailInput = document.querySelector('input[name="Email"]');
        const actualEmailValue = emailInput ? emailInput.value : email;

        if (actualEmailValue && actualEmailValue !== email) {
          setEmail(actualEmailValue);
        }

        if (validationError || !actualEmailValue || !passwordRef.current || !selectedDepartment) {
          if (!actualEmailValue && !passwordRef.current) {
            setValidationError("Please fill all required details");
          } else {
            setErrSubmit(true);
            setMsgSubmit("Please fill up all the fields");
            clearError();
          }
          return;
        }
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
            onFocus={checkForAutofill}
            onBlur={checkForAutofill}
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
            maxLength={PASSWORD_MAX}
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
          options={deptLoading ? ["Loading departments..."] : departments}
          selected={selectedDepartment}
          onSelect={deptLoading ? () => { } : handleDepartmentSelect}
          placeholder={deptLoading ? "Loading departments..." : "Select Department"}
          showSearch={true}
          width="100%"
          disabled={false}
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

      {/* Footer: Sign In + SSO buttons side by side */}
      <div className="formFooter">
        <button
          type="button"
          className="ssoBtn"
          onClick={handleSsoLogin}
          disabled={ssoLoading}
          tabIndex={5}
        >
          {ssoLoading ? (
            <>
              <div className="ssoBtnSpinner" />
              Redirecting...
            </>
          ) : (
            <>
              Use single sign on
              <SVGIcons icon="arrow-right" width={16} height={16} stroke="currentColor" />
            </>
          )}
        </button>
        <button type="submit" className="submitBtn" tabIndex={4}>
          Sign In
          <SVGIcons icon="arrow-right" width={12} height={10} stroke="currentColor" />
        </button>
      </div>

      {/* Register link */}
      <div className="registerPrompt">
        Don&apos;t have an account?{" "}
        <span
          className="registerLink"
          onClick={() => navigate("/infy-agent/service-register")}
          tabIndex={6}
          role="link"
        >
          Register
        </span>
      </div>

      {/* [MANUAL_TOKEN_MODE] — remove this button when removing the feature */}
      {MANUAL_TOKEN_MODE && (
        <div className="manualTokenPrompt">
          <button
            type="button"
            className="manualTokenBtn"
            onClick={handleManualTokenLogin}
            tabIndex={7}
          >
            Enter access token manually
          </button>
        </div>
      )}

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

      {showChangePasswordModal && createPortal(
        <div className="changePasswordOverlay" role="dialog" aria-modal="true">
          <div className="changePasswordModal">
            <h2 className="changePasswordTitle">Reset Your Password</h2>

            <form onSubmit={handleChangePassword} className="changePasswordForm">
              <div className="changePasswordInputGroup">
                <div className="changePasswordInputWrapper">
                  <input
                    type={showCurrentPwd ? "text" : "password"}
                    className="changePasswordInput"
                    value={currentPwdInput}
                    onChange={(e) => setCurrentPwdInput(e.target.value)}
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

              <div className="changePasswordInputGroup">
                <div className="changePasswordInputWrapper">
                  <input
                    type={showNewPwd ? "text" : "password"}
                    className="changePasswordInput"
                    value={newPwdInput}
                    onChange={(e) => { setNewPwdInput(e.target.value); setChangePasswordError(""); }}
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
                {newPwdInput && !/^(?=.*[A-Z])(?=.*\d)(?=.*[!@#$%^&*()_+[\]{};':"\\|,.<>/?]).{8,}$/.test(newPwdInput) && (
                  <span className="changePasswordFieldError">Must be at least 8 characters, include one uppercase letter, one number, and one special character</span>
                )}
              </div>

              <div className="changePasswordInputGroup">
                <div className="changePasswordInputWrapper">
                  <input
                    type={showConfirmPwd ? "text" : "password"}
                    className="changePasswordInput"
                    value={confirmPwdInput}
                    onChange={(e) => { setConfirmPwdInput(e.target.value); setChangePasswordError(""); }}
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
                {confirmPwdInput && confirmPwdInput !== newPwdInput && (
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
                disabled={changePasswordLoading || !currentPwdInput || !newPwdInput || !confirmPwdInput}
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