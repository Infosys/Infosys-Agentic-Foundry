import React from "react";
import styles from "../AgentAssignment.module.css";

const Table = ({ 
  headers, 
  data, 
  renderRow, 
  loading = false,
  emptyMessage = "No data available",
  pagination = null 
}) => {
  return (
    <div className={styles.assignmentsList}>
      <div className={styles.tableContainer}>
        <table className={styles.assignmentsTable}>
        <thead>
          <tr>
            {headers.map((header, index) => (
              <th key={index}>{header}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {loading ? (
            <tr>
              <td colSpan={headers.length} style={{ textAlign: "center", padding: "20px" }}>
                Loading...
              </td>
            </tr>
          ) : data.length === 0 ? (
            <tr>
              <td colSpan={headers.length} style={{ textAlign: "center", padding: "20px" }}>
                {emptyMessage}
              </td>
            </tr>
          ) : (
            (() => {
              if (pagination) {
                // If serverSide flag is set, assume `data` already contains only the current page rows
                if (pagination.serverSide) {
                  const dataRows = data.map((item, index) => renderRow(item, index));
                  const emptyRowsCount = Math.max(0, pagination.itemsPerPage - data.length);
                  const emptyRows = Array.from({ length: emptyRowsCount }, (_, index) => (
                    <tr key={`empty-${index}`}>
                      {headers.map((_, cellIndex) => (
                        <td key={cellIndex}>&nbsp;</td>
                      ))}
                    </tr>
                  ));
                  return [...dataRows, ...emptyRows];
                }

                // Client-side pagination: slice the provided data array
                const startIndex = (pagination.currentPage - 1) * pagination.itemsPerPage;
                const endIndex = startIndex + pagination.itemsPerPage;
                const paginatedData = data.slice(startIndex, endIndex);
                
                // Render actual data rows
                const dataRows = paginatedData.map((item, index) => renderRow(item, startIndex + index));
                
                // Fill remaining rows with empty rows to maintain consistent height
                const emptyRowsCount = pagination.itemsPerPage - paginatedData.length;
                const emptyRows = Array.from({ length: emptyRowsCount }, (_, index) => (
                  <tr key={`empty-${index}`}>
                    {headers.map((_, cellIndex) => (
                      <td key={cellIndex}>&nbsp;</td>
                    ))}
                  </tr>
                ));
                
                return [...dataRows, ...emptyRows];
              } else {
                return data.map((item, index) => renderRow(item, index));
              }
            })()
          )}
        </tbody>
        </table>
      </div>
      
      {pagination && pagination.totalItems > pagination.itemsPerPage && (
        <div className={styles.paginationControls}>
          <div className={styles.paginationInfo}>
            Showing {Math.min((pagination.currentPage - 1) * pagination.itemsPerPage + 1, pagination.totalItems)} to {Math.min(pagination.currentPage * pagination.itemsPerPage, pagination.totalItems)} of {pagination.totalItems} entries
          </div>
          <div className={styles.paginationButtons}>
            <button 
              onClick={() => pagination.onPageChange(pagination.currentPage - 1)}
              disabled={pagination.currentPage === 1}
              className={styles.paginationButton}
            >
              Previous
            </button>
            
            {(() => {
              const totalPages = Math.ceil(pagination.totalItems / pagination.itemsPerPage);
              const pages = [];
              const maxVisible = 5;
              const divisor = 2;
              const halfVisible = Math.floor(maxVisible / divisor);
              let startPage = Math.max(1, pagination.currentPage - halfVisible);
              const endPage = Math.min(totalPages, startPage + maxVisible - 1);
              
              if (endPage - startPage < maxVisible - 1) {
                startPage = Math.max(1, endPage - maxVisible + 1);
              }
              
              for (let i = startPage; i <= endPage; i++) {
                pages.push(
                  <button
                    key={i}
                    onClick={() => pagination.onPageChange(i)}
                    className={`${styles.paginationButton} ${i === pagination.currentPage ? styles.active : ""}`}
                  >
                    {i}
                  </button>
                );
              }
              
              return pages;
            })()}
            
            <button 
              onClick={() => pagination.onPageChange(pagination.currentPage + 1)}
              disabled={pagination.currentPage === Math.ceil(pagination.totalItems / pagination.itemsPerPage)}
              className={styles.paginationButton}
            >
              Next
            </button>
          </div>
        </div>
      )}
    </div>
  );
};

export default Table;