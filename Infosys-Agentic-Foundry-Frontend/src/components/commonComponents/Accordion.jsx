import styles from "./Accordion.module.css";
import React, { useState } from "react";
import ReactMarkdown from "react-markdown";
import dropdownCircle from "../../Assets/dropdown-circle.png"

const Accordion = (props) => {
  const [isOpen, setIsOpen] = useState(false);

  const toggleAccordion = () => {
    setIsOpen(!isOpen);
  };
  return (
    <div className={styles.accordion}>
      <div className={styles["accordion-header"]} onClick={toggleAccordion}>
        <p>Steps</p>
        <span
          className={
            isOpen ? styles.arrow + " " + styles["open"] : styles.arrow
          }
        >
          &#9662;
        </span>
      </div>
      {isOpen && (
        <div className={styles["accordion-content"]}>
          <pre className={styles["accordion-text"]}>{props.content}</pre>
        </div>
      )}
    </div>
  );
};

export default Accordion;
