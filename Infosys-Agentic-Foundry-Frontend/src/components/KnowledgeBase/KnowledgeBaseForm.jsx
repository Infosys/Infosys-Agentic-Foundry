import React, { useState, useRef, useMemo, useEffect } from "react";
import { FullModal } from "../../iafComponents/GlobalComponents/FullModal";
import IAFButton from "../../iafComponents/GlobalComponents/Buttons/Button";
import UploadBox from "../commonComponents/UploadBox";
import SVGIcons from "../../Icons/SVGIcons";
import { useMessage } from "../../Hooks/MessageContext";
import { useErrorHandler } from "../../Hooks/useErrorHandler";
import useFetch from "../../Hooks/useAxios.js";
import { APIs } from "../../constant";
import Cookies from "js-cookie";
import styles from "./KnowledgeBaseForm.module.css";
import { formatDateTimeWithTimezone } from "../../utils/timeFormatter";
import Toggle from "../commonComponents/Toggle";
import NewCommonDropdown from "../commonComponents/NewCommonDropdown";
import { useKnowledgeBaseService } from "../../services/knowledgeBaseService";
import DepartmentSelector from "../commonComponents/DepartmentSelector/DepartmentSelector";

/**
 * KnowledgeBaseForm - Unified component for Create and Update Knowledge Base operations
 * Uses global CSS classes from index.css for form layouts
 *
 * @param {Object} props
 * @param {"create" | "update"} props.mode - Form mode: "create" or "update"
 * @param {Object} props.kbData - Knowledge base data for update mode (optional for create)
 * @param {Function} props.onClose - Callback to close the modal
 * @param {Function} props.onSave - Callback after successful save
 */
const KnowledgeBaseForm = ({ mode = "create", kbData = null, onClose, onSave }) => {
  const isCreateMode = mode === "create";
  const loggedInUserEmail = Cookies.get("email");
  const userName = Cookies.get("userName");
  const loggedInDepartment = Cookies.get("department") || "";

  const { addMessage } = useMessage();
  const { handleApiError, handleApiSuccess } = useErrorHandler();
  const { postData, fetchData } = useFetch();
  const { updateKnowledgeBaseSharing } = useKnowledgeBaseService();
  const fileInputRef = useRef(null);

  const [formData, setFormData] = useState({
    name: kbData?.name || "",
  });
  const [files, setFiles] = useState([]);
  const [existingDocuments, setExistingDocuments] = useState(kbData?.documents || []);
  const [removedDocuments, setRemovedDocuments] = useState([]);
  const [loading, setLoading] = useState(false);
  const [isDragging, setIsDragging] = useState(false);

  // ============ Is Public & Shared Departments State ============
  const [isPublic, setIsPublic] = useState(kbData?.is_public || false);
  const [sharedDepartments, setSharedDepartments] = useState(kbData?.shared_with_departments || []);
  const [departmentsList, setDepartmentsList] = useState([]);
  const [departmentsLoading, setDepartmentsLoading] = useState(false);

  // ============ Fetch Departments List ============
  useEffect(() => {
    const fetchDepartments = async () => {
      setDepartmentsLoading(true);
      try {
        const response = await fetchData(APIs.GET_DEPARTMENTS_LIST);
        if (response && Array.isArray(response)) {
          setDepartmentsList(response.map((dept) => dept.department_name || dept.name || dept));
        } else if (response?.departments && Array.isArray(response.departments)) {
          setDepartmentsList(response.departments.map((dept) => dept.department_name || dept.name || dept));
        } else {
          setDepartmentsList([]);
        }
      } catch (err) {
        console.error("Failed to fetch departments", err);
        setDepartmentsList([]);
      } finally {
        setDepartmentsLoading(false);
      }
    };
    fetchDepartments();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Check if form is valid for submission (used for button disabled state)
  const isFormValid = useMemo(() => {
    const hasName = formData.name.trim().length > 0;
    const hasDocuments = isCreateMode
      ? files.length > 0
      : (files.length > 0 || existingDocuments.length > 0);
    return hasName && hasDocuments;
  }, [formData.name, files.length, existingDocuments.length, isCreateMode]);

  const validateForm = () => {
    if (!formData.name.trim()) {
      addMessage("Knowledge Base name is required", "error");
      return false;
    }
    if (isCreateMode && files.length === 0) {
      addMessage("Please upload at least one document", "error");
      return false;
    }
    if (!isCreateMode && files.length === 0 && existingDocuments.length === 0) {
      addMessage("Knowledge Base must have at least one document", "error");
      return false;
    }
    return true;
  };

  const handleInputChange = (e) => {
    const { name, value } = e.target;
    setFormData((prev) => ({ ...prev, [name]: value }));
  };

  // File upload handlers
  const handleDragEnter = (e) => { e.preventDefault(); setIsDragging(true); };
  const handleDragLeave = (e) => { e.preventDefault(); setIsDragging(false); };
  const handleDragOver = (e) => { e.preventDefault(); };

  const handleDrop = (e) => {
    e.preventDefault();
    setIsDragging(false);
    const droppedFiles = Array.from(e.dataTransfer.files);
    handleFilesAdded(droppedFiles);
  };

  const handleFilesAdded = (newFiles) => {
    const validExtensions = [".pdf", ".txt", ".md", ".doc", ".docx"];
    const validFiles = newFiles.filter((file) =>
      validExtensions.some((ext) => file.name.toLowerCase().endsWith(ext))
    );

    if (validFiles.length !== newFiles.length) {
      addMessage("Some files were skipped. Only PDF, TXT, MD, DOC, DOCX files are allowed.", "error");
    }

    setFiles((prev) => [...prev, ...validFiles]);
  };

  const handleFileInputChange = (e) => {
    const selectedFiles = Array.from(e.target.files);
    handleFilesAdded(selectedFiles);
    e.target.value = ""; // Reset input
  };

  const handleRemoveFile = (index) => {
    setFiles((prev) => prev.filter((_, i) => i !== index));
  };

  const handleRemoveExistingDocument = (index) => {
    const removedDoc = existingDocuments[index];
    setExistingDocuments((prev) => prev.filter((_, i) => i !== index));
    setRemovedDocuments((prev) => [...prev, removedDoc]);
  };

  const handleUploadClick = () => {
    fileInputRef.current?.click();
  };

  const handleSubmit = async () => {
    if (!validateForm()) return;

    // Additional check to ensure files array is not empty for create mode (issue #3)
    if (isCreateMode && files.length === 0) {
      addMessage("Please upload at least one document", "error");
      return;
    }

    setLoading(true);
    try {
      // ============ Handle Sharing Update (Update Mode) ============
      // In update mode, use the dedicated PUT /utility/knowledge-base/{kb_id}/sharing endpoint
      if (!isCreateMode && kbData?.kb_id) {
        try {
          await updateKnowledgeBaseSharing(kbData.kb_id, isPublic, sharedDepartments);
        } catch (sharingError) {
          handleApiError(sharingError, { context: "KnowledgeBaseForm.updateSharing" });
          setLoading(false);
          return;
        }
      }

      // ============ Update Mode: No new files → sharing-only update is done ============
      if (!isCreateMode && files.length === 0) {
        handleApiSuccess(null, {
          fallbackMessage: `Knowledge Base "${kbData?.name || formData.name}" sharing settings updated successfully`,
        });

        if (onSave) {
          onSave({
            kb_id: kbData?.kb_id,
            name: kbData?.name || formData.name,
            documents: existingDocuments,
            created_by: kbData?.created_by || loggedInUserEmail,
            created_on: kbData?.created_on || new Date().toISOString(),
            is_public: isPublic,
            shared_with_departments: isPublic ? [] : sharedDepartments,
          });
        }

        onClose();
        return;
      }

      // ============ Build FormData for document upload ============
      const uploadFormData = new FormData();
      uploadFormData.append("session_id", `session_${Date.now()}`);
      uploadFormData.append("kb_name", formData.name.trim());
      uploadFormData.append("user_email", loggedInUserEmail);

      // Add is_public and shared_with_departments for access control (create mode)
      uploadFormData.append("is_public", isPublic);
      if (!isPublic && sharedDepartments.length > 0) {
        sharedDepartments.forEach((dept) => uploadFormData.append("shared_with_departments", dept));
      }

      // For update mode, include KB ID and removed documents if available
      if (!isCreateMode && kbData?.kb_id) {
        uploadFormData.append("kb_id", kbData.kb_id);
        if (removedDocuments.length > 0) {
          uploadFormData.append("removed_documents", JSON.stringify(removedDocuments));
        }
      }

      // Append all files
      files.forEach((file) => {
        uploadFormData.append("files", file);
      });

      const response = await postData(APIs.KB_UPLOAD_DOCUMENTS, uploadFormData, {
        headers: { "Content-Type": "multipart/form-data" },
      });

      // Validate response structure
      if (!response || typeof response !== "object") {
        throw new Error("Invalid response format from server");
      }

      // Check upload results for any failures
      const uploadResults = response?.upload_results || [];
      const failedUploads = uploadResults.filter((r) => r.status === "failed");

      if (failedUploads.length > 0) {
        const failedNames = failedUploads.map((f) => f.filename).join(", ");
        addMessage(`Some files failed to upload: ${failedNames}`, "error");
      } else {
        const operationType = response?.is_new ? "created" : "updated";
        const kbName = response?.kb_name || formData.name;
        handleApiSuccess(response, {
          fallbackMessage: `Knowledge Base "${kbName}" ${operationType} successfully`,
        });
      }

      if (onSave) {
        onSave({
          kb_id: response?.kb_id || kbData?.kb_id,
          name: response?.kb_name || formData.name,
          documents: [...existingDocuments, ...files.map((f) => f.name)],
          created_by: response?.created_by || loggedInUserEmail,
          created_on: response?.created_on || kbData?.created_on || new Date().toISOString(),
          is_public: isPublic,
          shared_with_departments: isPublic ? [] : sharedDepartments,
        });
      }

      onClose();
    } catch (error) {
      handleApiError(error, {
        context: "KnowledgeBaseForm.handleSubmit",
        customMessage: null, // let handleApiError extract backend detail/message automatically
      });
    } finally {
      setLoading(false);
    }
  };

  const footer = (
    <div className={styles.footerContainer}>
      {/* Left side: Access Control Toggle */}
      <div className={styles.footerToggleItem}>
        <Toggle
          value={isPublic}
          onChange={(e) => {
            const newIsPublic = e.target.checked;
            setIsPublic(newIsPublic);
            if (newIsPublic) {
              // When toggling to public, clear shared departments
              setSharedDepartments([]);
            }
          }}
        />
        <span className={styles.footerToggleLabel}>
          Visible to All Departments
        </span>
      </div>

      {/* Right side: Action Buttons */}
      <div className={styles.footerButtons}>
        <IAFButton type="secondary" onClick={onClose} disabled={loading}>
          Cancel
        </IAFButton>
        <IAFButton type="primary" onClick={handleSubmit} disabled={loading}>{/* disabled={loading || !isFormValid} */}
          {isCreateMode ? "Create Knowledge Base" : "Update"}
        </IAFButton>
      </div>
    </div>
  );

  const headerInfo = isCreateMode
    ? [{ label: "Created By", value: userName || loggedInUserEmail }]
    : [{ label: "Created By", value: kbData?.created_by || "Unknown" }];

  return (
    <FullModal
      isOpen={true}
      onClose={onClose}
      title={isCreateMode ? "Create Knowledge Base" : `Edit: ${kbData?.name || "Knowledge Base"}`}
      loading={loading}
      headerInfo={headerInfo}
      footer={footer}
    >
      <div className="form">
        {/* Basic Information - Name and Departments inline */}
        <div className="formSection">
          <div className={styles.inlineFormRow}>
            {/* Name Field - Inline Label and Input */}
            <div className={styles.nameFieldContainer}>
              <label className={styles.inlineLabel}>
                Name <span className="required">*</span>
              </label>
              <textarea
                name="name"
                className={styles.nameTextarea}
                value={formData.name}
                onChange={handleInputChange}
                placeholder="Enter knowledge base name"
                disabled={!isCreateMode}
                readOnly={!isCreateMode}
                rows={1}
              />
            </div>

            {/* Departments - Using DepartmentSelector like Agent/Tool pages */}
            {!isPublic && (
              <DepartmentSelector
                selectedDepartments={sharedDepartments}
                onChange={setSharedDepartments}
                departmentsList={departmentsList.filter(dept => dept !== loggedInDepartment)}
                disabled={false}
                loading={departmentsLoading}
              />
            )}
          </div>
        </div>

        {/* Documents Section */}
        <div className="formSection">
          <label className="label-desc">Documents {isCreateMode && <span className="required">*</span>}</label>

          {/* Existing Documents (Update Mode - read only) */}
          {!isCreateMode && existingDocuments.length > 0 && (
            <div className={styles.existingDocuments}>
              <p className={styles.existingDocsLabel}>Existing Documents ({existingDocuments.length})</p>
              <div className={styles.documentsList}>
                {existingDocuments.map((doc, index) => (
                  <div key={index} className={styles.documentItem}>
                    <div className={styles.documentInfo}>
                      <SVGIcons icon="file-default" width={16} height={16} color="var(--content-color)" />
                      <span className={styles.documentName}>{doc}</span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Upload section - only in create mode */}
          {isCreateMode && (
            <>
              <UploadBox
                files={files}
                isDragging={isDragging}
                onDragEnter={handleDragEnter}
                onDragLeave={handleDragLeave}
                onDragOver={handleDragOver}
                onDrop={handleDrop}
                onClick={handleUploadClick}
                onRemoveFile={handleRemoveFile}
                loading={loading}
                fileInputId="kb-file-input"
                acceptedFileTypes=".pdf,.txt,.md,.doc,.docx"
                supportedText="Supported: PDF, TXT, MD, DOC, DOCX"
                uploadText="Click to upload"
                dragDropText=" or drag and drop"
                multiple={true}
              />

              <input
                ref={fileInputRef}
                id="kb-file-input"
                type="file"
                multiple
                accept=".pdf,.txt,.md,.doc,.docx"
                onChange={handleFileInputChange}
                style={{ display: "none" }}
              />
            </>
          )}
        </div>
      </div>
    </FullModal>
  );
};

export default KnowledgeBaseForm;
