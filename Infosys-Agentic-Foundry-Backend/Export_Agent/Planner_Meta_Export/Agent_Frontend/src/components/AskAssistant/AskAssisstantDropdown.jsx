import React, { useState, useRef, useEffect } from "react";
import styles from "./AskAssisstantDropdown.module.css";

const DropDown = (props) => {
  const {
    options,
    containerStyle,
    placeholder,
    isSearch = false,
    value,
    onChange,
    disabled,
  } = props;

  const [searchQuery, setSearchQuery] = useState("");
  const [isDropdownOpen, setIsDropdownOpen] = useState(false);
  const [highlightIndex, setHighlightIndex] = useState(-1);
  const dropdownRef = useRef(null);
  const searchInputRef = useRef(null);

  const filteredOptions = options.filter((option) =>
    option?.label?.toLowerCase().startsWith(searchQuery.toLowerCase())
  );

  const handleOptionClick = (optionValue) => {
    onChange(optionValue);
    setIsDropdownOpen(false);
    setSearchQuery("");
    setHighlightIndex(-1);
  };

  const highlightMatch = (label, query) => {
    if (!query) return label;
    const regex = new RegExp(`(${query})`, "gi");
    return label.split(regex).map((part, index) =>
      part.toLowerCase() === query.toLowerCase() ? (
        <span key={index} style={{ fontWeight: "bold" }}>{part}</span>
      ) : (
        part
      )
    );
  };

  const handleKeyDown = (e) => {
    if (!isDropdownOpen || disabled) return;

    switch (e.key) {
      case "ArrowDown":
        e.preventDefault();
        setHighlightIndex((prev) =>
          prev < filteredOptions.length - 1 ? prev + 1 : 0
        );
        break;
      case "ArrowUp":
        e.preventDefault();
        setHighlightIndex((prev) =>
          prev > 0 ? prev - 1 : filteredOptions.length - 1
        );
        break;
      case "Enter":
        e.preventDefault();
        if (highlightIndex >= 0 && highlightIndex < filteredOptions.length) {
          handleOptionClick(filteredOptions[highlightIndex].value);
        }
        break;
      case "Escape":
        setIsDropdownOpen(false);
        break;
      default:
        break;
    }
  };

  useEffect(() => {
    const handleClickOutside = (event) => {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target)) {
        setIsDropdownOpen(false);
      }
    };

    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  useEffect(() => {
    if (isDropdownOpen && isSearch && searchInputRef.current) {
      searchInputRef.current.focus();
    }
  }, [isDropdownOpen]);

  return (
    <div
      className={`${styles.dropdownContainer} ${containerStyle}`}
      style={{ position: "relative", width: "20rem" }}
      ref={dropdownRef}
      onKeyDown={handleKeyDown}
      tabIndex={0}
    >
      <div
        className={styles.selectedValue}
        onClick={() => {
          if (!disabled) setIsDropdownOpen((prevState) => !prevState);
        }}
      >
        <span>
          {value
            ? options.find((option) => option.value === value)?.label || placeholder
            : placeholder}
        </span>
        <span className={styles.dropdownIcon}>
          {isDropdownOpen && !disabled ? "▲" : "▼"}
        </span>
      </div>

      {isDropdownOpen && !disabled && (
        <div
          className={`${styles.dropdownMenu} ${isSearch ? styles.dropdownMenuWithSearch : ''}`}
        >
          <div className={styles.dropdownOptionsContainer}>
            {filteredOptions.length > 0 ? (
              filteredOptions.map((option, index) => (
                <div
                  key={option.value}
                  className={`${styles.dropdownOption} ${
                    index === highlightIndex ? styles.highlighted : ""
                  }`}
                  onClick={() => handleOptionClick(option.value)}
                >
                  {highlightMatch(option.label, searchQuery)}
                </div>
              ))
            ) : (
              <div className={styles.noOptions}>No options found</div>
            )}
          </div>

          {isSearch && (
            <input
              type="text"
              placeholder="Search..."
              value={searchQuery}
              onChange={(e) => {
                setSearchQuery(e.target.value);
                setHighlightIndex(0); 
              }}
              className={styles.searchInput}
              ref={searchInputRef}
            />
          )}
        </div>
      )}
    </div>
  );
};

export default DropDown;