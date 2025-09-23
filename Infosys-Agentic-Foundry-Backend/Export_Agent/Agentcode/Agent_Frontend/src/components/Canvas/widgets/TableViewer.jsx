import React, { useState } from 'react';
import styles from './TableViewer.module.css';
import SVGIcons from '../../../Icons/SVGIcons';

const TableViewer = ({ content, messageId }) => {
  const [copySuccess, setCopySuccess] = useState(false);

  // Parse table data (expecting array of objects or CSV-like format)
  const parseTableData = (data) => {
    if (Array.isArray(data) && data.length > 0) {
      return {
        headers: Object.keys(data[0]),
        rows: data
      };
    }
    
    // Try to parse as CSV
    if (typeof data === 'string') {
      const lines = data.trim().split('\n');
      if (lines.length > 1) {
        const headers = lines[0].split(',').map(h => h.trim());
        const rows = lines.slice(1).map(line => {
          const values = line.split(',').map(v => v.trim());
          const row = {};
          headers.forEach((header, index) => {
            row[header] = values[index] || '';
          });
          return row;
        });
        return { headers, rows };
      }
    }
    
    return null;
  };

  const tableData = parseTableData(content);

  const handleCopy = async () => {
    try {
      const textContent = typeof content === 'string' ? content : JSON.stringify(content, null, 2);
      await navigator.clipboard.writeText(textContent);
      setCopySuccess(true);
      setTimeout(() => setCopySuccess(false), 2000);
    } catch (err) {
      console.error('Failed to copy:', err);
    }
  };

  if (!tableData) {
    return (
      <div className={styles.emptyState}>
        <SVGIcons icon="tableIcon" width={32} height={32} fill="#cbd5e1" />
        <p className={styles.emptyMessage}>Unable to parse table data</p>
      </div>
    );
  }

  return (
    <div className={styles.tableViewer}>
      {/* Toolbar */}
      <div className={styles.toolbar}>
        <div className={styles.toolbarLeft}>
          <div className={styles.contentTag}>
            <SVGIcons icon="tableIcon" width={14} height={14} fill="#007acc" />
            <span>Table</span>
          </div>
          <span className={styles.rowCount}>{tableData.rows.length} rows</span>
        </div>
        
        <div className={styles.toolbarActions}>
          <button
            className={`${styles.toolbarButton} ${copySuccess ? styles.copied : ''}`}
            onClick={handleCopy}
            title="Copy table data"
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

      {/* Table Content */}
      <div className={styles.tableContent}>
        <table className={styles.table}>
          <thead>
            <tr>
              {tableData.headers.map((header, index) => (
                <th key={index} className={styles.tableHeader}>
                  {header}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {tableData.rows.map((row, rowIndex) => (
              <tr key={rowIndex} className={styles.tableRow}>
                {tableData.headers.map((header, colIndex) => (
                  <td key={colIndex} className={styles.tableCell}>
                    {row[header]}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
};

export default TableViewer;
