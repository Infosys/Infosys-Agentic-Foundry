import { useState, useEffect, useCallback, useMemo, useRef } from "react";
import { APIs, threshold_epoch_config, inference_config_ui } from "../../constant";
import useFetch from "../../Hooks/useAxios";
import { useMessage } from "../../Hooks/MessageContext";
import IAFButton from "../../iafComponents/GlobalComponents/Buttons/Button";
import Loader from "../commonComponents/Loader.jsx";
import styles from "./InferenceConfig.module.css";

/**
 * Default configuration values - used when API is unavailable or fails
 */
const DEFAULT_CONFIG = threshold_epoch_config;

/**
 * Get all slider keys from the UI configuration
 * Used to dynamically generate state and comparison logic
 */
const getAllSliderKeys = () => {
  return inference_config_ui.sections.flatMap((section) => section.sliders.map((slider) => slider.key));
};

/**
 * InferenceConfig Component
 *
 * Admin page for managing inference configuration limits.
 * Uses configuration-driven approach from constant.js for easy extensibility.
 *
 * API Endpoints:
 * - GET /admin/config/limits - Fetch current values on mount
 * - PUT /admin/config/limits - Update values when modified
 * - POST /admin/config/limits/reset - Reset to default values
 */
const InferenceConfig = () => {
  const { fetchData, putData, postData } = useFetch();
  const { addMessage } = useMessage();

  // Ref to prevent duplicate API calls in React Strict Mode
  const hasFetchedRef = useRef(false);

  // Loading and operation states
  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);
  const [isResetting, setIsResetting] = useState(false);

  // API availability state
  const [apiAvailable, setApiAvailable] = useState(true);
  const [loadError, setLoadError] = useState(null);
  const [bannerDismissed, setBannerDismissed] = useState(false);

  // Dynamic state object for all slider values
  const [configValues, setConfigValues] = useState(() => ({ ...DEFAULT_CONFIG }));

  // Original values for change detection
  const [originalValues, setOriginalValues] = useState(null);

  // Detect if values have changed from original
  const hasChanges = useMemo(() => {
    if (!originalValues) return false;
    return getAllSliderKeys().some((key) => originalValues[key] !== configValues[key]);
  }, [originalValues, configValues]);

  // Update a single config value
  const updateConfigValue = useCallback((key, value) => {
    setConfigValues((prev) => ({ ...prev, [key]: value }));
  }, []);

  // Set all values from API response or default config
  const setValuesFromResponse = useCallback((data) => {
    const newValues = { ...DEFAULT_CONFIG };
    getAllSliderKeys().forEach((key) => {
      if (data[key] !== undefined) {
        newValues[key] = data[key];
      }
    });
    setConfigValues(newValues);
    setOriginalValues({ ...newValues });
  }, []);

  /**
   * Fetch current configuration on mount
   */
  useEffect(() => {
    if (hasFetchedRef.current) return;
    hasFetchedRef.current = true;

    const loadConfig = async () => {
      setIsLoading(true);
      setLoadError(null);

      try {
        const response = await fetchData(APIs.GET_INFERENCE_CONFIG_LIMITS);
        if (response) {
          setValuesFromResponse(response);
          setApiAvailable(true);
        }
      } catch (error) {
        const status = error?.response?.status;
        let errorMessage = "Failed to load inference configuration";

        if (status === 404) {
          errorMessage = "Configuration API not available. Using default values.";
        } else if (status === 401 || status === 403) {
          errorMessage = "Not authorized to access configuration";
        } else if (!error.response) {
          errorMessage = "Network error. Using default values.";
        }

        console.warn("InferenceConfig: API unavailable, using defaults", error);
        setApiAvailable(false);
        setLoadError(errorMessage);
        setValuesFromResponse(DEFAULT_CONFIG);
        addMessage(errorMessage, "error");
      } finally {
        setIsLoading(false);
      }
    };

    loadConfig();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Handle Update button click
  const handleUpdate = async () => {
    if (!apiAvailable) {
      addMessage("Cannot save: Configuration API is not available.", "error");
      return;
    }
    setIsSaving(true);
    try {
      const updateResponse = await putData(APIs.UPDATE_INFERENCE_CONFIG_LIMITS, configValues);
      setOriginalValues(updateResponse.config);
      addMessage(updateResponse.message, "success");
    } catch (error) {
      addMessage("Failed to update inference configuration", "error");
      console.error("Error updating inference config:", error);
    } finally {
      setIsSaving(false);
    }
  };

  // Handle Reset button click
  const handleReset = async () => {
    if (!apiAvailable) {
      setValuesFromResponse(DEFAULT_CONFIG);
      addMessage("Reset to default values (API unavailable)", "success");
      return;
    }
    setIsResetting(true);
    try {
      const response = await postData(APIs.RESET_INFERENCE_CONFIG_LIMITS, {});
      if (response) {
        setValuesFromResponse(response.config);
        addMessage(response.message, "success");
      }
    } catch (error) {
      addMessage("Failed to reset inference configuration", "error");
      console.error("Error resetting inference config:", error);
    } finally {
      setIsResetting(false);
    }
  };

  // Calculate slider progress for visual fill
  const calculateProgress = (value, min, max) => {
    return Math.round(((value - min) / (max - min)) * 100);
  };

  // Render a single slider control
  const renderSlider = ({ key, label, min, max, step, isFloat }) => {
    const value = configValues[key];
    const progress = calculateProgress(value, min, max);
    const displayValue = isFloat ? value.toFixed(2) : value;

    return (
      <div key={key} className={styles.sliderGroup}>
        <div className={styles.sliderHeader}>
          <span className={styles.sliderLabel}>{label}</span>
          <span className={styles.sliderValue}>{displayValue}</span>
        </div>
        <div className={styles.rangeWrapper}>
          <input
            type="range"
            min={min}
            max={max}
            step={step}
            value={value}
            onChange={(e) => updateConfigValue(key, isFloat ? parseFloat(e.target.value) : parseInt(e.target.value, 10))}
            className={styles.sliderInput}
            style={{ "--progress": `${progress}%` }}
            disabled={isLoading || isSaving || isResetting}
            aria-label={label}
          />
        </div>
        <div className={styles.sliderRow}>
          <span className={styles.rangeLabel}>{min}</span>
          <span className={styles.rangeLabel}>{max}</span>
        </div>
      </div>
    );
  };

  // Render a section with its sliders
  const renderSection = (section) => (
    <div key={section.id} className={styles.section}>
      <h3 className={styles.sectionTitle}>{section.title}</h3>
      <p className={styles.sectionDescription}>{section.description}</p>
      {section.sliders.map(renderSlider)}
    </div>
  );

  if (isLoading) {
    return <Loader />;
  }

  return (
    <div className={styles.container}>
      {/* Header */}
      <div className={styles.header}>
        <h2 className={styles.title}>Inference Configuration</h2>
        <p className={styles.description}>Configure the inference parameters for agent evaluation, validation, and execution limits.</p>
      </div>

      {/* API Unavailable Warning Banner */}
      {!apiAvailable && loadError && !bannerDismissed && (
        <div className={styles.warningBanner}>
          <span className={styles.warningIcon}>⚠️</span>
          <span className={styles.warningText}>{loadError} Values shown are defaults and cannot be saved until the API is available.</span>
          <button className={styles.bannerCloseBtn} onClick={() => setBannerDismissed(true)} aria-label="Dismiss warning" title="Dismiss">
            ✕
          </button>
        </div>
      )}

      {/* Dynamically rendered sections from config */}
      <div className={styles.sectionsGrid}>{inference_config_ui.sections.map(renderSection)}</div>

      {/* Action buttons */}
      <div className={styles.actionBar}>
        <IAFButton type="secondary" onClick={handleReset} disabled={isSaving || isResetting} loading={isResetting} aria-label="Reset to default values">
          Reset
        </IAFButton>
        <IAFButton
          type="primary"
          onClick={handleUpdate}
          disabled={!hasChanges || isSaving || isResetting}
          loading={isSaving}
          aria-label="Update configuration"
          title={!apiAvailable ? "Changes won't persist: API is unavailable" : ""}>
          Update
        </IAFButton>
      </div>
    </div>
  );
};

export default InferenceConfig;
