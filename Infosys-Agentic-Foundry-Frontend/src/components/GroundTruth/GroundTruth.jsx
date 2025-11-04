import React, { useState, useEffect, useRef } from "react";
import styles from "./GroundTruth.module.css";
import { useMessage } from "../../Hooks/MessageContext";
import { APIs, agentTypesDropdown } from "../../constant";
import useFetch from "../../Hooks/useAxios";
import Loader from "../commonComponents/Loader";

const GroundTruth = ({ isInAdminScreen = false, isInDeveloperScreen = false }) => {
  const [progressMessages, setProgressMessages] = useState([]);
  const [isStreaming, setIsStreaming] = useState(false);
  const hideStreamingTimeoutRef = useRef(null);

  useEffect(() => {
    return () => {
      if (hideStreamingTimeoutRef.current) {
        clearTimeout(hideStreamingTimeoutRef.current);
        hideStreamingTimeoutRef.current = null;
      }
    };
  }, []);

  const [formData, setFormData] = useState({
    model_name: "",
    agent_name: "",
    agent_type: "",
    agentic_application_id: "",
    session_id: "test_groundTruth",
    use_llm_grading: false,
    uploaded_file: null,
  });
  const [loading, setLoading] = useState(false);
  const [models, setModels] = useState([]);
  const { addMessage, setShowPopup } = useMessage();
  const { fetchData, postData } = useFetch();
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
  const hasLoadedModelsOnce = useRef(false);
  const hasLoadedAgentsOnce = useRef(false);
  const [isDragging, setIsDragging] = useState(false);
  const [evaluationResults, setEvaluationResults] = useState({
    averageScores: null,
    diagnosticSummary: "",
    message: "",
    fileName: "",
    showResults: false,
  });
  const [downloadableResponse, setDownloadableResponse] = useState(null);
  const enableExecute = formData.model_name && formData.agent_type && formData.agent_name && formData.uploaded_file;

  // Function to reset evaluation results when any input changes
  const resetEvaluationResults = () => {
    setEvaluationResults({
      averageScores: null,
      diagnosticSummary: "",
      message: "",
      fileName: "",
      showResults: false,
    });
    setDownloadableResponse(null);
  };

  useEffect(() => {
    if (!loading) {
      setShowPopup(true);
    } else {
      setShowPopup(false);
    }
  }, [loading, setShowPopup]);

  const fetchModels = async () => {
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
    } catch (error) {
      addMessage("Failed to fetch models", "error");
      setModels([]);
    }
  };

  const fetchAgents = async () => {
    try {
      setLoading(true);
      const data = await fetchData(APIs.GET_AGENTS_BY_DETAILS);
      setAgentsListData(data);
    } catch (error) {
      addMessage("Failed to fetch agents", "error");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (!hasLoadedModelsOnce.current) {
      hasLoadedModelsOnce.current = true;
      fetchModels();
    }
    if (!hasLoadedAgentsOnce.current) {
      hasLoadedAgentsOnce.current = true;
      fetchAgents();
    }
  }, []);

  // Initialize filtered agent types
  useEffect(() => {
    setFilteredAgentTypes(agentTypesDropdown);
  }, []);

  // Initialize filtered models
  useEffect(() => {
    setFilteredModels(models);
  }, [models]);

  useEffect(() => {
    setFormData((prev) => ({
      ...prev,
      agent_name: "",
    }));
    setAgentSearchTerm("");
    setSelectedAgentIndex(-1);

    if (!agentType) return;
    const tempList = agentsListData?.filter((list) => list.agentic_application_type === agentType);
    setAgentListDropdown(tempList || []);
    setFilteredAgents(tempList || []);
  }, [agentType, agentsListData]);

  // Filter agents based on search term
  useEffect(() => {
    if (!agentSearchTerm) {
      setFilteredAgents(agentListDropdown);
    } else {
      const filtered = agentListDropdown.filter((agent) => agent.agentic_application_name.toLowerCase().includes(agentSearchTerm.toLowerCase()));
      setFilteredAgents(filtered);
    }
    setSelectedAgentIndex(-1); // Reset selection when filter changes
  }, [agentSearchTerm, agentListDropdown]);

  // Filter agent types based on search term
  useEffect(() => {
    if (!agentTypeSearchTerm) {
      setFilteredAgentTypes(agentTypesDropdown);
    } else {
      const filtered = agentTypesDropdown.filter((type) => type.label.toLowerCase().includes(agentTypeSearchTerm.toLowerCase()));
      setFilteredAgentTypes(filtered);
    }
    setSelectedAgentTypeIndex(-1); // Reset selection when filter changes
  }, [agentTypeSearchTerm]);

  // Filter models based on search term
  useEffect(() => {
    if (!modelSearchTerm) {
      setFilteredModels(models);
    } else {
      const filtered = models.filter((model) => model.label.toLowerCase().includes(modelSearchTerm.toLowerCase()));
      setFilteredModels(filtered);
    }
    setSelectedModelIndex(-1); // Reset selection when filter changes
  }, [modelSearchTerm, models]);

  // Close dropdown when clicking outside
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

  const handleInputChange = (e) => {
    const { name, value, type, checked, files } = e.target;
    if (name === "model_name") {
      if (value !== formData.model_name) {
        // Reset evaluation results when model changes
        resetEvaluationResults();
        setFormData({
          model_name: value,
          agent_name: "",
          agent_type: "",
          use_llm_grading: false,
          uploaded_file: null,
        });
        setAgentType(agentTypesDropdown[0].value);
        setAgentSearchTerm("");
        setIsAgentDropdownOpen(false);
        setSelectedAgentIndex(-1);
        const fileInput = document.getElementById("uploaded_file");
        if (fileInput) {
          fileInput.value = "";
        }
        return;
      }
    }
    if (type === "file" && files.length > 0) {
      const file = files[0];

      if (validateFile(file)) {
        // Reset evaluation results when file changes
        resetEvaluationResults();
        setFormData((prev) => ({
          ...prev,
          [name]: file,
        }));
        e.target.value = "";
      } else {
        e.target.value = "";
      }
    } else {
      // Reset evaluation results for other input changes (including use_llm_grading checkbox)
      if (formData[name] !== (type === "checkbox" ? checked : value)) {
        resetEvaluationResults();
      }
      setFormData((prev) => ({
        ...prev,
        [name]: type === "checkbox" ? checked : value,
      }));
    }
  };

  const handleExecute = async () => {
    setEvaluationResults({
      averageScores: null,
      diagnosticSummary: "",
      message: "",
      fileName: "",
      showResults: false,
    });
    setDownloadableResponse(null);
    setProgressMessages([]);
    setIsStreaming(true);

    const requiredFields = [
      { field: "model_name", label: "Model Name" },
      { field: "agent_type", label: "Agent Type" },
      { field: "agent_name", label: "Agent Name" },
      { field: "uploaded_file", label: "Uploaded File" },
    ];

    const missingFields = requiredFields.filter(({ field }) => !formData[field]).map(({ label }) => label);

    if (missingFields.length > 0) {
      addMessage(`Please fill in the following required fields: ${missingFields.join(", ")}`, "error");
      return;
    }

    try {
      const selectedAgent = agentListDropdown.find((agent) => agent.agentic_application_name === formData.agent_name);
      const agentic_application_id = selectedAgent ? selectedAgent.agentic_application_id : "";
      const agentDisplayName = selectedAgent ? selectedAgent.agentic_application_name : formData.agent_name;
      // Construct query params using encodeURIComponent for each value
      const params = [
        `model_name=${encodeURIComponent(formData.model_name)}`,
        `agent_type=${encodeURIComponent(formData.agent_type)}`,
        `agent_name=${encodeURIComponent(agentDisplayName)}`,
        `agentic_application_id=${encodeURIComponent(agentic_application_id)}`,
        `session_id=${encodeURIComponent("test_groundTruth")}`,
        `use_llm_grading=${encodeURIComponent(formData.use_llm_grading.toString())}`,
      ].join("&");
      const baseUrl = process.env.REACT_APP_BASE_URL || "";
      const finalUrl = `${baseUrl}${APIs.UPLOAD_AND_EVALUATE_JSON}/?${params}`;
      const formDataToSend = new FormData();
      if (formData.uploaded_file) {
        if (!validateFile(formData.uploaded_file)) {
          return;
        }
        formDataToSend.append("file", formData.uploaded_file, formData.uploaded_file.name);
      } else {
        return;
      }

      // Use fetch for streaming SSE
       // Get JWT token from cookies
      const getJwtToken = () => {
        const match = document.cookie.match(/(^|;)\s*jwt-token=([^;]*)/);
        return match ? decodeURIComponent(match[2]) : null;
      };
      const jwtToken = getJwtToken();
      // Use fetch directly for streaming
      const fetchResponse = await fetch(finalUrl, {
        method: 'POST',
        headers: {
          "Accept": "text/event-stream",
          ...(jwtToken ? { "Authorization": `Bearer ${jwtToken}` } : {})
        },
        credentials: "include",
        body: formDataToSend
      });
      if (!fetchResponse.body) {
        addMessage('Streaming not supported by backend.', 'error');
        setIsStreaming(false);
        return;
      }
      const reader = fetchResponse.body.getReader();
      const decoder = new TextDecoder();
      let receivedText = '';
      let done = false;
      let finalResultLine = '';
      while (!done) {
        const { value, done: streamDone } = await reader.read();
        done = streamDone;
        if (value) {
          const chunk = decoder.decode(value, { stream: true });
          receivedText += chunk;
          // Split by newlines and process each line
          const lines = receivedText.split('\n');
          // Keep last incomplete line in receivedText
          receivedText = lines.pop();
          for (const line of lines) {
            if (!line.trim()) continue;
            try {
              const obj = JSON.parse(line);
              if (obj.progress) {
                setProgressMessages(prev => [...prev, obj.progress]);
                if (obj.progress === 'Evaluation completed successfully.') {
                    setIsStreaming(false);
                }
              }
              if (obj.result) {
                finalResultLine = line;
              }
            } catch (e) {
              // Ignore parse errors for incomplete lines
            }
          }
        }
      }
      // After streaming, parse the final result
      if (finalResultLine) {
        try {
          const data = JSON.parse(finalResultLine);
          const result = data.result || {};
          addMessage(result.message || 'Evaluation executed successfully!', 'success');
          setEvaluationResults({
            averageScores: result.average_scores || null,
            diagnosticSummary: result.diagnostic_summary || '',
            message: result.message || '',
            fileName: null,
            showResults: true,
          });
          if (result.download_url) {
            const fileName = result.download_url.split('file_name=')[1];
            setDownloadableResponse({ url: result.download_url, fileName: fileName });
          }
        } catch (e) {
          addMessage('Failed to parse final result.', 'error');
        }
      }
    } catch (error) {
      addMessage(`Error: ${error.message}`, "error");
    }
  };

  const validateFile = (file) => {
    if (!file) return false;

    // Check file extension
    const validExtensions = [".csv", ".xlsx"];
    const fileName = file.name.toLowerCase();
    const isValidExtension = validExtensions.some((ext) => fileName.endsWith(ext));
    if (!isValidExtension) {
      addMessage(`Invalid file format. Please upload a .csv or .xlsx file.`, "error");
      return false;
    }

    return true;
  };

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

      if (validateFile(file)) {
        // Reset evaluation results when file is dropped
        resetEvaluationResults();
        setFormData((prev) => ({
          ...prev,
          uploaded_file: file,
        }));
      }
    }
  };
  const handleRemoveFile = () => {
    // Reset evaluation results when file is removed
    resetEvaluationResults();
    setFormData((prev) => ({ ...prev, uploaded_file: null }));
    const fileInput = document.getElementById("uploaded_file");
    if (fileInput) fileInput.value = "";
  };

  const downloadFileFromResponse = async (response, fileName) => {
    try {
      const blob = await response.blob();
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
    } catch (error) {
      throw new Error(`Download failed: ${error.message}`);
    }
  };

  const handleDownload = async () => {
    if (!downloadableResponse) {
      addMessage("No file is available for download", "error");
      return;
    }

    try {
      if (downloadableResponse.url) {
        const urlObj = new URL(downloadableResponse.url);
        const relativePath = urlObj.pathname + urlObj.search;
        const blob = await fetchData(relativePath, {
          responseType: "blob",
        });
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
      } else if (downloadableResponse.response) {
        await downloadFileFromResponse(downloadableResponse.response.clone(), downloadableResponse.fileName || "download");
        addMessage(`File downloaded successfully`, "success");
      }
    } catch (error) {
      addMessage(`Error downloading file: ${error.message}`, "error");
    }
  };

  const handleTemplateDownload = async () => {
    try {
      setLoading(true);
      const fileName = "Groundtruth_template.xlsx";
      const templateUrl = `${APIs.DOWNLOAD_TEMPLATE}?file_name=${encodeURIComponent(fileName)}`;

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

  // Handle keyboard navigation for agent dropdown
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
          // Reset evaluation results when agent name changes
          resetEvaluationResults();
          setFormData((prev) => ({
            ...prev,
            agent_name: selectedAgent.agentic_application_name,
          }));
          setAgentSearchTerm(selectedAgent.agentic_application_name);
          setIsAgentDropdownOpen(false);
          setSelectedAgentIndex(-1);
        }
        break;
      case "Escape":
        setIsAgentDropdownOpen(false);
        setSelectedAgentIndex(-1);
        break;
    }
  };

  // Handle keyboard navigation for agent type dropdown
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
          // Reset evaluation results when agent type changes
          resetEvaluationResults();
          setFormData((prev) => ({
            ...prev,
            agent_type: selectedAgentType.value,
            agent_name: "",
          }));
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

  // Handle keyboard navigation for model dropdown
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
          setFormData((prev) => ({
            ...prev,
            model_name: selectedModel.value,
          }));
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

  return (
    <div className={`${styles.container} ${styles.groundTruthContainter}`}>
      <div className="iafPageSubHeader">
        <h6>Ground Truth Evaluation</h6>
      </div>
      <div className="groundTruthFormAndResults" style={{ display: "flex" }}>
        <div
          style={{
            display: "flex",
            width: "100%",
            minWidth: "350px",
            height: "Calc(100vh - 100px)",
            overflowY: "auto",
            paddingTop: "8px",
            paddingLeft: "0",
            paddingRight: "8px",
            marginRight: "5px",
            flex: "1",
          }}>
          <form onSubmit={(e) => e.preventDefault()} className={styles.form}>
            <div className={styles.formRow} style={{ flexDirection: "column" }}>
              <div className={styles.formGroup}>
                <label htmlFor="model_name" className={styles.label}>
                  Model Name <span className={styles.required}>*</span>
                </label>
                <div className={styles.searchableDropdown} ref={modelDropdownRef}>
                  <input
                    type="text"
                    placeholder="select model"
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
                            className={`${styles.dropdownItem} ${formData.model_name === model.value ? styles.selected : ""} ${
                              selectedModelIndex === index ? styles.highlighted : ""
                            }`}
                            onClick={() => {
                              resetEvaluationResults();
                              setFormData((prev) => ({
                                ...prev,
                                model_name: model.value,
                              }));
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

              <div className={styles.formGroup}>
                <label htmlFor="agent_type" className={styles.label}>
                  Agent Type <span className={styles.required}>*</span>
                </label>
                <div className={styles.searchableDropdown} ref={agentTypeDropdownRef}>
                  <input
                    type="text"
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
                            className={`${styles.dropdownItem} ${formData.agent_type === agentType.value ? styles.selected : ""} ${
                              selectedAgentTypeIndex === index ? styles.highlighted : ""
                            }`}
                            onClick={() => {
                              // Reset evaluation results when agent type changes
                              resetEvaluationResults();
                              setFormData((prev) => ({
                                ...prev,
                                agent_type: agentType.value,
                                agent_name: "",
                              }));
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
                        <div className={styles.dropdownItem}>{"No agent types found"}</div>
                      )}
                    </div>
                  )}
                </div>
              </div>

              <div className={styles.formGroup}>
                <label htmlFor="agent_name" className={styles.label}>
                  Agent Name <span className={styles.required}>*</span>
                </label>
                <div className={styles.searchableDropdown} ref={agentDropdownRef}>
                  <input
                    type="text"
                    placeholder="select agent name"
                    value={agentSearchTerm}
                    onChange={(e) => {
                      setAgentSearchTerm(e.target.value);
                      setIsAgentDropdownOpen(true);
                      setSelectedAgentIndex(-1);
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
                            key={index}
                            className={`${styles.dropdownItem} ${formData.agent_name === agent.agentic_application_name ? styles.selected : ""} ${
                              selectedAgentIndex === index ? styles.highlighted : ""
                            }`}
                            onClick={() => {
                              // Reset evaluation results when agent name changes
                              resetEvaluationResults();
                              setFormData((prev) => ({
                                ...prev,
                                agent_name: agent.agentic_application_name,
                              }));
                              setAgentSearchTerm(agent.agentic_application_name);
                              setIsAgentDropdownOpen(false);
                              setSelectedAgentIndex(-1);
                            }}>
                            {agent.agentic_application_name}
                          </div>
                        ))
                      ) : (
                        <div className={styles.dropdownItem}>{"No agents found"}</div>
                      )}
                    </div>
                  )}
                </div>
              </div>
            </div>

            <div className={styles.formGroup}>
              <div className={styles.labelWithInfo}>
                <div style={{ width: "100%", display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
                  <label htmlFor="uploaded_file" className={styles.label}>
                    Upload File <span className={styles.required}>*</span>
                    <span className={styles.instructionText}> (Only 'queries' and 'expected outputs' as columns")</span>
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
                onChange={handleInputChange}
                className={styles.fileInput}
                accept=".csv,.xlsx"
                disabled={!formData.model_name}
                style={{ display: "none" }}
                required
              />
              {!formData.uploaded_file ? (
                <div
                  className={`${styles.fileUploadContainer} ${isDragging ? styles.dragging : ""} ${!formData.model_name ? styles.disabled : ""}`}
                  onDragEnter={formData.model_name ? handleDragEnter : undefined}
                  onDragLeave={formData.model_name ? handleDragLeave : undefined}
                  onDragOver={formData.model_name ? handleDragOver : undefined}
                  onDrop={formData.model_name ? handleDrop : undefined}
                  onClick={() => formData.model_name && document.getElementById("uploaded_file").click()}>
                  <div className={styles.uploadPrompt}>
                    <span>{isDragging ? "Drop file here" : "Click or drag and drop"}</span>
                    <span>
                      <small>Supported Extensions csv or xlsx</small>
                    </span>
                  </div>
                </div>
              ) : (
                <div className={styles.fileCard}>
                  <div className={styles.fileInfo}>
                    <span className={styles.fileName}> {formData.uploaded_file.name}</span>
                    <button type="button" onClick={handleRemoveFile} className={styles.removeFileButton} aria-label="Remove file">
                      &times;
                    </button>
                  </div>
                </div>
              )}
            </div>

            <div className={styles.formGroup}>
              <div className={styles.checkboxGroup}>
                <input
                  type="checkbox"
                  id="use_llm_grading"
                  name="use_llm_grading"
                  checked={formData.use_llm_grading}
                  onChange={handleInputChange}
                  className={styles.checkbox}
                  disabled={!formData.model_name}
                />
                <label htmlFor="use_llm_grading" className={styles.checkboxLabel}>
                  Use LLM Grading
                </label>
              </div>
            </div>

            <div className={styles.buttonGroup}>
              <button type="button" onClick={handleExecute} className="iafButton iafButtonPrimary" disabled={loading || !enableExecute || isStreaming}>
                Execute
                {loading && <Loader />}
              </button>
              {downloadableResponse && (
                <button type="button" onClick={handleDownload} className="iafButton iafButtonPrimary">
                  Download
                </button>
              )}
            </div>
          </form>

          {/* Streaming response section */}
          {isStreaming && (
            <div className={styles.evaluationResults}>
              <h4>Evaluation Progress</h4>
              <div style={{ padding: '16px 0' }}>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '5px' }}>
                  {progressMessages.map((msg, idx) => (
                    <div key={idx} style={{ display: 'flex', alignItems: 'flex-start' }}>
                      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', marginRight: '12px' }}>
                        <div style={{ width: 18, height: 18, borderRadius: '50%', background: '#007cc3', color: '#fff', display: 'flex', alignItems: 'center', justifyContent: 'center', fontWeight: 'bold', fontSize: 12 }}>{idx + 1}</div>
                        {idx < progressMessages.length - 1 && <div style={{ width: 2, height: 32, background: '#e0e7ff', margin: '0 auto' }} />}
                      </div>
                      <div style={{ background: '#f6f8fa', padding: '10px 16px', borderRadius: '8px', minWidth: 180 }}>
                        <div style={{ fontWeight: 600, color: '#222', marginBottom: 4 }}>{`Step ${idx + 1}`}</div>
                        <div style={{ color: '#555', fontSize: 14 }}>{msg}</div>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          )}
        </div>

        {/* Width was 700px */}
        {evaluationResults.showResults && (
          <div style={{ minWidth: "300px", width: "100%", overflowX: "auto", height: "Calc(100vh - 100px)", padding: "10px", borderLeft: "1px solid #e1e5e9" }}>
            <div className={styles.evaluationResults} style={{ padding: "10px" }}>
              {evaluationResults.diagnosticSummary && (
                <div className={styles.diagnosticSummary}>
                  <h4>Diagnostic Summary</h4>
                  <div
                    style={{
                      fontSize: "14px",
                    }}>
                    <pre style={{ margin: 0, whiteSpace: "pre-wrap" }}>{evaluationResults.diagnosticSummary}</pre>
                  </div>
                </div>
              )}
              {evaluationResults.averageScores && Object.keys(evaluationResults.averageScores).length > 0 && (
                <div className={styles.averageScores}>
                  <h4>Average Scores</h4>
                  <div className={styles.scoresGrid}>
                    {Object.entries(evaluationResults.averageScores).map(([key, val]) => (
                      <div key={key} className={styles.scoreItem}>
                        <div className={styles.scoreLabel}>{key.replace(/_/g, " ")}</div>
                        <div className={styles.scoreValue}>{(val * 100).toFixed(1)}%</div>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

export default GroundTruth;
