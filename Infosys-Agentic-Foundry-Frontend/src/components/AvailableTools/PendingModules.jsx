import React, { useState, useEffect } from "react";
import useFetch from "../../Hooks/useAxios.js";
import { APIs } from "../../constant";
import { useErrorHandler } from "../../Hooks/useErrorHandler";
import { useMessage } from "../../Hooks/MessageContext";
import styles from "./PendingModules.module.css";
import AceEditor from "react-ace";
import "ace-builds/src-noconflict/mode-python";
import "ace-builds/src-noconflict/theme-monokai";
import Loader from "../commonComponents/Loader.jsx";

const PendingModules = () => {
  const [pendingModules, setPendingModules] = useState([]);
  const [expandedModule, setExpandedModule] = useState(null);
  const [loading, setLoading] = useState(false);
  const { fetchData } = useFetch();
  const { handleError } = useErrorHandler();
  const { addMessage } = useMessage();

  useEffect(() => {
    fetchPendingModules();
  }, []);

  const fetchPendingModules = async () => {
    setLoading(true);
    try {
      const response = await fetchData(APIs.PENDING_MODULES, "GET");
      if (response?.success && response?.details) {
        setPendingModules(response.details);
      } else {
        setPendingModules([]);
      }
    } catch (error) {
      handleError(error, { context: "PendingModules.fetchPendingModules" });
      addMessage("Failed to fetch pending modules", "error");
      setPendingModules([]);
    } finally {
      setLoading(false);
    }
  };

  const toggleExpand = (moduleName) => {
    setExpandedModule(expandedModule === moduleName ? null : moduleName);
  };

  const formatDate = (dateString) => {
    if (!dateString) return "N/A";
    try {
      const date = new Date(dateString);
      return date.toLocaleString("en-US", {
        year: "numeric",
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      });
    } catch (error) {
      return dateString;
    }
  };

  return (
    <div className={styles.pageWrapper}>
      {loading && (
        <div className={styles.loaderOverlay}>
          <Loader contained />
        </div>
      )}
      <h6 className={styles.pageHeading}>PENDING MODULES</h6>
      {!loading && (!pendingModules || pendingModules.length === 0) ? (
        <div className={styles.container}>
          <div className={styles.emptyState}>
            <p>No pending modules found</p>
          </div>
        </div>
      ) : !loading ? (
        <div className={styles.container}>
          <div className={styles.modulesList}>
          {pendingModules.map((module, index) => (
            <div key={`${module.module_name}-${index}`} className={styles.moduleItem}>
              <div 
                className={styles.moduleHeader} 
                onClick={() => toggleExpand(module.module_name)}
              >
                <div className={styles.moduleNameWrapper}>
                <span className={styles.moduleName}>{module.module_name}</span>
              </div>
            </div>
            
            {expandedModule === module.module_name && (
              <div className={styles.moduleDetails}>
                <div className={styles.detailsGrid}>
                  <div className={styles.detailItem}>
                    <span className={styles.detailLabel}>Created By:</span>
                    <span className={styles.detailValue}>{module.created_by || "N/A"}</span>
                  </div>
                  <div className={styles.detailItem}>
                    <span className={styles.detailLabel}>Created On:</span>
                    <span className={styles.detailValue}>{formatDate(module.created_on)}</span>
                  </div>
                </div>
                
                <div className={styles.codeSection}>
                  <div className={styles.codeSectionHeader}>
                    <span className={styles.detailLabel}>Code Snippet:</span>
                  </div>
                  <div className={styles.codeEditorWrapper}>
                    <AceEditor
                      mode="python"
                      theme="monokai"
                      value={module.code_snippet || ""}
                      readOnly={true}
                      name={`code-editor-${module.module_name}`}
                      editorProps={{ $blockScrolling: true }}
                      width="100%"
                      height="200px"
                      fontSize={13}
                      showPrintMargin={false}
                      showGutter={true}
                      highlightActiveLine={false}
                      setOptions={{
                        enableBasicAutocompletion: false,
                        enableLiveAutocompletion: false,
                        enableSnippets: false,
                        showLineNumbers: true,
                        tabSize: 4,
                      }}
                    />
                  </div>
                </div>
              </div>
            )}
          </div>
        ))}
          </div>
        </div>
      ) : null}
    </div>
  );
};

export default PendingModules;
