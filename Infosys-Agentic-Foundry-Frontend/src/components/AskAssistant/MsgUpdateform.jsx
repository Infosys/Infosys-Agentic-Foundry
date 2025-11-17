import { useEffect, useState } from "react";
import style from "../../css_modules/InferenceUploadfile.module.css";
import Loader from "../commonComponents/Loader.jsx";
import { BASE_URL, APIs } from "../../constant";
import useFetch from "../../Hooks/useAxios";
import SVGIcons from "../../Icons/SVGIcons";
// import ToastMessage from "../commonComponents/ToastMessages/ToastMessage.jsx"; // removed
import DocViewerModal from "../DocViewerModal/DocViewerModal";
import { useMessage } from "../../Hooks/MessageContext.js";

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

  useEffect(() => {
    fetchAgents();
  }, []);

  // Patch hideComponent to respect a flag set during delete
  const safeHideComponent = (...args) => {
    if (window.preventModalCloseAfterDelete) return;
    if (typeof hideComponent === "function") hideComponent(...args);
  };

  const handleInputChange = (event) => {
    const { name, value } = event.target;
    setInputValues((prev) => ({ ...prev, [name]: value }));
  };

  const handleKBChange = (event) => {
    const { name, value } = event.target;
    setInputValues((prev) => ({ ...prev, [name]: value }));
    setIsFormValid(value.trim() !== "");
  };

  let SUPPORTED_EXTENSIONS = showKnowledge
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
    files.forEach((f) => formData.append("file", f));
    try {
      await postData(`${APIs.UPLOAD_FILES}?subdirectory=${encodeURIComponent(inputValues.subdirectory || "")}`, formData);
      addMessage("File Uploaded Successfully !", "success");
      setInputValues({ subdirectory: "", search: "" });
      fetchAgents();
      setFiles([]);
    } catch {
      addMessage("Error uploading file", "error");
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
      await postData(url, formData);
      addMessage("File Uploaded Successfully!", "success");
      setKbloader(false);
      setInputValues({ knowledgeBaseName: "", search: "" });
      fetchAgents();
      setFiles([]);
    } catch (error) {
      console.error("Error uploading file", error);
      addMessage("Error uploading file", "error");
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
        addMessage("File deleted successfully !", "success");
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
      addMessage("Download started", "success");
    } catch (err) {
      console.error("Download failed:", err);
      addMessage("Download failed", "error");
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

  const filteredResponseData = Object.keys(responseData || {}).reduce((acc, sectionKey) => {
    const files = responseData?.[sectionKey]?.__files__ || responseData?.[sectionKey];
    if (Array.isArray(files)) {
      const filteredFiles = files.filter((item) => typeof item === "string" && item.toLowerCase().includes((inputValues.search || "").toLowerCase()));
      if (filteredFiles.length > 0) acc[sectionKey] = filteredFiles;
    }
    return acc;
  }, {});

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
                  <h3>UPLOAD FILE</h3>
                  <div className={style["sidebar"]}>
                    <div className={style["toggle"]}>
                      <button className={style["closebtn"]} onClick={safeHideComponent}>
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
                            <p>{file.name}</p>
                          </div>
                          <button className={style["closebtntwo"]} onClick={handleRemoveFile(index)}>
                            &times;
                          </button>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <div className={style["customFileUploadContainer"]}>
                      <section className={style["customDragDrop"]}>
                        <div className={style["customFileUploadBox"]}>
                          <span className={style["customUploadPrompt"]}>Click to upload or drag and drop</span>
                          <div className={style["customSupportedExtensions"]}>
                            Supported: {showKnowledge ? ".pdf,.txt" : ".pdf, .docx, .pptx, .txt, .xlsx, .msg, .json, .img, .db, .jpg, .png, .jpeg, .csv, .pkl, .zip, .tar, .eml"}
                          </div>
                          <input
                            type="file"
                            id="browse"
                            onChange={handleFileChange}
                            accept={showKnowledge ? ".pdf,.txt" : ".pdf, .docx, .pptx, .txt, .xlsx, .msg, .json, .img, .db, .jpg, .png, .jpeg, .csv, .pkl, .zip, .tar, .eml"}
                            multiple={showKnowledge ? true : false}
                            style={{ display: "none" }}
                          />
                          <label htmlFor="browse" style={{ position: "absolute", left: 0, top: 0, width: "100%", height: "100%", cursor: "pointer", zIndex: 2 }}></label>
                        </div>
                      </section>
                    </div>
                  )}

                  {showKnowledge ? (
                    <div className={style["url-section"]}>
                      <label className={style["label-desc"]} htmlFor="url">
                        KNOWLEDGE BASE NAME:
                      </label>
                      <input id="url" type="text" name="knowledgeBaseName" value={inputValues.knowledgeBaseName || ""} onChange={handleKBChange} required />
                    </div>
                  ) : (
                    <>
                      <span>OR</span>
                      <div className={style["url-section"]}>
                        <label className={style["label-desc"]} htmlFor="url">
                          Enter subdirectory name (leave blank for base directory):
                        </label>
                        <input id="url" type="text" name="subdirectory" value={inputValues.subdirectory} onChange={handleInputChange} />
                      </div>
                    </>
                  )}

                  <div className={style["button-class"]}>
                    <button onClick={safeHideComponent} className={style["cancel-button"]}>
                      CANCEL
                    </button>
                    {showKnowledge ? (
                      <button className="iafButton iafButtonPrimary" onClick={toolSubmit} disabled={!isFormValid || files.length === 0 || kbloader}>
                        {/* {kbloader ? "UPLOADING..." : "UPLOAD"} */} Upload
                      </button>
                    ) : (
                      <button className="iafButton iafButtonPrimary" onClick={handleSubmit} disabled={files.length === 0}>
                        UPLOAD
                      </button>
                    )}
                  </div>
                </div>
              </div>

              {!showKnowledge && (
                <>
                  <div className={style["subnav"]}>
                    <div className={style["header"]}>
                      <h1 className={style["subText"]}>Files</h1>
                      <div className={style["underline"]}></div>
                    </div>
                    <div className={style["search-outer-container"]}>
                      <div className={style.searchContainer}>
                        <input type="search" name="search" className={style.searchInput} placeholder="Search Files" value={inputValues.search} onChange={handleInputChange} />
                        <SVGIcons icon="search" fill="#ffffff" width={12} height={12} />
                      </div>
                    </div>
                  </div>

                  <div className={style["documentslistconatiner"]}>
                    {Object.keys(filteredResponseData).map((sectionKey) => (
                      <div key={sectionKey}>
                        <h3>{sectionKey}</h3>
                        <ul className={style["no-bullets"]}>
                          {Array.isArray(filteredResponseData[sectionKey]) &&
                            filteredResponseData[sectionKey].map((item, index) => (
                              <div className={style["listitem"]} key={`${sectionKey}-item-${index}`}>
                                <li>{item}</li>
                                <div className={style["optionscontainer"]}>
                                  {(item.includes(".pdf") || item.includes(".docx")) && (
                                    <button
                                      className={style["ButtonStyle"]}
                                      onClick={(event) => (sectionKey === "__files__" ? handleViewFile(event, item) : handleViewFilewithuser(event, item, sectionKey))}>
                                      <SVGIcons icon="eyeIcon" width={15} height={18} fill="#025601" />
                                    </button>
                                  )}
                                  <button
                                    className={style["ButtonStyle"]}
                                    onClick={(event) => {
                                      event.preventDefault();
                                      if (sectionKey === "__files__") {
                                        handleDownload(event, item);
                                      } else {
                                        handleDownloadwithuser(event, item, sectionKey);
                                      }
                                    }}>
                                    <SVGIcons icon="download" width={15} height={18} fill="#1B0896" />
                                  </button>
                                  <button className={style["ButtonStyle"]} onClick={handledelete(sectionKey, item)}>
                                    <SVGIcons icon="fa-trash" width={12} height={16} fill="#FF0000" />
                                  </button>
                                </div>
                              </div>
                            ))}
                        </ul>
                      </div>
                    ))}
                  </div>
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
