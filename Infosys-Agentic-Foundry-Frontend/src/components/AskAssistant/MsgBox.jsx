import { useEffect, useState, useId, useRef } from "react";
import { useMessage } from "../../Hooks/MessageContext";
import PlaceholderScreen from "./PlaceholderScreen";
import DOMPurify from "dompurify";
import SVGIcons from "../../Icons/SVGIcons";
import {
  BOT,
  CUSTOM_TEMPLATE,
  HYBRID_AGENT,
  META_AGENT,
  MULTI_AGENT,
  PLANNER_EXECUTOR_AGENT,
  REACT_CRITIC_AGENT,
  USER,
  REACT_AGENT,
  like,
  dislike,
  regenerate,
  sessionId,
  feedBackMessage,
  APIs,
  PLANNER_META_AGENT,
} from "../../constant";
import LoadingChat from "./LoadingChat";
import AccordionPlanSteps from "../commonComponents/Accordions/AccordionPlanSteps";
import parse from "html-react-parser";
import ToolCallFinalResponse from "./ToolCallFinalResponse";
import { useChatServices } from "../../services/chatService";
import chatBubbleCss from "./ChatBubble.module.css";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faUser, faRobot, faThumbsUp, faThumbsDown, faRotateRight, faChevronDown } from "@fortawesome/free-solid-svg-icons";
import { formatResponseTimeSeconds } from "../../utils/timeFormatter";
import ExecutionStepsList from "./ExecutionStepsList";

const JSON_INDENT = 2;
const FEEDBACK_TIMEOUT_MS = 5000;
const SLICE_LAST_TWO = -2;

const MsgBox = ({ nodes, currentNodeIndex, ...props }) => {
  const baseId = useId();
  const { addMessage } = useMessage();
  const [feedBackText, setFeedBackText] = useState("");
  const [close, setClose] = useState(false);
  const [loadingText, setLoadingText] = useState("");

  // Track previous message to detect changes (for plan visibility)
  const [previousMessage, setPreviousMessage] = useState(null);

  // Dropdown style summary for nodes (first → last) controlling visibility of full list
  // CHANGED: default from true -> false so it starts closed
  const [showNodeDetails, setShowNodeDetails] = useState(false);

  // Refs for auto-scrolling execution steps lists
  const executionStepsRef = useRef(null);
  const executionStepsInitialRef = useRef(null);
  const executionStepsInlineRef = useRef(null);
  const sseNodeListRef = useRef(null);

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
    isCanvasEnabled,
    isContextEnabled,
    onlineEvaluatorFlag,
    mentionedAgent,
    planVerifierText,
    useValidator,
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

  // Track the index of the message whose plan was approved via "Good response" from feedbackWrapper-1
  // null = no plan approved, number = index of the approved message (to hide only that message's feedbackWrapper-3)
  const [planApprovedIndex, setPlanApprovedIndex] = useState(null);

  const [sendIconShow, setSendIconShow] = useState(false);

  // New state to track expanded/collapsed nodes
  const [expandedNodes, setExpandedNodes] = useState({});

  // Toggle function to expand/collapse individual nodes
  const toggleNodeExpand = (nodeIndex) => {
    setExpandedNodes((prev) => ({
      ...prev,
      [nodeIndex]: !prev[nodeIndex],
    }));
  };

  // Consolidated feedback handler (like/dislike/regenerate)
  const handleFeedBack = (value, sessionId) => {
    setFeedback(value);

    if (value === dislike || value === "no") {
      setLoadingText("Loading...");
      setClose(true);
    } else {
      // For like and regenerate, show loading state
      setGenerateButton(true);
      setLoadingText(value === regenerate ? "Re-generating" : "Generating");
    }

    // Call sendFeedback for like and regenerate (not for dislike - that shows input first)
    if (value !== dislike) {
      sendFeedback(value, "", sessionId);
    }
    // Note: setGenerateButton(false) is called inside sendFeedback after API response
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
        mentioned_agentic_application_id: mentionedAgent && mentionedAgent.agentic_application_id ? mentionedAgent.agentic_application_id : null,
        validator_flag: useValidator,
      };

      const resp = await storeMemoryExample(payload);
      if (resp && !isDeletingChat) {
        // Show success or error popup based on response.success
        if (resp.success) {
          addMessage(resp?.message || "Successfully stored interaction as positive example", "success");
        } else {
          addMessage(resp?.message || "Failed to store feedback", "error");
        }
      }
    } catch (err) {
      addMessage("Failed to submit feedback", "error");
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
        mentioned_agentic_application_id: mentionedAgent && mentionedAgent.agentic_application_id ? mentionedAgent.agentic_application_id : null,
        validator_flag: useValidator,
      };

      const resp = await storeMemoryExample(payload);
      if (resp && !isDeletingChat) {
        // Show success or error popup based on response.success
        if (resp.success) {
          addMessage(resp?.message || "Successfully stored interaction as negative example", "success");
        } else {
          addMessage(resp?.message || "Failed to store feedback", "error");
        }
      }
    } catch (err) {
      addMessage("Failed to submit feedback", "error");
    } finally {
      setProcessingFeedback((p) => {
        const copy = { ...p };
        delete copy[idx];
        return copy;
      });
    }
  };

  const onMsgEdit = (data) => {
    const jsonString = data?.toolcallData?.additional_details?.[0]?.additional_kwargs?.tool_calls?.[0]?.function?.arguments || "";
    try {
      const obj = typeof jsonString !== "object" ? JSON.parse(jsonString || "{}") : jsonString;
      setParsedValues(obj);
    } catch {
      setParsedValues({});
    }
    props.setLikeIcon(true);
    setIsEditable(true);
    setSendIconShow(true);
  };
  const handlePlanFeedBack = async (feedBack, userText) => {
    setClose(feedBack === "no" ? true : false);
    setFeedback(feedBack);
    setgenerateFeedBackButton(true);
    setLoadingText(feedBack === "no" ? "Loading..." : "Generating");
    setFetching(true);

    // Set the index of the last bot message when user approves plan to hide only that message's feedbackWrapper-3
    if (feedBack === "yes") {
      // The plan is always on the last bot message
      const lastBotIndex = messageData.length - 1;
      setPlanApprovedIndex(lastBotIndex);
    }

    try {
      // Make API call with is_plan_approved: "yes" or "no"
      // For "no", don't pass feedback text yet - just the approval status
      await sendHumanInLoop(feedBack, "", userText);

      if (feedBack === "no") {
        // After API response, show the feedback input section
        setShowInput(true);
      }
    } finally {
      setFetching(false);
      setgenerateFeedBackButton(false);
      // Reset the plan approved index when done
      setPlanApprovedIndex(null);
    }
  };

  const handlePlanDislikeFeedBack = async (userText) => {
    setShowInput(false); // Hide textarea immediately
    setLoadingText("Re-generating");
    setFetching(true);
    setgenerateFeedBackButton(true); // Show loading indicator
    try {
      const response = await sendHumanInLoop(feedBack, feedBackText, userText);
      setFeedBackText("");
      // Reset all feedback-related states so new plan shows with fresh feedback buttons
      setFeedback("");
      setClose(false);
      setShowInput(false);
      setGenerateButton(false);
      if (response) {
        setMessageData(converToChatFormat(response) || []);
      }
    } finally {
      setFetching(false);
      setLoadingText("");
      setgenerateFeedBackButton(false); // Hide loading indicator
    }
  };

  // Enhanced mapping with multi-level fallbacks including plan verifier and parts/tool outputs.
  const converToChatFormat = (chatHistory) => {
    const chats = [];
    if (!chatHistory) return chats;

    // Prefer streaming-captured planVerifierText prop if final response root no longer carries raw.plan_verifier
    const localPlanVerifierText =
      chatHistory?.raw?.plan_verifier || chatHistory?.plan_verifier || (typeof chatHistory?.plan_verifier === "string" ? chatHistory.plan_verifier : "") || planVerifierText || "";

    chatHistory?.executor_messages?.forEach((item, index) => {
      // USER bubble
      chats.push({
        type: USER,
        message: item?.user_query,
        debugExecutor: item?.additional_details,
      });

      // Build bot message using existing fallbacks
      let botMessage = item?.final_response || item?.response || item?.message || "";

      let synthesized = null;
      if (item?.tools_used && !(Array.isArray(item?.additional_details) && item.additional_details.length > 0)) {
        try {
          const toolCalls = Object.entries(item.tools_used).map(([id, tu]) => {
            const argsObj = tu?.arguments ?? tu?.args ?? {};
            const serialized = typeof argsObj === "string" ? argsObj : JSON.stringify(argsObj || {});
            return {
              id,
              function: { name: tu?.name || tu?.tool_name || id, arguments: serialized },
              output: tu?.output ?? tu?.tool_output ?? null,
            };
          });
          synthesized = [{ additional_kwargs: { tool_calls: toolCalls } }];
        } catch (e) {
          synthesized = null;
        }
      }

      const toolcallData = { ...(item || {}), ...(synthesized ? { additional_details: synthesized } : {}) };

      // Tool interrupt case: suppress bot message if tool calls exist
      if (toolInterrupt && Array.isArray(toolcallData.additional_details) && toolcallData.additional_details.length > 0) {
        botMessage = "";
      } else {
        // Plan verifier fallback when empty and human verifier active
        if ((!botMessage || botMessage.trim() === "") && isHuman && localPlanVerifierText) {
          botMessage = localPlanVerifierText;
        }

        // Parts fallback
        if ((!botMessage || botMessage.trim() === "") && Array.isArray(item?.parts) && item.parts.length > 0) {
          const partsText = item.parts.map((p) => (p?.data?.content || p?.text || p?.content || "").trim()).filter((t) => t.length > 0);
          if (partsText.length > 0) botMessage = partsText.join("\n\n");
        }

        // Tool output fallback (first tool)
        if ((!botMessage || botMessage.trim() === "") && item?.tools_used) {
          const firstTool = Object.values(item.tools_used)[0];
          if (firstTool?.output) botMessage = String(firstTool.output);
        }
      }

      chats.push({
        type: BOT,
        message: botMessage,
        toolcallData: toolcallData,
        userText: item?.user_query || chatHistory?.query || "",
        steps: JSON.stringify(item?.agent_steps, null, JSON_INDENT),
        debugExecutor: item?.additional_details,
        // ...(index === chatHistory?.executor_messages?.length - 1 &&
        //   (!botMessage || botMessage.trim() === "") &&
        //   !(toolInterrupt && Array.isArray(toolcallData?.additional_details) && toolcallData.additional_details.length > 0) && { plan: chatHistory?.plan }),
        // Always attach plan if present in response
        ...(index === chatHistory?.executor_messages?.length - 1 && chatHistory?.plan ? { plan: chatHistory.plan } : {}),
        parts: item?.parts || [],
        show_canvas: item?.show_canvas || false,
        plan_verifier: Boolean(localPlanVerifierText),
        response_time: item?.response_time || chatHistory?.response_time || null,
      });
    });

    // Edge case: only plan verifier prompt, no executor messages
    if ((!chatHistory?.executor_messages || chatHistory.executor_messages.length === 0) && localPlanVerifierText) {
      chats.push({ type: BOT, message: localPlanVerifierText, plan_verifier: true });
    }

    return chats;
  };

  const sendFeedback = async (feedBack, user_feedback = "", session_Id) => {
    setgenerateFeedBackButton(true);
    // setFetching(true);
    if (feedBack === "no") {
      setLoadingText("Loading");
    } else if (feedBack === regenerate || feedBack === dislike) {
      setLoadingText("Re-generating");
    } else {
      setLoadingText("Generating");
    }
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
      mentioned_agentic_application_id: mentionedAgent && mentionedAgent.agentic_application_id ? mentionedAgent.agentic_application_id : null,
    };
    // Reset feedback state to close the feedback section
    if (feedBack === dislike) {
      setFeedback("");
      setClose(false);
    }
    const response = await fetchFeedback(data, feedBack);
    if (feedBack !== like) {
      setMessageData(converToChatFormat(response) || []);
    }

    // Show toast for like feedback using useMessage hook
    if (response && !isDeletingChat && feedBack === like) {
      addMessage(response?.message || "Thanks for the feedback!", "success");
    }
    setFetching(false);
    setgenerateFeedBackButton(false);
    setGenerateButton(false);
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

  // Update previousMessage when messageData changes
  useEffect(() => {
    if (!messageData || messageData.length === 0) {
      setPreviousMessage(null);
      return;
    }

    // Get the last bot message
    const lastBotMessage = [...messageData].reverse().find((m) => m?.type === BOT);
    if (lastBotMessage) {
      const currentMsg = typeof lastBotMessage.message === "string" ? lastBotMessage.message : JSON.stringify(lastBotMessage.message || "");

      // Only update if message is empty (plan phase) - preserve the last known value
      if (currentMsg.trim() === "") {
        // Don't update previousMessage when empty - keep tracking
        return;
      }

      setPreviousMessage(currentMsg);
    }
  }, [messageData]);

  /**
   * Determines if the plan should be displayed
   * @param {Object} data - Current message data
   * @param {boolean} isLastPlanInMessages - Is this the last plan in the message list
   * @param {boolean} isHuman - Is human verifier enabled
   * @param {boolean} toolInterrupt - Is tool interrupt enabled
   * @param {boolean} hasToolDetails - Does the message have tool details
   * @returns {boolean} - Whether to show the plan
   */
  const checktoShowPlan = (data, isLastPlanInMessages, isHuman, toolInterrupt, hasToolDetails) => {
    // Plan should stay visible while:
    // 1. Plan exists and this is the last plan in messages
    // 2. Human verifier is enabled (plan verifier)
    // 3. Message is empty (no final response yet) OR we're currently streaming
    // 4. No tool details present (not in tool verification phase)
    const hasPartsWithContent =
      Array.isArray(data?.parts) &&
      data.parts.some((part) => {
        const partContent = part?.data?.content || part?.text || part?.content;
        if (typeof partContent === "string") {
          return partContent.trim().length > 0;
        }
        return Boolean(partContent);
      });
    const hasEmptyMessage = data.message === "" || !data.message;
    const hasNoFinalResponse = data.message === "" && !hasPartsWithContent;

    // Show plan if we have a plan, human verifier is on, message is empty, and we're waiting for approval
    // The plan should stay visible even when nodes/steps are loading (props.isStreaming)
    return (
      data?.plan?.length > 0 &&
      isLastPlanInMessages &&
      hasEmptyMessage &&
      hasNoFinalResponse &&
      ((isHuman && toolInterrupt) || isHuman) &&
      (!data?.toolcallData?.additional_details ||
        (Array.isArray(data.toolcallData.additional_details) &&
          data.toolcallData.additional_details.length > 0 &&
          Object.keys(data.toolcallData.additional_details[0]?.additional_kwargs || {}).length === 0)) &&
      !hasToolDetails
    );
  };

  const sendArgumentEditData = async (data) => {
    const argData = convertStringifiedObjects(parsedValues);
    setFetching(true);
    setSendIconShow(false);
    setGenerateButton(true);

    // Enable streaming UI
    props.setIsStreaming?.(true);
    props.setCurrentNodeIndex?.(-1);

    const payload = {
      agentic_application_id: agentSelectValue,
      query: data?.userText || lastResponse?.query || "",
      session_id: oldSessionId !== "" ? oldSessionId : session,
      model_name: model,
      reset_conversation: false,
      tool_verifier_flag: Boolean(toolInterrupt),
      tool_feedback: JSON.stringify(argData),
      response_formatting_flag: Boolean(isCanvasEnabled),
      context_flag: Boolean(isContextEnabled),
      evaluation_flag: Boolean(onlineEvaluatorFlag),
      plan_verifier_flag: Boolean(isHuman),
      mentioned_agentic_application_id: mentionedAgent && mentionedAgent.agentic_application_id ? mentionedAgent.agentic_application_id : null,
      validator_flag: useValidator,
    };

    let nodeIndex = Array.isArray(nodes) ? nodes.length - 1 : -1;
    const onStreamChunk = (obj) => {
      if (!obj || typeof obj !== "object") return;

      const nodeName = obj["Node Name"] || obj.node_name || obj.node || obj.name || null;
      const statusVal = obj.Status || obj.status || obj.state || null;
      const toolName = obj["Tool Name"] || obj.tool_name || (obj.raw && (obj.raw["Tool Name"] || obj.raw.tool_name)) || null;

      if (nodeName && statusVal) {
        nodeIndex++;
        const newNode = {
          "Node Name": nodeName,
          Status: statusVal,
          "Tool Name": toolName,
        };
        props.setNodes?.((prev) => [...prev, newNode]);
        props.setCurrentNodeIndex?.(nodeIndex);
      } else if (obj && (obj.content || obj.raw || obj["Tool Output"])) {
        // Content-only chunk (tool output or interim message) — append as content event
        const rawToolOut = obj["Tool Output"] || (obj.raw && (obj.raw["Tool Output"] || obj.raw.ToolOutput || obj.raw["tool_output"]));
        let contentVal = "";
        if (typeof obj.content === "string" && obj.content.trim().length > 0) {
          contentVal = obj.content;
        } else if (rawToolOut != null) {
          contentVal = String(rawToolOut);
        } else if (obj.raw && typeof obj.raw === "object" && obj.raw.content) {
          contentVal = typeof obj.raw.content === "string" ? obj.raw.content : JSON.stringify(obj.raw.content);
        }
        props.setNodes?.((prev) => [...prev, { content: contentVal, raw: obj.raw || {} }]);
      }
    };

    const response = await getChatQueryResponse(payload, APIs.CHAT_INFERENCE, onStreamChunk);

    setMessageData(converToChatFormat(response) || []);
    props.setIsStreaming?.(false);
    props.setCurrentNodeIndex?.(-1); // Reset to show final state
    setFetching(false);
    setGenerateButton(false);
    props.setLikeIcon(false);
  };
  const submitFeedbackYes = async (data) => {
    setIsEditable(false);
    setLoadingText("Generating");
    setGenerateButton(true);
    setFetching(true);

    // Enable streaming UI
    props.setIsStreaming?.(true);
    props.setCurrentNodeIndex?.(-1);

    const payload = {
      agentic_application_id: agentSelectValue,
      query: data?.userText || lastResponse?.query || "",
      session_id: oldSessionId !== "" ? oldSessionId : session,
      model_name: model,
      reset_conversation: false,
      tool_verifier_flag: Boolean(toolInterrupt),
      tool_feedback: "yes",
      response_formatting_flag: Boolean(isCanvasEnabled),
      context_flag: Boolean(isContextEnabled),
      evaluation_flag: Boolean(onlineEvaluatorFlag),
      plan_verifier_flag: Boolean(isHuman),
      mentioned_agentic_application_id: mentionedAgent && mentionedAgent.agentic_application_id ? mentionedAgent.agentic_application_id : null,
      validator_flag: useValidator,
    };
    let nodeIndex = Array.isArray(nodes) ? nodes.length - 1 : -1;
    const onStreamChunk = (obj) => {
      if (!obj || typeof obj !== "object") return;

      const nodeName = obj["Node Name"] || obj.node_name || obj.node || obj.name || null;
      const statusVal = obj.Status || obj.status || obj.state || null;
      const toolName = obj["Tool Name"] || obj.tool_name || (obj.raw && (obj.raw["Tool Name"] || obj.raw.tool_name)) || null;

      if (nodeName && statusVal) {
        nodeIndex++;
        const newNode = {
          "Node Name": nodeName,
          Status: statusVal,
          "Tool Name": toolName,
        };
        props.setNodes?.((prev) => [...prev, newNode]);
        props.setCurrentNodeIndex?.(nodeIndex);
      } else if (obj && (obj.content || obj.raw || obj["Tool Output"])) {
        // Content-only chunk (tool output or interim message) — append as content event
        const rawToolOut = obj["Tool Output"] || (obj.raw && (obj.raw["Tool Output"] || obj.raw.ToolOutput || obj.raw["tool_output"]));
        let contentVal = "";
        if (typeof obj.content === "string" && obj.content.trim().length > 0) {
          contentVal = obj.content;
        } else if (rawToolOut != null) {
          contentVal = String(rawToolOut);
        } else if (obj.raw && typeof obj.raw === "object" && obj.raw.content) {
          contentVal = typeof obj.raw.content === "string" ? obj.raw.content : JSON.stringify(obj.raw.content);
        }
        props.setNodes?.((prev) => [...prev, { content: contentVal, raw: obj.raw || {} }]);
      }
    };
    const response = await getChatQueryResponse(payload, APIs.CHAT_INFERENCE, onStreamChunk);

    setMessageData(converToChatFormat(response) || []);
    props.setIsStreaming?.(false);
    props.setCurrentNodeIndex?.(-1); // Reset to show final state

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
    setLoadingText("Re-generating");
    setgenerateFeedBackButton(true);
    setFetching(true);
    await sendFeedback(dislike, feedBackText, sessionId);
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

  // Auto-scroll to latest item when nodes change
  useEffect(() => {
    if (showNodeDetails && nodes.length > 0) {
      // Scroll all execution step lists to bottom
      [executionStepsRef, executionStepsInitialRef, executionStepsInlineRef].forEach((ref) => {
        if (ref.current) {
          ref.current.scrollTop = ref.current.scrollHeight;
        }
      });
    }
    // Always scroll SSE node list when streaming (doesn't depend on showNodeDetails)
    if (sseNodeListRef.current) {
      sseNodeListRef.current.scrollTop = sseNodeListRef.current.scrollHeight;
    }
  }, [nodes.length, showNodeDetails, currentNodeIndex]);

  return (
    <div className={styles.messagesContainer}>
      {((!props?.isMissingRequiredOptions && props?.oldChats.length === 0) || (props?.isMissingRequiredOptions && props?.oldChats.length === 0)) && messageData.length === 0 && (
        <PlaceholderScreen agentType={agentType} model={model} selectedAgent={agentSelectValue} />
      )}

      {/* Loading indicator when streaming has started but no nodes have arrived yet */}
      {props.isStreaming && messageData.length === 0 && (!Array.isArray(nodes) || nodes.length === 0) && (
        <div className={`${chatBubbleCss.container} ${chatBubbleCss.botMessage}`}>
          <div className={chatBubbleCss.avatarContainer}>
            <div className={`${chatBubbleCss.avatar} ${chatBubbleCss.botAvatar}`}>
              <span className={chatBubbleCss.agentIcon}>
                <FontAwesomeIcon icon={faRobot} />
              </span>
            </div>
          </div>
          <div className={`${styles.loadingChat} generating-1`}>
            <LoadingChat label="Generating" />
          </div>
        </div>
      )}

      {/* Pre-first-message streaming execution summary: show nodes before any bot bubble exists */}
      {props.isStreaming && messageData.length === 0 && Array.isArray(nodes) && nodes.length > 0 && (
        <div className={`${chatBubbleCss.container} ${chatBubbleCss.botMessage}`}>
          {/* Streaming execution steps panel (no avatar, no feedback) */}
          <div className={chatBubbleCss.messageWrapper} style={{ marginLeft: 0 }}>
            <ExecutionStepsList
              rawNodes={nodes}
              showDetails={showNodeDetails}
              onToggleDetails={() => setShowNodeDetails((v) => !v)}
              expandedNodes={expandedNodes}
              onToggleNode={toggleNodeExpand}
              keyPrefix="initial"
              baseId={baseId}
              listRef={executionStepsInitialRef}
              isStreaming={props.isStreaming}
            />
          </div>
        </div>
      )}

      {(messageData?.length > 0 || props?.oldChats.length > 0) &&
        (() => {
          // Determine the actual array to iterate based on feedback state
          const displayMessages =
            (feedBack === "no" || feedBack === dislike) &&
            ((agentType === REACT_AGENT && close) ||
              agentType === MULTI_AGENT ||
              agentType === PLANNER_EXECUTOR_AGENT ||
              agentType === REACT_CRITIC_AGENT ||
              agentType === PLANNER_META_AGENT ||
              agentType === HYBRID_AGENT)
              ? messageData.slice(SLICE_LAST_TWO)
              : messageData;

          return displayMessages;
        })()?.map((data, index, currentArray) => {
          const trimmedMessage = typeof data?.message === "string" ? data.message.trim() : "";
          const hasMessageText = trimmedMessage.length > 0;
          const hasMessageObject = data?.message && typeof data.message === "object" && !Array.isArray(data.message) && Object.keys(data.message).length > 0;
          const hasPartsContent = Array.isArray(data?.parts)
            ? data.parts.some((part) => {
                const partContent = part?.data?.content || part?.text || part?.content;
                if (typeof partContent === "string") {
                  return partContent.trim().length > 0;
                }
                return Boolean(partContent);
              })
            : false;
          const hasPlanContent = Array.isArray(data?.plan)
            ? data.plan.some((step) => {
                if (typeof step === "string") {
                  return step.trim().length > 0;
                }
                if (step && typeof step === "object") {
                  return Object.keys(step).length > 0;
                }
                return Boolean(step);
              })
            : false;

          // During streaming, skip the last BOT bubble to avoid showing duplicate/incomplete content
          // EXCEPTION: Don't skip if the bubble has a plan that needs user approval (plan verifier case)
          // The plan should remain visible on screen while execution steps are loading
          const hasEmptyMessage = !hasMessageText && !hasMessageObject && !hasPartsContent;
          const hasToolDetailsForVerifier = Array.isArray(data?.toolcallData?.additional_details)
            ? data.toolcallData.additional_details.length > 0 && Object.keys(data.toolcallData.additional_details[0]?.additional_kwargs || {}).length > 0
            : false;
          const shouldKeepForPlanVerifier = hasPlanContent && hasEmptyMessage && isHuman;
          const shouldKeepForToolVerifier = hasToolDetailsForVerifier && toolInterrupt && hasEmptyMessage;
          const shouldSkipBubble = props?.isStreaming && data?.type === BOT && index === currentArray.length - 1 && !shouldKeepForPlanVerifier && !shouldKeepForToolVerifier;
          if (shouldSkipBubble) {
            return null;
          }
          const hasToolDetails = Array.isArray(data?.toolcallData?.additional_details)
            ? data.toolcallData.additional_details.length > 0 && Object.keys(data.toolcallData.additional_details[0]?.additional_kwargs || {}).length > 0
            : false;
          const hasToolInterruptFallback = data?.message === "" && !isHuman && toolInterrupt && !("additional_details" in (data?.toolcallData || {}));
          const shouldRenderAccordion = hasMessageText || hasMessageObject || hasPartsContent;
          const shouldRenderBotMessage = shouldRenderAccordion || hasToolDetails || hasToolInterruptFallback;

          const willRenderInner = shouldRenderBotMessage || hasPlanContent;
          const hasVisibleBubbleContent = willRenderInner;

          // Use currentArray (the actual displayed messages) for plan position calculation
          const hasLaterPlan = Array.isArray(currentArray) ? currentArray.slice(index + 1).some((m) => Array.isArray(m?.plan) && m.plan.length > 0) : false;
          const isLastPlanInMessages = !hasLaterPlan;

          const hasPlanOnly = data.type === BOT && hasPlanContent && !hasMessageText && !hasMessageObject && !hasPartsContent && !hasToolDetails && !hasToolInterruptFallback;

          // Avatar should appear for substantive bot response OR plan-only bubbles per user request
          const showAvatar = data.type === BOT && (hasMessageText || hasMessageObject || hasPartsContent || hasToolDetails || hasToolInterruptFallback || hasPlanOnly);

          //Skip rendering entirely if bot and no inner content (removes empty chat bubble container)
          if (data?.type === BOT && !willRenderInner) {
            return null;
          }

          if (data?.type === BOT && !shouldRenderBotMessage && !hasPlanContent) {
            return null;
          }

          // Use currentArray length for lastIndex calculation
          const lastIndex = currentArray.length - 1;

          const messageKey = `${baseId}-message-${index}`;
          return (
            <div className={`${chatBubbleCss.container} ${data.type === BOT ? chatBubbleCss.botMessage : chatBubbleCss.userMessage}`} key={messageKey}>
              {data.type === BOT && hasVisibleBubbleContent && (
                <>
                  {showAvatar && (
                    <div className={chatBubbleCss.avatarContainer}>
                      <div className={`${chatBubbleCss.avatar} ${chatBubbleCss.botAvatar}`}>
                        <span className={chatBubbleCss.agentIcon}>
                          <FontAwesomeIcon icon={faRobot} />
                        </span>
                      </div>
                    </div>
                  )}
                  <div className={chatBubbleCss.messageWrapper}>
                    {/* Nodes summary */}
                    {index === lastIndex && !props.isStreaming && Array.isArray(nodes) && nodes.length > 0 && (
                      <div style={{ marginBottom: 6 }}>
                        <ExecutionStepsList
                          rawNodes={nodes}
                          showDetails={showNodeDetails}
                          onToggleDetails={() => setShowNodeDetails((v) => !v)}
                          expandedNodes={expandedNodes}
                          onToggleNode={toggleNodeExpand}
                          keyPrefix="inline"
                          baseId={baseId}
                          listRef={executionStepsInlineRef}
                          isStreaming={false}
                        />
                      </div>
                    )}
                    {shouldRenderAccordion && agentType !== CUSTOM_TEMPLATE && agentType !== PLANNER_META_AGENT && (
                      <>
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
                      </>
                    )}
                    {/* {shouldRenderAccordion && agentType !== CUSTOM_TEMPLATE && agentType === PLANNER_META_AGENT && data?.plan?.length === 0 && (
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
                    )} */}
                    <div className={styles.accordionContainer}>
                      {checktoShowPlan(data, isLastPlanInMessages, isHuman, toolInterrupt, hasToolDetails) && (
                        <>
                          <div className={styles.planContainer}>
                            <h3>Plan</h3>
                            {data?.plan?.map((planItem, planIndex) => (
                              <p className={styles.stepsContent} key={`plan-step-${planIndex}`}>
                                {planItem}
                              </p>
                            ))}
                          </div>

                          {!fetching && feedBack !== "no" && (
                            <div className={`${chatBubbleCss.feedbackWrapper} feedbackWrapper-1`}>
                              <button
                                className={`${chatBubbleCss.feedbackButton}`} /*  ${highlightedFeedback === 'up' ? chatBubbleCss.highlighted : ''} */
                                onClick={() => handlePlanFeedBack("yes", data?.userText)}
                                title="Good response">
                                <FontAwesomeIcon icon={faThumbsUp} />
                              </button>{" "}
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

                          {!fetching && showInput && feedBack === "no" && (
                            <div className={styles.feedBackSection}>
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

                      {agentType !== CUSTOM_TEMPLATE && agentType === PLANNER_META_AGENT && (
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
                            <div className={`${chatBubbleCss.feedbackWrapper}  feedbackWrapper-2`}>
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
                      {data?.message === "" &&
                        !isHuman &&
                        toolInterrupt &&
                        !("additional_details" in (data?.toolcallData || {})) &&
                        (() => {
                          // Try to surface the last streamed tool_verifier message if present in the overall message list
                          const lastVerifier = Array.isArray(props?.messageData)
                            ? [...props.messageData]
                                .slice()
                                .reverse()
                                .find((m) => m && m.tool_verifier && m.message)
                            : null;
                          if (lastVerifier) {
                            return (
                              <div className={styles.botChatSection}>
                                <div className={styles.accordion}>
                                  <div className={styles["accordion-header"]}>
                                    <div className={chatBubbleCss.messageBubble}>
                                      <span>{lastVerifier.message}</span>
                                    </div>
                                  </div>
                                </div>
                              </div>
                            );
                          }
                          // Fallback generic error when no verifier message available
                          return (
                            <div className={styles.botChatSection}>
                              <div className={styles.accordion}>
                                <div className={styles["accordion-header"]}>
                                  <div className={chatBubbleCss.messageBubble}>
                                    <span>{"Something went wrong"}</span>
                                  </div>
                                </div>
                              </div>
                            </div>
                          );
                        })()}
                    </div>
                    {data.type === BOT &&
                      hasVisibleBubbleContent &&
                      index !== lastIndex &&
                      planApprovedIndex !== index &&
                      (processingFeedback[index] ? (
                        <div className={`${styles.loadingChat} generating-2`} style={{ marginTop: 8 }}>
                          <LoadingChat label={"Generating"} />
                        </div>
                      ) : (
                        <div className={`${chatBubbleCss.feedbackWrapper}  feedbackWrapper-3`} style={{ marginTop: 8 }}>
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
                          {!fetching &&
                          (((agentType === REACT_AGENT ||
                            agentType === MULTI_AGENT ||
                            agentType === PLANNER_EXECUTOR_AGENT ||
                            agentType === REACT_CRITIC_AGENT ||
                            agentType === HYBRID_AGENT) &&
                            close) ||
                            (agentType === PLANNER_META_AGENT && feedBack === dislike && close)) ? (
                            <div className={styles["cancel-btn"]}>
                              <button
                                onClick={() => {
                                  setClose(false);
                                  setFeedback("");
                                  setShowInput(false);
                                  setGenerateButton(false);
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
                    {index === lastIndex && hasVisibleBubbleContent && feedBack === dislike && (
                      <>
                        {fetching && generateFeedBackButton && !props.isStreaming && (
                          <div className={`${styles.loadingChat} generating-3`}>
                            <LoadingChat label={loadingText || "Re-generating"} />
                          </div>
                        )}
                      </>
                    )}
                    {index === lastIndex &&
                      hasVisibleBubbleContent &&
                      (agentType === REACT_AGENT ||
                        agentType === MULTI_AGENT ||
                        agentType === PLANNER_EXECUTOR_AGENT ||
                        agentType === REACT_CRITIC_AGENT ||
                        agentType === HYBRID_AGENT ||
                        agentType === PLANNER_META_AGENT ||
                        agentType === META_AGENT) &&
                      feedBack !== dislike && (
                        <div className={styles["feedback-section"]}>
                          {!fetching && !generateFeedBackButton && (
                            <div className={styles["button-container"]}>
                              {loadingText && fetching && !props.isStreaming ? (
                                <>
                                  <div className={`${styles.loadingChat} generating-4`}>
                                    <LoadingChat label={"Generating"} />
                                  </div>
                                </>
                              ) : (
                                <></>
                              )}

                              {hasVisibleBubbleContent &&
                              data?.message === "" &&
                              !props?.likeIcon &&
                              Array.isArray(data?.toolcallData?.additional_details) &&
                              data.toolcallData.additional_details.length > 0 &&
                              data.toolcallData.additional_details[0]?.additional_kwargs &&
                              Object.keys(data.toolcallData.additional_details[0]?.additional_kwargs).length > 0 ? (
                                <>
                                  <div className={`${chatBubbleCss.feedbackWrapper}  feedbackWrapper-4`}>
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
                                  {" "}
                                  {/* Generic feedback when there is visible content (message text, parts, or other content) */}
                                  {/* Skip rendering if Plan Feedback wrapper is already shown (Plan Verifier scenario) */}
                                  {/* Also skip for plan-only responses when Plan Verifier (isHuman) is enabled */}
                                  {/* Also skip when feedBack === "no" (user clicked thumbs down on plan, showing feedback input) */}
                                  {/* Hide feedback buttons when generating (like/regenerate in progress) */}
                                  {/* For PLANNER_META_AGENT/META_AGENT: Hide feedback buttons when there's a final response (non-empty message) */}
                                  {hasVisibleBubbleContent &&
                                    agentType !== PLANNER_META_AGENT &&
                                    agentType !== META_AGENT &&
                                    feedBack !== "no" &&
                                    !showgenerateButton &&
                                    !isEditable &&
                                    !(hasPlanContent && isLastPlanInMessages && data?.message === "" && !hasPartsContent && isHuman && !hasToolDetails) &&
                                    !((agentType === PLANNER_META_AGENT || agentType === META_AGENT) && data?.message === "" && !hasPartsContent) && (
                                      <div className={`${chatBubbleCss.feedbackWrapper} feedbackWrapper-5`}>
                                        <button className={`${chatBubbleCss.feedbackButton}`} onClick={() => handleFeedBack(like, session)} title="Good response">
                                          <FontAwesomeIcon icon={faThumbsUp} />
                                        </button>
                                        <button className={`${chatBubbleCss.feedbackButton}`} onClick={() => handleFeedBack(dislike, session)} title="Poor response">
                                          <FontAwesomeIcon icon={faThumbsDown} style={{ transform: "scaleX(-1)" }} />
                                        </button>
                                        <button className={chatBubbleCss.feedbackButton} onClick={() => handleFeedBack(regenerate, session)} title="Regenerate response">
                                          <FontAwesomeIcon icon={faRotateRight} style={{ transform: "rotate(-106deg)" }} className={generating ? chatBubbleCss.spinning : ""} />
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
                                </>
                              )}

                              {/* </>} */}
                            </div>
                          )}
                          {feedBack !== dislike && (showgenerateButton || (fetching && generateFeedBackButton)) && !props.isStreaming ? (
                            <>
                              <div className={`${styles.loadingChat} generating-5`}>
                                <LoadingChat label={loadingText || "Generating"} />
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

      {/* Show "Generating..." while waiting for streaming nodes to arrive */}
      {props.isStreaming && messageData.length > 0 && (!Array.isArray(nodes) || nodes.length === 0) && (
        <div className={`${chatBubbleCss.container} ${chatBubbleCss.botMessage}`}>
          <div className={chatBubbleCss.avatarContainer}>
            <div className={`${chatBubbleCss.avatar} ${chatBubbleCss.botAvatar}`}>
              <span className={chatBubbleCss.agentIcon}>
                <FontAwesomeIcon icon={faRobot} />
              </span>
            </div>
          </div>
          <div className={chatBubbleCss.messageWrapper} style={{ marginLeft: 0 }}>
            <div className={`${styles.loadingChat} generating-waiting-for-nodes`}>
              <LoadingChat label="Generating" />
            </div>
          </div>
        </div>
      )}

      {(() => {
        // Streaming active node bubble (after first message exists). For pre-first-message we render above.
        if (!props.isStreaming) return false;
        if (messageData.length === 0) return false; // handled by the pre-first-message block
        if (!Array.isArray(nodes) || nodes.length === 0) return false;
        return true;
      })() && (
        <div className={`${chatBubbleCss.container} ${chatBubbleCss.botMessage}`}>
          {/* Streaming active steps (no avatar / feedback) */}
          <div className={chatBubbleCss.avatarContainer}>
            <div className={`${chatBubbleCss.avatar} ${chatBubbleCss.botAvatar}`}>
              <span className={chatBubbleCss.agentIcon}>
                <FontAwesomeIcon icon={faRobot} />
              </span>
            </div>
          </div>

          <div className={chatBubbleCss.messageWrapper} style={{ marginLeft: 0 }}>
            <ExecutionStepsList
              rawNodes={nodes}
              showDetails={showNodeDetails}
              onToggleDetails={() => setShowNodeDetails((v) => !v)}
              expandedNodes={expandedNodes}
              onToggleNode={toggleNodeExpand}
              keyPrefix="streaming"
              baseId={baseId}
              listRef={sseNodeListRef}
              isStreaming={true}
              streamContents={props?.streamContents}
              currentNodeIndex={currentNodeIndex}
            />
          </div>
        </div>
      )}
      <div className={`${"fixedDebugpanel"} ${styles.loadingChat}`} style={{ width: "100%", maxWidth: "98%" }}></div>
    </div>
  );
};

export default MsgBox;
