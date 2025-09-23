import React, { useState, useMemo } from "react";
import { useReactTable, getCoreRowModel, getFilteredRowModel, getSortedRowModel, getPaginationRowModel, flexRender } from "@tanstack/react-table";
import * as XLSX from "xlsx";
import styles from "./TableViewer.module.css";
import SVGIcons from "../../../Icons/SVGIcons";

const AdvancedTableViewer = ({ content, messageId }) => {
  const [globalFilter, setGlobalFilter] = useState("");
  const [copySuccess, setCopySuccess] = useState(false);

  // Parse and prepare data
  const { data, columns } = useMemo(() => {
    try {
      let tableData = [];
      let tableColumns = [];

      // Handle parts table format with headers and rows
      if (content && typeof content === "object" && content.headers && content.rows) {
        // Parts format: { title: "...", headers: [...], rows: [[...]] }
        const { headers, rows } = content;

        // Create columns from headers
        tableColumns = headers.map((header, index) => ({
          accessorKey: `col_${index}`,
          header: header,
          cell: ({ getValue }) => {
            const value = getValue();
            if (typeof value === "boolean") return value ? "✓" : "✗";
            if (typeof value === "object" && value !== null) return JSON.stringify(value);
            return String(value || "");
          },
        }));

        // Convert rows array to objects with column accessors
        tableData = rows.map((row) => {
          const rowObj = {};
          headers.forEach((header, index) => {
            rowObj[`col_${index}`] = row[index] || "";
          });
          return rowObj;
        });
      }
      // Handle array of objects (existing format)
      else if (Array.isArray(content) && content.length > 0) {
        tableData = content;
        const firstItem = content[0];
        if (typeof firstItem === "object" && firstItem !== null) {
          tableColumns = Object.keys(firstItem).map((key) => ({
            accessorKey: key,
            header: key.charAt(0).toUpperCase() + key.slice(1).replace(/([A-Z])/g, " $1"),
            cell: ({ getValue }) => {
              const value = getValue();
              if (typeof value === "boolean") return value ? "✓" : "✗";
              if (typeof value === "object" && value !== null) return JSON.stringify(value);
              return String(value || "");
            },
          }));
        }
      } else if (typeof content === "string") {
        // Try parsing different string formats
        const lines = content.trim().split("\n");

        // Check if it's a markdown table (contains pipe symbols)
        if (lines.some((line) => line.includes("|"))) {
          // Filter out separator lines (containing only |, -, :, and whitespace)
          const tableLines = lines.filter((line) => {
            const trimmed = line.trim();
            return (
              trimmed.includes("|") &&
              !trimmed.match(/^\s*\|[\s\-:|\|]+\|\s*$/) && // More comprehensive separator pattern
              !trimmed.match(/^\s*[\-:|\s]+\s*$/)
            ); // Also catch lines without pipes but just dashes
          });

          if (tableLines.length >= 1) {
            // Parse markdown table
            const headerLine = tableLines[0];
            const headers = headerLine
              .split("|")
              .map((h) => h.trim())
              .filter((h) => h.length > 0)
              .map((h) => h.replace(/^[\s\*\|]*|[\s\*\|]*$/g, ""));

            const dataLines = tableLines.slice(1);
            tableData = dataLines.map((line, index) => {
              const values = line
                .split("|")
                .map((v) => v.trim())
                .filter((v) => v.length > 0); // Remove empty elements

              const row = { id: index };
              headers.forEach((header, idx) => {
                row[header] = values[idx] || "";
              });
              return row;
            });

            tableColumns = headers.map((header) => ({
              accessorKey: header,
              header: header.charAt(0).toUpperCase() + header.slice(1),
              cell: ({ getValue }) => String(getValue() || ""),
            }));
          }
        }
        // Try CSV parsing for regular comma-separated data
        else if (lines.length > 1 && !lines[0].includes("|")) {
          const headers = lines[0].split(",").map((h) => h.trim().replace(/^"|"$/g, ""));
          tableData = lines.slice(1).map((line, index) => {
            const values = line.split(",").map((v) => v.trim().replace(/^"|"$/g, ""));
            const row = { id: index };
            headers.forEach((header, idx) => {
              row[header] = values[idx] || "";
            });
            return row;
          });

          tableColumns = headers.map((header) => ({
            accessorKey: header,
            header: header.charAt(0).toUpperCase() + header.slice(1),
            cell: ({ getValue }) => String(getValue() || ""),
          }));
        } else {
          // Try JSON parsing
          try {
            const parsed = JSON.parse(content);
            if (Array.isArray(parsed)) {
              // Handle JSON array like the main array case
              tableData = parsed;
              const firstItem = parsed[0];
              if (typeof firstItem === "object" && firstItem !== null) {
                tableColumns = Object.keys(firstItem).map((key) => ({
                  accessorKey: key,
                  header: key.charAt(0).toUpperCase() + key.slice(1).replace(/([A-Z])/g, " $1"),
                  cell: ({ getValue }) => {
                    const value = getValue();
                    if (typeof value === "boolean") return value ? "✓" : "✗";
                    if (typeof value === "object" && value !== null) return JSON.stringify(value);
                    return String(value || "");
                  },
                }));
              }
            } else if (typeof parsed === "object") {
              tableData = [parsed];
              tableColumns = Object.keys(parsed).map((key) => ({
                accessorKey: key,
                header: key.charAt(0).toUpperCase() + key.slice(1).replace(/([A-Z])/g, " $1"),
                cell: ({ getValue }) => {
                  const value = getValue();
                  if (typeof value === "boolean") return value ? "✓" : "✗";
                  if (typeof value === "object" && value !== null) return JSON.stringify(value);
                  return String(value || "");
                },
              }));
            }
          } catch (e) {
            // Not valid JSON, return empty
            return { data: [], columns: [] };
          }
        }
      } else if (typeof content === "object" && content !== null) {
        tableData = [content];
        tableColumns = Object.keys(content).map((key) => ({
          accessorKey: key,
          header: key.charAt(0).toUpperCase() + key.slice(1).replace(/([A-Z])/g, " $1"),
          cell: ({ getValue }) => {
            const value = getValue();
            if (typeof value === "boolean") return value ? "✓" : "✗";
            if (typeof value === "object" && value !== null) return JSON.stringify(value);
            return String(value || "");
          },
        }));
      }

      return { data: tableData, columns: tableColumns };
    } catch (error) {
      console.error("Error parsing table data:", error);
      return { data: [], columns: [] };
    }
  }, [content]);

  const tableTitle = content.title;

  const table = useReactTable({
    data,
    columns,
    state: {
      globalFilter,
    },
    onGlobalFilterChange: setGlobalFilter,
    getCoreRowModel: getCoreRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getPaginationRowModel: getPaginationRowModel(),
    initialState: {
      pagination: {
        pageSize: 10,
      },
    },
  });

  // Helper function to get clean data for export
  const getExportData = () => {
    const rows = table.getFilteredRowModel().rows;
    
    return rows.map(row => {
      const cleanRow = {};
      columns.forEach(col => {
        const cellValue = row.getValue(col.accessorKey);
        // Clean the data for export
        if (typeof cellValue === "boolean") {
          cleanRow[col.header] = cellValue ? "Yes" : "No";
        } else if (typeof cellValue === "object" && cellValue !== null) {
          cleanRow[col.header] = JSON.stringify(cellValue);
        } else {
          cleanRow[col.header] = String(cellValue || "");
        }
      });
      return cleanRow;
    });
  };

  // Copy table data to clipboard
  const handleCopy = async () => {
    try {
      const exportData = getExportData();
      const headers = columns.map(col => col.header);
      
      // Create tab-separated values
      const tsvContent = [
        headers.join('\t'),
        ...exportData.map(row => headers.map(header => row[header] || '').join('\t'))
      ].join('\n');

      // Try modern clipboard API first
      if (navigator.clipboard && navigator.clipboard.writeText) {
        await navigator.clipboard.writeText(tsvContent);
        setCopySuccess(true);
        setTimeout(() => setCopySuccess(false), 2000);
        return;
      }
      
      // Fallback for environments where clipboard API is not available
      const textArea = document.createElement('textarea');
      textArea.value = tsvContent;
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
      } finally {
        document.body.removeChild(textArea);
      }
    } catch (err) {
      console.error('Copy operation failed:', err);
    }
  };

  // Download as Excel file
  const handleExcelDownload = () => {
    try {
      const exportData = getExportData();
      
      if (exportData.length === 0) {
        return;
      }

      // Create workbook and worksheet
      const wb = XLSX.utils.book_new();
      const ws = XLSX.utils.json_to_sheet(exportData);
      
      // Auto-size columns
      const colWidths = [];
      const headers = columns.map(col => col.header);
      headers.forEach((header, index) => {
        const maxLength = Math.max(
          header.length,
          ...exportData.map(row => String(row[header] || '').length)
        );
        colWidths.push({ wch: Math.min(maxLength + 2, 50) }); // Cap at 50 characters
      });
      ws['!cols'] = colWidths;
      
      // Add worksheet to workbook
      const sheetName = tableTitle ? tableTitle.substring(0, 31) : 'Table Data'; // Excel sheet name limit
      XLSX.utils.book_append_sheet(wb, ws, sheetName);
      
      // Generate filename
      const timestamp = new Date().toISOString().slice(0, 19).replace(/[:.]/g, '-');
      const filename = `${sheetName.replace(/[^a-zA-Z0-9]/g, '_')}_${timestamp}.xlsx`;
      
      // Save file
      XLSX.writeFile(wb, filename);
    } catch (error) {
      console.error('Excel export failed:', error);
    }
  };

  if (data.length === 0) {
    return (
      <div className={styles.emptyState}>
        <SVGIcons icon="fa-table" width={48} height={48} fill="#cbd5e1" />
        <h3 className={styles.emptyTitle}>No Table Data Available</h3>
        <p className={styles.emptyMessage}>Supported formats: JSON array, CSV string, or object data</p>
      </div>
    );
  }

  return (
    <div className={styles.tableViewer}>
      {/* Advanced Toolbar */}
      <div className={styles.toolbar}>
        <div className={styles.toolbarLeft}>
            <span className={styles.tableTitle} title={tableTitle}>{tableTitle}</span>
        </div>

        <div className={styles.toolbarActions}>
          {/* Export Actions */}
          <div className={styles.exportActions}>
            <button
              className={styles.toolbarButton}
              onClick={() => handleExcelDownload()}
              title="Download as Excel"
            >
              <svg width="16" height="16" viewBox="0 0 20 20" fill="none">
                <path d="M10 13V3M7 10L10 13L13 10M5 17H15" 
                  stroke="#007acc" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
              </svg>
            </button>

            <button
              className={`${styles.toolbarButton} ${copySuccess ? styles.copied : ''}`}
              onClick={() => handleCopy()}
              title="Copy to clipboard"
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

          <div className={styles.searchContainer}>
            {/* <SVGIcons icon="search" width={14} height={14} fill="#64748b" /> */}
            <input type="text" placeholder="Search all rows..." value={globalFilter ?? ""} onChange={(e) => setGlobalFilter(e.target.value)} className={styles.searchInput} />
            {globalFilter && (
              <button onClick={() => setGlobalFilter("")} className={styles.clearButton}>
                <SVGIcons icon="fa-times" width={12} height={12} fill="#64748b" />
              </button>
            )}
          </div>
        </div>
      </div>

      {/* Table */}
      <div className={styles.tableContainer}>
        <table className={styles.table}>
          <thead>
            {table.getHeaderGroups().map((headerGroup) => (
              <tr key={headerGroup.id}>
                {headerGroup.headers.map((header) => (
                  <th key={header.id} className={`${styles.tableHeader} ${header.column.getCanSort() ? styles.sortable : ""}`} onClick={header.column.getToggleSortingHandler()}>
                    <div className={styles.headerContent}>
                      {header.isPlaceholder ? null : flexRender(header.column.columnDef.header, header.getContext())}
                      {header.column.getCanSort() && (
                        <div className={styles.sortIcons}>
                          {{
                            asc: <SVGIcons icon="fa-sort-up" width={12} height={12} fill="#007acc" />,
                            desc: <SVGIcons icon="fa-sort-down" width={12} height={12} fill="#007acc" />,
                          }[header.column.getIsSorted()] ?? <SVGIcons icon="fa-sort" width={12} height={12} fill="#94a3b8" />}
                        </div>
                      )}
                    </div>
                  </th>
                ))}
              </tr>
            ))}
          </thead>
          <tbody>
            {table.getRowModel().rows.map((row) => (
              <tr key={row.id} className={styles.tableRow}>
                {row.getVisibleCells().map((cell) => (
                  <td key={cell.id} className={styles.tableCell}>
                    {flexRender(cell.column.columnDef.cell, cell.getContext())}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Pagination */}
      <div className={styles.pagination}>
        <div className={styles.paginationInfo}>
          Showing {table.getState().pagination.pageIndex * table.getState().pagination.pageSize + 1} to{" "}
          {Math.min((table.getState().pagination.pageIndex + 1) * table.getState().pagination.pageSize, table.getFilteredRowModel().rows.length)} of{" "}
          {table.getFilteredRowModel().rows.length} entries
          {table.getFilteredRowModel().rows.length !== data.length && <span className={styles.filteredInfo}>(filtered from {data.length} total entries)</span>}
        </div>

        <div className={styles.paginationControls}>
          <select value={table.getState().pagination.pageSize} onChange={(e) => table.setPageSize(Number(e.target.value))} className={styles.pageSizeSelect}>
            {[5, 10, 20, 30, 50].map((pageSize) => (
              <option key={pageSize} value={pageSize}>
                Show {pageSize}
              </option>
            ))}
          </select>

          <div className={styles.pageNavigation}>
            <button onClick={() => table.setPageIndex(0)} disabled={!table.getCanPreviousPage()} className={styles.pageButton}>
              First
            </button>
            <button onClick={() => table.previousPage()} disabled={!table.getCanPreviousPage()} className={styles.pageButton}>
              Previous
            </button>
            <span className={styles.pageInfo}>
              Page {table.getState().pagination.pageIndex + 1} of {table.getPageCount()}
            </span>
            <button onClick={() => table.nextPage()} disabled={!table.getCanNextPage()} className={styles.pageButton}>
              Next
            </button>
            <button onClick={() => table.setPageIndex(table.getPageCount() - 1)} disabled={!table.getCanNextPage()} className={styles.pageButton}>
              Last
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};

export default AdvancedTableViewer;
