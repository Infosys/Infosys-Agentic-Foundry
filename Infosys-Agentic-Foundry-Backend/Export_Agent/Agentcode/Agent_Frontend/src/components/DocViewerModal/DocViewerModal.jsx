import React, { useEffect, useState } from 'react';
import DOMPurify from "dompurify";
import styles from './DocViewerModal.module.css';
import mammoth from 'mammoth';
import parse from 'html-react-parser';
import { useMessage } from "../../Hooks/MessageContext";

const DocViewerModal = ({ url, onClose }) => {
  const [blobUrl, setBlobUrl] = useState(null);
  const [docxHtml, setDocxHtml] = useState(null);

  const isPdf = url?.toLowerCase().endsWith('.pdf');
  const isDocx = url?.toLowerCase().endsWith('.docx');
  const { addMessage } = useMessage();

  useEffect(() => {
    const fetchPdf = async () => {
      try {
        const response = await fetch(url);
        if (!response.ok) throw new Error('Failed to fetch PDF');
        const arrayBuffer = await response.arrayBuffer();
        const blob = new Blob([arrayBuffer], { type: 'application/pdf' });
        const blobUrl = URL.createObjectURL(blob);
        setBlobUrl(blobUrl);
      } catch (err) {
        console.error(err);
        addMessage('Failed to load PDF', 'error');
      }
    };

    const fetchDocx = async () => {
      try {
        const response = await fetch(url);
        if (!response.ok) throw new Error('Failed to fetch DOCX');
        const arrayBuffer = await response.blob();
        const result = await mammoth.convertToHtml({ arrayBuffer });
        const sanitizedHtml = DOMPurify.sanitize(result.value);
        setDocxHtml(sanitizedHtml);
      } catch (err) {
        console.error(err);
        addMessage('Failed to load DOCX', 'error');
      }
    };

    if (isPdf) {
      fetchPdf();
    } else if (isDocx) {
      fetchDocx();
    }

    return () => {
      if (blobUrl) {
        URL.revokeObjectURL(blobUrl);
      }
    };
  }, [url]);

  return (
    <div className={styles.overlay} onClick={onClose}>
      <div className={styles.modal} onClick={(e) => e.stopPropagation()}>
        {isPdf && blobUrl && (
          <iframe src={blobUrl} title="PDF Viewer" className={styles.iframe} />
        )}

        {isDocx && docxHtml && (
          <div
            id="word-document"
            className={styles.docxContainer}
          >
            {/* Sanitize the message (with newlines already converted to <br />), 
              then parse the resulting safe HTML string into React elements. */}
              {parse(DOMPurify.sanitize(docxHtml))}
          </div>
        )}
      </div>
      <button className={styles.closeButton} onClick={onClose}>✖</button>
    </div>
  );
};

export default DocViewerModal;