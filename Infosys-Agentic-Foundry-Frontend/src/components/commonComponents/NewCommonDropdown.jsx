import { useState, useRef, useEffect, useId } from "react";
import { createPortal } from "react-dom";
import styles from "../../css_modules/NewCommonDropdown.module.css";
import SVGIcons from "../../Icons/SVGIcons.js";
import CheckBox from "../../iafComponents/GlobalComponents/CheckBox/CheckBox.jsx";
import TextField from "../../iafComponents/GlobalComponents/TextField/TextField.jsx";

const NewCommonDropdown = ({
  options = [],
  selected = "",
  onSelect = () => { },
  placeholder = "Select...",
  width,
  maxWidth,
  dropdownWidth,
  multiSelect = false,
  showCheckbox = false,
  selectedItems = [],
  onApply = null,
  onClear = null,
  showSearch = true,
  applyLabel = "Apply",
  clearLabel = "Clear",
  dropdownName = "",
  footerType = "default",
  disabled = false,
  hideFooter = false,
  onSelectionChange = null,
  prefixIcon = null,
  selectFirstByDefault = false,
  showClearIcon = false,
  optionMetadata = {},
  optionTooltips = {},
  onDropdownOpen = null,
  showTypeFilter = false,
  typeFilterOptions = [],
  selectedTypeFilter = "all",
  onTypeFilterChange = null,
  showSelectedOnTop = false,
  // New label props
  label = "", // Optional label text
  labelPosition = "top", // "top" | "left" - position of label relative to dropdown
  required = false, // Show required asterisk
  className = "", // Custom className for root
  theme = "", // "dark" | "" - Theme variant for dropdown
  onOptionDelete = null, // Callback for delete icon on each option (opt) => void
  forceDirection = null, // "up" | "down" | null - Force dropdown direction (overrides auto-detection)
  fixedHeight = false, // When true, dropdown maintains fixed 280px height (for agent/@mention dropdowns)
  defaultOpen = false, // When true, dropdown opens automatically on mount
}) => {
  const newdropId = useId();
  const dropdownId = `dropdown-${newdropId}`;
  // ...existing code...
  const [open, setOpen] = useState(false);
  const [highlighted, setHighlighted] = useState(-1);
  const [search, setSearch] = useState("");
  const [direction, setDirection] = useState("down");
  const [isKeyboardNavigation, setIsKeyboardNavigation] = useState(false);
  const [stagedItems, setStagedItems] = useState(selectedItems);
  const [hasApplied, setHasApplied] = useState(false);
  const [dropdownStyle, setDropdownStyle] = useState({});
  const [internalTypeFilter, setInternalTypeFilter] = useState(selectedTypeFilter);
  const [showTypeDropdown, setShowTypeDropdown] = useState(false);
  const listRef = useRef(null);
  const optionsContainerRef = useRef(null);
  const optionRefs = useRef([]);
  const inputRef = useRef(null);
  const lastKeyPressTime = useRef(0);
  const typeFilterRef = useRef(null);

  // ...existing code (all the existing logic stays the same)...
  const filteredOptions = options.filter((opt) => !search || opt.toLowerCase().includes(search.toLowerCase()));

  const selectedOption = showSelectedOnTop && selected ? selected : null;
  const displayOptions = showSelectedOnTop && selected ? filteredOptions.filter((opt) => opt !== selected) : filteredOptions;

  const autoSelectDoneRef = useRef(false);

  useEffect(() => {
    autoSelectDoneRef.current = false;
  }, [JSON.stringify(options)]);

  useEffect(() => {
    if (selectFirstByDefault && (!selected || selected.trim() === "")) {
      autoSelectDoneRef.current = false;
    }
  }, [selected, selectFirstByDefault]);

  useEffect(() => {
    if (autoSelectDoneRef.current || !selectFirstByDefault || multiSelect || options.length === 0) {
      return;
    }

    if (selected && selected.trim() !== "") {
      return;
    }

    // Use first option from original order (no sorting)
    const firstOption = options[0];

    if (firstOption) {
      autoSelectDoneRef.current = true;
      onSelect(firstOption);
    }
  }, [selectFirstByDefault, multiSelect, options, selected, onSelect]);

  // Handle defaultOpen - open dropdown on mount
  const defaultOpenDoneRef = useRef(false);
  useEffect(() => {
    if (defaultOpen && !defaultOpenDoneRef.current && options.length > 0 && !disabled) {
      defaultOpenDoneRef.current = true;
      // Small delay to ensure DOM is ready
      const timer = setTimeout(() => {
        setOpen(true);
        if (onDropdownOpen) {
          onDropdownOpen();
        }
      }, 100);
      return () => clearTimeout(timer);
    }
  }, [defaultOpen, options.length, disabled, onDropdownOpen]);

  const checkDropdownDirection = () => {
    const input = inputRef.current;
    if (!input) return "down";
    const rect = input.getBoundingClientRect();
    const windowHeight = window.innerHeight;
    const spaceBelow = windowHeight - rect.bottom;
    const spaceAbove = rect.top;
    const requiredSpace = 250;
    if (spaceBelow < requiredSpace && spaceAbove > spaceBelow && spaceAbove >= requiredSpace) {
      return "up";
    }
    return "down";
  };

  useEffect(() => {
    if (open) {
      // Use forceDirection if provided, otherwise check automatically
      const newDirection = forceDirection || checkDropdownDirection();
      setDirection(newDirection);
    }
  }, [open, forceDirection]);

  useEffect(() => {
    if (!open) return;

    const calculatePosition = () => {
      if (!inputRef.current) return null;
      const rect = inputRef.current.getBoundingClientRect();
      // Use forceDirection if provided, otherwise check automatically
      const dir = forceDirection || checkDropdownDirection();
      const offset = 4;

      // Calculate dropdown width (use trigger width as default)
      const dropdownListWidth = dropdownWidth ? parseInt(dropdownWidth) : rect.width;

      // Constrain left position to keep dropdown within viewport
      let leftPos = rect.left;
      const viewportWidth = window.innerWidth;
      const viewportHeight = window.innerHeight;
      const rightEdge = leftPos + dropdownListWidth;

      // If dropdown would overflow right side, adjust left position
      if (rightEdge > viewportWidth - 10) {
        leftPos = Math.max(10, viewportWidth - dropdownListWidth - 10);
      }

      // Calculate vertical position with overflow protection
      const dropdownHeight = 280; // max-height of dropdown
      let verticalStyle = {};

      if (dir === "down") {
        const bottomEdge = rect.bottom + offset + dropdownHeight;
        if (bottomEdge > viewportHeight - 10) {
          // Not enough space below, open upward instead
          verticalStyle = { bottom: viewportHeight - rect.top + offset };
        } else {
          verticalStyle = { top: rect.bottom + offset };
        }
      } else {
        verticalStyle = { bottom: viewportHeight - rect.top + offset };
      }

      return {
        position: "fixed",
        left: leftPos,
        width: rect.width, // Match trigger width
        maxWidth: rect.width, // Constrain to trigger width
        zIndex: 1000010,
        ...verticalStyle,
      };
    };

    setDropdownStyle(calculatePosition());

    // Track trigger position changes (e.g., nav expand/collapse shifts content)
    let lastLeft = inputRef.current?.getBoundingClientRect().left;
    let lastTop = inputRef.current?.getBoundingClientRect().top;
    let rafId;
    const trackPosition = () => {
      if (!inputRef.current) return;
      const rect = inputRef.current.getBoundingClientRect();
      if (Math.abs(rect.left - lastLeft) > 1 || Math.abs(rect.top - lastTop) > 1) {
        setDropdownStyle(calculatePosition());
        lastLeft = rect.left;
        lastTop = rect.top;
      }
      rafId = requestAnimationFrame(trackPosition);
    };
    rafId = requestAnimationFrame(trackPosition);

    const handleScroll = (e) => {
      if (listRef.current && listRef.current.contains(e.target)) {
        return;
      }
      // Don't close if scrolling inside the dropdown's parent modal/container
      if (inputRef.current && inputRef.current.closest && inputRef.current.closest('[class*="modalContent"], [class*="FullModal"], [class*="fullModal"]')?.contains(e.target)) {
        return;
      }
      setOpen(false);
    };

    const handleResize = () => setOpen(false);

    window.addEventListener("scroll", handleScroll, true);
    window.addEventListener("resize", handleResize);

    return () => {
      cancelAnimationFrame(rafId);
      window.removeEventListener("scroll", handleScroll, true);
      window.removeEventListener("resize", handleResize);
    };
  }, [open, dropdownWidth, forceDirection]);

  useEffect(() => {
    if (open && selected && !search) {
      const timeoutId = setTimeout(() => {
        const selectedIndex = filteredOptions.findIndex((opt) => opt === selected);
        if (selectedIndex >= 0 && optionRefs.current[selectedIndex] && optionsContainerRef.current) {
          const option = optionRefs.current[selectedIndex];
          const container = optionsContainerRef.current;

          const optionTop = option.offsetTop;
          const containerHeight = container.clientHeight;

          const scrollPosition = optionTop - containerHeight / 2 + option.offsetHeight / 2;

          container.scrollTop = Math.max(0, Math.min(scrollPosition, container.scrollHeight - containerHeight));
        }
      }, 100);

      return () => clearTimeout(timeoutId);
    }
  }, [open, selected]);

  useEffect(() => {
    if (open && highlighted >= 0 && isKeyboardNavigation && optionRefs.current[highlighted]) {
      const option = optionRefs.current[highlighted];
      const optionsContainer = optionsContainerRef.current;
      if (option && optionsContainer) {
        const containerRect = optionsContainer.getBoundingClientRect();
        const optionRect = option.getBoundingClientRect();

        const optionTop = optionRect.top - containerRect.top + optionsContainer.scrollTop;
        const optionBottom = optionTop + option.offsetHeight;
        const viewTop = optionsContainer.scrollTop;
        const viewBottom = viewTop + optionsContainer.clientHeight;

        const padding = 4;

        if (optionTop < viewTop + padding) {
          optionsContainer.scrollTop = Math.max(0, optionTop - padding);
        } else if (optionBottom > viewBottom - padding) {
          optionsContainer.scrollTop = optionBottom - optionsContainer.clientHeight + padding;
        }
      }
    }
  }, [highlighted, open, isKeyboardNavigation, filteredOptions.length]);

  useEffect(() => {
    if (!open) return;
    const handleClickOutside = (e) => {
      if (listRef.current && !listRef.current.contains(e.target) && inputRef.current && !inputRef.current.contains(e.target)) {
        setOpen(false);
        setHighlighted(-1);
        setShowTypeDropdown(false);
      }
    };
    document.addEventListener("mousedown", handleClickOutside);
    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
    };
  }, [open]);

  useEffect(() => {
    if (!open) {
      setSearch("");
      setShowTypeDropdown(false);
      setIsKeyboardNavigation(false);
    }
  }, [open]);

  useEffect(() => {
    if (open && !multiSelect && selected && !search) {
      const selectedIndex = filteredOptions.findIndex((opt) => opt === selected);
      if (selectedIndex >= 0) {
        setHighlighted(selectedIndex);
      }
    }
  }, [open, selected, search, multiSelect]);

  const prevOpenRef = useRef(false);

  useEffect(() => {
    if (open && !prevOpenRef.current) {
      setStagedItems(selectedItems);
    }
    prevOpenRef.current = open;
  }, [open, selectedItems]);

  const handleMultiSelectToggle = (option) => {
    const newItems = stagedItems.includes(option) ? stagedItems.filter((item) => item !== option) : [...stagedItems, option];

    setStagedItems(newItems);

    if (hideFooter && onSelectionChange) {
      onSelectionChange(newItems);
    }
  };

  const handleKeyDown = (e) => {
    const ARROW_KEY_DELAY = 200;
    const now = Date.now();
    const isArrowKey = e.key === "ArrowDown" || e.key === "ArrowUp";

    if (!open) {
      if (e.key === "Enter" || e.key === " " || e.key === "ArrowDown" || e.key === "ArrowUp") {
        setOpen(true);
        const selectedIndex = !multiSelect && selected ? filteredOptions.findIndex((opt) => opt === selected) : -1;
        setHighlighted(selectedIndex >= 0 ? selectedIndex : 0);
        setIsKeyboardNavigation(true);
        e.preventDefault();
        return;
      }
      return;
    }

    if (isArrowKey && now - lastKeyPressTime.current < ARROW_KEY_DELAY) {
      e.preventDefault();
      return;
    }

    if (isArrowKey) {
      lastKeyPressTime.current = now;
    }

    if (e.key === "ArrowDown") {
      setIsKeyboardNavigation(true);
      setHighlighted((prev) => Math.min(prev + 1, filteredOptions.length - 1));
      e.preventDefault();
    } else if (e.key === "ArrowUp") {
      setIsKeyboardNavigation(true);
      setHighlighted((prev) => Math.max(prev - 1, 0));
      e.preventDefault();
    } else if (e.key === "Enter") {
      if (highlighted >= 0 && filteredOptions[highlighted]) {
        if (multiSelect) {
          handleMultiSelectToggle(filteredOptions[highlighted]);
        } else {
          onSelect(filteredOptions[highlighted]);
          setOpen(false);
          setHighlighted(-1);
          setSearch("");
          setIsKeyboardNavigation(false);
        }
      }
      e.preventDefault();
    } else if (e.key === " ") {
      // Allow space character to be typed in search input
      const isSearchInput = e.target.tagName === "INPUT" && e.target.type === "text";
      if (isSearchInput) {
        // Let the space character be typed normally in the search field
        return;
      }
      if (highlighted >= 0 && filteredOptions[highlighted]) {
        if (multiSelect) {
          handleMultiSelectToggle(filteredOptions[highlighted]);
        } else {
          onSelect(filteredOptions[highlighted]);
          setOpen(false);
          setHighlighted(-1);
          setSearch("");
          setIsKeyboardNavigation(false);
        }
      } else if (!multiSelect) {
        setOpen(false);
        setHighlighted(-1);
        setSearch("");
        setIsKeyboardNavigation(false);
      }
      e.preventDefault();
    } else if (e.key === "Escape" || e.key === "Tab") {
      setOpen(false);
      setHighlighted(-1);
      setSearch("");
      setIsKeyboardNavigation(false);
      if (e.key === "Escape") {
        e.preventDefault();
      }
    }
  };

  // Handler for label click - focuses the dropdown
  const handleLabelClick = () => {
    if (!disabled && inputRef.current) {
      inputRef.current.focus();
    }
  };

  const hasSelection = multiSelect ? selectedItems.length > 0 : showCheckbox ? selected && selected !== "All" : false;

  // Wrapper class based on label position
  const wrapperClass = label ? (labelPosition === "left" ? styles.dropdownWithLabelLeft : styles.dropdownWithLabelTop) : "";

  // Check if dark theme is enabled via className - safe string handling
  const classNameStr = className || "";
  const isDarkTheme = theme === "dark" || classNameStr.includes("darkTheme");
  const isChatMentionDropdown = classNameStr.includes("chatMentionDropdown");

  return (
    <div className={`${styles.dropdownWrapper} ${wrapperClass} ${classNameStr} ${isDarkTheme ? styles.darkTheme : ""}`}>
      {/* Optional Label */}
      {label && (
        <label htmlFor={dropdownId} className={`label-desc`} onClick={handleLabelClick}>
          {label}
          {required && <span className="required"> *</span>}
        </label>
      )}

      <div className={styles.dropdownContainer} style={{ width, maxWidth }}>
        <div
          id={dropdownId}
          className={`${styles.dropdownInput} ${hasSelection ? styles.dropdownInputSelected : ""} ${disabled ? styles.dropdownDisabled : ""} ${isChatMentionDropdown ? "chatMentionDropdown" : ""} ${isDarkTheme ? styles.darkTheme : ""}`}
          tabIndex={disabled ? -1 : 0}
          role="combobox"
          aria-haspopup="listbox"
          aria-expanded={open}
          aria-disabled={disabled}
          aria-labelledby={label ? undefined : undefined}
          aria-label={label || placeholder}
          onClick={() => {
            if (!disabled) {
              setOpen((prev) => {
                const willOpen = !prev;
                if (willOpen && typeof onDropdownOpen === "function") {
                  onDropdownOpen();
                }
                return willOpen;
              });
            }
          }}
          onKeyDown={disabled ? null : handleKeyDown}
          ref={inputRef}>
          <div className={styles.dropdownInputContent}>
            {multiSelect ? (
              <>
                {prefixIcon && <span className={styles.prefixIcon}>{prefixIcon}</span>}
                <span className={styles.dropdownLabelMarginTop}>{placeholder}</span>
                {selectedItems.length > 0 && <span className={styles.countBadge}>{selectedItems.length}</span>}
              </>
            ) : showCheckbox ? (
              <>
                {prefixIcon && <span className={styles.prefixIcon}>{prefixIcon}</span>}
                <span className={styles.dropdownLabelMarginTop}>{placeholder}</span>
                {selected && selected !== "All" && <span className={styles.countBadge}>1</span>}
              </>
            ) : (
              <>
                {prefixIcon && <span className={styles.prefixIcon}>{prefixIcon}</span>}
                <span
                  className={`${styles.dropdownLabelMarginTop} ${!selected ? styles.dropdownPlaceholder : styles.selectedValueTruncate}`}
                  title={selected || ""}>
                  {selected || placeholder}
                </span>
              </>
            )}
          </div>
          <SVGIcons icon="chevron-down" width={18} height={18} color="currentColor" className={`${styles.dropdownArrow} ${open ? styles.rotated : ""}`} />
        </div>
        {open &&
          createPortal(
            <div
              tabIndex={-1}
              role="listbox"
              ref={listRef}
              className={`${styles.dropdownList} ${isDarkTheme ? styles.darkTheme : ''}`}
              style={{
                ...dropdownStyle,
                // Use calculated width from dropdownStyle, fallback to dropdownWidth prop or trigger width
                width: dropdownStyle.width || dropdownWidth || inputRef.current?.offsetWidth || width,
                // minWidth: dropdownStyle.width || inputRef.current?.offsetWidth || width,
                maxWidth: dropdownStyle.maxWidth || maxWidth || dropdownStyle.width,
                ...(fixedHeight ? { minHeight: 280, maxHeight: 280, overflowY: 'hidden' } : { maxHeight: 280, overflowY: 'auto' }),
              }}
              onMouseDown={(e) => {
                // Prevent blur on dropdown trigger so dropdown stays open,
                // but allow default on input elements so text selection works
                if (e.target.tagName !== "INPUT") {
                  e.preventDefault();
                }
              }}>
              {/* ...existing dropdown content... */}
              {(showSearch || (showTypeFilter && typeFilterOptions.length > 0)) && (
                <div className={styles.dropdownSearchWrapper}>
                  {showSearch && (
                    <TextField
                      placeholder="Search..."
                      value={search}
                      onChange={(e) => {
                        const searchValue = e.target.value;
                        setSearch(searchValue);
                        if (searchValue.trim() === "" && selected) {
                          setTimeout(() => {
                            const selectedIndex = filteredOptions.findIndex((opt) => opt === selected);
                            setHighlighted(selectedIndex >= 0 ? selectedIndex : 0);
                          }, 0);
                        } else {
                          setHighlighted(0);
                        }
                      }}
                      onKeyDown={handleKeyDown}
                      onClear={() => {
                        setSearch("");
                        if (selected) {
                          const selectedIndex = filteredOptions.findIndex((opt) => opt === selected);
                          setHighlighted(selectedIndex >= 0 ? selectedIndex : 0);
                        }
                      }}
                      showSearchButton={true}
                      showClearButton={true}
                      autoFocus
                      aria-label="Search options"
                    />
                  )}
                  {showTypeFilter && typeFilterOptions.length > 0 && (
                    <div className={styles.typeFilterContainer} ref={typeFilterRef}>
                      <button
                        type="button"
                        className={`${styles.typeFilterIconButton} ${showTypeDropdown ? styles.typeFilterIconActive : ""}`}
                        onClick={(e) => {
                          e.stopPropagation();
                          setShowTypeDropdown(!showTypeDropdown);
                        }}
                        title="Filter by type"
                        aria-label="Filter by type">
                        <SVGIcons icon="filter-funnel" width={16} height={16} color="currentColor" />
                      </button>
                      {showTypeDropdown && (
                        <div className={styles.typeFilterDropdown}>
                          {typeFilterOptions.map((typeOpt) => (
                            <div
                              key={typeOpt.value}
                              className={`${styles.typeFilterOption} ${(onTypeFilterChange ? selectedTypeFilter : internalTypeFilter) === typeOpt.value ? styles.typeFilterOptionSelected : ""
                                }`}
                              onClick={(e) => {
                                e.stopPropagation();
                                if (onTypeFilterChange) {
                                  onTypeFilterChange(typeOpt.value);
                                } else {
                                  setInternalTypeFilter(typeOpt.value);
                                }
                                setShowTypeDropdown(false);
                              }}>
                              {typeOpt.label}
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  )}
                </div>
              )}
              {showSelectedOnTop && selectedOption && (
                <div className={styles.selectedOnTopWrapper}>
                  <div className={styles.selectedOnTopItem}>
                    <span className={styles.selectedOnTopLabel} title={selectedOption}>{selectedOption}</span>
                    <div className={styles.selectedOnTopRight}>
                      {optionMetadata[selectedOption] && <span className={styles.optionMetadata} title={optionTooltips[selectedOption] || ""}>{optionMetadata[selectedOption]}</span>}
                      <button
                        type="button"
                        className={styles.selectedOnTopClear}
                        onClick={(e) => {
                          e.stopPropagation();
                          onSelect("");
                          if (onClear) onClear();
                        }}
                        aria-label="Remove selection"
                        tabIndex={-1}>
                        <SVGIcons icon="close-x" width={14} height={14} color="currentColor" />
                      </button>
                    </div>
                  </div>
                  {displayOptions.length > 0 && <div className={styles.selectedOnTopDivider}></div>}
                </div>
              )}
              <div
                className={styles.dropdownOptionsContainer}
                ref={optionsContainerRef}
                style={{
                  ...(fixedHeight ? { flex: 1 } : {}),
                  maxHeight: (showSearch || showTypeFilter) ? 180 : 220,
                  overflowY: 'auto',
                  overflowX: 'hidden'
                }}>
                {displayOptions.length === 0 && !selectedOption && <div className={styles.dropdownNoOption}>No options found</div>}
                {displayOptions.length === 0 && selectedOption && <div className={styles.dropdownNoOption}>No other agents available</div>}
                {displayOptions.map((opt, idx) => {
                  const isSelected = multiSelect ? stagedItems.includes(opt) : selected === opt;
                  return (
                    <div
                      key={opt}
                      role="option"
                      aria-selected={isSelected}
                      onClick={() => {
                        if (multiSelect) {
                          handleMultiSelectToggle(opt);
                        } else {
                          onSelect(opt);
                          setOpen(false);
                          setHighlighted(-1);
                          setSearch("");
                          setIsKeyboardNavigation(false);
                        }
                      }}
                      onMouseEnter={() => {
                        if (!isKeyboardNavigation) {
                          setHighlighted(idx);
                        }
                      }}
                      onMouseMove={() => {
                        if (isKeyboardNavigation) {
                          setIsKeyboardNavigation(false);
                          setHighlighted(idx);
                        }
                      }}
                      onMouseLeave={() => setHighlighted(-1)}
                      ref={(el) => (optionRefs.current[idx] = el)}
                      className={`${styles.dropdownOption} ` + (highlighted === idx ? styles.highlighted : isSelected ? styles.selected : "")}>
                      {showCheckbox && (
                        <CheckBox
                          checked={isSelected}
                          onChange={() => {
                            if (multiSelect) {
                              handleMultiSelectToggle(opt);
                            } else {
                              onSelect(opt);
                              setOpen(false);
                              setHighlighted(-1);
                              setSearch("");
                              setIsKeyboardNavigation(false);
                            }
                          }}
                          disabled={false}
                          label={`Select ${opt}`}
                          tabIndex={0}
                        />
                      )}
                      <span className={styles.optionLabel} title={opt}>{opt}</span>
                      <div className={styles.optionRightSection}>
                        {optionMetadata[opt] && <span className={styles.optionMetadata} title={optionTooltips[opt] || ""}>{optionMetadata[opt]}</span>}
                        {onOptionDelete && (
                          <button
                            type="button"
                            className={styles.optionDeleteIcon}
                            onClick={(e) => {
                              e.stopPropagation();
                              onOptionDelete(opt);
                            }}
                            aria-label={`Delete ${opt}`}
                            tabIndex={-1}>
                            <SVGIcons icon="trash" width={16} height={16} color="currentColor" />
                          </button>
                        )}
                        {showClearIcon && isSelected ? (
                          <button
                            type="button"
                            className={styles.optionClearIcon}
                            onClick={(e) => {
                              e.stopPropagation();
                              onSelect("");
                              if (onClear) onClear();
                              setOpen(false);
                            }}
                            aria-label="Remove selection"
                            tabIndex={-1}>
                            <SVGIcons icon="close-x" width={12} height={12} color="currentColor" />
                          </button>
                        ) : showClearIcon && optionMetadata[opt] ? (
                          <span className={styles.optionClearIconPlaceholder}></span>
                        ) : null}
                      </div>
                    </div>
                  );
                })}
              </div>
              {multiSelect && !hideFooter && (
                <div className={styles.dropdownFooter + " " + styles.dropdownFooterFlex}>
                  {hasApplied && selectedItems.length > 0 ? (
                    <>
                      <button
                        type="button"
                        className={styles.clearButton}
                        onClick={(e) => {
                          e.stopPropagation();
                          setStagedItems([]);
                          if (onApply) {
                            onApply([]);
                          }
                          if (onClear) {
                            onClear();
                          }
                          setOpen(false);
                        }}
                        role="button">
                        <span className={styles.clearIconSpan}>
                          <SVGIcons icon="close-x" width={16} height={16} color="currentColor" />
                        </span>
                        {dropdownName ? `Clear ${dropdownName}` : clearLabel}
                      </button>
                      <div className={styles.dropdownDivider} />
                      <button
                        type="button"
                        className={styles.applyButton}
                        onClick={(e) => {
                          e.stopPropagation();
                          setHasApplied(true);
                          if (onApply) {
                            onApply(stagedItems);
                          }
                          setOpen(false);
                        }}>
                        <span className={styles.applyTick}></span>
                        {applyLabel} {stagedItems.length > 0 ? `(${stagedItems.length})` : `(${stagedItems.length})`}
                      </button>
                    </>
                  ) : (
                    <button
                      type="button"
                      className={styles.applyButton}
                      onClick={(e) => {
                        e.stopPropagation();
                        setHasApplied(true);
                        if (onApply) {
                          onApply(stagedItems);
                        }
                        setOpen(false);
                      }}>
                      <span className={styles.applyTick}></span>
                      {applyLabel} {stagedItems.length > 0 ? `(${stagedItems.length})` : `(${stagedItems.length})`}
                    </button>
                  )}
                </div>
              )}
            </div>,
            document.body
          )}
      </div>
    </div>
  );
};

export default NewCommonDropdown;
