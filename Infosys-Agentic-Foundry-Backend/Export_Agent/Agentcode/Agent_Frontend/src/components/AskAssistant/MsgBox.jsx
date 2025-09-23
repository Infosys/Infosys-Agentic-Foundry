import { useEffect, useState } from "react";
import PlaceholderScreen from "./PlaceholderScreen";
import DOMPurify from "dompurify";
import SVGIcons from "../../Icons/SVGIcons";
import {
  BOT,
  CUSTOM_TEMPLATE,
  MULTI_AGENT,
  PLANNER_EXECUTOR_AGENT,
  REACT_CRITIC_AGENT,
  USER,
} from "../../constant";
import LoadingChat from "./LoadingChat";
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
import AccordionPlanSteps from "../commonComponents/Accordions/AccordionPlanSteps";
import parse from "html-react-parser";
import ToolCallFinalResponse from "./ToolCallFinalResponse";
import { getChatQueryResponse } from "../../services/chatService";
import chatBubbleCss from "./ChatBubble.module.css";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import {
  faUser,
  faRobot,
  faThumbsUp,
  faThumbsDown,
  faRotateRight,
} from "@fortawesome/free-solid-svg-icons";

const MsgBox = (props) => {
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
      chats?.push({ type: USER, message: item?.user_query,debugExecutor: item?.additional_details });
      chats?.push({
        type: BOT,
        message: item?.final_response,
        toolcallData: item,
        steps: JSON.stringify(item?.agent_steps, null, "\t"),
        debugExecutor: item?.additional_details,
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
    if (feedBack !== like) {
      setMessageData(converToChatFormat(response) || []);
    }

    if (feedBack === like) {
      if (!isDeletingChat) {
        setShowToast(true);
        setTimeout(() => {
          setShowToast(false);
        }, 5000);
      }
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
          : agentType === PLANNER_EXECUTOR_AGENT
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
          : agentType === PLANNER_EXECUTOR_AGENT
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

  let argunentKey;
  let argumentValue;
  useEffect(() => {
    setIsEditable(false);
  }, [messageData]);
  const [value, setValue] = useState(argunentKey);
  const [text, setText] = useState(argumentValue);

  return (
    <div className={styles.messagesContainer}>
      {((!props?.allOptionsSelected && props?.oldChats.length === 0) ||
        (props?.allOptionsSelected && props?.oldChats.length === 0)) &&
        messageData.length === 0 && (
          <PlaceholderScreen
            agentType={agentType}
            model={model}
            selectedAgent={agentSelectValue}
          />
        )}

      {(messageData?.length > 0 || props?.oldChats.length > 0) &&
        ((feedBack === "no" || feedBack === dislike) &&
        ((agentType === REACT_AGENT && close) ||
          agentType === MULTI_AGENT ||
          agentType === PLANNER_EXECUTOR_AGENT ||
          agentType === REACT_CRITIC_AGENT ||
          agentType === PLANNER_META_AGENT)
          ? messageData.slice(-2)
          : messageData
        )?.map((data, index) => {
          const lastIndex =
            (feedBack === "no" || feedBack === dislike) &&
            ((agentType === REACT_AGENT && close) ||
              agentType === MULTI_AGENT ||
              agentType === PLANNER_EXECUTOR_AGENT ||
              agentType === REACT_CRITIC_AGENT ||
              agentType === PLANNER_META_AGENT)
              ? messageData.slice(-2).length - 1
              : messageData.length - 1;
          return (
            <>
              <div
                className={`${chatBubbleCss.container} ${
                  data.type === BOT
                    ? chatBubbleCss.botMessage
                    : chatBubbleCss.userMessage
                }`}
                key={data.message}
              >
                {data.type === BOT && (
                  <>
                    <div className={chatBubbleCss.avatarContainer}>
                      <div
                        className={`${chatBubbleCss.avatar} ${chatBubbleCss.botAvatar}`}
                      >
                        <span className={chatBubbleCss.agentIcon}>
                          <FontAwesomeIcon icon={faRobot} />
                        </span>
                      </div>
                    </div>
                    <div className={chatBubbleCss.messageWrapper}>                      {data.message &&
                        agentType !== CUSTOM_TEMPLATE &&
                        agentType === PLANNER_META_AGENT &&
                        continueButton &&
                        index != lastIndex && (
                          <AccordionPlanSteps
                            response={data.message}
                            content={data.steps}
                            debugExecutor={data.debugExecutor}
                            messageData={messageData}
                            isEditable={isEditable}
                            value={value}
                            text={text}
                            argunentKey={argunentKey}
                            openCanvas={props.openCanvas}
                            detectCanvasContent={props.detectCanvasContent}
                          />
                        )}                     
                        {data.message &&
                        agentType !== CUSTOM_TEMPLATE &&
                        agentType !== PLANNER_META_AGENT && (
                          <AccordionPlanSteps
                            response={data.message}
                            content={data.steps}
                            debugExecutor={data.debugExecutor}
                            messageData={messageData}
                            isEditable={isEditable}
                            value={value}
                            text={text}
                            argunentKey={argunentKey}
                            openCanvas={props.openCanvas}
                            detectCanvasContent={props.detectCanvasContent}
                          />
                        )}                     
                        {data.message &&
                        agentType !== CUSTOM_TEMPLATE &&
                        agentType === PLANNER_META_AGENT &&
                        data?.plan?.length == 0 && (
                          <AccordionPlanSteps
                            response={data.message}
                            content={data.steps}
                            debugExecutor={data.debugExecutor}
                            messageData={messageData}
                            isEditable={isEditable}
                            value={value}
                            text={text}
                            argunentKey={argunentKey}
                            openCanvas={props.openCanvas}
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
                                    <p className={styles.stepsContent}>
                                      {data}
                                    </p>
                                  </>
                                ))}
                              </div>

                              {!fetching && feedBack !== "no" && (
                                <div className={chatBubbleCss.feedbackWrapper}>
                                  <button
                                    className={`${chatBubbleCss.feedbackButton}`} /*  ${highlightedFeedback === 'up' ? chatBubbleCss.highlighted : ''} */
                                    onClick={() =>
                                      handlePlanFeedBack("yes", data?.userText)
                                    }
                                    title="Good response"
                                  >
                                    <FontAwesomeIcon icon={faThumbsUp} />
                                  </button>                                  <button
                                    className={`${chatBubbleCss.feedbackButton}`} /*  ${highlightedFeedback === 'down' ? chatBubbleCss.highlighted : ''} */
                                    onClick={() =>
                                      handlePlanFeedBack("no", data?.userText)
                                    }
                                    title="Poor response"
                                  >
                                    <FontAwesomeIcon
                                      icon={faThumbsDown}
                                      style={{ transform: "scaleX(-1)" }}
                                    />
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
                                        handlePlanDislikeFeedBack(
                                          data?.userText
                                        )
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

                              {fetching && (
                                <div className={styles.loadingChat}>
                                  <LoadingChat label={loadingText} />
                                </div>
                              )}
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
                                    <p className={styles.stepsContent}>
                                      {data}
                                    </p>
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
                          )}                        {agentType !== CUSTOM_TEMPLATE &&
                          agentType === PLANNER_META_AGENT &&
                          !continueButton && (
                            <AccordionPlanSteps
                              response={data.message}
                              content={data.steps}
                              debugExecutor={data.debugExecutor}
                              messageData={messageData}
                              isEditable={isEditable}
                              value={value}
                              text={text}
                              argunentKey={argunentKey}
                              openCanvas={props.openCanvas}
                              detectCanvasContent={props.detectCanvasContent}
                            />
                          )}                        {agentType === CUSTOM_TEMPLATE && (
                          <>
                            <AccordionPlanSteps
                              response={data.message}
                              content={data.steps}
                              debugExecutor={data.debugExecutor}
                              messageData={messageData}
                              isEditable={isEditable}
                              value={value}
                              text={text}
                              argunentKey={argunentKey}
                              openCanvas={props.openCanvas}
                              detectCanvasContent={props.detectCanvasContent}
                            />

                            {!fetching &&
                              index === lastIndex &&
                              agentType === CUSTOM_TEMPLATE && (
                                <div className={chatBubbleCss.feedbackWrapper}>
                                  <button
                                    className={`${chatBubbleCss.feedbackButton} `} /* ${highlightedFeedback === 'up' ? chatBubbleCss.highlighted : ''} */
                                    onClick={() =>
                                      handlePlanFeedBack("yes", data?.userText)
                                    }
                                    title="Good response"
                                  >
                                    <FontAwesomeIcon icon={faThumbsUp} />
                                  </button>
                                  <button
                                    className={`${chatBubbleCss.feedbackButton}`} /*  ${highlightedFeedback === 'down' ? chatBubbleCss.highlighted : ''} */
                                    onClick={() =>
                                      handlePlanFeedBack("no", data?.userText)
                                    }
                                    title="Poor response"
                                  >
                                    <FontAwesomeIcon
                                      icon={faThumbsDown}
                                      style={{ transform: "scaleX(-1)" }}
                                    />
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
                              <>{fetching && (
                                  <div className={styles.loadingChat}>
                                    <LoadingChat label={"Regnerating"} />
                                  </div>
                                )}
                              </>
                            )}
                          </>
                        )}
                        {data?.message === "" &&
                          Array.isArray(
                            data?.toolcallData?.additional_details
                          ) &&
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
                                setIsEditable={setIsEditable}
                                setLikeIcon={setLikeIcon}
                                handleEditChange={handleEditChange}
                                sendArgumentEditData={sendArgumentEditData}
                                fetching={fetching}
                                sendIconShow={sendIconShow}
                                generating={generating}
                              />
                            </>
                          )
                        }
                        {data?.message === "" &&
                          !isHuman &&
                          toolInterrupt &&
                          !(
                            "additional_details" in (data?.toolcallData || {})
                          ) && (
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

                      {feedBack === dislike &&
                        index === lastIndex &&
                        (agentType === REACT_AGENT ||
                          agentType === "react_agent" ||
                          agentType === MULTI_AGENT ||
                          agentType === PLANNER_EXECUTOR_AGENT ||
                          agentType === REACT_CRITIC_AGENT ||
                          agentType === "multi_agent" ||
                          agentType === PLANNER_META_AGENT) && (
                          <div className={styles.feedBackSection}>
                            {((agentType === REACT_AGENT ||
                              agentType === MULTI_AGENT ||
                              agentType === PLANNER_EXECUTOR_AGENT ||
                              agentType === REACT_CRITIC_AGENT) &&
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
                        <>{fetching && generateFeedBackButton && (
                          <div className={styles.loadingChat}>
                            <LoadingChat label={"Generating"} />
                          </div>
                          )}
                        </>
                      )}

                      {index === lastIndex &&
                        (agentType === REACT_AGENT ||
                          agentType === MULTI_AGENT ||
                          agentType === PLANNER_EXECUTOR_AGENT ||
                          agentType === REACT_CRITIC_AGENT ||
                          (agentType === PLANNER_META_AGENT &&
                            continueButton)) &&
                        feedBack !== dislike && (
                          <div className={styles["feedback-section"]}>
                            {!fetching && (
                              <div className={styles["button-container"]}>
                                {loadingText ? (
                                  <>
                                    {fetching && (
                                      <div className={styles.loadingChat}>
                                        <LoadingChat label={"Generating"} />
                                      </div>
                                    )}
                                  </>
                                ) : (
                                  <></>
                                )}

                                {data?.message === "" &&
                                !props?.likeIcon &&
                                Array.isArray(
                                  data?.toolcallData?.additional_details
                                ) &&
                                data.toolcallData.additional_details.length >
                                  0 &&
                                Object.keys(
                                  data.toolcallData.additional_details[0]
                                    ?.additional_kwargs
                                ).length > 0 ? (
                                  <>
                                    <div
                                      className={chatBubbleCss.feedbackWrapper}
                                    >
                                      <button
                                        className={`${chatBubbleCss.feedbackButton}`} /* ${highlightedFeedback === 'up' ? chatBubbleCss.highlighted : ''} */
                                        onClick={() => submitFeedbackYes(data)}
                                        title="Good response"
                                      >
                                        <FontAwesomeIcon icon={faThumbsUp} />
                                      </button>

                                      {Array.isArray(
                                        props?.messageData?.toolcallData
                                          ?.additional_details
                                      ) &&
                                      props.messageData.toolcallData
                                        .additional_details.length > 0 &&
                                      Array.isArray(
                                        props.messageData.toolcallData
                                          .additional_details[0]
                                          ?.additional_kwargs?.tool_calls
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
                                        className={chatBubbleCss.editBtn}
                                        onClick={() => onMsgEdit(data)}
                                        title="Edit"
                                      >
                                        <svg
                                          width="16"
                                          height="16"
                                          viewBox="0 0 20 20"
                                          fill="none"
                                        >
                                          <g>
                                            <path
                                              d="M15.2 3.8c.5-.5 1.3-.5 1.8 0l.2.2c.5.5.5 1.3 0 1.8l-9.7 9.7-2.7.3.3-2.7 9.7-9.7z"
                                              fill="currentColor"
                                              stroke="currentColor"
                                              strokeWidth="1.5"
                                              strokeLinecap="round"
                                              strokeLinejoin="round"
                                            />
                                            <rect
                                              x="2.5"
                                              y="14.5"
                                              width="5"
                                              height="2"
                                              rx="0.8"
                                              fill="currentColor"
                                              opacity="0.18"
                                            />
                                            <path
                                              d="M13.7 5.7l1.6 1.6"
                                              stroke="#fff"
                                              strokeWidth="1.2"
                                              strokeLinecap="round"
                                              strokeLinejoin="round"                                            />
                                          </g>
                                        </svg>
                                      </button>
                                    </div>
                                  </>
                                ) : (
                                  <>
                                    {(data?.message === "" &&
                                      props?.likeIcon) ||
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
                                            <div
                                              className={
                                                chatBubbleCss.feedbackWrapper
                                              }
                                            >
                                              <button
                                                className={`${chatBubbleCss.feedbackButton}`} /*${highlightedFeedback === 'up' ? chatBubbleCss.highlighted : ''}*/
                                                onClick={() =>
                                                  handleFeedBack(like)
                                                }
                                                title="Good response"
                                              >
                                                <FontAwesomeIcon
                                                  icon={faThumbsUp}
                                                />
                                              </button>
                                              <button
                                                className={`${chatBubbleCss.feedbackButton}`} /*  ${highlightedFeedback === 'down' ? chatBubbleCss.highlighted : ''} */
                                                onClick={() =>
                                                  handleFeedBack(dislike)
                                                }
                                                title="Poor response"
                                              >
                                                <FontAwesomeIcon
                                                  icon={faThumbsDown}
                                                  style={{
                                                    transform: "scaleX(-1)",
                                                  }}
                                                />
                                              </button>                                              <button
                                                className={
                                                  chatBubbleCss.feedbackButton
                                                }
                                                onClick={() =>
                                                  handleFeedBack(regenerate)
                                                }
                                                title="Regenerate response"
                                              >
                                                <FontAwesomeIcon
                                                  icon={faRotateRight}
                                                  style={{
                                                    transform:
                                                      "rotate(-106deg)",
                                                  }}
                                                  className={
                                                    generating
                                                      ? chatBubbleCss.spinning
                                                      : ""
                                                  }
                                                />
                                              </button>
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
                      <div
                        className={`${chatBubbleCss.avatar} ${chatBubbleCss.userAvatar}`}
                      >
                        <FontAwesomeIcon
                          icon={faUser}
                          className={chatBubbleCss.avatarIcon}
                        />
                      </div>
                    </div>
                    <div className={chatBubbleCss.messageWrapper}>
                      <div
                        className={`${chatBubbleCss.messageBubble} ${chatBubbleCss.userBubble}`}
                      >
                        <div className={chatBubbleCss.messageContent}>
                          <div className={chatBubbleCss.userText}>
                            {/* Sanitize the message (with newlines already converted to <br />), 
                            then parse the resulting safe HTML string into React elements. */}
                            {parse(
                              DOMPurify.sanitize(
                                (data?.message || "").replace(/\n/g, "<br />")
                              ), {
                                replace: (domNode) => {
                                  if (domNode.name === 'ul') {
                                    domNode.attribs = domNode.attribs || {};
                                    domNode.attribs.class = (domNode.attribs.class || '') + ' markdownList';
                                  }
                                  if (domNode.name === 'li') {
                                    domNode.attribs = domNode.attribs || {};
                                    domNode.attribs.class = (domNode.attribs.class || '') + ' markdownListItem';
                                  }
                                }
                              }
                            )}
                          </div>
                          <div className={chatBubbleCss.timestamp}>
                            {/* Time to be displayed here */}
                          </div>
                        </div>
                      </div>
                    </div>
                  </>
                )}
              </div>
            </>
          );
        })}
      {generating && (
        <div className={styles.loadingChat}>
          <LoadingChat label={"Generating"} />
        </div>
      )}
    </div>
  );
};

export default MsgBox;
