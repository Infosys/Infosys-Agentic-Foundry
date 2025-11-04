import React, { useEffect, useState } from 'react';
import DOMPurify from "dompurify";
import styles from './DocViewerModal.module.css';
import mammoth from 'mammoth';
import parse from 'html-react-parser';
import { useMessage } from "../../Hooks/MessageContext";
import axios from "axios";
import { APIs, BASE_URL } from "../../constant";
import Cookies from "js-cookie";
import Loader from "../commonComponents/Loader";

const DocViewerModal = ({ url, onClose }) => {
  const [blobUrl, setBlobUrl] = useState(null);
  const [docxHtml, setDocxHtml] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);

  const isPdf = url?.toLowerCase().endsWith('.pdf');
  const isDocx = url?.toLowerCase().endsWith('.docx');
  const messageContext = useMessage();
  const addMessage = messageContext?.addMessage;

  // Move fetchOnceRef outside useEffect so it persists across all renders and modal opens
  const fetchOnceRef = React.useRef(false);

  // Only fetch once per modal open, not per render
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    // Only fetch once per modal open
    if (fetchOnceRef.current) return;
    fetchOnceRef.current = true;
    (async () => {
      try {
        let fileUrl;
        if (url.startsWith("http://") || url.startsWith("https://")) {
          fileUrl = url;
        } else {
          if (url.startsWith(APIs.DOWNLOAD_FILE)) {
            fileUrl = BASE_URL + url;
          } else {
            fileUrl = `${BASE_URL}${APIs.DOWNLOAD_FILE}?filename=${encodeURIComponent(url)}`;
          }
        }
        const jwtToken = Cookies.get("jwt-token");
        const headers = jwtToken ? { Authorization: `Bearer ${jwtToken}` } : {};
        const responseType = isPdf ? "arraybuffer" : isDocx ? "blob" : "text";
        // Always hit endpoint once per modal open
        const response = await axios.get(fileUrl, {
          responseType,
          headers,
        });
        if (isPdf) {
          const contentType = response.headers["content-type"] || "";
          if (typeof response.data === "string" || contentType.includes("application/json")) {
            setError("PDF preview not available. File is not a valid PDF.");
            return;
          }
          if (!blobUrl) {
            setBlobUrl(URL.createObjectURL(new Blob([response.data], { type: 'application/pdf' })));
          }
        } else if (isDocx) {
          let docBlob = response.data;
          if (typeof docBlob === "string" || response.headers["content-type"]?.includes("application/json")) {
            setError("DOCX preview not available. File is not a valid DOCX.");
            return;
          }
          const arrayBuffer = await docBlob.arrayBuffer();
          const result = await mammoth.convertToHtml({ arrayBuffer });
          const sanitizedHtml = DOMPurify.sanitize(result.value);
          setDocxHtml(sanitizedHtml);
        } else {
          setError("Preview not available for this file type.");
        }
      } catch (err) {
        if (!cancelled) {
          setError("Failed to load file preview.");
          if (addMessage) addMessage('Failed to load file preview', 'error');
        }
      } finally {
        setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
      if (blobUrl) {
        URL.revokeObjectURL(blobUrl);
      }
      fetchOnceRef.current = false;
      setLoading(false);
    };
  }, [url, addMessage, blobUrl, isDocx, isPdf]); // Add all required dependencies for React

  return (
    <div className={styles.overlay} onClick={onClose}>
      {loading && <Loader />}
      <div className={styles.modal} onClick={(e) => e.stopPropagation()}>
        {!loading && isPdf && blobUrl && !error && (
          <iframe src={blobUrl} title="PDF Viewer" className={styles.iframe} />
        )}
        {!loading && isDocx && docxHtml && !error && (
          <div id="word-document" className={styles.docxContainer}>
            {parse(DOMPurify.sanitize(docxHtml))}
          </div>
        )}
        {!loading && error && (
          <div style={{ padding: "32px", textAlign: "center", color: "#b32b2b" }}>
            {error}
          </div>
        )}
      </div>
      <button className={styles.closeButton} onClick={onClose}>✖</button>
    </div>
  );
};

export default DocViewerModal;