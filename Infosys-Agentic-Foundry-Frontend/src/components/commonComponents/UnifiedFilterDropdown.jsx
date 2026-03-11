import React, { useState, useRef, useEffect, useId, useMemo } from "react";
import { createPortal } from "react-dom";
import styles from "./UnifiedFilterDropdown.module.css";
import SVGIcons from "../../Icons/SVGIcons.js";
import CheckBox from "../../iafComponents/GlobalComponents/CheckBox/CheckBox.jsx";
import IAFButton from "../../iafComponents/GlobalComponents/Buttons/Button.jsx";
import TextField from "../../iafComponents/GlobalComponents/TextField/TextField.jsx";
import { useMessage } from "../../Hooks/MessageContext";
import { getAgentTypeAbbreviation } from "../Pipeline/pipelineUtils";

/**
 * UnifiedFilterDropdown - A single filter button that opens a dropdown panel
 * containing Type, Industry (Tags), and Created By filters.
 *
 * Props:
 * - typeOptions: array of { value, label, disabled? } for type filter
 *   - disabled: optional boolean to make the option non-interactive
 *   - When disabled=true, the checkbox cannot be checked/unchecked by user
 * - selectedTypes: array of selected type values
 * - onTypeChange: callback when types change (receives array of values)
 *
 * - industryOptions: array of strings OR objects { value, label?, disabled?, agentType? } for industry/tags filter
 *   - disabled: optional boolean to make the option non-interactive
 *   - agentType: optional string for agent type (used to show type badge)
 * - selectedIndustries: array of selected industry values
 * - onIndustryChange: callback when industries change (receives array of values)
 *
 * - createdByOptions: array of strings OR objects { value, label?, disabled? } for created by filter
 *   - disabled: optional boolean to make the option non-interactive
 * - selectedCreatedBy: string for selected created by value
 * - onCreatedByChange: callback when created by changes (receives string)
 *
 * - onApply: callback when Apply button is clicked
 * - onClear: callback when all filters are cleared
 *
 * - contextType: string representing the screen type (e.g., "Tools", "Servers", "Agents", "Metrics")
 * - industryLabel: string to customize the label for industry/tags section (defaults to "Industry")
 * - showInlineTypeFilter: boolean to show type filter as an inline icon menu inside industry section (like chat screen)
 * - agentTypeMetadata: object mapping agent names to their types { [agentName]: agentType }
 */
const UnifiedFilterDropdown = ({
  // Type filter props
  typeOptions = [],
  selectedTypes = [],
  onTypeChange = () => { },

  // Industry/Tags filter props
  industryOptions = [],
  selectedIndustries = [],
  onIndustryChange = () => { },

  // Created By filter props
  createdByOptions = ["All", "Me"],
  selectedCreatedBy = "All",
  onCreatedByChange = () => { },

  // Action callbacks
  onApply = () => { },
  onClear = () => { },

  // Context type for toast messages
  contextType = "items",

  // Custom label for industry/tags section
  industryLabel = "Industry",

  // Additional top offset for dropdown positioning (useful in sliders/modals)
  topOffset = 0,

  // Show type filter inline inside industry section (like chat screen)
  showInlineTypeFilter = false,

  // Agent type metadata - mapping agent names to their types for badges
  agentTypeMetadata = {},
}) => {
  const dropdownId = useId();
  const [open, setOpen] = useState(false);
  const [industrySearch, setIndustrySearch] = useState("");
  const [dropdownStyle, setDropdownStyle] = useState({});

  // Message context for toast notifications
  const { addMessage } = useMessage();

  // Staged states for Type, Industry, and Created By (wait for Apply)
  const [stagedTypes, setStagedTypes] = useState(selectedTypes);
  const [stagedIndustries, setStagedIndustries] = useState(selectedIndustries);
  const [stagedCreatedBy, setStagedCreatedBy] = useState(selectedCreatedBy);

  const [showInlineTypeDropdown, setShowInlineTypeDropdown] = useState(false);

  const buttonRef = useRef(null);
  const dropdownRef = useRef(null);
  const inlineTypeFilterRef = useRef(null);

  // Filter industry options based on search AND selected types (for inline type filter)
  // Use useMemo to prevent unnecessary recalculations and deduplicate entries
  const filteredIndustryOptions = useMemo(() => {
    // Normalize industry option to { value, label, disabled, agentType }
    const normalizeOption = (opt) => {
      if (typeof opt === "string") {
        const agentType = agentTypeMetadata[opt] || "";
        return { value: opt, label: opt, disabled: false, agentType };
      }
      return {
        value: opt.value || opt.label || opt,
        label: opt.label || opt.value || opt,
        disabled: opt.disabled === true,
        agentType: opt.agentType || agentTypeMetadata[opt.value] || agentTypeMetadata[opt.label] || "",
      };
    };

    const normalized = industryOptions.map(normalizeOption);

    // Deduplicate by value to prevent duplicate entries
    const uniqueOptions = Array.from(new Map(normalized.map(opt => [opt.value, opt])).values());

    // Apply filters
    const filtered = uniqueOptions.filter((opt) => {
      // Filter by search term
      const matchesSearch = !industrySearch || opt.label.toLowerCase().includes(industrySearch.toLowerCase());

      // Filter by selected types (only when inline type filter is active and types are selected)
      const matchesType = !showInlineTypeFilter || stagedTypes.length === 0 || stagedTypes.includes(opt.agentType);

      return matchesSearch && matchesType;
    });

    // Sort: selected items first, then alphabetically within each group
    return filtered.sort((a, b) => {
      const aSelected = stagedIndustries.includes(a.value);
      const bSelected = stagedIndustries.includes(b.value);
      if (aSelected && !bSelected) return -1;
      if (!aSelected && bSelected) return 1;
      return a.label.localeCompare(b.label);
    });
  }, [industryOptions, industrySearch, showInlineTypeFilter, stagedTypes, stagedIndustries, agentTypeMetadata]);

  // Helper to normalize createdBy option to { value, label, disabled }
  const normalizeCreatedByOption = (opt) => {
    if (typeof opt === "string") {
      return { value: opt, label: opt, disabled: false };
    }
    return {
      value: opt.value || opt.label || opt,
      label: opt.label || opt.value || opt,
      disabled: opt.disabled === true,
    };
  };

  // Calculate total active filters count
  const activeFiltersCount = selectedTypes.length + selectedIndustries.length + (selectedCreatedBy !== "All" ? 1 : 0);

  // Sync staged states when props change (e.g., external clear)
  useEffect(() => {
    setStagedTypes(selectedTypes);
  }, [selectedTypes]);

  useEffect(() => {
    setStagedIndustries(selectedIndustries);
  }, [selectedIndustries]);

  useEffect(() => {
    setStagedCreatedBy(selectedCreatedBy);
  }, [selectedCreatedBy]);

  // Position constants for dropdown placement
  const DROPDOWN_OFFSET = 8;
  const EDGE_PADDING = 16;

  // Calculate dropdown position when opened
  useEffect(() => {
    if (open && buttonRef.current) {
      // Use requestAnimationFrame to ensure DOM is ready
      requestAnimationFrame(() => {
        if (!buttonRef.current) return;

        const rect = buttonRef.current.getBoundingClientRect();
        const windowHeight = window.innerHeight;
        const windowWidth = window.innerWidth;
        const dropdownWidth = 280;
        const dropdownHeight = 450;

        // Position dropdown aligned to the right edge of the button
        // (dropdown's right edge aligns with button's right edge)
        let left = rect.right - dropdownWidth;
        // Position below the button with offset
        let top = rect.bottom + DROPDOWN_OFFSET;

        // Calculate available space below the button
        const spaceBelow = windowHeight - rect.bottom - EDGE_PADDING;

        // If not enough space below, position above the button
        if (spaceBelow < dropdownHeight) {
          const spaceAbove = rect.top - EDGE_PADDING;
          if (spaceAbove >= dropdownHeight) {
            top = rect.top - dropdownHeight - DROPDOWN_OFFSET;
          } else {
            // Neither has enough space - position to maximize visibility below button
            top = rect.bottom + DROPDOWN_OFFSET;
          }
        }

        // Ensure dropdown doesn't go off the left edge
        if (left < EDGE_PADDING) {
          left = EDGE_PADDING;
        }

        // Ensure dropdown doesn't go off the right edge
        if (left + dropdownWidth > windowWidth - EDGE_PADDING) {
          left = windowWidth - dropdownWidth - EDGE_PADDING;
        }

        // Ensure top doesn't go negative
        if (top < EDGE_PADDING) {
          top = EDGE_PADDING;
        }

        setDropdownStyle({
          position: "fixed",
          left: `${Math.round(left)}px`,
          top: `${Math.round(top)}px`,
          zIndex: 1000060,
        });
      });
    }
  }, [open]);

  // Close dropdown when clicking outside
  useEffect(() => {
    if (!open) return;

    const handleClickOutside = (e) => {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target) && buttonRef.current && !buttonRef.current.contains(e.target)) {
        setOpen(false);
        setStagedTypes(selectedTypes);
        setStagedIndustries(selectedIndustries);
        setStagedCreatedBy(selectedCreatedBy);
        setIndustrySearch("");
        setShowInlineTypeDropdown(false);
      }
    };

    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [open, selectedTypes, selectedIndustries]);

  useEffect(() => {
    if (!showInlineTypeDropdown) return;

    const handleClickOutside = (e) => {
      if (inlineTypeFilterRef.current && !inlineTypeFilterRef.current.contains(e.target)) {
        setShowInlineTypeDropdown(false);
      }
    };

    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [showInlineTypeDropdown]);

  // Handle type toggle (staged, waits for Apply)
  const handleTypeToggle = (value, isDisabled = false) => {
    if (isDisabled) return; // Don't toggle if option is disabled
    setStagedTypes((prev) => (prev.includes(value) ? prev.filter((t) => t !== value) : [...prev, value]));
  };

  // Handle industry toggle (staged, waits for Apply)
  const handleIndustryToggle = (value, isDisabled = false) => {
    if (isDisabled) return; // Don't toggle if option is disabled
    setStagedIndustries((prev) => (prev.includes(value) ? prev.filter((t) => t !== value) : [...prev, value]));
  };

  // Handle created by change (staged, waits for Apply)
  const handleCreatedBySelect = (value, isDisabled = false) => {
    if (isDisabled) return; // Don't change if option is disabled
    setStagedCreatedBy(value);
  };

  // Handle Apply button click
  const handleApply = () => {
    // Pass the staged values directly to parent callbacks
    // Don't rely on parent state updates being immediate
    onTypeChange(stagedTypes);
    onIndustryChange(stagedIndustries);
    onCreatedByChange(stagedCreatedBy);

    // Call onApply with fresh staged values to trigger API call
    // Parent should use these values instead of relying on state
    onApply(stagedTypes, stagedIndustries, stagedCreatedBy);

    // Close dropdown and reset search
    setOpen(false);
    setIndustrySearch("");
  };

  // Handle Clear Selection - only reset staged selections, keep dropdown open
  const handleClear = () => {
    // Clear staged states only (don't apply or close)
    setStagedTypes([]);
    setStagedIndustries([]);
    setStagedCreatedBy("All");
    setIndustrySearch("");
  };

  const dropdownContent = (
    <div ref={dropdownRef} className={styles.dropdownPanel} style={dropdownStyle} role="dialog" aria-labelledby={`${dropdownId}-title`}>
      {/* Scrollable content wrapper */}
      <div className={styles.scrollableContent}>
        {/* Type Section - Only render if typeOptions has values AND not inline mode */}
        {typeOptions.length > 0 && !showInlineTypeFilter && (
          <div className={styles.section}>
            <div className={styles.sectionHeader}>Type</div>
            <div className={styles.optionsList}>
              {typeOptions.map((option) => {
                const isDisabled = option.disabled === true;
                return (
                  <div
                    key={option.value}
                    className={`${styles.optionItem} ${isDisabled ? styles.optionItemDisabled : ""}`}
                    onClick={() => handleTypeToggle(option.value, isDisabled)}
                    title={isDisabled ? "This option cannot be changed" : ""}>
                    <CheckBox
                      checked={stagedTypes.includes(option.value)}
                      onChange={() => handleTypeToggle(option.value, isDisabled)}
                      disabled={isDisabled}
                    />
                    <span className={`${styles.optionLabel} ${isDisabled ? styles.optionLabelDisabled : ""}`}>{option.label}</span>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* Industry/Tags Section - Only render if industryOptions has values */}
        {industryOptions.length > 0 && (
          <div className={styles.section}>
            <div className={styles.sectionHeader}>{industryLabel}</div>
            <div className={styles.searchWrapper}>
              <TextField
                placeholder={`Search ${industryLabel}`}
                value={industrySearch}
                onChange={(e) => setIndustrySearch(e.target.value)}
                onClear={() => setIndustrySearch("")}
                showSearchButton={true}
                showClearButton={true}
                aria-label={`Search ${industryLabel}`}
              />
              {showInlineTypeFilter && typeOptions.length > 0 && (
                <div className={styles.inlineTypeFilterContainer} ref={inlineTypeFilterRef}>
                  <button
                    type="button"
                    className={`${styles.inlineTypeFilterIconButton} ${showInlineTypeDropdown ? styles.inlineTypeFilterIconActive : ""}`}
                    onClick={(e) => {
                      e.stopPropagation();
                      setShowInlineTypeDropdown(!showInlineTypeDropdown);
                    }}
                    title="Filter by agent type"
                    aria-label="Filter by agent type">
                    <SVGIcons icon="filter-funnel" width={16} height={16} color="currentColor" />
                  </button>
                  {showInlineTypeDropdown && (
                    <div className={styles.inlineTypeFilterDropdown}>
                      <div className={styles.inlineTypeFilterHeader}>Agent Type</div>
                      {typeOptions.map((option) => {
                        const isDisabled = option.disabled === true;
                        return (
                          <div
                            key={option.value}
                            className={`${styles.inlineTypeFilterOption} ${stagedTypes.includes(option.value) ? styles.inlineTypeFilterOptionSelected : ""
                              } ${isDisabled ? styles.inlineTypeFilterOptionDisabled : ""}`}
                            onClick={(e) => {
                              e.stopPropagation();
                              if (!isDisabled) {
                                handleTypeToggle(option.value, isDisabled);
                              }
                            }}
                            title={isDisabled ? "This option cannot be changed" : ""}>
                            <CheckBox
                              checked={stagedTypes.includes(option.value)}
                              onChange={() => handleTypeToggle(option.value, isDisabled)}
                              disabled={isDisabled}
                            />
                            <span className={`${styles.inlineTypeFilterLabel} ${isDisabled ? styles.inlineTypeFilterLabelDisabled : ""}`}>
                              {option.label}
                            </span>
                          </div>
                        );
                      })}
                    </div>
                  )}
                </div>
              )}
            </div>
            <div className={styles.optionsListScrollable}>
              {filteredIndustryOptions.length > 0 ? (
                filteredIndustryOptions.map((option) => {
                  const typeAbbr = option.agentType ? getAgentTypeAbbreviation(option.agentType) : "";
                  return (
                    <div
                      key={option.value}
                      className={`${styles.optionItem} ${option.disabled ? styles.optionItemDisabled : ""}`}
                      onClick={() => handleIndustryToggle(option.value, option.disabled)}
                      title={option.disabled ? "This option cannot be changed" : ""}>
                      <CheckBox
                        checked={stagedIndustries.includes(option.value)}
                        onChange={() => handleIndustryToggle(option.value, option.disabled)}
                        disabled={option.disabled}
                      />
                      <span className={`${styles.optionLabel} ${option.disabled ? styles.optionLabelDisabled : ""}`}>{option.label}</span>
                      {typeAbbr && <span className={styles.agentTypeBadge}>{typeAbbr}</span>}
                    </div>
                  );
                })
              ) : (
                <div className={styles.noResults}>No {stagedTypes.length > 0 ? `${industryLabel.toLowerCase()} found for selected type(s)` : `${industryLabel.toLowerCase()} found`}</div>
              )}
            </div>
          </div>
        )}

        {/* Created By Section - Only render if createdByOptions has values */}
        {createdByOptions.length > 0 && (
          <div className={styles.section}>
            <div className={styles.sectionHeader}>Created By</div>
            <div className={styles.optionsList}>
              {createdByOptions.map((opt) => {
                const option = normalizeCreatedByOption(opt);
                return (
                  <div
                    key={option.value}
                    className={`${styles.optionItem} ${option.disabled ? styles.optionItemDisabled : ""}`}
                    onClick={() => handleCreatedBySelect(option.value, option.disabled)}
                    title={option.disabled ? "This option cannot be changed" : ""}>
                    <CheckBox
                      checked={stagedCreatedBy === option.value}
                      onChange={() => handleCreatedBySelect(option.value, option.disabled)}
                      disabled={option.disabled}
                    />
                    <span className={`${styles.optionLabel} ${option.disabled ? styles.optionLabelDisabled : ""}`}>{option.label}</span>
                  </div>
                );
              })}
            </div>
          </div>
        )}
      </div>

      {/* Footer with Apply and Clear */}
      <div className={styles.footer}>
        <IAFButton
          type="secondary"
          onClick={handleClear}
          disabled={stagedTypes.length === 0 && stagedIndustries.length === 0 && stagedCreatedBy === "All"}
          className={styles.clearButton}>
          Clear Selection
        </IAFButton>
        <IAFButton type="primary" onClick={handleApply} className={styles.applyButton}>
          Apply
        </IAFButton>
      </div>
    </div>
  );

  return (
    <div className={styles.container}>
      <button
        ref={buttonRef}
        type="button"
        className={`${styles.filterButton} ${open ? styles.filterButtonActive : ""} ${activeFiltersCount > 0 ? styles.filterButtonWithBadge : ""}`}
        onClick={() => setOpen(!open)}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label="Open filters">
        <SVGIcons icon="funnel" width={16} height={16} color="var(--content-color)" />
        {activeFiltersCount > 0 && <span className={styles.badge}>{activeFiltersCount}</span>}
      </button>

      {open && createPortal(dropdownContent, document.body)}
    </div>
  );
};

export default UnifiedFilterDropdown;
