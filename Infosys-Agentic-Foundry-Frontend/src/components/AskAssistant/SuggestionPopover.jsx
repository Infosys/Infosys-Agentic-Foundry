import { useRef, useEffect, useState } from "react";
import chatInputModule from "./ChatInput.module.css";

const SuggestionPopover = ({ suggestions, userValue, onSelect, visible, onClose }) => {
  const popoverRef = useRef(null);
  const [highlightedIndex, setHighlightedIndex] = useState(null);

  // Filter out recommendations that are already in history
  const filteredRecommendations = suggestions.recommendations.filter((recommendation) => !suggestions.history.includes(recommendation));

  // Find index of suggestion that matches userValue
  const allSuggestions = [...suggestions.history, ...filteredRecommendations];
  const matchedIndex = userValue ? allSuggestions.findIndex((item) => item.trim() === userValue.trim()) : -1;

  useEffect(() => {
    if (!visible) return;
    setHighlightedIndex(null); // No highlight by default
    const handleClickOutside = (event) => {
      if (popoverRef.current && !popoverRef.current.contains(event.target)) {
        onClose && onClose();
      }
    };
    document.addEventListener("mousedown", handleClickOutside);
    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
    };
  }, [visible, onClose, suggestions]);

  // Keyboard navigation for popover
  useEffect(() => {
    if (!visible) return;
    const totalItems = allSuggestions.length;
    const handleKeyDown = (e) => {
      if (!visible) return;
      if (!totalItems) return;

      if (["ArrowDown", "ArrowUp", "Enter"].includes(e.key)) {
        e.stopPropagation();
      }
      switch (e.key) {
        case "ArrowDown":
          e.preventDefault();
          setHighlightedIndex((prev) => {
            if (prev === null) return 0; // Start highlighting
            if (prev < totalItems - 1) return prev + 1;
            return null; // Remove highlight if at last item
          });
          break;
        case "ArrowUp":
          e.preventDefault();
          setHighlightedIndex((prev) => {
            if (prev === null) return totalItems - 1; // Start from last
            if (prev > 0) return prev - 1;
            return null; // Remove highlight if at first item
          });
          break;
        case "Enter":
          e.preventDefault();
          let selectedSuggestion = null;
          // Always select highlighted suggestion if any
          if (highlightedIndex !== null && highlightedIndex >= 0) {
            selectedSuggestion = allSuggestions[highlightedIndex];
            onSelect(selectedSuggestion, false);
          } else if (userValue && userValue.trim().length > 0) {
            // Only select userValue if nothing is highlighted
            onSelect(userValue.trim(), true);
          }
          break;
        case "Escape":
          e.preventDefault();
          onClose && onClose();
          break;
        default:
          break;
      }
    };
    document.addEventListener("keydown", handleKeyDown, true);
    return () => {
      document.removeEventListener("keydown", handleKeyDown, true);
    };
  }, [visible, highlightedIndex, suggestions, filteredRecommendations, onSelect, onClose, userValue, matchedIndex, allSuggestions]);

  if (!visible || (!suggestions.history.length && !filteredRecommendations.length)) return null;

  return (
    <div ref={popoverRef} className={chatInputModule.suggestionPopover}>
      {suggestions.history.length > 0 && (
        <div className={chatInputModule.suggestionSection}>
          <div className={chatInputModule.suggestionLabel}>
            <svg width="18" height="18" viewBox="0 0 20 20" fill="none" aria-label="History" xmlns="http://www.w3.org/2000/svg" style={{ verticalAlign: "middle" }}>
              <circle cx="10" cy="10" r="7" stroke="currentColor" strokeWidth="1.3" fill="none" />
              <path d="M10 6V10L13 12" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" />
              {/* <path d="M4.5 10a5.5 5.5 5.5 0 1 1 2.5 4.7" stroke="currentColor" strokeWidth="1.1" strokeLinecap="round" fill="none" />
              <path d="M4.5 10H7" stroke="currentColor" strokeWidth="1.1" strokeLinecap="round" />
              <path d="M4.5 10l1.5 1.5" stroke="currentColor" strokeWidth="1.1" strokeLinecap="round" /> */}
            </svg>
            <span>History</span>
          </div>
          <ul className={chatInputModule.suggestionList}>
            {suggestions.history.map((item, idx) => {
              const isHighlighted = highlightedIndex === idx;
              return (
                <li
                  key={item + idx}
                  className={`${chatInputModule.suggestionItem} ${isHighlighted ? chatInputModule.highlighted : ""}`}
                  onClick={() => onSelect(item, false)}
                  tabIndex={0}
                  style={isHighlighted ? { background: "#e0f2fe", color: "#007acc" } : {}}>
                  {item}
                </li>
              );
            })}
          </ul>
        </div>
      )}
      {filteredRecommendations.length > 0 && (
        <div className={chatInputModule.suggestionSection}>
          <div className={chatInputModule.suggestionLabel}>
            <svg width="18" height="18" viewBox="0 0 20 20" fill="none" aria-label="Recommended" xmlns="http://www.w3.org/2000/svg" style={{ verticalAlign: "middle" }}>
              <path d="M10 3.5V7.5" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" />
              <path d="M10 12.5V16.5" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" />
              <path d="M3.5 10H7.5" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" />
              <path d="M12.5 10H16.5" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" />
              <circle cx="10" cy="10" r="2.8" stroke="currentColor" strokeWidth="1.1" fill="none" />
              <path d="M10 8.5L10 11.5" stroke="currentColor" strokeWidth="0.9" strokeLinecap="round" opacity="0.7" />
              <path d="M8.5 10L11.5 10" stroke="currentColor" strokeWidth="0.9" strokeLinecap="round" opacity="0.7" />
              <circle cx="15.2" cy="5.2" r="0.7" fill="currentColor" opacity="0.7" />
              <circle cx="4.8" cy="15.2" r="0.7" fill="currentColor" opacity="0.7" />
            </svg>
            <span>Suggested</span>
          </div>
          <ul className={chatInputModule.suggestionList}>
            {filteredRecommendations.map((item, idx) => {
              const actualIndex = suggestions.history.length + idx;
              const isHighlighted = highlightedIndex === actualIndex;
              return (
                <li
                  key={item + idx}
                  className={`${chatInputModule.suggestionItem} ${isHighlighted ? chatInputModule.highlighted : ""}`}
                  onClick={() => onSelect(item)}
                  tabIndex={0}
                  style={isHighlighted ? { background: "#e0f2fe", color: "#007acc" } : {}}>
                  {item}
                </li>
              );
            })}
          </ul>
        </div>
      )}
    </div>
  );
};

export default SuggestionPopover;
