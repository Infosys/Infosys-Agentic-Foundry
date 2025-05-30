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
  } = props;

  const [searchQuery, setSearchQuery] = useState("");
  const [isDropdownOpen, setIsDropdownOpen] = useState(false);
  const dropdownRef = useRef(null);

  const filteredOptions = options.filter((option) =>
    option?.label?.toLowerCase().startsWith(searchQuery.toLowerCase())
  );

  const handleOptionClick = (optionValue) => {
    onChange(optionValue);
    setIsDropdownOpen(false);
    setSearchQuery("");
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

  useEffect(() => {
    const handleClickOutside = (event) => {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target)) {
        setIsDropdownOpen(false); // Close the dropdown
      }
    };

    document.addEventListener("mousedown", handleClickOutside);

    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
    };
  }, []);

  return (
    <div
      className={`${styles.dropdownContainer} ${containerStyle}`}
      style={{ position: "relative", width: "20rem" }}
      ref={dropdownRef}
    >
      {/* Selected Value */}
      <div
        className={styles.selectedValue}
        onClick={() => setIsDropdownOpen((prevState) => !prevState)}
      >
        <span>
          {value
            ? options.find((option) => option.value === value)?.label || placeholder
            : placeholder}
        </span>
        {/* Dropdown Icon */}
        <span className={styles.dropdownIcon}>
          {isDropdownOpen ? "▲" : "▼"}
        </span>
      </div>

      {isDropdownOpen && (
        <div
          className={`${styles.dropdownMenu} ${isSearch ? styles.dropdownMenuWithSearch : ''}`}
        >
          <div className={styles.dropdownOptionsContainer}>
            {filteredOptions.map((option) => (
              <div
                key={option.value}
                className={styles.dropdownOption}
                onClick={() => handleOptionClick(option.value)}
                style={{
                  fontWeight:
                    searchQuery &&
                    option.label.toLowerCase() === searchQuery.toLowerCase()
                      ? "bold"
                      : "normal",
                }}
              >
                {highlightMatch(option.label, searchQuery)}
              </div>
            ))}

            {filteredOptions.length === 0 && (
              <div className={styles.noOptions}>No options found</div>
            )}
          </div>

          {isSearch && (
            <input
              type="text"
              placeholder="Search..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className={styles.searchInput}
            />
          )}
        </div>
      )}
    </div>
  );
};

export default DropDown;