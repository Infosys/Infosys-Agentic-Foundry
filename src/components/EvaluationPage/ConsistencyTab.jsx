import React, { useState, useEffect, useRef } from "react";
import styles from "../GroundTruth/GroundTruth.module.css";
import { APIs, agentTypesDropdown } from "../../constant";
import Loader from "../commonComponents/Loader";
import useFetch from "../../Hooks/useAxios";
import { useMessage } from "../../Hooks/MessageContext";
import { useConsistencyApi } from "./consistencyApi";
import LeftNavPanel from "../commonComponents/LeftNavPanel";
import RightResultsPanel from "../commonComponents/RightResultsPanel";
import ConsistencyAgentCard from "./ConsistencyAgentCard";
import listStyles from "../../css_modules/ListOfAgents.module.css";
import consistencyStyles from "./ConsistencyTab.module.css";
import SVGIcons from "../../Icons/SVGIcons";
import useErrorHandler from "../../Hooks/useErrorHandler";

const ConsistencyTab = () => {
  // --- State setup for dropdowns and form ---
  const [formData, setFormData] = useState({
    model_name: "",
    agent_type: "",
    agent_name: "",
    uploaded_file: null,
  });
  const [loading, setLoading] = useState(false);
  const [models, setModels] = useState([]);
  const [agentsListData, setAgentsListData] = useState([]);
  const [agentType, setAgentType] = useState(agentTypesDropdown[0].value);
  const [agentListDropdown, setAgentListDropdown] = useState([]);
  const [agentSearchTerm, setAgentSearchTerm] = useState("");
  const [filteredAgents, setFilteredAgents] = useState([]);
  const [isAgentDropdownOpen, setIsAgentDropdownOpen] = useState(false);
  const [selectedAgentIndex, setSelectedAgentIndex] = useState(-1);
  const agentDropdownRef = useRef(null);
  const [agentTypeSearchTerm, setAgentTypeSearchTerm] = useState("");
  const [filteredAgentTypes, setFilteredAgentTypes] = useState([]);
  const [isAgentTypeDropdownOpen, setIsAgentTypeDropdownOpen] = useState(false);
  const [selectedAgentTypeIndex, setSelectedAgentTypeIndex] = useState(-1);
  const agentTypeDropdownRef = useRef(null);
  const [modelSearchTerm, setModelSearchTerm] = useState("");
  const [filteredModels, setFilteredModels] = useState([]);
  const [isModelDropdownOpen, setIsModelDropdownOpen] = useState(false);
  const [selectedModelIndex, setSelectedModelIndex] = useState(-1);
  const modelDropdownRef = useRef(null);
  const [isDragging, setIsDragging] = useState(false);
  const [results, setResults] = useState(null);
  const fileInputRef = useRef(null);
  const { fetchData, postData, deleteData, putData } = useFetch();
  const { addMessage } = useMessage();
  const { handleApiError } = useErrorHandler();
  const hasLoadedModelsOnce = useRef(false);
  const hasLoadedAgentsOnce = useRef(false);
  const [downloadableResponse, setDownloadableResponse] = useState(null);
  const { executeConsistencyEvaluation } = useConsistencyApi();
  const [availableAgents, setAvailableAgents] = useState([]);
  const [deleteLoading, setDeleteLoading] = useState(false);
  const [isEditMode, setIsEditMode] = useState(false);
  const [editQueries, setEditQueries] = useState([]);
  const [forceUpdate, setForceUpdate] = useState(0);
  const [globalLoading, setGlobalLoading] = useState(false);

  // --- New: Manual query input ---
  const [manualQuery, setManualQuery] = useState("");

  // --- New: Dynamic queries for add mode ---
  const [addModeQueries, setAddModeQueries] = useState([""]);

  // --- State to store queries parsed from uploaded file ---
  const [fileQueries, setFileQueries] = useState([]);

  // --- Edit mode file upload state ---
  const [editModeFile, setEditModeFile] = useState(null);
  const [editIsDragging, setEditIsDragging] = useState(false);
  const [editFileQueries, setEditFileQueries] = useState([]);
  const editFileInputRef = useRef(null);

  // --- Refs for query inputs to handle focus ---
  const addModeQueryRefs = useRef([]);
  const editModeQueryRefs = useRef([]);

  // --- Track original values for edit mode change detection ---
  const [originalEditData, setOriginalEditData] = useState({
    model_name: "",
    queries: [],
  });

  // Enable execute if all dropdowns are entered and either queries or file is provided (but not both)
  const hasNonEmptyQueries = addModeQueries.some((q) => q.trim() !== "");
  const enableExecute =
    formData.model_name && formData.agent_type && formData.agent_name && ((hasNonEmptyQueries && !formData.uploaded_file) || (!hasNonEmptyQueries && formData.uploaded_file));

  // Visibility logic for query sections
  const showAllSections = !hasNonEmptyQueries && !formData.uploaded_file;
  const showOnlyFileUpload = hasNonEmptyQueries && !formData.uploaded_file;
  const showOnlyQueries = !hasNonEmptyQueries && formData.uploaded_file;

  // Edit mode visibility logic
  const hasEditQueries = editQueries.some((q) => q.trim() !== "");
  const showAllEditSections = !hasEditQueries && !editModeFile;
  const showOnlyEditFileUpload = hasEditQueries && !editModeFile;
  const showOnlyEditQueries = !hasEditQueries && editModeFile;

  // Check if edit data has been modified
  const hasEditDataChanged = () => {
    // Check if model name changed
    if (formData.model_name !== originalEditData.model_name) {
      return true;
    }

    // Check if file is uploaded (new modification)
    if (editModeFile) {
      return true;
    }

    // Filter out empty queries for comparison
    const currentNonEmptyQueries = editQueries.filter((q) => q.trim() !== "");
    const originalNonEmptyQueries = originalEditData.queries.filter((q) => q.trim() !== "");

    // Check if query count changed
    if (currentNonEmptyQueries.length !== originalNonEmptyQueries.length) {
      return true;
    }

    // Check if any query content changed
    for (let i = 0; i < currentNonEmptyQueries.length; i++) {
      if (currentNonEmptyQueries[i] !== originalNonEmptyQueries[i]) {
        return true;
      }
    }

    return false;
  };

  // Enable UPDATE button only if data changed and required fields are filled
  const hasEditQueriesNonEmpty = editQueries.some((q) => q.trim() !== "");
  const enableUpdate =
    formData.model_name &&
    (hasEditQueriesNonEmpty || editModeFile) &&
    !(hasEditQueriesNonEmpty && editModeFile) && // not both
    hasEditDataChanged();

  // --- API call tracking for centralized loader ---
  const pendingApiCalls = useRef(0);

  // Helper functions to manage loading state
  const startApiCall = () => {
    if (pendingApiCalls.current === 0) {
      setLoading(true);
    }
    pendingApiCalls.current += 1;
  };

  const endApiCall = () => {
    pendingApiCalls.current -= 1;
    if (pendingApiCalls.current === 0) {
      setLoading(false);
    }
  };

  // --- New: Post-approve workflow ---
  const [robustnessQueries, setRobustnessQueries] = useState([]);
  const [robustnessLoading, setRobustnessLoading] = useState(false);
  const [robustnessResults, setRobustnessResults] = useState(null);
  const [robustnessActive, setRobustnessActive] = useState(false);

  // --- Add state for plus button ---
  const [plusBtnClicked, setPlusBtnClicked] = useState(false);

  // --- State for score view ---
  const [isScoreView, setIsScoreView] = useState(false);
  const [consistencyScoreData, setConsistencyScoreData] = useState(null);
  const [robustnessScoreData, setRobustnessScoreData] = useState(null);
  const [scoreViewLoading, setScoreViewLoading] = useState(false);
  const [currentScoreAgentId, setCurrentScoreAgentId] = useState(null);
  const [expandedCards, setExpandedCards] = useState({});

  // --- Add plus icon click handler ---
  const handlePlusClick = () => {
    // Open the consistency evaluation panel and reset form fields
    setPlusBtnClicked(true);
    setIsEditMode(false);
    setFormData({
      model_name: "",
      agent_type: "",
      agent_name: "",
      uploaded_file: null,
    });
    setManualQuery("");
    setAddModeQueries([""]); // Reset to one empty query
    setModelSearchTerm("");
    setAgentType(agentTypesDropdown[0].value);
    setAgentTypeSearchTerm("");
    setAgentSearchTerm("");
    setSelectedModelIndex(-1);
    setSelectedAgentTypeIndex(-1);
    setSelectedAgentIndex(-1);
    setResults(null); // <-- Reset preview/results state
    setDownloadableResponse(null); // <-- Reset downloadable response
    setRobustnessActive(false); // <-- Reset robustness panel
    setRobustnessResults(null); // <-- Reset robustness results
    setRobustnessQueries([]); // <-- Reset robustness queries
    if (fileInputRef.current) fileInputRef.current.value = "";
  };

  // --- Add: Edit icon handler for agent card ---
  const handleEditAgent = (agent) => {
    setPlusBtnClicked(true);
    setIsEditMode(true);
    const canonicalId = agent.agent_id;
    const agentName = agent.agent_name || agent.agentic_application_name || "";

    // IMPORTANT: Don't clear agent_name when agentType changes during edit mode
    isEditModeTransitionRef.current = true;

    setFormData({
      model_name: agent.model_name || "",
      agent_type: agent.agent_type || agent.agentic_application_type || "",
      agent_name: agentName,
      uploaded_file: null,
      agent_id: canonicalId,
      agentic_application_id: canonicalId,
    });
    setManualQuery("");
    setModelSearchTerm(agent.model_name || "");
    setAgentType(agent.agent_type || agent.agentic_application_type || agentTypesDropdown[0].value);
    setAgentTypeSearchTerm(agent.agent_type || agent.agentic_application_type || "");
    setAgentSearchTerm(agentName);
    setSelectedModelIndex(-1);
    setSelectedAgentTypeIndex(-1);
    setSelectedAgentIndex(-1);
    // Ensure editQueries always has at least one empty string
    setEditQueries(agent.queries && agent.queries.length > 0 ? agent.queries : [""]);

    // Store original data for change detection
    setOriginalEditData({
      model_name: agent.model_name || "",
      queries: agent.queries && agent.queries.length > 0 ? [...agent.queries] : [""],
      agent_name: agentName,
    });

    // Reset edit mode file upload state
    setEditModeFile(null);
    setEditFileQueries([]);
    setEditIsDragging(false);
    if (editFileInputRef.current) editFileInputRef.current.value = "";

    // Only set results if there are actual responses (coming from add flow)
    // When coming from pencil icon, responses will be empty, so don't show preview panel
    if (agent.responses && agent.responses.length > 0) {
      setResults({
        queries: agent.queries || [],
        responses: agent.responses || [],
        agentic_application_id: canonicalId,
        agent_id: canonicalId,
        rerun_url: agent.rerun_url || "",
        approve_url: agent.approve_url || "",
      });
    } else {
      // Clear results when editing from ConsistencyAgentCard (no responses yet)
      setResults(null);
    }

    setRobustnessActive(false); // Ensure robustness panel is closed
    setRobustnessResults(null); // Reset robustness results
    setRobustnessQueries([]); // Reset robustness queries
    setForceUpdate((f) => f + 1); // Force preview panel to re-render
    if (fileInputRef.current) fileInputRef.current.value = "";

    // Clear the transition flag after state updates
    setTimeout(() => {
      isEditModeTransitionRef.current = false;
    }, 100);
  };

  const handleScoreAgent = async (agent) => {
    const agentId = agent?.agent_id || agent?.agentic_application_id;
    if (!agentId) {
      addMessage("Agent ID is required to view scores.", "error");
      return;
    }

    setScoreViewLoading(true);
    setIsScoreView(true);
    setCurrentScoreAgentId(agentId);
    startApiCall();

    try {
      // Make both API calls in parallel
      const [consistencyResponse, robustnessResponse] = await Promise.all([
        fetchData(`${APIs.SCORE_AND_DOWNLOAD_BASE}${agentId}/recent_consistency_scores`),
        fetchData(`${APIs.SCORE_AND_DOWNLOAD_BASE}${agentId}/recent_robustness_scores`),
      ]);

      setConsistencyScoreData(consistencyResponse);
      setRobustnessScoreData(robustnessResponse);

      // Store agent name in formData for display
      setFormData((prev) => ({
        ...prev,
        agent_name: agent.agent_name || agent.agentic_application_name || "",
      }));

      // addMessage("Score data loaded successfully!", "success");
    } catch (error) {
      handleApiError(error, {
        context: "fetch_scores",
        customMessage: "Error fetching score data",
      });
      setIsScoreView(false);
    } finally {
      endApiCall();
      setScoreViewLoading(false);
    }
  };

  const handleCloseScoreView = () => {
    setIsScoreView(false);
    setConsistencyScoreData(null);
    setRobustnessScoreData(null);
    setCurrentScoreAgentId(null);
    setExpandedCards({});
  };

  const toggleExpandAll = (cardId) => {
    const isCurrentlyExpanded = expandedCards[cardId];
    setExpandedCards((prev) => ({
      ...prev,
      [cardId]: !isCurrentlyExpanded,
    }));

    // Toggle all details elements within this card
    const cardElement = document.querySelector(`[data-card-id="${cardId}"]`);
    if (cardElement) {
      const detailsElements = cardElement.querySelectorAll("details");
      detailsElements.forEach((details) => {
        details.open = !isCurrentlyExpanded;
      });
    }
  };

  const handleDownloadConsistencyReport = async () => {
    if (!currentScoreAgentId) {
      addMessage("Agent ID is not available for download.", "error");
      return;
    }

    try {
      const response = await fetchData(`${APIs.SCORE_AND_DOWNLOAD_BASE}${currentScoreAgentId}/download_consistency_record`);

      // Convert response to CSV format with proper delimiters
      let csvContent = "";

      if (typeof response === "string") {
        // If response is already a string, use it directly with proper line breaks
        csvContent = response.replace(/\\r\\n/g, "\r\n");
      } else if (Array.isArray(response)) {
        // If response is an array of objects, convert to CSV
        if (response.length > 0) {
          // Extract headers from first object
          const headers = Object.keys(response[0]);
          csvContent = headers.join(",") + "\r\n";

          // Add data rows
          response.forEach((row) => {
            const values = headers.map((header) => {
              const value = row[header];
              // Escape quotes and wrap in quotes if contains comma, quote, or newline
              if (value == null) return "";
              const stringValue = String(value);
              if (stringValue.includes(",") || stringValue.includes('"') || stringValue.includes("\n")) {
                return '"' + stringValue.replace(/"/g, '""') + '"';
              }
              return stringValue;
            });
            csvContent += values.join(",") + "\r\n";
          });
        }
      } else if (typeof response === "object") {
        // If response has a specific structure, handle accordingly
        csvContent = JSON.stringify(response, null, 2);
      }

      const blob = new Blob([csvContent], { type: "text/csv;charset=utf-8;" });
      const url = window.URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `consistency_report_${formData.agent_name}_${new Date().toISOString().split("T")[0]}.csv`;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      window.URL.revokeObjectURL(url);

      addMessage("Consistency report downloaded successfully!", "success");
    } catch (error) {
      handleApiError(error, {
        context: "download_consistency_report",
        customMessage: "Error downloading consistency report",
      });
    }
  };

  const handleDownloadRobustnessReport = async () => {
    if (!currentScoreAgentId) {
      addMessage("Agent ID is not available for download.", "error");
      return;
    }

    try {
      const response = await fetchData(`${APIs.SCORE_AND_DOWNLOAD_BASE}${currentScoreAgentId}/download_robustness_record`);

      // Convert response to CSV format with proper delimiters
      let csvContent = "";

      if (typeof response === "string") {
        // If response is already a string, use it directly with proper line breaks
        csvContent = response.replace(/\\r\\n/g, "\r\n");
      } else if (Array.isArray(response)) {
        // If response is an array of objects, convert to CSV
        if (response.length > 0) {
          // Extract headers from first object
          const headers = Object.keys(response[0]);
          csvContent = headers.join(",") + "\r\n";

          // Add data rows
          response.forEach((row) => {
            const values = headers.map((header) => {
              const value = row[header];
              // Escape quotes and wrap in quotes if contains comma, quote, or newline
              if (value == null) return "";
              const stringValue = String(value);
              if (stringValue.includes(",") || stringValue.includes('"') || stringValue.includes("\n")) {
                return '"' + stringValue.replace(/"/g, '""') + '"';
              }
              return stringValue;
            });
            csvContent += values.join(",") + "\r\n";
          });
        }
      } else if (typeof response === "object") {
        // If response has a specific structure, handle accordingly
        csvContent = JSON.stringify(response, null, 2);
      }

      const blob = new Blob([csvContent], { type: "text/csv;charset=utf-8;" });
      const url = window.URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `robustness_report_${formData.agent_name}_${new Date().toISOString().split("T")[0]}.csv`;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      window.URL.revokeObjectURL(url);

      addMessage("Robustness report downloaded successfully!", "success");
    } catch (error) {
      handleApiError(error, {
        context: "download_robustness_report",
        customMessage: "Error downloading robustness report",
      });
    }
  };

  const handleUpdate = async () => {
    const hasEditQueriesNonEmpty = editQueries.some((q) => q.trim() !== "");

    if (!formData.model_name || !formData.agent_name) {
      addMessage("Please fill in all required fields for update!", "error");
      return;
    }

    if (!hasEditQueriesNonEmpty && !editModeFile) {
      addMessage("Please provide either queries or upload a file!", "error");
      return;
    }

    if (hasEditQueriesNonEmpty && editModeFile) {
      addMessage("Please use either queries OR file upload, not both!", "error");
      return;
    }

    startApiCall();
    try {
      // Always use agent_id as canonical
      let canonicalId = formData.agent_id;
      if (!canonicalId && Array.isArray(availableAgents)) {
        const found = availableAgents.find((a) => a.agent_id === formData.agent_id || a.agent_name === formData.agent_name);
        if (found) canonicalId = found.agent_id;
      }
      if (!canonicalId && Array.isArray(agentsListData)) {
        const found = agentsListData.find((a) => a.agent_id === formData.agent_id || a.agent_name === formData.agent_name);
        if (found) canonicalId = found.agent_id;
      }
      if (!canonicalId && Array.isArray(agentListDropdown)) {
        const found = agentListDropdown.find((a) => a.agent_id === formData.agent_id || a.agent_name === formData.agent_name);
        if (found) canonicalId = found.agent_id;
      }
      if (!canonicalId) {
        addMessage("No agent_id found for update!", "error");
        endApiCall();
        return;
      }

      const endpoint = `${APIs.CONSISTENCY_GENERATE_UPDATE_PREVIEW}${canonicalId}`;
      let response;

      if (editModeFile) {
        // Use FormData if file is uploaded
        const formDataToSend = new FormData();
        formDataToSend.append("model_name", formData.model_name);
        formDataToSend.append("uploaded_file", editModeFile);

        response = await putData(endpoint, formDataToSend);
      } else {
        // Use JSON if queries are provided
        const payload = {
          model_name: formData.model_name,
          queries: editQueries.filter((q) => q.trim() !== ""),
          queries_str: editQueries.filter((q) => q.trim() !== ""),
        };

        response = await putData(endpoint, payload);
      }

      if (response) {
        // Always update editQueries with backend queries if present
        const newQueries = response.queries && response.queries.length > 0 ? response.queries : editQueries;
        // Fallback to previous responses if backend does not return them
        const newResponses = response.responses && response.responses.length > 0 ? response.responses : results && results.responses ? results.responses : [];

        // Update editQueries if we got new queries from the file
        if (response.queries && response.queries.length > 0) {
          setEditQueries(response.queries);
        }

        // Update original data to reflect the new state (so button becomes disabled again)
        setOriginalEditData({
          model_name: formData.model_name,
          queries: newQueries && newQueries.length > 0 ? [...newQueries] : editQueries.filter((q) => q.trim() !== ""),
        });

        // Clear file if it was uploaded
        if (editModeFile) {
          setEditModeFile(null);
          setEditFileQueries([]);
          if (editFileInputRef.current) editFileInputRef.current.value = "";
        }

        // Always set both agentic_application_id and agent_id to the canonical value
        setResults({
          queries: newQueries,
          responses: newResponses,
          rerun_url: response.rerun_url,
          approve_url: response.approve_url,
          agentic_application_id: canonicalId,
          agent_id: canonicalId,
        });
        // Ensure edit mode and plus panel remain open after update
        setIsEditMode(true);
        setPlusBtnClicked(true);
        setForceUpdate((f) => f + 1);
        addMessage("Update preview generated. Please review and approve the new responses.", "success");
      } else {
        addMessage(response?.message || "Failed to update agent.", "error");
      }
    } catch (error) {
      handleApiError(error, {
        context: "agent_update",
        customMessage: "Error updating agent",
      });
    } finally {
      endApiCall();
    }
  };

  const getAgentIdForActions = () => {
    // Try all possible sources for agent_id
    if (results?.agent_id) return results.agent_id;
    if (results?.agentic_application_id) return results.agentic_application_id;
    if (formData.agent_id) return formData.agent_id;
    if (formData.agentic_application_id) return formData.agentic_application_id;
    // Try to find from agent lists
    const agentFromList = (availableAgents || []).find(
      (a) =>
        a.agentic_application_id === formData.agent_id ||
        a.agentic_application_id === formData.agentic_application_id ||
        a.id === formData.agent_id ||
        a.id === formData.agentic_application_id ||
        a.agent_name === formData.agent_name ||
        a.agentic_application_name === formData.agent_name
    );
    if (agentFromList) return agentFromList.agentic_application_id || agentFromList.id;
    // Try from agentsListData
    const agentFromList2 = (agentsListData || []).find(
      (a) =>
        a.agentic_application_id === formData.agent_id ||
        a.agentic_application_id === formData.agentic_application_id ||
        a.id === formData.agent_id ||
        a.id === formData.agentic_application_id ||
        a.agent_name === formData.agent_name ||
        a.agentic_application_name === formData.agent_name
    );
    if (agentFromList2) return agentFromList2.agentic_application_id || agentFromList2.id;
    // Try from agentListDropdown
    const agentFromList3 = (agentListDropdown || []).find(
      (a) =>
        a.agentic_application_id === formData.agent_id ||
        a.agentic_application_id === formData.agentic_application_id ||
        a.id === formData.agent_id ||
        a.id === formData.agentic_application_id ||
        a.agent_name === formData.agent_name ||
        a.agentic_application_name === formData.agent_name
    );
    if (agentFromList3) return agentFromList3.agentic_application_id || agentFromList3.id;
    return null;
  };

  const handleRerun = async () => {
    const agentId = getAgentIdForActions();
    if (!agentId) {
      addMessage("Agent ID is required for rerun.", "error");
      return;
    }
    setGlobalLoading(true);
    startApiCall();
    try {
      // Always hit rerun endpoint, regardless of edit mode
      const payload = new URLSearchParams();
      payload.append("agent_id", String(agentId));
      const response = await postData(APIs.CONSISTENCY_RERUN_RESPONSES, { agent_id: String(agentId) }, { headers: { "Content-Type": "application/x-www-form-urlencoded" } });
      if (response) {
        const data = response;
        addMessage(data.message || "Rerun executed and results updated.", "success");
        setResults({
          queries: data.queries,
          responses: data.responses,
          rerun_url: data.rerun_url,
          approve_url: data.approve_url,
          agentic_application_id: data.agentic_application_id || agentId,
          agent_id: data.agent_id || agentId,
        });
      } else {
        addMessage("Failed to execute rerun.", "error");
      }
    } catch (error) {
      handleApiError(error, {
        context: "consistency_rerun",
        customMessage: "Error during rerun",
      });
    } finally {
      endApiCall();
      setGlobalLoading(false);
    }
  };

  const handleApprove = async () => {
    const applicationId = results?.agentic_application_id;
    const endpoint = APIs.CONSISTENCY_APPROVE_RESPONSES;
    if (!endpoint || typeof endpoint !== "string" || !endpoint.startsWith("/")) {
      addMessage("Approval endpoint is not configured correctly.", "error");
      return;
    }
    if (!applicationId) {
      addMessage("Application ID is required for approval.", "error");
      return;
    }
    startApiCall();
    try {
      const payload = new URLSearchParams();
      payload.append("agentic_application_id", String(applicationId));
      const response = await postData(endpoint, { agentic_application_id: String(applicationId) }, { headers: { "Content-Type": "application/x-www-form-urlencoded" } });
      if (response) {
        addMessage(response.message || "Approval executed successfully.", "success");
        await fetchAvailableAgents();

        // Immediately trigger robustness API
        setRobustnessActive(true);
        setRobustnessLoading(true);

        const robustnessEndpoint = `${APIs.ROBUSTNESS_PREVIEW_QUERIES}${applicationId}`;
        try {
          const robustnessResponse = await postData(robustnessEndpoint, { agentic_application_id: String(applicationId) }, { headers: { "Content-Type": "application/json" } });
          if (robustnessResponse && Array.isArray(robustnessResponse.generated_queries)) {
            setRobustnessResults({
              queries: robustnessResponse.generated_queries,
              responses: [],
              agentic_application_id: applicationId,
            });
            addMessage(robustnessResponse.message || "Robustness queries loaded!", "success");
          } else {
            setRobustnessResults({ queries: [], responses: [], agentic_application_id: applicationId });
            addMessage("No robustness queries found.", "warning");
          }
        } catch (robustnessError) {
          // setRobustnessResults({ queries: [], responses: [], agentic_application_id: applicationId });
          handleApiError(robustnessError, {
            context: "robustness_preview",
            customMessage: "Error loading robustness queries",
          });
        } finally {
          setRobustnessLoading(false);
        }
      } else {
        addMessage("Failed to execute approval.", "error");
      }
    } catch (error) {
      handleApiError(error, {
        context: "consistency_approval",
        customMessage: "Error during approval",
      });
    } finally {
      endApiCall();
    }
  };

  const handleClosePlusPanel = () => {
    setPlusBtnClicked(false);
    setIsEditMode(false);
  };

  // New: Delete handler for ConsistencyAgentCard
  const handleDeleteAgent = async (agent) => {
    // Standup-style: get the right ID, fallback if needed
    const agentId = agent?.agent_id || agent?.agentic_application_id;
    if (!agentId) {
      addMessage("Agent ID is required for delete.", "error");
      return;
    }
    setDeleteLoading(true);
    startApiCall();
    try {
      // DELETE to /evaluation/delete-agent/{agent_id} endpoint
      const endpoint = `${APIs.CONSISTENCY_DELETE_AGENT}${agentId}`;
      const response = await deleteData(endpoint);
      if (response && (response.status === 200 || response.status === "success" || response.deleted)) {
        addMessage(response.message || "Agent deleted successfully!", "success");
        await fetchAvailableAgents(); // Always refresh the list after delete
      } else {
        addMessage("Failed to delete agent.", "error");
      }
    } catch (error) {
      handleApiError(error, {
        context: "agent_deletion",
        customMessage: "Error deleting agent",
      });
    } finally {
      endApiCall();
      setDeleteLoading(false);
    }
  };

  // --- Fix: Always hit /evaluation/available_agents/ on mount ---
  const fetchAvailableAgents = async () => {
    startApiCall();
    try {
      const response = await fetchData(APIs.CONSISTENCY_AVAILABLE_AGENTS);
      if (Array.isArray(response)) {
        setAvailableAgents(response);
      } else {
        addMessage("No agents found!", "warning");
        setAvailableAgents([]);
      }
    } catch (error) {
      handleApiError(error, {
        context: "fetch_available_agents",
        suppressToast: true, // Don't show toast for background fetches
      });
      // The useFetch hook should already handle error logging
      setAvailableAgents([]);
    } finally {
      endApiCall();
    }
  };

  // --- Fetch models and agents ---
  // Only fetch available agents on mount, not on every render
  const hasLoadedAvailableAgents = useRef(false);
  useEffect(() => {
    const fetchModels = async () => {
      startApiCall();
      try {
        const data = await fetchData(APIs.GET_MODELS);
        if (data?.models && Array.isArray(data.models)) {
          const formattedModels = data.models.map((model) => ({
            label: model,
            value: model,
          }));
          setModels(formattedModels);
        } else {
          setModels([]);
        }
      } catch(error){
        handleApiError(error, {
          context: "fetch_models",
          customMessage: "Failed to fetch models",
        });
        setModels([]);
      } finally {
        endApiCall();
      }
    };
    const fetchAgents = async () => {
      startApiCall();
      try {
        const data = await fetchData(APIs.GET_AGENTS_BY_DETAILS);
        setAgentsListData(data);
      } catch(error) {
        handleApiError(error, {
          context: "fetch_agents",
          customMessage: "Failed to fetch agents",
        });
      } finally {
        endApiCall();
      }
    };
    if (!hasLoadedModelsOnce.current) {
      hasLoadedModelsOnce.current = true;
      fetchModels();
    }
    if (!hasLoadedAgentsOnce.current) {
      hasLoadedAgentsOnce.current = true;
      fetchAgents();
    }
    if (!hasLoadedAvailableAgents.current) {
      hasLoadedAvailableAgents.current = true;
      fetchAvailableAgents();
    }
  }, [fetchData, addMessage, fetchAvailableAgents]);

  // --- Dropdown filtering logic ---
  useEffect(() => {
    setFilteredAgentTypes(agentTypesDropdown);
  }, []);
  useEffect(() => {
    setFilteredModels(models);
  }, [models]);

  // Track previous agentType to only clear agent_name when agentType actually changes
  const prevAgentTypeRef = useRef(agentType);

  useEffect(() => {
    // Only clear agent_name if agentType has actually changed (not on agentsListData changes)
    // AND we're not in the middle of an edit mode transition
    if (prevAgentTypeRef.current !== agentType && !isEditModeTransitionRef.current) {
      setFormData((prev) => ({ ...prev, agent_name: "" }));
      setAgentSearchTerm("");
      setSelectedAgentIndex(-1);
      prevAgentTypeRef.current = agentType;
    }

    if (!agentType) return;
    const tempList = agentsListData?.filter((list) => list.agentic_application_type === agentType);
    setAgentListDropdown(tempList || []);
    setFilteredAgents(tempList || []);
  }, [agentType, agentsListData, isEditMode]);

  useEffect(() => {
    if (!agentSearchTerm) {
      setFilteredAgents(agentListDropdown);
    } else {
      const filtered = agentListDropdown.filter((agent) => agent.agentic_application_name.toLowerCase().includes(agentSearchTerm.toLowerCase()));
      setFilteredAgents(filtered);
    }
    setSelectedAgentIndex(-1);
  }, [agentSearchTerm, agentListDropdown]);
  useEffect(() => {
    if (!agentTypeSearchTerm) {
      setFilteredAgentTypes(agentTypesDropdown);
    } else {
      const filtered = agentTypesDropdown.filter((type) => type.label.toLowerCase().includes(agentTypeSearchTerm.toLowerCase()));
      setFilteredAgentTypes(filtered);
    }
    setSelectedAgentTypeIndex(-1);
  }, [agentTypeSearchTerm]);
  useEffect(() => {
    if (!modelSearchTerm) {
      setFilteredModels(models);
    } else {
      const filtered = models.filter((model) => model.label.toLowerCase().includes(modelSearchTerm.toLowerCase()));
      setFilteredModels(filtered);
    }
    setSelectedModelIndex(-1);
  }, [modelSearchTerm, models]);

  // --- Dropdown outside click logic ---
  useEffect(() => {
    const handleClickOutside = (event) => {
      if (agentDropdownRef.current && !agentDropdownRef.current.contains(event.target)) {
        setIsAgentDropdownOpen(false);
      }
      if (agentTypeDropdownRef.current && !agentTypeDropdownRef.current.contains(event.target)) {
        setIsAgentTypeDropdownOpen(false);
      }
      if (modelDropdownRef.current && !modelDropdownRef.current.contains(event.target)) {
        setIsModelDropdownOpen(false);
      }
    };
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  useEffect(() => {
    if (plusBtnClicked || isScoreView) {
      document.body.style.overflow = "hidden";
    } else {
      document.body.style.overflow = "";
    }
    return () => {
      document.body.style.overflow = "";
    };
  }, [plusBtnClicked, isScoreView]);

  const handleDragEnter = (e) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(true);
  };
  const handleDragLeave = (e) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(false);
  };
  const handleDragOver = (e) => {
    e.preventDefault();
    e.stopPropagation();
    if (!isDragging) setIsDragging(true);
  };
  const handleDrop = (e) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(false);
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      const file = e.dataTransfer.files[0];
      validateFile(file).then((isValid) => {
        if (isValid) {
          setFormData((prev) => ({ ...prev, uploaded_file: file }));
        } else {
          if (fileInputRef.current) fileInputRef.current.value = "";
        }
      });
    }
  };
  const handleRemoveFile = () => {
    setFormData((prev) => ({ ...prev, uploaded_file: null }));
    setFileQueries([]); // Clear the parsed queries
    if (fileInputRef.current) fileInputRef.current.value = "";
  };

  const handleTemplateDownload = async () => {
    try {
      setLoading(true);
      const fileName = "Consistency_template.xlsx";
      const templateUrl = `${APIs.DOWNLOAD_CONSISTENCY_TEMPLATE}?file_name=${encodeURIComponent(fileName)}`;

      const blob = await fetchData(templateUrl, {
        responseType: "blob",
      });
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = fileName;
      document.body.appendChild(a);
      a.click();

      setTimeout(() => {
        window.URL.revokeObjectURL(url);
        document.body.removeChild(a);
      }, 100);

      addMessage("Template downloaded successfully!", "success");
    } catch (error) {
      addMessage(`Unable to download the template`, "error");
    } finally {
      setLoading(false);
    }
  };

  // Edit mode file upload handlers
  const handleEditDragEnter = (e) => {
    e.preventDefault();
    e.stopPropagation();
    setEditIsDragging(true);
  };

  const handleEditDragLeave = (e) => {
    e.preventDefault();
    e.stopPropagation();
    setEditIsDragging(false);
  };

  const handleEditDragOver = (e) => {
    e.preventDefault();
    e.stopPropagation();
    if (!editIsDragging) setEditIsDragging(true);
  };

  const handleEditDrop = (e) => {
    e.preventDefault();
    e.stopPropagation();
    setEditIsDragging(false);
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      const file = e.dataTransfer.files[0];
      validateEditFile(file).then((isValid) => {
        if (isValid) {
          setEditModeFile(file);
          // Clear edit queries when file is uploaded
          setEditQueries([""]);
        } else {
          if (editFileInputRef.current) editFileInputRef.current.value = "";
        }
      });
    }
  };

  const handleEditRemoveFile = () => {
    setEditModeFile(null);
    setEditFileQueries([]);
    if (editFileInputRef.current) editFileInputRef.current.value = "";
  };

  const handleEditFileInputChange = (e) => {
    const { files } = e.target;
    if (files.length > 0) {
      const file = files[0];
      validateEditFile(file).then((isValid) => {
        if (isValid) {
          setEditModeFile(file);
          // Clear edit queries when file is uploaded
          setEditQueries([""]);
        } else {
          if (editFileInputRef.current) editFileInputRef.current.value = "";
        }
      });
    }
  };

  // Input change handler
  const handleInputChange = (e) => {
    const { name, value, type, checked, files } = e.target;
    if (type === "file" && files.length > 0) {
      const file = files[0];
      validateFile(file).then((isValid) => {
        if (isValid) {
          setFormData((prev) => ({ ...prev, [name]: file }));
        } else {
          if (fileInputRef.current) fileInputRef.current.value = "";
        }
      });
    } else if (type === "checkbox") {
      setFormData((prev) => ({ ...prev, [name]: checked }));
    } else {
      setFormData((prev) => ({ ...prev, [name]: value }));
    }
  };

  // Download handler
  const handleDownload = async () => {
    if (!downloadableResponse) {
      addMessage("No file is available for download", "error");
      return;
    }
    try {
      if (downloadableResponse.url) {
        let fileUrl = downloadableResponse.url;
        // If not absolute, prepend window.location.origin
        if (!/^https?:\/\//.test(fileUrl)) {
          fileUrl = window.location.origin + (fileUrl.startsWith("/") ? fileUrl : "/" + fileUrl);
        }
        const blob = await fetchData(fileUrl, { responseType: "blob" });
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = downloadableResponse.fileName;
        document.body.appendChild(a);
        a.click();
        setTimeout(() => {
          window.URL.revokeObjectURL(url);
          document.body.removeChild(a);
        }, 100);
        addMessage("File downloaded successfully", "success");
      }
    } catch (error) {
      addMessage(`Error downloading file: ${error.message}`, "error");
    }
  };

  // File validation
  const validateFile = (file) => {
    if (!file) return false;
    const validExtensions = [".csv", ".xlsx"];
    const fileName = file.name.toLowerCase();
    const isValidExtension = validExtensions.some((ext) => fileName.endsWith(ext));
    if (!isValidExtension) {
      addMessage("Invalid file format. Please upload a .csv or .xlsx file.", "error");
      return false;
    }
    // Validate file content for exactly one column: 'queries' (case-insensitive)
    return new Promise((resolve) => {
      const reader = new FileReader();
      reader.onload = async (e) => {
        let columns = [];
        let queries = [];
        if (fileName.endsWith(".csv")) {
          const text = e.target.result;
          const lines = text.split(/\r?\n/).filter(Boolean);
          if (lines.length > 0) {
            columns = lines[0].split(",").map((col) => col.trim().toLowerCase());
            // Extract queries (skip header row)
            queries = lines
              .slice(1)
              .map((line) => line.trim())
              .filter(Boolean);
          }
        } else if (fileName.endsWith(".xlsx")) {
          try {
            const xlsx = await import("xlsx");
            const workbook = xlsx.read(e.target.result, { type: "binary" });
            const firstSheetName = workbook.SheetNames[0];
            const worksheet = workbook.Sheets[firstSheetName];
            const jsonData = xlsx.utils.sheet_to_json(worksheet, { header: 1 });
            if (jsonData.length > 0) {
              const headers = jsonData[0];
              columns = headers.map((col) => String(col).trim().toLowerCase());
              // Extract queries (skip header row)
              queries = jsonData
                .slice(1)
                .map((row) => String(row[0] || "").trim())
                .filter(Boolean);
            }
          } catch (err) {
            addMessage("Error reading Excel file. Please check the file format.", "error");
            resolve(false);
            return;
          }
        }
        checkColumns(columns, queries);
        function checkColumns(cols, extractedQueries) {
          if (cols.length !== 1 || cols[0] !== "queries") {
            addMessage("File must have only one column named 'queries'.", "error");
            setFileQueries([]);
            resolve(false);
          } else {
            // Store the extracted queries
            setFileQueries(extractedQueries);
            resolve(true);
          }
        }
      };
      if (fileName.endsWith(".csv")) {
        reader.readAsText(file);
      } else {
        reader.readAsBinaryString(file);
      }
    });
  };

  // File validation for edit mode
  const validateEditFile = (file) => {
    if (!file) return false;
    const validExtensions = [".csv", ".xlsx"];
    const fileName = file.name.toLowerCase();
    const isValidExtension = validExtensions.some((ext) => fileName.endsWith(ext));
    if (!isValidExtension) {
      addMessage("Invalid file format. Please upload a .csv or .xlsx file.", "error");
      return false;
    }
    // Validate file content for exactly one column: 'queries' (case-insensitive)
    return new Promise((resolve) => {
      const reader = new FileReader();
      reader.onload = async (e) => {
        let columns = [];
        let queries = [];
        if (fileName.endsWith(".csv")) {
          const text = e.target.result;
          const lines = text.split(/\r?\n/).filter(Boolean);
          if (lines.length > 0) {
            columns = lines[0].split(",").map((col) => col.trim().toLowerCase());
            // Extract queries (skip header row)
            queries = lines
              .slice(1)
              .map((line) => line.trim())
              .filter(Boolean);
          }
        } else if (fileName.endsWith(".xlsx")) {
          try {
            const xlsx = await import("xlsx");
            const workbook = xlsx.read(e.target.result, { type: "binary" });
            const firstSheetName = workbook.SheetNames[0];
            const worksheet = workbook.Sheets[firstSheetName];
            const jsonData = xlsx.utils.sheet_to_json(worksheet, { header: 1 });
            if (jsonData.length > 0) {
              const headers = jsonData[0];
              columns = headers.map((col) => String(col).trim().toLowerCase());
              // Extract queries (skip header row)
              queries = jsonData
                .slice(1)
                .map((row) => String(row[0] || "").trim())
                .filter(Boolean);
            }
          } catch (err) {
            addMessage("Error reading Excel file. Please check the file format.", "error");
            resolve(false);
            return;
          }
        }
        checkColumns(columns, queries);
        function checkColumns(cols, extractedQueries) {
          if (cols.length !== 1 || cols[0] !== "queries") {
            addMessage("File must have only one column named 'queries'.", "error");
            setEditFileQueries([]);
            resolve(false);
          } else {
            // Store the extracted queries for edit mode
            setEditFileQueries(extractedQueries);
            resolve(true);
          }
        }
      };
      if (fileName.endsWith(".csv")) {
        reader.readAsText(file);
      } else {
        reader.readAsBinaryString(file);
      }
    });
  };

  // --- Update handleExecute for preview ---
  const handleExecute = async () => {
    setResults(null);
    setDownloadableResponse(null);
    const requiredFields = [
      { field: "model_name", label: "Model Name" },
      { field: "agent_type", label: "Agent Type" },
      { field: "agent_name", label: "Agent Name" },
    ];

    // Filter out empty queries
    const nonEmptyQueries = addModeQueries.filter((q) => q.trim() !== "");

    // Check if either queries are provided OR file is uploaded
    const hasQueries = nonEmptyQueries.length > 0;
    const hasFile = formData.uploaded_file;

    const missingFields = requiredFields.filter(({ field }) => !formData[field]).map(({ label }) => label);
    if (missingFields.length > 0) {
      addMessage(`Please fill in the following required fields: ${missingFields.join(", ")}`, "error");
      return;
    }

    if (!hasQueries && !hasFile) {
      addMessage("Please either provide queries or upload a file", "error");
      return;
    }

    startApiCall();
    try {
      // Prepare payload for preview
      const payload = {
        ...formData,
        queries: hasQueries ? nonEmptyQueries : undefined,
      };
      const response = await executeConsistencyEvaluation(payload, agentListDropdown);
      if (response) {
        let data;
        try {
          data = await response;
        } catch (e) {
          addMessage("Unexpected response format from server.", "error");
          endApiCall();
          return;
        }
        if (data.status === "agent_exists") {
          addMessage(data.message || "Agent already exists!", "error");
          setResults(null); // Don't show preview/results panel
          endApiCall();
          return;
        }
        addMessage(data.message || "Preview generated and saved successfully.", "success");

        // Get the canonical ID from response or formData
        const canonicalId =
          data.agent_id ||
          data.agentic_application_id ||
          formData.agent_id ||
          agentListDropdown.find((a) => a.agentic_application_name === formData.agent_name)?.agentic_application_id;

        // Close the add modal first
        setPlusBtnClicked(false);

        // Clear add modal content completely
        setFormData({
          model_name: "",
          agent_type: "",
          agent_name: "",
          uploaded_file: null,
        });
        setManualQuery("");
        setAddModeQueries([""]); // Reset to one empty query
        setModelSearchTerm("");
        setAgentType(agentTypesDropdown[0].value);
        setAgentTypeSearchTerm("");
        setAgentSearchTerm("");
        setSelectedModelIndex(-1);
        setSelectedAgentTypeIndex(-1);
        setSelectedAgentIndex(-1);
        if (fileInputRef.current) fileInputRef.current.value = "";

        // Immediately switch to edit mode with the response data
        setTimeout(() => {
          isEditModeTransitionRef.current = true; // Mark that we're transitioning to edit mode
          setPlusBtnClicked(true);
          setIsEditMode(true);

          // Populate form with response data for edit mode
          setFormData({
            model_name: data.model_name || payload.model_name || "",
            agent_type: data.agent_type || payload.agent_type || "",
            agent_name: data.agent_name || payload.agent_name || "",
            uploaded_file: null,
            agent_id: canonicalId,
            agentic_application_id: canonicalId,
          });

          setModelSearchTerm(data.model_name || payload.model_name || "");
          setAgentType(data.agent_type || payload.agent_type || agentTypesDropdown[0].value);
          setAgentTypeSearchTerm(data.agent_type || payload.agent_type || "");
          setAgentSearchTerm(data.agent_name || payload.agent_name || "");
          setEditQueries(data.queries || []);

          // Clear edit mode transition flag after state updates complete
          setTimeout(() => {
            isEditModeTransitionRef.current = false;
          }, 100);

          // Set results for preview panel
          setResults({
            queries: data.queries,
            responses: data.responses,
            rerun_url: data.rerun_url || "",
            approve_url: data.approve_url || "",
            agentic_application_id: canonicalId,
            agent_id: canonicalId,
            agent_name: data.agent_name || payload.agent_name || "",
          });

          // Reset robustness states
          setRobustnessActive(false);
          setRobustnessResults(null);
          setRobustnessQueries([]);
          setForceUpdate((f) => f + 1); // Force preview panel to re-render
        }, 100); // Small delay to ensure modal closes before reopening in edit mode
      } else {
        addMessage(`Failed to execute preview: ${response.status} ${response.statusText}`, "error");
      }
    } catch (error) {
      handleApiError(error, {
        context: "consistency_execution",
        customMessage: "Error executing consistency evaluation",
      });
    } finally {
      endApiCall();
    }
  };

  const handleRobustnessRerun = async (agenticId) => {
    if (!agenticId) {
      addMessage("Agentic Application ID is required for robustness rerun.", "error");
      return;
    }
    setRobustnessLoading(true);
    startApiCall();
    try {
      const endpoint = `${APIs.ROBUSTNESS_PREVIEW_QUERIES}${agenticId}`;
      const response = await postData(endpoint, { agentic_application_id: String(agenticId) }, { headers: { "Content-Type": "application/json" } });
      if (response && Array.isArray(response.generated_queries)) {
        setRobustnessResults({
          queries: response.generated_queries,
          responses: [],
          agentic_application_id: agenticId,
        });
        addMessage(response.message || "Robustness queries loaded!", "success");
      } else {
        setRobustnessResults({ queries: [], responses: [], agentic_application_id: agenticId });
        addMessage("No robustness queries found.", "warning");
      }
    } catch (error) {
      //setRobustnessResults({ queries: [], responses: [], agentic_application_id: agenticId });
      handleApiError(error, {
        context: "robustness_rerun",
        customMessage: "Error loading robustness queries",
      });
    } finally {
      endApiCall();
      setRobustnessLoading(false);
    }
  };

  const handleRobustnessApprove = async () => {
    const agenticId = robustnessResults?.agentic_application_id || results?.agentic_application_id;
    if (!agenticId) {
      addMessage("Agentic Application ID is required for robustness approve.", "error");
      return;
    }
    setRobustnessLoading(true);
    startApiCall();
    try {
      // POST to /evaluation/robustness/approve-evaluation/{agenticId} with agentic_application_id in body
      const endpoint = `${APIs.ROBUSTNESS_APPROVE_EVALUATION}${agenticId}`;
      const response = await postData(endpoint, { agentic_application_id: agenticId }, { headers: { "Content-Type": "application/json" } });
      if (response) {
        addMessage(response.message || "Robustness approval executed successfully.", "success");
        // Close the edit mode and reset states
        setRobustnessResults(null);
        setRobustnessQueries([]);
        setRobustnessActive(false);
        setIsEditMode(false);
        setPlusBtnClicked(false);
        setResults(null);
        await fetchAvailableAgents();
      } else {
        addMessage("Failed to execute robustness approval.", "error");
      }
    } catch (error) {
      // Extract the actual error message from the response if available
      handleApiError(error, {
        context: "robustness_approval",
        customMessage: "Error during robustness approval",
        suppressToast: false,
      });
    } finally {
      endApiCall();
      setRobustnessLoading(false);
    }
  };

  // --- Keyboard navigation handlers ---
  const handleAgentKeyDown = (e) => {
    if (!isAgentDropdownOpen) {
      if (e.key === "ArrowDown") {
        setIsAgentDropdownOpen(true);
        setSelectedAgentIndex(0);
        e.preventDefault();
      }
      return;
    }
    switch (e.key) {
      case "ArrowDown":
        e.preventDefault();
        setSelectedAgentIndex((prev) => (prev < filteredAgents.length - 1 ? prev + 1 : 0));
        break;
      case "ArrowUp":
        e.preventDefault();
        setSelectedAgentIndex((prev) => (prev > 0 ? prev - 1 : filteredAgents.length - 1));
        break;
      case "Enter":
        e.preventDefault();
        if (selectedAgentIndex >= 0 && selectedAgentIndex < filteredAgents.length) {
          const selectedAgent = filteredAgents[selectedAgentIndex];
          handleAgentDropdownSelect(selectedAgent);
        }
        break;
      case "Escape":
        setIsAgentDropdownOpen(false);
        setSelectedAgentIndex(-1);
        break;
    }
  };
  const handleAgentTypeKeyDown = (e) => {
    if (!isAgentTypeDropdownOpen) {
      if (e.key === "ArrowDown") {
        setIsAgentTypeDropdownOpen(true);
        setSelectedAgentTypeIndex(0);
        e.preventDefault();
      }
      return;
    }
    switch (e.key) {
      case "ArrowDown":
        e.preventDefault();
        setSelectedAgentTypeIndex((prev) => (prev < filteredAgentTypes.length - 1 ? prev + 1 : 0));
        break;
      case "ArrowUp":
        e.preventDefault();
        setSelectedAgentTypeIndex((prev) => (prev > 0 ? prev - 1 : filteredAgentTypes.length - 1));
        break;
      case "Enter":
        e.preventDefault();
        if (selectedAgentTypeIndex >= 0 && selectedAgentTypeIndex < filteredAgentTypes.length) {
          const selectedAgentType = filteredAgentTypes[selectedAgentTypeIndex];
          setFormData((prev) => ({ ...prev, agent_type: selectedAgentType.value, agent_name: "", agent_id: "" }));
          setAgentTypeSearchTerm(selectedAgentType.label);
          setAgentType(selectedAgentType.value);
          setIsAgentTypeDropdownOpen(false);
          setSelectedAgentTypeIndex(-1);
          setAgentSearchTerm("");
          setIsAgentDropdownOpen(false);
          setSelectedAgentIndex(-1);
        }
        break;
      case "Escape":
        setIsAgentTypeDropdownOpen(false);
        setSelectedAgentTypeIndex(-1);
        break;
    }
  };
  const handleModelKeyDown = (e) => {
    if (!isModelDropdownOpen) {
      if (e.key === "ArrowDown") {
        setIsModelDropdownOpen(true);
        setSelectedModelIndex(0);
        e.preventDefault();
      }
      return;
    }
    switch (e.key) {
      case "ArrowDown":
        e.preventDefault();
        setSelectedModelIndex((prev) => (prev < filteredModels.length - 1 ? prev + 1 : 0));
        break;
      case "ArrowUp":
        e.preventDefault();
        setSelectedModelIndex((prev) => (prev > 0 ? prev - 1 : filteredModels.length - 1));
        break;
      case "Enter":
        e.preventDefault();
        if (selectedModelIndex >= 0 && selectedModelIndex < filteredModels.length) {
          const selectedModel = filteredModels[selectedModelIndex];
          setFormData((prev) => ({ ...prev, model_name: selectedModel.value, agent_type: "", agent_name: "", agent_id: "" }));
          setModelSearchTerm(selectedModel.label);
          setIsModelDropdownOpen(false);
          setSelectedModelIndex(-1);
        }
        break;
      case "Escape":
        setIsModelDropdownOpen(false);
        setSelectedModelIndex(-1);
        break;
    }
  };

  const agentsListRef = useRef(null);
  const lastCardRef = useRef(null);
  const isEditModeTransitionRef = useRef(false); // Track when we're transitioning to edit mode

  useEffect(() => {
    if (agentsListRef.current && lastCardRef.current) {
      // Scroll the container so the last card is visible
      const container = agentsListRef.current;
      const lastCard = lastCardRef.current;
      // Scroll so last card is at the bottom
      container.scrollTop = lastCard.offsetTop - container.offsetTop;
    }
  }, [availableAgents]);

  // In the agent name dropdown, when an agent is selected:
  const handleAgentDropdownSelect = (agent) => {
    const canonicalId = agent.agent_id;
    setFormData((prev) => ({
      ...prev,
      agent_name: agent.agent_name,
      agent_id: canonicalId,
      agentic_application_id: canonicalId,
    }));
    setAgentSearchTerm(agent.agent_name);
    setIsAgentDropdownOpen(false);
    setSelectedAgentIndex(-1);
  };

  return (
    <div className={`${styles.container} consistencyContainer`}>
      {loading && <Loader />}
      <div className={consistencyStyles.agentsPageContainer}>
        {/* Score View Modal */}
        {isScoreView && (
          <div className={consistencyStyles.scoreViewContainer}>
            <button className={`${listStyles.closeBtn} ${consistencyStyles.scoreViewCloseBtn}`} onClick={handleCloseScoreView} aria-label="Close score view">
              ✖
            </button>

            {/* Agent Name Header */}
            <div className={consistencyStyles.scoreViewHeader}>
              <h3 className={consistencyStyles.scoreViewTitle}>{formData.agent_name}</h3>
            </div>

            {scoreViewLoading ? (
              <div className={consistencyStyles.scoreViewLoading}>
                <Loader />
              </div>
            ) : (
              <div className={consistencyStyles.scoreViewContent}>
                {/* Left Panel - Consistency Scores (50%) */}
                <div className={consistencyStyles.scorePanel}>
                  <div className={`${consistencyStyles.scorePanelHeader} ${consistencyStyles.scorePanelHeaderConsistency}`}>
                    <h4 className={consistencyStyles.scorePanelHeaderTitle}>Consistency Scores</h4>
                    <button
                      onClick={handleDownloadConsistencyReport}
                      className={consistencyStyles.downloadReportBtn}
                      aria-label="Download consistency report"
                      title="Download consistency report">
                      <SVGIcons icon="download" fill="#007cc3" width={16} height={16} />
                      <span>Download Report</span>
                    </button>
                  </div>

                  {consistencyScoreData ? (
                    <div className={consistencyStyles.scorePanelContent}>
                      {/* Metadata Section */}
                      <div className={consistencyStyles.scoreMetadata}>
                        <div className={consistencyStyles.scoreMetadataRow}>
                          <span className={consistencyStyles.scoreMetadataLabel}>Model Name:</span>
                          <span className={consistencyStyles.scoreMetadataValue}>{consistencyScoreData.model_name || "N/A"}</span>
                        </div>
                        <div className={consistencyStyles.scoreMetadataRow}>
                          <span className={consistencyStyles.scoreMetadataLabel}>Last Updated:</span>
                          <span className={consistencyStyles.scoreMetadataValue}>
                            {consistencyScoreData.last_updated_at ? new Date(consistencyScoreData.last_updated_at).toLocaleString() : "N/A"}
                          </span>
                        </div>
                        <div className={consistencyStyles.scoreMetadataRow}>
                          <span className={consistencyStyles.scoreMetadataLabel}>Last Robustness Run:</span>
                          <span className={consistencyStyles.scoreMetadataValue}>
                            {consistencyScoreData.last_robustness_run_at ? new Date(consistencyScoreData.last_robustness_run_at).toLocaleString() : "N/A"}
                          </span>
                        </div>
                        <div className={consistencyStyles.scoreMetadataRow}>
                          <span className={consistencyStyles.scoreMetadataLabel}>Queries Last Updated:</span>
                          <span className={consistencyStyles.scoreMetadataValue}>
                            {consistencyScoreData.queries_last_updated_at ? new Date(consistencyScoreData.queries_last_updated_at).toLocaleString() : "N/A"}
                          </span>
                        </div>
                      </div>

                      {/* Recent Scores */}
                      <div className={consistencyStyles.scoreSection}>
                        <h5 className={consistencyStyles.scoreSectionTitle}>Recent Consistency Scores</h5>
                        {consistencyScoreData.recent_scores && consistencyScoreData.recent_scores.length > 0 ? (
                          consistencyScoreData.recent_scores.map((scoreItem, idx) => {
                            const cardId = `consistency-card-${idx}`;
                            const isExpanded = expandedCards[cardId];
                            return (
                              <div key={idx} className={consistencyStyles.scoreCard} data-card-id={cardId}>
                                <div
                                  className={`${consistencyStyles.scoreCardExpandAll} ${isExpanded ? consistencyStyles.expanded : ""}`}
                                  onClick={() => toggleExpandAll(cardId)}
                                  title={isExpanded ? "Collapse all responses" : "Expand all responses"}>
                                  {isExpanded ? "Hide all responses" : "Show all responses"}
                                </div>
                                <div className={consistencyStyles.scoreCardQuery}>
                                  <span className={`${consistencyStyles.scoreCardQueryLabel} ${consistencyStyles.scoreCardQueryLabelConsistency}`}>Query: </span>
                                  <span className={consistencyStyles.scoreCardQueryText}>{scoreItem.query}</span>
                                </div>
                                {scoreItem.category && (
                                  <div className={consistencyStyles.scoreCardCategory}>
                                    <span className={consistencyStyles.scoreCardCategoryLabel}>Category: </span>
                                    <span className={consistencyStyles.scoreCardCategoryText}>{scoreItem.category}</span>
                                  </div>
                                )}
                                {/* Display all available scores and responses */}
                                {Object.keys(scoreItem)
                                  .filter((key) => key.startsWith("score_"))
                                  .map((scoreKey) => {
                                    const index = scoreKey.split("_")[1];
                                    const responseKey = `response_${index}`;
                                    const timestampKey = `timestamp_${index}`;
                                    return (
                                      <details key={scoreKey} className={consistencyStyles.scoreItem}>
                                        <summary className={consistencyStyles.scoreItemSummary}>
                                          <div className={consistencyStyles.scoreItemLeft}>
                                            <span className={consistencyStyles.scoreItemScore}>Score {index}</span>
                                            <span
                                              className={`${consistencyStyles.scoreItemScoreValue} ${
                                                scoreItem[scoreKey] === 1 ? consistencyStyles.scoreValueSuccess : consistencyStyles.scoreValueError
                                              }`}>
                                              {scoreItem[scoreKey]}
                                            </span>
                                          </div>
                                          {scoreItem[timestampKey] && (
                                            <div className={consistencyStyles.scoreItemRight}>
                                              <span className={consistencyStyles.scoreItemTimestamp}>Timestamp</span>
                                              <span className={consistencyStyles.scoreItemTimestampValue}>{new Date(scoreItem[timestampKey]).toLocaleString()}</span>
                                            </div>
                                          )}
                                        </summary>
                                        {scoreItem[responseKey] && (
                                          <div className={consistencyStyles.scoreItemResponse}>
                                            <span className={consistencyStyles.scoreItemResponseLabel}>Response:</span>
                                            <span className={consistencyStyles.scoreItemResponseText}>{scoreItem[responseKey]}</span>
                                          </div>
                                        )}
                                      </details>
                                    );
                                  })}
                              </div>
                            );
                          })
                        ) : (
                          <p className={consistencyStyles.scoreEmptyState}>No recent scores available</p>
                        )}
                      </div>
                    </div>
                  ) : (
                    <p className={consistencyStyles.scoreEmptyState}>No consistency data available</p>
                  )}
                </div>

                {/* Right Panel - Robustness Scores (50%) */}
                <div className={consistencyStyles.scorePanel}>
                  <div className={`${consistencyStyles.scorePanelHeader} ${consistencyStyles.scorePanelHeaderRobustness}`}>
                    <h4 className={consistencyStyles.scorePanelHeaderTitle}>Robustness Scores</h4>
                    <button
                      onClick={handleDownloadRobustnessReport}
                      className={consistencyStyles.downloadReportBtn}
                      aria-label="Download robustness report"
                      title="Download robustness report">
                      <SVGIcons icon="download" fill="#28a745" width={16} height={16} />
                      <span>Download Report</span>
                    </button>
                  </div>

                  {robustnessScoreData ? (
                    <div className={consistencyStyles.scorePanelContent}>
                      {/* Metadata Section */}
                      <div className={consistencyStyles.scoreMetadata}>
                        <div className={consistencyStyles.scoreMetadataRow}>
                          <span className={consistencyStyles.scoreMetadataLabel}>Model Name:</span>
                          <span className={consistencyStyles.scoreMetadataValue}>{robustnessScoreData.model_name || "N/A"}</span>
                        </div>
                        <div className={consistencyStyles.scoreMetadataRow}>
                          <span className={consistencyStyles.scoreMetadataLabel}>Last Updated:</span>
                          <span className={consistencyStyles.scoreMetadataValue}>
                            {robustnessScoreData.last_updated_at ? new Date(robustnessScoreData.last_updated_at).toLocaleString() : "N/A"}
                          </span>
                        </div>
                        <div className={consistencyStyles.scoreMetadataRow}>
                          <span className={consistencyStyles.scoreMetadataLabel}>Last Robustness Run:</span>
                          <span className={consistencyStyles.scoreMetadataValue}>
                            {robustnessScoreData.last_robustness_run_at ? new Date(robustnessScoreData.last_robustness_run_at).toLocaleString() : "N/A"}
                          </span>
                        </div>
                        <div className={consistencyStyles.scoreMetadataRow}>
                          <span className={consistencyStyles.scoreMetadataLabel}>Queries Last Updated:</span>
                          <span className={consistencyStyles.scoreMetadataValue}>
                            {robustnessScoreData.queries_last_updated_at ? new Date(robustnessScoreData.queries_last_updated_at).toLocaleString() : "N/A"}
                          </span>
                        </div>
                      </div>

                      {/* Recent Robustness Scores */}
                      <div className={consistencyStyles.scoreSection}>
                        <h5 className={consistencyStyles.scoreSectionTitle}>Recent Robustness Scores</h5>
                        {robustnessScoreData.recent_robustness_scores && robustnessScoreData.recent_robustness_scores.length > 0 ? (
                          robustnessScoreData.recent_robustness_scores.map((scoreItem, idx) => {
                            const cardId = `robustness-card-${idx}`;
                            const isExpanded = expandedCards[cardId];
                            return (
                              <div key={idx} className={consistencyStyles.scoreCard} data-card-id={cardId}>
                                <div
                                  className={`${consistencyStyles.scoreCardExpandAll} ${isExpanded ? consistencyStyles.expanded : ""}`}
                                  onClick={() => toggleExpandAll(cardId)}
                                  title={isExpanded ? "Collapse all responses" : "Expand all responses"}>
                                  {isExpanded ? "Hide all responses" : "Show all responses"}
                                </div>
                                <div className={consistencyStyles.scoreCardQuery}>
                                  <span className={`${consistencyStyles.scoreCardQueryLabel} ${consistencyStyles.scoreCardQueryLabelRobustness}`}>Query: </span>
                                  <span className={consistencyStyles.scoreCardQueryText}>{scoreItem.query}</span>
                                </div>
                                {scoreItem.category && (
                                  <div className={consistencyStyles.scoreCardCategory}>
                                    <span className={consistencyStyles.scoreCardCategoryLabel}>Category: </span>
                                    <span className={consistencyStyles.scoreCardCategoryText}>{scoreItem.category}</span>
                                  </div>
                                )}
                                {/* Display all available scores and responses */}
                                {Object.keys(scoreItem)
                                  .filter((key) => key.startsWith("score_"))
                                  .map((scoreKey) => {
                                    const index = scoreKey.split("_")[1];
                                    const responseKey = `response_${index}`;
                                    const timestampKey = `timestamp_${index}`;
                                    return (
                                      <details key={scoreKey} className={consistencyStyles.scoreItem}>
                                        <summary className={consistencyStyles.scoreItemSummary}>
                                          <div className={consistencyStyles.scoreItemLeft}>
                                            <span className={consistencyStyles.scoreItemScore}>Score {index}</span>
                                            <span
                                              className={`${consistencyStyles.scoreItemScoreValue} ${
                                                scoreItem[scoreKey] === 1 ? consistencyStyles.scoreValueSuccess : consistencyStyles.scoreValueError
                                              }`}>
                                              {scoreItem[scoreKey]}
                                            </span>
                                          </div>
                                          {scoreItem[timestampKey] && (
                                            <div className={consistencyStyles.scoreItemRight}>
                                              <span className={consistencyStyles.scoreItemTimestamp}>Timestamp</span>
                                              <span className={consistencyStyles.scoreItemTimestampValue}>{new Date(scoreItem[timestampKey]).toLocaleString()}</span>
                                            </div>
                                          )}
                                        </summary>
                                        {scoreItem[responseKey] && (
                                          <div className={consistencyStyles.scoreItemResponse}>
                                            <span className={consistencyStyles.scoreItemResponseLabel}>Response:</span>
                                            <span className={consistencyStyles.scoreItemResponseText}>{scoreItem[responseKey]}</span>
                                          </div>
                                        )}
                                      </details>
                                    );
                                  })}
                              </div>
                            );
                          })
                        ) : (
                          <p className={consistencyStyles.scoreEmptyState}>No recent robustness scores available</p>
                        )}
                      </div>
                    </div>
                  ) : (
                    <p className={consistencyStyles.scoreEmptyState}>No robustness data available</p>
                  )}
                </div>
              </div>
            )}
          </div>
        )}

        {/* Always show the agents list */}
        {!isEditMode && !isScoreView && (
          <div className={listStyles.visibleAgentsContainer} ref={agentsListRef} style={{ gap: "16px" }}>
            <div className={listStyles.subHeaderContainer} style={{ display: "flex", alignItems: "center", justifyContent: "space-between", width: "100%" }}>
              <div className="iafPageSubHeader">
                <h6>Consistency</h6>
              </div>
              <button
                type="button"
                onClick={handlePlusClick}
                className="plus addConssitencyAgent"
                style={{ background: "#f5f5f5", boxShadow: "0px 4px 4px #00000029", border: "1px solid #c7c7c745", borderRadius: "3px", padding: "7px", display: "flex" }}>
                <SVGIcons icon="fa-plus" fill="#007CC3" width={16} height={16} />
              </button>
            </div>
            <div className={listStyles.agentsList} style={{ maxHeight: "Calc(100vh - 135px)", overflowY: "auto" }}>
              {availableAgents.length === 0 ? (
                <div
                  style={{
                    display: "flex",
                    flexDirection: "column",
                    alignItems: "center",
                    justifyContent: "center",
                    padding: "10px 0",
                    textAlign: "center",
                    color: "#666",
                  }}>
                  <p
                    style={{
                      fontSize: "16px",
                      marginBottom: "8px",
                      fontWeight: "500",
                    }}>
                    No Available Agents Found
                  </p>
                  <p
                    style={{
                      fontSize: "14px",
                      color: "#999",
                      maxWidth: "400px",
                    }}>
                    Get started by clicking the + button above to add your first consistency evaluation agent.
                  </p>
                </div>
              ) : (
                availableAgents.map((agent, idx) => (
                  <ConsistencyAgentCard
                    key={agent.agentic_application_id || agent.id || idx}
                    agent={{
                      ...agent,
                      agentic_application_id: agent.agentic_application_id || agent.id,
                    }}
                    onDelete={handleDeleteAgent}
                    onEdit={handleEditAgent}
                    onScore={handleScoreAgent}
                    isLoading={deleteLoading}
                  />
                ))
              )}
            </div>
          </div>
        )}

        {/* Show this update section as soon as Adding a new consistency agent is successfull
        Also show this section if user clicks on the pencil icon of each agent */}
        {isEditMode && (
          <div
            className="editMode"
            style={{
              width: "100%",
              height: "Calc(100vh - 70px)",
              display: "flex",
              flexDirection: "row",
              gap: "24px",
              alignItems: "flex-start",
              minHeight: "80vh",
              position: "relative",
              overflow: "hidden",
            }}>
            <button
              className={listStyles.closeBtn}
              onClick={handleClosePlusPanel}
              aria-label="Close update panel"
              style={{ position: "absolute", top: "-4px", right: 16, zIndex: 2 }}>
              ✖
            </button>
            {/* Left: Edit Form Panel */}
            <div style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column", alignItems: "stretch", height: "100%", overflow: "auto" }}>
              <LeftNavPanel styles={consistencyStyles} title={formData.agent_name || formData.agentic_application_name || "Edit Agent"}>
                <div className={consistencyStyles.formGroup}>
                  <p className="spacer" style={{ marginTop: "8px" }}></p>
                  <label htmlFor="model_name" className="label">
                    Model Name <span className="required">*</span>
                  </label>
                  <div className={styles.searchableDropdown} ref={modelDropdownRef}>
                    <input
                      type="text"
                      id="model_name"
                      placeholder="select model"
                      value={modelSearchTerm}
                      onChange={(e) => {
                        setModelSearchTerm(e.target.value);
                        setIsModelDropdownOpen(true);
                        setSelectedModelIndex(-1);
                      }}
                      onFocus={() => setIsModelDropdownOpen(true)}
                      className={styles.searchInput}
                      disabled={loading}
                      onKeyDown={handleModelKeyDown}
                    />
                    {isModelDropdownOpen && (
                      <div className={styles.dropdownList}>
                        {filteredModels.length > 0 ? (
                          filteredModels.map((model, index) => (
                            <div
                              key={index}
                              className={[styles.dropdownItem, formData.model_name === model.value ? styles.selected : "", selectedModelIndex === index ? styles.highlighted : ""]
                                .filter(Boolean)
                                .join(" ")}
                              onClick={() => {
                                setFormData((prev) => ({ ...prev, model_name: model.value }));
                                setModelSearchTerm(model.label);
                                setIsModelDropdownOpen(false);
                                setSelectedModelIndex(-1);
                              }}>
                              {model.label}
                            </div>
                          ))
                        ) : (
                          <div className={styles.dropdownItem}>{modelSearchTerm ? "No models found" : "Loading models..."}</div>
                        )}
                      </div>
                    )}
                  </div>
                </div>

                {/* Dynamic Queries Section - Hidden when file is uploaded */}
                {!showOnlyEditQueries && (
                  <div className={`${consistencyStyles.formGroup} dynamicQuery`}>
                    <label className={consistencyStyles.label}>
                      Queries <span className={consistencyStyles.required}>*</span>
                    </label>
                    <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
                      {editQueries.map((query, idx) => (
                        <div key={idx} style={{ display: "flex", gap: "8px", alignItems: "center" }}>
                          <input
                            type="text"
                            ref={(el) => (editModeQueryRefs.current[idx] = el)}
                            value={query}
                            onChange={(e) => {
                              const newQueries = [...editQueries];
                              newQueries[idx] = e.target.value;
                              setEditQueries(newQueries);
                              // Clear file when user starts typing
                              if (e.target.value.trim() !== "" && editModeFile) {
                                setEditModeFile(null);
                                setEditFileQueries([]);
                                if (editFileInputRef.current) editFileInputRef.current.value = "";
                              }
                            }}
                            placeholder={`Enter query ${idx + 1}`}
                            className={styles.searchInput}
                            style={{ flex: 1 }}
                            disabled={loading || editModeFile}
                          />
                          {!(editQueries.length === 1 && !query?.trim()) && (
                            <button
                              type="button"
                              onClick={() => {
                                if (editQueries.length === 1) {
                                  // Clear the input value if only one query exists
                                  const newQueries = [""];
                                  setEditQueries(newQueries);
                                } else {
                                  // Remove the query if multiple queries exist
                                  const newQueries = editQueries.filter((_, i) => i !== idx);
                                  setEditQueries(newQueries);
                                }
                              }}
                              className={styles.removeFileButton}
                              style={{ padding: "8px 12px", fontSize: "18px" }}
                              aria-label="Remove query"
                              disabled={editModeFile}>
                              &times;
                            </button>
                          )}
                        </div>
                      ))}
                      {editQueries.length > 0 && editQueries[editQueries.length - 1] !== undefined && (
                        <button
                          type="button"
                          onClick={() => {
                            setEditQueries([...editQueries, ""]);
                            // Focus on the newly added input after state updates
                            setTimeout(() => {
                              const newIndex = editQueries.length;
                              if (editModeQueryRefs.current[newIndex]) {
                                editModeQueryRefs.current[newIndex].focus();
                              }
                            }, 0);
                          }}
                          className="iafButton iafSubButton"
                          style={{ alignSelf: "flex-start", padding: "3px 6px", fontSize: "12px" }}
                          disabled={loading || editModeFile}>
                          + Add Another Query
                        </button>
                      )}
                    </div>
                  </div>
                )}

                {/* Show "or" text only when both sections are visible */}
                {showAllEditSections && (
                  <p className="queriesOrText" style={{ width: "100%", textAlign: "center", fontSize: "14px", color: "#ccc" }}>
                    (or)
                  </p>
                )}

                {/* File Upload Section - Hidden when queries are entered */}
                {!showOnlyEditFileUpload && (
                  <div className={`${consistencyStyles.formGroup} queryAddUpload`}>
                    <div className={styles.labelWithInfo}>
                      <div style={{ width: "100%", display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
                        <label htmlFor="edit_uploaded_file" className={consistencyStyles.label}>
                          Upload a Query File {!hasEditQueries && <span className={styles.required}>*</span>}
                          <span className={styles.instructionText}>(File must have exactly one column named 'queries'. Use either queries above OR file upload, not both)</span>
                        </label>
                        <div className={styles.templateDownloadContainer}>
                          <span
                            onClick={(e) => {
                              e.preventDefault();
                              handleTemplateDownload();
                            }}
                            className={styles.templateDownloadLink}>
                            Download template
                          </span>
                        </div>
                      </div>
                    </div>
                    <input
                      type="file"
                      id="edit_uploaded_file"
                      name="edit_uploaded_file"
                      ref={editFileInputRef}
                      accept=".csv,.xlsx"
                      onChange={handleEditFileInputChange}
                      className={styles.fileInput}
                      disabled={loading || hasEditQueries}
                      style={{ display: "none" }}
                    />
                    {!editModeFile ? (
                      <div
                        className={[styles.fileUploadContainer, editIsDragging ? styles.dragging : "", loading || hasEditQueries ? styles.disabled : ""].filter(Boolean).join(" ")}
                        onDragEnter={!loading && !hasEditQueries ? handleEditDragEnter : undefined}
                        onDragLeave={!loading && !hasEditQueries ? handleEditDragLeave : undefined}
                        onDragOver={!loading && !hasEditQueries ? handleEditDragOver : undefined}
                        onDrop={(e) => {
                          if (!loading && !hasEditQueries) {
                            handleEditDrop(e);
                          }
                        }}
                        onClick={() => !loading && !hasEditQueries && !editModeFile && editFileInputRef.current && editFileInputRef.current.click()}>
                        <div className={styles.uploadPrompt}>
                          <span>{editIsDragging ? "Drop file here" : hasEditQueries ? "Queries provided - file upload disabled" : "Click to upload or drag and drop"}</span>
                          <span>
                            <small>Supported Extensions csv & xlsx</small>
                          </span>
                        </div>
                      </div>
                    ) : (
                      <>
                        <div className={styles.fileCard}>
                          <div className={consistencyStyles.fileInfo}>
                            <span className={styles.fileName}>{editModeFile.name}</span>
                            <button type="button" onClick={handleEditRemoveFile} className={styles.removeFileButton} aria-label="Remove file">
                              &times;
                            </button>
                          </div>
                        </div>
                        {/* Display queries from uploaded file */}
                        {editFileQueries.length > 0 && (
                          <div style={{ marginTop: "12px" }}>
                            <label className={styles.label} style={{ marginBottom: "8px", display: "block" }}>
                              Queries from file ({editFileQueries.length})
                            </label>
                            <div
                              style={{
                                // maxHeight: "200px",
                                overflowY: "auto",
                                border: "1px solid #e0e0e0",
                                borderRadius: "4px",
                                padding: "8px",
                                backgroundColor: "#f9f9f9",
                              }}>
                              {editFileQueries.map((query, idx) => (
                                <div
                                  key={idx}
                                  style={{
                                    padding: "6px 8px",
                                    marginBottom: "4px",
                                    backgroundColor: "#fff",
                                    borderRadius: "3px",
                                    border: "1px solid #e8e8e8",
                                    fontSize: "13px",
                                    color: "#333",
                                  }}>
                                  <span style={{ fontWeight: "500", color: "#666", marginRight: "8px" }}>{idx + 1}.</span>
                                  {query}
                                </div>
                              ))}
                            </div>
                          </div>
                        )}
                      </>
                    )}
                  </div>
                )}

                <div className={consistencyStyles.buttonGroupSticky}>
                  <button type="button" onClick={handleUpdate} className="iafButton iafButtonPrimary" disabled={loading || !enableUpdate}>
                    Update
                  </button>
                </div>
              </LeftNavPanel>
            </div>
            {/* Right: Results Panels - Consistency and Robustness */}
            {results && !robustnessActive && (
              <div
                style={{ flex: 1, minWidth: 0, minHeight: 0, height: "100%", display: "flex", flexDirection: "column", alignItems: "stretch", position: "relative" }}
                key={forceUpdate}>
                <div className="rightResult1" style={{ flex: 1, minHeight: 0, display: "flex", flexDirection: "column" }}>
                  <RightResultsPanel
                    styles={consistencyStyles}
                    results={results}
                    loading={loading}
                    handleRerun={handleRerun}
                    handleApprove={handleApprove}
                    scrollCardsOnly={true}
                  />
                </div>
              </div>
            )}
            {/* Robustness Panel in Edit Mode */}
            {robustnessActive && (
              <div style={{ flex: 1, minWidth: 0, minHeight: 0, height: "100%", display: "flex", flexDirection: "column", alignItems: "stretch", position: "relative" }}>
                <div className="rightResultRobustness" style={{ flex: 1, minHeight: 0, display: "flex", flexDirection: "column" }}>
                  <RightResultsPanel
                    styles={consistencyStyles}
                    results={robustnessResults || { queries: [], responses: [], agentic_application_id: null }}
                    loading={robustnessLoading}
                    handleRerun={() => handleRobustnessRerun(robustnessResults?.agentic_application_id)}
                    handleApprove={handleRobustnessApprove}
                    scrollCardsOnly={true}
                  />
                </div>
              </div>
            )}
          </div>
        )}

        {/* Modal overlay for add mode */}
        {plusBtnClicked && !isEditMode && (
          <div className={consistencyStyles.modalOverlay} onClick={handleClosePlusPanel}>
            {loading && (
              <div onClick={(e) => e.stopPropagation()}>
                <Loader />
              </div>
            )}
            <div className={consistencyStyles.modal} onClick={(e) => e.stopPropagation()}>
              <div className={consistencyStyles.modalContent}>
                <div className={consistencyStyles.modalHeader}>
                  <h2 className={consistencyStyles.modalTitle}>ADD CONSISTENCY EVALUATION</h2>
                  <button className={consistencyStyles.closeBtn} onClick={handleClosePlusPanel}>
                    ×
                  </button>
                </div>
                {/* <div style={{ width: "100%", display: "flex", flexDirection: "row", gap: "24px", alignItems: "flex-start", minHeight: "80vh", overflow: "hidden" }}> */}
                <div style={{ width: "100%", display: "flex", flexDirection: "row", gap: "24px", alignItems: "flex-start", minHeight: "80vh" }}>
                  {/* Left: Form Panel */}
                  <div style={{ flex: 1, minWidth: 0, minHeight: 0, height: "92vh", display: "flex", flexDirection: "column", alignItems: "stretch", position: "relative" }}>
                    <LeftNavPanel styles={consistencyStyles} title="">
                      <div style={{ display: "flex", flexDirection: "column", flex: 1, minHeight: 0, height: "100%" }}>
                        <div style={{ flex: 1, minHeight: 0, overflowY: "auto", gap: "12px", display: "flex", flexDirection: "column" }}>
                          {/* ...existing form fields... */}
                          <div className={consistencyStyles.formGroup}>
                            <label htmlFor="model_name" className={styles.label}>
                              Model Name <span className={styles.required}>*</span>
                            </label>
                            <div className={styles.searchableDropdown} ref={modelDropdownRef}>
                              <input
                                type="text"
                                id="model_name"
                                placeholder="Select model"
                                value={modelSearchTerm}
                                onChange={(e) => {
                                  setModelSearchTerm(e.target.value);
                                  setIsModelDropdownOpen(true);
                                  setSelectedModelIndex(-1);
                                }}
                                // autoFocus
                                onFocus={() => setIsModelDropdownOpen(true)}
                                className={styles.searchInput}
                                onKeyDown={handleModelKeyDown}
                              />
                              {isModelDropdownOpen && (
                                <div className={styles.dropdownList}>
                                  {filteredModels.length > 0 ? (
                                    filteredModels.map((model, index) => (
                                      <div
                                        key={index}
                                        className={[
                                          styles.dropdownItem,
                                          formData.model_name === model.value ? styles.selected : "",
                                          selectedModelIndex === index ? styles.highlighted : "",
                                        ]
                                          .filter(Boolean)
                                          .join(" ")}
                                        onClick={() => {
                                          setFormData((prev) => ({ ...prev, model_name: model.value, agent_type: "", agent_name: "", uploaded_file: null }));
                                          setModelSearchTerm(model.label);
                                          setIsModelDropdownOpen(false);
                                          setSelectedModelIndex(-1);
                                          setAgentType(agentTypesDropdown[0].value);
                                          setAgentSearchTerm("");
                                          setIsAgentDropdownOpen(false);
                                          setSelectedAgentIndex(-1);
                                          if (fileInputRef.current) fileInputRef.current.value = "";
                                        }}>
                                        {model.label}
                                      </div>
                                    ))
                                  ) : (
                                    <div className={styles.dropdownItem}>{modelSearchTerm ? "No models found" : "Loading models..."}</div>
                                  )}
                                </div>
                              )}
                            </div>
                          </div>
                          <div className={consistencyStyles.formGroup}>
                            <label htmlFor="agent_type" className={styles.label}>
                              Agent Type <span className={styles.required}>*</span>
                            </label>
                            <div className={styles.searchableDropdown} ref={agentTypeDropdownRef}>
                              <input
                                type="text"
                                id="agent_type"
                                placeholder="select agent type"
                                value={agentTypeSearchTerm}
                                onChange={(e) => {
                                  setAgentTypeSearchTerm(e.target.value);
                                  setIsAgentTypeDropdownOpen(true);
                                  setSelectedAgentTypeIndex(-1);
                                }}
                                onFocus={() => setIsAgentTypeDropdownOpen(true)}
                                className={styles.searchInput}
                                disabled={!formData.model_name}
                                onKeyDown={handleAgentTypeKeyDown}
                              />
                              {isAgentTypeDropdownOpen && (
                                <div className={styles.dropdownList}>
                                  {filteredAgentTypes.length > 0 ? (
                                    filteredAgentTypes.map((agentType, index) => (
                                      <div
                                        key={index}
                                        className={[
                                          styles.dropdownItem,
                                          formData.agent_type === agentType.value ? styles.selected : "",
                                          selectedAgentTypeIndex === index ? styles.highlighted : "",
                                        ]
                                          .filter(Boolean)
                                          .join(" ")}
                                        onClick={() => {
                                          setFormData((prev) => ({ ...prev, agent_type: agentType.value, agent_name: "" }));
                                          setAgentTypeSearchTerm(agentType.label);
                                          setAgentType(agentType.value);
                                          setIsAgentTypeDropdownOpen(false);
                                          setSelectedAgentTypeIndex(-1);
                                          setAgentSearchTerm("");
                                          setIsAgentDropdownOpen(false);
                                          setSelectedAgentIndex(-1);
                                        }}>
                                        {agentType.label}
                                      </div>
                                    ))
                                  ) : (
                                    <div className={styles.dropdownItem}>No agent types found</div>
                                  )}
                                </div>
                              )}
                            </div>
                          </div>
                          <div className={consistencyStyles.formGroup}>
                            <label htmlFor="agent_name" className={consistencyStyles.label}>
                              Agent Name <span className={consistencyStyles.required}>*</span>
                            </label>
                            <div className={styles.searchableDropdown} ref={agentDropdownRef}>
                              <input
                                type="text"
                                id="agent_name"
                                placeholder="select agent name"
                                value={formData.agent_name || agentSearchTerm}
                                onChange={(e) => {
                                  setAgentSearchTerm(e.target.value);
                                  setIsAgentDropdownOpen(true);
                                  setSelectedAgentIndex(-1);
                                  setFormData((prev) => ({ ...prev, agent_name: e.target.value }));
                                }}
                                onFocus={() => setIsAgentDropdownOpen(true)}
                                className={styles.searchInput}
                                disabled={!formData.model_name || !formData.agent_type}
                                onKeyDown={handleAgentKeyDown}
                              />
                              {isAgentDropdownOpen && (
                                <div className={styles.dropdownList}>
                                  {filteredAgents.length > 0 ? (
                                    filteredAgents.map((agent, index) => (
                                      <div
                                        key={agent.agentic_application_id || agent.id}
                                        className={[
                                          styles.dropdownItem,
                                          formData.agent_name === agent.agentic_application_name || agentSearchTerm === agent.agentic_application_name ? styles.selected : "",
                                          selectedAgentIndex === index ? styles.highlighted : "",
                                        ]
                                          .filter(Boolean)
                                          .join(" ")}
                                        onClick={() => {
                                          handleAgentDropdownSelect(agent);
                                          setFormData((prev) => ({ ...prev, agent_name: agent.agentic_application_name }));
                                          setAgentSearchTerm(agent.agentic_application_name);
                                        }}>
                                        {agent.agentic_application_name}
                                      </div>
                                    ))
                                  ) : (
                                    <div className={styles.dropdownItem}>No agents found</div>
                                  )}
                                </div>
                              )}
                            </div>
                          </div>

                          {/* Dynamic Queries Section - Hidden when file is uploaded */}
                          {!showOnlyQueries && (
                            <div className={`${consistencyStyles.formGroup} dynamicQuery`}>
                              <label className={consistencyStyles.label}>
                                Queries <span className={consistencyStyles.required}>*</span>
                              </label>
                              <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
                                {addModeQueries.map((query, idx) => (
                                  <div key={idx} style={{ display: "flex", gap: "8px", alignItems: "center" }}>
                                    <input
                                      type="text"
                                      ref={(el) => (addModeQueryRefs.current[idx] = el)}
                                      value={query}
                                      onChange={(e) => {
                                        const newQueries = [...addModeQueries];
                                        newQueries[idx] = e.target.value;
                                        setAddModeQueries(newQueries);
                                        // Clear file when user starts typing
                                        if (e.target.value.trim() !== "" && formData.uploaded_file) {
                                          setFormData((prev) => ({ ...prev, uploaded_file: null }));
                                          if (fileInputRef.current) fileInputRef.current.value = "";
                                        }
                                      }}
                                      placeholder={`Enter query ${idx + 1}`}
                                      className={styles.searchInput}
                                      style={{ flex: 1 }}
                                      disabled={!formData.model_name || formData.uploaded_file}
                                    />
                                    {!(addModeQueries.length === 1 && !query?.trim()) && (
                                      <button
                                        type="button"
                                        onClick={() => {
                                          if (addModeQueries.length === 1) {
                                            // Clear the input value if only one query exists
                                            const newQueries = [""];
                                            setAddModeQueries(newQueries);
                                          } else {
                                            // Remove the query if multiple queries exist
                                            const newQueries = addModeQueries.filter((_, i) => i !== idx);
                                            setAddModeQueries(newQueries);
                                          }
                                        }}
                                        className={styles.removeFileButton}
                                        style={{ padding: "8px 12px", fontSize: "18px" }}
                                        aria-label="Remove query"
                                        disabled={formData.uploaded_file}>
                                        &times;
                                      </button>
                                    )}
                                  </div>
                                ))}
                                {addModeQueries[addModeQueries.length - 1] && (
                                  <button
                                    type="button"
                                    onClick={() => {
                                      setAddModeQueries([...addModeQueries, ""]);
                                      // Focus on the newly added input after state updates
                                      setTimeout(() => {
                                        const newIndex = addModeQueries.length;
                                        if (addModeQueryRefs.current[newIndex]) {
                                          addModeQueryRefs.current[newIndex].focus();
                                        }
                                      }, 0);
                                    }}
                                    className="iafButton iafSubButton"
                                    style={{ alignSelf: "flex-start", padding: "3px 6px", fontSize: "12px" }}
                                    disabled={!formData.model_name || formData.uploaded_file}>
                                    + Add Another Query
                                  </button>
                                )}
                              </div>
                            </div>
                          )}
                          {/* Show "or" text only when both sections are visible */}
                          {showAllSections && (
                            <p className="queriesOrText" style={{ width: "100%", textAlign: "center", fontSize: "14px", color: "#ccc" }}>
                              (or)
                            </p>
                          )}
                          {/* File Upload Section - Hidden when queries are entered */}
                          {!showOnlyFileUpload && (
                            <div className={`${consistencyStyles.formGroup} queryAddUpload`}>
                              <div className={styles.labelWithInfo}>
                                <div style={{ width: "100%", display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
                                  <label htmlFor="uploaded_file" className={consistencyStyles.label}>
                                    Upload a Query File {!hasNonEmptyQueries && <span className={styles.required}>*</span>}
                                    <span className={styles.instructionText}>
                                      (File must have exactly one column named 'queries'. Use either queries above OR file upload, not both)
                                    </span>
                                  </label>
                                  <div className={styles.templateDownloadContainer}>
                                    <span
                                      onClick={(e) => {
                                        e.preventDefault();
                                        handleTemplateDownload();
                                      }}
                                      className={styles.templateDownloadLink}>
                                      Download template
                                    </span>
                                  </div>
                                </div>
                              </div>
                              <input
                                type="file"
                                id="uploaded_file"
                                name="uploaded_file"
                                ref={fileInputRef}
                                accept=".csv,.xlsx"
                                onChange={(e) => {
                                  handleInputChange(e);
                                  // Clear queries when file is uploaded
                                  if (e.target.files && e.target.files.length > 0) {
                                    setAddModeQueries([""]);
                                  }
                                }}
                                className={styles.fileInput}
                                disabled={!formData.model_name || hasNonEmptyQueries}
                                style={{ display: "none" }}
                                required
                              />
                              {!formData.uploaded_file ? (
                                <div
                                  className={[styles.fileUploadContainer, isDragging ? styles.dragging : "", !formData.model_name || hasNonEmptyQueries ? styles.disabled : ""]
                                    .filter(Boolean)
                                    .join(" ")}
                                  onDragEnter={formData.model_name && !hasNonEmptyQueries ? handleDragEnter : undefined}
                                  onDragLeave={formData.model_name && !hasNonEmptyQueries ? handleDragLeave : undefined}
                                  onDragOver={formData.model_name && !hasNonEmptyQueries ? handleDragOver : undefined}
                                  onDrop={(e) => {
                                    if (formData.model_name && !hasNonEmptyQueries) {
                                      handleDrop(e);
                                      // Clear queries when file is dropped
                                      setAddModeQueries([""]);
                                    }
                                  }}
                                  onClick={() => formData.model_name && !hasNonEmptyQueries && !formData.uploaded_file && fileInputRef.current && fileInputRef.current.click()}>
                                  <div className={styles.uploadPrompt}>
                                    <span>
                                      {isDragging ? "Drop file here" : hasNonEmptyQueries ? "Queries provided - file upload disabled" : "Click to upload or drag and drop"}
                                    </span>
                                    <span>
                                      <small>Supported Extensions csv & xlsx</small>
                                    </span>
                                  </div>
                                </div>
                              ) : (
                                <>
                                  <div className={styles.fileCard}>
                                    <div className={consistencyStyles.fileInfo}>
                                      <span className={styles.fileName}>{formData.uploaded_file.name}</span>
                                      <button type="button" onClick={handleRemoveFile} className={styles.removeFileButton} aria-label="Remove file">
                                        &times;
                                      </button>
                                    </div>
                                  </div>
                                  {/* Display queries from uploaded file */}
                                  {fileQueries.length > 0 && (
                                    <div style={{ marginTop: "12px" }}>
                                      <label className={styles.label} style={{ marginBottom: "8px", display: "block" }}>
                                        Queries from file ({fileQueries.length})
                                      </label>
                                      <div
                                        style={{
                                          maxHeight: "200px",
                                          overflowY: "auto",
                                          border: "1px solid #e0e0e0",
                                          borderRadius: "4px",
                                          padding: "8px",
                                          backgroundColor: "#f9f9f9",
                                        }}>
                                        {fileQueries.map((query, idx) => (
                                          <div
                                            key={idx}
                                            style={{
                                              padding: "6px 8px",
                                              marginBottom: "4px",
                                              backgroundColor: "#fff",
                                              borderRadius: "3px",
                                              border: "1px solid #e8e8e8",
                                              fontSize: "13px",
                                              color: "#333",
                                            }}>
                                            <span style={{ fontWeight: "500", color: "#666", marginRight: "8px" }}>{idx + 1}.</span>
                                            {query}
                                          </div>
                                        ))}
                                      </div>
                                    </div>
                                  )}
                                </>
                              )}
                            </div>
                          )}

                          {/* position: "sticky" */}
                          <div style={{ bottom: 0, left: 0, right: 0, background: "#fff", marginTop: "12px" }}>
                            {/* <div className={styles.buttonGroup}> */}
                            <button type="button" onClick={handleExecute} className="iafButton iafButtonPrimary" disabled={loading || !enableExecute}>
                              Execute
                            </button>
                            {downloadableResponse && (
                              <button type="button" onClick={handleDownload} className="iafButton iafButtonSecondary">
                                Download
                              </button>
                            )}
                            {/* </div> */}
                          </div>
                        </div>
                      </div>
                    </LeftNavPanel>
                  </div>
                  {/* --- Panel width/height logic for 3 panels --- */}
                  {(() => {
                    // Count how many panels are visible (excluding left nav)
                    let rightPanels = 0;
                    if (results) rightPanels++;
                    if (robustnessActive) rightPanels++;
                    // If there are exactly 2 right panels (total 3 including left nav), apply equal width/height
                    if (rightPanels === 2) {
                      return (
                        <>
                          {results && (
                            <div
                              style={{
                                flex: 1,
                                minWidth: 0,
                                minHeight: 0,
                                display: "flex",
                                flexDirection: "column",
                                alignItems: "stretch",
                                maxWidth: "50%",
                                position: "relative",
                              }}>
                              <div className="rightResult2" style={{ flex: 1, minHeight: 0, display: "flex", flexDirection: "column" }}>
                                <RightResultsPanel
                                  styles={styles}
                                  results={results}
                                  loading={loading}
                                  handleRerun={handleRerun}
                                  handleApprove={handleApprove}
                                  scrollCardsOnly={true}
                                />
                              </div>
                            </div>
                          )}
                          {robustnessActive && (
                            <div
                              style={{
                                flex: 1,
                                minWidth: 0,
                                minHeight: 0,
                                height: "80vh",
                                display: "flex",
                                flexDirection: "column",
                                alignItems: "stretch",
                                maxWidth: "50%",
                                position: "relative",
                              }}>
                              <div className="rightResult3" style={{ flex: 1, minHeight: 0, display: "flex", flexDirection: "column" }}>
                                <RightResultsPanel
                                  styles={styles}
                                  results={robustnessResults || { queries: [], responses: [], agentic_application_id: null }}
                                  loading={robustnessLoading}
                                  handleRerun={() => handleRobustnessRerun(robustnessResults?.agentic_application_id)}
                                  handleApprove={handleRobustnessApprove}
                                  scrollCardsOnly={true}
                                />
                              </div>
                            </div>
                          )}
                        </>
                      );
                    }
                    // Otherwise, use original layout
                    return (
                      <>
                        {results && (
                          <div
                            style={{ flex: 1, minWidth: 0, minHeight: 0, height: "80vh", display: "flex", flexDirection: "column", alignItems: "stretch", position: "relative" }}>
                            <div className="rightResult4" style={{ flex: 1, minHeight: 0, display: "flex", flexDirection: "column" }}>
                              <RightResultsPanel
                                styles={styles}
                                results={results}
                                loading={loading}
                                handleRerun={handleRerun}
                                handleApprove={handleApprove}
                                scrollCardsOnly={true}
                              />
                            </div>
                          </div>
                        )}
                        {robustnessActive && (
                          <div
                            style={{ flex: 1, minWidth: 0, minHeight: 0, height: "80vh", display: "flex", flexDirection: "column", alignItems: "stretch", position: "relative" }}>
                            <div className="rightResult5" style={{ flex: 1, minHeight: 0, display: "flex", flexDirection: "column" }}>
                              <RightResultsPanel
                                styles={styles}
                                results={robustnessResults || { queries: [], responses: [], agentic_application_id: null }}
                                loading={robustnessLoading}
                                handleRerun={() => handleRobustnessRerun(robustnessResults?.agentic_application_id)}
                                handleApprove={handleRobustnessApprove}
                                scrollCardsOnly={true}
                              />
                            </div>
                          </div>
                        )}
                      </>
                    );
                  })()}
                </div>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

export default ConsistencyTab;
