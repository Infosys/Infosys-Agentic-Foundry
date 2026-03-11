import React, { useMemo } from "react";
import SVGIcons from "../../Icons/SVGIcons";
import styles from "./ExecutionStepsList.module.css";

// Steps will display the node's attached content (parsedContents) as the step label/description.

/**
 * Combines and processes raw node status events into a hierarchical structure
 * with proper content attachment.
 */
const combineNodeStatuses = (nodes) => {
  if (!Array.isArray(nodes)) return [];
  const events = [];

  for (let i = 0; i < nodes.length; i++) {
    const node = nodes[i];
    const nodeName = node["Node Name"] || node.node_name || node.node || node.name || null;

    // Normalize content from several possible shapes used by the server/tool responses
    // Priority: Tool Output > content > raw.Tool Output > raw.content
    let contentVal = null;

    // First priority: Tool Output field (actual tool results)
    if (node["Tool Output"]) {
      const toolOutput = node["Tool Output"];
      contentVal = typeof toolOutput === "string" ? toolOutput : JSON.stringify(toolOutput, null, 2);
    }
    // Second priority: direct content field
    else if (node.content) {
      const c = node.content;
      if (typeof c === "object") {
        contentVal = JSON.stringify(c, null, 2);
      } else if (typeof c === "string") {
        contentVal = c;
      }
    }
    // Third priority: raw object paths for Tool Output
    else if (node.raw && typeof node.raw === "object") {
      if (node.raw["Tool Output"]) {
        const rawToolOutput = node.raw["Tool Output"];
        contentVal = typeof rawToolOutput === "string" ? rawToolOutput : JSON.stringify(rawToolOutput, null, 2);
      } else if (node.raw["tool_output"]) {
        const rawToolOutput = node.raw["tool_output"];
        contentVal = typeof rawToolOutput === "string" ? rawToolOutput : JSON.stringify(rawToolOutput, null, 2);
      } else if (node.raw.ToolOutput) {
        const rawToolOutput = node.raw.ToolOutput;
        contentVal = typeof rawToolOutput === "string" ? rawToolOutput : JSON.stringify(rawToolOutput, null, 2);
      } else if (node.raw.content) {
        contentVal = typeof node.raw.content === "string" ? node.raw.content : JSON.stringify(node.raw.content, null, 2);
      }
    }

    const toolNameRaw = node["Tool Name"] || null;
    const rawStatus = node.Status || node.status || node.state || "";
    const statusLower = String(rawStatus || "")
      .toLowerCase()
      .trim();

    if (nodeName) {
      if (statusLower.includes("started&completed")) {
        events.push({ type: "start", name: nodeName, toolName: toolNameRaw, originalIndex: i, content: contentVal });
        events.push({ type: "complete", name: nodeName, originalIndex: i, content: contentVal });
      } else if (statusLower.includes("started")) {
        // Include content even for "started" status - content may arrive with the start event
        events.push({ type: "start", name: nodeName, toolName: toolNameRaw, originalIndex: i, content: contentVal });
      } else if (statusLower.includes("completed")) {
        events.push({ type: "complete", name: nodeName, content: contentVal, originalIndex: i });
      } else {
        // Fallback: treat any other status as a started node (handles "running", "active", etc.)
        events.push({ type: "start", name: nodeName, toolName: toolNameRaw, originalIndex: i, content: contentVal });
      }
    } else if (contentVal) {
      // Content without Node Name - attach to the most recent node
      // Find the last node that was started
      const forNode = node.forNode || node["Node Name"] || node.node_name || null;
      events.push({ type: "content", content: contentVal, originalIndex: i, forNode });
    }
  }

  const result = [];
  const openStack = [];
  let lastCompletedNode = null;

  for (const event of events) {
    if (event.type === "start") {
      // Only skip if there's an actively OPEN (not yet completed) node with the same name
      const existingOpenIdx = openStack.findIndex((s) => s.name === event.name);
      if (existingOpenIdx !== -1) {
        // Same-name node is still open — update its content instead of creating a duplicate
        const existingNode = openStack[existingOpenIdx].node;
        if (event.content && !existingNode.parsedContents.includes(event.content)) {
          existingNode.parsedContents.push(event.content);
        }
        continue;
      }

      // Create a new node (even if the same name appeared before — it's a new execution)
      const newNode = {
        "Node Name": event.name || "Node",
        "Tool Name": event.toolName,
        Status: "Started",
        parsedContents: event.content ? [event.content] : [],
        children: [],
        depth: openStack.length,
      };

      if (openStack.length > 0) {
        const parent = openStack[openStack.length - 1];
        parent.node.children.push(newNode);
      } else {
        result.push(newNode);
      }

      openStack.push({ node: newNode, name: event.name });
    } else if (event.type === "content") {
      if (openStack.length > 0) {
        // Attach content to the matching open node by forNode, or to the most recent open node
        let target = null;
        if (event.forNode) {
          const match = [...openStack].reverse().find((s) => s.name === event.forNode);
          if (match) target = match.node;
        }
        if (!target) target = openStack[openStack.length - 1].node;
        if (event.content) {
          target.parsedContents.push(event.content);
        }
      } else if (lastCompletedNode) {
        if (event.content) {
          lastCompletedNode.parsedContents.push(event.content);
        }
      }
    } else if (event.type === "complete") {
      const idx = openStack.findIndex((s) => s.name === event.name);
      if (idx !== -1) {
        // Found matching open node — mark it completed
        const completed = openStack[idx];
        completed.node.Status = "Completed";
        if (event.content) {
          completed.node.parsedContents.push(event.content);
        }
        lastCompletedNode = completed.node;
        openStack.splice(idx, 1);
      } else {
        // No matching open node — create a standalone completed node
        // This handles nodes that only emit "Completed" without a prior "Started"
        const newNode = {
          "Node Name": event.name || "Node",
          "Tool Name": event.toolName || null,
          Status: "Completed",
          parsedContents: event.content ? [event.content] : [],
          children: [],
          depth: openStack.length,
        };

        if (openStack.length > 0) {
          const parent = openStack[openStack.length - 1];
          parent.node.children.push(newNode);
        } else {
          result.push(newNode);
        }
        lastCompletedNode = newNode;
      }
    }
  }

  return result;
};

/**
 * Flattens hierarchical nodes for display with depth info and numbering
 */
const flattenNodesForDisplay = (nodeList, depth = 0, parentNumber = "") => {
  const flattened = [];
  let childCounter = 1;

  for (let idx = 0; idx < nodeList.length; idx++) {
    const node = nodeList[idx];
    const nodeDepth = typeof node.depth === "number" ? node.depth : depth;

    let displayNumber;
    if (parentNumber) {
      displayNumber = `${parentNumber}.${childCounter}`;
    } else {
      displayNumber = String(idx + 1);
    }

    flattened.push({ ...node, depth: nodeDepth, displayNumber, children: node.children || [] });

    if (parentNumber) {
      childCounter++;
    }
  }
  return flattened;
};

/**
 * ExecutionStepsList - Reusable timeline-style component for displaying execution steps
 * Handles all node processing internally - just pass raw nodes array
 *
 * @param {Array} props.rawNodes - Raw nodes array from SSE/API (processes internally)
 * @param {boolean} props.showDetails - Whether the list is expanded
 * @param {Function} props.onToggleDetails - Callback to toggle list visibility
 * @param {Object} props.expandedNodes - Object tracking which nodes are expanded by key
 * @param {Function} props.onToggleNode - Callback to toggle individual node expansion
 * @param {string} props.keyPrefix - Prefix for unique keys (e.g., "initial" or "inline")
 * @param {string} props.baseId - Base ID for accessibility
 * @param {React.Ref} props.listRef - Ref for the list element
 * @param {boolean} props.isStreaming - Whether currently streaming
 * @param {Array} props.streamContents - Streaming content chunks
 * @param {number} props.currentNodeIndex - Current streaming node index (for slicing during stream)
 */
const ExecutionStepsList = ({
  rawNodes = [],
  showDetails = false,
  onToggleDetails,
  expandedNodes = {},
  onToggleNode,
  keyPrefix = "steps",
  baseId = "execution-steps",
  listRef,
  isStreaming = false,
  streamContents = [],
  currentNodeIndex = -1,
  renderToggle = true,
  showNamesOnly = false, // When true, only show node names without expandable content (for restricted access)
}) => {
  // Process raw nodes internally with memoization
  const processedNodes = useMemo(() => {
    if (!Array.isArray(rawNodes) || rawNodes.length === 0) return [];
    const hierarchical = combineNodeStatuses(rawNodes);
    return flattenNodesForDisplay(hierarchical);
  }, [rawNodes]);

  // For streaming, slice nodes up to currentNodeIndex
  const displayNodes = useMemo(() => {
    if (isStreaming && currentNodeIndex >= 0) {
      return processedNodes.slice(0, currentNodeIndex + 1);
    }
    return processedNodes;
  }, [processedNodes, isStreaming, currentNodeIndex]);

  // Early return when no nodes
  if (!Array.isArray(displayNodes) || displayNodes.length === 0) {
    return null;
  }

  // Flatten nodes to remove parent-child hierarchy - show all nodes sequentially
  const flattenNodes = (nodeList) => {
    const result = [];
    nodeList.forEach((node) => {
      result.push(node);
      if (Array.isArray(node.children) && node.children.length > 0) {
        result.push(...flattenNodes(node.children));
      }
    });
    return result;
  };

  const flatNodes = flattenNodes(displayNodes);
  const stepCount = flatNodes.length;
  const firstNodeName = flatNodes[0]?.["Node Name"] || "Node 1";
  const lastNodeName = flatNodes[flatNodes.length - 1]?.["Node Name"] || `Node ${stepCount}`;

  // Process streaming content for display
  const getStreamingContent = () => {
    if (!Array.isArray(streamContents) || streamContents.length === 0) return null;

    const CHUNK_CHAR_LIMIT = 300;
    let latestLines = streamContents.map((c) => (typeof c?.content === "string" ? c.content.trim() : JSON.stringify(c?.content || "", null, 2)));

    // Remove consecutive duplicates
    latestLines = latestLines.reduce((acc, cur) => {
      if (acc.length === 0 || acc[acc.length - 1] !== cur) acc.push(cur);
      return acc;
    }, []);

    // Keep only the last N lines
    const MAX_LINES = 20;
    if (latestLines.length > MAX_LINES) latestLines = latestLines.slice(-MAX_LINES);

    if (latestLines.length === 0) return null;

    const last = latestLines[latestLines.length - 1];
    const display = typeof last === "string" ? (last.length > CHUNK_CHAR_LIMIT ? "…" + last.slice(-CHUNK_CHAR_LIMIT) : last) : String(last);

    return display;
  };

  const streamingDisplay = isStreaming ? getStreamingContent() : null;
  const flatNodesWithStream =
    streamingDisplay && flatNodes.length > 0
      ? flatNodes.map((n, i) => {
        if (i !== flatNodes.length - 1) return n;
        const existingContents = Array.isArray(n.parsedContents) ? n.parsedContents : [];
        const lastContent = existingContents[existingContents.length - 1];
        if (lastContent === streamingDisplay) return n;
        return { ...n, parsedContents: [...existingContents, streamingDisplay] };
      })
      : flatNodes;

  // For streaming mode, show timeline directly without dropdown (streaming text embedded into last node)
  if (isStreaming) {
    // Ensure last node is expanded during streaming only when it has content
    const lastIndex = flatNodesWithStream.length - 1;
    const lastNode = flatNodesWithStream[lastIndex];
    const lastNodeHasContent = Array.isArray(lastNode?.parsedContents) && lastNode.parsedContents.length > 0;
    const lastNodeKey = `${keyPrefix}-${lastIndex}`;
    const effectiveExpandedNodes = { ...(expandedNodes || {}) };
    if (lastNodeHasContent) {
      effectiveExpandedNodes[lastNodeKey] = true;
    }

    return (
      <div className={styles.stepsStreamingContainer}>
        <div className={`${styles.timeline} ${styles.timelineStreaming}`} ref={listRef}>
          {flatNodesWithStream.map((node, index) => (
            <TimelineStep
              key={`${keyPrefix}-node-${index}`}
              node={node}
              index={index}
              totalSteps={flatNodesWithStream.length}
              isLast={index === flatNodesWithStream.length - 1}
              expandedNodes={effectiveExpandedNodes}
              onToggleNode={onToggleNode}
              keyPrefix={keyPrefix}
              isStreaming={isStreaming}
              showNamesOnly={showNamesOnly}
            />
          ))}
        </div>
      </div>
    );
  }

  // Non-streaming mode with dropdown toggle
  return (
    <div className={styles.stepsDropdownContainer}>
      {/* Toggle Button */}
      {renderToggle && (
        <div
          onClick={onToggleDetails}
          aria-expanded={showDetails}
          aria-controls={`${baseId}-${keyPrefix}-list`}
          className={`${styles.stepsToggleButton} ${showDetails ? styles.stepsToggleButtonExpanded : ""}`}
          title="Toggle reasoning steps"
          aria-label={`Reasoning summary: ${firstNodeName} to ${lastNodeName}`}>
          <div className={styles.stepsToggleLeft}>
            <SVGIcons icon="brain" width={20} height={20} color="currentColor" stroke="currentColor" />
            <span className={styles.stepsLabel}>Reasoning Steps ({stepCount})</span>
          </div>
          <SVGIcons
            icon="chevron-down-sm"
            width={16}
            height={16}
            color="currentColor"
            stroke="currentColor"
            style={{ transform: showDetails ? "rotate(180deg)" : "rotate(0deg)", transition: "transform 0.2s ease" }}
          />
        </div>
      )}

      {/* Timeline Steps List */}
      {showDetails && (
        <div id={`${baseId}-${keyPrefix}-list`} className={styles.timeline} ref={listRef}>
          {flatNodes.map((node, index) => (
            <TimelineStep
              key={`${keyPrefix}-node-${index}`}
              node={node}
              index={index}
              totalSteps={flatNodes.length}
              isLast={index === flatNodes.length - 1}
              expandedNodes={expandedNodes}
              onToggleNode={onToggleNode}
              keyPrefix={keyPrefix}
              isStreaming={false}
              showNamesOnly={showNamesOnly}
            />
          ))}
        </div>
      )}
    </div>
  );
};

/**
 * TimelineStep - Individual timeline step component
 * All steps are clickable and expand to show content or "No contents available"
 */
const TimelineStep = ({ node, index, totalSteps, isLast, expandedNodes, onToggleNode, keyPrefix, isStreaming = false, showNamesOnly = false }) => {
  const name = node["Node Name"] || `Node ${index + 1}`;
  const toolName = node["Tool Name"] || null;
  let rawStatus = typeof node?.Status === "string" ? node.Status : "";
  if (rawStatus === "Started&Completed") rawStatus = "Completed";

  const contents = Array.isArray(node.parsedContents) ? node.parsedContents : [];
  const hasContent = contents.length > 0;

  const nodeKey = `${keyPrefix}-${index}`;
  const isExpanded = expandedNodes[nodeKey];

  // Default descriptions for common node names
  const getDefaultDescription = (nodeName) => {
    const descriptions = {
      "Generating Context": "Analyzed query and gathered relevant context from knowledge base",
      "Thinking...": "Processed information using advanced reasoning algorithms",
      "Thinking": "Processed information using advanced reasoning algorithms",
      "Memory Updation": "Updated conversation memory with new insights",
      "Memory Update": "Updated conversation memory with new insights",
      "Planning": "Creating execution plan for the task",
      "Executing": "Running the planned actions",
      "Tool Execution": "Executing tool to gather information",
      "Tool Call": "Calling external tool for processing",
      "Response Generation": "Generating final response",
    };
    return descriptions[nodeName] || null;
  };

  // Get description - prefer content, fallback to default
  const description = hasContent && typeof contents[0] === "string"
    ? contents[0].trim()
    : getDefaultDescription(name);

  const handleToggle = () => {
    // Don't allow expansion in showNamesOnly mode
    if (showNamesOnly) return;
    if (onToggleNode) {
      onToggleNode(nodeKey);
    }
  };

  const handleKeyDown = (e) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      handleToggle();
    }
  };

  return (
    <div className={`${styles.timelineStep} ${isLast ? styles.timelineStepLast : ""}`}>
      {/* Timeline connector line */}
      {!isLast && <div className={styles.timelineConnector} />}

      {/* Step Header */}
      <div
        onClick={showNamesOnly ? undefined : handleToggle}
        className={`${styles.timelineHeader} ${index === 0 ? styles.timelineHeaderActive : ""} ${showNamesOnly ? styles.timelineHeaderReadOnly : ""}`}
        role={showNamesOnly ? undefined : "button"}
        aria-expanded={showNamesOnly ? undefined : isExpanded}
        tabIndex={showNamesOnly ? -1 : 0}
        onKeyDown={showNamesOnly ? undefined : handleKeyDown}
        title={`${name}${toolName ? ` (${toolName})` : ""}${rawStatus ? ` - ${rawStatus}` : ""}`}>
        {/* Step circle/icon */}
        <div className={`${styles.timelineCircle} ${styles.timelineCircleSmall} ${isLast && isStreaming ? styles.timelineCircleActive : ""}`}>
          {isLast && isStreaming ? (
            <span className={styles.timelineSpinner} aria-hidden="true" />
          ) : (
            <span className={styles.timelineDot} aria-hidden="true" />
          )}
        </div>

        {/* Step info - name and description */}
        <div className={styles.timelineInfo}>
          <span className={styles.timelineName}>
            {name}
            {toolName ? ` : ${toolName}` : ""}
          </span>
        </div>

        {/* Status and Chevron on right side */}
        <div className={styles.timelineRight}>
          <span className={`${styles.timelineStatus} ${rawStatus === "Completed" ? styles.statusCompleted : rawStatus === "Started" ? styles.statusStarted : ""}`}>
            {rawStatus || "Completed"}
          </span>
          {/* Hide chevron in showNamesOnly mode */}
          {!showNamesOnly && (
            <span className={`${styles.timelineChevron} ${isExpanded ? styles.timelineChevronExpanded : ""}`}>
              <SVGIcons icon="chevron-down-sm" width={16} height={16} color="currentColor" />
            </span>
          )}
        </div>
      </div>

      {/* Expanded Content - hidden in showNamesOnly mode */}
      {!showNamesOnly && isExpanded && (
        <div className={styles.timelineContent}>
          {contents.length > 0 ? (
            contents.map((content, contentIndex) => (
              <div key={`${keyPrefix}-content-${index}-${contentIndex}`} className={styles.timelineContentItem}>
                {content}
              </div>
            ))
          ) : (
            <div className={styles.timelineNoContent}>No contents available</div>
          )}
        </div>
      )}
    </div>
  );
};

export default ExecutionStepsList;
