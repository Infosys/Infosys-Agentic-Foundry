import { APIs } from "../constant";
import useFetch from "../Hooks/useAxios";

export const useSchedulerService = () => {
  const { fetchData, postData, patchData, deleteData } = useFetch();

  const getEnums = async () => {
    const response = await fetchData(APIs.SCHEDULER_ENUMS);
    return response;
  };

  const validateCron = async (payload) => {
    const response = await postData(APIs.SCHEDULER_VALIDATE_CRON, payload);
    return response;
  };

  const getUpcoming = async ({ onlyMine = false, limit = 20 } = {}) => {
    const params = new URLSearchParams({
      only_mine: onlyMine,
      limit: String(limit),
    });
    const response = await fetchData(`${APIs.SCHEDULER_UPCOMING}?${params}`);
    return response;
  };

  const createSchedule = async (payload) => {
    const response = await postData(APIs.SCHEDULER_BASE, payload);
    return response;
  };

  const listSchedules = async ({ onlyMine = false, onlyActive = false, searchValue = "", limit = 100, offset = 0 } = {}) => {
    const params = new URLSearchParams({
      only_mine: onlyMine,
      only_active: onlyActive,
      limit: String(limit),
      offset: String(offset),
    });
    if (searchValue.trim()) {
      params.set("search_value", searchValue.trim());
    }
    const response = await fetchData(`${APIs.SCHEDULER_BASE}?${params}`);
    return response;
  };

  const getSchedule = async (jobId) => {
    const response = await fetchData(
      `${APIs.SCHEDULER_BASE}/${encodeURIComponent(jobId)}`
    );
    return response;
  };

  const updateSchedule = async (jobId, payload) => {
    // List 2: PATCH /{job_id}  →  POST /update/{job_id}
    const response = await patchData(
      `${APIs.SCHEDULER_BASE}/update/${encodeURIComponent(jobId)}`,
      payload
    );
    return response;
  };

  const deleteSchedule = async (jobId, hardDelete = false) => {
    // List 2: DELETE /{job_id}  →  POST /delete/{job_id}
    const path = `${APIs.SCHEDULER_BASE}/delete/${encodeURIComponent(jobId)}${hardDelete ? "?hard_delete=true" : ""}`;
    const response = await deleteData(path);
    return response;
  };

  const pauseSchedule = async (jobId) => {
    const response = await postData(
      `${APIs.SCHEDULER_BASE}/${encodeURIComponent(jobId)}/pause`
    );
    return response;
  };

  const resumeSchedule = async (jobId) => {
    const response = await postData(
      `${APIs.SCHEDULER_BASE}/${encodeURIComponent(jobId)}/resume`
    );
    return response;
  };

  const runNow = async (jobId) => {
    const response = await postData(
      `${APIs.SCHEDULER_BASE}/${encodeURIComponent(jobId)}/run-now`
    );
    return response;
  };

  const getHistory = async (jobId, { limit = 50, offset = 0 } = {}) => {
    const params = new URLSearchParams({
      limit: String(limit),
      offset: String(offset),
    });
    const response = await fetchData(
      `${APIs.SCHEDULER_BASE}/${encodeURIComponent(jobId)}/history?${params}`
    );
    return response;
  };

  const getExecutionDetail = async (jobId, executionId) => {
    const response = await fetchData(
      `${APIs.SCHEDULER_BASE}/${encodeURIComponent(jobId)}/history/${encodeURIComponent(executionId)}`
    );
    return response;
  };

  return {
    getEnums,
    validateCron,
    getUpcoming,
    createSchedule,
    listSchedules,
    getSchedule,
    updateSchedule,
    deleteSchedule,
    pauseSchedule,
    resumeSchedule,
    runNow,
    getHistory,
    getExecutionDetail,
  };
};
