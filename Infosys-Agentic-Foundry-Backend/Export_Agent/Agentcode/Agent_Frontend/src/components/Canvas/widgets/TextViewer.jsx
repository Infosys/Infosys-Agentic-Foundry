import React, { useState } from 'react';
import styles from './TextViewer.module.css';
import SVGIcons from '../../../Icons/SVGIcons';

const TextViewer = ({ content, messageId }) => {
  const [copySuccess, setCopySuccess] = useState(false);

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(content || '');
      setCopySuccess(true);
      setTimeout(() => setCopySuccess(false), 2000);
    } catch (err) {
      console.error('Failed to copy:', err);
    }
  };

  const handleDownload = () => {
    const blob = new Blob([content || ''], { type: 'text/plain' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `text-${messageId || Date.now()}.txt`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  };

  if (!content) {
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
        <pre className={styles.textPre}>{content}</pre>
      </div>

      {/* Footer */}
      <div className={styles.footer}>
        <div className={styles.stats}>
          <span className={styles.stat}>
            Lines: {(content || '').split('\n').length}
          </span>
          <span className={styles.stat}>
            Characters: {(content || '').length}
          </span>
          <span className={styles.stat}>
            Words: {(content || '').split(/\s+/).filter(word => word.length > 0).length}
          </span>
        </div>
      </div>
    </div>
  );
};

export default TextViewer;
