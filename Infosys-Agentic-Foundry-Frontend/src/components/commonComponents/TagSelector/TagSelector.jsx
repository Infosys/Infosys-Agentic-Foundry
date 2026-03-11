import React, { useState, useEffect, useRef } from "react";
import ReactDOM from "react-dom";
import styles from "./TagSelector.module.css";
import { APIs } from "../../../constant";
import useFetch from "../../../Hooks/useAxios";
import TextField from "../../../iafComponents/GlobalComponents/TextField/TextField";

function TagSelector({ selectedTags = [], onTagsChange, multiSelect = true, showSearch = true, nonRemovableTags = [], disabled = false }) {
  const [allTags, setAllTags] = useState([]);
  const [showDropdown, setShowDropdown] = useState(false);
  const [loading, setLoading] = useState(false);
  const [highlightedIndex, setHighlightedIndex] = useState(-1);
  const [dropdownPosition, setDropdownPosition] = useState({ top: 0, left: 0, direction: "bottom" });
  const [isKeyboardMode, setIsKeyboardMode] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const dropdownRef = useRef(null);
  const containerRef = useRef(null);
  const plusButtonRef = useRef(null);
  const scrollRAFRef = useRef(null);
  const tagItemSearchRef = useRef(null);
  const listContainerRef = useRef(null);
  const lastKeyPressTime = useRef(0);
  const { fetchData } = useFetch();

  // Get available tags (tags that are not selected)
  const availableTags = allTags.filter((tag) => !selectedTags.some((selectedTag) => selectedTag.tag_id === tag.tag_id));

  // Filter available tags based on search query
  const filteredTags = availableTags.filter((tag) => tag.tag_name.toLowerCase().includes(searchQuery.toLowerCase()));

  // Fetch tags from API
  const fetchTags = async () => {
    try {
      setLoading(true);
      const data = await fetchData(APIs.GET_TAGS);
      if (data && Array.isArray(data)) {
        setAllTags(data);
      }
    } catch (error) {
      console.error("Error fetching tags:", error);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchTags();
  }, []);

  // Scroll to highlighted item when it changes (for keyboard navigation)
  useEffect(() => {
    if (isKeyboardMode && highlightedIndex >= 0) {
      // Cancel any pending scroll animation
      if (scrollRAFRef.current) {
        cancelAnimationFrame(scrollRAFRef.current);
      }

      // Schedule scroll for next animation frame for smooth rendering
      scrollRAFRef.current = requestAnimationFrame(() => {
        scrollToHighlightedItem(highlightedIndex);
      });
    }

    return () => {
      if (scrollRAFRef.current) {
        cancelAnimationFrame(scrollRAFRef.current);
      }
    };
  }, [highlightedIndex, isKeyboardMode]);

  // Handle tag selection
  const handleTagSelect = (tag) => {
    const newSelectedTags = [...selectedTags, tag];
    onTagsChange(newSelectedTags);
    // Only close dropdown if multiSelect is false
    if (!multiSelect) {
      setShowDropdown(false);
      setHighlightedIndex(-1);
    }
  };

  // Handle tag removal - prevent removing non-removable tags
  const handleTagRemove = (tagToRemove) => {
    // Check if tag is in non-removable list
    const isNonRemovable = nonRemovableTags.some((tag) => tag.tag_id === tagToRemove.tag_id);

    if (isNonRemovable) {
      return; // Don't remove non-removable tags
    }

    const newSelectedTags = selectedTags.filter((tag) => tag.tag_id !== tagToRemove.tag_id);
    onTagsChange(newSelectedTags);
  };

  // Handle plus icon click
  const handlePlusClick = () => {
    if (availableTags.length > 0) {
      const willOpen = !showDropdown;
      setShowDropdown(willOpen);
      setHighlightedIndex(-1);
      setIsKeyboardMode(false);
      setSearchQuery(""); // Reset search when opening dropdown

      // Calculate dropdown position when opening
      if (willOpen) {
        // Use requestAnimationFrame to ensure DOM is updated
        requestAnimationFrame(() => {
          calculateDropdownPosition();
        });
      }

      // Reset dropdown scroll position when opening and focus search input
      setTimeout(() => {
        if (showSearch && tagItemSearchRef.current) {
          const input = tagItemSearchRef.current.querySelector("input");
          if (input) input.focus();
        }
        if (listContainerRef.current) {
          listContainerRef.current.scrollTop = 0;
        }
      }, 0);
    }
  };

  // Calculate optimal dropdown position based on viewport space and plus button position
  const calculateDropdownPosition = () => {
    if (plusButtonRef.current) {
      const rect = plusButtonRef.current.getBoundingClientRect();
      const dropdownWidth = 250; // Approximate width

      // Always open above the + icon, using bottom so it sticks to the icon
      let direction = "top";
      let bottom = window.innerHeight - rect.top + 4; // 4px gap above the button
      let left = rect.left;

      // Ensure dropdown doesn't go off-screen horizontally
      if (left + dropdownWidth > window.innerWidth) {
        left = window.innerWidth - dropdownWidth - 10;
      }
      if (left < 10) {
        left = 10;
      }

      setDropdownPosition({ bottom, left, direction });
    }
  };

  // Update dropdown position when showDropdown changes or when scrolling/resizing
  useEffect(() => {
    if (showDropdown) {
      calculateDropdownPosition();
    }
  }, [showDropdown]);

  // Handle keyboard navigation - only for dropdown
  const handleDropdownKeyDown = (event) => {
    // Throttle arrow key navigation to reduce scroll speed on long press
    const ARROW_KEY_DELAY = 200; // milliseconds between arrow key actions
    const now = Date.now();
    const isArrowKey = event.key === "ArrowDown" || event.key === "ArrowUp";

    if (isArrowKey && now - lastKeyPressTime.current < ARROW_KEY_DELAY) {
      event.preventDefault();
      event.stopPropagation();
      return;
    }

    if (isArrowKey) {
      lastKeyPressTime.current = now;
    }

    switch (event.key) {
      case "Tab":
        // Close dropdown on Tab key in multiSelect mode
        if (multiSelect) {
          setShowDropdown(false);
          setHighlightedIndex(-1);
          setIsKeyboardMode(false);
          setSearchQuery("");
          event.preventDefault();
          event.stopPropagation();
          // Return focus to plus button
          if (plusButtonRef.current) {
            plusButtonRef.current.focus();
          }
        }
        break;

      case "Escape":
        setShowDropdown(false);
        setHighlightedIndex(-1);
        setIsKeyboardMode(false);
        setSearchQuery("");
        event.preventDefault();
        event.stopPropagation();
        // Return focus to plus button
        if (plusButtonRef.current) {
          plusButtonRef.current.focus();
        }
        break;

      case "ArrowDown":
        event.preventDefault();
        event.stopPropagation();
        setIsKeyboardMode(true);
        setHighlightedIndex((prev) => {
          const nextIndex = prev === -1 ? 0 : Math.min(prev + 1, filteredTags.length - 1);
          return nextIndex;
        });
        break;

      case "ArrowUp":
        event.preventDefault();
        event.stopPropagation();
        setIsKeyboardMode(true);
        setHighlightedIndex((prev) => {
          const prevIndex = prev === -1 ? 0 : Math.max(prev - 1, 0);
          return prevIndex;
        });
        break;

      case " ":
      case "Enter":
        event.preventDefault();
        event.stopPropagation();
        if (highlightedIndex >= 0 && highlightedIndex < filteredTags.length) {
          handleTagSelect(filteredTags[highlightedIndex]);
          setSearchQuery(""); // Reset search after selection
          setHighlightedIndex(-1);
        }
        break;

      default:
        break;
    }
  };

  // Scroll highlighted item into view with precise control
  const scrollToHighlightedItem = (index) => {
    if (!listContainerRef.current || index < 0 || index >= filteredTags.length) return;

    const listContainer = listContainerRef.current;
    // Sanitize selector to avoid trailing +
    let itemClass = styles.pickerDropdownItem;
    if (itemClass.endsWith("+")) {
      itemClass = itemClass.slice(0, -1);
    }
    const items = listContainer.querySelectorAll(`.${itemClass}`);

    if (!items || index >= items.length) return;

    const highlightedElement = items[index];
    if (!highlightedElement) return;

    // Get the item's offset relative to the scrollable container
    const itemOffsetTop = highlightedElement.offsetTop;
    const itemHeight = highlightedElement.offsetHeight;
    const containerScrollTop = listContainer.scrollTop;
    const containerHeight = listContainer.clientHeight;

    // Calculate the visible range
    const visibleTop = containerScrollTop;
    const visibleBottom = containerScrollTop + containerHeight;

    // Add a small padding to make scrolling feel better
    const padding = 2;

    // Check if item is not fully visible and scroll if needed
    if (itemOffsetTop < visibleTop + padding) {
      // Item is above visible area - scroll up to show it at the top
      listContainer.scrollTop = itemOffsetTop - padding;
    } else if (itemOffsetTop + itemHeight > visibleBottom - padding) {
      // Item is below visible area - scroll down to show it at the bottom
      listContainer.scrollTop = itemOffsetTop + itemHeight - containerHeight + padding;
    }
    // If item is already fully visible, don't scroll
  };

  // Handle mouse wheel scroll to update highlighted item
  const handleWheel = (event) => {
    if (!listContainerRef.current) return;

    setIsKeyboardMode(false);

    // After scroll, find which item is most visible and highlight it
    requestAnimationFrame(() => {
      if (!listContainerRef.current) return;

      const listContainer = listContainerRef.current;
      const listRect = listContainer.getBoundingClientRect();
      const listCenter = listRect.top + listRect.height / 2;

      let closestIndex = -1;
      let closestDistance = Infinity;

      // Find the item closest to the center of the list container
      let itemClass = styles.pickerDropdownItem;
      if (itemClass.endsWith("+")) {
        itemClass = itemClass.slice(0, -1);
      }
      Array.from(listContainer.querySelectorAll(`.${itemClass}`)).forEach((child, index) => {
        const childRect = child.getBoundingClientRect();
        const childCenter = childRect.top + childRect.height / 2;
        const distance = Math.abs(childCenter - listCenter);

        if (distance < closestDistance) {
          closestDistance = distance;
          closestIndex = index;
        }
      });

      if (closestIndex !== -1 && closestIndex !== highlightedIndex) {
        setHighlightedIndex(closestIndex);
      }
    });
  };

  // Close dropdown when clicking outside
  useEffect(() => {
    const handleClickOutside = (event) => {
      // Check if click is outside both the container AND the dropdown (which is in a portal)
      const isOutsideContainer = containerRef.current && !containerRef.current.contains(event.target);
      const isOutsideDropdown = dropdownRef.current && !dropdownRef.current.contains(event.target);

      if (isOutsideContainer && isOutsideDropdown) {
        setShowDropdown(false);
        setHighlightedIndex(-1);
      }
    };

    const updatePosition = () => {
      if (plusButtonRef.current) {
        const rect = plusButtonRef.current.getBoundingClientRect();
        const dropdownWidth = 250;

        // Always open above the + icon, using bottom so it sticks to the icon
        let direction = "top";
        let bottom = window.innerHeight - rect.top + 4;
        let left = rect.left;

        // Ensure dropdown doesn't go off-screen horizontally
        if (left + dropdownWidth > window.innerWidth) {
          left = window.innerWidth - dropdownWidth - 10;
        }
        if (left < 10) {
          left = 10;
        }

        setDropdownPosition({ bottom, left, direction });
      }
    };

    const handleResize = () => {
      if (showDropdown) {
        requestAnimationFrame(updatePosition);
      }
    };

    const handleScroll = () => {
      if (showDropdown) {
        requestAnimationFrame(updatePosition);
      }
    };

    const handleEscapeKey = (event) => {
      if (event.key === "Escape" && showDropdown) {
        event.stopPropagation();
        setShowDropdown(false);
        setHighlightedIndex(-1);
        setIsKeyboardMode(false);
        setSearchQuery("");
        // Return focus to plus button
        if (plusButtonRef.current) {
          plusButtonRef.current.focus();
        }
      }
    };

    const handleTabKey = (event) => {
      if (event.key === "Tab" && showDropdown && multiSelect) {
        // Only close on Tab in multiSelect mode
        setShowDropdown(false);
        setHighlightedIndex(-1);
        setIsKeyboardMode(false);
        setSearchQuery("");
      }
    };

    // Only add listeners when dropdown is open
    if (showDropdown) {
      // Initial position update
      requestAnimationFrame(updatePosition);

      document.addEventListener("mousedown", handleClickOutside);
      document.addEventListener("keydown", handleEscapeKey);
      document.addEventListener("keydown", handleTabKey);
      window.addEventListener("resize", handleResize);
      window.addEventListener("scroll", handleScroll, true);
    }

    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
      document.removeEventListener("keydown", handleEscapeKey);
      document.removeEventListener("keydown", handleTabKey);
      window.removeEventListener("resize", handleResize);
      window.removeEventListener("scroll", handleScroll, true);
    };
  }, [showDropdown, multiSelect, selectedTags]);

  return (
    <div className={styles.tagContainer} ref={containerRef}>
      <div className={styles.pickerWrapper}>
        <span className={`${styles.tagPickerLabel} label-desc`}>Tags</span>
        <div className={`${styles.pillsContainer} ${disabled ? styles.pillsContainerDisabled : ""}`}>
          {selectedTags.map((tag) => {
            const isNonRemovable = nonRemovableTags.some((t) => t.tag_id === tag.tag_id);

            return (
              <span key={tag.tag_id} className={styles.tagPill}>
                <span className={styles.tagPillText} tabIndex={-1}>
                  {tag.tag_name}
                </span>
                {!isNonRemovable && !disabled && (
                  <span
                    className={styles.removeTagBtn}
                    onClick={() => handleTagRemove(tag)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" || e.key === " ") {
                        e.preventDefault();
                        handleTagRemove(tag);
                      }
                    }}
                    tabIndex={0}
                    aria-label={`Remove ${tag.tag_name}`}>
                    ×
                  </span>
                )}
              </span>
            );
          })}
        </div>
        {!disabled && (
          <div
            ref={plusButtonRef}
            className={`smallAddBtn ${availableTags.length === 0 || loading ? "disabled" : ""}`}
            onClick={availableTags.length > 0 && !loading ? handlePlusClick : undefined}
            onKeyDown={(e) => {
              if (availableTags.length === 0 || loading) return;
              if (e.key === " " || e.key === "Enter") {
                e.preventDefault();
                handlePlusClick();
              } else if (showDropdown && (e.key === "ArrowDown" || e.key === "ArrowUp")) {
                handleDropdownKeyDown(e);
              }
            }}
            aria-label="Add tag"
            title={loading ? "Loading tags..." : availableTags.length === 0 ? "No more tags available" : "Add tag"}
            tabIndex={availableTags.length > 0 && !loading ? 0 : -1}>
            +
          </div>
        )}
      </div>
      {showDropdown && availableTags.length > 0 && ReactDOM.createPortal(
        <div
          className={`${styles.pickerDropdown} ${dropdownPosition.direction === "top" ? styles.dropdownTop : styles.dropdownBottom}`}
          ref={dropdownRef}
          style={{
            position: "fixed",
            bottom: `${dropdownPosition.bottom}px`,
            left: `${dropdownPosition.left}px`,
            zIndex: 1000010,
          }}
          onKeyDown={handleDropdownKeyDown}
          onMouseLeave={() => {
            // Close dropdown when mouse leaves in multiSelect mode, but not while searching
            if (multiSelect && !searchQuery) {
              setShowDropdown(false);
              setHighlightedIndex(-1);
              setIsKeyboardMode(false);
              setSearchQuery("");
            }
          }}
          onMouseMove={() => {
            // Re-enable mouse mode when mouse actually moves
            if (isKeyboardMode) {
              setIsKeyboardMode(false);
            }
          }}
          tabIndex={-1}>
          {/* Search input - always at top */}
          {showSearch && (
            <div className={styles.searchContainer} ref={tagItemSearchRef}>
              <TextField
                placeholder="Search tags..."
                value={searchQuery}
                onChange={(e) => {
                  setSearchQuery(e.target.value);
                  setHighlightedIndex(-1); // Reset highlight when searching
                }}
                onClear={() => {
                  setSearchQuery("");
                  setHighlightedIndex(-1);
                }}
                showClearButton={true}
                showSearchButton={true}
                onKeyDown={(e) => {
                  // Allow arrow keys to navigate to list items
                  if (e.key === "ArrowDown" || e.key === "ArrowUp") {
                    handleDropdownKeyDown(e);
                  } else if (e.key === "Escape") {
                    handleDropdownKeyDown(e);
                  } else if (e.key === "Tab") {
                    handleDropdownKeyDown(e);
                  }
                }}
                onClick={(e) => e.stopPropagation()}
                aria-label="Search tags"
              />
            </div>
          )}

          {/* List items container */}
          <div className={styles.listItemsContainer} ref={listContainerRef} onWheel={handleWheel}>
            {loading ? (
              <div className={styles.loading}>Loading tags...</div>
            ) : filteredTags.length === 0 ? (
              <div className={styles.noResults}>No tags found</div>
            ) : (
              filteredTags.map((tag, index) => (
                <div
                  key={tag.tag_id}
                  className={`${styles.pickerDropdownItem} ${index === highlightedIndex ? styles.highlighted : ""}`}
                  onClick={() => {
                    handleTagSelect(tag);
                    setSearchQuery(""); // Reset search after selection
                    setHighlightedIndex(-1);
                  }}
                  onMouseEnter={() => {
                    // Only update highlight on mouse enter if not in keyboard mode
                    if (!isKeyboardMode) {
                      setHighlightedIndex(index);
                    }
                  }}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === " ") {
                      e.preventDefault();
                      e.stopPropagation();
                      handleTagSelect(tag);
                      setSearchQuery(""); // Reset search after selection
                      setHighlightedIndex(-1);
                    }
                  }}
                  role="option"
                  aria-selected={index === highlightedIndex}>
                  <span className={styles.tagText}>{tag.tag_name}</span>
                </div>
              ))
            )}
          </div>
        </div>,
        document.body
      )}
    </div>
  );
}

export default TagSelector;