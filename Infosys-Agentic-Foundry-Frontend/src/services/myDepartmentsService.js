import { useState, useEffect } from "react";
import { axiosInstance } from "../Hooks/useAxios";
import { APIs } from "../constant";

let cachedDepartments = null;
let inFlight = null;

export const clearMyDepartmentsCache = () => {
  cachedDepartments = null;
  inFlight = null;
};

/** GET /auth/my-departments — one shared call for dept + role switchers. */
export const fetchMyDepartments = async () => {
  if (cachedDepartments) return cachedDepartments;
  if (inFlight) return inFlight;

  inFlight = axiosInstance
    .get(APIs.MY_DEPARTMENTS)
    .then((res) => {
      const data = res?.data;
      cachedDepartments =
        data?.approval && Array.isArray(data.departments) ? data.departments : [];
      return cachedDepartments;
    })
    .finally(() => {
      inFlight = null;
    });

  return inFlight;
};

/** Roles for the active department from my-departments response. */
export const getRolesForDepartment = (departments, departmentName) => {
  if (!Array.isArray(departments) || departments.length === 0) return [];

  const dept =
    departments.find(
      (d) =>
        String(d?.department_name || "").toLowerCase() ===
        String(departmentName || "").toLowerCase()
    ) ||
    departments.find((d) => d?.is_default) ||
    departments[0];

  if (Array.isArray(dept?.roles) && dept.roles.length > 0) return dept.roles;
  return dept?.role ? [dept.role] : [];
};

/** Load departments once when user is authenticated. */
export function useMyDepartments(isAuthenticated) {
  const [departments, setDepartments] = useState([]);
  const [isLoading, setIsLoading] = useState(false);

  useEffect(() => {
    if (!isAuthenticated) {
      setDepartments([]);
      return;
    }

    let cancelled = false;
    setIsLoading(true);

    fetchMyDepartments()
      .then((items) => {
        if (!cancelled) setDepartments(items);
      })
      .catch(() => {
        if (!cancelled) setDepartments([]);
      })
      .finally(() => {
        if (!cancelled) setIsLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [isAuthenticated]);

  return { departments, isLoading };
};
