import React, { useEffect, useCallback } from "react";
import styles from "./Modal.module.css";

/**
 * Reusable Modal Component
 * 
 * A modular, navbar-aware modal component that handles:
 * - Overlay positioning (adjusts for collapsed/expanded navbar)
 * - Click outside to close
 * - ESC key to close
 * - Accessibility (ARIA attributes)
 * - Animation
 * 
 * @param {Object} props
 * @param {boolean} props.isOpen - Controls modal visibility
 * @param {function} props.onClose - Callback when modal should close
 * @param {React.ReactNode} props.children - Modal content
 * @param {string} props.className - Additional class for modal container
 * @param {string} props.overlayClassName - Additional class for overlay
 * @param {string} props.size - Modal size: "sm" | "md" | "lg" | "xl" | "auto" (default: "md")
 * @param {string} props.ariaLabel - Accessibility label for the modal
 * @param {boolean} props.closeOnOverlayClick - Whether clicking overlay closes modal (default: true)
 * @param {boolean} props.closeOnEsc - Whether ESC key closes modal (default: true)
 * @param {boolean} props.showCloseButton - Whether to show close button (default: true)
 */
const Modal = ({
  isOpen,
  onClose,
  children,
  className = "",
  overlayClassName = "",
  size = "md",
  ariaLabel = "Modal dialog",
  closeOnOverlayClick = true,
  closeOnEsc = true,
  showCloseButton = true,
}) => {
  // Handle ESC key press
  const handleKeyDown = useCallback(
    (e) => {
      if (closeOnEsc && e.key === "Escape") {
        onClose();
      }
    },
    [closeOnEsc, onClose]
  );

  // Add/remove event listener for ESC key
  useEffect(() => {
    if (isOpen) {
      document.addEventListener("keydown", handleKeyDown);
      // Prevent body scroll when modal is open
      document.body.style.overflow = "hidden";
    }

    return () => {
      document.removeEventListener("keydown", handleKeyDown);
      document.body.style.overflow = "";
    };
  }, [isOpen, handleKeyDown]);

  // Handle overlay click
  const handleOverlayClick = (e) => {
    if (closeOnOverlayClick && e.target === e.currentTarget) {
      onClose();
    }
  };

  // Don't render if not open
  if (!isOpen) return null;

  // Size class mapping
  const sizeClass = styles[`modal${size.charAt(0).toUpperCase() + size.slice(1)}`] || styles.modalMd;

  return (
    <div
      className={`${styles.modalOverlay} ${overlayClassName}`}
      onClick={handleOverlayClick}
      role="dialog"
      aria-modal="true"
      aria-label={ariaLabel}
    >
      <div
        className={`${styles.modal} ${sizeClass} ${className}`}
        onClick={(e) => e.stopPropagation()}
      >
        {showCloseButton && (
          <button
            className="closeBtn"
            onClick={onClose}
            aria-label="Close modal"
          >
            ×
          </button>
        )}
        {children}
      </div>
    </div>
  );
};

export default Modal;
