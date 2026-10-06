import React, { useState, useEffect, useCallback } from "react";
import ReactDOM from "react-dom";
import { useHookRepositoryService } from "../../services/hookRepositoryService";
import { useMessage } from "../../Hooks/MessageContext";
import { copyToClipboard } from "../../utils/clipboardUtils";
import CodeEditor from "../commonComponents/CodeEditor";
import Loader from "../commonComponents/Loader";
import IAFButton from "../../iafComponents/GlobalComponents/Buttons/Button";
import SVGIcons from "../../Icons/SVGIcons";
import styles from "./SampleHooksModal.module.css";

/**
 * Event badge color mapping.
 */
const EVENT_META = {
  PreToolUse: { color: "blue", icon: "shield" },
  PostToolUse: { color: "green", icon: "check-circle" },
  PreResponse: { color: "orange", icon: "lock" },
};

/**
 * SampleHooksModal — Popup showing 3 sample hook templates side-by-side.
 * Each template has Copy (clipboard) and Use Template (upload into form) buttons.
 *
 * @param {boolean} isOpen - Controls modal visibility
 * @param {Function} onClose - Close callback
 * @param {Function} onUseTemplate - Callback when user clicks "Use Template": receives { name, code, description }
 */
const SampleHooksModal = ({ isOpen, onClose, onUseTemplate }) => {
  const [sampleHooks, setSampleHooks] = useState([]);
  const [loading, setLoading] = useState(false);
  const [copiedKey, setCopiedKey] = useState(null);
  const [activeTab, setActiveTab] = useState(0);

  const { getSampleHooks } = useHookRepositoryService();
  const { addMessage } = useMessage();

  // Fetch sample hooks on open
  useEffect(() => {
    if (!isOpen) return;
    const fetchSamples = async () => {
      setLoading(true);
      try {
        const data = await getSampleHooks();
        setSampleHooks(data);
        setActiveTab(0);
      } catch {
        addMessage("Failed to load sample hooks", "error");
      } finally {
        setLoading(false);
      }
    };
    fetchSamples();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isOpen]);

  // Copy code to clipboard
  const handleCopy = useCallback(async (code, key) => {
    const result = await copyToClipboard(code);
    if (result === "success") {
      setCopiedKey(key);
      setTimeout(() => setCopiedKey(null), 2000);
    } else {
      addMessage("Failed to copy code", "error");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Use template — pre-fill form and close
  const handleUseTemplate = (hook) => {
    onUseTemplate({
      name: hook.name,
      code: hook.code,
      description: hook.description,
    });
    onClose();
  };

  if (!isOpen) return null;

  const activeHook = sampleHooks[activeTab] || null;

  return ReactDOM.createPortal(
    <div className={styles.overlay} onClick={onClose} role="dialog" aria-modal="true" aria-label="Sample Hook Templates">
      <div className={styles.modal} onClick={(e) => e.stopPropagation()}>
        <button className={styles.closeBtn} onClick={onClose} aria-label="Close modal" type="button">
          &times;
        </button>
        <div className={styles.container}>
          {/* Header */}
          <div className={styles.header}>
            <h3 className={styles.title}>
              <SVGIcons icon="code" width={18} height={18} />
              Sample Hook Templates
            </h3>
            <p className={styles.subtitle}>
              Choose a template to pre-fill the hook form. You can edit the code after selecting.
            </p>
          </div>

          {/* Content */}
          {loading ? (
            <div className={styles.loadingWrap}>
              <Loader />
            </div>
          ) : sampleHooks.length === 0 ? (
            <div className={styles.emptyState}>No sample hooks available</div>
          ) : (
            <>
              {/* Tab navigation */}
              <div className={styles.tabBar}>
                {sampleHooks.map((hook, idx) => {
                  const meta = EVENT_META[hook.event] || { color: "blue", icon: "code" };
                  return (
                    <button
                      key={hook.name}
                      type="button"
                      className={`${styles.tab} ${activeTab === idx ? styles.tabActive : ""} ${styles[`tab${meta.color}`]}`}
                      onClick={() => setActiveTab(idx)}
                    >
                      <span className={styles.tabName}>{hook.name}</span>
                      <span className={`${styles.eventBadge} ${styles[`badge${meta.color}`]}`}>
                        {hook.event}
                      </span>
                    </button>
                  );
                })}
              </div>

              {/* Code editor with action buttons in its header */}
              <div className={styles.codeSection}>
                <div className={styles.codeSectionHeader}>
                  <span className={styles.codeSectionLabel}>Python</span>
                  {activeHook && (
                    <div className={styles.actionRow}>
                      <IAFButton
                        type="secondary"
                        onClick={() => handleCopy(activeHook.code, activeHook.name)}
                        title="Copy code to clipboard"
                        icon={
                          <SVGIcons
                            icon={copiedKey === activeHook.name ? "check" : "fa-regular fa-copy"}
                            width={14}
                            height={14}
                          />
                        }
                      >
                        {copiedKey === activeHook.name ? "Copied!" : "Copy"}
                      </IAFButton>
                      <IAFButton
                        type="primary"
                        onClick={() => handleUseTemplate(activeHook)}
                        title="Use this template"
                        icon={<SVGIcons icon="upload" width={14} height={14} />}
                      >
                        Use Template
                      </IAFButton>
                    </div>
                  )}
                </div>
                <div className={styles.codeWrap}>
                  {sampleHooks.map((hook, idx) => (
                    <div
                      key={hook.name}
                      className={`${styles.panel} ${activeTab === idx ? styles.panelActive : ""}`}
                    >
                      <CodeEditor
                        codeToDisplay={hook.code}
                        readOnly={true}
                        mode="python"
                        height="calc(80vh - 200px)"
                        fontSize={12}
                        placeholder=""
                        showLanguageBadge={false}
                      />
                    </div>
                  ))}
                </div>
              </div>
            </>
          )}
        </div>
      </div>
    </div>,
    document.body
  );
};

export default SampleHooksModal;