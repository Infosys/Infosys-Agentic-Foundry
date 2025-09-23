import React, { useState, useRef } from 'react';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { oneLight, oneDark } from 'react-syntax-highlighter/dist/esm/styles/prism';
import styles from './CodeViewer.module.css';
import SVGIcons from '../../../Icons/SVGIcons';
import MonacoEditor from "@monaco-editor/react";

const CodeViewer = ({ content, messageId, language = 'python', theme = 'dark' }) => {
  const [currentTheme, setCurrentTheme] = useState(theme);
  const [copySuccess, setCopySuccess] = useState(false);
  const [isEditMode, setIsEditMode] = useState(false);
  // Safely handle content - ensure it's always a string
  const safeContent = React.useMemo(() => {
    if (typeof content === 'string') return content;
    if (content === null || content === undefined) return '';
    
    // Handle object with content property (common API response structure)
    if (typeof content === 'object') {
      // If it has a content property, extract it
      if (content.content && typeof content.content === 'string') {
        return content.content;
      }
      
      // If it has a code property, extract it  
      if (content.code && typeof content.code === 'string') {
        return content.code;
      }
      
      // If it has a text property, extract it
      if (content.text && typeof content.text === 'string') {
        return content.text;
      }
      
      // If it has a data property, extract it
      if (content.data && typeof content.data === 'string') {
        return content.data;
      }
      
      // Fallback to JSON stringify for other objects
      try {
        return JSON.stringify(content, null, 2);
      } catch (error) {
        return String(content);
      }
    }
    
    return String(content);
  }, [content]);
  
  const [editedContent, setEditedContent] = useState(safeContent);
  const textareaRef = useRef(null);  // Auto-detect language from content if not provided
  const detectedLanguage = content.type ==="json" ? "json" : content.language ? content.language: "python";
  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(editedContent || safeContent);
      setCopySuccess(true);
      setTimeout(() => setCopySuccess(false), 2000);
    } catch (err) {
      console.error('Failed to copy:', err);
      // Fallback for browsers that don't support clipboard API
      const textArea = document.createElement('textarea');
      textArea.value = editedContent || safeContent;
      document.body.appendChild(textArea);
      textArea.select();
      try {
        document.execCommand('copy');
        setCopySuccess(true);
        setTimeout(() => setCopySuccess(false), 2000);
      } catch (fallbackErr) {
        console.error('Fallback copy failed:', fallbackErr);
      }
      document.body.removeChild(textArea);
    }
  };

  const toggleTheme = () => {
    setCurrentTheme(prev => prev === 'light' ? 'dark' : 'light');
  };
  const toggleEditMode = () => {
    if (isEditMode) {
      // Save changes when exiting edit mode
      setEditedContent(textareaRef.current?.value || safeContent);
    }
    setIsEditMode(!isEditMode);
  };
  const handleDownload = () => {
    const blob = new Blob([editedContent || safeContent], { type: 'text/plain' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `iaf_code.${getFileExtension(detectedLanguage)}`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  };

  const getFileExtension = (lang) => {
    const extensions = {
      javascript: 'js',
      python: 'py',
      html: 'html',
      css: 'css',
      sql: 'sql',
      php: 'php',
      cpp: 'cpp',
      java: 'java',
      go: 'go',
      typescript: 'ts',
      json: 'json',
      xml: 'xml',
      yaml: 'yml',
      bash: 'sh'
    };
    return extensions[lang] || 'txt';
  };

  const syntaxHighlighterStyle = currentTheme === 'dark' ? oneDark : oneLight;

  if (!content && !editedContent) {
    return (
      <div className={styles.emptyState}>
        <SVGIcons icon="hardware-chip" width={32} height={32} fill="#cbd5e1" />
        <p className={styles.emptyMessage}>No code content to display</p>
      </div>
    );
  }

  return (
    <div className={`${styles.codeViewer} ${currentTheme === 'dark' ? styles.dark : styles.light}`}>
      {/* Toolbar */}
      <div className={styles.toolbar}>
        {/* <div className={styles.toolbarLeft}>
          <div className={styles.languageTag}>
            <SVGIcons icon="hardware-chip" width={14} height={14} fill="#007acc" />
            <span>{detectedLanguage}</span>
          </div>
          {(editedContent !== content && editedContent) && (
            <div className={styles.modifiedIndicator}>
              <span>Modified</span>
            </div>
          )}
        </div> */}
        
        <div className={styles.toolbarActions}>
          <button
            className={styles.toolbarButton}
            onClick={toggleTheme}
            title={`Switch to ${currentTheme === 'light' ? 'dark' : 'light'} theme`}
          >
            {currentTheme === 'light' ? (
              <svg width="14" height="14" viewBox="0 0 20 20" fill="none">
                <path d="M10 2V4M10 16V18M4 10H2M6.22 4.22L4.81 2.81M15.78 4.22L17.19 2.81M6.22 15.78L4.81 17.19M15.78 15.78L17.19 17.19M18 10H16M14 10C14 12.21 12.21 14 10 14C7.79 14 6 12.21 6 10C6 7.79 7.79 6 10 6C12.21 6 14 7.79 14 10Z" 
                  stroke="#666" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
              </svg>
            ) : (
              <svg width="14" height="14" viewBox="0 0 20 20" fill="none">
                <path d="M17.293 13.293C16.478 13.754 15.547 14 14.5 14C10.91 14 8 11.09 8 7.5C8 6.453 8.246 5.522 8.707 4.707C6.123 5.385 4.25 7.784 4.25 10.625C4.25 14.04 7.085 16.875 10.5 16.875C13.341 16.875 15.74 15.002 16.418 12.418L17.293 13.293Z" 
                  fill="#666"/>
              </svg>
            )}
          </button>
          
          {/* <button
            className={styles.toolbarButton}
            onClick={toggleEditMode}
            title={isEditMode ? 'Exit edit mode' : 'Edit code'}
          >
            {isEditMode ? (
              <SVGIcons icon="eyeIcon" width={14} height={14} fill="#666" />
            ) : (
              <SVGIcons icon="fa-solid fa-pen" width={12} height={12} fill="#666" />
            )}
          </button> */}
          
          <button
            className={styles.toolbarButton}
            onClick={handleDownload}
            title="Download code"
          >
            <svg width="14" height="14" viewBox="0 0 20 20" fill="none">
              <path d="M10 13V3M7 10L10 13L13 10M5 17H15" 
                stroke="#666" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
            </svg>
          </button>
          
          <button
            className={`${styles.toolbarButton} ${copySuccess ? styles.copied : ''}`}
            onClick={handleCopy}
            title="Copy code"
          >
            {copySuccess ? (
              <svg width="14" height="14" viewBox="0 0 20 20" fill="none">
                <path d="M16 6L8.5 14.5L4 10" stroke="#22c55e" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
              </svg>
            ) : (
              <SVGIcons icon="fa-regular fa-copy" width={14} height={14} fill="#666" />
            )}
          </button>
        </div>
      </div>      {/* Code Content */}
      <div className={styles.codeContent}>
        {isEditMode ? (
          <MonacoEditor
            height="400px"
            defaultLanguage={detectedLanguage}
            defaultValue={editedContent || safeContent}
            theme={currentTheme === 'dark' ? 'vs-dark' : 'light'}
            onChange={(value) => setEditedContent(value)}
            options={{
              selectOnLineNumbers: true,
              automaticLayout: true,
              minimap: { enabled: false },
            }}
          />
        ) : (
          <SyntaxHighlighter
            language={detectedLanguage}
            style={syntaxHighlighterStyle}
            showLineNumbers={true}
            wrapLines={true}
            wrapLongLines={true}
            customStyle={{
              margin: 0,
              padding: '16px',
              background: 'transparent',
              fontSize: '13px',
              lineHeight: '1.5',
            }}
            codeTagProps={{
              style: {
                fontFamily: "'Monaco', 'Menlo', 'Ubuntu Mono', 'Consolas', monospace",
              }
            }}
          >
            {editedContent || safeContent}
          </SyntaxHighlighter>
        )}
      </div>

      {/* Footer with stats */}
      <div className={styles.footer}>
        <div className={styles.stats}>
          <span className={styles.stat}>
            Lines: {(editedContent || safeContent).split('\n').length}
          </span>
          <span className={styles.stat}>
            Characters: {(editedContent || safeContent).length}
          </span>
        </div>
      </div>
    </div>
  );
};

export default CodeViewer;
