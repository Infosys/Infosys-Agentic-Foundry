import React, { useEffect, useRef, useState } from "react";
import styles from "../../css_modules/AskAssistant.module.css";
import MsgBox from "./MsgBox";
import {
  BOT,
  USER,
  APIs,
  likeMessage,
  dislike,
  branchInteruptValue,
  branchInteruptKey,
  CUSTOM_TEMPLATE,
  customTemplatId,
} from "../../constant";
import SVGIcons from "../../Icons/SVGIcons";
import {
  resetChat,
  getChatQueryResponse,
  getChatHistory,
  fetchNewChats,
} from "../../services/chatService";
import ToastMessage from "../commonComponents/ToastMessage";
import clearChat from "../../Assets/clearchat.png";
import useFetch from "../../Hooks/useAxios";
import Cookies from "js-cookie";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faPaperclip } from "@fortawesome/free-solid-svg-icons";
import { useGlobalComponent } from "../../Hooks/GlobalComponentContext.js";

import CustomDropdown from "../commonComponents/DropDowns/CustomDropdown"; // Keep this if you still need a model dropdown

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
  const [fetchedAgentSelectValue, setFetchedAgentSelectValue] = useState("");
  const [fetchedAgentType, setFetchedAgentType] = useState("");
  // New state to store the agent name
  const [agentApplicationName, setAgentApplicationName] = useState("ASK ASSISTANT");
  const [model, setModel] = useState("");
  const [feedBack, setFeedback] = useState("");
  const [fetching, setFetching] = useState(false);
  const [showToast, setShowToast] = useState(false);
  const [planData, setPlanData] = useState(null);
  const [showInput, setShowInput] = useState(false);
  const [oldChats, setOldChats] = useState([]);
  const [oldSessionId, setOldSessionId] = useState("");
  const [session, setSessionId] = useState("");

  useEffect(() => {
    let sessionId = localStorage.getItem("session_id");
    if (!sessionId) {
      sessionId = generateRandomSessionId();
      localStorage.setItem("session_id", sessionId);
    }
    setSessionId(sessionId);
  }, []);

  function generateRandomSessionId() {
    return "session-" + Math.random().toString(36).substr(2, 9);
  }

  const [selectedModels, setSelectedModels] = useState([]);
  const [toolInterrupt, setToolInterrupt] = useState(false);
  const [toolData, setToolData] = useState(null);
  const [loadingAgents, setLoadingAgents] = useState(true);
  const [isEditable, setIsEditable] = useState(false);

  const chatbotContainerRef = useRef(null);
  const [likeIcon, setLikeIcon] = useState(false);
  const [showInputSendIcon, setShowInputSendIcon] = useState(false);

  const { showComponent } = useGlobalComponent();
  let messageDisable = messageData.some((msg) => msg.message.trim() === "");

  useEffect(() => {
    window.addEventListener("resize", () => {
      const currentZoomPercentage = Math.floor(window.devicePixelRatio * 100);
      if (chatbotContainerRef.current) {
        if (currentZoomPercentage <= 75) {
          chatbotContainerRef.current.style.height = "86vh";
        } else if (currentZoomPercentage <= 80) {
          chatbotContainerRef.current.style.height = "85vh";
        } else if (currentZoomPercentage <= 90) {
          chatbotContainerRef.current.style.height = "83vh";
        } else if (currentZoomPercentage <= 100) {
          chatbotContainerRef.current.style.height = "82vh";
        } else if (currentZoomPercentage <= 110) {
          chatbotContainerRef.current.style.height = "80vh";
        } else if (currentZoomPercentage <= 125) {
          chatbotContainerRef.current.style.height = "77vh";
        } else if (currentZoomPercentage <= 150) {
          chatbotContainerRef.current.style.height = "72vh";
        } else if (currentZoomPercentage <= 175) {
          chatbotContainerRef.current.style.height = "67vh";
        }
      }
    });
  }, []);

  const { fetchData, postData } = useFetch();

  const msgContainerRef = useRef(null);
  const hasInitialized = useRef(false);

  const allOptionsSelected =
    fetchedAgentType !== CUSTOM_TEMPLATE
      ? fetchedAgentType === "" || fetchedAgentSelectValue === "" || model === ""
      : fetchedAgentType === "" || model === "";

  useEffect(() => {
    if (hasInitialized.current) return;
    fetchAgentsAndSetDefaults();
    fetchModels();
    hasInitialized.current = true;
  }, []);

  useEffect(() => {
    setMessageData([]);
    setShowInput(false);
    setFeedback("");
  }, [fetchedAgentType]);

  useEffect(() => {
    if (!allOptionsSelected) {
      fetchChatHistory();
    } else {
      setMessageData([]);
    }
  }, [model, fetchedAgentSelectValue, allOptionsSelected]);

  useEffect(() => {
    if (msgContainerRef.current) {
      msgContainerRef.current.scrollTop = msgContainerRef.current.scrollHeight;
    }
  }, [messageData]);

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
        fetchedAgentType === CUSTOM_TEMPLATE
          ? customTemplatId
          : fetchedAgentSelectValue,
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
        fetchedAgentType === CUSTOM_TEMPLATE
          ? customTemplatId
          : fetchedAgentSelectValue,
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
        fetchedAgentType === CUSTOM_TEMPLATE
          ? APIs.CUSTOME_TEMPLATE_QUERY
          : APIs.PLANNER;
      response = await postData(url, payload);
      setLastResponse(response);
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
        fetchedAgentType === CUSTOM_TEMPLATE
          ? customTemplatId
          : fetchedAgentSelectValue,
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
        fetchedAgentType === "META_AGENT"
          ? APIs.META_AGENT_QUERY
          : fetchedAgentType === "PLANNER_META_AGENT"
          ? APIs.PLANNER_META_AGENT_QUERY
          : APIs.REACT_MULTI_AGENT_QUERY;

      const response = await getChatQueryResponse(payload, url);
      setLastResponse(response);
      setMessageData(converToChatFormat(response) || []);
    }
    setGenerating(false);
    setFetching(false);
  };

  useEffect(() => {
    calculateHeight();
  }, [userChat]);

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

  const handleResetChat = async () => {
    const data = {
      session_id: oldSessionId !== "" ? oldSessionId : session,
      agent_id:
        fetchedAgentType !== CUSTOM_TEMPLATE
          ? fetchedAgentSelectValue
          : customTemplatId,
    };
    const response = await resetChat(data);
    if (response?.status === "success") {
      setMessageData([]);
    }
  };

  const fetchAgentsAndSetDefaults = async () => {
    try {
      setLoadingAgents(true);
      const data = await fetchData(APIs.GET_AGENTS_BY_DETAILS);
      if (data && data.length > 0) {
        const defaultAgent = data[0]; // Or your logic to pick a specific default agent
        setFetchedAgentType(defaultAgent.agentic_application_type);
        setFetchedAgentSelectValue(defaultAgent.agentic_application_id);
        // Set the agent name here
        setAgentApplicationName(defaultAgent.agentic_application_name);

        if (
          defaultAgent.agentic_application_type === "multi_agent" ||
          defaultAgent.agentic_application_type === "react_agent"
        ) {
          setIsShowIsHuman(true);
        } else {
          setIsShowIsHuman(false);
        }
        if (defaultAgent.agentic_application_type === CUSTOM_TEMPLATE) {
          setIsHuman(true);
        } else {
          setIsHuman(false);
        }
      } else {
        // Handle case where no agents are returned, revert to default title
        setAgentApplicationName("ASK ASSISTANT");
      }
    } catch (e) {
      console.error(e);
      setAgentApplicationName("ASK ASSISTANT"); // Fallback on error
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
        if (formattedModels.length > 0) {
          setModel(formattedModels[0].value);
        }
      } else {
        setSelectedModels([]);
      }
    } catch (e) {
      console.error(e);
      setSelectedModels([]);
    }
  };

  const handleNewChat = async () => {
    const sessionId = await fetchNewChats(loggedInUserEmail);
    setOldSessionId("");
    setSessionId(sessionId);
    fetchChatHistory(sessionId);
  };

  const textareaRef = useRef(null);

  const resetHeight = () => {
    const textarea = textareaRef.current;
    textarea.style.height = "40px";
  };

  const calculateHeight = () => {
    const textarea = textareaRef.current;
    textarea.style.height = "40px";
    textarea.style.height = `${Math.min(textarea.scrollHeight, 80)}px`;
  };

  const handleChange = (e) => {
    setUserChat(e.target.value);
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
        <div className={styles.pageHeader}></div>
        <div className={styles.container} ref={chatbotContainerRef}>
          {/* Header */}
          <div className={styles.headerContainer}>
            {/* Use the new state variable here */}
            <h1>{agentApplicationName}</h1>
            <div className={styles.rightSection}>
              <div className={styles.headerDropdowns}>
                <CustomDropdown
                  onChange={(selectedOption) => {
                    setModel(selectedOption);
                    setLikeIcon(false);
                  }}
                  options={selectedModels}
                  placeholder={"Model"}
                  value={model}
                  disabled={generating || fetching || isEditable}
                ></CustomDropdown>

                <button
                  disabled={
                    allOptionsSelected || fetching || messageData.length === 0
                  }
                  title={"Reset Chat"}
                  className={styles.resetButton}
                  onClick={handleResetChat}
                >
                  <img src={clearChat} alt="clearChat" />
                </button>

                <button className={styles.liveTracking} onClick={handleNewChat}>
                  New Chat
                </button>
                
              </div>
            </div>
          </div>

          {/* message container */}
          <div className={styles.messageContainer} ref={msgContainerRef}>
            {showToast && (
              <ToastMessage
                message={likeMessage}
                showToast={showToast}
                setShowToast={setShowToast}
              />
            )}
            <MsgBox
              styles={styles}
              messageData={messageData}
              generating={generating}
              agentType={fetchedAgentType}
              feedBack={feedBack}
              setFeedback={setFeedback}
              setMessageData={setMessageData}
              agentSelectValue={fetchedAgentSelectValue}
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
              selectedOption={fetchedAgentType}
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
            />
          </div>
          <div className={styles.messageInputContainer}>
            {!allOptionsSelected && (
              <div className={styles.chatHistoryContainer}>
                
              </div>
            )}

            {feedBack !== dislike && feedBack !== "no" && (
              <div className={styles.messageInput}>
                <div className={styles.textareaContainer}>
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
                      isEditable
                    }
                  ></textarea>
                  <div onClick={handleFileClick} className={styles.fileIcon}>
                    <FontAwesomeIcon icon={faPaperclip} />
                  </div>
                </div>
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
                    width={28}
                    height={28}
                  />
                </button>
              </div>
            )}
          </div>
        </div>
      </div>
    </>
  );
};

export default AskAssistant;