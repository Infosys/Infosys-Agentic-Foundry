import styles from "../../components/commonComponents/Accordions/AccordionPlan.module.css";
import React, { useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import "../../css_modules/MsgBox.css";
import dropdownCircle from "../../Assets/dropdown-circle.png";
import remarkGfm from "remark-gfm";
import SVGIcons from "../../../src/Icons/SVGIcons";

const ToolCallFinalResponse = (props) => {
  const [isOpen, setIsOpen] = useState(false);

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
      <div className={styles.botChatSection}>
        <div className={styles.accordionContainerToolCall}>
          <div
            className={
              styles["accordion-content"] + " " + styles.OpacityVisible
            }
          >
            <div className="MessagingboxToolcall">
              <div className="table-container">
                <div className={styles.planContainer}>
                  <span className={styles.toolCallCss}>
                    <p className={styles.toolcalltextCss}>
                      <h3>{"Tool Calls"}</h3>
                    </p>
                  </span>
                  <div className={styles.toolNameCss}>
                    <span>
                      <h5>{"Tool Name :"}</h5>
                    </span>
                    <span className={styles.toolNameTextCss}>
                      <ReactMarkdown rehypePlugins={[remarkGfm]}>
                        {props?.messageData?.toolcallData &&
                        props?.messageData?.toolcallData?.additional_details[0]
                          ? props?.messageData?.toolcallData
                              ?.additional_details[0]?.additional_kwargs
                              ?.tool_calls[0]?.function?.name
                          : ""}
                      </ReactMarkdown>
                    </span>
                  </div>
                  <div>
                    {props.isEditable ? (
                      <>
                        <p className={styles.toolCallCss}>
                          <h5>{"Arguments :"}</h5>
                        </p>
                        {/* <span><h5>{"Arguments:"}</h5></span> */}
                        {props?.messageData?.toolcallData &&
                        props?.messageData?.toolcallData
                          ?.additional_details[0] &&
                        props?.messageData?.toolcallData?.additional_details[0]
                          ?.additional_kwargs?.tool_calls[0]?.function
                          ?.arguments === "{}" ? (
                          <>
                            <span>{"No arguments to show"}</span>
                          </>
                        ) : (
                          <>
                            <div>
                              {Object.entries(props?.parsedValues).map(
                                ([key, val]) => (
                                  <>
                                    {typeof val === "object" ||
                                    val?.length > 10 ? (
                                      <>
                                        <div className="argumentValueTextArea">
                                          <span className={styles.toolDisplay}>
                                            <h5>{key}:</h5>
                                          </span>
                                          <textarea
                                            className="argumentValueTextArea"
                                            value={
                                              typeof val === "object"
                                                ? JSON.stringify(val)
                                                : val
                                            }
                                            onChange={(e) =>
                                              props.handleEditChange(
                                                key,
                                                e.target.value,
                                                val
                                              )
                                            }
                                          />
                                        </div>
                                      </>
                                    ) : (
                                      <>
                                        <div
                                          className={styles.argumentinputCss}
                                        >
                                          <span className={styles.toolDisplay}>
                                            <h5>{key}:</h5>
                                          </span>
                                          <input
                                            className={styles.toolNameTextCss}
                                            type="text"
                                            value={
                                              typeof val === "object"
                                                ? JSON.stringify(val)
                                                : val
                                            }
                                            onChange={(e) =>
                                              props.handleEditChange(
                                                key,
                                                e.target.value,
                                                val
                                              )
                                            }
                                            autoFocus
                                          />
                                        </div>
                                      </>
                                    )}
                                  </>
                                )
                              )}
                            </div>
                          </>
                        )}
                      </>
                    ) : (
                      <>
                        {/* <span><strong>{"Arguments :"}</strong></span> */}
                        <p className={styles.toolCallCss}>
                          <h5>{"Arguments :"}</h5>
                        </p>
                        {props?.messageData?.toolcallData &&
                        props?.messageData?.toolcallData
                          ?.additional_details[0] &&
                        props?.messageData?.toolcallData?.additional_details[0]
                          ?.additional_kwargs?.tool_calls[0]?.function
                          ?.arguments === "{}" ? (
                          <>
                            <span>{"No arguments to show"}</span>
                          </>
                        ) : (
                          <>
                            {/* <ReactMarkdown rehypePlugins={[remarkGfm]}>

             {props?.messageData?.toolcallData?.additional_details[0]?.additional_kwargs?.tool_calls[0]?.function?.arguments?.replace(/^{/,'').replace(/}$/,'').replace(/"/g,'').replace(/\\/,'')}
             </ReactMarkdown> */}
                            {props?.messageData?.toolcallData
                              ?.additional_details?.[0] &&
                              Object.entries(
                                JSON.parse(
                                  props?.messageData?.toolcallData
                                    ?.additional_details?.[0]?.additional_kwargs
                                    ?.tool_calls?.[0]?.function?.arguments ||
                                    "{}"
                                )
                              ).map(([key, value]) => (
                                <div key={key} className={styles.toolNameCss}>
                                  <h5>{key}:</h5>{" "}
                                  <p className={styles.toolNameTextCss}>
                                    {typeof value === "object"
                                      ? JSON.stringify(value)
                                      : String(value)}
                                  </p>
                                </div>
                              ))}
                          </>
                        )}
                      </>
                    )}
                  </div>
                </div>
                {props?.isEditable &&
                  (!props?.generating || !props?.fetching) &&
                  props?.sendIconShow && (
                    <>
                      <button>
                        <div
                          className={styles.accordionButtonSend}
                          onClick={(e) =>
                            props?.sendArgumentEditData(props?.messageData)
                          }
                          title={"send"}
                        >
                          <button className={styles.submitButtonCss}>
                            <p className={styles?.submitChanges}>{"Update"}</p>
                          </button>
                        </div>
                      </button>
                    </>
                  )}
                {/* {props?.isEditable && !props?.fetching &&(
                <>
                 <div className={styles.accordionButtonSend}  onClick={(e)=>props.sendArgumentEditData(props?.messageData)} title={"send"}>
                      <span
            className={
              styles?.arrowOpen
                
            } 
          >
                                  <SVGIcons
                                    icon="ionic-ios-send"
                                    fill="#007CC3"
                                    width={48}
                                    height={15}
                                  />
          </span>
        </div>
                </>
            )} */}
              </div>
            </div>
          </div>
          
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
      </div>
      {isOpen && (
        <div
          className={`${styles["accordion-content"]} ${
            isOpen ? styles.open : ""
          }`}
        >
          <pre
            className={styles["accordion-text"]}
            dangerouslySetInnerHTML={{
              __html: props?.content
                .replace(/\\n/g, "<br>")
                .replace(/\\"/g, '"'),
            }}
          ></pre>
        </div>
      )}
    </>
  );
};

export default ToolCallFinalResponse;
