import React, { useEffect, useState, useRef, useCallback } from "react";
import styles from "../../../css_modules/UpdateAgent.module.css";
import DropDown from "../../commonComponents/DropDowns/DropDown";
import SVGIcons from "../../../Icons/SVGIcons";
import AddTools from "./AddTools";
import AddToolsFilterModal from "./AddToolsFilter";
import {
  APIs,
  META_AGENT,
  MULTI_AGENT,
  REACT_AGENT,
  PLANNER_META_AGENT,
  SystemPromptsMultiAgent,
  SystemPromptsPlannerMetaAgent,
  REACT_CRITIC_AGENT,
  PLANNER_EXECUTOR_AGENT,
  systemPromptReactCriticAgents,
  systemPromptPlannerExecutorAgents,
} from "../../../constant";
import useFetch from "../../../Hooks/useAxios";
import Loader from "../../commonComponents/Loader";
import { useMessage } from "../../../Hooks/MessageContext";
import Cookies from "js-cookie";
import DeleteModal from "../../commonComponents/DeleteModal";
import ZoomPopup from "../../commonComponents/ZoomPopup";
import InfoTag from "../../commonComponents/InfoTag";
import ToolOnBoarding from "../../AvailableTools/ToolOnBoarding";
import { useToolsAgentsService } from "../../../services/toolService";
import { debounce } from "lodash";
import { useMcpServerService } from "../../../services/serverService";
import { useAuth } from "../../../context/AuthContext";

const UpdateAgent = (props) => {
  const { getAllServers } = useMcpServerService();
  const loggedInUserEmail = Cookies.get("email");
  const userName = Cookies.get("userName");
  const role = Cookies.get("role");

  const { agentData, onClose, agentsListData, tags, fetchAgents, searchTerm, RestoreAgent, deleteAgent } = props;
  const { fetchData, putData, postData } = useFetch();
  const [fullAgentData, setFullAgentData] = useState({});
  const [selectedTools, setSelectedTools] = useState([]);
  const [selectedAgents, setSelectedAgents] = useState([]);
  const [remainingTools, setRemainingTools] = useState([]);
  const [remainingAgents, setRemainingAgents] = useState([]);
  const [agentType, setAgentType] = useState("");
  const [selectedToolsLoading, setSelectedToolsLoading] = useState(true); // Added state
  const [addedToolsId, setAddedToolsId] = useState([]);
  const [removedToolsId, setremovedToolsId] = useState([]);
  const [addedAgentsId, setAddedAgentsId] = useState([]);
  const [removedAgentsId, setRemovedAgentsId] = useState([]);
  const [systemPromptType, setSystemPromptType] = useState(SystemPromptsMultiAgent[0].value);
  const [plannersystempromtType, setPlannersystempromptType] = useState(SystemPromptsPlannerMetaAgent[0].value);
  const [reactCriticSystemPromptType, setReactCriticSystemPromptType] = useState(systemPromptReactCriticAgents[0].value);
  const [plannerExecutorSystemPromptType, setPlannerExecutorSystemPromptType] = useState(systemPromptPlannerExecutorAgents[0].value);
  const [systemPromptData, setSystemPromptData] = useState({});
  const [selectedPromptData, setSelectedPromptData] = useState({});
  const [selectedTag, setSelectedTags] = useState([]);
  const [models, setModels] = useState([]);
  const [showUpdateModal, setShowUpdateModal] = useState(false);
  const { getToolsSearchByPageLimit, getAgentsSearchByPageLimit, calculateDivs } = useToolsAgentsService();

  const [showZoomPopup, setShowZoomPopup] = useState(false);
  const [popupTitle, setPopupTitle] = useState("");
  const [popupContent, setPopupContent] = useState("");
  const [popupType, setPopupType] = useState("text");
  const [toggleSelected, setToggleSelected] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [editTool, setEditTool] = useState({});
  const [loader, setLoader] = useState(false);
  const [filterModalOpen, setFilterModalOpen] = useState(false);
  const toolListContainerRef = useRef(null);
  const pageRef = useRef(1);
  const hasLoadedOnce = useRef(false);

  const [remainingServers, setRemainingServers] = useState([]);

  const handleZoomClick = (title, content, type = "text") => {
    setPopupTitle(title);
    setPopupContent(content);
    setPopupType(type);
    setShowZoomPopup(true);
  };

  const [formData, setFormData] = useState({
    agentic_application_name: agentData?.agentic_application_name,
    created_by: "",
    agentic_application_description: fullAgentData?.agentic_application_description || agentData?.agentic_application_description,
    agentic_application_workflow_description: fullAgentData?.agentic_application_workflow_description || agentData?.agentic_application_workflow_description,
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
    if (!props?.recycleBin) {
      if (loader) return; // Prevent concurrent requests
      setLoader(true);
      try {
        const data = await fetchData(APIs.GET_AGENTS_BY_ID + agentData?.agentic_application_id);

        // Batch your state updates where possible
        const agentType = data[0]?.agentic_application_type;
        const systemPrompts = typeof data[0]["system_prompt"] === "string" ? JSON.parse(data[0]["system_prompt"], null, "\t") : data[0]["system_prompt"];
        const selectedToolsId = typeof data[0]["tools_id"] === "string" ? JSON.parse(data[0]["tools_id"]) : data[0]["tools_id"];
        setFullAgentData(data[0]);
        setAgentType(agentType);
        setSystemPromptData(systemPrompts);

        // Update form data in one operation
        setFormData((prevFormData) => ({
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
          setSelectedToolsLoading(true);
          loadRelatedTools(agentType, selectedToolsId);
        } else {
          setSelectedToolsLoading(false); // If no agentType, nothing to load
        }
      } catch {
        console.error("Details failed");
      } finally {
        setLoader(false);
      }
    } else {
      setAgentType(agentData?.agentic_application_type);
      setSystemPromptData(JSON.parse(agentData["system_prompt"], null, "\t"));
      setFullAgentData(agentData);
      loadRelatedTools(agentData?.agentic_application_type, JSON.parse(agentData.tools_id));
      setLoader(false);
    }
  };

  // New function to handle tool loading
  const loadRelatedTools = async (type, selectedToolsId) => {
    try {
      if (type === REACT_AGENT || type === MULTI_AGENT || type === REACT_CRITIC_AGENT || type === PLANNER_EXECUTOR_AGENT) {
        const response = await postData(APIs.GET_TOOLS_BY_LIST, selectedToolsId);
        setSelectedTools(response);
      } else if (type === META_AGENT || type === PLANNER_META_AGENT) {
        const response = await postData(APIs.GET_AGENTS_BY_LIST, selectedToolsId);
        setSelectedAgents(response);
      }
    } catch {
      console.error("Check problem in Load Related Tools");
    } finally {
      setSelectedToolsLoading(false); // Set loading to false when done
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
    if (!props?.recycleBin) {
      setLoader(true);
      try {
        if (agentType === REACT_AGENT || agentType === MULTI_AGENT || agentType === REACT_CRITIC_AGENT || agentType === PLANNER_EXECUTOR_AGENT) {
          const response = await getToolsSearchByPageLimit({
            page: pageNumber,
            limit: divsCount,
            search: "",
          });
          const fetchedTools = response || [];
          const filteredTools = fetchedTools.filter((tool) => !selectedTools?.some((selectedTool) => selectedTool.tool_id === tool.tool_id));
          setRemainingTools((prev) => (pageNumber === 1 ? filteredTools : [...prev, ...filteredTools]));
          setVisibleData((prev) => (pageNumber === 1 ? filteredTools : [...prev, ...filteredTools]));
          setTotalCount(fetchedTools.length || 0);
        } else if (agentType === META_AGENT || agentType === PLANNER_META_AGENT) {
          const response = await getAgentsSearchByPageLimit({
            page: pageNumber,
            limit: divsCount,
            search: "",
          });
          const fetchedAgents = response || [];
          const agents = fetchedAgents?.filter(
            (agent) =>
              (agent.agentic_application_type === REACT_AGENT || agent.agentic_application_type === MULTI_AGENT) &&
              !selectedAgents?.some((selectedTool) => agent?.agentic_application_id === selectedTool.agentic_application_id)
          );
          setRemainingAgents((prev) => (pageNumber === 1 ? agents : [...prev, ...agents]));
          setVisibleData((prev) => (pageNumber === 1 ? agents : [...prev, ...agents]));
          setTotalCount(fetchedAgents.length || 0);
        }
      } catch {
        console.error("Error fetching tools or agents");
      } finally {
        setLoader(false);
      }
    }
  };

  // useEffect(()=>{
  //   const divsCount = calculateDivs(toolListContainerRef, 231, 70, 26);
  //   fetchToolsData(1,divsCount)
  // },[agentType])

  // --- Patch: Ensure selectedTools is loaded before fetching unmapped tools ---
  useEffect(() => {
    if (!agentType) return;
    // Only fetch unmapped tools after selectedTools is loaded
    if (agentType === REACT_AGENT || agentType === MULTI_AGENT || agentType === REACT_CRITIC_AGENT || agentType === PLANNER_EXECUTOR_AGENT) {
      if (selectedToolsLoading) return; // Wait for selectedTools to load
      const divsCount = calculateDivs(toolListContainerRef, 231, 70, 26);
      // Reset pagination and data for the list of remaining tools/agents
      setPage(1);
      pageRef.current = 1;
      setVisibleData([]);
      setRemainingAgents([]);
      setRemainingTools([]);

      fetchToolsData(1, divsCount); // Pass latest searchTerm
    } else if (agentType === META_AGENT || agentType === PLANNER_META_AGENT) {
      if (selectedToolsLoading) return;
      const divsCount = calculateDivs(toolListContainerRef, 231, 70, 26);
      setPage(1);
      pageRef.current = 1;
      setVisibleData([]);
      setRemainingAgents([]);
      fetchToolsData(1, divsCount);
    }
  }, [agentType, selectedToolsLoading, selectedTools, selectedAgents]);

  const loadMoreData = useCallback(() => {
    if (loader || visibleData.length >= totalCount) return;
    const nextPage = pageRef.current + 1;
    const divsCount = calculateDivs(toolListContainerRef, 231, 70, 26);
    setPage(nextPage);
    pageRef.current = nextPage;
    fetchToolsData(nextPage, divsCount);
  }, [loader, visibleData, totalCount]);

  useEffect(() => {
    const debouncedCheckAndLoad = debounce(() => {
      if (!searchTerm?.trim() && tags?.length === 0) {
        const container = toolListContainerRef.current;
        if (container && container.scrollHeight <= container.clientHeight && agentsListData.length < totalCount) {
          loadMoreData();
        }
      }
    }, 300);
    const handleResize = () => {
      debouncedCheckAndLoad();
    };

    window.addEventListener("resize", handleResize);
    return () => {
      window.removeEventListener("resize", handleResize);
      debouncedCheckAndLoad.cancel && debouncedCheckAndLoad.cancel();
    };
  }, [visibleData.length, totalCount, tags]);
  useEffect(() => {
    if (agentType === PLANNER_META_AGENT) {
      setSelectedPromptData(systemPromptData[plannersystempromtType]);
    } else if (agentType === REACT_CRITIC_AGENT) {
      setSelectedPromptData(systemPromptData[reactCriticSystemPromptType]);
    } else if (agentType === PLANNER_EXECUTOR_AGENT) {
      setSelectedPromptData(systemPromptData[plannerExecutorSystemPromptType]);
    } else {
      setSelectedPromptData(systemPromptData[systemPromptType]);
    }
  }, [systemPromptType, systemPromptData, plannersystempromtType, reactCriticSystemPromptType, plannerExecutorSystemPromptType]);

  const onSubmit = async (e) => {
    e.preventDefault();
    if (userName === "Guest") {
      setShowUpdateModal(true);
      return;
    }
    setLoader(true);

    const isSystemPromptChanged = (() => {
      let parsedSystemPrompt = {};
      try {
        parsedSystemPrompt = typeof fullAgentData?.system_prompt === "string" ? JSON.parse(fullAgentData?.system_prompt) : fullAgentData?.system_prompt || {};
      } catch {
        console.error("Error parsing");
      }

      return JSON.stringify(systemPromptData) !== JSON.stringify(parsedSystemPrompt);
    })();

    const payload = {
      ...formData,
      created_by: fullAgentData.created_by, // Always use creator email from fullAgentData
      updated_tag_id_list: selectedTag,
      is_admin: role && role.toUpperCase() === "ADMIN",
      system_prompt: isSystemPromptChanged ? systemPromptData : {},
      user_email_id: formData?.created_by,
      agentic_application_id_to_modify: agentData?.agentic_application_id,
      tools_id_to_add: agentType === META_AGENT || agentType === PLANNER_META_AGENT ? addedAgentsId : addedToolsId,
      tools_id_to_remove: agentType === META_AGENT || agentType === PLANNER_META_AGENT ? removedAgentsId : removedToolsId,
    };
    try {
      let url = APIs.UPDATE_AGENTS;
      const res = await putData(url, payload);
      fetchAgentDetail();
      fetchAgents();
      if (agentType === META_AGENT || agentType === PLANNER_META_AGENT) {
        setAddedAgentsId([]);
        setRemovedAgentsId([]);
      } else {
        setAddedToolsId([]);
        setremovedToolsId([]);
      }
      if (res.detail) {
        addMessage(res.detail, "error");
      } else {
        addMessage(res.status_message, "success");
      }
    } catch {
      addMessage("Something went wrong!", "error");
    } finally {
      setLoader(false);
    }
  };

  const handlePromptChange = (e) => {
    e.preventDefault();
    if (agentType === MULTI_AGENT) {
      setSystemPromptData({
        ...systemPromptData,
        [systemPromptType]: e?.target?.value,
      });
    } else if (agentType === PLANNER_META_AGENT) {
      setSystemPromptData({
        ...systemPromptData,
        [plannersystempromtType]: e?.target?.value,
      });
    } else if (agentType === REACT_CRITIC_AGENT) {
      setSystemPromptData({
        ...systemPromptData,
        [reactCriticSystemPromptType]: e?.target?.value,
      });
    } else if (agentType === PLANNER_EXECUTOR_AGENT) {
      setSystemPromptData({
        ...systemPromptData,
        [plannerExecutorSystemPromptType]: e?.target?.value,
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

  const handleFilter = (selectedTags) => {
    setSelectedTags(selectedTags); // Update selected tags
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
      console.error("Model fetch failed");
      setModels([]);
    }
  };

  // Use a ref to ensure models are fetched only once
  const hasLoadedModelsOnce = useRef(false);

  useEffect(() => {
    if (hasLoadedModelsOnce.current) return;
    hasLoadedModelsOnce.current = true;
    fetchModels();
  }, []);

  const { logout } = useAuth();

  const handleLoginButton = (e) => {
    e.preventDefault();
    logout("/login");
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
      if (agentType === MULTI_AGENT) {
        setSystemPromptData((prev) => ({
          ...prev,
          [systemPromptType]: updatedContent,
        }));
      } else if (agentType === PLANNER_META_AGENT) {
        setSystemPromptData((prev) => ({
          ...prev,
          [plannersystempromtType]: updatedContent,
        }));
      } else if (agentType === REACT_CRITIC_AGENT) {
        setSystemPromptData((prev) => ({
          ...prev,
          [reactCriticSystemPromptType]: updatedContent,
        }));
      } else if (agentType === PLANNER_EXECUTOR_AGENT) {
        setSystemPromptData((prev) => ({
          ...prev,
          [plannerExecutorSystemPromptType]: updatedContent,
        }));
      } else {
        setSystemPromptData((prev) => ({
          ...prev,
          [Object.keys(systemPromptData)[0]]: updatedContent,
        }));
      }
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

  const fetchPaginatedTools = async (pageNumber = 1) => {
    setVisibleData([]);
    setPage(pageNumber);
    pageRef.current = pageNumber;
    const divsCount = calculateDivs(toolListContainerRef, 200, 141, 40);
    await fetchToolsData(pageNumber, divsCount);
  };

  useEffect(() => {
    // Fetch servers only for eligible non-meta agent types.
    const eligibleForServers = [REACT_AGENT, MULTI_AGENT, REACT_CRITIC_AGENT, PLANNER_EXECUTOR_AGENT];
    if (!eligibleForServers.includes(agentType) || props?.recycleBin) {
      setRemainingServers([]);
      return;
    }
    // Wait until selected tools for this agent are loaded so we know what's already mapped.
    if (selectedToolsLoading) return;

    let isCancelled = false;
    (async () => {
      try {
        setLoader(true);
        const allServers = await getAllServers();

        // Collect tool_ids already mapped to THIS agent only (from selectedTools / fullAgentData)
        const currentMappedIds = new Set();
        (selectedTools || []).forEach((t) => {
          if (t && (t.tool_id || t.id)) currentMappedIds.add(t.tool_id || t.id);
        });
        // Fallback: if selectedTools not yet populated but fullAgentData.tools_id exists
        if (currentMappedIds.size === 0) {
          const rawIds = fullAgentData?.tools_id;
          if (Array.isArray(rawIds)) rawIds.forEach((id) => currentMappedIds.add(id));
          else if (typeof rawIds === "string") {
            try {
              JSON.parse(rawIds).forEach((id) => currentMappedIds.add(id));
            } catch {}
          }
        }

        const remaining = (allServers || []).filter((s) => !currentMappedIds.has(s.tool_id || s.id));
        if (!isCancelled) setRemainingServers(remaining);
      } catch {
        if (!isCancelled) setRemainingServers([]);
      } finally {
        if (!isCancelled) setLoader(false);
      }
    })();

    return () => {
      isCancelled = true;
    };
  }, [agentType, selectedToolsLoading, selectedTools, fullAgentData, getAllServers, props?.recycleBin]);

  return (
    <>
      <DeleteModal show={showUpdateModal} onClose={() => setShowUpdateModal(false)}>
        <p>You are not authorized to update this agent. Please login with registered email.</p>
        <div className={styles.buttonContainer}>
          <button onClick={(e) => handleLoginButton(e)} className={styles.loginBtn}>
            Login
          </button>
          <button onClick={() => setShowUpdateModal(false)} className={styles.cancelBtn}>
            Cancel
          </button>
        </div>
      </DeleteModal>
      <div className={styles.container}>
        <div className={styles.header}>
          {props?.recycleBin ? <h6>{agentData?.agentic_application_name.toUpperCase()}</h6> : <h6>UPDATE AGENT</h6>}
          <p>
            AGENT TYPE: <span>{agentData?.agentic_application_type?.replace(/_/g, " ")}</span>
          </p>
          <button onClick={handleClose}>
            <SVGIcons icon="close-icon" color="#7F7F7F" width={28} height={28} />
          </button>
        </div>
        <div className={styles.formContainer}>
          <div className={styles.inputName}>
            <label htmlFor="agentic_application_name">
              AGENT NAME
              <InfoTag message="Provide name for the agent." />
            </label>
            <input type="text" id="agentic_application_name" name="agentic_application_name" value={formData.agentic_application_name} required disabled />
          </div>
          <div className={styles.selectContainer}>
            <label htmlFor="model_name">
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
              disabled={props?.recycleBin}
            />
          </div>
          <div className={styles.inputUserId}>
            <label htmlFor="created_by">
              CREATED BY
              <InfoTag message="Provide email for the agent." />
            </label>
            <input type="email" id="created_by" name="created_by" value={fullAgentData.created_by} onChange={handleChange} disabled />
          </div>
          <div className={styles.tagsFilterContainer}>
            <button
              className={styles.tagsFilterButton}
              onClick={(e) => {
                e.preventDefault();
                setFilterModalOpen(true);
              }}
              disabled={props?.recycleBin}>
              <SVGIcons icon="fa-filter" fill="#007AC0" width={16} height={16} style={{ marginRight: "5px" }} />
              Tags
              {selectedTag.length > 0 && <span className={styles.filterBadge}>{selectedTag.length}</span>}
            </button>
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
                disabled={props?.recycleBin}
              />
              <div className={styles.iconContainer}>
                <button
                  type="button"
                  className={styles.copyIcon}
                  onClick={() => handleCopy("agentic_application_description", formData.agentic_application_description)}
                  title="Copy">
                  <SVGIcons icon="fa-regular fa-copy" width={16} height={16} fill="#343741" />
                </button>
                <div className={styles.iconGroup}>
                  <button
                    type="button"
                    className={styles.expandIcon}
                    onClick={() => handleZoomClick("Agent Goal", formData.agentic_application_description, "text")}
                    title="Expand">
                    <SVGIcons icon="fa-solid fa-up-right-and-down-left-from-center" width={16} height={16} fill="#343741" />
                  </button>
                </div>
                <span className={`${styles.copiedText} ${copiedStates["agentic_application_description"] ? styles.visible : styles.hidden}`}>Text Copied!</span>
              </div>
            </div>
          </div>
          <div className={styles.inputDescription}>
            <label htmlFor="agentic_application_workflow_description">
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
                disabled={props?.recycleBin}
              />
              <div className={styles.iconContainer}>
                <button
                  type="button"
                  className={styles.copyIcon}
                  onClick={() => handleCopy("agentic_application_workflow_description", formData.agentic_application_workflow_description)}
                  title="Copy">
                  <SVGIcons icon="fa-regular fa-copy" width={16} height={16} fill="#343741" />
                </button>
                <div className={styles.iconGroup}>
                  <button
                    type="button"
                    className={styles.expandIcon}
                    onClick={() => handleZoomClick("Workflow Description", formData.agentic_application_workflow_description, "text")}
                    title="Expand">
                    <SVGIcons icon="fa-solid fa-up-right-and-down-left-from-center" width={16} height={16} fill="#343741" />
                  </button>
                </div>
                <span className={`${styles.copiedText} ${copiedStates["agentic_application_workflow_description"] ? styles.visible : styles.hidden}`}>Text Copied!</span>
              </div>
            </div>
          </div>
          <div className={styles.inputSystemPrompt}>
            {agentType === MULTI_AGENT || agentType === PLANNER_META_AGENT || agentType === REACT_CRITIC_AGENT || agentType === PLANNER_EXECUTOR_AGENT ? (
              <>
                <DropDown
                  options={
                    agentType === MULTI_AGENT
                      ? SystemPromptsMultiAgent
                      : agentType === PLANNER_META_AGENT
                      ? SystemPromptsPlannerMetaAgent
                      : agentType === REACT_CRITIC_AGENT
                      ? systemPromptReactCriticAgents
                      : agentType === PLANNER_EXECUTOR_AGENT
                      ? systemPromptPlannerExecutorAgents
                      : SystemPromptsMultiAgent
                  }
                  value={
                    agentType === MULTI_AGENT
                      ? systemPromptType
                      : agentType === PLANNER_META_AGENT
                      ? plannersystempromtType
                      : agentType === REACT_CRITIC_AGENT
                      ? reactCriticSystemPromptType
                      : agentType === PLANNER_EXECUTOR_AGENT
                      ? plannerExecutorSystemPromptType
                      : systemPromptType
                  }
                  onChange={(e) => {
                    if (agentType === MULTI_AGENT) {
                      setSystemPromptType(e?.target?.value);
                    } else if (agentType === PLANNER_META_AGENT) {
                      setPlannersystempromptType(e?.target?.value);
                    } else if (agentType === REACT_CRITIC_AGENT) {
                      setReactCriticSystemPromptType(e?.target?.value);
                    } else if (agentType === PLANNER_EXECUTOR_AGENT) {
                      setPlannerExecutorSystemPromptType(e?.target?.value);
                    }
                  }}
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
                    disabled={props?.recycleBin}
                  />
                  <div className={styles.iconContainer}>
                    <button type="button" className={styles.copyIcon} onClick={() => handleCopy("system_prompt", selectedPromptData)} title="Copy">
                      <SVGIcons icon="fa-regular fa-copy" width={16} height={16} fill="#343741" />
                    </button>
                    <div className={styles.iconGroup}>
                      <button
                        type="button"
                        className={styles.expandIcon}
                        onClick={() => handleZoomClick("System Prompt", selectedPromptData)}
                        title="Expand"
                        disabled={props?.recycleBin}>
                        <SVGIcons icon="fa-solid fa-up-right-and-down-left-from-center" width={16} height={16} fill="#343741" />
                      </button>
                    </div>
                    <span className={`${styles.copiedText} ${copiedStates["system_prompt"] ? styles.visible : styles.hidden}`}>Text Copied!</span>
                  </div>
                </div>
              </>
            ) : (
              <>
                <label htmlFor="system_prompt">SYSTEM PROMPT</label>
                <div className={styles.textAreaContainer}>
                  <textarea
                    id="system_prompt"
                    name="system_prompt"
                    value={systemPromptData[Object.keys(systemPromptData)[0]]}
                    onChange={handlePromptChange}
                    className={styles.agentTextArea}
                    required
                    disabled={props?.recycleBin}
                  />
                  <div className={styles.iconContainer}>
                    <button type="button" className={styles.copyIcon} onClick={() => handleCopy("system_prompt", systemPromptData[Object.keys(systemPromptData)[0]])} title="Copy">
                      <SVGIcons icon="fa-regular fa-copy" width={16} height={16} fill="#343741" />
                    </button>
                    <div className={styles.iconGroup}>
                      <button
                        type="button"
                        className={styles.expandIcon}
                        onClick={() => handleZoomClick("System Prompt", systemPromptData[Object.keys(systemPromptData)[0]])}
                        title="Expand">
                        <SVGIcons icon="fa-solid fa-up-right-and-down-left-from-center" width={16} height={16} fill="#343741" />
                      </button>
                    </div>
                    <span className={`${styles.copiedText} ${copiedStates["system_prompt"] ? styles.visible : styles.hidden}`}>Text Copied!</span>
                  </div>
                </div>
              </>
            )}
          </div>
          {props?.recycleBin ? (
            <>
              {selectedToolsLoading && <Loader />}
              <AddTools
                styles={styles}
                loader={loader}
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
                pageRef={pageRef}
                fetchToolsData={(pageNumber, divsCount) => fetchToolsData(pageNumber, divsCount)}
                setVisibleData={setVisibleData}
                setLoader={setLoader}
                setPage={setPage}
                visibleData={visibleData}
                recycleBin={true}
              />
              <div className={styles.btnsRestore}>
                <input type="button" value="RESTORE" className={styles.restoreBtn} onClick={RestoreAgent} />

                <input type="button" value="DELETE" className={styles.submitBtn} onClick={deleteAgent} />
              </div>
            </>
          ) : (
            <>
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
                remainingServers={remainingServers} // <-- Pass unmapped servers here
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
                pageRef={pageRef}
                fetchToolsData={(pageNumber, divsCount) => fetchToolsData(pageNumber, divsCount)}
                setVisibleData={setVisibleData}
                setLoader={setLoader}
                setPage={setPage}
                visibleData={visibleData}
                recycleBin={props?.recycleBin}
              />

              <div className={styles.btns}>
                <input type="submit" value="UPDATE" className={styles.submitBtn} onClick={onSubmit} />
                <button onClick={handleClose} className={styles.closeBtn}>
                  CLOSE
                </button>
              </div>
            </>
          )}
        </div>
        {loader && <Loader />}
        <ZoomPopup
          show={showZoomPopup}
          onClose={() => setShowZoomPopup(false)}
          title={popupTitle}
          content={popupContent}
          onSave={handleZoomSave}
          recycleBin={props?.recycleBin}
          type={popupType}
        />
        {showForm && <ToolOnBoarding setShowForm={setShowForm} isAddTool={false} editTool={editTool} tags={tags} fetchPaginatedTools={fetchPaginatedTools} contextType="tools" />}
        <AddToolsFilterModal show={filterModalOpen} onClose={() => setFilterModalOpen(false)} tags={updatedTags} handleFilter={handleFilter} selectedTags={selectedTag} />
      </div>
    </>
  );
};

export default UpdateAgent;
