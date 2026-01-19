/**
 * Pipeline Builder Component
 *
 * Main canvas component for building and editing pipelines.
 * Supports drag-drop nodes, connections, zoom/pan, and properties panel.
 */

import React, { useState, useEffect, useCallback, useRef, useMemo } from "react";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import {
  faPlus,
  faMinus,
  faExpand,
  faTrash,
  faTimes,
  faRobot,
  faCodeBranch,
  faFlag,
  faComments,
  faSignInAlt,
  faCog,
  faHand,
  faCubes,
} from "@fortawesome/free-solid-svg-icons";
import { usePipelineService } from "../../services/pipelineService";
import { useMessage } from "../../Hooks/MessageContext";
import { useErrorHandler } from "../../Hooks/useErrorHandler";
import styles from "../../css_modules/PipelineBuilder.module.css";
import { getAgentTypeAbbreviation } from "./pipelineUtils";
import Cookies from "js-cookie";
import DeleteModal from "../commonComponents/DeleteModal";

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
    maxIncoming: 0,  // Input node cannot receive connections
    maxOutgoing: 1,  // Input node can only have ONE outgoing connection
  },
  [NODE_TYPES.AGENT]: {
    label: "Agent",
    icon: faRobot,
    headerClass: "nodeHeaderAgent",
    paletteClass: "paletteNodeAgent",
    canReceive: true,
    canSend: true,
    maxCount: Infinity,
    maxIncoming: 1,  // Agent can have ONE incoming connection
    maxOutgoing: 1,  // Agent can have ONE outgoing connection
  },
  [NODE_TYPES.CONDITION]: {
    label: "Condition",
    icon: faCodeBranch,
    headerClass: "nodeHeaderCondition",
    paletteClass: "paletteNodeCondition",
    canReceive: true,
    canSend: true,
    maxCount: Infinity,
    maxIncoming: 1,        // Condition can have ONE incoming connection
    maxOutgoing: Infinity, // Condition can have MANY outgoing connections
  },
  [NODE_TYPES.OUTPUT]: {
    label: "Output",
    icon: faFlag,
    headerClass: "nodeHeaderOutput",
    paletteClass: "paletteNodeOutput",
    canReceive: true,
    canSend: false,
    maxCount: Infinity,
    maxIncoming: 1,  // Output can have ONE incoming connection
    maxOutgoing: 0,  // Output cannot send connections
  },
};

/**
 * Generate unique ID for nodes/edges
 */
const generateId = (prefix = "node") => {
  return `${prefix}_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
};

/**
 * Output Schema Editor Component
 * Uses local state to allow free-form typing, validates JSON on blur
 */
const OutputSchemaEditor = ({ value, onChange }) => {
  const [text, setText] = useState(value ? JSON.stringify(value, null, 2) : "");
  const [isValid, setIsValid] = useState(true);

  // Sync with parent value when it changes externally
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
      {!isValid && (
        <div className={styles.inputError}>Invalid JSON format</div>
      )}
      <div className={styles.propertyInfo}>
        Enter valid JSON schema. Leave empty for no schema validation.
      </div>
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
const PipelineBuilder = ({ pipeline, onBack, onSave }) => {
  // Canvas state
  const [nodes, setNodes] = useState(new Map());
  const [edges, setEdges] = useState(new Map());
  const [zoom, setZoom] = useState(1);
  const [panOffset, setPanOffset] = useState({ x: 0, y: 0 });

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
  const [loadingAgents, setLoadingAgents] = useState(false);

  // Agent search state
  const [agentSearchTerm, setAgentSearchTerm] = useState("");
  const [showAgentDropdown, setShowAgentDropdown] = useState(false);
  const [highlightedAgentIndex, setHighlightedAgentIndex] = useState(-1);
  const agentDropdownRef = useRef(null);
  const agentListRef = useRef(null);

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
   * Fetch available agents (only once on mount)
   */
  useEffect(() => {
    const fetchAgents = async () => {
      setLoadingAgents(true);
      try {
        const response = await getAvailableAgents();
        setAvailableAgents(response?.agents || []);
      } catch (error) {
        // Silently handle - agents dropdown will be empty
        console.error("Failed to fetch agents:", error);
      } finally {
        setLoadingAgents(false);
      }
    };
    fetchAgents();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  /**
   * Close agent dropdown when clicking outside
   */
  useEffect(() => {
    const handleClickOutside = (event) => {
      if (agentDropdownRef.current && !agentDropdownRef.current.contains(event.target)) {
        setShowAgentDropdown(false);
        setAgentSearchTerm("");
        setHighlightedAgentIndex(-1);
      }
    };
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  /**
   * Handle keyboard navigation for agent dropdown
   */
  useEffect(() => {
    if (!showAgentDropdown) return;

    const handleAgentDropdownKeyDown = (event) => {
      // Get filtered agents list
      const filteredAgents = availableAgents.filter(agent => 
        agent.agent_name.toLowerCase().includes(agentSearchTerm.toLowerCase())
      );

      if (event.key === "Escape") {
        event.preventDefault();
        setShowAgentDropdown(false);
        setAgentSearchTerm("");
        setHighlightedAgentIndex(-1);
      } else if (event.key === "ArrowDown") {
        event.preventDefault();
        setHighlightedAgentIndex(prev => 
          prev < filteredAgents.length - 1 ? prev + 1 : prev
        );
      } else if (event.key === "ArrowUp") {
        event.preventDefault();
        setHighlightedAgentIndex(prev => (prev > 0 ? prev - 1 : -1));
      } else if (event.key === "Enter" && highlightedAgentIndex >= 0) {
        event.preventDefault();
        const selectedAgent = filteredAgents[highlightedAgentIndex];
        if (selectedAgent) {
          updateNodeProperty(selectedNode, "config.agent_id", selectedAgent.agent_id);
          setShowAgentDropdown(false);
          setAgentSearchTerm("");
          setHighlightedAgentIndex(-1);
        }
      }
    };

    document.addEventListener("keydown", handleAgentDropdownKeyDown);
    return () => document.removeEventListener("keydown", handleAgentDropdownKeyDown);
  }, [showAgentDropdown, highlightedAgentIndex, availableAgents, agentSearchTerm, selectedNode]);

  /**
   * Scroll highlighted agent into view
   */
  useEffect(() => {
    if (showAgentDropdown && highlightedAgentIndex >= 0 && agentListRef.current) {
      const highlightedElement = agentListRef.current.children[highlightedAgentIndex];
      if (highlightedElement) {
        highlightedElement.scrollIntoView({ block: "nearest", behavior: "smooth" });
      }
    }
  }, [highlightedAgentIndex, showAgentDropdown]);

  /**
   * Reset highlighted index when search term changes
   */
  useEffect(() => {
    if (showAgentDropdown) {
      setHighlightedAgentIndex(-1);
    }
  }, [agentSearchTerm, showAgentDropdown]);

  /**
   * Handle keyboard shortcuts (Delete key for edges)
   */
  useEffect(() => {
    const handleKeyDown = (event) => {
      // Delete selected edge with Delete or Backspace key
      if ((event.key === "Delete" || event.key === "Backspace") && selectedEdge) {
        // Don't delete if user is typing in an input/textarea
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

    // Check if at least one output node exists
    const hasOutputNode = nodesArray.some((n) => n.node_type === NODE_TYPES.OUTPUT);

    // Validate that all Agent and Output nodes have non-empty node_name
    const allRequiredFieldsFilled = nodesArray.every((node) => {
      if (node.node_type === NODE_TYPES.AGENT || node.node_type === NODE_TYPES.OUTPUT) {
        return node.node_name && node.node_name.trim().length > 0;
      }
      return true; // Other node types don't require node_name
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
   * Handle canvas drop
   */
  const handleCanvasDrop = useCallback(
    (e) => {
      e.preventDefault();
      const nodeType = e.dataTransfer.getData("nodeType");
      if (!nodeType || !NODE_CONFIG[nodeType]) return;

      // Check max count for input nodes
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
        node_name: (nodeType === NODE_TYPES.AGENT || nodeType === NODE_TYPES.OUTPUT) ? "" : NODE_CONFIG[nodeType].label,
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
      if (e.target.closest(`.${styles.connectionPoint}`)) return;
      
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
      // Node dragging
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

      // Canvas panning
      if (isPanning) {
        setPanOffset({
          x: e.clientX - panStart.x,
          y: e.clientY - panStart.y,
        });
      }

      // Connection drawing
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
    
    // Always clear connection state on mouse up if connecting
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

      // Check if this node type can send/receive
      const config = NODE_CONFIG[node.node_type];
      if (isOutput && !config.canSend) return;
      if (!isOutput && !config.canReceive) return;

      // Get connection point position
      const nodeEl = document.getElementById(`node-${nodeId}`);
      if (!nodeEl) return;

      const rect = nodeEl.getBoundingClientRect();
      const canvasRect = canvasRef.current.getBoundingClientRect();
      
      const x = isOutput
        ? (rect.right - canvasRect.left - panOffset.x) / zoom
        : (rect.left - canvasRect.left - panOffset.x) / zoom;
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
        // Invalid connection - must go from output to input
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

      // Validate connection rules
      const sourceConfig = NODE_CONFIG[sourceNode.node_type];
      const targetConfig = NODE_CONFIG[targetNode.node_type];

      if (!sourceConfig.canSend || !targetConfig.canReceive) {
        addMessage("Invalid connection", "error");
        setIsConnecting(false);
        setConnectionStart(null);
        setTempConnection(null);
        return;
      }

      // Check if connection already exists
      const existingEdge = edgesArray.find(
        (e) => e.source_node_id === connectionStart.nodeId && e.target_node_id === nodeId
      );
      if (existingEdge) {
        addMessage("Connection already exists", "error");
        setIsConnecting(false);
        setConnectionStart(null);
        setTempConnection(null);
        return;
      }

      // Check outgoing connection limit for source node
      const outgoingCount = edgesArray.filter(
        (e) => e.source_node_id === connectionStart.nodeId
      ).length;
      if (sourceConfig.maxOutgoing !== undefined && outgoingCount >= sourceConfig.maxOutgoing) {
        addMessage(`${sourceConfig.label} node can only have ${sourceConfig.maxOutgoing} outgoing connection(s)`, "error");
        setIsConnecting(false);
        setConnectionStart(null);
        setTempConnection(null);
        return;
      }

      // Check incoming connection limit for target node
      const incomingCount = edgesArray.filter(
        (e) => e.target_node_id === nodeId
      ).length;
      if (targetConfig.maxIncoming !== undefined && incomingCount >= targetConfig.maxIncoming) {
        addMessage(`${targetConfig.label} node can only have ${targetConfig.maxIncoming} incoming connection(s)`, "error");
        setIsConnecting(false);
        setConnectionStart(null);
        setTempConnection(null);
        return;
      }

      // If conditional connection, show modal
      if (isConditionalConnection) {
        setPendingConnection({
          source_node_id: connectionStart.nodeId,
          target_node_id: nodeId,
        });
        setShowConditionModal(true);
      } else {
        // Create normal connection
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

      // Remove connected edges
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
   * Add input key
   */
  const handleAddInputKey = useCallback(() => {
    if (!selectedNode || !newKeyLabel.trim()) return;

    const node = nodes.get(selectedNode);
    if (!node || node.node_type !== NODE_TYPES.INPUT) return;

    const keyName = newKeyLabel.trim();
    const currentSchema = node.config?.input_schema || {};
    const currentDescription = node.config?.description || {};

    // Add to input_schema
    updateNodeProperty(selectedNode, "config.input_schema", {
      ...currentSchema,
      [keyName]: newKeyType,
    });

    // Add to description if provided
    if (newKeyDescription.trim()) {
      updateNodeProperty(selectedNode, "config.description", {
        ...currentDescription,
        [keyName]: newKeyDescription.trim(),
      });
    }

    setShowAddKeyModal(false);
    setNewKeyLabel("");
    setNewKeyType("string");
    setNewKeyDescription("");
  }, [selectedNode, nodes, newKeyLabel, newKeyType, newKeyDescription, updateNodeProperty]);

  /**
   * Remove input key
   */
  const handleRemoveInputKey = useCallback(
    (keyName) => {
      if (!selectedNode) return;

      const node = nodes.get(selectedNode);
      if (!node || node.node_type !== NODE_TYPES.INPUT) return;

      const currentSchema = { ...node.config?.input_schema } || {};
      const currentDescription = { ...node.config?.description } || {};

      delete currentSchema[keyName];
      delete currentDescription[keyName];

      updateNodeProperty(selectedNode, "config.input_schema", currentSchema);
      updateNodeProperty(selectedNode, "config.description", currentDescription);
    },
    [selectedNode, nodes, updateNodeProperty]
  );

  /**
   * Zoom controls
   */
  const handleZoomIn = useCallback(() => {
    setZoom((prev) => Math.min(prev + 0.1, 2.0));
  }, []);

  const handleZoomOut = useCallback(() => {
    setZoom((prev) => Math.max(prev - 0.1, 0.5));
  }, []);

  const handleFitView = useCallback(() => {
    setZoom(1);
    setPanOffset({ x: 0, y: 0 });
  }, []);

  const handleClearCanvas = useCallback(() => {
    if (nodesArray.length === 0) return;
    setShowClearCanvasConfirm(true);
  }, [nodesArray]);

  const confirmClearCanvas = useCallback(() => {
    setNodes(new Map());
    setEdges(new Map());
    setSelectedNode(null);
    setSelectedEdge(null);
    setShowClearCanvasConfirm(false);
  }, []);

  /**
   * Save pipeline
   */
  const handleSave = useCallback(async () => {
    if (!canSave) return;

    const pipelineDefinition = {
      nodes: nodesArray,
      edges: edgesArray,
    };

    const payload = {
      pipeline_name: pipelineName.trim(),
      pipeline_description: pipelineDescription.trim(),
      pipeline_definition: pipelineDefinition,
      created_by: Cookies.get("email") || "unknown",
    };

    // Debug log to verify edge format
    console.log("Saving pipeline with edges:", JSON.stringify(edgesArray, null, 2));

    try {
      if (pipeline?.pipeline_id) {
      const response = await updatePipeline(pipeline.pipeline_id, payload);
        addMessage(response?.result?.message, "success");
      } else {
         const response = await createPipeline(payload);
        addMessage(response?.result?.message, "success");
      }
      setShowSaveModal(false);
      onSave?.();
    } catch (error) {
      addMessage(error?.response?.data?.detail,"error");
    }
  }, [
    canSave,
    nodesArray,
    edgesArray,
    pipelineName,
    pipelineDescription,
    pipeline,
    updatePipeline,
    createPipeline,
    addMessage,
    handleError,
    onSave,
  ]);

  /**
   * Calculate connection path
   */
  const getConnectionPath = useCallback((sourceNode, targetNode) => {
    if (!sourceNode || !targetNode) return "";

    const sourceX = sourceNode.position.x + 200; // Right side of node
    const sourceY = sourceNode.position.y + 40; // Middle of node
    const targetX = targetNode.position.x; // Left side of node
    const targetY = targetNode.position.y + 40; // Middle of node

    const controlPointOffset = Math.abs(targetX - sourceX) / 2;

    return `M ${sourceX} ${sourceY} C ${sourceX + controlPointOffset} ${sourceY}, ${targetX - controlPointOffset} ${targetY}, ${targetX} ${targetY}`;
  }, []);

  /**
   * Get all accessible inputs for agent nodes
   * Returns input keys from Input node and outputs from other Agent nodes
   */
  const getAccessibleInputs = useCallback(() => {
    const inputs = [];

    // Add input keys from Input node (using input_schema object)
    const inputNode = nodesArray.find((n) => n.node_type === NODE_TYPES.INPUT);
    if (inputNode?.config?.input_schema && Object.keys(inputNode.config.input_schema).length > 0) {
      Object.entries(inputNode.config.input_schema).forEach(([keyName, keyType]) => {
        // Ensure type is always a string (handle object format {raw, type})
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

    // Add outputs from other agent nodes (agent outputs can be inputs for other agents)
    nodesArray
      .filter((n) => n.node_type === NODE_TYPES.AGENT && n.node_id !== selectedNode)
      .forEach((agent) => {
        const agentName = agent.node_name || "Agent";
        const agentId = agent.config?.agent_id;
        const agentLabel = agentId 
          ? availableAgents.find(a => a.agent_id === agentId)?.agent_name || agentName
          : agentName;
        
        inputs.push({
          id: `agent.${agent.node_id}`,
          label: `${agentLabel} Output`,
          type: "agent_output",
          source: "agent",
          sourceLabel: agentLabel,
          nodeId: agent.node_id,
        });
      });

    return inputs;
  }, [nodesArray, selectedNode, availableAgents]);

  // Selected node data
  const selectedNodeData = selectedNode ? nodes.get(selectedNode) : null;

  return (
    <div className={styles.pipelineContainer}>
      {/* Header */}
      <div className={styles.pipelineHeader}>
        <div style={{ display: "flex", alignItems: "center", gap: "16px" }}>
          <h2>{pipeline ? "Edit Pipeline" : "New Pipeline"}</h2>
        </div>
        <div className={styles.headerActions}>
          <button
            className={styles.closeBtn}
            onClick={onBack}
            title="Close"
          >
            ×
          </button>
        </div>
      </div>

      {/* Main Content */}
      <div className={styles.canvasWrapper}>
        {/* Node Palette */}
        <div className={styles.nodePalette}>
          <h4 className={styles.paletteTitle}>
            <FontAwesomeIcon icon={faCubes} />
            Nodes
          </h4>

          {Object.entries(NODE_CONFIG).map(([type, config]) => (
            <div
              key={type}
              className={`${styles.paletteNode} ${styles[config.paletteClass]}`}
              draggable
              onDragStart={(e) => handlePaletteDragStart(e, type)}
            >
              <FontAwesomeIcon icon={config.paletteIcon || config.icon} className={styles.nodeIcon} />
              {config.label}
            </div>
          ))}
        </div>

        {/* Canvas */}
        <div
          ref={canvasRef}
          className={`${styles.canvasContainer} ${panMode ? styles.panModeActive : ""}`}
          onDrop={handleCanvasDrop}
          onDragOver={handleCanvasDragOver}
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
          }}
        >
          <div
            className={styles.canvasContent}
            style={{
              transform: `translate(${panOffset.x}px, ${panOffset.y}px) scale(${zoom})`,
            }}
          >
            {/* SVG for connections */}
            <svg ref={svgRef} className={styles.connectionsSvg}>
              {/* Existing connections */}
              {edgesArray.map((edge) => {
                const sourceNode = nodes.get(edge.source_node_id);
                const targetNode = nodes.get(edge.target_node_id);
                if (!sourceNode || !targetNode) return null;

                const isSelected = selectedEdge === edge.edge_id;
                const pathData = getConnectionPath(sourceNode, targetNode);

                return (
                  <g key={edge.edge_id}>
                    {/* Invisible wider path for easier clicking */}
                    <path
                      d={pathData}
                      stroke="transparent"
                      strokeWidth="20"
                      fill="none"
                      style={{ cursor: 'pointer' }}
                      onClick={(e) => {
                        e.stopPropagation();
                        setSelectedEdge(edge.edge_id);
                        setSelectedNode(null);
                      }}
                    />
                    {/* Visible connection line */}
                    <path
                      d={pathData}
                      className={`${styles.connectionLine} ${isSelected ? styles.connectionLineSelected : ''}`}
                      style={{ pointerEvents: 'none' }}
                    />
                    {/* Delete button for selected edge */}
                    {isSelected && (
                      <g>
                        {/* Calculate midpoint for delete button */}
                        {(() => {
                          const sourceX = sourceNode.position.x + 200;
                          const sourceY = sourceNode.position.y + 40;
                          const targetX = targetNode.position.x;
                          const targetY = targetNode.position.y + 40;
                          const midX = (sourceX + targetX) / 2;
                          const midY = (sourceY + targetY) / 2;

                          return (
                            <>
                              <circle
                                cx={midX}
                                cy={midY}
                                r="12"
                                fill="#e74c3c"
                                stroke="white"
                                strokeWidth="2"
                                style={{ cursor: 'pointer' }}
                                onClick={(e) => {
                                  e.stopPropagation();
                                  handleDeleteEdge(edge.edge_id);
                                }}
                              />
                              <path
                                d={`M ${midX - 4} ${midY - 4} L ${midX + 4} ${midY + 4} M ${midX + 4} ${midY - 4} L ${midX - 4} ${midY + 4}`}
                                stroke="white"
                                strokeWidth="2"
                                strokeLinecap="round"
                                style={{ pointerEvents: 'none' }}
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
                  d={`M ${tempConnection.startX} ${tempConnection.startY} C ${tempConnection.startX + 50} ${tempConnection.startY}, ${tempConnection.endX - 50} ${tempConnection.endY}, ${tempConnection.endX} ${tempConnection.endY}`}
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
                    className={`${styles.canvasNode} ${
                      selectedNode === node.node_id ? styles.selected : ""
                    }`}
                    style={{
                      left: node.position.x,
                      top: node.position.y,
                    }}
                    onMouseDown={(e) => handleNodeDragStart(e, node.node_id)}
                    onClick={(e) => {
                      e.stopPropagation();
                      setSelectedNode(node.node_id);
                    }}
                  >
                    {/* Node Header */}
                    <div className={`${styles.nodeHeader} ${styles[config.headerClass]}`}>
                      <span>{config.label} Node</span>
                      <button
                        className={styles.nodeCloseBtn}
                        onClick={(e) => {
                          e.stopPropagation();
                          setDeleteNodeConfirm(node.node_id);
                        }}
                      >
                        <FontAwesomeIcon icon={faTimes} size="sm" />
                      </button>
                    </div>

                    {/* Node Body */}
                    <div className={styles.nodeBody}>
                      <div className={styles.connectionPointsWrapper}>
                        {/* Input connection point */}
                        {config.canReceive && (
                          <div
                            className={`${styles.connectionPoint} ${styles.connectionPointInput}`}
                            onMouseUp={(e) => handleConnectionEnd(e, node.node_id, true)}
                          />
                        )}

                        {/* Output connection point */}
                        {config.canSend && (
                          <div
                            className={`${styles.connectionPoint} ${styles.connectionPointOutput}`}
                            onMouseDown={(e) => handleConnectionStart(e, node.node_id, true)}
                          />
                        )}
                      </div>

                      <div className={styles.nodeName}>
                        <FontAwesomeIcon icon={config.icon} />
                        {node.node_type === NODE_TYPES.INPUT 
                          ? NODE_CONFIG[NODE_TYPES.INPUT].description 
                          : (node.node_name || NODE_CONFIG[node.node_type]?.label)}
                      </div>

                      {/* Node-specific content */}
                      {node.node_type === NODE_TYPES.INPUT && (
                        <div className={styles.nodeConfig}>
                          Query: string
                        </div>
                      )}

                      {node.node_type === NODE_TYPES.AGENT && node.config?.agent_id && (
                        <div className={styles.nodeConfig}>
                          {availableAgents.find((a) => a.agent_id === node.config.agent_id)?.agent_name || node.config.agent_id}
                        </div>
                      )}

                      {node.node_type === NODE_TYPES.CONDITION && node.config?.condition && (
                        <div className={styles.nodeConfig}>
                          {node.config.condition.length > 30
                            ? node.config.condition.substring(0, 30) + "..."
                            : node.config.condition}
                        </div>
                      )}
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
              title={panMode ? "Exit Pan Mode" : "Pan Mode (Move Graph)"}
            >
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
            <button
              className={styles.controlBtn}
              onClick={handleClearCanvas}
              title="Clear Canvas"
              disabled={nodesArray.length === 0}
            >
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
          <button
            className={styles.closeBtn}
            onClick={() => setSelectedNode(null)}
            title="Close"
          >
            ×
          </button>
        </div>
            </div>

          <div className={styles.propertiesPanelContent}>
            {/* Common Properties */}
            <div className={styles.propertyGroup}>
                  <label className={styles.propertyLabel}>
                    Node Name
                    {(selectedNodeData.node_type === NODE_TYPES.AGENT || selectedNodeData.node_type === NODE_TYPES.OUTPUT) && (
                      <span className={styles.required}> *</span>
                    )}
                  </label>
                  <input
                    type="text"
                    className={styles.propertyInput}
                    value={selectedNodeData.node_name}
                    onChange={(e) =>
                      updateNodeProperty(selectedNode, "node_name", e.target.value)
                    }
                    disabled={selectedNodeData.node_type === NODE_TYPES.INPUT}
                    placeholder={(selectedNodeData.node_type === NODE_TYPES.AGENT || selectedNodeData.node_type === NODE_TYPES.OUTPUT) ? `Enter ${NODE_CONFIG[selectedNodeData.node_type]?.label} name...` : ""}
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
                        <span className={styles.nodeDescription}>
                          On every chat message pipeline will be triggered
                        </span>
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
                      <label className={styles.propertyLabel}>
                        {/* Input Schema ({Object.keys(selectedNodeData.config?.input_schema || {}).length}) */}
                        Input Schema
                      </label>
                      <button
                        className={styles.addKeyIconBtn}
                        onClick={() => setShowAddKeyModal(true)}
                        title="Add Key"
                        disabled
                      >
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
                      <div className={styles.searchableDropdown} ref={agentDropdownRef}>
                        <div
                          className={styles.searchableDropdownTrigger}
                          onClick={() => setShowAgentDropdown(!showAgentDropdown)}
                        >
                          <span className={selectedNodeData.config?.agent_id ? styles.selectedValue : styles.placeholderValue}>
                            {selectedNodeData.config?.agent_id
                              ? (() => {
                                  const agent = availableAgents.find(a => a.agent_id === selectedNodeData.config.agent_id);
                                  const abbr = getAgentTypeAbbreviation(agent?.agent_type);
                                  return agent ? `${agent.agent_name}${abbr ? ` [${abbr}]` : ""}` : "Select Agent...";
                                })()
                              : "Select Agent..."}
                          </span>
                          <svg width="12" height="12" viewBox="0 0 12 12" fill="none" xmlns="http://www.w3.org/2000/svg" className={`${styles.dropdownArrow} ${showAgentDropdown ? styles.open : ""}`}>
                            <path d="M2.5 4.5L6 8L9.5 4.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
                          </svg>
                        </div>
                        {showAgentDropdown && (
                          <div className={styles.searchableDropdownMenu}>
                            <div className={styles.searchInputWrapper}>
                              <input
                                type="text"
                                className={styles.searchInput}
                                placeholder="Search agents..."
                                value={agentSearchTerm}
                                onChange={(e) => setAgentSearchTerm(e.target.value)}
                                onClick={(e) => e.stopPropagation()}
                                autoFocus
                              />
                            </div>
                            <div className={styles.dropdownOptionsList} ref={agentListRef}>
                              {availableAgents
                                .filter(agent => agent.agent_name.toLowerCase().includes(agentSearchTerm.toLowerCase()))
                                .map((agent, index) => {
                                  const abbr = getAgentTypeAbbreviation(agent.agent_type);
                                  return (
                                    <div
                                      key={agent.agent_id}
                                      className={`${styles.dropdownOption} ${selectedNodeData.config?.agent_id === agent.agent_id ? styles.selected : ""} ${index === highlightedAgentIndex ? styles.highlighted : ""}`}
                                      onClick={() => {
                                        updateNodeProperty(selectedNode, "config.agent_id", agent.agent_id);
                                        setShowAgentDropdown(false);
                                        setAgentSearchTerm("");
                                        setHighlightedAgentIndex(-1);
                                      }}
                                    >
                                      <span className={styles.agentOptionName}>{agent.agent_name}</span>
                                      {abbr && <span className={styles.agentOptionAbbr}>[{abbr}]</span>}
                                    </div>
                                  );
                                })}
                              {availableAgents.filter(agent => agent.agent_name.toLowerCase().includes(agentSearchTerm.toLowerCase())).length === 0 && (
                                <div className={styles.noResults}>No agents found</div>
                              )}
                            </div>
                          </div>
                        )}
                      </div>
                    </div>

                    <div className={styles.propertyGroup}>
                      <label className={styles.propertyLabel}>Accessible Inputs</label>
                      <div className={styles.propertyInfo} style={{ marginBottom: "8px" }}>
                        Select which inputs this agent can access
                      </div>
                      <div className={styles.accessibleInputsList}>
                        <div className={`${styles.accessibleInputItem} ${styles.allInputsToggle}`}>
                          <input
                            type="checkbox"
                            id="all-inputs"
                            checked={
                              selectedNodeData.config?.accessible_inputs?.input_keys?.includes("all") ||
                              false
                            }
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
                              <div className={styles.noInputsMessage}>
                                No inputs available. Add input keys to the Input node or add other Agent nodes.
                              </div>
                            ) : (
                              getAccessibleInputs().map((input) => (
                                <div 
                                  key={input.id} 
                                  className={`${styles.accessibleInputItem} ${
                                    input.source === "agent" ? styles.agentInputItem : ""
                                  }`}
                                >
                                  <input
                                    type="checkbox"
                                    id={`input-${input.id}`}
                                    checked={
                                      selectedNodeData.config?.accessible_inputs?.input_keys?.includes(
                                        input.id
                                      ) || false
                                    }
                                    onChange={(e) => {
                                      const currentKeys =
                                        selectedNodeData.config?.accessible_inputs?.input_keys || [];
                                      const newKeys = e.target.checked
                                        ? [...currentKeys, input.id]
                                        : currentKeys.filter((k) => k !== input.id);
                                      updateNodeProperty(selectedNode, "config.accessible_inputs", {
                                        input_keys: newKeys,
                                      });
                                    }}
                                  />
                                  <label htmlFor={`input-${input.id}`}>
                                    <span className={styles.inputLabel}>{input.label}</span>
                                    <span className={styles.inputSource}>({input.sourceLabel})</span>
                                  </label>
                                  <span className={`${styles.accessibleInputType} ${
                                    input.source === "agent" ? styles.agentType : ""
                                  }`}>
                                    {input.type}
                                  </span>
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
                      onChange={(e) =>
                        updateNodeProperty(selectedNode, "config.condition", e.target.value)
                      }
                      placeholder="result.status == 'success'"
                    />
                  </div>
                )}

                {/* Output Node Properties */}
                {selectedNodeData.node_type === NODE_TYPES.OUTPUT && (
                  <OutputSchemaEditor
                    value={selectedNodeData.config?.output_schema}
                    onChange={(value) => updateNodeProperty(selectedNode, "config.output_schema", value)}
                  />
                )}
          </div>
        </div>
        )}
      </div>

      {/* Footer */}
      <div className={styles.pipelineFooter}>
        <button
          className={styles.primaryBtn}
          onClick={() => setShowSaveModal(true)}
          disabled={!canOpenSaveModal}
          title={!canOpenSaveModal ? "Add at least one node to the canvas" : "Save Pipeline"}
        >
          Save
        </button>
        <button
          className={styles.cancelBtn}
          onClick={onBack}
        >
          Cancel
        </button>
      </div>

      {/* Save Modal */}
      {showSaveModal && (
        <div className={styles.modalOverlay} onClick={() => setShowSaveModal(false)}>
          <div className={styles.modalContent} onClick={(e) => e.stopPropagation()}>
            <div className={styles.modalHeader}>
              <h3 className={styles.modalTitle}>Save Pipeline</h3>
              <button
                className={styles.modalCloseBtn}
                onClick={() => setShowSaveModal(false)}
              >
                <FontAwesomeIcon icon={faTimes} />
              </button>
            </div>
            <div className={styles.modalBody}>
              <div className={styles.propertyGroup}>
                <label className={styles.propertyLabel}>Pipeline Name <span className={styles.required}>*</span></label>
                <input
                  type="text"
                  className={styles.propertyInput}
                  value={pipelineName}
                  onChange={(e) => setPipelineName(e.target.value)}
                  placeholder="My Pipeline"
                />
              </div>
              <div className={styles.propertyGroup}>
                <label className={styles.propertyLabel}>Description <span className={styles.required}>*</span></label>
                <textarea
                  className={styles.propertyTextarea}
                  value={pipelineDescription}
                  onChange={(e) => setPipelineDescription(e.target.value)}
                  placeholder="Describe what this pipeline does..."
                />
              </div>
              {/* Validation messages */}
              {nodesArray.length === 0 && (
                <div className={styles.validationError}>
                  ⚠️ Add at least one node to the canvas
                </div>
              )}
              {nodesArray.length > 0 && !nodesArray.some((n) => n.node_type === NODE_TYPES.OUTPUT) && (
                <div className={styles.validationError}>
                  ⚠️ Add at least one Output node to the pipeline
                </div>
              )}
              {nodesArray.some((node) => 
                (node.node_type === NODE_TYPES.AGENT || node.node_type === NODE_TYPES.OUTPUT) && 
                (!node.node_name || node.node_name.trim().length === 0)
              ) && (
                <div className={styles.validationError}>
                  ⚠️ All Agent and Output nodes must have a name. Please fill in the required "Node Name" field in the properties panel.
                </div>
              )}
            </div>
            <div className={styles.modalActions}>
              <button
                className={styles.primaryBtn}
                onClick={handleSave}
                disabled={!canSave}
              >
                Save
              </button>
              <button
                className={styles.cancelBtn}
                onClick={() => setShowSaveModal(false)}
              >
                Cancel
              </button>
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
                }}
              >
                <FontAwesomeIcon icon={faTimes} />
              </button>
            </div>
            <div className={styles.modalBody}>
              <div className={styles.propertyGroup}>
                <label className={styles.propertyLabel}>Condition Expression</label>
                <textarea
                  className={styles.propertyTextarea}
                  value={conditionText}
                  onChange={(e) => setConditionText(e.target.value)}
                  placeholder="result.status == 'success'"
                />
              </div>
            </div>
            <div className={styles.modalActions}>
              <button
                className={styles.cancelBtn}
                onClick={() => {
                  setShowConditionModal(false);
                  setPendingConnection(null);
                  setConditionText("");
                }}
              >
                Cancel
              </button>
              <button
                className={styles.primaryBtn}
                onClick={handleAddCondition}
                disabled={!conditionText.trim()}
              >
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
                }}
              >
                <FontAwesomeIcon icon={faTimes} />
              </button>
            </div>
            <div className={styles.modalBody}>
              <div className={styles.propertyGroup}>
                <label className={styles.propertyLabel}>Label <span className={styles.required}>*</span></label>
                <input
                  type="text"
                  className={styles.propertyInput}
                  value={newKeyLabel}
                  onChange={(e) => setNewKeyLabel(e.target.value)}
                  placeholder="query"
                />
              </div>
              <div className={styles.propertyGroup}>
                <label className={styles.propertyLabel}>Type <span className={styles.required}>*</span></label>
                <select
                  className={styles.propertySelect}
                  value={newKeyType}
                  onChange={(e) => setNewKeyType(e.target.value)}
                >
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
                }}
              >
                Cancel
              </button>
              <button
                className={styles.primaryBtn}
                onClick={handleAddInputKey}
                disabled={!newKeyLabel.trim()}
              >
                Add Key
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Delete Node Confirmation Modal */}
      <DeleteModal show={!!deleteNodeConfirm} onClose={() => setDeleteNodeConfirm(null)}>
        <p>Are you sure you want to delete this node? This action cannot be undone.</p>
        <div className={styles.buttonContainer}>
          <button
            className={styles.deleteBtns}
            onClick={() => handleDeleteNode(deleteNodeConfirm)}
          >
            Delete
          </button>
          <button
            className={styles.cancelBtn}
            onClick={() => setDeleteNodeConfirm(null)}
          >
            Cancel
          </button>
        </div>
      </DeleteModal>

      {/* Clear Canvas Confirmation Modal */}
      <DeleteModal show={showClearCanvasConfirm} onClose={() => setShowClearCanvasConfirm(false)}>
        <p>Are you sure you want to clear the canvas? This action cannot be undone.</p>
        <div className={styles.buttonContainer}>
          <button
            className={styles.deleteBtns}
            onClick={confirmClearCanvas}
          >
            Clear
          </button>
          <button
            className={styles.cancelBtn}
            onClick={() => setShowClearCanvasConfirm(false)}
          >
            Cancel
          </button>
        </div>
      </DeleteModal>
    </div>
  );
};

export default PipelineBuilder;