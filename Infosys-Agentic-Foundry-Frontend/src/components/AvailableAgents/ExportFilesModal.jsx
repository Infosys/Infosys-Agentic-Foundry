import React, { useState, useEffect } from "react";
import styles from "../../css_modules/ExportFilesModal.module.css";
import { APIs } from "../../constant";
import useFetch from "../../Hooks/useAxios";
import Loader from "../commonComponents/Loader";
import { useMessage } from "../../Hooks/MessageContext";
import SVGIcons from "../../Icons/SVGIcons";
import IAFButton from "../../iafComponents/GlobalComponents/Buttons/Button";
import TextField from "../../iafComponents/GlobalComponents/TextField/TextField";
import CheckBox from "../../iafComponents/GlobalComponents/CheckBox/CheckBox";

const ExportFilesModal = ({ onClose, selectedAgentIds, onExport }) => {
  const [fileStructure, setFileStructure] = useState([]);
  const [selectedFiles, setSelectedFiles] = useState([]);
  const [loading, setLoading] = useState(false);
  const [currentStep, setCurrentStep] = useState(1); // 1: File selection, 2: Configuration
  const [configData, setConfigData] = useState({
    AZURE_OPENAI_API_KEY: "",
    AZURE_ENDPOINT: "",
    OPENAI_API_VERSION: "",
    AZURE_OPENAI_MODELS: "gpt-4o, gpt-4o-mini, gpt-4.1, gpt-35-turbo",
    AZURE_OPENAI_API_KEY_GPT_5: "",
    AZURE_ENDPOINT_GPT_5: "",
    OPENAI_API_VERSION_GPT_5: "",
    AZURE_OPENAI_GPT_5_MODELS: "",
    GOOGLE_API_KEY: "",
    GOOGLE_GENAI_MODELS: "",
    POSTGRESQL_HOST: "localhost",
    POSTGRESQL_USER: "postgres",
    POSTGRESQL_PASSWORD: "",
    POSTGRESQL_PORT: "5432",
    DATABASE: "",
    CONNECTION_POOL_SIZE: "low",
    PHOENIX_COLLECTOR_ENDPOINT: "",
    PHOENIX_GRPC_PORT: "50051",
    REDIS_HOST: "",
    REDIS_PORT: "",
    REDIS_DB: "",
    REDIS_PASSWORD: "",
    CACHE_EXPIRY_TIME: "",
    ENABLE_CACHING: false,
    EXPORT_AND_DEPLOY: false,
  });

  // Search functionality
  const [searchTerm, setSearchTerm] = useState("");
  const [filteredFiles, setFilteredFiles] = useState([]);

  const { fetchData } = useFetch();
  const { addMessage } = useMessage();

  const getAllFiles = (structure, basePath = "") => {
    let files = [];
    if (Array.isArray(structure)) {
      structure.forEach((item) => {
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
      const filtered = allFiles.filter((filePath) => filePath.toLowerCase().includes(searchTerm.toLowerCase()));
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
    setSelectedFiles((prev) => (prev.includes(filePath) ? prev.filter((path) => path !== filePath) : [...prev, filePath]));
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
      const fileName = filePath.split("/").pop();

      return (
        <div key={`${filePath}-${index}`} className={styles.fileItem} onClick={() => handleFileSelect(filePath)}>
          <CheckBox checked={selectedFiles.includes(filePath)} onChange={() => handleFileSelect(filePath)} label={fileName} />
          <label className={styles.fileLabel}>
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
    setConfigData((prev) => ({
      ...prev,
      [field]: value,
    }));
  };

  const handleExport = () => {
    // Pass export_and_deploy as a separate argument for query param usage
    const { EXPORT_AND_DEPLOY, REDIS_HOST, REDIS_PORT, REDIS_DB, REDIS_PASSWORD, CACHE_EXPIRY_TIME, ...restConfig } = configData;

    // Only include Redis config fields when caching is enabled
    const finalConfig = {
      ...restConfig,
      ENABLE_CACHING: configData.ENABLE_CACHING,
      ...(configData.ENABLE_CACHING && {
        REDIS_HOST,
        REDIS_PORT,
        REDIS_DB,
        REDIS_PASSWORD,
        CACHE_EXPIRY_TIME,
      }),
    };

    onExport(selectedFiles, finalConfig, EXPORT_AND_DEPLOY);
  };

  const renderConfigurationForm = () => {
    const configSections = [
      {
        title: "Azure OpenAI Configuration",
        fields: [
          { key: "AZURE_OPENAI_API_KEY", label: "Azure OpenAI API Key", type: "password" },
          { key: "AZURE_ENDPOINT", label: "Azure Endpoint", type: "text" },
          { key: "OPENAI_API_VERSION", label: "OpenAI API Version", type: "text" },
          { key: "AZURE_OPENAI_MODELS", label: "Azure OpenAI Models", type: "text" },
        ],
      },
      {
        title: "Azure OpenAI GPT-5 Configuration",
        fields: [
          { key: "AZURE_OPENAI_API_KEY_GPT_5", label: "Azure OpenAI API Key (GPT-5)", type: "password", optional: true },
          { key: "AZURE_ENDPOINT_GPT_5", label: "Azure Endpoint (GPT-5)", type: "text", optional: true },
          { key: "OPENAI_API_VERSION_GPT_5", label: "OpenAI API Version (GPT-5)", type: "text", optional: true },
          { key: "AZURE_OPENAI_GPT_5_MODELS", label: "Azure OpenAI GPT-5 Models", type: "text", optional: true },
        ],
      },
      {
        title: "Google Configuration",
        fields: [
          { key: "GOOGLE_API_KEY", label: "Google API Key", type: "password", optional: true },
          { key: "GOOGLE_GENAI_MODELS", label: "Google GenAI Models", type: "text", optional: true },
        ],
      },
      {
        title: "PostgreSQL Configuration",
        fields: [
          { key: "POSTGRESQL_HOST", label: "PostgreSQL Host", type: "text" },
          { key: "POSTGRESQL_USER", label: "PostgreSQL User", type: "text" },
          { key: "POSTGRESQL_PASSWORD", label: "PostgreSQL Password", type: "password" },
          { key: "POSTGRESQL_PORT", label: "PostgreSQL Port", type: "text" },
          { key: "DATABASE", label: "Database", type: "text" },
        ],
      },
      {
        title: "Phoenix Configuration",
        fields: [
          { key: "PHOENIX_COLLECTOR_ENDPOINT", label: "Phoenix Collector Endpoint", type: "text", optional: true },
          { key: "PHOENIX_GRPC_PORT", label: "Phoenix GRPC Port", type: "text", optional: true },
        ],
      },
      {
        title: "Redis Configuration",
        fields: [
          { key: "ENABLE_CACHING", label: "Caching", checkboxLabel: "Enable", type: "checkbox" },
          { key: "REDIS_HOST", label: "Redis Host", type: "text", conditionalOn: "ENABLE_CACHING" },
          { key: "REDIS_PORT", label: "Redis Port", type: "number", conditionalOn: "ENABLE_CACHING" },
          { key: "REDIS_DB", label: "Redis DB", type: "number", conditionalOn: "ENABLE_CACHING" },
          { key: "REDIS_PASSWORD", label: "Redis Password", type: "password", conditionalOn: "ENABLE_CACHING" },
          { key: "CACHE_EXPIRY_TIME", label: "Cache Expiry Time", type: "number", conditionalOn: "ENABLE_CACHING" },
        ],
      },
      {
        title: "Other Configuration",
        fields: [{ key: "CONNECTION_POOL_SIZE", label: "Connection Pool Size", type: "select", options: ["low", "medium", "high"] }],
      },
      {
        title: "GitHub Configuration",
        fields: [{ key: "EXPORT_AND_DEPLOY", label: "GitHub", checkboxLabel: "Export and Push", type: "checkbox" }],
      },
    ];

    return (
      <div className={styles.configurationForm}>
        {configSections.map((section, sectionIndex) => (
          <div key={sectionIndex} className={styles.configSection}>
            <h4 className={styles.sectionTitle}>{section.title}</h4>
            <div className={styles.fieldsGrid}>
              {section.fields.map((field) => {
                // Skip rendering if field has conditionalOn and that condition is not met
                if (field.conditionalOn && !configData[field.conditionalOn]) {
                  return null;
                }
                return (
                  <div key={field.key} className={styles.fieldGroup}>
                    {field.type === "checkbox" ? (
                      <>
                        <label className={styles.fieldLabel}>{field.label}</label>
                        <div className={styles.fieldCheckboxWrapper}>
                          <CheckBox checked={configData[field.key]} onChange={(checked) => handleConfigChange(field.key, checked)} />
                          <span className={styles.checkboxText}>{field.checkboxLabel || field.label}</span>
                        </div>
                      </>
                    ) : (
                      <>
                        <label htmlFor={field.key} className={styles.fieldLabel}>
                          {field.label}
                          {!field.optional && <span className={styles.required}>*</span>}
                        </label>
                        {field.type === "select" ? (
                          <select
                            id={field.key}
                            value={configData[field.key]}
                            onChange={(e) => handleConfigChange(field.key, e.target.value)}
                            className={styles.fieldInput}
                            {...(field.optional ? {} : { required: true })}>
                            <option value="">Select...</option>
                            {field.options &&
                              field.options.map((option) => (
                                <option key={option} value={option}>
                                  {option}
                                </option>
                              ))}
                          </select>
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
                      </>
                    )}
                  </div>
                );
              })}
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

  // Render step indicator for header
  const renderStepIndicator = () => (
    <div className={styles.stepIndicator}>
      <span className={`${styles.stepBadge} ${currentStep >= 1 ? styles.active : ""} ${currentStep > 1 ? styles.completed : ""}`}>{currentStep > 1 ? "✓" : "1"}</span>
      <span className={`${styles.stepLabel} ${currentStep === 1 ? styles.active : ""}`}>Files</span>
      <span className={styles.stepDivider} />
      <span className={`${styles.stepBadge} ${currentStep === 2 ? styles.active : ""}`}>2</span>
      <span className={`${styles.stepLabel} ${currentStep === 2 ? styles.active : ""}`}>Config</span>
    </div>
  );

  const modalContent = (
    <div className={styles.modalOverlay} onClick={handleOverlayClick}>
      <div className={styles.modalContainer} onClick={(e) => e.stopPropagation()}>
        <form onSubmit={handleFormSubmit} className={styles.modalForm}>
          {/* Modal Header */}
          <div className={styles.modalHeader}>
            <div className={styles.modalHeaderLeft}>
              <h2 className={styles.modalTitle}>Export Files</h2>
              {renderStepIndicator()}
            </div>
            <button type="button" className={styles.modalCloseBtn} onClick={onClose} aria-label="Close modal">
              <SVGIcons icon="x" width={20} height={20} color="var(--text-primary)" />
            </button>
          </div>

          {/* Modal Content */}
          <div className={styles.modalContent}>
            {currentStep === 1 ? (
              <div className={styles.fileSelectionContainer}>
                <div className={styles.filesListHeader}>
                  <h4>Select Files to Export</h4>
                  <div className={styles.headerControls}>
                    <div className={styles.selectAllContainer}>
                      <CheckBox
                        checked={selectedFiles.length === getAllFiles(fileStructure).length && getAllFiles(fileStructure).length > 0}
                        onChange={handleSelectAll}
                        label="Select All"
                      />
                      <label className={styles.selectAllLabel} onClick={handleSelectAll}>
                        Select All ({getAllFiles(fileStructure).length})
                      </label>
                    </div>
                    <div className={styles.searchFieldWrapper}>
                      <TextField
                        placeholder="Search Files..."
                        value={searchTerm}
                        onChange={(e) => handleSearch(e.target.value)}
                        onClear={clearSearch}
                        showClearButton={true}
                        showSearchButton={true}
                        aria-label="Search Files"
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
                    <div className={styles.fileStructure}>{renderFileList()}</div>
                  )}
                </div>

                {searchTerm && (
                  <span className={styles.searchInfo}>
                    Showing {filteredFiles.length} of {getAllFiles(fileStructure).length} files
                  </span>
                )}
              </div>
            ) : (
              <div className={styles.configContainer}>{renderConfigurationForm()}</div>
            )}
          </div>

          {/* Modal Footer */}
          <div className={styles.modalFooter}>
            {currentStep === 1 ? (
              <>
                <IAFButton type="secondary" onClick={onClose} aria-label="Cancel">
                  Cancel
                </IAFButton>
                <IAFButton type="primary" onClick={handleNext} aria-label="Next">
                  Next
                </IAFButton>
              </>
            ) : (
              <>
                <IAFButton type="secondary" onClick={handleBack} aria-label="Back">
                  Back
                </IAFButton>
                <IAFButton type="primary" htmlType="submit" aria-label="Export">
                  Export {selectedAgentIds.length} Agent(s)
                </IAFButton>
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
