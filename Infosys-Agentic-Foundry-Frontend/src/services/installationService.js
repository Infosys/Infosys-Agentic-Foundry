import useFetch from "../Hooks/useAxios";
import { APIs } from "../constant";

export const useInstallationService = () => {
  const { fetchData, postData } = useFetch();

  const getInstalledPackages = async () => {
    return await fetchData(APIs.GET_INSTALLED_PACKAGES);
  };

  const getMissingDependencies = async () => {
    return await fetchData(APIs.GET_MISSING_DEPENDENCIES);
  };

  const getPendingModules = async () => {
    return await fetchData(APIs.GET_PENDING_MODULES);
  };

  // modules: array of strings
  const installDependencies = async (modules) => {
    // API expects: { modules: ["pkg1", "pkg2"] }
    return await postData(APIs.INSTALL_DEPENDENCIES, { modules });
  };

  const restartServer = async () => {
    return await fetchData(APIs.RESTART_SERVER);
  };
  return { getInstalledPackages, getMissingDependencies, getPendingModules, installDependencies, restartServer };
};
