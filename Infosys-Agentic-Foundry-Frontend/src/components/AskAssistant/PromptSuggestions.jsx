import React, { useState, useEffect, useRef } from 'react';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import { faTimes, faChevronUp, faChevronDown } from '@fortawesome/free-solid-svg-icons';
import styles from './PromptSuggestions.module.css';
import SVGIcons from "../../Icons/SVGIcons";

const PromptSuggestions = React.forwardRef(({ onClose, onSelectPrompt, isVisible, promptSuggestions = [], filteredSuggestions = [], cachedSuggestions = {}, searchText = "", openedViaIcon = false, onFocusedIndexChange }, ref) => {
  // no expand/collapse; keep a compact list
  const [isClosing, setIsClosing] = useState(false);
  const [focusedIndex, setFocusedIndex] = useState(-1); // Start with no focus
  const promptRefs = useRef([]);

  // Notify parent whenever focusedIndex changes so it knows if a suggestion is highlighted
  useEffect(() => {
    if (onFocusedIndexChange) {
      onFocusedIndexChange(focusedIndex);
    }
  }, [focusedIndex, onFocusedIndexChange]);



  // Use promptSuggestions from props, fallback to default if empty
  const defaultPrompts = [
    "Analyze the data trends and provide insights",
    "Create a comprehensive report on market performance",
    "Summarize the key findings from the research",
    "Generate a project timeline with milestones",
    "Explain the benefits and drawbacks of this approach",
    "Compare different solutions and recommend the best one",
    "Write a detailed technical documentation",
    "Create a step-by-step implementation guide",
    "Analyze user feedback and suggest improvements",
    "Draft a professional email for client communication",
    "Generate test cases for the new feature",
    "Create a risk assessment matrix",
    "Develop a training plan for the team",
    "Write a performance optimization strategy",
    "Generate creative content ideas for marketing"
  ];

  // Get history from cached suggestions (user's past queries)
  const historyPrompts = cachedSuggestions?.user_history || [];
  
  // Check if user is actively searching (typing 2+ characters)
  const safeSearchText = searchText || "";
  const isSearching = safeSearchText.trim().length >= 2;
  const searchTerm = isSearching ? safeSearchText.toLowerCase().trim() : "";
  
  // Filter function for search - only filter when actively searching
  const filterBySearch = (items) => {
    if (!isSearching) return items;
    return items.filter(item => item && item.toLowerCase().includes(searchTerm));
  };

  // Apply filtering to history and suggested prompts
  const filteredHistory = filterBySearch(historyPrompts);
  // Use default prompts if promptSuggestions is empty or undefined
  const suggestedPrompts = (promptSuggestions && promptSuggestions.length > 0) ? promptSuggestions : defaultPrompts;
  const filteredSuggestedPrompts = filterBySearch(suggestedPrompts);
  
  // Always show at least 5 suggested prompts when not searching
  const visiblePrompts = isSearching ? filteredSuggestedPrompts.slice(0, 8) : suggestedPrompts.slice(0, 5);
  
  // Get user and agent history for the new layout
  const userHistory = cachedSuggestions?.user_history || [];
  const agentHistory = cachedSuggestions?.agent_history || [];
  const filteredUserHistory = filterBySearch(userHistory);
  const filteredAgentHistory = filterBySearch(agentHistory);
  
  // Determine which mode we're in
  const showHistoryMode = !openedViaIcon && isSearching;
  
  // query_library suggestions for icon click mode
  const suggestions = promptSuggestions && promptSuggestions.length > 0 ? promptSuggestions : [];
  
  // Combined list for keyboard navigation - depends on mode
  const allVisibleItems = showHistoryMode 
    ? [...filteredUserHistory.slice(0, 5), ...filteredAgentHistory.slice(0, 5)]
    : suggestions;

  // Focus management - only focus when using keyboard navigation
  // Removed auto-focus on open to prevent unwanted highlight

  // Keyboard navigation
  useEffect(() => {
    if (!isVisible || isClosing) return;
    const handleKeyDown = (e) => {
      // Only handle navigation when we have items
      if (allVisibleItems.length === 0) return;
      
      let nextIndex = focusedIndex;
      
      switch (e.key) {
        case 'ArrowUp':
          e.preventDefault();
          // Move up one item, stop at first item (no wrap)
          if (focusedIndex > 0) {
            nextIndex = focusedIndex - 1;
          }
          break;
        case 'ArrowDown':
          e.preventDefault();
          // Move down one item, stop at last item (no wrap)
          if (focusedIndex === -1) {
            nextIndex = 0;
          } else if (focusedIndex < allVisibleItems.length - 1) {
            nextIndex = focusedIndex + 1;
          }
          break;
        case 'Enter':
          // Select the focused item
          if (focusedIndex >= 0 && focusedIndex < allVisibleItems.length && allVisibleItems[focusedIndex]) {
            e.preventDefault();
            handlePromptClick(allVisibleItems[focusedIndex]);
          }
          return;
        case 'Escape':
          e.preventDefault();
          onClose();
          return;
        default:
          return;
      }
      setFocusedIndex(nextIndex);
      // Scroll focused item into view
      if (promptRefs.current[nextIndex]) {
        promptRefs.current[nextIndex].scrollIntoView({ block: 'nearest', behavior: 'smooth' });
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isVisible, isClosing, focusedIndex, allVisibleItems, onClose]);

  useEffect(() => {
    if (!isVisible) setFocusedIndex(-1); // Reset to no focus when panel closes
  }, [isVisible]);

  const handlePromptClick = (prompt) => {
    onSelectPrompt(prompt);
    onClose();
  };

  // removed toggleExpanded; always show compact suggestions

  const handleClose = () => {
    setIsClosing(true);
    setTimeout(() => {
        setIsClosing(false);
        onClose();
    }, 200); // shorter fade
  };

  if (!isVisible && !isClosing) return null;

  // If in history mode and no matching results in both lists, hide the popup
  if (showHistoryMode && filteredUserHistory.length === 0 && filteredAgentHistory.length === 0) {
    return null;
  }

  return (
    <div ref={ref} className={`${styles.overlay} ${isClosing ? styles.closing : ""}`}> 

      <div className={`${styles.slider} ${isClosing ? styles.closing : ""}`}>
        {/* Fixed header with title and close button */}
        <div className={styles.fixedHeader}>
          <div className={styles.sectionHeading}>
            {showHistoryMode ? (
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                <path d="M12 7v5l3 2" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"/>
                <circle cx="12" cy="12" r="8" stroke="currentColor" strokeWidth="1.6"/>
              </svg>
            ) : (
              <SVGIcons icon="sparkles" width={16} height={16} />
            )}
            <span>{showHistoryMode ? "History" : "Suggestions"}</span>
          </div>
          <button
            className={styles.closeButton}
            onClick={handleClose}
            aria-label="Close"
          >
            <FontAwesomeIcon icon={faTimes} />
          </button>
        </div>

        {/* Scrollable content area */}
        <div className={styles.promptsContainer}>
          {showHistoryMode ? (
            // TYPING MODE: Show user_history as History, agent_history as Suggested
            <>
              {/* History Section (user_history) */}
              <div className={styles.section}>
                <div className={styles.sectionList}>
                  {filteredUserHistory.length > 0 &&
                    filteredUserHistory.slice(0, 5).map((prompt, idx) => (
                      <div
                        key={`history-${idx}`}
                        ref={(el) => (promptRefs.current[idx] = el)}
                        tabIndex={0}
                        className={`${styles.promptCard} ${focusedIndex === idx ? styles.promptCardFocused : ""}`}
                        onClick={() => handlePromptClick(prompt)}
                        onFocus={() => setFocusedIndex(idx)}
                      >
                        <span className={styles.promptText}>{prompt}</span>
                      </div>
                    ))
                  }
                </div>
              </div>

              {/* Suggested Section (agent_history) */}
              <div className={styles.section}>
                <div className={styles.sectionHeaderRow}>
                  <div className={styles.sectionHeading}>
                    <SVGIcons icon="sparkles" width={16} height={16} />
                    <span>Suggested</span>
                  </div>
                </div>
                <div className={styles.sectionDivider}></div>
                <div className={styles.sectionList}>
                  {filteredAgentHistory.length > 0 ? (
                    filteredAgentHistory.slice(0, 5).map((prompt, index) => {
                      const globalIndex = filteredUserHistory.slice(0, 5).length + index;
                      return (
                        <div
                          key={`suggested-${index}`}
                          ref={(el) => (promptRefs.current[globalIndex] = el)}
                          tabIndex={0}
                          className={`${styles.promptCard} ${focusedIndex === globalIndex ? styles.promptCardFocused : ""}`}
                          onClick={() => handlePromptClick(prompt)}
                          onFocus={() => setFocusedIndex(globalIndex)}
                        >
                          <span className={styles.promptText}>{prompt}</span>
                        </div>
                      );
                    })
                  ) : (
                    <div className={styles.emptyState}>
                      <span className={styles.emptyText}>No matching suggestions</span>
                    </div>
                  )}
                </div>
              </div>
            </>
          ) : (
            // ICON CLICK MODE: Show only query_library suggestions
            <div className={styles.section}>
              <div className={styles.sectionList}>
                {suggestions.length > 0 ? (
                  suggestions.map((prompt, index) => (
                    <div
                      key={`suggestion-${index}`}
                      ref={(el) => (promptRefs.current[index] = el)}
                      tabIndex={0}
                      className={`${styles.promptCard} ${focusedIndex === index ? styles.promptCardFocused : ""}`}
                      onClick={() => handlePromptClick(prompt)}
                      onFocus={() => setFocusedIndex(index)}
                    >
                      <span className={styles.promptText}>{prompt}</span>
                    </div>
                  ))
                ) : (
                  <div className={styles.emptyState}>
                    <span className={styles.emptyText}>No suggestions available</span>
                  </div>
                )}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
});

export default PromptSuggestions;
