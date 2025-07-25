import React, { useEffect, useState } from "react";
import style from "../../css_modules/InferenceUploadfile.module.css";
import Loader from "../commonComponents/Loader.jsx";
import { BASE_URL, APIs, KNOWLEDGE_BASE_FILE_UPLOAD, KB_LIST, sessionId } from "../../constant";
import useFetch from "../../Hooks/useAxios";
import SVGIcons from "../../Icons/SVGIcons";
import axios from "axios";
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
  const[kbloader,setKbloader]=useState(false)
  const [inputValues, setInputValues] = useState({
    subdirectory: "",
    search: "",
  });
  const { fetchData, getCsrfToken, getSessionId } = useFetch();
  const [showToast, setShowToast] = useState(false);
  const [isFormValid, setIsFormValid] = useState(false);

  useEffect(() => {
    fetchAgents();
  }, []);

  const handleEmpty = (event) => {
    event.preventDefault();
    setFiles([]);
  };

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
    if (value.trim() !== '') {
    setIsFormValid(true);
  } else {
    setIsFormValid(false);
  }
  };
  let SUPPORTED_EXTENSIONS;
if(showKnowledge){
   SUPPORTED_EXTENSIONS = [".pdf",".txt"];

}else{
     SUPPORTED_EXTENSIONS = [".pdf", ".docx", ".pptx", ".txt", ".xlsx", ".msg", ".json", ".img",".db", ".jpg", ".png", ".jpeg", ".csv", ".pkl", ".zip", ".tar"];

}


  const isSupportedFile = (file) => {
    const fileName = file.name.toLowerCase();
    return SUPPORTED_EXTENSIONS.some((ext) => fileName.endsWith(ext));
  };

  const handleFileChange = (event) => {
    const selectedFiles = event.target.files;
    if (selectedFiles && selectedFiles.length > 0) {
      const file = selectedFiles[0];
      if (!isSupportedFile(file)) {
        setErrorMessage("Unsupported file type");
        setShowToast(true);
        setFiles([]);
        return;
      }
      setFiles([file]);
    }
  };

  const handleDrop = (event) => {
    event.preventDefault();
    const droppedFiles = event.dataTransfer.files;
    if (droppedFiles.length > 0) {
      const file = droppedFiles[0];
      if (!isSupportedFile(file)) {
        setErrorMessage("Unsupported file type");
        setShowToast(true);
        setFiles([]);
        return;
      }
      setFiles([file]);
    }
  };

  const fetchAgents = async (e) => {
    if(!showKnowledge){
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
      const response = await axios.post(
        `${BASE_URL}/files/user-uploads/upload-file/?subdirectory=${inputValues.subdirectory}`,
        formData,
        {
          headers: {
            "Content-Type": "multipart/form-data",
            "csrf-token": getCsrfToken(),
            "session-id": getSessionId(), // added for CSRF token implementation
          },
        }
      );
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
    setKbloader(true)
    event.preventDefault();
    const subdirectory = inputValues.knowledgeBaseName;
    const url =`${BASE_URL}${APIs.KNOWLEDGE_BASE_FILE_UPLOAD}?kb_name=${subdirectory}`
    const formData = new FormData();
    formData.append("session_id", getSessionId());
    for (let i = 0; i < files.length; i++) {
      formData.append("files", files[i]);
    }
    try {
      const response = await axios.post(url, formData, {
        headers: {
          "Content-Type": "multipart/form-data",
          "accept": "application/json",
        },
      });
      setSuccessMessage("File Uploaded Successfully!");
      setKbloader(false)
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
        console.error("Response data:", error.response.data);
      }
      setErrorMessage("Error uploading file");
    }
  };



  const deletefile = async (event) => {
    event.preventDefault();

    let isFilesPath = false;

    if (selectdeleteheader === "__files__") {
      isFilesPath = true;
    }

    const url = isFilesPath
      ? `${BASE_URL}${APIs.FILE_UPLOAD}${selectdeletefile}`
      : `${BASE_URL}${APIs.FILE_UPLOAD}${selectdeleteheader}/${selectdeletefile}`;

    let config = {
      method: "delete",
      maxBodyLength: Infinity,
      url: url,
      headers: {
        "csrf-token": getCsrfToken(),
        "session-id": getSessionId(), // added for CSRF token implementation
      }
    };

    await axios
      .request(config)
      .then((response) => {
        fetchAgents();
        setShowConfirmation(false);
        setShowToast(true);
        setShowConfirmation(false);
        setSuccessMessage("File deleted successfully !");
      })
      .catch((error) => {
        setShowToast(true);
        setShowConfirmation(false);
        setErrorMessage("Error Deleting File");
      });
  };

  const handledelete = (heading, value, event) => (event) => {
    event.preventDefault();
    setselectdeleteheader(heading);
    setselectdeletefile(value);
    setconfirmdelete(true);
    setShowConfirmation(true);
  };

  const handleDownload = async (event, paramone) => {
    event.preventDefault();
    try {
      const response = await axios.get(`${BASE_URL}/download?filename=${paramone}`, {
        responseType: "blob", // Ensure the response is a Blob
        headers: {
          "csrf-token": getCsrfToken(),
          "session-id": getSessionId(), // added for CSRF token implementation
        },
      });

      // Check if the response is a file
      const contentType = response.headers["content-type"];
      if (contentType.includes("application/json")) {
        // Handle JSON response
        const jsonResponse = await response.data.text();
      } else {
        // Handle file download
        const url = window.URL.createObjectURL(new Blob([response.data]));
        const link = document.createElement("a");
        link.href = url;
        link.setAttribute("download", `${paramone}`); // Specify the file name and extension
        document.body.appendChild(link);
        link.click();
        link.parentNode.removeChild(link);
      }
    } catch (error) { }
  };
  const [viewUrl,setViewUrl]=useState("")
  const [showFile, setShowFile]=useState(false)
  const handleViewFile = async (event, paramone) => {
    event.preventDefault();
    setViewUrl(`${BASE_URL}/download?filename=${paramone}`)
    setShowFile(true)
  };
  const handleViewFilewithuser = async (event, paramone, secondparam) => {
    event.preventDefault();
    setViewUrl(`${BASE_URL}/download?filename=${paramone}&sub_dir_name=${secondparam}`)
    setShowFile(true)
  }

  const handleDownloadwithuser = async (event, paramone, secondparam) => {
    event.preventDefault();
    try {
      const response = await axios.get(
        `${BASE_URL}/download?filename=${paramone}&sub_dir_name=${secondparam}`,
        {
          responseType: "blob", // Ensure the response is a Blob
          headers: {
            "csrf-token": getCsrfToken(),
            "session-id": getSessionId(), // added for CSRF token implementation
          }
        }
      );
      // Check if the response is a file
      const contentType = response.headers["content-type"];
      if (contentType.includes("application/json")) {
        // Handle JSON response
        const jsonResponse = await response.data.text();
      } else {
        // Handle file download
        const url = window.URL.createObjectURL(new Blob([response.data]));
        const link = document.createElement("a");
        link.href = url;
        link.setAttribute("download", `${paramone}`); // Specify the file name and extension
        document.body.appendChild(link);
        link.click();
        link.parentNode.removeChild(link);
      }
    } catch {
      console.error("Error downloading file:");
    }
  };

  const filteredResponseData = Object.keys(responseData || {}).reduce(
    (acc, sectionKey) => {
      const files =
        responseData?.[sectionKey]?.__files__ || responseData?.[sectionKey];
      if (Array.isArray(files)) {
        const filteredFiles = files.filter(
          (item) =>
            typeof item === "string" &&
            item.toLowerCase().includes(inputValues.search.toLowerCase() || "")
        );
        if (filteredFiles.length > 0) {
          acc[sectionKey] = filteredFiles;
        }
      }
      return acc;
    },
    {}
  );

  return (
    <div id="myOverlay" className={style["overlay"]}>
      {(loading || kbloader) && <Loader />}

      <div
        className={
          showKnowledge
            ? `${style["form-container"]} ${style["updateformonly"]} ${style["toolOnboardingForm"]}`
            : `${style["form-container"]} ${style["updateformonly"]}`
        }
        onDrop={handleDrop}
        onDragOver={(event) => event.preventDefault()}
      >
        <div className={style["container"]}>
          <div className={style["main"]}>
            <form className={style["file-upload-form"]}>
              <div className={style["form-content"]}>
                <div className={style["uploadfileheader"]}>
                  <h3>UPLOAD FILE</h3>
                  <div className={style["sidebar"]}>
                    <div className={style["toggle"]}>
                      <button
                        className={style["closebtn"]}
                        onClick={hideComponent}
                      >
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
                          <button
                            className={style["closebtntwo"]}
                            onClick={handleEmpty}
                          >
                            &times;
                          </button>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <div className={style["file-drop"]}>
                      <section className={style["drag-drop"]}>
                        <div
                          className={style["drag-container"]}
                        >
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
                              accept=".pdf,.docx,.pptx,.txt,.xlsx,.msg,.json,.img,.db,.jpg,.png,.jpeg,.csv,.pkl,.zip,.tar"
                              multiple={false}
                            />
                            <label
                              htmlFor="browse"
                              className={style["browse-btn"]}
                            >
                              browse
                            </label>
                          </>
                        </div>
                      </section>
                    </div>
                  )}
                  {showKnowledge ? <>
                    <div className={style["url-section"]}>
                      <label className={style["label-desc"]} htmlFor="url">
                        KNOWLEDGE BASE NAME:
                      </label>
                      <input
                        id="url"
                        type="text"
                        name="knowledgeBaseName"
                        value={inputValues.knowledgeBaseName}
                        onChange={handleKBChange}
                        required
                      ></input>
                    </div>
                  </> : <>
                    <span>OR</span>
                    <div className={style["url-section"]}>
                      <label className={style["label-desc"]} htmlFor="url">
                        Enter subdirectory name (leave blank for base directory):
                      </label>
                      <input
                        id="url"
                        type="text"
                        name="subdirectory"
                        value={inputValues.subdirectory}
                        onChange={handleInputChange}
                      ></input>
                    </div>
                  </>}


                  <div className={style["button-class"]}>
                    <button
                      onClick={hideComponent}
                      className={style["cancel-button"]}
                    >
                      CANCEL
                    </button>

                    {showKnowledge ? <>
                      <button
                        className={style["add-button"]}
                        onClick={toolSubmit}
                        disabled={!isFormValid|| files?.length === 0}
                      >
                        {"UPLOAD"}
                      </button>
                    </> : <>
                      <button
                        className={style["add-button"]}
                        onClick={handleSubmit}
                        disabled={files?.length === 0}
                      >
                        {"UPLOAD"}
                      </button>
                    </>
                    }
                  </div>
                </div>
              </div>
              {showToast && (
                <div className={style["status-section"]}>
                  <ToastMessage
                    successMessage={successMessage}
                    errorMessage={errorMessage}
                    setShowToast={setShowToast}
                  />
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
              {!showKnowledge ? <>
                <div className={style["subnav"]}>
                  <div className={style["header"]}>
                    <h1 className={style["subText"]}>{"Files"}</h1>
                    <div className={style["underline"]}></div>
                  </div>
                  <div className={style["search-outer-container"]}>
                    <div className={style.searchContainer}>
                      <input
                        type="search"
                        name="search"
                        className={style.searchInput}
                        placeholder="Search Files"
                        value={inputValues.search}
                        onChange={handleInputChange}
                      />
                      <SVGIcons
                        icon="search"
                        fill="#ffffff"
                        width={12}
                        height={12}
                      />
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
                                {item.includes(".pdf") || item.includes(".docx") ? (<button
                                  className={style["ButtonStyle"]}
                                  onClick={(event) =>
                                    sectionKey === "__files__"
                                      ? handleViewFile(event, item)
                                      : handleViewFilewithuser(
                                        event,
                                        item,
                                        sectionKey
                                      )
                                  }
                                >
                                  <SVGIcons
                                    icon="eyeIcon"
                                    width={15}
                                    height={18}
                                    fill={"#025601"}
                                  />
                                </button>) : null}
                                <button
                                  className={style["ButtonStyle"]}
                                  onClick={(event) =>
                                    sectionKey === "__files__"
                                      ? handleDownload(event, item)
                                      : handleDownloadwithuser(
                                        event,
                                        item,
                                        sectionKey
                                      )
                                  }
                                >
                                  <SVGIcons
                                    icon="download"
                                    width={15}
                                    fill={"#1B0896"}
                                    height={18}
                                  />
                                </button>

                                <button
                                  className={style["ButtonStyle"]}
                                  onClick={handledelete(sectionKey, item)}
                                >
                                  <SVGIcons
                                    icon="fa-trash"
                                    width={12}
                                    fill={"#FF0000"}
                                    height={16}
                                  />
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
              </> : <></>}
            </form>
          </div>
        </div>
      </div>
      {showFile && <DocViewerModal url={viewUrl} onClose={() => { setShowFile(false) }} />}
    </div>
  );
}

export default MessageUpdateform;
