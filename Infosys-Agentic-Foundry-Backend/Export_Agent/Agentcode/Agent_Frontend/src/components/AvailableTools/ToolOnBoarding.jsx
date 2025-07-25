import React, { useEffect, useState, useRef } from "react";
import style from "../../css_modules/ToolOnboarding.module.css";
import { updateTools, addTool,RecycleTools,deletedTools } from "../../services/toolService.js";
import Loader from "../commonComponents/Loader.jsx";
import DropDown from "../commonComponents/DropDowns/DropDown";
import { APIs,BASE_URL } from "../../constant";
import { useMessage } from "../../Hooks/MessageContext";
import Tag from "../Tag/Tag";
import useFetch from "../../Hooks/useAxios.js";
import Cookies from "js-cookie";
import DeleteModal from "../commonComponents/DeleteModal.jsx";
import { useNavigate } from "react-router-dom";
import InfoTag from "../commonComponents/InfoTag.jsx";
import MessageUpdateform from "../AskAssistant/MsgUpdateform.jsx";
import SVGIcons from "../../Icons/SVGIcons.js";
import ZoomPopup from "../commonComponents/ZoomPopup.jsx";
import {WarningModal} from "../AvailableTools/WarningModal.jsx";

function ToolOnBoarding(props) {
  const loggedInUserEmail = Cookies.get("email");
  const userName = Cookies.get("userName");
  const role = Cookies.get("role");

  const formObject = {
    description: "",
    code: "",
    model: "",
    createdBy: userName === "Guest" ? userName : loggedInUserEmail,
    userEmail: "",
  };
  const {
    isAddTool,
    setShowForm,
    editTool,
    tags,
    refreshData = true,
    fetchPaginatedTools
  } = props;

  const [formData, setFormData] = useState({});
  const [showKnowledge, setShowKnowledge] = useState(false);
  const [loading, setLoading] = useState(false);
  const [errorModalVisible, setErrorModalVisible] = useState(false);
  const [errorMessages, setErrorMessages] = useState([]);


  const [files, setFiles] = useState([]);

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


  const { fetchData } = useFetch();

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
        name:editTool.tool_name,
        createdBy:
          userName === "Guest" ? null : editTool.created_by,
      }));
    }else if(props?.recycle){
setFormData((values) => ({
        ...values,
        item_id: editTool.tool_id,
        description: editTool.tool_description,
        code: editTool.code_snippet,
        model: editTool.model_name,
        userEmail: loggedInUserEmail,
        name:editTool.tool_name,
        createdBy:
          userName === "Guest" ? null : editTool.created_by,
      }));
    } else {
      setFormData(formObject);
    }
  }, []);

  const handleChange =  (event) => {
    const { name, value } = event.target;
    setFormData((values) => ({ ...values, [name]: value }));
  };
  const deleteTool=async()=>{
     let response;
      if(props?.recycle){
const isAdmin = role && role.toUpperCase() === "ADMIN";
      const toolsdata = {
        model_name: formData.model,
        is_admin: isAdmin,
        tool_description: formData.description,
        code_snippet: formData.code,
        created_by: editTool.created_by, // Use creator email from editTool
        user_email_id: formData.userEmail,
        updated_tag_id_list: initialUpdateTags
          .filter((e) => e.selected)
          .map((e) => e.tagId),
      };
      
      response = await deletedTools(toolsdata, editTool.tool_id,props?.selectedType);
       if(response?.is_delete){
          props?.setRestoreData(response)
         addMessage("Tool has been Deleted successfully!", "success");
         setLoading(false);
         setShowForm(false)
        }else{
          addMessage(response?.status_message, "error");
           setLoading(false);
        //  setShowForm(false)
        }
      }
  }

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
      const toolsdata = {
        model_name: formData.model,
        tool_description: formData.description,
        code_snippet: formData.code,
        created_by:
          userName === "Guest" ? formData.createdBy : loggedInUserEmail,
        tag_ids: initialTags.filter((e) => e.selected).map((e) => e.tagId),
      };
      response = await addTool(toolsdata,force);
    } else if(!isAddTool && !props?.recycle){
      const isAdmin = role && role.toUpperCase() === "ADMIN";
      const toolsdata = {
        model_name: formData.model,
        is_admin: isAdmin,
        tool_description: formData.description,
        code_snippet: formData.code,
        created_by: editTool.created_by, // Use creator email from editTool
        user_email_id: formData.userEmail,
        updated_tag_id_list: initialUpdateTags
          .filter((e) => e.selected)
          .map((e) => e.tagId),
      };
      response = await updateTools(toolsdata, editTool.tool_id,props?.selectedType);
    }else{
      if(props?.recycle){
const isAdmin = role && role.toUpperCase() === "ADMIN";
      const toolsdata = {
        model_name: formData.model,
        is_admin: isAdmin,
        tool_description: formData.description,
        code_snippet: formData.code,
        created_by: editTool.created_by, // Use creator email from editTool
        user_email_id: formData.userEmail,
        updated_tag_id_list: initialUpdateTags
          .filter((e) => e.selected)
          .map((e) => e.tagId),
      };
      
      response = await RecycleTools(toolsdata, editTool.tool_id,props?.selectedType);
       if(response?.is_delete){
          props?.setRestoreData(response)
         addMessage("Tool has been restored successfully!", "success");
         setLoading(false);
         setShowForm(false)
        }else{
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
      setShowForm(false);
      setErrorModalVisible(false);
      setForceAdd(false);
    } else if(!props?.recycle) {
      setLoading(false);
      if (response?.message?.includes("Verification failed:")) {
        const match = response.message.match(/Verification failed:\s*\[(.*)\]/s);
        if (match && match[1]) {
          const raw = match[1];
          let warnings = [];
          try {
            warnings = JSON.parse(`[${raw}]`);
          } catch {
            warnings = raw.split(/(?<!\\)',\s*|(?<!\\)"\,\s*/).map(s => s.replace(/^['"]|['"]$/g, ''));
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
        addMessage((response?.message) ? response?.message : "No response received. Please try again.", "error");
      }
    }else{
      if(props?.recycle){
        if(response?.is_delete){
          props?.setRestoreData(response)
         addMessage("Tool has been restored successfully!", "success");
         setLoading(false);
         setShowForm(false)
        }else{
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

  const navigate = useNavigate();

  const handleLoginButton = (e) => {
    e.preventDefault();
    Cookies.remove("userName");
    Cookies.remove("session_id");    
    Cookies.remove("csrf-token");
    Cookies.remove("email");
    Cookies.remove("role");
    navigate("/login");
  };

  const handleZoomClick = (title, content) => {
    setPopupTitle(title);
    setPopupContent(content || "");
    setShowZoomPopup(true);
  };

  const handleZoomSave = (updatedContent) => {
    if (popupTitle === "Code Snippet") {
      setFormData((prev) => ({
        ...prev,
        code: updatedContent,
      }));
    } else if (popupTitle === "Description") {
      setFormData((prev) => ({
        ...prev,
        description: updatedContent,
      }));
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
        <p>
          You are not authorized to update a tool. Please login with registered
          email.
        </p>
        <button onClick={(e) => handleLoginButton(e)}>Login</button>
      </DeleteModal>
      <div id="myOverlay" className={style["overlay"]}>
        {loading && <Loader />}
        <div
          className={
            showKnowledge
              ? style["form-container"] + " " + style["expanded"]
              : style["form-container"]
          }
        >
          <div className={style["container"]}>
            <div className={style["main"]}>
              <div className={style["nav"]}>
                <div className={style["header"]}>
                  <h1 className={style["subText"]}>
                    {props?.recycle ?<>
                    {formData.name}
                    </>:<>
                    {isAddTool ? "TOOL ONBOARDING" : "UPDATE TOOL"}
                    </>}
                    
                  </h1>
                  <div className={style["underline"]}></div>
                </div>
                {props?.recycle ?<>
                 <div className={style["sidebar"]}>
                   <div className={style["toggle"]}>
                    {!hideCloseIcon && (
                      <button
                        className={style["closebtn"]}
                        onClick={() => setShowForm(false)}
                      >
                        &times;
                      </button>
                    )}
                  </div>
                 </div>
                </>:<>
                 <div className={style["sidebar"]}>
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
                 
                  <div
                    className={
                      showKnowledge
                        ? style["knowledge"] + " " + style["active"]
                        : style["knowledge"]
                    }
                  >
                    KNOWLEDGE
                  </div>
                <div className={style["toggle"]}>
                    {!hideCloseIcon && (
                      <button
                        className={style["closebtn"]}
                        onClick={() => setShowForm(false)}
                      >
                        &times;
                      </button>
                    )}
                  </div>
                </div>
                </>}
                
                 
                
               
              </div>
              <form onSubmit={handleSubmit}>
                <div className={`${style["form-content"]} ${props?.recycle ? style.disabledButton: ""}`}>
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
                        className={style["input-class"] +
                          " " +
                          style.agentTextArea
                        }
                        type="text"
                        onChange={handleChange}
                        value={formData.description}
                        
                        required
                      />
                      <button
                          type="button"
                          className={style.copyIcon}
                          onClick={() =>
                            handleCopy("desc", formData.description)
                          }
                          title="Copy"
                        >
                          <SVGIcons
                            icon="fa-regular fa-copy"
                            width={16}
                            height={16}
                            fill="#343741"
                          />
                        </button>
                       <div className={style.iconGroup}>
                          <button
                            type="button"
                            className={style.expandIcon}
                            onClick={() => handleZoomClick("Description", formData.description)}
                            title="Expand"
                          >
                            <SVGIcons
                              icon="fa-solid fa-up-right-and-down-left-from-center"
                              width={16}
                              height={16}
                              fill="#343741"
                            />
                          </button>
                        </div>
                        <span
                          className={`${style.copiedText} ${
                            copiedStates["desc"]
                              ? style.visible
                              : style.hidden
                          }`}
                        >
                          Text Copied!
                        </span>
                      </div>
                    </div>

                    <div className={style["snippet-container"]}>
                      <label className={style["label-desc"]}>
                        CODE SNIPPET
                        <InfoTag message="Enter the code snippet." />
                      </label>
                      <div className={style.textAreaContainer}>
                        <textarea
                          id="code-snippet"
                          name="code"
                          className={
                            style["snippet-textarea"] +
                            " " +
                            style.agentTextArea
                          }
                          type="text"
                          rows=""
                          onChange={handleChange}
                          value={formData.code}
                          required
                        />
                        <button
                          type="button"
                          className={style.copyIcon}
                          onClick={() =>
                            handleCopy("code-snippet", formData.code)
                          }
                          title="Copy"
                        >
                          <SVGIcons
                            icon="fa-regular fa-copy"
                            width={16}
                            height={16}
                            fill="#343741"
                          />
                        </button>
                        <div className={style.iconGroup}>
                          <button
                            type="button"
                            className={style.expandIcon}
                            onClick={() => handleZoomClick("Code Snippet", formData.code)}
                            title="Expand"
                          >
                            <SVGIcons
                              icon="fa-solid fa-up-right-and-down-left-from-center"
                              width={16}
                              height={16}
                              fill="#343741"
                            />
                          </button>
                        </div>
                        <span
                          className={`${style.copiedText} ${
                            copiedStates["code-snippet"]
                              ? style.visible
                              : style.hidden
                          }`}
                        >
                          Text Copied!
                        </span>
                      </div>
                    </div>

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
                          />
                        </div>
                      </div>
                      <div className={style["left"]}>
                        <label className={style["label-desc"]}>
                          {isAddTool ? null : "CREATED BY" }
                        </label>
                        <div>
                          {isAddTool ? null : (
                              <input
                                id="created-by"
                                className={style["created-input"]}
                                type="text"
                                name="createdBy"
                                value={editTool.created_by}
                                disabled
                              />
                          )}
                        </div>
                      </div>
                    </div>
{!props?.recycle &&(
   <div className={style["tagsMainContainer"]}>
                      <label htmlFor="tags" className={style["label-desc"]}>
                        Select Tags
                        <InfoTag message="Select the tags." />
                      </label>
                      <div className={style["tagsContainer"]}>
                        {isAddTool
                          ? initialTags.map((tag, index) => (
                              <Tag
                                //key={index}
                                key={"li-<ulName>-"+index}
                                index={index}
                                tag={tag.tag}
                                selected={tag.selected}
                                toggleTagSelection={toggleTagSelection}
                              />
                            ))
                          : initialUpdateTags.map((tag, index) => (
                              <Tag
                               // key={index}
                               key={"li-<ulName>-"+index}
                                index={index}
                                tag={tag.tag}
                                selected={tag.selected}
                                toggleTagSelection={toggleTagSelection}
                              />
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
{props?.recycle ?<>
 <div className={style["modal-footer"]}>
                  <div className={style["button-class"]}>
                     <button type="submit" className={style["add-button"]}>
                      {"RESTORE"}
                    </button>
                    <button type="button" className={style["add-button"]} onClick={deleteTool}>
    {"DELETE"}
  </button>

                  </div>
                </div>
</>:<>
 <div className={style["modal-footer"]}>
                  <div className={style["button-class"]}>
                    <button
                      onClick={() => setShowForm(false)}
                      className={style["cancel-button"]}
                    >
                      CANCEL
                    </button>
                    <button type="submit" className={style["add-button"]}>
                      {isAddTool ? "ADD TOOL" : "UPDATE"}
                    </button>
                    {errorMessages.length > 0 && !errorModalVisible && !forceAdd && (
                      <button
                        type="button"
                        className={style["viewWarningsButton"]}
                        onClick={() => setErrorModalVisible(true)}
                      >
                        VIEW WARNINGS
                      </button>
                    )}
                  </div>
                </div>
</>}
               
              </form>
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
      />

      <WarningModal
        show={errorModalVisible}
        messages={errorMessages}
        onClose={() => {
          setErrorModalVisible(false);
          setForceAdd(false);
        }}
        onForceAdd={async() => {
          setErrorModalVisible(false);
          await handleSubmit(null, true); 
        }}
        showForceAdd={forceAdd}
      />
    </> 
);
}

export default ToolOnBoarding;