import { useState, useEffect } from "react";
import styles from "./CreateAccessKeyModal.module.css";
import FullModal from "../../iafComponents/GlobalComponents/FullModal/FullModal.jsx";
import IAFButton from "../../iafComponents/GlobalComponents/Buttons/Button";
import Cookies from "js-cookie";

/**
 * ViewAccessKeyModal Component
 * Slide-in modal from right for viewing/editing access key details
 */
export default function ViewAccessKeyModal({ 
  onClose, 
  accessKeyData, 
  loading,
  isEditMode = false 
}) {
  const [formData, setFormData] = useState({
    access_key: "",
    description: "",
    created_by: "",
    department_name: "",
    created_at: ""
  });

  const userName = Cookies.get("userName");
  const userEmail = Cookies.get("email");

  // Populate form data when accessKeyData changes
  useEffect(() => {
    if (accessKeyData) {
      setFormData({
        access_key: accessKeyData.access_key || accessKeyData.name || "",
        description: accessKeyData.description || "",
        created_by: accessKeyData.created_by || "",
        department_name: accessKeyData.department_name || "",
        created_at: accessKeyData.created_at || ""
      });
    }
  }, [accessKeyData]);

  // Format date for display
  const formatDate = (dateString) => {
    if (!dateString) return "N/A";
    try {
      const date = new Date(dateString);
      return date.toLocaleString();
    } catch {
      return dateString;
    }
  };

  // Header info items for the FullModal
  const headerInfo = [
    { label: "Created By", value: formData.created_by || "Unknown" }
  ];

  // Footer with action buttons
  const footer = (
    <div className={styles.footerButtons}>
      <IAFButton
        variant="secondary"
        onClick={onClose}
        disabled={loading}
      >
        Close
      </IAFButton>
    </div>
  );

  return (
    <FullModal
      isOpen={true}
      onClose={onClose}
      title="Access Key Details"
      loading={loading}
      headerInfo={headerInfo}
      footer={footer}
    >
      <div className={styles.form}>
        <div className={styles.formGroup}>
          <label className={styles.label}>Access Key Name</label>
          <div className={styles.readOnlyField}>
            {formData.access_key || "N/A"}
          </div>
        </div>

        <div className={styles.formGroup}>
          <label className={styles.label}>Description</label>
          <div className={styles.readOnlyField}>
            {formData.description || "No description provided"}
          </div>
        </div>

        <div className={styles.formGroup}>
          <label className={styles.label}>Department</label>
          <div className={styles.readOnlyField}>
            {formData.department_name || "N/A"}
          </div>
        </div>
      </div>
    </FullModal>
  );
}
