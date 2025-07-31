import React, { useEffect, useRef, useState } from "react";
import styles from "../../css_modules/AskAssistant.module.css";
import stylesNew from "./AskAssistant2.module.css";
import chatInputModule from "./ChatInput.module.css";
import MsgBox from "./MsgBox";
import Toggle from "../commonComponents/Toggle";
import ChatHistorySlider from "./ChatHistorySlider";
import {
  BOT,
  agentTypesDropdown,
  USER,
  APIs,
  likeMessage,
  dislike,
  branchInteruptValue,
  branchInteruptKey,
  CUSTOM_TEMPLATE,
  MULTI_AGENT,
  REACT_AGENT,
  customTemplatId,
  META_AGENT,
  PLANNER_META_AGENT_QUERY,
  PLANNER_META_AGENT,
  liveTrackingUrl,
  REACT_CRITIC_AGENT,
  PLANNER_EXECUTOR_AGENT,
  KB_LIST,
  BASE_URL
} from "../../constant";
import axios, { all } from "axios";
import SVGIcons from "../../Icons/SVGIcons";
import {
  resetChat,
  getChatQueryResponse,
  getChatHistory,
  fetchOldChats,
  fetchNewChats,
} from "../../services/chatService";
import ToastMessage from "../commonComponents/ToastMessage";
import clearChat from "../../Assets/clearchat.png";
import useFetch from "../../Hooks/useAxios";
import { getCsrfToken, getSessionId } from "../../Hooks/useAxios";
import tracking from "../../Assets/tracking.png";
import CustomDropdown from "../commonComponents/DropDowns/CustomDropdown";
import OldChatsHistory from "./OldChatsHistory";
import Cookies from "js-cookie";
import AskAssistantDropdown from "./AskAssisstantDropdown.jsx";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import {
  faPaperclip,
  faChartPie,
  faTrash,
  faArrowTrendUp,
  faHexagonNodes,
  faRobot,
  faScrewdriverWrench,
  faGlobe,
  faArrowUp,
  faCommentMedical,
  faBookOpenReader
} from "@fortawesome/free-solid-svg-icons";
import { useGlobalComponent } from "../../Hooks/GlobalComponentContext.js";
import Loader from "../commonComponents/Loader";

const AskAssistant = () => {
  const loggedInUserEmail = Cookies.get("email");
  const session_id = Cookies.get("session_id");
  const [messageData, setMessageData] = useState([]);
  const [lastResponse, setLastResponse] = useState({});
  const [userChat, setUserChat] = useState("");
  const [generating, setGenerating] = useState(false);
  const [isHuman, setIsHuman] = useState(false);
  const [isTool, setIsTool] = useState(false);
  const [isPlanVerifierOn, setIsPlanVerifierOn] = useState(false);
  const [agentsListData, setAgentsListData] = useState([]);
  const [agentListDropdown, setAgentListDropdown] = useState([]);
  const [agentSelectValue, setAgentSelectValue] = useState("");
  const [agentType, setAgentType] = useState("");
  const [model, setModel] = useState("");
  const [feedBack, setFeedback] = useState("");
  const [fetching, setFetching] = useState(false);
  const [showToast, setShowToast] = useState(false);
  const [isDeletingChat, setIsDeletingChat] = useState(false);
  const [planData, setPlanData] = useState(null);
  const [showInput, setShowInput] = useState(false);
  const [oldChats, setOldChats] = useState([]);
  const [oldSessionId, setOldSessionId] = useState("");
  const [session, setSessionId] = useState(session_id);
  const [selectedModels, setSelectedModels] = useState([]);
  const [toolInterrupt, setToolInterrupt] = useState(false);
  const [toolData, setToolData] = useState(null);
  const [loadingAgents, setLoadingAgents] = useState(true);
  const [isEditable, setIsEditable] = useState(false);
  const [showModelPopover, setShowModelPopover] = useState(false);
  const bullseyeRef = useRef(null);

  const chatbotContainerRef = useRef(null);
  const [likeIcon, setLikeIcon] = useState(false);
  const [showInputSendIcon, setShowInputSendIcon] = useState(false);
  const [isOldChatOpen, setIsOldChatOpen] = useState(false);
  const [isKnowledgeOpen, setIsKnowledgeOpen] = useState(false);
  // Knowledge base popover state
  const [showKnowledgePopover, setShowKnowledgePopover] = useState(false);
  const [showVerifierSettings, setShowVerifierSettings] = useState(false);

  const [agentSearchTerm, setAgentSearchTerm] = useState("");
  const [showAgentDropdown, setShowAgentDropdown] = useState(false);
  const [highlightedAgentIndex, setHighlightedAgentIndex] = useState(-1);
  const [showSettings, setShowSettings] = useState(false);
  const [selectedAgent, setSelectedAgent] = useState("");
  
  const [isHumanVerifierEnabled, setIsHumanVerifierEnabled] = useState(false);
  const [isToolVerifierEnabled, setIsToolVerifierEnabled] = useState(false);
  const [showChatHistory, setShowChatHistory] = useState(false);
    
  const settingsRef = useRef(null);
  const agentTriggerRef = useRef(null);
  const agentSearchInputRef = useRef(null);
  const agentDropdownRef = useRef(null);
  const agentListRef = useRef(null);
  const knowledgePopoverRef = useRef(null);

  let messageDisable = messageData.some((msg) => msg?.message.trim() === "");
  const shouldShowHumanVerifier = () => {
    return agentType === MULTI_AGENT || agentType === PLANNER_EXECUTOR_AGENT || agentType === "multi_agent";
  };
    const handleLiveTracking = () => {
      window.open(liveTrackingUrl, '_blank');
    };
    
  const selectAgent = (agent) => {
    setSelectedAgent(agent);
    closeAgentDropdown();
  };

  const shouldShowToolVerifier = () => {
    return agentType === REACT_AGENT ||
      agentType === MULTI_AGENT ||
      agentType === REACT_CRITIC_AGENT ||
      agentType === PLANNER_EXECUTOR_AGENT ||
      agentType === "react_agent";
  };

  const handleToggle2 = async (e) => {
    if (shouldShowToolVerifier()) {
      handleToolInterrupt(e.target.checked);
    }
  };
  const handleHumanInLoop = (isEnabled) => {
    setIsHuman(isEnabled);
  };
  const popoverRef = useRef(null);
  useEffect(() => {
    function handleClickOutside(event) {
      if (popoverRef.current && !popoverRef.current.contains(event.target)) {
        setShowVerifierSettings(false);
      }
    }

    if (showVerifierSettings) {
      document.addEventListener("mousedown", handleClickOutside);
    }

    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
    };
  }, [showVerifierSettings]);
  const handleToggle = (e) => {
    if (shouldShowHumanVerifier()) {
      handleHumanInLoop(e.target.checked);
    } else {
      handleToolInterrupt(e.target.checked);
    }
  };
  const handleIconClick = () => {
    setShowVerifierSettings((prev) => !prev);
  };
  const oldChatRef = useRef(null);
  const knowledgeRef = useRef(null)
  const toggleDropdown = () => {
    setIsOldChatOpen((prev) => !prev);
  };
  const toggleKnowledge = async () => {
    const newState = !isKnowledgeOpen;
    setIsKnowledgeOpen(newState);
        if (newState && (!knowledgeResponse || knowledgeResponse.length === 0)) {
      await knowledgeBaseData();
    }
  }
  useEffect(() => {
    function handleClickOutside(event) {
      if (oldChatRef.current && !oldChatRef.current.contains(event.target)) {
        setIsOldChatOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
    };
  }, []);
  useEffect(() => {
    function handleClickOutside(event) {
      if (knowledgeRef.current && !knowledgeRef.current.contains(event.target)) {
        setIsKnowledgeOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
    };
  }, []);
  const { showComponent } = useGlobalComponent();

  const { fetchData, postData } = useFetch();

  const msgContainerRef = useRef(null);
  const hasInitialized = useRef(false);

  const allOptionsSelected =
    agentType !== CUSTOM_TEMPLATE
      ? agentType === "" || model === "" || agentSelectValue === ""
      : agentType === "" || model === "";

  useEffect(() => {
    if (hasInitialized.current) return;
    fetchAgents();
    fetchModels();
    // Initialize textarea height
    if (textareaRef.current) {
      calculateHeight();
    }
    hasInitialized.current = true;
  }, []);


  useEffect(() => {
    if (isHumanVerifierEnabled || isToolVerifierEnabled) {
      setIsHumanVerifierEnabled(false);
      setIsToolVerifierEnabled(false);
    }
    setSelectedAgent("");
    setMessageData([]);
    setShowInput(false);
    setFeedback("");
  }, [agentType]);


  const filteredAgents = agentListDropdown.filter((agent) => {
    return agent.agentic_application_name?.toLowerCase().includes(agentSearchTerm.toLowerCase())
  });

  useEffect(() => {
    // Reset highlighted index if it's out of bounds
    if (highlightedAgentIndex >= filteredAgents.length) {
      setHighlightedAgentIndex(filteredAgents.length > 0 ? 0 : -1);
    }
  }, [filteredAgents.length, highlightedAgentIndex]);

  useEffect(() => {
    if (showAgentDropdown && agentSearchInputRef.current) {
      agentSearchInputRef.current.focus();
    }
  }, [showAgentDropdown]);

  useEffect(() => {
    setAgentSelectValue("");
    if (!agentType) return;
    const tempList = agentsListData?.filter(
      (list) => list.agentic_application_type === agentType
    );
    setAgentListDropdown(tempList);
  }, [agentType, agentsListData]);

  useEffect(() => {
    if (!allOptionsSelected) {
      fetchChatHistory();
      fetchOldChatsData();
    } else {
      setMessageData([]);
    }
  }, [model, agentSelectValue, allOptionsSelected]);
  useEffect(() => {
    if (msgContainerRef.current) {
      const container = msgContainerRef.current;
      setTimeout(() => {
        container.scrollTo({
          top: container.scrollHeight,
          behavior: "smooth",
        });
      }, 0);
    }
  }, [messageData, generating]);

  useEffect(() => {
    const handleClickOutside = (event) => {
      if (bullseyeRef.current && !bullseyeRef.current.contains(event.target)) {
        setShowModelPopover(false);
      }
      if (agentDropdownRef.current && !agentDropdownRef.current.contains(event.target)) {
        closeAgentDropdown();
      }
      if (settingsRef.current && !settingsRef.current.contains(event.target)) {
        setShowSettings(false);
      }
      if (knowledgePopoverRef.current && !knowledgePopoverRef.current.contains(event.target)) {
        setShowKnowledgePopover(false);
      }
    };
    document.addEventListener("mousedown", handleClickOutside);
    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
    };
  }, []);

  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
      textareaRef.current.style.height = Math.min(textareaRef.current.scrollHeight, 120) + 'px';
    }
  }, [userChat]);

  const handleSettingsKeyDown = (e) => {
    if (!showSettings) return;

    switch (e.key) {
      case 'Escape':
        e.preventDefault();
        setShowSettings(false);
        if (settingsRef.current) {
          const settingsButton = settingsRef.current.querySelector('button');
          if (settingsButton) settingsButton.focus();
        }
        break;
    }
  };

  const handleToggleKeyDown = (e, toggleHandler, currentValue) => {
    switch (e.key) {
      case 'Enter':
      case ' ':
        e.preventDefault();
        toggleHandler(!currentValue);
        break;
      case 'ArrowRight':
        e.preventDefault();
        if (!currentValue) toggleHandler(true);
        break;
      case 'ArrowLeft':
        e.preventDefault();
        if (currentValue) toggleHandler(false);
        break;
    }
  };

  const closeAgentDropdown = () => {
    setShowAgentDropdown(false);
    setAgentSearchTerm("");
    setHighlightedAgentIndex(-1);
    if (agentTriggerRef.current) {
      agentTriggerRef.current.focus();
    }
  };
  const handleAgentDropdownToggle = () => {
    if (showAgentDropdown) {
      closeAgentDropdown();
    } else {
      setShowAgentDropdown(true);
      // If opening via keyboard, highlight first item
      if (filteredAgents.length > 0) {
        setHighlightedAgentIndex(0);
      }
    }
  };

  const converToChatFormat = (chatHistory) => {
    let chats = [];
    setPlanData(null);
    setToolData(null);
    if (chatHistory && chatHistory[branchInteruptKey] === branchInteruptValue) {
      setFeedback("no");
      setShowInput(true);
    }
    chatHistory?.executor_messages?.map((item, index) => {
      chats?.push({ type: USER, message: item?.user_query });
      chats?.push({
        type: BOT,
        message: item?.final_response,
        toolcallData: item,
        userText: item?.user_query,
        steps: JSON.stringify(item?.agent_steps, null, "\t"),
        ...(index === chatHistory?.executor_messages?.length - 1 && {
          plan: chatHistory?.plan,
        }),
      });
    });
    setPlanData(chatHistory?.plan);
    setToolData(chats?.toolcallData);
    return chats;
  };

  const fetchChatHistory = async (sessionId = session) => {
    const data = {
      session_id: sessionId,
      agent_id:
        agentType === CUSTOM_TEMPLATE ? customTemplatId : agentSelectValue,
    };
    const chatHistory = await getChatHistory(data);
    setLastResponse(chatHistory);
    setMessageData(converToChatFormat(chatHistory) || []);
  };

  const addMessage = (type, message, steps, plan, userText) => {
    setMessageData((prevProp) => [
      ...prevProp,
      { type, message, steps, plan, userText },
    ]);
  };

  const sendHumanInLoop = async (isApprove = "", feedBack = "", userText) => {
    const payload = {
      agentic_application_id:
        agentType === CUSTOM_TEMPLATE ? customTemplatId : agentSelectValue,
      query: userText,
      session_id: oldSessionId !== "" ? oldSessionId : session,
      model_name: model,
      reset_conversation: false,
      ...(isApprove !== "" && { approval: isApprove }),
      ...(feedBack !== "" && { feedback: feedBack }),
      ...(toolInterrupt ? { interrupt_flag: true } : { interrupt_flag: false }),
    };
    
    if (selectedValues && selectedValues.length > 0) {
      const selectedString = selectedValues.join(',');
      payload.knowledgebase_name = JSON.stringify(selectedString);
    }
    let response;
    try {
      const url =
        agentType === CUSTOM_TEMPLATE
          ? APIs.CUSTOME_TEMPLATE_QUERY
          : agentType === PLANNER_EXECUTOR_AGENT
            ? APIs.PLANNER_EXECUTOR_AGENT_QUERY
            : APIs.PLANNER;
      response = await postData(url, payload);
      setLastResponse(response);
      setPlanData(response?.plan);
      setMessageData(converToChatFormat(response) || []);
    } catch (err) {
      console.error(err);
    }
    return response;
  };

  const sendUserMessage = async () => {
    setFetching(true);
    resetHeight();
    if (!userChat || generating) return;
    addMessage(USER, userChat);
    setUserChat("");
    setGenerating(true);
    setLikeIcon(false);
    let userText = userChat;
    const payload = {
      agentic_application_id:
        agentType === CUSTOM_TEMPLATE ? customTemplatId : agentSelectValue,
      query: userChat.trim(),
      session_id: oldSessionId !== "" ? oldSessionId : session,
      model_name: model,
      reset_conversation: false,
      ...(toolInterrupt ? { interrupt_flag: true } : { interrupt_flag: false }),
    };
    
    if (selectedValues && selectedValues.length > 0) {
      const selectedString = selectedValues.join(',');
      payload.knowledgebase_name = JSON.stringify(selectedString);
    }
    if (isHuman) {
      await sendHumanInLoop("", "", userText);
    } else {
      const url =
        agentType === META_AGENT
          ? APIs.META_AGENT_QUERY
          : agentType === PLANNER_META_AGENT
            ? APIs.PLANNER_META_AGENT_QUERY
            : APIs.REACT_MULTI_AGENT_QUERY;

      const response = await getChatQueryResponse(payload, url);
      setLastResponse(response);
      if (response === null) {
        setShowToast(true);
        setTimeout(() => {
          setShowToast(false);
        }, 5000);
      }

      setMessageData(converToChatFormat(response) || []);
    }
    setGenerating(false);
    setFetching(false);
    setSelectedValues("")
  };

  const handleKeyDown = (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      sendUserMessage();
      resetHeight();
    } else if (event.shiftKey && event.key === "Enter") {
      event.preventDefault();
      setUserChat((prev) => prev + "\n");
      calculateHeight();
    }
  };

  const handleTypeChange = (selectedOption) => {
    setAgentType(selectedOption);
    setLikeIcon(false);
    setIsPlanVerifierOn(
      selectedOption === MULTI_AGENT ||
      selectedOption === REACT_AGENT ||
      selectedOption === REACT_CRITIC_AGENT ||
      selectedOption === PLANNER_EXECUTOR_AGENT ||
      selectedOption === "react_agent"
    );
    if (selectedOption === CUSTOM_TEMPLATE) {
      setIsHuman(true);
    } else {
      setIsHuman(false);
    }
  };

  const handleResetChat = async () => {
    if (window.confirm("Are you sure you want to delete this chat?")) {
      const data = {
        session_id: oldSessionId !== "" ? oldSessionId : session,
        agent_id:
          agentType !== CUSTOM_TEMPLATE ? agentSelectValue : customTemplatId,
      };
      try {
        const response = await resetChat(data);
        if (response?.status === "success") {
          setMessageData([]);
          fetchOldChatsData();
          setOldSessionId("");
        }
      }
      catch (error) {
        console.error("Error deleting chat:", error);
      }
    }
  };

  const fetchAgents = async () => {
    try {
      setLoadingAgents(true);
      const data = await fetchData(APIs.GET_AGENTS_BY_DETAILS);
      setAgentsListData(data);
    } catch (e) {
      console.error(e);
    } finally {
      setLoadingAgents(false);
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
        setSelectedModels(formattedModels);
      } else {
        setSelectedModels([]);
      }
    } catch (e) {
      console.error(e);
      setSelectedModels([]);
    }
  };

  const fetchOldChatsData = async () => {
    const data = {
      user_email: loggedInUserEmail,
      agent_id: agentSelectValue,
    };
    const reseponse = await fetchOldChats(data);
    const oldChats = reseponse;
    let temp = [];
    for (let key in oldChats) {
      temp.push({ ...oldChats[key][0], session_id: key, messageCount: oldChats[key].length });
    }
    setOldChats(temp);
  };

  const handleChatDeleted = (deletedSessionId) => {
    setIsDeletingChat(true);
    setShowToast(false);
    
    setOldChats(prev => prev.filter(chat => chat.session_id !== deletedSessionId));
    
    if ((oldSessionId !== "" ? oldSessionId : session) === deletedSessionId) {
      setOldSessionId("");
      setMessageData([]);
    }
    
    setTimeout(() => {
      fetchOldChatsData();
    }, 100);
    
    setTimeout(() => {
      setIsDeletingChat(false);
      setShowToast(false);
    }, 2000);
  };

  const handleChatSelected = (sessionId) => {
    setOldSessionId(sessionId);
    fetchChatHistory(sessionId);
    setShowChatHistory(false);
  };
  const [knowledgeResponse, serKnowledgeResponse] = useState([])
  const knowledgeBaseData = async () => {
    try {
      const url = `${BASE_URL}${APIs.KB_LIST}`;
      const response = await axios.request({
        method: "GET",
        url: url,
        headers: {
          "Content-Type": "application/json",
          "csrf-token": getCsrfToken(),
          "session-id": getSessionId(),
        },
      });
          serKnowledgeResponse(response?.data?.knowledge_bases || []);
    } catch (error) {
      console.error('Error fetching knowledge base data:', error);
      serKnowledgeResponse([]);
    }
  };

  const handleNewChat = async () => {
    const sessionId = await fetchNewChats(loggedInUserEmail);
    fetchOldChatsData();
    setOldSessionId("");
    setSessionId(sessionId);
    fetchChatHistory(sessionId);
  };

  const handleAgentDropdownKeyDown = (e) => {
    if (!showAgentDropdown) return;

    switch (e.key) {
      case 'ArrowDown':
        e.preventDefault();
        setHighlightedAgentIndex(prev => {
          const newIndex = prev < filteredAgents.length - 1 ? prev + 1 : 0;
          scrollToHighlightedItem(newIndex);
          return newIndex;
        });
        break;
      case 'ArrowUp':
        e.preventDefault();
        setHighlightedAgentIndex(prev => {
          const newIndex = prev > 0 ? prev - 1 : filteredAgents.length - 1;
          scrollToHighlightedItem(newIndex);
          return newIndex;
        });
        break;
      case 'Enter':
        e.preventDefault();
        if (highlightedAgentIndex >= 0 && filteredAgents[highlightedAgentIndex]) {
          selectAgent(filteredAgents[highlightedAgentIndex]);
          setAgentSelectValue(filteredAgents[highlightedAgentIndex].agentic_application_id);
          setFeedback("");
          setOldSessionId("");
          setLikeIcon(false);
        }
        break;
      case 'Escape':
        e.preventDefault();
        closeAgentDropdown();
        break;
      case 'Tab':
        if (!e.shiftKey && highlightedAgentIndex >= 0 && filteredAgents[highlightedAgentIndex]) {
          e.preventDefault();
          selectAgent(filteredAgents[highlightedAgentIndex]);
          setAgentSelectValue(filteredAgents[highlightedAgentIndex].agentic_application_id);
          setFeedback("");
          setOldSessionId("");
          setLikeIcon(false);
        }
        break;
    }
  };

  const scrollToHighlightedItem = (index) => {
    if (agentListRef.current && index >= 0) {
      const items = agentListRef.current.children;
      if (items[index]) {
        items[index].scrollIntoView({
          behavior: 'smooth',
          block: 'nearest',
        });
      }
    }
  };

  const textareaRef = useRef(null);
  const resetHeight = () => {
    const textarea = textareaRef.current;
    if (textarea) {
      textarea.style.height = "40px";
    }
  };

  const calculateHeight = () => {
    const textarea = textareaRef.current;
    if (textarea) {
      textarea.style.height = "20px";
      const maxHeight = 144;
      const newHeight = Math.min(textarea.scrollHeight, maxHeight);
      textarea.style.height = `${newHeight}px`;
    }
  };
  const handleChange = (e) => {
    setUserChat(e.target.value);
    calculateHeight();
  };

  const handleFileClick = () => {
    showComponent(<div>Your file content here</div>);
  };

  const handleToolInterrupt = (isEnabled) => {
    setToolInterrupt(isEnabled);
    setIsTool(isEnabled);
  };

  let fieldData = messageData?.map((item, index) => {
    return <>{item?.message}</>;
  });
  const [selectedValues, setSelectedValues] = useState([]);
  const handleCheckboxChange = (e) => {
    const value = e.target.value;
    const isChecked = e.target.checked;
    if (isChecked) {
      setSelectedValues((prevValues) => [...prevValues, value]); // Add value if checked
    } else {
      setSelectedValues((prevValues) => prevValues.filter(item => item !== value)); // Remove if unchecked
    }
    if (isChecked) {
    } else {
    }
  };
  const [searchTerm, setSearchTerm] = useState("");
  const handleSearchChange = (e) => {
    setSearchTerm(e.target.value);
  };
  const highlightText = (text) => {
    if (!searchTerm) return text;

    const parts = text.split(new RegExp(`(${searchTerm})`, "gi"));
    return parts.map((part, index) =>
      part.toLowerCase() === searchTerm.toLowerCase() ? (
        <span key={index} style={{ color: "#0078d4" }}>
          {part}
        </span>
      ) : (
        part
      )
    );
  };
  return (
    <>
    <div className={styles.container} ref={chatbotContainerRef}>
      <div className={stylesNew.chatWrapper}>
        <div className={stylesNew.bubbleAndInput}>
          <div className={stylesNew.chatBubblesWrapper}>
            <div className={stylesNew.messagesWrapper}>
              {/* message container */}{" "}
              {/* <div className={stylesNew.messagesContainer} ref={msgContainerRef}> */}
                {showToast && !showChatHistory && !isDeletingChat && (
                  <ToastMessage
                    message={lastResponse === null ? "Internal Server error" : likeMessage}
                    showToast={showToast}
                    setShowToast={setShowToast}
                  />
                )}
                {/* {(lastResponse === null) &&(
                  <ToastMessage
                    message={"Internal Server error"}
                    showToast={showToast}
                    setShowToast={setShowToast}
                  />
                )} */}

                <MsgBox
                  styles={styles}
                  messageData={messageData}
                  generating={generating}
                  agentType={agentType}
                  feedBack={feedBack}
                  setFeedback={setFeedback}
                  setMessageData={setMessageData}
                  agentSelectValue={agentSelectValue}
                  model={model}
                  fetching={fetching}
                  setFetching={setFetching}
                  showToast={showToast}
                  setShowToast={setShowToast}
                  isHuman={isHuman}
                  planData={planData}
                  sendHumanInLoop={sendHumanInLoop}
                  showInput={showInput}
                  setShowInput={setShowInput}
                  isPlanVerifierOn={isPlanVerifierOn}
                  setIsHuman={setIsHuman}
                  lastResponse={lastResponse}
                  setIsTool={setIsTool}
                  isTool={isTool}
                  selectedOption={agentType}
                  toolInterrupt={toolInterrupt}
                  handleToolInterrupt={handleToolInterrupt}
                  handleHumanInLoop={handleHumanInLoop}
                  oldSessionId={oldSessionId}
                  setOldSessionId={setOldSessionId}
                  session={session}
                  likeIcon={likeIcon}
                  setLikeIcon={setLikeIcon}
                  setGenerating={setGenerating}
                  showInputSendIcon={showInputSendIcon}
                  setShowInputSendIcon={setShowInputSendIcon}
                  messageDisable={messageDisable}
                  isEditable={isEditable}
                  setIsEditable={setIsEditable}
                  allOptionsSelected={allOptionsSelected}
                  oldChats={oldChats}
                  isDeletingChat={isDeletingChat}
                />
            </div>
          </div>
          <div className={styles.chatSection}>
            <div className={chatInputModule.container}>
              <div className={chatInputModule.topControls}>
                <div className={chatInputModule.controlGroup}>
                  <select
                    className={chatInputModule.select}
                    value={agentType}
                    onChange={(e) => handleTypeChange(e.target.value)}
                    disabled={generating || fetching || isEditable}
                  >
                    <option value="">Select Agent Type</option>
                    {agentTypesDropdown.map((option) => (
                      <option key={option.value} value={option.value}>
                        {option.label}
                      </option>
                    ))}
                  </select>
                </div>

                <div className={chatInputModule.controlGroup}>
                  <select
                    className={chatInputModule.select}
                    value={model}
                    onChange={(selectedOption) => {
                      setModel(selectedOption.target.value);
                      setLikeIcon(false);
                    }}
                    disabled={generating || fetching || isEditable}
                  >
                    <option value="">Select Model</option>
                    {selectedModels.map((modelOption) => (
                      <option key={modelOption.value} value={modelOption.value}>
                        {modelOption.value}
                      </option>
                    ))}
                  </select>
                </div>
                <div className={chatInputModule.controlGroup} ref={agentDropdownRef}>
                  <div className={`${chatInputModule.searchableDropdown} ${(messageDisable || fetching || generating || isEditable) ? chatInputModule.disabled : ''}`} aria-disabled={(messageDisable || fetching || generating || isEditable)}>
                    <div
                      ref={agentTriggerRef}
                      className={`${chatInputModule.dropdownTrigger} ${showAgentDropdown ? chatInputModule.active : ''} ${(messageDisable || fetching || generating || isEditable) ? chatInputModule.disabled : ''}`}
                      onClick={!(messageDisable || fetching || generating || isEditable) ? handleAgentDropdownToggle : undefined}
                      onKeyDown={(e) => {
                        if ((messageDisable || fetching || generating || isEditable)) return;
                        if (e.key === 'Enter' || e.key === ' ') {
                          e.preventDefault();
                          handleAgentDropdownToggle();
                        } else if (e.key === 'ArrowDown') {
                          e.preventDefault();
                          if (!showAgentDropdown) {
                            setShowAgentDropdown(true);
                            setHighlightedAgentIndex(0);
                          } else {
                            handleAgentDropdownKeyDown(e);
                          }
                        } else if (e.key === 'ArrowUp') {
                          e.preventDefault();
                          if (showAgentDropdown) {
                            handleAgentDropdownKeyDown(e);
                          }
                        } else if (showAgentDropdown) {
                          handleAgentDropdownKeyDown(e);
                        }
                      }}
                      tabIndex={(messageDisable || fetching || generating || isEditable) ? -1 : 0}
                      role="combobox"
                      aria-expanded={showAgentDropdown}
                      aria-haspopup="listbox"
                      aria-label="Select Agent"
                      aria-disabled={(messageDisable || fetching || generating || isEditable)}
                    >
                      <span>{selectedAgent.agentic_application_name || "Select Agent"}</span>
                      <svg width="18" height="18" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg" className={`${chatInputModule.chevronIcon} ${showAgentDropdown ? chatInputModule.rotated : ''}`}>
                        <path d="M6 8L10 12L14 8" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
                      </svg>
                    </div>

                    {showAgentDropdown && (
                      <div
                        className={chatInputModule.dropdownContent}
                        role="listbox"
                        aria-label="Agent options"
                        onClick={(e) => e.stopPropagation()}
                      >
                        <div className={chatInputModule.searchContainer}>
                          <svg width="18" height="18" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg" className={chatInputModule.searchIcon}>
                            <circle cx="9" cy="9" r="6" stroke="currentColor" strokeWidth="1.5" fill="none"/>
                            <path d="m15 15 4 4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/>
                          </svg>
                          <input
                            ref={agentSearchInputRef}
                            type="text"
                            placeholder="Search agents..."
                            value={agentSearchTerm}
                            onChange={(e) => {
                              const newSearchTerm = e.target.value;
                              setAgentSearchTerm(newSearchTerm);
                              // Reset highlight when searching
                              setHighlightedAgentIndex(newSearchTerm === '' ? -1 : 0);
                            }}
                            onKeyDown={handleAgentDropdownKeyDown}
                            className={chatInputModule.searchInput}
                            aria-label="Search agents"
                            autoComplete="off"
                          />
                        </div>
                        <div className={chatInputModule.agentsList} ref={agentListRef}>
                          {filteredAgents.length > 0 ? (
                            filteredAgents.map((agent, index) => (
                              <div
                                key={agent.agentic_application_id}
                                className={`${chatInputModule.agentItem} ${index === highlightedAgentIndex ? chatInputModule.highlighted : ''}`}
                                onClick={() => {
                                  selectAgent(agent);
                                  setAgentSelectValue(agent.agentic_application_id);
                                  setFeedback("");
                                  setOldSessionId("");
                                  setLikeIcon(false);
                                }}
                                onMouseEnter={() => setHighlightedAgentIndex(index)}
                                onMouseLeave={() => setHighlightedAgentIndex(-1)}
                                role="option"
                                aria-selected={index === highlightedAgentIndex}
                              >
                                <div className={chatInputModule.agentName}>{agent.agentic_application_name}</div>
                              </div>
                            ))
                          ) : (
                            <div className={chatInputModule.noAgents}>No agents found</div>
                          )}
                        </div>
                      </div>
                    )}
                  </div>
                </div>
              </div>
              {!allOptionsSelected && <div className={chatInputModule.inputsWrapperRow2}>
                <div className={chatInputModule.inputForm}>
                  <div className={chatInputModule.inputContainer}>
                    <button
                      type="button"
                      className={chatInputModule.inputButton}
                      onClick={handleFileClick}
                      disabled={messageDisable || fetching || generating || isEditable || allOptionsSelected}
                      title="Upload Files"
                      tabIndex={0}
                    >
                      <svg width="18" height="18" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg">
  <path d="M10 13V3" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
  <path d="M7 6L10 3L13 6" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
  <rect x="4" y="15" width="12" height="2" rx="1" stroke="currentColor" strokeWidth="1.5"/>
</svg>

                    </button>
                    <div className={chatInputModule.textInputWrapper}>
                      <textarea
                        ref={textareaRef}
                        value={userChat}
                        onChange={handleChange}
                        onKeyDown={handleKeyDown}
                        placeholder={
                          !allOptionsSelected
                            ? "Type your message..."
                            : "Please select Agent Type, Model, and Agent to start chatting"
                        }
                        disabled={generating || allOptionsSelected || fetching || feedBack === dislike || isEditable || messageDisable}
                        className={chatInputModule.textInput}
                        rows={1}
                      />
                    </div>

                    <div className={chatInputModule.rightButtons}>
                      <button
                        type="submit"
                        onClick={sendUserMessage}
                        className={`${chatInputModule.inputButton} ${chatInputModule.sendButton}`}
                        disabled={allOptionsSelected || generating || !userChat.trim()}
                        title="Send Message"
                        tabIndex={0}
                      >
                        <svg width="18" height="18" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg">
                          <path d="M3 17L17 10L3 3V8L13 10L3 12V17Z" fill="currentColor" />
                        </svg>
                      </button>
                    </div>
                  </div>
                </div>
                <div className={chatInputModule.actionButtons}>

                  <div className={chatInputModule.settingsContainer} ref={settingsRef}>
                    <button
                      className={`${chatInputModule.actionButton} ${showSettings ? chatInputModule.active : ''}`}
                      onClick={() => setShowSettings(!showSettings)}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter' || e.key === ' ') {
                          e.preventDefault();
                          setShowSettings(!showSettings);
                        } else if (e.key === 'ArrowDown' && !showSettings) {
                          e.preventDefault();
                          setShowSettings(true);
                        }
                      }}
                      title="Settings"
                      tabIndex={generating ? -1 : 0}

                      disabled={allOptionsSelected || generating}
                      aria-expanded={showSettings}
                      aria-haspopup="menu"
                      aria-label="Settings menu"
                      aria-disabled={generating}
                    >
                      <svg width="18" height="18" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg">
                        <rect x="4" y="7" width="12" height="6" rx="3" stroke="currentColor" strokeWidth="1.5" />
                        <circle cx="13" cy="10" r="2" fill="currentColor" />

                      </svg>
                    </button>
                    {showSettings && (
                      <div
                        className={chatInputModule.settingsDropdown}
                        onKeyDown={handleSettingsKeyDown}
                        role="menu"
                        aria-label="Settings menu"
                      >
                        <div className={chatInputModule.settingsHeader}>Verifier Settings</div>

                        {shouldShowHumanVerifier() && (
                          <div className={chatInputModule.toggleGroup + " plan-verifier"} role="menuitem">
                            <label className={chatInputModule.toggleLabel}>
                              <span className={chatInputModule.toggleText} id="humanVerifierLabel">Plan Verifier</span>
                              <input
                                type="checkbox"
                                checked={isHuman}
                                onChange={(e) => handleHumanInLoop(e.target.checked)}
                                className={chatInputModule.toggleInput}
                                id="humanVerifierToggle"
                                disabled={messageDisable || generating || fetching || isEditable}
                              />
                              <span
                                className={chatInputModule.toggleSlider}
                                tabIndex={0}
                                role="switch"
                                aria-checked={isHuman}
                                aria-labelledby="humanVerifierLabel"
                                onKeyDown={(e) => handleToggleKeyDown(e, handleHumanInLoop, isHuman)}
                              ></span>
                            </label>
                          </div>
                        )}

                        {shouldShowToolVerifier() && (
                          <div className={chatInputModule.toggleGroup + " tool-verifier"} role="menuitem">
                            <label className={chatInputModule.toggleLabel}>
                              <span className={chatInputModule.toggleText} id="toolVerifierLabel">Tool Verifier</span>
                              <input
                                type="checkbox"
                                checked={toolInterrupt}
                                onChange={(e) => handleToolInterrupt(e.target.checked)}
                                className={chatInputModule.toggleInput}
                                id="toolVerifierToggle"
                                disabled={messageDisable || generating || fetching || isEditable}
                              />
                              <span
                                className={chatInputModule.toggleSlider}
                                tabIndex={0}
                                role="switch"
                                aria-checked={toolInterrupt}
                                aria-labelledby="toolVerifierLabel"
                                onKeyDown={(e) => handleToggleKeyDown(e, handleToolInterrupt, toolInterrupt)}
                              ></span>
                            </label>
                          </div>
                        )}
                      </div>
                    )}
                  </div>

                  {agentType === REACT_AGENT && (
                    <div className={chatInputModule.relativeWrapper} ref={knowledgePopoverRef}>
                      <button
                        className={chatInputModule.actionButton}
                        onClick={async () => {
                          const newState = !showKnowledgePopover;
                          setShowKnowledgePopover(newState);
                          if (newState && (!knowledgeResponse || knowledgeResponse.length === 0)) {
                            await knowledgeBaseData();
                          }
                        }}
                        title="Knowledge Base"
                        tabIndex={0}
                        aria-haspopup="listbox"
                        aria-expanded={showKnowledgePopover}
                        disabled={allOptionsSelected || generating || fetching || isEditable}
                      >
                        <svg width="64" height="64" viewBox="0 0 64 64" fill="none" xmlns="http://www.w3.org/2000/svg">
                          <circle cx="32" cy="18" r="5.5" fill="currentColor" />
                                                    <path
                            d="M16 32
                              C16 28, 24 28, 32 32
                              C40 28, 48 28, 48 32
                              V48
                              C48 44, 40 44, 32 48
                              C24 44, 16 44, 16 48
                              V32Z"
                            stroke="currentColor"
                            strokeWidth="2"
                            fill="none"
                          />
                          
                          <line x1="32" y1="32" x2="32" y2="48" stroke="currentColor" strokeWidth="1.5" />
                          
                          <line x1="19" y1="33" x2="19" y2="47" stroke="currentColor" strokeWidth="0.8" />
                          <line x1="22" y1="34" x2="22" y2="46" stroke="currentColor" strokeWidth="0.8" />
                          <line x1="25" y1="35" x2="25" y2="45" stroke="currentColor" strokeWidth="0.8" />
                          <line x1="28" y1="36" x2="28" y2="44" stroke="currentColor" strokeWidth="0.8" />
                          
                          <line x1="36" y1="36" x2="36" y2="44" stroke="currentColor" strokeWidth="0.8" />
                          <line x1="39" y1="35" x2="39" y2="45" stroke="currentColor" strokeWidth="0.8" />
                          <line x1="42" y1="34" x2="42" y2="46" stroke="currentColor" strokeWidth="0.8" />
                          <line x1="45" y1="33" x2="45" y2="47" stroke="currentColor" strokeWidth="0.8" />
                          
                          <path d="M19 33C19 33 25 31 32 33C39 31 45 33 45 33" stroke="currentColor" strokeWidth="1" />
                        </svg>
                      </button>
                      {showKnowledgePopover && (
                        <div className={chatInputModule.dropdownContent} role="listbox" aria-label="Knowledge Base options" style={{ minWidth: 220, maxWidth: 260 }}>
                          <div className={chatInputModule.searchContainer} style={{ padding: '8px 8px 4px 8px' }}>
                            <svg width="18" height="18" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg" className={chatInputModule.searchIcon}>
                              <circle cx="9" cy="9" r="6" stroke="currentColor" strokeWidth="1.5" fill="none"/>
                              <path d="m15 15 4 4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/>
                            </svg>
                            <input
                              type="text"
                              placeholder="Search knowledge base..."
                              value={searchTerm}
                              onChange={handleSearchChange}
                              className={chatInputModule.searchInput}
                              aria-label="Search knowledge base"
                              autoComplete="off"
                            />
                          </div>
                          <div className={chatInputModule.agentsList} style={{ maxHeight: 160, overflowY: 'auto', padding: '4px 8px' }}>
                            {Array.isArray(knowledgeResponse) && knowledgeResponse.length > 0 ? (
                              knowledgeResponse
                                .filter(option => option.toLowerCase().includes(searchTerm.toLowerCase()))
                                .map((option, idx) => (
                                  <div key={idx} className={chatInputModule.agentItem} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                                    <input
                                      type="checkbox"
                                      id={`kb-checkbox-${idx}`}
                                      value={option}
                                      checked={selectedValues.includes(option)}
                                      onChange={handleCheckboxChange}
                                      // className={chatInputModule.toggInput}
                                      style={{ marginRight: 6 }}
                                    />
                                    <label htmlFor={`kb-checkbox-${idx}`} className={chatInputModule.agentName} style={{ fontSize: 13, fontWeight: 500, cursor: 'pointer' }}>
                                      {option}
                                    </label>
                                  </div>
                                ))
                            ) : (
                              <div className={chatInputModule.noAgents}>No knowledge base found</div>
                            )}
                          </div>
                        </div>
                      )}
                    </div>
                  )}

                  <button
                    className={chatInputModule.actionButton}
                    onClick={() => setShowChatHistory(true)}
                    title="Chat History"
                    tabIndex={0}
                    disabled={allOptionsSelected || generating || fetching || isEditable}
                  >
                    <svg width="18" height="18" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg">
                      <rect x="3" y="3" width="14" height="11" rx="2" stroke="currentColor" strokeWidth="1.5" />
                      <path d="M6 7H11" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
                      <path d="M6 9H14" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
                      <path d="M6 11H10" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
        
                      <g transform="translate(1.1, 0)">
                        <circle cx="14" cy="16" r="3" stroke="currentColor" strokeWidth="1.5" fill="none" />
                        <path d="M14 14V16L15.5 17.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
        
                      </g>
                    </svg>
                  </button>

                  <button
                    className={chatInputModule.actionButton}
                    onClick={handleNewChat}
                    title="New Chat"
                    tabIndex={0}
                    disabled={allOptionsSelected || generating || fetching || isEditable || messageData.length === 0}
                  >
                    <svg width="20" height="20" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg">
                      <path d="M3 6C3 4.34315 4.34315 3 6 3H14C15.6569 3 17 4.34315 17 6V11C17 12.6569 15.6569 14 14 14H8L5 17V6Z"
                        stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
                      <g transform="translate(11, 8.5)">
                        <path d="M0 -2.5V2.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
                        <path d="M-2.5 0H2.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
                      </g>
                    </svg>
        
                  </button>

                  <button
                    className={chatInputModule.actionButton}
                    onClick={(e) => {
                      if (
                        allOptionsSelected ||
                        fetching ||
                        messageData.length === 0
                      ) {
                        e.preventDefault();
                        return;
                      }
                      handleResetChat();
                    }}
                    title="Delete Chat"
                    tabIndex={0}
                    disabled={allOptionsSelected || generating || fetching || isEditable || messageData.length === 0}
                  >
                    <svg width="18" height="18" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg">
                      <path d="M7 4V3C7 2.44772 7.44772 2 8 2H12C12.5523 2 13 2.44772 13 3V4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
                      <path d="M5 4H15" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
                      <path d="M6 4V16C6 17.1046 6.89543 18 8 18H12C13.1046 18 14 17.1046 14 16V4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
                      <path d="M8 8V14" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
                      <path d="M12 8V14" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
                    </svg>
                  </button>

                  <button
                    className={chatInputModule.actionButton}
                    onClick={handleLiveTracking}
                    title="Live Tracking"
                    tabIndex={0}
                    disabled={allOptionsSelected || generating || fetching || isEditable}
                  >
                    <svg width="18" height="18" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg">
                      <circle cx="10" cy="6" r="3" stroke="currentColor" strokeWidth="1.5" fill="none" />
                      <circle cx="10" cy="6" r="1" stroke="currentColor" strokeWidth="1" fill="none" opacity="0.4" />
                      <path d="M10 9L10 13" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
                      <path d="M6 15L10 13L14 15" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
                      <circle cx="4" cy="4" r="1.5" stroke="currentColor" strokeWidth="1" fill="none" opacity="0.6" />
                      <circle cx="16" cy="5" r="1" stroke="currentColor" strokeWidth="1" fill="none" opacity="0.4" />
                      <circle cx="15" cy="15" r="1.5" stroke="currentColor" strokeWidth="1" fill="none" opacity="0.5" />
                      <rect x="2" y="17" width="16" height="1.5" rx="0.75" fill="currentColor" opacity="0.3" />
                    </svg>
                  </button>
                </div>
              </div>}
            </div>
            {showChatHistory && (
              <ChatHistorySlider
                chats={oldChats}
                onClose={() => setShowChatHistory(false)}
                fetchChatHistory={fetchChatHistory}
                setOldSessionId={setOldSessionId}
                agentSelectValue={agentSelectValue}
                agentType={agentType}
                customTemplatId={customTemplatId}
                onChatDeleted={handleChatDeleted}
                onSelectChat={handleChatSelected}
              />
            )}
          </div>
        </div>
      </div>
    </div>
    </>
  );
};

export default AskAssistant;
