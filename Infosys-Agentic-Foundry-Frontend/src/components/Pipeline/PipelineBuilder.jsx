/**
 * Pipeline Builder Component
 *
 * Visual node-based pipeline builder with drag-and-drop canvas,
 * node palette, and properties panel for configuration.
 *
 * Features:
 * - Drag-and-drop nodes (Input, Agent, Condition, Output)
 * - Visual connections between nodes with SVG paths
 * - Properties panel for node configuration
 * - Canvas controls: pan, zoom, fit view, clear
 * - Save modal with validation
 */

import React, { useState, useEffect, useCallback, useRef, useMemo } from "react";
import Button from "../../iafComponents/GlobalComponents/Buttons/Button";
import FullModal from "../../iafComponents/GlobalComponents/FullModal";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faPlus, faMinus, faExpand, faTrash, faTimes, faRobot, faCodeBranch, faFlag, faComments, faSignInAlt, faCog, faHand, faCubes } from "@fortawesome/free-solid-svg-icons";
import { usePipelineService } from "../../services/pipelineService";
import { useMessage } from "../../Hooks/MessageContext";
import { useErrorHandler } from "../../Hooks/useErrorHandler";
import styles from "../../css_modules/Pipeline.module.css";
import { getAgentTypeAbbreviation, generateId } from "./pipelineUtils";
import Cookies from "js-cookie";
import DeleteModal from "../commonComponents/DeleteModal";
import NewCommonDropdown from "../commonComponents/NewCommonDropdown";
import SVGIcons from "../../Icons/SVGIcons";

// Node type constants
const NODE_TYPES = {
  INPUT: "input",
  AGENT: "agent",
  CONDITION: "condition",
  OUTPUT: "output",
};

// Node type configurations
const NODE_CONFIG = {
  [NODE_TYPES.INPUT]: {
    label: "Input",
    description: "On every chat message pipeline will be triggered",
    icon: faComments,
    paletteIcon: faSignInAlt,
    headerClass: "nodeHeaderInput",
    paletteClass: "paletteNodeInput",
    canReceive: false,
    canSend: true,
    maxCount: 1,
    maxIncoming: 0,
    maxOutgoing: Infinity,
  },
  [NODE_TYPES.AGENT]: {
    label: "Agent",
    icon: faRobot,
    headerClass: "nodeHeaderAgent",
    paletteClass: "paletteNodeAgent",
    canReceive: true,
    canSend: true,
    maxCount: Infinity,
    maxIncoming: Infinity,
    maxOutgoing: Infinity,
  },
  [NODE_TYPES.CONDITION]: {
    label: "Condition",
    icon: faCodeBranch,
    headerClass: "nodeHeaderCondition",
    paletteClass: "paletteNodeCondition",
    canReceive: true,
    canSend: true,
    maxCount: Infinity,
    maxIncoming: 1,
    maxOutgoing: Infinity,
  },
  [NODE_TYPES.OUTPUT]: {
    label: "Output",
    icon: faFlag,
    headerClass: "nodeHeaderOutput",
    paletteClass: "paletteNodeOutput",
    canReceive: true,
    canSend: false,
    maxCount: Infinity,
    maxIncoming: 1,
    maxOutgoing: 0,
  },
};

/**
 * Output Schema Editor Component
 * Uses local state to allow free-form typing, validates JSON on blur
 */
const OutputSchemaEditor = ({ value, onChange }) => {
  const [text, setText] = useState(value ? JSON.stringify(value, null, 2) : "");
  const [isValid, setIsValid] = useState(true);

  useEffect(() => {
    const newText = value ? JSON.stringify(value, null, 2) : "";
    setText(newText);
    setIsValid(true);
  }, [value]);

  const handleChange = (e) => {
    setText(e.target.value);
  };

  const handleBlur = () => {
    const trimmed = text.trim();
    if (!trimmed) {
      onChange(null);
      setIsValid(true);
      return;
    }
    try {
      const parsed = JSON.parse(trimmed);
      onChange(parsed);
      setIsValid(true);
    } catch {
      setIsValid(false);
    }
  };

  return (
    <div className={styles.propertyGroup}>
      <label className={styles.propertyLabel}>Output Schema</label>
      <textarea
        className={`${styles.propertyTextarea} ${!isValid ? styles.invalidInput : ""}`}
        value={text}
        onChange={handleChange}
        onBlur={handleBlur}
        placeholder='{"result": "string"}'
      />
      {!isValid && <div className={styles.inputError}>Invalid JSON format</div>}
      <div className={styles.propertyInfo}>Enter valid JSON schema. Leave empty for no schema validation.</div>
    </div>
  );
};

/**
 * PipelineBuilder - Main canvas component
 * @param {Object} props
 * @param {Object} props.pipeline - Existing pipeline data (for editing)
 * @param {Function} props.onBack - Handler to go back to list
 * @param {Function} props.onSave - Handler after successful save
 */
const PipelineBuilder = ({ pipeline, onBack, onSave, readOnly = false }) => {
  // Canvas state
  const [nodes, setNodes] = useState(new Map());
  const [edges, setEdges] = useState(new Map());
  const [zoom, setZoom] = useState(1);
  const [panOffset, setPanOffset] = useState({ x: 0, y: 0 });
  const [renderKey, setRenderKey] = useState(0); // Force re-render after zoom

  // Interaction state
  const [selectedNode, setSelectedNode] = useState(null);
  const [selectedEdge, setSelectedEdge] = useState(null);
  const [isDragging, setIsDragging] = useState(false);
  const [draggedNode, setDraggedNode] = useState(null);
  const [dragOffset, setDragOffset] = useState({ x: 0, y: 0 });
  const [isPanning, setIsPanning] = useState(false);
  const [panStart, setPanStart] = useState({ x: 0, y: 0 });
  const [panMode, setPanMode] = useState(false);

  // Connection state
  const [isConnecting, setIsConnecting] = useState(false);
  const [connectionStart, setConnectionStart] = useState(null);
  const [tempConnection, setTempConnection] = useState(null);
  const [isConditionalConnection, setIsConditionalConnection] = useState(false);

  // Modal state
  const [showSaveModal, setShowSaveModal] = useState(false);
  const [showConditionModal, setShowConditionModal] = useState(false);
  const [pendingConnection, setPendingConnection] = useState(null);
  const [showAddKeyModal, setShowAddKeyModal] = useState(false);
  const [deleteNodeConfirm, setDeleteNodeConfirm] = useState(null);
  const [showClearCanvasConfirm, setShowClearCanvasConfirm] = useState(false);

  // Form state
  const [pipelineName, setPipelineName] = useState("");
  const [pipelineDescription, setPipelineDescription] = useState("");
  const [conditionText, setConditionText] = useState("");
  const [newKeyLabel, setNewKeyLabel] = useState("");
  const [newKeyType, setNewKeyType] = useState("string");
  const [newKeyDescription, setNewKeyDescription] = useState("");

  // Available agents
  const [availableAgents, setAvailableAgents] = useState([]);

  // Refs
  const canvasRef = useRef(null);
  const svgRef = useRef(null);

  const { createPipeline, updatePipeline, getAvailableAgents } = usePipelineService();
  const { addMessage } = useMessage();
  const { handleError } = useErrorHandler();

  /**
   * Delete edge/connection
   */
  const handleDeleteEdge = useCallback(
    (edgeId) => {
      setEdges((prev) => {
        const newMap = new Map(prev);
        newMap.delete(edgeId);
        return newMap;
      });

      if (selectedEdge === edgeId) {
        setSelectedEdge(null);
      }
    },
    [selectedEdge]
  );

  /**
   * Load existing pipeline data
   */
  useEffect(() => {
    if (pipeline) {
      setPipelineName(pipeline.pipeline_name || "");
      setPipelineDescription(pipeline.pipeline_description || "");

      // Load nodes
      const definition = pipeline.pipeline_definition;
      if (definition?.nodes) {
        const nodeMap = new Map();
        definition.nodes.forEach((node) => {
          nodeMap.set(node.node_id, node);
        });
        setNodes(nodeMap);
      }

      // Load edges
      if (definition?.edges) {
        const edgeMap = new Map();
        definition.edges.forEach((edge) => {
          edgeMap.set(edge.edge_id, edge);
        });
        setEdges(edgeMap);
      }
    }
  }, [pipeline]);

  /**
   * Force re-render connections after zoom/pan changes
   * This ensures connection paths are recalculated after CSS transforms are applied
   */
  useEffect(() => {
    const rafId = requestAnimationFrame(() => {
      setRenderKey((prev) => prev + 1);
    });
    return () => cancelAnimationFrame(rafId);
  }, [zoom, panOffset]);

  /**
   * Fetch available agents (only once on mount)
   */
  useEffect(() => {
    const fetchAgents = async () => {
      try {
        const response = await getAvailableAgents();
        setAvailableAgents(response?.agents || []);
      } catch (error) {
        console.error("Failed to fetch agents:", error);
      }
    };
    fetchAgents();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  /**
   * Handle keyboard shortcuts (Delete key for edges)
   */
  useEffect(() => {
    const handleKeyDown = (event) => {
      if ((event.key === "Delete" || event.key === "Backspace") && selectedEdge) {
        const activeElement = document.activeElement;
        if (activeElement && (activeElement.tagName === "INPUT" || activeElement.tagName === "TEXTAREA")) {
          return;
        }
        event.preventDefault();
        handleDeleteEdge(selectedEdge);
      }
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [selectedEdge, handleDeleteEdge]);

  /**
   * Convert Map to Array for operations
   */
  const nodesArray = useMemo(() => Array.from(nodes.values()), [nodes]);
  const edgesArray = useMemo(() => Array.from(edges.values()), [edges]);

  /**
   * Check if we can open save modal - requires at least one node
   */
  const canOpenSaveModal = useMemo(() => {
    return nodesArray.length > 0;
  }, [nodesArray]);

  /**
   * Check if save is enabled - requires nodes, pipeline name, and output node
   */
  const canSave = useMemo(() => {
    const hasNodes = nodesArray.length > 0;
    const hasName = pipelineName.trim().length > 0;
    const hasDescription = pipelineDescription.trim().length > 0;
    const hasOutputNode = nodesArray.some((n) => n.node_type === NODE_TYPES.OUTPUT);

    const allRequiredFieldsFilled = nodesArray.every((node) => {
      if (node.node_type === NODE_TYPES.AGENT || node.node_type === NODE_TYPES.OUTPUT) {
        return node.node_name && node.node_name.trim().length > 0;
      }
      return true;
    });

    return hasNodes && hasName && hasDescription && hasOutputNode && allRequiredFieldsFilled;
  }, [nodesArray, pipelineName, pipelineDescription]);

  /**
   * Get canvas coordinates from mouse event
   */
  const getCanvasCoords = useCallback(
    (e) => {
      if (!canvasRef.current) return { x: 0, y: 0 };
      const rect = canvasRef.current.getBoundingClientRect();
      return {
        x: (e.clientX - rect.left - panOffset.x) / zoom,
        y: (e.clientY - rect.top - panOffset.y) / zoom,
      };
    },
    [zoom, panOffset]
  );

  /**
   * Handle node palette drag start
   */
  const handlePaletteDragStart = useCallback((e, nodeType) => {
    e.dataTransfer.setData("nodeType", nodeType);
    e.dataTransfer.effectAllowed = "copy";
  }, []);

  /**
   * Get default config for node type
   */
  const getDefaultConfig = (nodeType) => {
    switch (nodeType) {
      case NODE_TYPES.INPUT:
        return { input_schema: {}, description: {} };
      case NODE_TYPES.AGENT:
        return {
          agent_id: "",
          tool_verifier: false,
          plan_verifier: false,
          accessible_inputs: { input_keys: ["all"] },
        };
      case NODE_TYPES.CONDITION:
        return { condition: "" };
      case NODE_TYPES.OUTPUT:
        return { output_schema: null };
      default:
        return {};
    }
  };

  /**
   * Handle canvas drop
   */
  const handleCanvasDrop = useCallback(
    (e) => {
      e.preventDefault();
      const nodeType = e.dataTransfer.getData("nodeType");
      if (!nodeType || !NODE_CONFIG[nodeType]) return;

      if (nodeType === NODE_TYPES.INPUT) {
        const inputCount = nodesArray.filter((n) => n.node_type === NODE_TYPES.INPUT).length;
        if (inputCount >= 1) {
          addMessage("Only one Input node is allowed per pipeline", "error");
          return;
        }
      }

      const coords = getCanvasCoords(e);
      const newNode = {
        node_id: generateId("node"),
        node_name: nodeType === NODE_TYPES.AGENT || nodeType === NODE_TYPES.OUTPUT ? "" : NODE_CONFIG[nodeType].label,
        node_type: nodeType,
        position: { x: coords.x - 100, y: coords.y - 40 },
        config: getDefaultConfig(nodeType),
      };

      setNodes((prev) => new Map(prev).set(newNode.node_id, newNode));
      setSelectedNode(newNode.node_id);
    },
    [nodesArray, getCanvasCoords, addMessage]
  );

  /**
   * Handle canvas drag over
   */
  const handleCanvasDragOver = useCallback((e) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = "copy";
  }, []);

  /**
   * Handle node drag start
   */
  const handleNodeDragStart = useCallback(
    (e, nodeId) => {
      // Check if clicked on connection point using data attribute
      if (e.target.closest("[data-connection-point]")) return;

      const node = nodes.get(nodeId);
      if (!node) return;

      setDraggedNode(nodeId);
      setIsDragging(true);

      const coords = getCanvasCoords(e);
      setDragOffset({
        x: coords.x - node.position.x,
        y: coords.y - node.position.y,
      });
    },
    [nodes, getCanvasCoords]
  );

  /**
   * Handle mouse move for dragging/panning/connecting
   */
  const handleMouseMove = useCallback(
    (e) => {
      if (isDragging && draggedNode) {
        const coords = getCanvasCoords(e);
        setNodes((prev) => {
          const newMap = new Map(prev);
          const node = newMap.get(draggedNode);
          if (node) {
            newMap.set(draggedNode, {
              ...node,
              position: {
                x: coords.x - dragOffset.x,
                y: coords.y - dragOffset.y,
              },
            });
          }
          return newMap;
        });
      }

      if (isPanning) {
        setPanOffset({
          x: e.clientX - panStart.x,
          y: e.clientY - panStart.y,
        });
      }

      if (isConnecting && connectionStart) {
        const coords = getCanvasCoords(e);
        setTempConnection({
          startX: connectionStart.x,
          startY: connectionStart.y,
          endX: coords.x,
          endY: coords.y,
        });
      }
    },
    [isDragging, draggedNode, dragOffset, isPanning, panStart, isConnecting, connectionStart, getCanvasCoords]
  );

  /**
   * Handle mouse up
   */
  const handleMouseUp = useCallback(() => {
    setIsDragging(false);
    setDraggedNode(null);
    setIsPanning(false);

    if (isConnecting) {
      setIsConnecting(false);
      setConnectionStart(null);
      setTempConnection(null);
    }
  }, [isConnecting]);

  /**
   * Handle right-click for panning
   */
  const handleContextMenu = useCallback(
    (e) => {
      e.preventDefault();
      if (!canvasRef.current) return;

      setIsPanning(true);
      setPanStart({
        x: e.clientX - panOffset.x,
        y: e.clientY - panOffset.y,
      });
    },
    [panOffset]
  );

  /**
   * Handle connection start
   */
  const handleConnectionStart = useCallback(
    (e, nodeId, isOutput) => {
      e.stopPropagation();

      const node = nodes.get(nodeId);
      if (!node) return;

      const config = NODE_CONFIG[node.node_type];
      if (isOutput && !config.canSend) return;
      if (!isOutput && !config.canReceive) return;

      const nodeEl = document.getElementById(`node-${nodeId}`);
      if (!nodeEl) return;

      const rect = nodeEl.getBoundingClientRect();
      const canvasRect = canvasRef.current.getBoundingClientRect();

      const x = isOutput ? (rect.right - canvasRect.left - panOffset.x) / zoom : (rect.left - canvasRect.left - panOffset.x) / zoom;
      const y = (rect.top + rect.height / 2 - canvasRect.top - panOffset.y) / zoom;

      setIsConnecting(true);
      setIsConditionalConnection(e.shiftKey);
      setConnectionStart({
        nodeId,
        isOutput,
        x,
        y,
      });
    },
    [nodes, zoom, panOffset]
  );

  /**
   * Handle connection end
   */
  const handleConnectionEnd = useCallback(
    (e, nodeId, isInput) => {
      e.stopPropagation();

      if (!isConnecting || !connectionStart) return;
      if (!isInput || connectionStart.isOutput === false) {
        setIsConnecting(false);
        setConnectionStart(null);
        setTempConnection(null);
        return;
      }

      const sourceNode = nodes.get(connectionStart.nodeId);
      const targetNode = nodes.get(nodeId);

      if (!sourceNode || !targetNode) {
        setIsConnecting(false);
        setConnectionStart(null);
        setTempConnection(null);
        return;
      }

      const sourceConfig = NODE_CONFIG[sourceNode.node_type];
      const targetConfig = NODE_CONFIG[targetNode.node_type];

      if (!sourceConfig.canSend || !targetConfig.canReceive) {
        addMessage("Invalid connection", "error");
        setIsConnecting(false);
        setConnectionStart(null);
        setTempConnection(null);
        return;
      }

      const existingEdge = edgesArray.find((e) => e.source_node_id === connectionStart.nodeId && e.target_node_id === nodeId);
      if (existingEdge) {
        addMessage("Connection already exists", "error");
        setIsConnecting(false);
        setConnectionStart(null);
        setTempConnection(null);
        return;
      }

      const outgoingCount = edgesArray.filter((e) => e.source_node_id === connectionStart.nodeId).length;
      if (sourceConfig.maxOutgoing !== undefined && outgoingCount >= sourceConfig.maxOutgoing) {
        addMessage(`${sourceConfig.label} node can only have ${sourceConfig.maxOutgoing} outgoing connection(s)`, "error");
        setIsConnecting(false);
        setConnectionStart(null);
        setTempConnection(null);
        return;
      }

      const incomingCount = edgesArray.filter((e) => e.target_node_id === nodeId).length;
      if (targetConfig.maxIncoming !== undefined && incomingCount >= targetConfig.maxIncoming) {
        addMessage(`${targetConfig.label} node can only have ${targetConfig.maxIncoming} incoming connection(s)`, "error");
        setIsConnecting(false);
        setConnectionStart(null);
        setTempConnection(null);
        return;
      }

      if (isConditionalConnection) {
        setPendingConnection({
          source_node_id: connectionStart.nodeId,
          target_node_id: nodeId,
        });
        setShowConditionModal(true);
      } else {
        const newEdge = {
          edge_id: generateId("edge"),
          source_node_id: connectionStart.nodeId,
          target_node_id: nodeId,
        };
        setEdges((prev) => new Map(prev).set(newEdge.edge_id, newEdge));
      }

      setIsConnecting(false);
      setConnectionStart(null);
      setTempConnection(null);
      setIsConditionalConnection(false);
    },
    [isConnecting, connectionStart, nodes, edgesArray, isConditionalConnection, addMessage]
  );

  /**
   * Add conditional connection
   */
  const handleAddCondition = useCallback(() => {
    if (!pendingConnection || !conditionText.trim()) return;

    const newEdge = {
      edge_id: generateId("edge"),
      source_node_id: pendingConnection.source_node_id,
      target_node_id: pendingConnection.target_node_id,
    };

    setEdges((prev) => new Map(prev).set(newEdge.edge_id, newEdge));
    setShowConditionModal(false);
    setPendingConnection(null);
    setConditionText("");
  }, [pendingConnection, conditionText]);

  /**
   * Delete node
   */
  const handleDeleteNode = useCallback(
    (nodeId) => {
      setNodes((prev) => {
        const newMap = new Map(prev);
        newMap.delete(nodeId);
        return newMap;
      });

      setEdges((prev) => {
        const newMap = new Map(prev);
        prev.forEach((edge, edgeId) => {
          if (edge.source_node_id === nodeId || edge.target_node_id === nodeId) {
            newMap.delete(edgeId);
          }
        });
        return newMap;
      });

      if (selectedNode === nodeId) {
        setSelectedNode(null);
      }
      setDeleteNodeConfirm(null);
    },
    [selectedNode]
  );

  /**
   * Update node property
   */
  const updateNodeProperty = useCallback((nodeId, path, value) => {
    setNodes((prev) => {
      const newMap = new Map(prev);
      const node = newMap.get(nodeId);
      if (!node) return prev;

      const pathParts = path.split(".");
      const newNode = { ...node };

      let current = newNode;
      for (let i = 0; i < pathParts.length - 1; i++) {
        current[pathParts[i]] = { ...current[pathParts[i]] };
        current = current[pathParts[i]];
      }
      current[pathParts[pathParts.length - 1]] = value;

      newMap.set(nodeId, newNode);
      return newMap;
    });
  }, []);

  /**
   * Handle zoom in
   */
  const handleZoomIn = useCallback(() => {
    setZoom((prev) => Math.min(prev + 0.1, 2));
  }, []);

  /**
   * Handle zoom out
   */
  const handleZoomOut = useCallback(() => {
    setZoom((prev) => Math.max(prev - 0.1, 0.5));
  }, []);

  /**
   * Handle fit view
   */
  const handleFitView = useCallback(() => {
    setZoom(1);
    setPanOffset({ x: 0, y: 0 });
  }, []);

  /**
   * Handle clear canvas
   */
  const handleClearCanvas = useCallback(() => {
    setShowClearCanvasConfirm(true);
  }, []);

  /**
   * Confirm clear canvas
   */
  const confirmClearCanvas = useCallback(() => {
    setNodes(new Map());
    setEdges(new Map());
    setSelectedNode(null);
    setSelectedEdge(null);
    setShowClearCanvasConfirm(false);
  }, []);

  /**
   * Get connection path for SVG - uses actual DOM element positions
   */
  const getConnectionPath = useCallback(
    (sourceNode, targetNode) => {
      const sourceEl = document.getElementById(`node-${sourceNode.node_id}`);
      const targetEl = document.getElementById(`node-${targetNode.node_id}`);
      const canvasEl = canvasRef.current;

      if (!sourceEl || !targetEl || !canvasEl) {
        // Fallback to position-based calculation
        const sourceX = sourceNode.position.x + 200;
        const sourceY = sourceNode.position.y + 50;
        const targetX = targetNode.position.x;
        const targetY = targetNode.position.y + 50;
        const controlOffset = Math.abs(targetX - sourceX) / 2;
        return `M ${sourceX} ${sourceY} C ${sourceX + controlOffset} ${sourceY}, ${targetX - controlOffset} ${targetY}, ${targetX} ${targetY}`;
      }

      const canvasRect = canvasEl.getBoundingClientRect();
      const sourceRect = sourceEl.getBoundingClientRect();
      const targetRect = targetEl.getBoundingClientRect();

      // Source: right edge, vertically centered
      const sourceX = (sourceRect.right - canvasRect.left - panOffset.x) / zoom;
      const sourceY = (sourceRect.top + sourceRect.height / 2 - canvasRect.top - panOffset.y) / zoom;

      // Target: left edge, vertically centered
      const targetX = (targetRect.left - canvasRect.left - panOffset.x) / zoom;
      const targetY = (targetRect.top + targetRect.height / 2 - canvasRect.top - panOffset.y) / zoom;

      const controlOffset = Math.abs(targetX - sourceX) / 2;
      return `M ${sourceX} ${sourceY} C ${sourceX + controlOffset} ${sourceY}, ${targetX - controlOffset} ${targetY}, ${targetX} ${targetY}`;
    },
    [zoom, panOffset]
  );

  /**
   * Handle save pipeline
   */
  const handleSave = useCallback(async () => {
    const pipelineData = {
      pipeline_name: pipelineName.trim(),
      pipeline_description: pipelineDescription.trim(),
      pipeline_definition: {
        nodes: nodesArray,
        edges: edgesArray,
      },
      created_by: Cookies.get("email"),
    };

    try {
      if (pipeline?.pipeline_id) {
        await updatePipeline(pipeline.pipeline_id, pipelineData);
        addMessage("Pipeline updated successfully", "success");
      } else {
        await createPipeline(pipelineData);
        addMessage("Pipeline created successfully", "success");
      }
      setShowSaveModal(false);
      onSave && onSave();
    } catch (error) {
      const errorMessage = error?.response?.data?.detail || "Failed to save pipeline";
      handleError(error, { customMessage: errorMessage });
    }
  }, [pipelineName, pipelineDescription, nodesArray, edgesArray, pipeline, createPipeline, updatePipeline, addMessage, handleError, onSave]);

  /**
   * Get accessible inputs for agent nodes
   */
  const getAccessibleInputs = useCallback(() => {
    const inputs = [];

    const inputNode = nodesArray.find((n) => n.node_type === NODE_TYPES.INPUT);
    if (inputNode?.config?.input_schema && Object.keys(inputNode.config.input_schema).length > 0) {
      Object.entries(inputNode.config.input_schema).forEach(([keyName, keyType]) => {
        const typeStr = typeof keyType === "string" ? keyType : keyType?.raw || keyType?.type || "string";
        inputs.push({
          id: `input.${keyName}`,
          label: keyName,
          type: typeStr,
          source: "input",
          sourceLabel: "Pipeline Input",
          description: inputNode.config.description?.[keyName] || "",
        });
      });
    }

    nodesArray
      .filter((n) => n.node_type === NODE_TYPES.AGENT && n.node_id !== selectedNode)
      .forEach((agent) => {
        const nodeName = agent.node_name || "Agent";
        const agentId = agent.config?.agent_id;
        const selectedAgent = agentId ? availableAgents.find((a) => a.agent_id === agentId) : null;
        const agentName = selectedAgent?.agent_name || "";

        inputs.push({
          id: `agent.${agent.node_id}`,
          label: nodeName,
          agentName: agentName,
          type: "agent_output",
          source: "agent",
          sourceLabel: agentName || nodeName,
          nodeId: agent.node_id,
        });
      });

    return inputs;
  }, [nodesArray, selectedNode, availableAgents]);

  const selectedNodeData = selectedNode ? nodes.get(selectedNode) : null;

  /** Renders the footer buttons */
  const renderFooter = () => (
    <>
      {readOnly ? (
        <Button type="secondary" onClick={onBack}>
          Close
        </Button>
      ) : (
        <>
          <Button type="secondary" onClick={onBack}>
            Cancel
          </Button>
          <Button
            type="primary"
            onClick={() => setShowSaveModal(true)}
            disabled={!canOpenSaveModal}
            title={!canOpenSaveModal ? "Add at least one node to the canvas" : "Save Pipeline"}>
            Save
          </Button>
        </>
      )}
    </>
  );

  return (
    <FullModal
      isOpen={true}
      onClose={onBack}
      title={readOnly ? "View Pipeline" : (pipeline ? "Edit Pipeline" : "New Pipeline")}
      footer={readOnly ? null : renderFooter()}
      closeOnOverlayClick={false}
      fullHeight={true}
      contentClassName={styles.pipelineModalContent}>
      {/* Main Content */}
      <div className={styles.canvasWrapper}>
        {/* Node Palette */}
        <div className={styles.nodePalette}>
          <h4 className={styles.paletteTitle}>
            <FontAwesomeIcon icon={faCubes} />
            Nodes
          </h4>

          {Object.entries(NODE_CONFIG).map(([type, config]) => (
            <div key={type} className={`${styles.paletteNode} ${styles[config.paletteClass]}`} draggable={!readOnly} onDragStart={(e) => !readOnly && handlePaletteDragStart(e, type)} style={readOnly ? { opacity: 0.5, cursor: "not-allowed" } : {}}>
              <FontAwesomeIcon icon={config.paletteIcon || config.icon} className={styles.nodeIcon} />
              {config.label}
            </div>
          ))}
        </div>

        {/* Canvas */}
        <div
          ref={canvasRef}
          className={`${styles.canvasContainer} ${panMode ? styles.panModeActive : ""}`}
          onDrop={readOnly ? undefined : handleCanvasDrop}
          onDragOver={readOnly ? undefined : handleCanvasDragOver}
          onMouseMove={handleMouseMove}
          onMouseUp={handleMouseUp}
          onMouseLeave={handleMouseUp}
          onContextMenu={handleContextMenu}
          onMouseDown={(e) => {
            if (panMode && e.button === 0) {
              e.preventDefault();
              setIsPanning(true);
              setPanStart({
                x: e.clientX - panOffset.x,
                y: e.clientY - panOffset.y,
              });
            }
          }}
          onClick={() => {
            if (!panMode) {
              setSelectedNode(null);
              setSelectedEdge(null);
            }
          }}>
          <div
            className={styles.canvasContent}
            style={{
              transform: `translate(${panOffset.x}px, ${panOffset.y}px) scale(${zoom})`,
            }}>
            {/* SVG for connections - key forces re-render after zoom/pan */}
            <svg ref={svgRef} className={styles.connectionsSvg} key={`connections-${renderKey}`}>
              {/* Existing connections */}
              {edgesArray.map((edge) => {
                const sourceNode = nodes.get(edge.source_node_id);
                const targetNode = nodes.get(edge.target_node_id);
                if (!sourceNode || !targetNode) return null;

                const isSelected = selectedEdge === edge.edge_id;
                const pathData = getConnectionPath(sourceNode, targetNode);

                return (
                  <g key={edge.edge_id}>
                    <path
                      d={pathData}
                      stroke="transparent"
                      strokeWidth="20"
                      fill="none"
                      className={styles.connectionHitbox}
                      onClick={(e) => {
                        e.stopPropagation();
                        setSelectedEdge(edge.edge_id);
                        setSelectedNode(null);
                      }}
                    />
                    <path d={pathData} className={`${styles.connectionLine} ${isSelected ? styles.connectionLineSelected : ""} ${styles.connectionPathOverlay}`} />
                    {isSelected && (
                      <g>
                        {(() => {
                          // Parse the path to get start and end points for midpoint calculation
                          const pathMatch = pathData.match(/^M\s+([\d.-]+)\s+([\d.-]+)\s+C\s+[\d.-]+\s+[\d.-]+,\s+[\d.-]+\s+[\d.-]+,\s+([\d.-]+)\s+([\d.-]+)$/);
                          if (!pathMatch) return null;

                          const sourceX = parseFloat(pathMatch[1]);
                          const sourceY = parseFloat(pathMatch[2]);
                          const targetX = parseFloat(pathMatch[3]);
                          const targetY = parseFloat(pathMatch[4]);
                          const midX = (sourceX + targetX) / 2;
                          const midY = (sourceY + targetY) / 2;

                          return (
                            <>
                              <circle
                                cx={midX}
                                cy={midY}
                                r="12"
                                fill="var(--danger, #e74c3c)"
                                stroke="var(--card-bg, white)"
                                strokeWidth="2"
                                className={styles.connectionDeleteBtn}
                                onClick={(e) => {
                                  e.stopPropagation();
                                  handleDeleteEdge(edge.edge_id);
                                }}
                              />
                              <path
                                d={`M ${midX - 4} ${midY - 4} L ${midX + 4} ${midY + 4} M ${midX + 4} ${midY - 4} L ${midX - 4} ${midY + 4}`}
                                stroke="var(--header-color, #fff)"
                                strokeWidth="2"
                                strokeLinecap="round"
                                className={styles.connectionPathOverlay}
                              />
                            </>
                          );
                        })()}
                      </g>
                    )}
                  </g>
                );
              })}

              {/* Temporary connection while dragging */}
              {tempConnection && (
                <path
                  d={`M ${tempConnection.startX} ${tempConnection.startY} C ${tempConnection.startX + 50} ${tempConnection.startY}, ${tempConnection.endX - 50} ${tempConnection.endY
                    }, ${tempConnection.endX} ${tempConnection.endY}`}
                  className={styles.connectionLineTemp}
                />
              )}
            </svg>

            {/* Nodes container */}
            <div className={styles.nodesContainer}>
              {nodesArray.map((node) => {
                const config = NODE_CONFIG[node.node_type];
                return (
                  <div
                    key={node.node_id}
                    id={`node-${node.node_id}`}
                    className={styles.canvasNodeWrapper}
                    style={{
                      left: node.position.x,
                      top: node.position.y,
                    }}
                    onMouseDown={(e) => handleNodeDragStart(e, node.node_id)}
                    onClick={(e) => {
                      e.stopPropagation();
                      setSelectedNode(node.node_id);
                    }}>
                    {/* Connection Points - positioned relative to wrapper */}
                    <div className={styles.connectionPointsWrapper}>
                      {config.canReceive && (
                        <div data-connection-point className={`${styles.connectionPoint} ${styles.connectionPointInput}`} onMouseUp={(e) => handleConnectionEnd(e, node.node_id, true)} />
                      )}

                      {config.canSend && (
                        <div data-connection-point className={`${styles.connectionPoint} ${styles.connectionPointOutput}`} onMouseDown={(e) => handleConnectionStart(e, node.node_id, true)} />
                      )}
                    </div>

                    {/* Node Card */}
                    <div className={`${styles.canvasNode} ${selectedNode === node.node_id ? styles.selected : ""}`}>
                      {/* Node Header */}
                      <div className={`${styles.nodeHeader} ${styles[config.headerClass]}`}>
                        <span>{config.label} Node</span>
                        <button
                          className={styles.nodeCloseBtn}
                          onClick={(e) => {
                            e.stopPropagation();
                            setDeleteNodeConfirm(node.node_id);
                          }}>
                          <FontAwesomeIcon icon={faTimes} size="sm" />
                        </button>
                      </div>

                      {/* Node Body */}
                      <div className={styles.nodeBody}>
                        <div className={styles.nodeName}>
                          <FontAwesomeIcon icon={config.icon} />
                          {node.node_type === NODE_TYPES.INPUT ? NODE_CONFIG[NODE_TYPES.INPUT].description : node.node_name || NODE_CONFIG[node.node_type]?.label}
                        </div>

                        {node.node_type === NODE_TYPES.INPUT && <div className={styles.nodeConfig}>Query: string</div>}

                        {node.node_type === NODE_TYPES.AGENT && node.config?.agent_id && (
                          <div className={styles.nodeConfig}>{availableAgents.find((a) => a.agent_id === node.config.agent_id)?.agent_name || node.config.agent_id}</div>
                        )}

                        {node.node_type === NODE_TYPES.CONDITION && node.config?.condition && (
                          <div className={styles.nodeConfig}>{node.config.condition.length > 30 ? node.config.condition.substring(0, 30) + "..." : node.config.condition}</div>
                        )}
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          {/* Canvas Controls */}
          <div className={styles.canvasControls}>
            <button
              className={`${styles.controlBtn} ${panMode ? styles.controlBtnActive : ""}`}
              onClick={() => setPanMode(!panMode)}
              title={panMode ? "Exit Pan Mode" : "Pan Mode (Move Graph)"}>
              <FontAwesomeIcon icon={faHand} />
            </button>
            <button className={styles.controlBtn} onClick={handleZoomIn} title="Zoom In">
              <FontAwesomeIcon icon={faPlus} />
            </button>
            <button className={styles.controlBtn} onClick={handleZoomOut} title="Zoom Out">
              <FontAwesomeIcon icon={faMinus} />
            </button>
            <button className={styles.controlBtn} onClick={handleFitView} title="Fit View">
              <FontAwesomeIcon icon={faExpand} />
            </button>
            <button className={styles.controlBtn} onClick={handleClearCanvas} title="Clear Canvas" disabled={readOnly || nodesArray.length === 0}>
              <FontAwesomeIcon icon={faTrash} />
            </button>
          </div>
        </div>

        {/* Properties Panel - Only visible when a node is selected */}
        {selectedNodeData && (
          <div className={styles.propertiesPanel}>
            <div className={styles.propertiesPanelHeader}>
              <h4 className={styles.propertiesPanelTitle}>
                <FontAwesomeIcon icon={faCog} />
                Properties
              </h4>
              <div className={styles.headerActions}>
                <button className="closeBtn" onClick={() => setSelectedNode(null)} title="Close">
                  ×
                </button>
              </div>
            </div>

            <div className={styles.propertiesPanelContent}>
              {/* Common Properties */}
              <div className={styles.propertyGroup}>
                <label className={styles.propertyLabel}>
                  Node Name
                  {(selectedNodeData.node_type === NODE_TYPES.AGENT || selectedNodeData.node_type === NODE_TYPES.OUTPUT) && <span className={styles.required}> *</span>}
                </label>
                <input
                  type="text"
                  className={styles.propertyInput}
                  value={selectedNodeData.node_name}
                  onChange={(e) => updateNodeProperty(selectedNode, "node_name", e.target.value)}
                  disabled={readOnly || selectedNodeData.node_type === NODE_TYPES.INPUT}
                  placeholder={
                    selectedNodeData.node_type === NODE_TYPES.AGENT || selectedNodeData.node_type === NODE_TYPES.OUTPUT
                      ? `Enter ${NODE_CONFIG[selectedNodeData.node_type]?.label} name...`
                      : ""
                  }
                />
              </div>

              <div className={styles.propertyGroup}>
                <label className={styles.propertyLabel}>Type</label>
                <div className={styles.typeInfoContainer}>
                  <div className={styles.typeInfoRow}>
                    <span className={`${styles.typeBadge} ${styles[`typeBadge${NODE_CONFIG[selectedNodeData.node_type]?.label}`]}`}>
                      <FontAwesomeIcon icon={NODE_CONFIG[selectedNodeData.node_type]?.icon} />
                      {NODE_CONFIG[selectedNodeData.node_type]?.label}
                    </span>
                  </div>
                  {selectedNodeData.node_type === NODE_TYPES.INPUT && (
                    <div className={styles.typeInfoRow}>
                      <span className={styles.nodeDescription}>On every chat message pipeline will be triggered</span>
                    </div>
                  )}
                  <div className={styles.typeInfoRow}>
                    <span className={styles.nodeIdLabel}>ID:</span>
                    <span className={styles.nodeIdValue}>{selectedNodeData.node_id.substring(0, 16)}...</span>
                  </div>
                </div>
              </div>

              {/* Input Node Properties */}
              {selectedNodeData.node_type === NODE_TYPES.INPUT && (
                <div className={styles.propertyGroup}>
                  <div className={styles.propertyLabelWithAction}>
                    <label className={styles.propertyLabel}>Input Schema</label>
                    <button className={styles.addKeyIconBtn} onClick={() => setShowAddKeyModal(true)} title="Add Key" disabled>
                      <FontAwesomeIcon icon={faPlus} />
                    </button>
                  </div>
                  <div className={styles.inputKeysList}>
                    <div className={styles.inputKeyItem}>
                      <span className={styles.inputKeyLabel}>Query</span>
                      <span className={styles.inputKeyType}>string</span>
                    </div>
                  </div>
                </div>
              )}

              {/* Agent Node Properties */}
              {selectedNodeData.node_type === NODE_TYPES.AGENT && (
                <>
                  <div className={styles.propertyGroup}>
                    <label className={styles.propertyLabel}>Agent</label>
                    <NewCommonDropdown
                      options={availableAgents.map((agent) => agent.agent_name)}
                      optionMetadata={availableAgents.reduce((acc, agent) => {
                        const abbr = getAgentTypeAbbreviation(agent.agent_type);
                        if (abbr) {
                          acc[agent.agent_name] = abbr;
                        }
                        return acc;
                      }, {})}
                      selected={
                        selectedNodeData.config?.agent_id
                          ? (() => {
                            const agent = availableAgents.find((a) => a.agent_id === selectedNodeData.config.agent_id);
                            return agent ? agent.agent_name : "";
                          })()
                          : ""
                      }
                      onSelect={(value) => {
                        const agent = availableAgents.find((a) => a.agent_name === value);
                        if (agent) {
                          updateNodeProperty(selectedNode, "config.agent_id", agent.agent_id);
                        }
                      }}
                      placeholder="Select Agent..."
                      showSearch={true}
                      width="100%"
                      dropdownWidth="280px"
                      maxWidth="280px"
                      disabled={readOnly}
                    />
                  </div>

                  <div className={styles.propertyGroup}>
                    <label className={styles.propertyLabel}>Accessible Inputs</label>
                    <div className={`${styles.propertyInfo} ${styles.propertyInfoSpaced}`}>Select which inputs this agent can access</div>
                    <div className={styles.accessibleInputsList}>
                      <div className={`${styles.accessibleInputItem} ${styles.allInputsToggle}`}>
                        <input
                          type="checkbox"
                          id="all-inputs"
                          disabled={readOnly}
                          checked={selectedNodeData.config?.accessible_inputs?.input_keys?.includes("all") || false}
                          onChange={(e) => {
                            if (e.target.checked) {
                              updateNodeProperty(selectedNode, "config.accessible_inputs", {
                                input_keys: ["all"],
                              });
                            } else {
                              updateNodeProperty(selectedNode, "config.accessible_inputs", {
                                input_keys: [],
                              });
                            }
                          }}
                        />
                        <label htmlFor="all-inputs">All Inputs</label>
                      </div>

                      {!selectedNodeData.config?.accessible_inputs?.input_keys?.includes("all") && (
                        <>
                          {getAccessibleInputs().length === 0 ? (
                            <div className={styles.noInputsMessage}>No inputs available. Add input keys to the Input node or add other Agent nodes.</div>
                          ) : (
                            getAccessibleInputs().map((input) => (
                              <div key={input.id} className={`${styles.accessibleInputItem} ${input.source === "agent" ? styles.agentInputItem : ""}`}>
                                <input
                                  type="checkbox"
                                  id={`input-${input.id}`}
                                  disabled={readOnly}
                                  checked={selectedNodeData.config?.accessible_inputs?.input_keys?.includes(input.id) || false}
                                  onChange={(e) => {
                                    const currentKeys = selectedNodeData.config?.accessible_inputs?.input_keys || [];
                                    const newKeys = e.target.checked ? [...currentKeys, input.id] : currentKeys.filter((k) => k !== input.id);
                                    updateNodeProperty(selectedNode, "config.accessible_inputs", {
                                      input_keys: newKeys,
                                    });
                                  }}
                                />
                                <label htmlFor={`input-${input.id}`}>
                                  <span className={styles.inputLabel}>{input.label}</span>
                                  {input.source === "agent" && input.agentName && (
                                    <span className={styles.inputSource}>({input.agentName})</span>
                                  )}
                                  {input.source !== "agent" && (
                                    <span className={styles.inputSource}>({input.sourceLabel})</span>
                                  )}
                                </label>
                                <span className={`${styles.accessibleInputType} ${input.source === "agent" ? styles.agentType : ""}`}>{input.type}</span>
                              </div>
                            ))
                          )}
                        </>
                      )}
                    </div>
                  </div>
                </>
              )}

              {/* Condition Node Properties */}
              {selectedNodeData.node_type === NODE_TYPES.CONDITION && (
                <div className={styles.propertyGroup}>
                  <label className={styles.propertyLabel}>Condition</label>
                  <textarea
                    className={styles.propertyTextarea}
                    value={selectedNodeData.config?.condition || ""}
                    onChange={(e) => updateNodeProperty(selectedNode, "config.condition", e.target.value)}
                    placeholder="result.status == 'success'"
                    disabled={readOnly}
                  />
                </div>
              )}

              {/* Output Node Properties */}
              {selectedNodeData.node_type === NODE_TYPES.OUTPUT && (
                <OutputSchemaEditor value={selectedNodeData.config?.output_schema} onChange={(value) => updateNodeProperty(selectedNode, "config.output_schema", value)} />
              )}
            </div>
          </div>
        )}
      </div>

      {/* Save Modal */}
      {showSaveModal && (
        <div className={styles.modalOverlay} onClick={() => setShowSaveModal(false)}>
          <div className={styles.modalContent} onClick={(e) => e.stopPropagation()}>
            <div className={styles.modalHeader}>
              <h3 className={styles.modalTitle}>Save Pipeline</h3>
              <button className={styles.modalCloseBtn} onClick={() => setShowSaveModal(false)}>
                <FontAwesomeIcon icon={faTimes} />
              </button>
            </div>
            <div className={styles.modalBody}>
              <div className={styles.propertyGroup}>
                <label className={styles.propertyLabel}>
                  Pipeline Name <span className={styles.required}>*</span>
                </label>
                <input type="text" className={styles.propertyInput} value={pipelineName} onChange={(e) => setPipelineName(e.target.value)} placeholder="My Pipeline" />
              </div>
              <div className={styles.propertyGroup}>
                <label className={styles.propertyLabel}>
                  Description <span className={styles.required}>*</span>
                </label>
                <textarea
                  className={styles.propertyTextarea}
                  value={pipelineDescription}
                  onChange={(e) => setPipelineDescription(e.target.value)}
                  placeholder="Describe what this pipeline does..."
                />
              </div>
              {nodesArray.length === 0 && <div className={styles.validationError}>⚠️ Add at least one node to the canvas</div>}
              {nodesArray.length > 0 && !nodesArray.some((n) => n.node_type === NODE_TYPES.OUTPUT) && (
                <div className={styles.validationError}>⚠️ Add at least one Output node to the pipeline</div>
              )}
              {nodesArray.some(
                (node) => (node.node_type === NODE_TYPES.AGENT || node.node_type === NODE_TYPES.OUTPUT) && (!node.node_name || node.node_name.trim().length === 0)
              ) && (
                  <div className={styles.validationError}>⚠️ All Agent and Output nodes must have a name. Please fill in the required "Node Name" field in the properties panel.</div>
                )}
            </div>
            <div className={styles.modalActions}>
              <Button type="secondary" onClick={() => setShowSaveModal(false)}>
                Cancel
              </Button>
              <Button type="primary" onClick={handleSave} disabled={!canSave}>
                Save
              </Button>
            </div>
          </div>
        </div>
      )}

      {/* Condition Modal */}
      {showConditionModal && (
        <div className={styles.modalOverlay} onClick={() => setShowConditionModal(false)}>
          <div className={styles.modalContent} onClick={(e) => e.stopPropagation()}>
            <div className={styles.modalHeader}>
              <h3 className={styles.modalTitle}>Add Condition</h3>
              <button
                className={styles.modalCloseBtn}
                onClick={() => {
                  setShowConditionModal(false);
                  setPendingConnection(null);
                  setConditionText("");
                }}>
                <FontAwesomeIcon icon={faTimes} />
              </button>
            </div>
            <div className={styles.modalBody}>
              <div className={styles.propertyGroup}>
                <label className={styles.propertyLabel}>Condition Expression</label>
                <textarea className={styles.propertyTextarea} value={conditionText} onChange={(e) => setConditionText(e.target.value)} placeholder="result.status == 'success'" />
              </div>
            </div>
            <div className={styles.modalActions}>
              <button
                className={styles.cancelBtn}
                onClick={() => {
                  setShowConditionModal(false);
                  setPendingConnection(null);
                  setConditionText("");
                }}>
                Cancel
              </button>
              <button className={styles.primaryBtn} onClick={handleAddCondition} disabled={!conditionText.trim()}>
                Add
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Add Key Modal */}
      {showAddKeyModal && (
        <div className={styles.modalOverlay} onClick={() => setShowAddKeyModal(false)}>
          <div className={styles.modalContent} onClick={(e) => e.stopPropagation()}>
            <div className={styles.modalHeader}>
              <h3 className={styles.modalTitle}>Add Input Key</h3>
              <button
                className={styles.modalCloseBtn}
                onClick={() => {
                  setShowAddKeyModal(false);
                  setNewKeyLabel("");
                  setNewKeyType("string");
                  setNewKeyDescription("");
                }}>
                <FontAwesomeIcon icon={faTimes} />
              </button>
            </div>
            <div className={styles.modalBody}>
              <div className={styles.propertyGroup}>
                <label className={styles.propertyLabel}>
                  Label <span className={styles.required}>*</span>
                </label>
                <input type="text" className={styles.propertyInput} value={newKeyLabel} onChange={(e) => setNewKeyLabel(e.target.value)} placeholder="query" />
              </div>
              <div className={styles.propertyGroup}>
                <label className={styles.propertyLabel}>
                  Type <span className={styles.required}>*</span>
                </label>
                <select className={styles.propertySelect} value={newKeyType} onChange={(e) => setNewKeyType(e.target.value)}>
                  <option value="string">String</option>
                  <option value="integer">Integer</option>
                  <option value="json">JSON</option>
                </select>
              </div>
              <div className={styles.propertyGroup}>
                <label className={styles.propertyLabel}>Description (optional)</label>
                <input
                  type="text"
                  className={styles.propertyInput}
                  value={newKeyDescription}
                  onChange={(e) => setNewKeyDescription(e.target.value)}
                  placeholder="Optional description"
                />
              </div>
            </div>
            <div className={styles.modalActions}>
              <button
                className={styles.cancelBtn}
                onClick={() => {
                  setShowAddKeyModal(false);
                  setNewKeyLabel("");
                  setNewKeyType("string");
                  setNewKeyDescription("");
                }}>
                Cancel
              </button>
              <button
                className={styles.primaryBtn}
                onClick={() => {
                  // Add key logic here
                  setShowAddKeyModal(false);
                  setNewKeyLabel("");
                  setNewKeyType("string");
                  setNewKeyDescription("");
                }}
                disabled={!newKeyLabel.trim()}>
                Add Key
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Delete Node Confirmation Modal */}
      <DeleteModal show={Boolean(deleteNodeConfirm)} onClose={() => setDeleteNodeConfirm(null)}>
        <div className={styles.deleteConfirmIcon}>
          <SVGIcons icon="warnings" width={48} height={48} color="#ef4444" />
        </div>
        <h3 className={styles.deleteConfirmTitle}>Delete Node?</h3>
        <p className={styles.deleteConfirmMessage}>Are you sure you want to delete this node? This action cannot be undone.</p>
        <div className={styles.deleteConfirmActions}>
          <button className={styles.deleteConfirmCancelBtn} onClick={() => setDeleteNodeConfirm(null)}>
            Cancel
          </button>
          <button className={styles.deleteConfirmDeleteBtn} onClick={() => handleDeleteNode(deleteNodeConfirm)}>
            Delete
          </button>
        </div>
      </DeleteModal>

      {/* Clear Canvas Confirmation Modal */}
      <DeleteModal show={showClearCanvasConfirm} onClose={() => setShowClearCanvasConfirm(false)}>
        <div className={styles.deleteConfirmIcon}>
          <SVGIcons icon="warnings" width={48} height={48} color="#ef4444" />
        </div>
        <h3 className={styles.deleteConfirmTitle}>Clear Canvas?</h3>
        <p className={styles.deleteConfirmMessage}>Are you sure you want to clear the canvas? All nodes and connections will be removed.</p>
        <div className={styles.deleteConfirmActions}>
          <button className={styles.deleteConfirmCancelBtn} onClick={() => setShowClearCanvasConfirm(false)}>
            Cancel
          </button>
          <button className={styles.deleteConfirmDeleteBtn} onClick={confirmClearCanvas}>
            Clear
          </button>
        </div>
      </DeleteModal>
    </FullModal>
  );
};

export default PipelineBuilder;
