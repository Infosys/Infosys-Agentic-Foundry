import { useState, useEffect, useRef } from "react";
import useFetch from "../../Hooks/useAxios";
import { useAuth } from "../../context/AuthContext";
import { APIs } from "../../constant";
import useErrorHandler from "../../Hooks/useErrorHandler";
import SVGIcons from "../../Icons/SVGIcons";
import authStorage from "../../utils/authStorage";
import { useMyDepartments } from "../../services/myDepartmentsService";
import "./departmentSwitcher.css";

function DepartmentSwitcher({ wrapperClassName = "" }) {
  const { postData, setJwtToken, setRefreshToken } = useFetch();
  const { department, role, login, isAuthenticated } = useAuth();
  const { handleApiError } = useErrorHandler();
  const { departments, isLoading } = useMyDepartments(isAuthenticated);

  const [isOpen, setIsOpen] = useState(false);
  const [isSwitching, setIsSwitching] = useState(false);
  const dropdownRef = useRef(null);

  // Close dropdown when clicking outside
  useEffect(() => {
    const handleClickOutside = (event) => {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target)) {
        setIsOpen(false);
      }
    };

    if (isOpen) {
      document.addEventListener("mousedown", handleClickOutside);
    }

    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
    };
  }, [isOpen]);

  // Close dropdown when nav collapses (mouse leaves nav area)
  useEffect(() => {
    const navEl = document.querySelector("[data-nav]");
    if (!navEl) return;

    const handleNavMouseLeave = () => {
      setIsOpen(false);
    };

    navEl.addEventListener("mouseleave", handleNavMouseLeave);
    return () => navEl.removeEventListener("mouseleave", handleNavMouseLeave);
  }, []);

  const handleSwitchDepartment = async (departmentName) => {
    if (departmentName === department) {
      setIsOpen(false);
      return;
    }

    setIsSwitching(true);

    try {
      const response = await postData(APIs.SWITCH_DEPARTMENT, {
        department_name: departmentName,
      });

      if (response && response.approval) {
        const isMsal = localStorage.getItem("auth_type") === "msal";

        if (!isMsal) {
          if (response.token) setJwtToken(response.token);
          if (response.refresh_token) setRefreshToken(response.refresh_token);
        }

        login({
          userName: authStorage.getUserName() || "",
          user_session: authStorage.getSession() || "",
          role: response.role,
          department_name: response.department_name,
          ...(!isMsal && { refresh_token: response.refresh_token }),
        });

        window.location.reload();
      }
    } catch (error) {
      handleApiError(error, { context: "DepartmentSwitcher.switchDepartment" });
      setIsSwitching(false);
    }
  };

  const hasMultipleDepartments = !isLoading && departments.length > 1;
  const displayDepartment = isLoading
    ? (department || "Loading departments...")
    : (department || departments[0]?.department_name || "Select Department");

  const switcherContent = hasMultipleDepartments ? (
    <div className="department-switcher" ref={dropdownRef}>
      <button
        className={`department-trigger ${isOpen ? "open" : ""}`}
        onClick={() => setIsOpen(!isOpen)}
        disabled={isSwitching}
        title="Department Switcher"
      >
        <span className="department-switcher-title">Department Switcher</span>
        <div className="department-label-row">
          <SVGIcons icon="building" width={16} height={16} fill="currentColor" />
          <span className="department-name">{displayDepartment}</span>
          {role && <span className="department-role">({role})</span>}
          <SVGIcons
            icon="chevron-down"
            width={12}
            height={12}
            fill="currentColor"
            className={`dropdown-arrow ${isOpen ? "rotate" : ""}`}
          />
        </div>
      </button>

      {isOpen && (
        <div className="department-dropdown-menu">
          {departments.map((dept) => (
            <button
              key={dept.department_name}
              className={`dropdown-item ${dept.department_name === department ? "active" : ""} ${!dept.is_active ? "disabled" : ""}`}
              onClick={() => dept.is_active && handleSwitchDepartment(dept.department_name)}
              disabled={!dept.is_active || isSwitching}
            >
              <div className="dropdown-item-content">
                <div className="dropdown-item-left">
                  {dept.department_name === department && (
                    <SVGIcons icon="check" width={14} height={14} fill="currentColor" />
                  )}
                  <span className="dropdown-item-name">{dept.department_name}</span>
                </div>
              </div>
              {dept.is_default && dept.department_name !== department && (
                <span className="dropdown-item-badge">Default</span>
              )}
              {!dept.is_active && (
                <span className="dropdown-item-badge inactive">Inactive</span>
              )}
            </button>
          ))}
        </div>
      )}

      {isSwitching && (
        <div className="switching-overlay">
          <div className="spinner"></div>
          <span>Switching department...</span>
        </div>
      )}
    </div>
  ) : (
    <div
      className={`department-label department-label-disabled ${isLoading && !department ? "department-label-loading" : ""}`}
      title={hasMultipleDepartments ? "Department Switcher" : "Only one department available"}
    >
      <span className="department-switcher-title">Department Switcher</span>
      <div className="department-label-row">
        <SVGIcons icon="building" width={16} height={16} fill="currentColor" />
        <span className="department-name">{displayDepartment}</span>
        {!isLoading && role && <span className="department-role">({role})</span>}
      </div>
    </div>
  );

  return wrapperClassName ? (
    <div className={wrapperClassName}>{switcherContent}</div>
  ) : (
    switcherContent
  );
}

export default DepartmentSwitcher;
