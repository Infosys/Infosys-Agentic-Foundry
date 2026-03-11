import { useState, useEffect } from "react";
import { FullModal } from "../../iafComponents/GlobalComponents/FullModal";
import IAFButton from "../../iafComponents/GlobalComponents/Buttons/Button";
import SVGIcons from "../../Icons/SVGIcons.js";
import TextareaWithActions from "../commonComponents/TextareaWithActions";
import Toggle from "../commonComponents/Toggle";
import styles from "./EditAccessKeyModal.module.css";

/**
 * EditAccessKeyModal Component
 * Modal for viewing access key details and editing values and exclusions
 * - Shows existing values/exclusions as chips
 * - Input to add new values/exclusions
 * - Click X on chip to remove it
 */
export default function EditAccessKeyModal({
  onClose,
  onSubmit,
  loading,
  accessKeyData,
  detailsLoading = false
}) {
  // Current values (combined existing + new, minus removed)
  const [values, setValues] = useState([]);
  // Current exclusions (combined existing + new, minus removed)
  const [exclusions, setExclusions] = useState([]);
  // Track original values to compute diff on submit
  const [originalValues, setOriginalValues] = useState([]);
  // Track original exclusions to compute diff on submit
  const [originalExclusions, setOriginalExclusions] = useState([]);
  // Input for new value
  const [newValue, setNewValue] = useState("");
  // Input for new exclusion
  const [newExclusion, setNewExclusion] = useState("");
  // Toggle state for showing exclusions section
  const [showExclusions, setShowExclusions] = useState(false);
  // Preserve values before enabling "Include All Values" toggle
  const [preservedValues, setPreservedValues] = useState([]);

  // Initialize values from accessKeyData
  useEffect(() => {
    // Support both 'values' (old format) and 'allowed_values' (new format from /my-access/full)
    const allowedValues = accessKeyData?.allowed_values || accessKeyData?.values || [];
    const excludedVals = accessKeyData?.excluded_values || [];

    const valuesArray = Array.isArray(allowedValues) ? [...allowedValues] : [];
    const exclusionsArray = Array.isArray(excludedVals) ? [...excludedVals] : [];

    setValues(valuesArray);
    setExclusions(exclusionsArray);
    setOriginalValues(valuesArray);
    setOriginalExclusions(exclusionsArray);
    setNewValue("");
    setNewExclusion("");
    // Initialize toggle state: show exclusions if values contain "*" (include all) or if there are existing exclusions
    const hasWildcard = valuesArray.includes("*");
    setShowExclusions(hasWildcard || exclusionsArray.length > 0);
  }, [accessKeyData]);

  // Add a new value
  const handleAddValue = () => {
    const trimmedValue = newValue.trim();
    if (trimmedValue && !values.includes(trimmedValue)) {
      setValues([...values, trimmedValue]);
      setNewValue("");
    }
  };

  // Remove a value
  const handleRemoveValue = (valueToRemove) => {
    setValues(values.filter((v) => v !== valueToRemove));
  };

  // Handle key press for adding values
  const handleKeyPress = (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      handleAddValue();
    }
  };

  // Add a new exclusion
  const handleAddExclusion = () => {
    const trimmedValue = newExclusion.trim();
    if (trimmedValue && !exclusions.includes(trimmedValue)) {
      setExclusions([...exclusions, trimmedValue]);
      setNewExclusion("");
    }
  };

  // Remove an exclusion
  const handleRemoveExclusion = (valueToRemove) => {
    setExclusions(exclusions.filter((v) => v !== valueToRemove));
  };

  // Handle key press for adding exclusions
  const handleExclusionKeyPress = (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      handleAddExclusion();
    }
  };

  const accessKeyName = accessKeyData?.access_key || accessKeyData?.name || "Access Key";

  // Compute changes for API
  const addValues = values.filter((v) => !originalValues.includes(v));
  const removeValues = originalValues.filter((v) => !values.includes(v));
  const addExclusions = exclusions.filter((v) => !originalExclusions.includes(v));
  const removeExclusions = originalExclusions.filter((v) => !exclusions.includes(v));

  const hasChanges = addValues.length > 0 || removeValues.length > 0 || addExclusions.length > 0 || removeExclusions.length > 0;

  // Handle form submission
  const handleSubmit = (e) => {
    e.preventDefault();

    // Submit add_values, remove_values, add_exclusions, and remove_exclusions as required by API
    onSubmit({
      add_values: addValues,
      remove_values: removeValues,
      add_exclusions: addExclusions,
      remove_exclusions: removeExclusions
    });
  };

  // Header info - matching ToolOnBoarding pattern
  const getHeaderInfo = () => {
    const info = [];
    if (accessKeyData?.department_name) {
      info.push({
        label: "Department",
        value: accessKeyData.department_name
      });
    }
    if (accessKeyData?.created_by) {
      info.push({
        label: "Created By",
        value: accessKeyData.created_by
      });
    }
    return info;
  };

  // Footer render function to ensure it updates with state changes
  const renderFooter = () => (
    <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", width: "100%" }}>
      {/* Left side: Toggle - Always show */}
      <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
        <Toggle
          value={showExclusions}
          onChange={(e) => {
            const newState = e.target.checked;
            setShowExclusions(newState);
            if (newState) {
              // When enabling "Include All Values", preserve current values and set to ["*"]
              setPreservedValues(values.filter(v => v !== "*"));
              setValues(["*"]);
              setNewValue("");
            } else {
              // When disabling, restore preserved values and clear exclusions
              setValues(preservedValues);
              setExclusions([]);
              setNewExclusion("");
            }
          }}
          disabled={loading}
        />
        <span style={{
          fontSize: "13px",
          color: "var(--content-color, #555)",
          whiteSpace: "nowrap"
        }}>
          Include All Values
        </span>
      </div>

      {/* Right side: Buttons */}
      <div style={{ display: "flex", gap: "12px" }}>
        <IAFButton
          type="secondary"
          onClick={onClose}
          disabled={loading}
        >
          Cancel
        </IAFButton>
        <IAFButton
          type="primary"
          onClick={handleSubmit}
          disabled={loading || !hasChanges}
        >
          {loading ? "Updating..." : "Update Access Key"}
        </IAFButton>
      </div>
    </div>
  );

  return (
    <FullModal
      isOpen={true}
      onClose={onClose}
      title={accessKeyName}
      loading={detailsLoading}
      headerInfo={getHeaderInfo()}
      footer={renderFooter()}
    >
      <form onSubmit={handleSubmit} className="form-section">
        <div className="formContent">
          <div className={`form ${styles.compactForm}`}>
            {/* Department - Read Only */}
            {accessKeyData?.department_name && (
              <div className="formGroup">
                <label className="label-desc">Department</label>
                <input
                  type="text"
                  value={accessKeyData.department_name}
                  className={`input ${styles.readOnlyInput}`}
                  disabled={true}
                  readOnly={true}
                />
              </div>
            )}

            {/* Description - Using TextareaWithActions like ToolOnBoarding */}
            <div className="formGroup">
              <TextareaWithActions
                name="description"
                value={accessKeyData?.description || ""}
                label="Description"
                required={false}
                disabled={true}
                readOnly={true}
                placeholder="No description provided"
                rows={2}
                showCopy={true}
                showExpand={true}
              />
            </div>

            {/* Include Values Section */}
            <div className="formGroup">
              <label className="label-desc">
                Include Values
              </label>

              {/* Show * indicator when Include All Values is enabled */}
              {showExclusions ? (
                <div className={styles.chipContainer}>
                  <span className={styles.chip}>
                    *
                  </span>
                </div>
              ) : (
                <>
                  {/* Input to add new values */}
                  <div className={styles.inputWithButton}>
                    <input
                      type="text"
                      value={newValue}
                      onChange={(e) => setNewValue(e.target.value)}
                      onKeyPress={handleKeyPress}
                      placeholder="Enter a value and press Enter or click Add"
                      className="input"
                      disabled={loading}
                    />
                    <button
                      type="button"
                      onClick={handleAddValue}
                      className={styles.addButton}
                      disabled={loading || !newValue.trim()}
                    >
                      <SVGIcons icon="plus" width={16} height={16} />
                      Add
                    </button>
                  </div>

                  {/* Display all values as chips */}
                  {values.length > 0 && (
                    <div className={styles.chipContainer}>
                      {values.map((value, index) => (
                        <span key={`value-${index}`} className={styles.chip}>
                          {value}
                          <button
                            type="button"
                            onClick={() => handleRemoveValue(value)}
                            className={styles.chipRemoveBtn}
                            disabled={loading}
                            title="Remove this value"
                          >
                            <SVGIcons icon="x" width={12} height={12} />
                          </button>
                        </span>
                      ))}
                    </div>
                  )}
                </>
              )}
            </div>

            {/* Exclude Values Section - Only show when toggle is OFF (not including all) */}
            {showExclusions && (
              <div className="formGroup">
                <label className="label-desc">
                  Exclude Values
                </label>

                {/* Input to add new exclusions */}
                <div className={styles.inputWithButton}>
                  <input
                    type="text"
                    value={newExclusion}
                    onChange={(e) => setNewExclusion(e.target.value)}
                    onKeyPress={handleExclusionKeyPress}
                    placeholder="Enter an exclusion and press Enter or click Add"
                    className="input"
                    disabled={loading}
                  />
                  <button
                    type="button"
                    onClick={handleAddExclusion}
                    className={styles.addButton}
                    disabled={loading || !newExclusion.trim()}
                  >
                    <SVGIcons icon="plus" width={16} height={16} />
                    Add
                  </button>
                </div>

                {/* Display all exclusions as chips */}
                {exclusions.length > 0 && (
                  <div className={styles.chipContainer}>
                    {exclusions.map((value, index) => (
                      <span key={`exclusion-${index}`} className={styles.chip}>
                        {value}
                        <button
                          type="button"
                          onClick={() => handleRemoveExclusion(value)}
                          className={styles.chipRemoveBtn}
                          disabled={loading}
                          title="Remove this exclusion"
                        >
                          <SVGIcons icon="x" width={12} height={12} />
                        </button>
                      </span>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      </form>
    </FullModal>
  );
}
