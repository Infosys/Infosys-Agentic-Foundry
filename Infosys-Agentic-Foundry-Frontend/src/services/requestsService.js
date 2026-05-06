import { APIs } from "../constant";
import useFetch from "../Hooks/useAxios";
import { extractErrorMessage } from "../utils/errorUtils";

/**
 * Service hook for My Requests feature.
 * Handles fetching user requests and raising new department access requests.
 */
export const useRequestsService = () => {
  const { fetchData, postData } = useFetch();

  /**
   * Fetch all requests for the logged-in user.
   * GET /auth/my-requests
   */
  const getMyRequests = async () => {
    try {
      const response = await fetchData(APIs.GET_MY_REQUESTS);
      return response;
    } catch (error) {
      return extractErrorMessage(error);
    }
  };

  /**
   * Request access to additional departments.
   * POST /auth/request-department-access
   * @param {string[]} departmentNames - Array of department names to request access to
   */
  const requestDepartmentAccess = async (departmentNames) => {
    try {
      const response = await postData(APIs.REQUEST_DEPARTMENT_ACCESS, {
        department_names: departmentNames,
      });
      return response;
    } catch (error) {
      return extractErrorMessage(error);
    }
  };

  /**
   * Fetch all available departments for the dropdown.
   * GET /departments/list
   */
  const getDepartmentsList = async () => {
    try {
      const response = await fetchData(APIs.GET_DEPARTMENTS_LIST);
      return response;
    } catch (error) {
      return extractErrorMessage(error);
    }
  };

  return {
    getMyRequests,
    requestDepartmentAccess,
    getDepartmentsList,
  };
};
