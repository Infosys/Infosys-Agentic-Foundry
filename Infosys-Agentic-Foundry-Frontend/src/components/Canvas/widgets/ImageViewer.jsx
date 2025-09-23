import React, { useState, useRef } from "react";
import styles from "./ImageViewer.module.css";
import SVGIcons from "../../../Icons/SVGIcons";

const ImageViewer = ({ content, messageId }) => {
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState(null);
  const [isZoomed, setIsZoomed] = useState(false);
  const [zoomLevel, setZoomLevel] = useState(1);
  const [position, setPosition] = useState({ x: 0, y: 0 });
  const [isDragging, setIsDragging] = useState(false);
  const [dragStart, setDragStart] = useState({ x: 0, y: 0 });
  const imageRef = useRef(null);
  const containerRef = useRef(null);

  // Handle different content formats
  const getImageSrc = () => {
    if (typeof content === "string") {
      // Handle base64 encoded images
      if (content.startsWith("data:image/")) {
        return content;
      }
      // Handle URLs
      if (content.startsWith("http") || content.startsWith("/")) {
        return content;
      }
      // Handle base64 without data URL prefix
      if (content.match(/^[A-Za-z0-9+/]+={0,2}$/)) {
        return `data:image/png;base64,${content}`;
      }
    }
    
    // Handle object format with src property
    if (typeof content === "object" && content.src) {
      return content.src;
    }
    
    return null;
  };

  const imageSrc = getImageSrc();
  const imageAlt = content.alt;

  const handleImageLoad = () => {
    setIsLoading(false);
    setError(null);
  };

  const handleImageError = () => {
    setIsLoading(false);
    setError("Failed to load image");
  };

  const handleZoomIn = () => {
    setZoomLevel(prev => Math.min(prev * 1.25, 5));
  };

  const handleZoomOut = () => {
    setZoomLevel(prev => Math.max(prev / 1.25, 0.25));
  };

  const handleResetZoom = () => {
    setZoomLevel(1);
    setPosition({ x: 0, y: 0 });
  };

  const toggleFullscreen = () => {
    setIsZoomed(!isZoomed);
    if (isZoomed) {
      handleResetZoom();
    }
  };

  const handleMouseDown = (e) => {
    if (zoomLevel > 1) {
      setIsDragging(true);
      setDragStart({
        x: e.clientX - position.x,
        y: e.clientY - position.y,
      });
      e.preventDefault();
    }
  };

  const handleMouseMove = (e) => {
    if (isDragging && zoomLevel > 1) {
      setPosition({
        x: e.clientX - dragStart.x,
        y: e.clientY - dragStart.y,
      });
    }
  };

  const handleMouseUp = () => {
    setIsDragging(false);
  };

  const handleDownload = async () => {
    if (!imageSrc) return;

    try {
      // For base64 images, we can download directly
      if (imageSrc.startsWith("data:image/")) {
        const link = document.createElement("a");
        link.href = imageSrc;
        link.download = `image-${messageId || Date.now()}.png`;
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        return;
      }

      // For external URLs, fetch the image to avoid CORS issues
      const response = await fetch(imageSrc);
      
      if (!response.ok) {
        throw new Error(`Failed to fetch image: ${response.statusText}`);
      }

      const blob = await response.blob();
      const url = window.URL.createObjectURL(blob);
      
      // Get file extension from content type or default to png
      const contentType = response.headers.get("content-type") || "image/png";
      const extension = contentType.split("/")[1] || "png";
      
      const link = document.createElement("a");
      link.href = url;
      link.download = `image-${messageId || Date.now()}.${extension}`;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      
      // Clean up the blob URL
      window.URL.revokeObjectURL(url);
    } catch (error) {
      console.error("Download failed:", error);
      const link = document.createElement("a");
      link.href = imageSrc;
      link.download = `image-${messageId || Date.now()}.png`;
      link.target = "_blank"; // Open in new tab if download fails
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
    }
  };


  return (
    <div className={styles.imageViewer}>
      {/* Toolbar */}
      <div className={styles.toolbar}>
        <div className={styles.toolbarLeft}>
          {/* <div className={styles.contentTag}>
            <SVGIcons icon="fa-image" width={14} height={14} fill="#007acc" />
            <span>Image</span>
          </div> */}
          <span className={styles.imageTitle}>{imageAlt}</span>
        </div>
        
        <div className={styles.toolbarActions}>
          <button
            className={styles.toolbarButton}
            onClick={handleZoomOut}
            title="Zoom Out"
            disabled={zoomLevel <= 0.25}
          >
            <svg width="16" height="16" viewBox="0 0 20 20" fill="none">
              <circle cx="9" cy="9" r="7" stroke="#666" strokeWidth="1.5"/>
              <path d="M6 9h6" stroke="#666" strokeWidth="1.5" strokeLinecap="round"/>
              <path d="M21 21l-4.35-4.35" stroke="#666" strokeWidth="1.5" strokeLinecap="round"/>
            </svg>
          </button>
          
          <span className={styles.zoomLevel}>{Math.round(zoomLevel * 100)}%</span>
          
          <button
            className={styles.toolbarButton}
            onClick={handleZoomIn}
            title="Zoom In"
            disabled={zoomLevel >= 5}
          >
            <svg width="16" height="16" viewBox="0 0 20 20" fill="none">
              <circle cx="9" cy="9" r="7" stroke="#666" strokeWidth="1.5"/>
              <path d="M6 9h6M9 6v6" stroke="#666" strokeWidth="1.5" strokeLinecap="round"/>
              <path d="M21 21l-4.35-4.35" stroke="#666" strokeWidth="1.5" strokeLinecap="round"/>
            </svg>
          </button>
          
          <button
            className={styles.toolbarButton}
            onClick={handleResetZoom}
            title="Reset Zoom"
          >
            <svg width="16" height="16" viewBox="0 0 20 20" fill="none">
              <path d="M4 12v4h4M16 8V4h-4M4 16l6-6M20 4l-6 6" 
                stroke="#666" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
            </svg>
          </button>
          
          <div className={styles.separator}></div>
          
          <button
            className={styles.toolbarButton}
            onClick={handleDownload}
            title="Download Image"
          >
            <svg width="16" height="16" viewBox="0 0 20 20" fill="none">
              <path d="M10 13V3M7 10L10 13L13 10M5 17H15" 
                stroke="#666" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
            </svg>
          </button>
          
        </div>
      </div>

      {/* Image Container */}
      <div 
        className={`${styles.imageContainer} ${isZoomed ? styles.fullscreen : ""}`}
        ref={containerRef}
        onMouseDown={handleMouseDown}
        onMouseMove={handleMouseMove}
        onMouseUp={handleMouseUp}
        onMouseLeave={handleMouseUp}
        style={{ cursor: zoomLevel > 1 ? (isDragging ? "grabbing" : "grab") : "default" }}
      >
        {isLoading && (
          <div className={styles.loadingState}>
            <div className={styles.spinner}></div>
            <p>Loading image...</p>
          </div>
        )}
        
        {error && (
          <div className={styles.errorState}>
            <SVGIcons icon="fa-exclamation-triangle" width={48} height={48} fill="#dc2626" />
            <p className={styles.errorMessage}>{error}</p>
          </div>
        )}
        
        <img
          ref={imageRef}
          src={imageSrc}
          alt={imageAlt}
          className={styles.image}
          onLoad={handleImageLoad}
          onError={handleImageError}
          style={{
            transform: `scale(${zoomLevel}) translate(${position.x / zoomLevel}px, ${position.y / zoomLevel}px)`,
            transformOrigin: "center",
            transition: isDragging ? "none" : "transform 0.2s ease",
            display: isLoading || error ? "none" : "block"
          }}
          draggable={false}
        />
      </div>
      
      {/* Footer with image info */}
      <div className={styles.footer}>
        <div className={styles.imageInfo}>
          {imageRef.current && (
            <>
              <span>{imageRef.current.naturalWidth} × {imageRef.current.naturalHeight}</span>
              <span className={styles.separator}>•</span>
            </>
          )}
          <span>{zoomLevel !== 1 ? `${Math.round(zoomLevel * 100)}% zoom` : "Fit to view"}</span>
        </div>
      </div>
    </div>
  );
};

export default ImageViewer;
