import { useEffect, useState, useRef } from "react";
import style from "../../css_modules/InferenceUploadfile.module.css";
import Loader from "../commonComponents/Loader.jsx";
import { BASE_URL, APIs } from "../../constant";
import useFetch from "../../Hooks/useAxios";
import SVGIcons from "../../Icons/SVGIcons";
import DocViewerModal from "../DocViewerModal/DocViewerModal";
import { useMessage } from "../../Hooks/MessageContext.js";
import { sanitizeFormField, isValidEvent } from "../../utils/sanitization";

function MessageUpdateform(props) {
  const { hideComponent, showKnowledge } = props;
  const [loading, setLoading] = useState(false);
  const [files, setFiles] = useState([]);
  const [responseData, setresponseData] = useState({});
  const [inputValues, setInputValues] = useState({
    subdirectory: "",
    search: "",
  });
  const { fetchData, getSessionId, postData, deleteData } = useFetch();
  const [isFormValid, setIsFormValid] = useState(false);
  const [kbloader, setKbloader] = useState(false);
  const { addMessage } = useMessage();

  // Ref to track if initial fetch has been done (persists across StrictMode remounts)
  const hasFetchedRef = useRef(false);

  // Fetch file list on mount - prevents double calls in StrictMode
  useEffect(() => {
    // Skip if already fetched or if showKnowledge is true
    if (hasFetchedRef.current || showKnowledge) {
      return;
    }

    const loadFiles = async () => {
      hasFetchedRef.current = true;
      try {
        const data = await fetchData(APIs.GET_ALLUPLOADFILELIST);
        setresponseData(data?.user_uploads);
      } catch (e) {
        console.error(e);
      }
    };

    loadFiles();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Patch hideComponent to respect a flag set during delete
  const safeHideComponent = (...args) => {
    if (window.preventModalCloseAfterDelete) return;
    if (typeof hideComponent === "function") hideComponent(...args);
  };

  const handleInputChange = (event) => {
    // Validate event structure before destructuring
    if (!isValidEvent(event)) {
      return;
    }

    const { name, value } = event.target;

    // Sanitize value using centralized utility
    const sanitizedValue = sanitizeFormField(name, value);

    setInputValues((prev) => ({ ...prev, [name]: sanitizedValue }));
  };

  const handleKBChange = (event) => {
    // Validate event structure before destructuring
    if (!isValidEvent(event)) {
      return;
    }

    const name = event.target.name;
    const value = event.target.value;

    // Sanitize value using centralized utility
    const sanitizedValue = sanitizeFormField(name, value);

    setInputValues((prev) => ({ ...prev, [name]: sanitizedValue }));
    setIsFormValid(sanitizedValue.trim() !== "");
  };

  const SUPPORTED_EXTENSIONS = showKnowledge
    ? [".pdf", ".txt"]
    : [".pdf", ".docx", ".ppt", ".pptx", ".txt", ".xlsx", ".msg", ".json", ".img", ".db", ".jpg", ".png", ".jpeg", ".csv", ".pkl", ".zip", ".tar", ".eml"];

  const isSupportedFile = (file) => {
    const fileName = file.name.toLowerCase();
    return SUPPORTED_EXTENSIONS.some((ext) => fileName.endsWith(ext));
  };

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
    const droppedFiles = Array.from(event.dataTransfer.files);
    const validFiles = droppedFiles.filter(isSupportedFile);
    if (validFiles.length !== droppedFiles.length) {
      addMessage("Unsupported file added", "error");
    }
    setFiles(validFiles);
  };

  const fetchAgents = async () => {
    if (!showKnowledge) {
      try {
        const data = await fetchData(APIs.GET_ALLUPLOADFILELIST);
        setresponseData(data?.user_uploads);
      } catch (e) {
        console.error(e);
      }
    }
  };

  const handleSubmit = async (event) => {
    event.preventDefault();
    const formData = new FormData();
    files.forEach((f) => formData.append("files", f));
    try {
      const response = await postData(`${APIs.UPLOAD_FILES}?subdirectory=${encodeURIComponent(inputValues.subdirectory || "")}`, formData);
      addMessage(response.info, "success");
      setInputValues({ subdirectory: "", search: "" });
      fetchAgents();
      setFiles([]);
    } catch (error) {
      console.error("Error uploading file", error);
      const errorMessage = error?.response?.data?.detail;
      addMessage(errorMessage, "error");
    }
  };

  const toolSubmit = async (event) => {
    setKbloader(true);
    event.preventDefault();
    const kbName = inputValues.knowledgeBaseName;
    const url = `${APIs.UPLOAD_KB_DOCUMENT}?kb_name=${encodeURIComponent(kbName || "")}`;
    const formData = new FormData();
    formData.append("session_id", getSessionId());
    files.forEach((f) => formData.append("files", f));
    try {
      const response = await postData(url, formData);
      addMessage(response.message, "success");
      setKbloader(false);
      setInputValues({ knowledgeBaseName: "", search: "" });
      fetchAgents();
      setFiles([]);
    } catch (error) {
      console.error("Error uploading file", error);
      addMessage(error?.response?.detail, "error");
      setKbloader(false);
    }
  };

  const deletefile = async (heading, value) => {
    const isFilesPath = heading === "__files__";
    const encodedHeader = encodeURIComponent(heading);
    const encodedFile = encodeURIComponent(value);
    const url = isFilesPath ? `${APIs.DELETE_FILE}?file_path=${encodedFile}` : `${APIs.DELETE_FILE}?file_path=${encodedHeader}/${encodedFile}`;

    setLoading(true);
    try {
      const deleteResponse = await deleteData(url, { maxBodyLength: Infinity });
      if (deleteResponse) {
        addMessage(deleteResponse.info, "success");
        window.preventModalCloseAfterDelete = true;
        setTimeout(() => {
          window.preventModalCloseAfterDelete = false;
          fetchAgents();
        }, 1500);
      } else {
        addMessage("Delete failed (no response)", "error");
      }
    } catch {
      addMessage("Error Deleting File", "error");
    } finally {
      setLoading(false);
    }
  };

  const handledelete = (heading, value) => async (e) => {
    e.preventDefault();
    await deletefile(heading, value);
  };

  const extractFilename = (disposition, fallback) => {
    if (!disposition) return fallback;
    const match = /filename\*?=(?:UTF-8'')?["']?([^"';]+)["']?/i.exec(disposition);
    return decodeURIComponent(match?.[1] || fallback);
  };

  const triggerBrowserDownload = (blob, fileName) => {
    const url = URL.createObjectURL(blob);
    try {
      const link = document.createElement("a");
      link.href = url;
      link.download = fileName;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
    } finally {
      setTimeout(() => URL.revokeObjectURL(url), 1500);
    }
  };

  const downloadFile = async (url, fallbackName) => {
    try {
      const response = await fetchData(url, { responseType: "blob" });
      const isAxios = response && response.data !== undefined && response.headers !== undefined;
      const dataBlob = isAxios ? response.data : response;
      const headers = isAxios ? response.headers : response?.headers || {};
      const getHeader = typeof headers.get === "function" ? (k) => headers.get(k) : (k) => headers[k.toLowerCase()];
      const contentType = getHeader && getHeader("content-type");
      const disposition = getHeader && getHeader("content-disposition");

      if (contentType && contentType.includes("application/json")) {
        addMessage("Unable to download file (server returned JSON).", "error");
        return;
      }

      const fileName = extractFilename(disposition, fallbackName);
      const finalBlob = dataBlob instanceof Blob ? dataBlob : new Blob([dataBlob], { type: contentType || "application/octet-stream" });
      triggerBrowserDownload(finalBlob, fileName);
      addMessage(`${fileName} downloaded successfully`, "success");
    } catch (err) {
      console.error("Download failed:", err);
      addMessage("Failed to download file", "error");
    }
  };

  const handleDownload = async (event, paramone) => {
    event.preventDefault();
    await downloadFile(`${APIs.DOWNLOAD_FILE}?filename=${encodeURIComponent(paramone)}`, paramone);
  };

  const handleDownloadwithuser = async (event, paramone, secondparam) => {
    event.preventDefault();
    await downloadFile(`${APIs.DOWNLOAD_FILE}?filename=${encodeURIComponent(paramone)}&sub_dir_name=${encodeURIComponent(secondparam)}`, paramone);
  };

  const [viewUrl, setViewUrl] = useState("");
  const [showFile, setShowFile] = useState(false);
  const [expandedFolders, setExpandedFolders] = useState({});

  // Toggle folder accordion
  const toggleFolder = (folderPath, depth) => {
    setExpandedFolders((prev) => {
      // If folder state is undefined, set it based on current default (opposite of what it should collapse/expand to)
      const currentState = prev[folderPath] !== undefined ? prev[folderPath] : depth === 0;
      return {
        ...prev,
        [folderPath]: !currentState,
      };
    });
  };

  // Check if folder is expanded (default to expanded for root level)
  const isFolderExpanded = (folderPath, depth) => {
    if (expandedFolders[folderPath] === undefined) {
      return depth === 0; // Root level folders expanded by default
    }
    return expandedFolders[folderPath];
  };

  const handleViewFile = async (event, paramone) => {
    event.preventDefault();
    setViewUrl(`${BASE_URL}/download?filename=${encodeURIComponent(paramone)}`);
    setShowFile(true);
  };
  const handleViewFilewithuser = async (event, paramone, secondparam) => {
    event.preventDefault();
    setViewUrl(`${BASE_URL}/download?filename=${encodeURIComponent(paramone)}&sub_dir_name=${encodeURIComponent(secondparam)}`);
    setShowFile(true);
  };

  // Recursive function to filter nested folder structure based on search
  const filterNestedData = (data, searchTerm) => {
    if (!data || typeof data !== "object") return null;

    const result = {};
    const search = (searchTerm || "").toLowerCase();

    for (const key of Object.keys(data)) {
      if (key === "__files__") {
        // Filter files array
        const filteredFiles = data[key].filter((file) => typeof file === "string" && file.toLowerCase().includes(search));
        if (filteredFiles.length > 0) {
          result.__files__ = filteredFiles;
        }
      } else {
        // Recursively filter subdirectories
        const filteredSubDir = filterNestedData(data[key], searchTerm);
        if (filteredSubDir && Object.keys(filteredSubDir).length > 0) {
          result[key] = filteredSubDir;
        }
      }
    }

    return Object.keys(result).length > 0 ? result : null;
  };

  const filteredResponseData = filterNestedData(responseData, inputValues.search) || {};

  // Recursive component to render folder structure
  const renderFolderStructure = (data, parentPath = "", depth = 0) => {
    if (!data || typeof data !== "object") return null;

    const folders = Object.keys(data).filter((key) => key !== "__files__");
    const files = data.__files__ || [];

    // Check if there's any content to display
    const hasAnyContent =
      files.length > 0 ||
      folders.some((f) => {
        const folderData = data[f];
        return folderData?.__files__?.length > 0 || Object.keys(folderData || {}).filter((k) => k !== "__files__").length > 0;
      });

    if (!hasAnyContent && depth === 0) {
      return (
        <div className={style["emptyStateContainer"]}>
          <div className={style["emptyStateIcon"]}>📁</div>
          <p className={style["emptyStateTitle"]}>No files uploaded yet</p>
          <p className={style["emptyStateSubtitle"]}>Upload files using the section above</p>
        </div>
      );
    }

    // Helper function to get file icon based on extension
    const getFileIcon = (fileExtension) => {
      if (["pdf"].includes(fileExtension)) return "📄";
      if (["doc", "docx"].includes(fileExtension)) return "📝";
      if (["xls", "xlsx", "csv"].includes(fileExtension)) return "📊";
      if (["jpg", "jpeg", "png", "img", "gif", "bmp", "svg", "webp"].includes(fileExtension)) return "🖼️";
      if (["json", "db", "sql"].includes(fileExtension)) return "🗃️";
      if (["zip", "tar", "pkl", "rar", "7z", "gz"].includes(fileExtension)) return "📦";
      if (["ppt", "pptx"].includes(fileExtension)) return "📽️";
      if (["msg", "eml"].includes(fileExtension)) return "✉️";
      if (["mp3", "wav", "ogg", "flac", "aac", "wma", "m4a"].includes(fileExtension)) return "🎵";
      if (["mp4", "avi", "mov", "mkv", "wmv", "flv", "webm", "vid", "m4v"].includes(fileExtension)) return "🎬";
      if (["txt", "log", "md"].includes(fileExtension)) return "📃";
      if (["py", "js", "jsx", "ts", "tsx", "html", "css", "java", "cpp", "c"].includes(fileExtension)) return "💻";
      return "📄";
    };

    // Render file list
    const renderFiles = (filesList, sectionKey, currentPath) => (
      <ul className={style["no-bullets"]}>
        {filesList.map((item, index) => {
          const fileExtension = item.split(".").pop()?.toLowerCase();
          return (
            <div className={style["listitem"]} key={`${sectionKey}-file-${index}`}>
              <li>
                <span className={style["fileIcon"]}>{getFileIcon(fileExtension)}</span>
                {item}
              </li>
              <div className={style["optionscontainer"]}>
                {(item.includes(".pdf") || item.includes(".docx")) && (
                  <button
                    className={style["ButtonStyle"]}
                    title="View file"
                    onClick={(event) => (currentPath === "" ? handleViewFile(event, item) : handleViewFilewithuser(event, item, currentPath))}>
                    <SVGIcons icon="eyeIcon" width={14} height={14} fill="#16a34a" />
                  </button>
                )}
                <button
                  className={style["ButtonStyle"]}
                  title="Download file"
                  onClick={(event) => {
                    event.preventDefault();
                    if (currentPath === "") {
                      handleDownload(event, item);
                    } else {
                      handleDownloadwithuser(event, item, currentPath);
                    }
                  }}>
                  <SVGIcons icon="download" width={14} height={14} fill="#2563eb" />
                </button>
                <button className={style["ButtonStyle"]} title="Delete file" onClick={handledelete(sectionKey, item)}>
                  <SVGIcons icon="fa-trash" width={12} height={12} fill="#dc2626" />
                </button>
              </div>
            </div>
          );
        })}
      </ul>
    );

    const rootFolderPath = "__root__";
    const isRootExpanded = isFolderExpanded(rootFolderPath, 0);

    return (
      <>
        {/* Render root level files in accordion */}
        {depth === 0 && files.length > 0 && (
          <div className={style["folderAccordion"]}>
            <button
              type="button"
              className={`${style["folderHeader"]} ${isRootExpanded ? style["folderHeaderExpanded"] : ""}`}
              onClick={() => toggleFolder(rootFolderPath, 0)}
              aria-expanded={isRootExpanded}>
              <span className={style["folderToggleIcon"]}>{isRootExpanded ? "▼" : "▶"}</span>
              <SVGIcons icon="folder" width={16} height={16} fill="#3b82f6" />
              <span className={style["folderName"]}>Root Directory</span>
              <span className={style["fileCount"]}>
                {files.length} file{files.length !== 1 ? "s" : ""}
              </span>
            </button>
            <div className={`${style["folderContent"]} ${isRootExpanded ? style["folderContentExpanded"] : ""}`}>{renderFiles(files, "__files__", "")}</div>
          </div>
        )}

        {/* Render files at non-root level (no accordion needed, parent handles it) */}
        {depth > 0 && files.length > 0 && renderFiles(files, parentPath, parentPath)}

        {/* Render subfolders as accordions */}
        {folders.map((folderName) => {
          const newPath = parentPath ? `${parentPath}/${folderName}` : folderName;
          const hasContent = data[folderName]?.__files__?.length > 0 || Object.keys(data[folderName] || {}).filter((k) => k !== "__files__").length > 0;

          if (!hasContent) return null;

          const isExpanded = isFolderExpanded(newPath, depth);
          const subFiles = data[folderName]?.__files__ || [];
          const subFolders = Object.keys(data[folderName] || {}).filter((k) => k !== "__files__");
          const totalItems = subFiles.length + subFolders.length;

          return (
            <div key={`folder-${newPath}`} className={`${style["folderAccordion"]} ${depth > 0 ? style["nestedFolder"] : ""}`}>
              <button
                type="button"
                className={`${style["folderHeader"]} ${isExpanded ? style["folderHeaderExpanded"] : ""}`}
                onClick={() => toggleFolder(newPath, depth)}
                aria-expanded={isExpanded}>
                <span className={style["folderToggleIcon"]}>{isExpanded ? "▼" : "▶"}</span>
                <SVGIcons icon="folder" width={16} height={16} fill={isExpanded ? "#3b82f6" : "#64748b"} />
                <span className={style["folderName"]}>{folderName}</span>
                <span className={style["fileCount"]}>
                  {totalItems} item{totalItems !== 1 ? "s" : ""}
                </span>
              </button>
              <div className={`${style["folderContent"]} ${isExpanded ? style["folderContentExpanded"] : ""}`}>{renderFolderStructure(data[folderName], newPath, depth + 1)}</div>
            </div>
          );
        })}
      </>
    );
  };

  const handleRemoveFile = (index) => (event) => {
    event.preventDefault();
    setFiles((prev) => prev.filter((_, i) => i !== index));
  };

  return (
    <div id="myOverlay" className={style["overlay"]}>
      {loading && <Loader />}
      <div className={`${style["form-container"]} ${style["updateformonly"]}`} onDrop={handleDrop} onDragOver={(e) => e.preventDefault()}>
        <div className={style["container"]}>
          <div className={style["main"]}>
            <form className={style["file-upload-form"]}>
              <div className={style["form-content"]}>
                <div className={style["uploadfileheader"]}>
                  <h3>Upload Files</h3>
                  <div className={style["sidebar"]}>
                    <div className={style["toggle"]}>
                      <button type="button" className={style["closebtn"]} onClick={safeHideComponent} aria-label="Close">
                        &times;
                      </button>
                    </div>
                  </div>
                </div>
                <div className={style["uploadfilesection"]}>
                  {files.length > 0 ? (
                    <div className={style["file-list"]}>
                      {files.map((file, index) => (
                        <div className={style["file-item"]} key={index}>
                          <div className="file-info">
                            <p>📎 {file.name}</p>
                          </div>
                          <button type="button" className={style["closebtntwo"]} onClick={handleRemoveFile(index)} aria-label="Remove file">
                            &times;
                          </button>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <div className={style["customFileUploadContainer"]}>
                      <section className={style["customDragDrop"]}>
                        <div className={style["customFileUploadBox"]}>
                          <span className={style["customUploadPrompt"]}>Click to upload or drag & drop</span>
                          <div className={style["customSupportedExtensions"]}>{showKnowledge ? "Supported: PDF, TXT" : "PDF, DOCX, PPTX, TXT, XLSX, JSON, CSV, Images & more"}</div>
                          <input
                            type="file"
                            id="browse"
                            onChange={handleFileChange}
                            accept={showKnowledge ? ".pdf,.txt" : ".pdf, .docx, .pptx, .txt, .xlsx, .msg, .json, .img, .db, .jpg, .png, .jpeg, .csv, .pkl, .zip, .tar, .eml"}
                            multiple={showKnowledge ? true : false}
                            className={style["hiddenInput"]}
                          />
                          <label htmlFor="browse" className={style["hiddenInputLabel"]}></label>
                        </div>
                      </section>
                    </div>
                  )}

                  {showKnowledge ? (
                    <div className={style["url-section"]}>
                      <label className={style["label-desc"]} htmlFor="url">
                        Knowledge Base Name
                      </label>
                      <input
                        id="url"
                        type="text"
                        name="knowledgeBaseName"
                        value={inputValues.knowledgeBaseName || ""}
                        onChange={handleKBChange}
                        placeholder="Enter a name for your knowledge base"
                        required
                      />
                    </div>
                  ) : (
                    <>
                      <span></span>
                      <div className={style["url-section"]}>
                        <label className={style["label-desc"]} htmlFor="url">
                          Subdirectory Name (Optional)
                        </label>
                        <input
                          id="url"
                          type="text"
                          name="subdirectory"
                          value={inputValues.subdirectory}
                          onChange={handleInputChange}
                          placeholder="Leave blank for root directory"
                        />
                      </div>
                    </>
                  )}

                  <div className={style["button-class"]}>
                    <button type="button" onClick={safeHideComponent} className={style["cancel-button"]}>
                      Cancel
                    </button>
                    {showKnowledge ? (
                      <button type="button" className="iafButton iafButtonPrimary" onClick={toolSubmit} disabled={!isFormValid || files.length === 0 || kbloader}>
                        {kbloader ? "Uploading..." : "Upload"}
                      </button>
                    ) : (
                      <button type="button" className="iafButton iafButtonPrimary" onClick={handleSubmit} disabled={files.length === 0}>
                        Upload Files
                      </button>
                    )}
                  </div>
                </div>
              </div>

              {!showKnowledge && (
                <>
                  <div className={style["subnav"]}>
                    <div className={style["header"]}>
                      <h1 className={style["subText"]}>Your Files</h1>
                      <div className={style["underline"]}></div>
                    </div>
                    <div className={style["search-outer-container"]}>
                      <div className={style.searchContainer}>
                        <input type="search" name="search" className={style.searchInput} placeholder="Search files..." value={inputValues.search} onChange={handleInputChange} />
                        <SVGIcons icon="search" fill="#64748b" width={14} height={14} />
                      </div>
                    </div>
                  </div>

                  <div className={style["documentslistconatiner"]}>{renderFolderStructure(filteredResponseData)}</div>
                </>
              )}
            </form>
          </div>
        </div>
      </div>
      {showFile && (
        <DocViewerModal
          url={viewUrl}
          onClose={() => {
            setShowFile(false);
          }}
        />
      )}
    </div>
  );
}

export default MessageUpdateform;
