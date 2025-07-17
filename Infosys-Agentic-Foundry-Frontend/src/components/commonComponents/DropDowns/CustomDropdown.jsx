import React, { useState, useRef, useEffect } from "react";
import styles from "./CustomeDropdown.module.css";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faChevronDown, faChevronUp ,faRobot,faGlobe} from "@fortawesome/free-solid-svg-icons";
import { REACT_AGENT } from "../../../constant";

const Dropdown = (props) => {
  const { options, placeholder, onChange, value, disabled,agentType } = props;
  const [isOpen, setIsOpen] = useState(false);
  const [selectedOption, setSelectedOption] = useState(value);
  const [highlightIndex, setHighlightIndex] = useState(0);
  const dropdownRef = useRef(null);

  const toggleDropdown = () => {
    if (!disabled) {
      setIsOpen(!isOpen);
    }
  };

  const handleKeyDown = (e) => {
    if (!isOpen) return;

    switch (e.key) {
      case "ArrowDown":
        e.preventDefault();
        setHighlightIndex((prev) => (prev + 1) % options.length);
        break;
      case "ArrowUp":
        e.preventDefault();
        setHighlightIndex((prev) => (prev - 1 + options.length) % options.length);
        break;
      case "Enter":
        e.preventDefault();
        const selected = options[highlightIndex];
        setSelectedOption(selected?.value);
        onChange(selected?.value);
        setIsOpen(false);
        break;
      case "Escape":
        setIsOpen(false);
        break;
      default:
        break;
    }
  };

  const handleOptionClick = (option, index) => {
    setSelectedOption(option.value);
    setHighlightIndex(index);
    setIsOpen(false);
    onChange(option.value);
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
 const displayLabel = selectedOption.length > 12 ? `${selectedOption.slice(0, 12)}....` : selectedOption;
  return (
    // <div
    //   className={styles["dropdown"]}
    //   ref={dropdownRef}
    //   tabIndex={0}
    //   onKeyDown={handleKeyDown}
    // >
    <div
  className={`${styles["dropdown"]} ${isOpen  ? styles["dropdown-up"] : ""}`}
  ref={dropdownRef}
  tabIndex={0}
  onKeyDown={handleKeyDown}
>
      <div
       
        onClick={toggleDropdown} title={selectedOption}
      >
        {agentType===REACT_AGENT ?(
          <>
<span className={styles.hoverEffectCss}>
                              <FontAwesomeIcon icon={faRobot} />
                            </span>
                            </>
        ):(
          <>
          <span className={styles.hoverEffectCss}>
           <FontAwesomeIcon icon={faGlobe} />
                            </span>
          </>
        )}
        
        {/* <span className={styles["placeholder"]}> */}
          {/* <span className={styles.placeholderText}>{`${placeholder}: `}</span> */}
          {agentType===REACT_AGENT ? selectedOption:displayLabel|| "Model"}

        {/* </span> */}
        {/* <span className={styles.chevronCss}>
          <FontAwesomeIcon icon={isOpen ? faChevronUp : faChevronDown} />
        </span> */}
      </div>

      {isOpen && !disabled && (
        <ul className={styles["dropdown-menu"]}>
          {options?.map((option, index) => (
            <li
              key={option.value}
              onClick={() => handleOptionClick(option, index)}
              className={
                index === highlightIndex ? styles["highlighted"] : ""
              }
            >
              {option.label}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
};

export default Dropdown;
