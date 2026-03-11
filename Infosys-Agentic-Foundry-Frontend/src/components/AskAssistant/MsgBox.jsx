import { useEffect, useState, useId, useRef } from "react";
import { useMessage } from "../../Hooks/MessageContext";
import PlaceholderScreen from "./PlaceholderScreen";
import DOMPurify from "dompurify";
import SVGIcons from "../../Icons/SVGIcons";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import TextareaWithActions from "../commonComponents/TextareaWithActions";

import {
  BOT,
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
  PIPELINE_AGENT,
} from "../../constant";
import LoadingChat from "./LoadingChat";
import AccordionPlanSteps from "../commonComponents/Accordions/AccordionPlanSteps";
import PlanVerifier from "./PlanVerifier";
import parse from "html-react-parser";
import ToolCallFinalResponse from "./ToolCallFinalResponse";
import { useChatServices } from "../../services/chatService";
import chatBubbleCss from "./ChatBubble.module.css";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faUser, faRobot, faChevronDown } from "@fortawesome/free-solid-svg-icons";
import { formatResponseTimeSeconds, formatMessageTimestamp } from "../../utils/timeFormatter";
import ExecutionStepsList from "./ExecutionStepsList";

const JSON_INDENT = 2;
const FEEDBACK_TIMEOUT_MS = 5000;
const SLICE_LAST_TWO = -2;

export const extractPlanFromDetails = (details) => {
  if (!Array.isArray(details)) return null;
  const entry = details.find((d) => d && (d.role === "plan" || d.type === "plan" || d.role === "re-plan" || d.type === "re-plan"));
  if (!entry) return null;
  if (Array.isArray(entry.content) && entry.content.length > 0) return entry.content;
  if (typeof entry.content === "string" && entry.content.trim().length > 0)
    return entry.content
      .split(/\r?\n/)
      .map((s) => s.trim())
      .filter(Boolean);
  return null;
};

export const getPlanForMessage = (item) => {
  if (!item) return null;
  const fromDetails = extractPlanFromDetails(item?.additional_details) || extractPlanFromDetails(item?.toolcallData?.additional_details);
  if (Array.isArray(fromDetails) && fromDetails.length > 0) return fromDetails;
  if (Array.isArray(item?.plan) && item.plan.length > 0) return item.plan;
  if (typeof item?.plan === "string" && item.plan.trim().length > 0)
    return item.plan
      .split(/\r?\n/)
      .map((s) => s.trim())
      .filter(Boolean);
  return null;
};

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
    isFileContextEnabled,
    isMessageQueueEnabled,
    onlineEvaluatorFlag,
    mentionedAgent,
    planVerifierText,
    useValidator,
    temperature,
    selectedInterruptTools,
    mappedTools,
    selectedAgent,
    framework,
    onViewFile,
    setGenerating,
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

  // Track all approved plan queries by userText (persists across new queries and survives array slicing)
  const [approvedPlanQueries, setApprovedPlanQueries] = useState(new Set());

  // Persist plans per-message so plans remain attached to the response
  // key: message index, value: plan array
  // persistedPlans removed: plans are derived from `messageData` at render time

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
      // For regenerate, set generating to true to disable chat input
      if (value === regenerate && setGenerating) {
        setGenerating(true);
      }
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
        file_context_management_flag: Boolean(isFileContextEnabled),
        evaluation_flag: Boolean(onlineEvaluatorFlag),
        plan_verifier_flag: Boolean(isHuman),
        mentioned_agentic_application_id: mentionedAgent && mentionedAgent.agentic_application_id ? mentionedAgent.agentic_application_id : null,
        validator_flag: useValidator,
        temperature: temperature,
        message_queue: Boolean(isMessageQueueEnabled),
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
        file_context_management_flag: Boolean(isFileContextEnabled),
        evaluation_flag: Boolean(onlineEvaluatorFlag),
        plan_verifier_flag: Boolean(isHuman),
        mentioned_agentic_application_id: mentionedAgent && mentionedAgent.agentic_application_id ? mentionedAgent.agentic_application_id : null,
        validator_flag: useValidator,
        temperature: temperature,
        message_queue: Boolean(isMessageQueueEnabled),
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
    setIsEditable(true);
    setSendIconShow(true);
  };
  const handlePlanFeedBack = async (feedBack, userText, messageIndex = null, msgId = null) => {
    setClose(feedBack === "no" ? true : false);
    setFeedback(feedBack);
    setgenerateFeedBackButton(true);
    setLoadingText(feedBack === "no" ? "Loading..." : "Generating");
    setFetching(true);

    // Plans are derived from messageData; no local persistence needed here

    // Set the index of the approved plan so only that message's feedback wrapper is affected
    if (feedBack === "yes") {
      const idx = typeof messageIndex === "number" ? messageIndex : messageData.length - 1;
      setPlanApprovedIndex(idx);
      // Add msgId to persistent approved queries set (survives array slicing)
      if (msgId) {
        setApprovedPlanQueries((prev) => new Set([...prev, msgId]));
      }
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
      // don't immediately clear planApprovedIndex here so UI can show any toast
      if (feedBack === "yes") {
        setPlanApprovedIndex(null);
      }
    }
  };

  const handlePlanDislikeFeedBack = async (userText, feedbackTextParam = null) => {
    setShowInput(false); // Hide textarea immediately
    setLoadingText("Re-generating");
    setFetching(true);
    setgenerateFeedBackButton(true); // Show loading indicator
    // Use passed parameter if available, otherwise fall back to state
    const textToSend = feedbackTextParam || feedBackText;
    try {
      const response = await sendHumanInLoop(feedBack, textToSend, userText);
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
      // Find existing USER message with matching query to preserve its timestamp
      const existingUserMsg = messageData.find((msg) => msg.type === USER && msg.message === item?.user_query && msg.start_timestamp);

      // USER bubble - use existing timestamp if available, otherwise try backend fields
      chats.push({
        type: USER,
        message: item?.user_query,
        debugExecutor: item?.additional_details,
        start_timestamp:
          existingUserMsg?.start_timestamp ||
          item?.start_timestamp ||
          item?.time_stamp ||
          (index === 0 ? chatHistory?.start_timestamp || chatHistory?.time_stamp || null : null) ||
          null,
        end_timestamp: item?.end_timestamp || null,
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

      const _planArr = getPlanForMessage(item) || null;

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

      const stableQuery = item?.user_query || chatHistory?.query || "";
      chats.push({
        type: BOT,
        message: botMessage,
        toolcallData: toolcallData,
        userText: stableQuery,
        msgId: `plan-${stableQuery}-${index}`,
        steps: JSON.stringify(item?.agent_steps, null, JSON_INDENT),
        debugExecutor: item?.additional_details,
        // Attach plan (if any) extracted from details or top-level
        ...(Array.isArray(_planArr) && _planArr.length > 0 ? { plan: _planArr } : {}),
        parts: item?.parts || [],
        show_canvas: item?.show_canvas || false,
        plan_verifier: Boolean(localPlanVerifierText),
        response_time: item?.response_time || chatHistory?.response_time || null,
        start_timestamp: item?.start_timestamp || null,
        end_timestamp: item?.end_timestamp || null,
      });
    });

    // Edge case: only plan verifier prompt, no executor messages
    if ((!chatHistory?.executor_messages || chatHistory.executor_messages.length === 0) && localPlanVerifierText) {
      const stableQueryEdge = chatHistory?.query || "";
      chats.push({
        type: BOT,
        message: localPlanVerifierText,
        plan_verifier: true,
        msgId: `plan-${stableQueryEdge}-edge`,
        userText: stableQueryEdge,
      });
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
      framework_type: framework,
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
      file_context_management_flag: Boolean(isFileContextEnabled),
      evaluation_flag: Boolean(onlineEvaluatorFlag),
      plan_verifier_flag: Boolean(isHuman),
      mentioned_agentic_application_id: mentionedAgent && mentionedAgent.agentic_application_id ? mentionedAgent.agentic_application_id : null,
      temperature: temperature,
      message_queue: Boolean(isMessageQueueEnabled),
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
    // Reset generating state to re-enable chat input
    if (setGenerating) {
      setGenerating(false);
    }
  };

  const handleChange = (e) => {
    setFeedBackText(e?.target?.value);
  };
  const handleEditChange = (key, newValue, val) => {
    // Parse the new value if it looks like JSON, otherwise keep as string
    let parsedNewValue = newValue;
    if (typeof newValue === "string") {
      const trimmed = newValue.trim();
      // Try to parse if it looks like JSON object or array
      if ((trimmed.startsWith('{') && trimmed.endsWith('}')) ||
        (trimmed.startsWith('[') && trimmed.endsWith(']'))) {
        try {
          parsedNewValue = JSON.parse(trimmed);
        } catch {
          // Keep as string if parsing fails
          parsedNewValue = newValue;
        }
      }
    }
    setParsedValues((prev) => ({
      ...prev,
      [key]: parsedNewValue,
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
    return (
      data?.plan?.length > 0 &&
      isLastPlanInMessages &&
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
      framework_type: framework,
      agentic_application_id: agentSelectValue,
      query: data?.userText || lastResponse?.query || "",
      session_id: oldSessionId !== "" ? oldSessionId : session,
      model_name: model,
      reset_conversation: false,
      tool_verifier_flag: Boolean(toolInterrupt),
      tool_feedback: JSON.stringify(argData),
      response_formatting_flag: Boolean(isCanvasEnabled),
      context_flag: Boolean(isContextEnabled),
      file_context_management_flag: Boolean(isFileContextEnabled),
      evaluation_flag: Boolean(onlineEvaluatorFlag),
      plan_verifier_flag: Boolean(isHuman),
      mentioned_agentic_application_id: mentionedAgent && mentionedAgent.agentic_application_id ? mentionedAgent.agentic_application_id : null,
      validator_flag: useValidator,
      enable_streaming_flag: true,
      temperature: temperature,
      message_queue: Boolean(isMessageQueueEnabled),
      ...(toolInterrupt && { interrupt_items: selectedInterruptTools || [] }),
    };

    let nodeIndex = Array.isArray(nodes) ? nodes.length - 1 : -1;
    const onStreamChunk = (obj) => {
      if (!obj || typeof obj !== "object") return;

      const nodeName = obj["Node Name"] || obj.node_name || obj.node || obj.name || null;
      const statusVal = obj.Status || obj.status || obj.state || null;
      const toolName = obj["Tool Name"] || obj.tool_name || (obj.raw && (obj.raw["Tool Name"] || obj.raw.tool_name)) || null;

      // Extract content from multiple possible fields
      let contentVal = null;
      if (obj.content && typeof obj.content === "string") {
        contentVal = obj.content;
      } else if (obj["Tool Output"]) {
        const toolOutput = obj["Tool Output"];
        contentVal = typeof toolOutput === "string" ? toolOutput : JSON.stringify(toolOutput);
      } else if (obj.raw) {
        if (obj.raw.content) {
          contentVal = typeof obj.raw.content === "string" ? obj.raw.content : JSON.stringify(obj.raw.content);
        } else if (obj.raw["Tool Output"]) {
          const rawToolOutput = obj.raw["Tool Output"];
          contentVal = typeof rawToolOutput === "string" ? rawToolOutput : JSON.stringify(rawToolOutput);
        }
      }

      if (nodeName && statusVal) {
        nodeIndex++;
        const newNode = {
          "Node Name": nodeName,
          Status: statusVal,
          "Tool Name": toolName,
          ...(obj["Tool Output"] && { "Tool Output": obj["Tool Output"] }),
          ...(contentVal && { content: contentVal }),
        };
        props.setNodes?.((prev) => [...prev, newNode]);
        props.setCurrentNodeIndex?.(nodeIndex);
      } else if (contentVal) {
        // Content-only chunk (tool output or interim message) — append as content event
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
      framework_type: framework,
      agentic_application_id: agentSelectValue,
      query: data?.userText || lastResponse?.query || "",
      session_id: oldSessionId !== "" ? oldSessionId : session,
      model_name: model,
      reset_conversation: false,
      tool_verifier_flag: Boolean(toolInterrupt),
      tool_feedback: "yes",
      response_formatting_flag: Boolean(isCanvasEnabled),
      context_flag: Boolean(isContextEnabled),
      file_context_management_flag: Boolean(isFileContextEnabled),
      evaluation_flag: Boolean(onlineEvaluatorFlag),
      plan_verifier_flag: Boolean(isHuman),
      mentioned_agentic_application_id: mentionedAgent && mentionedAgent.agentic_application_id ? mentionedAgent.agentic_application_id : null,
      validator_flag: useValidator,
      enable_streaming_flag: true,
      temperature: temperature,
      message_queue: Boolean(isMessageQueueEnabled),
      ...(toolInterrupt && { interrupt_items: selectedInterruptTools || [] }),
    };
    let nodeIndex = Array.isArray(nodes) ? nodes.length - 1 : -1;
    const onStreamChunk = (obj) => {
      if (!obj || typeof obj !== "object") return;

      const nodeName = obj["Node Name"] || obj.node_name || obj.node || obj.name || null;
      const statusVal = obj.Status || obj.status || obj.state || null;
      const toolName = obj["Tool Name"] || obj.tool_name || (obj.raw && (obj.raw["Tool Name"] || obj.raw.tool_name)) || null;

      // Extract content from multiple possible fields
      let contentVal = null;
      if (obj.content && typeof obj.content === "string") {
        contentVal = obj.content;
      } else if (obj["Tool Output"]) {
        const toolOutput = obj["Tool Output"];
        contentVal = typeof toolOutput === "string" ? toolOutput : JSON.stringify(toolOutput);
      } else if (obj.raw) {
        if (obj.raw.content) {
          contentVal = typeof obj.raw.content === "string" ? obj.raw.content : JSON.stringify(obj.raw.content);
        } else if (obj.raw["Tool Output"]) {
          const rawToolOutput = obj.raw["Tool Output"];
          contentVal = typeof rawToolOutput === "string" ? rawToolOutput : JSON.stringify(rawToolOutput);
        }
      }

      if (nodeName && statusVal) {
        nodeIndex++;
        const newNode = {
          "Node Name": nodeName,
          Status: statusVal,
          "Tool Name": toolName,
          ...(obj["Tool Output"] && { "Tool Output": obj["Tool Output"] }),
          ...(contentVal && { content: contentVal }),
        };
        props.setNodes?.((prev) => [...prev, newNode]);
        props.setCurrentNodeIndex?.(nodeIndex);
      } else if (contentVal) {
        // Content-only chunk (tool output or interim message) — append as content event
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
      } catch (e) { }
      setShowToast(true);
      setTimeout(() => {
        setShowToast(false);
        try {
          setToastMessage && setToastMessage("");
        } catch (e) { }
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
    if (!Array.isArray(messageData) || messageData.length === 0) {
      setIsEditable(false);
      setSendIconShow(false);
      return;
    }

    // Automatically enter edit mode for the latest tool interrupt message
    const lastToolInterrupt = [...messageData]
      .slice()
      .reverse()
      .find((m) => {
        if (!m || m.type !== BOT) return false;
        if (m.message !== "") return false;
        const details = m?.toolcallData?.additional_details;
        return Array.isArray(details) && details.length > 0 && details[0]?.additional_kwargs && Object.keys(details[0].additional_kwargs || {}).length > 0;
      });

    if (lastToolInterrupt) {
      onMsgEdit(lastToolInterrupt);
    } else {
      setIsEditable(false);
      setSendIconShow(false);
    }
  }, [messageData]);

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

  // Auto-collapse Reasoning Steps accordion when streaming ends (response complete)
  useEffect(() => {
    if (!props.isStreaming && showNodeDetails) {
      setShowNodeDetails(false);
    }
  }, [props.isStreaming]);

  return (
    <div className={styles.messagesContainer}>
      {/* PlaceholderScreen only shows when no agent is selected */}
      {props?.oldChats?.length === 0 && messageData.length === 0 && !generating && !selectedAgent && (
        <PlaceholderScreen agentType={agentType} model={model} selectedAgent={agentSelectValue} />
      )}

      {/* Welcome message from selected agent - always shows as first bot response when agent is selected */}
      {selectedAgent && (
        <div className={`${chatBubbleCss.container} ${chatBubbleCss.botMessage}`}>
          <div className={chatBubbleCss.messageWrapper}>
            <div className={styles.accordionContainer}>
              <div className={styles.accordion}>
                <div className={styles["accordion-header"]}>
                  <div className={`${chatBubbleCss.messageBubble} ${chatBubbleCss.welcomeMessageBubble}`}>
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>
                      {selectedAgent?.welcome_message || `Hello! I'm ${selectedAgent?.agentic_application_name || "your assistant"}. How can I help you today?`}
                    </ReactMarkdown>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
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
              showNamesOnly={props.canExecutionSteps === false}
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
          // Derive plan from message data (handles array or string plans)
          const effectivePlan = getPlanForMessage(data) || data?.plan || [];
          const hasPlanContent = Array.isArray(effectivePlan)
            ? effectivePlan.some((step) => {
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

          // Show plan only if Plan Verifier (isHuman) is enabled AND plan data exists
          const shouldShowPlan = isHuman && Array.isArray(effectivePlan) && effectivePlan.length > 0;

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
          const processing = Boolean(processingFeedback[index]);
          return (
            <div className={`${chatBubbleCss.container} ${data.type === BOT ? chatBubbleCss.botMessage : chatBubbleCss.userMessage}`} key={messageKey}>
              {data.type === BOT && hasVisibleBubbleContent && (
                <>
                  <div className={chatBubbleCss.messageWrapper}>
                    <div className={styles.accordionContainer}>
                      {/* Nodes summary - only show when NOT streaming to avoid duplicate with streaming panel */}
                      {index === lastIndex && !props.isStreaming && !generating && Array.isArray(nodes) && nodes.length > 0 && (
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
                            showNamesOnly={props.canExecutionSteps === false}
                          />
                        </div>
                      )}

                      {shouldShowPlan && (
                        <>
                          <PlanVerifier
                            plan={effectivePlan}
                            onApprove={() => handlePlanFeedBack("yes", data?.userText, index, data?.msgId)}
                            onRequestChanges={() => handlePlanFeedBack("no", data?.userText, index, data?.msgId)}
                            onSubmitFeedback={(feedbackText) => {
                              handlePlanDislikeFeedBack(data?.userText, feedbackText);
                            }}
                            onCancelFeedback={() => {
                              setFeedBackText("");
                              setShowInput(false);
                            }}
                            isProcessing={fetching || generating}
                            isApproved={approvedPlanQueries.has(data?.msgId) || hasMessageText || hasMessageObject || hasPartsContent}
                            showButtons={isHuman}
                          />
                        </>
                      )}

                      {agentType === PLANNER_META_AGENT && (
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
                                  : item,
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
                          agentType={agentType}
                        />
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
                                      : item,
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
                              handleEditChange={handleEditChange}
                              sendArgumentEditData={sendArgumentEditData}
                              fetching={fetching}
                              sendIconShow={sendIconShow}
                              generating={generating}
                              agentType={agentType}
                              submitFeedbackYes={submitFeedbackYes}
                              canExecute={toolInterrupt}
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
                    {shouldRenderAccordion && agentType !== PLANNER_META_AGENT && (
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
                                  : item,
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
                          agentType={agentType}
                        />
                      </>
                    )}
                    {data.type === BOT &&
                      hasVisibleBubbleContent &&
                      index !== lastIndex &&
                      planApprovedIndex !== index &&
                      (processingFeedback[index] && agentType !== PIPELINE_AGENT ? (
                        <div className={`${styles.loadingChat} generating-2`} style={{ marginTop: 8 }}>
                          <LoadingChat label={"Generating"} />
                        </div>
                      ) : (
                        <div className={`${chatBubbleCss.feedbackWrapper}  feedbackWrapper-3`} style={{ marginTop: 0 }}>
                          {data?.response_time && (
                            <span className={chatBubbleCss.responseTime}>
                              <span className={chatBubbleCss.time} title={`Response time: ${formatResponseTimeSeconds(data.response_time)}`}>
                                {formatResponseTimeSeconds(data.response_time)}
                              </span>
                            </span>
                          )}
                          {agentType !== PIPELINE_AGENT && (
                            <>
                              <button
                                type="button"
                                className={chatBubbleCss.feedbackButton}
                                onClick={(e) => {
                                  e.stopPropagation();
                                  handleMessageLike(data, index);
                                }}
                                title="Good response">
                                <SVGIcons icon="thumbs-up" width={16} height={16} />
                              </button>
                              <button
                                type="button"
                                className={chatBubbleCss.feedbackButton}
                                onClick={(e) => {
                                  e.stopPropagation();
                                  handleMessageDislike(data, index);
                                }}
                                title="Not helpful">
                                <SVGIcons icon="thumbs-down" width={16} height={16} />
                              </button>
                            </>
                          )}
                        </div>
                      ))}
                    {feedBack === dislike &&
                      index === lastIndex &&
                      agentType && ( // Only require that agentType is set
                        <div className={styles.feedBackSection}>
                          <p className={styles.warning}>What could be improved?</p>
                          <div className={styles.feedBackInput}>
                            <TextareaWithActions
                              name="feedbackText"
                              placeholder="Please Share Your Feedback..."
                              value={feedBackText}
                              onChange={handleChange}
                              rows={4}
                              showCopy={false}
                              showExpand={false}
                            />
                            <div className={styles.feedbackActions}>
                              <button disabled={generating || feedBackText.trim().length < 1} onClick={handleDislikeFeedBack} className={styles.submitFeedbackBtn}>
                                Submit Feedback
                              </button>
                              <button
                                className={styles.cancelFeedbackBtn}
                                onClick={() => {
                                  setClose(false);
                                  setFeedback("");
                                  setShowInput(false);
                                  setGenerateButton(false);
                                }}>
                                Cancel
                              </button>
                            </div>
                          </div>
                        </div>
                      )}
                    {index === lastIndex && hasVisibleBubbleContent && (feedBack === dislike || feedBack === regenerate) && (
                      <>
                        {(fetching || generating) && generateFeedBackButton && !props.isStreaming && (
                          <div className={`${styles.loadingChat} generating-3`}>
                            <LoadingChat label={loadingText || "Re-generating"} />
                          </div>
                        )}
                      </>
                    )}
                    {index === lastIndex &&
                      hasVisibleBubbleContent &&
                      agentType && // Only require that agentType is set (not empty)
                      !props.isStreaming &&
                      !generating && (
                        <div className={styles["feedback-section"]}>
                          {!fetching && !generateFeedBackButton && feedBack !== dislike && (
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
                                Array.isArray(data?.toolcallData?.additional_details) &&
                                data.toolcallData.additional_details.length > 0 &&
                                data.toolcallData.additional_details[0]?.additional_kwargs &&
                                Object.keys(data.toolcallData.additional_details[0]?.additional_kwargs).length > 0 ? null : ( // buttons inside the ToolCallFinalResponse card and skip extra feedback icons. // For tool-call verifier messages, rely on the Approve / Request Changes
                                <>
                                  {" "}
                                  {/* Generic feedback when there is visible content (message text, parts, or other content) */}
                                  {/* Skip rendering if Plan Feedback wrapper is already shown (Plan Verifier scenario) */}
                                  {/* Also skip for plan-only responses when Plan Verifier (isHuman) is enabled */}
                                  {/* Hide feedback buttons when generating (like/regenerate in progress) */}
                                  {/* For PLANNER_META_AGENT/META_AGENT: Show feedback buttons when there's a final response (non-empty message) */}
                                  {/* Hide feedback buttons for pipeline agents but show response time */}
                                  {hasVisibleBubbleContent &&
                                    !showgenerateButton &&
                                    !isEditable &&
                                    // Previously this used isLastPlanInMessages (undefined). Use the actual intent:
                                    // skip when this is a plan-only response that should be handled by the plan verifier UI
                                    !(hasPlanContent && data?.message === "" && !hasPartsContent && isHuman && !hasToolDetails) &&
                                    !((agentType === PLANNER_META_AGENT || agentType === META_AGENT) && data?.message === "" && !hasPartsContent) && (
                                      <div className={`${chatBubbleCss.feedbackWrapper} feedbackWrapper-5`}>
                                        {data?.response_time && (
                                          <span className={chatBubbleCss.responseTime}>
                                            <span className={chatBubbleCss.time} title={`Response time: ${formatResponseTimeSeconds(data.response_time)}`}>
                                              {formatResponseTimeSeconds(data.response_time)}
                                            </span>
                                          </span>
                                        )}
                                        {agentType !== PIPELINE_AGENT && (
                                          <>
                                            <button className={`${chatBubbleCss.feedbackButton}`} onClick={() => handleFeedBack(like, session)} title="Good response">
                                              <SVGIcons icon="thumbs-up" width={16} height={16} />
                                            </button>
                                            <button className={`${chatBubbleCss.feedbackButton}`} onClick={() => handleFeedBack(dislike, session)} title="Not helpful">
                                              <SVGIcons icon="thumbs-down" width={16} height={16} />
                                            </button>
                                            <button
                                              className={`${chatBubbleCss.feedbackButton} ${generating ? chatBubbleCss.spinning : ""}`}
                                              onClick={() => handleFeedBack(regenerate, session)}
                                              title="Regenerate response">
                                              <SVGIcons icon="rotate-ccw" width={16} height={16} />
                                            </button>
                                          </>
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
                            {(() => {
                              // Remove "[Attached files: ...]" section from displayed message
                              let cleanMessage = data.message || "";
                              cleanMessage = cleanMessage.replace(/\[Attached files:[\s\S]*?\]/gi, "").trim();
                              if (!cleanMessage) return null;
                              return parse(DOMPurify.sanitize(cleanMessage.replace(/\n/g, "<br />")), {
                                replace: (domNode) => {
                                  if (domNode.name === "ul" || domNode.name === "ol") {
                                    domNode.attribs = domNode.attribs || {};
                                    domNode.attribs.class = (domNode.attribs.class || "") + " " + chatBubbleCss.markdownList;
                                  }
                                  if (domNode.name === "li") {
                                    domNode.attribs = domNode.attribs || {};
                                    domNode.attribs.class = (domNode.attribs.class || "") + " " + chatBubbleCss.markdownListItem;
                                  }
                                },
                              });
                            })()}
                          </div>
                        </div>
                      ) : null}
                      {/* Attached files display - from attachedFiles prop or parsed from message */}
                      {(() => {
                        // Use attachedFiles if available, otherwise try to parse from message
                        let filesToShow = data.attachedFiles;
                        if ((!filesToShow || filesToShow.length === 0) && typeof data.message === "string") {
                          // Parse files from "[Attached files: - path1 - path2]" format
                          const match = data.message.match(/\[Attached files:([\s\S]*?)\]/i);
                          if (match && match[1]) {
                            // Split by newline or " - " (with spaces) to avoid breaking filenames with hyphens
                            const fileLines = match[1].split(/\n| - /).map(s => s.trim()).filter(Boolean);
                            filesToShow = fileLines.map(filePath => {
                              // Extract filename from path
                              const fileName = filePath.split("/").pop() || filePath;
                              // Try to extract original name by removing email and UUID parts
                              // Format: original_name_email@domain.com_uuid1_uuid2_uuid3_uuid4.ext
                              // Or: original_name_uuid-uuid-uuid-uuid_email@domain.com_uuid_uuid_uuid_uuid.ext
                              const emailUuidPattern = /_[^_]+@[^_]+\.[^_]+_[a-f0-9]{4,}_[a-f0-9]{4,}_[a-f0-9]{4,}_[a-f0-9]{4,}\./i;
                              const uuidEmailPattern = /_[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}_[^_]+@[^_]+\.[^_]+_[a-f0-9]{4,}_[a-f0-9]{4,}_[a-f0-9]{4,}_[a-f0-9]{4,}\./i;
                              let displayName = fileName;

                              // Try the uuid-email pattern first (for filenames like optimization_results_uuid_email_uuid.ext)
                              let patternMatch = fileName.match(uuidEmailPattern);
                              if (!patternMatch) {
                                // Fall back to email-uuid pattern
                                patternMatch = fileName.match(emailUuidPattern);
                              }

                              if (patternMatch) {
                                // Get the extension
                                const ext = fileName.split(".").pop();
                                // Get everything before the pattern match
                                const beforePattern = fileName.substring(0, patternMatch.index);
                                displayName = beforePattern ? `${beforePattern}.${ext}` : fileName;
                              }
                              return {
                                name: displayName,
                                path: filePath,
                              };
                            });
                          }
                        }
                        if (!filesToShow || filesToShow.length === 0) return null;
                        return (
                          <div className={chatBubbleCss.attachedFilesContainer}>
                            {filesToShow.map((file, fileIdx) => (
                              <div
                                key={file.path || fileIdx}
                                className={chatBubbleCss.attachedFileChip}
                                onClick={() => onViewFile && onViewFile(file)}
                                title={`View ${file.name}`}
                              >
                                <SVGIcons icon="file" width={14} height={14} />
                                <span className={chatBubbleCss.attachedFileName}>
                                  {file.name.length > 25 ? `${file.name.substring(0, 22)}...` : file.name}
                                </span>
                              </div>
                            ))}
                          </div>
                        );
                      })()}
                    </div>
                    {(() => {
                      // Render timestamp below the bubble if available
                      const formattedTimestamp = formatMessageTimestamp(data?.start_timestamp);
                      if (!formattedTimestamp) return null;

                      return (
                        <div className={chatBubbleCss.timestamp} title={`Query sent at: ${formattedTimestamp.fullTime}`}>
                          {formattedTimestamp.displayText}
                        </div>
                      );
                    })()}
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
                showNamesOnly={props.canExecutionSteps === false}
              />
            </div>
          </div>
        )}

      <div className={`${"fixedDebugpanel"} ${styles.loadingChat}`} style={{ width: "100%", maxWidth: "98%" }}></div>
    </div>
  );
};

export default MsgBox;
