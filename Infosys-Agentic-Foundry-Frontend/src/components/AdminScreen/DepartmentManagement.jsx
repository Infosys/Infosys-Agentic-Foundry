import React, { useState, useEffect, useCallback } from "react";
import styles from "./AgentAssignment.module.css";
import { useMessage } from "../../Hooks/MessageContext";
import useFetch from "../../Hooks/useAxios";
import { APIs } from "../../constant";
import Cookies from "js-cookie";
import Loader from "../commonComponents/Loader";
import IAFButton from "../../iafComponents/GlobalComponents/Buttons/Button";
import TextField from "../../iafComponents/GlobalComponents/TextField/TextField";
import SVGIcons from "../../Icons/SVGIcons";
import NewCommonDropdown from "../commonComponents/NewCommonDropdown";
import DepartmentOnBoarding from "./DepartmentOnBoarding";

const MIN_NAME_LENGTH = 2;
const MAX_NAME_LENGTH = 50;
const SEARCH_THRESHOLD = 5;

// Main DepartmentManagement Component - Dropdown-based UI like the reference image
const DepartmentManagement = ({ externalSearchTerm = "", onPlusClickRef, onClearSearchRef }) => {
  const [departments, setDepartments] = useState([]);
  const [selectedDepartment, setSelectedDepartment] = useState(null);
  const [loading, setLoading] = useState(false);
  const [rolesLoading, setRolesLoading] = useState(false);
  const [deptRoles, setDeptRoles] = useState([]);
  const [newRoleName, setNewRoleName] = useState("");
  const [saveLoading, setSaveLoading] = useState(false);
  
  // Modal state for creating/editing department
  const [showForm, setShowForm] = useState(false);
  const [isAddDepartment, setIsAddDepartment] = useState(true);
  const [editDepartment, setEditDepartment] = useState(null);
  
  const { addMessage } = useMessage();
  const { fetchData, postData, deleteData } = useFetch();
  
  const role = Cookies.get("role");
  const normalizedRole = role ? role.toUpperCase().replace(/[\s_-]/g, "") : "";
  const isSuperAdmin = normalizedRole === "SUPERADMIN";
  const isAdmin = normalizedRole === "ADMIN";
  const canManage = isSuperAdmin || isAdmin;

  // Load departments list
  const loadDepartments = useCallback(async () => {
    setLoading(true);
    try {
      const resp = await fetchData(APIs.GET_DEPARTMENTS_LIST);
      let source = [];
      if (Array.isArray(resp)) source = resp;
      else if (Array.isArray(resp?.departments)) source = resp.departments;
      else if (Array.isArray(resp?.data)) source = resp.data;
      
      const normalized = source.map((item, idx) => {
        if (typeof item === "string") {
          return { id: `dept-${idx}`, department_name: item };
        }
        return {
          id: item.id || item._id || `dept-${idx}`,
          department_name: item.department_name || item.name || ""
        };
      }).filter(d => d.department_name);
      
      setDepartments(normalized);
      
      // Auto-select first department if available
      if (normalized.length > 0 && !selectedDepartment) {
        setSelectedDepartment(normalized[0]);
      }
    } catch (error) {
      console.error("Error loading departments:", error);
      setDepartments([]);
    } finally {
      setLoading(false);
    }
  }, [fetchData, selectedDepartment]);

  // Load roles for selected department
  const loadDeptRoles = useCallback(async () => {
    if (!selectedDepartment) {
      setDeptRoles([]);
      return;
    }
    setRolesLoading(true);
    try {
      const resp = await fetchData(
        `${APIs.GET_DEPARTMENT_ROLES}${encodeURIComponent(selectedDepartment.department_name)}/roles`
      );
      let roles = [];
      if (Array.isArray(resp)) roles = resp;
      else if (Array.isArray(resp?.roles)) roles = resp.roles;
      else if (Array.isArray(resp?.data)) roles = resp.data;

      const normalized = roles.map((r, idx) => {
        if (typeof r === "string") return { id: `role-${idx}`, name: r, role_name: r };
        return {
          id: r.id || r.role_id || `role-${idx}`,
          name: r.name || r.role_name || "",
          role_name: r.role_name || r.name || ""
        };
      });
      setDeptRoles(normalized);
    } catch (err) {
      console.error("Error loading department roles:", err);
      setDeptRoles([]);
    } finally {
      setRolesLoading(false);
    }
  }, [fetchData, selectedDepartment]);

  // Handle plus button click - open create department modal
  const handlePlusClick = useCallback(() => {
    setShowForm(true);
    setIsAddDepartment(true);
    setEditDepartment(null);
  }, []);

  // Expose handlePlusClick to parent via ref
  useEffect(() => {
    if (onPlusClickRef) {
      onPlusClickRef.current = handlePlusClick;
    }
  }, [onPlusClickRef, handlePlusClick]);

  // Handle clear search ref
  useEffect(() => {
    if (onClearSearchRef) {
      onClearSearchRef.current = () => {
        // Clear any search-related state if needed
      };
    }
  }, [onClearSearchRef]);

  // Callback to refresh departments after form close
  const fetchDepartmentsAfterFormClose = useCallback(() => {
    loadDepartments();
  }, [loadDepartments]);

  // Initial load
  useEffect(() => {
    loadDepartments();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Load roles when department changes
  useEffect(() => {
    if (selectedDepartment) {
      loadDeptRoles();
    }
  }, [selectedDepartment, loadDeptRoles]);

  // Handle department selection from NewCommonDropdown
  const handleDepartmentChange = (deptName) => {
    const dept = departments.find(d => d.department_name === deptName);
    setSelectedDepartment(dept || null);
  };

  // Validate role name
  const validateRoleName = (name) => {
    if (!name.trim()) return "Role name is required";
    if (!/^[A-Z]/.test(name.trim())) return "Role name must start with a capital letter";
    if (name.trim().length < MIN_NAME_LENGTH) return `Role name must be at least ${MIN_NAME_LENGTH} characters`;
    if (name.trim().length > MAX_NAME_LENGTH) return `Role name must be less than ${MAX_NAME_LENGTH} characters`;
    const existingRole = deptRoles.find(
      r => (r.name || r.role_name || "").toLowerCase() === name.trim().toLowerCase()
    );
    if (existingRole) return "This role already exists in this department";
    return "";
  };

  // Add role to department
  const handleAddRole = async () => {
    if (!selectedDepartment) {
      addMessage("Please select a department first", "error");
      return;
    }
    const validationError = validateRoleName(newRoleName);
    if (validationError) {
      addMessage(validationError, "error");
      return;
    }
    setSaveLoading(true);
    try {
      const response = await postData(
        `${APIs.ADD_DEPARTMENT_ROLE}${encodeURIComponent(selectedDepartment.department_name)}/roles/add`,
        { role_name: newRoleName.trim() }
      );
      if (response && response.success === false) {
        addMessage(response.message || "Failed to add role", "error");
        return;
      }
      addMessage(response?.message || `Role "${newRoleName.trim()}" added successfully`, "success");
      setNewRoleName("");
      await loadDeptRoles();
    } catch (err) {
      console.error("Error adding role:", err);
      addMessage("Failed to add role", "error");
    } finally {
      setSaveLoading(false);
    }
  };

  // Remove role from department
  const handleRemoveRole = async (role) => {
    if (!selectedDepartment) return;
    const roleName = typeof role === "string" ? role : (role.role_name || role.name);
    setSaveLoading(true);
    try {
      const response = await deleteData(
        `${APIs.DELETE_DEPARTMENT_ROLE}${encodeURIComponent(selectedDepartment.department_name)}/roles/${encodeURIComponent(roleName)}`
      );
      if (response && response.success === false) {
        addMessage(response.message || "Failed to remove role", "error");
        return;
      }
      addMessage(response?.message || `Role "${roleName}" removed successfully`, "success");
      await loadDeptRoles();
    } catch (err) {
      console.error("Error removing role:", err);
      addMessage("Failed to remove role", "error");
    } finally {
      setSaveLoading(false);
    }
  };

  // Delete department
  const handleDeleteDepartment = async (dept) => {
    if (!dept) return;
    const deptName = dept.department_name || dept.name || dept;
    setLoading(true);
    try {
      const response = await deleteData(
        `${APIs.DELETE_DEPARTMENT}${encodeURIComponent(deptName)}`
      );
      if (response && response.success === false) {
        addMessage(response.message || "Failed to delete department", "error");
        return;
      }
      addMessage(response?.message || `Department "${deptName}" deleted successfully`, "success");
      
      // If the deleted department was selected, clear selection
      if (selectedDepartment?.department_name === deptName) {
        setSelectedDepartment(null);
        setDeptRoles([]);
      }
      
      // Reload departments list
      await loadDepartments();
    } catch (err) {
      console.error("Error deleting department:", err);
      addMessage("Failed to delete department", "error");
    } finally {
      setLoading(false);
    }
  };

  // Handle Enter key in role input
  const handleKeyDown = (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      handleAddRole();
    }
  };

  // Handle delete from dropdown option
  const handleDeleteFromDropdown = (deptName) => {
    const dept = departments.find(d => d.department_name === deptName);
    if (dept) {
      handleDeleteDepartment(dept);
    }
  };

  return (
    <>
      {/* Department Create/Edit Modal */}
      {showForm && (
        <DepartmentOnBoarding
          setShowForm={setShowForm}
          isAddDepartment={isAddDepartment}
          editDepartment={editDepartment}
          fetchDepartmentsAfterFormClose={fetchDepartmentsAfterFormClose}
        />
      )}
      
      {loading && <Loader />}

      <div className={styles.deptManagementContainer}>
        {/* Top Section - Department Selector with Delete Icons in Dropdown */}
        <div className={styles.deptTopSection}>
          <div className={styles.deptSelectorGroup}>
            <label className={styles.deptSelectorLabel}>Select Department</label>
            <NewCommonDropdown
              options={departments.map(d => d.department_name)}
              selected={selectedDepartment?.department_name || ""}
              onSelect={handleDepartmentChange}
              placeholder="Select a department"
              showSearch={departments.length > SEARCH_THRESHOLD}
              disabled={loading || departments.length === 0}
              selectFirstByDefault={true}
              width="100%"
              onOptionDelete={canManage ? handleDeleteFromDropdown : null}
            />
          </div>
        </div>

        {/* Roles Section - Only show when a department is selected */}
        {selectedDepartment && (
          <div className={styles.permissionsSectionWrapper}>
            {rolesLoading ? (
              <div className={styles.loadingState}>
                <Loader />
              </div>
            ) : (
              <>
                {/* Add Role Input - Clean inline style */}
                {canManage && (
                  <div className={styles.deptAddRoleInline}>
                    <TextField
                      value={newRoleName}
                      onChange={(e) => setNewRoleName(e.target.value)}
                      onKeyDown={handleKeyDown}
                      placeholder="Enter new role name..."
                      maxLength={MAX_NAME_LENGTH}
                    />
                    <IAFButton
                      type="primary"
                      onClick={handleAddRole}
                      disabled={saveLoading || !newRoleName.trim()}
                      loading={saveLoading}
                    >
                      Add Role
                    </IAFButton>
                  </div>
                )}

                {/* Roles Grid - Card based like permissions */}
                {deptRoles.length === 0 ? (
                  <div className={styles.deptEmptyRolesModern}>
                    <SVGIcons icon="users" width={40} height={40} color="var(--content-color)" />
                    <p>No roles in this department</p>
                    <span>Add roles using the input above to get started.</span>
                  </div>
                ) : (
                  <div className={styles.deptRolesCardGrid}>
                    {deptRoles.map((role, idx) => {
                      const name = typeof role === "string" ? role : (role.role_name || role.name);
                      return (
                        <div key={name || idx} className={styles.deptRoleCard}>
                          <span className={styles.deptRoleCardName}>{name}</span>
                          <button
                            onClick={() => handleRemoveRole(role)}
                            disabled={saveLoading}
                            className={styles.deptRoleDeleteBtn}
                            title="Remove role"
                            type="button"
                          >
                            <SVGIcons icon="trash" width={16} height={16} color="currentColor" />
                          </button>
                        </div>
                      );
                    })}
                  </div>
                )}
              </>
            )}
          </div>
        )}

        {/* No Department Selected State */}
        {!selectedDepartment && !loading && departments.length === 0 && (
          <div className={styles.deptEmptyState}>
            <SVGIcons icon="folder" width={48} height={48} color="var(--content-color)" />
            <h3>No Departments</h3>
            <p>No departments available in the system.</p>
          </div>
        )}
      </div>
    </>
  );
};

export default DepartmentManagement;
