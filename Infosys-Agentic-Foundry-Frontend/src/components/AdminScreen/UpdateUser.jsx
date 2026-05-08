import { useState, useEffect, useCallback } from "react";
import styles from "./UpdateUser.module.css";
import containerStyles from "../../css_modules/AnimatedContainer.module.css";
import SVGIcons from "../../Icons/SVGIcons";
import { APIs, BASE_URL } from "../../constant";
import Loader from "../commonComponents/Loader";
import useFetch from "../../Hooks/useAxios";
import NewCommonDropdown from "../commonComponents/NewCommonDropdown";
import IAFButton from "../../iafComponents/GlobalComponents/Buttons/Button";
import { useMessage } from "../../Hooks/MessageContext";
import { encodePassword } from "../../utils/encodeUtils";
import { getDepartmentFromToken, getRoleFromToken } from "../../utils/jwtUtils";
import axios from "axios";

const defaultRoleOptions = ["Admin", "Developer", "User"];

const UpdateUser = ({ embedded = false }) => {
  const [email, setEmail] = useState("");
  const [selectedOption, setSelectedOption] = useState("Select role");
  const [temporaryPwd, setTemporaryPwd] = useState("");
  const [showPassword, setShowPassword] = useState(false);

  const [errors, setErrors] = useState({
    email: "",
    role: "",
    department: "",
    pwd: "",
    api: "",
  });
  const [touched, setTouched] = useState({});
  const [isLoading, setIsLoading] = useState(false);
  const [isSubmitDisabled, setIsSubmitDisabled] = useState(true);
  const { patchData, fetchData } = useFetch();
  const { addMessage } = useMessage();

  // Get logged-in user's department and role from cookies
  const loggedInDepartment = getDepartmentFromToken();
  const loggedInRole = getRoleFromToken().toUpperCase();
  const isSuperAdmin = loggedInRole === "SUPERADMIN";

  // SuperAdmin existence check — drives department dropdown visibility
  const [superadminExists, setSuperadminExists] = useState(false);
  const [superadminCheckLoading, setSuperadminCheckLoading] = useState(true);

  // Department state (shown when superadmin exists)
  const [departments, setDepartments] = useState([]);
  const [selectedDepartment, setSelectedDepartment] = useState("");
  const [deptLoading, setDeptLoading] = useState(false);

  // Dynamic roles based on department
  const [departmentRoles, setDepartmentRoles] = useState([]);
  const [rolesLoading, setRolesLoading] = useState(false);

  /**
   * Check if superadmin exists on mount.
   * If logged-in user is SuperAdmin → show department dropdown + fetch departments list.
   * If not → keep form as-is (no department dropdown).
   */
  useEffect(() => {
    const checkAndLoadDepartments = async () => {
      setSuperadminCheckLoading(true);
      try {
        const res = await axios.get(`${BASE_URL}${APIs.SUPERADMIN_EXISTS}`);
        const exists = res.data?.superadmin_exists ?? false;
        setSuperadminExists(exists);

        // If logged-in user is SuperAdmin, fetch the departments list
        if (exists && isSuperAdmin) {
          setDeptLoading(true);
          try {
            const deptRes = await fetchData(APIs.GET_DEPARTMENTS_LIST);
            let items = [];
            if (Array.isArray(deptRes)) {
              items = deptRes;
            } else if (deptRes?.departments && Array.isArray(deptRes.departments)) {
              items = deptRes.departments;
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
        }
      } catch (err) {
        console.error("Failed to check superadmin existence:", err);
        setSuperadminExists(false);
      } finally {
        setSuperadminCheckLoading(false);
      }
    };
    checkAndLoadDepartments();
  }, [fetchData, isSuperAdmin]);

  // Fetch roles based on department
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

  // Fetch roles when department changes
  useEffect(() => {
    if (superadminExists && selectedDepartment) {
      // Reset role selection when department changes
      setSelectedOption("Select role");
      // Reset role touched state to prevent showing error immediately
      setTouched((prev) => ({ ...prev, selectedOption: false }));
      // Clear any existing API error
      setErrors((prev) => ({ ...prev, api: "" }));
      fetchDepartmentRoles(selectedDepartment);
    } else if (!superadminExists && loggedInDepartment) {
      // When no superadmin, fetch roles from logged-in user's department
      fetchDepartmentRoles(loggedInDepartment);
    }
  }, [superadminExists, selectedDepartment, loggedInDepartment, fetchDepartmentRoles]);

  useEffect(() => {
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = "auto";
    };
  }, []);

  const validate = (overrideTouched) => {
    const newErrors = {};
    const currentTouched = overrideTouched || touched;

    const emailRegex = /^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$/;

    if (currentTouched.email && !email) {
      newErrors.email = "Email is required";
    } else if (currentTouched.email && email && !emailRegex.test(email)) {
      newErrors.email = "Please enter a valid email address";
    }

    // Check if a valid role is selected (not the placeholder)
    const isRoleSelected = selectedOption && selectedOption !== "Select role" && selectedOption.trim() !== "";

    // Check if department is selected (when user is superadmin)
    const isDepartmentSelected = !isSuperAdmin || (selectedDepartment && selectedDepartment.trim() !== "");

    const hasPassword = temporaryPwd && temporaryPwd.trim() !== "";
    let isPasswordValid = true;
    if (hasPassword) {
      const passwordRegex = /^(?=.*[A-Z])(?=.*\d)(?=.*[!@#$%^&*()_+[\]{};':"\\|,.<>/?]).{8,}$/;
      if (!passwordRegex.test(temporaryPwd)) {
        newErrors.pwd = "Must be at least 8 characters, include one uppercase, one number, and one special character";
        isPasswordValid = false;
      }
    }

    // Valid combinations:
    // 1. (Department + Role) selected - for role update
    // At least one must be true
    const hasValidRoleUpdate = isRoleSelected && isDepartmentSelected;
    const hasValidPasswordUpdate = hasPassword && isPasswordValid;
    const hasValidUpdate = hasValidRoleUpdate || hasValidPasswordUpdate;

    // Show department error only if trying to update role without department
    if (isSuperAdmin && currentTouched.department && isRoleSelected && !selectedDepartment) {
      newErrors.department = "Department is required when updating role";
    }

    setErrors(newErrors);

    // Form is valid when:
    // 1. No errors
    // 2. Email is provided and valid format
    const isEmailValid = email && emailRegex.test(email);
    const isFormValid = Object.keys(newErrors).length === 0 &&
      isEmailValid &&
      hasValidUpdate;

    setIsSubmitDisabled(!isFormValid);
    return isFormValid;
  };

  useEffect(() => {
    validate();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [email, selectedOption, selectedDepartment, temporaryPwd, touched]);

  const handleBlur = (field) => {
    setTouched((prev) => ({ ...prev, [field]: true }));
  };

  const handleDepartmentSelect = (option) => {
    setSelectedDepartment(option);
    setTouched((prev) => ({ ...prev, department: true }));
  };

  const handleRoleSelect = (option) => {
    setSelectedOption(option);
    setTouched((prev) => ({ ...prev, selectedOption: true }));
  };

  const togglePasswordVisibility = () => {
    setShowPassword((prev) => !prev);
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setIsLoading(true);

    // Check what's being submitted
    const isRoleSelected = selectedOption && selectedOption !== "Select role" && selectedOption.trim() !== "";
    const hasPassword = temporaryPwd && temporaryPwd.trim() !== "";
    const isDepartmentSelected = selectedDepartment && selectedDepartment.trim() !== "";

    const allTouched = {
      email: true,
      selectedOption: true,
      department: isSuperAdmin && isRoleSelected, // Only require department if updating role as superadmin
      password: true,
    };
    setTouched(allTouched);

    if (!validate(allTouched)) {
      setIsLoading(false);
      return;
    }

    // Create request body
    const requestBody = {
      email_id: email,
    };

    // Always include department_name for superadmin
    if (isSuperAdmin && isDepartmentSelected) {
      requestBody.department_name = selectedDepartment;
    } else if (!isSuperAdmin) {
      requestBody.department_name = loggedInDepartment;
    }

    // Add role if selected
    if (isRoleSelected) {
      requestBody.new_role = selectedOption;
    }
    if (hasPassword) {
      requestBody.temporary_password = encodePassword(temporaryPwd);
    }

    try {
      const response = await patchData(APIs.UPDATE_USER_ROLE, requestBody);
      const data = await response;

      addMessage(data?.message || data?.detail || "User updated successfully!", "success");
      setErrors({ email: "", role: "", department: "", pwd: "", api: "" });

      // Reset form
      setEmail("");
      setSelectedOption("Select role");
      setTemporaryPwd("");
      if (superadminExists) {
        setSelectedDepartment("");
        setDepartmentRoles([]);
      }
      setTouched({});
    } catch (err) {
      console.error(err);
      // Extract error message from API response (detail) or fallback to generic error
      const rawDetail = err?.response?.data?.detail;
      let apiErrorMsg;
      if (Array.isArray(rawDetail)) {
        apiErrorMsg = rawDetail.map((d) => d.msg || JSON.stringify(d)).join(", ");
      } else if (typeof rawDetail === "object" && rawDetail !== null) {
        apiErrorMsg = rawDetail.msg || rawDetail.message || JSON.stringify(rawDetail);
      } else {
        apiErrorMsg = rawDetail ||
          err?.response?.data?.message ||
          err?.message ||
          "Failed to update user. Please try again.";
      }
      // Note: handleApiError in patchData already shows a toast, so we only set form error
      setErrors((prev) => ({ ...prev, api: String(apiErrorMsg) }));
    } finally {
      setIsLoading(false);
    }
  };

  // Form content without container wrapper
  const formContent = (
    <div className={styles.updateContainer}>
      <h3 className={styles.updateTitle}>Update User</h3>
      {isLoading && <Loader />}
      <form onSubmit={handleSubmit} className={styles.form}>
        {/* Email */}
        <div className={styles.inputGroup}>
          <input
            type="email"
            value={email}
            placeholder="Email"
            className={styles.input}
            onChange={(e) => setEmail(e.target.value)}
            onBlur={() => handleBlur("email")}
            autoComplete="off"
          />
          {touched.email && errors.email && <span className={styles.errorText}>{errors.email}</span>}
        </div>

        {/* Department Dropdown - Shown only for SuperAdmin */}
        {isSuperAdmin && (
          <div className={styles.inputGroup}>
            <NewCommonDropdown
              options={departments}
              selected={selectedDepartment}
              onSelect={handleDepartmentSelect}
              placeholder={deptLoading ? "Loading departments..." : "Select department"}
              showSearch={true}
              width="382px"
              disabled={deptLoading || superadminCheckLoading}
            />
            {touched.department && errors.department && <span className={styles.errorText}>{errors.department}</span>}
          </div>
        )}

        {/* Role Dropdown */}
        <div className={styles.inputGroup}>
          <NewCommonDropdown
            options={(departmentRoles.length > 0 ? departmentRoles : defaultRoleOptions).filter((r) => isSuperAdmin || r.toLowerCase() !== "admin")}
            selected={selectedOption === "Select role" ? "" : selectedOption}
            onSelect={handleRoleSelect}
            placeholder={rolesLoading ? "Loading roles..." : "Select role"}
            showSearch={true}
            width="382px"
            disabled={rolesLoading || (isSuperAdmin && !selectedDepartment)}
          />
          {touched.selectedOption && errors.role && <span className={styles.errorText}>{errors.role}</span>}
        </div>

        <div className={styles.inputGroup}>
          <div className={styles.passwordWrapper}>
            <input
              type={showPassword ? "text" : "password"}
              value={temporaryPwd}
              placeholder="Temporary Password (optional)"
              className={styles.input}
              onChange={(e) => setTemporaryPwd(e.target.value)}
              onBlur={() => handleBlur("password")}
              autoComplete="new-password"
            />
            <button
              type="button"
              className={styles.eyeButton}
              onClick={togglePasswordVisibility}
              aria-label={showPassword ? "Hide password" : "Show password"}
            >
              <SVGIcons icon={showPassword ? "eye-off" : "eye"} width={18} height={18} stroke="var(--content-color)" />
            </button>
          </div>
          {temporaryPwd && errors.pwd && <span className={styles.errorText}>{errors.pwd}</span>}
        </div>

        {/* API Error Display */}
        {errors.api && <div className={styles.apiError}>{errors.api}</div>}

        {/* Footer with Submit Button - matches Register page */}
        <div className={styles.formFooter}>
          <IAFButton
            type="primary"
            htmlType="submit"
            disabled={isSubmitDisabled || isLoading}
            loading={isLoading}
            style={{ alignSelf: "flex-start", flexDirection: "row-reverse" }}
            icon={!isLoading && <SVGIcons icon="arrow-right" width={12} height={10} stroke="currentColor" />}>
            {isLoading ? "Updating..." : "Update User"}
          </IAFButton>
        </div>
      </form>
    </div>
  );

  // Skip container wrapper when embedded in combined page
  if (embedded) {
    return formContent;
  }

  return (
    <div className={containerStyles.pageWrapper}>
      <div className={containerStyles.container}>
        {formContent}
      </div>
    </div>
  );
};

export default UpdateUser;
