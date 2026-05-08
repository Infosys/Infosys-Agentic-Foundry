import React, { useState, useMemo } from "react";
import styles from "./ConflictResolutionModal.module.css";
import { Modal } from "../commonComponents/Modal";
import Button from "../../iafComponents/GlobalComponents/Buttons/Button";
import Loader from "../commonComponents/Loader";

/**
 * ConflictResolutionModal
 *
 * Shows when /tools/import-preview returns has_conflicts: true.
 *
 * Handles two conflict scenarios:
 *   1. status="conflict" — tool(s) exist with different code → show radio options
 *      (create_new_tool, create_new_version, skip).
 *      Supports MULTIPLE conflicting tools — each gets its own new-name input.
 *   2. status="needs_new_name" — tool(s) exist in recycle bin → show info message
 *      and only allow "create_new_tool" (user provides new names).
 *
 * Returns the selected conflict_resolution string and name_overrides on proceed.
 *
 * @param {Object}   props.previewData  - result from import-preview (tools[], conflicts_count)
 * @param {Function} props.onClose      - cancel / close handler
 * @param {Function} props.onProceed    - called with (conflictResolution: string, nameOverrides: string|null)
 * @param {boolean}  props.loading      - import in progress
 */
const ConflictResolutionModal = ({
  previewData,
  onClose,
  onProceed,
  loading = false,
  validationErrors = null,
}) => {
  const tools = previewData?.tools || [];

  // Collect ALL conflicting tools (Scenario 1)
  const conflictTools = useMemo(
    () => tools.filter((t) => t.status === "conflict" && t.requires_decision),
    [tools]
  );

  // Collect ALL needs_new_name tools (Scenario 2) — only if no conflict tools
  const needsNameTools = useMemo(
    () =>
      conflictTools.length === 0
        ? tools.filter((t) => t.status === "needs_new_name" && t.requires_decision)
        : [],
    [tools, conflictTools]
  );

  // Which set of tools are we dealing with?
  const activeTools = conflictTools.length > 0 ? conflictTools : needsNameTools;
  const isNeedsNameScenario = conflictTools.length === 0 && needsNameTools.length > 0;

  // Track selected radio option (Scenario 1 only)
  const [selected, setSelected] = useState(
    conflictTools[0]?.options?.[0]?.value || ""
  );

  // Track new names per tool: { "original_tool_name": "new_name_entered" }
  const [newToolNames, setNewToolNames] = useState(() => {
    const initial = {};
    activeTools.forEach((t) => {
      const name = t.tool_name || t.name || "";
      if (name) initial[name] = "";
    });
    return initial;
  });

  const updateToolName = (originalName, value) => {
    setNewToolNames((prev) => ({ ...prev, [originalName]: value }));
  };

  // Resolved selection for needs_new_name is always create_new_tool
  const resolvedSelection = isNeedsNameScenario ? "create_new_tool" : selected;

  // All conflicting tools must have a non-empty new name when create_new_tool is selected
  const allNamesProvided =
    resolvedSelection === "create_new_tool"
      ? activeTools.every((t) => {
        const key = t.tool_name || t.name || "";
        return newToolNames[key]?.trim();
      })
      : true;

  const isProceedDisabled = loading || !resolvedSelection || !allNamesProvided;

  const handleProceed = () => {
    if (isProceedDisabled) return;

    // Build name_overrides JSON string mapping original → new for each tool
    let nameOverrides = null;
    if (resolvedSelection === "create_new_tool") {
      const overridesObj = {};
      activeTools.forEach((t) => {
        const originalName = t.tool_name || t.name || "";
        const newName = newToolNames[originalName]?.trim();
        if (originalName && newName) {
          overridesObj[originalName] = newName;
        }
      });
      if (Object.keys(overridesObj).length > 0) {
        nameOverrides = JSON.stringify(overridesObj);
      }
    }
    onProceed(resolvedSelection, nameOverrides);
  };

  return (
    <Modal
      isOpen={true}
      onClose={onClose}
      size="md"
      ariaLabel="Import Conflict"
      className={styles.conflictModal}
      showCloseButton={true}
      closeOnOverlayClick={!loading}
      closeOnEsc={!loading}
    >
      {loading && <Loader />}

      <div className={styles.modalHeader}>
        <h2 className={styles.modalTitle}>Import Conflict</h2>
        {activeTools.length > 1 && (
          <span className={styles.conflictCount}>
            {activeTools.length} conflicting tools
          </span>
        )}
      </div>

      <div className={styles.modalBody}>
        {activeTools.length > 0 && (
          <>
            {/* Show first conflict message as the summary */}
            <p className={styles.conflictMessage}>
              {activeTools.length === 1
                ? activeTools[0].message
                : `${activeTools.length} tools have name conflicts and need to be resolved.`}
            </p>

            {/* Scenario 1: tool(s) exist with different code — show radio options */}
            {conflictTools.length > 0 && (
              <>
                <p className={styles.prompt}>What would you like to do?</p>

                <div className={styles.optionsList}>
                  {conflictTools[0].options.map((opt) => (
                    <label
                      key={opt.value}
                      className={`${styles.optionItem} ${selected === opt.value ? styles.optionSelected : ""
                        }`}
                    >
                      <input
                        type="radio"
                        name="conflict-resolution"
                        value={opt.value}
                        checked={selected === opt.value}
                        onChange={() => setSelected(opt.value)}
                        className={styles.radio}
                        disabled={loading}
                      />
                      <div className={styles.optionContent}>
                        <span className={styles.optionLabel}>{opt.label}</span>
                        {opt.description && (
                          <span className={styles.optionDesc}>
                            {opt.description}
                          </span>
                        )}
                      </div>
                    </label>
                  ))}
                </div>
              </>
            )}

            {/* Scenario 2: tool(s) in recycle bin — show info */}
            {isNeedsNameScenario && (
              <div className={styles.needsNameInfo}>
                <p className={styles.prompt}>
                  {needsNameTools.length === 1
                    ? "The tool will be imported with a new name to avoid the conflict."
                    : "The tools will be imported with new names to avoid conflicts."}
                </p>
              </div>
            )}

            {/* New name inputs — one per conflicting tool when create_new_tool is selected */}
            {resolvedSelection === "create_new_tool" && (
              <div className={styles.newNameSection}>
                {activeTools.map((tool, idx) => {
                  const originalName = tool.tool_name || tool.name || "";
                  return (
                    <div key={originalName || idx} className={styles.newNameGroup}>
                      <label className={styles.newNameLabel}>
                        <span className={styles.originalName}>{originalName}</span>
                        <span className={styles.arrowIcon}>→</span>
                      </label>
                      <input
                        type="text"
                        className={styles.newNameInput}
                        value={newToolNames[originalName] || ""}
                        onChange={(e) => updateToolName(originalName, e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === "Enter" && !isProceedDisabled) handleProceed();
                        }}
                        placeholder={`Enter new name for ${originalName}`}
                        autoFocus={idx === 0}
                        disabled={loading}
                      />
                      {validationErrors?.[originalName] && !validationErrors[originalName].valid && (
                        <span className={styles.validationError}>
                          {validationErrors[originalName].reason}
                        </span>
                      )}
                    </div>
                  );
                })}
                <span className={styles.newNameHint}>
                  Names ending with _v1, _v2, etc. are not allowed.
                </span>
              </div>
            )}
          </>
        )}
      </div>

      <div className={styles.modalFooter}>
        <Button type="secondary" onClick={onClose} disabled={loading}>
          Cancel
        </Button>
        <Button
          type="primary"
          onClick={handleProceed}
          disabled={isProceedDisabled}
          loading={loading}
        >
          Import
        </Button>
      </div>
    </Modal>
  );
};

export default ConflictResolutionModal;
