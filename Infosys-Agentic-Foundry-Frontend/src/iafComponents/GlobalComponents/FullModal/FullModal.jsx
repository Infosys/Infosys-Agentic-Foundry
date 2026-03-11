import React, { useEffect, useCallback } from "react";
import { createPortal } from "react-dom";
import PropTypes from "prop-types";
import SVGIcons from "../../../Icons/SVGIcons";
import Loader from "../../../components/commonComponents/Loader";
import styles from "./FullModal.module.css";

/**
 * FullModal - A reusable full-screen modal component for Agentic Pro UI
 *
 * This component provides a standardized modal experience across the application,
 * replacing the need for repetitive modal markup in components like:
 * - ToolOnBoarding
 * - AgentForm
 * - AddServer
 * - ResponseDetailModal
 * - ConsistencyTab
 *
 * Features:
 * - Portal rendering for proper z-index stacking
 * - ESC key and overlay click to close
 * - Body scroll lock when open
 * - Split layout support for side panels
 * - Dynamic header info items
 * - Accessible with ARIA attributes
 * - Smooth animations
 *
 * @example
 * // Basic usage
 * <FullModal
 *   isOpen={showModal}
 *   onClose={handleClose}
 *   title="Create Agent"
 *   loading={isLoading}
 *   headerInfo={[{ label: "Created By", value: userName }]}
 *   footer={<Button onClick={handleSubmit}>Submit</Button>}
 * >
 *   <form>{...}</form>
 * </FullModal>
 *
 * @example
 * // Split layout with side panel
 * <FullModal
 *   isOpen={showModal}
 *   onClose={handleClose}
 *   title="Add Tool"
 *   splitLayout={showExecutorPanel}
 *   sidePanel={<ExecutorPanel />}
 *   splitHeaderLabels={{ left: "Configuration", right: "Execution" }}
 * >
 *   <form>{...}</form>
 * </FullModal>
 */
const FullModal = ({
  isOpen,
  onClose,
  title,
  children,
  loading = false,
  headerInfo = [],
  footer,
  closeOnOverlayClick = true,
  closeOnEscape = true,
  showCloseButton = true,
  className = "",
  contentClassName = "",
  mainRef = null,
  // Full height mode - for canvas/editors that need full height
  fullHeight = false,
  // Split layout props
  splitLayout = false,
  sidePanel = null,
  splitHeaderLabels = null,
}) => {
  // Handle ESC key press
  const handleEscapeKey = useCallback(
    (event) => {
      if (closeOnEscape && event.key === "Escape" && !loading) {
        onClose();
      }
    },
    [closeOnEscape, onClose, loading]
  );

  // Lock body scroll when modal is open
  useEffect(() => {
    if (isOpen) {
      const originalOverflow = document.body.style.overflow;
      document.body.style.overflow = "hidden";
      document.addEventListener("keydown", handleEscapeKey);

      return () => {
        document.body.style.overflow = originalOverflow;
        document.removeEventListener("keydown", handleEscapeKey);
      };
    }
  }, [isOpen, handleEscapeKey]);

  // Handle overlay click
  const handleOverlayClick = (event) => {
    if (closeOnOverlayClick && event.target === event.currentTarget && !loading) {
      onClose();
    }
  };

  // Prevent event propagation from modal content
  const handleContentClick = (event) => {
    event.stopPropagation();
  };

  if (!isOpen) return null;

  const modalContent = (
    <div className={`${styles.fullModalOverlay}`} onClick={handleOverlayClick} role="dialog" aria-modal="true" aria-labelledby="modal-title">
      {loading && (
        <div onClick={(e) => e.stopPropagation()}>
          <Loader />
        </div>
      )}

      <div className={`${styles.fullModal} ${className}`} onClick={handleContentClick}>
        {/* Header */}
        <div className={`${styles.fullModalHeader}`}>
          <div className={`${styles.fullModalHeaderLeft}`}>
            <h2 id="modal-title" className={`${styles.fullModalHeaderTitle}`}>
              {title}
            </h2>
          </div>

          <div className={`${styles.fullModalHeaderRight}`}>
            {headerInfo.map((info, index) => (
              <div key={index} className={`${styles.fullModalHeaderInfoItem}`}>
                <span className={`${styles.fullModalHeaderInfoLabel}`}>{info.label}</span>
                <span className={`${styles.fullModalHeaderInfoValue}`}>{info.value || "—"}</span>
              </div>
            ))}

            {showCloseButton && (
              <button className={`${styles.fullModalCloseBtn}`} onClick={onClose} aria-label="Close modal" type="button" disabled={loading}>
                <SVGIcons icon="x" width={24} height={24} color="var(--text-primary)" />
              </button>
            )}
          </div>
        </div>

        {/* Main Content */}
        <div
          className={`${styles.fullModalMain} ${fullHeight ? styles.fullModalMainFullHeight : ""} ${contentClassName}`}
          ref={mainRef}>
          {/* Split header bar (optional) */}
          {splitLayout && splitHeaderLabels && (
            <div className={styles.splitHeaderBar}>
              <div className={styles.splitHeaderColLeft}>{splitHeaderLabels.left || "Configuration"}</div>
              <div className={styles.splitHeaderColRight}>{splitHeaderLabels.right || "Preview"}</div>
            </div>
          )}

          {/* Content wrapper with optional split layout */}
          <div className={`${styles.fullModalContentWrapper} ${fullHeight ? styles.fullModalContentWrapperFullHeight : ""} ${splitLayout ? styles.splitLayout : ""}`}>
            {/* Main content (left panel in split mode) */}
            <div className={splitLayout ? styles.splitLeftPanel : fullHeight ? styles.fullModalContentInner : ""}>{children}</div>

            {/* Side panel (right panel in split mode) */}
            {splitLayout && sidePanel && <div className={styles.splitRightPanel}>{sidePanel}</div>}
          </div>
        </div>

        {/* Footer */}
        {footer && <div className={`${styles.fullModalFooter}`}>{footer}</div>}
      </div>
    </div>
  );

  // Render via portal for proper z-index stacking
  return createPortal(modalContent, document.body);
};

// PropTypes for type safety and documentation
FullModal.propTypes = {
  /** Whether the modal is open/visible */
  isOpen: PropTypes.bool.isRequired,
  /** Callback function when modal closes */
  onClose: PropTypes.func.isRequired,
  /** Modal title displayed in the header */
  title: PropTypes.node.isRequired,
  /** Modal body content */
  children: PropTypes.node.isRequired,
  /** Whether to show loading overlay */
  loading: PropTypes.bool,
  /** Array of header info items to display (label/value pairs) */
  headerInfo: PropTypes.arrayOf(
    PropTypes.shape({
      label: PropTypes.string.isRequired,
      value: PropTypes.string,
    })
  ),
  /** Footer content (typically buttons) */
  footer: PropTypes.node,
  /** Whether clicking overlay closes the modal */
  closeOnOverlayClick: PropTypes.bool,
  /** Whether pressing ESC closes the modal */
  closeOnEscape: PropTypes.bool,
  /** Whether to show the close button in header */
  showCloseButton: PropTypes.bool,
  /** Additional CSS class for the modal container */
  className: PropTypes.string,
  /** Additional CSS class for the main content area */
  contentClassName: PropTypes.string,
  /** Ref for the main content container (for scroll control) */
  mainRef: PropTypes.oneOfType([PropTypes.func, PropTypes.shape({ current: PropTypes.instanceOf(Element) })]),
  /** Whether content takes full available height (for canvas/editors) */
  fullHeight: PropTypes.bool,
  /** Whether to use split layout with side panel */
  splitLayout: PropTypes.bool,
  /** Content for the side panel (right side in split layout) */
  sidePanel: PropTypes.node,
  /** Labels for split header columns */
  splitHeaderLabels: PropTypes.shape({
    left: PropTypes.string,
    right: PropTypes.string,
  }),
};

export default FullModal;
