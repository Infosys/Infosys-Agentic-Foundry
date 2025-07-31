import React, { useState, useRef } from "react";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import {
  faTimes,
  faUpload,
  faFile,
  faFolder,
  faEye,
  faDownload,
  faTrash,
  faCloudUploadAlt,
  faSpinner
} from "@fortawesome/free-solid-svg-icons";
import styles from "./FileUploadModal.module.css";

const FileUploadModal = ({ onClose, sessionId }) => {
  const [files, setFiles] = useState([]);
  const [subfolderName, setSubfolderName] = useState("");
  const [existingFiles, setExistingFiles] = useState([
    // Mock existing files - replace with actual API data
    {
      id: 1,
      name: "document.pdf",
      folder: "reports",
      size: "2.4 MB",
      uploadDate: "2024-01-15",
      type: "pdf"
    },
    {
      id: 2,
      name: "data.xlsx",
      folder: "spreadsheets",
      size: "1.8 MB",
      uploadDate: "2024-01-14",
      type: "xlsx"
    },
    {
      id: 3,
      name: "presentation.pptx",
      folder: "presentations",
      size: "5.2 MB",
      uploadDate: "2024-01-13",
      type: "pptx"
    }
  ]);
  const [dragActive, setDragActive] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [selectedFolder, setSelectedFolder] = useState("all");
  const fileInputRef = useRef(null);

  // Group files by folder
  const filesByFolder = existingFiles.reduce((acc, file) => {
    if (!acc[file.folder]) {
      acc[file.folder] = [];
    }
    acc[file.folder].push(file);
    return acc;
  }, {});

  const folders = Object.keys(filesByFolder);

  // Handle drag events
  const handleDrag = (e) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.type === "dragenter" || e.type === "dragover") {
      setDragActive(true);
    } else if (e.type === "dragleave") {
      setDragActive(false);
    }
  };

  const handleDrop = (e) => {
    e.preventDefault();
    e.stopPropagation();
    setDragActive(false);
    
    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      handleFiles(e.dataTransfer.files);
    }
  };

  const handleFileInput = (e) => {
    if (e.target.files && e.target.files[0]) {
      handleFiles(e.target.files);
    }
  };

  const handleFiles = (fileList) => {
    const newFiles = Array.from(fileList).map((file, index) => ({
      id: Date.now() + index,
      file,
      name: file.name,
      size: formatFileSize(file.size),
      type: file.type,
      progress: 0
    }));
    
    setFiles(prev => [...prev, ...newFiles]);
  };

  const formatFileSize = (bytes) => {
    if (bytes === 0) return '0 Bytes';
    const k = 1024;
    const sizes = ['Bytes', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
  };

  const removeFile = (fileId) => {
    setFiles(prev => prev.filter(file => file.id !== fileId));
  };

  const uploadFiles = async () => {
    if (files.length === 0) return;
    
    setUploading(true);
    
    try {
      // Simulate upload progress
      for (const file of files) {
        for (let progress = 0; progress <= 100; progress += 10) {
          await new Promise(resolve => setTimeout(resolve, 100));
          setFiles(prev => prev.map(f => 
            f.id === file.id ? { ...f, progress } : f
          ));
        }
      }
      
      // Add uploaded files to existing files
      const uploadedFiles = files.map(file => ({
        id: Date.now() + Math.random(),
        name: file.name,
        folder: subfolderName || "uploads",
        size: file.size,
        uploadDate: new Date().toISOString().split('T')[0],
        type: file.file.type
      }));
      
      setExistingFiles(prev => [...prev, ...uploadedFiles]);
      setFiles([]);
      setSubfolderName("");
      
    } catch (error) {
      console.error("Upload failed:", error);
    } finally {
      setUploading(false);
    }
  };

  const deleteExistingFile = (fileId) => {
    setExistingFiles(prev => prev.filter(file => file.id !== fileId));
  };

  const downloadFile = (file) => {
    // Simulate file download
    console.log("Downloading file:", file.name);
  };

  const viewFile = (file) => {
    // Simulate file view
    console.log("Viewing file:", file.name);
  };

  const getFileIcon = (type) => {
    if (type.includes('pdf')) return '📄';
    if (type.includes('image')) return '🖼️';
    if (type.includes('video')) return '🎥';
    if (type.includes('audio')) return '🎵';
    if (type.includes('spreadsheet') || type.includes('excel')) return '📊';
    if (type.includes('presentation') || type.includes('powerpoint')) return '📈';
    if (type.includes('document') || type.includes('word')) return '📝';
    return '📄';
  };

  const filteredFiles = selectedFolder === "all" 
    ? existingFiles 
    : existingFiles.filter(file => file.folder === selectedFolder);

  return (
    <div className={styles.overlay} onClick={(e) => e.target === e.currentTarget && onClose()}>
      <div className={styles.modal}>
        {/* Header */}
        <div className={styles.header}>
          <div className={styles.headerContent}>
            <FontAwesomeIcon icon={faUpload} className={styles.headerIcon} />
            <h3 className={styles.title}>File Upload & Management</h3>
          </div>
          <button className={styles.closeButton} onClick={onClose}>
            <FontAwesomeIcon icon={faTimes} />
          </button>
        </div>

        <div className={styles.content}>
          {/* Upload Section */}
          <div className={styles.uploadSection}>
            {/* <h4 className={styles.sectionTitle}>Upload Files</h4> */}
            
            {/* Subfolder Input */}
            <div className={styles.inputGroup}>
              <label className={styles.label}>Subfolder Name (Optional)</label>
              <input
                type="text"
                value={subfolderName}
                onChange={(e) => setSubfolderName(e.target.value)}
                placeholder="Enter folder name or leave empty for default"
                className={styles.input}
              />
            </div>

            {/* Drag & Drop Area */}
            <div
              className={`${styles.dropZone} ${dragActive ? styles.dragActive : ''}`}
              onDragEnter={handleDrag}
              onDragLeave={handleDrag}
              onDragOver={handleDrag}
              onDrop={handleDrop}
              onClick={() => fileInputRef.current?.click()}
            >
              <FontAwesomeIcon icon={faCloudUploadAlt} className={styles.uploadIcon} />
              <p className={styles.dropText}>
                Drag & drop files here or <span className={styles.clickText}>click to browse</span>
              </p>
              <p className={styles.dropSubtext}>
                Supports: PDF, DOC, DOCX, XLS, XLSX, PPT, PPTX, TXT, CSV, Images
              </p>
              <input
                ref={fileInputRef}
                type="file"
                multiple
                onChange={handleFileInput}
                className={styles.hiddenInput}
                accept=".pdf,.doc,.docx,.xls,.xlsx,.ppt,.pptx,.txt,.csv,.jpg,.jpeg,.png,.gif"
              />
            </div>

            {/* Files to Upload */}
            {files.length > 0 && (
              <div className={styles.filesToUpload}>
                <h5 className={styles.filesTitle}>Files to Upload:</h5>
                {files.map((file) => (
                  <div key={file.id} className={styles.fileItem}>
                    <div className={styles.fileInfo}>
                      <span className={styles.fileIcon}>{getFileIcon(file.type)}</span>
                      <div className={styles.fileDetails}>
                        <span className={styles.fileName}>{file.name}</span>
                        <span className={styles.fileSize}>{file.size}</span>
                      </div>
                    </div>
                    {uploading ? (
                      <div className={styles.progressContainer}>
                        <div className={styles.progressBar}>
                          <div 
                            className={styles.progressFill}
                            style={{ width: `${file.progress}%` }}
                          ></div>
                        </div>
                        <span className={styles.progressText}>{file.progress}%</span>
                      </div>
                    ) : (
                      <button
                        className={styles.removeButton}
                        onClick={() => removeFile(file.id)}
                      >
                        <FontAwesomeIcon icon={faTimes} />
                      </button>
                    )}
                  </div>
                ))}
                
                {!uploading && (
                  <button
                    className={styles.uploadButton}
                    onClick={uploadFiles}
                    disabled={files.length === 0}
                  >
                    <FontAwesomeIcon icon={faUpload} />
                    Upload {files.length} File{files.length !== 1 ? 's' : ''}
                  </button>
                )}
                
                {uploading && (
                  <div className={styles.uploadingIndicator}>
                    <FontAwesomeIcon icon={faSpinner} spin />
                    <span>Uploading files...</span>
                  </div>
                )}
              </div>
            )}
          </div>

          {/* Existing Files Section */}
          <div className={styles.existingSection}>
            <div className={styles.existingHeader}>
              <h4 className={styles.sectionTitle}>Existing Files</h4>
              
              {/* Folder Filter */}
              <select
                value={selectedFolder}
                onChange={(e) => setSelectedFolder(e.target.value)}
                className={styles.folderSelect}
              >
                <option value="all">All Folders</option>
                {folders.map(folder => (
                  <option key={folder} value={folder}>{folder}</option>
                ))}
              </select>
            </div>

            <div className={styles.filesList}>
              {filteredFiles.length > 0 ? (
                filteredFiles.map((file) => (
                  <div key={file.id} className={styles.existingFileItem}>
                    <div className={styles.fileInfo}>
                      <span className={styles.fileIcon}>{getFileIcon(file.type)}</span>
                      <div className={styles.fileDetails}>
                        <span className={styles.fileName}>{file.name}</span>
                        <div className={styles.fileMetadata}>
                          <span className={styles.fileFolder}>
                            <FontAwesomeIcon icon={faFolder} />
                            {file.folder}
                          </span>
                          <span className={styles.fileSize}>{file.size}</span>
                          <span className={styles.fileDate}>{file.uploadDate}</span>
                        </div>
                      </div>
                    </div>
                    
                    <div className={styles.fileActions}>
                      <button
                        className={styles.actionButton}
                        onClick={() => viewFile(file)}
                        title="View File"
                      >
                        <FontAwesomeIcon icon={faEye} />
                      </button>
                      <button
                        className={styles.actionButton}
                        onClick={() => downloadFile(file)}
                        title="Download File"
                      >
                        <FontAwesomeIcon icon={faDownload} />
                      </button>
                      <button
                        className={styles.actionButton}
                        onClick={() => deleteExistingFile(file.id)}
                        title="Delete File"
                      >
                        <FontAwesomeIcon icon={faTrash} />
                      </button>
                    </div>
                  </div>
                ))
              ) : (
                <div className={styles.noFiles}>
                  <FontAwesomeIcon icon={faFile} className={styles.noFilesIcon} />
                  <p>No files found in this folder</p>
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

export default FileUploadModal;
