import React, {
  useState,
  useRef,
  useEffect,
  forwardRef,
  useImperativeHandle,
} from "react";
import "./AgenticChat.css";
import { APIs } from '../../constant';
import { useAuditContext } from "../../context/AuditContext";
import ModelSelectorPopover from "../commonComponents/ModelSelectorPopover/ModelSelectorPopover";

const AgenticChat = forwardRef((props, ref) => {
  const { setAuditData } = useAuditContext();

  const [messages, setMessages] = useState([
    {
      id: "1",
      text: "Hello! I can help you analyze your documents and provide insights on audit findings.",
      sender: "ai",
      timestamp: new Date(),
    },
  ]);

  useImperativeHandle(ref, () => ({
    resetChat: () => {
      setMessages([
        {
          id: "1",
          text: "Hello! I can help you analyze your documents and provide insights on audit findings.",
          sender: "ai",
          timestamp: new Date(),
        },
      ]);
      setIsTyping(false);
    },
  }));

  const [inputMessage, setInputMessage] = useState("");
  const [isTyping, setIsTyping] = useState(false);
  const chatContainerRef = useRef(null);
  const [uploadedFiles, setUploadedFiles] = useState([]);
  const [filePaths, setFilePaths] = useState([]);
  const [isPdfPreviewOpen, setIsPdfPreviewOpen] = useState(false);
  const [pdfPreviewUrl, setPdfPreviewUrl] = useState(null);
  const [pdfPreviewName, setPdfPreviewName] = useState("");
  const [socket, setSocket] = useState(null);
  const idleTimeoutRef = useRef(null);
  const [showSummaryContent, setShowSummaryContent] = useState(false);

  const resetIdleTimeout = () => {
    if (idleTimeoutRef.current) clearTimeout(idleTimeoutRef.current);
    idleTimeoutRef.current = setTimeout(() => {
      if (socket) {
        socket.close();
        setSocket(null);
      }
    }, 10 * 60 * 1000);
  };

  const initializeWebSocket = (pathsTotheFile) => {
    const ws = new WebSocket("");
    ws.onopen = () => {
      resetIdleTimeout();
      const data = {
        session_id: "test_socket_123",
        question: inputMessage,
        file_info: JSON.stringify(pathsTotheFile),
      };
      if (ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify(data));
      } else {
        setIsTyping(false);
        setSocket(null);
      }
    };

    ws.onmessage = (event) => {
      resetIdleTimeout();
      try {
        const data = JSON.parse(event.data);
        if (data.type === "chat" || data.type === "summary") {
          const aiMessage = {
            id: (Date.now() + 1).toString(),
            text: data.final_response || String(event.data.final_response),
            sender: data.type === "summary" ? "ai button" : "ai",
            timestamp: new Date(),
          };
          setMessages((prevMessages) => [...prevMessages, aiMessage]);
        } else {
          setAuditData(data);
        }
      } catch (e) {
        setMessages((prevMessages) => [...prevMessages, {
          id: (Date.now() + 1).toString(),
          text: String(event.data),
          sender: "ai",
          timestamp: new Date(),
        }]);
      }
      setIsTyping(false);
    };

    ws.onerror = () => {
      setIsTyping(false);
      ws.close();
      setSocket(null);
    };

    ws.onclose = () => {
      setIsTyping(false);
      setSocket(null);
      if (idleTimeoutRef.current) clearTimeout(idleTimeoutRef.current);
    };

    setSocket(ws);
  };

  useEffect(() => {
    return () => {
      if (socket) socket.close();
      if (idleTimeoutRef.current) clearTimeout(idleTimeoutRef.current);
    };
  }, [socket]);

  // With column-reverse layout, we need to handle scrolling differently
  useEffect(() => {
    // For column-reverse layout, the initial scroll position is already at the "bottom" (which is visually the top)
    if (chatContainerRef.current) {
      chatContainerRef.current.scrollTop = 0;
    }
  }, [messages]);

  const handleSendMessage = async () => {
    setIsTyping(true); // show loader and disable button as soon as user clicks send
    setAuditData(null); // Clear audit data when sending a new message after summary

    if (inputMessage.trim() === "") return;

    let newFilePaths = [...filePaths];

    // Upload new files if any (files that don't have a file-path yet)
    const filesToUpload = uploadedFiles.filter((_, idx) => !filePaths[idx]);
    if (filesToUpload.length > 0) {
      // Upload the files to server and get the file-location value
      // const response = await uploadFile(filesToUpload);
      const response = {file_infos: []}; // Mock response for testing

      // Assume uploadData.file_infos is an array of file-paths in the same order
      if (response && response.file_infos) {
        response.file_infos.forEach((fileInfo) => {
          newFilePaths.push(fileInfo.file_location);
        });
        setFilePaths(newFilePaths);
      }
      else {
        console.error("File upload failed or returned unexpected data:", response);
        setMessages((prevMessages) => [...prevMessages, {
          id: (Date.now() + 2).toString(),
          text: 'Unfortunately chat couldnt be delivered. Please retry',
          sender: 'ai error',
          timestamp: new Date(),
        }]);
        return;
      }
    }

    const userMessage = {
      id: Date.now().toString(),
      text: inputMessage,
      sender: "user",
      timestamp: new Date(),
    };

    setMessages((prevMessages) => [...prevMessages, userMessage]);
    setInputMessage("");

    // WebSocket logic
    if (!socket || socket.readyState !== WebSocket.OPEN) {
      initializeWebSocket(newFilePaths);
    }

    const chatPayload = {
      session_id: "test_session_id",
      file_info: JSON.stringify(newFilePaths),
      question: inputMessage,
    };

    const sendMessage = () => {
      if (socket && socket.readyState === WebSocket.OPEN) {
        socket.send(JSON.stringify(chatPayload));
        resetIdleTimeout();
      } else {
        console.warn("WebSocket is not open. Message not sent.");
      }
    };

    sendMessage();
  };

  const handleKeyDown = (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSendMessage();
    }
  };

  const formatTime = (date) => {
    return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  };

  const formatFileSize = (bytes) => {
    if (bytes < 1024) return bytes + ' B';
    else if (bytes < 1048576) return (bytes / 1024).toFixed(1) + ' KB';
    else return (bytes / 1048576).toFixed(1) + ' MB';
  };

  const handleFileChange = (event) => {
    if (event.target.files) {
      const selectedFiles = Array.from(event.target.files);

      // Enforce maximum of 2 files
      if (uploadedFiles.length + selectedFiles.length > 2) {
        alert('You can only upload a maximum of 2 files.');
        return;
      }

      setUploadedFiles((prevFiles) => [...prevFiles, ...selectedFiles]);
    }
  };

  const handleRemoveFile = (index) => {
    setUploadedFiles((prevFiles) => prevFiles.filter((_, i) => i !== index));
    setFilePaths((prevPaths) => prevPaths.filter((_, i) => i !== index));
  };

  const handlePreviewPdf = (file) => {
    setPdfPreviewUrl(URL.createObjectURL(file));
    setPdfPreviewName(file.name);
    setIsPdfPreviewOpen(true);
  };

  const handleShowSummary = () => {
    setShowSummaryContent(true);
    setPdfPreviewName("Audit Summary");
    setIsPdfPreviewOpen(true);
  };

  const handleClosePreview = () => {
    if (pdfPreviewUrl) URL.revokeObjectURL(pdfPreviewUrl);
    setIsPdfPreviewOpen(false);
    setPdfPreviewUrl(null);
    setPdfPreviewName("");
    setShowSummaryContent(false);
  };

  const [feedback, setFeedback] = useState({});

  const handleFeedback = (messageId, feedbackType) => {
    setFeedback((prevFeedback) => ({
      ...prevFeedback,
      [messageId]: prevFeedback[messageId] === feedbackType ? null : feedbackType, // Update feedback for the specific message
    }));
    // Optionally, send this feedback to the server
  };

  useEffect(() => {
    if (chatContainerRef.current) {
      chatContainerRef.current.scrollTop = chatContainerRef.current.scrollHeight;
    }
  }, [messages]);

  const [isAgentTypePopoverOpen, setIsAgentTypePopoverOpen] = useState(false);
  const [selectedAgentType, setSelectedAgentType] = useState("Gemini 2.5 Pro"); // Default model

  const [isModelPopoverOpen, setIsModelPopoverOpen] = useState(false);
  const [selectedModel, setSelectedModel] = useState("Gemini 2.5 Pro"); // Default model

  const [isAgentPopoverOpen, setIsAgentPopoverOpen] = useState(false);
  const [selectedAgent, setSelectedAgent] = useState("Gemini 2.5 Pro"); // Default model


  const handleAgenttypeSelect = (agentType) => {
    setSelectedAgentType(agentType);
  };

  const handleModelSelect = (model) => {
    setSelectedModel(model);
  };

  const handleAgentSelect = (agent) => {
    setSelectedAgent(agent);
  };

  useEffect(() => {
    if (chatContainerRef.current) {
      chatContainerRef.current.scrollTop = chatContainerRef.current.scrollHeight;
    }
  }, [messages]);

  return (
    <div className={`chat-container`}>
      <div className="chat-content">

        <div className="chat-messages" ref={chatContainerRef}>
          {isTyping && (
            <div className="typing-indicator">
              <span></span>
              <span></span>
              <span></span>
            </div>
          )}

          {messages
            .map((message, index) => (
              <div
                key={message.id}
                className={`message-with-feedback ${index === messages.length - 1 ? "message-appear" : ""}}`}
              >
                <div className={`message ${message.sender}`}>
                  {message.text}
                  <span className="message-time">
                    {formatTime(message.timestamp)}
                  </span>
                  {message.sender === "ai button" && (
                    <button
                      className="view-summary-button"
                      onClick={handleShowSummary}
                    >
                      View Summary
                    </button>
                  )}
                </div>
                {message.sender === "ai" && message.id !== "1" && (
                  <div className="feedback-icons">
                    <button
                      className={`like-button ${feedback[message.id] === "like" ? "active" : ""}`}
                      onClick={() => handleFeedback(message.id, "like")}
                      title="Like"
                    >
                      👍
                    </button>
                    <button
                      className={`dislike-button ${feedback[message.id] === "dislike" ? "active" : ""}`}
                      onClick={() => handleFeedback(message.id, "dislike")}
                      title="Dislike"
                    >
                      👎
                    </button>
                  </div>
                )}
              </div>
            ))
            .reverse()}
        </div>

        {/* Display uploaded files with improved styling */}
        {uploadedFiles.length > 0 && (
          <div className="uploaded-files">
            {uploadedFiles.map((file, index) => (
              <div
                key={index}
                className="file-item"
                style={{ cursor: "pointer" }}
                onClick={() => handlePreviewPdf(file)}
                title="Click to preview PDF"
              >
                <span className="file-name" title={file.name}>
                  {file.name.length > 5 ? `${file.name.slice(0, 5)}...` : file.name}
                  <span className="file-size">{formatFileSize(file.size)}</span>
                </span>
                <button
                  className="delete-icon"
                  onClick={e => {
                    e.stopPropagation();
                    handleRemoveFile(index);
                  }}
                  title="Remove file"
                >
                  x
                </button>
              </div>
            ))}
          </div>
        )}

        <div className="chat-input-container">
          <div className={`chat-input-wrapper ${isTyping ? 'disabled' : ''}`}>
            <input
              type="file"
              id="fileInput"
              accept=".pdf"
              multiple
              onChange={handleFileChange}
              style={{ display: "none" }}
            />

            <textarea
              className="chat-input"
              value={inputMessage}
              onChange={(e) => setInputMessage(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Type a message..."
              disabled={isTyping}
              rows={1}
            />
          </div>
          <div className={`chat-input-buttons ${isTyping ? 'disabled' : ''}`}>
            <div className="left-buttons">
              <button
                className="attach-button"
                onClick={() => document.getElementById("fileInput")?.click()}
                aria-label="Attach file"
                title="Attach files (PDF only, max 2 files)"
              >
                <span className="icon-wrapper">
                  <svg width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
                    <path d="M21.44 11.05l-9.19 9.19a5.5 5.5 0 01-7.78-7.78l9.19-9.19a3.5 3.5 0 014.95 4.95l-9.19 9.19a1.5 1.5 0 01-2.12-2.12l8.48-8.48" />
                  </svg>
                </span>
              </button>

              {/*Agent Type Selector*/}
              <div className="model-selector-wrapper">
                <button
                  className="model-selector-button"
                  onClick={() => setIsAgentTypePopoverOpen(!isAgentTypePopoverOpen)}
                  aria-label="Select Agent Type"
                  title="Select Agent Type"
                >
                  <span className="icon-wrapper">
                    <svg
                      width="18"
                      height="18"
                      viewBox="0 0 24 24"
                      fill="none"
                      stroke="#2c6ecb"
                      strokeWidth="2"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                    >
                      {/* System/AI type icon */}
                      <rect x="5" y="5" width="14" height="8" rx="2" />
                      {/* Connection points */}
                      <path d="M12 13v3" />
                      {/* Base/Stand */}
                      <path d="M8 16h8" />
                      {/* Dropdown indicator */}
                      <path d="M9 20l3 1 3-1" />
                    </svg>
                  </span>
                  <span className="model-name"> {selectedAgentType}</span>
                </button>
              
                {/* Agent Type Selector Popover */}
                <ModelSelectorPopover
                  isOpen={isAgentTypePopoverOpen}
                  onClose={() => setIsAgentTypePopoverOpen(false)}
                  onModelSelect={handleAgenttypeSelect}
                  selectedModel={selectedAgentType}
                />
              </div>

              {/* Model Selector */}
              <div className="model-selector-wrapper">
                <button
                  className="model-selector-button"
                  onClick={() => setIsModelPopoverOpen(!isModelPopoverOpen)}
                  aria-label="Select Model"
                  title="Select Model"
                >
                  <span className="icon-wrapper">
                    <svg
                      width="18"
                      height="18"
                      viewBox="0 0 24 24"
                      fill="none"
                      stroke="#2c6ecb"
                      strokeWidth="2"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      >
                      {/* AI chip outline */}
                      <rect x="5" y="5" width="14" height="14" rx="3" />
                      {/* AI text or dots */}
                      <circle cx="12" cy="12" r="2.5" />
                      {/* Selector caret */}
                      <path d="M9 17l3 3 3-3" />
                    </svg>
                  </span>
                  <span className="model-name"> {selectedModel}</span>
                </button>
              
                {/* Model Selector Popover */}
                <ModelSelectorPopover
                  isOpen={isModelPopoverOpen}
                  onClose={() => setIsModelPopoverOpen(false)}
                  onModelSelect={handleModelSelect}
                  selectedModel={selectedModel}
                />
              </div>

              {/* Agent Selector */}
              <div className="model-selector-wrapper">
                <button
                  className="model-selector-button"
                  onClick={() => setIsAgentPopoverOpen(!isAgentPopoverOpen)}
                  aria-label="Select Agent"
                  title="Select Agent"
                >
                  <span className="icon-wrapper">
                    <svg
                      width="18"
                      height="18"
                      viewBox="0 0 24 24"
                      fill="none"
                      stroke="#2c6ecb"
                      strokeWidth="2"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                    >
                      {/* Agent/Robot head */}
                      <rect x="7" y="4" width="10" height="10" rx="2" />
                      {/* Eyes */}
                      <circle cx="10" cy="8" r="1" />
                      <circle cx="14" cy="8" r="1" />
                      {/* Antenna */}
                      <path d="M12 2v2" />
                      {/* Connection/Network lines */}
                      <path d="M6 15l6 5 6-5" />
                    </svg>
                  </span>
                  <span className="model-name"> {selectedAgent}</span>
                </button>
              
                {/* Agent Selector Popover */}
                <ModelSelectorPopover
                  isOpen={isAgentPopoverOpen}
                  onClose={() => setIsAgentPopoverOpen(false)}
                  onModelSelect={handleAgentSelect}
                  selectedModel={selectedAgent}
                />
              </div>
            </div>
            <div className="right-buttons">
              <button
                className="send-button"
                onClick={handleSendMessage}
                disabled={(!inputMessage.trim() && uploadedFiles.length === 0) || isTyping}
                aria-label="Send message"
              >
                <span className="icon-wrapper">
                  <svg width="18" height="18" fill="currentColor" viewBox="0 0 24 24">
                    <path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z" />
                  </svg>
                </span>
              </button>
            </div>
          </div>
        </div>
      </div>

      {isPdfPreviewOpen && (
        <div className="modal-overlay" onClick={handleClosePreview}>
          <div className="pdf-modal-content" onClick={e => e.stopPropagation()}>
            <div className="pdf-modal-header">
              <h3>{pdfPreviewName}</h3>
              <button className="modal-close-icon" onClick={handleClosePreview}>
                <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <line x1="18" y1="6" x2="6" y2="18"></line>
                  <line x1="6" y1="6" x2="18" y2="18"></line>
                </svg>
              </button>
            </div>
            <div className="pdf-modal-body">
              {!showSummaryContent && pdfPreviewUrl ? (
                <iframe
                  src={`${pdfPreviewUrl}#toolbar=0`}
                  title="PDF Preview"
                  width="100%"
                  height="100%"
                  className="pdf-iframe"
                />
              ) : (
                <div className="summary-content">
                  <h4>Audit Summary</h4>
                  <div className="summary-details">
                    {/* Connect to your audit data from context here */}
                    <p>This is where the audit summary will be displayed.</p>
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
});

export default AgenticChat;