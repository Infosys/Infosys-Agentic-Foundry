import React, { useState, useRef, useEffect } from "react";
import styles from "./OldChats.module.css";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faChevronDown } from "@fortawesome/free-solid-svg-icons";
import { faChevronUp } from "@fortawesome/free-solid-svg-icons";

const OldChats = (props) => {
  const {
    data,
    placeholder,
    onChange,
    value,
    fetchChatHistory,
    setOldSessionId,
  } = props;
  const [isOpen, setIsOpen] = useState(false);
  const [selectedOption, setSelectedOption] = useState(value);
  const dropdownRef = useRef(null);

  const toggleDropdown = () => {
    setIsOpen(!isOpen);
  };

  const handleOptionClick = async (option, sessionId) => {
    setSelectedOption(option);
    setIsOpen(false);
    onChange(option);
    setOldSessionId(sessionId);
    await fetchChatHistory(sessionId);
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
    // <div className={styles.dropdown} ref={dropdownRef}>
    //   {!isOpen && (
    //     <>
    //       <ul className={styles["dropdown-menu"]}>
    //         {data.length > 0 &&
    //           data?.map((option) => {
    //             const date = new Date(
    //               option?.timestamp_start
    //             ).toLocaleDateString();
    //             return (
    //               <li
    //                 onClick={() =>
    //                   handleOptionClick(option?.value, option?.session_id)
    //                 }
    //               >
    //                 <div className={styles["dropdown-item"]}>
    //                   <div className={styles.date}>
    //                     <span className={styles["dropdown-text"]}>Date:</span>
    //                     {date}
    //                   </div>
    //                   <div>
    //                     <span className={styles["dropdown-text"]}>
    //                       User Query:
    //                     </span>
    //                     {option?.user_input}
    //                   </div>
    //                   <div>
    //                     <span className={styles["dropdown-text"]}>
    //                       Response:
    //                     </span>
    //                     <span className={styles["response-text"]}>
    //                       {option?.agent_response}
    //                     </span>
    //                   </div>
    //                 </div>
    //               </li>
    //             );
    //           })}
    //       </ul>

    //       {data.length === 0 && (
    //         <span className={styles.noresultText}>No Chats</span>
    //       )}
    //     </>
    //   )}
    //   <div className={styles["dropdown-header"]} onClick={toggleDropdown}>
    //     {placeholder}

    //     <span className={styles["arrow"]}>
    //       {isOpen ? (
    //         <FontAwesomeIcon icon={faChevronDown} />
    //       ) : (
    //         <FontAwesomeIcon icon={faChevronUp} />
    //       )}
    //     </span>
    //   </div>
    // </div>
    <>
     <ul>
            {data.length > 0 &&
              data?.map((option) => {
                const date = new Date(
                  option?.timestamp_start
                ).toLocaleDateString();
                return (
                  <div className={styles?.OldChatsCss}>
                  <li
                    onClick={() =>
                      handleOptionClick(option?.value, option?.session_id)
                    }
                  >
                    <div className={styles["dropdown-item"]}>
                      <div className={styles.date}>
                        <span className={styles["dropdown-text"]}>Date:</span>
                        {date}
                      </div>
                      <div>
                        <span className={styles["dropdown-text"]}>
                          User Query:
                        </span>
                        {option?.user_input}
                      </div>
                      <div>
                        <span className={styles["dropdown-text"]}>
                          Response:
                        </span>
                        <span className={styles["response-text"]}>
                          {option?.agent_response}
                        </span>
                      </div>
                    </div>
                  </li>
                  </div>
                );
              })}
          </ul>

          {data.length === 0 && (
            <span className={styles.noresultText}>No Chats</span>
          )}
          </>
  );
};

export default OldChats;
