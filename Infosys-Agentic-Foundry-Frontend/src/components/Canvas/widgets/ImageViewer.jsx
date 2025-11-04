import React, { useState, useRef, useEffect } from "react";
import styles from "./ImageViewer.module.css";
import SVGIcons from "../../../Icons/SVGIcons";

import { BASE_URL } from "../../../constant";
import Cookies from "js-cookie";

// Constants for magic numbers
const ZOOM_STEP = 1.25;
const ZOOM_MIN = 0.25;
const ZOOM_MAX = 5;
const ZOOM_PERCENT = 100;

// Utility to resolve image URL: if public, use as is; else prepend BASE_URL
function resolveImageUrl(path) {
  // If path is absolute (starts with http/https), use as is
  if (/^https?:\/\//.test(path)) {
    return path;
  }
  // If path starts with '/' or 'user_uploads/', prepend BASE_URL
  if (path.startsWith('/')) {
    return BASE_URL ? `${BASE_URL.replace(/\/$/, "")}${path}` : path;
  }
  if (path.startsWith('user_uploads/')) {
    return BASE_URL ? `${BASE_URL.replace(/\/$/, "")}/${path}` : `/${path}`;
  }
  // Otherwise, return as is
  return path;
}

const ImageViewer = ({ content, messageId }) => {
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState(null);
  // Removed unused isZoomed and setIsZoomed
  const [zoomLevel, setZoomLevel] = useState(1);
  const [position, setPosition] = useState({ x: 0, y: 0 });
  const [isDragging, setIsDragging] = useState(false);
  const [dragStart, setDragStart] = useState({ x: 0, y: 0 });
  const [protectedImageUrl, setProtectedImageUrl] = useState(null);
  const imageRef = useRef(null);
  const containerRef = useRef(null);

  // Handle different content formats

  // Utility: Parse markdown image ![alt](src)
  const MARKDOWN_ALT_GROUP = 1;
  const MARKDOWN_SRC_GROUP = 2;
  const parseMarkdownImage = (str) => {
    const match = str.match(/!\[([^\]]*)\]\(([^)]+)\)/);
    if (match) {
      return { src: match[MARKDOWN_SRC_GROUP], alt: match[MARKDOWN_ALT_GROUP] };
    }
    return null;
  };

  // Enhanced getImageSrc: supports string, object, and markdown, and resolves with public/backend logic
  const getImageData = () => {
    let src = null;
    let alt = "";
    if (typeof content === "string") {
      // Markdown image fallback
      const md = parseMarkdownImage(content);
      if (md) {
        src = resolveImageUrl(md.src);
        alt = md.alt;
      } else if (content.startsWith("data:image/")) {
        src = content;
      } else if (content.match(/^[A-Za-z0-9+/]+={0,2}$/)) {
        src = `data:image/png;base64,${content}`;
      } else if (content.startsWith("http")) {
        src = content;
      } else if (content.startsWith("/")) {
        src = resolveImageUrl(content);
      }
    } else if (typeof content === "object" && content.src) {
      // Always use alt from object if present
      src = resolveImageUrl(content.src);
      alt = typeof content.alt === "string" ? content.alt : "";
    }
    return { src, alt };
  };

  // Always resolve imageSrc with BASE_URL if it starts with '/'
  const { src: initialImageSrc, alt: imageAlt } = getImageData(); // Declare imageAlt here
  let imageSrc = initialImageSrc;
  if (imageSrc && imageSrc.startsWith('/')) {
    imageSrc = resolveImageUrl(imageSrc);
  }

  // Handle image load and error
  const handleImageLoad = () => {
    setIsLoading(false);
    setError(null);
  };

  const handleImageError = (e) => {
    setIsLoading(false);
    setError("Failed to load image.");
  };

  // Unified logic: handle data/blob/public/backend/protected images
  useEffect(() => {
    let objectUrl = null;
    setProtectedImageUrl(null);
    setIsLoading(true);
    setError(null);

    if (!imageSrc) {
      setIsLoading(false);
      return;
    }

    // 1. Data URL or blob: use directly
    if (imageSrc.startsWith("data:image/") || imageSrc.startsWith("blob:")) {
      setProtectedImageUrl(null);
      setIsLoading(false);
      return;
    }

    // 2. Public absolute URL (not backend): use directly
    const isAbsolute = /^https?:\/\//.test(imageSrc);
    const isBackend = BASE_URL && imageSrc.startsWith(BASE_URL.replace(/\/$/, ""));
    if (isAbsolute && !isBackend) {
      setProtectedImageUrl(null);
      setIsLoading(false);
      return;
    }

    // 3. Protected backend route (e.g., /utility/files/) or any backend/relative image: fetch as blob with JWT
    const isProtected = (
      typeof imageSrc === "string" &&
      (
        imageSrc.includes("/utility/files/") ||
        isBackend ||
        imageSrc.startsWith("/") ||
        imageSrc.startsWith("user_uploads/")
      )
    );

    if (isProtected) {
      const jwtToken = Cookies.get("jwt-token");
      const fetchUrl = imageSrc.startsWith("/") ? resolveImageUrl(imageSrc) : imageSrc;
      const fetchOptions = {
        credentials: "include",
        headers: jwtToken ? { Authorization: `Bearer ${jwtToken}` } : {},
      };
      fetch(fetchUrl, fetchOptions)
        .then((response) => {
          if (!response.ok) throw new Error("Failed to fetch image");
          return response.blob();
        })
        .then((blob) => {
          objectUrl = URL.createObjectURL(blob);
          setProtectedImageUrl(objectUrl);
          setIsLoading(false);
        })
        .catch((err) => {
          setProtectedImageUrl(null);
          setIsLoading(false);
          setError(
            imageAlt && imageAlt.trim()
              ? `Failed to load image: ${imageAlt}`
              : 'Failed to load image.'
          );
        });
      return () => {
        if (objectUrl) URL.revokeObjectURL(objectUrl);
      };
    }

    // 4. Fallback: use direct src
    setProtectedImageUrl(null);
    setIsLoading(false);
  }, [imageSrc, imageAlt]);

  const handleZoomIn = () => {
    setZoomLevel(prev => Math.min(prev * ZOOM_STEP, ZOOM_MAX));
  };

  const handleZoomOut = () => {
    setZoomLevel(prev => Math.max(prev / ZOOM_STEP, ZOOM_MIN));
  };

  const handleResetZoom = () => {
    setZoomLevel(1);
    setPosition({ x: 0, y: 0 });
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
      // Prefer protectedImageUrl if available
      const downloadUrl = protectedImageUrl || imageSrc;
      // If it's a blob/object URL, just download it
      if (downloadUrl.startsWith('blob:') || downloadUrl.startsWith('data:image/')) {
        const link = document.createElement('a');
        link.href = downloadUrl;
        link.download = `image-${messageId || Date.now()}.png`;
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        return;
      }
      // Otherwise, fetch and download
      const response = await fetch(downloadUrl, { credentials: 'include' });
      if (!response.ok) {
        throw new Error(`Failed to fetch image: ${response.statusText}`);
      }
      const blob = await response.blob();
      const url = window.URL.createObjectURL(blob);
      const contentType = response.headers.get('content-type') || 'image/png';
      const extension = contentType.split('/')[1] || 'png';
      const link = document.createElement('a');
      link.href = url;
      link.download = `image-${messageId || Date.now()}.${extension}`;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      window.URL.revokeObjectURL(url);
    } catch (error) {
      console.error('Download failed:', error);
      const link = document.createElement('a');
      link.href = imageSrc;
      link.download = `image-${messageId || Date.now()}.png`;
      link.target = '_blank';
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
            disabled={zoomLevel <= ZOOM_MIN}
          >
            <svg width="16" height="16" viewBox="0 0 20 20" fill="none">
              <circle cx="9" cy="9" r="7" stroke="#666" strokeWidth="1.5"/>
              <path d="M6 9h6" stroke="#666" strokeWidth="1.5" strokeLinecap="round"/>
              <path d="M21 21l-4.35-4.35" stroke="#666" strokeWidth="1.5" strokeLinecap="round"/>
            </svg>
          </button>
          
          <span className={styles.zoomLevel}>{Math.round(zoomLevel * ZOOM_PERCENT)}%</span>
          
          <button
            className={styles.toolbarButton}
            onClick={handleZoomIn}
            title="Zoom In"
            disabled={zoomLevel >= ZOOM_MAX}
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
        className={styles.imageContainer}
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
        
        {/* Only render image if not loading and no error */}
        {!isLoading && !error && (
          <img
            ref={imageRef}
            src={protectedImageUrl || imageSrc}
            alt={imageAlt}
            className={styles.image}
            onLoad={handleImageLoad}
            onError={handleImageError}
            style={{
              transform: `scale(${zoomLevel}) translate(${position.x / zoomLevel}px, ${position.y / zoomLevel}px)`,
              transformOrigin: "center",
              transition: isDragging ? "none" : "transform 0.2s ease",
              display: "block"
            }}
            draggable={false}
          />
        )}
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
          <span>{zoomLevel !== 1 ? `${Math.round(zoomLevel * ZOOM_PERCENT)}% zoom` : "Fit to view"}</span>
        </div>
      </div>
    </div>

  );
}
export default ImageViewer;
