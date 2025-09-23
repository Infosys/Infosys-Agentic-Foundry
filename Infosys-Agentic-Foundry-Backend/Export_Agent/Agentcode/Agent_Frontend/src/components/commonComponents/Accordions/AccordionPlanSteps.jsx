import { useState } from "react";
import ReactMarkdown from "react-markdown";
import DOMPurify from "dompurify";
import remarkGfm from "remark-gfm";
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { oneDark } from 'react-syntax-highlighter/dist/esm/styles/prism';
import styles from "./AccordionPlan.module.css";
import DebugStepsCss from "../../../css_modules/DebugSteps.module.css";

const AccordionPlanSteps = (props) => {
  const [isOpen, setIsOpen] = useState(false);

  const toggleAccordion = () => {
    setIsOpen(!isOpen);
  };
  const handleCanvasOpen = () => {
    // Check if Canvas functions are available from props
    if (props.detectCanvasContent && props.openCanvas && props.response) {
      const canvasContent = props.detectCanvasContent(props.response);
      if (canvasContent) {
        props.openCanvas(canvasContent.content, canvasContent.title, canvasContent.type);
      }
    }
  };

  // const sanitizedContent = () =>{
  //   return DOMPurify.sanitize(
  //   props?.response
  //     ?.replace(/\\n/g, "<br>")
  //     ?.replace(/\\"/g, '"'));
  // };

  // Check if the content is canvas-worthy (contains code or other canvas content)
  const isCanvasWorthy = () => {
    if (props.detectCanvasContent && props.response) {
      const canvasContent = props.detectCanvasContent(props.response);
      return !!canvasContent;
    }
    return false;
  };

  return (
    <div className={styles.accordion}>      
      <div className={styles["accordion-header"]}>
        {isCanvasWorthy() ? (
          <div 
            className={styles.messageBubble}
            onClick={handleCanvasOpen}
            style={{ cursor: 'pointer' }}
          >
            <span>View result on Canvas</span>
          </div>
        ) : (
          <div className={styles.messageBubble}>
            {/* <span dangerouslySetInnerHTML={{ __html: sanitizedContent() }} /> */}

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
              {props?.response?.replace(/\\n/g, '\n').replace(/\\"/g, '"')}
            </ReactMarkdown>
          </div>
        )}
        <div className={styles.accordionButton} onClick={toggleAccordion}>
          <span>DEBUG</span>
          <span
            className={
              isOpen ? styles.arrow + " " + styles["open"] : styles.arrow
            }
          >
            <svg width="20" height="20" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg">
              <path d="M5 7 L10 13 L15 7 Z" fill="white" />
            </svg>
          </span>
        </div>
      </div>
      <div className={`${styles["accordion-content"]} ${isOpen ? styles.open : ''}`}>
        <>{/* Debug Steps UI Start */}
        {isOpen && props?.debugExecutor && (
          <>
            <div className={DebugStepsCss.debugStepsWrapper}>
              <div className={styles.debugExecutionsHeader}>Execution Steps</div>
              <div className={styles.debugExecutionsteps}>
                {Array.isArray(props.debugExecutor) &&
                  (() => {
                    let stepCounter = 1;
                    return props.debugExecutor.slice().reverse().map((item, idx, arr) => {
                      let stepElement = null;

                      // User Query Stage
                      if (item.role) {
                        stepElement = (
                          <div key={idx} className={DebugStepsCss.eachSteps+" "+DebugStepsCss.userQueryStage}>
                            <div className={DebugStepsCss.stepHeader}><span className={DebugStepsCss.stepCount}>{stepCounter}</span> User Query</div>
                            <div className={DebugStepsCss.stepsContent}>{item.content}</div>
                          </div>
                        );
                      }
                      // Tool Calls Stage
                      else if (item.tool_calls && item.tool_calls.length > 0) {
                        stepElement = (
                          <div key={idx} className={DebugStepsCss.eachSteps+" "+DebugStepsCss.toolsCallStage}>
                            <div className={DebugStepsCss.stepHeader}><span className={DebugStepsCss.stepCount}>{stepCounter}</span> Tool Calls</div>
                            <div className={DebugStepsCss.stepsContent}>
                              {item.tool_calls.map((call, tIdx) => {
                                // Find the tool response in the next items (type: 'tool', tool_call_id matches)
                                const toolResp = arr.find(
                                  d => d.type === 'tool' && d.tool_call_id === call.id
                                );
                                return (
                                  <div key={call.id} className={DebugStepsCss.stepsToolBlockWrapper}>
                                    <div className={DebugStepsCss.toolName+" "+DebugStepsCss.toolCallRow}>
                                      <span className={DebugStepsCss.toolTitle}>Function: </span>
                                      <span>{call.name}</span>
                                    </div>
                                    <div className={DebugStepsCss.toolCallRow}>
                                      <span className={DebugStepsCss.toolTitle}>Args: </span> 
                                      <span>{Object.entries(call.args).map(([k, v]) => `${k}: ${v}`).join(', ')}</span>
                                    </div>
                                    <div className={DebugStepsCss.toolCallRow}>
                                      <span className={DebugStepsCss.toolTitle}>Response  </span>
                                      <span className={DebugStepsCss.toolResponse}>
                                        {toolResp?.content ? (
                                          <>{toolResp.content}</>
                                        ) : (
                                          <span style={{ color: '#b6beca' }}>[No response found]</span>
                                        )}
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
                      else if (item.content && item.type !== 'tool') {
                        stepElement = (
                          <div key={idx} className={DebugStepsCss.eachSteps+" "+DebugStepsCss.AiHumanStage}>
                            <div className={DebugStepsCss.stepHeader}>
                              <span className={DebugStepsCss.stepCount}>{stepCounter}</span> Message</div>
                            <div className={DebugStepsCss.stepsContent}>
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
                  })()
                }
              </div>
            </div>
          </>
        )}
        {/* Debug Steps UI End */}
        </>
      </div>
    </div>
  );
};

export default AccordionPlanSteps;