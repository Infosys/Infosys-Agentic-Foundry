import React, { useState, useRef, useEffect } from "react";
import styles from "./CustomeDropdown.module.css";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faChevronDown } from "@fortawesome/free-solid-svg-icons";
import { faChevronUp } from "@fortawesome/free-solid-svg-icons";

const Dropdown = (props) => {
  const { options, placeholder, onChange, value } = props;
  const [isOpen, setIsOpen] = useState(false);
  const [selectedOption, setSelectedOption] = useState(value);
  const dropdownRef = useRef(null);

  const toggleDropdown = () => {
    setIsOpen(!isOpen);
  };

  const handleOptionClick = (option) => {
    setSelectedOption(option);
    setIsOpen(false);
    onChange(option);
  };

  const handleClickOutside = (event) => {
    if (dropdownRef.current && !dropdownRef.current.contains(event.target)) {
      setIsOpen(false);
    }
  };

  useEffect(() => {
    document.addEventListener("mousedown", handleClickOutside);
    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
    };
  }, []);

  return (
    <div className={styles["dropdown"]} ref={dropdownRef}>
      <div className={styles["dropdown-header"]} onClick={toggleDropdown}>
        <span className={styles["placeholder"]}>
          <span className={styles.placeholderText}>{`${placeholder}: `}</span>
          {selectedOption}
        </span>
        <span className={styles["arrow"]}>
          {isOpen ? (
            <FontAwesomeIcon icon={faChevronUp} />
          ) : (
            <FontAwesomeIcon icon={faChevronDown} />
          )}
        </span>
      </div>
      {isOpen && (
        <ul className={styles["dropdown-menu"]}>
          {options?.map((option) => (
            <li onClick={() => handleOptionClick(option?.value)}>
              {option?.label}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
};

export default Dropdown;
