import React, { useState, useEffect, useRef, useCallback } from "react";
import AceEditor from "react-ace";
import styles from "./CodeEditor.module.css";
import { useMessage } from "../../Hooks/MessageContext";
import SVGIcons from "../../Icons/SVGIcons";

// Pre-load ace modules immediately when this file is imported
import ace from "ace-builds/src-noconflict/ace";
import "ace-builds/src-noconflict/mode-python";
import "ace-builds/src-noconflict/mode-text";
import "ace-builds/src-noconflict/mode-javascript";
import "ace-builds/src-noconflict/theme-monokai";
import "ace-builds/src-noconflict/theme-github";
import "ace-builds/src-noconflict/theme-twilight";
import "ace-builds/src-noconflict/theme-tomorrow";
import "ace-builds/src-noconflict/ext-language_tools";

// Configure ace to prevent any dynamic loading that causes python.js errors
ace.config.set("basePath", "https://cdn.jsdelivr.net/npm/ace-builds@1.43.3/src-noconflict/");
ace.config.set("modePath", "https://cdn.jsdelivr.net/npm/ace-builds@1.43.3/src-noconflict/");
ace.config.set("themePath", "https://cdn.jsdelivr.net/npm/ace-builds@1.43.3/src-noconflict/");
ace.config.set("workerPath", "https://cdn.jsdelivr.net/npm/ace-builds@1.43.3/src-noconflict/");
ace.config.set("useWorker", false);
ace.config.set("loadWorkerFromBlob", false);

// Completely disable workers globally for all ace instances
window.ace = ace;
if (ace.config) {
  ace.config.setDefaultValues("editor", {
    useWorker: false,
  });
  ace.config.setDefaultValues("session", {
    useWorker: false,
  });
}

// Ensure all modes and themes are properly registered
try {
  ace.require("ace/mode/python");
  ace.require("ace/mode/text");
  ace.require("ace/mode/javascript");
  ace.require("ace/theme/monokai");
  ace.require("ace/theme/github");
  ace.require("ace/theme/twilight");
  ace.require("ace/theme/tomorrow");
  ace.require("ace/ext/language_tools");
} catch (error) {
  console.warn("Some ace modules failed to register:", error);
}

// Backup dynamic loading function for fallback
const loadAceModules = async () => {
  try {
    // Already loaded via static imports above
    return true;
  } catch (error) {
    console.warn("Failed to load ace modules:", error);
    return false;
  }
};

let editorIdCounter = 0;

const CodeEditor = ({
  codeToDisplay = "",
  onChange,
  readOnly = false,
  mode = "python",
  width = "100%",
  height = "250px",
  fontSize = 14,
  placeholder = "Enter your Python code here...",
  style = {},
  onLoad,
  /** Delay (ms) to debounce change propagation to parent. Helps prevent parent layout thrash that can cause scroll jumps. */
  debounceDelay = 60,
  /** Callback when user clicks "Explain" button on selected text */
  onExplainSelection,
  /** Whether to show the language badge header (default: true) */
  showLanguageBadge = true,
  /** Enable drag-and-drop file upload functionality */
  enableDragDrop = false,
  /** Accepted file extensions for drag-drop (e.g., ['.py', '.txt']) */
  acceptedFileTypes = ['.py'],
  /** Callback when file is successfully loaded */
  onFileLoad,
  /** Show upload button in label */
  showUploadButton = false,
  /** Show helper text in label */
  showHelperText = false,
  /** Custom helper text */
  helperText = "(drag & drop / upload .py file / type directly)",
  /** Label text for the code editor */
  label = "",
  /** Callback when label is clicked (e.g., to focus editor) */
  onLabelClick,
  ...props
}) => {
  const [isLoaded, setIsLoaded] = useState(false);
  const [loadError, setLoadError] = useState(false);
  const editorRef = useRef(null);
  const retryTimeoutRef = useRef(null);
  const containerRef = useRef(null);
  const fileInputRef = useRef(null);
  const [isDragging, setIsDragging] = useState(false);
  const { addMessage } = useMessage();

  // Detect current theme (dark or light)
  const [currentTheme, setCurrentTheme] = useState(() => {
    return document.documentElement.getAttribute("data-theme") || "light";
  });

  // Listen for theme changes
  useEffect(() => {
    const observer = new MutationObserver((mutations) => {
      mutations.forEach((mutation) => {
        if (mutation.attributeName === "data-theme") {
          const newTheme = document.documentElement.getAttribute("data-theme") || "light";
          setCurrentTheme(newTheme);
        }
      });
    });

    observer.observe(document.documentElement, { attributes: true });

    return () => observer.disconnect();
  }, []);

  // Get Ace theme based on current app theme
  const aceTheme = currentTheme === "dark" ? "monokai" : "github";

  // State for selection popover
  const [selectionPopover, setSelectionPopover] = useState({
    visible: false,
    x: 0,
    y: 0,
    selectedText: "",
  });
  // Stable editor id prevents Ace from remounting each render (avoids scroll reset/jump)
  const editorIdRef = useRef(`ace-editor-${++editorIdCounter}`);
  const debounceTimerRef = useRef(null);

  // File reading function
  const readFileContent = (file) => {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = (e) => resolve(e.target.result);
      reader.onerror = reject;
      reader.readAsText(file);
    });
  };

  // Validate file type
  const isValidFileType = (fileName) => {
    return acceptedFileTypes.some(ext =>
      fileName.toLowerCase().endsWith(ext.toLowerCase())
    );
  };

  // Process selected/dropped file
  const processFile = async (file) => {
    if (!isValidFileType(file.name)) {
      const extensions = acceptedFileTypes.join(', ');
      addMessage(`Please upload a valid file type: ${extensions}`, 'error');
      return;
    }

    try {
      const content = await readFileContent(file);

      // Call onChange to update parent component
      if (onChange) {
        onChange(content);
      }

      // Call optional callback
      if (onFileLoad) {
        onFileLoad(content, file);
      }

      addMessage(`File "${file.name}" loaded successfully`, 'success');
    } catch (error) {
      console.error('Error reading file:', error);
      addMessage('Failed to read file content', 'error');
    }
  };

  // Handle drag events
  const handleDragEnter = useCallback((e) => {
    if (!enableDragDrop || readOnly) return;
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(true);
  }, [enableDragDrop, readOnly]);

  const handleDragLeave = useCallback((e) => {
    if (!enableDragDrop || readOnly) return;
    e.preventDefault();
    e.stopPropagation();
    if (e.currentTarget === e.target || !e.currentTarget.contains(e.relatedTarget)) {
      setIsDragging(false);
    }
  }, [enableDragDrop, readOnly]);

  const handleDragOver = useCallback((e) => {
    if (!enableDragDrop || readOnly) return;
    e.preventDefault();
    e.stopPropagation();
  }, [enableDragDrop, readOnly]);

  const handleDrop = useCallback(async (e) => {
    if (!enableDragDrop || readOnly) return;
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(false);

    const files = e.dataTransfer.files;
    if (files && files.length > 0) {
      await processFile(files[0]);
    }
  }, [enableDragDrop, readOnly, processFile]);

  // Handle file picker selection
  const handleFileSelect = useCallback(async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    await processFile(file);
    // Reset input for re-selection
    if (fileInputRef.current) {
      fileInputRef.current.value = '';
    }
  }, [processFile]);

  // Trigger file picker
  const handleUploadClick = useCallback(() => {
    if (!enableDragDrop || readOnly) return;
    fileInputRef.current?.click();
  }, [enableDragDrop, readOnly]);

  // Direct onChange handler (removed debounce to fix cursor jumping issues)
  const handleChange = useCallback(
    (val) => {
      if (!onChange) return;
      onChange(val);
    },
    [onChange],
  );

  useEffect(() => {
    // Since modules are pre-loaded via static imports, we can load immediately
    // Just add a tiny delay to ensure DOM is ready

    const timer = setTimeout(() => {
      try {
        // Verify ace is properly loaded
        if (typeof ace !== "undefined" && ace.edit) {
          setIsLoaded(true);
          setLoadError(false);
        } else {
          console.error("Ace editor not properly loaded");
          setLoadError(true);
        }
      } catch (error) {
        console.error("Error initializing CodeEditor:", error);
        setLoadError(true);
      }
    }, 100); // Increased delay to ensure proper initialization

    return () => {
      clearTimeout(timer);
      if (retryTimeoutRef.current) {
        clearTimeout(retryTimeoutRef.current);
      }
    };
  }, []);

  const handleEditorLoad = (editor) => {
    editorRef.current = editor;

    // Configure editor session to completely disable workers
    if (editor && editor.getSession) {
      editorRef.current.renderer.$cursorLayer.element.style.visibility = "hidden"; // To remove the last cursor position highlight

      const session = editor.getSession();
      if (session) {
        session.setUseWorker(false);
        session.setUseWrapMode(true);

        // Force disable worker in the session
        session.$useWorker = false;
        if (session.$worker) {
          session.$worker = null;
        }

        // Ensure the mode is properly set without worker
        try {
          const Mode = ace.require(`ace/mode/${mode}`).Mode;
          const modeInstance = new Mode();
          if (modeInstance.createWorker) {
            modeInstance.createWorker = function () {
              return null;
            };
          }
          session.setMode(modeInstance);
        } catch (error) {
          console.warn(`Failed to set mode ${mode}:`, error);
        }
      }
    }

    // Set editor options to prevent worker usage
    if (editor) {
      editor.setOption("useWorker", false);
      if (editor.renderer) {
        editor.renderer.setShowGutter(true);
        editor.renderer.setShowPrintMargin(false);
      }
      // Minimal non-jank config: disable animated & auto centering scroll features only.
      editor.setOptions({
        animatedScroll: false,
        autoScrollEditorIntoView: false,
        scrollPastEnd: 0,
        cursorStyle: "ace",
      });
      // Remove command that can cause recentering jump during selection extension
      if (editor.commands && editor.commands.byName && editor.commands.byName.centerselection) {
        editor.commands.removeCommand("centerselection");
      }

      // Add selection change listener for "Explain" popover feature
      if (onExplainSelection) {
        const selection = editor.getSelection();
        selection.on("changeSelection", () => {
          const selectedText = editor.getSelectedText();
          if (selectedText && selectedText.trim().length > 0) {
            // Get the cursor position to place the popover
            const cursorPos = editor.getCursorPosition();
            const screenPos = editor.renderer.textToScreenCoordinates(cursorPos.row, cursorPos.column);
            const containerRect = containerRef.current?.getBoundingClientRect() || { left: 0, top: 0 };

            setSelectionPopover({
              visible: true,
              x: screenPos.pageX - containerRect.left,
              y: screenPos.pageY - containerRect.top - 35, // Position above the selection
              selectedText: selectedText,
            });
          } else {
            setSelectionPopover((prev) => ({ ...prev, visible: false }));
          }
        });

        // Hide popover on editor blur or click outside
        editor.on("blur", () => {
          setTimeout(() => {
            setSelectionPopover((prev) => ({ ...prev, visible: false }));
          }, 150); // Delay to allow button click
        });
      }
    }

    if (onLoad) {
      onLoad(editor);
    }
  };
  const defaultStyle = {
    border: "none",
    borderRadius: "0",
    fontFamily: "Consolas, Monaco, 'Courier New', monospace",
    ...style,
  };

  if (!isLoaded) {
    if (loadError) {
      console.warn("CodeEditor failed to load, showing fallback textarea");
      return (
        <textarea
          value={codeToDisplay}
          onChange={(e) => !readOnly && onChange && onChange(e.target.value)}
          readOnly={readOnly}
          placeholder={placeholder}
          className={styles.fallbackTextarea}
          style={{
            ...defaultStyle,
            height,
            fontSize: `${fontSize}px`,
          }}
        />
      );
    }

    return (
      <div className={styles.loadingContainer} style={{ width, height }}>
        <div className={styles.loadingText}>
          <div>Loading code editor...</div>
          <div className={styles.loadingSubtext}>Please wait while we initialize the editor</div>
        </div>
      </div>
    );
  }

  /**
   * Handle "Explain" button click
   */
  const handleExplainClick = () => {
    if (onExplainSelection && selectionPopover.selectedText) {
      onExplainSelection(selectionPopover.selectedText);
      setSelectionPopover((prev) => ({ ...prev, visible: false }));
    }
  };

  try {
    return (
      <div className={styles.codeEditorOuterWrapper}>
        {/* Optional Label with Upload Button */}
        {label && (
          <div className={styles.labelContainer}>
            <label
              className={styles.codeLabel}
              onClick={onLabelClick}
            >
              {label}
            </label>
            {showUploadButton && enableDragDrop && !readOnly && (
              <button
                type="button"
                onClick={handleUploadClick}
                className={styles.uploadBtn}
                title="Upload File"
                aria-label={`Upload ${acceptedFileTypes.join(', ')} file`}
              >
                +
              </button>
            )}
            {showHelperText && (
              <span className={styles.helperText}>
                {helperText}
              </span>
            )}
          </div>
        )}

        {/* Hidden file input */}
        {enableDragDrop && !readOnly && (
          <input
            ref={fileInputRef}
            type="file"
            accept={acceptedFileTypes.join(',')}
            onChange={handleFileSelect}
            className={styles.hiddenFileInput}
            aria-label="Upload code file"
          />
        )}

        <div
          className={`${styles.codeEditorWrapper} ${isDragging ? styles.dragging : ''}`}
          ref={containerRef}
          onDragEnter={handleDragEnter}
          onDragLeave={handleDragLeave}
          onDragOver={handleDragOver}
          onDrop={handleDrop}
        >
          {/* Drag overlay */}
          {enableDragDrop && !readOnly && isDragging && (
            <div className={styles.dragOverlay}>
              <div className={styles.dragOverlayContent}>
                <SVGIcons
                  icon="fa-solid fa-file-code"
                  width={48}
                  height={48}
                  fill="var(--app-primary-color)"
                />
                <p className={styles.dragOverlayText}>Drop file here</p>
                <p className={styles.dragOverlaySubtext}>Content will replace current code</p>
              </div>
            </div>
          )}

          <div className={styles.editorContainer}>
            {/* Explain Popover Button */}
            {onExplainSelection && selectionPopover.visible && (
              <button
                type="button"
                className={styles.explainPopover}
                style={{
                  left: `${selectionPopover.x}px`,
                  top: `${selectionPopover.y}px`,
                }}
                onClick={handleExplainClick}
                onMouseDown={(e) => e.preventDefault()} // Prevent blur before click
              >
                Explain
              </button>
            )}

            {showLanguageBadge && (
              <div className={styles.editorHeader}>
                <span className={styles.languageBadge}>Python</span>
              </div>
            )}
            <AceEditor
              ref={editorRef}
              mode={mode}
              theme={aceTheme}
              className={styles.aceEditor}
              name={editorIdRef.current}
              onChange={readOnly ? undefined : handleChange}
              value={codeToDisplay}
              width={width}
              height={height}
              fontSize={fontSize}
              showPrintMargin={false}
              showGutter={true}
              highlightActiveLine={false}
              readOnly={readOnly}
              setOptions={{
                enableBasicAutocompletion: !readOnly,
                enableLiveAutocompletion: !readOnly,
                enableSnippets: !readOnly,
                showLineNumbers: true,
                tabSize: 4,
                useWorker: false,
                wrap: true,
                animatedScroll: false,
                cursorStyle: "ace",
                mergeUndoDeltas: true,
                behavioursEnabled: !readOnly,
                wrapBehavioursEnabled: !readOnly,
                autoScrollEditorIntoView: false,
                copyWithEmptySelection: false,
                scrollPastEnd: 0,
                fixedWidthGutter: true,
                ...props.setOptions,
              }}
              style={defaultStyle}
              placeholder={placeholder}
              onLoad={handleEditorLoad}
              editorProps={{
                $blockScrolling: Infinity,
                $useWorker: false, // Additional worker prevention
              }}
              onBlur={() => {
                // optional: disable active line highlight when blurred
                const ed = editorRef.current?.editor;
                if (ed) ed.setHighlightActiveLine(false); // On focus out remove the line highlight
                editorRef.current.editor.renderer.$cursorLayer.element.style.visibility = "hidden"; // To remove the last cursor position highlight
              }}
              onFocus={() => {
                const ed = editorRef.current?.editor;
                if (ed) ed.setHighlightActiveLine(true); // On focus in enable the line highlight
                editorRef.current.editor.renderer.$cursorLayer.element.style.visibility = "visible"; // To remove the last cursor position highlight
              }}
              {...props}
            />
          </div>
        </div>
      </div>
    );
  } catch (error) {
    console.error("Error rendering AceEditor:", error);

    // Fallback to textarea if AceEditor fails
    return (
      <textarea
        value={codeToDisplay}
        onChange={(e) => !readOnly && onChange && onChange(e.target.value)}
        readOnly={readOnly}
        placeholder={placeholder}
        className={styles.fallbackTextarea}
        style={{
          ...defaultStyle,
          height,
          fontSize: `${fontSize}px`,
        }}
      />
    );
  }
};

export default CodeEditor;
