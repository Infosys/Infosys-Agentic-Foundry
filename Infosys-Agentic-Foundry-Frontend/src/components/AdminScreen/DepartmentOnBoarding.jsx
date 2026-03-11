import React, { useEffect, useState, useCallback } from "react";
import styles from "./AgentAssignment.module.css";
import Loader from "../commonComponents/Loader.jsx";
import { APIs } from "../../constant";
import { useMessage } from "../../Hooks/MessageContext";
import useFetch from "../../Hooks/useAxios.js";
import { extractErrorMessage } from "../../utils/errorUtils";
import Cookies from "js-cookie";
import { FullModal } from "../../iafComponents/GlobalComponents/FullModal";
import IAFButton from "../../iafComponents/GlobalComponents/Buttons/Button";
import TextField from "../../iafComponents/GlobalComponents/TextField/TextField";
import SVGIcons from "../../Icons/SVGIcons";

const MIN_ROLE_LENGTH = 2;
const MAX_ROLE_LENGTH = 50;

function DepartmentOnBoarding(props) {
  const loggedInUserEmail = Cookies.get("email");
  const userName = Cookies.get("userName");

  const formObject = {
    name: "",
    description: "",
    createdBy: userName === "Guest" ? userName : loggedInUserEmail,
  };

  const { isAddDepartment, setShowForm, editDepartment, fetchDepartmentsAfterFormClose } = props;

  const [formData, setFormData] = useState(formObject);
  const [loading, setLoading] = useState(false);
  const [roles, setRoles] = useState([]);
  const [newRoleName, setNewRoleName] = useState("");
  const [rolesLoading, setRolesLoading] = useState(false);

  const { addMessage, setShowPopup } = useMessage();
  const { fetchData, postData, putData, deleteData } = useFetch();

  // Control global popup visibility on loading change
  useEffect(() => {
    if (!loading) {
      setShowPopup(true);
    } else {
      setShowPopup(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loading]);

  // Load department roles for edit mode
  const loadDepartmentRoles = useCallback(async (deptName) => {
    if (!deptName) return;
    setRolesLoading(true);
    try {
      const resp = await fetchData(`${APIs.GET_DEPARTMENT_ROLES}${encodeURIComponent(deptName)}/roles`);
      let rolesData = [];
      if (Array.isArray(resp)) rolesData = resp;
      else if (resp && Array.isArray(resp.roles)) rolesData = resp.roles;
      else if (resp && Array.isArray(resp.data)) rolesData = resp.data;

      const normalized = rolesData.map((r, idx) => {
        if (typeof r === "string") return { id: `role-${idx}`, name: r, role_name: r };
        return { id: r.id || r.role_id || `role-${idx}`, name: r.name || r.role_name || "", role_name: r.role_name || r.name || "" };
      });
      setRoles(normalized);
    } catch (err) {
      console.error("Error loading department roles:", err);
      setRoles([]);
    } finally {
      setRolesLoading(false);
    }
  }, [fetchData]);

  // Populate form for edit mode
  useEffect(() => {
    if (!isAddDepartment && editDepartment) {
      const deptName = editDepartment.department_name || editDepartment.name || "";
      setFormData({
        name: deptName,
        description: editDepartment.department_description || editDepartment.description || "",
        createdBy: editDepartment.created_by || loggedInUserEmail,
      });

      // Load roles for this department
      if (deptName) {
        loadDepartmentRoles(deptName);
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isAddDepartment, editDepartment]);

  const handleClose = () => {
    setShowForm(false);
  };

  const handleChange = (e) => {
    const { name, value } = e.target;
    setFormData((prev) => ({ ...prev, [name]: value }));
  };

  const validateRoleName = (name) => {
    if (!name.trim()) return "Role name is required";
    if (!/^[A-Z]/.test(name.trim())) return "Role name must start with a capital letter";
    if (name.trim().length < MIN_ROLE_LENGTH) return `Role name must be at least ${MIN_ROLE_LENGTH} characters`;
    if (name.trim().length > MAX_ROLE_LENGTH) return `Role name must be less than ${MAX_ROLE_LENGTH} characters`;
    const existingRole = roles.find(r => (r.name || r.role_name || "").toLowerCase() === name.trim().toLowerCase());
    if (existingRole) return "This role already exists";
    return "";
  };

  const handleAddRole = async () => {
    const validationError = validateRoleName(newRoleName);
    if (validationError) {
      addMessage(validationError, "error");
      return;
    }

    // For edit mode, add role via API
    if (!isAddDepartment && formData.name) {
      setRolesLoading(true);
      try {
        const response = await postData(`${APIs.ADD_DEPARTMENT_ROLE}${encodeURIComponent(formData.name)}/roles/add`, {
          role_name: newRoleName.trim()
        });
        if (response && response.success === false) {
          addMessage(response.message || "Failed to add role", "error");
          return;
        }
        addMessage(response?.message || `Role "${newRoleName.trim()}" added successfully`, "success");
        setNewRoleName("");
        await loadDepartmentRoles(formData.name);
      } catch (err) {
        console.error("Error adding role:", err);
        addMessage("Failed to add role", "error");
      } finally {
        setRolesLoading(false);
      }
    } else {
      // For add mode, just add to local state (will be created with department)
      const newRole = { id: `new-role-${Date.now()}`, name: newRoleName.trim(), role_name: newRoleName.trim() };
      setRoles((prev) => [...prev, newRole]);
      setNewRoleName("");
    }
  };

  const handleRemoveRole = async (role) => {
    const roleName = typeof role === "string" ? role : (role.role_name || role.name);

    // For edit mode, remove role via API
    if (!isAddDepartment && formData.name) {
      setRolesLoading(true);
      try {
        const response = await deleteData(`${APIs.DELETE_DEPARTMENT_ROLE}${encodeURIComponent(formData.name)}/roles/${encodeURIComponent(roleName)}`);
        if (response && response.success === false) {
          addMessage(response.message || "Failed to remove role", "error");
          return;
        }
        addMessage(response?.message || `Role "${roleName}" removed successfully`, "success");
        await loadDepartmentRoles(formData.name);
      } catch (err) {
        console.error("Error removing role:", err);
        addMessage("Failed to remove role", "error");
      } finally {
        setRolesLoading(false);
      }
    } else {
      // For add mode, just remove from local state
      setRoles((prev) => prev.filter((r) => (r.role_name || r.name) !== roleName));
    }
  };

  const handleSubmit = async (e) => {
    if (e) e.preventDefault();

    // Validation
    if (!formData.name.trim()) {
      addMessage("Department name is required", "error");
      return;
    }

    if (!/^[A-Z]/.test(formData.name.trim())) {
      addMessage("Department name must start with a capital letter", "error");
      return;
    }

    setLoading(true);
    try {
      const payload = {
        department_name: formData.name.trim(),
        department_description: formData.description.trim(),
        created_by: formData.createdBy,
      };

      let result;
      if (isAddDepartment) {
        // Create new department
        result = await postData(APIs.ADD_DEPARTMENT, payload);

        // If department created and we have roles to add
        if (result && result.success !== false && roles.length > 0) {
          // Add each role
          for (const role of roles) {
            const roleName = role.role_name || role.name;
            try {
              await postData(`${APIs.ADD_DEPARTMENT_ROLE}${encodeURIComponent(formData.name.trim())}/roles/add`, {
                role_name: roleName
              });
            } catch (roleErr) {
              console.error(`Error adding role ${roleName}:`, roleErr);
            }
          }
        }
      } else {
        // Update existing department - just update the description
        // Note: We can't change department name, roles are managed separately
        const updateUrl = `${APIs.DELETE_DEPARTMENT}${encodeURIComponent(editDepartment.department_name || editDepartment.name)}/update`;
        result = await putData(updateUrl, payload);
      }

      if (result && result.success !== false) {
        addMessage(`Department "${formData.name}" ${isAddDepartment ? "created" : "updated"} successfully!`, "success");
        if (fetchDepartmentsAfterFormClose) {
          fetchDepartmentsAfterFormClose();
        }
        handleClose();
      } else {
        throw new Error(result?.message || `Failed to ${isAddDepartment ? "create" : "update"} department`);
      }
    } catch (error) {
      console.error("Error saving department:", error);
      const errorMsg = extractErrorMessage(error).message || `Failed to ${isAddDepartment ? "create" : "update"} department`;
      addMessage(errorMsg, "error");
    } finally {
      setLoading(false);
    }
  };

  return (
    <>
      {loading && <Loader />}
      <FullModal
        isOpen={true}
        title={isAddDepartment ? "Create New Department" : "Edit Department"}
        onClose={handleClose}
        footer={
          <div className={styles.modalFooterButtons}>
            <IAFButton type="secondary" onClick={handleClose}>
              Cancel
            </IAFButton>
            <IAFButton
              type="primary"
              onClick={handleSubmit}
              disabled={loading || !formData.name.trim()}
              loading={loading}
            >
              {isAddDepartment ? "Create Department" : "Update Department"}
            </IAFButton>
          </div>
        }
      >
        <div className={styles.modernFormContainer}>
          {/* Department Name */}
          <div className={styles.formFieldGroup}>
            <TextField
              label="Department Name"
              name="name"
              value={formData.name}
              onChange={handleChange}
              placeholder="Enter department name (e.g., Engineering)"
              maxLength={50}
              disabled={!isAddDepartment}
              required
            />
            <p className={styles.fieldHint}>
              Department names should be descriptive and must start with a capital letter.
            </p>
          </div>
        </div>
      </FullModal>
    </>
  );
}

export default DepartmentOnBoarding;
