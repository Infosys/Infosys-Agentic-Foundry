import { APIs } from "../constant";
import useFetch from "../Hooks/useAxios";
import { extractErrorMessage } from "../utils/errorUtils";

export const useSystemUtilityService = () => {
  const { fetchData, postData } = useFetch();

  /**
   * Trigger backup & export for a given user email.
   * POST /utility/backup-and-export
   */
  const backupAndExport = async (userEmail) => {
    try {
      const response = await postData(APIs.BACKUP_AND_EXPORT, {
        user_email: userEmail,
      });
      return response;
    } catch (error) {
      return extractErrorMessage(error);
    }
  };

  /**
   * Preview items that would be cleaned up.
   * POST /utility/cleanup/preview
   */
  const cleanupPreview = async (sendEmails = true) => {
    try {
      const response = await postData(APIs.CLEANUP_PREVIEW, {
        send_emails: sendEmails,
      });
      return response;
    } catch (error) {
      return extractErrorMessage(error);
    }
  };

  /**
   * Execute the actual cleanup/deletion.
   * POST /utility/cleanup/execute
   */
  const cleanupExecute = async () => {
    try {
      const response = await postData(APIs.CLEANUP_EXECUTE, {});
      return response;
    } catch (error) {
      return extractErrorMessage(error);
    }
  };

  /**
   * List all cleanup/deletion report files.
   * GET /utility/cleanup/reports/list
   */
  const listCleanupReports = async () => {
    try {
      const response = await fetchData(APIs.CLEANUP_REPORTS_LIST);
      return response;
    } catch (error) {
      return extractErrorMessage(error);
    }
  };

  /**
   * Build the full download URL for a report file.
   * GET /utility/cleanup/report/download/{filename}
   */
  const getReportDownloadUrl = (filename) => {
    return `${APIs.CLEANUP_REPORT_DOWNLOAD}${encodeURIComponent(filename)}`;
  };

  /**
   * Download a report file as a blob.
   * @param {string} downloadUrl - The relative download URL path
   * @returns {Promise<Blob>}
   */
  const downloadReport = (downloadUrl) => {
    return fetchData(downloadUrl, {
      responseType: "blob",
    });
  };

  return {
    backupAndExport,
    cleanupPreview,
    cleanupExecute,
    listCleanupReports,
    getReportDownloadUrl,
    downloadReport,
  };
};