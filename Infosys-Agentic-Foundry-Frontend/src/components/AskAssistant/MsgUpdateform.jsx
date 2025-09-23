import React, { useEffect, useState } from "react";
import style from "../../css_modules/InferenceUploadfile.module.css";
import Loader from "../commonComponents/Loader.jsx";
import { BASE_URL, APIs } from "../../constant";
import useFetch from "../../Hooks/useAxios";
import SVGIcons from "../../Icons/SVGIcons";
import ToastMessage from "../commonComponents/ToastMessages/ToastMessage.jsx";
import ConfirmationPopup from "../commonComponents/ToastMessages/ConfirmationPopup.jsx";
import DocViewerModal from "../DocViewerModal/DocViewerModal";

function MessageUpdateform(props) {
  const { hideComponent, showKnowledge } = props;
  const [showConfirmation, setShowConfirmation] = useState(false);
  const [errorMessage, setErrorMessage] = useState("");
  const [successMessage, setSuccessMessage] = useState("");
  const [loading, setLoading] = useState(false);
  const [confirmdelete, setconfirmdelete] = useState(false);
  const [files, setFiles] = useState([]);
  const [responseData, setresponseData] = useState({});
  const [selectdeleteheader, setselectdeleteheader] = useState("");
  const [selectdeletefile, setselectdeletefile] = useState("");
  const [kbloader, setKbloader] = useState(false);
  const [inputValues, setInputValues] = useState({
    subdirectory: "",
    search: "",
  });
  const { fetchData, getSessionId, postData, deleteData } = useFetch();
  const [showToast, setShowToast] = useState(false);
  const [isFormValid, setIsFormValid] = useState(false);

  useEffect(() => {
    fetchAgents();
  }, []);

  const handleInputChange = (event) => {
    const { name, value } = event.target;
    setInputValues({
      ...inputValues,
      [name]: value,
    });
  };
  const handleKBChange = (event) => {
    const { name, value } = event.target;
    setInputValues({
      ...inputValues,
      [name]: value,
    });
    if (value.trim() !== "") {
      setIsFormValid(true);
    } else {
      setIsFormValid(false);
    }
  };
  let SUPPORTED_EXTENSIONS;
  if (showKnowledge) {
    SUPPORTED_EXTENSIONS = [".pdf", ".txt"];
  } else {
    SUPPORTED_EXTENSIONS = [".pdf", ".docx", ".pptx", ".txt", ".xlsx", ".msg", ".json", ".img", ".db", ".jpg", ".png", ".jpeg", ".csv", ".pkl", ".zip", ".tar", ".eml"];
  }

  const isSupportedFile = (file) => {
    const fileName = file.name.toLowerCase();
    return SUPPORTED_EXTENSIONS.some((ext) => fileName.endsWith(ext));
  };

  const handleFileChange = (event) => {
    const selectedFiles = Array.from(event.target.files);
    const validFiles = selectedFiles.filter(isSupportedFile);
    if (validFiles.length !== selectedFiles.length) {
      setErrorMessage("Unsupported file type");
      setShowToast(true);
    }
    setFiles(validFiles);
  };

  const handleDrop = (event) => {
    event.preventDefault();
    const droppedFiles = Array.from(event.dataTransfer.files);
    const validFiles = droppedFiles.filter(isSupportedFile);
    if (validFiles.length !== droppedFiles.length) {
      setErrorMessage("Some files have unsupported types");
      setShowToast(true);
    }
    setFiles(validFiles);
  };

  const fetchAgents = async (e) => {
    if (!showKnowledge) {
      try {
        const data = await fetchData(APIs.GET_ALLUPLOADFILELIST);
        setresponseData(data?.user_uploads);
      } catch (e) {
        console.error(e);
      }
    }
  };

  const onCancel = () => {
    setShowConfirmation(false);
  };

  const handleSubmit = async (event) => {
    event.preventDefault();
    const formData = new FormData();
    for (let i = 0; i < files.length; i++) {
      formData.append("file", files[i]);
    }
    try {
      const response = await postData(`${APIs.UPLOAD_FILES}?subdirectory=${inputValues.subdirectory}`, formData);
      setSuccessMessage("File Uploaded Successfully !");
      setShowToast(true);
      setInputValues({
        subdirectory: "",
        search: "",
      });
      fetchAgents();
      setFiles([]);
    } catch {
      setErrorMessage("Error uploading file");
    }
  };
  const toolSubmit = async (event) => {
    setKbloader(true);
    event.preventDefault();
    const subdirectory = inputValues.knowledgeBaseName;
    const url = `${APIs.UPLOAD_KB_DOCUMENT}?kb_name=${subdirectory}`;
    const formData = new FormData();
    formData.append("session_id", getSessionId());
    for (let i = 0; i < files.length; i++) {
      formData.append("files", files[i]);
    }
    try {
      const response = await postData(url, formData);
      setSuccessMessage("File Uploaded Successfully!");
      setKbloader(false);
      setShowToast(true);
      setInputValues({
        knowledgeBaseName: "",
        search: "",
      });
      fetchAgents();
      setFiles([]);
    } catch (error) {
      console.error("Error uploading file", error);
      if (error.response) {
        console.error("Response data:", error.response);
      }
      setErrorMessage("Error uploading file");
    }
  };

  const deletefile = async () => {
    // Removed event.preventDefault() because ConfirmationPopup likely calls onConfirm without event
    if (!selectdeletefile) {
      setErrorMessage("No file selected to delete");
      setShowToast(true);
      setShowConfirmation(false);
      return;
    }

    let isFilesPath = selectdeleteheader === "__files__";

    // Encode to avoid issues with spaces/special chars
    const encodedHeader = encodeURIComponent(selectdeleteheader);
    const encodedFile = encodeURIComponent(selectdeletefile);

    const url = isFilesPath ? `${APIs.DELETE_FILE}?file_path=${encodedFile}` : `${APIs.DELETE_FILE}?file_path=${encodedHeader}/${encodedFile}`;

    try {
      setLoading(true);
      const deleteResponse = await deleteData(url, { maxBodyLength: Infinity });
      if (deleteResponse) {
        fetchAgents();
        setSuccessMessage("File deleted successfully !");
        setShowToast(true);
      } else {
        setErrorMessage("Delete failed (no response)");
        setShowToast(true);
      }
    } catch (error) {
      console.error("Delete error:", error);
      setErrorMessage("Error Deleting File");
      setShowToast(true);
    } finally {
      setShowConfirmation(false);
      setLoading(false);
    }
  };

  const handledelete = (heading, value) => (e) => {
    e.preventDefault();
    setselectdeleteheader(heading);
    setselectdeletefile(value);
    setconfirmdelete(true); // (Optional) can remove confirmdelete state altogether
    setShowConfirmation(true);
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

      // Handle both axios-style and fetch-style responses gracefully
      const isAxios = response && response.data !== undefined && response.headers !== undefined;
      const dataBlob = isAxios ? response.data : response; // if fetchData already returns blob
      const headers = isAxios ? response.headers : response?.headers || {};
      const getHeader = typeof headers.get === "function" ? (k) => headers.get(k) : (k) => headers[k.toLowerCase()];

      const contentType = getHeader && getHeader("content-type");
      const disposition = getHeader && getHeader("content-disposition");

      // If JSON error masquerading as blob
      if (contentType && contentType.includes("application/json")) {
        const text = await dataBlob.text?.();
        console.error("Download error payload:", text);
        setErrorMessage("Unable to download file (server returned JSON).");
        setShowToast(true);
        return;
      }

      const fileName = extractFilename(disposition, fallbackName);
      const finalBlob = dataBlob instanceof Blob ? dataBlob : new Blob([dataBlob], { type: contentType || "application/octet-stream" });
      triggerBrowserDownload(finalBlob, fileName);
      setSuccessMessage("Download started");
      setShowToast(true);
    } catch (err) {
      console.error("Download failed:", err);
      setErrorMessage("Download failed");
      setShowToast(true);
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
    setViewUrl(`${BASE_URL}/download?filename=${paramone}`);
    setShowFile(true);
  };
  const handleViewFilewithuser = async (event, paramone, secondparam) => {
    event.preventDefault();
    setViewUrl(`${BASE_URL}/download?filename=${paramone}&sub_dir_name=${secondparam}`);
    setShowFile(true);
  };

  const filteredResponseData = Object.keys(responseData || {}).reduce((acc, sectionKey) => {
    const files = responseData?.[sectionKey]?.__files__ || responseData?.[sectionKey];
    if (Array.isArray(files)) {
      const filteredFiles = files.filter((item) => typeof item === "string" && item.toLowerCase().includes(inputValues.search.toLowerCase() || ""));
      if (filteredFiles.length > 0) {
        acc[sectionKey] = filteredFiles;
      }
    }
    return acc;
  }, {});

  const handleRemoveFile = (index) => (event) => {
    event.preventDefault();
    setFiles((prevFiles) => prevFiles.filter((_, i) => i !== index));
  };

  return (
    <div id="myOverlay" className={style["overlay"]}>
      {(loading || kbloader) && <Loader />}

      <div
        className={showKnowledge ? `${style["form-container"]} ${style["updateformonly"]} ${style["toolOnboardingForm"]}` : `${style["form-container"]} ${style["updateformonly"]}`}
        onDrop={handleDrop}
        onDragOver={(event) => event.preventDefault()}>
        <div className={style["container"]}>
          <div className={style["main"]}>
            <form className={style["file-upload-form"]}>
              <div className={style["form-content"]}>
                <div className={style["uploadfileheader"]}>
                  <h3>UPLOAD FILE</h3>
                  <div className={style["sidebar"]}>
                    <div className={style["toggle"]}>
                      <button className={style["closebtn"]} onClick={hideComponent}>
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
                    <div className={style["file-drop"]}>
                      <section className={style["drag-drop"]}>
                        <div className={style["drag-container"]}>
                          <>
                            <div className={style["upload-info"]}>
                              <div>
                                <p>Drag & Drop to Upload</p>
                              </div>
                            </div>
                            <label>or</label>&nbsp;
                            <input
                              type="file"
                              hidden
                              id="browse"
                              onChange={handleFileChange}
                              accept=".pdf,.docx,.pptx,.txt,.xlsx,.msg,.json,.img,.db,.jpg,.png,.jpeg,.csv,.pkl,.zip,.tar,.eml"
                              multiple={true}
                            />
                            <label htmlFor="browse" className={style["browse-btn"]}>
                              browse
                            </label>
                          </>
                        </div>
                      </section>
                    </div>
                  )}
                  {showKnowledge ? (
                    <>
                      <div className={style["url-section"]}>
                        <label className={style["label-desc"]} htmlFor="url">
                          KNOWLEDGE BASE NAME:
                        </label>
                        <input id="url" type="text" name="knowledgeBaseName" value={inputValues.knowledgeBaseName} onChange={handleKBChange} required></input>
                      </div>
                    </>
                  ) : (
                    <>
                      <span>OR</span>
                      <div className={style["url-section"]}>
                        <label className={style["label-desc"]} htmlFor="url">
                          Enter subdirectory name (leave blank for base directory):
                        </label>
                        <input id="url" type="text" name="subdirectory" value={inputValues.subdirectory} onChange={handleInputChange}></input>
                      </div>
                    </>
                  )}

                  <div className={style["button-class"]}>
                    <button onClick={hideComponent} className={style["cancel-button"]}>
                      CANCEL
                    </button>

                    {showKnowledge ? (
                      <>
                        <button className={style["add-button"]} onClick={toolSubmit} disabled={!isFormValid || files?.length === 0}>
                          {"UPLOAD"}
                        </button>
                      </>
                    ) : (
                      <>
                        <button className={style["add-button"]} onClick={handleSubmit} disabled={files?.length === 0}>
                          {"UPLOAD"}
                        </button>
                      </>
                    )}
                  </div>
                </div>
              </div>
              {showToast && (
                <div className={style["status-section"]}>
                  <ToastMessage successMessage={successMessage} errorMessage={errorMessage} setShowToast={setShowToast} />
                </div>
              )}
              {showConfirmation && (
                <ConfirmationPopup
                  message={`ARE YOU SURE YOU WANT TO DELETE FILE (${selectdeletefile}) ?`}
                  setShowConfirmation={setShowConfirmation}
                  onConfirm={deletefile}
                  onCancel={onCancel}
                />
              )}
              {!showKnowledge ? (
                <>
                  <div className={style["subnav"]}>
                    <div className={style["header"]}>
                      <h1 className={style["subText"]}>{"Files"}</h1>
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
                    {Object?.keys(filteredResponseData)?.map((sectionKey) => (
                      <div key={sectionKey}>
                        <h3>{sectionKey}</h3>
                        <ul className={style["no-bullets"]}>
                          {Array.isArray(filteredResponseData[sectionKey]) ? (
                            filteredResponseData[sectionKey].map((item, index) => (
                              <div className={style["listitem"]} key={`${sectionKey}-item-${index}`}>
                                <li>{item}</li>
                                <div className={style["optionscontainer"]}>
                                  {item.includes(".pdf") || item.includes(".docx") ? (
                                    <button
                                      className={style["ButtonStyle"]}
                                      onClick={(event) => (sectionKey === "__files__" ? handleViewFile(event, item) : handleViewFilewithuser(event, item, sectionKey))}>
                                      <SVGIcons icon="eyeIcon" width={15} height={18} fill={"#025601"} />
                                    </button>
                                  ) : null}
                                  <button
                                    className={style["ButtonStyle"]}
                                    onClick={(event) => (sectionKey === "__files__" ? handleDownload(event, item) : handleDownloadwithuser(event, item, sectionKey))}>
                                    <SVGIcons icon="download" width={15} fill={"#1B0896"} height={18} />
                                  </button>

                                  <button className={style["ButtonStyle"]} onClick={handledelete(sectionKey, item)}>
                                    <SVGIcons icon="fa-trash" width={12} fill={"#FF0000"} height={16} />
                                  </button>
                                </div>
                              </div>
                            ))
                          ) : (
                            <li>{""}</li>
                          )}
                        </ul>
                      </div>
                    ))}
                  </div>
                </>
              ) : (
                <></>
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
