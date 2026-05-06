import { useState, useEffect, useRef, useCallback } from "react";
import { useLocation } from "react-router-dom";
import { getRoleFromToken, getEmailFromToken, getUserNameFromToken } from "../../utils/jwtUtils";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { APIs, BOT, USER } from "../../constant";
import useFetch from "../../Hooks/useAxios";
import { useMessage } from "../../Hooks/MessageContext";
import { useChatServices } from "../../services/chatService";
import SVGIcons from "../../Icons/SVGIcons";
import styles from "./FloatingChatBot.module.css";

/**
 * FloatingChatBot Component
 * A draggable floating chatbot that appears on all pages except the chat page.
 * Features:
 * - Draggable bot icon positioned at bottom-right corner
 * - Expandable chat popup with smooth animation
 * - Welcome message display
 * - Simple chat input with model selection
 * - Uses viber-agent-id endpoint for agent interaction
 */
const FloatingChatBot = () => {
  const location = useLocation();
  const { fetchData, postDataStream } = useFetch();
  const { addMessage } = useMessage();
  const { uploadChatFiles, deleteChatFile } = useChatServices();

  // State management
  const [isMounted, setIsMounted] = useState(false);
  const [isPageLoading, setIsPageLoading] = useState(true);
  const [isOpen, setIsOpen] = useState(false);
  const [isAnimating, setIsAnimating] = useState(false);
  const [messages, setMessages] = useState([]);
  const [userInput, setUserInput] = useState("");
  const [isGenerating, setIsGenerating] = useState(false);
  const [agentId, setAgentId] = useState("");
  const [selectedModel, setSelectedModel] = useState("");
  const [sessionId, setSessionId] = useState("");

  // File upload state
  const [uploadedFiles, setUploadedFiles] = useState([]);
  const [isUploadingFiles, setIsUploadingFiles] = useState(false);

  // Drag state
  const [position, setPosition] = useState(() => ({
    x: typeof window !== "undefined" ? window.innerWidth - 56 - 16 : 0,
    y: typeof window !== "undefined" ? window.innerHeight - 56 - 100 : 0,
  }));
  const [isDragging, setIsDragging] = useState(false);
  const [dragOffset, setDragOffset] = useState({ x: 0, y: 0 });
  const [hasDragged, setHasDragged] = useState(false);
  const [isOverDustbin, setIsOverDustbin] = useState(false);
  const [isHiddenForSession, setIsHiddenForSession] = useState(false);
  const [isHiddenByPage, setIsHiddenByPage] = useState(false);
  const [skipTransition, setSkipTransition] = useState(false);

  // Streaming state - to show current step/tool info
  const [streamingState, setStreamingState] = useState({ nodeName: null, status: null, toolName: null });

  // Refs
  const chatContainerRef = useRef(null);
  const inputRef = useRef(null);
  const botIconRef = useRef(null);
  const abortControllerRef = useRef(null);
  const fileInputRef = useRef(null);
  const dustbinRef = useRef(null);

  // Get user info from cookies
  const userEmail = getEmailFromToken();
  const userName = getUserNameFromToken() || "User";

  // Constants for icon positioning
  const ICON_SIZE = 56;
  const EDGE_MARGIN = 16;
  const DUSTBIN_SIZE = 60;

  // Check if bot is over dustbin
  const checkDustbinCollision = useCallback((botX, botY) => {
    if (!dustbinRef.current) return false;
    const dustbinRect = dustbinRef.current.getBoundingClientRect();
    const botCenterX = botX + ICON_SIZE / 2;
    const botCenterY = botY + ICON_SIZE / 2;
    return (
      botCenterX >= dustbinRect.left &&
      botCenterX <= dustbinRect.right &&
      botCenterY >= dustbinRect.top &&
      botCenterY <= dustbinRect.bottom
    );
  }, []);

  // Hide bot for current session (until refresh or restore)
  const hideBotForSession = useCallback(() => {
    setIsHiddenForSession(true);
    // Notify NavBar to show restore option
    window.dispatchEvent(new CustomEvent("floatingChatBotHidden"));
  }, []);

  // Listen for page-level hide/show requests (e.g. System Utility tab)
  useEffect(() => {
    const handleHideByPage = () => setIsHiddenByPage(true);
    const handleShowByPage = () => setIsHiddenByPage(false);
    window.addEventListener("floatingChatBot:hide", handleHideByPage);
    window.addEventListener("floatingChatBot:show", handleShowByPage);
    return () => {
      window.removeEventListener("floatingChatBot:hide", handleHideByPage);
      window.removeEventListener("floatingChatBot:show", handleShowByPage);
    };
  }, []);

  // Listen for restore event from NavBar
  useEffect(() => {
    const handleRestore = () => {
      // Skip CSS transition when restoring
      setSkipTransition(true);
      // Reset position to right edge before showing
      const defaultY = window.innerHeight - ICON_SIZE - 100;
      setPosition({ x: window.innerWidth - ICON_SIZE - EDGE_MARGIN, y: defaultY });
      setIsHiddenForSession(false);
      // Re-enable transition after position is set
      requestAnimationFrame(() => {
        requestAnimationFrame(() => {
          setSkipTransition(false);
        });
      });
    };
    window.addEventListener("restoreFloatingChatBot", handleRestore);
    return () => {
      window.removeEventListener("restoreFloatingChatBot", handleRestore);
    };
  }, []);

  // Initialize position on mount (always right edge)
  useEffect(() => {
    const savedPosition = localStorage.getItem("floatingChatBotPosition");
    const defaultY = window.innerHeight - ICON_SIZE - 100;

    if (savedPosition) {
      try {
        const parsed = JSON.parse(savedPosition);
        // Always snap to right edge, only restore Y position
        const snappedY = Math.max(EDGE_MARGIN, Math.min(parsed.y, window.innerHeight - ICON_SIZE - EDGE_MARGIN));
        setPosition({ x: window.innerWidth - ICON_SIZE - EDGE_MARGIN, y: snappedY });
      } catch {
        setPosition({ x: window.innerWidth - ICON_SIZE - EDGE_MARGIN, y: defaultY });
      }
    } else {
      setPosition({ x: window.innerWidth - ICON_SIZE - EDGE_MARGIN, y: defaultY });
    }
  }, []);

  // Delay rendering until the page has fully painted
  // This ensures the bot icon appears after other UI elements load
  useEffect(() => {
    const timer = setTimeout(() => {
      requestAnimationFrame(() => {
        setIsMounted(true);
      });
    }, 1500);
    return () => clearTimeout(timer);
  }, []);

  // Detect page-level loading by watching for the Loader component in the DOM
  // The Loader renders an <img alt="Loading..."> inside a backdrop overlay
  useEffect(() => {
    const checkLoader = () => {
      const loaderImg = document.querySelector("img[alt='Loading...']");
      setIsPageLoading(!!loaderImg);
    };

    // Initial check
    checkLoader();

    // Watch for loader appearing/disappearing in the DOM
    const observer = new MutationObserver(() => {
      checkLoader();
    });

    observer.observe(document.body, {
      childList: true,
      subtree: true,
    });

    return () => observer.disconnect();
  }, []);

  // Also hide briefly on route changes to let the new page load
  useEffect(() => {
    setIsPageLoading(true);
    const timer = setTimeout(() => {
      // Re-check if the actual loader is still present
      const loaderImg = document.querySelector("img[alt='Loading...']");
      if (!loaderImg) {
        setIsPageLoading(false);
      }
    }, 800);
    return () => clearTimeout(timer);
  }, [location.pathname]);

  // Fetch viber agent ID on mount
  useEffect(() => {
    const fetchAgentId = async () => {
      try {
        const response = await fetchData(APIs.GET_VIBER_AGENT_ID, { silent: true });
        // Handle multiple possible response formats from the backend
        const id = response?.agent_id
          || response?.agentic_application_id
          || (typeof response === "string" ? response : null);
        if (id) {
          setAgentId(id);
        } else {
          console.warn("Viber agent ID not found in API response:", response);
        }
      } catch (error) {
        console.error("Failed to fetch viber agent ID:", error);
      }
    };
    fetchAgentId();
  }, [fetchData]);

  // Fetch models on mount and use first one
  useEffect(() => {
    const fetchModels = async () => {
      try {
        const response = await fetchData(APIs.GET_MODELS);
        if (response?.models && Array.isArray(response.models)) {
          const defaultModel = response.default_model_name || response.models[0];
          if (defaultModel) {
            setSelectedModel(defaultModel);
          }
        }
      } catch (error) {
        console.error("Failed to fetch models:", error);
      }
    };
    fetchModels();
  }, [fetchData]);

  // Generate session ID on mount
  useEffect(() => {
    setSessionId(`floating_chat_${Date.now()}`);
  }, []);

  // Scroll to bottom when messages update
  useEffect(() => {
    if (chatContainerRef.current) {
      chatContainerRef.current.scrollTop = chatContainerRef.current.scrollHeight;
    }
  }, [messages]);

  // Focus input when chat opens
  useEffect(() => {
    if (isOpen && inputRef.current) {
      inputRef.current.focus();
    }
  }, [isOpen]);

  // Handle window resize to keep bot icon on right edge
  useEffect(() => {
    const handleResize = () => {
      setPosition((prev) => {
        // Always stay on right edge
        const newX = window.innerWidth - ICON_SIZE - EDGE_MARGIN;
        const newY = Math.max(EDGE_MARGIN, Math.min(prev.y, window.innerHeight - ICON_SIZE - EDGE_MARGIN));
        return { x: newX, y: newY };
      });
    };
    window.addEventListener("resize", handleResize);
    return () => window.removeEventListener("resize", handleResize);
  }, []);

  // Drag handlers
  const handleMouseDown = useCallback((e) => {
    if (e.target.closest(`.${styles.chatPopup}`)) return;

    setIsDragging(true);
    setHasDragged(false);
    const rect = botIconRef.current?.getBoundingClientRect();
    if (rect) {
      setDragOffset({
        x: e.clientX - rect.left,
        y: e.clientY - rect.top,
      });
    }
  }, []);

  const handleMouseMove = useCallback(
    (e) => {
      if (!isDragging) return;

      setHasDragged(true);
      const newX = Math.max(0, Math.min(e.clientX - dragOffset.x, window.innerWidth - ICON_SIZE));
      const newY = Math.max(0, Math.min(e.clientY - dragOffset.y, window.innerHeight - ICON_SIZE));

      setPosition({ x: newX, y: newY });
      setIsOverDustbin(checkDustbinCollision(newX, newY));
    },
    [isDragging, dragOffset, checkDustbinCollision]
  );

  // Helper function to snap position to right edge (only Y position changes)
  const snapToRightEdge = useCallback((currentY) => {
    // Always snap to right edge
    const snapX = window.innerWidth - ICON_SIZE - EDGE_MARGIN;

    // Keep Y within bounds
    const snapY = Math.max(EDGE_MARGIN, Math.min(currentY, window.innerHeight - ICON_SIZE - EDGE_MARGIN));

    return { x: snapX, y: snapY };
  }, []);

  const handleMouseUp = useCallback(() => {
    if (isDragging) {
      setIsDragging(false);
      // Check if dropped on dustbin
      if (isOverDustbin) {
        hideBotForSession();
        setIsOverDustbin(false);
        return;
      }
      // Always snap to right edge
      const snappedPosition = snapToRightEdge(position.y);
      setPosition(snappedPosition);
      // Save snapped position to localStorage
      localStorage.setItem("floatingChatBotPosition", JSON.stringify(snappedPosition));
      setIsOverDustbin(false);
    }
  }, [isDragging, position, snapToRightEdge, isOverDustbin, hideBotForSession]);

  // Attach global mouse events for dragging
  useEffect(() => {
    if (isDragging) {
      document.addEventListener("mousemove", handleMouseMove);
      document.addEventListener("mouseup", handleMouseUp);
    }
    return () => {
      document.removeEventListener("mousemove", handleMouseMove);
      document.removeEventListener("mouseup", handleMouseUp);
    };
  }, [isDragging, handleMouseMove, handleMouseUp]);

  // Touch handlers for mobile
  const handleTouchStart = useCallback((e) => {
    if (e.target.closest(`.${styles.chatPopup}`)) return;

    const touch = e.touches[0];
    setIsDragging(true);
    setHasDragged(false);
    const rect = botIconRef.current?.getBoundingClientRect();
    if (rect) {
      setDragOffset({
        x: touch.clientX - rect.left,
        y: touch.clientY - rect.top,
      });
    }
  }, []);

  const handleTouchMove = useCallback(
    (e) => {
      if (!isDragging) return;

      const touch = e.touches[0];
      setHasDragged(true);
      const newX = Math.max(0, Math.min(touch.clientX - dragOffset.x, window.innerWidth - ICON_SIZE));
      const newY = Math.max(0, Math.min(touch.clientY - dragOffset.y, window.innerHeight - ICON_SIZE));

      setPosition({ x: newX, y: newY });
      setIsOverDustbin(checkDustbinCollision(newX, newY));
    },
    [isDragging, dragOffset, checkDustbinCollision]
  );

  const handleTouchEnd = useCallback(() => {
    if (isDragging) {
      setIsDragging(false);
      // Check if dropped on dustbin
      if (isOverDustbin) {
        hideBotForSession();
        setIsOverDustbin(false);
        return;
      }
      // Always snap to right edge
      const snappedPosition = snapToRightEdge(position.y);
      setPosition(snappedPosition);
      localStorage.setItem("floatingChatBotPosition", JSON.stringify(snappedPosition));
      setIsOverDustbin(false);
    }
  }, [isDragging, position, snapToRightEdge, isOverDustbin, hideBotForSession]);

  // Toggle chat popup
  const toggleChat = useCallback(() => {
    if (hasDragged) {
      setHasDragged(false);
      return;
    }

    setIsAnimating(true);
    setIsOpen((prev) => !prev);

    // Reset animation state after animation completes
    setTimeout(() => {
      setIsAnimating(false);
    }, 300);
  }, [hasDragged]);

  // Close chat popup
  const closeChat = useCallback(() => {
    setIsAnimating(true);
    setIsOpen(false);
    setTimeout(() => {
      setIsAnimating(false);
    }, 300);
  }, []);

  // Send message
  const sendMessage = async () => {
    if (!userInput.trim() || isGenerating || !agentId) return;

    // Save files before clearing
    const filesToSend = [...uploadedFiles];

    const userMessage = {
      id: Date.now(),
      type: USER,
      content: userInput.trim(),
      timestamp: new Date().toISOString(),
      attachedFiles: filesToSend.length > 0 ? filesToSend : null,
    };

    setMessages((prev) => [...prev, userMessage]);
    setUserInput("");
    setUploadedFiles([]); // Clear files after adding to message
    setIsGenerating(true);

    // Create abort controller for this request
    abortControllerRef.current = new AbortController();

    try {
      const payload = {
        framework_type: "langgraph",
        agentic_application_id: agentId,
        query: userMessage.content,
        session_id: sessionId,
        model_name: selectedModel,
        temperature: 0.0,
        reset_conversation: false,
        tool_verifier_flag: false,
        plan_verifier_flag: false,
        response_formatting_flag: false,
        context_flag: true,
        file_context_management_flag: false,
        evaluation_flag: false,
        mentioned_agentic_application_id: null,
        validator_flag: false,
        enable_streaming_flag: true,
        message_queue: false,
        ...(filesToSend.length > 0 && { uploaded_files: filesToSend.map((f) => f.path) }),
      };

      let botResponse = "";

      const onStreamChunk = (chunk) => {
        if (chunk?.response) {
          botResponse = chunk.response;
          // Update the bot message in real-time
          setMessages((prev) => {
            const lastMessage = prev[prev.length - 1];
            if (lastMessage?.type === BOT && lastMessage?.isStreaming) {
              return [
                ...prev.slice(0, -1),
                { ...lastMessage, content: botResponse },
              ];
            }
            return prev;
          });
        }

        // Extract streaming state info for loading display
        const nodeName = chunk?.["Node Name"] || chunk?.node_name || chunk?.node || chunk?.name || null;
        const statusVal = chunk?.Status || chunk?.status || chunk?.state || null;
        const toolName = chunk?.["Tool Name"] || chunk?.tool_name || (chunk?.raw && (chunk.raw["Tool Name"] || chunk.raw.tool_name)) || null;

        if (nodeName || statusVal || toolName) {
          setStreamingState({
            nodeName: nodeName || null,
            status: statusVal || null,
            toolName: toolName || null,
          });
        }
      };

      // Add streaming bot message placeholder
      setMessages((prev) => [
        ...prev,
        {
          id: Date.now() + 1,
          type: BOT,
          content: "",
          timestamp: new Date().toISOString(),
          isStreaming: true,
        },
      ]);

      const response = await postDataStream(
        APIs.CHAT_INFERENCE,
        payload,
        { signal: abortControllerRef.current.signal },
        onStreamChunk
      );

      // Finalize the bot message
      const finalResponse = response?.[response.length - 1]?.response || botResponse || "I apologize, but I couldn't generate a response.";

      setMessages((prev) => {
        const lastMessage = prev[prev.length - 1];
        if (lastMessage?.type === BOT) {
          return [
            ...prev.slice(0, -1),
            {
              ...lastMessage,
              content: finalResponse,
              isStreaming: false,
            },
          ];
        }
        return prev;
      });
    } catch (error) {
      if (error.name !== "AbortError") {
        console.error("Chat error:", error);
        addMessage("Failed to send message. Please try again.", "error");

        // Remove the streaming placeholder
        setMessages((prev) => {
          const lastMessage = prev[prev.length - 1];
          if (lastMessage?.type === BOT && lastMessage?.isStreaming) {
            return prev.slice(0, -1);
          }
          return prev;
        });
      }
    } finally {
      setIsGenerating(false);
      setStreamingState({ nodeName: null, status: null, toolName: null });
      abortControllerRef.current = null;
    }
  };

  // Handle input key press
  const handleKeyPress = (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  };

  // Stop generation
  const stopGeneration = useCallback(() => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
    }
    setIsGenerating(false);
  }, []);

  // Clear chat
  const clearChat = useCallback(() => {
    setMessages([]);
    setUploadedFiles([]);
    setSessionId(`floating_chat_${Date.now()}`);
  }, []);

  // Handle file click
  const handleFileClick = () => {
    if (fileInputRef.current) {
      fileInputRef.current.click();
    }
  };

  // Handle file upload
  const handleFileUpload = async (files) => {
    if (!files || files.length === 0) return;

    setIsUploadingFiles(true);
    const originalFileNames = files.map((file) => file.name);

    try {
      const response = await uploadChatFiles(files, sessionId);
      if (response && response.uploaded_files) {
        const newFiles = response.uploaded_files.map((filePath, index) => ({
          name: originalFileNames[index] || filePath.split("/").pop() || filePath,
          path: filePath,
        }));
        setUploadedFiles((prev) => [...prev, ...newFiles]);
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

  // Handle file input change
  const handleFileInputChange = (event) => {
    const selectedFiles = Array.from(event.target.files);
    if (selectedFiles.length > 0) {
      handleFileUpload(selectedFiles);
    }
    event.target.value = "";
  };

  // Handle file delete
  const handleFileDelete = async (filePath) => {
    try {
      const response = await deleteChatFile(filePath);
      if (response) {
        setUploadedFiles((prev) => prev.filter((file) => file.path !== filePath));
        addMessage("File deleted successfully", "success");
      }
    } catch (error) {
      console.error("Error deleting file:", error);
      addMessage("Error deleting file", "error");
    }
  };

  // Handle textarea auto resize
  const handleTextareaChange = (e) => {
    setUserInput(e.target.value);
    // Auto resize textarea
    if (inputRef.current) {
      inputRef.current.style.height = "24px"; // Reset height
      const scrollHeight = inputRef.current.scrollHeight;
      inputRef.current.style.height = Math.min(scrollHeight, 84) + "px"; // Max 4 lines (~84px)
    }
  };

  // Truncate file name helper
  const truncateFileName = (name, maxLen = 20) => {
    if (name.length <= maxLen) return name;
    const ext = name.split(".").pop();
    const base = name.substring(0, name.lastIndexOf("."));
    return `${base.substring(0, maxLen - ext.length - 4)}...${ext}`;
  };

  // Don't render until mounted and page loaded, on chat page, if hidden for session/page, or for SuperAdmin users
  const role = getRoleFromToken();
  if (!isMounted || isPageLoading || location.pathname === "/" || location.pathname === "/chat" || isHiddenForSession || isHiddenByPage || (role && role.toUpperCase() === "SUPERADMIN")) {
    return null;
  }

  return (
    <div className={styles.floatingChatBotContainer}>
      {/* Dustbin - appears when dragging */}
      {isDragging && (
        <div
          ref={dustbinRef}
          className={`${styles.dustbin} ${isOverDustbin ? styles.dustbinActive : ""}`}
          title="Drop to hide"
        >
          <SVGIcons icon="trash" width={20} height={20} />
        </div>
      )}

      {/* Draggable Bot Icon */}
      <div
        ref={botIconRef}
        className={`${styles.botIcon} ${isOpen ? styles.botIconActive : ""} ${isDragging ? styles.dragging : ""} ${isOverDustbin ? styles.botIconDelete : ""} ${skipTransition ? styles.noTransition : ""}`}
        style={{
          left: position.x,
          top: position.y,
        }}
        onMouseDown={handleMouseDown}
        onTouchStart={handleTouchStart}
        onTouchMove={handleTouchMove}
        onTouchEnd={handleTouchEnd}
        onClick={toggleChat}
        title="AI Assistant"
      >
        <SVGIcons icon="fa-robot" width={24} height={24} />
      </div>

      {/* Chat Popup with Fullscreen Blur Overlay */}
      {(isOpen || isAnimating) && (
        <>
          {/* Blur Overlay */}
          <div
            className={`${styles.chatOverlay} ${isOpen ? styles.overlayOpen : styles.overlayClose}`}
            onClick={closeChat}
          />

          {/* Chat Popup */}
          <div
            className={`${styles.chatPopup} ${isOpen ? styles.chatPopupOpen : styles.chatPopupClose}`}
          >
            {/* Header */}
            <div className={styles.chatHeader}>
              <div className={styles.chatHeaderLeft}>
                <div className={styles.chatHeaderIcon}>
                  <SVGIcons icon="brain" width={20} height={20} />
                </div>
                <div className={styles.chatHeaderTitle}>
                  <span className={styles.chatTitle}>IAF Assistant</span>
                  <span className={styles.chatSubtitle}>How can I help you?</span>
                </div>
              </div>
              <div className={styles.chatHeaderActions}>
                <button
                  className={styles.headerButton}
                  onClick={clearChat}
                  title="Clear Chat"
                >
                  <SVGIcons icon="trash" width={16} height={16} />
                </button>
                <button
                  className={styles.headerButton}
                  onClick={closeChat}
                  title="Close"
                >
                  <SVGIcons icon="x" width={16} height={16} />
                </button>
              </div>
            </div>

            {/* Messages Container */}
            <div className={styles.chatMessages} ref={chatContainerRef}>
              {/* Welcome Message */}
              {messages.length === 0 && (
                <div className={styles.welcomeContainer}>
                  <div className={styles.welcomeIcon}>
                    <SVGIcons icon="sparkles" width={32} height={32} />
                  </div>
                  <h3 className={styles.welcomeTitle}>How can I help you?</h3>
                  <p className={styles.welcomeText}>
                    Hi {userName}! I'm your AI assistant powered by Infosys Agentic Foundry. Feel free to ask me anything about tools, agents, or any assistance you need.
                  </p>
                  <div className={styles.welcomeFeatures}>
                    <div className={styles.welcomeFeature}>
                      <SVGIcons icon="bolt" width={16} height={16} />
                      <span>Quick Answers</span>
                    </div>
                    <div className={styles.welcomeFeature}>
                      <SVGIcons icon="circle-check" width={16} height={16} />
                      <span>Reliable Help</span>
                    </div>
                  </div>
                </div>
              )}

              {/* Chat Messages */}
              {messages.map((message) => (
                <div
                  key={message.id}
                  className={`${styles.messageWrapper} ${message.type === USER ? styles.userMessage : styles.botMessage
                    }`}
                >
                  <div className={styles.messageContent}>
                    {message.type === BOT ? (
                      <div className={styles.markdownContent}>
                        {message.isStreaming && !message.content ? (
                          <div className={styles.typingIndicator}>
                            <div className={styles.thinkingWrapper}>
                              <span className={styles.thinkingIcon}>
                                {streamingState.toolName ? (
                                  <SVGIcons icon="wrench" width={16} height={16} />
                                ) : streamingState.nodeName ? (
                                  <SVGIcons icon="bolt" width={16} height={16} />
                                ) : (
                                  <SVGIcons icon="brain" width={16} height={16} />
                                )}
                              </span>
                              <div className={styles.thinkingContent}>
                                <span className={styles.thinkingText}>
                                  {streamingState.nodeName
                                    ? streamingState.nodeName.replace(/_/g, " ")
                                    : "Processing"}
                                </span>
                                {(streamingState.toolName || streamingState.status) && (
                                  <span className={styles.thinkingSubtext}>
                                    {streamingState.toolName && streamingState.toolName}
                                    {streamingState.toolName && streamingState.status && " • "}
                                    {streamingState.status && streamingState.status}
                                  </span>
                                )}
                              </div>
                              <span className={styles.thinkingDots}>
                                <span>.</span>
                                <span>.</span>
                                <span>.</span>
                              </span>
                            </div>
                          </div>
                        ) : (
                          <ReactMarkdown remarkPlugins={[remarkGfm]}>
                            {message.content}
                          </ReactMarkdown>
                        )}
                      </div>
                    ) : (
                      <div className={styles.userMessageContent}>
                        <span>{message.content}</span>
                        {message.attachedFiles && message.attachedFiles.length > 0 && (
                          <div className={styles.attachedFilesDisplay}>
                            {message.attachedFiles.map((file, idx) => (
                              <span key={idx} className={styles.attachedFileTag}>
                                <SVGIcons icon="file" width={12} height={12} />
                                {file.name}
                              </span>
                            ))}
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                </div>
              ))}
            </div>

            {/* Input Area */}
            <div className={styles.chatInputArea}>
              {/* Hidden file input */}
              <input
                ref={fileInputRef}
                type="file"
                multiple
                onChange={handleFileInputChange}
                style={{ display: "none" }}
                accept=".pdf,.docx,.ppt,.pptx,.txt,.xlsx,.json,.csv,.jpg,.png,.jpeg,.py,.js"
              />

              {/* Uploaded files preview */}
              {uploadedFiles.length > 0 && (
                <div className={styles.filesPreview}>
                  {uploadedFiles.map((file, index) => (
                    <div key={file.path || index} className={styles.fileChip} title={file.name}>
                      <SVGIcons icon="file" width={14} height={14} />
                      <span className={styles.fileName}>{truncateFileName(file.name)}</span>
                      <button
                        type="button"
                        className={styles.fileDeleteBtn}
                        onClick={() => handleFileDelete(file.path)}
                        title="Remove file"
                        disabled={isGenerating || isUploadingFiles}
                      >
                        <SVGIcons icon="close" width={12} height={12} />
                      </button>
                    </div>
                  ))}
                </div>
              )}

              {/* Input Row */}
              <div className={styles.inputTopRow}>
                {/* Text Input */}
                <div className={styles.inputWrapper}>
                  {/* Upload Button */}
                  <button
                    type="button"
                    className={styles.uploadButton}
                    onClick={handleFileClick}
                    disabled={isGenerating || isUploadingFiles}
                    title="Upload Files"
                  >
                    <SVGIcons icon="upload" width={18} height={18} />
                    {isUploadingFiles && <span className={styles.uploadingDot}></span>}
                  </button>

                  <textarea
                    ref={inputRef}
                    className={styles.chatInput}
                    value={userInput}
                    onChange={handleTextareaChange}
                    onKeyDown={handleKeyPress}
                    placeholder={!agentId ? "Loading agent..." : "Type your message..."}
                    disabled={isGenerating || !agentId}
                    rows={1}
                  />
                  <div className={styles.inputActions}>
                    <button
                      className={`${styles.sendButton} ${!userInput.trim() || isGenerating ? styles.sendButtonDisabled : ""}`}
                      onClick={sendMessage}
                      disabled={!userInput.trim() || isGenerating || !agentId}
                      title="Send message"
                    >
                      <SVGIcons icon="send" width={18} height={18} />
                    </button>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  );
};

export default FloatingChatBot;
