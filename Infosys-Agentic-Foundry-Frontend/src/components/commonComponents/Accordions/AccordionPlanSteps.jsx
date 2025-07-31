import styles from "./AccordionPlan.module.css";
import React, { useState } from "react";
import ReactMarkdown from "react-markdown";
import DOMPurify from "dompurify";
import "../../../css_modules/MsgBox.css";
import dropdownCircle from "../../../Assets/dropdown-circle.png";
import remarkGfm from "remark-gfm";
import parse from "html-react-parser";
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { oneDark } from 'react-syntax-highlighter/dist/esm/styles/prism';

const AccordionPlanSteps = (props) => {
  const [isOpen, setIsOpen] = useState(false);

  const toggleAccordion = () => {
    setIsOpen(!isOpen);
  };
  const sanitizedContent = DOMPurify.sanitize(
    props?.content
      ?.replace(/\\n/g, "<br>")
      ?.replace(/\\"/g, '"')
  );
  return (
    <div className={styles.accordion}>
      <div className={styles["accordion-header"]}>
        <div className="Messagingbox">
          <div className="table-container">
            <ReactMarkdown 
              rehypePlugins={[remarkGfm]}
              components={{
                code({node, inline, className, children, ...props}) {
                  const match = /language-(\w+)/.exec(className || '');
                  return !inline && match ? (
                    <SyntaxHighlighter
                      style={oneDark}
                      language={match[1]}
                      PreTag="div"
                      {...props}
                    >
                      {String(children).replace(/\n$/, '')}
                    </SyntaxHighlighter>
                  ) : (
                    <code className={className} {...props}>
                      {children}
                    </code>
                  );
                }
              }}
            >
              {props.response}
            </ReactMarkdown>
          </div>
        </div>
        <div className={styles.accordionButton} onClick={toggleAccordion}>
          <span>DEBUG</span>
          <span
            className={
              isOpen ? styles.arrow + " " + styles["open"] : styles.arrow
            }
          >
            {/* <img src={dropdownCircle} /> */}
            <svg width="20" height="20" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg">
              <path d="M5 7 L10 13 L15 7 Z" fill="white" />
            </svg>
          </span>
        </div>
      </div>
        <div className={`${styles["accordion-content"]} ${isOpen ? styles.open : ''}`}>
          {isOpen && (<pre className={styles["accordion-text"]}>
            {/* Sanitize the message (with newlines already converted to <br />), 
              then parse the resulting safe HTML string into React elements. */}
            {parse(DOMPurify.sanitize(sanitizedContent))}
          </pre>
        )}
      </div>
    </div>
  );
};

export default AccordionPlanSteps;