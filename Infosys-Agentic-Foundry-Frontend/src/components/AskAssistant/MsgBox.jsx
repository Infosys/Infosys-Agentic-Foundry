import { useEffect, useState, useId } from "react";
import PlaceholderScreen from "./PlaceholderScreen";
import DOMPurify from "dompurify";
import SVGIcons from "../../Icons/SVGIcons";
import DebugStepsPanel from "./DebugStepsPanel.jsx";
import { BOT, CUSTOM_TEMPLATE, HYBRID_AGENT, MULTI_AGENT, PLANNER_EXECUTOR_AGENT, REACT_CRITIC_AGENT, USER } from "../../constant";
import LoadingChat from "./LoadingChat";
import { REACT_AGENT, like, dislike, regenerate, sessionId, feedBackMessage, APIs, PLANNER_META_AGENT } from "../../constant";
import AccordionPlanSteps from "../commonComponents/Accordions/AccordionPlanSteps";
import parse from "html-react-parser";
import ToolCallFinalResponse from "./ToolCallFinalResponse";
import { useChatServices } from "../../services/chatService";
import chatBubbleCss from "./ChatBubble.module.css";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faUser, faRobot, faThumbsUp, faThumbsDown, faRotateRight } from "@fortawesome/free-solid-svg-icons";
import { formatResponseTimeSeconds } from "../../utils/timeFormatter";

const JSON_INDENT = 2;
const FEEDBACK_TIMEOUT_MS = 5000;
const SLICE_LAST_TWO = -2;

const MsgBox = (props) => {
  const baseId = useId();
  const [feedBackText, setFeedBackText] = useState("");
  const [close, setClose] = useState(false);
  const [loadingText, setLoadingText] = useState("");

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
    setToastMessage,
    sendHumanInLoop,
    showInput,
    setShowInput,
    isHuman,
    lastResponse,
    toolInterrupt,
    setLikeIcon,
    oldSessionId,
    session,
    isEditable,
    setIsEditable,
    isDeletingChat,
    debugSteps,
    showLiveSteps,
    setShowLiveSteps,
    expanded,
    setExpanded,
    isCanvasEnabled,
    isContextEnabled,
    onlineEvaluatorFlag,
     plan_verifier_flag
  } = props;
  const [parsedValues, setParsedValues] = useState({});
  const { getChatQueryResponse, fetchFeedback, storeMemoryExample } = useChatServices();
  const rawData =
    messageData?.toolcallData && messageData?.toolcallData?.additional_details[0]
      ? messageData?.toolcallData?.additional_details[0]?.additional_kwargs?.tool_calls[0]?.function?.arguments
      : "";
  const [generateFeedBackButton, setgenerateFeedBackButton] = useState(false);
  const [showgenerateButton, setGenerateButton] = useState(false);

  // Track per-message feedback processing so UI (loader/toast) can be shown for that specific message
  const [processingFeedback, setProcessingFeedback] = useState({});

  const [continueButton, setContinueButton] = useState(true);
  const [sendIconShow, setSendIconShow] = useState(false);

  const handleFeedBack = (value, sessionId) => {
    setGenerateButton(true);
    setFeedback(value);
        if (value === dislike) {
          setLoadingText("Loading...");
        } else if (value === "no") {
          setLoadingText("Loading...");
        } else {
          setLoadingText("Generating");
        }
    if (value !== dislike) {
      sendFeedback(value, "", sessionId);
    } else {
      setClose(true);
    }
    setGenerateButton(false);
  };

  const handleMessageLike = async (data, idx) => {
    setProcessingFeedback((p) => ({ ...p, [idx]: true }));
    try {
      const payload = {
        agent_id: agentSelectValue,
        query: data?.userText ? data.userText : lastResponse?.query || "",
        response: typeof data?.message === "string" ? data.message : JSON.stringify(data?.message || ""),
        label: "positive",
        tool_calls:
          data?.toolcallData?.additional_details && Array.isArray(data.toolcallData.additional_details) && data.toolcallData.additional_details[0]?.additional_kwargs?.tool_calls
            ? data.toolcallData.additional_details[0].additional_kwargs.tool_calls.map((tc) => (typeof tc === "string" ? tc : JSON.stringify(tc)))
            : [],
        tool_verifier_flag: Boolean(toolInterrupt),
        response_formatting_flag: Boolean(isCanvasEnabled),
        context_flag: Boolean(isContextEnabled),
        evaluation_flag: Boolean(onlineEvaluatorFlag),
         plan_verifier_flag: Boolean(isHuman),
      };

      const resp = await storeMemoryExample(payload);
      if (resp && !isDeletingChat) {
        try {
          setToastMessage && setToastMessage(resp?.message || "Thanks for the like!");
        } catch (e) {}
        setShowToast(true);
        setTimeout(() => {
          setShowToast(false);
          try {
            setToastMessage && setToastMessage("");
          } catch (e) {}
        }, FEEDBACK_TIMEOUT_MS);
      }
    } catch (err) {
      // ignore errors to match existing patterns
    } finally {
      setProcessingFeedback((p) => {
        const copy = { ...p };
        delete copy[idx];
        return copy;
      });
    }
  };

  const handleMessageDislike = async (data, idx) => {
    setProcessingFeedback((p) => ({ ...p, [idx]: true }));
    try {
      const payload = {
        agent_id: agentSelectValue,
        query: data?.userText ? data.userText : lastResponse?.query || "",
        response: typeof data?.message === "string" ? data.message : JSON.stringify(data?.message || ""),
        label: "negative",
        tool_calls:
          data?.toolcallData?.additional_details && Array.isArray(data.toolcallData.additional_details) && data.toolcallData.additional_details[0]?.additional_kwargs?.tool_calls
            ? data.toolcallData.additional_details[0].additional_kwargs.tool_calls.map((tc) => (typeof tc === "string" ? tc : JSON.stringify(tc)))
            : [],
        tool_verifier_flag: Boolean(toolInterrupt),
        response_formatting_flag: Boolean(isCanvasEnabled),
        context_flag: Boolean(isContextEnabled),
        evaluation_flag: Boolean(onlineEvaluatorFlag),
        plan_verifier_flag: Boolean(isHuman),
      };

      const resp = await storeMemoryExample(payload);
      if (resp && !isDeletingChat) {
        try {
          setToastMessage && setToastMessage(resp?.message || "Thanks — your feedback was submitted");
        } catch (e) {}
        setShowToast(true);
        setTimeout(() => {
          setShowToast(false);
          try {
            setToastMessage && setToastMessage("");
          } catch (e) {}
        }, FEEDBACK_TIMEOUT_MS);
      }
    } catch (err) {
      // ignore errors to match existing patterns
    } finally {
      setProcessingFeedback((p) => {
        const copy = { ...p };
        delete copy[idx];
        return copy;
      });
    }
  };

  const continueOnclick = () => {
    setContinueButton(false);
  };
  useEffect(() => {
    setContinueButton(true);
  }, [messageData]);

  const onMsgEdit = (data) => {
    const jsonString =
      data?.toolcallData && data?.toolcallData?.additional_details[0] ? data?.toolcallData?.additional_details[0]?.additional_kwargs?.tool_calls[0]?.function?.arguments : "";
    const obj = typeof jsonString !== "object" ? JSON.parse(jsonString) : jsonString;
    setParsedValues(obj);
    props.setLikeIcon(true);
    setIsEditable(true);
    setSendIconShow(true);
  };
  const handlePlanFeedBack = async (feedBack, userText) => {
    setClose(feedBack === "no" ? true : false);
    setFeedback(feedBack);
    setgenerateFeedBackButton(true); // Show loading indicator
    if (feedBack === "no") {
      setShowInput(false); // Hide textarea immediately
      setLoadingText("Loading...");
    } else {
      setLoadingText("Generating");
    }
    setFetching(true);
    const response = await sendHumanInLoop(feedBack, feedBackText, userText);
    if (response && feedBack === "no") {
      setFetching(false); // Hide loading first
      setShowInput(true); // Then show textarea
      setLoadingText("");
      setgenerateFeedBackButton(false); // Hide loading indicator
    } else {
      setFetching(false);
      setgenerateFeedBackButton(false); // Hide loading indicator
    }
  };

  const handlePlanDislikeFeedBack = async (userText) => {
    setShowInput(false); // Hide textarea immediately
        setLoadingText("Generating...");
    setFetching(true);
    setgenerateFeedBackButton(true); // Show loading indicator
    try {
      const response = await sendHumanInLoop(feedBack, feedBackText, userText);
      setFeedBackText("");
      setFeedback("");
      setClose(false);
      if (response) {
        setMessageData(converToChatFormat(response) || []);
      }
    } finally {
      setFetching(false);
      setLoadingText("");
      setgenerateFeedBackButton(false); // Hide loading indicator
    }
  };

  const converToChatFormat = (chatHistory) => {
    const chats = [];

    chatHistory?.executor_messages?.map((item, index) => {
      chats?.push({
        type: USER,
        message: item?.user_query,
        debugExecutor: item?.additional_details,
      });
      chats?.push({
        type: BOT,
        message: item?.final_response,
        toolcallData: item,
        steps: JSON.stringify(item?.agent_steps, null, JSON_INDENT),
        debugExecutor: item?.additional_details,
        ...(index === chatHistory?.executor_messages?.length - 1 && item?.final_response === "" && { plan: chatHistory?.plan }),
        parts: item?.parts || [],
        show_canvas: item?.show_canvas || false,
      });
      return null;
    });

    return chats;
  };

  const sendFeedback = async (feedBack, user_feedback = "", session_Id) => {
    setgenerateFeedBackButton(true);
    setFetching(true);
    feedBack === "no" ? setLoadingText("Loading") : setLoadingText("Generating");
    const data = {
      agentic_application_id: agentSelectValue,
      query: lastResponse.query,
      session_id: oldSessionId !== "" ? oldSessionId : session,
      model_name: model,
      reset_conversation: false,
      prev_response: lastResponse || {},
      final_response_feedback: user_feedback,
      tool_verifier_flag: Boolean(toolInterrupt),
      response_formatting_flag: Boolean(isCanvasEnabled),
      context_flag: Boolean(isContextEnabled),
      evaluation_flag: Boolean(onlineEvaluatorFlag),
       plan_verifier_flag: Boolean(isHuman),
    };
    const response = await fetchFeedback(data, feedBack);
    if (feedBack !== like) {
      setMessageData(converToChatFormat(response) || []);
    }

    // Show toast for both like and dislike actions (prefer server message when available)
    if (response && !isDeletingChat && (feedBack === like || feedBack === dislike)) {
      try {
        setToastMessage && setToastMessage(response?.message || (feedBack === like ? "Thanks for the like!" : "Thanks — your feedback was submitted"));
      } catch (e) {}
      setShowToast(true);
      setTimeout(() => {
        setShowToast(false);
        try {
          setToastMessage && setToastMessage("");
        } catch (e) {}
      }, FEEDBACK_TIMEOUT_MS);
    }
    setFetching(false);
    setgenerateFeedBackButton(false);
  };

  const handleChange = (e) => {
    setFeedBackText(e?.target?.value);
  };
  const handleEditChange = (key, newValue, val) => {
    setParsedValues((prev) => ({
      ...prev,
      [key]: newValue,
    }));
  };
  function convertStringifiedObjects(data) {
    const newData = {};

    for (const [key, value] of Object.entries(data)) {
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
    const argData = convertStringifiedObjects(parsedValues);
    setFetching(true);
    setSendIconShow(false);
    setGenerateButton(true);
    const payload = {
      agentic_application_id: agentSelectValue,
      query: data?.userText ? data?.userText : "",
      session_id: oldSessionId !== "" ? oldSessionId : session,
      model_name: model,
      reset_conversation: false,
  tool_verifier_flag: Boolean(toolInterrupt),
      tool_feedback: JSON.stringify(argData),
  response_formatting_flag: Boolean(isCanvasEnabled),
  context_flag: Boolean(isContextEnabled),
      evaluation_flag: Boolean(onlineEvaluatorFlag),
   plan_verifier_flag: Boolean(isHuman),
    };

    const response = await getChatQueryResponse(payload, APIs.CHAT_INFERENCE);

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
    const payload = {
      agentic_application_id: agentSelectValue,
      query: data?.userText ? data?.userText : "",
      session_id: oldSessionId !== "" ? oldSessionId : session,
      model_name: model,
      reset_conversation: false,
  tool_verifier_flag: Boolean(toolInterrupt),
      tool_feedback: "yes",
  response_formatting_flag: Boolean(isCanvasEnabled),
  context_flag: Boolean(isContextEnabled),
      evaluation_flag: Boolean(onlineEvaluatorFlag),
   plan_verifier_flag: Boolean(isHuman),
    };

    const response = await getChatQueryResponse(payload, APIs.CHAT_INFERENCE);

    setMessageData(converToChatFormat(response) || []);
    // show toast from server response if present (feedback via 'yes' action)
    if (response && !isDeletingChat) {
      try {
        setToastMessage && setToastMessage(response?.message || "Thanks for the like!");
      } catch (e) {}
      setShowToast(true);
      setTimeout(() => {
        setShowToast(false);
        try {
          setToastMessage && setToastMessage("");
        } catch (e) {}
      }, FEEDBACK_TIMEOUT_MS);
    }
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

  useEffect(() => {
    setIsEditable(false);
  }, [messageData, setIsEditable]);

  // keep the original argument key/value placeholders — required by child components
  let argunentKey;
  let argumentValue;
  // value/text are used as read-only props passed into child accordions
  const [value] = useState(argunentKey);
  const [text] = useState(argumentValue);

  return (
    <div className={styles.messagesContainer}>
      {((!props?.allOptionsSelected && props?.oldChats.length === 0) || (props?.allOptionsSelected && props?.oldChats.length === 0)) && messageData.length === 0 && (
        <PlaceholderScreen agentType={agentType} model={model} selectedAgent={agentSelectValue} />
      )}
      {(messageData?.length > 0 || props?.oldChats.length > 0) &&
        ((feedBack === "no" || feedBack === dislike) &&
        ((agentType === REACT_AGENT && close) ||
          agentType === MULTI_AGENT ||
          agentType === PLANNER_EXECUTOR_AGENT ||
          agentType === REACT_CRITIC_AGENT ||
          agentType === PLANNER_META_AGENT ||
          agentType === HYBRID_AGENT)
          ? messageData.slice(SLICE_LAST_TWO)
          : messageData
        )?.map((data, index) => {
          const lastIndex =
            (feedBack === "no" || feedBack === dislike) &&
            ((agentType === REACT_AGENT && close) ||
              agentType === MULTI_AGENT ||
              agentType === PLANNER_EXECUTOR_AGENT ||
              agentType === REACT_CRITIC_AGENT ||
              agentType === PLANNER_META_AGENT ||
              agentType === HYBRID_AGENT)
              ? messageData.slice(SLICE_LAST_TWO).length - 1
              : messageData.length - 1;
          const messageKey = `${baseId}-message-${index}`;
          return (
            <div className={`${chatBubbleCss.container} ${data.type === BOT ? chatBubbleCss.botMessage : chatBubbleCss.userMessage}`} key={messageKey}>
              {data.type === BOT && (
                <>
                  <div className={chatBubbleCss.avatarContainer}>
                    <div className={`${chatBubbleCss.avatar} ${chatBubbleCss.botAvatar}`}>
                      <span className={chatBubbleCss.agentIcon}>
                        <FontAwesomeIcon icon={faRobot} />
                      </span>
                    </div>
                  </div>
                  <div className={chatBubbleCss.messageWrapper}>
                    {" "}
                    {data.message && agentType !== CUSTOM_TEMPLATE && agentType === PLANNER_META_AGENT && continueButton && index !== lastIndex && (
                      <AccordionPlanSteps
                        response={
                          typeof data.message === "object" && data.message !== null && !Array.isArray(data.message)
                            ? JSON.stringify(data.message, null, 2)
                            : typeof data.message === "string"
                            ? data.message
                            : ""
                        }
                        content={
                          typeof data.steps === "object" && data.steps !== null && !Array.isArray(data.steps)
                            ? JSON.stringify(data.steps, null, 2)
                            : typeof data.steps === "string"
                            ? data.steps
                            : ""
                        }
                        debugExecutor={
                          Array.isArray(data.debugExecutor)
                            ? data.debugExecutor.map((item) =>
                                typeof item === "object" && item !== null && !Array.isArray(item)
                                  ? {
                                      ...item,
                                      content: typeof item.content === "object" ? JSON.stringify(item.content, null, 2) : item.content,
                                    }
                                  : item
                              )
                            : []
                        }
                        messageData={messageData}
                        isEditable={isEditable}
                        value={value}
                        text={text}
                        argunentKey={argunentKey}
                        parts={data?.parts || []}
                        show_canvas={data?.show_canvas || false}
                        openCanvas={props.openCanvas}
                        detectCanvasContent={props.detectCanvasContent}
                      />
                    )}
                    {data.message && agentType !== CUSTOM_TEMPLATE && agentType !== PLANNER_META_AGENT && (
                      <AccordionPlanSteps
                        response={
                          typeof data.message === "object" && data.message !== null && !Array.isArray(data.message)
                            ? JSON.stringify(data.message, null, 2)
                            : typeof data.message === "string"
                            ? data.message
                            : ""
                        }
                        content={
                          typeof data.steps === "object" && data.steps !== null && !Array.isArray(data.steps)
                            ? JSON.stringify(data.steps, null, 2)
                            : typeof data.steps === "string"
                            ? data.steps
                            : ""
                        }
                        debugExecutor={
                          Array.isArray(data.debugExecutor)
                            ? data.debugExecutor.map((item) =>
                                typeof item === "object" && item !== null && !Array.isArray(item)
                                  ? {
                                      ...item,
                                      content: typeof item.content === "object" ? JSON.stringify(item.content, null, 2) : item.content,
                                    }
                                  : item
                              )
                            : []
                        }
                        messageData={messageData}
                        isEditable={isEditable}
                        value={value}
                        text={text}
                        argunentKey={argunentKey}
                        openCanvas={props.openCanvas}
                        parts={data?.parts || []}
                        show_canvas={data?.show_canvas || false}
                        detectCanvasContent={props.detectCanvasContent}
                      />
                    )}
                    {data.message && agentType !== CUSTOM_TEMPLATE && agentType === PLANNER_META_AGENT && data?.plan?.length === 0 && (
                      <AccordionPlanSteps
                        response={
                          typeof data.message === "object" && data.message !== null && !Array.isArray(data.message)
                            ? JSON.stringify(data.message, null, 2)
                            : typeof data.message === "string"
                            ? data.message
                            : ""
                        }
                        content={
                          typeof data.steps === "object" && data.steps !== null && !Array.isArray(data.steps)
                            ? JSON.stringify(data.steps, null, 2)
                            : typeof data.steps === "string"
                            ? data.steps
                            : ""
                        }
                        debugExecutor={
                          Array.isArray(data.debugExecutor)
                            ? data.debugExecutor.map((item) =>
                                typeof item === "object" && item !== null && !Array.isArray(item)
                                  ? {
                                      ...item,
                                      content: typeof item.content === "object" ? JSON.stringify(item.content, null, 2) : item.content,
                                    }
                                  : item
                              )
                            : []
                        }
                        messageData={messageData}
                        isEditable={isEditable}
                        value={value}
                        text={text}
                        argunentKey={argunentKey}
                        openCanvas={props.openCanvas}
                        parts={data?.parts || []}
                        show_canvas={data?.show_canvas || false}
                        detectCanvasContent={props.detectCanvasContent}
                      />
                    )}
                    <div className={styles.accordionContainer}>
                      {index === lastIndex &&
                        data?.plan?.length > 0 &&
                        agentType !== PLANNER_META_AGENT &&
                        data?.message === "" &&
                        ((isHuman && toolInterrupt) || isHuman) &&
                        (!data?.toolcallData?.additional_details || // not present at all
                          (Array.isArray(data.toolcallData.additional_details) &&
                            data.toolcallData.additional_details.length > 0 &&
                            Object.keys(data.toolcallData.additional_details[0]?.additional_kwargs || {}).length === 0)) && (
                          <>
                            <div className={styles.planContainer}>
                              <h3>Plan</h3>
                              {data?.plan?.map((planItem, planIndex) => (
                                <>
                                  <p className={styles.stepsContent} key={`plan-step-${planIndex}`}>
                                    {planItem}
                                  </p>
                                </>
                              ))}
                            </div>

                            {!fetching && feedBack !== "no" && (
                              <div className={chatBubbleCss.feedbackWrapper}>
                                <button
                                  className={`${chatBubbleCss.feedbackButton}`} /*  ${highlightedFeedback === 'up' ? chatBubbleCss.highlighted : ''} */
                                  onClick={() => handlePlanFeedBack("yes", data?.userText)}
                                  title="Good response">
                                  <FontAwesomeIcon icon={faThumbsUp} />
                                </button>{" "}
                                <button
                                  className={`${chatBubbleCss.feedbackButton}`} /*  ${highlightedFeedback === 'down' ? chatBubbleCss.highlighted : ''} */
                                  onClick={() => {
                                    handlePlanFeedBack("no", data?.userText);
                                    setShowInput(true);
                                    setClose(true);
                                  }}
                                  title="Poor response">
                                  <FontAwesomeIcon icon={faThumbsDown} style={{ transform: "scaleX(-1)" }} />
                                </button>
                                {data?.response_time && (
                                  <span className={chatBubbleCss.responseTime}>
                                    <span className={chatBubbleCss.time} title={`Response time: ${formatResponseTimeSeconds(data.response_time)}`}>
                                      {formatResponseTimeSeconds(data.response_time)}
                                    </span>
                                  </span>
                                )}
                              </div>
                            )}

                            {!fetching && showInput && (
                              <div className={styles.feedBackSection}>
                                {(agentType === REACT_AGENT ||
                                  agentType === MULTI_AGENT ||
                                  agentType === REACT_CRITIC_AGENT ||
                                  agentType === PLANNER_EXECUTOR_AGENT ||
                                  agentType === HYBRID_AGENT) &&
                                  close && (
                                    <div className={styles["cancel-btn"]}>
                                      <button
                                        onClick={() => {
                                          setClose(false);
                                          setFeedback("");
                                          setShowInput(false);
                                        }}>
                                        <SVGIcons icon="fa-xmark" fill="#3D4359" width={13} height={13} />
                                      </button>
                                    </div>
                                  )}
                                <p className={styles.warning}>{feedBackMessage}</p>
                                <div className={styles.feedBackInput}>
                                  <textarea
                                    type="text"
                                    placeholder="Enter your feedback:"
                                    className={styles.feedBackTextArea}
                                    value={feedBackText}
                                    onChange={handleChange}
                                    rows={4}></textarea>
                                  <button
                                    disabled={generating || feedBackText.trim().length < 1}
                                    onClick={() => handlePlanDislikeFeedBack(data?.userText)}
                                    className={styles.feedbackSendBtn}>
                                    <svg width="18" height="18" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg">
                                      <path d="M3 17L17 10L3 3V8L13 10L3 12V17Z" fill="currentColor" />
                                    </svg>
                                  </button>
                                </div>
                              </div>
                            )}
                          </>
                        )}
                      {index === lastIndex &&
                        data?.plan?.length > 0 &&
                        data?.message !== "" &&
                        agentType === PLANNER_META_AGENT &&
                        (!data?.toolcallData?.additional_details || // not present at all
                          (Array.isArray(data.toolcallData.additional_details) &&
                            data.toolcallData.additional_details.length > 0 &&
                            Object.keys(data.toolcallData.additional_details[0]?.additional_kwargs || {}).length === 0)) && (
                          <>
                            <div className={styles.planContainer}>
                              <h3>Plan</h3>
                              {data?.plan?.map((planItem, planIndex) => (
                                <>
                                  <p className={styles.stepsContent} key={`plan-${planIndex}`}>
                                    {planItem}
                                  </p>
                                </>
                              ))}
                            </div>
                            {continueButton && agentType === PLANNER_META_AGENT && (
                              <div className={styles["plan-feedback"]}>
                                <button
                                  onClick={() => continueOnclick()}
                                  className={styles.continueButton}
                                  style={{ border: "1px solid #ccc", borderRadius: "4px", padding: "4px 8px", cursor: "pointer" }}>
                                  {"continue...."}
                                </button>
                              </div>
                            )}
                          </>
                        )}
                      {agentType !== CUSTOM_TEMPLATE && agentType === PLANNER_META_AGENT && !continueButton && (
                        <AccordionPlanSteps
                          response={
                            typeof data.message === "object" && data.message !== null && !Array.isArray(data.message)
                              ? JSON.stringify(data.message, null, 2)
                              : typeof data.message === "string"
                              ? data.message
                              : ""
                          }
                          content={
                            typeof data.steps === "object" && data.steps !== null && !Array.isArray(data.steps)
                              ? JSON.stringify(data.steps, null, 2)
                              : typeof data.steps === "string"
                              ? data.steps
                              : ""
                          }
                          debugExecutor={
                            Array.isArray(data.debugExecutor)
                              ? data.debugExecutor.map((item) =>
                                  typeof item === "object" && item !== null && !Array.isArray(item)
                                    ? {
                                        ...item,
                                        content: typeof item.content === "object" ? JSON.stringify(item.content, null, 2) : item.content,
                                      }
                                    : item
                                )
                              : []
                          }
                          messageData={messageData}
                          isEditable={isEditable}
                          value={value}
                          text={text}
                          argunentKey={argunentKey}
                          openCanvas={props.openCanvas}
                          parts={data?.parts || []}
                          show_canvas={data?.show_canvas || false}
                          detectCanvasContent={props.detectCanvasContent}
                        />
                      )}
                      {agentType === CUSTOM_TEMPLATE && (
                        <>
                          <AccordionPlanSteps
                            response={
                              typeof data.message === "object" && data.message !== null && !Array.isArray(data.message)
                                ? JSON.stringify(data.message, null, JSON_INDENT)
                                : typeof data.message === "string"
                                ? data.message
                                : ""
                            }
                            content={
                              typeof data.steps === "object" && data.steps !== null && !Array.isArray(data.steps)
                                ? JSON.stringify(data.steps, null, JSON_INDENT)
                                : typeof data.steps === "string"
                                ? data.steps
                                : ""
                            }
                            debugExecutor={
                              Array.isArray(data.debugExecutor)
                                ? data.debugExecutor.map((item) =>
                                    typeof item === "object" && item !== null && !Array.isArray(item)
                                      ? {
                                          ...item,
                                          content: typeof item.content === "object" ? JSON.stringify(item.content, null, JSON_INDENT) : item.content,
                                        }
                                      : item
                                  )
                                : []
                            }
                            messageData={messageData}
                            isEditable={isEditable}
                            value={value}
                            text={text}
                            argunentKey={argunentKey}
                            openCanvas={props.openCanvas}
                            parts={data?.parts || []}
                            show_canvas={data?.show_canvas || false}
                            detectCanvasContent={props.detectCanvasContent}
                          />

                          {!fetching && index === lastIndex && agentType === CUSTOM_TEMPLATE && (
                            <div className={chatBubbleCss.feedbackWrapper}>
                              <button
                                className={`${chatBubbleCss.feedbackButton} `} /* ${highlightedFeedback === 'up' ? chatBubbleCss.highlighted : ''} */
                                onClick={() => handlePlanFeedBack("yes", data?.userText)}
                                title="Good response">
                                <FontAwesomeIcon icon={faThumbsUp} />
                              </button>
                              <button
                                className={`${chatBubbleCss.feedbackButton}`} /*  ${highlightedFeedback === 'down' ? chatBubbleCss.highlighted : ''} */
                                onClick={() => handlePlanFeedBack("no", data?.userText)}
                                title="Poor response">
                                <FontAwesomeIcon icon={faThumbsDown} style={{ transform: "scaleX(-1)" }} />
                              </button>
                              {data?.response_time && (
                                <span className={chatBubbleCss.responseTime}>
                                  <span className={chatBubbleCss.time} title={`Response time: ${formatResponseTimeSeconds(data.response_time)}`}>
                                    {formatResponseTimeSeconds(data.response_time)}
                                  </span>
                                </span>
                              )}
                            </div>
                          )}

                          {showInput && index === lastIndex && agentType === CUSTOM_TEMPLATE && (
                            <div className={styles.feedBackInput}>
                              <textarea
                                type="text"
                                placeholder="Enter your feedback:"
                                className={styles.feedBackTextArea}
                                value={feedBackText}
                                onChange={handleChange}
                                rows={4}></textarea>
                              <button disabled={generating} onClick={() => handlePlanDislikeFeedBack(data?.userText)} className={styles.feedbackSendBtn}>
                                <svg width="18" height="18" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg">
                                  <path d="M3 17L17 10L3 3V8L13 10L3 12V17Z" fill="currentColor" />
                                </svg>
                              </button>
                            </div>
                          )}

                          {/* Removed duplicate unconditional loader for plan feedback (CUSTOM_TEMPLATE) */}
                        </>
                      )}
                      {data?.message === "" &&
                        Array.isArray(data?.toolcallData?.additional_details) &&
                        data.toolcallData.additional_details.length > 0 &&
                        data.toolcallData.additional_details[0]?.additional_kwargs &&
                        Object.keys(data.toolcallData.additional_details[0].additional_kwargs).length > 0 && (
                          <>
                            <ToolCallFinalResponse
                              response={
                                typeof data.message === "object" && data.message !== null && !Array.isArray(data.message)
                                  ? JSON.stringify(data.message, null, JSON_INDENT)
                                  : typeof data.message === "string"
                                  ? data.message
                                  : ""
                              }
                              content={
                                typeof data.steps === "object" && data.steps !== null && !Array.isArray(data.steps)
                                  ? JSON.stringify(data.steps, null, JSON_INDENT)
                                  : typeof data.steps === "string"
                                  ? data.steps
                                  : ""
                              }
                              debugExecutor={
                                Array.isArray(data.debugExecutor)
                                  ? data.debugExecutor.map((item) =>
                                      typeof item === "object" && item !== null && !Array.isArray(item)
                                        ? {
                                            ...item,
                                            content: typeof item.content === "object" ? JSON.stringify(item.content, null, JSON_INDENT) : item.content,
                                          }
                                        : item
                                    )
                                  : []
                              }
                              messageData={data}
                              isEditable={isEditable}
                              value={value}
                              text={text}
                              argunentKey={argunentKey}
                              parsedValues={parsedValues}
                              setParsedValues={setParsedValues}
                              rawData={rawData}
                              setIsEditable={setIsEditable}
                              setLikeIcon={setLikeIcon}
                              handleEditChange={handleEditChange}
                              sendArgumentEditData={sendArgumentEditData}
                              fetching={fetching}
                              sendIconShow={sendIconShow}
                              generating={generating}
                            />
                          </>
                        )}
                      {data?.message === "" && !isHuman && toolInterrupt && !("additional_details" in (data?.toolcallData || {})) && (
                        <div className={styles.botChatSection}>
                          <div className={styles.accordion}>
                            <div className={styles["accordion-header"]}>
                              <div className={chatBubbleCss.messageBubble}>
                                <span>{"Something went wrong"}</span>
                              </div>
                            </div>
                          </div>
                        </div>
                      )}
                    </div>
                    {data.type === BOT &&
                      index !== lastIndex &&
                      (processingFeedback[index] ? (
                        <div style={{ marginTop: 8 }}>
                          <LoadingChat label={"Generating"} />
                        </div>
                      ) : (
                        <div className={chatBubbleCss.feedbackWrapper} style={{ marginTop: 8 }}>
                          <button
                            type="button"
                            className={chatBubbleCss.feedbackButton}
                            onClick={(e) => {
                              e.stopPropagation();
                              handleMessageLike(data, index);
                            }}
                            title="Good response">
                            <FontAwesomeIcon icon={faThumbsUp} />
                          </button>
                          <button
                            type="button"
                            className={chatBubbleCss.feedbackButton}
                            onClick={(e) => {
                              e.stopPropagation();
                              handleMessageDislike(data, index);
                            }}
                            title="Poor response">
                            <FontAwesomeIcon icon={faThumbsDown} style={{ transform: "scaleX(-1)" }} />
                          </button>
                          {data?.response_time && (
                            <span className={chatBubbleCss.responseTime}>
                              <span className={chatBubbleCss.time} title={`Response time: ${formatResponseTimeSeconds(data.response_time)}`}>
                                {formatResponseTimeSeconds(data.response_time)}
                              </span>
                            </span>
                          )}
                        </div>
                      ))}
                    {feedBack === dislike &&
                      index === lastIndex &&
                      (agentType === REACT_AGENT ||
                        agentType === "react_agent" ||
                        agentType === MULTI_AGENT ||
                        agentType === PLANNER_EXECUTOR_AGENT ||
                        agentType === REACT_CRITIC_AGENT ||
                        agentType === "multi_agent" ||
                        agentType === PLANNER_META_AGENT ||
                        agentType === HYBRID_AGENT) && (
                        <div className={styles.feedBackSection}>
                          {(!fetching && (((agentType === REACT_AGENT ||
                            agentType === MULTI_AGENT ||
                            agentType === PLANNER_EXECUTOR_AGENT ||
                            agentType === REACT_CRITIC_AGENT ||
                            agentType === HYBRID_AGENT) &&
                            close) ||
                          (agentType === PLANNER_META_AGENT && continueButton && feedBack === dislike && close))) ? (
                            <div className={styles["cancel-btn"]}>
                              <button
                                onClick={() => {
                                  setClose(false);
                                  setFeedback("");
                                  setShowInput(false);
                                }}>
                                <SVGIcons icon="fa-xmark" fill="#3D4359" width={13} height={13} />
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
                              rows={4}></textarea>
                            <button disabled={generating || feedBackText.trim().length < 1} onClick={handleDislikeFeedBack} className={styles.feedbackSendBtn}>
                              <svg width="18" height="18" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg">
                                <path d="M3 17L17 10L3 3V8L13 10L3 12V17Z" fill="currentColor" />
                              </svg>
                            </button>
                          </div>
                        </div>
                      )}
                    {index === lastIndex && (
                      <>
                        {fetching && generateFeedBackButton && (
                          <div className={styles.loadingChat}>
                            {/* Basic SSE actions list replaced with compact panel */}
                            <DebugStepsPanel steps={debugSteps} visible={showLiveSteps} expanded={expanded} setExpanded={setExpanded} onClose={() => setShowLiveSteps(false)} />
                            <LoadingChat label={loadingText || "Generating"} />
                          </div>
                        )}
                      </>
                    )}
                    {index === lastIndex &&
                      (agentType === REACT_AGENT ||
                        agentType === MULTI_AGENT ||
                        agentType === PLANNER_EXECUTOR_AGENT ||
                        agentType === REACT_CRITIC_AGENT ||
                        agentType === HYBRID_AGENT ||
                        (agentType === PLANNER_META_AGENT && continueButton)) &&
                      feedBack !== dislike && (
                        <div className={styles["feedback-section"]}>
                          {!fetching && (
                            <div className={styles["button-container"]}>
                              {loadingText ? (
                                <>
                                  {fetching && (
                                    <div className={styles.loadingChat}>
                                      {/* Basic SSE actions list replaced with compact panel */}
                                      <DebugStepsPanel
                                        steps={debugSteps}
                                        visible={showLiveSteps}
                                        expanded={expanded}
                                        setExpanded={setExpanded}
                                        onClose={() => setShowLiveSteps(false)}
                                      />
                                      <LoadingChat label={"Generating"} />
                                    </div>
                                  )}
                                </>
                              ) : (
                                <></>
                              )}

                              {data?.message === "" &&
                              !props?.likeIcon &&
                              Array.isArray(data?.toolcallData?.additional_details) &&
                              data.toolcallData.additional_details.length > 0 &&
                              data.toolcallData.additional_details[0]?.additional_kwargs &&
                              Object.keys(data.toolcallData.additional_details[0]?.additional_kwargs).length > 0 ? (
                                <>
                                  <div className={chatBubbleCss.feedbackWrapper}>
                                    <button
                                      className={`${chatBubbleCss.feedbackButton}`} /* ${highlightedFeedback === 'up' ? chatBubbleCss.highlighted : ''} */
                                      onClick={() => submitFeedbackYes(data)}
                                      title="Good response">
                                      <FontAwesomeIcon icon={faThumbsUp} />
                                    </button>

                                    {Array.isArray(props?.messageData?.toolcallData?.additional_details) &&
                                    props.messageData.toolcallData.additional_details.length > 0 &&
                                    Array.isArray(props.messageData.toolcallData.additional_details[0]?.additional_kwargs?.tool_calls) &&
                                    props.messageData.toolcallData.additional_details[0].additional_kwargs.tool_calls.length > 0 &&
                                    props.messageData.toolcallData.additional_details[0].additional_kwargs.tool_calls[0]?.function?.arguments === "{}" ? (
                                      <></>
                                    ) : (
                                      <></>
                                    )}

                                    <button className={chatBubbleCss.editBtn} onClick={() => onMsgEdit(data)} title="Edit">
                                      <svg width="16" height="16" viewBox="0 0 20 20" fill="none">
                                        <g>
                                          <path
                                            d="M15.2 3.8c.5-.5 1.3-.5 1.8 0l.2.2c.5.5.5 1.3 0 1.8l-9.7 9.7-2.7.3.3-2.7 9.7-9.7z"
                                            fill="currentColor"
                                            stroke="currentColor"
                                            strokeWidth="1.5"
                                            strokeLinecap="round"
                                            strokeLinejoin="round"
                                          />
                                          <rect x="2.5" y="14.5" width="5" height="2" rx="0.8" fill="currentColor" opacity="0.18" />
                                          <path d="M13.7 5.7l1.6 1.6" stroke="#fff" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round" />
                                        </g>
                                      </svg>
                                    </button>
                                    {data?.response_time && (
                                      <span className={chatBubbleCss.responseTime}>
                                        <span className={chatBubbleCss.time} title={`Response time: ${formatResponseTimeSeconds(data.response_time)}`}>
                                          {formatResponseTimeSeconds(data.response_time)}
                                        </span>
                                      </span>
                                    )}
                                  </div>
                                </>
                              ) : (
                                <>
                                  {(data?.message === "" && props?.likeIcon) ||
                                  (data?.message === "" && (data?.plan || !data?.plan)) ||
                                  (data?.message === "" &&
                                    isHuman &&
                                    Array.isArray(data?.toolcallData?.additional_details) &&
                                    data.toolcallData.additional_details.length > 0 &&
                                    Object.keys(data.toolcallData.additional_details[0]?.additional_kwargs || {}).length === 0) ? (
                                    <></>
                                  ) : (
                                    <>
                                      {agentType !== PLANNER_META_AGENT && (
                                        <>
                                          <div className={chatBubbleCss.feedbackWrapper}>
                                            <button
                                              className={`${chatBubbleCss.feedbackButton}`} /*${highlightedFeedback === 'up' ? chatBubbleCss.highlighted : ''}*/
                                              onClick={() => handleFeedBack(like)}
                                              title="Good response">
                                              <FontAwesomeIcon icon={faThumbsUp} />
                                            </button>
                                            <button
                                              className={`${chatBubbleCss.feedbackButton}`} /*  ${highlightedFeedback === 'down' ? chatBubbleCss.highlighted : ''} */
                                              onClick={() => handleFeedBack(dislike)}
                                              title="Poor response">
                                              <FontAwesomeIcon
                                                icon={faThumbsDown}
                                                style={{
                                                  transform: "scaleX(-1)",
                                                }}
                                              />
                                            </button>{" "}
                                            <button className={chatBubbleCss.feedbackButton} onClick={() => handleFeedBack(regenerate)} title="Regenerate response">
                                              <FontAwesomeIcon
                                                icon={faRotateRight}
                                                style={{
                                                  transform: "rotate(-106deg)",
                                                }}
                                                className={generating ? chatBubbleCss.spinning : ""}
                                              />
                                            </button>
                                            {data?.response_time && (
                                              <span className={chatBubbleCss.responseTime}>
                                                <span className={chatBubbleCss.time} title={`Response time: ${formatResponseTimeSeconds(data.response_time)}`}>
                                                  {formatResponseTimeSeconds(data.response_time)}
                                                </span>
                                              </span>
                                            )}
                                          </div>
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
                              <div className={styles.loadingChat}>
                                {/* Basic SSE actions list replaced with compact panel */}
                                <DebugStepsPanel steps={debugSteps} visible={showLiveSteps} expanded={expanded} setExpanded={setExpanded} onClose={() => setShowLiveSteps(false)} />
                                <LoadingChat label={"Generating"} />
                              </div>
                            </>
                          ) : (
                            <></>
                          )}
                        </div>
                      )}
                  </div>
                </>
              )}
              {data.type === USER && (
                <>
                  <div className={chatBubbleCss.avatarContainer}>
                    <div className={`${chatBubbleCss.avatar} ${chatBubbleCss.userAvatar}`}>
                      <FontAwesomeIcon icon={faUser} className={chatBubbleCss.avatarIcon} />
                    </div>
                  </div>
                  <div className={chatBubbleCss.messageWrapper}>
                    <div className={`${chatBubbleCss.messageBubble} ${chatBubbleCss.userBubble}`}>
                      {/* Only render if data.message is a string or a plain object, never as a React child or array */}
                      {Array.isArray(data.message) ? null : typeof data.message === "object" && data.message !== null ? (
                        <div className={chatBubbleCss.messageContent}>
                          <div className={chatBubbleCss.userText}>
                            <pre
                              style={{
                                whiteSpace: "pre-wrap",
                                wordBreak: "break-word",
                              }}>
                              {JSON.stringify(data.message, null, 2)}
                            </pre>
                          </div>
                        </div>
                      ) : typeof data.message === "string" ? (
                        <div className={chatBubbleCss.messageContent}>
                          <div className={chatBubbleCss.userText}>
                            {parse(DOMPurify.sanitize((data.message || "").replace(/\n/g, "<br />")), {
                              replace: (domNode) => {
                                if (domNode.name === "ul") {
                                  domNode.attribs = domNode.attribs || {};
                                  domNode.attribs.class = (domNode.attribs.class || "") + " markdownList";
                                }
                                if (domNode.name === "li") {
                                  domNode.attribs = domNode.attribs || {};
                                  domNode.attribs.class = (domNode.attribs.class || "") + " markdownListItem";
                                }
                              },
                            })}
                          </div>
                        </div>
                      ) : null}
                      <div className={chatBubbleCss.timestamp}>{/* Time to be displayed here */}</div>
                    </div>
                  </div>
                </>
              )}
            </div>
          );
        })}
      {generating && (
        <div className={styles.loadingChat}>
          {/* Basic SSE actions list replaced with compact panel */}
          <DebugStepsPanel steps={debugSteps} expanded={expanded} setExpanded={setExpanded} visible={showLiveSteps} onClose={() => setShowLiveSteps(false)} />
          <LoadingChat label={"Generating"} />
        </div>
      )}

      <div className={`${"fixedDebugpanel"} ${styles.loadingChat}`} style={{ width: "100%", maxWidth: "98%" }}>
        {/* Basic SSE actions list replaced with compact panel */}
        <DebugStepsPanel steps={debugSteps} visible={true} expanded={true} setExpanded={setExpanded} onClose={() => setShowLiveSteps(false)} />
      </div>
    </div>
  );
};

export default MsgBox;
