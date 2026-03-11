import { useRef, useEffect, useState } from "react";
import chatInputModule from "./ChatInput.module.css";
import SVGIcons from "../../Icons/SVGIcons";

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
      {/* Close button */}
      <button className={chatInputModule.suggestionCloseButton} onClick={() => onClose && onClose()} aria-label="Close suggestions">
        <SVGIcons icon="close-small" width={16} height={16} stroke="currentColor" />
      </button>

      {suggestions.history.length > 0 && (
        <div className={chatInputModule.suggestionSection}>
          <div className={chatInputModule.suggestionLabel}>
            <SVGIcons icon="history-clock" width={18} height={18} stroke="currentColor" />
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
                  tabIndex={0}>
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
            <SVGIcons icon="star-outline" width={18} height={18} stroke="currentColor" />
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
                  tabIndex={0}>
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
