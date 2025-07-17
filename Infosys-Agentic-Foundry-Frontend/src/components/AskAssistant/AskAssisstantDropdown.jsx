import React, { useState, useRef, useEffect } from "react";
import styles from "./AskAssisstantDropdown.module.css";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import {faHexagonNodes} from "@fortawesome/free-solid-svg-icons";
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

const selectedOptions = options.find(option => option.value === value);

const reorderedOptions = selectedOptions
  ? [selectedOptions, ...filteredOptions.filter(option => option.value !== value)]
  : filteredOptions;

const handleOptionClick = (optionValue, index) => {
  onChange(optionValue);
  setIsDropdownOpen(false);
  setSearchQuery("");
  setHighlightIndex(index);
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
    if (highlightIndex >= 0 && isDropdownOpen) {
      const optionEl = document.getElementById(`dropdown-option-${highlightIndex}`);
      if (optionEl) optionEl.scrollIntoView({ block: 'nearest' });
    }
  }, [highlightIndex, isDropdownOpen]);
 
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
const selectedOption = options.find(option => option.value === value);
  const fullLabel = selectedOption?.label || placeholder;
  const displayLabel = fullLabel.length > 5 ? `${fullLabel.slice(0, 10)}...` : fullLabel;
  return (
    // <div
    //   className={`${styles.dropdownContainer} ${containerStyle}`}
    //   style={{ position: "relative", width: "20rem" }}
    //   ref={dropdownRef}
    //   onKeyDown={handleKeyDown}
    //   tabIndex={0}
    // >
    <>
      {/* <div
        className={styles.selectedValue}
        onClick={() => {
          if (!disabled) setIsDropdownOpen((prevState) => !prevState);
        }}
      > */}
      <span ref={dropdownRef}
      onKeyDown={handleKeyDown}
      tabIndex={0} className={styles.agentNodeCss}
      >
        <span className={styles.hoverEffectCss}>
          <FontAwesomeIcon icon={faHexagonNodes} />
                            </span>
        <span onClick={() => {
          if (!disabled) setIsDropdownOpen((prevState) => !prevState);
        }} className={styles.chevronCss} title={fullLabel}>
          {displayLabel}
        </span>
                  

      {isDropdownOpen && !disabled && (
        
        <div
          className={`${styles.dropdownMenu} ${isSearch ? styles.dropdownMenuWithSearch : ''}`}
        >
          <div className={styles.dropdownOptionsContainer}>
{reorderedOptions.length > 0 ? (
  reorderedOptions.map((option, index) => {
    const isSelected = option.value === value;
    const isHighlighted = index === highlightIndex; 

    return (
      <div
        key={option.value}
        className={`${styles.dropdownOption} ${
          isSelected ? styles.highlighted : ""
        }`}
        onClick={() => handleOptionClick(option.value, index)} 
      >
        {highlightMatch(option.label, searchQuery)}
      </div>
      
    );
  })
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
      </span>
      </>
    // {/* // </div> */}
  );
};
 
export default DropDown;