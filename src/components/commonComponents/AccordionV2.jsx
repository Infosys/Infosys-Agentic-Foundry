import styles from "./Accordion.module.css";
import React, { useState } from "react";

const AccordionSteps = ({children, header=""}) => {
  const [isOpen, setIsOpen] = useState(true);

  const toggleAccordion = () => {
    setIsOpen(!isOpen);
  };
  return (
    <div className={styles.accordion}>
      <div className={styles["accordion-header"]} onClick={toggleAccordion}>
        <p>{header}</p>
        <span className={isOpen ? styles.arrow + " " + styles["open"] : styles.arrow} >&#9662;</span>
      </div>
      {isOpen && <div className={styles["accordion-content"]}>{children}</div>}
    </div>
  );
};

export default AccordionSteps;
