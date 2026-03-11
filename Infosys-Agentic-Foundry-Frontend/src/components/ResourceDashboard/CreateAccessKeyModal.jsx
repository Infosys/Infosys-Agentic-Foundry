import { useState } from "react";
import { FullModal } from "../../iafComponents/GlobalComponents/FullModal";
import IAFButton from "../../iafComponents/GlobalComponents/Buttons/Button";
import TextareaWithActions from "../commonComponents/TextareaWithActions";
import Cookies from "js-cookie";

/**
 * CreateAccessKeyModal Component
 * Slide-in modal from right for creating a new access key
 * Uses global CSS classes (.form, .formGroup, .label-desc, etc.) for consistency
 */
export default function CreateAccessKeyModal({ onClose, onSubmit, loading }) {
  const [formData, setFormData] = useState({
    access_key: "",
    description: ""
  });
  const [errors, setErrors] = useState({});
  const userName = Cookies.get("userName");
  const userEmail = Cookies.get("email");

  const handleChange = (e) => {
    const { name, value } = e.target;
    setFormData((prev) => ({
      ...prev,
      [name]: value
    }));
    // Clear error when user types
    if (errors[name]) {
      setErrors((prev) => ({
        ...prev,
        [name]: ""
      }));
    }
  };

  const validateForm = () => {
    const newErrors = {};
    if (!formData.access_key.trim()) {
      newErrors.access_key = "Access key name is required";
    }
    setErrors(newErrors);
    return Object.keys(newErrors).length === 0;
  };

  const handleSubmit = (e) => {
    e.preventDefault();
    if (validateForm()) {
      onSubmit(formData);
    }
  };

  // Header info items for the FullModal
  const headerInfo = [
    { label: "Created By", value: userName || userEmail || "Unknown" }
  ];

  // Footer with action buttons
  const footer = (
    <div style={{ display: "flex", justifyContent: "flex-end", gap: "12px" }}>
      <IAFButton
        type="secondary"
        onClick={onClose}
        disabled={loading}
      >
        Cancel
      </IAFButton>
      <IAFButton
        type="primary"
        onClick={handleSubmit}
        disabled={loading}
      >
        {loading ? "Creating..." : "Create Access Key"}
      </IAFButton>
    </div>
  );

  return (
    <FullModal
      isOpen={true}
      onClose={onClose}
      title="Create Access Key"
      loading={loading}
      headerInfo={headerInfo}
      footer={footer}
    >
      <form onSubmit={handleSubmit} className="form-section">
        <div className="formContent">
          <div className="form">
            <div className="formGroup">
              <label htmlFor="access_key" className="label-desc">
                Access Key Name <span className="required">*</span>
              </label>
              <input
                type="text"
                id="access_key"
                name="access_key"
                value={formData.access_key}
                onChange={handleChange}
                placeholder="Enter access key name"
                className={`input ${errors.access_key ? "inputError" : ""}`}
                disabled={loading}
              />
              {errors.access_key && (
                <span style={{ fontSize: "12px", color: "var(--danger, #ef4444)" }}>
                  {errors.access_key}
                </span>
              )}
            </div>

            <div className="formGroup">
              <TextareaWithActions
                name="description"
                value={formData.description}
                onChange={handleChange}
                label="Description"
                required={false}
                disabled={loading}
                placeholder="Enter description for this access key"
                rows={3}
                onZoomSave={(updatedContent) => setFormData((prev) => ({ ...prev, description: updatedContent }))}
              />
            </div>
          </div>
        </div>
      </form>
    </FullModal>
  );
}
