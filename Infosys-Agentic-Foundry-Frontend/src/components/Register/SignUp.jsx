import React, { useState, useRef, useEffect, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import SVGIcons from "../../Icons/SVGIcons";
import styles from "./SignUpAdmin.module.css";
import containerStyles from "../../css_modules/AnimatedContainer.module.css";
import useFetch from "../../Hooks/useAxios";
import { APIs, BASE_URL, roleOptions } from "../../constant";
import NewCommonDropdown from "../commonComponents/NewCommonDropdown";
import DepartmentSelector from "../commonComponents/DepartmentSelector/DepartmentSelector";
import { useMessage } from "../../Hooks/MessageContext";
import { encodePassword } from "../../utils/encodeUtils";
import { getDepartmentFromToken, getRoleFromToken } from "../../utils/jwtUtils";
import axios from "axios";

const SignUp = ({ isAdminScreen = false, embedded = false }) => {
  const { postData, fetchData, setJwtToken } = useFetch();
  const { addMessage } = useMessage();

  // Constants
  const REDIRECT_TIMEOUT_MS = 3000;
  const MIN_USERNAME_LENGTH = 3;
  const TAB_INDEX_EMAIL = 2;

  // Get user role from cookies
  const userRole = getRoleFromToken();
  const normalizedRole = userRole.toUpperCase().replace(/[\s_-]/g, "");
  const isSuperAdmin = normalizedRole === "SUPERADMIN";

  const [email, setEmail] = useState("");
  const [errEmail, setErrEmail] = useState("");

  // Username state - only for login page
  const [username, setUsername] = useState("");
  const [errUsername, setErrUsername] = useState("");

  // Department state for SuperAdmin
  const [departments, setDepartments] = useState([]);
  const [selectedDepartment, setSelectedDepartment] = useState("");
  const [deptLoading, setDeptLoading] = useState(false);

  // SuperAdmin existence check (for login-page registration)
  const [superadminExists, setSuperadminExists] = useState(true);
  const [superadminCheckLoading, setSuperadminCheckLoading] = useState(false);

  // Departments for login-page registration when no superadmin exists
  const [registerDepartments, setRegisterDepartments] = useState([]);
  const [selectedRegisterDepts, setSelectedRegisterDepts] = useState([]);
  const [registerDeptLoading, setRegisterDeptLoading] = useState(false);

  // Dynamic roles state - fetched based on department
  const [departmentRoles, setDepartmentRoles] = useState([]);
  const [rolesLoading, setRolesLoading] = useState(false);
  const passwordRef = useRef("");
  const confirmPasswordRef = useRef("");

  // Add refs for the input fields
  const passwordInputRef = useRef(null);
  const confirmPasswordInputRef = useRef(null);

  const [hasPasswordInput, setHasPasswordInput] = useState(false);
  const [hasConfirmPasswordInput, setHasConfirmPasswordInput] = useState(false);

  const [errPass, setErrPass] = useState("");
  const [errConfirmPass, setErrConfirmPass] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [showPassword, setShowPassword] = useState(false);
  const [showConfirmPassword, setShowConfirmPassword] = useState(false);
  const [selectedOption, setSelectedOption] = useState("Select Role");

  const navigate = useNavigate();

  // Get Admin's department from cookies
  const adminDepartment = getDepartmentFromToken();
  const isAdmin = normalizedRole === "ADMIN";

  // Check if superadmin exists when on login-page registration
  useEffect(() => {
    if (!isAdminScreen) {
      const checkSuperadminExists = async () => {
        setSuperadminCheckLoading(true);
        try {
          const response = await axios.get(`${BASE_URL}${APIs.SUPERADMIN_EXISTS}`);
          const data = response.data;
          setSuperadminExists(data?.superadmin_exists ?? false);

          // If superadmin EXISTS, fetch departments for dropdown (same as Login page)
          if (data?.superadmin_exists === true) {
            setRegisterDeptLoading(true);
            try {
              const deptRes = await axios.get(`${BASE_URL}${APIs.GET_DEPARTMENTS}`);
              const resp = deptRes.data;
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
              const mapped = items.map((d) =>
                typeof d === "string" ? d : d.department_name || d.domain_name || d.name || String(d)
              );
              setRegisterDepartments(Array.isArray(mapped) ? mapped : []);
            } catch (err) {
              console.error("Failed to fetch departments:", err);
              setRegisterDepartments([]);
            } finally {
              setRegisterDeptLoading(false);
            }
          }
        } catch (err) {
          console.error("Failed to check superadmin existence:", err);
          setSuperadminExists(false); // default to false on error (no dropdown)
        } finally {
          setSuperadminCheckLoading(false);
        }
      };
      checkSuperadminExists();
    }
  }, [isAdminScreen]);

  // Fetch departments for SuperAdmin
  useEffect(() => {
    if (isAdminScreen && isSuperAdmin) {
      const loadDepartments = async () => {
        setDeptLoading(true);
        try {
          const response = await fetchData(APIs.GET_DEPARTMENTS_LIST);
          let items = [];
          if (Array.isArray(response)) {
            items = response;
          } else if (response?.departments && Array.isArray(response.departments)) {
            items = response.departments;
          }
          const mapped = items.map((d) =>
            typeof d === "string" ? d : d.department_name || d.name || String(d)
          );
          setDepartments(mapped);
        } catch (err) {
          console.error("Failed to fetch departments:", err);
          setDepartments([]);
        } finally {
          setDeptLoading(false);
        }
      };
      loadDepartments();
    }
  }, [isAdminScreen, isSuperAdmin, fetchData]);

  // Fetch roles based on department - for SuperAdmin when department selected, for Admin use their department
  const fetchDepartmentRoles = useCallback(async (deptName) => {
    if (!deptName) {
      setDepartmentRoles([]);
      return;
    }
    setRolesLoading(true);
    try {
      const url = `${APIs.GET_DEPARTMENT_ROLES}${encodeURIComponent(deptName)}/roles`;
      const response = await fetchData(url);
      let rolesArray = [];
      if (Array.isArray(response)) {
        rolesArray = response;
      } else if (response?.roles && Array.isArray(response.roles)) {
        rolesArray = response.roles;
      }
      const roleNames = rolesArray.map((r) =>
        typeof r === "string" ? r : r.role_name || r.name || String(r)
      );
      setDepartmentRoles(roleNames);
    } catch (err) {
      console.error("Failed to fetch department roles:", err);
      setDepartmentRoles([]);
    } finally {
      setRolesLoading(false);
    }
  }, [fetchData]);

  // For Admin, fetch roles from their department on mount
  useEffect(() => {
    if (isAdminScreen && isAdmin && adminDepartment) {
      fetchDepartmentRoles(adminDepartment);
    }
  }, [isAdminScreen, isAdmin, adminDepartment, fetchDepartmentRoles]);

  // For SuperAdmin, fetch roles when department is selected
  useEffect(() => {
    if (isAdminScreen && isSuperAdmin && selectedDepartment) {
      fetchDepartmentRoles(selectedDepartment);
      // Reset role selection when department changes
      setSelectedOption("Select Role");
    }
  }, [isAdminScreen, isSuperAdmin, selectedDepartment, fetchDepartmentRoles]);

  const togglePasswordVisibility = () => {
    setShowPassword((prev) => !prev);
  };

  const toggleConfirmPwdVisibility = () => {
    setShowConfirmPassword((prev) => !prev);
  };

  const handleOptionSelect = (option) => {
    setSelectedOption(option);
  };

  const handleDepartmentSelect = (option) => {
    setSelectedDepartment(option);
  };

  const handleRegisterDeptsApply = (items) => {
    setSelectedRegisterDepts(items);
  };

  const usernameChange = (value) => {
    setUsername(value);
    if (value) {
      if (value.length < MIN_USERNAME_LENGTH) {
        setErrUsername("Username must be at least 3 characters");
      } else if (!/^[a-zA-Z0-9 ]+$/.test(value)) {
        setErrUsername("Username must contain only alphanumeric characters and spaces");
      } else {
        setErrUsername("");
      }
    } else {
      setErrUsername("");
    }
  };

  const emailChange = (value) => {
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

  const passwordChange = (value) => {
    // Match UpdateUser validation: at least 8 chars, one uppercase, one number, one special character
    const passwordRegex = /^(?=.*[A-Z])(?=.*\d)(?=.*[!@#$%^&*()_+[\]{};':"\\|,.<>/?]).{8,}$/;
    passwordRef.current = value;
    setHasPasswordInput(value.length > 0);

    if (value) {
      if (!passwordRegex.test(value)) {
        setErrPass("Must be at least 8 characters, include one uppercase letter, one number, and one special character");
      } else {
        setErrPass("");
      }
    } else {
      setErrPass("");
    }
  };

  const confirmPasswordChange = (value) => {
    confirmPasswordRef.current = value;
    setHasConfirmPasswordInput(value.length > 0);

    if (!value && passwordRef.current) {
      setErrConfirmPass("Please confirm your password");
    } else if (value && value !== passwordRef.current) {
      setErrConfirmPass("Passwords do not match");
    } else {
      setErrConfirmPass("");
    }
  };

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
    // Admin page: email + role
    // SuperAdmin page: email + department + role

    if (!isAdminScreen) {
      // Login page registration
      syncAutofilledPasswords();

      if (!username || !email || !passwordRef.current || !confirmPasswordRef.current) {
        addMessage("Please fill all the fields", "error");
        return;
      }

      // When superadmin exists, at least one department is required
      if (superadminExists && selectedRegisterDepts.length === 0) {
        addMessage("Please select at least one department", "error");
        return;
      }

      if (errUsername) {
        return;
      }

      if (passwordRef.current !== confirmPasswordRef.current) {
        setErrConfirmPass("Passwords do not match");
        return;
      }

      if (errEmail || errPass || errConfirmPass) {
        return;
      }
    } else {
      // Admin/SuperAdmin page registration
      if (!email || selectedOption === "Select Role") {
        addMessage("Please fill all the fields", "error");
        return;
      }

      if (isSuperAdmin && !selectedDepartment) {
        addMessage("Please select a department", "error");
        return;
      }

      if (errEmail) {
        return;
      }
    }

    setIsLoading(true);

    try {
      let response;

      if (!isAdminScreen) {
        // Login page: use appropriate endpoint based on superadmin existence
        const payload = {
          email_id: email,
          user_name: username,
          password: encodePassword(passwordRef.current),
        };

        if (superadminExists) {
          // Superadmin exists → normal register with selected departments
          if (selectedRegisterDepts.length > 0) {
            payload.department_names = selectedRegisterDepts;
          }
          response = await postData(APIs.REGISTER, payload);
        } else {
          // No superadmin → register as superadmin (no department needed)
          response = await postData(APIs.REGISTER_SUPERADMIN, payload);
        }
      } else {
        // Admin/SuperAdmin: use ASSIGN_ROLE_DEPARTMENT endpoint
        // Admin uses logged-in department, SuperAdmin uses selected department
        const userDepartment = getDepartmentFromToken();
        const payload = {
          email_id: email,
          department_name: isSuperAdmin ? selectedDepartment : userDepartment,
          role: selectedOption,
        };
        response = await postData(APIs.ASSIGN_ROLE_DEPARTMENT, payload);
      }

      if (response?.token) {
        setJwtToken(response.token);
      }

      if (response?.approval || response?.success) {
        addMessage(response.message || "User registered successfully!", "success");

        if (isAdminScreen) {
          // Reset form for admin screen
          setEmail("");
          setSelectedOption("Select Role");
          setSelectedDepartment("");
        } else {
          // Reset and navigate to login after success
          setUsername("");
          setEmail("");
          passwordRef.current = "";
          confirmPasswordRef.current = "";
          if (passwordInputRef.current) passwordInputRef.current.value = "";
          if (confirmPasswordInputRef.current) confirmPasswordInputRef.current.value = "";
          setShowPassword(false);
          setShowConfirmPassword(false);
          setHasPasswordInput(false);
          setHasConfirmPasswordInput(false);
          setSelectedRegisterDepts([]);

          setTimeout(() => {
            navigate("/login");
          }, REDIRECT_TIMEOUT_MS);
        }
      } else {
        const detail = response?.detail;
        const msg = Array.isArray(detail)
          ? detail.map((d) => d.msg || JSON.stringify(d)).join(", ")
          : detail || response?.message || "Registration failed";
        addMessage(typeof msg === "string" ? msg : String(msg), "error");
      }
    } catch (error) {
      const errDetail = error?.response?.data?.detail;
      const errMsg = Array.isArray(errDetail)
        ? errDetail.map((d) => d.msg || JSON.stringify(d)).join(", ")
        : errDetail || error?.response?.data?.message || "Something went wrong. Please try again.";
      addMessage(typeof errMsg === "string" ? errMsg : String(errMsg), "error");
    } finally {
      setIsLoading(false);
    }
  };

  // Computed validation based on context
  // Admin page: email + role
  // SuperAdmin page: email + department + role
  const isFormValid = !isAdminScreen
    ? username && email && hasPasswordInput && hasConfirmPasswordInput && !errUsername && !errEmail && !errPass && !errConfirmPass && (!superadminExists || selectedRegisterDepts.length > 0)
    : isSuperAdmin
      ? email && selectedOption !== "Select Role" && selectedDepartment && !errEmail
      : email && selectedOption !== "Select Role" && !errEmail;

  // Form content component to avoid code duplication
  const formContent = (
    <div className={`${styles.registerContainer} ${!isAdminScreen ? "authCardDark" : styles.adminRegister}`}>
      <h3 className={styles.registerTitle}>{isAdminScreen ? "Assignment" : (!superadminExists ? "Super Admin Register" : "Register")}</h3>
      <form className={styles.form} onSubmit={onSubmit}>
        {/* Email - Always shown */}
        <div className={styles.inputGroup}>
          <div className={styles.inputWrapper}>
            <span className={styles.inputIcon}>
              <SVGIcons icon="at-sign" width={16} height={16} fill="currentColor" />
            </span>
            <input
              type="email"
              name="Email"
              className={`${styles.input} ${styles.inputWithIcon}`}
              placeholder="Email"
              value={email}
              onChange={(e) => emailChange(e.target.value)}
              autoComplete="email"
              tabIndex={1}
            />
          </div>
          {errEmail && (
            <span className={styles.errorText}>
              <SVGIcons icon="exclamation" width={12} height={12} fill="currentColor" />
              {errEmail}
            </span>
          )}
        </div>

        {/* Username - Only on login page */}
        {!isAdminScreen && (
          <div className={styles.inputGroup}>
            <input
              type="text"
              name="Username"
              className={styles.input}
              placeholder="Username (letters, numbers, spaces only)"
              value={username}
              onChange={(e) => usernameChange(e.target.value)}
              autoComplete="username"
              tabIndex={TAB_INDEX_EMAIL}
            />
            {errUsername && <span className={styles.errorText}>{errUsername}</span>}
          </div>
        )}

        {!isAdminScreen && (
          <div className={styles.inputGroup}>
            <div className={styles.inputWrapper}>
              <input
                type={showPassword ? "text" : "password"}
                name="Password"
                className={styles.input}
                placeholder="Password"
                onChange={(e) => passwordChange(e.target.value)}
                ref={passwordInputRef}
                autoComplete="new-password"
                tabIndex={3}
                onFocus={() => setHasPasswordInput(true)}
                maxLength={18}
              />
              {hasPasswordInput && (
                <span className={styles.eyeIcon} onClick={togglePasswordVisibility}>
                  <SVGIcons icon={showPassword ? "eye-slash" : "eye"} fill="#9ca3af" />
                </span>
              )}
            </div>
            {errPass && <span className={styles.errorText}>{errPass}</span>}
          </div>
        )}

        {!isAdminScreen && (
          <div className={styles.inputGroup}>
            <div className={styles.inputWrapper}>
              <input
                type={showConfirmPassword ? "text" : "password"}
                name="ConfirmPassword"
                className={styles.input}
                placeholder="Confirm Password"
                onChange={(e) => confirmPasswordChange(e.target.value)}
                ref={confirmPasswordInputRef}
                autoComplete="new-password"
                tabIndex={3}
                onFocus={() => setHasConfirmPasswordInput(true)}
                maxLength={18}
              />
              {hasConfirmPasswordInput && (
                <span className={styles.eyeIcon} onClick={toggleConfirmPwdVisibility}>
                  <SVGIcons icon={showConfirmPassword ? "eye-slash" : "eye"} fill="#9ca3af" />
                </span>
              )}
            </div>
            {errConfirmPass && <span className={styles.errorText}>{errConfirmPass}</span>}
          </div>
        )}

        {/* Department Multi-Select Dropdown - On login page register when superadmin exists */}
        {!isAdminScreen && superadminExists && (
          <div className={styles.inputGroup}>
            <DepartmentSelector
              selectedDepartments={selectedRegisterDepts}
              onChange={handleRegisterDeptsApply}
              departmentsList={registerDepartments}
              disabled={registerDeptLoading || superadminCheckLoading}
              loading={registerDeptLoading}
              placeholder={registerDeptLoading ? "Loading departments..." : "Click + to add departments"}
            />
          </div>
        )}

        {/* Department Dropdown - Only for SuperAdmin in Admin Screen */}
        {isAdminScreen && isSuperAdmin && (
          <div className={styles.inputGroup}>
            <NewCommonDropdown
              options={departments}
              selected={selectedDepartment}
              onSelect={handleDepartmentSelect}
              placeholder={deptLoading ? "Loading departments..." : "Select Department"}
              showSearch={true}
              width="382px"
              theme=""
              disabled={deptLoading}
            />
          </div>
        )}

        {/* Role Dropdown - Only on admin screen, uses dynamic roles based on department */}
        {isAdminScreen && (
          <div className={styles.inputGroup}>
            <NewCommonDropdown
              options={(departmentRoles.length > 0 ? departmentRoles : roleOptions).filter((r) => isSuperAdmin || r.toLowerCase() !== "admin")}
              selected={selectedOption === "Select Role" ? "" : selectedOption}
              onSelect={handleOptionSelect}
              placeholder={rolesLoading ? "Loading roles..." : "Select Role"}
              showSearch={true}
              width="382px"
              theme=""
              disabled={rolesLoading || (isSuperAdmin && !selectedDepartment)}
            />
          </div>
        )}

        {/* Footer: Login link (for signup page) + Submit Button */}
        <div className={`${styles.formFooter} ${!isAdminScreen ? styles.formFooterWithLink : ""}`}>
          {!isAdminScreen && superadminExists && (
            <a href="/login" className={styles.loginLink} tabIndex={7}>
              Already have an account? Login
            </a>
          )}
          <button
            type="submit"
            className={styles.submitBtn}
            tabIndex={8}
            disabled={!isFormValid || isLoading}
          >
            {isLoading ? (isAdminScreen ? "Assigning..." : "Registering...") : (isAdminScreen ? "Assign" : "Sign Up")}
            {!isLoading && <SVGIcons icon="arrow-right" width={12} height={10} stroke="currentColor" />}
          </button>
        </div>
      </form>
    </div>
  );

  // Wrap admin screen with animated container, regular signup renders directly
  // Skip container when embedded in combined page
  if (isAdminScreen && !embedded) {
    return (
      <div className={containerStyles.pageWrapper}>
        <div className={containerStyles.container}>
          {formContent}
        </div>
      </div>
    );
  }

  return formContent;
};

export default SignUp;
