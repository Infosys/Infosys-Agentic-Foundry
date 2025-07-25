import React, { useEffect, useState } from "react";
import DOMPurify from "dompurify";
import SVGIcons from "../../Icons/SVGIcons";
import { BOT, CUSTOM_TEMPLATE, MULTI_AGENT, PLANNER_EXECUTOR_AGENT, REACT_CRITIC_AGENT, USER } from "../../constant";
import LoadingChat from "./LoadingChat";
import brandlogotwo from "../../Assets/Agentic-Foundry-Logo-Blue-2.png";
import {
  REACT_AGENT,
  like,
  dislike,
  regenerate,
  sessionId,
  feedBackMessage,
  META_AGENT,
  APIs,
  PLANNER_META_AGENT,
} from "../../constant";
import { fetchFeedback } from "../../services/chatService";
import ReactMarkdown from "react-markdown";
import "../../css_modules/MsgBox.css";
import refresh from "../../Assets/refresh.png";
import thumbsDown from "../../Assets/thumbsDown.png";
import thumbsUp from "../../Assets/thumbsUp.png";
import robot from "../../Assets/robot.png";
import AccordionPlanSteps from "../commonComponents/Accordions/AccordionPlanSteps";
import parse from "html-react-parser";
import remarkGfm from "remark-gfm";
import ToolCallFinalResponse from "./ToolCallFinalResponse";
import useFetch from "../../Hooks/useAxios";
import Toggle from "../commonComponents/Toggle";
import {
  resetChat,
  getChatQueryResponse,
  getChatHistory,
  fetchOldChats,
  fetchNewChats,
} from "../../services/chatService";

const MsgBox = (props) => {
  const [feedBackText, setFeedBackText] = useState("");
  const [close, setClose] = useState(false);
  const [loadingText, setLoadingText] = useState("");
  
  // Typewriter effect states
  const [displayedText, setDisplayedText] = useState("");
  const [isTyping, setIsTyping] = useState(false);
  const [showCursor, setShowCursor] = useState(true);
  const [currentSentenceIndex, setCurrentSentenceIndex] = useState(0);
  const { fetchData, postData } = useFetch();
  const {
    styles,
    messageData,
    generating,
    agentType,
    setFeedback,
    feedBack,
    agentSelectValue,
    model,
    setMessageData,
    fetching,
    setFetching,
    setShowToast,
    sendHumanInLoop,
    showInput,
    setShowInput,
    isShowIsHuman,
    isHuman,
    setIsHuman,
    lastResponse,
    setIsTool,
    isTool,
    selectedOption,
    toolInterrupt,
    handleToolInterrupt,
    handleHumanInLoop,
    setGenerating,
    oldSessionId,
    session,
    messageDisable,
    isEditable,
    setIsEditable,
  } = props;
  const [parsedValues, setParsedValues] = useState({});
  const rawData =
    messageData?.toolcallData &&
    messageData?.toolcallData?.additional_details[0]
      ? messageData?.toolcallData?.additional_details[0]?.additional_kwargs
          ?.tool_calls[0]?.function?.arguments
      : "";
  const [newData, setNewData] = useState(false);
  const [generateFeedBackButton, setgenerateFeedBackButton] = useState(false);
  const [showgenerateButton, setGenerateButton] = useState(false);

  const [continueButton, setContinueButton] = useState(true);
  const [sendIconShow, setSendIconShow] = useState(false);
  const handleFeedBack = (value, sessionId) => {
    setGenerateButton(true);
    setFeedback(value);
    value === "no" ? setLoadingText("Loading") : setLoadingText("Generating");
    if (value !== dislike) {
      sendFeedback(value, "", sessionId);
    } else {
      setClose(true);
    }
    setGenerateButton(false);
  };
  const continueOnclick = () => {
    setContinueButton(false);
  };
  useEffect(() => {
    setContinueButton(true);
  }, [messageData]);

  // Typewriter effect for placeholder text
  const sentences = [
    "Build Reliable Enterprise Agents.",
    "Pro-code development with reusable templates.",
    "Robust tool integration for complex workflows.",
    "Deep observability and monitoring capabilities.",
    "From concept to production in minutes.",
    "Simple bots to multi-agent systems made easy."
  ];
  
  useEffect(() => {
    // Check if placeholder should be shown
    const shouldShowPlaceholder = (((!props?.allOptionsSelected && props?.oldChats.length===0) ||(props?.allOptionsSelected && props?.oldChats.length===0))&& messageData.length ===0);
    
    if (shouldShowPlaceholder) {
      setIsTyping(true);
      setDisplayedText("");
      setShowCursor(true);
      setCurrentSentenceIndex(0);
      
      const typeSentence = (sentenceIndex) => {
        if (sentenceIndex >= sentences.length) {
          // Reset to first sentence and continue the cycle
          sentenceIndex = 0;
          setCurrentSentenceIndex(0);
        }
        
        const currentSentence = sentences[sentenceIndex];
        let charIndex = 0;
        
        // Clear previous text
        setDisplayedText("");
        
        const typeChar = () => {
          if (charIndex < currentSentence.length) {
            setDisplayedText(currentSentence.slice(0, charIndex + 1));
            charIndex++;
            
            // More consistent typing speed for smoother effect
            const speed = currentSentence[charIndex - 1] === ' ' ? 120 : 
                         currentSentence[charIndex - 1] === '.' ? 200 :
                         75; // Consistent speed with slight variations
            setTimeout(typeChar, speed);
          } else {
            // Sentence completed, wait before starting next sentence
            setTimeout(() => {
              setCurrentSentenceIndex(sentenceIndex + 1);
              typeSentence(sentenceIndex + 1);
            }, 2500); // 2.5 second pause between sentences
          }
        };
        
        // Start typing the current sentence
        setTimeout(typeChar, 500); // Initial delay before typing starts
      };
      
      // Start the typewriter effect
      typeSentence(0);
      
    } else {
      // Reset states when placeholder is not shown
      setDisplayedText("");
      setIsTyping(false);
      setShowCursor(false);
      setCurrentSentenceIndex(0);
    }
  }, [props?.allOptionsSelected, props?.oldChats?.length, messageData?.length]);

  const onMsgEdit = (data) => {
    const jsonString =
      data?.toolcallData && data?.toolcallData?.additional_details[0]
        ? data?.toolcallData?.additional_details[0]?.additional_kwargs
            ?.tool_calls[0]?.function?.arguments
        : "";
    const obj =
      typeof jsonString !== "object" ? JSON.parse(jsonString) : jsonString;
    setParsedValues(obj);
    props.setLikeIcon(true);
    setIsEditable(true);
    setSendIconShow(true);
  };
  const handlePlanFeedBack = async (feedBack, userText) => {
    setClose(feedBack === "no" ? true : false);
    setFeedback(feedBack);
    setFetching(true);
    feedBack === "no"
      ? setLoadingText("Loading")
      : setLoadingText("Generating");
    const response = await sendHumanInLoop(feedBack, feedBackText, userText);
    if (response && feedBack === "no") {
      setShowInput(true);
    }
    setFetching(false);
  };

  const handlePlanDislikeFeedBack = async (userText) => {
    setFetching(true);
    setFeedback(feedBack);
    setShowInput(false);
    setLoadingText("Regenerating");
    await sendHumanInLoop(feedBack, feedBackText, userText);
    setFetching(false);
    setFeedBackText("");
    setFeedback("");
  };

  const converToChatFormat = (chatHistory) => {
    let chats = [];
    chatHistory?.executor_messages?.map((item, index) => {
      chats?.push({ type: USER, message: item?.user_query });
      chats?.push({
        type: BOT,
        message: item?.final_response,
        toolcallData: item,
        steps: JSON.stringify(item?.agent_steps, null, "\t"),
        ...(index === chatHistory?.executor_messages?.length - 1 &&
          item?.final_response === "" && { plan: chatHistory?.plan }),
      });
    });
    return chats;
  };

  const sendFeedback = async (feedBack, user_feedback = "", session_Id) => {
    setgenerateFeedBackButton(true);
    setFetching(true);
    feedBack === "no"
      ? setLoadingText("Loading")
      : setLoadingText("Generating");
    const data = {
      agentic_application_id: agentSelectValue,
      query: lastResponse.query,
      session_id: oldSessionId !== "" ? oldSessionId : session,
      model_name: model,
      reset_conversation: false,
      prev_response: lastResponse || {},
      feedback: user_feedback,
    };
    const response = await fetchFeedback(data, feedBack);
    if (feedBack !== like) setMessageData(converToChatFormat(response) || []);

    if (feedBack === like) {
      setShowToast(true);
      setTimeout(() => {
        setShowToast(false);
      }, 5000);
    }
    setFetching(false);
    setgenerateFeedBackButton(false);
  };

  const handleChange = (e) => {
    setFeedBackText(e?.target?.value);
  };
  const handleEditChange = (key, newValue, val) => {
    if (newValue !== parsedValues) {
      setNewData(true);
    } else {
      setNewData(false);
    }
    setParsedValues((prev) => ({
      ...prev,
      [key]: newValue,
    }));
  };
  function convertStringifiedObjects(data) {
    const newData = {};

    for (const [key, value] of Object.entries(data)) {
      // if (typeof value !=='number'&& value?.includes("{")) {
      if (typeof value !== "number") {
        try {
          const parsed = JSON.parse(value);
          if (typeof parsed === "object" && parsed !== null) {
            newData[key] = parsed;
          } else {
            newData[key] = value;
          }
        } catch (e) {
          newData[key] = value;
        }
      } else {
        newData[key] = value;
      }
    }
    return newData;
  }

  const sendArgumentEditData = async (data) => {
    let argData = convertStringifiedObjects(parsedValues);
    setFetching(true);
    // setIsEditable(false)
    setSendIconShow(false);
    setGenerateButton(true);
    let feedBack;
    if (!newData) {
      feedBack = "yes";
    } else {
      feedBack = JSON.stringify(argData);
    }
    let response;
    let url;
    const payload = {
      agentic_application_id: agentSelectValue,
      query: data?.userText ? data?.userText : "",
      session_id: oldSessionId !== "" ? oldSessionId : session,
      model_name: model,
      reset_conversation: false,
      ...(toolInterrupt ? { interrupt_flag: true } : { interrupt_flag: false }),
      tool_feedback: JSON.stringify(argData),
      feedback: JSON.stringify(argData),
    };

    if (isHuman) {
      url =
        agentType === CUSTOM_TEMPLATE
          ? APIs.CUSTOME_TEMPLATE_QUERY
          :agentType === PLANNER_EXECUTOR_AGENT
          ? APIs.PLANNER_EXECUTOR_AGENT_QUERY
          : APIs.PLANNER;
      response = await getChatQueryResponse(payload, url);
    } else {
      url =
        agentType === META_AGENT
          ? APIs.META_AGENT_QUERY
          : agentType === PLANNER_META_AGENT
          ? APIs.PLANNER_META_AGENT_QUERY
          : APIs.REACT_MULTI_AGENT_QUERY;
      response = await getChatQueryResponse(payload, url);
    }
    setFetching(false);
    setGenerateButton(false);
    setMessageData(converToChatFormat(response) || []);
    props.setLikeIcon(false);
  };
  const submitFeedbackYes = async (data) => {
    setIsEditable(false);
    setLoadingText("Generating");
    setGenerateButton(true);
    setFetching(true);
    let url;
    let response;
    const payload = {
      agentic_application_id: agentSelectValue,
      query: data?.userText ? data?.userText : "",
      session_id: oldSessionId !== "" ? oldSessionId : session,
      model_name: model,
      reset_conversation: false,
      ...(toolInterrupt ? { interrupt_flag: true } : { interrupt_flag: false }),
      feedback: "yes",
      tool_feedback: "yes",
    };
    if (isHuman) {
      url =
        agentType === CUSTOM_TEMPLATE
          ? APIs.CUSTOME_TEMPLATE_QUERY
          :agentType === PLANNER_EXECUTOR_AGENT
          ? APIs.PLANNER_EXECUTOR_AGENT_QUERY
          : APIs.PLANNER;
      response = await getChatQueryResponse(payload, url);
    } else {
      url =
        agentType === META_AGENT
          ? APIs.META_AGENT_QUERY
          : agentType === PLANNER_META_AGENT
          ? APIs.PLANNER_META_AGENT_QUERY
          : APIs.REACT_MULTI_AGENT_QUERY;
      response = await getChatQueryResponse(payload, url);
    }

    setMessageData(converToChatFormat(response) || []);
    setLoadingText("");
    setGenerateButton(false);
    setFetching(false);
  };
  const handleDislikeFeedBack = async () => {
    setClose(true);
    sendFeedback(dislike, feedBackText, sessionId);
    setFeedBackText("");
    setFeedback("");
  };

  const handleToggle2 = async (e) => {
    if (agentType === "multi_agent" || agentType === MULTI_AGENT) {
      handleToolInterrupt(e.target.checked);
    }
  };

  const handleToggle = (e) => {
    if (agentType === MULTI_AGENT || agentType === "multi_agent") {
      handleHumanInLoop(e.target.checked);
    } else {
      handleToolInterrupt(e.target.checked);
    }
  };

  let argunentKey;
  let argumentValue;
  useEffect(() => {
    setIsEditable(false);
  }, [messageData]);
  const [value, setValue] = useState(argunentKey);
  const [text, setText] = useState(argumentValue);
  let messagetext = messageData?.filter((item) => item.message.trim() === "");
  
  return (
    <div className={styles.msgBoxWrapper}>
       {(((!props?.allOptionsSelected && props?.oldChats.length===0) ||(props?.allOptionsSelected && props?.oldChats.length===0))&& messageData.length ===0) &&(

       <div className={styles.msgBoxPlaceHolder}>
          <img src={brandlogotwo} alt="Brandlogo" />
          <div className={styles.typewriterContainer}>
            <span className={styles.typewriterText}>
              {displayedText}
            </span>
            {showCursor && <span className={styles.cursor}></span>}
          </div>
        </div>

      )}      
      {(messageData?.length > 0 || props?.oldChats.length > 0)&&
        ((feedBack === "no" || feedBack === dislike) &&
        ((agentType === REACT_AGENT && close) ||
          agentType === MULTI_AGENT ||agentType === PLANNER_EXECUTOR_AGENT|| agentType=== REACT_CRITIC_AGENT||
          agentType === PLANNER_META_AGENT)
          ? messageData.slice(-2)
          : messageData
        )?.map((data, index) => {
          const lastIndex =
            (feedBack === "no" || feedBack === dislike) &&
            ((agentType === REACT_AGENT && close) ||
              agentType === MULTI_AGENT ||agentType === PLANNER_EXECUTOR_AGENT|| agentType=== REACT_CRITIC_AGENT||
              agentType === PLANNER_META_AGENT)
              ? messageData.slice(-2).length - 1
              : messageData.length - 1;
          return (
            <>
              <div className={styles.chatContainer} key={data.message}>
                {data.type === BOT && (
                  <div className={styles.botChats}>
                    <div className={styles.botIcon}>
                      <img src={robot} alt="Robot" />
                    </div>
                    <div className={styles.botChatSection}>
                      {data.message &&
                        agentType !== CUSTOM_TEMPLATE &&
                        agentType === PLANNER_META_AGENT &&
                        continueButton &&
                        index != lastIndex && (
                          <AccordionPlanSteps
                            response={data.message}
                            content={data.steps}
                            messageData={messageData}
                            isEditable={isEditable}
                            value={value}
                            text={text}
                            argunentKey={argunentKey}
                          />
                        )}
                      {data.message &&
                        agentType !== CUSTOM_TEMPLATE &&
                        agentType !== PLANNER_META_AGENT && (
                          <AccordionPlanSteps
                            response={data.message}
                            content={data.steps}
                            messageData={messageData}
                            isEditable={isEditable}
                            value={value}
                            text={text}
                            argunentKey={argunentKey}
                          />
                        )}
                      {data.message &&
                        agentType !== CUSTOM_TEMPLATE &&
                        agentType === PLANNER_META_AGENT &&
                        data?.plan?.length == 0 && (
                          <AccordionPlanSteps
                            response={data.message}
                            content={data.steps}
                            messageData={messageData}
                            isEditable={isEditable}
                            value={value}
                            text={text}
                            argunentKey={argunentKey}
                          />
                        )}
                      <div className={styles.accordionContainer}>
                        {index === lastIndex &&
                          data?.plan?.length > 0 &&
                          agentType !== PLANNER_META_AGENT &&
                          data?.message === "" &&
                          ((isHuman && toolInterrupt) || isHuman) &&
                          (!data?.toolcallData?.additional_details || // not present at all
                            (Array.isArray(
                              data.toolcallData.additional_details
                            ) &&
                              data.toolcallData.additional_details.length > 0 &&
                              Object.keys(
                                data.toolcallData.additional_details[0]
                                  ?.additional_kwargs || {}
                              ).length === 0)) && (
                            <>
                              <div className={styles.planContainer}>
                                <h3>Plan</h3>
                                {data?.plan?.map((data) => (
                                  <>
                                    <p className={styles.stepsContent}>{data}</p>
                                  </>
                                ))}
                              </div>

                              {!fetching && feedBack !== "no" && (
                                <div className={styles["plan-feedback"]}>
                                  <button
                                    onClick={() =>
                                      handlePlanFeedBack("yes", data?.userText)
                                    }
                                    className={styles.button}
                                  >
                                    <img src={thumbsUp} alt="Approve" />
                                  </button>

                                  <button
                                    onClick={() =>
                                      handlePlanFeedBack("no", data?.userText)
                                    }
                                    className={`${styles.button} + ${styles.dislikeButton}`}
                                  >
                                    <img src={thumbsDown} alt="Dislike" />
                                  </button>
                                </div>
                              )}

                              {showInput && (
                                <>
                                  {(agentType === REACT_AGENT ||
                                    agentType === MULTI_AGENT || 
                                    agentType === REACT_CRITIC_AGENT ||
                                    agentType === PLANNER_EXECUTOR_AGENT) &&
                                    close && (
                                      <div className={styles["cancel-btn"]}>
                                        <button
                                          onClick={() => {
                                            setClose(false);
                                            setFeedback("");
                                            setShowInput(false);
                                          }}
                                        >
                                          <SVGIcons
                                            icon="fa-xmark"
                                            fill="#3D4359"
                                          />
                                        </button>
                                      </div>
                                    )}
                                  <p className={styles.warning}>
                                    {feedBackMessage}
                                  </p>
                                  <div className={styles.feedBackInput}>
                                    <textarea
                                      type="text"
                                      placeholder="Enter your feedback:"
                                      className={styles.feedBackTextArea}
                                      value={feedBackText}
                                      onChange={handleChange}
                                      rows={4}
                                    ></textarea>
                                    <button
                                      disabled={generating}
                                      onClick={() =>
                                        handlePlanDislikeFeedBack(data?.userText)
                                      }
                                      className={styles.sendIcon}
                                    >
                                      <SVGIcons
                                        icon="ionic-ios-send"
                                        fill="#007CC3"
                                        width={28}
                                        height={28}
                                      />
                                    </button>
                                  </div>
                                </>
                              )}

                              <span className={styles.regenerateText}>
                                {fetching && <LoadingChat label={loadingText} />}
                              </span>
                            </>
                          )}
                        {index === lastIndex &&
                          data?.plan?.length > 0 &&
                          data?.message !== "" &&
                          agentType === PLANNER_META_AGENT &&
                          (!data?.toolcallData?.additional_details || // not present at all
                            (Array.isArray(
                              data.toolcallData.additional_details
                            ) &&
                              data.toolcallData.additional_details.length > 0 &&
                              Object.keys(
                                data.toolcallData.additional_details[0]
                                  ?.additional_kwargs || {}
                              ).length === 0)) && (
                            <>
                              <div className={styles.planContainer}>
                                <h3>Plan</h3>
                                {data?.plan?.map((data) => (
                                  <>
                                    <p className={styles.stepsContent}>{data}</p>
                                  </>
                                ))}
                              </div>
                              {continueButton &&
                                agentType === PLANNER_META_AGENT && (
                                  <div className={styles["plan-feedback"]}>
                                    <button
                                      onClick={() => continueOnclick()}
                                      className={styles.continueButton}
                                    >
                                      {"continue...."}
                                    </button>
                                  </div>
                                )}
                            </>
                          )}

                        {agentType !== CUSTOM_TEMPLATE &&
                          agentType === PLANNER_META_AGENT &&
                          !continueButton && (
                            <AccordionPlanSteps
                              response={data.message}
                              content={data.steps}
                              messageData={messageData}
                              isEditable={isEditable}
                              value={value}
                              text={text}
                              argunentKey={argunentKey}
                            />
                          )}

                        {agentType === CUSTOM_TEMPLATE && (
                          <>
                            <AccordionPlanSteps
                              response={data.message}
                              content={data.steps}
                              messageData={messageData}
                              isEditable={isEditable}
                              value={value}
                              text={text}
                              argunentKey={argunentKey}
                            />

                            {!fetching &&
                              index === lastIndex &&
                              agentType === CUSTOM_TEMPLATE && (
                                <div className={styles["plan-feedback"]}>
                                  <button
                                    onClick={() =>
                                      handlePlanFeedBack("yes", data?.userText)
                                    }
                                    className={styles.button}
                                  >
                                    <img src={thumbsUp} alt="Approve" />
                                  </button>

                                  <button
                                    onClick={() =>
                                      handlePlanFeedBack("no", data?.userText)
                                    }
                                    className={`${styles.button} + ${styles.dislikeButton}`}
                                  >
                                    <img src={thumbsDown} alt="Dislike" />
                                  </button>
                                </div>
                              )}

                            {showInput &&
                              index === lastIndex &&
                              agentType === CUSTOM_TEMPLATE && (
                                <div className={styles.feedBackInput}>
                                  <textarea
                                    type="text"
                                    placeholder="Enter your feedback:"
                                    className={styles.feedBackTextArea}
                                    value={feedBackText}
                                    onChange={handleChange}
                                    rows={4}
                                  ></textarea>
                                  <button
                                    disabled={generating}
                                    onClick={() =>
                                      handlePlanDislikeFeedBack(data?.userText)
                                    }
                                    className={styles.sendIcon}
                                  >
                                    <SVGIcons
                                      icon="ionic-ios-send"
                                      fill="#007CC3"
                                      width={28}
                                      height={28}
                                    />
                                  </button>
                                </div>
                              )}

                            {index === lastIndex && (
                              <span className={styles.regenerateText}>
                                {fetching && (
                                  <LoadingChat label={"Regnerating"} />
                                )}
                              </span>
                            )}
                          </>
                        )}
                        {data?.message === "" &&
                          Array.isArray(data?.toolcallData?.additional_details) &&
                          data.toolcallData.additional_details.length > 0 &&
                          Object.keys(
                            data.toolcallData.additional_details[0]
                              ?.additional_kwargs
                          ).length > 0 && (
                            <>
                              <ToolCallFinalResponse
                                response={data.message}
                                content={data.steps}
                                messageData={data}
                                isEditable={isEditable}
                                value={value}
                                text={text}
                                argunentKey={argunentKey}
                                parsedValues={parsedValues}
                                setParsedValues={setParsedValues}
                                rawData={rawData}
                                handleEditChange={handleEditChange}
                                sendArgumentEditData={sendArgumentEditData}
                                fetching={fetching}
                                sendIconShow={sendIconShow}
                                generating={generating}
                              />
                            </>
                          )}
                        {/* {data.message==="" &&isEditable && (!generating || !fetching) && sendIconShow &&(
                  <>
                  <div className={styles.accordionButtonSend}  onClick={(e)=>sendArgumentEditData(props?.messageData)} title={"send"}>
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
                        {data?.message === "" &&
                          !isHuman &&
                          toolInterrupt &&
                          !(
                            "additional_details" in (data?.toolcallData || {})
                          ) && (
                            <div className={styles.botChatSection}>
                              <div className={styles.accordion}>
                                <div className={styles["accordion-header"]}>
                                  <div className="Messagingbox">
                                    <div className="table-container">
                                      <span>{"Something went wrong"}</span>
                                    </div>
                                  </div>
                                </div>
                              </div>
                            </div>
                          )}
                      </div>

                      {feedBack === dislike &&
                        index === lastIndex &&
                        (agentType === REACT_AGENT ||
                          agentType === "react_agent" ||
                          agentType === MULTI_AGENT ||agentType === PLANNER_EXECUTOR_AGENT|| agentType=== REACT_CRITIC_AGENT||
                          agentType === "multi_agent" ||
                          agentType === PLANNER_META_AGENT) && (                        <div className={styles.feedBackSection}>
                            {((agentType === REACT_AGENT ||
                              agentType === MULTI_AGENT ||agentType === PLANNER_EXECUTOR_AGENT|| agentType=== REACT_CRITIC_AGENT) &&
                              close) ||
                              (agentType === PLANNER_META_AGENT &&
                                continueButton &&
                                feedBack === dislike &&
                                close) ? (
                                  <div className={styles["cancel-btn"]}>
                                    <button
                                      onClick={() => {
                                        setClose(false);
                                        setFeedback("");
                                      }}
                                    >
                                      <SVGIcons icon="fa-xmark" fill="#3D4359" />
                                    </button>
                                  </div>
                                ) : null}
                            <p className={styles.warning}>{feedBackMessage}</p>
                            <div className={styles.feedBackInput}>
                              <textarea
                                type="text"
                                placeholder="Enter your feedback:"
                                className={styles.feedBackTextArea}
                                value={feedBackText}
                                onChange={handleChange}
                                rows={4}
                              ></textarea>
                              <button
                                disabled={generating}
                                onClick={handleDislikeFeedBack}
                                className={styles.sendIcon}
                              >
                                <SVGIcons
                                  icon="ionic-ios-send"
                                  fill="#007CC3"
                                  width={28}
                                  height={28}
                                />
                              </button>
                            </div>
                          </div>
                        )}
                      {index === lastIndex && (
                        <span className={styles.regenerateText}>
                          {fetching && generateFeedBackButton && (
                            <LoadingChat label={"Generating"} />
                          )}
                        </span>
                      )}

                      {index === lastIndex &&
                        (agentType === REACT_AGENT ||
                          agentType === MULTI_AGENT || agentType === PLANNER_EXECUTOR_AGENT|| agentType=== REACT_CRITIC_AGENT||
                          (agentType === PLANNER_META_AGENT && continueButton)) &&
                        feedBack !== dislike && (
                          <div className={styles["feedback-section"]}>
                            {!fetching && (
                              <div className={styles["button-container"]}>
                                {loadingText ? (
                                  <>
                                    <span className={styles.regenerateText}>
                                      {fetching && (
                                        <LoadingChat label={"Generating"} />
                                      )}
                                    </span>
                                  </>
                                ) : (
                                  <></>
                                )}

                                {data?.message === "" &&
                                !props?.likeIcon &&
                                Array.isArray(
                                  data?.toolcallData?.additional_details
                                ) &&
                                data.toolcallData.additional_details.length > 0 &&
                                Object.keys(
                                  data.toolcallData.additional_details[0]
                                    ?.additional_kwargs
                                ).length > 0 ? (
                                  <>
                                    <button
                                      onClick={() => submitFeedbackYes(data)}
                                      className={styles.button}
                                    >
                                      <img src={thumbsUp} alt="Approve" />
                                    </button>
                                    {Array.isArray(
                                      props?.messageData?.toolcallData
                                        ?.additional_details
                                    ) &&
                                    props.messageData.toolcallData
                                      .additional_details.length > 0 &&
                                    Array.isArray(
                                      props.messageData.toolcallData
                                        .additional_details[0]?.additional_kwargs
                                        ?.tool_calls
                                    ) &&
                                    props.messageData.toolcallData
                                      .additional_details[0].additional_kwargs
                                      .tool_calls.length > 0 &&
                                    props.messageData.toolcallData
                                      .additional_details[0].additional_kwargs
                                      .tool_calls[0]?.function?.arguments ===
                                      "{}" ? (
                                      <></>
                                    ) : (
                                      <></>
                                    )}

                                    <button
                                      className={styles.editBtn}
                                      onClick={() => onMsgEdit(data)}
                                    >
                                      <SVGIcons
                                        icon="fa-solid fa-pen"
                                        width={16}
                                        height={16}
                                        fill={"  #007ac0"}
                                      />
                                    </button>
                                  </>
                                ) : (
                                  <>
                                    {(data?.message === "" && props?.likeIcon) ||
                                    (data?.message === "" &&
                                      (data?.plan || !data?.plan)) ||
                                    (data?.message === "" &&
                                      isHuman &&
                                      Array.isArray(
                                        data?.toolcallData?.additional_details
                                      ) &&
                                      data.toolcallData.additional_details
                                        .length > 0 &&
                                      Object.keys(
                                        data.toolcallData.additional_details[0]
                                          ?.additional_kwargs || {}
                                      ).length === 0) ? (
                                      <></>
                                    ) : (
                                      <>
                                        {agentType !== PLANNER_META_AGENT && (
                                          <>
                                            <button
                                              onClick={() => handleFeedBack(like)}
                                              className={styles.button}
                                            >
                                              <img src={thumbsUp} alt="Approve" />
                                            </button>
                                            <button
                                              onClick={() =>
                                                handleFeedBack(dislike)
                                              }
                                              className={`${styles.button} + ${styles.dislikeButton}`}
                                            >
                                              <img
                                                src={thumbsDown}
                                                alt="Dislike"
                                              />
                                            </button>
                                            <button
                                              onClick={() =>
                                                handleFeedBack(regenerate)
                                              }
                                              className={styles.button}
                                            >
                                              <img
                                                src={refresh}
                                                alt="Regenerate"
                                              />
                                            </button>
                                          </>
                                        )}
                                      </>
                                    )}
                                  </>
                                )}

                                {/* </>} */}
                              </div>
                            )}
                            {showgenerateButton ? (
                              <>
                                <span className={styles.regenerateText}>
                                  <LoadingChat label={"Generating"} />
                                </span>
                              </>
                            ) : (
                              <></>
                            )}
                          </div>
                        )}
                    </div>
                  </div>
                )}
                {data.type === USER && (
                  <>
                    <div className={styles.userChat}>
                      {/* Sanitize the message (with newlines already converted to <br />), 
                      then parse the resulting safe HTML string into React elements. */}
                      {parse(
                        DOMPurify.sanitize(
                          (data?.message || "").replace(/\n/g, "<br />")
                        )
                      )}
                    </div>
                    <div className={"userIcon"}>
                      <SVGIcons icon="person-circle" fill="000000" />
                    </div>
                  </>
                )}
              </div>
            </>
          );
        }) 

      }
      {generating && (
        <div className={styles.loadingChat}>
          <LoadingChat />
        </div>
      )}
    </div>
  );
};

export default MsgBox;
