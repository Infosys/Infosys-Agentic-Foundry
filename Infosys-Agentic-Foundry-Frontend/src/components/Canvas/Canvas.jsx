import React, { useState, useRef, useEffect } from "react";
import styles from "./Canvas.module.css";
import DynamicWidget from "./DynamicWidget";
import SVGIcons from "../../Icons/SVGIcons";

const Canvas = ({ isOpen, onClose, content, contentType = "code", title = "Canvas", messageId = null, is_last, sendUserMessage, selectedAgent }) => {
  const canvasRef = useRef(null);
  const resizeRef = useRef(null);
  const [isMinimized, setIsMinimized] = useState(false);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [isResizing, setIsResizing] = useState(false);
  const [canvasWidth, setCanvasWidth] = useState(null); // null means use CSS default

  // Close canvas when clicking outside
  useEffect(() => {
    const handleClickOutside = (event) => {
      if (canvasRef.current && !canvasRef.current.contains(event.target)) {
        // Only close if clicking outside the canvas area
        if (!event.target.closest(".canvasToggleBtn")) {
          // Don't auto-close for now - let user manually close
          // onClose();
        }
      }
    };

    if (isOpen) {
      document.addEventListener("mousedown", handleClickOutside);
      return () => {
        document.removeEventListener("mousedown", handleClickOutside);
      };
    }
  }, [isOpen, onClose]);
  // Prevent scrolling on body when canvas is open
  useEffect(() => {
    if (isOpen) {
      document.body.style.overflow = "hidden";
    } else {
      document.body.style.overflow = "auto";
    }

    return () => {
      document.body.style.overflow = "auto";
    };
  }, [isOpen]);

  // Resize functionality
  useEffect(() => {
    if (!isResizing) return;

    const handleMouseMove = (e) => {
      if (!canvasRef.current) return;

      // Get the navbar width from CSS variable or use default
      const navWidth = parseInt(getComputedStyle(document.documentElement).getPropertyValue('--main-width') || '180');
      const isNavCollapsed = document.documentElement.getAttribute('data-nav-collapsed') === 'true';
      const effectiveNavWidth = isNavCollapsed ? 50 : navWidth;

      // Calculate available width (viewport - navbar)
      const availableWidth = window.innerWidth - effectiveNavWidth;

      // Calculate new width based on mouse position from right edge
      const newWidth = window.innerWidth - e.clientX;

      // Set minimum and maximum width constraints
      const minWidth = 350;
      const maxWidth = availableWidth * 0.85;

      if (newWidth >= minWidth && newWidth <= maxWidth) {
        setCanvasWidth(newWidth);
      }
    };

    const handleMouseUp = () => {
      setIsResizing(false);
    };

    // Add class to body for global cursor control
    document.body.classList.add("resizing");

    document.addEventListener("mousemove", handleMouseMove);
    document.addEventListener("mouseup", handleMouseUp);

    return () => {
      document.body.classList.remove("resizing");
      document.removeEventListener("mousemove", handleMouseMove);
      document.removeEventListener("mouseup", handleMouseUp);
    };
  }, [isResizing]);

  const handleResizeStart = (e) => {
    e.preventDefault();
    e.stopPropagation();
    setIsResizing(true);
  };

  const handleMinimize = () => {
    setIsMinimized(!isMinimized);
  };

  const handleFullscreen = () => {
    setIsFullscreen(!isFullscreen);
  };

  const handleClose = () => {
    setIsMinimized(false);
    setIsFullscreen(false);
    // Find all other "View details" bubbles and remove the active class
    const allBubbles = document.querySelectorAll(`.canvasIsOpen`);
    if (allBubbles.length > 0) allBubbles[0].classList?.remove("canvasIsOpen");
    onClose();
  };

  if (!isOpen) return null;

  return (
    <div
      className={`${styles.canvasContainer} ${isFullscreen ? styles.fullscreen : ""} ${isMinimized ? styles.minimized : ""} ${isResizing ? styles.isResizing : ""}`}
      ref={canvasRef}
      style={{
        width: isFullscreen ? undefined : isMinimized ? "300px" : canvasWidth ? `${canvasWidth}px` : undefined,
      }}>
      {/* Canvas Header */}
      <div className={styles.canvasHeader}>
        <div className={styles.headerLeft}>
          <SVGIcons icon="canvas-grid" width={18} height={18} stroke="#0073CF" />
          <span className={styles.canvasTitle}>{title}</span>
        </div>

        <div className={styles.headerActions}>
          <button className={styles.actionButton} onClick={handleFullscreen} title={isFullscreen ? "Exit Fullscreen" : "Fullscreen"}>
            {isFullscreen ? (
              <SVGIcons icon="fullscreen-collapse" width={14} height={14} stroke="currentColor" />
            ) : (
              <SVGIcons icon="fullscreen-expand" width={14} height={14} stroke="currentColor" />
            )}
          </button>
          <button className={styles.actionButton} onClick={handleClose} title="Close Canvas">
            <SVGIcons icon="close-canvas" width={14} height={14} stroke="currentColor" />
          </button>
        </div>
      </div>
      {/* Canvas Content */}
      {!isMinimized && (
        <div className={styles.canvasContent}>
          <DynamicWidget
            type={contentType}
            content={content}
            messageId={messageId}
            is_last={is_last}
            sendUserMessage={sendUserMessage}
            isMinimized={isMinimized}
            isFullscreen={isFullscreen}
            selectedAgent={selectedAgent}
          />
        </div>
      )}
      {""}
      {/* Resize Handle */}
      {!isFullscreen && !isMinimized && (
        <div className={styles.resizeHandle} ref={resizeRef} onMouseDown={handleResizeStart}>
          <div className={styles.resizeIndicator}>
            <div className={styles.resizeDot}></div>
            <div className={styles.resizeDot}></div>
            <div className={styles.resizeDot}></div>
          </div>
        </div>
      )}
    </div>
  );
};

export default Canvas;
