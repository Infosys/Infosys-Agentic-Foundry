import React, { useState, useRef, useEffect } from "react";
import styles from "./ImportModal.module.css";
import { Modal } from "../commonComponents/Modal";
import Loader from "../commonComponents/Loader";
import Button from "../../iafComponents/GlobalComponents/Buttons/Button";
import UploadBox from "../commonComponents/UploadBox";
import NewCommonDropdown from "../commonComponents/NewCommonDropdown";
import useFetch from "../../Hooks/useAxios";
import { APIs } from "../../constant";

/**
 * ImportModal - Unified modal for importing tools or servers from a zip file
 *
 * @param {Function} onClose - Callback to close the modal
 * @param {Function} onImport - Callback: tools → (zipFile, modelName), servers → (zipFile)
 * @param {boolean} loading - Whether the import request is in progress
 * @param {"tools"|"servers"} type - Determines title, description, and whether to show model dropdown
 */
const ImportModal = ({ onClose, onImport, loading = false, type = "tools" }) => {
  const isTools = type === "tools";
  const [zipFile, setZipFile] = useState(null);
  const [modelName, setModelName] = useState("");
  const [models, setModels] = useState([]);
  const [modelsLoading, setModelsLoading] = useState(false);
  const [isDragging, setIsDragging] = useState(false);
  const fileInputRef = useRef(null);
  const { fetchData } = useFetch();

  // Fetch models only for tools import
  useEffect(() => {
    if (!isTools) return;
    const fetchModels = async () => {
      setModelsLoading(true);
      try {
        const data = await fetchData(APIs.GET_MODELS);
        if (data?.models && Array.isArray(data.models)) {
          setModels(data.models);
          const defaultModel = data.default_model_name || (data.models.length > 0 ? data.models[0] : "");
          if (defaultModel) setModelName(defaultModel);
        }
      } catch {
        console.error("Failed to fetch models");
        setModels([]);
      } finally {
        setModelsLoading(false);
      }
    };
    fetchModels();
  }, [isTools]); // eslint-disable-line react-hooks/exhaustive-deps

  const handleSubmit = (e) => {
    e.preventDefault();
    if (!zipFile) return;
    isTools ? onImport(zipFile, modelName.trim()) : onImport(zipFile);
  };

  const validateFile = (file) => {
    if (!file) return false;
    return (
      file.name.toLowerCase().endsWith(".zip") ||
      file.type === "application/zip" ||
      file.type === "application/x-zip-compressed"
    );
  };

  const handleFileSelect = (file) => {
    if (validateFile(file)) setZipFile(file);
  };

  const handleDragEnter = (e) => { e.preventDefault(); e.stopPropagation(); setIsDragging(true); };
  const handleDragLeave = (e) => { e.preventDefault(); e.stopPropagation(); setIsDragging(false); };
  const handleDragOver = (e) => { e.preventDefault(); e.stopPropagation(); };

  const handleDrop = (e) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(false);
    const file = e.dataTransfer?.files?.[0];
    if (file) handleFileSelect(file);
  };

  const handleClick = () => fileInputRef.current?.click();

  const handleFileInputChange = (e) => {
    const file = e.target.files?.[0];
    if (file) handleFileSelect(file);
    e.target.value = "";
  };

  const handleRemoveFile = () => setZipFile(null);

  const title = isTools ? "Import Tools" : "Import Servers";
  const description = isTools
    ? "Upload a zip file exported from tools to import them into the system."
    : "Upload a zip file exported from servers to import them into the system.";
  const fileInputId = isTools ? "import-tools-zip" : "import-servers-zip";

  return (
    <Modal
      isOpen={true}
      onClose={onClose}
      size="md"
      ariaLabel={title}
      className={styles.importModal}
      showCloseButton={true}
      closeOnOverlayClick={!loading}
      closeOnEsc={!loading}
    >
      {loading && <Loader />}

      <div className={styles.modalHeader}>
        <h2 className={styles.modalTitle}>{title}</h2>
      </div>

      <form onSubmit={handleSubmit} className={styles.importForm}>
        <div className={styles.modalBody}>
          <p className={styles.modalInfo}>{description}</p>

          <div className="formGroup">
            <label className="label-desc">Zip File <span className="required">*</span></label>
            <UploadBox
              file={zipFile}
              isDragging={isDragging}
              onDragEnter={handleDragEnter}
              onDragLeave={handleDragLeave}
              onDragOver={handleDragOver}
              onDrop={handleDrop}
              onClick={handleClick}
              onRemoveFile={handleRemoveFile}
              loading={loading}
              fileInputId={fileInputId}
              acceptedFileTypes=".zip"
              supportedText="Supported: .zip"
              uploadText="Click to upload"
              dragDropText=" or drag and drop"
              disabled={loading}
            />
            <input
              ref={fileInputRef}
              type="file"
              id={fileInputId}
              accept=".zip,application/zip,application/x-zip-compressed"
              onChange={handleFileInputChange}
              style={{ display: "none" }}
            />
          </div>

          {isTools && (
            <div className="formGroup">
              <label className="label-desc">Model Name</label>
              <NewCommonDropdown
                options={models}
                selected={modelName}
                onSelect={(val) => setModelName(val)}
                placeholder={modelsLoading ? "Loading models..." : "Select Model"}
                showSearch={models.length > 5}
                disabled={loading || modelsLoading}
                selectFirstByDefault={true}
                width="100%"
              />
              <span className={styles.formHint}>
                LLM model used to generate tool descriptions during import
              </span>
            </div>
          )}
        </div>

        <div className={styles.modalFooter}>
          <Button type="secondary" onClick={onClose} disabled={loading}>
            Cancel
          </Button>
          <Button type="primary" htmlType="submit" disabled={loading || !zipFile} loading={loading}>
            Import
          </Button>
        </div>
      </form>
    </Modal>
  );
};

export default ImportModal;
