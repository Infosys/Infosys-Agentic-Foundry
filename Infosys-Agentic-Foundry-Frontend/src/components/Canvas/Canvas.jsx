import React, { useState, useRef, useEffect } from "react";
import styles from "./Canvas.module.css";
import SVGIcons from "../../Icons/SVGIcons";
import DynamicWidget from "./DynamicWidget";

const Canvas = ({ isOpen, onClose, content, contentType = "code", title = "Canvas", messageId = null }) => {
  const canvasRef = useRef(null);
  const resizeRef = useRef(null);
  const [isMinimized, setIsMinimized] = useState(false);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [isResizing, setIsResizing] = useState(false);
  const [canvasWidth, setCanvasWidth] = useState(600); // Default width

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
    const handleMouseMove = (e) => {
      if (!isResizing || !canvasRef.current) return;

      const canvasRect = canvasRef.current.getBoundingClientRect();
      const newWidth = window.innerWidth - e.clientX;

      // Set minimum and maximum width constraints
      const minWidth = 300;
      const maxWidth = window.innerWidth * 0.8;

      if (newWidth >= minWidth && newWidth <= maxWidth) {
        setCanvasWidth(newWidth);
      }
    };

    const handleMouseUp = () => {
      setIsResizing(false);
      document.body.style.cursor = "default";
      document.body.style.userSelect = "auto";
    };

    if (isResizing) {
      document.body.style.cursor = "col-resize";
      document.body.style.userSelect = "none";
      document.addEventListener("mousemove", handleMouseMove);
      document.addEventListener("mouseup", handleMouseUp);
    }

    return () => {
      document.removeEventListener("mousemove", handleMouseMove);
      document.removeEventListener("mouseup", handleMouseUp);
    };
  }, [isResizing]);

  const handleResizeStart = (e) => {
    e.preventDefault();
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
      className={`${styles.canvasContainer} ${isFullscreen ? styles.fullscreen : ""} ${isMinimized ? styles.minimized : ""}`}
      ref={canvasRef}
      style={{
        width: isFullscreen ? "100vw" : isMinimized ? "300px" : `${canvasWidth}px`,
      }}>
      {/* Canvas Header */}
      <div className={styles.canvasHeader}>
        <div className={styles.headerLeft}>
          <SVGIcons icon="hardware-chip" width={18} height={18} fill="#007acc" />
          <span className={styles.canvasTitle}>{title}</span>
        </div>

        <div className={styles.headerActions}>
          {/* <button
            className={styles.actionButton}
            onClick={handleMinimize}
            title={isMinimized ? "Expand" : "Minimize"}
          >
            {isMinimized ? (
              <SVGIcons icon="fa-plus" width={12} height={12} fill="#666" />
            ) : (
              <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
                <line x1="2" y1="6" x2="10" y2="6" stroke="#666" strokeWidth="1.5" strokeLinecap="round"/>
              </svg>
            )}
          </button> */}

          <button className={styles.actionButton} onClick={handleFullscreen} title={isFullscreen ? "Exit Fullscreen" : "Fullscreen"}>
            {isFullscreen ? (
              <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
                <path d="M8 4L4 4L4 8" stroke="#666" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
                <path d="M4 4L8 8" stroke="#666" strokeWidth="1.5" strokeLinecap="round" />
              </svg>
            ) : (
              <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
                <path d="M2 4L2 2L4 2" stroke="#666" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
                <path d="M10 4L10 2L8 2" stroke="#666" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
                <path d="M10 8L10 10L8 10" stroke="#666" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
                <path d="M2 8L2 10L4 10" stroke="#666" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            )}
          </button>

          <button className={styles.actionButton} onClick={handleClose} title="Close Canvas">
            <SVGIcons icon="fa-xmark" width={12} height={12} fill="#666" />
          </button>
        </div>
      </div>
      {/* Canvas Content */}
      {!isMinimized && (
        <div className={styles.canvasContent}>
          <DynamicWidget type={contentType} content={content} messageId={messageId} />
        </div>
      )}{" "}
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
