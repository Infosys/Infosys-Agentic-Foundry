import { useEffect, useRef, useState } from "react";
import Cookies from "js-cookie";
import {
  BOT,
  agentTypesDropdown,
  USER,
  APIs,
  dislike,
  branchInteruptValue,
  branchInteruptKey,
  CUSTOM_TEMPLATE,
  MULTI_AGENT,
  REACT_AGENT,
  customTemplatId,
  META_AGENT,
  PLANNER_META_AGENT,
  liveTrackingUrl,
  REACT_CRITIC_AGENT,
  PLANNER_EXECUTOR_AGENT,
  HYBRID_AGENT
} from "../../constant";
import { useChatServices } from "../../services/chatService";
import useFetch from "../../Hooks/useAxios";
import { useGlobalComponent } from "../../Hooks/GlobalComponentContext.js";
import SVGIcons from "../../Icons/SVGIcons";

// Components
import MsgBox from "./MsgBox";
import ChatHistorySlider from "./ChatHistorySlider";
import PromptSuggestions from "./PromptSuggestions";
import SuggestionPopover from "./SuggestionPopover";
import Canvas from "../Canvas/Canvas";
import TemperatureSliderPopup from "./TemperatureSliderPopup.jsx";

// Styles
import stylesNew from "./AskAssistant.module.css";
import chatInputModule from "./ChatInput.module.css";
import "./TemperatureSlider.css";

// Constants
const TEXTAREA_MAX_HEIGHT = 120; // Maximum height for textarea in pixels
const TEMPERATURE_MAX_PERCENT = 100; // Maximum percentage for temperature slider
const AUTO_HIDE_TIMEOUT = 5000; // Timeout for auto-hiding messages (5 seconds)
const DEBOUNCE_DELAY = 100; // Delay for debounce operations
const STATE_UPDATE_DELAY = 2000; // Delay for state updates

const AskAssistant = () => {
  const loggedInUserEmail = Cookies.get("email");
  const user_session = Cookies.get("user_session");
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
  const [showModelPopover, setShowModelPopover] = useState(false);
  const [toolData, setToolData] = useState(null);
  const [loadingAgents, setLoadingAgents] = useState(false);
  const [showToast, setShowToast] = useState(false);
  const [toastMessage, setToastMessage] = useState("");
  const [isDeletingChat, setIsDeletingChat] = useState(false);
  const [planData, setPlanData] = useState(null);
  const [showInput, setShowInput] = useState(false);
  const [oldChats, setOldChats] = useState([]);
  const [oldSessionId, setOldSessionId] = useState("");
  const [session, setSessionId] = useState(user_session);
  const [selectedModels, setSelectedModels] = useState([]);
  const [toolInterrupt, setToolInterrupt] = useState(false);
  const [isEditable, setIsEditable] = useState(false);
  const bullseyeRef = useRef(null);
  const { resetChat, getChatQueryResponse, getChatHistory, fetchOldChats, fetchNewChats, getQuerySuggestions, setSseMessageCallback } = useChatServices();

  const chatbotContainerRef = useRef(null);
  const [likeIcon, setLikeIcon] = useState(false);
  const [showInputSendIcon, setShowInputSendIcon] = useState(false);
  const [isOldChatOpen, setIsOldChatOpen] = useState(false);
  const [isKnowledgeOpen, setIsKnowledgeOpen] = useState(false);
  // Knowledge base popover state
  const [showKnowledgePopover, setShowKnowledgePopover] = useState(false);
  const [showVerifierSettings, setShowVerifierSettings] = useState(false);
  const [showChatSettings, setShowChatSettings] = useState(false);

  const [agentSearchTerm, setAgentSearchTerm] = useState("");
  const [showAgentDropdown, setShowAgentDropdown] = useState(false);
  const [highlightedAgentIndex, setHighlightedAgentIndex] = useState(-1);
  const [selectedAgent, setSelectedAgent] = useState("");
  const [isHumanVerifierEnabled, setIsHumanVerifierEnabled] = useState(false);
  const [isToolVerifierEnabled, setIsToolVerifierEnabled] = useState(false);
  const [isCanvasEnabled, setIsCanvasEnabled] = useState(true);
  const [isContextEnabled, setIsContextEnabled] = useState(true);
  const [showChatHistory, setShowChatHistory] = useState(false);
  const [isListening, setIsListening] = useState(false);
  const [recording, setRecording] = useState(false);
  const [transcription, setTranscription] = useState("");
  const mediaRecorder = useRef(null);
  const audioChunks = useRef([]);
  const mediaStream = useRef(null);

  // Canvas states
  const [isCanvasOpen, setIsCanvasOpen] = useState(false);
  const [canvasContent, setCanvasContent] = useState(null);
  const [canvasTitle, setCanvasTitle] = useState("Code View");
  const [canvasContentType, setCanvasContentType] = useState("");
  const [canvasMessageId, setCanvasMessageId] = useState(null);
  const [canvasIsLast, setCanvasIsLast] = useState(false);

  const [showPromptSuggestions, setShowPromptSuggestions] = useState(false);
  const [promptSuggestions, setPromptSuggestions] = useState([]);

  const [highlightedKbIndex, setHighlightedKbIndex] = useState(-1);

  const verifierSettingsRef = useRef(null);
  const chatSettingsRef = useRef(null);
  const agentTriggerRef = useRef(null);
  const agentSearchInputRef = useRef(null);
  const agentDropdownRef = useRef(null);
  const agentListRef = useRef(null);
  const knowledgePopoverRef = useRef(null);
  const knowledgeSearchInputRef = useRef(null);
  const knowledgeListRef = useRef(null);
  const suggestionPopoverRef = useRef(null);

  const [cachedSuggestions, setCachedSuggestions] = useState({
    user_history: [],
    agent_history: [],
  });

  const [temperature, setTemperature] = useState(0.0);
  const [showTemperaturePopup, setShowTemperaturePopup] = useState(false);
  const temperaturePopupRef = useRef(null);
  const temperatureSliderRef = useRef(null);
  // Close temperature popup on outside click
  useEffect(() => {
    function handleClickOutside(event) {
      if (temperaturePopupRef.current && !temperaturePopupRef.current.contains(event.target)) {
        setShowTemperaturePopup(false);
      }
    }
    if (showTemperaturePopup) {
      document.addEventListener("mousedown", handleClickOutside);
    }
    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
    };
  }, [showTemperaturePopup]);

  const messageDisable = messageData.some((msg) => typeof msg?.message === "string" && msg.message.trim() === "");
  const startRecording = async () => {
    try {
      // Reset audio chunks for new recording
      audioChunks.current = [];

      // Get user media stream
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          sampleRate: 44100,
        },
      });

      // Store the stream reference
      mediaStream.current = stream;

      // Create MediaRecorder instance
      mediaRecorder.current = new MediaRecorder(stream, {
        mimeType: "audio/webm;codecs=opus",
      });

      // Handle data available event
      mediaRecorder.current.ondataavailable = (event) => {
        if (event.data.size > 0) {
          audioChunks.current.push(event.data);
        }
      };

      // Handle recording stop event
      mediaRecorder.current.onstop = () => {
        // Create blob from audio chunks
        const audioBlob = new Blob(audioChunks.current, {
          type: "audio/webm;codecs=opus",
        });

        // Send to transcription service
        sendAudioForTranscription(audioBlob);

        // Clean up stream
        if (mediaStream.current) {
          mediaStream.current.getTracks().forEach((track) => track.stop());
          mediaStream.current = null;
        }
      };

      // Start recording
      mediaRecorder.current.start();
      setRecording(true);
    } catch (error) {
      console.error("Error starting recording:", error);
      setRecording(false);
    }
  };

  const stopRecording = async () => {
    if (mediaRecorder.current && mediaRecorder.current.state === "recording") {
      mediaRecorder.current.stop();
      setRecording(false);
    }
  };

  const sendAudioForTranscription = async (audioBlob) => {
    // Convert webm to wav if needed by backend
    const formData = new FormData();
    formData.append("file", audioBlob, "recording.webm");

    try {
      const data = await postData(APIs.TRANSCRIBE_AUDIO, formData);

      // Update the chat input with transcription
      if (data && data.transcription) {
        setUserChat((prev) => prev + data.transcription);
        setTranscription(data.transcription);
      }
    } catch (error) {
      console.error("Transcription failed:", error);
      setTranscription("Error transcribing audio.");
    }
  };

  const handlePromptSuggestionsToggle = () => {
    setShowPromptSuggestions(!showPromptSuggestions);
  };

  const handlePromptSelect = (prompt) => {
    setUserChat(prompt);
    calculateHeight();
  };

  const shouldShowHumanVerifier = () => {
    return agentType === MULTI_AGENT || agentType === PLANNER_EXECUTOR_AGENT || agentType === "multi_agent" || agentType === HYBRID_AGENT;
  };

  const handleLiveTracking = () => {
    window.open(liveTrackingUrl, "_blank");
  };

  const selectAgent = (agent) => {
    closeCanvas(); // Close canvas on agent change
    setSelectedAgent(agent);
    closeAgentDropdown();
  };

  const shouldShowToolVerifier = () => {
    return agentType === REACT_AGENT || agentType === MULTI_AGENT || agentType === REACT_CRITIC_AGENT || agentType === PLANNER_EXECUTOR_AGENT || agentType === "react_agent" || agentType === HYBRID_AGENT;
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

  const handleCanvasToggle = (checked) => {
    setIsCanvasEnabled(checked);
    // If disabling canvas and it's currently open, close it
    if (!checked && isCanvasOpen) {
      closeCanvas();
    }
  };

  const handleContextToggle = (checked) => {
    setIsContextEnabled(checked);
  };

  const handleToolInterrupt = (isEnabled) => {
    setToolInterrupt(isEnabled);
    setIsTool(isEnabled);
  };

  const handleIconClick = () => {
    setShowVerifierSettings((prev) => !prev);
  };
  const oldChatRef = useRef(null);
  const knowledgeRef = useRef(null);
  const toggleDropdown = () => {
    setIsOldChatOpen((prev) => !prev);
  };
  const toggleKnowledge = async () => {
    const newState = !isKnowledgeOpen;
    setIsKnowledgeOpen(newState);
    if (newState && (!knowledgeResponse || knowledgeResponse.length === 0)) {
      await knowledgeBaseData();
    }
  };
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

  const allOptionsSelected = agentType !== CUSTOM_TEMPLATE ? agentType === "" || model === "" || agentSelectValue === "" : agentType === "" || model === "";

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

  // Cleanup media streams on component unmount
  useEffect(() => {
    return () => {
      // Clean up any active recording when component unmounts
      if (mediaRecorder.current && mediaRecorder.current.state === "recording") {
        mediaRecorder.current.stop();
      }
      if (mediaStream.current) {
        mediaStream.current.getTracks().forEach((track) => track.stop());
      }
    };
  }, []);

  const filteredAgents = agentListDropdown.filter((agent) => {
    return agent.agentic_application_name?.toLowerCase().includes(agentSearchTerm.toLowerCase());
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
    if (showKnowledgePopover && knowledgeSearchInputRef.current) {
      knowledgeSearchInputRef.current.focus();
    }
  }, [showKnowledgePopover]);

  useEffect(() => {
    // Reset previously selected agent value any time agentType changes
    setAgentSelectValue("");
    setSelectedAgent("");
    const cookieSessionId = Cookies.get("user_session");
    if (cookieSessionId) {
      setSessionId(cookieSessionId);
    }
    // If agentType cleared, also clear the dropdown list so user can't pick stale agents
    if (!agentType) {
      setAgentListDropdown([]);
      return;
    }

    const tempList = agentsListData?.filter((list) => list.agentic_application_type === agentType) || [];
    setAgentListDropdown(tempList);
  }, [agentType, agentsListData]);

  useEffect(() => {
    // Only fetch history when agent changes or options are selected, not on model change
    if (!allOptionsSelected && agentSelectValue) {
      fetchChatHistory();
      fetchOldChatsData();
    } else if (allOptionsSelected) {
      setMessageData([]);
    }
  }, [agentSelectValue, allOptionsSelected]); // Removed model from dependencies
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
      if (verifierSettingsRef.current && !verifierSettingsRef.current.contains(event.target)) {
        setShowVerifierSettings(false);
      }
      if (chatSettingsRef.current && !chatSettingsRef.current.contains(event.target)) {
        setShowChatSettings(false);
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
      textareaRef.current.style.height = "auto";
      textareaRef.current.style.height = Math.min(textareaRef.current.scrollHeight, TEXTAREA_MAX_HEIGHT) + "px";
    }
  }, [userChat]);

  // Update the temperature slider's visual state whenever temperature changes
  useEffect(() => {
    if (temperatureSliderRef.current) {
      temperatureSliderRef.current.style.setProperty("--value-percent", `${temperature * TEMPERATURE_MAX_PERCENT}%`);
    }
  }, [temperature]);

  useEffect(() => {
    const handleGlobalKeyDown = (event) => {
      if (event.key === "Escape") {
        if (showKnowledgePopover) {
          event.preventDefault();
          setShowKnowledgePopover(false);
          setSearchTerm("");
        } else if (showChatHistory) {
          event.preventDefault();
          setShowChatHistory(false);
        } else if (showVerifierSettings) {
          event.preventDefault();
          setShowVerifierSettings(false);
        } else if (showPromptSuggestions) {
          event.preventDefault();
          setShowPromptSuggestions(false);
        } else if (showChatSettings) {
          event.preventDefault();
          setShowChatSettings(false);
        }
      }
    };

    document.addEventListener("keydown", handleGlobalKeyDown);
    return () => {
      document.removeEventListener("keydown", handleGlobalKeyDown);
    };
  }, [showKnowledgePopover, showChatHistory, showVerifierSettings, showPromptSuggestions, showChatSettings]);

  const handleSettingsKeyDown = (e) => {
    if (!showVerifierSettings) return;

    switch (e.key) {
      case "Escape":
        e.preventDefault();

        if (verifierSettingsRef.current) {
          setShowVerifierSettings(false);
          const verifierSettingsButton = verifierSettingsRef.current.querySelector("button");
          if (verifierSettingsButton) verifierSettingsButton.focus();
        }
        if (chatSettingsRef.current) {
          setShowChatSettings(false);
          const chatSettingsButton = chatSettingsRef.current.querySelector("button");
          if (chatSettingsButton) chatSettingsButton.focus();
        }
        break;
    }
  };

  const handleToggleKeyDown = (e, toggleHandler, currentValue) => {
    switch (e.key) {
      case "Enter":
      case " ":
        e.preventDefault();
        toggleHandler(!currentValue);
        break;
      case "ArrowRight":
        e.preventDefault();
        if (!currentValue) toggleHandler(true);
        break;
      case "ArrowLeft":
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
    const chats = [];
    setPlanData(null);
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
        debugExecutor: item?.additional_details,
        ...(index === chatHistory?.executor_messages?.length - 1 && {
          plan: chatHistory?.plan,
        }),
        parts: item?.parts || [],
        show_canvas: item?.show_canvas || false,
        response_time: item?.response_time || null,
      });
    });
    setPlanData(chatHistory?.plan);
    setToolData(chats?.toolcallData);
    return chats;
  };

  const fetchChatHistory = async (sessionId = session) => {
    try {
      const data = {
        session_id: sessionId,
        agent_id: agentType === CUSTOM_TEMPLATE ? customTemplatId : agentSelectValue,
      };
      const chatHistory = await getChatHistory(data);
      
      if (chatHistory) {
        setLastResponse(chatHistory);
        const chatData = converToChatFormat(chatHistory) || [];
        setMessageData(chatData);
        // Update model if it's available in the chat history
        if (chatHistory.model_name) {
          setModel(chatHistory.model_name);
        }
        fetchPromptSuggestions();
      }
    } catch (error) {
      console.error("Error fetching chat history:", error);
    }

    fetchPromptSuggestions();
  };

  const fetchPromptSuggestions = async () => {
    // Fetch and cache suggestions only once per chat history fetch
    const payload = {
      agentic_application_id: agentSelectValue,
      user_email: loggedInUserEmail,
    };
    const response = await getQuerySuggestions(payload);
    if (response) {
      setCachedSuggestions({
        user_history: response.user_history || [],
        agent_history: response.agent_history || [],
      });
      if (response.query_library) {
        setPromptSuggestions(response.query_library);
      } else {
        setPromptSuggestions([]);
      }
    }
  };

  const addMessageData = (type, message, steps, plan, userText) => {
    setMessageData((prevProp) => [...prevProp, { type, message, steps, plan, userText }]);
  };

  const sendHumanInLoop = async (isApprove = "", feedBack = "", userText) => {
    const payload = {
      agentic_application_id: agentType === CUSTOM_TEMPLATE ? customTemplatId : agentSelectValue,
      query: userText,
      session_id: oldSessionId !== "" ? oldSessionId : session,
      model_name: model,
      temperature: temperature,
      reset_conversation: false,
      is_plan_approved: isApprove !== "" ? isApprove : null,
      plan_feedback: feedBack !== "" ? feedBack : null,
      tool_verifier_flag: Boolean(toolInterrupt),
      plan_verifier_flag: Boolean(isHuman),
      response_formatting_flag: Boolean(isCanvasEnabled),
      context_flag: Boolean(isContextEnabled),
      evaluation_flag: Boolean(onlineEvaluatorFlag),
    };

    if (selectedValues && selectedValues.length > 0) {
      const selectedString = selectedValues.join(",");
      payload.knowledgebase_name = JSON.stringify(selectedString);
    }
    try {
      const response = await postData(APIs.CHAT_INFERENCE, payload);
      if (response) {
        setLastResponse(response);
        setPlanData(response?.plan);

        const chatData = converToChatFormat(response) || [];
        setMessageData(chatData);

        // First check for parts format in the root response
        if (response.parts) {
          const textParts = response.parts.filter((part) => part.type === "text");
          if (textParts.length > 0) {
            // Handle text parts if needed
          }
        }

      const canvasContent = detectCanvasContent(response);
      if (response.executor_messages[response.executor_messages.length - 1].show_canvas) {
        // Only open canvas if response_formatting_flag is true
        if (payload.response_formatting_flag === true) {
          openCanvas(canvasContent.content,canvasContent.title,canvasContent.type,null,false);
        }
        }
      }
    } catch (error) {
      console.error("Error handling chat response:", error);
      setGenerating(false);
      setFetching(false);
    }
  };

  const sendUserMessage = async (overrideText) => {
    let messageToSend = "";
    let contextFlag = false;
    let responseFormattingFlag = false;
    // If overrideText is an object (from EmailViewer), extract flags and query
    if (overrideText && typeof overrideText === "object") {
      messageToSend = overrideText.query ? String(overrideText.query).trim() : "";
      contextFlag = overrideText.context_flag === true;
      responseFormattingFlag = overrideText.response_formatting_flag === true;
    } else {
      messageToSend = overrideText !== undefined ? String(overrideText).trim() : userChat.trim();
    }
    if (!messageToSend || generating) return;

    setFetching(true);
    resetHeight();

    // Clear previous debug steps
    clearDebugSteps();
    addMessageData(USER, messageToSend);
    setUserChat("");
    setGenerating(true);
    setLikeIcon(false);
    setSuggestionVisible(false);

    const payload = {
      agentic_application_id: agentType === CUSTOM_TEMPLATE ? customTemplatId : agentSelectValue,
      query: messageToSend,
      session_id: oldSessionId !== "" ? oldSessionId : session,
      model_name: model,
      temperature: temperature,
      reset_conversation: false,
      tool_verifier_flag: Boolean(toolInterrupt),
      plan_verifier_flag: Boolean(isHuman),
      response_formatting_flag: typeof overrideText === "object" ? Boolean(responseFormattingFlag) : Boolean(isCanvasEnabled),
      context_flag: typeof overrideText === "object" ? Boolean(contextFlag) : Boolean(isContextEnabled),
      evaluation_flag: Boolean(onlineEvaluatorFlag),
    };

    if (selectedValues && selectedValues.length > 0) {
      const selectedString = selectedValues.join(",");
      payload.knowledgebase_name = JSON.stringify(selectedString);
    }

    // To hide the open canvas when user sends the next query
    setIsCanvasOpen(false);

    if (isHuman) {
      await sendHumanInLoop("", "", messageToSend);
    } else {
      const response = await getChatQueryResponse(payload, APIs.CHAT_INFERENCE);
      setLastResponse(response);
      if (response === null) {
        setShowToast(true);
        setTimeout(() => {
          setShowToast(false);
        }, AUTO_HIDE_TIMEOUT);
      }

      // Call prompt suggestion API to fetch latest suggestions based on new chat history
      fetchPromptSuggestions();

      const chatData = converToChatFormat(response) || [];
      setMessageData(chatData);

      const canvasContent = detectCanvasContent(response);
      if (canvasContent) {
         if (payload.response_formatting_flag === true) {
          openCanvas(canvasContent.content,canvasContent.title,canvasContent.type,null,false);
        }
      }
      // Fallback: Auto-detect and open Canvas for individual message content
      else if (chatData.length > 0) {
        const lastMessage = chatData[chatData.length - 1];
        if (lastMessage.type === BOT && lastMessage.message) {
          const canvasContent = detectCanvasContent(lastMessage.message);
          if (canvasContent) {
             if (payload.response_formatting_flag === true) {
          openCanvas(canvasContent.content,canvasContent.title,canvasContent.type,null,false);
        }
          }
        }
      }
    }
    setGenerating(false);
    setFetching(false);
    setSelectedValues("");
  };

  const handleKeyDown = (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      sendUserMessage(event.target.value);
      resetHeight();
    } else if (event.shiftKey && event.key === "Enter") {
      event.preventDefault();
      setUserChat((prev) => prev + "\n");
      calculateHeight();
    }
  };

  const handleTypeChange = (selectedOption) => {
    closeCanvas(); // Close canvas on agent type change
    setAgentType(selectedOption);
    setLikeIcon(false);
    // Clearing model when agent type changes (including reset)
    setModel("");
    // Reset temperature to default value of 0.0
    setTemperature(0.0);
    // Ensure we use cookie session ID when changing agent type
    const cookieSessionId = Cookies.get("user_session");
    if (cookieSessionId) {
      setSessionId(cookieSessionId);
    }
    setIsPlanVerifierOn(
      selectedOption === MULTI_AGENT ||
        selectedOption === REACT_AGENT ||
        selectedOption === REACT_CRITIC_AGENT ||
        selectedOption === PLANNER_EXECUTOR_AGENT ||
      selectedOption === "react_agent"|| selectedOption === HYBRID_AGENT
    );
    if (selectedOption === CUSTOM_TEMPLATE) {
      setIsHuman(true);
    } else {
      setIsHuman(false);
    }
  };

  const handleResetChat = async () => {
    if (window.confirm("Are you sure you want to delete this chat?")) {
      clearDebugSteps();
      closeCanvas(); // Close canvas on chat delete
      const data = {
        session_id: oldSessionId !== "" ? oldSessionId : session,
        agent_id: agentType !== CUSTOM_TEMPLATE ? agentSelectValue : customTemplatId,
      };
      try {
        const response = await resetChat(data);
        if (response?.status === "success") {
          setMessageData([]);
          fetchOldChatsData();
          setOldSessionId("");
        }
      } catch (error) {
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
    const temp = [];
    for (const key in oldChats) {
      temp.push({
        ...oldChats[key][0],
        session_id: key,
        messageCount: oldChats[key].length,
      });
    }
    setOldChats(temp);
  };

  const handleChatDeleted = (deletedSessionId) => {
    setIsDeletingChat(true);
    setShowToast(false);

    setOldChats((prev) => prev.filter((chat) => chat.session_id !== deletedSessionId));

    if ((oldSessionId !== "" ? oldSessionId : session) === deletedSessionId) {
      setOldSessionId("");
      setMessageData([]);
    }

    setTimeout(() => {
      fetchOldChatsData();
    }, DEBOUNCE_DELAY);

    setTimeout(() => {
      setIsDeletingChat(false);
      setShowToast(false);
    }, STATE_UPDATE_DELAY);
  };

  const handleChatSelected = async (sessionId) => {
    clearDebugSteps();
    closeCanvas(); // Close canvas on chat select from history
    
    // First update both session IDs and wait for them to be set
    await new Promise(resolve => {
      setOldSessionId(sessionId);
      setSessionId(sessionId); // Set current session ID as well
      setTimeout(resolve, DEBOUNCE_DELAY); // Give React time to update state
    });
    
    try {
      // Then fetch chat history with the new session ID
      await fetchChatHistory(sessionId);
    } catch (error) {
      console.error("Error fetching chat history:", error);
      // Reset oldSessionId if fetching fails
      setOldSessionId("");
    }
    
    setShowChatHistory(false);
  };
  const [knowledgeResponse, serKnowledgeResponse] = useState([]);
  const knowledgeBaseData = async () => {
    try {
      const response = await fetchData(APIs.GET_KB_LIST);
      serKnowledgeResponse(response?.knowledge_bases || []);
    } catch (error) {
      console.error("Error fetching knowledge base data:", error);
      serKnowledgeResponse([]);
    }
  };

  const handleNewChat = async () => {
    clearDebugSteps();
    setShowChatSettings(false);
    closeCanvas(); // Close canvas on new chat
    const sessionId = await fetchNewChats(loggedInUserEmail);
    fetchOldChatsData();
    setOldSessionId("");
    setSessionId(sessionId);
    fetchChatHistory(sessionId);
  };

  const handleAgentDropdownKeyDown = (e) => {
    if (!showAgentDropdown) return;

    switch (e.key) {
      case "ArrowDown":
        e.preventDefault();
        setHighlightedAgentIndex((prev) => {
          const newIndex = prev < filteredAgents.length - 1 ? prev + 1 : 0;
          scrollToHighlightedItem(newIndex);
          return newIndex;
        });
        break;
      case "ArrowUp":
        e.preventDefault();
        setHighlightedAgentIndex((prev) => {
          const newIndex = prev > 0 ? prev - 1 : filteredAgents.length - 1;
          scrollToHighlightedItem(newIndex);
          return newIndex;
        });
        break;
      case "Enter":
        e.preventDefault();
        if (highlightedAgentIndex >= 0 && filteredAgents[highlightedAgentIndex]) {
          selectAgent(filteredAgents[highlightedAgentIndex]);
          setAgentSelectValue(filteredAgents[highlightedAgentIndex].agentic_application_id);
          setFeedback("");
          setOldSessionId("");
          setLikeIcon(false);
        }
        break;
      case "Escape":
        e.preventDefault();
        closeAgentDropdown();
        break;
      case "Tab":
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
          behavior: "smooth",
          block: "nearest",
        });
      }
    }
  };

  const scrollToHighlightedKbItem = (index) => {
    if (knowledgeListRef.current && index >= 0) {
      const items = knowledgeListRef.current.children;
      if (items[index]) {
        items[index].scrollIntoView({
          behavior: "smooth",
          block: "nearest",
        });
      }
    }
  };

  const handleKnowledgeDropdownKeyDown = (e) => {
    if (!showKnowledgePopover) return;

    const filteredKnowledgeOptions = Array.isArray(knowledgeResponse) ? knowledgeResponse.filter((option) => option.toLowerCase().includes(searchTerm.toLowerCase())) : [];

    switch (e.key) {
      case "ArrowDown":
        e.preventDefault();
        setHighlightedKbIndex((prev) => {
          const newIndex = prev < filteredKnowledgeOptions.length - 1 ? prev + 1 : 0;
          scrollToHighlightedKbItem(newIndex);
          return newIndex;
        });
        break;
      case "ArrowUp":
        e.preventDefault();
        setHighlightedKbIndex((prev) => {
          const newIndex = prev > 0 ? prev - 1 : filteredKnowledgeOptions.length - 1;
          scrollToHighlightedKbItem(newIndex);
          return newIndex;
        });
        break;
      case "Enter":
      case " ":
        e.preventDefault();
        if (highlightedKbIndex >= 0 && filteredKnowledgeOptions[highlightedKbIndex]) {
          const selectedOption = filteredKnowledgeOptions[highlightedKbIndex];
          const isChecked = selectedValues.includes(selectedOption);
          if (isChecked) {
            setSelectedValues((prev) => prev.filter((item) => item !== selectedOption));
          } else {
            setSelectedValues((prev) => [...prev, selectedOption]);
          }
        }
        break;
      case "Escape":
        e.preventDefault();
        setShowKnowledgePopover(false);
        setSearchTerm("");
        setHighlightedKbIndex(-1);
        break;
      default:
        break;
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

  const [selectedValues, setSelectedValues] = useState([]);
  const handleCheckboxChange = (e) => {
    const value = e.target.value;
    const isChecked = e.target.checked;
    if (isChecked) {
      setSelectedValues((prevValues) => [...prevValues, value]); // Add value if checked
    } else {
      setSelectedValues((prevValues) => prevValues.filter((item) => item !== value)); // Remove if unchecked
    }
    if (isChecked) {
    } else {
    }
  };
  const [searchTerm, setSearchTerm] = useState("");
  const handleSearchChange = (e) => {
    setSearchTerm(e.target.value);
  };

  useEffect(() => {
    const filteredKnowledgeOptions = Array.isArray(knowledgeResponse) ? knowledgeResponse.filter((option) => option.toLowerCase().includes(searchTerm.toLowerCase())) : [];
    if (searchTerm !== "" && filteredKnowledgeOptions.length > 0) {
      setHighlightedKbIndex(0);
    } else {
      setHighlightedKbIndex(-1);
    }
  }, [searchTerm, knowledgeResponse]);
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
  const [suggestionVisible, setSuggestionVisible] = useState(false);
  const [suggestionData, setSuggestionData] = useState({
    history: [],
    recommendations: [],
  });
  const handleInputChangeForSuggestion = (e) => {
    const value = e.target.value;
    setUserChat(value);
    calculateHeight();
    if (!value.trim()) {
      setSuggestionVisible(false);
      setSuggestionData({ history: [], recommendations: [] });
      return;
    }
    // Use cached suggestions for filtering
    let historyMatches = (cachedSuggestions.user_history || []).filter((item) => item && item.toLowerCase().includes(value.toLowerCase()));
    let recommendationsMatches = (cachedSuggestions.agent_history || []).filter((item) => item && item.toLowerCase().includes(value.toLowerCase()));
    const MAX_SUGGESTIONS = 6;
    historyMatches = historyMatches.slice(0, MAX_SUGGESTIONS);
    const recCount = Math.max(0, MAX_SUGGESTIONS - historyMatches.length);
    recommendationsMatches = recommendationsMatches.slice(0, recCount);
    setSuggestionData({
      history: historyMatches,
      recommendations: recommendationsMatches,
    });
    setSuggestionVisible(historyMatches.length > 0 || recommendationsMatches.length > 0);
  };
  const handleSuggestionSelect = (text, submitUserMessage = false) => {
    setUserChat(text);
    setSuggestionVisible(false);
    calculateHeight();
    if (submitUserMessage) {
      // If user wants to directly call the chat on selection of the suggestion then current it populates the input and adds focus to it
      // If we have to trigger the chat immediately upon selection comment the above focus line and uncomment the below submit function
      sendUserMessage(text);
    } else {
      if (textareaRef.current) textareaRef.current.focus();
    }
  };

  // Canvas helper functions
  const openCanvas = (content, title = "Code View", type = "code", messageId = null, forceOpen = false) => {
    // Don't open canvas if it's disabled, unless it's a manual/forced open
    if (!isCanvasEnabled && !forceOpen) {
      return;
    }

    // Check if content type is text-only in parts array
    if (Array.isArray(content) && content.every((part) => part.type === "text")) {
      return;
    }

    // Always close first, then open with new data
    setIsCanvasOpen(false);
    setTimeout(() => {
      setCanvasContent(content);
      setCanvasTitle(title);
      setCanvasContentType(type);
      setCanvasMessageId(messageId);
      setIsCanvasOpen(true);
      setCanvasIsLast(true);
    }, 0);
  };

  const closeCanvas = () => {
    setIsCanvasOpen(false);
    setCanvasContent(null);
    setCanvasTitle("");
    setCanvasContentType("");
    setCanvasMessageId(null);
    setCanvasIsLast(false);
  };

  // Auto-detect canvas content from AI responses - PARTS FORMAT ONLY
  const detectCanvasContent = (input) => {
    try {
      // Detect email content
      if (
        typeof input === "object" && input !== null && (
          input.type === "email" ||
          input.contentType === "email" ||
          input?.to || input?.subject || input?.body || (input.data && (input.data.to || input.data.subject || input.data.body))
        )
      ) {
        // Normalize email data
        let emailContent = input;
        if (input.data) emailContent = input.data;
        return {
          type: "email",
          content: emailContent,
          title: "Email Viewer",
          is_last: true,
        };
      }
      // Check if input is the API response object with parts at root level
      if (typeof input === "object" && input !== null && input.parts) {
        const parts = input.parts;
        // Check if parts has components array
        if (parts && Array.isArray(parts) && parts?.length > 0) {
          // Any valid parts structure should trigger canvas rendering
          return {
            type: "parts",
            content: parts,
            title: "Canvas View",
            isParts: true,
          };
        }
      }

      // FALLBACK: If no parts format, try markdown parsing for chart content
      // let text = "";
      // if (typeof input === "string") {
      //   text = input;
      // } else if (input && input.message) {
      //   text = input.message;
      // } else {
      //   return null;
      // }

      // Check for chart patterns in the text
      // if (text.includes("Day") && text.includes("Income") && (text.includes("Expenses") || text.includes("Expense")) && text.includes("████")) {
      //   // Parse chart lines
      //   const chartLines = text.split("\n").filter((line) => line.includes("Day") && line.includes("Income") && (line.includes("Expenses") || line.includes("Expense")));

      //   if (chartLines.length > 0) {
      //     const chartData = chartLines
      //       .map((line) => {
      //         const dayMatch = line.match(/Day\s+(\d+)/);
      //         const incomeMatch = line.match(/Income.*?\(([\d,]+)\)/);
      //         const expensesMatch = line.match(/Expenses?.*?\(([\d,]+)\)/);

      //         if (dayMatch && incomeMatch && expensesMatch) {
      //           return {
      //             day: `Day ${dayMatch[1]}`,
      //             income: parseInt(incomeMatch[1].replace(/,/g, "")),
      //             expenses: parseInt(expensesMatch[1].replace(/,/g, "")),
      //           };
      //         }
      //         return null;
      //       })
      //       .filter(Boolean);

      //     if (chartData.length > 0) {
      //       // Return chart data in parts format
      //       return {
      //         type: "parts",
      //         content: [
      //           {
      //             type: "chart",
      //             data: {
      //               chart_type: "bar",
      //               title: "Income vs Expenses",
      //               chart_data: chartData,
      //             },
      //             metadata: {},
      //           },
      //         ],
      //         title: "Chart View",
      //         isParts: true,
      //       };
      //     }
      //   }
      // }
      // No parts format found - return null (no canvas)
      return null;
    } catch (error) {
      console.error("Error processing message in detectCanvasContent:", error);
      return null;
    }
  };

  const [debugSteps, setDebugSteps] = useState([]);
  const [showLiveSteps, setShowLiveSteps] = useState(false);
  const [expanded, setExpanded] = useState(false);

  // Augment existing SSE callback logic to also accept plain debug step objects
  useEffect(() => {
    const genericHandler = (data) => {
      // Accept either structured control events (open/close) or direct debug steps
      if (data && (data.type === "open" || data.event === "open")) {
        setDebugSteps([]);
        setShowLiveSteps(true);
        return;
      }
      if (data && (data.type === "close" || data.event === "close")) {
        setShowLiveSteps(false);
        return;
      }
      // Normalize possible string payload
      let payload = data;
      if (typeof data === "string") {
        try {
          payload = JSON.parse(data);
        } catch (_) {
          payload = { debug_value: data };
        }
      }
      if (!payload) return;
      const hasDebug = payload.debug_value || payload.debug_key;
      if (hasDebug) {
        setShowLiveSteps(true);
        const MAX_DEBUG_STEPS = 200;
        setDebugSteps((prev) => [...prev, { step: prev.length + 1, ...payload }].slice(-MAX_DEBUG_STEPS));
      }
    };
    setSseMessageCallback(genericHandler);
    return () => setSseMessageCallback(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Clear debug steps when starting new operations
  const clearDebugSteps = () => {
    setDebugSteps([]);
    setShowLiveSteps(false);
  };

  const ONLINE_EVAL_AGENT_TYPES = [REACT_AGENT, REACT_CRITIC_AGENT, PLANNER_EXECUTOR_AGENT, MULTI_AGENT,HYBRID_AGENT];

  const shouldShowOnlineEvaluator = () => {
    if (!agentType) return false;
    return ONLINE_EVAL_AGENT_TYPES.includes(agentType);
  };
  const [onlineEvaluatorFlag, setOnlineEvaluatorFlag] = useState(false);
  const handleOnlineEvaluatorToggle = (checked) => {
    setOnlineEvaluatorFlag(checked);
  };

  return (
    <>
      <div className={stylesNew.askAssistantContainer} ref={chatbotContainerRef}>
        <div className={`${stylesNew.chatWrapper} ${isCanvasOpen ? stylesNew.withCanvas : ""}`}>
          <div className={stylesNew.bubbleAndInput}>
            <div className={stylesNew.chatBubblesWrapper}>
              <div className={stylesNew.messagesWrapper}>
                {/* message container */} {/* <div className={stylesNew.messagesContainer} ref={msgContainerRef}> */}
                {/* {showToast && !showChatHistory && !isDeletingChat && lastResponse && (
                  <ToastMessage message={lastResponse === null ? "Internal Server error" : likeMessage} onClose={() => setShowToast(false)} />
                )} */}
                <MsgBox
                  styles={stylesNew}
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
                  setToastMessage={setToastMessage}
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
                  handleCanvasToggle={handleCanvasToggle}
                  handleHumanInLoop={handleHumanInLoop}
                  handleContextToggle={handleContextToggle}
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
                  openCanvas={openCanvas}
                  detectCanvasContent={detectCanvasContent}
                  debugSteps={debugSteps}
                  showLiveSteps={showLiveSteps}
                  setShowLiveSteps={setShowLiveSteps}
                  expanded={expanded}
                  setExpanded={setExpanded}
                  isCanvasEnabled={isCanvasEnabled}
                  isContextEnabled={isContextEnabled}
                  onlineEvaluatorFlag={onlineEvaluatorFlag}
                   plan_verifier_flag={isHuman}
                />
              </div>
            </div>
            <div className={"chatSection"}>
              <div className={chatInputModule.container}>
                <div className={chatInputModule.topControls}>
                  <div className={chatInputModule.controlGroup}>
                    <select className={chatInputModule.select} value={agentType} onChange={(e) => handleTypeChange(e.target.value)} disabled={generating || fetching || isEditable}>
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
                        // When changing model, preserve session IDs but update model
                        const newModel = selectedOption.target.value;
                        setModel(newModel);
                        setLikeIcon(false);
                      }}
                      disabled={!agentType || generating || fetching || isEditable}
                      aria-disabled={!agentType || generating || fetching || isEditable}>
                      <option value="">Select Model</option>
                      {selectedModels.map((modelOption) => (
                        <option key={modelOption.value} value={modelOption.value}>
                          {modelOption.value}
                        </option>
                      ))}
                    </select>
                  </div>

                  <div className={chatInputModule.controlGroup} ref={agentDropdownRef}>
                    <div
                      className={`${chatInputModule.searchableDropdown} ${!agentType || messageDisable || fetching || generating || isEditable ? chatInputModule.disabled : ""}`}
                      aria-disabled={!agentType || messageDisable || fetching || generating || isEditable}>
                      <div
                        ref={agentTriggerRef}
                        className={`${chatInputModule.dropdownTrigger} ${showAgentDropdown ? chatInputModule.active : ""} ${
                          !agentType || messageDisable || fetching || generating || isEditable ? chatInputModule.disabled : ""
                        }`}
                        onClick={!(!agentType || messageDisable || fetching || generating || isEditable) ? handleAgentDropdownToggle : null}
                        onKeyDown={(e) => {
                          if (!agentType || messageDisable || fetching || generating || isEditable) return;
                          if (e.key === "Enter" || e.key === " ") {
                            e.preventDefault();
                            handleAgentDropdownToggle();
                          } else if (e.key === "ArrowDown") {
                            e.preventDefault();
                            if (!showAgentDropdown) {
                              setShowAgentDropdown(true);
                              setHighlightedAgentIndex(0);
                            } else {
                              handleAgentDropdownKeyDown(e);
                            }
                          } else if (e.key === "ArrowUp") {
                            e.preventDefault();
                            if (showAgentDropdown) {
                              handleAgentDropdownKeyDown(e);
                            }
                          } else if (showAgentDropdown) {
                            handleAgentDropdownKeyDown(e);
                          }
                        }}
                        tabIndex={!agentType || messageDisable || fetching || generating || isEditable ? -1 : 0}
                        role="combobox"
                        aria-expanded={showAgentDropdown}
                        aria-controls="agent-dropdown-list"
                        aria-haspopup="listbox"
                        aria-label="Select Agent"
                        aria-disabled={!agentType || messageDisable || fetching || generating || isEditable}>
                        <span>{selectedAgent.agentic_application_name || "Select Agent"}</span>
                        <svg
                          width="18"
                          height="18"
                          viewBox="0 0 20 20"
                          fill="none"
                          xmlns="http://www.w3.org/2000/svg"
                          className={`${chatInputModule.chevronIcon} ${showAgentDropdown ? chatInputModule.rotated : ""}`}>
                          <path d="M6 8L10 12L14 8" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
                        </svg>
                      </div>

                      {showAgentDropdown && agentType && (
                        <div className={chatInputModule.dropdownContent} role="listbox" aria-label="Agent options" onClick={(e) => e.stopPropagation()}>
                          <div className={chatInputModule.searchContainer}>
                            <svg width="18" height="18" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg" className={chatInputModule.searchIcon}>
                              <circle cx="9" cy="9" r="6" stroke="currentColor" strokeWidth="1.5" fill="none" />
                              <path d="m15 15 4 4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
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
                                setHighlightedAgentIndex(newSearchTerm === "" ? -1 : 0);
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
                                  className={`${chatInputModule.agentItem} ${index === highlightedAgentIndex ? chatInputModule.highlighted : ""}`}
                                  onClick={() => {
                                    selectAgent(agent);
                                    setAgentSelectValue(agent.agentic_application_id);
                                    setFeedback("");
                                    setOldSessionId("");
                                    const cookieSessionId = Cookies.get("user_session");
                                    if (cookieSessionId) {
                                      setSessionId(cookieSessionId);
                                    }
                                    setLikeIcon(false);
                                  }}
                                  onMouseEnter={() => setHighlightedAgentIndex(index)}
                                  onMouseLeave={() => setHighlightedAgentIndex(-1)}
                                  role="option"
                                  aria-selected={index === highlightedAgentIndex}>
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
                {!allOptionsSelected && (
                  <div className={chatInputModule.inputsWrapperRow2}>
                    <div className={chatInputModule.inputForm}>
                      <div className={chatInputModule.inputContainer}>
                        <button
                          type="button"
                          className={chatInputModule.inputButton + " " + chatInputModule.actionButton}
                          onClick={handleFileClick}
                          disabled={messageDisable || fetching || generating || isEditable || allOptionsSelected}
                          title="Upload Files"
                          tabIndex={0}>
                          <svg width="18" height="18" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg">
                            <path d="M10 13V3" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
                            <path d="M7 6L10 3L13 6" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
                            <rect x="4" y="15" width="12" height="2" rx="1" stroke="currentColor" strokeWidth="1.5" />
                          </svg>
                        </button>

                        <div className={chatInputModule.promptLibraryAndTextArea}>
                          {promptSuggestions && promptSuggestions.length > 0 && (
                            <button
                              type="button"
                              className={chatInputModule.promptSuggestionBtn}
                              onClick={handlePromptSuggestionsToggle}
                              disabled={messageDisable || fetching || generating || isEditable || allOptionsSelected}
                              title="Prompt Library"
                              tabIndex={0}>
                              <svg width="18" height="18" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg">
                                <path
                                  d="M10 2L12.09 6.26L17 7L13.5 10.74L14.18 15.74L10 13.77L5.82 15.74L6.5 10.74L3 7L7.91 6.26L10 2Z"
                                  stroke="currentColor"
                                  strokeWidth="1.5"
                                  strokeLinecap="round"
                                  strokeLinejoin="round"
                                  fill="none"
                                />
                                <path d="M6 3L7 5L9 4" stroke="currentColor" strokeWidth="1" strokeLinecap="round" opacity="0.6" />
                                <path d="M15 4L16 6L18 5" stroke="currentColor" strokeWidth="1" strokeLinecap="round" opacity="0.6" />
                                <path d="M4 12L5 14L7 13" stroke="currentColor" strokeWidth="1" strokeLinecap="round" opacity="0.6" />
                              </svg>
                            </button>
                          )}
                          <div className={chatInputModule.textInputWrapper}>
                            {recording ? (
                              <div className={stylesNew.recordingIndicator}>
                                <div className={stylesNew.recordingAnimation}>
                                  <div className={stylesNew.recordingDot}></div>
                                  <div className={stylesNew.recordingPulse}></div>
                                </div>
                                <span className={stylesNew.recordingText}>
                                  <span className={stylesNew.recordingLabel}>Recording</span>
                                  <div className={stylesNew.audioVisualizer}>
                                    <div className={stylesNew.audioBar}></div>
                                    <div className={stylesNew.audioBar}></div>
                                    <div className={stylesNew.audioBar}></div>
                                    <div className={stylesNew.audioBar}></div>
                                    <div className={stylesNew.audioBar}></div>
                                  </div>
                                </span>
                              </div>
                            ) : (
                              <textarea
                                ref={textareaRef}
                                value={userChat}
                                onChange={handleInputChangeForSuggestion}
                                onKeyDown={handleKeyDown}
                                placeholder={!allOptionsSelected ? "Type your message..." : "Please select Agent Type, Model, and Agent to start chatting"}
                                disabled={generating || allOptionsSelected || fetching || feedBack === dislike || isEditable || messageDisable}
                                className={chatInputModule.textInput}
                                rows={1}
                                maxLength={2000}
                                autoComplete="off"
                                aria-autocomplete="list"
                                aria-controls="suggestion-popover"
                              />
                            )}
                          </div>
                        </div>

                        <div className={"rightButtons"}>
                          <button
                            type="submit"
                            onClick={() => sendUserMessage(userChat)}
                            className={`${chatInputModule.inputButton} ${chatInputModule.sendButton}`}
                            disabled={allOptionsSelected || generating || !userChat.trim()}
                            title="Send Message"
                            tabIndex={0}>
                            {/* SVG icon for send */}
                            <svg width="18" height="18" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg">
                              <path d="M3 17L17 10L3 3V8L13 10L3 12V17Z" fill="currentColor" />
                            </svg>
                          </button>
                        </div>
                        {/* Do not remove the below code it is needed for microphone implementation */}
                        {/* Voice/Send Button */}
                        {/* <div className={"rightButtons"}>
                      {userChat.trim() ? (
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
                      ) : (
                        <button
                          type="button"
                          className={`${chatInputModule.inputButton} ${!recording ? chatInputModule.micHighlight : ''} ${recording ? chatInputModule.selected : ''}`}
                          onClick={recording ? stopRecording : startRecording}
                          disabled={allOptionsSelected || generating}
                          title={recording ? "Stop Recording" : "Voice Input"}
                          tabIndex={0}
                        >
                          {recording ? (
                            <svg width="18" height="18" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg">
                              <rect x="5" y="5" width="10" height="10" rx="2" fill="currentColor" />
                            </svg>
                          ) : (
                            <svg width="18" height="18" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg">
                              <rect x="8" y="3" width="4" height="10" rx="2" fill="currentColor" />
                              <path d="M10 15V17" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
                              <path d="M7 17H13" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
                            </svg>
                          )}
                        </button>
                      )}
                    </div> */}
                      </div>
                    </div>
                    {/* Action Buttons */}
                    <div className={chatInputModule.actionButtons}>
                      <div className={chatInputModule.settingsContainer} ref={verifierSettingsRef}>
                        <button
                          className={`${chatInputModule.actionButton} ${showVerifierSettings ? chatInputModule.active : ""}`}
                          onClick={() => setShowVerifierSettings(!showVerifierSettings)}
                          onKeyDown={(e) => {
                            if (e.key === "Enter" || e.key === " ") {
                              e.preventDefault();
                              setShowVerifierSettings(!showVerifierSettings);
                            } else if (e.key === "ArrowDown" && !showVerifierSettings) {
                              e.preventDefault();
                              setShowVerifierSettings(true);
                            }
                          }}
                          title="Settings"
                          tabIndex={generating ? -1 : 0}
                          disabled={generating || allOptionsSelected || fetching || feedBack === dislike || isEditable || messageDisable}
                          aria-expanded={showVerifierSettings}
                          aria-haspopup="menu"
                          aria-label="Verifier Settings menu"
                          aria-disabled={generating}>
                          <svg width="18" height="18" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg">
                            <rect x="4" y="7" width="12" height="6" rx="3" stroke="currentColor" strokeWidth="1.5" />
                            <circle cx="13" cy="10" r="2" fill="currentColor" />
                          </svg>
                        </button>
                        {showVerifierSettings && (
                          <div className={chatInputModule.settingsDropdown} onKeyDown={handleSettingsKeyDown} role="menu" aria-label="Verifier Settings menu">
                            <div className={chatInputModule.settingsHeader}>Toggle Settings</div>

                            {shouldShowHumanVerifier() && (
                              <div className={chatInputModule.toggleGroup + " plan-verifier"} role="menuitem">
                                <label className={chatInputModule.toggleLabel}>
                                  <span className={chatInputModule.toggleText} id="humanVerifierLabel">
                                    Plan Verifier
                                  </span>
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
                                    onKeyDown={(e) => handleToggleKeyDown(e, handleHumanInLoop, isHuman)}></span>
                                </label>
                              </div>
                            )}

                            {shouldShowToolVerifier() && (
                              <div className={chatInputModule.toggleGroup + " tool-verifier"} role="menuitem">
                                <label className={chatInputModule.toggleLabel}>
                                  <span className={chatInputModule.toggleText} id="toolVerifierLabel">
                                    Tool Verifier
                                  </span>
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
                                    onKeyDown={(e) => handleToggleKeyDown(e, handleToolInterrupt, toolInterrupt)}></span>
                                </label>
                              </div>
                            )}

                            {/* Canvas Toggle - Available for all agent types */}
                            <div className={chatInputModule.toggleGroup + " canvas-toggle"} role="menuitem">
                              <label className={chatInputModule.toggleLabel}>
                                <span className={chatInputModule.toggleText} id="canvasToggleLabel">
                                  Canvas View
                                </span>
                                <input
                                  type="checkbox"
                                  checked={isCanvasEnabled}
                                  onChange={(e) => handleCanvasToggle(e.target.checked)}
                                  className={chatInputModule.toggleInput}
                                  id="canvasToggle"
                                  disabled={messageDisable || generating || fetching || isEditable}
                                />
                                <span
                                  className={chatInputModule.toggleSlider}
                                  tabIndex={0}
                                  role="switch"
                                  aria-checked={isCanvasEnabled}
                                  aria-labelledby="canvasToggleLabel"
                                  onKeyDown={(e) => handleToggleKeyDown(e, handleCanvasToggle, isCanvasEnabled)}></span>
                              </label>
                            </div>

                            {/* Context Toggle - Available for all agent types */}
                            <div className={chatInputModule.toggleGroup + " context-toggle"} role="menuitem">
                              <label className={chatInputModule.toggleLabel}>
                                <span className={chatInputModule.toggleText} id="contextToggleLabel">
                                  Context
                                </span>
                                <input
                                  type="checkbox"
                                  checked={isContextEnabled}
                                  onChange={(e) => handleContextToggle(e.target.checked)}
                                  className={chatInputModule.toggleInput}
                                  id="contextToggle"
                                  disabled={messageDisable || generating || fetching || isEditable}
                                />
                                <span
                                  className={chatInputModule.toggleSlider}
                                  tabIndex={0}
                                  role="switch"
                                  aria-checked={isContextEnabled}
                                  aria-labelledby="contextToggleLabel"
                                  onKeyDown={(e) => handleToggleKeyDown(e, handleContextToggle, isContextEnabled)}></span>
                              </label>
                            </div>
                            {shouldShowOnlineEvaluator() && (
                              <div className={chatInputModule.toggleGroup + " online-evaluator"} role="menuitem">
                                <label className={chatInputModule.toggleLabel}>
                                  <span className={chatInputModule.toggleText} id="onlineEvaluatorLabel">
                                    {"Online Evaluator"}
                                  </span>
                                  <input
                                    type="checkbox"
                                    checked={onlineEvaluatorFlag}
                                    onChange={(e) => handleOnlineEvaluatorToggle(e.target.checked)}
                                    className={chatInputModule.toggleInput}
                                    id="onlineEvaluatorToggle"
                                    disabled={messageDisable || generating || fetching || isEditable}
                                  />
                                  <span
                                    className={chatInputModule.toggleSlider}
                                    tabIndex={0}
                                    role="switch"
                                    aria-checked={onlineEvaluatorFlag}
                                    aria-labelledby="onlineEvaluatorLabel"
                                    onKeyDown={(e) => handleToggleKeyDown(e, handleOnlineEvaluatorToggle, onlineEvaluatorFlag)}></span>
                                </label>
                              </div>
                            )}
                          </div>
                        )}
                      </div>
                      <div className={chatInputModule.settingsContainer} style={{ position: "relative", display: "inline-block" }} ref={temperaturePopupRef}>
                        <button
                          className={`${chatInputModule.actionButton} ${showTemperaturePopup ? chatInputModule.active : ""}`}
                          onClick={() => setShowTemperaturePopup((v) => !v)}
                          title="Set Temperature"
                          tabIndex={0}
                          disabled={allOptionsSelected || generating || fetching || isEditable}
                          aria-expanded={showTemperaturePopup}
                          aria-haspopup="menu"
                          aria-label="Temperature Settings menu">
                          <SVGIcons icon="thermometerIcon" width={18} height={18} fill="currentColor" color="none"/>
                        </button>
                        {showTemperaturePopup && (
                          <div
                            className={`${chatInputModule.settingsDropdown} ${chatInputModule.chatSettingsDropdown}`}
                            style={{ minWidth: 300, right: 0, left: "auto", bottom: 40, zIndex: 2001, position: "absolute" }}
                            role="menu"
                            aria-label="Temperature Settings menu">
                            <div className={chatInputModule.settingsHeader}>Temperature</div>
                            <TemperatureSliderPopup value={temperature} onChange={setTemperature} onClose={() => setShowTemperaturePopup(false)} hideOverlay />
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
                            disabled={generating || allOptionsSelected || fetching || feedBack === dislike || isEditable || messageDisable}>
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
                              <div className={chatInputModule.searchContainer} style={{ padding: "8px 8px 4px 8px" }}>
                                <svg width="18" height="18" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg" className={chatInputModule.searchIcon}>
                                  <circle cx="9" cy="9" r="6" stroke="currentColor" strokeWidth="1.5" fill="none" />
                                  <path d="m15 15 4 4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
                                </svg>
                                <input
                                  ref={knowledgeSearchInputRef}
                                  type="text"
                                  placeholder="Search knowledge base..."
                                  value={searchTerm}
                                  onChange={handleSearchChange}
                                  onKeyDown={handleKnowledgeDropdownKeyDown}
                                  className={chatInputModule.searchInput}
                                  aria-label="Search knowledge base"
                                  autoComplete="off"
                                />
                              </div>
                              <div
                                className={chatInputModule.agentsList}
                                ref={knowledgeListRef}
                                style={{
                                  maxHeight: 200,
                                  overflowY: "auto",
                                  padding: "4px 8px",
                                }}>
                                {Array.isArray(knowledgeResponse) && knowledgeResponse.length > 0 ? (
                                  (() => {
                                    const filteredOptions = knowledgeResponse.filter((option) => option.toLowerCase().includes(searchTerm.toLowerCase()));
                                    return filteredOptions.map((option, idx) => (
                                      <div
                                        key={idx}
                                        className={`${chatInputModule.agentItem} ${idx === highlightedKbIndex ? chatInputModule.highlighted : ""}`}
                                        style={{
                                          display: "flex",
                                          alignItems: "center",
                                          gap: 8,
                                        }}
                                        onMouseEnter={() => setHighlightedKbIndex(idx)}
                                        onMouseLeave={() => setHighlightedKbIndex(-1)}
                                        onClick={() => {
                                          const isChecked = selectedValues.includes(option);
                                          if (isChecked) {
                                            setSelectedValues((prev) => prev.filter((item) => item !== option));
                                          } else {
                                            setSelectedValues((prev) => [...prev, option]);
                                          }
                                        }}
                                        role="option"
                                        aria-selected={idx === highlightedKbIndex}>
                                        <input
                                          type="checkbox"
                                          id={`kb-checkbox-${idx}`}
                                          value={option}
                                          checked={selectedValues.includes(option)}
                                          onChange={handleCheckboxChange}
                                          style={{ marginRight: 6 }}
                                          tabIndex={-1}
                                        />
                                        <label
                                          htmlFor={`kb-checkbox-${idx}`}
                                          className={chatInputModule.agentName}
                                          style={{
                                            fontSize: 13,
                                            fontWeight: 500,
                                            cursor: "pointer",
                                          }}>
                                          {option}
                                        </label>
                                      </div>
                                    ));
                                  })()
                                ) : (
                                  <div className={chatInputModule.noAgents}>No knowledge base found</div>
                                )}
                              </div>
                            </div>
                          )}
                        </div>
                      )}

                      <div className={chatInputModule.settingsContainer} ref={chatSettingsRef}>
                        <button
                          className={`${chatInputModule.actionButton} ${showChatSettings ? chatInputModule.active : ""}`}
                          onClick={() => setShowChatSettings(!showChatSettings)}
                          onKeyDown={(e) => {
                            if (e.key === "Enter" || e.key === " ") {
                              e.preventDefault();
                              setShowChatSettings(!showChatSettings);
                            } else if (e.key === "ArrowDown" && !showChatSettings) {
                              e.preventDefault();
                              setShowChatSettings(true);
                            }
                          }}
                          title="ChatSettings"
                          tabIndex={generating ? -1 : 0}
                          // disabled={generating || allOptionsSelected || fetching || feedBack === dislike || isEditable || messageDisable}
                          aria-expanded={showChatSettings}
                          aria-haspopup="menu"
                          aria-label="Chat Settings menu"
                          aria-disabled={generating}>
                          <svg width="18" height="18" viewBox="0 0 18 18" fill="none" xmlns="http://www.w3.org/2000/svg">
                            {/* <!-- Speech bubble outline with reduced height --> */}
                            <path
                              d="M2.5 2.5 C2.5 1.95 2.95 1.5 3.5 1.5 L14.5 1.5 C15.05 1.5 15.5 1.95 15.5 2.5 L15.5 11.5 C15.5 12.05 15.05 12.5 14.5 12.5 L6.5 12.5 L3.5 15.5 C3.2 15.8 2.5 15.6 2.5 15.2 L2.5 2.5 Z"
                              stroke="currentColor"
                              strokeWidth="1"
                              fill="none"
                              strokeLinejoin="round"
                            />

                            {/* <!-- Gear outline positioned higher --> */}
                            <path
                              d="M9 3.5 C8.7 3.5 8.5 3.7 8.5 4 L8.5 4.3 C8.3 4.4 8.2 4.5 8 4.6 L7.8 4.4 C7.6 4.2 7.3 4.2 7.1 4.4 L6.6 4.9 C6.4 5.1 6.4 5.4 6.6 5.6 L6.8 5.8 C6.7 6 6.6 6.1 6.5 6.3 L6.2 6.3 C5.9 6.3 5.7 6.5 5.7 6.8 L5.7 7.5 C5.7 7.8 5.9 8 6.2 8 L6.5 8 C6.6 8.2 6.7 8.3 6.8 8.5 L6.6 8.7 C6.4 8.9 6.4 9.2 6.6 9.4 L7.1 9.9 C7.3 10.1 7.6 10.1 7.8 9.9 L8 9.7 C8.2 9.8 8.3 9.9 8.5 10 L8.5 10.3 C8.5 10.6 8.7 10.8 9 10.8 L9.7 10.8 C10 10.8 10.2 10.6 10.2 10.3 L10.2 10 C10.4 9.9 10.5 9.8 10.7 9.7 L10.9 9.9 C11.1 10.1 11.4 10.1 11.6 9.9 L12.1 9.4 C12.3 9.2 12.3 8.9 12.1 8.7 L11.9 8.5 C12 8.3 12.1 8.2 12.2 8 L12.5 8 C12.8 8 13 7.8 13 7.5 L13 6.8 C13 6.5 12.8 6.3 12.5 6.3 L12.2 6.3 C12.1 6.1 12 6 11.9 5.8 L12.1 5.6 C12.3 5.4 12.3 5.1 12.1 4.9 L11.6 4.4 C11.4 4.2 11.1 4.2 10.9 4.4 L10.7 4.6 C10.5 4.5 10.4 4.4 10.2 4.3 L10.2 4 C10.2 3.7 10 3.5 9.7 3.5 L9 3.5 Z"
                              stroke="currentColor"
                              strokeWidth="0.8"
                              fill="none"
                            />

                            {/* <!-- Gear center circle positioned higher --> */}
                            <circle cx="9.35" cy="7.15" r="1.2" stroke="currentColor" strokeWidth="0.8" fill="none" />
                          </svg>
                        </button>
                        {showChatSettings && (
                          <div
                            className={`${chatInputModule.settingsDropdown} ${chatInputModule.chatSettingsDropdown}`}
                            onKeyDown={handleSettingsKeyDown}
                            role="menu"
                            aria-label="Chat Settings menu">
                            <div className={chatInputModule.settingsHeader}>Chat Options</div>

                            <div className={`${chatInputModule.toggleGroup} ${chatInputModule.chatOptions}`} role="menuitem">
                              <div className={chatInputModule.chatOptionsItems}>
                                <button
                                  className={chatInputModule.actionButton}
                                  onClick={handleNewChat}
                                  title="New Chat"
                                  tabIndex={0}
                                  disabled={allOptionsSelected || generating || fetching || isEditable}>
                                  {" "}
                                  {/* Removed the condition check 'messageData.length === 0' */}
                                  <svg width="20" height="20" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg">
                                    <path
                                      d="M3 6C3 4.34315 4.34315 3 6 3H14C15.6569 3 17 4.34315 17 6V11C17 12.6569 15.6569 14 14 14H8L5 17V6Z"
                                      stroke="currentColor"
                                      strokeWidth="1.5"
                                      strokeLinecap="round"
                                      strokeLinejoin="round"
                                    />
                                    <g transform="translate(11, 8.5)">
                                      <path d="M0 -2.5V2.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
                                      <path d="M-2.5 0H2.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
                                    </g>
                                  </svg>
                                  <p className={chatInputModule.chatOptionName}>New Chat</p>
                                </button>
                              </div>

                              <div className={chatInputModule.chatOptionsItems}>
                                <button
                                  className={chatInputModule.actionButton}
                                  onClick={() => {
                                    setShowChatHistory(true);
                                    setShowChatSettings(false);
                                  }}
                                  title="Chat History"
                                  tabIndex={0}
                                  disabled={allOptionsSelected || generating || fetching || isEditable}>
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
                                  <p className={chatInputModule.chatOptionName}>Chat History</p>
                                </button>
                              </div>

                              <div className={chatInputModule.chatOptionsItems}>
                                <button
                                  className={chatInputModule.actionButton}
                                  onClick={(e) => {
                                    if (allOptionsSelected || fetching || messageData.length === 0) {
                                      e.preventDefault();
                                      return;
                                    }
                                    handleResetChat();
                                    setShowChatSettings(false);
                                  }}
                                  title="Delete Chat"
                                  tabIndex={0}
                                  disabled={allOptionsSelected || generating || fetching || isEditable || messageData.length === 0}>
                                  <svg width="18" height="18" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg">
                                    <path d="M7 4V3C7 2.44772 7.44772 2 8 2H12C12.5523 2 13 2.44772 13 3V4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
                                    <path d="M5 4H15" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
                                    <path d="M6 4V16C6 17.1046 6.89543 18 8 18H12C13.1046 18 14 17.1046 14 16V4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
                                    <path d="M8 8V14" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
                                    <path d="M12 8V14" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
                                  </svg>
                                  <p className={chatInputModule.chatOptionName}>Delete Chat</p>
                                </button>
                              </div>
                            </div>
                          </div>
                        )}
                      </div>
                      <button
                        className={chatInputModule.actionButton}
                        onClick={handleLiveTracking}
                        title="Live Tracking"
                        tabIndex={0}
                        disabled={allOptionsSelected || generating || fetching || isEditable}>
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
                  </div>
                )}
                <PromptSuggestions
                  isVisible={showPromptSuggestions}
                  onClose={() => setShowPromptSuggestions(false)}
                  onSelectPrompt={handlePromptSelect}
                  promptSuggestions={promptSuggestions}
                />
                {/* Autofill Suggestion Popover */}
                <div style={{ position: "relative" }}>
                  <SuggestionPopover
                    suggestions={suggestionData}
                    userValue={userChat}
                    onSelect={handleSuggestionSelect}
                    visible={suggestionVisible}
                    onClose={() => setSuggestionVisible(false)}
                  />
                </div>
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
          {/* Canvas Component */}
          {isCanvasOpen && (
            <Canvas
              isOpen={isCanvasOpen}
              onClose={closeCanvas}
              content={canvasContent}
              contentType={canvasContentType}
              title={canvasTitle}
              messageId={canvasMessageId}
              is_last={canvasIsLast}
              sendUserMessage={sendUserMessage}
              selectedAgent={agentSelectValue}
            />
          )}
        </div>
      </div>
    </>
  );
};
      
export default AskAssistant;
