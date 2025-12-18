import React, { useMemo } from "react";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faChevronDown } from "@fortawesome/free-solid-svg-icons";
import styles from "./ExecutionStepsList.module.css";

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
    const contentVal =
      node.content ||
      node["Tool Output"] ||
      (node.raw && (node.raw.content || node.raw["Tool Output"] || node.raw["tool_output"] || node.raw.ToolOutput)) ||
      null;
    const toolNameRaw = node["Tool Name"] || null;
    const rawStatus = node.Status || node.status || node.state || "";
    const statusLower = String(rawStatus || "").toLowerCase().trim();

    if (nodeName) {
      if (statusLower.includes("started&completed")) {
        events.push({ type: "start", name: nodeName, toolName: toolNameRaw, originalIndex: i });
        events.push({ type: "complete", name: nodeName, originalIndex: i });
      } else if (statusLower.includes("started")) {
        events.push({ type: "start", name: nodeName, toolName: toolNameRaw, originalIndex: i });
      } else if (statusLower.includes("completed")) {
        events.push({ type: "complete", name: nodeName, content: contentVal, originalIndex: i });
      }
    } else if (contentVal) {
      // If the content payload contains an explicit node reference, keep it.
      // Otherwise treat it as generic content that may belong to the last-open node
      // or the most recently completed node if no open node exists.
      const forNode = node.forNode || node["Node Name"] || node.node_name || null;
      events.push({ type: "content", content: contentVal, originalIndex: i, forNode });
    }
  }

  const result = [];
  const openStack = [];
  const allNodes = new Map();
  let lastCompletedNode = null;

  for (const event of events) {
    if (event.type === "start") {
      const newNode = {
        "Node Name": event.name || "Node",
        "Tool Name": event.toolName,
        Status: "Started",
        parsedContents: [],
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
      allNodes.set(event.name, newNode);
    } else if (event.type === "content") {
      if (event.forNode && allNodes.has(event.forNode)) {
        const targetNode = allNodes.get(event.forNode);
        if (event.content) {
          targetNode.parsedContents.push(event.content);
        }
      } else if (openStack.length > 0) {
        const current = openStack[openStack.length - 1];
        if (event.content) {
          current.node.parsedContents.push(event.content);
        }
      } else if (lastCompletedNode) {
        if (event.content) {
          lastCompletedNode.parsedContents.push(event.content);
        }
      }
    } else if (event.type === "complete") {
      const idx = openStack.findIndex((s) => s.name === event.name);
      if (idx !== -1) {
        const completed = openStack[idx];
        completed.node.Status = "Completed";
        if (event.content) {
          completed.node.parsedContents.push(event.content);
        }
        lastCompletedNode = completed.node;
        openStack.splice(idx, 1);
      } else if (allNodes.has(event.name)) {
        const existingNode = allNodes.get(event.name);
        existingNode.Status = "Completed";
        if (event.content) {
          existingNode.parsedContents.push(event.content);
        }
        lastCompletedNode = existingNode;
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
    let latestLines = streamContents.map((c) => 
      typeof c?.content === "string" ? c.content.trim() : JSON.stringify(c?.content || "", null, 2)
    );

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
    const display =
      typeof last === "string"
        ? last.length > CHUNK_CHAR_LIMIT
          ? "…" + last.slice(-CHUNK_CHAR_LIMIT)
          : last
        : String(last);

    return display;
  };

  const streamingDisplay = isStreaming ? getStreamingContent() : null;
  const flatNodesWithStream = streamingDisplay && flatNodes.length > 0
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
      <button
        type="button"
        onClick={onToggleDetails}
        aria-expanded={showDetails}
        aria-controls={`${baseId}-${keyPrefix}-list`}
        className={styles.stepsToggleButton}
        title="Toggle execution steps"
        aria-label={`Execution summary: ${firstNodeName} to ${lastNodeName}`}
      >
        <FontAwesomeIcon
          icon={faChevronDown}
          className={`${styles.toggleIcon} ${showDetails ? styles.toggleIconExpanded : ""}`}
          aria-hidden="true"
        />
        <span className={styles.stepsLabel}>Steps</span>
        <span className={styles.stepsCount}>
          {stepCount} step{stepCount > 1 ? "s" : ""}
        </span>
      </button>

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
const TimelineStep = ({
  node,
  index,
  totalSteps,
  isLast,
  expandedNodes,
  onToggleNode,
  keyPrefix,
  isStreaming = false,
}) => {
  const name = node["Node Name"] || `Node ${index + 1}`;
  const toolName = node["Tool Name"] || null;
  let rawStatus = typeof node?.Status === "string" ? node.Status : "";
  if (rawStatus === "Started&Completed") rawStatus = "Completed";
  const statusLower = rawStatus.toLowerCase();

  const contents = Array.isArray(node.parsedContents) ? node.parsedContents : [];
  const hasContent = contents.length > 0;

  const nodeKey = `${keyPrefix}-${index}`;
  const isExpanded = expandedNodes[nodeKey];

  const handleToggle = () => {
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

      {/* Step Header - always clickable */}
      <div
        onClick={handleToggle}
        className={`${styles.timelineHeader} ${isLast && isStreaming ? styles.timelineHeaderActive : ""}`}
        role="button"
        aria-expanded={isExpanded}
        tabIndex={0}
        onKeyDown={handleKeyDown}
        title={`${name}${toolName ? ` (${toolName})` : ""}${rawStatus ? ` - ${rawStatus}` : ""}`}
      >
        {/* Step number circle */}
        <div className={`${styles.timelineCircle} ${styles.timelineCircleSmall} ${isLast && isStreaming ? styles.timelineCircleActive : ""}`}>
          {isLast && isStreaming ? (
            <span className={styles.timelineSpinner} aria-hidden="true" />
          ) : (
            <span className={styles.timelineDot} aria-hidden="true" />
          )}
        </div>

        {/* Step info */}
        <div className={styles.timelineInfo}>
          <span className={styles.timelineName}>
            {name}
            {toolName ? ` : ${toolName}` : ""}
          </span>
          {rawStatus && <span className={styles.timelineStatus}>{statusLower}</span>}
        </div>
        
        {/* Expand chevron - always visible */}
        <FontAwesomeIcon
          icon={faChevronDown}
          className={`${styles.timelineChevron} ${isExpanded ? styles.timelineChevronExpanded : ""}`}
          aria-hidden="true"
        />
      </div>

      {/* Expanded Content - shows "No contents available" when empty */}
      {isExpanded && (
        <div className={styles.timelineContent}>
          {hasContent ? (
            contents.map((content, contentIndex) => (
              <div key={`${keyPrefix}-content-${index}-${contentIndex}`} className={styles.timelineContentItem}>
                {content}
              </div>
            ))
          ) : (
            <div className={styles.noContent}>No contents available</div>
          )}
        </div>
      )}
    </div>
  );
};

export default ExecutionStepsList;
