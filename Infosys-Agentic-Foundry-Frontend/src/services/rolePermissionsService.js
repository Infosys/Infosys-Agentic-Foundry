// src/services/rolePermissionsService.js
import useFetch from "../Hooks/useAxios";
import { APIs } from "../constant";

// Service to get role permissions for a department/role
export const useRolePermissionsService = () => {
  const { postData } = useFetch();

  // departmentName and roleName are required
  const getRolePermissions = async (departmentName, roleName) => {
    if (!departmentName || !roleName) return null;
    try {
      const resp = await postData(APIs.GET_ROLE_PERMISSIONS, {
        department_name: departmentName,
        role_name: roleName,
      });
      return resp;
    } catch (e) {
      return null;
    }
  };
  return { getRolePermissions };
};

// Map API response to UI structure for permissions
// Fully dynamic - returns whatever the API sends without static defaults
export function mapApiPermissionsToUI(api) {
  if (!api) return null;
  // If the API response has a 'permissions' key, use it, otherwise use the response directly
  const perms = api.permissions || api;
  
  // Return permissions as-is from API - no hardcoded defaults
  // The UI will show items by default if permission key is not present
  return perms;
}
