import React, { useState, useEffect, useRef } from "react";
import styles from "./GroundTruth.module.css";
import sliderStyles from "../commonComponents/ResourceSlider/ResourceSlider.module.css";
import { useMessage } from "../../Hooks/MessageContext";
import { APIs } from "../../constant";
import useFetch from "../../Hooks/useAxios";
import NewCommonDropdown from "../commonComponents/NewCommonDropdown";
import { getAgentTypeAbbreviation } from "../Pipeline/pipelineUtils";
import IAFButton from "../../iafComponents/GlobalComponents/Buttons/Button";
import UploadBox from "../commonComponents/UploadBox";
import SvgIcon from "../../Icons/SVGIcons";

const GroundTruth = () => {
  const [progressMessages, setProgressMessages] = useState([]);
  const [isStreaming, setIsStreaming] = useState(false);
  const hideStreamingTimeoutRef = useRef(null);
  const [isSliderCollapsed, setIsSliderCollapsed] = useState(false);
  const fileInputRef = useRef(null);

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
    use_llm_grading: false,
    uploaded_file: null,
  });
  const [loading, setLoading] = useState(false);
  const [templateDownloading, setTemplateDownloading] = useState(false);
  const [models, setModels] = useState([]);
  const { addMessage, setShowPopup } = useMessage();
  const { fetchData, postDataStream } = useFetch();
  const [agentsListData, setAgentsListData] = useState([]);
  const [agentTypeFilter, setAgentTypeFilter] = useState("all");
  const [agentListDropdown, setAgentListDropdown] = useState([]);
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
  const isExecuting = loading || isStreaming;

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

        // Auto-select default model for create screen
        if (data.default_model_name && !formData.model) {
          setFormData((prev) => ({ ...prev, model: data.default_model_name }));
        }
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

  // Update agent list when agent type filter changes
  useEffect(() => {
    if (!agentsListData || agentsListData.length === 0) {
      setAgentListDropdown([]);
      return;
    }
    if (agentTypeFilter === "all") {
      setAgentListDropdown(agentsListData);
    } else {
      const tempList = agentsListData.filter((list) => list.agentic_application_type === agentTypeFilter);
      setAgentListDropdown(tempList || []);
    }
  }, [agentTypeFilter, agentsListData]);

  // Get unique agent types for filter dropdown with proper { value, label } format
  const agentTypeFilterOptions = [
    { value: "all", label: "All" },
    ...[...new Set(agentsListData?.map((agent) => agent.agentic_application_type).filter(Boolean) || [])].map((type) => ({
      value: type,
      label: `${getAgentTypeAbbreviation(type)} - ${type.replace(/_/g, " ").replace(/\b\w/g, (l) => l.toUpperCase())}`,
    })),
  ];

  const handleInputChange = (e) => {
    const { name, type, checked, files } = e.target;
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
    } else if (type === "checkbox") {
      // Reset evaluation results for checkbox changes
      if (formData[name] !== checked) {
        resetEvaluationResults();
      }
      setFormData((prev) => ({
        ...prev,
        [name]: checked,
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
    // Don't set isStreaming to true immediately - wait for first progress message
    // setIsStreaming(true);
    setLoading(true); // Show loading state on button
    setIsSliderCollapsed(false); // Auto-expand panel when starting new evaluation

    const requiredFields = [
      { field: "model_name", label: "Model Name" },
      { field: "agent_type", label: "Agent Type" },
      { field: "agent_name", label: "Agent Name" },
      { field: "uploaded_file", label: "Uploaded File" },
    ];

    const missingFields = requiredFields.filter(({ field }) => !formData[field]).map(({ label }) => label);

    if (missingFields.length > 0) {
      addMessage(`Please fill in the following required fields: ${missingFields.join(", ")}`, "error");
      setLoading(false);
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
        `use_llm_grading=${encodeURIComponent(formData.use_llm_grading.toString())}`,
      ].join("&");
      const finalUrl = `${APIs.UPLOAD_AND_EVALUATE_JSON}?${params}`;
      const formDataToSend = new FormData();
      if (formData.uploaded_file) {
        if (!validateFile(formData.uploaded_file)) {
          return;
        }
        formDataToSend.append("file", formData.uploaded_file, formData.uploaded_file.name);
      } else {
        return;
      }

      let finalResultObj = null;
      let hasError = false;

      // Stream chunk handler for postDataStream
      const onStreamChunk = (obj) => {
        if (obj.error) {
          addMessage(obj.error, "error");
          setIsStreaming(false);
          setLoading(false);
          // Reset form and evaluation state so user can re-evaluate
          setFormData({
            model_name: "",
            agent_name: "",
            agent_type: "",
            use_llm_grading: false,
            uploaded_file: null,
          });
          setAgentTypeFilter("all");
          setProgressMessages([]);
          hasError = true;
          return;
        }
        if (obj.progress) {
          // Set streaming to true on first progress message to open the slider
          setIsStreaming(true);
          setLoading(false); // Stop button loading when slider opens
          setProgressMessages((prev) => [...prev, obj.progress]);
          if (obj.progress === "Evaluation completed successfully.") {
            setIsStreaming(false);
          }
        }
        if (obj.result) {
          finalResultObj = obj.result;
        }
      };

      // Use postDataStream from useAxios for consistent streaming with FormData
      await postDataStream(finalUrl, formDataToSend, {}, onStreamChunk);

      // After streaming, process the final result
      if (!hasError && finalResultObj) {
        const result = finalResultObj;
        addMessage(result.message || "Evaluation executed successfully!", "success");
        setEvaluationResults({
          averageScores: result.average_scores || null,
          diagnosticSummary: result.diagnostic_summary || "",
          message: result.message || "",
          fileName: null,
          showResults: true,
        });
        if (result.download_url) {
          const fileName = result.download_url.split("file_name=")[1];
          setDownloadableResponse({ url: result.download_url, fileName: fileName });
        }
      }
    } catch (error) {
      addMessage(`Error: ${error.message}`, "error");
      setIsStreaming(false);
      setLoading(false);
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
    if (fileInputRef.current) fileInputRef.current.value = "";
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
      setTemplateDownloading(true);
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
      setTemplateDownloading(false);
    }
  };

  return (
    <div className={styles.pageWrapper}>
      <div className={`${styles.container} ${styles.GroundTruthContainer}`}>
        <div>
          <form onSubmit={(e) => e.preventDefault()} className="form formContent">
            <div className="gridTwoCol">
              <div className="formGroup">
                <label htmlFor="model_name" className="label-desc">
                  Model Name <span className="required">*</span>
                </label>
                <NewCommonDropdown
                  options={models.map((model) => model.value)}
                  selected={formData.model_name}
                  onSelect={(value) => {
                    if (value !== formData.model_name) {
                      resetEvaluationResults();
                      setFormData((prev) => ({
                        ...prev,
                        model_name: value,
                      }));
                    }
                  }}
                  placeholder="Select Model"
                  showSearch={true}
                  width="100%"
                  disabled={isExecuting}
                />
              </div>

              <div className="formGroup">
                <label htmlFor="agent_name" className="label-desc">
                  Agent Name <span className="required">*</span>
                </label>
                <NewCommonDropdown
                  options={agentListDropdown.map((agent) => agent.agentic_application_name)}
                  optionMetadata={agentListDropdown.reduce((acc, agent) => {
                    const abbr = getAgentTypeAbbreviation(agent.agentic_application_type);
                    if (abbr) {
                      acc[agent.agentic_application_name] = abbr;
                    }
                    return acc;
                  }, {})}
                  selected={formData.agent_name}
                  onSelect={(value) => {
                    if (value !== formData.agent_name) {
                      resetEvaluationResults();
                      const selectedAgent = agentsListData.find((agent) => agent.agentic_application_name === value);
                      setFormData((prev) => ({
                        ...prev,
                        agent_name: value,
                        agent_type: selectedAgent?.agentic_application_type || "",
                      }));
                    }
                  }}
                  placeholder="Select Agent Name"
                  showSearch={true}
                  width="100%"
                  disabled={isExecuting}
                  showTypeFilter={true}
                  typeFilterOptions={agentTypeFilterOptions}
                  selectedTypeFilter={agentTypeFilter}
                  onTypeFilterChange={(filter) => {
                    setAgentTypeFilter(filter);
                    // Reset agent selection when filter changes
                    setFormData((prev) => ({
                      ...prev,
                      agent_name: "",
                      agent_type: "",
                    }));
                  }}
                />
              </div>
            </div>

            <div className="formGroup">
              <div style={{ width: "100%", display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
                <label htmlFor="uploaded_file" className="label-desc">
                  Upload File <span className="required">*</span>
                  <span className="instructionText"> (Only 'queries' and 'expected outputs' as columns")</span>
                </label>
                <div className={styles.templateDownloadContainer}>
                  <span
                    onClick={(e) => {
                      e.preventDefault();
                      if (!isExecuting && !templateDownloading) handleTemplateDownload();
                    }}
                    className={`${styles.templateDownloadLink} ${isExecuting || templateDownloading ? styles.templateDownloadDisabled : ""}`}>
                    {templateDownloading ? "Downloading..." : "Download template"}
                  </span>
                </div>
              </div>
              <input
                type="file"
                ref={fileInputRef}
                id="uploaded_file"
                name="uploaded_file"
                onChange={handleInputChange}
                className={styles.fileInput}
                accept=".csv,.xlsx"
                disabled={isStreaming}
                style={{
                  position: "absolute",
                  width: "1px",
                  height: "1px",
                  padding: 0,
                  margin: "-1px",
                  overflow: "hidden",
                  clip: "rect(0, 0, 0, 0)",
                  whiteSpace: "nowrap",
                  border: 0
                }}
                required
              />
              <UploadBox
                file={formData.uploaded_file}
                isDragging={isDragging}
                onDragEnter={handleDragEnter}
                onDragLeave={handleDragLeave}
                onDragOver={handleDragOver}
                onDrop={handleDrop}
                onClick={() => {
                  if (fileInputRef.current) {
                    fileInputRef.current.click();
                  }
                }}
                onRemoveFile={handleRemoveFile}
                loading={loading}
                fileInputId="uploaded_file"
                acceptedFileTypes=".csv,.xlsx"
                supportedText="Supported: .csv, .xlsx"
                disabled={isStreaming}
                disabledHint={isStreaming ? "File upload disabled during streaming" : ""}
              />
            </div>

            <div className="formGroup">
              <div className={styles.checkboxGroup}>
                <input
                  type="checkbox"
                  id="use_llm_grading"
                  name="use_llm_grading"
                  checked={formData.use_llm_grading}
                  onChange={handleInputChange}
                  className={styles.checkbox}
                  disabled={isStreaming}
                />
                <label htmlFor="use_llm_grading" className={styles.checkboxLabel}>
                  Use LLM Grading
                </label>
              </div>
            </div>

            <div className={styles.buttonContainer} style={{ marginTop: "-8px" }}>
              <IAFButton type="primary" onClick={handleExecute} disabled={loading || !enableExecute || isStreaming} loading={loading}>
                Execute
              </IAFButton>
            </div>
          </form>
        </div>
      </div>

      {/* Results Slider Panel - rendered outside container to avoid stacking context issues */}
      {(isStreaming || evaluationResults.showResults) && (
        <>
          {/* Backdrop - only show when expanded */}
          {!isSliderCollapsed && (
            <div
              className={`${sliderStyles.sliderBackdrop} ${sliderStyles.visible}`}
              onClick={() => {
                if (!isStreaming) {
                  resetEvaluationResults();
                  setIsSliderCollapsed(false);
                }
              }}
            />
          )}
          {/* Slider Panel - always visible, just transforms position */}
          <div
            className={`${sliderStyles.sliderOverlay} ${styles.evaluationSlider} ${isSliderCollapsed ? sliderStyles.collapsed : ""}`}
            role="dialog"
            aria-modal={!isSliderCollapsed}
            onClick={(e) => e.stopPropagation()}>
            {/* Collapse Toggle Button */}
            <button
              className={`${sliderStyles.sliderToggle} ${styles.evaluationToggle} ${isSliderCollapsed ? sliderStyles.toggleCollapsed : ""}`}
              onClick={() => setIsSliderCollapsed((prev) => !prev)}
              aria-label={isSliderCollapsed ? "Expand panel" : "Collapse panel"}
              title={isSliderCollapsed ? "Expand panel" : "Collapse panel"}>
              <SvgIcon icon="chevronRight" width={16} height={16} color="currentColor" />
            </button>

            {/* Slider Header */}
            <div className={sliderStyles.sliderHeader}>
              <h2 className={sliderStyles.sliderTitle}>{isStreaming ? "Evaluation Progress" : "Diagnostic Summary"}</h2>
              <button
                className="closeBtn"
                onClick={() => {
                  resetEvaluationResults();
                  setIsSliderCollapsed(false);
                }}
                aria-label="Close panel"
                title="Close">
                <SvgIcon icon="close-x" width={20} height={20} color="currentColor" />
              </button>
            </div>

            {/* Slider Content - Ground Truth specific content */}
            <div className={styles.evaluationContent}>
              {/* Streaming Progress Section */}
              {isStreaming && progressMessages.length > 0 && (
                <div className={styles.progressSection}>
                  <div className={styles.progressList}>
                    {progressMessages.map((msg, idx) => (
                      <div key={idx} className={styles.progressItem}>
                        <div className={styles.progressIndicator}>
                          <div className={styles.progressDot}>{idx + 1}</div>
                          {idx < progressMessages.length - 1 && <div className={styles.progressLine} />}
                        </div>
                        <div className={styles.progressContent}>
                          <div className={styles.progressStep}>{`Step ${idx + 1}`}</div>
                          <div className={styles.progressMessage}>{msg}</div>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Input Summary Card - Show when results are ready */}
              {evaluationResults.showResults && (
                <div className={styles.inputSummaryCard}>
                  <div className={styles.cardGrid}>
                    <div className={styles.cardItem}>
                      <span className={styles.cardLabel}>Model</span>
                      <span className={styles.cardValue}>{formData.model_name || "—"}</span>
                    </div>
                    <div className={styles.cardItem}>
                      <span className={styles.cardLabel}>Agent Type</span>
                      <span className={styles.cardValue}>{formData.agent_type || "—"}</span>
                    </div>
                    <div className={styles.cardItem}>
                      <span className={styles.cardLabel}>Agent Name</span>
                      <span className={styles.cardValue}>{formData.agent_name || "—"}</span>
                    </div>
                    <div className={styles.cardItem}>
                      <span className={styles.cardLabel}>File Uploaded</span>
                      <span className={styles.cardValue}>{formData.uploaded_file?.name || "—"}</span>
                    </div>
                    <div className={styles.cardItem}>
                      <span className={styles.cardLabel}>Use LLM Grading</span>
                      <span className={styles.cardValue}>{formData.use_llm_grading ? "Yes" : "No"}</span>
                    </div>
                  </div>
                </div>
              )}

              {/* Diagnostic Summary */}
              {evaluationResults.showResults && evaluationResults.diagnosticSummary && (
                <div className={styles.diagnosticSection}>
                  <h3 className={styles.sectionTitle}>Summary</h3>
                  <p className={styles.summaryText}>{evaluationResults.diagnosticSummary}</p>
                </div>
              )}

              {/* Average Scores */}
              {evaluationResults.showResults && evaluationResults.averageScores && Object.keys(evaluationResults.averageScores).length > 0 && (
                <div className={styles.scoresSection}>
                  <h3 className={styles.sectionTitle}>Average Scores</h3>
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

            {/* Slider Footer */}
            {evaluationResults.showResults && downloadableResponse && (
              <div className={sliderStyles.sliderFooter} style={{ flexDirection: "row", justifyContent: "flex-end" }}>
                <IAFButton type="primary" onClick={handleDownload}>
                  Download
                </IAFButton>
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
};

export default GroundTruth;
