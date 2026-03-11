import { useEffect, useState, useRef, useCallback } from "react";
import DOMPurify from "dompurify";
import styles from "./DocViewerModal.module.css";
import mammoth from "mammoth";
import parse from "html-react-parser";
import * as XLSX from "xlsx";
import { useMessage } from "../../Hooks/MessageContext";
import axios from "axios";
import { APIs, BASE_URL } from "../../constant";
import Cookies from "js-cookie";
import Loader from "../commonComponents/Loader";
import SVGIcons from "../../Icons/SVGIcons";

/**
 * Parse CSV string into array of arrays
 * @param {string} csvText - Raw CSV text
 * @returns {Array<Array<string>>} Parsed CSV data
 */
const parseCSV = (csvText) => {
  const rows = [];
  const lines = csvText.split(/\r?\n/);

  for (const line of lines) {
    if (line.trim() === "") continue;

    const row = [];
    let cell = "";
    let insideQuotes = false;

    for (let i = 0; i < line.length; i++) {
      const char = line[i];

      if (char === '"') {
        if (insideQuotes && line[i + 1] === '"') {
          cell += '"';
          i++;
        } else {
          insideQuotes = !insideQuotes;
        }
      } else if (char === "," && !insideQuotes) {
        row.push(cell.trim());
        cell = "";
      } else {
        cell += char;
      }
    }
    row.push(cell.trim());
    rows.push(row);
  }

  return rows;
};

/**
 * Render JSON with syntax highlighting
 * @param {any} data - JSON data to render
 * @param {number} indent - Current indentation level
 * @returns {JSX.Element} Highlighted JSON
 */
const renderJsonValue = (data, indent = 0) => {
  if (data === null) {
    return <span className={styles.jsonNull}>null</span>;
  }

  if (typeof data === "boolean") {
    return <span className={styles.jsonBoolean}>{data.toString()}</span>;
  }

  if (typeof data === "number") {
    return <span className={styles.jsonNumber}>{data}</span>;
  }

  if (typeof data === "string") {
    return <span className={styles.jsonString}>"{data}"</span>;
  }

  if (Array.isArray(data)) {
    if (data.length === 0) {
      return <span className={styles.jsonBracket}>[]</span>;
    }

    return (
      <span>
        <span className={styles.jsonBracket}>[</span>
        <div className={styles.jsonIndent}>
          {data.map((item, idx) => (
            <div key={idx} className={styles.jsonLine}>
              {renderJsonValue(item, indent + 1)}
              {idx < data.length - 1 && <span className={styles.jsonComma}>,</span>}
            </div>
          ))}
        </div>
        <span className={styles.jsonBracket}>]</span>
      </span>
    );
  }

  if (typeof data === "object") {
    const keys = Object.keys(data);
    if (keys.length === 0) {
      return <span className={styles.jsonBracket}>{"{}"}</span>;
    }

    return (
      <span>
        <span className={styles.jsonBracket}>{"{"}</span>
        <div className={styles.jsonIndent}>
          {keys.map((key, idx) => (
            <div key={key} className={styles.jsonLine}>
              <span className={styles.jsonKey}>"{key}"</span>
              <span className={styles.jsonColon}>: </span>
              {renderJsonValue(data[key], indent + 1)}
              {idx < keys.length - 1 && <span className={styles.jsonComma}>,</span>}
            </div>
          ))}
        </div>
        <span className={styles.jsonBracket}>{"}"}</span>
      </span>
    );
  }

  return <span>{String(data)}</span>;
};

/**
 * Get file type from filename or URL
 * @param {string} url - The file URL or filename
 * @returns {string} File type: 'pdf', 'docx', 'image', 'text', or 'unknown'
 */
const getFileType = (url) => {
  if (!url) return "unknown";
  const lowerUrl = url.toLowerCase();

  // Check for blob URLs - need to extract type from content-type or filename prop
  if (lowerUrl.startsWith("blob:")) {
    return "blob";
  }

  // PDF
  if (lowerUrl.endsWith(".pdf") || (lowerUrl.includes("filename=") && lowerUrl.includes(".pdf"))) {
    return "pdf";
  }

  // DOCX
  if (lowerUrl.endsWith(".docx") || (lowerUrl.includes("filename=") && lowerUrl.includes(".docx"))) {
    return "docx";
  }

  // Images
  const imageExtensions = [".jpg", ".jpeg", ".png", ".gif", ".bmp", ".svg", ".webp", ".ico"];
  for (const ext of imageExtensions) {
    if (lowerUrl.endsWith(ext) || (lowerUrl.includes("filename=") && lowerUrl.includes(ext))) {
      return "image";
    }
  }

  // JSON files
  if (lowerUrl.endsWith(".json") || (lowerUrl.includes("filename=") && lowerUrl.includes(".json"))) {
    return "json";
  }

  // CSV files
  if (lowerUrl.endsWith(".csv") || (lowerUrl.includes("filename=") && lowerUrl.includes(".csv"))) {
    return "csv";
  }

  // Excel files (xlsx, xls)
  if (lowerUrl.endsWith(".xlsx") || lowerUrl.endsWith(".xls") || (lowerUrl.includes("filename=") && (lowerUrl.includes(".xlsx") || lowerUrl.includes(".xls")))) {
    return "xlsx";
  }

  // Text files
  const textExtensions = [".txt", ".xml", ".md", ".log"];
  for (const ext of textExtensions) {
    if (lowerUrl.endsWith(ext) || (lowerUrl.includes("filename=") && lowerUrl.includes(ext))) {
      return "text";
    }
  }

  return "unknown";
};

/**
 * Get file type from filename prop
 */
const getFileTypeFromName = (fileName) => {
  if (!fileName) return "unknown";
  const lowerName = fileName.toLowerCase();

  if (lowerName.endsWith(".pdf")) return "pdf";
  if (lowerName.endsWith(".docx")) return "docx";

  const imageExtensions = [".jpg", ".jpeg", ".png", ".gif", ".bmp", ".svg", ".webp", ".ico"];
  for (const ext of imageExtensions) {
    if (lowerName.endsWith(ext)) return "image";
  }

  // JSON
  if (lowerName.endsWith(".json")) return "json";

  // CSV
  if (lowerName.endsWith(".csv")) return "csv";

  // Excel files
  if (lowerName.endsWith(".xlsx") || lowerName.endsWith(".xls")) return "xlsx";

  // Text files
  const textExtensions = [".txt", ".xml", ".md", ".log"];
  for (const ext of textExtensions) {
    if (lowerName.endsWith(ext)) return "text";
  }

  return "unknown";
};

/**
 * DocViewerModal - A robust document viewer supporting PDF, DOCX, images, and text files
 *
 * @param {Object} props
 * @param {string} props.url - The URL or blob URL of the file to view
 * @param {string} props.fileName - Optional filename to help determine file type
 * @param {function} props.onClose - Callback when modal is closed
 */
const DocViewerModal = ({ url, fileName, onClose }) => {
  const [blobUrl, setBlobUrl] = useState(null);
  const [docxHtml, setDocxHtml] = useState(null);
  const [textContent, setTextContent] = useState(null);
  const [jsonData, setJsonData] = useState(null);
  const [csvData, setCsvData] = useState(null);
  const [xlsxData, setXlsxData] = useState(null);
  const [activeSheet, setActiveSheet] = useState(0);
  const [imageUrl, setImageUrl] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);
  const [zoom, setZoom] = useState(100);

  const messageContext = useMessage();
  const addMessage = messageContext?.addMessage;

  // Use ref to track if fetch has been done - prevents multiple fetches
  const hasFetchedRef = useRef(false);
  const abortControllerRef = useRef(null);

  // Determine file type from URL or fileName
  const fileType = fileName ? getFileTypeFromName(fileName) : getFileType(url);

  // Handle zoom for images
  const handleZoomIn = useCallback(() => {
    setZoom((prev) => Math.min(prev + 25, 300));
  }, []);

  const handleZoomOut = useCallback(() => {
    setZoom((prev) => Math.max(prev - 25, 25));
  }, []);

  const handleZoomReset = useCallback(() => {
    setZoom(100);
  }, []);

  // Cleanup function
  const cleanup = useCallback(() => {
    if (blobUrl && !url?.startsWith("blob:")) {
      URL.revokeObjectURL(blobUrl);
    }
    if (imageUrl && !url?.startsWith("blob:")) {
      URL.revokeObjectURL(imageUrl);
    }
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
    }
  }, [blobUrl, imageUrl, url]);

  useEffect(() => {
    // Prevent multiple fetches
    if (hasFetchedRef.current) {
      return;
    }
    hasFetchedRef.current = true;

    // Create abort controller for cleanup
    abortControllerRef.current = new AbortController();
    const signal = abortControllerRef.current.signal;

    const fetchDocument = async () => {
      setLoading(true);
      setError(null);

      try {
        // If URL is already a blob URL, use it directly
        if (url?.startsWith("blob:")) {
          if (fileType === "pdf") {
            setBlobUrl(url);
          } else if (fileType === "image") {
            setImageUrl(url);
          } else if (fileType === "docx") {
            // For blob DOCX, we need to fetch and convert
            const response = await fetch(url);
            const blob = await response.blob();
            const arrayBuffer = await blob.arrayBuffer();
            const result = await mammoth.convertToHtml({ arrayBuffer });
            setDocxHtml(DOMPurify.sanitize(result.value));
          } else if (fileType === "text") {
            const response = await fetch(url);
            const text = await response.text();
            setTextContent(text);
          } else if (fileType === "json") {
            const response = await fetch(url);
            const text = await response.text();
            try {
              const parsed = JSON.parse(text);
              setJsonData(parsed);
            } catch {
              setTextContent(text); // Fallback to text if parse fails
            }
          } else if (fileType === "csv") {
            const response = await fetch(url);
            const text = await response.text();
            setCsvData(parseCSV(text));
          } else if (fileType === "xlsx") {
            const response = await fetch(url);
            const blob = await response.blob();
            const arrayBuffer = await blob.arrayBuffer();
            const workbook = XLSX.read(arrayBuffer, { type: "array" });
            const sheets = workbook.SheetNames.map((name) => ({
              name,
              data: XLSX.utils.sheet_to_json(workbook.Sheets[name], { header: 1 }),
            }));
            setXlsxData(sheets);
            setActiveSheet(0);
          } else {
            // Try to detect from content
            setBlobUrl(url);
          }
          setLoading(false);
          return;
        }

        // Build the full URL
        let fileUrl;
        if (url.startsWith("http://") || url.startsWith("https://")) {
          fileUrl = url;
        } else if (url.startsWith(APIs.DOWNLOAD_FILE)) {
          fileUrl = BASE_URL + url;
        } else {
          fileUrl = `${BASE_URL}${APIs.DOWNLOAD_FILE}?filename=${encodeURIComponent(url)}`;
        }

        // Get auth token
        const jwtToken = Cookies.get("jwt-token");
        const headers = jwtToken ? { Authorization: `Bearer ${jwtToken}` } : {};

        // Determine response type based on file type
        let responseType = "arraybuffer";
        if (fileType === "text" || fileType === "json" || fileType === "csv") {
          responseType = "text";
        }

        // Single fetch request
        const response = await axios.get(fileUrl, {
          responseType,
          headers,
          signal,
        });

        // Check if request was aborted
        if (signal.aborted) return;

        const contentType = response.headers["content-type"] || "";

        // Handle based on file type
        if (fileType === "pdf") {
          if (typeof response.data === "string" || contentType.includes("application/json")) {
            setError("PDF preview not available. File may be corrupted or inaccessible.");
            return;
          }
          const blob = new Blob([response.data], { type: "application/pdf" });
          setBlobUrl(URL.createObjectURL(blob));
        } else if (fileType === "docx") {
          if (typeof response.data === "string" || contentType.includes("application/json")) {
            setError("DOCX preview not available. File may be corrupted or inaccessible.");
            return;
          }
          const result = await mammoth.convertToHtml({ arrayBuffer: response.data });
          setDocxHtml(DOMPurify.sanitize(result.value));
        } else if (fileType === "image") {
          const blob = new Blob([response.data], { type: contentType || "image/png" });
          setImageUrl(URL.createObjectURL(blob));
        } else if (fileType === "json") {
          try {
            const parsed = JSON.parse(response.data);
            setJsonData(parsed);
          } catch {
            setTextContent(response.data); // Fallback to text if parse fails
          }
        } else if (fileType === "csv") {
          setCsvData(parseCSV(response.data));
        } else if (fileType === "xlsx") {
          const workbook = XLSX.read(response.data, { type: "array" });
          const sheets = workbook.SheetNames.map((name) => ({
            name,
            data: XLSX.utils.sheet_to_json(workbook.Sheets[name], { header: 1 }),
          }));
          setXlsxData(sheets);
          setActiveSheet(0);
        } else if (fileType === "text") {
          setTextContent(response.data);
        } else {
          // Try to auto-detect based on content-type
          if (contentType.includes("pdf")) {
            const blob = new Blob([response.data], { type: "application/pdf" });
            setBlobUrl(URL.createObjectURL(blob));
          } else if (contentType.includes("image")) {
            const blob = new Blob([response.data], { type: contentType });
            setImageUrl(URL.createObjectURL(blob));
          } else if (contentType.includes("text") || contentType.includes("json")) {
            const decoder = new TextDecoder();
            setTextContent(decoder.decode(response.data));
          } else {
            setError("Preview not available for this file type.");
          }
        }
      } catch (err) {
        if (err.name === "AbortError" || err.name === "CanceledError") {
          return; // Request was cancelled, don't show error
        }
        console.error("DocViewerModal fetch error:", err);
        setError("Failed to load file preview. Please try again.");
        if (addMessage) {
          addMessage("Failed to load file preview", "error");
        }
      } finally {
        if (!signal.aborted) {
          setLoading(false);
        }
      }
    };

    fetchDocument();

    // Cleanup on unmount
    return () => {
      if (abortControllerRef.current) {
        abortControllerRef.current.abort();
      }
      hasFetchedRef.current = false;
    };
  }, [url, fileName, fileType, addMessage]);

  // Cleanup blob URLs on unmount
  useEffect(() => {
    return () => {
      cleanup();
    };
  }, [cleanup]);

  const handleClose = (e) => {
    e.stopPropagation();
    cleanup();
    onClose();
  };

  const handleOverlayClick = (e) => {
    e.stopPropagation();
    cleanup();
    onClose();
  };

  return (
    <div className={styles.overlay} onClick={handleOverlayClick}>
      {loading && (
        <div className={styles.loaderContainer}>
          <Loader />
        </div>
      )}

      <div className={styles.modal} onClick={(e) => e.stopPropagation()}>
        {/* Header with file info and controls */}
        <div className={styles.modalHeader}>
          <div className={styles.headerLeft}>
            <span className={styles.fileName}>{fileName || "Document Preview"}</span>
            {fileType !== "unknown" && <span className={styles.fileType}>{fileType.toUpperCase()}</span>}
          </div>
          <div className={styles.headerRight}>
            {/* Zoom controls for images */}
            {fileType === "image" && imageUrl && !loading && !error && (
              <div className={styles.zoomControls}>
                <button type="button" className={styles.zoomButton} onClick={handleZoomOut} title="Zoom Out">
                  <SVGIcons icon="fa-minus" width={16} height={16} color="var(--content-color, #6B7280)" />
                </button>
                <span className={styles.zoomLevel}>{zoom}%</span>
                <button type="button" className={styles.zoomButton} onClick={handleZoomIn} title="Zoom In">
                  <SVGIcons icon="fa-plus" width={16} height={16} color="var(--content-color, #6B7280)" />
                </button>
                <button type="button" className={styles.zoomButton} onClick={handleZoomReset} title="Reset Zoom">
                  <SVGIcons icon="refresh" width={16} height={16} color="var(--content-color, #6B7280)" />
                </button>
              </div>
            )}
            <button className={styles.closeButtonInner} onClick={handleClose} title="Close">
              <SVGIcons icon="x" width={20} height={20} color="var(--content-color, #6B7280)" />
            </button>
          </div>
        </div>

        {/* Content area */}
        <div className={styles.contentArea}>
          {/* PDF Viewer */}
          {!loading && fileType === "pdf" && blobUrl && !error && <iframe src={blobUrl} title="PDF Viewer" className={styles.iframe} />}

          {/* DOCX Viewer */}
          {!loading && fileType === "docx" && docxHtml && !error && <div className={styles.docxContainer}>{parse(DOMPurify.sanitize(docxHtml))}</div>}

          {/* Image Viewer */}
          {!loading && fileType === "image" && imageUrl && !error && (
            <div className={styles.imageContainer}>
              <img src={imageUrl} alt={fileName || "Image Preview"} className={styles.imagePreview} style={{ transform: `scale(${zoom / 100})` }} />
            </div>
          )}

          {/* Text Viewer */}
          {!loading && fileType === "text" && textContent !== null && !error && (
            <div className={styles.textContainer}>
              <pre className={styles.textContent}>{textContent}</pre>
            </div>
          )}

          {/* JSON Viewer */}
          {!loading && fileType === "json" && jsonData !== null && !error && (
            <div className={styles.jsonContainer}>
              <div className={styles.jsonContent}>{renderJsonValue(jsonData)}</div>
            </div>
          )}

          {/* CSV Viewer */}
          {!loading && fileType === "csv" && csvData !== null && !error && (
            <div className={styles.csvContainer}>
              <table className={styles.csvTable}>
                <thead>
                  <tr>
                    {csvData[0]?.map((header, idx) => (
                      <th key={idx} className={styles.csvHeader}>
                        {header}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {csvData.slice(1).map((row, rowIdx) => (
                    <tr key={rowIdx} className={rowIdx % 2 === 0 ? styles.csvRowEven : styles.csvRowOdd}>
                      {row.map((cell, cellIdx) => (
                        <td key={cellIdx} className={styles.csvCell}>
                          {cell}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {/* Excel (XLSX) Viewer */}
          {!loading && fileType === "xlsx" && xlsxData !== null && !error && (
            <div className={styles.csvContainer}>
              {/* Sheet tabs for multi-sheet workbooks */}
              {xlsxData.length > 1 && (
                <div className={styles.sheetTabs}>
                  {xlsxData.map((sheet, idx) => (
                    <button key={idx} type="button" className={`${styles.sheetTab} ${activeSheet === idx ? styles.sheetTabActive : ""}`} onClick={() => setActiveSheet(idx)}>
                      {sheet.name}
                    </button>
                  ))}
                </div>
              )}
              <table className={styles.csvTable}>
                <thead>
                  <tr>
                    {xlsxData[activeSheet]?.data[0]?.map((header, idx) => (
                      <th key={idx} className={styles.csvHeader}>
                        {header !== undefined && header !== null ? String(header) : ""}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {xlsxData[activeSheet]?.data.slice(1).map((row, rowIdx) => (
                    <tr key={rowIdx} className={rowIdx % 2 === 0 ? styles.csvRowEven : styles.csvRowOdd}>
                      {row.map((cell, cellIdx) => (
                        <td key={cellIdx} className={styles.csvCell}>
                          {cell !== undefined && cell !== null ? String(cell) : ""}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {/* Blob URL fallback (when type detected from blob) */}
          {!loading && fileType === "blob" && blobUrl && !error && <iframe src={blobUrl} title="Document Viewer" className={styles.iframe} />}

          {/* Error State */}
          {!loading && error && (
            <div className={styles.errorContainer}>
              <div className={styles.errorIcon}>
                <SVGIcons icon="warnings" width={48} height={48} color="#ef4444" />
              </div>
              <p className={styles.errorText}>{error}</p>
              <button type="button" className={styles.retryButton} onClick={handleClose}>
                Close
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export default DocViewerModal;
