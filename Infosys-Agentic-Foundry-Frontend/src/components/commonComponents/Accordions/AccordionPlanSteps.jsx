import { useState } from "react";
import Cookies from "js-cookie";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Prism as SyntaxHighlighter } from "react-syntax-highlighter";
import { oneDark } from "react-syntax-highlighter/dist/esm/styles/prism";
import styles from "./AccordionPlan.module.css";
import DebugStepsCss from "../../../css_modules/DebugSteps.module.css";

const AccordionPlanSteps = (props) => {
  const userRole = (Cookies.get("role") || "").toLowerCase();
  const [isOpen, setIsOpen] = useState(false);
  const [canvasIsOpen, setCanvasIsOpen] = useState(false);

  const toggleAccordion = () => {
    setIsOpen(!isOpen);
  };
  const handleCanvasOpen = (e) => {
    const targetElement = e.currentTarget;

    // If the element is already active, don't do a thing!
    if (targetElement.classList.contains("canvasIsOpen")) {
      return;
    }

    // Find all other "View details" bubbles and remove the active class
    const allBubbles = document.querySelectorAll(`.${styles.viewDetailsBubble}`);
    allBubbles.forEach((bubble) => {
      bubble.classList.remove("canvasIsOpen");
    });

    // Add the active class to show it's been clicked
    targetElement.classList.add("canvasIsOpen");

    // Simplified logic: if we have openCanvas function and structured parts, use them directly
    if (props.openCanvas && props.parts && Array.isArray(props.parts)) {
      // Filter out parts with type 'text' as they are already displayed.
      const canvasParts = props.parts.filter((part) => part.type !== "text");

      if (canvasParts.length > 0) {
        // We have content for the canvas!
        // setCanvasIsOpen(true);
        props.openCanvas(canvasParts, "Detailed View", "parts", null, true);
      }
    }
  };

  // Check if there's any content to display before rendering the entire component
  const textContent = props.parts
    ?.filter((part) => part.type === "text" && part.data?.content)
    .map((part) => part.data.content)
    .join("\n\n");

  const canvasParts = props.parts?.filter((part) => part.type !== "text") || [];

  // If there's no text content and no canvas parts, don't render anything
  if ((!textContent || textContent.trim() === "") && canvasParts.length === 0) {
    return null;
  }

  return (
    <div className={styles.accordion}>
      <div className={styles["accordion-header"]}>
        {(() => {
          if (!props?.show_canvas) {
            // Only render if there's actually content to display
            if (!textContent || textContent.trim() === "") {
              return null;
            }

            // Show all text parts as text-only bubble
            return (
              <div className={`${styles.messageBubble} textOnlyBubble`}>
                <ReactMarkdown
                  rehypePlugins={[remarkGfm]}
                  components={{
                    code({ node, inline, className, children, ...props }) {
                      const match = /language-(\w+)/.exec(className || "");
                      return !inline && match ? (
                        <SyntaxHighlighter style={oneDark} language={match[1]} PreTag="div" {...props}>
                          {String(children).replace(/\n$/, "")}
                        </SyntaxHighlighter>
                      ) : (
                        <code className={className} {...props}>
                          {children}
                        </code>
                      );
                    },
                  }}>
                  {textContent}
                </ReactMarkdown>
              </div>
            );
          } else {
            // Only render if there's text content or canvas parts
            if ((!textContent || textContent.trim() === "") && canvasParts.length === 0) {
              return null;
            }

            // Multiple parts, show all text parts and canvas button
            return (
              <div className={`${styles.messageBubble} showCanvasBtn`}>
                {textContent && textContent.trim() !== "" && (
                  <ReactMarkdown
                    rehypePlugins={[remarkGfm]}
                    components={{
                      code({ node, inline, className, children, ...props }) {
                        const match = /language-(\w+)/.exec(className || "");
                        return !inline && match ? (
                          <SyntaxHighlighter style={oneDark} language={match[1]} PreTag="div" {...props}>
                            {String(children).replace(/\n$/, "")}
                          </SyntaxHighlighter>
                        ) : (
                          <code className={className} {...props}>
                            {children}
                          </code>
                        );
                      },
                    }}>
                    {textContent}
                  </ReactMarkdown>
                )}
                {canvasParts.length > 0 && (
                  <div className={styles.viewDetailsBubble} tabIndex={0} role="button" aria-label="View details" onClick={handleCanvasOpen}>
                    <span className={styles.viewDetailsText}>View details</span>
                    <span className={styles.viewDetailsArrow} aria-hidden="true">
                      <svg width="18" height="18" viewBox="0 0 18 18" fill="none">
                        <path d="M6 4L12 9L6 14" stroke="#007acc" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                      </svg>
                    </span>
                  </div>
                )}
              </div>
            );
          }
        })()}
        {/* Hide Execution Steps accordion for USER role */}
        {userRole !== "user" && (
          <div className={styles.accordionButton} onClick={toggleAccordion}>
            <span style={{ fontSize: "10px" }}>Execution Steps</span>
            <span className={isOpen ? styles.arrow + " " + styles["open"] : styles.arrow}>
              <svg width="15" height="15" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg">
                <path d="M5 7 L10 13 L15 7 Z" fill="white" />
              </svg>
            </span>
          </div>
        )}
      </div>
      {/* Hide Execution Steps content for USER role */}
      {userRole !== "user" && (
        <div className={`${styles["accordion-content"]} ${isOpen ? styles.open : ""}`}>
          <>
            {/* Debug Steps UI Start */}
            {isOpen && props?.debugExecutor && (
              <>
                <div className={DebugStepsCss.debugStepsWrapper}>
                  <div className={styles.debugExecutionsHeader}>Execution Steps</div>
                  <div className={styles.debugExecutionsteps}>
                    {Array.isArray(props.debugExecutor) &&
                      (() => {
                        let stepCounter = 1;
                        return props.debugExecutor
                          .slice()
                          .reverse()
                          .map((item, idx, arr) => {
                            let stepElement = null;

                            // User Query Stage
                            if (item.role) {
                              // Format the role for display: capitalize, replace underscores with spaces
                              const formattedRole = item.role.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
                              stepElement = (
                                <div key={idx} className={DebugStepsCss.eachSteps + " " + DebugStepsCss.userQueryStage}>
                                  <div className={DebugStepsCss.stepHeader}>
                                    <span className={DebugStepsCss.stepCount}>{stepCounter}</span> {formattedRole}
                                  </div>
                                  <div className={DebugStepsCss.stepsContent}>{item.content}</div>
                                </div>
                              );
                            }
                            // Tool Calls Stage
                            else if (item.tool_calls && item.tool_calls.length > 0) {
                              stepElement = (
                                <div key={idx} className={DebugStepsCss.eachSteps + " " + DebugStepsCss.toolsCallStage}>
                                  <div className={DebugStepsCss.stepHeader}>
                                    <span className={DebugStepsCss.stepCount}>{stepCounter}</span> Tool Calls
                                  </div>
                                  <div className={DebugStepsCss.stepsContent}>
                                    {item.tool_calls.map((call, tIdx) => {
                                      // Find the tool response in the next items (type: 'tool', tool_call_id matches)
                                      const toolResp = arr.find((d) => d.type === "tool" && d.tool_call_id === call.id);
                                      return (
                                        <div key={call.id} className={DebugStepsCss.stepsToolBlockWrapper}>
                                          <div className={DebugStepsCss.toolName + " " + DebugStepsCss.toolCallRow}>
                                            <span className={DebugStepsCss.toolTitle}>Function: </span>
                                            <span>{call.name}</span>
                                          </div>
                                          <div className={DebugStepsCss.toolCallRow}>
                                            <span className={DebugStepsCss.toolTitle}>Args: </span>
                                            <span>
                                              {Object.entries(call.args)
                                                .map(([k, v]) => `${k}: ${v}`)
                                                .join(", ")}
                                            </span>
                                          </div>
                                          <div className={DebugStepsCss.toolCallRow}>
                                            <span className={DebugStepsCss.toolTitle}>Response </span>
                                            <span className={DebugStepsCss.toolResponse}>
                                              {toolResp?.content ? <>{toolResp.content}</> : <span style={{ color: "#b6beca" }}>[No response found]</span>}
                                            </span>
                                          </div>
                                        </div>
                                      );
                                    })}
                                  </div>
                                </div>
                              );
                            }
                            // AI/Human Message Stage
                            else if (item.content && item.type !== "tool") {
                              stepElement = (
                                <div key={idx} className={DebugStepsCss.eachSteps + " " + DebugStepsCss.AiHumanStage}>
                                  <div className={DebugStepsCss.stepHeader}>
                                    <span className={DebugStepsCss.stepCount}>{stepCounter}</span> {item.content.includes("Past Conversation Summary") ? "Context" : "Response"}
                                  </div>
                                  <div className={DebugStepsCss.stepsContent}>
                                    <ReactMarkdown
                                      rehypePlugins={[remarkGfm]}
                                      components={{
                                        code({ node, inline, className, children, ...props }) {
                                          const match = /language-(\w+)/.exec(className || "");
                                          return !inline && match ? (
                                            <SyntaxHighlighter style={oneDark} language={match[1]} PreTag="div" {...props}>
                                              {String(children).replace(/\n$/, "")}
                                            </SyntaxHighlighter>
                                          ) : (
                                            <code className={className} {...props}>
                                              {children}
                                            </code>
                                          );
                                        },
                                      }}>
                                      {item.content}
                                    </ReactMarkdown>
                                  </div>
                                </div>
                              );
                            }

                            // Only increment counter if we're actually displaying a step
                            if (stepElement) {
                              stepCounter++;
                              return stepElement;
                            }
                            return null;
                          });
                      })()}
                  </div>
                </div>
              </>
            )}
            {/* Debug Steps UI End */}
          </>
        </div>
      )}
    </div>
  );
};

export default AccordionPlanSteps;
