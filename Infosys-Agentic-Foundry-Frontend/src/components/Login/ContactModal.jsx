import React, { useState, useEffect, useMemo } from "react";
import styles from "./ContactModal.module.css";
import SVGIcons from "../../Icons/SVGIcons";
import { FullModal } from "../../iafComponents/GlobalComponents/FullModal";
import axios from "axios";
import { APIs, BASE_URL } from "../../constant";
import ContactCard from "./ContactCard";

/**
 * ContactModal - Displays admin contact information
 * 
 * This modal shows contact information for administrators
 * fetched from the /auth/admin-contacts API.
 * 
 * Response format:
 * {
 *   success: true,
 *   message: "Contact a SuperAdmin for system-wide help...",
 *   superadmins: [{email, username}],
 *   departments: [{department_name, admins: [{email, username}]}]
 * }
 * 
 * @param {boolean} isOpen - Controls modal visibility
 * @param {function} onClose - Callback to close the modal
 */
const ContactModal = ({ isOpen, onClose }) => {
  const [superadmins, setSuperadmins] = useState([]);
  const [departments, setDepartments] = useState([]);
  const [message, setMessage] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [copyFeedback, setCopyFeedback] = useState("");

  // Copy email to clipboard with fallback for non-secure contexts
  const handleCopyEmail = async (email) => {
    try {
      if (navigator.clipboard && window.isSecureContext) {
        await navigator.clipboard.writeText(email);
      } else {
        // Fallback for HTTP or older browsers
        const textArea = document.createElement("textarea");
        textArea.value = email;
        textArea.style.position = "fixed";
        textArea.style.left = "-9999px";
        textArea.style.top = "-9999px";
        document.body.appendChild(textArea);
        textArea.focus();
        textArea.select();
        document.execCommand("copy");
        document.body.removeChild(textArea);
      }
      setCopyFeedback("Email copied!");
      setTimeout(() => setCopyFeedback(""), 2000);
    } catch (err) {
      setCopyFeedback("Failed to copy");
      setTimeout(() => setCopyFeedback(""), 2000);
    }
  };

  // Fetch contacts when modal opens
  useEffect(() => {
    if (isOpen) {
      fetchContacts();
    }
  }, [isOpen]);

  const fetchContacts = async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await axios.get(`${BASE_URL}${APIs.GET_ADMIN_CONTACTS}`);
      const data = response.data;
      
      if (data?.success) {
        setSuperadmins(data.superadmins || []);
        setDepartments(data.departments || []);
        setMessage(data.message || "");
      } else {
        setError("Failed to load contact information.");
      }
    } catch (err) {
      console.error("Failed to fetch admin contacts:", err);
      setError("Failed to load contact information. Please try again later.");
      setSuperadmins([]);
      setDepartments([]);
    } finally {
      setLoading(false);
    }
  };

  const hasContacts = superadmins.length > 0 || departments.some(d => d.admins?.length > 0);

  // Transform contacts data for DisplayCard1
  const contactsData = useMemo(() => {
    const contacts = [];
    
    // Add super admins
    superadmins.forEach((admin, index) => {
      contacts.push({
        id: `super-${admin.email || index}`,
        name: admin.username || admin.name || "Super Admin",
        email: admin.email || "",
        department: "System Wide",
        role: admin.role || "Super Admin",
      });
    });
    
    // Add department admins
    departments.forEach((dept) => {
      (dept.admins || []).forEach((admin, index) => {
        contacts.push({
          id: `${dept.department_name}-${admin.email || index}`,
          name: admin.username || admin.name || "Admin",
          email: admin.email || "",
          department: dept.department_name || "Unknown Department",
          role: admin.role || "Admin",
        });
      });
    });
    
    return contacts;
  }, [superadmins, departments]);

  // Add class to body when modal is open to override overlay styles
  useEffect(() => {
    if (isOpen) {
      document.body.classList.add("login-modal-open");
    } else {
      document.body.classList.remove("login-modal-open");
    }
    return () => {
      document.body.classList.remove("login-modal-open");
    };
  }, [isOpen]);

  return (
    <FullModal
      isOpen={isOpen}
      onClose={onClose}
      title="Admin Contacts"
      loading={loading}
      closeOnOverlayClick={true}
      closeOnEscape={true}
      className={styles.fullWidthModal}
    >
      <div className={styles.content}>
        {/* Copy feedback toast */}
        {copyFeedback && (
          <div className={styles.copyFeedback}>
            {copyFeedback}
          </div>
        )}

        {/* Info message from API */}
        {message && (
          <div className={styles.infoNote}>
            <SVGIcons icon="info" width={16} height={16} fill="var(--app-primary-color)" />
            <span>{message}</span>
          </div>
        )}

        {error && (
          <div className={styles.errorMessage}>
            <SVGIcons icon="exclamation" width={16} height={16} fill="var(--danger)" />
            <span>{error}</span>
          </div>
        )}

        {!error && !hasContacts && !loading && (
          <div className={styles.emptyState}>
            <SVGIcons icon="user" width={32} height={32} fill="var(--muted)" />
            <span>No contact information available.</span>
          </div>
        )}

        {/* All Contacts - Custom Cards */}
        {hasContacts && (
          <div className={styles.contactsGrid}>
            {contactsData.map((contact) => (
              <ContactCard
                key={contact.id}
                name={contact.name}
                email={contact.email}
                department={contact.department}
                role={contact.role}
                onCopyEmail={handleCopyEmail}
              />
            ))}
          </div>
        )}
      </div>
    </FullModal>
  );
};

export default ContactModal;
