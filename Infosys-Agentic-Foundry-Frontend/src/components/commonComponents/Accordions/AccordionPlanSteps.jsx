import { useState } from "react";
import Cookies from "js-cookie";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Prism as SyntaxHighlighter } from "react-syntax-highlighter";
import { oneDark, oneLight } from "react-syntax-highlighter/dist/esm/styles/prism";
import { useTheme } from "../../../Hooks/ThemeContext";
import styles from "./AccordionPlan.module.css";
import DebugStepsCss from "../../../css_modules/DebugSteps.module.css";
import SVGIcons from "../../../Icons/SVGIcons";
import { META_AGENT, PLANNER_META_AGENT } from "../../../constant";

const AccordionPlanSteps = (props) => {
  const userRole = (Cookies.get("role") || "").toLowerCase();
  const [isOpen, setIsOpen] = useState(false);
  const [reasoningOpen, setReasoningOpen] = useState(false);
  const { theme } = useTheme();
  const syntaxTheme = theme === "dark" ? oneDark : oneLight;

  const toggleAccordion = () => {
    setIsOpen(!isOpen);
  };

  const toggleReasoning = () => {
    setReasoningOpen(!reasoningOpen);
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
  // First try to get content from parts (for structured responses)
  const partsTextContent = props.parts
    ?.filter((part) => part.type === "text" && part.data?.content)
    .map((part) => part.data.content)
    .join("\n\n");

  // Use parts content if available, otherwise fall back to response prop (for tool/plan verifier final response)
  const textContent =
    partsTextContent && partsTextContent.trim() !== ""
      ? partsTextContent
      : props.response && typeof props.response === "string" && props.response.trim() !== ""
        ? props.response
        : "";

  const canvasParts = props.parts?.filter((part) => part.type !== "text") || [];

  // If there's no text content and no canvas parts, don't render anything
  if ((!textContent || textContent.trim() === "") && canvasParts.length === 0) {
    return null;
  }

  return (
    <div className={styles.accordion}>
      {/* Reasoning Steps Content */}
      {userRole !== "user" && reasoningOpen && props?.debugExecutor?.length > 0 && (
        <div className={styles.reasoningContent}>
          {Array.isArray(props.debugExecutor) &&
            props.debugExecutor
              .slice()
              .reverse()
              .map((item, idx) => {
                // Show content from each step as structured step item
                if (item.content && item.type !== "tool") {
                  // Parse the step title and description
                  const content = item.content || "";
                  const lines = content.split("\n").filter((line) => line.trim());
                  const title = item.name || item.title || (lines[0] ? lines[0].substring(0, 50) : `Step ${idx + 1}`);
                  const description = item.description || (lines.length > 1 ? lines.slice(1).join(" ").substring(0, 100) : "");

                  return (
                    <div key={idx} className={styles.reasoningStepItem}>
                      <div className={styles.reasoningStepIcon}>
                        <SVGIcons icon="step-checkmark" width={16} height={16} fill="#0073CF" stroke="white" />
                      </div>
                      <div className={styles.reasoningStepContent}>
                        <div className={styles.reasoningStepTitle}>{title}</div>
                        {description && <div className={styles.reasoningStepDescription}>{description}</div>}
                      </div>
                    </div>
                  );
                }
                return null;
              })}
        </div>
      )}

      {/* Message Content Card */}
      <div className={styles["accordion-header"]}>
        {(() => {
          if (!props?.show_canvas) {
            if (!textContent || textContent.trim() === "") {
              return null;
            }
            return (
              <div className={`${styles.messageBubble} ${styles.textOnlyBubble}`}>
                <ReactMarkdown
                  rehypePlugins={[remarkGfm]}
                  components={{
                    code({ node, inline, className, children, ...props }) {
                      const match = /language-(\w+)/.exec(className || "");
                      return !inline && match ? (
                        <SyntaxHighlighter style={syntaxTheme} language={match[1]} PreTag="div" {...props}>
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
            if ((!textContent || textContent.trim() === "") && canvasParts.length === 0) {
              return null;
            }
            return (
              <div className={`${styles.messageBubble} ${styles.showCanvasBtn}`}>
                {textContent && textContent.trim() !== "" && (
                  <ReactMarkdown
                    rehypePlugins={[remarkGfm]}
                    components={{
                      code({ node, inline, className, children, ...props }) {
                        const match = /language-(\w+)/.exec(className || "");
                        return !inline && match ? (
                          <SyntaxHighlighter style={syntaxTheme} language={match[1]} PreTag="div" {...props}>
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
                {/* View Details Button - Inside message bubble */}
                {canvasParts.length > 0 && (
                  <div className={styles.viewDetailsBubble} tabIndex={0} role="button" aria-label="View details" onClick={handleCanvasOpen}>
                    <SVGIcons icon="view-details-eye" width={18} height={18} color="currentColor" stroke="currentColor" />
                    <span className={styles.viewDetailsText}>View details</span>
                    <SVGIcons icon="chevron-right" width={16} height={16} color="currentColor" stroke="currentColor" />
                  </div>
                )}
              </div>
            );
          }
        })()}
      </div>

      {/* Execution Steps Button */}
      {userRole !== "user" && (
        <div className={styles.accordionButton} onClick={toggleAccordion}>
          <div className={styles.accordionButtonLeft}>
            <SVGIcons icon="execution-steps" width={20} height={20} color="currentColor" stroke="currentColor" />
            <span>Execution Steps ({
              // Count only the steps that will actually be rendered (exclude tool response items)
              Array.isArray(props?.debugExecutor)
                ? props.debugExecutor.filter(item => item.role || item.tool_calls?.length > 0 || (item.content && item.type !== "tool")).length
                : 0
            })</span>
          </div>
          <SVGIcons
            icon="chevron-down-sm"
            width={16}
            height={16}
            color="currentColor"
            stroke="currentColor"
            style={{ transform: isOpen ? "rotate(180deg)" : "rotate(0deg)", transition: "transform 0.2s ease" }}
          />
        </div>
      )}

      {/* Execution Steps Content */}
      {userRole !== "user" && (
        <div className={`${styles["accordion-content"]} ${isOpen ? styles.open : ""}`}>
          <>
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
                                    <span className={DebugStepsCss.stepCount}>{stepCounter}</span> {props?.agentType === META_AGENT || props?.agentType === PLANNER_META_AGENT ? "Agent Calls" : "Tool Calls"}
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
                                            <SyntaxHighlighter style={syntaxTheme} language={match[1]} PreTag="div" {...props}>
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
