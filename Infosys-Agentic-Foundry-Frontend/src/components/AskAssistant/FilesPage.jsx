import { useEffect, useState, useRef } from "react";
import styles from "./FilesPage.module.css";
import Loader from "../commonComponents/Loader.jsx";
import { BASE_URL, APIs } from "../../constant.js";
import useFetch from "../../Hooks/useAxios.js";
import SVGIcons from "../../Icons/SVGIcons.js";
import DocViewerModal from "../DocViewerModal/DocViewerModal.jsx";
import { useMessage } from "../../Hooks/MessageContext.js";
import { sanitizeFormField, isValidEvent } from "../../utils/sanitization.js";
import TextField from "../../iafComponents/GlobalComponents/TextField/TextField.jsx";
import IAFButton from "../../iafComponents/GlobalComponents/Buttons/Button.jsx";
import UploadBox from "../commonComponents/UploadBox.jsx";

/**
 * FilesPage - A full-screen modal for managing user files
 * Following the modal pattern used by AgentForm, ToolOnBoarding, etc.
 */
function MessageUpdateform(props) {
  const { hideComponent, showKnowledge } = props;
  const [loading, setLoading] = useState(false);
  const [isLoadingFiles, setIsLoadingFiles] = useState(true);
  const [files, setFiles] = useState([]);
  const [responseData, setResponseData] = useState({});
  const [searchValue, setSearchValue] = useState("");
  const [subdirectory, setSubdirectory] = useState("");
  const [selectedFolder, setSelectedFolder] = useState("__all__");
  const [showUploadModal, setShowUploadModal] = useState(false);
  const [isDragging, setIsDragging] = useState(false);
  const [kbName, setKbName] = useState("");
  const [kbloader, setKbloader] = useState(false);
  const [viewUrl, setViewUrl] = useState("");
  const [viewFileName, setViewFileName] = useState("");
  const [showFile, setShowFile] = useState(false);
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState({ folderPath: "", fileName: "" });

  const { fetchData, getSessionId, postData, deleteData } = useFetch();
  const { addMessage } = useMessage();
  const hasFetchedRef = useRef(false);

  // Fetch file list on mount
  useEffect(() => {
    if (hasFetchedRef.current || showKnowledge) return;

    const loadFiles = async () => {
      hasFetchedRef.current = true;
      setIsLoadingFiles(true);
      try {
        const data = await fetchData(APIs.GET_ALLUPLOADFILELIST);
        setResponseData(data?.user_uploads || {});
      } catch (e) {
        console.error(e);
      } finally {
        setIsLoadingFiles(false);
      }
    };

    loadFiles();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Refresh files after operations
  const refreshFiles = async () => {
    try {
      const data = await fetchData(APIs.GET_ALLUPLOADFILELIST);
      setResponseData(data?.user_uploads || {});
    } catch (e) {
      console.error(e);
    }
  };

  // Supported file extensions
  const SUPPORTED_EXTENSIONS = showKnowledge
    ? [".pdf", ".txt"]
    : [".pdf", ".docx", ".ppt", ".pptx", ".txt", ".xlsx", ".msg", ".json", ".img", ".db", ".jpg", ".png", ".jpeg", ".csv", ".pkl", ".zip", ".tar", ".eml"];

  const isSupportedFile = (file) => {
    const fileName = file.name.toLowerCase();
    return SUPPORTED_EXTENSIONS.some((ext) => fileName.endsWith(ext));
  };

  // File handlers
  const handleFileChange = (event) => {
    const selectedFiles = Array.from(event.target.files);
    const validFiles = selectedFiles.filter(isSupportedFile);
    if (validFiles.length !== selectedFiles.length) {
      addMessage("Unsupported file added", "error");
    }
    setFiles(validFiles);
  };

  const handleDrop = (event) => {
    event.preventDefault();
    setIsDragging(false);
    const droppedFiles = Array.from(event.dataTransfer.files);
    const validFiles = droppedFiles.filter(isSupportedFile);
    if (validFiles.length !== droppedFiles.length) {
      addMessage("Unsupported file added", "error");
    }
    setFiles(validFiles);
  };

  const handleDragOver = (event) => {
    event.preventDefault();
    setIsDragging(true);
  };

  const handleDragLeave = () => {
    setIsDragging(false);
  };

  const handleRemoveFile = (index) => {
    setFiles((prev) => prev.filter((_, i) => i !== index));
  };

  // Upload handlers
  const handleSubmit = async () => {
    if (files.length === 0) return;

    setLoading(true);
    const formData = new FormData();
    files.forEach((f) => formData.append("files", f));
    try {
      const response = await postData(`${APIs.UPLOAD_FILES}?subdirectory=${encodeURIComponent(subdirectory || "")}`, formData);
      addMessage(response.info, "success");
      setSubdirectory("");
      setFiles([]);
      setShowUploadModal(false);
      refreshFiles();
    } catch (error) {
      console.error("Error uploading file", error);
      const errorMessage = error?.response?.data?.detail;
      addMessage(errorMessage || "Error uploading file", "error");
    } finally {
      setLoading(false);
    }
  };

  const toolSubmit = async () => {
    if (files.length === 0 || !kbName.trim()) return;

    setKbloader(true);
    const url = `${APIs.KB_UPLOAD_DOCUMENTS}?kb_name=${encodeURIComponent(kbName || "")}`;
    const formData = new FormData();
    formData.append("session_id", getSessionId());
    files.forEach((f) => formData.append("files", f));
    try {
      const response = await postData(url, formData);
      addMessage(response.message, "success");
      setKbName("");
      setFiles([]);
      setShowUploadModal(false);
      refreshFiles();
    } catch (error) {
      console.error("Error uploading file", error);
      addMessage(error?.response?.detail || "Error uploading file", "error");
    } finally {
      setKbloader(false);
    }
  };

  // Delete handler - opens confirmation modal
  const handleDelete = (folderPath, fileName) => {
    setDeleteTarget({ folderPath, fileName });
    setShowDeleteConfirm(true);
  };

  // Confirm delete handler - performs actual deletion
  const confirmDelete = async () => {
    const { folderPath, fileName } = deleteTarget;
    const isRootFile = folderPath === "__files__";
    const url = isRootFile
      ? `${APIs.DELETE_FILE}?file_path=${encodeURIComponent(fileName)}`
      : `${APIs.DELETE_FILE}?file_path=${encodeURIComponent(folderPath)}/${encodeURIComponent(fileName)}`;

    setLoading(true);
    setShowDeleteConfirm(false);
    try {
      const deleteResponse = await deleteData(url, { maxBodyLength: Infinity });
      if (deleteResponse) {
        addMessage(deleteResponse.info || "File deleted successfully", "success");
        refreshFiles();
      } else {
        addMessage("Delete failed", "error");
      }
    } catch (error) {
      addMessage(error?.response?.data?.detail || "Error deleting file", "error");
    } finally {
      setLoading(false);
      setDeleteTarget({ folderPath: "", fileName: "" });
    }
  };

  // Cancel delete handler
  const cancelDelete = () => {
    setShowDeleteConfirm(false);
    setDeleteTarget({ folderPath: "", fileName: "" });
  };

  // Download handler
  const handleDownload = async (fileName, subDir = "") => {
    const url = subDir
      ? `${APIs.DOWNLOAD_FILE}?filename=${encodeURIComponent(fileName)}&sub_dir_name=${encodeURIComponent(subDir)}`
      : `${APIs.DOWNLOAD_FILE}?filename=${encodeURIComponent(fileName)}`;

    try {
      const response = await fetchData(url, { responseType: "blob" });
      const isAxios = response && response.data !== undefined && response.headers !== undefined;
      const dataBlob = isAxios ? response.data : response;
      const headers = isAxios ? response.headers : response?.headers || {};
      const getHeader = typeof headers.get === "function" ? (k) => headers.get(k) : (k) => headers[k.toLowerCase()];
      const contentType = getHeader && getHeader("content-type");
      const disposition = getHeader && getHeader("content-disposition");

      if (contentType && contentType.includes("application/json")) {
        addMessage("Unable to download file", "error");
        return;
      }

      const extractedName = disposition ? /filename\*?=(?:UTF-8'')?["']?([^"';]+)["']?/i.exec(disposition)?.[1] : null;
      const finalName = extractedName ? decodeURIComponent(extractedName) : fileName;
      const finalBlob = dataBlob instanceof Blob ? dataBlob : new Blob([dataBlob], { type: contentType || "application/octet-stream" });

      const blobUrl = URL.createObjectURL(finalBlob);
      const link = document.createElement("a");
      link.href = blobUrl;
      link.download = finalName;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      setTimeout(() => URL.revokeObjectURL(blobUrl), 1500);

      addMessage(`${finalName} downloaded successfully`, "success");
    } catch (err) {
      console.error("Download failed:", err);
      addMessage("Failed to download file", "error");
    }
  };

  // View file handler - fetches blob once to prevent multiple API calls
  const handleViewFile = async (fileName, subDir = "") => {
    const url = subDir
      ? `${APIs.DOWNLOAD_FILE}?filename=${encodeURIComponent(fileName)}&sub_dir_name=${encodeURIComponent(subDir)}`
      : `${APIs.DOWNLOAD_FILE}?filename=${encodeURIComponent(fileName)}`;

    try {
      setLoading(true);
      const response = await fetchData(url, { responseType: "blob" });

      // Handle both axios and fetch response formats
      const isAxios = response && response.data !== undefined && response.headers !== undefined;
      const dataBlob = isAxios ? response.data : response;
      const headers = isAxios ? response.headers : response?.headers || {};
      const getHeader = typeof headers.get === "function" ? (k) => headers.get(k) : (k) => headers[k.toLowerCase()];
      const contentType = getHeader && getHeader("content-type");

      if (contentType && contentType.includes("application/json")) {
        addMessage("Unable to view file", "error");
        return;
      }

      // Determine the correct MIME type based on file extension for proper preview
      const getMimeType = (name) => {
        const ext = name.split(".").pop()?.toLowerCase();
        const mimeTypes = {
          pdf: "application/pdf",
          docx: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
          xlsx: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
          xls: "application/vnd.ms-excel",
          jpg: "image/jpeg",
          jpeg: "image/jpeg",
          png: "image/png",
          gif: "image/gif",
          bmp: "image/bmp",
          svg: "image/svg+xml",
          webp: "image/webp",
          ico: "image/x-icon",
          txt: "text/plain",
          json: "application/json",
          xml: "application/xml",
          csv: "text/csv",
          log: "text/plain",
        };
        return mimeTypes[ext] || contentType || "application/octet-stream";
      };

      const mimeType = getMimeType(fileName);

      // Always create a new Blob with the correct MIME type to ensure proper preview
      // This fixes the issue where PDFs were being downloaded instead of displayed
      let finalBlob;
      if (dataBlob instanceof Blob) {
        // Re-create blob with correct MIME type to ensure browser renders it properly
        const arrayBuffer = await dataBlob.arrayBuffer();
        finalBlob = new Blob([arrayBuffer], { type: mimeType });
      } else {
        finalBlob = new Blob([dataBlob], { type: mimeType });
      }

      // Create blob URL for preview (no actual download to user's system)
      const blobUrl = URL.createObjectURL(finalBlob);

      setViewUrl(blobUrl);
      setViewFileName(fileName);
      setShowFile(true);
    } catch (err) {
      console.error("View file failed:", err);
      addMessage("Failed to load file for viewing", "error");
    } finally {
      setLoading(false);
    }
  };

  // Clean up blob URL when closing viewer to prevent memory leaks
  const handleCloseViewer = () => {
    if (viewUrl && viewUrl.startsWith("blob:")) {
      URL.revokeObjectURL(viewUrl);
    }
    setViewUrl("");
    setViewFileName("");
    setShowFile(false);
  };

  // Get file icon based on extension
  const getFileIcon = (fileName) => {
    const ext = fileName.split(".").pop()?.toLowerCase();
    if (["pdf"].includes(ext)) return "file-pdf";
    if (["csv", "xlsx", "xls"].includes(ext)) return "file-csv";
    if (["jpg", "jpeg", "png", "gif", "bmp", "svg", "webp", "img"].includes(ext)) return "file-image";
    return "file-default";
  };

  // Helper to recursively count all files in a folder and its subfolders
  const countAllFilesRecursively = (data) => {
    if (!data || typeof data !== "object") return 0;

    let count = data.__files__?.length || 0;
    const folders = Object.keys(data).filter((key) => key !== "__files__");

    folders.forEach((folderName) => {
      count += countAllFilesRecursively(data[folderName]);
    });

    return count;
  };

  // Build folder structure with file counts (including nested children)
  const buildFolderStructure = (data, parentPath = "") => {
    if (!data || typeof data !== "object") return [];

    const result = [];
    const folders = Object.keys(data).filter((key) => key !== "__files__");

    // Process folders
    folders.forEach((folderName) => {
      const folderPath = parentPath ? `${parentPath}/${folderName}` : folderName;
      const folderData = data[folderName];
      const totalFiles = countAllFilesRecursively(folderData); // Count all nested files
      const nestedFolders = buildFolderStructure(folderData, folderPath);
      const depth = parentPath.split("/").filter(Boolean).length;

      result.push({
        name: folderName,
        path: folderPath,
        fileCount: totalFiles,
        depth: depth,
        children: nestedFolders,
      });

      // Add nested folders
      result.push(...nestedFolders);
    });

    return result;
  };

  // Get all files flat list
  const getAllFiles = (data, parentPath = "") => {
    if (!data || typeof data !== "object") return [];

    let result = [];
    const files = data.__files__ || [];
    const folders = Object.keys(data).filter((key) => key !== "__files__");

    // Add files from current level
    files.forEach((fileName) => {
      result.push({
        name: fileName,
        path: parentPath,
        fullPath: parentPath ? `${parentPath}/${fileName}` : fileName,
      });
    });

    // Process subfolders
    folders.forEach((folderName) => {
      const folderPath = parentPath ? `${parentPath}/${folderName}` : folderName;
      result = result.concat(getAllFiles(data[folderName], folderPath));
    });

    return result;
  };

  // Filter files based on search and selected folder
  const getFilteredFiles = () => {
    let allFiles = getAllFiles(responseData);

    // Filter by folder
    if (selectedFolder !== "__all__") {
      if (selectedFolder === "__root__") {
        allFiles = allFiles.filter((f) => f.path === "");
      } else {
        allFiles = allFiles.filter((f) => f.path === selectedFolder || f.path.startsWith(selectedFolder + "/"));
      }
    }

    // Filter by search - search in full path (folder/subfolder/filename)
    if (searchValue.trim()) {
      const search = searchValue.toLowerCase();
      allFiles = allFiles.filter((f) => f.fullPath.toLowerCase().includes(search) || f.name.toLowerCase().includes(search));
    }

    return allFiles;
  };

  // Get direct children (folders and files) for the current folder - used for file explorer view
  const getCurrentFolderContents = () => {
    // Get the folder data for the selected path
    const getFolderData = (data, pathParts) => {
      if (pathParts.length === 0) return data;
      const [first, ...rest] = pathParts;
      if (!data[first]) return null;
      return getFolderData(data[first], rest);
    };

    let folderData;
    if (selectedFolder === "__all__") {
      // For "All Files", show all files flat (no folder navigation)
      return { folders: [], files: getFilteredFiles(), isAllFiles: true };
    } else if (selectedFolder === "__root__") {
      folderData = responseData;
    } else {
      const pathParts = selectedFolder.split("/").filter(Boolean);
      folderData = getFolderData(responseData, pathParts);
    }

    if (!folderData) return { folders: [], files: [], isAllFiles: false };

    // Get direct subfolders - filter out empty folders (with 0 files)
    const subfolders = Object.keys(folderData)
      .filter((key) => key !== "__files__")
      .map((folderName) => ({
        name: folderName,
        path: selectedFolder === "__root__" ? folderName : `${selectedFolder}/${folderName}`,
        fileCount: countAllFilesRecursively(folderData[folderName]),
      }))
      .filter((folder) => folder.fileCount > 0);

    // Get direct files
    const directFiles = (folderData.__files__ || []).map((fileName) => ({
      name: fileName,
      path: selectedFolder === "__root__" ? "" : selectedFolder,
      fullPath: selectedFolder === "__root__" ? fileName : `${selectedFolder}/${fileName}`,
    }));

    // Apply search filter if any - search in full path for files
    let filteredFolders = subfolders;
    let filteredFiles = directFiles;

    if (searchValue.trim()) {
      const search = searchValue.toLowerCase();
      filteredFolders = subfolders.filter((f) => f.name.toLowerCase().includes(search) || f.path.toLowerCase().includes(search));
      filteredFiles = directFiles.filter((f) => f.fullPath.toLowerCase().includes(search) || f.name.toLowerCase().includes(search));
    }

    return { folders: filteredFolders, files: filteredFiles, isAllFiles: false };
  };

  // Navigate to parent folder
  const handleBackNavigation = () => {
    if (selectedFolder === "__root__" || selectedFolder === "__all__") {
      return; // Already at root or all files
    }

    const pathParts = selectedFolder.split("/").filter(Boolean);
    if (pathParts.length <= 1) {
      setSelectedFolder("__root__");
    } else {
      pathParts.pop();
      setSelectedFolder(pathParts.join("/"));
    }
  };

  // Navigate into a folder
  const handleFolderClick = (folderPath) => {
    setSelectedFolder(folderPath);
  };

  // Get current folder contents for file explorer view
  const currentFolderContents = getCurrentFolderContents();

  // Build folder list with counts
  const folderList = buildFolderStructure(responseData);
  const filteredFiles = getFilteredFiles();
  const totalFileCount = getAllFiles(responseData).length;

  // Handle close
  const handleClose = () => {
    if (typeof hideComponent === "function") {
      hideComponent();
    }
  };

  // Handle search change
  const handleSearchChange = (e) => {
    if (isValidEvent(e)) {
      setSearchValue(sanitizeFormField("search", e.target.value));
    }
  };

  // Clear search
  const handleClearSearch = () => {
    setSearchValue("");
  };

  // Can view file types - includes documents, images, and spreadsheets
  const canViewFile = (fileName) => {
    const ext = fileName.split(".").pop()?.toLowerCase();
    const viewableExtensions = [
      // Documents
      "pdf",
      "docx",
      // Spreadsheets
      "xlsx",
      "xls",
      // Images
      "jpg",
      "jpeg",
      "png",
      "gif",
      "bmp",
      "svg",
      "webp",
      "ico",
      // Text files
      "txt",
      "json",
      "xml",
      "csv",
      "log",
    ];
    return viewableExtensions.includes(ext);
  };

  return (
    <>
      <div className={styles.filesOverlay} onClick={handleClose}>
        <div className={styles.filesModal} onClick={(e) => e.stopPropagation()}>
          {/* Header */}
          <div className={styles.modalHeader}>
            <div className={styles.modalHeaderLeft}>
              <h2 className={styles.modalHeaderTitle}>FILES</h2>
            </div>
            <div className={styles.modalHeaderRight}>
              {!showKnowledge && (
                <div className={styles.searchWrapper}>
                  <TextField placeholder="Search Files..." value={searchValue} onChange={handleSearchChange} onClear={handleClearSearch} showSearchButton showClearButton />
                </div>
              )}
              <IAFButton
                type="primary"
                onClick={() => setShowUploadModal(true)}
                icon={<SVGIcons icon="fa-plus" fill="#FFF" width={16} height={16} className={styles.plusIcon} style={{ marginRight: "12px" }} />}>
                {" "}
                Upload File
              </IAFButton>
            </div>
          </div>

          {/* Main Content */}
          <div className={styles.modalMain}>
            {showKnowledge ? (
              /* Knowledge Base Mode - Show upload area directly */
              <div style={{ padding: "24px" }}>
                <p>Knowledge Base upload mode is active.</p>
              </div>
            ) : isLoadingFiles ? (
              /* Loading State */
              <div className={styles.filesMainContent} style={{ display: "flex", justifyContent: "center", alignItems: "center" }}>
                <Loader />
              </div>
            ) : (
              /* Files Mode - Two Column Layout */
              <div className={styles.filesMainContent}>
                {/* Left Panel - Folders */}
                <div className={styles.foldersPanel}>
                  <h3 className={styles.foldersPanelTitle}>Folders</h3>
                  <div className={styles.foldersList}>
                    {/* All Files option */}
                    <button
                      type="button"
                      className={`${styles.folderItem} ${selectedFolder === "__all__" ? styles.folderItemActive : ""}`}
                      onClick={() => setSelectedFolder("__all__")}
                      title="All Files">
                      <div className={styles.folderItemLeft}>
                        <span className={styles.folderItemIcon}>
                          <SVGIcons icon="folder-blue" width={16} height={16} color={selectedFolder === "__all__" ? "var(--app-primary-color)" : "var(--icon-color)"} />
                        </span>
                        <span className={styles.folderItemName}>All Files</span>
                      </div>
                      <span className={styles.folderItemCount}>{totalFileCount}</span>
                    </button>

                    {/* Root Directory */}
                    {responseData.__files__?.length > 0 && (
                      <button
                        type="button"
                        className={`${styles.folderItem} ${selectedFolder === "__root__" ? styles.folderItemActive : ""}`}
                        onClick={() => setSelectedFolder("__root__")}
                        title="Root Directory">
                        <div className={styles.folderItemLeft}>
                          <span className={styles.folderItemIcon}>
                            <SVGIcons icon="folder-blue" width={16} height={16} color={selectedFolder === "__root__" ? "var(--app-primary-color)" : "var(--icon-color)"} />
                          </span>
                          <span className={styles.folderItemName}>Root Directory</span>
                        </div>
                        <span className={styles.folderItemCount}>{responseData.__files__?.length || 0}</span>
                      </button>
                    )}

                    {/* Nested Folders - Hide folders with 0 files */}
                    {folderList
                      .filter((f) => f.path !== "__root__" && f.fileCount > 0)
                      .map((folder) => (
                        <button
                          key={folder.path}
                          type="button"
                          className={`${styles.folderItem} ${selectedFolder === folder.path ? styles.folderItemActive : ""} ${folder.depth > 0 ? styles.nestedFolder : ""}`}
                          onClick={() => setSelectedFolder(folder.path)}
                          title={folder.name}
                          style={{ paddingLeft: `${8 + folder.depth * 16}px` }}>
                          <div className={styles.folderItemLeft}>
                            <span className={styles.folderItemIcon}>
                              <SVGIcons icon="folder-blue" width={16} height={16} color={selectedFolder === folder.path ? "var(--app-primary-color)" : "var(--icon-color)"} />
                            </span>
                            <span className={styles.folderItemName}>{folder.name}</span>
                          </div>
                          <span className={styles.folderItemCount}>{folder.fileCount}</span>
                        </button>
                      ))}
                  </div>
                </div>

                {/* Right Panel - File Explorer View */}
                <div className={styles.filesPanel}>
                  <div className={styles.filesPanelHeader}>
                    {/* Back button - only show when not at root or all files */}
                    {selectedFolder !== "__all__" && selectedFolder !== "__root__" && (
                      <button type="button" className="backButton" onClick={handleBackNavigation} title="Go back">
                        <SVGIcons icon="chevron-left" width={20} height={20} color="#6B7280" />
                      </button>
                    )}
                    <h3 className={styles.filesPanelTitle}>
                      {selectedFolder === "__all__" ? "All Files" : selectedFolder === "__root__" ? "Root Directory" : selectedFolder.split("/").pop()}
                    </h3>
                  </div>

                  {/* Breadcrumb path */}
                  {selectedFolder !== "__all__" && selectedFolder !== "__root__" && (
                    <div className={styles.breadcrumb}>
                      <button type="button" className={styles.breadcrumbItem} onClick={() => setSelectedFolder("__root__")}>
                        Root
                      </button>
                      {selectedFolder.split("/").map((part, idx, arr) => (
                        <span key={idx} className={styles.breadcrumbSeparator}>
                          <span className={styles.breadcrumbSlash}>/</span>
                          <button
                            type="button"
                            className={`${styles.breadcrumbItem} ${idx === arr.length - 1 ? styles.breadcrumbItemActive : ""}`}
                            onClick={() => setSelectedFolder(arr.slice(0, idx + 1).join("/"))}>
                            {part}
                          </button>
                        </span>
                      ))}
                    </div>
                  )}

                  <div className={styles.filesList}>
                    {currentFolderContents.folders.length === 0 && currentFolderContents.files.length === 0 ? (
                      <div className={styles.emptyState}>
                        <div className={styles.emptyStateIcon}>📁</div>
                        <p className={styles.emptyStateTitle}>No files found</p>
                        <p className={styles.emptyStateSubtitle}>{searchValue ? "Try a different search term" : "Upload files using the button above"}</p>
                      </div>
                    ) : (
                      <>
                        {/* Folders first */}
                        {!currentFolderContents.isAllFiles &&
                          currentFolderContents.folders.map((folder) => (
                            <div
                              key={folder.path}
                              className={`${styles.fileItem} ${styles.folderExplorerItem}`}
                              onClick={() => handleFolderClick(folder.path)}
                              role="button"
                              tabIndex={0}
                              onKeyDown={(e) => e.key === "Enter" && handleFolderClick(folder.path)}>
                              <div className={styles.fileItemLeft}>
                                <div className={styles.fileItemIcon}>
                                  <SVGIcons icon="folder-blue" width={20} height={20} color="var(--app-primary-color)" />
                                </div>
                                <div className={styles.fileItemInfo}>
                                  <span className={styles.fileItemName} title={folder.name}>
                                    {folder.name}
                                  </span>
                                </div>
                              </div>
                              <div className={styles.fileItemActions}>
                                <span className={styles.folderFileCount}>{folder.fileCount} files</span>
                                <SVGIcons icon="chevron-right" width={16} height={16} color="#6B7280" />
                              </div>
                            </div>
                          ))}

                        {/* Files */}
                        {currentFolderContents.files.map((file, index) => (
                          <div key={`${file.fullPath}-${index}`} className={styles.fileItem}>
                            <div className={styles.fileItemLeft}>
                              <div className={styles.fileItemIcon}>
                                <SVGIcons icon={getFileIcon(file.name)} width={20} height={20} color="#0073CF" />
                              </div>
                              <div className={styles.fileItemInfo}>
                                <span className={styles.fileItemName} title={file.name}>
                                  {file.name}
                                </span>
                                {/* Show full path below filename when searching */}
                                {searchValue.trim() && file.path && (
                                  <span className={styles.fileItemPath} title={file.fullPath}>
                                    📁 {file.path}
                                  </span>
                                )}
                              </div>
                            </div>
                            <div className={styles.fileItemActions}>
                              {canViewFile(file.name) && (
                                <button type="button" className={styles.actionButton} onClick={() => handleViewFile(file.name, file.path)} title="View file">
                                  <SVGIcons icon="eye" width={16} height={16} color="#6B7280" />
                                </button>
                              )}
                              <button type="button" className={styles.actionButton} onClick={() => handleDownload(file.name, file.path)} title="Download file">
                                <SVGIcons icon="download-file" width={16} height={16} color="#6B7280" />
                              </button>
                              <button
                                type="button"
                                className={`${styles.actionButton} ${styles.actionButtonDelete}`}
                                onClick={() => handleDelete(file.path || "__files__", file.name)}
                                title="Delete file">
                                <SVGIcons icon="trash" width={16} height={16} color="#ef4444" />
                              </button>
                            </div>
                          </div>
                        ))}
                      </>
                    )}
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Loading Overlay */}
      {loading && (
        <div className={styles.loadingWrapper} onClick={(e) => e.stopPropagation()}>
          <Loader />
        </div>
      )}

      {/* Upload Modal */}
      {showUploadModal && (
        <div className={styles.uploadModalOverlay} onClick={() => setShowUploadModal(false)}>
          <div className={styles.uploadModal} onClick={(e) => e.stopPropagation()}>
            <div className={styles.uploadModalHeader}>
              <h3 className={styles.uploadModalTitle}>Upload Files</h3>
              <button type="button" className={styles.uploadModalCloseBtn} onClick={() => setShowUploadModal(false)} aria-label="Close">
                <SVGIcons icon="x" width={20} height={20} color="#6B7280" />
              </button>
            </div>
            <div className={styles.uploadModalBody}>
              {/* Subdirectory / KB Name Input */}
              {showKnowledge ? (
                <div className={styles.subdirectoryInput}>
                  <label for="kb_directory" className="label-desc">
                    Knowledge Base Name
                  </label>
                  <input
                    id="kb_directory"
                    type="text"
                    className={styles.subdirectoryField}
                    value={kbName}
                    onChange={(e) => setKbName(sanitizeFormField("knowledgeBaseName", e.target.value))}
                    placeholder="Enter A Name For Your Knowledge Base"
                  />
                </div>
              ) : (
                <div className={styles.subdirectoryInput}>
                  <label for="sub_dir_name" className="label-desc">
                    Subdirectory Name (Optional)
                  </label>
                  <input
                    id="sub_dir_name"
                    type="text"
                    className={styles.subdirectoryField}
                    value={subdirectory}
                    onChange={(e) => setSubdirectory(sanitizeFormField("subdirectory", e.target.value))}
                    placeholder="Leave Blank For Root Directory"
                  />
                </div>
              )}
              {/* Hidden file input */}
              <input
                type="file"
                id="filesPageUpload"
                className={styles.dragDropInput}
                onChange={handleFileChange}
                accept={showKnowledge ? ".pdf,.txt" : ".pdf,.docx,.pptx,.txt,.xlsx,.msg,.json,.img,.db,.jpg,.png,.jpeg,.csv,.pkl,.zip,.tar,.eml"}
                multiple={!showKnowledge}
                style={{ display: "none" }}
              />
              {/* Drag Drop Area using UploadBox */}
              <UploadBox
                files={files}
                isDragging={isDragging}
                onDragEnter={(e) => {
                  e.preventDefault();
                  e.stopPropagation();
                  setIsDragging(true);
                }}
                onDragLeave={(e) => {
                  e.preventDefault();
                  e.stopPropagation();
                  setIsDragging(false);
                }}
                onDragOver={handleDragOver}
                onDrop={handleDrop}
                onClick={() => document.getElementById("filesPageUpload").click()}
                onRemoveFile={(index) => handleRemoveFile(index)}
                loading={loading || kbloader}
                fileInputId="filesPageUpload"
                acceptedFileTypes={showKnowledge ? ".pdf,.txt" : ".pdf,.docx,.pptx,.txt,.xlsx,.msg,.json,.img,.db,.jpg,.png,.jpeg,.csv,.pkl,.zip,.tar,.eml"}
                supportedText={showKnowledge ? "Supported: PDF, TXT" : "PDF, DOCX, PPTX, TXT, XLSX, JSON, CSV, Images & more"}
                dragText="Drop files here"
                uploadText="Click to upload"
                dragDropText=" or drag and drop"
                multiple={!showKnowledge}
              />
            </div>
            <div className={styles.uploadModalFooter}>
              <IAFButton type="secondary" onClick={() => setShowUploadModal(false)}>
                Cancel
              </IAFButton>
              {showKnowledge ? (
                <IAFButton type="primary" onClick={toolSubmit} disabled={files.length === 0 || !kbName.trim() || kbloader} loading={kbloader}>
                  {kbloader ? "Uploading..." : "Upload"}
                </IAFButton>
              ) : (
                <IAFButton type="primary" onClick={handleSubmit} disabled={files.length === 0 || loading} loading={loading}>
                  Upload Files
                </IAFButton>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Document Viewer Modal */}
      {showFile && (
        <div className="leftMarginForFilesPage">
          <DocViewerModal url={viewUrl} fileName={viewFileName} onClose={handleCloseViewer} />
        </div>
      )}

      {/* Delete Confirmation Modal */}
      {showDeleteConfirm && (
        <div className={styles.deleteConfirmOverlay} onClick={cancelDelete}>
          <div className={styles.deleteConfirmModal} onClick={(e) => e.stopPropagation()}>
            <div className={styles.deleteConfirmIcon}>
              <SVGIcons icon="warnings" width={48} height={48} color="#ef4444" />
            </div>
            <h3 className={styles.deleteConfirmTitle}>Delete File?</h3>
            <p className={styles.deleteConfirmMessage}>
              Are you sure you want to delete <strong>{deleteTarget.fileName}</strong>? This action cannot be undone.
            </p>
            <div className={styles.deleteConfirmActions}>
              <button type="button" className={styles.deleteConfirmCancelBtn} onClick={cancelDelete}>
                Cancel
              </button>
              <button type="button" className={styles.deleteConfirmDeleteBtn} onClick={confirmDelete}>
                Delete
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}

export default MessageUpdateform;
