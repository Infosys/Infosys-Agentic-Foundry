import React, { useState, useEffect, useRef } from "react";
import ReactDOM from "react-dom";
import styles from "./DepartmentSelector.module.css";
import SVGIcons from "../../../Icons/SVGIcons";
import TextField from "../../../iafComponents/GlobalComponents/TextField/TextField";

function DepartmentSelector({
  selectedDepartments = [],
  onChange,
  departmentsList = [],
  disabled = false,
  loading = false,
  placeholder = ""
}) {
  const [showDropdown, setShowDropdown] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [dropdownPosition, setDropdownPosition] = useState({ top: 0, left: 0, direction: "bottom" });
  const [highlightedIndex, setHighlightedIndex] = useState(-1);

  const containerRef = useRef(null);
  const dropdownRef = useRef(null);
  const plusButtonRef = useRef(null);
  const searchInputRef = useRef(null);

  // Get available departments (departments that are not selected)
  const availableDepartments = departmentsList.filter(
    (dept) => !selectedDepartments.includes(dept)
  );

  // Filter available departments based on search query
  const filteredDepartments = availableDepartments.filter((dept) =>
    dept.toLowerCase().includes(searchQuery.toLowerCase())
  );

  // Handle department selection
  const handleDepartmentSelect = (dept) => {
    const newSelectedDepartments = [...selectedDepartments, dept];
    onChange(newSelectedDepartments);
    setSearchQuery("");
    // Don't close dropdown - allow multiple selections
  };

  // Handle department removal
  const handleDepartmentRemove = (deptToRemove) => {
    const newSelectedDepartments = selectedDepartments.filter(
      (dept) => dept !== deptToRemove
    );
    onChange(newSelectedDepartments);
  };

  // Handle plus icon click
  const handlePlusClick = () => {
    if (availableDepartments.length > 0 && !loading && !disabled) {
      setShowDropdown(!showDropdown);
      setHighlightedIndex(-1);
      setSearchQuery("");
    }
  };

  // Calculate dropdown position
  const updatePosition = () => {
    if (!plusButtonRef.current) return;

    const buttonRect = plusButtonRef.current.getBoundingClientRect();
    const viewportHeight = window.innerHeight;
    const spaceBelow = viewportHeight - buttonRect.bottom;
    const spaceAbove = buttonRect.top;
    const dropdownHeight = 280; // Estimated dropdown height

    const direction = spaceBelow < dropdownHeight && spaceAbove > spaceBelow ? "top" : "bottom";

    setDropdownPosition({
      bottom: direction === "bottom" ? viewportHeight - buttonRect.bottom - 8 : viewportHeight - buttonRect.top + 8,
      left: buttonRect.right - 250, // Align right edge with button
      direction,
    });
  };

  // Handle keyboard navigation
  const handleKeyDown = (e) => {
    if (!showDropdown) return;

    switch (e.key) {
      case "ArrowDown":
        e.preventDefault();
        setHighlightedIndex((prev) =>
          prev < filteredDepartments.length - 1 ? prev + 1 : prev
        );
        break;
      case "ArrowUp":
        e.preventDefault();
        setHighlightedIndex((prev) => (prev > 0 ? prev - 1 : prev));
        break;
      case "Enter":
        e.preventDefault();
        if (highlightedIndex >= 0 && filteredDepartments[highlightedIndex]) {
          handleDepartmentSelect(filteredDepartments[highlightedIndex]);
        }
        break;
      case "Escape":
        setShowDropdown(false);
        setHighlightedIndex(-1);
        setSearchQuery("");
        break;
      default:
        break;
    }
  };

  // Close dropdown when clicking outside
  useEffect(() => {
    const handleClickOutside = (event) => {
      if (
        containerRef.current &&
        !containerRef.current.contains(event.target) &&
        dropdownRef.current &&
        !dropdownRef.current.contains(event.target)
      ) {
        setShowDropdown(false);
        setHighlightedIndex(-1);
        setSearchQuery("");
      }
    };

    if (showDropdown) {
      requestAnimationFrame(updatePosition);
      document.addEventListener("mousedown", handleClickOutside);
      window.addEventListener("resize", updatePosition);
      window.addEventListener("scroll", updatePosition, true);
    }

    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
      window.removeEventListener("resize", updatePosition);
      window.removeEventListener("scroll", updatePosition, true);
    };
  }, [showDropdown]);

  // Focus search input when dropdown opens
  useEffect(() => {
    if (showDropdown && searchInputRef.current) {
      setTimeout(() => {
        const input = searchInputRef.current.querySelector("input");
        if (input) input.focus();
      }, 50);
    }
  }, [showDropdown]);

  return (
    <div className={styles.deptContainer} ref={containerRef}>
      <div className={styles.pickerWrapper}>
        <span className={styles.deptPickerLabel}>Departments</span>
        <div className={`${styles.pillsContainer} ${disabled ? styles.pillsContainerDisabled : ""}`}>
          {selectedDepartments.length === 0 && (
            <span className={styles.placeholder}>{placeholder}</span>
          )}
          {selectedDepartments.map((dept) => (
            <span key={dept} className={styles.deptPill}>
              <SVGIcons icon="building" width={12} height={12} className={styles.pillIcon} />
              <span className={styles.pillText}>{dept}</span>
              {!disabled && (
                <span
                  className={styles.removeDeptBtn}
                  onClick={() => handleDepartmentRemove(dept)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === " ") {
                      e.preventDefault();
                      handleDepartmentRemove(dept);
                    }
                  }}
                  tabIndex={0}
                  aria-label={`Remove ${dept}`}
                >
                  ×
                </span>
              )}
            </span>
          ))}
        </div>
        {!disabled && (
          <div
            ref={plusButtonRef}
            className={`smallAddBtn ${availableDepartments.length === 0 || loading ? "disabled" : ""}`}
            onClick={handlePlusClick}
            onKeyDown={(e) => {
              if (availableDepartments.length === 0 || loading) return;
              if (e.key === " " || e.key === "Enter") {
                e.preventDefault();
                handlePlusClick();
              } else if (showDropdown) {
                handleKeyDown(e);
              }
            }}
            aria-label="Add department"
            title={
              loading
                ? "Loading departments..."
                : availableDepartments.length === 0
                  ? "No more departments available"
                  : "Add department"
            }
            tabIndex={availableDepartments.length > 0 && !loading ? 0 : -1}
          >
            +
          </div>
        )}
      </div>

      {showDropdown &&
        availableDepartments.length > 0 &&
        ReactDOM.createPortal(
          <div
            className={`${styles.pickerDropdown} ${dropdownPosition.direction === "top" ? styles.dropdownTop : styles.dropdownBottom
              }`}
            ref={dropdownRef}
            style={{
              position: "fixed",
              bottom: `${dropdownPosition.bottom}px`,
              left: `${dropdownPosition.left}px`,
              zIndex: 1000010,
            }}
            onKeyDown={handleKeyDown}
            onMouseLeave={() => {
              if (!searchQuery) {
                setShowDropdown(false);
                setHighlightedIndex(-1);
                setSearchQuery("");
              }
            }}
          >
            {/* Search input - top position for bottom-opening dropdown */}
            {dropdownPosition.direction === "bottom" && (
              <div className={styles.searchContainer} ref={searchInputRef}>
                <TextField
                  placeholder="Search departments..."
                  value={searchQuery}
                  onChange={(e) => {
                    setSearchQuery(e.target.value);
                    setHighlightedIndex(-1);
                  }}
                  onClear={() => {
                    setSearchQuery("");
                    setHighlightedIndex(-1);
                  }}
                  showClearButton={true}
                  showSearchButton={true}
                  onKeyDown={(e) => {
                    if (e.key === "ArrowDown" || e.key === "ArrowUp" || e.key === "Escape") {
                      handleKeyDown(e);
                    }
                  }}
                  onClick={(e) => e.stopPropagation()}
                  aria-label="Search departments"
                />
              </div>
            )}

            {/* Departments list */}
            <div className={styles.listContainer}>
              {filteredDepartments.length === 0 ? (
                <div className={styles.noResults}>No departments found</div>
              ) : (
                filteredDepartments.map((dept, index) => (
                  <div
                    key={dept}
                    className={`${styles.deptItem} ${highlightedIndex === index ? styles.highlighted : ""
                      }`}
                    onClick={() => handleDepartmentSelect(dept)}
                    onMouseEnter={() => setHighlightedIndex(index)}
                  >
                    <SVGIcons icon="building" width={14} height={14} />
                    <span>{dept}</span>
                  </div>
                ))
              )}
            </div>

            {/* Search input - bottom position for top-opening dropdown */}
            {dropdownPosition.direction === "top" && (
              <div className={styles.searchContainer} ref={searchInputRef}>
                <TextField
                  placeholder="Search departments..."
                  value={searchQuery}
                  onChange={(e) => {
                    setSearchQuery(e.target.value);
                    setHighlightedIndex(-1);
                  }}
                  onClear={() => {
                    setSearchQuery("");
                    setHighlightedIndex(-1);
                  }}
                  showClearButton={true}
                  showSearchButton={true}
                  onKeyDown={(e) => {
                    if (e.key === "ArrowDown" || e.key === "ArrowUp" || e.key === "Escape") {
                      handleKeyDown(e);
                    }
                  }}
                  onClick={(e) => e.stopPropagation()}
                  aria-label="Search departments"
                />
              </div>
            )}
          </div>,
          document.body
        )}
    </div>
  );
}

export default DepartmentSelector;
