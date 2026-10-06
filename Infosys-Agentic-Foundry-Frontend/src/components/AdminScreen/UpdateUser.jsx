import { useState, useEffect, useCallback, useMemo } from "react";
import styles from "./UpdateUser.module.css";
import containerStyles from "../../css_modules/AnimatedContainer.module.css";
import SVGIcons from "../../Icons/SVGIcons";
import { APIs } from "../../constant";
import Loader from "../commonComponents/Loader";
import useFetch from "../../Hooks/useAxios";
import NewCommonDropdown from "../commonComponents/NewCommonDropdown";
import IAFButton from "../../iafComponents/GlobalComponents/Buttons/Button";
import { useMessage } from "../../Hooks/MessageContext";
import { encodePassword } from "../../utils/encodeUtils";
import { getDepartmentFromToken, getRoleFromToken, getEmailFromToken } from "../../utils/jwtUtils";

const defaultRoleOptions = ["Admin", "Developer", "User"];

const getUserOptionLabel = (user) => user.email || "";

const normalizeRoleName = (role) =>
  String(typeof role === "string" ? role : role?.role_name || role?.name || role || "").trim();

const parseUserDepartments = (user) =>
  (user.departments || [])
    .map((entry) => {
      try {
        return typeof entry === "string" ? JSON.parse(entry) : entry;
      } catch {
        return null;
      }
    })
    .filter(Boolean)
    .map((entry) => ({
      department_name: entry.department_name || "Global",
      role: entry.role || "User",
      is_active: entry.is_active,
    }));

const roleEquals = (a, b) => a.toLowerCase() === b.toLowerCase();

const hasRoleInList = (roles, role) => roles.some((item) => roleEquals(item, role));

const UpdateUser = ({ embedded = false }) => {
  const [email, setEmail] = useState("");
  const [initialRoles, setInitialRoles] = useState([]);
  const [pendingAddRoles, setPendingAddRoles] = useState([]);
  const [pendingRemoveRoles, setPendingRemoveRoles] = useState([]);
  const [userRolesLoading, setUserRolesLoading] = useState(false);
  const [temporaryPwd, setTemporaryPwd] = useState("");
  const [showPassword, setShowPassword] = useState(false);

  const [errors, setErrors] = useState({
    email: "",
    roles: "",
    department: "",
    pwd: "",
    api: "",
  });
  const [touched, setTouched] = useState({});
  const [isLoading, setIsLoading] = useState(false);
  const [isSubmitDisabled, setIsSubmitDisabled] = useState(true);
  const { patchData, fetchData } = useFetch();
  const { addMessage } = useMessage();

  const loggedInDepartment = getDepartmentFromToken();
  const loggedInRole = getRoleFromToken().toUpperCase();
  const loggedInUserEmail = (getEmailFromToken() || "").trim().toLowerCase();
  const isSuperAdmin = loggedInRole === "SUPERADMIN";
  const isAdmin = loggedInRole === "ADMIN";

  const ADMIN_ROLE_REMOVAL_TOOLTIP = "Admin role cannot be removed by Admin users";

  const isRoleRemovalDisabled = (role) =>
    isAdmin && role.trim().toLowerCase() === "admin";

  const [superadminExists, setSuperadminExists] = useState(false);
  const [superadminCheckLoading, setSuperadminCheckLoading] = useState(true);

  const [departments, setDepartments] = useState([]);
  const [selectedDepartment, setSelectedDepartment] = useState("");
  const [deptLoading, setDeptLoading] = useState(false);

  const [departmentRoles, setDepartmentRoles] = useState([]);
  const [rolesLoading, setRolesLoading] = useState(false);

  const [allUsers, setAllUsers] = useState([]);
  const [usersLoading, setUsersLoading] = useState(false);

  const activeDepartment = isSuperAdmin ? selectedDepartment : loggedInDepartment;

  const loadUsers = useCallback(async () => {
    setUsersLoading(true);
    try {
      const response = await fetchData(APIs.LIST_USERS);
      let users = [];
      if (Array.isArray(response)) users = response;
      else if (Array.isArray(response?.users)) users = response.users;
      else if (Array.isArray(response?.data)) users = response.data;

      const deduped = new Map();
      users.forEach((user) => {
        const userEmail = (user.email || user.mail_id || "").trim();
        if (!userEmail) return;
        const key = userEmail.toLowerCase();
        if (!deduped.has(key)) {
          deduped.set(key, {
            email: userEmail,
            user_name: user.username || user.user_name || "",
            departments: parseUserDepartments(user),
          });
        }
      });
      setAllUsers(Array.from(deduped.values()));
    } catch (err) {
      console.error("Failed to fetch users:", err);
      setAllUsers([]);
    } finally {
      setUsersLoading(false);
    }
  }, [fetchData]);

  useEffect(() => {
    loadUsers();
  }, [loadUsers]);

  const filteredUsers = useMemo(() => {
    const excludeSelf = (users) =>
      users.filter((user) => user.email.trim().toLowerCase() !== loggedInUserEmail);

    if (isSuperAdmin) {
      if (!selectedDepartment) return [];
      const deptKey = selectedDepartment.trim().toLowerCase();
      return excludeSelf(
        allUsers.filter((user) =>
          user.departments?.some(
            (entry) => (entry.department_name || "").trim().toLowerCase() === deptKey
          )
        )
      );
    }
    return excludeSelf(allUsers);
  }, [allUsers, isSuperAdmin, selectedDepartment, loggedInUserEmail]);

  const userDropdownOptions = useMemo(
    () => filteredUsers.map(getUserOptionLabel),
    [filteredUsers]
  );

  const userOptionTooltips = useMemo(() => {
    const tooltips = {};
    filteredUsers.forEach((user) => {
      if (user.email && user.user_name) tooltips[user.email] = user.user_name;
    });
    return tooltips;
  }, [filteredUsers]);

  const userOptionSearchText = useMemo(() => {
    const searchText = {};
    filteredUsers.forEach((user) => {
      if (user.email && user.user_name) searchText[user.email] = user.user_name;
    });
    return searchText;
  }, [filteredUsers]);

  const resetRoleChanges = () => {
    setPendingAddRoles([]);
    setPendingRemoveRoles([]);
  };

  const occupiedRoleSet = useMemo(() => {
    const set = new Set();
    initialRoles.forEach((role) => set.add(role.toLowerCase()));
    pendingAddRoles.forEach((role) => set.add(role.toLowerCase()));
    return set;
  }, [initialRoles, pendingAddRoles]);

  const unassignedRoleOptions = useMemo(() => {
    const base = departmentRoles.length > 0 ? departmentRoles : defaultRoleOptions;
    const filtered = base.filter((role) => isSuperAdmin || role.toLowerCase() !== "admin");
    return filtered.filter((role) => !occupiedRoleSet.has(role.toLowerCase()));
  }, [departmentRoles, isSuperAdmin, occupiedRoleSet]);

  const existingAssignedRoles = useMemo(
    () => initialRoles.filter((role) => !hasRoleInList(pendingRemoveRoles, role)),
    [initialRoles, pendingRemoveRoles]
  );

  const newlyAddedRoles = pendingAddRoles;

  const hasRoleChanges = useMemo(
    () => pendingAddRoles.length > 0 || pendingRemoveRoles.length > 0,
    [pendingAddRoles, pendingRemoveRoles]
  );

  const fetchUserRoles = useCallback(
    async (userEmail, dept) => {
      if (!userEmail || !dept) {
        setInitialRoles([]);
        resetRoleChanges();
        return;
      }
      setUserRolesLoading(true);
      try {
        const url = `${APIs.GET_USER_ROLES}${encodeURIComponent(userEmail)}/roles?department_name=${encodeURIComponent(dept)}`;
        const response = await fetchData(url);
        const roles = (Array.isArray(response?.roles)
          ? response.roles
          : Array.isArray(response)
            ? response
            : []
        )
          .map(normalizeRoleName)
          .filter(Boolean);
        setInitialRoles(roles);
        resetRoleChanges();
      } catch {
        setInitialRoles([]);
        resetRoleChanges();
      } finally {
        setUserRolesLoading(false);
      }
    },
    [fetchData]
  );

  useEffect(() => {
    const checkAndLoadDepartments = async () => {
      setSuperadminCheckLoading(true);
      try {
        const res = await fetchData(APIs.SUPERADMIN_EXISTS);
        const exists = res?.superadmin_exists ?? false;
        setSuperadminExists(exists);

        if (exists && isSuperAdmin) {
          setDeptLoading(true);
          try {
            const deptRes = await fetchData(APIs.GET_DEPARTMENTS_LIST);
            let items = [];
            if (Array.isArray(deptRes)) items = deptRes;
            else if (deptRes?.departments && Array.isArray(deptRes.departments)) items = deptRes.departments;
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

  const fetchDepartmentRoles = useCallback(async (deptName) => {
    if (!deptName) {
      setDepartmentRoles([]);
      return;
    }
    setRolesLoading(true);
    try {
      const url = `${APIs.GET_DEPARTMENT_ROLES}/${encodeURIComponent(deptName)}/roles`;
      const response = await fetchData(url);
      let rolesArray = [];
      if (Array.isArray(response)) rolesArray = response;
      else if (response?.roles && Array.isArray(response.roles)) rolesArray = response.roles;
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

  useEffect(() => {
    if (superadminExists && selectedDepartment) {
      fetchDepartmentRoles(selectedDepartment);
    } else if (!superadminExists && loggedInDepartment) {
      fetchDepartmentRoles(loggedInDepartment);
    }
  }, [superadminExists, selectedDepartment, loggedInDepartment, fetchDepartmentRoles]);

  useEffect(() => {
    if (email && activeDepartment) {
      fetchUserRoles(email, activeDepartment);
    } else {
      setInitialRoles([]);
      resetRoleChanges();
    }
  }, [email, activeDepartment, fetchUserRoles]);

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

    const isDepartmentSelected = !isSuperAdmin || (selectedDepartment && selectedDepartment.trim() !== "");
    const hasPassword = temporaryPwd && temporaryPwd.trim() !== "";
    let isPasswordValid = true;

    if (hasPassword) {
      const passwordRegex = /^(?=.*[A-Z])(?=.*\d)(?=.*[!@#$%^&*()_+[\]{};':"\\|,.<>/?]).{8,}$/;
      if (!passwordRegex.test(temporaryPwd)) {
        newErrors.pwd =
          "Must be at least 8 characters, include one uppercase, one number, and one special character";
        isPasswordValid = false;
      }
    }

    if (isSuperAdmin && currentTouched.department && hasRoleChanges && !selectedDepartment) {
      newErrors.department = "Department is required when updating roles";
    }

    const hasValidRoleUpdate = hasRoleChanges && isDepartmentSelected;
    const hasValidPasswordUpdate = hasPassword && isPasswordValid;
    const hasValidUpdate = hasValidRoleUpdate || hasValidPasswordUpdate;

    setErrors(newErrors);

    const isEmailValid = email && emailRegex.test(email);
    setIsSubmitDisabled(!(Object.keys(newErrors).length === 0 && isEmailValid && hasValidUpdate));
    return Object.keys(newErrors).length === 0 && isEmailValid && hasValidUpdate;
  };

  useEffect(() => {
    validate();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [email, pendingAddRoles, pendingRemoveRoles, selectedDepartment, temporaryPwd, touched, hasRoleChanges]);

  const handleDepartmentSelect = (option) => {
    setSelectedDepartment(option);
    setEmail("");
    setInitialRoles([]);
    resetRoleChanges();
    setTouched((prev) => ({ ...prev, department: true, email: false, roles: false }));
    setErrors((prev) => ({ ...prev, api: "" }));
  };

  const handleEmailSelect = (optionLabel) => {
    const user = filteredUsers.find((item) => item.email === optionLabel);
    setEmail(user?.email || "");
    setTouched((prev) => ({ ...prev, email: true, roles: false }));
    setErrors((prev) => ({ ...prev, api: "" }));
  };

  const handleRoleSelectionChange = (staged) => {
    const unassignedSet = new Set(unassignedRoleOptions.map((r) => r.toLowerCase()));
    setPendingAddRoles((prev) => {
      const kept = prev.filter((role) => !unassignedSet.has(role.toLowerCase()));
      const newlyAdded = staged.filter((role) => unassignedSet.has(role.toLowerCase()));
      return [...kept, ...newlyAdded];
    });
    setTouched((prev) => ({ ...prev, roles: true }));
  };

  const handleRemoveRole = (roleToRemove, isNewlyAdded = false) => {
    if (isRoleRemovalDisabled(roleToRemove)) return;

    if (isNewlyAdded || hasRoleInList(pendingAddRoles, roleToRemove)) {
      setPendingAddRoles((prev) => prev.filter((role) => !roleEquals(role, roleToRemove)));
      setTouched((prev) => ({ ...prev, roles: true }));
      return;
    }

    setPendingRemoveRoles((prev) => {
      if (hasRoleInList(prev, roleToRemove)) return prev;
      return [...prev, roleToRemove];
    });
    setTouched((prev) => ({ ...prev, roles: true }));
  };

  const handleUndoRemoveRole = (roleToRestore) => {
    setPendingRemoveRoles((prev) => prev.filter((role) => !roleEquals(role, roleToRestore)));
    setTouched((prev) => ({ ...prev, roles: true }));
  };

  const togglePasswordVisibility = () => {
    setShowPassword((prev) => !prev);
  };

  const renderRoleBadges = (roles, variant = "assigned") => {
    const isNew = variant === "new";
    const isRemoved = variant === "removed";

    return (
      <div className={styles.roleBadgesContainer}>
        {roles.map((role) => {
          const removalDisabled = !isRemoved && isRoleRemovalDisabled(role);
          return (
            <span
              key={role}
              className={`${styles.roleBadge} ${isRemoved ? styles.roleBadgeRemoved : ""} ${removalDisabled ? styles.roleBadgeLocked : ""}`}
              title={
                isRemoved
                  ? "Will be removed on Update User. Click undo to keep this role."
                  : removalDisabled
                    ? ADMIN_ROLE_REMOVAL_TOOLTIP
                    : undefined
              }
            >
              {role}
              <button
                type="button"
                className={`${styles.roleBadgeRemove} ${isRemoved ? styles.roleBadgeUndo : ""} ${removalDisabled ? styles.roleBadgeRemoveDisabled : ""}`}
                onClick={() => (isRemoved ? handleUndoRemoveRole(role) : handleRemoveRole(role, isNew))}
                disabled={removalDisabled}
                aria-label={
                  isRemoved
                    ? `Undo removal of ${role}`
                    : removalDisabled
                      ? ADMIN_ROLE_REMOVAL_TOOLTIP
                      : `Remove ${role}`
                }
                title={
                  isRemoved
                    ? `Undo removal of ${role}`
                    : removalDisabled
                      ? ADMIN_ROLE_REMOVAL_TOOLTIP
                      : `Remove ${role}`
                }
              >
                <SVGIcons
                  icon={isRemoved ? "rotate-ccw" : "close-x"}
                  width={12}
                  height={12}
                  color="currentColor"
                />
              </button>
            </span>
          );
        })}
      </div>
    );
  };

  const getApiErrorMessage = (err, fallback) => {
    const rawDetail = err?.response?.data?.detail;
    if (Array.isArray(rawDetail)) {
      return rawDetail.map((d) => d.msg || JSON.stringify(d)).join(", ");
    }
    if (typeof rawDetail === "object" && rawDetail !== null) {
      return rawDetail.msg || rawDetail.message || JSON.stringify(rawDetail);
    }
    return rawDetail || err?.response?.data?.message || err?.message || fallback;
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setIsLoading(true);

    const hasPassword = temporaryPwd && temporaryPwd.trim() !== "";
    const isDepartmentSelected = selectedDepartment && selectedDepartment.trim() !== "";

    const allTouched = {
      email: true,
      roles: true,
      department: isSuperAdmin && hasRoleChanges,
      password: true,
    };
    setTouched(allTouched);

    if (!validate(allTouched)) {
      setIsLoading(false);
      return;
    }

    const department = isSuperAdmin && isDepartmentSelected ? selectedDepartment : loggedInDepartment;

    try {
      const rolesToRemove = hasRoleChanges
        ? pendingRemoveRoles.filter((role) => !isRoleRemovalDisabled(role))
        : [];
      const rolesToAdd = hasRoleChanges ? pendingAddRoles : [];

      const payload = {
        email_id: email,
        department_name: department,
        add_roles: rolesToAdd,
        remove_roles: rolesToRemove,
      };

      if (hasPassword) {
        payload.temporary_password = encodePassword(temporaryPwd);
      }

      const response = await patchData(APIs.UPDATE_USER_ROLE, payload);

      addMessage(response?.message || "User updated successfully!", "success");
      setErrors({ email: "", roles: "", department: "", pwd: "", api: "" });
      setEmail("");
      setInitialRoles([]);
      resetRoleChanges();
      setTemporaryPwd("");
      if (superadminExists) {
        setSelectedDepartment("");
        setDepartmentRoles([]);
      }
      setTouched({});
      loadUsers();
    } catch (err) {
      setErrors((prev) => ({ ...prev, api: getApiErrorMessage(err, "Failed to update user. Please try again.") }));
    } finally {
      setIsLoading(false);
    }
  };

  const formContent = (
    <div className={styles.updateContainer}>
      <h3 className={styles.updateTitle}>Update User</h3>
      {isLoading && <Loader />}
      <form onSubmit={handleSubmit} className={styles.form}>
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
            {touched.department && errors.department && (
              <span className={styles.errorText}>{errors.department}</span>
            )}
          </div>
        )}

        <div className={styles.inputGroup}>
          <NewCommonDropdown
            options={userDropdownOptions}
            selected={email}
            onSelect={handleEmailSelect}
            placeholder={
              isSuperAdmin && !selectedDepartment
                ? "Select department first"
                : usersLoading
                  ? "Loading users..."
                  : userDropdownOptions.length === 0
                    ? "No users in this department"
                    : "Select user email"
            }
            showSearch={true}
            width="382px"
            disabled={
              usersLoading ||
              (isSuperAdmin && !selectedDepartment) ||
              userDropdownOptions.length === 0
            }
            optionTooltips={userOptionTooltips}
            optionSearchText={userOptionSearchText}
          />
          {touched.email && errors.email && <span className={styles.errorText}>{errors.email}</span>}
          {email && userRolesLoading && (
            <span className={styles.fieldHint}>Loading assigned roles...</span>
          )}
          {email && !userRolesLoading && existingAssignedRoles.length > 0 && (
            <>
              <label className={`${styles.fieldHint} ${styles.assignedRolesLabel}`}>Assigned roles</label>
              {renderRoleBadges(existingAssignedRoles)}
            </>
          )}
          {email && !userRolesLoading && pendingRemoveRoles.length > 0 && (
            <>
              <label className={`${styles.fieldHint} ${styles.assignedRolesLabel}`}>
                Roles to remove
              </label>
              <span className={styles.roleChangeHint}>Applied when you click Update User</span>
              {renderRoleBadges(pendingRemoveRoles, "removed")}
            </>
          )}
          {email && !userRolesLoading && initialRoles.length === 0 && activeDepartment && (
            <span className={styles.boundRoleHint}>No roles assigned in {activeDepartment}</span>
          )}
        </div>

        <div className={styles.inputGroup}>
          <label className={styles.fieldHint}>Assign roles</label>
          <NewCommonDropdown
            multiSelect={true}
            showCheckbox={true}
            hideFooter={true}
            selectedItems={[]}
            options={unassignedRoleOptions}
            onSelectionChange={handleRoleSelectionChange}
            placeholder={
              isSuperAdmin && !selectedDepartment
                ? "Select department first"
                : !email
                  ? "Select user email first"
                  : rolesLoading || userRolesLoading
                    ? "Loading roles..."
                    : unassignedRoleOptions.length === 0
                      ? "All roles assigned"
                      : "Select roles to assign"
            }
            showSearch={true}
            width="382px"
            dropdownName="roles"
            disabled={
              !email ||
              rolesLoading ||
              userRolesLoading ||
              (isSuperAdmin && !selectedDepartment) ||
              unassignedRoleOptions.length === 0
            }
          />

          {email && !userRolesLoading && newlyAddedRoles.length > 0 && (
            <>
              <label className={`${styles.fieldHint} ${styles.assignedRolesLabel}`}>Newly added roles</label>
              <span className={styles.roleChangeHint}>Applied when you click Update User</span>
              {renderRoleBadges(newlyAddedRoles, "new")}
            </>
          )}

        </div>

        <div className={styles.inputGroup}>
          <div className={styles.passwordWrapper}>
            <input
              type={showPassword ? "text" : "password"}
              value={temporaryPwd}
              placeholder="Temporary Password (optional)"
              className={styles.input}
              onChange={(e) => setTemporaryPwd(e.target.value)}
              onBlur={() => setTouched((prev) => ({ ...prev, password: true }))}
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

        {errors.api && <div className={styles.apiError}>{errors.api}</div>}

        <div className={styles.formFooter}>
          <IAFButton
            type="primary"
            htmlType="submit"
            disabled={isSubmitDisabled || isLoading}
            loading={isLoading}
            style={{ alignSelf: "flex-start", flexDirection: "row-reverse" }}
            icon={!isLoading && <SVGIcons icon="arrow-right" width={12} height={10} stroke="currentColor" />}
          >
            {isLoading ? "Updating..." : "Update User"}
          </IAFButton>
        </div>
      </form>
    </div>
  );

  if (embedded) return formContent;

  return (
    <div className={containerStyles.pageWrapper}>
      <div className={containerStyles.container}>{formContent}</div>
    </div>
  );
};

export default UpdateUser;