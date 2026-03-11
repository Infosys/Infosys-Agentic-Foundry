import React from "react";
import styles from "./ContactModal.module.css";
import SVGIcons from "../../Icons/SVGIcons";

/**
 * ContactCard - Reusable card component for displaying contact information
 * Uses glassmorphism styling matching tools/agents cards
 * 
 * @param {string} name - Contact's display name
 * @param {string} email - Contact's email address
 * @param {string} department - Department or "System Wide" for super admins
 * @param {string} role - Role badge text (e.g., "Super Admin", "Admin")
 * @param {function} onCopyEmail - Callback when copy button is clicked
 * @param {string} className - Optional additional className
 */
const ContactCard = ({
  name,
  email,
  department,
  role,
  onCopyEmail,
  className = ""
}) => {
  const handleCopy = (e) => {
    e.preventDefault();
    e.stopPropagation();
    if (onCopyEmail && email) {
      onCopyEmail(email);
    }
  };

  return (
    <div className={`${styles.cardContainer} ${className}`}>
      <div className={styles.contactCard}>
        {/* Card Header with Name */}
        <div className={styles.cardHeader}>
          <h3 className={styles.contactName}>{name}</h3>
          <span className={styles.roleBadge}>{role}</span>
        </div>

        {/* Card Body with Email */}
        <div className={styles.cardBody}>
          <div className={styles.emailRow}>
            <span className={styles.emailText}>{email}</span>
            <button
              type="button"
              className={styles.copyButton}
              onClick={handleCopy}
              title="Copy email"
              aria-label="Copy email to clipboard"
            >
              <SVGIcons icon="copy" width={14} height={14} />
            </button>
          </div>
        </div>

        {/* Card Footer with Department */}
        <div className={styles.cardFooter}>
          <div className={styles.departmentBadge}>
            <SVGIcons icon="building" width={12} height={12} />
            <span>{department}</span>
          </div>
        </div>
      </div>
    </div>
  );
};

export default ContactCard;
