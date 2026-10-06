import useFetch from "../Hooks/useAxios";
import { APIs } from "../constant";

export const useInstallationService = () => {
  const { fetchData } = useFetch();

  const getInstalledPackages = async () => {
    return await fetchData(APIs.GET_INSTALLED_PACKAGES);
  };

  const getMissingDependencies = async () => {
    return await fetchData(APIs.GET_MISSING_DEPENDENCIES);
  };

  const getPendingModules = async () => {
    return await fetchData(APIs.GET_PENDING_MODULES);
  };

  return { getInstalledPackages, getMissingDependencies, getPendingModules };
};