import React, { useState, useEffect, useRef, useCallback } from "react";
import AceEditor from "react-ace";
import styles from "./CodeEditor.module.css";

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

const CodeEditor = ({
  value = "",
  onChange,
  readOnly = false,
  theme = "github",
  mode = "python",
  width = "100%",
  height = "250px",
  fontSize = 14,
  placeholder = "Enter your Python code here...",
  style = {},
  onLoad,
  isDarkTheme = false,
  /** Delay (ms) to debounce change propagation to parent. Helps prevent parent layout thrash that can cause scroll jumps. */
  debounceDelay = 60,
  ...props
}) => {
  const [isLoaded, setIsLoaded] = useState(false);
  const [loadError, setLoadError] = useState(false);
  const editorRef = useRef(null);
  const retryTimeoutRef = useRef(null);
  // Stable editor id prevents Ace from remounting each render (avoids scroll reset/jump)
  const editorIdRef = useRef("ace-editor-" + Math.random().toString(36).slice(2));
  const debounceTimerRef = useRef(null);

  // Debounced onChange wrapper
  const handleChange = useCallback(
    (val) => {
      if (!onChange) return;
      if (debounceTimerRef.current) clearTimeout(debounceTimerRef.current);
      debounceTimerRef.current = setTimeout(() => {
        onChange(val);
      }, debounceDelay);
    },
    [onChange, debounceDelay]
  );

  useEffect(() => {
    // Since modules are pre-loaded via static imports, we can load immediately
    // Just add a tiny delay to ensure DOM is ready
    console.log("CodeEditor initializing...");

    const timer = setTimeout(() => {
      try {
        // Verify ace is properly loaded
        if (typeof ace !== "undefined" && ace.edit) {
          console.log("Ace editor is ready");
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
        session.setUseWrapMode(false);

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
    }

    if (onLoad) {
      onLoad(editor);
    }
  };
  const defaultStyle = {
    border: "1px solid #e0e0e0",
    borderRadius: "8px",
    fontFamily: "Consolas, Monaco, 'Courier New', monospace",
    ...style,
  };

  if (!isLoaded) {
    if (loadError) {
      console.warn("CodeEditor failed to load, showing fallback textarea");
      return (
        <textarea
          value={value}
          onChange={(e) => !readOnly && onChange && onChange(e.target.value)}
          readOnly={readOnly}
          placeholder={placeholder}
          className={`${styles.fallbackTextarea} ${isDarkTheme ? styles.darkTheme : ""}`}
          style={{
            ...defaultStyle,
            height,
            fontSize: `${fontSize}px`,
          }}
        />
      );
    }

    return (
      <div className={`${styles.loadingContainer} ${isDarkTheme ? styles.darkTheme : ""}`} style={{ width, height }}>
        <div className={styles.loadingText}>
          <div>Loading code editor...</div>
          <div className={styles.loadingSubtext}>Please wait while we initialize the editor</div>
        </div>
      </div>
    );
  }

  try {
    return (
      <div className="codeEditorWrapper">
        <div
          style={{
            border: "1px solid #e0e0e0",
            borderRadius: "8px",
            overflow: "hidden",
            fontFamily: "Consolas, Monaco, monospace",
            backgroundColor: "#1e1e1e",
            position: "relative",
            marginTop: "8px",
          }}>
          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
              padding: "8px 12px",
              backgroundColor: "#2d2d30",
              borderBottom: "1px solid #3e3e42",
              fontSize: "12px",
            }}>
            <span
              style={{
                padding: "4px 8px",
                border: "1px solid #d0d7de",
                borderRadius: "4px",
                backgroundColor: "#3c3c3c",
                color: "#ffffff",
                fontSize: "12px",
                display: "inline-block",
              }}>
              Python
            </span>
          </div>
          <AceEditor
            ref={editorRef}
            mode={mode}
            theme={isDarkTheme ? "monokai" : theme}
            name={editorIdRef.current}
            onChange={readOnly ? undefined : handleChange}
            value={value}
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
              wrap: false,
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
            commands={[]} // Prevent any commands that might trigger worker loading
            {...props}
          />
        </div>
      </div>
    );
  } catch (error) {
    console.error("Error rendering AceEditor:", error);

    // Fallback to textarea if AceEditor fails
    return (
      <textarea
        value={value}
        onChange={(e) => !readOnly && onChange && onChange(e.target.value)}
        readOnly={readOnly}
        placeholder={placeholder}
        className={`${styles.fallbackTextarea} ${isDarkTheme ? styles.darkTheme : ""}`}
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