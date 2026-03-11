import { useState, useCallback, useEffect, useRef, forwardRef, useImperativeHandle } from "react";
import Cookies from "js-cookie";
import SVGIcons from "../../Icons/SVGIcons";
import style from "../../css_modules/ChatPanel.module.css";
import { useMessage } from "../../Hooks/MessageContext";
import useFetch from "../../Hooks/useAxios.js";
import { APIs } from "../../constant";
import IAFButton from "../../iafComponents/GlobalComponents/Buttons/Button";
import CodeEditor from "./CodeEditor";
import { useChatServices } from "../../services/chatService.js";
import { sanitizeInput } from "../../utils/sanitization";
import NewCommonDropdown from "./NewCommonDropdown";

/**
 * ChatPanel - A mini chat interface for code assistance
 * Displays in a side panel with model selection, message history, and input
 * Calls POST /tools/generate/pipeline/chat API for code generation
 *
 * @param {string} pipelineId - Pipeline ID for the chat context
 * @param {Array} models - Array of available model names
 * @param {function} onCodeUpdate - Callback to update code in parent (receives code_snippet)
 * @param {function} onClose - Callback to close the panel
 * @param {string} codeSnippet - Current code snippet from the editor
 * @param {string} toolId - Current tool ID for session management
 * @param {string} chatSessionId - External session ID from parent (optional)
 * @param {function} onSessionIdChange - Callback when new session ID is generated (optional)
 */
const ChatPanel = forwardRef(({ messages, setMessages, pipelineId = "", models = [], onCodeUpdate = () => { }, onClose = () => { }, codeSnippet = "", toolId = "", chatSessionId = "", onSessionIdChange = () => { } }, ref) => {
  const { addMessage } = useMessage();
  const { fetchData, postData, deleteData } = useFetch();

  // Use external chatSessionId if provided, otherwise generate from email + toolId
  const userEmail = Cookies.get("email") || "";
  const [sessionId, setSessionId] = useState(chatSessionId || `${userEmail}_${toolId.replace(/-/g, "_")}`);

  // Chat state
  // const [messages, setMessages] = useState([]);
  const [inputValue, setInputValue] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [selectedModel, setSelectedModel] = useState("");

  // Modal state for code preview
  const [showCodeModal, setShowCodeModal] = useState(false);
  const [selectedCodeSnippet, setSelectedCodeSnippet] = useState("");

  // Refs
  const messagesEndRef = useRef(null);
  const inputRef = useRef(null);

  const { resetChat, fetchNewChats } = useChatServices();

  // Extract model labels from objects (models can be array of strings or objects with label property)
  const modelOptions = models.map((m) => (typeof m === "string" ? m : m?.label || "")).filter(Boolean);

  /**
   * Scroll to bottom of messages container
   */
  const scrollToBottom = useCallback(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, []);

  /**
   * Set default model on mount
   */
  useEffect(() => {
    if (modelOptions.length > 0 && !selectedModel) {
      setSelectedModel(modelOptions[0]);
    }
  }, [models, selectedModel]);

  /**
   * Scroll to bottom when messages update
   */
  useEffect(() => {
    scrollToBottom();
  }, [messages, scrollToBottom]);

  // Track if initial fetch has been done to prevent repeated API calls
  const hasFetchedRef = useRef(false);

  /**
   * Focus input on mount
   */
  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  /**
   * Initialize chat with empty query to get welcome message
   */
  const initializeChat = useCallback(async (currentSessionId = sessionId) => {
    // Section to fetch welcome message from api
    // const payload = {
    //   pipeline_id: pipelineId,
    //   session_id: currentSessionId,
    //   query: "",
    //   model_name: modelOptions[0] || undefined,
    //   reset_conversation: false,
    //   selected_code: "",
    // };

    // const response = await postData(APIs.PIPELINE_CHAT, payload);

    // if (response?.message) {
    //   const botMessage = {
    //     id: Date.now(),
    //     role: "assistant",
    //     content: response.message,
    //     code_snippet: response?.code_snippet || null,
    //     version_number: response?.version_number || null,
    //     timestamp: new Date().toISOString(),
    //   };
    //   setMessages([botMessage]);
    // }

    const botMessage = {
      id: Date.now(),
      role: "assistant",
      content: "Hello! It seems like you're interested in creating a custom Python tool. Let's get started. Which tool do you want to create? Please describe its purpose or functionality. If you're unsure, feel free to provide a general idea or example, and we can refine it together. Once you provide this information, we'll proceed to gather more details step-by-step.",
      code_snippet: null,
      version_number: null,
      timestamp: new Date().toISOString(),
    };
    setMessages([botMessage]);
  }, [pipelineId, sessionId, modelOptions, postData, setMessages]);

  /**
   * Fetch a new session ID from the server
   * Called when chat panel opens for a new tool creation
   * @returns {string|null} - The new session ID or null if failed
   */
  const getNewSessionId = useCallback(async () => {
    try {
      const newSessionId = await fetchNewChats(userEmail);
      if (newSessionId) {
        const sanitizedSessionId = newSessionId.replace(/-/g, "_");
        setSessionId(sanitizedSessionId);
        onSessionIdChange(sanitizedSessionId); // Notify parent about the new session ID
        return sanitizedSessionId;
      }
      return null;
    } catch (error) {
      console.error("Failed to fetch new session ID:", error);
      return null;
    }
  }, [fetchNewChats, userEmail, onSessionIdChange]);

  /**
   * Fetch conversation history or initialize chat on panel open (runs only once)
   */
  useEffect(() => {
    // Only fetch once when panel opens for the first time
    if (hasFetchedRef.current || messages.length > 0) return;
    hasFetchedRef.current = true;

    const onloadFetch = async () => {
      if (toolId) {
        // If toolId exists (editing existing tool), fetch conversation history
        try {
          setIsLoading(true);
          const response = await fetchData(`${APIs.CONVERSATION_HISTORY}${encodeURIComponent(sessionId)}`);

          if (response?.messages && Array.isArray(response.messages) && response.messages.length > 0) {
            // Transform messages from API to match local message format
            // Filter out user messages with empty content (from initialization calls)
            const formattedMessages = response.messages
              .filter((msg) => !(msg.role === "user" && (!msg.message || msg.message.trim() === "")))
              .map((msg, index) => ({
                id: msg.message_id || Date.now() + index,
                role: msg.role,
                content: msg.message || "",
                code_snippet: msg.code_snippet || null,
                version_number: msg.metadata.version_number || null,
                timestamp: msg.timestamp || new Date().toISOString(),
              }));

            // Add welcome message as the first item
            const welcomeMessage = {
              id: Date.now(),
              role: "assistant",
              content: "Hello! It seems like you're interested in creating a custom Python tool. Let's get started. Which tool do you want to create? Please describe its purpose or functionality. If you're unsure, feel free to provide a general idea or example, and we can refine it together. Once you provide this information, we'll proceed to gather more details step-by-step.",
              code_snippet: null,
              version_number: null,
              timestamp: new Date().toISOString(),
            };

            // Combine welcome message with formatted history
            setMessages([welcomeMessage, ...formattedMessages]);
            setIsLoading(false);
          } else {
            // No history exists, initialize chat with empty query
            await initializeChat();
            setIsLoading(false);
          }
        } catch (error) {
          console.error("Failed to fetch conversation history:", error);
          // On error, try to initialize chat
          try {
            await initializeChat();
            setIsLoading(false);
          } catch (initError) {
            console.error("Failed to initialize chat:", initError);
            setIsLoading(false);
          }
        }
      } else {
        // If no toolId (creating new tool), fetch new session ID first
        try {
          setIsLoading(true);
          // Get a new session ID from server for new tool creation
          const newSessionId = await getNewSessionId();
          // Initialize chat with the new session ID
          await initializeChat(newSessionId || sessionId);
        } catch (error) {
          console.error("Failed to initialize chat:", error);
          // Silently fail
        } finally {
          setIsLoading(false);
        }
      }
    };

    onloadFetch();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  /**
   * Handle sending a message
   * @param {string} selectedCode - Optional selected code for "Explain" feature
   */
  const handleSendMessage = useCallback(
    async (selectedCode = "") => {
      const trimmedInput = inputValue.trim();
      const hasSelectedCode = selectedCode && selectedCode.trim() !== "";

      // Need either input value or selected code to proceed
      if ((!trimmedInput && !hasSelectedCode) || isLoading) return;

      // Build the display content for user message
      let displayContent = "";
      if (trimmedInput && hasSelectedCode) {
        // User typed something + explain selected code
        displayContent = trimmedInput;
      } else if (hasSelectedCode) {
        // Only explain selected code (no user input)
        displayContent = "Explain this code:";
      } else {
        // Normal message (no selected code)
        displayContent = trimmedInput;
      }

      // Add user message to chat with selected_code metadata for visual rendering
      const userMessage = {
        id: Date.now(),
        role: "user",
        content: displayContent,
        selected_code: hasSelectedCode ? selectedCode.trim() : null,
        timestamp: new Date().toISOString(),
      };

      setMessages((prev) => [...prev, userMessage]);
      setInputValue(""); // Clear input after sending
      setIsLoading(true);

      // Build the query for the API
      const apiQuery = hasSelectedCode ? (trimmedInput ? `${trimmedInput}\n\nExplain this code:\n${selectedCode}` : `Explain this code:\n${selectedCode}`) : trimmedInput;

      try {
        // Build payload for pipeline chat API
        const payload = {
          pipeline_id: pipelineId,
          session_id: sessionId,
          query: apiQuery,
          model_name: selectedModel || undefined,
          reset_conversation: false,
          selected_code: hasSelectedCode ? selectedCode.trim() : "",
          // Include current_code only if codeSnippet starts with "def "
          ...(codeSnippet && codeSnippet.startsWith("def ") && { current_code: codeSnippet }),
        };

        const response = await postData(APIs.PIPELINE_CHAT, payload);

        // Debug: Log the response to check version_number
        console.log("ChatPanel API Response:", response);

        // Extract response content
        const botContent = response?.message || "I couldn't generate a response.";

        // If response contains code_snippet, update the parent code editor
        if (response?.code_snippet && response?.code_snippet.trim().indexOf("def") !== -1) {
          onCodeUpdate(response.code_snippet);
        }

        const botMessage = {
          id: Date.now() + 1,
          role: "assistant",
          content: botContent,
          code_snippet: response?.code_snippet,
          version_number: response?.version_number || null,
          timestamp: new Date().toISOString(),
        };

        setMessages((prev) => [...prev, botMessage]);
      } catch (error) {
        console.error("Pipeline chat failed:", error);
        addMessage("Failed to get response. Please try again.", "error");

        const errorMessage = {
          id: Date.now() + 1,
          role: "assistant",
          content: "Sorry, I encountered an error. Please try again.",
          timestamp: new Date().toISOString(),
          isError: true,
        };
        setMessages((prev) => [...prev, errorMessage]);
      } finally {
        setIsLoading(false);
        inputRef.current?.focus();
      }
    },
    [inputValue, isLoading, pipelineId, sessionId, selectedModel, postData, addMessage, onCodeUpdate, codeSnippet],
  );

  /**
   * Handle explain code request from external source (e.g., CodeEditor selection)
   * @param {string} selectedCode - The code to explain
   */
  const handleExplainCode = useCallback(
    (selectedCode) => {
      if (!selectedCode || selectedCode.trim() === "") return;
      handleSendMessage(selectedCode);
    },
    [handleSendMessage],
  );

  /**
   * Expose handleExplainCode method and sessionId to parent via ref
   */
  useImperativeHandle(
    ref,
    () => ({
      explainCode: handleExplainCode,
      getNewSessionId: getNewSessionId,
      getCurrentSessionId: () => sessionId,
    }),
    [handleExplainCode, getNewSessionId, sessionId],
  );

  /**
   * Handle key press in input field
   */
  const handleKeyPress = useCallback(
    (e) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        handleSendMessage();
      }
    },
    [handleSendMessage],
  );

  /**
   * Clear chat history, reset server conversation, and get new session ID
   */
  const handleClearChat = useCallback(async () => {
    setMessages([]);
    inputRef.current?.focus();
    setInputValue("");
    setIsLoading(true);

    // Delete conversation from server
    try {
      const deleteUrl = APIs.DELETE_TOOL_BOT_CONVERSATION.replace("{session_id}", encodeURIComponent(sessionId));
      await deleteData(deleteUrl, { pipeline_id: pipelineId });

      const payloadForInference = {
        session_id: sessionId,
        agent_id: pipelineId,
        framework_type: "langgraph",
      };
      await resetChat(payloadForInference);

      // Initialize chat with the new session ID
      await initializeChat(sessionId);
    } catch (error) {
      console.error("Failed to clear conversation:", error);
      // Try to initialize chat anyway
      try {
        await initializeChat();
      } catch (initError) {
        console.error("Failed to initialize chat after clear:", initError);
      }
    } finally {
      setIsLoading(false);
    }
  }, [sessionId, pipelineId, deleteData, initializeChat, setMessages, getNewSessionId, resetChat]);

  /**
   * Render a single message bubble
   */
  const renderMessage = (message) => {
    const isUser = message.role === "user";
    const hasSelectedCode = isUser && message.selected_code;

    return (
      <div key={message.id} className={`${style.messageRow} ${isUser ? style.userMessageRow : style.botMessageRow}`}>
        <div className={`${style.messageBubble} ${isUser ? style.userBubble : style.botBubble} ${message.isError ? style.errorBubble : ""}`}>
          {/* Regular message content */}
          <pre className={style.messageText}>{message.content}</pre>

          {/* Selected code accordion - collapsible */}
          {hasSelectedCode && (
            <details className={style.selectedCodeAccordion}>
              <summary className={style.selectedCodeSummary}>
                <span className={style.selectedCodeIndicator}>
                  <span className={style.codeIcon}>&lt;/&gt;</span>
                  <span>View highlighted code</span>
                </span>
                <span className={style.accordionChevron}>›</span>
              </summary>
              <pre className={style.selectedCodeContent}>{message.selected_code}</pre>
            </details>
          )}
        </div>
        {!isUser && message?.code_snippet?.indexOf("def") > -1 && (
          <div className={style.checkPoint}>
            <span className={style.checkpointIcon} onClick={handleCheckpointIconClick(message.id)}>
              <span className={style.checkpointIcon} onClick={handleCheckpointIconClick(message.id)}>
                {message?.version_number ? (
                  <span>v<span style={{ fontStyle: "italic" }}>{message.version_number}</span></span>
                ) : (
                  "</>"
                )}
              </span>
            </span>
            <span className={style.restoreCodeBtn} onClick={handleCheckpointClick(message.id)}>
              Restore Code
            </span>
          </div>
        )}
      </div>
    );
  };

  const handleCheckpointClick = (messageId) => () => {
    const msg = messages.find((m) => m.id === messageId);

    if (msg?.code_snippet && msg?.code_snippet.indexOf("def") !== -1) onCodeUpdate(msg.code_snippet);
  };

  const handleCheckpointIconClick = (messageId) => () => {
    const msg = messages.find((m) => m.id === messageId);
    if (msg?.code_snippet && msg?.code_snippet.indexOf("def") !== -1) {
      setSelectedCodeSnippet(msg.code_snippet);
      setShowCodeModal(true);
    }
  };

  /**
   * Close code preview modal
   */
  const handleCloseCodeModal = () => {
    setShowCodeModal(false);
    setSelectedCodeSnippet("");
  };

  /**
   * Restore code from modal to editor
   */
  const handleRestoreCode = () => {
    if (selectedCodeSnippet) {
      onCodeUpdate(selectedCodeSnippet);
      handleCloseCodeModal();
    }
  };

  return (
    <div className={style.chatPanelContainer}>
      {/* Header */}
      <div className={style.chatHeader}>
        <div className={style.chatHeaderTitle}>
          <SVGIcons icon="chat-bubble" width={20} height={20} fill="var(--primary-color)" />
          <span>Code Assistant</span>
        </div>
        <div className={style.chatHeaderActions}>
          <button type="button" className={style.clearButton} onClick={handleClearChat} title="Clear chat" disabled={messages.length === 0 || isLoading}>
            <SVGIcons icon="trash" width={14} height={14} color="currentColor" />
          </button>
          <button className="closeBtn" onClick={onClose} type="button" title="Close chat panel">
            ×
          </button>
        </div>
      </div>

      {/* Messages Area */}
      <div className={style.messagesContainer}>
        {messages.length === 0 ? (
          <div className={style.emptyState}>
            <SVGIcons icon="sparkles" width={40} height={40} />
            <p>AI Code Assistant</p>
            <span>Generate, refactor, or debug your code</span>
            <div className={style.typingIndicator}>
              <span></span>
              <span></span>
              <span></span>
            </div>
          </div>
        ) : (
          <>
            {messages.map(renderMessage)}
            {isLoading && (
              <div className={`${style.messageRow} ${style.botMessageRow}`}>
                <div className={`${style.messageBubble} ${style.botBubble} ${style.loadingBubble}`}>
                  <div className={style.typingIndicator}>
                    <span></span>
                    <span></span>
                    <span></span>
                  </div>
                </div>
              </div>
            )}
            <div ref={messagesEndRef} />
          </>
        )}
      </div>

      {/* Input Area */}
      <div className={style.inputArea}>
        {/* Compact Model Dropdown */}
        <div className={style.modelChip}>
          <NewCommonDropdown
            options={modelOptions}
            selected={selectedModel}
            onSelect={(val) => setSelectedModel(val)}
            placeholder="Model"
            showSearch={modelOptions.length > 5}
            disabled={isLoading}
            selectFirstByDefault={true}
          />
        </div>

        {/* Message Input */}
        <div className={style.inputWrapper}>
          <textarea
            id="chat-input"
            ref={inputRef}
            className={style.chatInput}
            value={inputValue}
            onChange={(e) => setInputValue(sanitizeInput(e.target.value, "text"))}
            onKeyDown={handleKeyPress}
            placeholder="Ask about your code..."
            rows={1}
            disabled={isLoading}
          />
        </div>

        {/* Send Button */}
        <button type="button" className={style.sendButton} onClick={() => handleSendMessage()} disabled={!inputValue.trim() || isLoading} title="Send message">
          <SVGIcons icon="send" width={16} height={16} fill="currentColor" />
        </button>
      </div>

      {/* Code Preview Modal */}
      {showCodeModal && selectedCodeSnippet && (
        <div className={style.modalOverlay} onClick={handleCloseCodeModal}>
          <div className={style.modal} onClick={(e) => e.stopPropagation()}>
            <button className={"closeBtn " + style.closeBtn} onClick={handleCloseCodeModal} type="button" title="Close modal">
              ×
            </button>
            <h3 className={style.modalTitle}>Code Preview</h3>
            <div className={style.modalBody}>
              <div className={style.codeEditorContainer}>
                <CodeEditor codeToDisplay={selectedCodeSnippet} readOnly={true} mode="python" width="100%" height="400px" fontSize={13} />
              </div>
            </div>
            <div className={style.modalFooter}>
              <IAFButton type="secondary" onClick={handleCloseCodeModal}>
                Close
              </IAFButton>
              <IAFButton type="primary" onClick={handleRestoreCode}>
                Restore Code
              </IAFButton>
            </div>
          </div>
        </div>
      )}
    </div>
  );
});

ChatPanel.displayName = "ChatPanel";
export default ChatPanel;

