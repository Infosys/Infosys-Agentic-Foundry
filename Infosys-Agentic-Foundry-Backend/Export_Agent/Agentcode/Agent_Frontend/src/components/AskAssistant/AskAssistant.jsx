import React, { useEffect, useRef, useState } from "react";
import styles from "../../css_modules/AskAssistant.module.css";
import MsgBox from "./MsgBox";
import Toggle from "../commonComponents/Toggle";
import {
  BOT,
  dropdown1,
  USER,
  APIs,
  likeMessage,
  dislike,
  branchInteruptValue,
  branchInteruptKey,
  CUSTOM_TEMPLATE,
  MULTI_AGENT,
  REACT_AGENT,
  customTemplatId,
  META_AGENT,
  PLANNER_META_AGENT_QUERY,
  PLANNER_META_AGENT,
  liveTrackingUrl,
  REACT_CRITIC_AGENT,
  PLANNER_EXECUTOR_AGENT
} from "../../constant";
import SVGIcons from "../../Icons/SVGIcons";
import {
  resetChat,
  getChatQueryResponse,
  getChatHistory,
  fetchOldChats,
  fetchNewChats,
} from "../../services/chatService";
import ToastMessage from "../commonComponents/ToastMessage";
import clearChat from "../../Assets/clearchat.png";
import useFetch from "../../Hooks/useAxios";
import tracking from "../../Assets/tracking.png";
import CustomDropdown from "../commonComponents/DropDowns/CustomDropdown";
import OldChatsHistory from "./OldChatsHistory";
import Cookies from "js-cookie";
import AskAssistantDropdown from "./AskAssisstantDropdown.jsx";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import {
  faPaperclip,
  faChartPie,
  faTrash,
  faArrowTrendUp,
  faHexagonNodes,
  faRobot,
  faScrewdriverWrench,
  faGlobe,
  faArrowUp,
  faCommentMedical
} from "@fortawesome/free-solid-svg-icons";
import { useGlobalComponent } from "../../Hooks/GlobalComponentContext.js";
import Loader from "../commonComponents/Loader";

const AskAssistant = () => {
  const loggedInUserEmail = Cookies.get("email");
  const session_id = Cookies.get("session_id");
  const [messageData, setMessageData] = useState([]);
  const [lastResponse, setLastResponse] = useState({});
  const [userChat, setUserChat] = useState("");
  const [generating, setGenerating] = useState(false);
  const [isHuman, setIsHuman] = useState(false);
  const [isTool, setIsTool] = useState(false);
  const [isShowIsHuman, setIsShowIsHuman] = useState(false);
  const [agentsListData, setAgentsListData] = useState([]);
  const [agentListDropdown, setAgentListDropdown] = useState([]);
  const [agentSelectValue, setAgentSelectValue] = useState("");
  const [agentType, setAgentType] = useState(dropdown1[0].value);
  const [model, setModel] = useState("");
  const [feedBack, setFeedback] = useState("");
  const [fetching, setFetching] = useState(false);
  const [showToast, setShowToast] = useState(false);
  const [planData, setPlanData] = useState(null);
  const [showInput, setShowInput] = useState(false);
  const [oldChats, setOldChats] = useState([]);
  const [oldSessionId, setOldSessionId] = useState("");
  const [session, setSessionId] = useState(session_id);
  const [selectedModels, setSelectedModels] = useState([]);
  const [toolInterrupt, setToolInterrupt] = useState(false);
  const [toolData, setToolData] = useState(null);
  const [loadingAgents, setLoadingAgents] = useState(true);
  const [isEditable, setIsEditable] = useState(false);
  const [showModelPopover, setShowModelPopover] = useState(false);
  const bullseyeRef = useRef(null);

  const chatbotContainerRef = useRef(null);
  const [likeIcon, setLikeIcon] = useState(false);
  const [showInputSendIcon, setShowInputSendIcon] = useState(false);
  const [isOldChatOpen, setIsOldChatOpen] = useState(false);
  const [showVerifierSettings, setShowVerifierSettings] = useState(false);
  const handleToggle2 = async (e) => {
    if (agentType === REACT_AGENT || agentType === MULTI_AGENT || agentType === REACT_CRITIC_AGENT || agentType === PLANNER_EXECUTOR_AGENT) {
      handleToolInterrupt(e.target.checked);
    }
  };
  const popoverRef = useRef(null);
  useEffect(() => {
    function handleClickOutside(event) {
      if (popoverRef.current && !popoverRef.current.contains(event.target)) {
        setShowVerifierSettings(false);
      }
    }

    if (showVerifierSettings) {
      document.addEventListener("mousedown", handleClickOutside);
    }

    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
    };
  }, [showVerifierSettings]);
  const handleToggle = (e) => {
    if (agentType === MULTI_AGENT || agentType === PLANNER_EXECUTOR_AGENT){
      handleHumanInLoop(e.target.checked);
    } else {
      handleToolInterrupt(e.target.checked);
    }
  };
  const handleIconClick = () => {
    setShowVerifierSettings((prev) => !prev);
  };
  const oldChatRef = useRef(null);
  const toggleDropdown = () => {
    setIsOldChatOpen((prev) => !prev);
  };

  useEffect(() => {
    function handleClickOutside(event) {
      if (oldChatRef.current && !oldChatRef.current.contains(event.target)) {
        setIsOldChatOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
    };
  }, []);
  const { showComponent } = useGlobalComponent();
  let messageDisable = messageData.some((msg) => msg?.message.trim() === "");
  useEffect(() => {
    // Remove the dynamic height adjustment since we're using flexbox layout
  }, []);

  const { fetchData, postData } = useFetch();

  const msgContainerRef = useRef(null);
  const hasInitialized = useRef(false);

  const allOptionsSelected =
    agentType !== CUSTOM_TEMPLATE
      ? agentType === "" || model === "" || agentSelectValue === ""
      : agentType === "" || model === "";
  useEffect(() => {
    if (hasInitialized.current) return;
    fetchAgents();
    fetchModels();
    // Initialize textarea height
    if (textareaRef.current) {
      calculateHeight();
    }
    hasInitialized.current = true;
  }, []);

  useEffect(() => {
    setMessageData([]);
    setShowInput(false);
    setFeedback("");
  }, [agentType]);

  useEffect(() => {
    setAgentSelectValue("");
    if (!agentType) return;
    const tempList = agentsListData?.filter(
      (list) => list.agentic_application_type === agentType
    );
    setAgentListDropdown(tempList);
  }, [agentType, agentsListData]);

  useEffect(() => {
    if (!allOptionsSelected) {
      fetchChatHistory();
      fetchOldChatsData();
    } else {
      setMessageData([]);
    }
  }, [model, agentSelectValue, allOptionsSelected]);
  useEffect(() => {
    if (msgContainerRef.current) {
      const container = msgContainerRef.current;
      // Smooth scroll to bottom with a slight delay to account for layout changes
      setTimeout(() => {
        container.scrollTo({
          top: container.scrollHeight,
          behavior: "smooth",
        });
      }, 0);
    }
  }, [messageData, generating]);
  useEffect(() => {
    const handleClickOutside = (event) => {
      if (bullseyeRef.current && !bullseyeRef.current.contains(event.target)) {
        setShowModelPopover(false);
      }
    };
    document.addEventListener("mousedown", handleClickOutside);
    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
    };
  }, []);
  const converToChatFormat = (chatHistory) => {
    let chats = [];
    setPlanData(null);
    setToolData(null);
    if (chatHistory && chatHistory[branchInteruptKey] === branchInteruptValue) {
      setFeedback("no");
      setShowInput(true);
    }
    chatHistory?.executor_messages?.map((item, index) => {
      chats?.push({ type: USER, message: item?.user_query });
      chats?.push({
        type: BOT,
        message: item?.final_response,
        toolcallData: item,
        userText: item?.user_query,
        steps: JSON.stringify(item?.agent_steps, null, "\t"),
        ...(index === chatHistory?.executor_messages?.length - 1 && {
          plan: chatHistory?.plan,
        }),
      });
    });
    setPlanData(chatHistory?.plan);
    setToolData(chats?.toolcallData);
    return chats;
  };

  const fetchChatHistory = async (sessionId = session) => {
    const data = {
      session_id: sessionId,
      agent_id:
        agentType === CUSTOM_TEMPLATE ? customTemplatId : agentSelectValue,
    };
    const chatHistory = await getChatHistory(data);
    setLastResponse(chatHistory);
    setMessageData(converToChatFormat(chatHistory) || []);
  };

  const addMessage = (type, message, steps, plan, userText) => {
    setMessageData((prevProp) => [
      ...prevProp,
      { type, message, steps, plan, userText },
    ]);
  };

  const sendHumanInLoop = async (isApprove = "", feedBack = "", userText) => {
    const payload = {
      agentic_application_id:
        agentType === CUSTOM_TEMPLATE ? customTemplatId : agentSelectValue,
      query: userText,
      session_id: oldSessionId !== "" ? oldSessionId : session,
      model_name: model,
      reset_conversation: false,
      ...(isApprove !== "" && { approval: isApprove }),
      ...(feedBack !== "" && { feedback: feedBack }),
      ...(toolInterrupt ? { interrupt_flag: true } : { interrupt_flag: false }),
    };
    let response;
    try {
      const url =
        agentType === CUSTOM_TEMPLATE
          ? APIs.CUSTOME_TEMPLATE_QUERY
          :agentType === PLANNER_EXECUTOR_AGENT
           ? APIs.PLANNER_EXECUTOR_AGENT_QUERY
          : APIs.PLANNER;
      response = await postData(url, payload);
      setLastResponse(response);
      setPlanData(response?.plan);
      setMessageData(converToChatFormat(response) || []);
    } catch (err) {
      console.error(err);
    }
    return response;
  };

  const sendUserMessage = async () => {
    setFetching(true);
    resetHeight();
    if (!userChat || generating) return;
    addMessage(USER, userChat);
    setUserChat("");
    setGenerating(true);
    setLikeIcon(false);
    let userText = userChat;
    const payload = {
      agentic_application_id:
        agentType === CUSTOM_TEMPLATE ? customTemplatId : agentSelectValue,
      query: userChat.trim(),
      session_id: oldSessionId !== "" ? oldSessionId : session,
      model_name: model,
      reset_conversation: false,
      ...(toolInterrupt ? { interrupt_flag: true } : { interrupt_flag: false }),
    };
    if (isHuman) {
      await sendHumanInLoop("", "", userText);
    } else {
      const url =
        agentType === META_AGENT
          ? APIs.META_AGENT_QUERY
          : agentType === PLANNER_META_AGENT
          ? APIs.PLANNER_META_AGENT_QUERY
          : APIs.REACT_MULTI_AGENT_QUERY;

      const response = await getChatQueryResponse(payload, url);
      setLastResponse(response);
          if (response === null ) {
      setShowToast(true);
      setTimeout(() => {
        setShowToast(false);
      }, 5000);
    }
      
      setMessageData(converToChatFormat(response) || []);
    }
    setGenerating(false);
    setFetching(false);
  };

  const handleKeyDown = (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      sendUserMessage();
      resetHeight();
    } else if (event.shiftKey && event.key === "Enter") {
      event.preventDefault();
      setUserChat((prev) => prev + "\n");
      calculateHeight();
    }
  };

  const handleTypeChange = (selectedOption) => {
    setAgentType(selectedOption);
    setLikeIcon(false);
    if (
      selectedOption === MULTI_AGENT ||
      selectedOption === REACT_AGENT ||
      selectedOption === REACT_CRITIC_AGENT ||
      selectedOption === PLANNER_EXECUTOR_AGENT ||
      selectedOption === "react_agent"
    ) {
      setIsShowIsHuman(true);
    } else {
      setIsShowIsHuman(false);
    }
    if (selectedOption === CUSTOM_TEMPLATE) {
      setIsHuman(true);
    } else {
      setIsHuman(false);
    }
  };

  const handleResetChat = async () => {
    const data = {
      session_id: oldSessionId !== "" ? oldSessionId : session,
      agent_id:
        agentType !== CUSTOM_TEMPLATE ? agentSelectValue : customTemplatId,
    };
    const response = await resetChat(data);
    if (response?.status === "success") {
      setMessageData([]);
    }
  };

  const fetchAgents = async () => {
    try {
      setLoadingAgents(true);
      const data = await fetchData(APIs.GET_AGENTS_BY_DETAILS);
      setAgentsListData(data);
    } catch (e) {
      console.error(e);
    } finally {
      setLoadingAgents(false);
    }
  };

  const fetchModels = async () => {
    try {
      const data = await fetchData(APIs.GET_MODELS);
      if (data?.models && Array.isArray(data.models)) {
        const formattedModels = data.models.map((model) => ({
          label: model,
          value: model,
        }));
        setSelectedModels(formattedModels);
      } else {
        setSelectedModels([]);
      }
    } catch (e) {
      console.error(e);
      setSelectedModels([]);
    }
  };

  const fetchOldChatsData = async () => {
    const data = {
      user_email: loggedInUserEmail,
      agent_id: agentSelectValue,
    };
    const reseponse = await fetchOldChats(data);
    const oldChats = reseponse;
    let temp = [];
    for (let key in oldChats) {
      temp.push({ ...oldChats[key][0], session_id: key });
    }
    setOldChats(temp);
  };

  const handleNewChat = async () => {
    const sessionId = await fetchNewChats(loggedInUserEmail);
    fetchOldChatsData();
    setOldSessionId("");
    setSessionId(sessionId);
    fetchChatHistory(sessionId);
  };

  const textareaRef = useRef(null);
  const resetHeight = () => {
    const textarea = textareaRef.current;
    if (textarea) {
      textarea.style.height = "40px";
    }
  };

  const calculateHeight = () => {
    const textarea = textareaRef.current;
    if (textarea) {
      textarea.style.height = "20px";
      const maxHeight = 144; // 8 lines * 18px line-height
      const newHeight = Math.min(textarea.scrollHeight, maxHeight);
      textarea.style.height = `${newHeight}px`;
    }
  };
  const handleChange = (e) => {
    setUserChat(e.target.value);
    calculateHeight();
  };

  const handleFileClick = () => {
    showComponent(<div>Your file content here</div>);
  };

  const handleToolInterrupt = (isEnabled) => {
    setToolInterrupt(isEnabled);
    setIsTool(isEnabled);
  };

  const handleHumanInLoop = (isEnabled) => {
    setIsHuman(isEnabled);
  };
  let fieldData = messageData?.map((item, index) => {
    return <>{item?.message}</>;
  });

  return (
    <>
      <div className={styles.outerContainer}>
        <div className={styles.container} ref={chatbotContainerRef}>
          {/* message container */}{" "}
          <div className={styles.messageContainer} ref={msgContainerRef}>
            {showToast && (
              <ToastMessage
                message={lastResponse === null ?"Internal Server error":likeMessage}
                showToast={showToast}
                setShowToast={setShowToast}
              />
            )}
            {/* {(lastResponse === null) &&(
               <ToastMessage
                message={"Internal Server error"}
                showToast={showToast}
                setShowToast={setShowToast}
              />
            )} */}
            <MsgBox
              styles={styles}
              messageData={messageData}
              generating={generating}
              agentType={agentType}
              feedBack={feedBack}
              setFeedback={setFeedback}
              setMessageData={setMessageData}
              agentSelectValue={agentSelectValue}
              model={model}
              fetching={fetching}
              setFetching={setFetching}
              showToast={showToast}
              setShowToast={setShowToast}
              isHuman={isHuman}
              planData={planData}
              sendHumanInLoop={sendHumanInLoop}
              showInput={showInput}
              setShowInput={setShowInput}
              isShowIsHuman={isShowIsHuman}
              setIsHuman={setIsHuman}
              lastResponse={lastResponse}
              setIsTool={setIsTool}
              isTool={isTool}
              selectedOption={agentType}
              toolInterrupt={toolInterrupt}
              handleToolInterrupt={handleToolInterrupt}
              handleHumanInLoop={handleHumanInLoop}
              oldSessionId={oldSessionId}
              setOldSessionId={setOldSessionId}
              session={session}
              likeIcon={likeIcon}
              setLikeIcon={setLikeIcon}
              setGenerating={setGenerating}
              showInputSendIcon={showInputSendIcon}
              setShowInputSendIcon={setShowInputSendIcon}
              messageDisable={messageDisable}
              isEditable={isEditable}
              setIsEditable={setIsEditable}
              allOptionsSelected={allOptionsSelected}
              oldChats={oldChats}
            />
          </div>
          {/* {feedBack !== dislike && feedBack !== "no" && ( */}
            <div className={styles.messageInput}>
              <textarea
                type="text"
                ref={textareaRef}
                placeholder="TYPE"
                className={styles.chat}
                onChange={handleChange}
                value={userChat}
                onKeyDown={handleKeyDown}
                disabled={
                  generating ||
                  allOptionsSelected ||
                  fetching ||
                  feedBack === dislike ||
                  isEditable || messageDisable
                }
              ></textarea>
              <div className={styles.chatIconWrapper}>
                <div className={styles.inferenceIconGroupLeft}>
                  <span
                    className={`${styles.inferenceIcon} ${
                      messageDisable || fetching || generating || isEditable
                        ? styles.disabledButton
                        : ""
                    }`}
                    title="Select Agent Type"
                  >
                    {/* <span className={styles.hoverEffectCss}>
                      <FontAwesomeIcon icon={faRobot} />
                    </span> */}
                    <CustomDropdown
                      onChange={handleTypeChange}
                      options={dropdown1}
                      placeholder={"AGENT TYPE"}
                      value={agentType}
                      text={"Agent Type"}
                      agentType={agentType}
                      disabled={generating || fetching || isEditable}
                    ></CustomDropdown>
                  </span>

                  <span
                    className={`${styles.inferenceIcon} ${
                      messageDisable || fetching || generating || isEditable
                        ? styles.disabledButton
                        : ""
                    }`}
                    title="Select Model"
                  >
                    {/* <FontAwesomeIcon icon={faGlobe} /> */}
                    <CustomDropdown
                      onChange={(selectedOption) => {
                        setModel(selectedOption);
                        setLikeIcon(false);
                      }}
                      options={selectedModels}
                      placeholder={"Model"}
                      value={model}
                      text={"Model"}
                      disabled={generating || fetching || isEditable}
                    ></CustomDropdown>
                  </span>
                  <span
                    className={`${styles.inferenceIcon} ${
                      messageDisable || fetching || generating || isEditable
                        ? styles.disabledButton
                        : ""
                    }`}
                  >
                    {/* <FontAwesomeIcon icon={faHexagonNodes} /> */}
                    <AskAssistantDropdown
                      options={agentListDropdown.map((list) => ({
                        value: list.agentic_application_id,
                        label: list.agentic_application_name,
                      }))}
                      placeholder={"Agent"}
                      text={"Agent"}
                      value={agentSelectValue}
                      onChange={(value) => {
                        setAgentSelectValue(value);
                        setFeedback("");
                        setOldSessionId("");
                        setLikeIcon(false);
                      }}
                      isSearch={true}
                      disabled={generating || fetching || isEditable}
                    />
                  </span>
                </div>
                <div className={styles?.inferenceIconGroupRight}>
                  <span
                    className={`${styles.inferenceIcon} ${
                      messageDisable || fetching || generating || isEditable ||allOptionsSelected
                        ? styles.disabledButton
                        : ""
                    }`}
                    title="Verifier Settings"
                    onClick={handleIconClick}
                    style={{ cursor: "pointer" }}
                    // Optional styling
                  >
                    <FontAwesomeIcon icon={faScrewdriverWrench} />
                  </span>

                  {showVerifierSettings && (
                    <>
                      <div className={styles.popoverBox} ref={popoverRef}>
                        {!isShowIsHuman &&
                        (agentType === "react_agent" ||
                          agentType === REACT_AGENT) ? (
                          <div
                            className={`${styles.toogleToolVerifier} ${
                              isTool ? styles.selected : ""
                            }`}
                          >
                            <label>Tool Verifier</label>
                            <span className={styles.toogleData}>
                              <Toggle
                                onChange={handleToggle2}
                                value={toolInterrupt}
                                disabled={
                                  messageDisable ||
                                  generating ||
                                  fetching ||
                                  isEditable
                                }
                              />
                            </span>
                          </div>
                        ) : (
                          isShowIsHuman && (
                            <div className={styles.toogle2}>
                              {agentType === "MULTI_AGENT" || agentType === PLANNER_EXECUTOR_AGENT ||
                              agentType === "multi_agent" ? (
                                <>
                                  <div
                                    className={`${styles.toogleToolVerifier} ${
                                      isHuman ? styles.selected : ""
                                    }`}
                                  >
                                    <label>Plan Verifier</label>
                                    <span className={styles.toogleData}>
                                      <Toggle
                                        onChange={handleToggle}
                                        value={isHuman}
                                        disabled={
                                          messageDisable ||
                                          generating ||
                                          fetching ||
                                          isEditable
                                        }
                                      />
                                    </span>
                                  </div>
                                  <div
                                    className={`${styles.toogleToolVerifier} ${
                                      isTool ? styles.selected : ""
                                    }`}
                                  >
                                    <label>Tool Verifier</label>
                                    <span className={styles.toogleData}>
                                      <Toggle
                                        onChange={handleToggle2}
                                        value={toolInterrupt}
                                        disabled={
                                          messageDisable ||
                                          generating ||
                                          fetching ||
                                          isEditable
                                        }
                                      />
                                    </span>
                                  </div>
                                </>
                              ) : (
                                <>
                                  <div className={styles.toogleToolVerifier}>
                                    <label>Tool Verifier</label>
                                    <span className={styles.toogleData}>
                                      <Toggle
                                        onChange={handleToggle2}
                                        value={toolInterrupt}
                                        disabled={
                                          messageDisable ||
                                          generating ||
                                          fetching ||
                                          isEditable
                                        }
                                      />
                                    </span>
                                  </div>
                                </>
                              )}
                            </div>
                          )
                        )}
                      </div>
                    </>
                  )}
                  {!allOptionsSelected && (
                    <>
                      <span
                        className={`${styles.inferenceIcon} ${
                          fetching || generating ? styles.disabledButton : ""
                        }`}
                        onClick={handleNewChat}
                        title={"New Chat"}
                      >
                        <FontAwesomeIcon icon={faCommentMedical} />
                      </span>
                      {/* <div className={styles.relativeWrapper} ref={oldChatRef}>
                        <span
                          className={`${styles.inferenceIcon} ${
                            messageDisable ||
                            fetching ||
                            generating ||
                            allOptionsSelected ||
                            isEditable
                              ? styles.disabledButton
                              : ""
                          }`}
                          title="Old Chat"
                          onClick={toggleDropdown}
                        >
                          <FontAwesomeIcon icon={faChartPie} />
                        </span>

                        {isOldChatOpen && (
                          <div className={styles.popoverBox}>
                            <OldChatsHistory
                              onChange={() => {}}
                              data={oldChats}
                              agentSelectValue={agentSelectValue}
                              fetchOldChatsData={fetchOldChatsData}
                              fetchChatHistory={fetchChatHistory}
                              setOldSessionId={setOldSessionId}
                              isOpen={isOldChatOpen}
                              setIsOpen={setIsOldChatOpen}
                            />
                          </div>
                        )}
                      </div> */}
                    </>
                  )}
                  <span
                    className={`${styles.inferenceIcon} ${
                      messageDisable || fetching || generating || isEditable || allOptionsSelected
                        ? styles.disabledButton
                        : ""
                    }`}
                    onClick={handleFileClick}
                    title="Attach Files"
                  >
                    <FontAwesomeIcon icon={faPaperclip} />
                  </span>
                  <span
                    className={`${styles.inferenceIcon} ${
                      allOptionsSelected ||
                      fetching ||
                      messageDisable ||
                      messageData.length === 0
                        ? styles.disabledButton
                        : ""
                    }`}
                    title="Reset Chat"
                    onClick={(e) => {
                      if (
                        allOptionsSelected ||
                        fetching ||
                        messageData.length === 0
                      ) {
                        e.preventDefault();
                        return;
                      }
                      handleResetChat();
                    }}
                  >
                    <FontAwesomeIcon icon={faTrash} />
                  </span>
                  {/* <span
                    className={`${styles.inferenceIcon} ${
                      messageDisable || fetching || generating || isEditable || allOptionsSelected
                        ? styles.disabledButton
                        : ""
                    }`}
                    title={"Live Tracking"}
                    onClick={() => {
                      window.open(liveTrackingUrl, "_blank");
                    }}
                  >
                    <FontAwesomeIcon icon={faArrowTrendUp} />
                  </span> */}
                  

                  <button
                    onClick={sendUserMessage}
                    disabled={
                      generating ||
                      allOptionsSelected ||
                      fetching ||
                      feedBack === dislike ||
                      userChat.trim() === "" ||
                      isEditable
                    }
                    className={styles.sendIcon}
                  >
                    <SVGIcons
                      icon="ionic-ios-send"
                      fill="#007CC3"
                      width={20}
                      height={20}
                    />
                  </button>
                </div>
              </div>
            </div>
          {/* // )} */}
        </div>
      </div>
    </>
  );
};

export default AskAssistant;
