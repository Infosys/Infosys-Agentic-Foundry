import React, { useState,useEffect,useRef } from "react";
import styles from "./GroundTruth.module.css";
import { useMessage } from "../../Hooks/MessageContext";
import { APIs, agentTypes,BASE_URL } from "../../constant";
import useFetch from "../../Hooks/useAxios";
import Loader from "../commonComponents/Loader";

const GroundTruth = () => {
  const [formData, setFormData] = useState({
    model_name: "",
    agent_name: "",
    agent_type: "",
    agentic_application_id: "",
    session_id: "test_groundTruth",
    use_llm_grading: false,
    uploaded_file: null
  });
  const [loading, setLoading] = useState(false);
  const [models, setModels] = useState([]);
  const { addMessage,setShowPopup } = useMessage();
  const { fetchData } = useFetch();
  const [agentsListData, setAgentsListData] = useState([]);
  const [agentType, setAgentType] = useState(agentTypes[0].value);
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
        addMessage("Failed to fetch models","error");
        setModels([]);
      }
  };

  const fetchAgents = async () => {
    try {
        setLoading(true);
        const data = await fetchData(APIs.GET_AGENTS_BY_DETAILS);
        setAgentsListData(data);
      } catch (error) {
        addMessage("Failed to fetch agents","error");
      } finally {
        setLoading(false);
      }
  };

  useEffect(() => {
    if (!hasLoadedModelsOnce.current) {
      hasLoadedModelsOnce.current = true;
      fetchModels();
    }
    if(!hasLoadedAgentsOnce.current) {
      hasLoadedAgentsOnce.current = true;
      fetchAgents();
    }
  }, []);

  // Initialize filtered agent types
  useEffect(() => {
    setFilteredAgentTypes(agentTypes);
  }, []);

  // Initialize filtered models
  useEffect(() => {
    setFilteredModels(models);
  }, [models]);

  useEffect(() => {
      setFormData(prev => ({
        ...prev,
        agent_name: "",
      }));
      setAgentSearchTerm("");
      setSelectedAgentIndex(-1);
      
      if (!agentType) return;
      const tempList = agentsListData?.filter(
        (list) => list.agentic_application_type === agentType
      );
      setAgentListDropdown(tempList || []);
      setFilteredAgents(tempList || []);
    }, [agentType, agentsListData]);

  // Filter agents based on search term
  useEffect(() => {
    if (!agentSearchTerm) {
      setFilteredAgents(agentListDropdown);
    } else {
      const filtered = agentListDropdown.filter(agent =>
        agent.agentic_application_name.toLowerCase().includes(agentSearchTerm.toLowerCase())
      );
      setFilteredAgents(filtered);
    }
    setSelectedAgentIndex(-1); // Reset selection when filter changes
  }, [agentSearchTerm, agentListDropdown]);

  // Filter agent types based on search term
  useEffect(() => {
    if (!agentTypeSearchTerm) {
      setFilteredAgentTypes(agentTypes);
    } else {
      const filtered = agentTypes.filter(type =>
        type.label.toLowerCase().includes(agentTypeSearchTerm.toLowerCase())
      );
      setFilteredAgentTypes(filtered);
    }
    setSelectedAgentTypeIndex(-1); // Reset selection when filter changes
  }, [agentTypeSearchTerm]);

  // Filter models based on search term
  useEffect(() => {
    if (!modelSearchTerm) {
      setFilteredModels(models);
    } else {
      const filtered = models.filter(model =>
        model.label.toLowerCase().includes(modelSearchTerm.toLowerCase())
      );
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
    
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);



  const handleInputChange = (e) => {
    const { name, value, type, checked, files } = e.target;
    if (name === 'model_name') {
      if (value !== formData.model_name) {
        setFormData({
          model_name: value,
          agent_name: "",
          agent_type: "",
          use_llm_grading: false,
          uploaded_file: null
        });
        setAgentType(agentTypes[0].value);
        setAgentSearchTerm("");
        setIsAgentDropdownOpen(false);
        setSelectedAgentIndex(-1);
        const fileInput = document.getElementById('uploaded_file');
        if (fileInput) {
          fileInput.value = '';
        }
        return;
      }
    }
    if (type === 'file' && files.length > 0) {
      const file = files[0];
      
      if (validateFile(file)) {
        setFormData(prev => ({
          ...prev,
          [name]: file
        }));
        e.target.value = '';
      } else {
        e.target.value = '';
      }
    } else {
      setFormData(prev => ({
        ...prev,
        [name]: type === 'checkbox' ? checked : value
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

    const requiredFields = [
      { field: 'model_name', label: 'Model Name' },
      { field: 'agent_type', label: 'Agent Type' },
      { field: 'agent_name', label: 'Agent Name' },
      { field: 'uploaded_file', label: 'Uploaded File' },
    ];
    
    const missingFields = requiredFields
      .filter(({ field }) => !formData[field])
      .map(({ label }) => label);
      
    if (missingFields.length > 0) {
      addMessage(`Please fill in the following required fields: ${missingFields.join(', ')}`, "error");
      return;
    }
    
    setLoading(true);
    
    try {
      const selectedAgent = agentListDropdown.find(agent => agent.agentic_application_name === formData.agent_name);
      const agentic_application_id = selectedAgent ? selectedAgent.agentic_application_id : "";
      const agentDisplayName = selectedAgent ? selectedAgent.agentic_application_name : formData.agent_name;
      const url = new URL(`${BASE_URL}/upload-and-evaluate-json/`);
      url.searchParams.append('model_name', formData.model_name);
      url.searchParams.append('agent_type', formData.agent_type);
      url.searchParams.append('agent_name', agentDisplayName);
      url.searchParams.append('agentic_application_id', agentic_application_id);
      url.searchParams.append('session_id','test_groundTruth');
      url.searchParams.append('use_llm_grading', formData.use_llm_grading.toString());
      
      const finalUrl = url.toString().replace(/\+/g, '%20');
      const formDataToSend = new FormData();
      if (formData.uploaded_file) {
        if (!validateFile(formData.uploaded_file)) {
          setLoading(false);
          return;
        }
        formDataToSend.append('file', formData.uploaded_file, formData.uploaded_file.name);
      } else {
        setLoading(false);
        return;
      }

      const response = await fetch(finalUrl, {
        method: "POST",
        body: formDataToSend
      });

      if (response.ok) {
        let data;
        try {
          data = await response.json();
        } catch (e) {
          addMessage("Unexpected response format from server.", "error");
          setLoading(false);
          return;
        }
        addMessage(data.message || "Evaluation executed successfully!", "success");
        setEvaluationResults({
          averageScores: data.average_scores || null,
          diagnosticSummary: data.diagnostic_summary || "",
          message: data.message || "",
          fileName: null,
          showResults: true,
        });
        if (data.download_url) {
          const fileName = data.download_url.split('file_name=')[1];
          setDownloadableResponse({ url: data.download_url, fileName: fileName });
        }
      } else {
        addMessage(`Failed to execute evaluation: ${response.status} ${response.statusText}`, "error");
      }
    } catch (error) {
      addMessage(`Error: ${error.message}`, "error");
    } finally {
      setLoading(false);
    }
  };

  const validateFile = (file) => {
    if (!file) return false;
    
    // Check file extension
    const validExtensions = ['.csv', '.xlsx'];
    const fileName = file.name.toLowerCase();
    const isValidExtension = validExtensions.some(ext => fileName.endsWith(ext));
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
        setFormData(prev => ({
          ...prev,
          uploaded_file: file
        }));
      }
    }
  };
  const handleRemoveFile = () => {
    setFormData(prev => ({ ...prev, uploaded_file: null }));
    const fileInput = document.getElementById('uploaded_file');
    if (fileInput) fileInput.value = '';
  };
  
  const downloadFileFromResponse = async (response, fileName) => {
    try {
      const blob = await response.blob();
      const url = window.URL.createObjectURL(blob);
      
      const a = document.createElement('a');
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
        const a = document.createElement('a');
        a.href = downloadableResponse.url;
        a.download = downloadableResponse.fileName || 'download';
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
      } else if (downloadableResponse.response) {
        await downloadFileFromResponse(
          downloadableResponse.response.clone(),
          downloadableResponse.fileName || 'download'
        );
        addMessage(`File downloaded successfully`, "success");
      }
    } catch (error) {
      addMessage(`Error downloading file: ${error.message}`, "error");
    }
  };

  // Handle keyboard navigation for agent dropdown
  const handleAgentKeyDown = (e) => {
    if (!isAgentDropdownOpen) {
      if (e.key === 'ArrowDown') {
        setIsAgentDropdownOpen(true);
        setSelectedAgentIndex(0);
        e.preventDefault();
      }
      return;
    }

    switch (e.key) {
      case 'ArrowDown':
        e.preventDefault();
        setSelectedAgentIndex(prev => 
          prev < filteredAgents.length - 1 ? prev + 1 : 0
        );
        break;
      case 'ArrowUp':
        e.preventDefault();
        setSelectedAgentIndex(prev => 
          prev > 0 ? prev - 1 : filteredAgents.length - 1
        );
        break;
      case 'Enter':
        e.preventDefault();
        if (selectedAgentIndex >= 0 && selectedAgentIndex < filteredAgents.length) {
          const selectedAgent = filteredAgents[selectedAgentIndex];
          setFormData(prev => ({
            ...prev,
            agent_name: selectedAgent.agentic_application_name
          }));
          setAgentSearchTerm(selectedAgent.agentic_application_name);
          setIsAgentDropdownOpen(false);
          setSelectedAgentIndex(-1);
        }
        break;
      case 'Escape':
        setIsAgentDropdownOpen(false);
        setSelectedAgentIndex(-1);
        break;
    }
  };

  // Handle keyboard navigation for agent type dropdown
  const handleAgentTypeKeyDown = (e) => {
    if (!isAgentTypeDropdownOpen) {
      if (e.key === 'ArrowDown') {
        setIsAgentTypeDropdownOpen(true);
        setSelectedAgentTypeIndex(0);
        e.preventDefault();
      }
      return;
    }

    switch (e.key) {
      case 'ArrowDown':
        e.preventDefault();
        setSelectedAgentTypeIndex(prev => 
          prev < filteredAgentTypes.length - 1 ? prev + 1 : 0
        );
        break;
      case 'ArrowUp':
        e.preventDefault();
        setSelectedAgentTypeIndex(prev => 
          prev > 0 ? prev - 1 : filteredAgentTypes.length - 1
        );
        break;
      case 'Enter':
        e.preventDefault();
        if (selectedAgentTypeIndex >= 0 && selectedAgentTypeIndex < filteredAgentTypes.length) {
          const selectedAgentType = filteredAgentTypes[selectedAgentTypeIndex];
          setFormData(prev => ({
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
      case 'Escape':
        setIsAgentTypeDropdownOpen(false);
        setSelectedAgentTypeIndex(-1);
        break;
    }
  };

  // Handle keyboard navigation for model dropdown
  const handleModelKeyDown = (e) => {
    if (!isModelDropdownOpen) {
      if (e.key === 'ArrowDown') {
        setIsModelDropdownOpen(true);
        setSelectedModelIndex(0);
        e.preventDefault();
      }
      return;
    }

    switch (e.key) {
      case 'ArrowDown':
        e.preventDefault();
        setSelectedModelIndex(prev => 
          prev < filteredModels.length - 1 ? prev + 1 : 0
        );
        break;
      case 'ArrowUp':
        e.preventDefault();
        setSelectedModelIndex(prev => 
          prev > 0 ? prev - 1 : filteredModels.length - 1
        );
        break;
      case 'Enter':
        e.preventDefault();
        if (selectedModelIndex >= 0 && selectedModelIndex < filteredModels.length) {
          const selectedModel = filteredModels[selectedModelIndex];
          setFormData(prev => ({
            ...prev,
            model_name: selectedModel.value,
          }));
          setModelSearchTerm(selectedModel.label);
          setIsModelDropdownOpen(false);
          setSelectedModelIndex(-1);
        }
        break;
      case 'Escape':
        setIsModelDropdownOpen(false);
        setSelectedModelIndex(-1);
        break;
    }
  };

  return (
    <div className={styles.groundTruthWrapper}>
      <div className={styles.groundTruthContainer}>
        <div className={styles.header}>
          <h2 className={styles.title}>Ground Truth Evaluation</h2>
        </div>
        <form onSubmit={(e) => e.preventDefault()} className={styles.form}>
        <div className={styles.formRow}>
          <div className={styles.formGroup}>
            <div className={styles.labelWithButton}>
              <label htmlFor="model_name" className={styles.label}>
                Model Name <span className={styles.required}>*</span>
              </label>
            </div>
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
                        className={`${styles.dropdownItem} ${
                          formData.model_name === model.value 
                            ? styles.selected 
                            : ''
                        } ${
                          selectedModelIndex === index 
                            ? styles.highlighted 
                            : ''
                        }`}
                        onClick={() => {
                          setFormData(prev => ({
                            ...prev,
                            model_name: model.value,
                          }));
                          setModelSearchTerm(model.label);
                          setIsModelDropdownOpen(false);
                          setSelectedModelIndex(-1);
                        }}
                      >
                        {model.label}
                      </div>
                    ))
                  ) : (
                    <div className={styles.dropdownItem}>
                      {modelSearchTerm ? 'No models found' : 'Loading models...'}
                    </div>
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
                        className={`${styles.dropdownItem} ${
                          formData.agent_type === agentType.value 
                            ? styles.selected 
                            : ''
                        } ${
                          selectedAgentTypeIndex === index 
                            ? styles.highlighted 
                            : ''
                        }`}
                        onClick={() => {
                          setFormData(prev => ({
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
                        }}
                      >
                        {agentType.label}
                      </div>
                    ))
                  ) : (
                    <div className={styles.dropdownItem}>
                      {agentTypeSearchTerm ? 'No agent types found' : 'Select model first'}
                    </div>
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
                        className={`${styles.dropdownItem} ${
                          formData.agent_name === agent.agentic_application_name 
                            ? styles.selected 
                            : ''
                        } ${
                          selectedAgentIndex === index 
                            ? styles.highlighted 
                            : ''
                        }`}
                        onClick={() => {
                          setFormData(prev => ({
                            ...prev,
                            agent_name: agent.agentic_application_name
                          }));
                          setAgentSearchTerm(agent.agentic_application_name);
                          setIsAgentDropdownOpen(false);
                          setSelectedAgentIndex(-1);
                        }}
                      >
                        {agent.agentic_application_name}
                      </div>
                    ))
                  ) : (
                    <div className={styles.dropdownItem}>
                      {agentSearchTerm ? 'No agents found' : 'Select agent type first'}
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>
        </div>

        <div className={styles.formGroup}>
           <div className={styles.labelWithInfo}>
             <label htmlFor="uploaded_file" className={styles.label}>
               Upload File <span className={styles.required}>*</span> 
               <span className={styles.instructionText}>
                (File must exactly two columns: 'queries' and 'expected outputs'")
               </span>
             </label>
           </div>
           <input
             type="file"
             id="uploaded_file"
             name="uploaded_file"
             onChange={handleInputChange}
             className={styles.fileInput}
             accept=".csv,.xlsx"
             disabled={!formData.model_name}
             style={{ display: 'none' }}
             required
           />
           {!formData.uploaded_file ? (
             <div
               className={`${styles.fileUploadContainer} ${isDragging ? styles.dragging : ''} ${!formData.model_name ? styles.disabled : ''}`}
               onDragEnter={formData.model_name ? handleDragEnter : undefined}
               onDragLeave={formData.model_name ? handleDragLeave : undefined}
               onDragOver={formData.model_name ? handleDragOver : undefined}
               onDrop={formData.model_name ? handleDrop : undefined}
               onClick={() => formData.model_name && document.getElementById('uploaded_file').click()}
             >
               <div className={styles.uploadPrompt}>
                 <span>{isDragging ? "Drop file here" : "Click to upload or drag and drop"}</span>
                 <span><small>Supported Extensions csv & xlsx</small></span>
               </div>
             </div>
           ) : (
             <div className={styles.fileCard}>
               <div className={styles.fileInfo}>
                 <span className={styles.fileName}> {formData.uploaded_file.name}</span>
               <button
                 type="button"
                 onClick={handleRemoveFile}
                 className={styles.removeFileButton}
                 aria-label="Remove file"
               >&times;</button>
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
          <button
            type="button"
            onClick={handleExecute}
            className={styles.submitButton}
            disabled={loading || !enableExecute}
          >
            Execute
            {loading && <Loader/>}
          </button>
          {downloadableResponse && (
            <button
              type="button"
              onClick={handleDownload}
              className={styles.submitButton}
            >
              Download
            </button>
          )}
        </div>
      </form>

      {evaluationResults.showResults && (
        <div className={styles.evaluationResults}>
          {evaluationResults.diagnosticSummary && (
            <div className={styles.diagnosticSummary}>
              <h4>Diagnostic Summary</h4>
              <div style={{ maxHeight: '200px', overflowY: 'auto', background: '#f8f8f8', border: '1px solid #ccc', borderRadius: '4px', padding: '10px', fontFamily: 'monospace', fontSize: '14px' }}>
                  <pre style={{ margin: 0, whiteSpace: 'pre-wrap' }}>{evaluationResults.diagnosticSummary}</pre>
              </div>
            </div>
          )}
          {evaluationResults.averageScores && Object.keys(evaluationResults.averageScores).length > 0 && (
            <div className={styles.averageScores}>
              <h4>Average Scores</h4>
              <div className={styles.scoresGrid}>
                {Object.entries(evaluationResults.averageScores).map(([key, val]) => (
                  <div key={key} className={styles.scoreItem}>
                    <div className={styles.scoreLabel}>{key.replace(/_/g, ' ')}</div>
                    <div className={styles.scoreValue}>{(val * 100).toFixed(1)}%</div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
    </div>
  );
};

export default GroundTruth;