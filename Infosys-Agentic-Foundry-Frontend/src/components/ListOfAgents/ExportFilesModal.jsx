import React, { useState, useEffect } from "react";
import styles from "../../css_modules/ExportFilesModal.module.css";
import { APIs } from "../../constant";
import useFetch from "../../Hooks/useAxios";
import Loader from "../commonComponents/Loader";
import SearchInput from "../commonComponents/SearchInput";
import { useMessage } from "../../Hooks/MessageContext";

const ExportFilesModal = ({ onClose, selectedAgentIds, onExport }) => {
  const [fileStructure, setFileStructure] = useState([]);
  const [selectedFiles, setSelectedFiles] = useState([]);
  const [loading, setLoading] = useState(false);
  const [currentStep, setCurrentStep] = useState(1); // 1: File selection, 2: Configuration
  const [configData, setConfigData] = useState({
    AZURE_OPENAI_API_KEY: "",
    AZURE_ENDPOINT: "",
    OPENAI_API_VERSION: "",
    AZURE_OPENAI_API_KEY_GPT_5: "",
    AZURE_ENDPOINT_GPT_5: "",
    OPENAI_API_VERSION_GPT_5: "",
    GOOGLE_API_KEY: "",
    GOOGLE_GENAI_MODELS: "",
    DATABASE_URL: "",
    POSTGRESQL_HOST: "",
    POSTGRESQL_USER: "",
    POSTGRESQL_PASSWORD: "",
    POSTGRESQL_PORT: "",
    DATABASE: "",
    POSTGRESQL_DB_URL_PREFIX: "",
    POSTGRESQL_DATABASE_URL: "",
    CONNECTION_POOL_SIZE: "low",
    PHOENIX_SQL_DATABASE_URL: "",
    PHOENIX_COLLECTOR_ENDPOINT: "",
    PHOENIX_GRPC_PORT: "50051",
    REDIS_HOST: "",
    REDIS_PORT: "6379",
    REDIS_DB: "0",
    REDIS_PASSWORD: "",
    CACHE_EXPIRY_TIME: "600",
    ENABLE_CACHING: false,
    EXPORT_AND_DEPLOY: false
  });

  // Search functionality
  const [searchTerm, setSearchTerm] = useState("");
  const [filteredFiles, setFilteredFiles] = useState([]);

  
  const { fetchData } = useFetch();
  const { addMessage } = useMessage();

  const getAllFiles = (structure, basePath = "") => {
    let files = [];
    if (Array.isArray(structure)) {
      structure.forEach(item => {
        if (typeof item === "string") {
          files.push(basePath ? `${basePath}/${item}` : item);
        } else if (typeof item === "object" && item !== null) {
          Object.entries(item).forEach(([key, value]) => {
            const currentPath = basePath ? `${basePath}/${key}` : key;
            if (Array.isArray(value) || typeof value === "object") {
              files = files.concat(getAllFiles(value, currentPath));
            } else {
              files.push(currentPath);
            }
          });
        }
      });
    } else if (typeof structure === "object" && structure !== null) {
      Object.entries(structure).forEach(([key, value]) => {
        const currentPath = basePath ? `${basePath}/${key}` : key;
        if (Array.isArray(value) || typeof value === "object") {
          files = files.concat(getAllFiles(value, currentPath));
        } else {
          files.push(currentPath);
        }
      });
    }
    return files;
  };

  useEffect(() => {
    fetchFileStructure();
  }, []);

  // Filter files based on search term
  useEffect(() => {
    const allFiles = getAllFiles(fileStructure);
    if (!searchTerm.trim()) {
      setFilteredFiles(allFiles);
    } else {
      const filtered = allFiles.filter(filePath => 
        filePath.toLowerCase().includes(searchTerm.toLowerCase())
      );
      setFilteredFiles(filtered);
    }
  }, [fileStructure, searchTerm]);

  const fetchFileStructure = async () => {
    setLoading(true);
    try {
      const data = await fetchData(APIs.GET_ALLUPLOADFILELIST);
      setFileStructure(data?.user_uploads || []);
    } catch (error) {
      const errorMsg = error?.response?.data?.message || error?.message || "Failed to fetch file structure";
      addMessage(errorMsg, "error");
      console.error("Error fetching file structure:", error);
    } finally {
      setLoading(false);
    }
  };

  const handleFileSelect = (filePath) => {
    setSelectedFiles(prev => 
      prev.includes(filePath) 
        ? prev.filter(path => path !== filePath)
        : [...prev, filePath]
    );
  };

  const handleSearch = (searchValue) => {
    setSearchTerm(searchValue);
  };

  const clearSearch = () => {
    setSearchTerm("");
  };

  const handleSelectAll = () => {
    const allFiles = getAllFiles(fileStructure);
    if (selectedFiles.length === allFiles.length) {
      setSelectedFiles([]);
    } else {
      setSelectedFiles(allFiles);
    }
  };

  const renderFileList = () => {
    return filteredFiles.map((filePath, index) => {
      const fileName = filePath.split('/').pop();
      const folderPath = filePath.split('/').slice(0, -1).join('/');
      
      return (
        <div key={`${filePath}-${index}`} className={styles.fileItem}>
          <input
            type="checkbox"
            id={filePath}
            checked={selectedFiles.includes(filePath)}
            onChange={() => handleFileSelect(filePath)}
            className={styles.checkbox}
          />
          <label htmlFor={filePath} className={styles.fileLabel}>
              <span className={styles.fileName}>{fileName}</span>
          </label>
        </div>
      );
    });
  };

  const handleNext = (e) => {
    if (e) {
      e.preventDefault();
      e.stopPropagation();
    }
    setCurrentStep(2);
  };

  const handleBack = (e) => {
    if (e) {
      e.preventDefault();
      e.stopPropagation();
    }
    setCurrentStep(1);
  };

  const handleConfigChange = (field, value) => {
    setConfigData(prev => ({
      ...prev,
      [field]: value
    }));
  };

  const handleExport = () => {
    // Pass export_and_deploy as a separate argument for query param usage
    const { EXPORT_AND_DEPLOY, ...restConfig } = configData;
    onExport(selectedFiles, restConfig, EXPORT_AND_DEPLOY);
  };

  const renderConfigurationForm = () => {
    const configSections = [
      {
        title: "Azure OpenAI Configuration",
        fields: [
          { key: "AZURE_OPENAI_API_KEY", label: "Azure OpenAI API Key", type: "password" },
          { key: "AZURE_ENDPOINT", label: "Azure Endpoint", type: "text" },
          { key: "OPENAI_API_VERSION", label: "OpenAI API Version", type: "text" }
        ]
      },
      {
        title: "Azure OpenAI GPT-5 Configuration",
        fields: [
          { key: "AZURE_OPENAI_API_KEY_GPT_5", label: "Azure OpenAI API Key (GPT-5)", type: "password", optional: true },
          { key: "AZURE_ENDPOINT_GPT_5", label: "Azure Endpoint (GPT-5)", type: "text", optional: true },
          { key: "OPENAI_API_VERSION_GPT_5", label: "OpenAI API Version (GPT-5)", type: "text", optional: true }
        ]
      },
      {
        title: "Google Configuration",
        fields: [
          { key: "GOOGLE_API_KEY", label: "Google API Key", type: "password" ,optional: true},
          { key: "GOOGLE_GENAI_MODELS", label: "Google GenAI Models", type: "text" ,optional: true}
        ]
      },
      {
        title: "PostgreSQL Configuration",
        fields: [
          { key: "DATABASE_URL", label: "Database URL", type: "text" },
          { key: "POSTGRESQL_HOST", label: "PostgreSQL Host", type: "text" },
          { key: "POSTGRESQL_USER", label: "PostgreSQL User", type: "text" },
          { key: "POSTGRESQL_PASSWORD", label: "PostgreSQL Password", type: "password" },
          { key: "POSTGRESQL_PORT", label: "PostgreSQL Port", type: "text" },
          { key: "DATABASE", label: "Database", type: "text" },
          { key: "POSTGRESQL_DB_URL_PREFIX", label: "PostgreSQL DB URL Prefix", type: "text" },
          { key: "POSTGRESQL_DATABASE_URL", label: "PostgreSQL Database URL", type: "text" }
        ]
      },
      {
        title: "Phoenix Configuration",
        fields: [
          { key: "PHOENIX_SQL_DATABASE_URL", label: "Phoenix SQL Database URL", type: "text",optional: true },
          { key: "PHOENIX_COLLECTOR_ENDPOINT", label: "Phoenix Collector Endpoint", type: "text", optional: true },
          { key: "PHOENIX_GRPC_PORT", label: "Phoenix GRPC Port", type: "text",optional: true }
        ]
      },
      {
        title: "Redis Configuration",
        fields: [
          { key: "REDIS_HOST", label: "Redis Host", type: "text" },
          { key: "REDIS_PORT", label: "Redis Port", type: "number" },
          { key: "REDIS_DB", label: "Redis DB", type: "number" },
          { key: "REDIS_PASSWORD", label: "Redis Password", type: "password" },
          { key: "CACHE_EXPIRY_TIME", label: "Cache Expiry Time", type: "number" },
          { key: "ENABLE_CACHING", label: "Enable Caching", type: "checkbox" }
        ]
      },
      {
        title: "Other Configuration",
        fields: [
          { key: "CONNECTION_POOL_SIZE", label: "Connection Pool Size", type: "select", options: ["low", "medium", "high"] },
        ]
      },
      {
        title: "GitHub Configuration",
        fields: [
          { key: "EXPORT_AND_DEPLOY", label: " Export And Push To GitHub", type: "checkbox" }
        ]
      }
    ];

    return (
      <div className={styles.configurationForm}>
        {configSections.map((section, sectionIndex) => (
          <div key={sectionIndex} className={styles.configSection}>
            <h4 className={styles.sectionTitle}>{section.title}</h4>
            <div className={styles.fieldsGrid}>
              {section.fields.map((field) => (
                <div key={field.key} className={styles.fieldGroup}>
                  <label htmlFor={field.key} className={styles.fieldLabel}>
                    {field.label}
                    {field.type !== "checkbox" && !field.optional && <span className={styles.required}>*</span>}
                  </label>
                  {field.type === "select" ? (
                    <select
                      id={field.key}
                      value={configData[field.key]}
                      onChange={(e) => handleConfigChange(field.key, e.target.value)}
                      className={styles.fieldInput}
                      {...(field.optional ? {} : { required: true })}
                    >
                      <option value="">Select...</option>
                      {field.options && field.options.map((option) => (
                        <option key={option} value={option}>
                          {option}
                        </option>
                      ))}
                    </select>
                  ) : field.type === "checkbox" ? (
                    <input
                      type="checkbox"
                      id={field.key}
                      checked={configData[field.key]}
                      onChange={(e) => handleConfigChange(field.key, e.target.checked)}
                      className={styles.fieldCheckbox}
                    />
                  ) : (
                    <input
                      type={field.type}
                      id={field.key}
                      name={field.key}
                      value={configData[field.key]}
                      onChange={(e) => handleConfigChange(field.key, e.target.value)}
                      className={styles.fieldInput}
                      placeholder={`Enter ${field.label.toLowerCase()}`}
                      {...(field.optional ? {} : { required: true })}
                    />
                  )}
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
    );
  };

  const allFiles = getAllFiles(fileStructure);

  const handleOverlayClick = (e) => {
    if (e.target === e.currentTarget) {
      onClose();
    }
  };

  const handleFormSubmit = (e) => {
    e.preventDefault();
    
    // Only handle export on step 2 (configuration page)
    if (currentStep === 2) {
      handleExport();
    }
    
    return false;
  };

  const modalContent = (
    <div className={styles.modalOverlay} onClick={handleOverlayClick}>
      <div className={styles.modalContainer} onClick={(e) => e.stopPropagation()}>
        <form onSubmit={handleFormSubmit} className={styles.modalForm}>
        <div className={styles.modalHeader}>
          <h2 className={styles.modalTitle}>
            {currentStep === 1 ? "Export Files (1/2)" : "Export Configuration (2/2)"}
          </h2>
          <button 
            type="button"
            onClick={onClose} 
            className={styles.closeBtn}
          >
            ×
          </button>
        </div>
        
        <div className={styles.modalContent}>
            {currentStep === 1 ? (
            <>
              <div className={styles.filesListHeader}>
                <h4>FILES</h4>
                <div className={styles.headerControls}>
                  <div className={styles.selectAllContainer}>
                    <input
                      type="checkbox"
                      id="selectAll"
                      checked={selectedFiles.length === getAllFiles(fileStructure).length && getAllFiles(fileStructure).length > 0}
                      onChange={handleSelectAll}
                      className={styles.checkbox}
                    />
                    <label htmlFor="selectAll" className={styles.selectAllLabel}>
                      Select All ({getAllFiles(fileStructure).length} files)
                    </label>
                  </div>
                  <div className={styles.searchContainer}>
                    <SearchInput
                      inputProps={{
                        placeholder: "Search files..."
                      }}
                      handleSearch={handleSearch}
                      searchValue={searchTerm}
                      clearSearch={clearSearch}
                    />
                  </div>
                </div>
              </div>

              <div className={styles.fileStructureContainer}>
                {loading ? (
                  <div className={styles.loaderContainer}>
                    <Loader />
                  </div>
                ) : (
                  <div className={styles.fileStructure}>
                    {renderFileList()}
                  </div>
                )}
              </div>

                {searchTerm && (
                  <span className={styles.searchInfo}>
                    {" • "}Showing {filteredFiles.length} of {getAllFiles(fileStructure).length} files
                  </span>
                )}
            </>
          ) : (
            <>
              <div className={styles.configContainer}>
                {renderConfigurationForm()}
              </div>
            </>
          )}
        </div>

        <div className={styles.modalFooter}>
          {currentStep === 1 ? (
            <>
              <button 
                type="button"
                onClick={handleNext} 
                className={styles.nextButton}
              >
                NEXT
                </button>
                
                <button 
                type="button"
                onClick={onClose} 
                className={styles.cancelButton}
              >
                CANCEL
              </button>
            </>
          ) : (
                <>
                  
              <button 
                type="submit"
                className={styles.exportButton}
              >
                EXPORT {selectedAgentIds.length} AGENT(S)
                  </button>
                  
              <button 
                type="button"
                onClick={handleBack} 
                className={styles.backButton}
              >
                BACK
              </button>
            </>
          )}
        </div>
        </form>
      </div>
    </div>
  );

  return modalContent;
};

export default ExportFilesModal;
