import { useEffect, useState, useRef, useCallback } from "react";
import style from "../../css_modules/ToolOnboarding.module.css";
import { useToolsAgentsService } from "../../services/toolService.js";
import Loader from "../commonComponents/Loader.jsx";
import DropDown from "../commonComponents/DropDowns/DropDown";
import { APIs, BASE_URL } from "../../constant";
import { useMessage } from "../../Hooks/MessageContext";
import Tag from "../Tag/Tag";
import useFetch from "../../Hooks/useAxios.js";
import Cookies from "js-cookie";
import DeleteModal from "../commonComponents/DeleteModal.jsx";
import { useAuth } from "../../context/AuthContext";
import InfoTag from "../commonComponents/InfoTag.jsx";
import MessageUpdateform from "../AskAssistant/MsgUpdateform.jsx";
import SVGIcons from "../../Icons/SVGIcons.js";
import ZoomPopup from "../commonComponents/ZoomPopup.jsx";
import { WarningModal } from "../AvailableTools/WarningModal.jsx";
import groundTruthStyles from "../GroundTruth/GroundTruth.module.css";
import AddServer from "../AgentOnboard/AddServer";
import ExecutorPanel from "../commonComponents/ExecutorPanel";
import CodeEditor from "../commonComponents/CodeEditor.jsx";

function ToolOnBoarding(props) {
  const loggedInUserEmail = Cookies.get("email");
  const userName = Cookies.get("userName");
  const role = Cookies.get("role");
  const { updateTools, addTool, recycleTools } = useToolsAgentsService();

  const formObject = {
    description: "",
    code: "",
    model: "",
    createdBy: userName === "Guest" ? userName : loggedInUserEmail,
    userEmail: "",
  };
  const { isAddTool, setShowForm, editTool, tags, refreshData = true, fetchPaginatedTools, hideServerTab = false, contextType = "tools" } = props;

  const [formData, setFormData] = useState({});
  const [showKnowledge, setShowKnowledge] = useState(false);
  const [loading, setLoading] = useState(false);
  const [errorModalVisible, setErrorModalVisible] = useState(false);
  const [errorMessages, setErrorMessages] = useState([]);

  const [files, setFiles] = useState([]);
  const [codeFile, setCodeFile] = useState(null);
  const [isDraggingCode, setIsDraggingCode] = useState(false);
  const [isDraggingCapabilities, setIsDraggingCapabilities] = useState(false);

  const { addMessage, setShowPopup } = useMessage();

  const [models, setModels] = useState([]);
  const [updateModal, setUpdateModal] = useState(false);
  const [responseData, setresponseData] = useState({});

  const [hideCloseIcon, setHideCloseIcon] = useState(false);

  const [showZoomPopup, setShowZoomPopup] = useState(false);
  const [popupTitle, setPopupTitle] = useState("");
  const [popupContent, setPopupContent] = useState("");

  const [copiedStates, setCopiedStates] = useState({});
  const [forceAdd, setForceAdd] = useState(false);
  // Theme for the whole form (if needed elsewhere)
  const [isDarkTheme, setIsDarkTheme] = useState(true);

  const activeTab = contextType === "servers" ? "addServer" : "toolOnboarding"; // 'toolOnboarding' | 'addServer'

  const { fetchData, deleteData, postData } = useFetch();

  // ExecutorPanel now manages its own loader, no need for executingCode state

  // Executor panel (autonomous) state triggers
  const [showExecutorPanel, setShowExecutorPanel] = useState(false);
  const [executeTrigger, setExecuteTrigger] = useState(0); // increment to trigger fresh run

  // No longer needed: validation scroll handled inside ExecutorPanel

  const fetchAgents = async (e) => {
    try {
      const data = await fetchData(APIs.GET_ALLUPLOADFILELIST);
      setresponseData(data?.user_uploads || {});
    } catch {
      console.error("Tool onboarding failed fetching agent");
      setresponseData({});
    }
  };

  useEffect(() => {
    if (!loading) {
      setShowPopup(true);
    } else {
      setShowPopup(false);
    }
  }, [loading]);

  useEffect(() => {
    setFiles(files);
  }, [files, setFiles]);

  useEffect(() => {
    if (!isAddTool) {
      setFormData((values) => ({
        ...values,
        id: editTool.tool_id,
        description: editTool.tool_description,
        code: editTool.code_snippet,
        model: editTool.model_name,
        userEmail: loggedInUserEmail,
        name: editTool.tool_name,
        createdBy: userName === "Guest" ? null : editTool.created_by,
      }));
    } else if (props?.recycle) {
      setFormData((values) => ({
        ...values,
        item_id: editTool.tool_id,
        description: editTool.tool_description,
        code: editTool.code_snippet,
        model: editTool.model_name,
        userEmail: loggedInUserEmail,
        name: editTool.tool_name,
        createdBy: userName === "Guest" ? null : editTool.created_by,
      }));
    } else {
      setFormData(formObject);
    }
  }, []);

  const handleChange = (event) => {
    const { name, value } = event.target;
    setFormData((values) => ({ ...values, [name]: value }));
  };

  const validateFile = (file, type) => {
    if (!file) return false;
    if (type === "code") {
      const validExtensions = [".py", ".txt"];
      const fileName = file.name.toLowerCase();
      const hasValidExtension = validExtensions.some((ext) => fileName.endsWith(ext));
      if (!hasValidExtension) {
        addMessage("Please upload a valid Python (.py) or text (.txt) file", "error");
        setShowPopup(true);
        return false;
      }
    }
    if (type === "json") {
      const validExtensions = [".json"];
      const fileName = file.name.toLowerCase();
      return validExtensions.some((ext) => fileName.endsWith(ext));
    }
    return true;
  };

  // Drag and drop handlers
  const handleDragEnter = (type) => (e) => {
    e.preventDefault();
    e.stopPropagation();
    if (type === "code") setIsDraggingCode(true);
    if (type === "capabilities") setIsDraggingCapabilities(true);
  };

  const handleDragLeave = (type) => (e) => {
    e.preventDefault();
    e.stopPropagation();
    if (type === "code") setIsDraggingCode(false);
    if (type === "capabilities") setIsDraggingCapabilities(false);
  };

  const handleDragOver = (type) => (e) => {
    e.preventDefault();
    e.stopPropagation();
    if (type === "code" && !isDraggingCode) setIsDraggingCode(true);
    if (type === "capabilities" && !isDraggingCapabilities) setIsDraggingCapabilities(true);
  };

  const handleRemoveFile = (type) => {
    if (type === "code") {
      setCodeFile(null);
    }
    const fileInput = document.getElementById(type + "File");
    if (fileInput) fileInput.value = "";
  };

  const commonInputStyle = {
    width: "100%",
    maxWidth: "700px",
    marginLeft: 0,
    marginRight: 0,
    boxSizing: "border-box",
    display: "block",
  };

  const deleteTool = async () => {
    let response;
    if (props?.recycle) {
      const isAdmin = role && role?.toUpperCase() === "ADMIN";
      const toolsdata = {
        model_name: formData.model,
        is_admin: isAdmin,
        tool_description: formData.description,
        code_snippet: formData.code,
        created_by: editTool.created_by, // Use creator email from editTool
        user_email_id: formData.userEmail,
        updated_tag_id_list: initialUpdateTags.filter((e) => e.selected).map((e) => e.tagId),
      };
      let url = "";
      if (props?.selectedType === "tools") {
        url = `${APIs.DELETE_TOOLS_PERMANENTLY}${editTool?.tool_id}?user_email_id=${encodeURIComponent(Cookies?.get("email"))}`;
      }

      response = await deleteData(url);
      if (response?.is_delete) {
        props?.setRestoreData(response);
        addMessage(response?.status_message, "success");
        setLoading(false);
        setShowForm(false);
      } else {
        addMessage(response?.status_message, "error");
        setLoading(false);
        //  setShowForm(false)
      }
    }
  };

  const handleSubmit = async (event, force = false) => {
    if (event) {
      event.preventDefault();
      event.stopPropagation();
    }
    if (userName === "Guest") {
      setUpdateModal(true);
      return;
    }

    setLoading(true);
    let response;
    if (isAddTool) {
      const formDataToSend = new FormData();

      formDataToSend.append("tool_description", formData.description);
      formDataToSend.append("model_name", formData.model);
      formDataToSend.append("created_by", userName === "Guest" ? formData.createdBy : loggedInUserEmail);
      formDataToSend.append(
        "tag_ids",
        initialTags
          .filter((e) => e.selected)
          .map((e) => e.tagId)
          .join(",")
      );

      // If file is uploaded, use file for tool_file and empty code_snippet
      // If no file, use textarea content for code_snippet and empty tool_file
      if (codeFile) {
        formDataToSend.append("code_snippet", "");
        formDataToSend.append("tool_file", codeFile);
      } else {
        formDataToSend.append("code_snippet", formData.code);
        formDataToSend.append("tool_file", "");
      }

      response = await addTool(formDataToSend, force);
    } else if (!isAddTool && !props?.recycle) {
      const isAdmin = role && role?.toUpperCase() === "ADMIN";
      const toolsdata = {
        model_name: formData.model,
        is_admin: isAdmin,
        tool_description: formData.description,
        code_snippet: formData.code,
        created_by: editTool.created_by, // Use creator email from editTool
        user_email_id: formData.userEmail,
        updated_tag_id_list: initialUpdateTags.filter((e) => e.selected).map((e) => e.tagId),
      };
      response = await updateTools(toolsdata, editTool.tool_id, force);
    } else {
      if (props?.recycle) {
        const isAdmin = role && role?.toUpperCase() === "ADMIN";
        const toolsdata = {
          model_name: formData.model,
          is_admin: isAdmin,
          tool_description: formData.description,
          code_snippet: formData.code,
          created_by: editTool.created_by, // Use creator email from editTool
          user_email_id: formData.userEmail,
          updated_tag_id_list: initialUpdateTags.filter((e) => e.selected).map((e) => e.tagId),
        };

        let url = "";
        if (props?.selectedType === "tools") {
          url = `${APIs.RESTORE_TOOLS}${editTool?.tool_id}?user_email_id=${encodeURIComponent(Cookies?.get("email"))}`;
        }

        response = await postData(url); // Check if tools data is needed here **
        if (response?.is_restored) {
          props?.setRestoreData(response);
          addMessage(response?.status_message, "success");
          setLoading(false);
          setShowForm(false);
        } else {
          addMessage(response?.status_message, "error");
          setLoading(false);
          //  setShowForm(false)
        }
      }
    }
    if (response?.is_created || response?.is_update) {
      if (isAddTool) {
        addMessage("Tool has been added successfully!", "success");
      } else {
        addMessage("Tool has been updated successfully!", "success");
      }
      setLoading(false);
      if (refreshData && typeof fetchPaginatedTools === "function") {
        await props.fetchPaginatedTools(1);
      }
      // Reset form state including file upload
      setCodeFile(null);
      setFormData(formObject);
      setShowForm(false);
      setErrorModalVisible(false);
      setForceAdd(false);
    } else if (!props?.recycle) {
      setLoading(false);
      if (response?.message?.includes("Verification failed:") && response?.error_on_screen === false) {
        const match = response.message.match(/Verification failed:\s*\[(.*)\]/s);
        if (match && match[1]) {
          const raw = match[1];
          let warnings = [];
          try {
            warnings = JSON.parse(`[${raw}]`);
          } catch {
            warnings = raw.split(/(?<!\\)',\s*|(?<!\\)"\,\s*/).map((s) => s.replace(/^['"]|['"]$/g, ""));
          }
          setErrorMessages(warnings);
          setErrorModalVisible(true);
          setForceAdd(true);
          return;
        }
      }
      if (response?.status && response?.response?.status !== 200) {
        addMessage(response?.response?.data?.detail, "error");
      } else {
        addMessage(response?.message ? response?.message : "No response received. Please try again.", "error");
      }
    } else {
      if (props?.recycle) {
        if (response?.is_restored) {
          props?.setRestoreData(response);
          addMessage(response?.status_message, "success");
          setLoading(false);
          setShowForm(false);
        } else {
          addMessage(response?.status_message, "error");
          setLoading(false);
          //  setShowForm(false)
        }
      }
    }
  };
  const [initialTags, setInitialTags] = useState([]);
  useEffect(() => {
    if (tags) {
      const newTags = tags.map((tag) => ({
        tag: tag.tag_name,
        tagId: tag.tag_id,
        selected: false,
      }));
      setInitialTags(newTags);
    }
  }, [tags]);

  const [initialUpdateTags, setInitialUpdateTags] = useState([]);
  useEffect(() => {
    if (editTool.tags && initialTags.length > 0) {
      const newTags = initialTags.map((tag) => {
        if (editTool.tags.some((editTag) => editTag.tag_id === tag.tagId)) {
          return { ...tag, selected: true };
        } else {
          return { ...tag, selected: false };
        }
      });

      setInitialUpdateTags(newTags);
    }
  }, [editTool.tags, initialTags]);

  const toggleTagSelection = (index) => {
    if (isAddTool) {
      const newTags = [...initialTags];
      newTags[index].selected = !newTags[index].selected;
      setInitialTags(newTags);
    } else {
      const newTags = [...initialUpdateTags];
      newTags[index].selected = !newTags[index].selected;
      setInitialUpdateTags(newTags);
    }
  };

  const fetchModels = async () => {
    try {
      const data = await fetchData(APIs.GET_MODELS);
      if (data?.models && Array.isArray(data.models)) {
        const formattedModels = data.models.map((model) => ({
          label: model,
          value: model,
        }));
        setModels(formattedModels);
      } else {
        setModels([]);
      }
    } catch {
      console.error("Fetching failed");
      setModels([]);
    }
  };

  const hasLoadedModelsOnce = useRef(false);
  const hasLoadedAgentsOnce = useRef(false);

  useEffect(() => {
    if (!hasLoadedModelsOnce.current) {
      hasLoadedModelsOnce.current = true;
      fetchModels();
    }
    if (!hasLoadedAgentsOnce.current) {
      hasLoadedAgentsOnce.current = true;
      fetchAgents();
    }
  }, []);

  const { logout } = useAuth();

  const handleLoginButton = (e) => {
    e.preventDefault();
    logout("/login");
  };

  const handleZoomClick = useCallback((title, content) => {
    setPopupTitle(title);
    setPopupContent(content || "");
    setShowZoomPopup(true);
  }, []);

  const handleZoomSave = (updatedContent) => {
    if (popupTitle === "Code Snippet") {
      if (!codeFile) {
        setFormData((prev) => ({
          ...prev,
          code: updatedContent,
        }));
      }
    } else if (popupTitle === "Description") {
      setFormData((prev) => ({
        ...prev,
        description: updatedContent,
      }));
    }
  };

  // Fire executor panel run
  const runCode = (userCode) => {
    if (!userCode) {
      addMessage("Please provide valid code to run", "error");
      return;
    }

    if (!showExecutorPanel) {
      // First time: just open panel; ExecutorPanel auto executes on mount
      setShowExecutorPanel(true);
    } else {
      // Panel already open: bump trigger to re-run
      setExecuteTrigger((c) => c + 1);
    }
  };

  const handleCopy = (key, text) => {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      // Use Clipboard API if supported
      navigator.clipboard
        .writeText(text)
        .then(() => {
          setCopiedStates((prev) => ({ ...prev, [key]: true })); // Set copied state
          setTimeout(() => {
            setCopiedStates((prev) => ({ ...prev, [key]: false })); // Reset after 2 seconds
          }, 2000);
        })
        .catch(() => {
          console.error("Failed to copy text, tool on board");
        });
    } else {
      // Fallback for unsupported browsers
      const textarea = document.createElement("textarea");
      textarea.value = text;
      textarea.style.position = "fixed"; // Prevent scrolling to the bottom of the page
      textarea.style.opacity = "0"; // Hide the textarea
      document.body.appendChild(textarea);
      textarea.focus();
      textarea.select();

      try {
        document.execCommand("copy");
        setCopiedStates((prev) => ({ ...prev, [key]: true })); // Set copied state
        setTimeout(() => {
          setCopiedStates((prev) => ({ ...prev, [key]: false })); // Reset after 2 seconds
        }, 2000);
      } catch {
        console.error("Fallback: Failed to copy text, on boarding tools");
      } finally {
        document.body.removeChild(textarea); // Clean up
      }
    }
  };

  return (
    <>
      <DeleteModal show={updateModal} onClose={() => setUpdateModal(false)}>
        <p>You are not authorized to update a tool. Please login with registered email.</p>
        <div className={style.buttonContainer}>
          <button onClick={(e) => handleLoginButton(e)} className={style.loginBtn}>
            Login
          </button>
          <button onClick={() => setUpdateModal(false)} className={style.cancelBtn}>
            Cancel
          </button>
        </div>
      </DeleteModal>{" "}
      <div
        className={style["modalOverlay"]}
        onClick={() => {
          setCodeFile(null);
          setFormData(formObject);
          setShowForm(false);
        }}>
        {loading && (
          <div onClick={(e) => e.stopPropagation()}>
            <Loader />
          </div>
        )}
        <div
          className={style["modal"]}
          onClick={(e) => e.stopPropagation()}
          style={{
            width: showExecutorPanel ? "calc(100vw - 70px)" : showKnowledge ? "900px" : "790px",
            maxWidth: "calc(100% - 40px)",
            paddingTop: "6px",
            transition: "width 0.3s ease-in-out",
          }}>
          <div
            className={style["container"]}
            style={{ flex: 1, display: "flex", flexDirection: "column", justifyContent: "flex-start", height: "100%", overflowY: "auto", paddingTop: 0, paddingBottom: 0 }}>
            {" "}
            <div
              className={style["main"]}
              style={{
                flex: 1,
                display: "flex",
                flexDirection: "column",
                justifyContent: "flex-start",
                height: "100%",
                overflowY: "auto",
                paddingTop: 0,
                paddingBottom: 0,
                paddingRight: "18px",
              }}>
              {" "}
              <div className={style["nav"]}>
                {" "}
                <div className={style["header"]} style={{ display: "flex", alignItems: "center", justifyContent: "space-between", width: "100%" }}>
                  <div>
                    {(isAddTool ? activeTab === "toolOnboarding" : true) && (
                      <h2 style={{ fontSize: "22px", fontWeight: 700, color: "#0f172a", margin: 0 }}>{props?.recycle ? "RESTORE TOOL" : isAddTool ? "ADD TOOL" : "UPDATE TOOL"}</h2>
                    )}
                    {isAddTool && activeTab === "addServer" && !hideServerTab && <h2 style={{ fontSize: "22px", fontWeight: 700, color: "#0f172a", margin: 0 }}>ADD SERVER</h2>}
                  </div>
                  <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
                    {!props?.recycle && activeTab === "toolOnboarding" && (
                      <label className={style["toggle-switch"]}>
                        <input
                          checked={showKnowledge}
                          onChange={(e) => {
                            setShowKnowledge(e.target.checked);
                            setHideCloseIcon(!hideCloseIcon);
                          }}
                          type="checkbox"
                        />
                        <span className={style["slider"]}></span>
                      </label>
                    )}
                    {!props?.recycle && activeTab === "toolOnboarding" && (
                      <div className={showKnowledge ? style["knowledge"] + " " + style["active"] : style["knowledge"]}>KNOWLEDGE</div>
                    )}
                    {/* Close button always visible */}
                    <button
                      className={style["closeBtn"]}
                      onClick={() => {
                        setCodeFile(null);
                        setFormData(formObject);
                        setShowForm(false);
                      }}>
                      ×
                    </button>
                  </div>
                </div>{" "}
              </div>{" "}
              {/* Only show ToolOnboarding form if editing, else allow tab switch */}{" "}
              {(isAddTool ? activeTab === "toolOnboarding" : true) && (
                <div className={`${style["main-content-wrapper"]} ${showExecutorPanel ? style["split-layout"] : ""}`}>
                  <form onSubmit={handleSubmit} className={style["form-section"]}>
                    <div className={style["form-content"]}>
                      <div className={style["form-fields"]}>
                        <div className={style["description-container"]}>
                          <label className={style["label-desc"]}>
                            DESCRIPTION
                            <InfoTag message="Enter a brief description." />
                          </label>
                          <div className={style.textAreaContainer}>
                            <input
                              id="description"
                              name="description"
                              className={style["input-class"] + " " + style.agentTextArea}
                              type="text"
                              onChange={handleChange}
                              value={formData.description}
                              required
                              readOnly={!!props?.recycle}
                              style={props?.recycle ? { background: "#f8f9fa", color: "#6c757d", cursor: "not-allowed" } : {}}
                            />
                            <button type="button" className={style.copyIcon} onClick={() => handleCopy("desc", formData.description)} title="Copy">
                              <SVGIcons icon="fa-regular fa-copy" width={16} height={16} fill="#000000" />
                            </button>
                            <div className={style.iconGroup}>
                              <button type="button" className={style.expandIcon} onClick={() => handleZoomClick("Description", formData.description)} title="Expand">
                                <SVGIcons icon="fa-solid fa-up-right-and-down-left-from-center" width={16} height={16} fill="#000000" />
                              </button>
                            </div>
                            <span className={`${style.copiedText} ${copiedStates["desc"] ? style.visible : style.hidden}`}>Text Copied!</span>
                          </div>
                        </div>

                        <div className={style["snippet-container"]}>
                          <label className={style["label-desc"]}>
                            CODE SNIPPET
                            <InfoTag message="Enter the code snippet." />
                          </label>
                          <div className={style.codeEditorContainer}>
                            <CodeEditor
                              value={formData.code || ""}
                              onChange={props?.recycle || codeFile ? undefined : (value) => setFormData((prev) => ({ ...prev, code: value }))}
                              readOnly={!!props?.recycle || !!codeFile}
                              isDarkTheme={isDarkTheme}
                            />
                            <button type="button" className={style.copyIcon} onClick={() => handleCopy("code-snippet", formData.code)} title="Copy">
                              <SVGIcons icon="fa-regular fa-copy" width={16} height={16} fill="#ffffff" />
                            </button>
                            <button type="button" className={style.playIcon} onClick={() => runCode(formData.code)} title="Run Code">
                              <SVGIcons icon="play" width={16} height={16} fill={isDarkTheme ? "#ffffff" : "#000000"} />
                            </button>
                            <div className={style.iconGroup}>
                              <button type="button" className={style.expandIcon} onClick={() => handleZoomClick("Code Snippet", formData.code)} title="Expand">
                                <SVGIcons icon="fa-solid fa-up-right-and-down-left-from-center" width={16} height={16} fill="#ffffff" />
                              </button>
                            </div>
                            <span className={`${style.copiedText} ${copiedStates["code-snippet"] ? style.visible : style.hidden}`}>Text Copied!</span>
                          </div>
                        </div>

                        {/* File upload UI - Only show for Add Tool mode and not in recycle mode */}
                        {isAddTool && !props?.recycle && (
                          <div className={style["form-block"]} style={{ width: "100%" }}>
                            <label htmlFor="codeFile" className={style["label-desc"]}>
                              Python File
                              <InfoTag message="Upload a Python file instead of typing code snippet." />
                              <span style={{ fontWeight: 400, fontSize: "13px", marginLeft: "8px", color: "#888" }}>(Supported: .py)</span>
                            </label>
                            <input
                              type="file"
                              id="codeFile"
                              name="codeFile"
                              onChange={async (e) => {
                                const file = e.target.files?.[0];
                                if (validateFile(file, "code")) {
                                  setCodeFile(file);
                                  // File is stored but doesn't auto-populate the textarea
                                  // The file content will be read during form submission
                                }
                              }}
                              className={style["input-class"]}
                              accept=".py"
                              style={{ display: "none" }}
                            />
                            {!codeFile ? (
                              <div
                                className={
                                  groundTruthStyles.fileUploadContainer +
                                  (isDraggingCode ? " " + groundTruthStyles.dragging : "") +
                                  (loading ? " " + groundTruthStyles.disabled : "")
                                }
                                onDragEnter={handleDragEnter("code")}
                                onDragLeave={handleDragLeave("code")}
                                onDragOver={handleDragOver("code")}
                                onDrop={async (e) => {
                                  e.preventDefault();
                                  e.stopPropagation();
                                  setIsDraggingCode(false);
                                  if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
                                    const file = e.dataTransfer.files[0];
                                    if (validateFile(file, "code")) {
                                      setCodeFile(file);
                                    }
                                  }
                                }}
                                onClick={() => !loading && document.getElementById("codeFile").click()}
                                tabIndex={0}
                                role="button"
                                aria-label="Upload Python File"
                                style={{
                                  ...commonInputStyle,
                                  width: "100%",
                                  minWidth: "100%",
                                }}>
                                <div className={groundTruthStyles.uploadPrompt} style={{ width: "100%", textAlign: "center" }}>
                                  <span>{isDraggingCode ? "Drop file here" : "Click to upload or drag and drop"}</span>
                                  <span>
                                    <small>Supported: .py</small>
                                  </span>
                                </div>
                              </div>
                            ) : (
                              <div
                                className={groundTruthStyles.fileCard}
                                style={{
                                  ...commonInputStyle,
                                  width: "100%",
                                  minWidth: "100%",
                                }}>
                                <div className={groundTruthStyles.fileInfo} style={{ width: "100%", textAlign: "left" }}>
                                  <span className={groundTruthStyles.fileName}>{codeFile.name}</span>
                                  <button
                                    type="button"
                                    onClick={() => handleRemoveFile("code")}
                                    className={groundTruthStyles.removeFileButton}
                                    aria-label="Remove file"
                                    style={{ color: isDarkTheme ? "#ff6b6b" : "#dc3545" }}>
                                    &times;
                                  </button>
                                </div>
                              </div>
                            )}
                          </div>
                        )}

                        <div className={style["other"]}>
                          <div className={style["model"]}>
                            <label className={style["label-desc"]}>
                              MODEL
                              <InfoTag message="Select the model." />
                            </label>
                            <div>
                              <DropDown
                                options={models}
                                selectStyle={style.selectStyle}
                                id="model"
                                name="model"
                                value={formData.model}
                                onChange={handleChange}
                                className={style["select-class"]}
                                placeholder={"Select Model"}
                                required
                                disabled={!!props?.recycle}
                              />
                            </div>
                          </div>
                          <div className={style["left"]}>
                            <label className={style["label-desc"]}>{isAddTool ? null : "CREATED BY"}</label>
                            <div>
                              {isAddTool ? null : <input id="created-by" className={style["created-input"]} type="text" name="createdBy" value={editTool.created_by} disabled />}
                            </div>
                          </div>
                        </div>
                        {!props?.recycle && (
                          <div className={style["tagsMainContainer"]}>
                            <label htmlFor="tags" className={style["label-desc"]}>
                              Select Tags
                              <InfoTag message="Select the tags." />
                            </label>
                            <div className={style["tagsContainer"]}>
                              {isAddTool
                                ? initialTags.map((tag, index) => (
                                    <Tag key={"li-<ulName>-" + index} index={index} tag={tag.tag} selected={tag.selected} toggleTagSelection={toggleTagSelection} />
                                  ))
                                : initialUpdateTags.map((tag, index) => (
                                    <Tag key={"li-<ulName>-" + index} index={index} tag={tag.tag} selected={tag.selected} toggleTagSelection={toggleTagSelection} />
                                  ))}
                            </div>
                          </div>
                        )}
                      </div>
                      {showKnowledge && (
                        <MessageUpdateform
                          hideComponent={() => {
                            setShowKnowledge(false);
                            setHideCloseIcon(false);
                          }}
                          showKnowledge={showKnowledge}
                        />
                      )}
                    </div>
                    {props?.recycle ? (
                      <>
                        <div className={style["modal-footer"]}>
                          <div className={style["button-class"]}>
                            <button type="button" className="iafButton iafButtonPrimary" onClick={deleteTool}>
                              {"DELETE"}
                            </button>
                            <button type="submit" className="iafButton iafButtonSecondary">
                              {"RESTORE"}
                            </button>
                          </div>
                        </div>
                      </>
                    ) : (
                      <>
                        <div className={style["modal-footer"]}>
                          <div className={style["button-class"]}>
                            <button type="submit" className="iafButton iafButtonPrimary">
                              {isAddTool ? (contextType === "servers" ? "Add Server" : "Add Tool") : contextType === "servers" ? "Update Server" : "Update Tool"}
                            </button>
                            <button
                              onClick={() => {
                                setCodeFile(null);
                                setFormData(formObject);
                                setShowForm(false);
                              }}
                              className="iafButton iafButtonSecondary">
                              Cancel
                            </button>
                            {errorMessages.length > 0 && !errorModalVisible && !forceAdd && (
                              <button type="button" className="iafButton iafButtonPrimary" onClick={() => setErrorModalVisible(true)}>
                                View Warnings
                              </button>
                            )}
                          </div>
                        </div>
                      </>
                    )}
                  </form>
                  {showExecutorPanel && (
                    <ExecutorPanel code={formData.code} autoExecute={true} executeTrigger={executeTrigger} onClose={() => setShowExecutorPanel(false)} mode="tool" />
                  )}
                </div>
              )}
              {isAddTool && activeTab === "addServer" && !hideServerTab && (
                <div className={style["main-content-wrapper"]}>
                  <AddServer />
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
      <ZoomPopup
        show={showZoomPopup}
        onClose={() => setShowZoomPopup(false)}
        title={popupTitle}
        content={popupContent}
        onSave={handleZoomSave}
        type={popupTitle === "Code Snippet" ? "code" : "text"}
        readOnly={popupTitle === "Code Snippet" && !!codeFile}
      />
      <WarningModal
        show={errorModalVisible}
        messages={errorMessages}
        onClose={() => {
          setErrorModalVisible(false);
          setForceAdd(false);
        }}
        onForceAdd={async () => {
          setErrorModalVisible(false);
          await handleSubmit(null, true);
        }}
        showForceAdd={forceAdd}
        isUpdate={!isAddTool}
      />
    </>
  );
}

export default ToolOnBoarding;
