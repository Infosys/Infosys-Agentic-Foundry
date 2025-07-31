import React, { useEffect, useRef, useState } from "react";
import styles from "./AskAssistant2.module.css";
import ChatBubble from "./ChatBubble";
import ChatInput from "./ChatInput";
import PlaceholderScreen from "./PlaceholderScreen";
import FeedbackModal from "./FeedbackModal";
import FileUploadModal from "./FileUploadModal";
import ChatHistorySlider from "./ChatHistorySlider";
import { BOT, USER, APIs, customTemplatId, META_AGENT, MULTI_AGENT, REACT_AGENT, PLANNER_META_AGENT, CUSTOM_TEMPLATE, liveTrackingUrl, } from "../../constant.js";
import { resetChat, getChatQueryResponse, getChatHistory, fetchOldChats, fetchNewChats, } from "../../services/chatService.js";
import ToastMessage from "../commonComponents/ToastMessage.jsx";
import Cookies from "js-cookie";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faSpinner } from "@fortawesome/free-solid-svg-icons";
import useFetch from '../../Hooks/useAxios';

const AskAssistant2 = () => {
  const loggedInUserEmail = Cookies.get("email");
  const session_id = Cookies.get("session_id");
  
  // Chat states
  const [messages, setMessages] = useState([]);
  const [isGenerating, setIsGenerating] = useState(false);
  const [isInitialized, setIsInitialized] = useState(false);
  
  // Form states
  const [agentType, setAgentType] = useState("");
  const [selectedModel, setSelectedModel] = useState("");
  const [selectedAgent, setSelectedAgent] = useState("");
  const [userInput, setUserInput] = useState("");
  
  // Settings states
  const [isHumanVerifierEnabled, setIsHumanVerifierEnabled] = useState(false);
  const [isToolVerifierEnabled, setIsToolVerifierEnabled] = useState(false);
  
  // Modal states
  const [showFeedbackModal, setShowFeedbackModal] = useState(false);
  const [showFileUploadModal, setShowFileUploadModal] = useState(false);
  const [showChatHistory, setShowChatHistory] = useState(false);
  const [selectedMessageForFeedback, setSelectedMessageForFeedback] = useState(null);
  
  // Data states
  const [agentsListData, setAgentsListData] = useState([]);
  const [agentListDropdown, setAgentListDropdown] = useState([]);
  const [modelsListData, setModelsListData] = useState([]);
  const [oldChats, setOldChats] = useState([]);
  const [session, setSessionId] = useState(session_id);
  
  // UI states
  const [showToast, setShowToast] = useState(false);
  const [toastMessage, setToastMessage] = useState("");
  const [toastType, setToastType] = useState("success");
  
  const chatContainerRef = useRef(null);
  const messagesEndRef = useRef(null);

  // Check if all required fields are selected
  const isFormValid = agentType && selectedModel && selectedAgent;

  const { fetchData, postData } = useFetch();

  const hasInitialized = useRef(false);
  // Initialize component
  useEffect(() => {
    if (hasInitialized.current) return; // Prevent re-initialization
    hasInitialized.current = true;
    initializeComponent();
    fetchOldChatsData();
  }, []);

  // Fetch old chats when agentType, selectedModel, or selectedAgent changes
  useEffect(() => {
    if (isFormValid) {
      fetchOldChatsData();
    } else {
      setOldChats([]);
    }
  }, [agentType, selectedModel, selectedAgent, isFormValid]);

  // Auto scroll to bottom when new messages arrive
  useEffect(() => {
    scrollToBottom();
  }, [messages, isGenerating]);

  const fetchAgents = async () => {
    try {
      // setLoadingAgents(true);
      const data = await fetchData(APIs.GET_AGENTS_BY_DETAILS);
      setAgentsListData(data);
    } catch (e) {
      console.error(e);
    } finally {
      // setLoadingAgents(false);
    }
  };

  // Filter and populate agents list based on selected agent type
  useEffect(() => {
    setSelectedAgent("");
    if (!agentType) return;
    const tempList = agentsListData?.filter(
      list => list.agentic_application_type === agentType
    );
    setAgentListDropdown(tempList);
  }, [agentType, agentsListData]);
  
  const formatModelLabel = (model) => {
    return model
      .replace(/[-_]/g, ' ')                // Replace dashes with spaces
      .replace(/\b([a-z])/g, c => c.toUpperCase()) // Capitalize first letter of each word
      .replace(/\bGpt(\d)/i, 'Gpt$1')    // Ensure "Gpt" stays as "Gpt"
      .replace(/\b(\d+)k\b/i, (m, p1) => `${p1}K`); // Capitalize 'k' in '8k'
  };

  const fetchModels = async () => {
    try {
      const data = await fetchData(APIs.GET_MODELS);
      if (data?.models && Array.isArray(data.models)) {
        const formattedModels = data.models.map((model) => ({
          label: formatModelLabel(model),
          value: model,
        }));
        setModelsListData(formattedModels);
      } else {
        setModelsListData([]);
      }
    } catch (e) {
      console.error(e);
      setModelsListData([]);
    }
  };

  // Initialize agents and models data
  const initializeComponent = async () => {
    try {
      fetchAgents();
      fetchModels();
    } catch (error) {
      console.error("Error initializing component:", error);
      showToastMessage("Error loading data", "error");
    }
  };

  // Scroll to bottom of chat
  const scrollToBottom = () => {
    // messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
    if (chatContainerRef.current) {
      chatContainerRef.current.scrollTop = chatContainerRef.current.scrollHeight;
    }
  };  
  
  // Show welcome message when all fields are selected
  useEffect(() => {
    if (isFormValid && !isInitialized) {
      const welcomeMessage = getWelcomeMessage();
      setMessages([{
        id: Date.now(),
        type: BOT,
        content: welcomeMessage,
        timestamp: new Date(),
        agentType: agentType,
        steps: getSampleSteps(agentType), // Add sample steps here
        tools: ['Sample','tools','list','goes','here'],
        isWelcomeMessage: true, // Flag to identify welcome messages
      }]);
      setIsInitialized(true);
    }
  }, [isFormValid, isInitialized, agentType, selectedAgent]);
  
  // Update welcome message when agent configuration changes
  useEffect(() => {
    if (isInitialized && isFormValid && messages.length > 0) {
      const welcomeMessage = getWelcomeMessage();
      setMessages(prevMessages => {
        const updatedMessages = [...prevMessages];
        if (updatedMessages.length > 0 && updatedMessages[0].type === BOT) {
          updatedMessages[0] = {
            ...updatedMessages[0],
            content: welcomeMessage,
            agentType: agentType,
            timestamp: new Date(),
            steps: getSampleSteps(agentType), // Update steps when agent changes
            tools: ['Sample','tools','list','goes','here','2'],
            isWelcomeMessage: true, // Flag to identify welcome messages
          };
        }
        return updatedMessages;
      });
    }
  }, [agentType, selectedModel, selectedAgent, isInitialized, isFormValid]);
  
  // Get welcome message based on selected agent
  const getWelcomeMessage = () => {
    const agentName = selectedAgent.agentic_application_name || "AI Assistant";
    const modelInfo = selectedModel ? ` using ${selectedModel}` : "";
    
    switch (agentType) {
      case META_AGENT:
        return `Hello! I'm ${agentName}${modelInfo}, your Meta Agent. I can coordinate multiple specialized agents to help you with complex tasks. What would you like to accomplish today?`;
      case MULTI_AGENT:
        return `Hi there! I'm ${agentName}${modelInfo}, your Multi-Agent assistant. I can work with a team of specialized agents to tackle your challenges. How can we help you?`;
      case REACT_AGENT:
        return `Welcome! I'm ${agentName}${modelInfo}, your ReAct Agent. I can reason and act to solve problems step by step. What task would you like me to help you with?`;
      default:
        return `Hello! I'm ${agentName}${modelInfo}, your AI assistant. I'm here to help you with your questions and tasks. How can I assist you today?`;
    }
  };

  // Add sample steps function
  const getSampleSteps = (agentType) => {
    switch (agentType) {
      case 'META_AGENT':
        return [
          "🔍 **Analyzing Request**: Understanding the complexity and requirements of your task",
          "🧠 **Agent Selection**: Identifying the best specialized agents for this task",
          "📋 **Task Decomposition**: Breaking down the task into manageable components",
          "🔄 **Coordination**: Managing communication between different agents",
          "✅ **Quality Assurance**: Reviewing and validating the combined results"
        ];
      case 'MULTI_AGENT':
        return [
          "👥 **Team Assembly**: Gathering the right agents for collaborative work",
          "📊 **Workload Distribution**: Assigning specific tasks to each agent",
          "🔄 **Parallel Processing**: Multiple agents working simultaneously",
          "🔗 **Result Integration**: Combining outputs from all agents",
          "🎯 **Final Optimization**: Ensuring coherent and complete solution"
        ];
      case 'REACT_AGENT':
        return [
          "🤔 **Reasoning**: Analyzing the problem and planning approach",
          "🔍 **Information Gathering**: Collecting relevant data and context",
          "⚡ **Action Execution**: Performing the necessary steps to solve the problem",
          "📝 **Result Evaluation**: Checking if the action achieved the desired outcome",
          "🔄 **Iterative Refinement**: Adjusting approach based on results"
        ];
      default:
        return [
          "📥 **Input Processing**: Understanding and parsing your request",
          "🧠 **Analysis**: Applying AI models to generate insights",
          "🔧 **Solution Generation**: Creating the appropriate response",
          "✅ **Validation**: Ensuring the response meets quality standards"
        ];
    }
  };

  // Handle form submission
  const handleSubmitMessage = async () => {
  // Validate input and form
  if (!userInput.trim() || !isFormValid || isGenerating) return;

  setIsGenerating(true);

  // Add user message to chat
  setMessages(prev => [
    ...prev,
    {
      id: Date.now(),
      type: USER,
      content: userInput.trim(),
      timestamp: new Date()
    }
  ]);
  setUserInput("");

  // Build payload for API
  const payload = {
    agentic_application_id:
      agentType === CUSTOM_TEMPLATE ? customTemplatId : selectedAgent.agentic_application_id,
    query: userInput.trim(),
    session_id: session,
    model_name: selectedModel,
    reset_conversation: false,
    interrupt_flag: !!isToolVerifierEnabled,
  };

  // Select API endpoint
  let apiUrl = APIs.REACT_MULTI_AGENT_QUERY;
  if (agentType === META_AGENT) apiUrl = APIs.META_AGENT_QUERY;
  else if (agentType === PLANNER_META_AGENT) apiUrl = APIs.PLANNER_META_AGENT_QUERY;

  try {
    // Human-in-the-loop support
    if (isHumanVerifierEnabled) {
      await sendHumanInLoop("", "", userInput.trim());
      // Optionally add a message or feedback here
    } else {
      const response = await getChatQueryResponse(payload, apiUrl);
      if (!response) {
        showToastMessage("Internal Server Error", "error");
        return;
      }
      // Convert response to chat format if needed
      let tempArray = [];
      tempArray.push(response.executor_messages[response.executor_messages.length - 1].agent_steps.replace(/\\n/g, '\n').replace(/\\`\\`\\`/g, '```'));
      setMessages(prev => [
        ...prev,
        {
          id: Date.now() + 1,
          type: BOT,
          content: response.response || "I understand your request. Let me work on that for you.",
          timestamp: new Date(),
          agentType: agentType,
          steps: tempArray || [
            "🔍 **Request Analysis**: Understanding your specific question",
            "🧠 **Knowledge Retrieval**: Accessing relevant information from my training",
            "⚙️ **Processing**: Applying reasoning and problem-solving techniques",
            "📝 **Response Formulation**: Crafting a comprehensive and helpful answer",
            "✅ **Quality Check**: Ensuring accuracy and relevance of the response"
          ],
          tools: response.tools || ['Sample','tools','list','goes','here','1'],
          executionDetails: response.executionDetails || {},
        }
      ]);
    }
  } catch (error) {
    console.error("Error getting response:", error);
    setMessages(prev => [
      ...prev,
      {
        id: Date.now() + 1,
        type: BOT,
        content: "I apologize, but I encountered an error while processing your request. Please try again.",
        timestamp: new Date(),
        agentType: agentType,
        steps: [
          "❌ **Error Detected**: An issue occurred during processing",
          "🔄 **Recovery Attempt**: Trying to handle the error gracefully",
          "📝 **Error Logging**: Recording the issue for improvement",
          "💡 **User Notification**: Informing you about the situation"
        ],
        tools: ['Error Handler', 'Logging System'],
        isError: true
      }
    ]);
    showToastMessage("Error processing your request", "error");
  } finally {
    setIsGenerating(false);
  }
};

  // Handle feedback submission
  const handleFeedbackSubmit = async (messageId, feedback, rating) => {
    try {
      // Submit feedback to API
      await fetch('/api/feedback', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          messageId,
          feedback,
          rating,
          sessionId: session,
          userEmail: loggedInUserEmail
        })
      });
      
      showToastMessage("Thank you for your feedback!", "success");
      setShowFeedbackModal(false);
      setSelectedMessageForFeedback(null);
      
    } catch (error) {
      console.error("Error submitting feedback:", error);
      showToastMessage("Error submitting feedback", "error");
    }
  };

  const sendHumanInLoop = async (isApprove = "", feedBack = "", userText="") => {
    // const payload = {
    //   agentic_application_id:
    //     agentType === CUSTOM_TEMPLATE ? customTemplatId : agentSelectValue,
    //   query: userText,
    //   session_id: oldSessionId !== "" ? oldSessionId : session,
    //   model_name: model,
    //   reset_conversation: false,
    //   ...(isApprove !== "" && { approval: isApprove }),
    //   ...(feedBack !== "" && { feedback: feedBack }),
    //   ...(toolInterrupt ? { interrupt_flag: true } : { interrupt_flag: false }),
    // };
    // let response;
    // try {
    //   const url =
    //     agentType === CUSTOM_TEMPLATE
    //       ? APIs.CUSTOME_TEMPLATE_QUERY
    //       : APIs.PLANNER;
    //   response = await postData(url, payload);
    //   setLastResponse(response);
    //   setPlanData(response?.plan);
    //   setMessageData(converToChatFormat(response) || []);
    // } catch (err) {
    //   console.error(err);
    // }
    return "response";
  };

  // Handle message regeneration
  const handleRegenerateMessage = async (messageId) => {
    const messageIndex = messages.findIndex(msg => msg.id === messageId);
    if (messageIndex === -1) return;

    const previousUserMessage = messages[messageIndex - 1];
    if (!previousUserMessage || previousUserMessage.type !== USER) return;

    setIsGenerating(true);

    try {
      const response = await getChatQueryResponse({
        message: previousUserMessage.content,
        agentType,
        selectedModel,
        agent: selectedAgent,
        sessionId: session,
        humanVerifier: isHumanVerifierEnabled,
        toolVerifier: isToolVerifierEnabled
      });

      const newBotMessage = {
        ...messages[messageIndex],
        content: response.message || "Here's a regenerated response for you.",
        steps: response.steps || [],
        tools: response.tools || [],
        executionDetails: response.executionDetails || {},
        timestamp: new Date()
      };

      const updatedMessages = [...messages];
      updatedMessages[messageIndex] = newBotMessage;
      setMessages(updatedMessages);
      
    } catch (error) {
      console.error("Error regenerating message:", error);
      showToastMessage("Error regenerating response", "error");
    } finally {
      setIsGenerating(false);
    }
  };

  // Handle new chat
  const handleNewChat = async () => {
    try {
      await resetChat(session);
      setMessages([]);
      setIsInitialized(false);
      showToastMessage("New chat started", "success");
    } catch (error) {
      console.error("Error starting new chat:", error);
      showToastMessage("Error starting new chat", "error");
    }
  };

  // Handle delete chat
  const handleDeleteChat = async () => {
    if (window.confirm("Are you sure you want to delete this chat?")) {
      try {
        await fetch(`/api/chats/${session}`, { method: 'DELETE' });
        setMessages([]);
        setIsInitialized(false);
        showToastMessage("Chat deleted successfully", "success");
      } catch (error) {
        console.error("Error deleting chat:", error);
        showToastMessage("Error deleting chat", "error");
      }
    }
  };

  // Show toast message
  const showToastMessage = (message, type = "success") => {
    setToastMessage(message);
    setToastType(type);
    setShowToast(true);
    setTimeout(() => setShowToast(false), 3000);
  };

  const [isCanvasVisible, setIsCanvasVisible] = useState(false);
  const [canvasWidth, setCanvasWidth] = useState(400);

  // Handle live tracking
  const handleLiveTracking = () => {
    window.open(liveTrackingUrl, '_blank');
  };

  const fetchOldChatsData = async () => {
    const data = {
      user_email: loggedInUserEmail,
      agent_id: selectedAgent.agentic_application_id,
    };
    const reseponse = await fetchOldChats(data);
    const oldChats = reseponse;
    let temp = [];
    for (let key in oldChats) {
      temp.push({ ...oldChats[key][0], session_id: key, messageCount: oldChats[key].length });
    }
    setOldChats(temp);
  };

  return (
    <div className={styles.container}>
      {/* Main Chat Area */}
      <div className={styles.chatWrapper}>
        <div 
          className={`${styles.bubbleAndInput} ${isCanvasVisible ? styles.withCanvas : ''}`}
          style={{
            width: isCanvasVisible ? `calc(100% - ${canvasWidth}px)` : '100%',
            transition: 'width 0.3s ease-in-out'
          }}
        >
          {/* Chat Bubbles Container */}
          <div className={styles.chatBubblesWrapper} ref={chatContainerRef}>
            {!isFormValid ? (
              <PlaceholderScreen 
                agentType={agentType}
                model={selectedModel}
                selectedAgent={selectedAgent}
              />
            ) : (
              <div className={styles.messagesWrapper}>
                <div className={styles.messagesContainer}>
                  {messages.slice().reverse().map((message) => (
                    <ChatBubble
                      key={message.id}
                      message={message}
                      onFeedback={(messageId) => {
                        setSelectedMessageForFeedback(messageId);
                        setShowFeedbackModal(true);
                      }}
                      onRegenerate={handleRegenerateMessage}
                      isGenerating={isGenerating && message.id === messages[messages.length - 1]?.id}
                    />
                  ))}
                
                <div ref={messagesEndRef} />
                </div>
                {/* Generating indicator */}
                  {isGenerating && (
                    <div className={styles.generatingIndicator}>
                      <div className={styles.generatingContent}>
                        <FontAwesomeIcon icon={faSpinner} spin className={styles.spinnerIcon} />
                        <span>Generating response...</span>
                      </div>
                    </div>
                  )}
              </div>
            )}
          </div>

          <div className={styles.chatSection}>
              {/* Chat Input Section */}
              <ChatInput
                agentType={agentType}
                setAgentType={setAgentType}
                selectedModel={selectedModel}
                setSelectedModel={setSelectedModel}
                selectedAgent={selectedAgent}
                setSelectedAgent={setSelectedAgent}
                userInput={userInput}
                setUserInput={setUserInput}
                agentListDropdown={agentListDropdown}
                modelsListData={modelsListData}
                isFormValid={isFormValid}
                isGenerating={isGenerating}
                isHumanVerifierEnabled={isHumanVerifierEnabled}
                setIsHumanVerifierEnabled={setIsHumanVerifierEnabled}
                isToolVerifierEnabled={isToolVerifierEnabled}
                setIsToolVerifierEnabled={setIsToolVerifierEnabled}
                onSubmit={handleSubmitMessage}
                onNewChat={handleNewChat}
                onDeleteChat={handleDeleteChat}
                onLiveTracking={handleLiveTracking}
                onFileUpload={() => setShowFileUploadModal(true)}
                onShowHistory={() => setShowChatHistory(true)}
              />
          </div>
        </div>        
      </div>
      {/* Modals */}
      {showFeedbackModal && (
        <FeedbackModal
          messageId={selectedMessageForFeedback}
          onSubmit={handleFeedbackSubmit}
          onClose={() => {
            setShowFeedbackModal(false);
            setSelectedMessageForFeedback(null);
          }}
        />
      )}

      {showFileUploadModal && (
        <FileUploadModal
          onClose={() => setShowFileUploadModal(false)}
          sessionId={session}
        />
      )}

      {showChatHistory && (
        <ChatHistorySlider
          chats={oldChats}
          onClose={() => setShowChatHistory(false)}
          onSelectChat={(chatId) => {
            // Load selected chat
            setShowChatHistory(false);
          }}
        />
      )}

      {/* Toast Message */}
      {showToast && (
        <ToastMessage
          message={toastMessage}
          type={toastType}
          onClose={() => setShowToast(false)}
        />
      )}
    </div>
  );
};

export default AskAssistant2;