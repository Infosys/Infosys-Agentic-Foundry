import React, { useState, useEffect, useCallback } from "react";
import { APIs } from "../../constant";
import useFetch from "../../Hooks/useAxios";
import { useMessage } from "../../Hooks/MessageContext";
import SVGIcons from "../../Icons/SVGIcons";
import IAFButton from "../../iafComponents/GlobalComponents/Buttons/Button";
import TextField from "../../iafComponents/GlobalComponents/TextField/TextField";
import { FullModal } from "../../iafComponents/GlobalComponents/FullModal";
import EmptyState from "../commonComponents/EmptyState";
import Table from "./commonComponents/Table";
import InfoTag from "../commonComponents/InfoTag";
import ConfirmationModal from "../commonComponents/ToastMessages/ConfirmationPopup";
import styles from "./ModelCosts.module.css";
import Loader from "../commonComponents/Loader.jsx";

/**
 * ModelCosts Component
 *
 * Admin tab for managing model pricing configuration.
 * Uses FullModal + global form classes (same as ToolOnBoarding) for consistency.
 * Supports: Create (POST), Update (PUT by name), Delete (DELETE by name).
 */

const EMPTY_FORM = {
  name: "",
  model_name: "",
  model_version: "",
  provider_key: "",
  input_cost_per_token: "",
  output_cost_per_token: "",
  cache_read_input_token_cost: "",
};

const ModelCosts = ({ onPlusClickRef }) => {
  const [modalOpen, setModalOpen] = useState(false);
  const [formData, setFormData] = useState({ ...EMPTY_FORM });
  const [isEditMode, setIsEditMode] = useState(false);
  const [saving, setSaving] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
  const [results, setResults] = useState([]);

  const { fetchData, postData, putData, deleteData } = useFetch();
  const { addMessage } = useMessage();

  const [loading, setLoading] = useState(true);

  // --- Fetch all model costs on mount ---
  const fetchModelCosts = useCallback(async () => {
    setLoading(true);
    try {
      const data = await fetchData(APIs.MODEL_COSTS);
      if (Array.isArray(data)) {
        setResults(data);
      } else if (data && Array.isArray(data.data)) {
        setResults(data.data);
      } else if (data && Array.isArray(data.results)) {
        setResults(data.results);
      }
    } catch {
      // silent - empty state will show
    } finally {
      setLoading(false);
    }
  }, [fetchData]);

  useEffect(() => {
    fetchModelCosts();
  }, [fetchModelCosts]);

  // --- Modal handlers ---
  const openCreateModal = useCallback(() => {
    setFormData({ ...EMPTY_FORM });
    setIsEditMode(false);
    setShowDeleteConfirm(false);
    setModalOpen(true);
  }, []);

  // Expose openCreateModal to parent SubHeader via ref
  useEffect(() => {
    if (onPlusClickRef) {
      onPlusClickRef.current = openCreateModal;
    }
  }, [onPlusClickRef, openCreateModal]);

  const openEditModal = (model) => {
    setFormData({
      name: model.name || "",
      model_name: model.model_name || "",
      model_version: model.model_version || "",
      provider_key: model.provider_key || "",
      input_cost_per_token: model.input_cost_per_token || "",
      output_cost_per_token: model.output_cost_per_token || "",
      cache_read_input_token_cost: model.cache_read_input_token_cost || "",
    });
    setIsEditMode(true);
    setShowDeleteConfirm(false);
    setModalOpen(true);
  };

  const closeModal = () => {
    setModalOpen(false);
    setFormData({ ...EMPTY_FORM });
    setIsEditMode(false);
    setShowDeleteConfirm(false);
  };

  const handleFieldChange = (field, value) => {
    setFormData((prev) => ({ ...prev, [field]: value }));
  };

  // --- Build payload ---
  const buildPayload = () => ({
    name: formData.name.trim(),
    model_name: formData.model_name.trim(),
    model_version: formData.model_version.trim(),
    provider_key: formData.provider_key.trim(),
    input_cost_per_token: Number(formData.input_cost_per_token) || 0,
    output_cost_per_token: Number(formData.output_cost_per_token) || 0,
    cache_read_input_token_cost: Number(formData.cache_read_input_token_cost) || 0,
  });

  // --- Create (POST) ---
  const handleCreate = async () => {
    if (!formData.name.trim() || !formData.model_name.trim()) {
      addMessage("Name, Model Name", "error");
      return;
    }
    setSaving(true);
    try {
      const payload = buildPayload();
      const response = await postData(APIs.MODEL_COSTS, payload);
      if (response) {
        setResults((prev) => {
          const filtered = prev.filter((r) => r.model_name !== response.model_name);
          return [response, ...filtered];
        });
      }
      addMessage("Model cost created successfully", "success");
      closeModal();
      fetchModelCosts();
    } catch {
      addMessage("Failed to create model cost", "error");
    } finally {
      setSaving(false);
    }
  };

  // --- Update (PUT) ---
  const handleUpdate = async () => {
    setSaving(true);
    try {
      const payload = buildPayload();
      // List 2: PUT /{model_name}  →  POST /update/{model_name}
      const url = `${APIs.MODEL_COSTS}/update/${encodeURIComponent(formData.model_name.trim())}`;
      const response = await putData(url, payload);
      if (response) {
        setResults((prev) => {
          const filtered = prev.filter((r) => r.model_name !== response.model_name);
          return [response, ...filtered];
        });
      }
      addMessage("Model cost updated successfully", "success");
      closeModal();
      fetchModelCosts();
    } catch {
      addMessage("Failed to update model cost", "error");
    } finally {
      setSaving(false);
    }
  };

  // --- Delete (DELETE) ---
  const handleDelete = async () => {
    if (!formData.name.trim()) return;
    setDeleting(true);
    try {
      // List 2: DELETE /{model_name}  →  POST /delete/{model_name}
      const url = `${APIs.MODEL_COSTS}/delete/${encodeURIComponent(formData.model_name.trim())}`;
      await deleteData(url);
      setResults((prev) => prev.filter((r) => r.model_name !== formData.model_name.trim()));
      addMessage("Model cost deleted successfully", "success");
      closeModal();
      fetchModelCosts();
    } catch {
      addMessage("Failed to delete model cost", "error");
    } finally {
      setDeleting(false);
      setShowDeleteConfirm(false);
    }
  };

  // --- Helpers ---
  const formatCost = (value) => {
    if (value == null || value === "") return "\u2014";
    const num = Number(value);
    if (isNaN(num)) return "\u2014";
    if (num === 0) return "$0";
    return `$${num.toExponential(2)}`;
  };

  const formatDate = (dateStr) => {
    if (!dateStr) return "";
    try {
      return new Date(dateStr).toLocaleDateString("en-US", {
        month: "short", day: "numeric", year: "numeric", hour: "2-digit", minute: "2-digit",
      });
    } catch { return dateStr; }
  };

  const isFormValid = Boolean(formData.name.trim() && formData.model_name.trim());

  // --- Footer for FullModal (same as ToolOnBoarding) ---
  const renderFooter = () => (
    <div style={{ display: "flex", alignItems: "center", justifyContent: "flex-end", width: "100%", gap: "12px" }}>
      <IAFButton type="secondary" onClick={closeModal}>
        Cancel
      </IAFButton>
      {isEditMode && (
        <IAFButton type="primary" onClick={() => setShowDeleteConfirm(true)}>
          Delete
        </IAFButton>
      )}
      <IAFButton
        type="primary"
        onClick={isEditMode ? handleUpdate : handleCreate}
        disabled={!isFormValid || saving}
        loading={saving || loading}
      >
        {isEditMode ? "Update" : "Add Model Cost"}
      </IAFButton>
    </div>
  );

  return (
    <div className={styles.container}>
      <div className={styles.container}>
        {/* Model costs table */}
        <div className={styles.tableWrapper}>
          {loading ? (
            <Loader />
          ) : (
            <Table
              headers={["Name", "Model Name", "Provider Key", "Input Cost/Token", "Output Cost/Token", "Cache Cost/Token"]}
              data={results}
              loading={false}
              emptyMessage="No model costs configured yet"
              renderRow={(item, index) => (
                <tr key={item.id || index} onClick={() => openEditModal(item)} style={{ cursor: "pointer" }}>
                  <td>{item.name || "NA"}</td>
                  <td>{item.model_name}</td>
                  <td>{item.provider_key || "NA"}</td>
                  <td>{formatCost(item.input_cost_per_token)}</td>
                  <td>{formatCost(item.output_cost_per_token)}</td>
                  <td>{formatCost(item.cache_read_input_token_cost)}</td>
                </tr>
              )}
            />
          )}
        </div>

        {/* Create / Edit FullModal � same theme as ToolOnBoarding */}
        <FullModal
          isOpen={modalOpen}
          onClose={closeModal}
          title={isEditMode ? "Edit Model Cost" : "Add Model Cost"}
          headerInfo={isEditMode ? [
            { label: "Name", value: formData.name },
            { label: "Provider", value: formData.provider_key },
          ] : undefined}
          loading={saving || loading}
          footer={renderFooter()}
        >
          <form className="form-section" onSubmit={(e) => e.preventDefault()}>
            <div className="formContent" style={{ paddingTop: 0 }}>
              <div className="form" style={{ gap: "4px" }}>

                {/* Basic Info Section */}
                <div className="formSection" style={{ overflow: "visible" }}>
                  <div className="formGroup" style={{ marginTop: 0, marginBottom: 0 }}>
                    <div className="formRow">
                      <div className="formGroup">
                        <label className="label-desc">
                          Name <span className="required">*</span> <span className={styles.infoTagWrap}><InfoTag message="Unique identifier (cannot change after creation)" /></span>
                        </label>
                        <TextField
                          placeholder={isEditMode ? "" : "Unique identifier"}
                          value={formData.name}
                          onChange={(e) => handleFieldChange("name", e.target.value)}
                          disabled={isEditMode}
                        />
                      </div>
                      <div className="formGroup">
                        <label className="label-desc">
                          Model Name <span className="required">*</span>
                        </label>
                        <TextField
                          placeholder={isEditMode ? "" : "e.g. GPT-4o Mini"}
                          value={formData.model_name}
                          onChange={(e) => handleFieldChange("model_name", e.target.value)}
                        />
                      </div>
                    </div>
                  </div>

                  <div className="formGroup" style={{ marginTop: 0, marginBottom: 0 }}>
                    <div className="formRow">
                      <div className="formGroup">
                        <label className="label-desc">Model Version</label>
                        <TextField
                          placeholder={isEditMode ? "" : "e.g. 2024-07-18"}
                          value={formData.model_version}
                          onChange={(e) => handleFieldChange("model_version", e.target.value)}
                        />
                      </div>
                      <div className="formGroup">
                        <label className="label-desc">
                          Provider Key
                        </label>
                        <TextField
                          placeholder={isEditMode ? "" : "e.g. azure/gpt-4o-mini"}
                          value={formData.provider_key}
                          onChange={(e) => handleFieldChange("provider_key", e.target.value)}
                        />
                      </div>
                    </div>
                  </div>
                </div>

                {/* Cost Configuration Section */}
                <div className="formSection">
                  <div className="formGroup" style={{ marginTop: 0, marginBottom: 0 }}>
                    <div className="formRow">
                      <div className="formGroup">
                        <label className="label-desc">Input Cost per Token</label>
                        <TextField
                          placeholder={isEditMode ? "" : "e.g. 0.00000015"}
                          value={formData.input_cost_per_token}
                          onChange={(e) => handleFieldChange("input_cost_per_token", e.target.value)}
                        />
                      </div>
                      <div className="formGroup">
                        <label className="label-desc">Output Cost per Token</label>
                        <TextField
                          placeholder={isEditMode ? "" : "e.g. 0.0000006"}
                          value={formData.output_cost_per_token}
                          onChange={(e) => handleFieldChange("output_cost_per_token", e.target.value)}
                        />
                      </div>
                    </div>
                  </div>

                  <div className="formGroup" style={{ marginTop: 0, marginBottom: 0 }}>
                    <div className="formRow">
                      <div className="formGroup">
                        <label className="label-desc">Cache Read Cost per Token</label>
                        <TextField
                          placeholder={isEditMode ? "" : "e.g. 0.000000075"}
                          value={formData.cache_read_input_token_cost}
                          onChange={(e) => handleFieldChange("cache_read_input_token_cost", e.target.value)}
                        />
                      </div>
                      <div className="formGroup" />
                    </div>
                  </div>
                </div>

              </div>
            </div>
          </form>
        </FullModal>

        {/* Delete Confirmation Popup (same as ToolOnBoarding) */}
        {showDeleteConfirm && (
          <ConfirmationModal
            message={`Are you sure you want to delete model cost "${formData.name || formData.model_name}"? This action cannot be undone.`}
            onConfirm={handleDelete}
            setShowConfirmation={setShowDeleteConfirm}
            loading={deleting}
          />
        )}
      </div>
    </div>
  );
};

export default ModelCosts;
