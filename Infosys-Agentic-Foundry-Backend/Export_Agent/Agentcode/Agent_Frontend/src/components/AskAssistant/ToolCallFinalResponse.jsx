import styles from "../../components/commonComponents/Accordions/AccordionPlan.module.css";
import React, { useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import toolCallCSS from "./ToolCallFinalResponse.module.css"; // Add this import for new styles

const ToolCallFinalResponse = (props) => {
  const [isOpen, setIsOpen] = useState(false);
  // Handler to reset values and exit edit mode
  const handleCancelEdit = () => {
    // Reset argument values to default from messageData
    try {
      const argObj =
        props?.messageData?.toolcallData?.additional_details?.[0]
          ?.additional_kwargs?.tool_calls?.[0]?.function?.arguments;
      const parsed = JSON.parse(argObj || "{}");
      props.setParsedValues(parsed);
    } catch {
      props.setParsedValues({});
    }

    // Need to return back to default state of the tool interrupt
    props.setLikeIcon(false);
    props.setIsEditable(false);

    // If parent controls isEditable, call callback if provided
    if (props.onCancelEdit) props.onCancelEdit();
  };

  const toggleAccordion = () => {
    setIsOpen(!isOpen);
  };
  useEffect(() => {
    const jsonString = props?.rawData;

    try {
      const obj = JSON.parse(jsonString);
      props.setParsedValues(obj);
    } catch (error) {
      console.error("Error parsing JSON:", error);
    }
  }, [props?.rawData]);
  useEffect(() => {}, [props?.messageData]);
  return (
    <>
      <div className={toolCallCSS.toolCallWrapper}>
        {/* Updated Tool Call Box Styling */}
        <div className={toolCallCSS.toolcallBox}>
          <div className={toolCallCSS.toolcallHeader}>
            <span className={toolCallCSS.toolcallHeaderTitle}>Tool Calls</span>
          </div>
          <div className={toolCallCSS.toolcallContent}>
            <div className={toolCallCSS.toolcallRow}>
              <span className={toolCallCSS.toolcallLabel}>Tool Name:</span>
              <span className={toolCallCSS.toolcallValue}>
                <ReactMarkdown rehypePlugins={[remarkGfm]}>
                  {props?.messageData?.toolcallData &&
                  props?.messageData?.toolcallData?.additional_details[0]
                    ? props?.messageData?.toolcallData?.additional_details[0]
                        ?.additional_kwargs?.tool_calls[0]?.function?.name
                    : ""}
                </ReactMarkdown>
              </span>
            </div>
            <div
              className={
                toolCallCSS.toolcallRow + " " + toolCallCSS.toolcallArguments
              }
            >
              <span className={toolCallCSS.toolcallLabel}>Arguments:</span>
              <span className={toolCallCSS.toolcallValue}>
                {(() => {
                  const argsEmpty =
                    props?.messageData?.toolcallData?.additional_details?.[0]
                      ?.additional_kwargs?.tool_calls?.[0]?.function
                      ?.arguments === "{}";
                  if (argsEmpty) {
                    return (
                      <span className={toolCallCSS.toolcallNoArgs}>
                        No arguments to show
                      </span>
                    );
                  }
                  // Always render inputs, control editability with readOnly
                  let argEntries = [];
                  if (props.isEditable) {
                    argEntries = Object.entries(props?.parsedValues || {});
                  } else {
                    const argObj =
                      props?.messageData?.toolcallData?.additional_details?.[0]
                        ?.additional_kwargs?.tool_calls?.[0]?.function?.arguments;
                    try {
                      argEntries = Object.entries(JSON.parse(argObj || "{}"));
                    } catch {
                      argEntries = [];
                    }
                  }
                  return (
                    <div className={toolCallCSS.toolcallArgsList}>
                      {argEntries.map(([key, val]) => {
                        const value =
                          typeof val === "object" ? JSON.stringify(val) : val;
                        const isLong =
                          typeof val === "object" ||
                          (typeof val === "string" && val.length > 10);
                        return (
                          <div className={toolCallCSS.toolcallArgItem} key={key}>
                            <span className={toolCallCSS.toolcallArgKey}>{key}:</span>
                            {isLong ? (
                              <textarea
                                className={toolCallCSS.toolcallArgInput}
                                value={value}
                                disabled={!props.isEditable}
                                onChange={
                                  props.isEditable
                                    ? (e) =>
                                        props.handleEditChange(
                                          key,
                                          e.target.value,
                                          val
                                        )
                                    : undefined
                                }
                              />
                            ) : (
                              <input
                                className={toolCallCSS.toolcallArgInput}
                                type="text"
                                value={value}
                                disabled={!props.isEditable}
                                onChange={
                                  props.isEditable
                                    ? (e) =>
                                        props.handleEditChange(
                                          key,
                                          e.target.value,
                                          val
                                        )
                                    : undefined
                                }
                                autoFocus={props.isEditable}
                              />
                            )}
                          </div>
                        );
                      })}
                    </div>
                  );
                })()}
              </span>
            </div>
            {props?.isEditable &&
              (!props?.generating || !props?.fetching) &&
              props?.sendIconShow && (
                <div className={toolCallCSS.toolcallActions}>
                  <button
                    className={toolCallCSS.toolcallUpdateBtn}
                    onClick={() =>
                      props?.sendArgumentEditData(props?.messageData)
                    }
                    title="Update"
                  >
                    Update
                  </button>
                  <button
                    className={toolCallCSS.toolcallCancelBtn}
                    onClick={handleCancelEdit}
                    title="Cancel"
                    style={{
                      marginLeft: 8,
                      background: "#f3f4f6",
                      color: "#374151",
                      border: "1px solid #e5e7eb",
                    }}
                  >
                    Cancel
                  </button>
                </div>
              )}
          </div>
        </div>
        {/* End Tool Call Box */}
        <div className={styles.accordionButton} onClick={toggleAccordion}>
          <span>DEBUG</span>
          <span
            className={
              isOpen ? styles.arrow + " " + styles["open"] : styles.arrow
            }
          >
            <svg
              width="20"
              height="20"
              viewBox="0 0 20 20"
              fill="none"
              xmlns="http://www.w3.org/2000/svg"
            >
              <path d="M5 7 L10 13 L15 7 Z" fill="white" />
            </svg>
          </span>
        </div>
      </div>
      {isOpen && (
        // <div className={`${styles["accordion-content"]} ${
        //     isOpen ? styles.open : ""
        //   }`}
        // >
        //   <pre
        //     className={styles["accordion-text"] +"accordionSteps-2"}
        //     dangerouslySetInnerHTML={{
        //       __html: props?.content
        //         .replace(/\\n/g, "<br>")
        //         .replace(/\\"/g, '"'),
        //     }}
        //   ></pre>
        // </div>

        <div
          className={`${styles["accordion-content"]} ${isOpen ? styles.open : ""}`}
        >
          <div className={styles["accordion-text"] + " accordionSteps-2"}>
            <ReactMarkdown
              rehypePlugins={[remarkGfm]}
              components={{
                code({ node, inline, className, children, ...props }) {
                  const match = /language-(\w+)/.exec(className || "");
                  return !inline && match ? (
                    <pre>
                      <code className={className} {...props}>
                        {String(children).replace(/\n$/, "")}
                      </code>
                    </pre>
                  ) : (
                    <code className={className} {...props}>
                      {children}
                    </code>
                  );
                },
              }}
            >
              {props?.content?.replace(/\\n/g, "\n").replace(/\\"/g, '"')}
            </ReactMarkdown>
          </div>
        </div>
      )}
    </>
  );
};

export default ToolCallFinalResponse;
