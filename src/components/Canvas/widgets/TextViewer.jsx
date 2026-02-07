import React, { useState } from 'react';
import styles from './TextViewer.module.css';
import SVGIcons from '../../../Icons/SVGIcons';

const TextViewer = ({ content, messageId }) => {
  const [copySuccess, setCopySuccess] = useState(false);

  // Ensure content is always a string
  const safeContent = React.useMemo(() => {
    if (typeof content === 'string') return content;
    if (content === null || content === undefined) return '';
    return JSON.stringify(content, null, 2);
  }, [content]);

  const handleCopy = async () => {
    try {
      // Try modern clipboard API first
      if (navigator.clipboard && navigator.clipboard.writeText) {
        await navigator.clipboard.writeText(safeContent);
        setCopySuccess(true);
        setTimeout(() => setCopySuccess(false), 2000);
        return;
      }
      
      // Fallback for environments where clipboard API is not available
      const textArea = document.createElement('textarea');
      textArea.value = safeContent;
      textArea.style.position = 'fixed';
      textArea.style.left = '-999999px';
      textArea.style.top = '-999999px';
      document.body.appendChild(textArea);
      textArea.focus();
      textArea.select();
      
      try {
        const successful = document.execCommand('copy');
        if (successful) {
          setCopySuccess(true);
          setTimeout(() => setCopySuccess(false), 2000);
        } else {
          throw new Error('execCommand copy failed');
        }
      } catch (execErr) {
        console.error('Fallback copy failed:', execErr);
        // Show user-friendly message
      } finally {
        document.body.removeChild(textArea);
      }
    } catch (err) {
      console.error('Copy operation failed:', err);
      // Show user-friendly message
    }
  };

  const handleDownload = () => {
    const blob = new Blob([safeContent], { type: 'text/plain' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `text-${messageId || Date.now()}.txt`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  };

  if (!safeContent) {
    return (
      <div className={styles.emptyState}>
        <SVGIcons icon="file" width={32} height={32} fill="#cbd5e1" />
        <p className={styles.emptyMessage}>No text content to display</p>
      </div>
    );
  }

  return (
    <div className={styles.textViewer}>
      {/* Toolbar */}
      <div className={styles.toolbar}>
        <div className={styles.toolbarLeft}>
          <div className={styles.contentTag}>
            <SVGIcons icon="file" width={14} height={14} fill="#007acc" />
            <span>Text</span>
          </div>
        </div>
        
        <div className={styles.toolbarActions}>
          <button
            className={styles.toolbarButton}
            onClick={handleDownload}
            title="Download text"
          >
            <svg width="16" height="16" viewBox="0 0 20 20" fill="none">
              <path d="M10 13V3M7 10L10 13L13 10M5 17H15" 
                stroke="#666" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
            </svg>
          </button>
          
          <button
            className={`${styles.toolbarButton} ${copySuccess ? styles.copied : ''}`}
            onClick={handleCopy}
            title="Copy text"
          >
            {copySuccess ? (
              <svg width="16" height="16" viewBox="0 0 20 20" fill="none">
                <path d="M16 6L8.5 14.5L4 10" stroke="#22c55e" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
              </svg>
            ) : (
              <SVGIcons icon="fa-regular fa-copy" width={14} height={14} fill="#666" />
            )}
          </button>
        </div>
      </div>

      {/* Text Content */}
      <div className={styles.textContent}>
        <pre className={styles.textPre}>{safeContent}</pre>
      </div>

      {/* Footer */}
      <div className={styles.footer}>
        <div className={styles.stats}>
          <span className={styles.stat}>
            Lines: {safeContent.split('\n').length}
          </span>
          <span className={styles.stat}>
            Characters: {safeContent.length}
          </span>
          <span className={styles.stat}>
            Words: {safeContent.split(/\s+/).filter(word => word.length > 0).length}
          </span>
        </div>
      </div>
    </div>
  );
};

export default TextViewer;
