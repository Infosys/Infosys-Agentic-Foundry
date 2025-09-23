import React, { useState, useEffect, useRef } from 'react';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import { faTimes, faChevronUp, faChevronDown } from '@fortawesome/free-solid-svg-icons';
import styles from './PromptSuggestions.module.css';

const PromptSuggestions = ({ onClose, onSelectPrompt, isVisible, promptSuggestions = [] }) => {
  const [isExpanded, setIsExpanded] = useState(false);
  const [isClosing, setIsClosing] = useState(false);
  const [focusedIndex, setFocusedIndex] = useState(0);
  const promptRefs = useRef([]);

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

  const promptsToShow = promptSuggestions.length > 0 ? promptSuggestions : defaultPrompts;
  const visiblePrompts = isExpanded ? promptsToShow : promptsToShow.slice(0, 8);

  // Focus management
  useEffect(() => {
    if (isVisible && !isClosing && promptRefs.current[focusedIndex]) {
      promptRefs.current[focusedIndex].focus();
    }
  }, [focusedIndex, isVisible, isClosing, promptsToShow.length]);

  // Keyboard navigation
  useEffect(() => {
    if (!isVisible || isClosing) return;
    const handleKeyDown = (e) => {
      if (['ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight', 'Enter', ' '].includes(e.key)) {
        e.preventDefault();
      }
      const numCols = 2; // Assume 2 columns for grid navigation
      const numRows = Math.ceil(promptsToShow.length / numCols);
      let nextIndex = focusedIndex;
      switch (e.key) {
        case 'ArrowUp':
          nextIndex = focusedIndex - numCols;
          break;
        case 'ArrowDown':
          nextIndex = focusedIndex + numCols;
          break;
        case 'ArrowLeft':
          nextIndex = focusedIndex - 1;
          break;
        case 'ArrowRight':
          nextIndex = focusedIndex + 1;
          break;
        case 'Enter':
        case ' ': // Spacebar
          handlePromptClick(promptsToShow[focusedIndex]);
          return;
        default:
          return;
      }
      if (nextIndex < 0) nextIndex = 0;
      if (nextIndex >= promptsToShow.length) nextIndex = promptsToShow.length - 1;
      setFocusedIndex(nextIndex);
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isVisible, isClosing, focusedIndex, promptsToShow]);

  useEffect(() => {
    if (!isVisible) setFocusedIndex(0);
  }, [isVisible]);

  const handlePromptClick = (prompt) => {
    onSelectPrompt(prompt);
    onClose();
  };

  const toggleExpanded = () => {
    setIsExpanded(!isExpanded);
  };

  const handleClose = () => {
    setIsClosing(true);
    setTimeout(() => {
        setIsClosing(false);
        onClose();
    }, 300); // match animation duration
  };

  if (!isVisible && !isClosing) return null;

  return (
    <div className={`${styles.overlay} ${isClosing ? styles.closing : ''}`} onClick={(e) => e.target === e.currentTarget && handleClose()}>
        <div className={`${styles.slider} ${isExpanded ? styles.expanded : ''} ${isClosing ? styles.closing : ''}`}>
            {/* Header */}
            <div className={styles.header}>
                <div className={styles.headerContent}>
                <svg width="18" height="18" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg" className={styles.headerIcon}>
                    <path d="M10 2L12.09 6.26L17 7L13.5 10.74L14.18 15.74L10 13.77L5.82 15.74L6.5 10.74L3 7L7.91 6.26L10 2Z" 
                    stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" fill="none"/>
                    <path d="M6 3L7 5L9 4" stroke="currentColor" strokeWidth="1" strokeLinecap="round" opacity="0.6"/>
                    <path d="M15 4L16 6L18 5" stroke="currentColor" strokeWidth="1" strokeLinecap="round" opacity="0.6"/>
                    <path d="M4 12L5 14L7 13" stroke="currentColor" strokeWidth="1" strokeLinecap="round" opacity="0.6"/>
                </svg>
                <h3 className={styles.title}>Prompt Suggestions</h3>
                </div>
                <button className={styles.closeButton} onClick={handleClose}>
                <FontAwesomeIcon icon={faTimes} />
                </button>
            </div>

            {/* Prompts Grid */}
            <div className={styles.promptsContainer}>
                <div className={styles.promptsGrid}>
                {promptsToShow.map((prompt, index) => (
                    <div
                    key={index}
                    ref={el => promptRefs.current[index] = el}
                    tabIndex={0}
                    className={`${styles.promptCard} ${focusedIndex === index ? styles.focusedPrompt : ''}`}
                    onClick={() => handlePromptClick(prompt)}
                    onFocus={() => setFocusedIndex(index)}
                    >
                    <span className={styles.promptText}>{prompt}</span>
                    </div>
                ))}
                </div>
            </div>

            {/* Footer with expand/collapse button */}
            <div className={styles.footer}>
                <button className={styles.expandButton} onClick={toggleExpanded}>
                <FontAwesomeIcon icon={isExpanded ? faChevronDown : faChevronUp} className={styles.expandIcon} />
                <span>{isExpanded ? 'Show Less' : 'Show More'}</span>
                </button>
            </div>
        </div>
    </div>
  );
};

export default PromptSuggestions;
