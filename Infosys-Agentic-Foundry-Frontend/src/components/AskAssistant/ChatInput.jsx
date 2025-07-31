import React, { useState, useRef, useEffect } from "react";
import styles from "./ChatInput.module.css";
import { agentTypesDropdown, CUSTOM_TEMPLATE } from "../../constant";
import useFetch from '../../Hooks/useAxios';

const ChatInput = ({
  agentType,
  setAgentType,
  selectedModel,
  setSelectedModel,
  selectedAgent,
  setSelectedAgent,
  userInput,
  setUserInput,
  agentListDropdown,
  modelsListData,
  isFormValid,
  isGenerating,
  isHumanVerifierEnabled,
  setIsHumanVerifierEnabled,
  isToolVerifierEnabled,
  setIsToolVerifierEnabled,
  onSubmit,
  onNewChat,
  onDeleteChat,
  onLiveTracking,
  onFileUpload,
  onShowHistory,
  // Canvas-related props
  isCanvasVisible,
  onCanvasToggle
}) => {
  const [isListening, setIsListening] = useState(false);
  const [showSettings, setShowSettings] = useState(false);
  const [agentSearchTerm, setAgentSearchTerm] = useState("");
  const [showAgentDropdown, setShowAgentDropdown] = useState(false);
  const [highlightedAgentIndex, setHighlightedAgentIndex] = useState(-1);
  const textareaRef = useRef(null);
  const settingsRef = useRef(null);
  const agentDropdownRef = useRef(null);
  const agentSearchInputRef = useRef(null);
  const agentTriggerRef = useRef(null);

  // Old implementation variables
  const [oldSessionId, setOldSessionId] = useState("");

  // const handleResetChat = async () => {
  //   const data = {
  //     session_id: oldSessionId !== "" ? oldSessionId : session,
  //     agent_id:
  //       agentType !== CUSTOM_TEMPLATE ? selectedAgent : customTemplatId,
  //   };
  //   const response = await resetChat(data);
  //   if (response?.status === "success") {
  //     setMessageData([]);
  //   }
  // };

  // const fetchOldChatsData = async () => {
  //   const data = {
  //     user_email: loggedInUserEmail,
  //     agent_id: selectedAgent,
  //   };
  //   const reseponse = await fetchOldChats(data);
  //   const oldChats = reseponse;
  //   let temp = [];
  //   for (let key in oldChats) {
  //     temp.push({ ...oldChats[key][0], session_id: key });
  //   }
  //   setOldChats(temp);
  // };

  // const handleNewChat = async () => {
  //   const sessionId = await fetchNewChats(loggedInUserEmail);
  //   fetchOldChatsData();
  //   setOldSessionId("");
  //   setSessionId(sessionId);
  //   fetchChatHistory(sessionId);
  // };

  // Filter agents based on search term
  const filteredAgents = agentListDropdown.filter((agent) =>{
    return agent.agentic_application_name?.toLowerCase().includes(agentSearchTerm.toLowerCase())
  }
  );

  // To make tool verifier and human verifier to false when agent type
  // we might have to consider if we needed to reset the toggle on modifiying selectedModel, selectedAgent
  useEffect(() => {
    if (isHumanVerifierEnabled || isToolVerifierEnabled) {
      setIsHumanVerifierEnabled(false);
      setIsToolVerifierEnabled(false);
    }
  }, [agentType]);

  // Reset highlighted index when filtered agents change
  useEffect(() => {
    setHighlightedAgentIndex(-1);
  }, [filteredAgents.length, agentSearchTerm]);

  // Focus management for dropdown
  useEffect(() => {
    if (showAgentDropdown && agentSearchInputRef.current) {
      agentSearchInputRef.current.focus();
    }
  }, [showAgentDropdown]);

  // Auto-resize textarea
  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
      textareaRef.current.style.height = Math.min(textareaRef.current.scrollHeight, 120) + 'px';
    }
  }, [userInput]);
  // Handle click outside for dropdowns
  useEffect(() => {
    const handleClickOutside = (event) => {
      if (settingsRef.current && !settingsRef.current.contains(event.target)) {
        setShowSettings(false);
      }
      if (agentDropdownRef.current && !agentDropdownRef.current.contains(event.target)) {
        closeAgentDropdown();
      }
    };

    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  // Handle form submission
  const handleSubmit = (e) => {
    e.preventDefault();
    if (userInput.trim() && isFormValid && !isGenerating) {
      onSubmit();
    }
  };
  // Handle Enter key
  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSubmit(e);
    }
  };

  // Handle keyboard navigation for agent dropdown
  const handleAgentDropdownKeyDown = (e) => {
    if (!showAgentDropdown) return;

    switch (e.key) {
      case 'ArrowDown':
        e.preventDefault();
        setHighlightedAgentIndex(prev =>
          prev < filteredAgents.length - 1 ? prev + 1 : 0
        );
        break;
      case 'ArrowUp':
        e.preventDefault();
        setHighlightedAgentIndex(prev =>
          prev > 0 ? prev - 1 : filteredAgents.length - 1
        );
        break;
      case 'Enter':
        e.preventDefault();
        if (highlightedAgentIndex >= 0 && filteredAgents[highlightedAgentIndex]) {
          selectAgent(filteredAgents[highlightedAgentIndex]);
        }
        break;
      case 'Escape':
        e.preventDefault();
        closeAgentDropdown();
        break;
      case 'Tab':
        // Allow natural tab behavior to move focus
        if (!e.shiftKey && highlightedAgentIndex >= 0 && filteredAgents[highlightedAgentIndex]) {
          e.preventDefault();
          selectAgent(filteredAgents[highlightedAgentIndex]);
        }
        break;
    }
  };

  // Handle agent selection
  const selectAgent = (agent) => {
    setSelectedAgent(agent);
    closeAgentDropdown();
  };

  // Close agent dropdown and reset states
  const closeAgentDropdown = () => {
    setShowAgentDropdown(false);
    setAgentSearchTerm("");
    setHighlightedAgentIndex(-1);
    if (agentTriggerRef.current) {
      agentTriggerRef.current.focus();
    }
  };
  // Handle agent dropdown trigger click
  const handleAgentDropdownToggle = () => {
    if (showAgentDropdown) {
      closeAgentDropdown();
    } else {
      setShowAgentDropdown(true);
    }
  };

  // Handle settings dropdown keyboard navigation
  const handleSettingsKeyDown = (e) => {
    if (!showSettings) return;

    switch (e.key) {
      case 'Escape':
        e.preventDefault();
        setShowSettings(false);
        // Return focus to settings button
        if (settingsRef.current) {
          const settingsButton = settingsRef.current.querySelector('button');
          if (settingsButton) settingsButton.focus();
        }
        break;
    }
  };

  // Handle toggle slider keyboard events
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

  // Voice recording functions
  const startListening = () => {
    if ('webkitSpeechRecognition' in window || 'SpeechRecognition' in window) {
      const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
      const recognition = new SpeechRecognition();

      recognition.continuous = false;
      recognition.interimResults = false;
      recognition.lang = 'en-US';

      recognition.onstart = () => {
        setIsListening(true);
      };

      recognition.onresult = (event) => {
        const transcript = event.results[0][0].transcript;
        setUserInput(prev => prev + transcript);
        setIsListening(false);
      };

      recognition.onerror = () => {
        setIsListening(false);
      };

      recognition.onend = () => {
        setIsListening(false);
      };

      recognition.start();
    } else {
      alert('Speech recognition is not supported in your browser.');
    }
  };

  const stopListening = () => {
    setIsListening(false);
  };

  // Plan verifier
  // const sendHumanInLoop = async (isApprove = "", feedBack = "", userText) => {
  //     const payload = {
  //       agentic_application_id:
  //         agentType === CUSTOM_TEMPLATE ? customTemplatId : selectedAgent,
  //       query: userText,
  //       session_id: oldSessionId !== "" ? oldSessionId : session,
  //       model_name: selectedModel,
  //       reset_conversation: false,
  //       ...(isApprove !== "" && { approval: isApprove }),
  //       ...(feedBack !== "" && { feedback: feedBack }),
  //       ...(toolInterrupt ? { interrupt_flag: true } : { interrupt_flag: false }),
  //     };
  //     let response;
  //     try {
  //       const url =
  //         agentType === CUSTOM_TEMPLATE
  //           ? APIs.CUSTOME_TEMPLATE_QUERY
  //           : APIs.PLANNER;
  //       response = await postData(url, payload);
  //       setLastResponse(response);
  //       setPlanData(response?.plan);
  //       setMessageData(converToChatFormat(response) || []);
  //     } catch (err) {
  //       console.error(err);
  //     }
  //     return response;
  //   };

  return (
    <div className={styles.container}>
      {/* Top Controls Bar */}
      <div className={styles.topControls}>
        {/* Agent Type Dropdown */}
        <div className={styles.controlGroup}>
          {/* <label className={styles.controlLabel}>Agent Type</label> */}
          <select
            className={styles.select}
            value={agentType}
            onChange={(e) => setAgentType(e.target.value)}
            disabled={isGenerating}
          >
            <option value="">Select Agent Type</option>
            {agentTypesDropdown.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </div>

        {/* Model Dropdown */}
        <div className={styles.controlGroup}>
          {/* <label className={styles.controlLabel}>Model</label> */}
          <select
            className={styles.select}
            value={selectedModel}
            onChange={(e) => setSelectedModel(e.target.value)}
            disabled={isGenerating}
          >
            <option value="">Select Model</option>
            {modelsListData.map((modelOption) => (
              <option key={modelOption.value} value={modelOption.value}>
                {modelOption.label}
              </option>
            ))}
          </select>
        </div>
        
        {/* Agent Dropdown with Search */}
        <div className={styles.controlGroup} ref={agentDropdownRef}>
          {/* <label className={styles.controlLabel}>Agent</label> */}
          <div className={`${styles.searchableDropdown} ${isGenerating ? styles.disabled : ''}`} aria-disabled={isGenerating}>
            <div
              ref={agentTriggerRef}
              className={`${styles.dropdownTrigger} ${showAgentDropdown ? styles.active : ''} ${isGenerating ? styles.disabled : ''}`}
              onClick={!isGenerating ? handleAgentDropdownToggle : undefined}
              onKeyDown={(e) => {
                if (isGenerating) return;
                if (e.key === 'Enter' || e.key === ' ') {
                  e.preventDefault();
                  handleAgentDropdownToggle();
                } else if (e.key === 'ArrowDown' && !showAgentDropdown) {
                  e.preventDefault();
                  setShowAgentDropdown(true);
                }
              }}
              tabIndex={isGenerating ? -1 : 0}
              role="combobox"
              aria-expanded={showAgentDropdown}
              aria-haspopup="listbox"
              aria-label="Select Agent"
              aria-disabled={isGenerating}
            >
              <span>{selectedAgent.agentic_application_name || "Select Agent"}</span>
              <svg width="18" height="18" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg" className={`${styles.chevronIcon} ${showAgentDropdown ? styles.rotated : ''}`}>
                <path d="M6 8L10 12L14 8" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </div>

            {showAgentDropdown && (
              <div
                className={styles.dropdownContent}
                role="listbox"
                aria-label="Agent options"
              >
                <div className={styles.searchContainer}>
                  <svg width="18" height="18" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg" className={styles.searchIcon}>
                    <circle cx="9" cy="9" r="6" stroke="currentColor" strokeWidth="1.5" fill="none"/>
                    <path d="m15 15 4 4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/>
                  </svg>
                  <input
                    ref={agentSearchInputRef}
                    type="text"
                    placeholder="Search agents..."
                    value={agentSearchTerm}
                    onChange={(e) => {
                      setAgentSearchTerm(e.target.value);
                      setHighlightedAgentIndex(-1);
                    }}
                    onKeyDown={handleAgentDropdownKeyDown}
                    className={styles.searchInput}
                    aria-label="Search agents"
                    autoComplete="off"
                  />
                </div>
                <div className={styles.agentsList}>
                  {filteredAgents.length > 0 ? (
                    filteredAgents.map((agent, index) => (
                      <div
                        key={agent.agentic_application_id}
                        className={`${styles.agentItem} ${index === highlightedAgentIndex ? styles.highlighted : ''}`}
                        onClick={() => selectAgent(agent)}
                        onMouseEnter={() => setHighlightedAgentIndex(index)}
                        onKeyDown={(e) => {
                          if (e.key === 'Enter' || e.key === ' ') {
                            e.preventDefault();
                            selectAgent(agent);
                          }
                        }}
                        tabIndex={0}
                        role="option"
                        aria-selected={index === highlightedAgentIndex}
                      >
                        <div className={styles.agentName}>{agent.agentic_application_name}</div>
                          {/* <div className={styles.agentDescription}>Description section</div> */}                  
                      </div>
                    ))
                  ) : (
                    <div className={styles.noAgents}>No agents found</div>
                  )}
                </div>
              </div>
            )}
          </div>
        </div>
      </div>

      {isFormValid && <div className={styles.inputsWrapperRow2}>
        {/* Input Section */}
        <form onSubmit={handleSubmit} className={styles.inputForm}>
          <div className={styles.inputContainer}>
            {/* File Upload Button */}
            <button
              type="button"
              className={styles.inputButton}
              onClick={onFileUpload}
              disabled={isGenerating}
              title="Upload Files"
              tabIndex={0}
            >
              {/* SVG icon for file upload */}
              <svg width="18" height="18" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg">
                <path d="M10 2V14M10 14L6 10M10 14L14 10" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
                <rect x="3" y="15" width="14" height="3" rx="1.5" stroke="currentColor" strokeWidth="1.5" />
              </svg>
            </button>

            {/* Text Input */}
            <div className={styles.textInputWrapper}>
              <textarea
                ref={textareaRef}
                value={userInput}
                onChange={(e) => setUserInput(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder={
                  isFormValid
                    ? "Type your message..."
                    : "Please select Agent Type, Model, and Agent to start chatting"
                }
                disabled={!isFormValid || isGenerating}
                className={styles.textInput}
                rows={1}
              />
            </div>

            {/* Voice/Send Button */}
            <div className={styles.rightButtons}>
              {userInput.trim() ? (
                <button
                  type="submit"
                  className={`${styles.inputButton} ${styles.sendButton}`}
                  disabled={!isFormValid || isGenerating}
                  title="Send Message"
                  tabIndex={0}
                >
                  {/* SVG icon for send */}
                  <svg width="18" height="18" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg">
                    <path d="M3 17L17 10L3 3V8L13 10L3 12V17Z" fill="currentColor" />
                  </svg>
                </button>
              ) : (
                <button
                  type="button"
                  className={`${styles.inputButton} ${isListening ? styles.selected : ''}`}
                  onClick={isListening ? stopListening : startListening}
                  disabled={!isFormValid || isGenerating}
                  title={isListening ? "Stop Recording" : "Voice Input"}
                  tabIndex={0}
                >
                  {/* SVG icon for mic/stop */}
                  {isListening ? (
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
            </div>
          </div>

          {/* Form Validation Message */}
          {/* {!isFormValid && (
            <div className={styles.validationMessage}>
              Please select all required fields (Agent Type, Model, and Agent) to enable messaging.
            </div>
          )} */}

          {/* Recording Indicator */}
          {isListening && (
            <div className={styles.recordingIndicator}>
              <div className={styles.recordingDot}></div>
              <span>Listening... Speak now</span>
            </div>
          )}
        </form>
        {/* Action Buttons */}
        <div className={styles.actionButtons}>
          
          {/* Settings Dropdown */}
          <div className={styles.settingsContainer} ref={settingsRef}>
            <button
              className={`${styles.actionButton} ${showSettings ? styles.active : ''}`}
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
              tabIndex={isGenerating ? -1 : 0}
              
              disabled={!isFormValid || isGenerating}
              aria-expanded={showSettings}
              aria-haspopup="menu"
              aria-label="Settings menu"
              aria-disabled={isGenerating}
            >
              <svg width="18" height="18" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg">
                <rect x="4" y="7" width="12" height="6" rx="3" stroke="currentColor" strokeWidth="1.5" />
                <circle cx="13" cy="10" r="2" fill="currentColor" />
                <circle cx="7" cy="10" r="1.5" stroke="currentColor" strokeWidth="1" fill="none" opacity="0.4" />
              </svg>
            </button>
            {showSettings && (
              <div
                className={styles.settingsDropdown}
                onKeyDown={handleSettingsKeyDown}
                role="menu"
                aria-label="Settings menu"
              >
                <div className={styles.settingsHeader}>Verifier Settings</div>
                <div className={styles.toggleGroup} role="menuitem">
                  <label className={styles.toggleLabel}>
                    <span className={styles.toggleText} id="humanVerifierLabel">Human Verifier</span>
                    <input
                      type="checkbox"
                      checked={isHumanVerifierEnabled}
                      onChange={(e) => setIsHumanVerifierEnabled(e.target.checked)}
                      className={styles.toggleInput}
                      id="humanVerifierToggle"
                    />
                    <span
                      className={styles.toggleSlider}
                      tabIndex={0}
                      role="switch"
                      aria-checked={isHumanVerifierEnabled}
                      aria-labelledby="humanVerifierLabel"
                      onKeyDown={(e) => handleToggleKeyDown(e, setIsHumanVerifierEnabled, isHumanVerifierEnabled)}
                    ></span>
                  </label>
                </div>

                <div className={styles.toggleGroup} role="menuitem">
                  <label className={styles.toggleLabel}>
                    <span className={styles.toggleText} id="toolVerifierLabel">Tool Verifier</span>
                    <input
                      type="checkbox"
                      checked={isToolVerifierEnabled}
                      onChange={(e) => setIsToolVerifierEnabled(e.target.checked)}
                      className={styles.toggleInput}
                      id="toolVerifierToggle"
                    />
                    <span
                      className={styles.toggleSlider}
                      tabIndex={0}
                      role="switch"
                      aria-checked={isToolVerifierEnabled}
                      aria-labelledby="toolVerifierLabel"
                      onKeyDown={(e) => handleToggleKeyDown(e, setIsToolVerifierEnabled, isToolVerifierEnabled)}
                    ></span>
                  </label>
                </div>
              </div>
            )}
          </div>

          {/* Knowledge base */}
          <button
            className={styles.actionButton}
            // onClick={onShowKnowledgeBase}
            title="Knowledge Base"
            tabIndex={0}
            disabled={!isFormValid || isGenerating}
          >
            <svg width="18" height="18" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg">
              <path d="M4 5C4 3.89543 4.89543 3 6 3H14C15.1046 3 16 3.89543 16 5V15C16 16.1046 15.1046 17 14 17H6C4.89543 17 4 16.1046 4 15V5Z" stroke="currentColor" strokeWidth="1.5" />
              <path d="M8 7H12" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
              <path d="M8 10H12" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
              <path d="M8 13H10" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
              <circle cx="6" cy="7" r="0.5" fill="currentColor" />
              <circle cx="6" cy="10" r="0.5" fill="currentColor" />
              <circle cx="6" cy="13" r="0.5" fill="currentColor" />
            </svg>
          </button>
          <button
            className={styles.actionButton}
            onClick={onShowHistory}
            title="Chat History"
            tabIndex={0}
            disabled={!isFormValid || isGenerating}
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
            className={styles.actionButton}
            onClick={onNewChat}
            title="New Chat"
            tabIndex={0}
            disabled={!isFormValid || isGenerating}
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
            className={styles.actionButton}
            onClick={onDeleteChat}
            title="Delete Chat"
            tabIndex={0}
            disabled={!isFormValid || isGenerating}
          >
            <svg width="18" height="18" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg">
              <path d="M7 4V3C7 2.44772 7.44772 2 8 2H12C12.5523 2 13 2.44772 13 3V4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
              <path d="M5 4H15" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
              <path d="M6 4V16C6 17.1046 6.89543 18 8 18H12C13.1046 18 14 17.1046 14 16V4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
              <path d="M8 8V14" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
              <path d="M12 8V14" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
            </svg>
          </button>

          {/* Canvas Toggle Button */}
          {onCanvasToggle && (
            <button
              className={`${styles.actionButton} ${isCanvasVisible ? styles.active : ''}`}
              onClick={onCanvasToggle}
              title={isCanvasVisible ? "Hide Canvas" : "Show Canvas"}
              tabIndex={0}
            >
              <svg width="18" height="18" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg">
                <rect x="2" y="3" width="16" height="11" rx="2" stroke="currentColor" strokeWidth="1.5" />
                <path d="M6 7H11" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
                <path d="M6 9H14" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
                <path d="M6 11H10" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
                <path d="M14 16L16 14L18 16" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </button>
          )}
          <button
            className={styles.actionButton}
            onClick={onLiveTracking}
            title="Live Tracking"
            tabIndex={0}
            disabled={!isFormValid || isGenerating}
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
  );
};

export default ChatInput;
