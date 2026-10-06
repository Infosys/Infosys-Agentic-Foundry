import { useState, useEffect, useRef, useMemo } from "react";
import useFetch from "../../Hooks/useAxios";
import { useAuth } from "../../context/AuthContext";
import { APIs } from "../../constant";
import useErrorHandler from "../../Hooks/useErrorHandler";
import SVGIcons from "../../Icons/SVGIcons";
import authStorage from "../../utils/authStorage";
import { useMyDepartments, getRolesForDepartment } from "../../services/myDepartmentsService";
import "./roleSwitcher.css";

function RoleSwitcher({ wrapperClassName = "" }) {
  const { postData, setJwtToken, setRefreshToken } = useFetch();
  const { department, role, login, isAuthenticated } = useAuth();
  const { handleApiError } = useErrorHandler();
  const { departments, isLoading } = useMyDepartments(isAuthenticated);

  const [isOpen, setIsOpen] = useState(false);
  const [isSwitching, setIsSwitching] = useState(false);
  const dropdownRef = useRef(null);

  const roles = useMemo(() => {
    const fromApi = getRolesForDepartment(departments, department);
    if (fromApi.length > 0) return fromApi;
    return role ? [role] : [];
  }, [departments, department, role]);

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
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [isOpen]);

  // Close dropdown when nav collapses
  useEffect(() => {
    const navEl = document.querySelector("[data-nav]");
    if (!navEl) return;
    const handleNavMouseLeave = () => setIsOpen(false);
    navEl.addEventListener("mouseleave", handleNavMouseLeave);
    return () => navEl.removeEventListener("mouseleave", handleNavMouseLeave);
  }, []);

  const handleSwitchRole = async (newRole) => {
    if (newRole === role) {
      setIsOpen(false);
      return;
    }

    setIsSwitching(true);
    try {
      const response = await postData(APIs.SWITCH_ROLE, {
        role: newRole,
        department_name: department,
      });

      if (response?.approval) {
        const isMsal = localStorage.getItem("auth_type") === "msal";

        if (!isMsal) {
          if (response.token) setJwtToken(response.token);
          if (response.refresh_token) setRefreshToken(response.refresh_token);
        }

        login({
          userName: authStorage.getUserName() || "",
          user_session: authStorage.getSession() || "",
          role: response.role || newRole,
          department_name: response.department_name || department,
          ...(!isMsal && { refresh_token: response.refresh_token }),
        });

        window.location.reload();
      }
    } catch (error) {
      handleApiError(error, { context: "RoleSwitcher.switchRole" });
      setIsSwitching(false);
    }
  };

  const hasMultipleRoles = !isLoading && roles.length > 1;
  const displayRole = isLoading ? (role || "Loading roles...") : (role || roles[0] || "No role");

  if (isLoading) {
    return (
      <div className={wrapperClassName}>
        <div className="role-label role-label-disabled" title="Loading roles">
          <span className="role-switcher-title">Role Switcher</span>
          <div className="role-label-row">
            <SVGIcons icon="user" width={14} height={14} fill="currentColor" />
            <span className="role-name">{displayRole}</span>
          </div>
        </div>
      </div>
    );
  }

  if (roles.length === 0) {
    return (
      <div className={wrapperClassName}>
        <div className="role-label role-label-disabled" title="No roles available">
          <span className="role-switcher-title">Role Switcher</span>
          <div className="role-label-row">
            <SVGIcons icon="user" width={14} height={14} fill="currentColor" />
            <span className="role-name">{displayRole}</span>
          </div>
        </div>
      </div>
    );
  }

  if (!hasMultipleRoles) {
    return (
      <div className={wrapperClassName}>
        <div className="role-label role-label-disabled" title="Only one role available">
          <span className="role-switcher-title">Role Switcher</span>
          <div className="role-label-row">
            <SVGIcons icon="user" width={14} height={14} fill="currentColor" />
            <span className="role-name">{displayRole}</span>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className={wrapperClassName}>
      <div className="role-switcher" ref={dropdownRef}>
        <button
          className={`role-trigger ${isOpen ? "open" : ""}`}
          onClick={() => setIsOpen(!isOpen)}
          disabled={isSwitching || isLoading}
          title="Role Switcher"
        >
          <span className="role-switcher-title">Role Switcher</span>
          <div className="role-label-row">
            <SVGIcons icon="user" width={14} height={14} fill="currentColor" />
            <span className="role-name">{displayRole}</span>
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
          <div className="role-dropdown-menu">
            {roles.map((r) => (
              <button
                key={r}
                className={`dropdown-item ${r === role ? "active" : ""}`}
                onClick={() => handleSwitchRole(r)}
                disabled={isSwitching}
              >
                <div className="dropdown-item-content">
                  <div className="dropdown-item-left">
                    {r === role && (
                      <SVGIcons icon="check" width={14} height={14} fill="currentColor" />
                    )}
                    <span className="dropdown-item-name">{r}</span>
                  </div>
                </div>
              </button>
            ))}
          </div>
        )}

        {isSwitching && (
          <div className="switching-overlay">
            <div className="spinner"></div>
            <span>Switching role...</span>
          </div>
        )}
      </div>
    </div>
  );
}

export default RoleSwitcher;
