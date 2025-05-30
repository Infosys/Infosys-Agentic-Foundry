import React, { useEffect, useState,useRef,useCallback } from "react";
import styles from "../../../css_modules/UpdateAgent.module.css";
import DropDown from "../../commonComponents/DropDowns/DropDown";
import SVGIcons from "../../../Icons/SVGIcons";
import AddTools from "./AddTools";
import {
  APIs,
  META_AGENT,
  MULTI_AGENT,
  REACT_AGENT,
  SystemPromptsTypes,
} from "../../../constant";
import useFetch from "../../../Hooks/useAxios";
import Loader from "../../commonComponents/Loader";
import { useMessage } from "../../../Hooks/MessageContext";
import Cookies from "js-cookie";
import DeleteModal from "../../commonComponents/DeleteModal";
import { useNavigate } from "react-router-dom";
import ZoomPopup from "../../commonComponents/ZoomPopup";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faExpand } from "@fortawesome/free-solid-svg-icons";
import InfoTag from "../../commonComponents/InfoTag";
import ToolOnBoarding from "../../AvailableTools/ToolOnBoarding";
import { getTools } from "../../../services/toolService";
import { calculateDivs } from "../../../util";
import { getToolsByPageLimit } from "../../../services/toolService";
import { getAgentsByPageLimit} from "../../../services/agentService";
 
const UpdateAgent = (props) => {
  const loggedInUserEmail = Cookies.get("email");
  const userName = Cookies.get("userName");

  const { agentData, onClose, agentsListData, tags, fetchAgents } =
    props;
  const { fetchData, putData,postData } = useFetch();
  const [fullAgentData, setFullAgentData] = useState({});
  const [selectedTools, setSelectedTools] = useState([]);
  const [selectedAgents, setSelectedAgents] = useState([]);
  const [remainingTools, setRemainingTools] = useState([]);
  const [remainingAgents, setRemainingAgents] = useState([]);
  const [agentType, setAgentType] = useState("");
  const [addedToolsId, setAddedToolsId] = useState([]);
  const [removedToolsId, setremovedToolsId] = useState([]);
  const [addedAgentsId, setAddedAgentsId] = useState([]);
  const [removedAgentsId, setRemovedAgentsId] = useState([]);
  const [systemPromptType, setSystemPromptType] = useState(
    SystemPromptsTypes[0].value
  );
  const [systemPromptData, setSystemPromptData] = useState({});
  const [selectedPromptData, setSelectedPromptData] = useState({});
  const [selectedTag, setSelectedTags] = useState([]);
  const [models, setModels] = useState([]);
  const [showUpdateModal, setShowUpdateModal] = useState(false);

  const [showZoomPopup, setShowZoomPopup] = useState(false);
  const [popupTitle, setPopupTitle] = useState("");
  const [popupContent, setPopupContent] = useState("");
  const [toggleSelected, setToggleSelected] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [editTool, setEditTool] = useState({});
  const[loader,setLoader] = useState(false);
  const toolListContainerRef = useRef(null);
  const pageRef = useRef(1);
  const hasLoadedOnce = useRef(false);
  const [searchTerm, setSearchTerm] = useState("");
 
  const handleZoomClick = (title, content) => {
    setPopupTitle(title);
    setPopupContent(content);
    setShowZoomPopup(true);
  };

  const [formData, setFormData] = useState({
    agentic_application_name: agentData?.agentic_application_name,
    created_by: "",
    agentic_application_description:
      fullAgentData?.agentic_application_description ||
      agentData?.agentic_application_description,
    agentic_application_workflow_description:
      fullAgentData?.agentic_application_workflow_description ||
      agentData?.agentic_application_workflow_description,
    model_name: agentData?.model_name,
    system_prompt: fullAgentData?.system_prompt || agentData?.system_prompt,
  });

  const [copiedStates, setCopiedStates] = useState({});

  const { addMessage, setShowPopup } = useMessage();
  const [visibleData, setVisibleData] = useState([]);
  const [totalCount, setTotalCount] = useState(0);
  const [page, setPage] = useState(1);
 
  useEffect(() => {
    if (!loader) {
      setShowPopup(true);
    } else {
      setShowPopup(false);
    }
  }, [loader]);

  const handleChange = (event) => {
    const { name, value } = event.target;
    setFormData({
      ...formData,
      [name]: value,
    });
  };

  const handleClose = () => {
    onClose();
  };

  const fetchAgentDetail = async () => {
    if (loader) return; // Prevent concurrent requests
    setLoader(true);
    try {
      const data = await fetchData(
        APIs.GET_AGENT + agentData?.agentic_application_id
      );
     
      // Batch your state updates where possible
      const agentType = data[0]?.agentic_application_type;
      const systemPrompts = JSON.parse(data[0]["system_prompt"], null, "\t");
      const selectedToolsId = JSON.parse(data[0]?.tools_id);
     
      setFullAgentData(data[0]);
      setAgentType(agentType);
      setSystemPromptData(systemPrompts);
     
      // Update form data in one operation
      setFormData(prevFormData => ({
        ...prevFormData,
        agentic_application_type: data[0]?.agentic_application_type,
        created_by: userName === "Guest" ? data[0].created_by : loggedInUserEmail,
        agentic_application_description: data[0]?.agentic_application_description,
        agentic_application_workflow_description: data[0]?.agentic_application_workflow_description,
        system_prompt: data[0]?.system_prompt,
        model_name: data[0]?.model_name,
        agentic_application_name: data[0]?.agentic_application_name,
      }));
     
      // Load tools separately
      if (agentType) {
        loadRelatedTools(agentType, selectedToolsId);
      }
    } catch {
      console.error("Details failed");
    } finally {
      setLoader(false);
    }
  };
 
  // New function to handle tool loading
  const loadRelatedTools = async (type, selectedToolsId) => {
    try {
      if (type === REACT_AGENT || type === MULTI_AGENT) {
        const response = await postData("/get-tools-by-list",selectedToolsId);
        setSelectedTools(response);
      } else if (type === META_AGENT) {
        const response = await postData("/get-agents-by-list",selectedToolsId);
        setSelectedAgents(response);
      }
    } catch {
      console.error("Check problem in Load Related Tools");
    }
  };
 
  const hasLoadedInitialData = useRef(false);
 
  useEffect(() => {
    if (!hasLoadedInitialData.current) {
      hasLoadedInitialData.current = true;
      fetchAgentDetail();
    }
  }, []);
 
  const fetchToolsData = async (pageNumber, divsCount) => {
    setLoader(true);
    try {
      if (agentType === REACT_AGENT || agentType === MULTI_AGENT) {
        const response = await getToolsByPageLimit({ page: pageNumber, limit: divsCount });
 
        const fetchedTools = response?.details || [];
 
        const filteredTools = fetchedTools.filter(
          (tool) => !selectedTools?.some(
            (selectedTool) => selectedTool.tool_id === tool.tool_id
          )
        );
 
        setRemainingTools((prev) => [...prev, ...filteredTools]);
        setVisibleData((prev) => [...prev, ...filteredTools]);
        setTotalCount(response?.total_count || 0);
      } else if (agentType === META_AGENT) {
        const response = await getAgentsByPageLimit({ page: pageNumber, limit: divsCount });
        const fetchedAgents = response?.details || [];
        const agents = fetchedAgents?.filter(
          (agent) => !selectedAgents?.some(
            (selectedTool) =>
              agent?.agentic_application_id === selectedTool.agentic_application_id
          )
        );
        setRemainingAgents((prev) => [...prev, ...agents]);
        setVisibleData((prev) => [...prev, ...agents]);
        setTotalCount(response?.total_count || 0);
      }
    } catch {
      console.error("Error fetching tools or agents");
    }
    finally{
      setLoader(false);
    }
  };
 
  useEffect(()=>{
    const divsCount = calculateDivs(toolListContainerRef, 231, 70, 26);
    fetchToolsData(1,divsCount)
  },[agentType])
 
  const loadMoreData = useCallback(() => {
    if (loader || visibleData.length >= totalCount) return;
    const nextPage = pageRef.current + 1;
    const divsCount = calculateDivs(toolListContainerRef, 231, 70, 26);
    setPage(nextPage);
    pageRef.current = nextPage;
    fetchToolsData(nextPage, divsCount);
  }, [loader, visibleData, totalCount]);
 
  const lastScrollTop = useRef(0);
  const scrollDirection = useRef('down');
 
  const handleScroll = () => {
    const container = toolListContainerRef.current;
    if (!container) return;
   
    const currentScrollTop = container.scrollTop;
    scrollDirection.current = currentScrollTop > lastScrollTop.current ? 'down' : 'up';
    lastScrollTop.current = currentScrollTop;
   
    const scrollThreshold = 20;
    const isNearBottom = container.scrollHeight - container.scrollTop <= container.clientHeight + scrollThreshold;
   
    if (isNearBottom && scrollDirection.current === 'down' && !searchTerm.trim() && !loader) {
      loadMoreData();
    }
  };
 
  useEffect(() => {
      if (!hasLoadedOnce.current) {
        hasLoadedOnce.current = true;
        const divsCount = calculateDivs(toolListContainerRef, 231, 70, 26);
        setPage(1);
        pageRef.current = 1;
        setVisibleData([]);
        setRemainingAgents([])
        setRemainingTools([]);
        fetchToolsData(1, divsCount);
      }
    }, [agentType]);
 
  useEffect(() => {
      const container = toolListContainerRef.current;
      if (container) {
        container.addEventListener("scroll", handleScroll);
        return () => container.removeEventListener("scroll", handleScroll);
      }
    }, [visibleData, page, loader]);
 
  useEffect(() => {
    setSelectedPromptData(systemPromptData[systemPromptType]);
  }, [systemPromptType, systemPromptData]);

  const onSubmit = async (e) => {
    e.preventDefault();
    if (userName === "Guest") {
      setShowUpdateModal(true);
      return;
    }
    // const isSystemPromptChanged =
    //   JSON.stringify(systemPromptData) !==
    //   JSON.stringify(JSON.parse(fullAgentData?.system_prompt || "{}"));

      const isSystemPromptChanged = (() => {
        let parsedSystemPrompt = {};
        try {
          parsedSystemPrompt =
            typeof fullAgentData?.system_prompt === "string"
              ? JSON.parse(fullAgentData?.system_prompt)
              : fullAgentData?.system_prompt || {};
            } catch {
              console.error("Error parsing");
        }
      
        return JSON.stringify(systemPromptData) !== JSON.stringify(parsedSystemPrompt);
      })();

    const payload = {
      ...formData,
      updated_tag_id_list: selectedTag,
      is_admin: false,
      system_prompt: isSystemPromptChanged ? systemPromptData : {},
      user_email_id: formData?.created_by,
      agentic_application_id_to_modify: agentData?.agentic_application_id,
      tools_id_to_add: agentType === META_AGENT ? addedAgentsId : addedToolsId,
      tools_id_to_remove:
        agentType === META_AGENT ? removedAgentsId : removedToolsId,
    };
    try {
      let url = "";
      switch (agentType) {
        case REACT_AGENT:
          url = APIs.UPDATE_AGENT;
          break;
        case MULTI_AGENT:
          url = APIs.UPDATE_MULTI_AGENT;
          break;
        case META_AGENT:
          url = APIs.UPADATE_META_AGENT;
          break;
        default:
          break;
      }
      const res = await putData(url, payload);
      fetchAgentDetail();
      fetchAgents();
      if (agentType === META_AGENT) {
        setAddedAgentsId([]);
        setRemovedAgentsId([]);
      } else {
        setAddedToolsId([]);
        setremovedToolsId([]);
      }
      if(res.detail){
        addMessage(res.detail, "error");
      }else{
        addMessage(res.status_message, "success");
      }
    } catch {
      addMessage("Something went wrong!", "error");
      console.error("Try Re-Submitting");
    }
  };

  const handlePromptChange = (e) => {
    e.preventDefault();
    if (agentType === MULTI_AGENT) {
      setSystemPromptData({
        ...systemPromptData,
        [systemPromptType]: e?.target?.value,
      });
    } else {
      setSystemPromptData({
        ...systemPromptData,
        [Object.keys(systemPromptData)[0]]: e?.target?.value,
      });
    }
  };

  const [updatedTags, setUpdatedTags] = useState([]);
  useEffect(() => {
    console.log(fullAgentData)
    if (fullAgentData.tags && tags.length > 0) {
      const newTags = tags.map((tag) => {
        if (fullAgentData.tags.some((editTag) => editTag.tag_id === tag.tag_id)) {
          return { ...tag, selected: true };
        } else {
          return { ...tag, selected: false };
        }
      });

      setUpdatedTags(newTags);
    }
  }, [fullAgentData, tags]);
  useEffect(() => {
    const selected = updatedTags.filter((tag) => tag.selected).map((tag) => tag.tag_id);
    setSelectedTags(selected);
  }, [updatedTags]);
  

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
      console.error("Model fetch failed");
      setModels([]);
    }
  };

  useEffect(() => {
    fetchModels();
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

  const handleZoomSave = (updatedContent) => {
    if (popupTitle === "Agent Goal") {
      setFormData((prev) => ({
        ...prev,
        agentic_application_description: updatedContent,
      }));
    } else if (popupTitle === "Workflow Description") {
      setFormData((prev) => ({
        ...prev,
        agentic_application_workflow_description: updatedContent,
      }));
    } else if (popupTitle === "System Prompt") {
      setSystemPromptData((prev) => ({
        ...prev,
        [Object.keys(systemPromptData)[0]]: updatedContent,
      }));
    }
  };

  // const handleCopy = (key, text) => {
  //   navigator.clipboard.writeText(text);
  //   setCopiedStates((prev) => ({ ...prev, [key]: true })); // Set copied state for the specific key
  //   setTimeout(() => {
  //     setCopiedStates((prev) => ({ ...prev, [key]: false })); // Reset after 2 seconds
  //   }, 2000);
  // };


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
          console.error("Copy failed");
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
        console.error("Fallback: copy failed");
      } finally {
        document.body.removeChild(textarea); // Clean up
      }
    }
  };

  return (
    <>
      <DeleteModal
        show={showUpdateModal}
        onClose={() => setShowUpdateModal(false)}
      >
        <p>
          You are not authorized to update this agent. Please login with
          registered email.
        </p>
        <button onClick={(e) => handleLoginButton(e)}>Login</button>
      </DeleteModal>
      <div className={styles.container}>
        <div className={styles.header}>
          <h6>UPDATE AGENT</h6>
          <p>
            AGENT TYPE: <span>{agentData?.agentic_application_type?.replace(/_/g," ")}</span>
          </p>
          <button onClick={handleClose}>
            <SVGIcons
              icon="close-icon"
              color="#7F7F7F"
              width={28}
              height={28}
            />
          </button>
        </div>
        <form
          className={styles.formContainer}
          onSubmit={(e) => {
            e.preventDefault();
            e.stopPropagation();
            onSubmit(e);
          }}
        >
          <div className={styles.inputName}>
            <label for="agentic_application_name">
              AGENT NAME
              <InfoTag message="Provide name for the agent." />
            </label>
            <input
              type="text"
              id="agentic_application_name"
              name="agentic_application_name"
              value={formData.agentic_application_name}
              required
              disabled
            />
          </div>
          <div className={styles.selectContainer}>
            <label for="model_name">
              MODEL
              <InfoTag message="Select the model for the agent." />
            </label>
            <DropDown
              options={models}
              selectStyle={styles.selectStyle}
              id="model_name"
              name="model_name"
              value={formData.model_name}
              onChange={handleChange}
              required
            />
          </div>
          <div className={styles.inputUserId}>
            <label for="created_by">
              USER EMAIL
              <InfoTag message="Provide email for the agent." />
            </label>
            <input
              type="email"
              id="created_by"
              name="created_by"
              value={formData.created_by}
              onChange={handleChange}
              required
            />
          </div>
          <div className={styles.inputGoal}>
            <label htmlFor="agentic_application_description">
              AGENT GOAL
              <InfoTag message="Provide goal for the agent." />
            </label>
            <div className={styles.textAreaContainer}>
              <textarea
                id="agentic_application_description"
                name="agentic_application_description"
                value={formData.agentic_application_description}
                onChange={handleChange}
                className={styles.agentTextArea}
                required
                onClick={() =>
                  handleZoomClick(
                    "Agent Goal",
                    formData.agentic_application_description
                  )
                }
              />
              <div className={styles.iconContainer}>
                <button
                  type="button"
                  className={styles.copyIcon}
                  onClick={() =>
                    handleCopy(
                      "agentic_application_description",
                      formData.agentic_application_description
                    )
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
                <span
                  className={`${styles.copiedText} ${
                    copiedStates["agentic_application_description"] ? styles.visible : styles.hidden
                  }`}
                >
                  Text Copied!
                </span>
              </div>
            </div>
          </div>
          <div className={styles.inputDescription}>
            <label for="agentic_application_workflow_description">
              WORKFLOW DESCRIPTION
              <InfoTag message="Provide description for the agent." />
            </label>
            <div className={styles.textAreaContainer}>
              <textarea
                id="agentic_application_workflow_description"
                name="agentic_application_workflow_description"
                value={formData.agentic_application_workflow_description}
                onChange={handleChange}
                className={styles.agentTextArea}
                required
                onClick={() =>
                  handleZoomClick(
                    "Workflow Description",
                    formData.agentic_application_workflow_description
                  )
                }
              />
              <div className={styles.iconContainer}>
                <button
                  type="button"
                  className={styles.copyIcon}
                  onClick={() => 
                    handleCopy(
                      "agentic_application_workflow_description",
                      formData.agentic_application_workflow_description
                    )
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
                <span
                  className={`${styles.copiedText} ${
                    copiedStates["agentic_application_workflow_description"] ? styles.visible : styles.hidden
                  }`}
                >
                  Text Copied!
                </span>
              </div>
            </div>
          </div>
          <div className={styles.inputSystemPrompt}>
            {agentType === MULTI_AGENT ? (
              <>
                <DropDown
                  options={SystemPromptsTypes}
                  value={systemPromptType}
                  onChange={(e) => setSystemPromptType(e?.target?.value)}
                  selectStyle={styles.selectNoBorder}
                />
                <div className={styles.textAreaContainer}>
                  <textarea
                    id="system_prompt"
                    name="system_prompt"
                    value={selectedPromptData}
                    onChange={handlePromptChange}
                    className={styles.agentTextArea}
                    required
                    onClick={() =>
                      handleZoomClick("System Prompt", selectedPromptData)
                    }
                  />
                  <div className={styles.iconContainer}>
                    <button
                      type="button"
                      className={styles.copyIcon}
                      onClick={() =>
                        handleCopy(
                          "system_prompt",
                          selectedPromptData
                        )
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
                    <span
                      className={`${styles.copiedText} ${
                        copiedStates["system_prompt"] ? styles.visible : styles.hidden
                      }`}
                    >
                      Text Copied!
                    </span>
                  </div>
                </div>
              </>
            ) : (
              <>
                <label for="system_prompt">SYSTEM PROMPT</label>
                <div className={styles.textAreaContainer}>
                  <textarea
                    id="system_prompt"
                    name="system_prompt"
                    value={systemPromptData[Object.keys(systemPromptData)[0]]}
                    onChange={handlePromptChange}
                    className={styles.agentTextArea}
                    required
                    onClick={() =>
                      handleZoomClick(
                        "System Prompt",
                        systemPromptData[Object.keys(systemPromptData)[0]]
                      )
                    }
                  />
                  <div className={styles.iconContainer}>
                    <button
                      type="button"
                      className={styles.copyIcon}
                      onClick={() => 
                        handleCopy(
                          "system_prompt",
                          systemPromptData[Object.keys(systemPromptData)[0]]
                        )
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
                    <span
                      className={`${styles.copiedText} ${
                        copiedStates["system_prompt"] ? styles.visible : styles.hidden
                      }`}
                    >
                      Text Copied!
                    </span>
                  </div>
                </div>
              </>
            )}
          </div>
          {loader && <Loader />}
          <AddTools
            styles={styles}
            addedToolsId={addedToolsId}
            setAddedToolsId={setAddedToolsId}
            removedToolsId={removedToolsId}
            addedAgentsId={addedAgentsId}
            setAddedAgentsId={setAddedAgentsId}
            removedAgentsId={removedAgentsId}
            setRemovedAgentsId={setRemovedAgentsId}
            setremovedToolsId={setremovedToolsId}
            selectedTools={selectedTools}
            remainingTools={remainingTools}
            selectedAgents={selectedAgents}
            remainingAgents={remainingAgents}
            agentType={agentType}
            setSelectedTags={setSelectedTags}
            tags={updatedTags}
            setTags={setUpdatedTags}
            setToggleSelected={setToggleSelected}
            toggleSelected={toggleSelected}
            selectedTags={selectedTag}
            agentData={agentData}
            tagsList={tags}
            setShowForm={setShowForm}
            editTool={editTool}
            setEditTool={setEditTool}
            toolListContainerRef={toolListContainerRef}
          />

          <div className={styles.btns}>
            <button onClick={handleClose} className={styles.closeBtn}>
              CLOSE
            </button>
            <input type="submit" value="UPDATE" className={styles.submitBtn} />
          </div>
        </form>
        {loader && <Loader />}
        <ZoomPopup
          show={showZoomPopup}
          onClose={() => setShowZoomPopup(false)}
          title={popupTitle}
          content={popupContent}
          onSave={handleZoomSave}
        />
        {showForm && (
          <ToolOnBoarding
            setShowForm={setShowForm}
            isAddTool={false}
            editTool={editTool}
            tags={tags}
            refreshData={false}
          />
        )}
      </div>
    </>
  );
};

export default UpdateAgent;