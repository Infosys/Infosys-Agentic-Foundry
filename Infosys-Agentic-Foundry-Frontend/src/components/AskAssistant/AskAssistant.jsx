import { useEffect, useRef, useState, useCallback } from "react";
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
  HYBRID_AGENT,
  PIPELINE_AGENT,
  chat_screen_config,
} from "../../constant";

import { useChatServices } from "../../services/chatService";
import useFetch from "../../Hooks/useAxios";
import { useGlobalComponent } from "../../Hooks/GlobalComponentContext.js";
import SVGIcons from "../../Icons/SVGIcons";
import { usePermissions } from "../../context/PermissionsContext";
import { useMessage } from "../../Hooks/MessageContext";

// Components
import MsgBox from "./MsgBox";
import ChatHistorySlider from "./ChatHistorySlider";
import PromptSuggestions from "./PromptSuggestions";
import SuggestionPopover from "./SuggestionPopover";
import Canvas from "../Canvas/Canvas";
import TemperatureSliderPopup from "./TemperatureSliderPopup.jsx";
import ConfirmationModal from "../commonComponents/ToastMessages/ConfirmationPopup";
import NewCommonDropdown from "../commonComponents/NewCommonDropdown";
import DocViewerModal from "../DocViewerModal/DocViewerModal.jsx";
import WelcomeModal from "./WelcomeModal.jsx";
import dropdownStyles from "../../css_modules/NewCommonDropdown.module.css";

// Styles
import stylesNew from "./AskAssistant.module.css";
import chatInputModule from "./ChatInput.module.css";

// Constants
const TEXTAREA_MAX_HEIGHT = 120; // Maximum height for textarea in pixels
const TEMPERATURE_MAX_PERCENT = 100; // Maximum percentage for temperature slider
const AUTO_HIDE_TIMEOUT = 5000; // Timeout for auto-hiding messages (5 seconds)
const DEBOUNCE_DELAY = 100; // Delay for debounce operations
const STATE_UPDATE_DELAY = 2000; // Delay for state updates

// Add a helper function to generate agent type filter options from chat_screen_config
const getAgentTypeFilterOptions = (framework) => {
  // Get mentionAgentTypes from chat_screen_config based on current framework
  const mentionAgentTypes = chat_screen_config[framework]?.mentionAgentTypes || [];

  // Mapping of agent type values to display labels and short codes
  const agentTypeLabels = {
    hybrid_agent: { label: "Hybrid Agent", short: "HA" },
    meta_agent: { label: "Meta Agent", short: "MA" },
    planner_meta_agent: { label: "Meta Planner", short: "MP" },
    planner_executor_agent: { label: "Planner Executor", short: "PE" },
    multi_agent: { label: "Planner Executor Critic", short: "PEC" },
    react_agent: { label: "React Agent", short: "RA" },
    react_critic_agent: { label: "React Critic", short: "RC" },
    pipeline: { label: "Pipeline", short: "PL" },
  };

  // Build options array starting with "All Types"
  const options = [{ label: "All Types", value: "all" }];

  // Add only the agent types allowed for this framework
  mentionAgentTypes.forEach((agentType) => {
    if (agentTypeLabels[agentType]) {
      options.push({
        label: agentTypeLabels[agentType].label,
        value: agentType,
        short: agentTypeLabels[agentType].short,
      });
    }
  });

  return options;
};

// Framework options for dropdown
const FRAMEWORK_OPTIONS = [
  { label: "LangGraph", value: "langgraph" },
  { label: "Google ADK", value: "google_adk" },
  { label: "Pure Python", value: "pure_python" },
];

const AskAssistant = () => {
  const userRole = Cookies.get("role") ? Cookies.get("role")?.toLowerCase() : "";
  const loggedInUserEmail = Cookies.get("email");
  const user_session = Cookies.get("user_session");
  const [messageData, setMessageData] = useState([]); // Holds the chat messages
  const [lastResponse, setLastResponse] = useState({}); // Stores the last response from the bot
  const [userChat, setUserChat] = useState(""); // User input for chat
  useEffect(() => {
    calculateHeight();
  }, [userChat]);
  const [generating, setGenerating] = useState(false); // Indicates if a response is being generated
  const [isHuman, setIsHuman] = useState(false); // Indicates if human verification is enabled
  const [isTool, setIsTool] = useState(false); // Indicates if tool verification is enabled
  const [isPlanVerifierOn, setIsPlanVerifierOn] = useState(false); // Indicates if plan verification is enabled
  const [agentsListData, setAgentsListData] = useState([]); // List of agents
  const [agentListDropdown, setAgentListDropdown] = useState([]); // Dropdown options for agents
  const [agentSelectValue, setAgentSelectValue] = useState(""); // Selected agent value
  const [agentType, setAgentType] = useState(""); // Type of agent selected
  const [model, setModel] = useState(""); // Model selected for chat
  const [feedBack, setFeedback] = useState(""); // Feedback for the plan verifier
  const [fetching, setFetching] = useState(false); // Indicates if data is being fetched
  const [showModelPopover, setShowModelPopover] = useState(false);
  const [toolData, setToolData] = useState(null);
  const [loadingAgents, setLoadingAgents] = useState(false);
  const [showToast, setShowToast] = useState(false);
  const [toastMessage, setToastMessage] = useState("");
  const [isDeletingChat, setIsDeletingChat] = useState(false);
  const [showDeleteConfirmation, setShowDeleteConfirmation] = useState(false);
  const [planData, setPlanData] = useState(null);
  const [showInput, setShowInput] = useState(false);
  const [oldChats, setOldChats] = useState([]);
  const [oldSessionId, setOldSessionId] = useState("");
  const [session, setSessionId] = useState(user_session);
  const [selectedModels, setSelectedModels] = useState([]);
  const [toolInterrupt, setToolInterrupt] = useState(false);
  const [isEditable, setIsEditable] = useState(false);
  // Tool interrupt submenu state
  const [mappedTools, setMappedTools] = useState([]);
  const [selectedInterruptTools, setSelectedInterruptTools] = useState([]);
  const [showToolInterruptModal, setShowToolInterruptModal] = useState(false);
  const [showToolsListExpanded, setShowToolsListExpanded] = useState(true); // Controls tools list collapse
  const [loadingMappedTools, setLoadingMappedTools] = useState(false);
  // Persist last seen plan verifier prompt from streaming chunks (backend only sends it transiently)
  const [planVerifierPrompt, setPlanVerifierPrompt] = useState("");
  // File upload states
  const [uploadedChatFiles, setUploadedChatFiles] = useState([]);
  const [isUploadingFiles, setIsUploadingFiles] = useState(false);
  const [showFileViewer, setShowFileViewer] = useState(false);
  const [viewingFile, setViewingFile] = useState({ url: "", name: "" });
  const fileInputRef = useRef(null);
  const bullseyeRef = useRef(null);
  const prevCanvasRef = useRef(null);
  const abortControllerRef = useRef(null); // AbortController for SSE streaming requests
  const { resetChat, getChatQueryResponse, getChatHistory, fetchOldChats, fetchNewChats, getQuerySuggestions, getToolsMappedByAgent, uploadChatFiles, deleteChatFile } = useChatServices();
  const { addMessage } = useMessage();

  const { permissions, hasPermission } = usePermissions();

  // Determine chat-related permission booleans with fallbacks to legacy shape
  // Using hasPermission(key, true) - show features by default unless explicitly denied
  const canExecutionSteps = typeof hasPermission === "function" ? hasPermission("execution_steps_access", true) : !(permissions && permissions.execution_steps_access === false);
  const canToolVerifier = typeof hasPermission === "function" ? hasPermission("tool_verifier_flag_access", true) : !(permissions && permissions.tool_verifier_flag_access === false);
  const canPlanVerifier = typeof hasPermission === "function" ? hasPermission("plan_verifier_flag_access", true) : !(permissions && permissions.plan_verifier_flag_access === false);
  const canEvaluation = typeof hasPermission === "function" ? hasPermission("online_evaluation_flag_access", true) : !(permissions && permissions.online_evaluation_flag_access === false);
  // New chat permissions
  const canValidator = typeof hasPermission === "function" ? hasPermission("validator_access", true) : !(permissions && permissions.validator_access === false);
  const canFileContext = typeof hasPermission === "function" ? hasPermission("file_context_access", true) : !(permissions && permissions.file_context_access === false);
  const canCanvasView = typeof hasPermission === "function" ? hasPermission("canvas_view_access", true) : !(permissions && permissions.canvas_view_access === false);
  const canContext = typeof hasPermission === "function" ? hasPermission("context_access", true) : !(permissions && permissions.context_access === false);

  const chatbotContainerRef = useRef(null);

  // (permission-enforced flags are applied inline where needed)
  const [likeIcon, setLikeIcon] = useState(false);
  const [showInputSendIcon, setShowInputSendIcon] = useState(false);
  const [isOldChatOpen, setIsOldChatOpen] = useState(false);
  const [isKnowledgeOpen, setIsKnowledgeOpen] = useState(false);
  // Knowledge base popover state
  const [showKnowledgePopover, setShowKnowledgePopover] = useState(false);
  const [showVerifierSettings, setShowVerifierSettings] = useState(false);
  const [showChatSettings, setShowChatSettings] = useState(false);

  const [highlightedAgentIndex, setHighlightedAgentIndex] = useState(-1);
  const [selectedAgent, setSelectedAgent] = useState("");

  // Mention (@) functionality states
  const [showMentionDropdown, setShowMentionDropdown] = useState(false);
  const [mentionSearchTerm, setMentionSearchTerm] = useState("");
  const [highlightedMentionIndex, setHighlightedMentionIndex] = useState(-1);
  const [mentionedAgent, setMentionedAgent] = useState("");
  const [mentionAgentTypeFilter, setMentionAgentTypeFilter] = useState("all");
  const [isHumanVerifierEnabled, setIsHumanVerifierEnabled] = useState(false);
  const [isToolVerifierEnabled, setIsToolVerifierEnabled] = useState(false);
  const [isCanvasEnabled, setIsCanvasEnabled] = useState(true);
  const [isContextEnabled, setIsContextEnabled] = useState(true); // context toggle - default true
  const [isFileContextEnabled, setIsFileContextEnabled] = useState(false); // file context management toggle - default false
  const [isMessageQueueEnabled, setIsMessageQueueEnabled] = useState(false); // message queue toggle - default false
  const [useValidator, setUseValidator] = useState(false); // validator toggle

  const [showChatHistory, setShowChatHistory] = useState(false);
  const [recording, setRecording] = useState(false);
  const [transcription, setTranscription] = useState("");
  const [isTranscribing, setIsTranscribing] = useState(false);
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

  // Right sidebar collapsed state
  const [isRightSidebarCollapsed, setIsRightSidebarCollapsed] = useState(false);

  // Auto-collapse right sidebar on narrow screens
  useEffect(() => {
    const SIDEBAR_BREAKPOINT = 900;
    const handleResize = () => {
      if (window.innerWidth <= SIDEBAR_BREAKPOINT) {
        setIsRightSidebarCollapsed(true);
      }
    };
    // Check on mount
    handleResize();
    window.addEventListener("resize", handleResize);
    return () => window.removeEventListener("resize", handleResize);
  }, []);

  const [showPromptSuggestions, setShowPromptSuggestions] = useState(false);
  const [promptSuggestions, setPromptSuggestions] = useState([]);
  const [openedViaIcon, setOpenedViaIcon] = useState(false);
  const promptSuggestionsRef = useRef(null);
  const promptSuggestionHasFocusRef = useRef(false);

  // Auto-suggest state for typing suggestions
  const [showAutoSuggest, setShowAutoSuggest] = useState(false);
  const [filteredAutoSuggestions, setFilteredAutoSuggestions] = useState([]);
  const [highlightedAutoSuggestIndex, setHighlightedAutoSuggestIndex] = useState(0);
  const autoSuggestRef = useRef(null);

  // Add framework state - defaults to "langgraph"
  const [framework, setFramework] = useState("langgraph");

  // Welcome modal state - show on first visit
  const [showWelcomeModal, setShowWelcomeModal] = useState(true);

  // Close PromptSuggestions on outside click
  useEffect(() => {
    function handleClickOutside(event) {
      if (showPromptSuggestions && promptSuggestionsRef.current && !promptSuggestionsRef.current.contains(event.target)) {
        setShowPromptSuggestions(false);
      }
      // Close auto-suggest on outside click
      if (showAutoSuggest && autoSuggestRef.current && !autoSuggestRef.current.contains(event.target)) {
        setShowAutoSuggest(false);
      }
    }
    if (showPromptSuggestions || showAutoSuggest) {
      document.addEventListener("mousedown", handleClickOutside);
    }
    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
    };
  }, [showPromptSuggestions, showAutoSuggest]);

  const [highlightedKbIndex, setHighlightedKbIndex] = useState(-1);

  const verifierSettingsRef = useRef(null);
  const chatSettingsRef = useRef(null);
  const knowledgePopoverRef = useRef(null);
  const knowledgeSearchInputRef = useRef(null);
  const knowledgeListRef = useRef(null);

  const [cachedSuggestions, setCachedSuggestions] = useState({
    user_history: [],
    agent_history: [],
  });

  const [temperature, setTemperature] = useState(0.0);
  const [showTemperaturePopup, setShowTemperaturePopup] = useState(false);
  const temperaturePopupRef = useRef(null);
  const temperatureSliderRef = useRef(null);
  const mentionDropdownRef = useRef(null);
  const mentionListRef = useRef(null);

  // Close temperature popup on outside click
  const [nodes, setNodes] = useState([]); // State to store nodes dynamically
  const [isStreaming, setIsStreaming] = useState(false); // State to track streaming status
  const [currentNodeIndex, setCurrentNodeIndex] = useState(-1); // State to track current node index for progressive display

  const [streamParsedContents, setStreamParsedContents] = useState([]);

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

  // Close mention dropdown on outside click
  useEffect(() => {
    function handleClickOutside(event) {
      // Don't close if clicking the @ button itself
      if (event.target.closest(`.${stylesNew.mentionButton}`)) {
        return;
      }
      if (mentionDropdownRef.current && !mentionDropdownRef.current.contains(event.target)) {
        setShowMentionDropdown(false);
        setMentionSearchTerm("");
        setHighlightedMentionIndex(-1);
      }
    }
    if (showMentionDropdown) {
      document.addEventListener("mousedown", handleClickOutside);
    }
    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
    };
  }, [showMentionDropdown]);

  // Auto-open the @mention dropdown when showMentionDropdown becomes true
  useEffect(() => {
    if (showMentionDropdown && mentionDropdownRef.current) {
      // Small delay to ensure the dropdown is rendered, then click to open it
      const timer = setTimeout(() => {
        const dropdownTrigger = mentionDropdownRef.current?.querySelector('[class*="dropdownTrigger"], [class*="trigger"], button, [role="combobox"]');
        if (dropdownTrigger) {
          dropdownTrigger.click();
        }
      }, 50);
      return () => clearTimeout(timer);
    }
  }, [showMentionDropdown]);

  // Check if verifier is awaiting user action (tool_verifier or plan_verifier active with pending input)
  // This tracks when we're waiting for user to approve/reject in tool/plan verifier flow
  const isAwaitingVerifierAction = (() => {
    if (!messageData || messageData.length === 0) return false;

    // Check if the last BOT message has tool_verifier or plan_verifier awaiting action
    const lastBotMessage = [...messageData].reverse().find((msg) => msg?.type === BOT);
    if (!lastBotMessage) return false;

    // Check if we have tool call details in the message
    const hasToolCallDetails =
      Array.isArray(lastBotMessage?.toolcallData?.additional_details) &&
      lastBotMessage.toolcallData.additional_details.length > 0 &&
      Object.keys(lastBotMessage.toolcallData.additional_details[0]?.additional_kwargs || {}).length > 0;

    const isEmptyMessage = !lastBotMessage?.message || lastBotMessage.message.trim() === "";

    // If the message has actual content (final response received), don't disable - enable input
    // This is the key check: if we have a non-empty message, the verifier flow is complete
    if (!isEmptyMessage) {
      return false;
    }

    // Check if there are parts with content (another indicator of completed response)
    const hasParts = Array.isArray(lastBotMessage?.parts) && lastBotMessage.parts.length > 0 && lastBotMessage.parts.some((p) => p?.data?.content || p?.text || p?.content);
    if (hasParts) {
      return false;
    }

    // Tool Verifier checks - only when message is empty (awaiting approval)
    // For tool interrupt: if message is empty AND we have tool call details, we're awaiting verification
    // This handles both first-time and subsequent tool interrupts (e.g., after user updates values)
    const toolVerifierAwaitingWithDetails = toolInterrupt && hasToolCallDetails && isEmptyMessage;
    const toolVerifierAwaitingStreaming = toolInterrupt && lastBotMessage?.tool_verifier && isEmptyMessage;

    // Plan Verifier checks - only when message is empty (awaiting approval)
    // Similar logic: if plan verifier is on and we have plan_verifier flag or prompt, we're awaiting approval
    const planVerifierAwaitingFlag = isHuman && lastBotMessage?.plan_verifier && isEmptyMessage;
    const planVerifierAwaitingPrompt = isHuman && planVerifierPrompt && isEmptyMessage;
    // Also check if we have a plan array (plan needs verification)
    const planVerifierAwaitingPlan = isHuman && Array.isArray(lastBotMessage?.plan) && lastBotMessage.plan.length > 0 && isEmptyMessage;

    // When BOTH verifiers are enabled, check if either verifier is awaiting action
    if (toolInterrupt && isHuman) {
      return toolVerifierAwaitingWithDetails || toolVerifierAwaitingStreaming || planVerifierAwaitingFlag || planVerifierAwaitingPrompt || planVerifierAwaitingPlan;
    }

    // When only Tool Verifier is enabled
    if (toolInterrupt) {
      return toolVerifierAwaitingWithDetails || toolVerifierAwaitingStreaming;
    }

    // When only Plan Verifier is enabled
    if (isHuman) {
      return planVerifierAwaitingFlag || planVerifierAwaitingPrompt || planVerifierAwaitingPlan;
    }

    // If tool verifier is on and we have an empty message with tool call details awaiting approval
    // This is the main case - tool verifier editor is shown and waiting for user action
    if (toolInterrupt && hasToolCallDetails && (!lastBotMessage?.message || lastBotMessage.message.trim() === "")) {
      return true;
    }

    // If tool verifier is on and we have a tool_verifier message (streaming state)
    if (toolInterrupt && lastBotMessage?.tool_verifier) {
      return true;
    }

    // If plan verifier (isHuman) is on and we have a plan_verifier message awaiting approval
    if (isHuman && lastBotMessage?.plan_verifier) {
      return true;
    }

    return false;
  })();

  // Disable input only for empty BOT bubbles that are not legitimate editor or
  // verifier placeholders. Restricting to BOT avoids blocking user bubbles.
  const messageDisable = (() => {
    // First check if verifier is awaiting action - this takes priority
    if (isAwaitingVerifierAction) return true;

    for (const msg of messageData || []) {
      try {
        if (!msg || msg.type !== "BOT") continue; // only consider bot bubbles
        if (typeof msg.message !== "string") continue;
        if (msg.message.trim() !== "") continue; // not empty -> ok

        const hasToolDetails =
          Array.isArray(msg?.toolcallData?.additional_details) &&
          msg.toolcallData.additional_details.length > 0 &&
          Object.keys(msg.toolcallData.additional_details[0]?.additional_kwargs || {}).length > 0;
        if (hasToolDetails) continue; // editor placeholder -> do not disable

        if (msg?.plan_verifier || msg?.tool_verifier) continue; // verifier -> do not disable

        // Found a stray empty BOT bubble — this should disable input
        // Log for diagnostics so developers can reproduce why input is disabled.
        // eslint-disable-next-line no-console
        console.warn("messageDisable: disabling due to stray empty BOT message:", msg);
        return true;
      } catch (e) {
        // ignore malformed entries
        // eslint-disable-next-line no-console
        console.warn("messageDisable: error while evaluating messageData", e);
      }
    }
    return false;
  })();
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

    setIsTranscribing(true);
    try {
      const data = await postData(APIs.TRANSCRIBE_AUDIO, formData);

      // Update the chat input with transcription, adding space between existing and new text
      if (data && data.transcription) {
        setUserChat((prev) => {
          const trimmed = prev.trimEnd();
          return trimmed ? `${trimmed} ${data.transcription}` : data.transcription;
        });
        setTranscription(data.transcription);
      }
    } catch (error) {
      console.error("Transcription failed:", error);
      setTranscription("Error transcribing audio.");
    } finally {
      setIsTranscribing(false);
    }
  };

  const handlePromptSuggestionsToggle = () => {
    const isOpening = !showPromptSuggestions;
    setShowPromptSuggestions(isOpening);
    setShowAutoSuggest(false); // Close auto-suggest when opening full prompt library
    // When opening via icon click, set flag and reset filtered suggestions
    if (isOpening) {
      setOpenedViaIcon(true); // Mark as opened via icon
      setFilteredAutoSuggestions([]);
      // Fetch suggestions if not already loaded
      if (!promptSuggestions || promptSuggestions.length === 0) {
        fetchPromptSuggestions();
      }
    } else {
      setOpenedViaIcon(false);
    }
  };

  // Filter suggestions based on typed text and show PromptSuggestions panel
  const filterSuggestionsForAutoSuggest = useCallback(
    (typedText) => {
      if (!typedText || typedText.trim().length < 2) {
        // Don't auto-close if user manually opened the panel
        return;
      }

      const searchTerm = typedText.toLowerCase().trim();
      const allSuggestions = promptSuggestions && promptSuggestions.length > 0 ? promptSuggestions : [];

      // Also include cached suggestions from user and agent history
      const combinedSuggestions = [...allSuggestions, ...(cachedSuggestions.user_history || []), ...(cachedSuggestions.agent_history || [])];

      // Remove duplicates and filter by search term
      const uniqueSuggestions = [...new Set(combinedSuggestions)];
      const filtered = uniqueSuggestions.filter((suggestion) => suggestion && suggestion.toLowerCase().includes(searchTerm));

      // If there are matching suggestions, show the PromptSuggestions panel
      if (filtered.length > 0) {
        setFilteredAutoSuggestions(filtered);
        setOpenedViaIcon(false); // When typing, switch to history mode
        setShowPromptSuggestions(true);
      }
    },
    [promptSuggestions, cachedSuggestions],
  );

  // Handle auto-suggest selection
  const handleAutoSuggestSelect = (suggestion) => {
    setUserChat(suggestion);
    setShowAutoSuggest(false);
    setFilteredAutoSuggestions([]);
    calculateHeight(suggestion);
    // Focus textarea and place cursor at end
    setTimeout(() => {
      if (textareaRef.current) {
        textareaRef.current.focus();
        textareaRef.current.selectionStart = textareaRef.current.selectionEnd = suggestion.length;
      }
    }, 0);
  };

  const handlePromptSelect = (prompt) => {
    setUserChat(prompt);
    setShowAutoSuggest(false);
    setShowPromptSuggestions(false);
    setOpenedViaIcon(false);
    calculateHeight();
    // Focus textarea and place cursor at end after selecting prompt
    setTimeout(() => {
      if (textareaRef.current) {
        textareaRef.current.focus();
        textareaRef.current.selectionStart = textareaRef.current.selectionEnd = prompt.length;
      }
    }, 0);
  };

  // If an agent is mentioned via @, use its type for verifier settings
  // Otherwise fall back to selected agent's type or the agentType filter
  const effectiveAgentType =
    mentionedAgent && mentionedAgent.agentic_application_type
      ? mentionedAgent.agentic_application_type
      : selectedAgent && selectedAgent.agentic_application_type
        ? selectedAgent.agentic_application_type
        : agentType;

  const shouldShowHumanVerifier = () => {
    if (!canPlanVerifier) return false;
    return (
      effectiveAgentType === MULTI_AGENT ||
      effectiveAgentType === PLANNER_EXECUTOR_AGENT ||
      effectiveAgentType === "multi_agent" ||
      effectiveAgentType === HYBRID_AGENT ||
      effectiveAgentType === PLANNER_META_AGENT
    );
  };

  const handleLiveTracking = () => {
    window.open(liveTrackingUrl, "_blank");
  };

  const selectAgent = (agent) => {
    // Skip reset if selecting the same agent
    if (selectedAgent?.agentic_application_id === agent?.agentic_application_id) {
      return;
    }
    closeCanvas(); // Close canvas on agent change
    setSelectedAgent(agent);
    // Reset mentioned agent when main agent changes
    setMentionedAgent("");
    // Reset mention agent type filter
    setMentionAgentTypeFilter("all");
    // Reset mention search term
    setMentionSearchTerm("");
  };

  const shouldShowToolVerifier = () => {
    if (userRole === "user") return false;
    return (
      effectiveAgentType === REACT_AGENT ||
      effectiveAgentType === MULTI_AGENT ||
      effectiveAgentType === REACT_CRITIC_AGENT ||
      effectiveAgentType === PLANNER_EXECUTOR_AGENT ||
      effectiveAgentType === "react_agent" ||
      effectiveAgentType === HYBRID_AGENT ||
      effectiveAgentType === META_AGENT ||
      effectiveAgentType === PLANNER_META_AGENT
    );
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

  const handleToolInterrupt = async (isEnabled) => {
    setToolInterrupt(isEnabled);
    setIsTool(isEnabled);

    // Skip tool fetching for PIPELINE_AGENT - pipelines don't have mapped tools
    if (agentType === PIPELINE_AGENT) {
      setShowToolInterruptModal(false);
      return;
    }

    // Determine which agent's tools to fetch - prioritize mentioned agent (@agent) over selected agent
    const effectiveAgentId = mentionedAgent?.agentic_application_id || agentSelectValue;

    // If enabling tool verifier and agent is selected
    if (isEnabled && effectiveAgentId) {
      // If tools are already loaded, just show the modal
      if (mappedTools && mappedTools.length > 0) {
        setShowToolInterruptModal(true);
      } else {
        // Fetch tools if not already loaded
        setLoadingMappedTools(true);
        try {
          const tools = await getToolsMappedByAgent(effectiveAgentId);
          if (tools && Array.isArray(tools)) {
            setMappedTools(tools);
            // Select all tools by default
            setSelectedInterruptTools(tools);
            setShowToolInterruptModal(true);
          }
        } catch (error) {
          console.error("Error fetching mapped tools:", error);
        } finally {
          setLoadingMappedTools(false);
        }
      }
    } else {
      setShowToolInterruptModal(false);
    }
  };

  // Handle toggle of individual interrupt tool
  const handleInterruptToolToggle = (toolName) => {
    setSelectedInterruptTools((prev) => (prev.includes(toolName) ? prev.filter((t) => t !== toolName) : [...prev, toolName]));
  };

  // Handle select all / unselect all interrupt tools
  const handleSelectAllInterruptTools = (selectAll) => {
    if (selectAll) {
      setSelectedInterruptTools([...mappedTools]);
    } else {
      setSelectedInterruptTools([]);
    }
  };

  // Agent types eligible for validator execution assistance
  const validatorEligibleTypes = [MULTI_AGENT, REACT_AGENT, REACT_CRITIC_AGENT, PLANNER_EXECUTOR_AGENT, META_AGENT, PLANNER_META_AGENT];
  const showValidatorToggle = () => validatorEligibleTypes.includes(effectiveAgentType);

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

  const { fetchData, postData, postDataStream } = useFetch();

  const msgContainerRef = useRef(null);
  const hasInitialized = useRef(false);

  // Require all 3 options: agentType, agent, and model
  const isMissingRequiredOptions = !agentSelectValue;

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
    // Reset tool verifier states when agent type changes
    setToolInterrupt(false);
    setIsTool(false);
    setSelectedInterruptTools([]);
    setMappedTools([]);
    setShowToolInterruptModal(false);
    // Reset plan/human verifier states
    setIsHuman(false);
    setIsPlanVerifierOn(false);
    setPlanVerifierPrompt("");
    // Note: Do NOT reset selectedAgent here as it causes the dropdown to clear
    // immediately after selection. The agent is set via selectAgent() in onSelect.
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

  // filteredAgents is used by NewCommonDropdown - filters by selected agent type
  // When "All Types" is selected (agentType is empty), exclude pipeline agents
  // Pipelines only show when explicitly selected via the type filter
  const filteredAgents = agentType
    ? agentListDropdown.filter((agent) => agent.agentic_application_type === agentType)
    : agentListDropdown.filter((agent) => agent.agentic_application_type !== PIPELINE_AGENT);

  useEffect(() => {
    // Reset highlighted index if it's out of bounds
    if (highlightedAgentIndex >= filteredAgents.length) {
      setHighlightedAgentIndex(filteredAgents.length > 0 ? 0 : -1);
    }
  }, [filteredAgents.length, highlightedAgentIndex]);

  useEffect(() => {
    if (showKnowledgePopover && knowledgeSearchInputRef.current) {
      knowledgeSearchInputRef.current.focus();
    }
  }, [showKnowledgePopover]);

  useEffect(() => {
    // Reset previously selected agent value any time agentType or framework changes
    // BUT only if the change is from user manually changing the type filter, not from agent selection
    // Skip reset if we already have an agent selected with matching type
    // Also skip reset if agentType is "all" (empty string) - user may be browsing without filtering
    if (selectedAgent) {
      const isTypeMatch = selectedAgent.agentic_application_type === agentType;
      const isAllFilter = !agentType || agentType === "all" || agentType === "All agent type";
      if (isTypeMatch || isAllFilter) {
        // Agent type matches selected agent OR user is viewing all - don't reset
        // Just update the dropdown list without resetting agent selection
        if (!agentsListData || agentsListData.length === 0) {
          setAgentListDropdown([]);
          return;
        }
        // Update dropdown list based on filter
        if (agentType === PIPELINE_AGENT) {
          const pipelineAgents = agentsListData?.filter((agent) => agent.agentic_application_type === PIPELINE_AGENT) || [];
          setAgentListDropdown(pipelineAgents);
        } else if (isAllFilter) {
          let allowedTypes = [];
          if (chat_screen_config[framework] && Array.isArray(chat_screen_config[framework].mentionAgentTypes)) {
            allowedTypes = chat_screen_config[framework].mentionAgentTypes;
          }
          let filteredTypes = allowedTypes;
          if (["google_adk", "langgraph"].includes(framework)) {
            filteredTypes = allowedTypes.filter((type) => type !== HYBRID_AGENT);
          }
          const tempList = agentsListData?.filter((list) => filteredTypes.length === 0 || filteredTypes.includes(list.agentic_application_type)) || [];
          setAgentListDropdown(tempList);
        } else {
          const tempList = agentsListData?.filter((list) => list.agentic_application_type === agentType) || [];
          setAgentListDropdown(tempList);
        }
        return;
      }
    }
    // If we get here, user changed the type filter to a different type - reset agent selection
    setAgentSelectValue("");
    setSelectedAgent("");
    setMentionedAgent("");
    setMentionAgentTypeFilter("all");
    setMentionSearchTerm("");
    const cookieSessionId = Cookies.get("user_session");
    if (cookieSessionId) {
      setSessionId(cookieSessionId);
    }

    // If no agents data, clear the dropdown list
    if (!agentsListData || agentsListData.length === 0) {
      setAgentListDropdown([]);
      return;
    }

    // Handle Pipeline type - filter pipelines from agentsListData
    if (agentType === PIPELINE_AGENT) {
      const pipelineAgents = agentsListData?.filter((agent) => agent.agentic_application_type === PIPELINE_AGENT) || [];
      setAgentListDropdown(pipelineAgents);
      return;
    }

    // Framework-based filtering for "all" agent types
    if (!agentType || agentType === "all" || agentType === "All agent type") {
      let allowedTypes = [];

      // Get allowed agent types based on framework from chat_screen_config
      if (chat_screen_config[framework] && Array.isArray(chat_screen_config[framework].mentionAgentTypes)) {
        allowedTypes = chat_screen_config[framework].mentionAgentTypes;
      }

      // Exclude hybrid_agent for google_adk and langgraph frameworks
      let filteredTypes = allowedTypes;
      if (["google_adk", "langgraph"].includes(framework)) {
        filteredTypes = allowedTypes.filter((type) => type !== HYBRID_AGENT);
      }

      // Filter agents based on allowed types for the selected framework
      const tempList = agentsListData?.filter((list) => filteredTypes.length === 0 || filteredTypes.includes(list.agentic_application_type)) || [];

      setAgentListDropdown(tempList);
    } else {
      // Filter by specific agent type
      const tempList = agentsListData?.filter((list) => list.agentic_application_type === agentType) || [];
      setAgentListDropdown(tempList);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [agentType, agentsListData, framework]);

  useEffect(() => {
    // Only fetch history when agent changes or options are selected, not on model change
    if (!isMissingRequiredOptions && agentSelectValue) {
      fetchChatHistory();
      fetchOldChatsData();
    } else if (isMissingRequiredOptions) {
      setMessageData([]);
    }
  }, [agentSelectValue, isMissingRequiredOptions]); // Removed model from dependencies
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
  }, [messageData, generating, fetching, isStreaming]);

  // Auto-focus textarea when agent response completes (streaming/generating ends)
  useEffect(() => {
    if (!generating && !isStreaming && !fetching && textareaRef.current) {
      // Small delay to ensure UI is ready
      setTimeout(() => {
        textareaRef.current?.focus();
      }, 100);
    }
  }, [generating, isStreaming, fetching]);

  useEffect(() => {
    const handleClickOutside = (event) => {
      if (bullseyeRef.current && !bullseyeRef.current.contains(event.target)) {
        setShowModelPopover(false);
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

  // Re-fetch prompt suggestions when mentioned agent changes
  useEffect(() => {
    if (agentSelectValue || (mentionedAgent && mentionedAgent.agentic_application_id)) {
      fetchPromptSuggestions();
    }
  }, [mentionedAgent]);

  // Fetch tools when @mentioned agent changes (select or deselect)
  useEffect(() => {
    // Skip for PIPELINE_AGENT
    if (agentType === PIPELINE_AGENT) return;
    // Prioritize mentioned agent, fallback to selected agent
    const targetAgentId = mentionedAgent && mentionedAgent.agentic_application_id ? mentionedAgent.agentic_application_id : agentSelectValue;
    fetchMappedTools(targetAgentId);
  }, [mentionedAgent]);

  // Fetch tools and prompt suggestions when selected agent changes
  useEffect(() => {
    // Skip for PIPELINE_AGENT
    if (agentType === PIPELINE_AGENT) return;

    if (agentSelectValue) {
      fetchMappedTools(agentSelectValue);
      fetchPromptSuggestions();
    }
  }, [agentSelectValue]);

  // Auto-show tool interrupt modal when tools are loaded and tool verifier is enabled
  useEffect(() => {
    if (toolInterrupt && mappedTools && mappedTools.length > 0) {
      setShowToolInterruptModal(true);
    }
  }, [toolInterrupt, mappedTools]);

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

  /**
   * Safely converts a value to a trimmed string.
   * Handles arrays, objects, null, undefined, and primitive types.
   * @param {*} value - The value to convert
   * @returns {string} - A trimmed string representation
   */
  const safeStringify = (value) => {
    if (value === null || value === undefined) {
      return "";
    }
    if (typeof value === "string") {
      return value.trim();
    }
    if (Array.isArray(value)) {
      // Join array elements, filtering out non-string/empty values
      return value
        .map((item) => (typeof item === "string" ? item : JSON.stringify(item)))
        .filter(Boolean)
        .join("\n")
        .trim();
    }
    if (typeof value === "object") {
      try {
        return JSON.stringify(value, null, 2);
      } catch {
        return "";
      }
    }
    // For numbers, booleans, etc.
    return String(value).trim();
  };

  const converToChatFormat = (chatHistory) => {
    const chats = [];
    setPlanData(null);
    if (chatHistory && chatHistory[branchInteruptKey] === branchInteruptValue) {
      setFeedback("no");
      setShowInput(true);
    }

    chatHistory?.executor_messages?.forEach((item, index) => {
      // USER bubble
      // NOTE: "start_timestamp" is the canonical backend field.
      // "time_stamp" is treated as a legacy/alternate field name and is only
      // used as a fallback for backward compatibility with older responses.
      // For the very first message, if neither field is present on the item,
      // we fall back to chatHistory.start_timestamp.
      // Also check existing messageData for client-side timestamps that backend may not have.
      const existingUserMsg = messageData.find((msg) => msg.type === USER && msg.message === item?.user_query && msg.start_timestamp);
      chats.push({
        type: USER,
        message: item?.user_query,
        start_timestamp:
          existingUserMsg?.start_timestamp ||
          item?.start_timestamp ||
          item?.time_stamp ||
          (index === 0 ? chatHistory?.start_timestamp : null) ||
          null,
        end_timestamp: item?.end_timestamp || null,
      });

      // Determine bot message (prefer canonical fields) - using safeStringify for robustness
      let botMessage = safeStringify(item?.final_response) || safeStringify(item?.response) || safeStringify(item?.message) || safeStringify(item?.content) || "";

      // If server returned tools_used (alternate shape), synthesize a canonical additional_details
      // so downstream UI (ToolCallFinalResponse) can always find tool call arguments.
      let synthesizedAdditionalDetails = null;
      if (item?.tools_used && (!Array.isArray(item?.additional_details) || item.additional_details.length === 0)) {
        try {
          const toolCalls = Object.entries(item.tools_used).map(([callId, tu]) => {
            const argsObj = tu?.arguments ?? tu?.args ?? {};
            const serializedArgs = typeof argsObj === "string" ? argsObj : JSON.stringify(argsObj || {});
            return {
              id: callId,
              function: {
                name: tu?.name || tu?.tool_name || callId,
                arguments: serializedArgs,
              },
              output: tu?.output ?? tu?.tool_output ?? null,
            };
          });
          synthesizedAdditionalDetails = [
            {
              additional_kwargs: {
                tool_calls: toolCalls,
              },
            },
          ];
        } catch (e) {
          synthesizedAdditionalDetails = null;
        }
      }

      // If we synthesized additional_details, attach it to a copy of the item so downstream code sees it
      const toolcallData = {
        ...item,
        ...(synthesizedAdditionalDetails ? { additional_details: synthesizedAdditionalDetails } : {}),
      };

      // If tool-verifier is enabled globally and we have tool-call metadata, blank the bot message
      // so the UI will show the ToolCallFinalResponse editor (MsgBox expects empty message for the editor gate).
      if (toolInterrupt && Array.isArray(toolcallData.additional_details) && toolcallData.additional_details.length > 0) {
        botMessage = "";
      }

      // Additional fallbacks for META_AGENT / PLANNER_META_AGENT when no message found yet
      // Try extracting from parts array
      if (!botMessage && Array.isArray(item?.parts) && item.parts.length > 0) {
        const partsText = item.parts.map((p) => safeStringify(p?.data?.content) || safeStringify(p?.text) || safeStringify(p?.content)).filter((t) => t.length > 0);
        if (partsText.length > 0) {
          botMessage = partsText.join("\n\n");
        }
      }

      // HIDDEN TEMP
      // // Try extracting from tools_used output (first tool)
      // if (!botMessage && item?.tools_used) {
      //   const firstTool = Object.values(item.tools_used)[0];
      //   if (firstTool?.output) {
      //     botMessage = safeStringify(firstTool.output);
      //   }
      // }

      // Try extracting from agent_response field (some meta agent responses use this)
      if (!botMessage && item?.agent_response) {
        botMessage = safeStringify(item.agent_response);
      }

      chats.push({
        type: BOT,
        message: botMessage,
        toolcallData: toolcallData,
        userText: item?.user_query || chatHistory?.query || "",
        steps: JSON.stringify(item?.agent_steps, null, "\t"),
        debugExecutor: item?.additional_details,
        // ...(index === chatHistory?.executor_messages?.length - 1 &&
        //   !botMessage &&
        //   !(toolInterrupt && Array.isArray(toolcallData?.additional_details) && toolcallData.additional_details.length > 0) && { plan: chatHistory?.plan }),
        parts: item?.parts || [],
        show_canvas: item?.show_canvas || false,
        response_time: item?.response_time || chatHistory?.response_time || null,
        start_timestamp: item?.start_timestamp || null,
        end_timestamp: item?.end_timestamp || null,
      });
    });

    setPlanData(null);
    setToolData(chats?.toolcallData);
    return chats;
  };

  const fetchChatHistory = async (sessionId = session) => {
    try {
      const data = {
        session_id: sessionId,
        agent_id: agentType === CUSTOM_TEMPLATE ? customTemplatId : agentSelectValue,
        framework_type: framework,
      };
      const chatHistory = await getChatHistory(data);

      if (chatHistory) {
        setLastResponse(chatHistory);
        setNodes([]);
        setIsStreaming(false);
        setCurrentNodeIndex(-1);
        setStreamParsedContents([]);
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
    // Prioritize mentioned agent, fallback to selected agent
    const targetAgentId = mentionedAgent && mentionedAgent.agentic_application_id ? mentionedAgent.agentic_application_id : agentSelectValue;

    const payload = {
      agentic_application_id: targetAgentId,
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

  // Fetch tools mapped by agent - called when agent or @mentioned agent changes
  const fetchMappedTools = async (agentId) => {
    // Skip for PIPELINE_AGENT - pipelines don't have mapped tools
    if (agentType === PIPELINE_AGENT) {
      setMappedTools([]);
      setSelectedInterruptTools([]);
      return;
    }
    if (!agentId) {
      setMappedTools([]);
      setSelectedInterruptTools([]);
      return;
    }
    try {
      const tools = await getToolsMappedByAgent(agentId);
      if (tools && Array.isArray(tools)) {
        setMappedTools(tools);
        setSelectedInterruptTools(tools);
      } else {
        setMappedTools([]);
        setSelectedInterruptTools([]);
      }
    } catch (error) {
      console.error("Error fetching mapped tools:", error);
      setMappedTools([]);
      setSelectedInterruptTools([]);
    }
  };

  const addMessageData = (type, message, steps, plan, userText, start_timestamp = null, end_timestamp = null, attachedFiles = null) => {
    setMessageData((prevProp) => [...prevProp, { type, message, steps, plan, userText, start_timestamp, end_timestamp, attachedFiles }]);
  };

  const sendHumanInLoop = async (isApprove = "", feedBack = "", userText) => {
    // Enable streaming for human verifier scenarios to capture transient plan_verifier prompt
    setIsStreaming(true);
    //setNodes([]);
    setCurrentNodeIndex(-1);
    setPlanVerifierPrompt("");
    const payload = {
      framework_type: framework,
      agentic_application_id: agentType === CUSTOM_TEMPLATE ? customTemplatId : agentSelectValue,
      query: userText,
      session_id: oldSessionId !== "" ? oldSessionId : session,
      model_name: model,
      temperature: temperature,
      reset_conversation: false,
      is_plan_approved: isApprove !== "" ? isApprove : null,
      plan_feedback: feedBack !== "" ? feedBack : null,
      tool_verifier_flag: canToolVerifier ? Boolean(toolInterrupt) : false,
      plan_verifier_flag: canPlanVerifier ? Boolean(isHuman) : false,
      response_formatting_flag: Boolean(isCanvasEnabled),
      context_flag: Boolean(isContextEnabled),
      file_context_management_flag: Boolean(isFileContextEnabled),
      evaluation_flag: Boolean(onlineEvaluatorFlag),
      mentioned_agentic_application_id: mentionedAgent && mentionedAgent.agentic_application_id ? mentionedAgent.agentic_application_id : null,
      validator_flag: useValidator,
      enable_streaming_flag: true,
      message_queue: Boolean(isMessageQueueEnabled),
      ...(toolInterrupt && { interrupt_items: selectedInterruptTools }),
    };

    if (selectedValues && selectedValues.length > 0) {
      const selectedString = selectedValues.join(",");
      payload.knowledgebase_name = JSON.stringify(selectedString);
    }
    try {
      // Abort any existing stream before starting a new one
      if (abortControllerRef.current) {
        abortControllerRef.current.abort();
      }
      abortControllerRef.current = new AbortController();

      // let nodeIndex = -1;
      let nodeIndex = Array.isArray(nodes) ? nodes.length - 1 : -1;
      const onStreamChunk = async (obj) => {
        if (!obj || typeof obj !== "object") return;

        // Handle error events from SSE stream
        if (obj.event_type === "error" || obj.error) {
          const errorMessage = obj.message || obj.error || "An error occurred during processing";
          addMessage(errorMessage, "error");
          return;
        }
        const nodeName = obj["Node Name"] || obj.node_name || obj.node || obj.name || null;
        const statusVal = obj.Status || obj.status || obj.state || null;
        const toolName = obj["Tool Name"] || obj.tool_name || (obj.raw && (obj.raw["Tool Name"] || obj.raw.tool_name)) || null;

        // Extract content from multiple possible fields
        let contentVal = null;
        if (obj.content && typeof obj.content === "string") {
          contentVal = obj.content;
        } else if (obj["Tool Output"]) {
          const toolOutput = obj["Tool Output"];
          contentVal = typeof toolOutput === "string" ? toolOutput : JSON.stringify(toolOutput);
        } else if (obj.raw) {
          if (obj.raw.content) {
            contentVal = typeof obj.raw.content === "string" ? obj.raw.content : JSON.stringify(obj.raw.content);
          } else if (obj.raw["Tool Output"]) {
            const rawToolOutput = obj.raw["Tool Output"];
            contentVal = typeof rawToolOutput === "string" ? rawToolOutput : JSON.stringify(rawToolOutput);
          }
        }

        if (nodeName && statusVal) {
          nodeIndex++;
          const newNode = {
            "Node Name": nodeName,
            Status: statusVal,
            "Tool Name": toolName,
            ...(obj["Tool Output"] && { "Tool Output": obj["Tool Output"] }),
            ...(contentVal && { content: contentVal }),
          };
          setNodes((prev) => [...prev, newNode]);
          setCurrentNodeIndex(nodeIndex);
        } else if (contentVal) {
          // Orphan content chunk - add as content-only entry
          setNodes((prev) => [...prev, { content: contentVal }]);
        }

        if (contentVal) {
          const source = nodeName || (obj.raw && (obj.raw["Tool Name"] || obj.raw.tool_name)) || "raw" || obj.content;
          setStreamParsedContents((prev) => [...prev, { source, content: contentVal }]);
        }

        // if (isHuman && obj?.raw?.plan_verifier) {
        //   setPlanVerifierPrompt(obj.raw.plan_verifier);
        //   // Capture plan from the streaming object if available (for plan verifier display)
        //   const streamPlan = obj?.plan || obj?.raw?.plan || null;
        //   if (streamPlan) {
        //     setPlanData(streamPlan);
        //   }
        //   // Capture query from the object for feedback handling
        //   const queryText = obj?.query || userText || "";
        //   setMessageData((prev) => {
        //     if (prev.some((m) => m.plan_verifier)) return prev;
        //     return [
        //       ...prev,
        //       {
        //         type: BOT,
        //         message: obj.raw.plan_verifier,
        //         plan_verifier: true,
        //         plan: streamPlan || null,
        //         userText: queryText,
        //       },
        //     ];
        //   });
        // }

        // // Tool verifier prompt (in case both enabled)
        // if (toolInterrupt && obj?.raw?.tool_verifier) {
        //   setMessageData((prev) => {
        //     if (prev.some((m) => m.tool_verifier)) return prev;
        //     return [...prev, { type: BOT, message: obj.raw.tool_verifier, tool_verifier: true }];
        //   });
        // }
        await new Promise((r) => setTimeout(r, 450));
      };
      const responseObjects = await postDataStream(APIs.CHAT_INFERENCE, payload, { signal: abortControllerRef.current.signal }, onStreamChunk);
      // Find response with executor_messages, or fallback to response with plan (for plan verifier)
      const chatObj = Array.isArray(responseObjects) ? responseObjects.find((obj) => obj && obj.executor_messages) : responseObjects;
      setLastResponse(chatObj);
      setPlanData(chatObj?.plan || null);
      setCurrentNodeIndex(nodeIndex);

      // If plan verifier is active and we have a plan but no executor_messages, preserve the plan verifier message
      if (isHuman && chatObj?.plan && (!chatObj?.executor_messages || chatObj.executor_messages.length === 0)) {
        // Don't overwrite - the plan verifier message was already set during streaming
        // Just update the plan data and ensure the message has the plan
        setMessageData((prev) => {
          const updated = [...prev];
          const planVerifierIdx = updated.findIndex((m) => m.plan_verifier);
          if (planVerifierIdx !== -1 && !updated[planVerifierIdx].plan) {
            updated[planVerifierIdx] = { ...updated[planVerifierIdx], plan: chatObj.plan };
          }
          return updated;
        });
      } else {
        const chatData = chatObj ? converToChatFormat(chatObj) || [] : [];
        // Preserve client-side timestamps for USER messages that backend may not have returned
        setMessageData((prev) => {
          const userTimestampMap = new Map();
          prev.forEach((msg) => {
            if (msg.type === USER && msg.start_timestamp) {
              userTimestampMap.set(msg.message, msg.start_timestamp);
            }
          });
          // Merge existing user timestamps into new chat data
          return chatData.map((item) => {
            if (item.type === USER && !item.start_timestamp && userTimestampMap.has(item.message)) {
              return { ...item, start_timestamp: userTimestampMap.get(item.message) };
            }
            return item;
          });
        });
      }

      // Canvas handling: prefer latest executor message to avoid showing stale canvas
      if (payload.response_formatting_flag === true && chatObj) {
        const latestExecutor =
          Array.isArray(chatObj?.executor_messages) && chatObj.executor_messages.length > 0 ? chatObj.executor_messages[chatObj.executor_messages.length - 1] : null;
        const detectedFromLatest = latestExecutor ? detectCanvasContent(latestExecutor) : null;
        // When tool verifier or human plan verifier are active, avoid using chat-level fallback
        const detectedFallback = !toolInterrupt && !isHuman ? detectCanvasContent(chatObj) : null;
        const detected = detectedFromLatest || detectedFallback;
        if (detected && detected.content) {
          try {
            const existingStr = prevCanvasRef.current || null;
            const newStr = JSON.stringify(detected.content);
            if (existingStr !== newStr) {
              openCanvas(detected.content, detected.title, detected.type, null, false);
              prevCanvasRef.current = newStr;
            }
          } catch (e) {
            openCanvas(detected.content, detected.title, detected.type, null, false);
            try {
              prevCanvasRef.current = JSON.stringify(detected.content);
            } catch { }
          }
        }
      }
    } catch (error) {
      console.error("Error handling human-in-loop streaming response:", error);
    } finally {
      setIsStreaming(false);
      setCurrentNodeIndex(-1);
    }
  };

  const extractContent = (responseArray = []) => {
    return responseArray.reduce(
      (acc, item) => {
        if (!item || typeof item !== "object") return acc;

        // Content objects: either explicit 'content' or raw.Tool Output
        if (item.content) {
          acc.contents.push({
            source: item["Node Name"] || (item.raw && item.raw["Tool Name"]) || "unknown",
            content: item.content,
          });
        }
        return acc;
      },
      { contents: [] },
    );
  };

  // Reconstructed (async) sendUserMessage after accidental brace corruption
  const sendUserMessage = async (overrideText) => {
    let messageToSend = "";
    let contextFlag = false;
    let responseFormattingFlag = false;

    if (overrideText && typeof overrideText === "object") {
      messageToSend = overrideText.query ? String(overrideText.query).trim() : "";
      contextFlag = overrideText.context_flag === true;
      responseFormattingFlag = overrideText.response_formatting_flag === true;
    } else {
      messageToSend = overrideText !== undefined ? String(overrideText).trim() : userChat.trim();
    }
    if (!messageToSend || generating) return;

    setFetching(true);
    setFeedback(""); // Reset feedback state for new query so plan verifier buttons show
    resetHeight();
    // Always enable streaming to capture plan/tool verifier prompts and node progress
    setIsStreaming(true);
    setNodes([]);
    setCurrentNodeIndex(-1);
    setStreamParsedContents([]); // Clear stream contents after completion
    setPlanVerifierPrompt("");
    // Close prompt suggestions popup when sending a message
    setShowPromptSuggestions(false);
    setOpenedViaIcon(false);
    // Capture the start timestamp when user sends the message
    const userMessageTimestamp = new Date().toISOString();
    // Pass uploaded files along with the message
    const filesToAttach = uploadedChatFiles.length > 0 ? [...uploadedChatFiles] : null;
    addMessageData(USER, messageToSend, null, null, null, userMessageTimestamp, null, filesToAttach);
    setUserChat("");
    setGenerating(true);
    setLikeIcon(false);
    setSuggestionVisible(false);

    const payload = {
      framework_type: framework,
      agentic_application_id: agentType === CUSTOM_TEMPLATE ? customTemplatId : agentSelectValue,
      query: messageToSend,
      session_id: oldSessionId !== "" ? oldSessionId : session,
      model_name: model,
      temperature: temperature,
      reset_conversation: false,
      tool_verifier_flag: canToolVerifier ? Boolean(toolInterrupt) : false,
      plan_verifier_flag: canPlanVerifier ? Boolean(isHuman) : false,
      response_formatting_flag: typeof overrideText === "object" ? Boolean(responseFormattingFlag) : Boolean(isCanvasEnabled),
      context_flag: typeof overrideText === "object" ? Boolean(contextFlag) : Boolean(isContextEnabled),
      file_context_management_flag: Boolean(isFileContextEnabled),
      evaluation_flag: canEvaluation ? Boolean(onlineEvaluatorFlag) : false,
      mentioned_agentic_application_id: mentionedAgent && mentionedAgent.agentic_application_id ? mentionedAgent.agentic_application_id : null,
      validator_flag: useValidator,
      enable_streaming_flag: true,
      message_queue: Boolean(isMessageQueueEnabled),
      ...(toolInterrupt && { interrupt_items: selectedInterruptTools }),
      ...(uploadedChatFiles.length > 0 && { uploaded_files: uploadedChatFiles.map((f) => f.path) }),
    };

    if (selectedValues && selectedValues.length > 0) {
      const selectedString = selectedValues.join(",");
      payload.knowledgebase_name = JSON.stringify(selectedString);
    }

    // Remember previously displayed canvas snapshot so we can avoid re-opening identical content
    prevCanvasRef.current = canvasContent ? JSON.stringify(canvasContent) : null;
    // Close and clear existing canvas state immediately so old content won't re-open
    setIsCanvasOpen(false);
    setCanvasContent(null);
    setCanvasTitle("");
    setCanvasContentType("");
    setCanvasMessageId(null);

    // Clear uploaded files after sending message
    const filesToClear = [...uploadedChatFiles];

    if (isHuman) {
      await sendHumanInLoop("", "", messageToSend);
    } else {
      try {
        // Abort any existing stream before starting a new one
        if (abortControllerRef.current) {
          abortControllerRef.current.abort();
        }
        abortControllerRef.current = new AbortController();

        let nodeIndex = -1;
        const onStreamChunk = async (obj) => {
          if (!obj || typeof obj !== "object") return;
          if (nodeIndex < 5) {
            console.debug("[stream-chunk]", obj);
          }

          // Handle error events from SSE stream
          if (obj.event_type === "error" || obj.error) {
            const errorMessage = obj.message || obj.error || "An error occurred during processing";
            addMessage(errorMessage, "error");
            return;
          }

          const nodeName = obj["Node Name"] || obj.node_name || obj.node || obj.name || null;
          const statusVal = obj.Status || obj.status || obj.state || null;
          const toolName = obj["Tool Name"] || obj.tool_name || (obj.raw && (obj.raw["Tool Name"] || obj.raw.tool_name)) || null;

          // Extract content from multiple possible fields
          let contentVal = null;
          if (obj.content && typeof obj.content === "string") {
            contentVal = obj.content;
          } else if (obj["Tool Output"]) {
            const toolOutput = obj["Tool Output"];
            contentVal = typeof toolOutput === "string" ? toolOutput : JSON.stringify(toolOutput);
          } else if (obj.raw) {
            if (obj.raw.content) {
              contentVal = typeof obj.raw.content === "string" ? obj.raw.content : JSON.stringify(obj.raw.content);
            } else if (obj.raw["Tool Output"]) {
              const rawToolOutput = obj.raw["Tool Output"];
              contentVal = typeof rawToolOutput === "string" ? rawToolOutput : JSON.stringify(rawToolOutput);
            }
          }

          if (nodeName && statusVal) {
            nodeIndex++;
            const newNode = {
              "Node Name": nodeName,
              Status: statusVal,
              "Tool Name": toolName,
              ...(obj["Tool Output"] && { "Tool Output": obj["Tool Output"] }),
              ...(contentVal && { content: contentVal }),
            };
            setNodes((prev) => [...prev, newNode]);
            setCurrentNodeIndex(nodeIndex);
          } else if (contentVal) {
            // Orphan content chunk - add as content-only entry
            setNodes((prev) => [...prev, { content: contentVal }]);
          }

          if (contentVal) {
            const source = nodeName || (obj.raw && (obj.raw["Tool Name"] || obj.raw.tool_name)) || "raw" || obj.content;
            setStreamParsedContents((prev) => [...prev, { source, content: contentVal }]);
          }
          // // Tool verifier prompt streaming early (before final executor_messages) -> inject a provisional BOT bubble
          // if (toolInterrupt && obj?.raw?.tool_verifier) {
          //   setMessageData((prev) => {
          //     if (prev.some((m) => m.tool_verifier)) return prev;
          //     return [...prev, { type: BOT, message: obj.raw.tool_verifier, tool_verifier: true }];
          //   });
          // }
          // Plan verifier prompt (human verifier) arrives before final response; capture & surface it immediately
          // if (isHuman && obj?.raw?.plan_verifier) {
          //   setPlanVerifierPrompt(obj.raw.plan_verifier);
          //   // Capture plan from the streaming object if available (for plan verifier display)
          //   const streamPlan = obj?.plan || obj?.raw?.plan || null;
          //   if (streamPlan) {
          //     setPlanData(streamPlan);
          //   }
          //   // Capture query from the object for feedback handling
          //   const queryText = obj?.query || messageToSend || "";
          //   setMessageData((prev) => {
          //     // Avoid duplicate insertion
          //     if (prev.some((m) => m.plan_verifier)) return prev;
          //     return [
          //       ...prev,
          //       {
          //         type: BOT,
          //         message: obj.raw.plan_verifier,
          //         plan_verifier: true,
          //         plan: streamPlan || null,
          //         userText: queryText,
          //       },
          //     ];
          //   });
          // }
          // slight delay to avoid UI thrash
          await new Promise((resolve) => setTimeout(resolve, 150));
        };

        // Call postDataStream with the callback and abort signal
        const responseObjects = await postDataStream(APIs.CHAT_INFERENCE, payload, { signal: abortControllerRef.current.signal }, onStreamChunk);

        // Parse content from mixed response array
        if (Array.isArray(responseObjects)) {
          const { contents: parsedContents } = extractContent(responseObjects);
          setStreamParsedContents(parsedContents);
        }

        // Find response with executor_messages, or fallback to response with plan (for plan verifier)
        const chatObj = Array.isArray(responseObjects) ? responseObjects.find((obj) => obj && (obj.executor_messages || obj.plan)) : responseObjects;

        // Ensure response_time is captured even if it arrived in a separate stream chunk
        if (chatObj && !chatObj.response_time && Array.isArray(responseObjects)) {
          const chunkWithTime = [...responseObjects].reverse().find((o) => o && o.response_time);
          if (chunkWithTime) {
            chatObj.response_time = chunkWithTime.response_time;
          }
        }

        setLastResponse(chatObj);

        if (chatObj === null) {
          setShowToast(true);
          setTimeout(() => {
            setShowToast(false);
          }, AUTO_HIDE_TIMEOUT);
        }

        // Call prompt suggestion API to fetch latest suggestions based on new chat history
        fetchPromptSuggestions();

        // If plan verifier is active and we have a plan but no executor_messages, preserve the plan verifier message
        if (isHuman && chatObj?.plan && (!chatObj?.executor_messages || chatObj.executor_messages.length === 0)) {
          // Don't overwrite - the plan verifier message was already set during streaming
          // Just update the plan data and ensure the message has the plan
          setPlanData(chatObj.plan);
          setMessageData((prev) => {
            const updated = [...prev];
            const planVerifierIdx = updated.findIndex((m) => m.plan_verifier);
            if (planVerifierIdx !== -1 && !updated[planVerifierIdx].plan) {
              updated[planVerifierIdx] = { ...updated[planVerifierIdx], plan: chatObj.plan };
            }
            return updated;
          });
        } else {
          const chatData = chatObj ? converToChatFormat(chatObj) || [] : [];
          // Preserve client-side timestamps for USER messages that backend may not have returned
          setMessageData((prev) => {
            const userTimestampMap = new Map();
            prev.forEach((msg) => {
              if (msg.type === USER && msg.start_timestamp) {
                userTimestampMap.set(msg.message, msg.start_timestamp);
              }
            });
            // Merge existing user timestamps into new chat data
            return chatData.map((item) => {
              if (item.type === USER && !item.start_timestamp && userTimestampMap.has(item.message)) {
                return { ...item, start_timestamp: userTimestampMap.get(item.message) };
              }
              return item;
            });
          });
        }

        // Stop streaming; retain final nodes & contents for display until next user query
        setIsStreaming(false);
        // Keep focus on the last streamed node so MsgBox shows its final status instead of the generic 'Generating'
        setCurrentNodeIndex(-1);
        // Clear streamed contents after they have been displayed
        setStreamParsedContents([]);

        // Canvas handling: prefer latest executor message to avoid showing stale canvas
        if (payload.response_formatting_flag === true && chatObj) {
          const latestExecutor =
            Array.isArray(chatObj?.executor_messages) && chatObj.executor_messages.length > 0 ? chatObj.executor_messages[chatObj.executor_messages.length - 1] : null;
          const detectedFromLatest = latestExecutor ? detectCanvasContent(latestExecutor) : null;
          const detectedFallback = !toolInterrupt && !isHuman ? detectCanvasContent(chatObj) : null;
          const detected = detectedFromLatest || detectedFallback;
          if (detected && detected.content) {
            try {
              const existingStr = prevCanvasRef.current || null;
              const newStr = JSON.stringify(detected.content);
              if (existingStr !== newStr) {
                openCanvas(detected.content, detected.title, detected.type, null, false);
                prevCanvasRef.current = newStr;
              }
            } catch (e) {
              openCanvas(detected.content, detected.title, detected.type, null, false);
              try {
                prevCanvasRef.current = JSON.stringify(detected.content);
              } catch { }
            }
          }
        }
      } catch (error) {
        // Abort errors are expected when user cancels — ignore silently
        if (error.name === "AbortError") {
          console.debug("Chat request aborted by user");
        } else {
          console.error("Error handling chat response:", error);
          const isNetworkError =
            error instanceof TypeError && error.message === "Failed to fetch";
          const friendlyMsg = isNetworkError
            ? "Unable to reach the server. Please check your network connection and try again."
            : error.message || "Something went wrong. Please try again.";
          addMessage(friendlyMsg, "error");
        }
        setIsStreaming(false);
      }
    }
    setGenerating(false);
    setFetching(false);
    setSelectedValues("");
    // Clear uploaded files after message is sent
    setUploadedChatFiles([]);
    // Keep focus on chat input after sending message
    if (textareaRef.current) {
      textareaRef.current.focus();
    }
  };

  const handleKeyDown = (event) => {
    // Handle auto-suggest navigation
    if (showAutoSuggest && filteredAutoSuggestions.length > 0) {
      if (event.key === "ArrowDown") {
        event.preventDefault();
        setHighlightedAutoSuggestIndex((prev) => (prev < filteredAutoSuggestions.length - 1 ? prev + 1 : 0));
        return;
      } else if (event.key === "ArrowUp") {
        event.preventDefault();
        setHighlightedAutoSuggestIndex((prev) => (prev > 0 ? prev - 1 : filteredAutoSuggestions.length - 1));
        return;
      } else if (event.key === "Enter" && !event.shiftKey) {
        event.preventDefault();
        handleAutoSuggestSelect(filteredAutoSuggestions[highlightedAutoSuggestIndex]);
        return;
      } else if (event.key === "Escape") {
        event.preventDefault();
        setShowAutoSuggest(false);
        return;
      }
    }

    // Default behavior
    if (event.key === "Enter" && !event.shiftKey) {
      sendUserMessage(event.target.value);
      resetHeight();
    } else if (event.shiftKey && event.key === "Enter") {
      event.preventDefault();
      const textarea = event.target;
      const start = textarea.selectionStart;
      const end = textarea.selectionEnd;
      const value = textarea.value;
      // Insert newline at cursor position
      const newValue = value.substring(0, start) + "\n" + value.substring(end);
      setUserChat(newValue);
      calculateHeight(newValue);
      // Set cursor position after the newline (need to do this after React updates the DOM)
      setTimeout(() => {
        textarea.selectionStart = textarea.selectionEnd = start + 1;
      }, 0);
    }
  };

  const handleFrameworkChange = (selectedFramework) => {
    closeCanvas();
    setFramework(selectedFramework);
    // Reset all states similar to handleTypeChange
    setAgentType("");
    // Keep model value when framework changes
    setTemperature(0.0);
    setSelectedAgent("");
    setAgentSelectValue("");
    setMessageData([]);
    setMentionedAgent("");
    setMentionAgentTypeFilter("all");
    setMentionSearchTerm("");
    setLikeIcon(false);
    setFeedback("");
    setShowInput(false);
    setOldSessionId("");
    setIsHuman(false);
    setToolInterrupt(false);
    setIsTool(false);
    setUseValidator(false);
    setIsCanvasEnabled(true);
    setIsContextEnabled(false);
    setOnlineEvaluatorFlag(false);
    // Ensure we use cookie session ID when changing framework
    const cookieSessionId = Cookies.get("user_session");
    if (cookieSessionId) {
      setSessionId(cookieSessionId);
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
      selectedOption === "react_agent" ||
      selectedOption === HYBRID_AGENT,
    );
    if (selectedOption === CUSTOM_TEMPLATE) {
      setIsHuman(true);
    } else {
      setIsHuman(false);
    }
  };

  const handleResetChat = async () => {
    closeCanvas(); // Close canvas on chat delete
    const data = {
      session_id: oldSessionId !== "" ? oldSessionId : session,
      agent_id: agentType !== CUSTOM_TEMPLATE ? agentSelectValue : customTemplatId,
      framework_type: framework,
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
    } finally {
      setShowDeleteConfirmation(false);
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

        // Auto-select default model if no model is currently selected
        if (!model) {
          const modelToSelect = data.default_model_name || (formattedModels.length > 0 ? formattedModels.sort((a, b) => a.value.localeCompare(b.value))[0].value : null);
          if (modelToSelect) {
            setModel(modelToSelect);
          }
        }
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
      framework_type: framework,
    };
    const reseponse = await fetchOldChats(data);
    const oldChats = reseponse;
    const temp = [];
    for (const key in oldChats) {
      const chatItem = oldChats[key][0];
      temp.push({
        ...chatItem,
        session_id: key,
        messageCount: oldChats[key].length,
        // Ensure timestamp_start is set for ChatHistorySlider compatibility
        // The API may return timestamp_start, start_timestamp, or time_stamp
        timestamp_start:
          chatItem?.timestamp_start ||
          chatItem?.start_timestamp ||
          chatItem?.time_stamp ||
          chatItem?.timestamp ||
          chatItem?.created_at ||
          null,
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
    closeCanvas(); // Close canvas on chat select from history

    // First update both session IDs and wait for them to be set
    await new Promise((resolve) => {
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
      const response = await fetchData(APIs.KB_GET_LIST);
      serKnowledgeResponse(response?.knowledge_bases || []);
    } catch (error) {
      console.error("Error fetching knowledge base data:", error);
      serKnowledgeResponse([]);
    }
  };

  const handleNewChat = async () => {
    // Abort any ongoing SSE stream
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
    }

    // Reset all streaming/loading states to enable input field
    setGenerating(false);
    setFetching(false);
    setIsStreaming(false);
    setNodes([]);
    setCurrentNodeIndex(-1);
    setStreamParsedContents([]);
    setMessageData([]);
    setFeedback("");
    setUserChat("");

    setShowChatSettings(false);
    closeCanvas(); // Close canvas on new chat
    const sessionId = await fetchNewChats(loggedInUserEmail);
    fetchOldChatsData();
    setOldSessionId("");
    setSessionId(sessionId);
    fetchChatHistory(sessionId);
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

  const scrollToHighlightedMentionItem = (index) => {
    if (mentionListRef.current && index >= 0) {
      const items = mentionListRef.current.children;
      if (items[index]) {
        items[index].scrollIntoView({
          behavior: "smooth",
          block: "nearest",
        });
      }
    }
  };

  const handleMentionDropdownKeyDown = (e) => {
    if (!showMentionDropdown) return;

    // Get allowed agent types based on framework from chat_screen_config
    const allowedMentionTypes = chat_screen_config[framework]?.mentionAgentTypes || [];

    const filteredAgents = Array.isArray(agentsListData)
      ? agentsListData.filter((agent) => {
        const matchesSearch = agent.agentic_application_name.toLowerCase().includes(mentionSearchTerm.toLowerCase());
        const matchesAgentType = mentionAgentTypeFilter === "all" || agent.agentic_application_type === mentionAgentTypeFilter;
        const notCurrentlySelected = agent.agentic_application_id !== agentSelectValue;
        const notMentioned = !mentionedAgent || agent.agentic_application_id !== mentionedAgent.agentic_application_id;
        // Filter by framework-allowed agent types
        const isAllowedForFramework = allowedMentionTypes.length === 0 || allowedMentionTypes.includes(agent.agentic_application_type);
        // Exclude pipelines from "all" view - only show when explicitly filtered
        const isPipeline = agent.agentic_application_type === PIPELINE_AGENT;
        const pipelineAllowed = mentionAgentTypeFilter === PIPELINE_AGENT || !isPipeline;
        return matchesSearch && matchesAgentType && notCurrentlySelected && notMentioned && isAllowedForFramework && pipelineAllowed;
      })
      : [];

    if (filteredAgents.length === 0) return;

    switch (e.key) {
      case "ArrowDown":
        e.preventDefault();
        e.stopPropagation();
        setHighlightedMentionIndex((prev) => {
          const newIndex = prev < filteredAgents.length - 1 ? prev + 1 : 0;
          setTimeout(() => scrollToHighlightedMentionItem(newIndex), 0);
          return newIndex;
        });
        break;
      case "ArrowUp":
        e.preventDefault();
        e.stopPropagation();
        setHighlightedMentionIndex((prev) => {
          const newIndex = prev > 0 ? prev - 1 : filteredAgents.length - 1;
          setTimeout(() => scrollToHighlightedMentionItem(newIndex), 0);
          return newIndex;
        });
        break;
      case "Enter":
      case " ":
        e.preventDefault();
        if (highlightedMentionIndex >= 0 && filteredAgents[highlightedMentionIndex]) {
          const selectedAgent = filteredAgents[highlightedMentionIndex];
          setMentionedAgent(selectedAgent);
          setShowMentionDropdown(false);
          setMentionSearchTerm("");
          setHighlightedMentionIndex(-1);
        }
        break;
      case "Escape":
        e.preventDefault();
        setShowMentionDropdown(false);
        setMentionSearchTerm("");
        setHighlightedMentionIndex(-1);
        break;
      default:
        break;
    }
  };

  // Handle selecting an agent from @mention dropdown
  const handleMentionAgentSelect = (agent) => {
    setMentionedAgent(agent);
    setShowMentionDropdown(false);
    setMentionSearchTerm("");
    setHighlightedMentionIndex(-1);
    setUserChat(""); // Clear the @ text from input
    if (textareaRef.current) {
      textareaRef.current.focus();
    }
  };

  // Handle clearing the mentioned agent
  const handleClearMentionedAgent = () => {
    setMentionedAgent("");
    if (textareaRef.current) {
      textareaRef.current.focus();
    }
  };

  const textareaRef = useRef(null);
  const resetHeight = () => {
    const textarea = textareaRef.current;
    if (textarea) {
      textarea.style.height = "auto";
      textarea.style.height = "24px";
    }
  };

  const calculateHeight = (newValue) => {
    const textarea = textareaRef.current;
    if (!textarea) return;

    const minHeight = 24;
    const maxHeight = 200;

    // Get the value to check
    const value = newValue !== undefined ? newValue : textarea.value;

    // If empty, reset to minimum
    if (!value || value === "") {
      textarea.style.height = `${minHeight}px`;
      return;
    }

    // Temporarily set to auto to get real scrollHeight
    textarea.style.height = "auto";
    const scrollHeight = textarea.scrollHeight;

    // Calculate new height within bounds
    const newHeight = Math.min(Math.max(scrollHeight, minHeight), maxHeight);
    textarea.style.height = `${newHeight}px`;
  };
  const handleChange = (e) => {
    setUserChat(e.target.value);
    calculateHeight(e.target.value);
  };

  // File upload click handler - triggers hidden file input
  const handleFileClick = () => {
    if (fileInputRef.current) {
      fileInputRef.current.click();
    }
  };

  // Handle file selection and upload
  const handleFileUpload = async (files) => {
    if (!files || files.length === 0) return;

    const currentSessionId = oldSessionId !== "" ? oldSessionId : session;
    setIsUploadingFiles(true);

    // Store original file names before upload
    const originalFileNames = files.map((file) => file.name);

    try {
      const response = await uploadChatFiles(files, currentSessionId);
      if (response && response.uploaded_files) {
        // Match uploaded files with original names
        // The API returns paths in the same order as uploaded files
        const newFiles = response.uploaded_files.map((filePath, index) => ({
          // Use original file name for display, fall back to extracting from path
          name: originalFileNames[index] || filePath.split("/").pop() || filePath,
          path: filePath,
        }));
        setUploadedChatFiles((prev) => [...prev, ...newFiles]);
        // Use the message from API response for toast
        addMessage(response.message || "Files uploaded successfully", "success");
      } else if (response && response.message) {
        addMessage(response.message, "success");
      }
    } catch (error) {
      console.error("Error uploading files:", error);
      addMessage("Error uploading files", "error");
    } finally {
      setIsUploadingFiles(false);
    }
  };

  // Handle file deletion
  const handleFileDelete = async (filePath) => {
    try {
      const response = await deleteChatFile(filePath);
      if (response) {
        setUploadedChatFiles((prev) => prev.filter((file) => file.path !== filePath));
        addMessage("File deleted successfully", "success");
      }
    } catch (error) {
      console.error("Error deleting file:", error);
      addMessage("Error deleting file", "error");
    }
  };

  // Handle file view - fetches blob for proper preview (same as FilesPage)
  const handleFileView = async (file) => {
    // For chat-uploaded files, the path may contain directory prefix
    // e.g., "user_uploads/Groundtruth_template (4)_admin12345@infosys.com_c3e6a720_7d7b_4f19_b229_fc88cee941b5.xlsx"
    const fullPath = file.path || file.name;
    const displayName = file.name || fullPath.split("/").pop();

    // Extract only the filename (remove directory prefix like "user_uploads/")
    const fileName = fullPath.includes("/") ? fullPath.split("/").pop() : fullPath;

    // Build URL with only filename parameter
    const url = `${APIs.DOWNLOAD_FILE}?filename=${encodeURIComponent(fileName)}`;

    try {
      const response = await fetchData(url, { responseType: "blob" });

      // Handle both axios and fetch response formats
      const isAxios = response && response.data !== undefined && response.headers !== undefined;
      const dataBlob = isAxios ? response.data : response;
      const headers = isAxios ? response.headers : response?.headers || {};
      const getHeader = typeof headers.get === "function" ? (k) => headers.get(k) : (k) => headers[k.toLowerCase()];
      const contentType = getHeader && getHeader("content-type");

      // Check if response is JSON (error response) - check both content type and blob content
      const isJsonContentType = contentType && contentType.includes("application/json");

      // Also check if blob content starts with JSON error pattern
      let blobText = null;
      if (dataBlob instanceof Blob && dataBlob.size < 10000) {
        // Only check small blobs (errors are typically small)
        try {
          blobText = await dataBlob.text();
          if (blobText.startsWith('{"error"') || blobText.startsWith('{"message"') || blobText.startsWith('{"detail"')) {
            const errorData = JSON.parse(blobText);
            const errorMessage = errorData.error || errorData.message || errorData.detail || "Unable to view file";
            addMessage(typeof errorMessage === "string" ? errorMessage : "Unable to view file", "error");
            return;
          }
        } catch {
          // Not JSON, continue with normal flow
        }
      }

      if (isJsonContentType) {
        // Try to parse error message from blob
        try {
          const text = blobText || await dataBlob.text();
          const errorData = JSON.parse(text);
          const errorMessage = errorData.error || errorData.message || "Unable to view file";
          addMessage(errorMessage, "error");
        } catch {
          addMessage("Unable to view file", "error");
        }
        return;
      }

      // Determine the correct MIME type based on file extension
      const getMimeType = (name) => {
        const ext = name.split(".").pop()?.toLowerCase();
        const mimeTypes = {
          pdf: "application/pdf",
          docx: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
          xlsx: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
          xls: "application/vnd.ms-excel",
          jpg: "image/jpeg",
          jpeg: "image/jpeg",
          png: "image/png",
          gif: "image/gif",
          txt: "text/plain",
          json: "application/json",
          csv: "text/csv",
          py: "text/plain",
          js: "text/plain",
        };
        return mimeTypes[ext] || contentType || "application/octet-stream";
      };

      const mimeType = getMimeType(fileName);

      // Create blob with correct MIME type - need to re-fetch if we already read the blob
      let finalBlob;
      if (blobText !== null) {
        // We already read the blob, create new one from the text
        finalBlob = new Blob([blobText], { type: mimeType });
      } else if (dataBlob instanceof Blob) {
        const arrayBuffer = await dataBlob.arrayBuffer();
        finalBlob = new Blob([arrayBuffer], { type: mimeType });
      } else {
        finalBlob = new Blob([dataBlob], { type: mimeType });
      }

      // Create blob URL for preview
      const blobUrl = URL.createObjectURL(finalBlob);

      setViewingFile({ url: blobUrl, name: displayName });
      setShowFileViewer(true);
    } catch (err) {
      console.error("View file failed:", err);
      // Try to extract error message from response
      const errorMessage = err?.response?.data?.error || err?.message || "Failed to load file for viewing";
      addMessage(errorMessage, "error");
    }
  };

  // Clean up blob URL when closing file viewer
  const handleCloseFileViewer = () => {
    if (viewingFile.url && viewingFile.url.startsWith("blob:")) {
      URL.revokeObjectURL(viewingFile.url);
    }
    setViewingFile({ url: "", name: "" });
    setShowFileViewer(false);
  };

  // Handle file input change
  const handleFileInputChange = (event) => {
    const selectedFiles = Array.from(event.target.files);
    if (selectedFiles.length > 0) {
      handleFileUpload(selectedFiles);
    }
    // Reset input to allow selecting the same file again
    event.target.value = "";
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
        <span key={index} style={{ color: "var(--app-primary-color)" }}>
          {part}
        </span>
      ) : (
        part
      ),
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
      if (textareaRef.current) {
        textareaRef.current.focus();
        // Place cursor at the end of the text
        setTimeout(() => {
          if (textareaRef.current) {
            textareaRef.current.selectionStart = textareaRef.current.selectionEnd = text.length;
          }
        }, 0);
      }
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
      // Auto-collapse right sidebar when canvas opens
      setIsRightSidebarCollapsed(true);
    }, 0);
  };

  const closeCanvas = () => {
    setIsCanvasOpen(false);
    setCanvasContent(null);
    setCanvasTitle("");
    setCanvasContentType("");
    setCanvasMessageId(null);
    setCanvasIsLast(false);
    // Keep right sidebar collapsed - user can manually expand if needed
  };

  // Auto-detect canvas content from AI responses - PARTS FORMAT ONLY
  const detectCanvasContent = (input) => {
    try {
      // Detect email content
      if (
        typeof input === "object" &&
        input !== null &&
        (input.type === "email" ||
          input.contentType === "email" ||
          input?.to ||
          input?.subject ||
          input?.body ||
          (input.data && (input.data.to || input.data.subject || input.data.body)))
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
      // No parts format found - return null (no canvas)
      return null;
    } catch (error) {
      console.error("Error processing message in detectCanvasContent:", error);
      return null;
    }
  };

  const ONLINE_EVAL_AGENT_TYPES = [REACT_AGENT, REACT_CRITIC_AGENT, PLANNER_EXECUTOR_AGENT, MULTI_AGENT, HYBRID_AGENT, META_AGENT, PLANNER_META_AGENT];

  const shouldShowOnlineEvaluator = () => {
    if (!agentType) return false;
    if (userRole === "user") return false;
    return ONLINE_EVAL_AGENT_TYPES.includes(agentType);
  };
  const [onlineEvaluatorFlag, setOnlineEvaluatorFlag] = useState(false);
  const handleOnlineEvaluatorToggle = (checked) => {
    setOnlineEvaluatorFlag(checked);
  };

  return (
    <>
      {/* Welcome Modal - shown on first visit */}
      <WelcomeModal
        isOpen={showWelcomeModal}
        onClose={() => setShowWelcomeModal(false)}
        frameworkOptions={FRAMEWORK_OPTIONS}
        selectedFramework={framework}
        onFrameworkChange={handleFrameworkChange}
        agents={agentsListData}
        selectedAgent={selectedAgent?.agentic_application_name || ""}
        onAgentChange={(agentName) => {
          const agent = agentsListData.find((a) => a.agentic_application_name === agentName);
          if (agent) {
            // Skip reset if selecting the same agent
            if (selectedAgent?.agentic_application_id === agent.agentic_application_id) {
              return;
            }
            // Auto-switch framework based on agent type
            // Hybrid agents require pure_python framework, all others use langgraph
            // Only set framework directly (don't use handleFrameworkChange which resets agent state)
            if (agent.agentic_application_type === HYBRID_AGENT) {
              setFramework("pure_python");
            } else if (framework === "pure_python" && agent.agentic_application_type !== HYBRID_AGENT) {
              // If switching from hybrid agent to non-hybrid, switch to langgraph
              setFramework("langgraph");
            }
            selectAgent(agent);
            setAgentSelectValue(agent.agentic_application_id);
            // Set agent type to match the selected agent
            setAgentType(agent.agentic_application_type || "");
            // Set model from agent's model_name if available
            if (agent.model_name) {
              setModel(agent.model_name);
            }
            setFeedback("");
            setOldSessionId("");
            const cookieSessionId = Cookies.get("user_session");
            if (cookieSessionId) {
              setSessionId(cookieSessionId);
            }
            setLikeIcon(false);
          }
        }}
        loadingAgents={loadingAgents}
        disabled={fetching || generating}
        getAgentTypeFilterOptions={getAgentTypeFilterOptions}
        agentType={agentType}
        onAgentTypeChange={(value) => setAgentType(value)}
        focusChatInput={() => {
          if (textareaRef.current) {
            textareaRef.current.focus();
          }
        }}
      />

      <div className={stylesNew.askAssistantContainer} ref={chatbotContainerRef}>
        {/* Main Chat Area */}
        <div className={`${stylesNew.chatWrapper} ${isCanvasOpen ? stylesNew.withCanvas : ""}`}>
          <div className={stylesNew.bubbleAndInput}>
            <div className={stylesNew.chatBubblesWrapper}>
              <div className={stylesNew.messagesWrapper} ref={msgContainerRef}>
                {/* message container */}
                <MsgBox
                  styles={stylesNew}
                  messageData={messageData}
                  generating={generating}
                  agentType={effectiveAgentType}
                  isStreaming={isStreaming}
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
                  toolInterrupt={canToolVerifier ? toolInterrupt : false}
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
                  isMissingRequiredOptions={isMissingRequiredOptions}
                  oldChats={oldChats}
                  isDeletingChat={isDeletingChat}
                  openCanvas={openCanvas}
                  detectCanvasContent={detectCanvasContent}
                  isCanvasEnabled={isCanvasEnabled}
                  isContextEnabled={isContextEnabled}
                  onlineEvaluatorFlag={onlineEvaluatorFlag}
                  plan_verifier_flag={isHuman}
                  planVerifierText={planVerifierPrompt}
                  nodes={nodes}
                  currentNodeIndex={currentNodeIndex}
                  streamContents={streamParsedContents}
                  setNodes={setNodes}
                  setIsStreaming={setIsStreaming}
                  setCurrentNodeIndex={setCurrentNodeIndex}
                  mentionedAgent={mentionedAgent}
                  useValidator={useValidator}
                  temperature={temperature}
                  selectedInterruptTools={selectedInterruptTools}
                  mappedTools={mappedTools}
                  isFileContextEnabled={isFileContextEnabled}
                  isMessageQueueEnabled={isMessageQueueEnabled}
                  selectedAgent={selectedAgent}
                  framework={framework}
                  onViewFile={handleFileView}
                  canExecutionSteps={canExecutionSteps}
                />
              </div>
            </div>
            <div className={"chatSection"}>
              <div className={chatInputModule.container}>
                {/* Hidden file input for uploads */}
                <input
                  ref={fileInputRef}
                  type="file"
                  multiple
                  onChange={handleFileInputChange}
                  style={{ display: "none" }}
                  accept=".pdf,.docx,.ppt,.pptx,.txt,.xlsx,.json,.csv,.jpg,.png,.jpeg,.py,.js"
                />

                {/* Input row */}
                <div className={chatInputModule.inputsWrapperRow2}>
                  {/* Left pill group: Upload + @ Agent */}
                  <div className={chatInputModule.leftControlsGroup}>
                    <button
                      type="button"
                      className={chatInputModule.inputButton}
                      onClick={handleFileClick}
                      disabled={messageDisable || fetching || generating || isEditable || isUploadingFiles}
                      title="Upload Files"
                      tabIndex={0}>
                      <SVGIcons icon="upload" width={18} height={18} />
                      {isUploadingFiles && <span className={chatInputModule.uploadingDot}></span>}
                    </button>

                    {/* Uploaded files preview - compact inline display */}
                    {uploadedChatFiles.length > 0 && (
                      <div className={chatInputModule.filesPreviewInline}>
                        {uploadedChatFiles.map((file, index) => {
                          const truncateName = (name, maxLen = 15) => {
                            if (name.length <= maxLen) return name;
                            const ext = name.split(".").pop();
                            const base = name.substring(0, name.lastIndexOf("."));
                            return `${base.substring(0, maxLen - ext.length - 4)}...${ext}`;
                          };
                          return (
                            <div key={file.path || index} className={chatInputModule.fileChipCompact} title={file.name}>
                              <SVGIcons icon="file" width={14} height={14} />
                              <span className={chatInputModule.fileNameCompact}>{truncateName(file.name)}</span>
                              <button
                                type="button"
                                className={chatInputModule.deleteButtonCompact}
                                onClick={() => handleFileDelete(file.path)}
                                title="Remove file"
                                disabled={messageDisable || fetching || generating || isUploadingFiles}
                              >
                                <SVGIcons icon="x" width={12} height={12} />
                              </button>
                            </div>
                          );
                        })}
                      </div>
                    )}

                    {/* @Mentioned Agent Badge with glow */}
                    {mentionedAgent && mentionedAgent.agentic_application_name && (
                      <div
                        className={chatInputModule.mentionedAgentBadge}
                        title={mentionedAgent.agentic_application_name}
                        onClick={handleClearMentionedAgent}
                      >
                        <span className={chatInputModule.mentionedAgentAt}>@</span>
                        <span className={chatInputModule.mentionedAgentName}>{mentionedAgent.agentic_application_name}</span>
                        <button
                          type="button"
                          className={chatInputModule.mentionedAgentClose}
                          onClick={(e) => {
                            e.stopPropagation();
                            handleClearMentionedAgent();
                          }}
                        >
                          <SVGIcons icon="x" width={10} height={10} />
                        </button>
                      </div>
                    )}
                  </div>

                  {/* Input Container - Text area with prompt suggestion */}
                  <div className={chatInputModule.inputContainer}>
                    <div className={chatInputModule.promptLibraryAndTextArea}>
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
                        ) : isTranscribing ? (
                          <div className={stylesNew.transcribingIndicator}>
                            <div className={stylesNew.transcribingDots}>
                              <span className={stylesNew.transcribingDot}></span>
                              <span className={stylesNew.transcribingDot}></span>
                              <span className={stylesNew.transcribingDot}></span>
                            </div>
                            <span className={stylesNew.transcribingLabel}>Transcribing...</span>
                          </div>
                        ) : (
                          <textarea
                            ref={textareaRef}
                            value={userChat}
                            rows={1}
                            onChange={(e) => {
                              const value = e.target.value;
                              setUserChat(value);
                              calculateHeight(value);
                              // Filter suggestions as user types and show PromptSuggestions panel
                              filterSuggestionsForAutoSuggest(value);

                              // Detect @ as first character to show agent mention dropdown
                              if (value === "@" || (value.startsWith("@") && value.indexOf(" ") === -1)) {
                                const searchTerm = value.substring(1).toLowerCase();
                                setMentionSearchTerm(searchTerm);
                                setShowMentionDropdown(true);
                                setHighlightedMentionIndex(0);
                              } else if (showMentionDropdown && !value.startsWith("@")) {
                                // Close dropdown if user removed the @
                                setShowMentionDropdown(false);
                                setMentionSearchTerm("");
                              }
                            }}
                            onInput={(e) => calculateHeight(e.target.value)}
                            onKeyDown={(e) => {
                              // Handle prompt suggestions keyboard navigation
                              // Arrow keys are intercepted here so they don't move the cursor.
                              // The PromptSuggestions component's own window keydown listener
                              // handles the actual navigation and selection.
                              if (showPromptSuggestions) {
                                if (e.key === "ArrowDown" || e.key === "ArrowUp") {
                                  e.preventDefault();
                                  return;
                                }
                                if (e.key === "Enter" && !e.shiftKey) {
                                  if (promptSuggestionHasFocusRef.current) {
                                    // User has highlighted a suggestion with arrow keys,
                                    // let PromptSuggestions handle the selection.
                                    e.preventDefault();
                                    return;
                                  }
                                  // No suggestion highlighted — close the panel and let
                                  // Enter fall through to handleKeyDown to send the message.
                                  setShowPromptSuggestions(false);
                                  setOpenedViaIcon(false);
                                }
                                if (e.key === "Escape") {
                                  e.preventDefault();
                                  setShowPromptSuggestions(false);
                                  return;
                                }
                              }
                              // Handle @mention dropdown navigation
                              if (showMentionDropdown) {
                                const filteredMentionAgents = agentListDropdown.filter(agent => {
                                  const matchesSearch = agent.agentic_application_name?.toLowerCase().includes(mentionSearchTerm);
                                  const notCurrentAgent = agent.agentic_application_id !== agentSelectValue;
                                  const matchesTypeFilter = mentionAgentTypeFilter === "all" || agent.agentic_application_type === mentionAgentTypeFilter;
                                  const isPipeline = agent.agentic_application_type === PIPELINE_AGENT;
                                  const pipelineAllowed = mentionAgentTypeFilter === PIPELINE_AGENT || !isPipeline;
                                  const isHybridAgent = agent.agentic_application_type === HYBRID_AGENT;
                                  const typeAllowed = effectiveAgentType === HYBRID_AGENT ? isHybridAgent : !isHybridAgent;
                                  return matchesSearch && notCurrentAgent && matchesTypeFilter && typeAllowed && pipelineAllowed;
                                });
                                if (e.key === "ArrowDown") {
                                  e.preventDefault();
                                  setHighlightedMentionIndex(prev =>
                                    prev < filteredMentionAgents.length - 1 ? prev + 1 : 0
                                  );
                                  return;
                                }
                                if (e.key === "ArrowUp") {
                                  e.preventDefault();
                                  setHighlightedMentionIndex(prev =>
                                    prev > 0 ? prev - 1 : filteredMentionAgents.length - 1
                                  );
                                  return;
                                }
                                if (e.key === "Enter" && filteredMentionAgents.length > 0) {
                                  e.preventDefault();
                                  const selectedMentionAgent = filteredMentionAgents[highlightedMentionIndex] || filteredMentionAgents[0];
                                  handleMentionAgentSelect(selectedMentionAgent);
                                  return;
                                }
                                if (e.key === "Escape") {
                                  e.preventDefault();
                                  setShowMentionDropdown(false);
                                  setMentionSearchTerm("");
                                  setUserChat("");
                                  return;
                                }
                              }
                              handleKeyDown(e);
                            }}
                            placeholder={!isMissingRequiredOptions ? (mentionedAgent ? "Ask anything..." : "Ask anything or type @ to mention agent...") : "Select options to start chatting"}
                            disabled={generating || isMissingRequiredOptions || fetching || feedBack === dislike || isEditable || messageDisable}
                            className={chatInputModule.textInput}
                            style={{ height: "24px" }}
                            maxLength={2000}
                            autoComplete="off"
                            aria-autocomplete="list"
                            aria-controls="suggestion-popover"
                          />
                        )}
                      </div>
                      {/* Prompt Suggestion Button inside input */}
                      <button
                        type="button"
                        className={chatInputModule.promptSuggestionBtn}
                        onClick={handlePromptSuggestionsToggle}
                        disabled={isMissingRequiredOptions || generating || fetching || messageDisable}
                        title="Prompt Library"
                        tabIndex={0}>
                        <SVGIcons icon="sparkles" width={16} height={16} />
                      </button>
                    </div>
                    {/* Send button */}
                    <button
                      type="submit"
                      onClick={() => sendUserMessage(userChat)}
                      className={chatInputModule.sendButton}
                      disabled={generating || fetching || messageDisable || isTranscribing || !(userChat && userChat.trim())}
                      title="Send Message"
                      tabIndex={0}>
                      <SVGIcons icon="send-message" width={16} height={16} />
                    </button>

                    {/* Mic Button - Inside the input box */}
                    <button
                      type="button"
                      className={`${chatInputModule.micButton} ${recording ? chatInputModule.active : ""}`}
                      onClick={recording ? stopRecording : startRecording}
                      disabled={generating || fetching || messageDisable || isTranscribing}
                      title={recording ? "Stop Recording" : isTranscribing ? "Processing audio..." : "Voice Input"}
                      tabIndex={0}>
                      {recording ? <SVGIcons icon="stop-recording" width={16} height={16} /> : <SVGIcons icon="mic" width={16} height={16} />}
                    </button>
                  </div>
                </div>
                <PromptSuggestions
                  isVisible={showPromptSuggestions}
                  onClose={() => {
                    setShowPromptSuggestions(false);
                    setOpenedViaIcon(false);
                  }}
                  onSelectPrompt={handlePromptSelect}
                  promptSuggestions={promptSuggestions}
                  filteredSuggestions={filteredAutoSuggestions}
                  cachedSuggestions={cachedSuggestions}
                  searchText={userChat}
                  openedViaIcon={openedViaIcon}
                  onFocusedIndexChange={(idx) => {
                    promptSuggestionHasFocusRef.current = idx >= 0;
                  }}
                  ref={promptSuggestionsRef}
                />

                {/* @Mention Agent Dropdown */}
                {showMentionDropdown && (
                  <div className={chatInputModule.mentionDropdown} ref={mentionDropdownRef}>
                    <div className={chatInputModule.mentionDropdownHeader}>
                      <div className={chatInputModule.mentionSearchWrapper}>
                        <SVGIcons icon="search" width={14} height={14} />
                        <input
                          type="text"
                          className={chatInputModule.mentionSearchInput}
                          placeholder="Search..."
                          value={mentionSearchTerm}
                          onChange={(e) => setMentionSearchTerm(e.target.value.toLowerCase())}
                          autoFocus
                        />
                      </div>
                      <select
                        className={chatInputModule.mentionFilterSelect}
                        value={mentionAgentTypeFilter}
                        onChange={(e) => setMentionAgentTypeFilter(e.target.value)}
                      >
                        {getAgentTypeFilterOptions(framework).map((option) => (
                          <option key={option.value} value={option.value}>
                            {option.label}
                          </option>
                        ))}
                      </select>
                    </div>
                    <div className={chatInputModule.mentionDropdownList} ref={mentionListRef}>
                      {agentListDropdown
                        .filter(agent => {
                          // Base filters: search term and exclude current agent
                          const matchesSearch = agent.agentic_application_name?.toLowerCase().includes(mentionSearchTerm);
                          const notCurrentAgent = agent.agentic_application_id !== agentSelectValue;
                          const matchesTypeFilter = mentionAgentTypeFilter === "all" || agent.agentic_application_type === mentionAgentTypeFilter;

                          // Exclude pipelines from "all" view - only show when explicitly filtered
                          const isPipeline = agent.agentic_application_type === PIPELINE_AGENT;
                          const pipelineAllowed = mentionAgentTypeFilter === PIPELINE_AGENT || !isPipeline;

                          // Agent type filtering:
                          // - For hybrid agents: show ONLY hybrid agents
                          // - For non-hybrid agents: hide hybrid agents
                          const isHybridAgent = agent.agentic_application_type === HYBRID_AGENT;
                          const typeAllowed = effectiveAgentType === HYBRID_AGENT ? isHybridAgent : !isHybridAgent;

                          return matchesSearch && notCurrentAgent && matchesTypeFilter && typeAllowed && pipelineAllowed;
                        })
                        .map((agent, index) => {
                          // Get short abbreviation for agent type
                          const getTypeAbbr = (type) => {
                            const abbrs = {
                              react_agent: "RA",
                              react_critic_agent: "RC",
                              hybrid_agent: "HA",
                              meta_agent: "MA",
                              planner_meta_agent: "MP",
                              planner_executor_agent: "PE",
                              multi_agent: "PEC",
                              pipeline: "PL",
                              custom_template: "CT"
                            };
                            return abbrs[type] || type?.substring(0, 2).toUpperCase() || "";
                          };
                          return (
                            <div
                              key={agent.agentic_application_id}
                              className={`${chatInputModule.mentionDropdownItem} ${index === highlightedMentionIndex ? chatInputModule.highlighted : ""}`}
                              onClick={() => handleMentionAgentSelect(agent)}
                              onMouseEnter={() => setHighlightedMentionIndex(index)}
                            >
                              <SVGIcons icon="fa-robot" width={16} height={16} />
                              <span className={chatInputModule.mentionDropdownItemName}>{agent.agentic_application_name}</span>
                              <span className={chatInputModule.mentionDropdownItemType}>{getTypeAbbr(agent.agentic_application_type)}</span>
                            </div>
                          );
                        })
                      }
                      {agentListDropdown.filter(agent => {
                        const matchesSearch = agent.agentic_application_name?.toLowerCase().includes(mentionSearchTerm);
                        const notCurrentAgent = agent.agentic_application_id !== agentSelectValue;
                        const matchesTypeFilter = mentionAgentTypeFilter === "all" || agent.agentic_application_type === mentionAgentTypeFilter;
                        const isPipeline = agent.agentic_application_type === PIPELINE_AGENT;
                        const pipelineAllowed = mentionAgentTypeFilter === PIPELINE_AGENT || !isPipeline;
                        const isHybridAgent = agent.agentic_application_type === HYBRID_AGENT;
                        const typeAllowed = effectiveAgentType === HYBRID_AGENT ? isHybridAgent : !isHybridAgent;
                        return matchesSearch && notCurrentAgent && matchesTypeFilter && typeAllowed && pipelineAllowed;
                      }).length === 0 && (
                          <div className={chatInputModule.mentionDropdownEmpty}>
                            No agents found
                          </div>
                        )}
                    </div>
                  </div>
                )}

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
                  framework_type={framework}
                />
              )}
            </div>
          </div>
        </div>

        {/* Canvas Component - opens between chat and right sidebar */}
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

        {/* Right Sidebar - Model Selection & Settings */}
        <div className={`${stylesNew.rightSidebar} ${isRightSidebarCollapsed ? stylesNew.rightSidebarCollapsed : ""}`}>
          {/* Collapse Toggle Button */}
          <button
            className={stylesNew.sidebarCollapseBtn}
            onClick={() => setIsRightSidebarCollapsed(!isRightSidebarCollapsed)}
            title={isRightSidebarCollapsed ? "Expand Settings" : "Collapse Settings"}
          >
            <SVGIcons
              icon={isRightSidebarCollapsed ? "chevron-left" : "chevron-right"}
              width={14}
              height={14}
            />
          </button>

          {/* Sidebar Content - Hidden when collapsed */}
          {!isRightSidebarCollapsed && (
            <>
              {/* Fixed Top Section - Agent Selection */}
              <div className={stylesNew.sidebarFixedTop}>
                {/* Framework Selection */}
                <div className={stylesNew.sidebarSectionCompact}>
                  <div className={stylesNew.sidebarLabel}>
                    <SVGIcons icon="layout-grid" width={14} height={14} />
                    <span>Framework</span>
                  </div>
                  <NewCommonDropdown
                    className={dropdownStyles.chatFrameworkDropdown}
                    options={FRAMEWORK_OPTIONS.map((f) => f.label)}
                    selected={FRAMEWORK_OPTIONS.find((f) => f.value === framework)?.label || "LangGraph"}
                    onSelect={(label) => {
                      const selected = FRAMEWORK_OPTIONS.find((f) => f.label === label);
                      if (selected) {
                        handleFrameworkChange(selected.value);
                      }
                    }}
                    placeholder="Select Framework"
                    showSearch={false}
                    disabled={messageDisable || fetching || generating || isEditable}
                    dropdownWidth="248px"
                  />
                </div>

                {/* Agent Selection */}
                <div className={stylesNew.sidebarSectionCompact}>
                  <div className={stylesNew.sidebarLabel}>
                    <SVGIcons icon="fa-robot" width={14} height={14} />
                    <span>Agent</span>
                  </div>
                  <NewCommonDropdown
                    className={dropdownStyles.chatAgentDropdown}
                    options={(() => {
                      const agentNames = filteredAgents.map((agent) => agent.agentic_application_name);
                      if (selectedAgent?.agentic_application_name && !agentNames.includes(selectedAgent.agentic_application_name)) {
                        agentNames.unshift(selectedAgent.agentic_application_name);
                      }
                      return agentNames;
                    })()}
                    selected={selectedAgent?.agentic_application_name || ""}
                    onSelect={(name) => {
                      if (!name) {
                        setSelectedAgent("");
                        setAgentSelectValue("");
                        setFeedback("");
                        return;
                      }
                      const agent = filteredAgents.find((a) => a.agentic_application_name === name) || agentsListData.find((a) => a.agentic_application_name === name);
                      if (agent) {
                        // Skip reset if selecting the same agent
                        if (selectedAgent?.agentic_application_id === agent.agentic_application_id) {
                          return;
                        }
                        selectAgent(agent);
                        setAgentSelectValue(agent.agentic_application_id);
                        setFeedback("");
                        setOldSessionId("");
                        const cookieSessionId = Cookies.get("user_session");
                        if (cookieSessionId) {
                          setSessionId(cookieSessionId);
                        }
                        setLikeIcon(false);
                        // Auto-focus chat input after agent selection
                        setTimeout(() => {
                          if (textareaRef.current) {
                            textareaRef.current.focus();
                          }
                        }, 100);
                      }
                    }}
                    placeholder="Select Agent"
                    showSearch={true}
                    disabled={messageDisable || fetching || generating || isEditable}
                    showClearIcon={false}
                    showSelectedOnTop={false}
                    dropdownWidth="248px"
                    maxWidth="248px"
                    showTypeFilter={framework !== "pure_python"}
                    typeFilterOptions={getAgentTypeFilterOptions(framework)}
                    selectedTypeFilter={agentType || "all"}
                    onTypeFilterChange={(value) => {
                      setAgentType(value === "all" ? "" : value);
                    }}
                    optionMetadata={(() => {
                      const typeAbbreviations = {
                        meta_agent: "MA",
                        react_agent: "RA",
                        planner_meta_agent: "PM",
                        planner_executor_agent: "PE",
                        multi_agent: "PC",
                        react_critic_agent: "RC",
                        hybrid_agent: "HA",
                      };
                      const metadata = Object.fromEntries(
                        filteredAgents.map((agent) => [
                          agent.agentic_application_name,
                          typeAbbreviations[agent.agentic_application_type] || (agent.agentic_application_type ? agent.agentic_application_type.toUpperCase().slice(0, 2) : ""),
                        ]),
                      );
                      if (selectedAgent?.agentic_application_name) {
                        const type = selectedAgent.agentic_application_type || "";
                        metadata[selectedAgent.agentic_application_name] = typeAbbreviations[type] || type.toUpperCase().slice(0, 2);
                      }
                      return metadata;
                    })()}
                    optionTooltips={(() => {
                      const typeFullNames = Object.fromEntries(
                        agentTypesDropdown.map((t) => [t.value, t.label]),
                      );
                      const tooltips = Object.fromEntries(
                        filteredAgents.map((agent) => [
                          agent.agentic_application_name,
                          typeFullNames[agent.agentic_application_type] || (agent.agentic_application_type ? agent.agentic_application_type.replace(/_/g, " ") : ""),
                        ]),
                      );
                      if (selectedAgent?.agentic_application_name) {
                        const type = selectedAgent.agentic_application_type || "";
                        tooltips[selectedAgent.agentic_application_name] = typeFullNames[type] || type.replace(/_/g, " ");
                      }
                      return tooltips;
                    })()}
                    fixedHeight={true}
                  />
                </div>
              </div>

              {/* Divider */}
              <div className={stylesNew.sidebarDivider}></div>

              {/* Scrollable Section - Settings & Actions */}
              <div className={stylesNew.sidebarScrollable}>
                {/* Model + Temperature in same row */}
                <div className={stylesNew.modelTempRow}>
                  <div className={stylesNew.modelSection}>
                    <div className={stylesNew.sidebarLabel}>
                      <SVGIcons icon="hardware-chip" width={14} height={14} />
                      <span>Model</span>
                    </div>
                    <NewCommonDropdown
                      className={dropdownStyles.chatModelDropdown}
                      options={selectedModels.map((m) => m.value)}
                      selected={model || ""}
                      onSelect={(name) => {
                        setModel(name || "");
                      }}
                      placeholder="Select Model"
                      showSearch={true}
                      disabled={messageDisable || fetching || generating || isEditable}
                      showClearIcon={false}
                      dropdownWidth="180px"
                      fixedHeight={true}
                    />
                  </div>

                  {/* Temperature Button with Popup */}
                  <div className={stylesNew.tempButtonWrapper} ref={temperaturePopupRef}>
                    <button
                      className={stylesNew.tempButton}
                      onClick={() => setShowTemperaturePopup(!showTemperaturePopup)}
                      disabled={messageDisable || fetching || generating || isEditable}
                      title={`Temperature: ${temperature.toFixed(1)}`}
                    >
                      <SVGIcons icon="thermometer" width={14} height={14} />
                      <span className={stylesNew.tempButtonValue}>{temperature.toFixed(1)}</span>
                    </button>

                    {showTemperaturePopup && (
                      <div className={stylesNew.tempPopup}>
                        <div className={stylesNew.tempPopupHeader}>
                          <span>Temperature</span>
                          <span className={stylesNew.tempPopupValue}>{temperature.toFixed(1)}</span>
                        </div>
                        <input
                          type="range"
                          min="0"
                          max="1"
                          step="0.1"
                          value={temperature}
                          onChange={(e) => setTemperature(parseFloat(e.target.value))}
                          className={stylesNew.temperatureSliderColorful}
                          ref={temperatureSliderRef}
                        />
                        <div className={stylesNew.tempPopupLabels}>
                          <span>Precise</span>
                          <span>Creative</span>
                        </div>
                      </div>
                    )}
                  </div>
                </div>

                {/* Verifier Settings - hidden when no toggles are allowed by permissions */}
                {(() => {
                  const config = chat_screen_config[framework]?.[effectiveAgentType] || {};
                  const toggles = [
                    { key: "plan-verifier", show: config.planVerifier && canPlanVerifier, label: "Plan Verifier", checked: isHuman, onChange: handleHumanInLoop },
                    { key: "tool-verifier", show: config.toolVerifier && canToolVerifier, label: effectiveAgentType === META_AGENT || effectiveAgentType === PLANNER_META_AGENT ? "Agent Verifier" : "Tool Verifier", checked: toolInterrupt, onChange: handleToolInterrupt, showToolsList: true },
                    { key: "validator", show: config.validator && canValidator, label: "Validator", checked: useValidator, onChange: setUseValidator },
                    { key: "file-context", show: config.fileContext && canFileContext, label: "File Context", checked: isFileContextEnabled, onChange: setIsFileContextEnabled },
                    { key: "canvas", show: config.canvasView && canCanvasView, label: "Canvas View", checked: isCanvasEnabled, onChange: handleCanvasToggle },
                    { key: "context", show: config.context && canContext, label: "Context", checked: isContextEnabled, onChange: handleContextToggle },
                    { key: "online-evaluator", show: config.onlineEvaluator && canEvaluation, label: "Online Evaluator", checked: onlineEvaluatorFlag, onChange: handleOnlineEvaluatorToggle },
                  ];
                  const visibleToggles = toggles.filter((t) => t.show);
                  if (visibleToggles.length === 0) return null;
                  return (
                    <div className={stylesNew.sidebarSection}>
                      <div className={stylesNew.sidebarLabel}>
                        <SVGIcons icon="sliders-vertical" width={14} height={14} />
                        <span>Settings</span>
                      </div>
                      <div className={stylesNew.settingsToggles}>
                        {visibleToggles.map((t) => (
                          <div key={t.key} className={stylesNew.toggleWithList}>
                            <div className={`${stylesNew.sidebarToggle} ${t.showToolsList && t.checked ? stylesNew.toggleWithExpandable : ""}`}>
                              <span className={stylesNew.toggleLabelText}>{t.label}</span>
                              <div className={stylesNew.toggleRightSection}>
                                {/* Expand/Collapse button for tools list */}
                                {t.showToolsList && t.checked && mappedTools && mappedTools.length > 0 && (
                                  <button
                                    className={stylesNew.expandCollapseBtn}
                                    onClick={() => setShowToolsListExpanded(!showToolsListExpanded)}
                                    title={showToolsListExpanded ? "Collapse tools" : "Expand tools"}
                                    type="button"
                                  >
                                    <SVGIcons icon={showToolsListExpanded ? "drop_arrow_up" : "drop_arrow_down"} width={12} height={12} />
                                  </button>
                                )}
                                <label className={stylesNew.toggleSwitchLabel}>
                                  <input
                                    type="checkbox"
                                    checked={t.checked}
                                    onChange={(e) => {
                                      t.onChange(e.target.checked);
                                      if (t.showToolsList && e.target.checked) setShowToolsListExpanded(true);
                                    }}
                                    disabled={messageDisable || generating || fetching || isEditable}
                                    className={stylesNew.toggleCheckbox}
                                  />
                                  <span className={stylesNew.toggleSwitch}></span>
                                </label>
                              </div>
                            </div>

                            {/* Show tools list when Tool Verifier is enabled and expanded */}
                            {t.showToolsList && t.checked && showToolsListExpanded && mappedTools && mappedTools.length > 0 && (
                              <div className={stylesNew.toolsListContainer}>
                                <div className={stylesNew.toolsListHeader}>
                                  <span className={stylesNew.toolsListTitle}>Select Tools ({selectedInterruptTools.length}/{mappedTools.length})</span>
                                  <button
                                    className={stylesNew.selectAllBtn}
                                    onClick={() => handleSelectAllInterruptTools(selectedInterruptTools.length !== mappedTools.length)}
                                    disabled={messageDisable || generating || fetching || isEditable}
                                  >
                                    {selectedInterruptTools.length === mappedTools.length ? "Deselect All" : "Select All"}
                                  </button>
                                </div>
                                <div className={stylesNew.toolsCheckboxList}>
                                  {mappedTools.map((tool) => (
                                    <label key={tool} className={stylesNew.toolCheckboxItem}>
                                      <input
                                        type="checkbox"
                                        checked={selectedInterruptTools.includes(tool)}
                                        onChange={() => handleInterruptToolToggle(tool)}
                                        disabled={messageDisable || generating || fetching || isEditable}
                                        className={stylesNew.toolCheckbox}
                                      />
                                      <span className={stylesNew.toolCheckboxLabel}>{tool}</span>
                                    </label>
                                  ))}
                                </div>
                              </div>
                            )}

                            {/* Show loading state when fetching tools */}
                            {t.showToolsList && t.checked && loadingMappedTools && (
                              <div className={stylesNew.toolsLoading}>
                                <span>Loading tools...</span>
                              </div>
                            )}
                          </div>
                        ))}
                      </div>
                    </div>
                  );
                })()}

                {/* Quick Actions - full width buttons */}
                <div className={stylesNew.sidebarSection}>
                  <div className={stylesNew.sidebarLabel}>
                    <SVGIcons icon="bolt" width={14} height={14} />
                    <span>Actions</span>
                  </div>
                  <div className={stylesNew.actionsFullWidth}>
                    <button
                      className={stylesNew.actionFullBtn}
                      onClick={handleNewChat}
                      disabled={isMissingRequiredOptions}
                      title="New Chat"
                    >
                      <SVGIcons icon="circle-plus" width={18} height={18} />
                    </button>
                    <button
                      className={stylesNew.actionFullBtn}
                      onClick={() => setShowChatHistory(true)}
                      disabled={isMissingRequiredOptions || generating || fetching || isEditable}
                      title="History"
                    >
                      <SVGIcons icon="history" width={18} height={18} />
                    </button>
                    <button
                      className={stylesNew.actionFullBtn}
                      onClick={handleLiveTracking}
                      title="Tracking"
                    >
                      <SVGIcons icon="activity" width={18} height={18} />
                    </button>
                    <button
                      className={`${stylesNew.actionFullBtn} ${stylesNew.deleteBtn}`}
                      onClick={() => setShowDeleteConfirmation(true)}
                      disabled={messageData.length === 0 || generating || fetching}
                      title="Delete Chat"
                    >
                      <SVGIcons icon="trash" width={18} height={18} />
                    </button>
                  </div>
                </div>
              </div>
            </>
          )}
        </div>
      </div>
      {showDeleteConfirmation && (
        <ConfirmationModal
          message="Are you sure you want to delete this chat? This action cannot be undone."
          onConfirm={handleResetChat}
          setShowConfirmation={setShowDeleteConfirmation}
        />
      )}
      {/* File Viewer Modal */}
      {showFileViewer && (
        <DocViewerModal
          url={viewingFile.url}
          fileName={viewingFile.name}
          onClose={handleCloseFileViewer}
        />
      )}
    </>
  );
};

export default AskAssistant;
