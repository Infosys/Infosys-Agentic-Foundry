import React, { useEffect, useState } from "react";
import DOMPurify from "dompurify";
import SVGIcons from "../../Icons/SVGIcons";
import { BOT, CUSTOM_TEMPLATE, MULTI_AGENT, USER } from "../../constant";
import LoadingChat from "./LoadingChat";
import {
  REACT_AGENT,
  like,
  dislike,
  regenerate,
  sessionId,
  feedBackMessage,
} from "../../constant";
import { fetchFeedback } from "../../services/chatService";
import "../../css_modules/MsgBox.css";
import refresh from "../../Assets/refresh.png";
import thumbsDown from "../../Assets/thumbsDown.png";
import thumbsUp from "../../Assets/thumbsUp.png";
import robot from "../../Assets/robot.png";
import AccordionPlanSteps from "../commonComponents/Accordions/AccordionPlanSteps";
import Toggle from "../commonComponents/Toggle";
import parse from 'html-react-parser';

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
    isShowIsHuman,
    isHuman,
    setIsHuman,
    lastResponse,
  } = props;



  const handleFeedBack = async (value, sessionId) => {

    setFeedback(value);
    if (value !== dislike) {
      sendFeedback(value, sessionId);
    } else {
      setClose(true);
    }
  };

  const handlePlanFeedBack = async (feedBack, userText) => {
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
    chatHistory?.executor_messages?.map((item) => {
      chats?.push({ type: USER, message: item?.user_query });
      chats?.push({
        type: BOT,
        message: item?.final_response,
        steps: JSON.stringify(item?.agent_steps, null, "\t"),
      });
    });
    return chats;
  };

  const sendFeedback = async (feedBack, user_feedback = "", session_Id) => {
    const data = {
      agentic_application_id: agentSelectValue,
      query: lastResponse.query,
      session_id: session_Id,
      model_name: model,
      reset_conversation: false,
      prev_response: lastResponse || {},
      feedback: user_feedback,
    };
    setFetching(true);
    const response = await fetchFeedback(data, feedBack);
    if (feedBack !== like) setMessageData(converToChatFormat(response) || []);

    if (feedBack === like) {
      setShowToast(true);
      setTimeout(() => {
        setShowToast(false);
      }, 5000);
    }
    setFetching(false);
  };

  const handleChange = (e) => {
    setFeedBackText(e?.target?.value);
  };

  const handleDislikeFeedBack = async () => {
    setClose(true);

    sendFeedback(dislike, feedBackText, sessionId);
    setFeedBackText("");
    setFeedback("");
  };

  const handleToggle = async (e) => {
    setIsHuman(e.target.checked);
  };

  return (
    <div>
      {agentType === REACT_AGENT && feedBack === dislike && close && (
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
      )}
      {isShowIsHuman && (
        <div className={`${styles.toogle} ${isHuman ? styles.selected : ""}`}>
          <div className={styles.toggleContainer}>
            <label>HUMAN IN THE LOOP</label>
            <Toggle onChange={handleToggle} value={isHuman} />
          </div>
        </div>
      )}
      {((feedBack === "no" || feedBack === dislike) &&
        ((agentType === REACT_AGENT && close) || agentType === MULTI_AGENT)
        ? messageData.slice(-2)
        : messageData
      )?.map((data, index) => {
        const lastIndex =
          (feedBack === "no" || feedBack === dislike) &&
            ((agentType === REACT_AGENT && close) || agentType === MULTI_AGENT)
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
                    {data.message && agentType !== CUSTOM_TEMPLATE && (
                      <AccordionPlanSteps
                        response={data.message || ""}
                        content={data.steps || ""}
                      />
                    )}

                    <div className={styles.accordionContainer}>
                      {index === lastIndex && data?.plan?.length > 0 && (
                        <>
                          <div className={styles.planContainer}>
                            <h3>Plan</h3>
                            {data?.plan?.map((data) => (
                              <>
                                <p className={styles.stepsContent}>{data}</p>
                                <br />
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
                              <p className={styles.warning}>
                                {feedBackMessage}
                              </p>
                              <div className={styles.feedBackInput}>
                                <textarea
                                  type="text"
                                  placeholder="Enter your feedback:"
                                  className={styles.chat}
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

                      {agentType === CUSTOM_TEMPLATE && (
                        <>
                          <AccordionPlanSteps
                            response={data.message}
                            content={data.steps}
                          />

                          {!fetching && index === lastIndex && (
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

                          {showInput && index === lastIndex && (
                            <div className={styles.feedBackInput}>
                              <textarea
                                type="text"
                                placeholder="Enter your feedback:"
                                className={styles.chat}
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
                    </div>

                    {feedBack === dislike &&
                      index === lastIndex &&
                      agentType === REACT_AGENT && (
                        <div className={styles.feedBackSection}>
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

                    {index === lastIndex &&
                      agentType === REACT_AGENT &&
                      feedBack !== dislike && (
                        <div className={styles["feedback-section"]}>
                          {!fetching && (
                            <div className={styles["button-container"]}>
                              <button
                                onClick={() => handleFeedBack(like)}
                                className={styles.button}
                              >
                                <img src={thumbsUp} alt="Approve" />
                              </button>
                              <button
                                onClick={() => handleFeedBack(dislike)}
                                className={`${styles.button} + ${styles.dislikeButton}`}
                              >
                                <img src={thumbsDown} alt="Dislike" />
                              </button>
                              <button
                                onClick={() => handleFeedBack(regenerate)}
                                className={styles.button}
                              >
                                <img src={refresh} alt="Regenerate" />
                              </button>
                            </div>
                          )}
                          <span className={styles.regenerateText}>
                            {fetching && feedBack !== like && (
                              <LoadingChat label={"Regenerating"} />
                            )}
                          </span>
                        </div>
                      )}
                  </div>
                </div>
              )}
              {/* Some times data.message is undefined and this breaks the applicationWe have to fix this scenario */}
              {data.type === USER && (
                <>
                  <div
                    className={styles.userChat}
                  >
                    {/* Sanitize the message (with newlines already converted to <br />), 
                    then parse the resulting safe HTML string into React elements. */}
                    {parse(DOMPurify.sanitize((data?.message || "").replace(/\n/g, "<br />")))}
                  </div>
                  <div className={styles.userIcon}>
                    <SVGIcons icon="person-circle" fill="000000" />
                  </div>
                </>
              )}
            </div>
          </>
        );
      })}
      {generating && (
        <div className={styles.loadingChat}>
          <LoadingChat />
        </div>
      )}
    </div>
  );
};

export default MsgBox;
