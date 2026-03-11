import React, { useState, useCallback, useEffect, useRef } from "react";
import SVGIcons from "../../Icons/SVGIcons";
import style from "../../css_modules/ExecutorPanel.module.css";
import { useMessage } from "../../Hooks/MessageContext";
import useFetch from "../../Hooks/useAxios.js";
import NewCommonDropdown from "./NewCommonDropdown";
import { APIs } from "../../constant";
import Loader from "./Loader.jsx";
import IAFButton from "../../iafComponents/GlobalComponents/Buttons/Button";

const JSON_INDENT = 2;

/**
 * Converts a string to Title Case (e.g., "user_name" -> "User Name")
 */
const toTitleCase = (str) =>
  str
    ? str
        .split(/[_\s]+/)
        .map((w) => w.charAt(0).toUpperCase() + w.slice(1).toLowerCase())
        .join(" ")
    : "Provide Value";

/**
 * Determines if a parameter should be treated as mandatory
 * - If `mandatory` is explicitly set (true/false), use that value
 * - Fallback: treat as mandatory if no default value exists
 * Works consistently for both tools and servers
 */
const isMandatoryParam = (param) => {
  if (typeof param.mandatory === "boolean") {
    return param.mandatory;
  }
  // Fallback: mandatory if no default exists
  return param.default == null;
};

/**
 * Gets the initial value for an input field based on mandatory status
 * - Mandatory params with default: pre-fill with default value
 * - Mandatory params without default: empty (user must fill)
 * - Optional params: always empty (default shown as placeholder)
 */
const getInitialValue = (param) => {
  const isMandatory = isMandatoryParam(param);
  if (isMandatory && param.default != null) {
    return String(param.default);
  }
  return "";
};

/**
 * Gets placeholder text for an input field
 * - Mandatory params: no placeholder (value is pre-filled or user must enter)
 * - Optional params with default: show default as hint
 * - Optional params without default: show "Optional"
 */
const getPlaceholder = (param) => {
  const isMandatory = isMandatoryParam(param);
  if (!isMandatory && param.default != null) {
    return `Optional - Default: "${param.default}"`;
  }
  if (!isMandatory) {
    return "Optional";
  }
  return "";
};

const ExecutorPanel = ({ code = "", mode = "tool", autoExecute = false, executeTrigger = 0, onClose = () => {}, onRunStart = () => {}, onRunComplete = () => {} }) => {
  const { addMessage } = useMessage();
  const { postData } = useFetch();

  const [runLoading, setRunLoading] = useState(false);

  // Active params for current execution context (server selected tool OR tool required inputs)
  const [inputsMeta, setInputsMeta] = useState([]);
  // Full server tool catalog (each { name, params: [...] })
  const [serverTools, setServerTools] = useState([]);
  const [selectedTool, setSelectedTool] = useState("");

  const [inputValues, setInputValues] = useState({});
  const [paramErrors, setParamErrors] = useState({});
  const [executionResult, setExecutionResult] = useState(null);
  const executionResultRef = useRef(null);
  const containerRef = useRef(null);
  const executedTriggersRef = useRef(new Set());

  // -------- Rendering helpers --------

  /**
   * Verifies if the response data is JSON or string and renders appropriately
   * Handles edge cases like JSON strings, plain text, and various data formats
   */
  const renderValidationContent = useCallback((data) => {
    // Handle null or undefined
    if (data === null || data === undefined) {
      return <pre className={style.success_error_content}>No output</pre>;
    }

    // If data is already an object (JSON), render as formatted JSON
    if (typeof data === "object") {
      return <pre className={style.success_error_content}>{JSON.stringify(data, null, JSON_INDENT)}</pre>;
    }

    // If data is a string, try to parse as JSON
    if (typeof data === "string") {
      const trimmedData = data.trim();

      // Try to parse as JSON if it looks like JSON (starts with { or [)
      if ((trimmedData.startsWith("{") && trimmedData.endsWith("}")) || (trimmedData.startsWith("[") && trimmedData.endsWith("]"))) {
        try {
          const parsedJson = JSON.parse(trimmedData);
          return <pre className={style.success_error_content}>{JSON.stringify(parsedJson, null, JSON_INDENT)}</pre>;
        } catch {
          // If parsing fails, render as plain string
          return <pre className={style.success_error_content}>{data}</pre>;
        }
      }

      // Plain string response
      return <pre className={style.success_error_content}>{data}</pre>;
    }

    // Handle boolean
    if (typeof data === "boolean") {
      return <pre className={style.success_error_content}>{data.toString()}</pre>;
    }

    // Handle number
    if (typeof data === "number") {
      return <pre className={style.success_error_content}>{String(data)}</pre>;
    }

    // Fallback for any other type
    return <pre className={style.success_error_content}>{String(data)}</pre>;
  }, []);

  // -------- Param helpers --------
  const setActiveParams = (paramsArray) => {
    const params = paramsArray || [];
    setInputsMeta(params);

    // Initialize values based on mandatory status
    // - Mandatory with default: pre-fill
    // - Optional: leave empty (default shown as placeholder)
    const initialValues = {};
    params.forEach((p) => {
      initialValues[p.name] = getInitialValue(p);
    });
    setInputValues(initialValues);
    setParamErrors({});
  };

  const validateParams = () => {
    if (!inputsMeta.length) return true;

    const errs = {};
    inputsMeta.forEach((p) => {
      const isMandatory = isMandatoryParam(p);

      if (isMandatory) {
        const val = inputValues[p.name];
        const isEmpty =
          val === "" ||
          val === null ||
          val === undefined ||
          (Array.isArray(val) && val.length === 0) ||
          (typeof val === "object" && !Array.isArray(val) && Object.keys(val).length === 0);

        if (isEmpty) {
          errs[p.name] = `${toTitleCase(p.name)} is required`;
        }
      }
    });

    setParamErrors(errs);
    return Object.keys(errs).length === 0;
  };

  const buildArguments = () => {
    const args = {};
    inputsMeta.forEach((p) => {
      const userValue = inputValues[p.name];

      // Include value if user provided one
      if (userValue !== "" && userValue != null) {
        args[p.name] = userValue;
      }
      // For optional params with no user input, include default if exists
      else if (!isMandatoryParam(p) && p.default != null) {
        args[p.name] = p.default;
      }
    });
    return args;
  };

  const handleParamChange = (name, value) => {
    setInputValues((prev) => ({ ...prev, [name]: value }));
    if (paramErrors[name]) setParamErrors((e) => ({ ...e, [name]: "" }));
  };

  // -------- Response handling (shared) --------
  const processResponse = (response) => {
    // Server mode introspection: list of tools (each has params)
    if (mode === "server" && Array.isArray(response?.inputs_required) && response.inputs_required.length && !response.success && response.error === "") {
      setServerTools(response.inputs_required);
      const first = response.inputs_required[0];
      setSelectedTool(first.name);
      setActiveParams(first.params || []);
      setExecutionResult(null);
      return;
    }
    // Tool mode required inputs (flat param list)
    else if (mode === "tool" && Array.isArray(response?.inputs_required) && response.inputs_required.length && !response.success && response.error === "") {
      setActiveParams(response.inputs_required);
      setExecutionResult(null);
      return;
    }
    // If error and no required inputs, clear form and show error only
    else if (!response?.success && response?.error && Array.isArray(response?.inputs_required) && response.inputs_required.length === 0) {
      setActiveParams([]);
      setExecutionResult({ type: "error", data: response.error });
      return;
    }
    // On clicking of Run button it is success
    else if (response?.success && response?.output !== "") {
      setExecutionResult({ type: "success", data: response.output });
      return;
    }
    // On clicking of Run button it is error
    else if (!response?.success && response?.error) {
      setExecutionResult({ type: "error", data: response.error });
    }
    // Dry-run / introspection error
    else {
      setExecutionResult({ type: "error", data: response?.message || "Unknown response" });
    }
  };

  // -------- Run handler --------
  const handleRun = async (e) => {
    if (e) e.preventDefault();
    if (!code?.trim()) {
      addMessage("No code to execute", "error");
      return;
    }
    if (!validateParams()) return;

    onRunStart();
    setRunLoading(true);
    try {
      const isTool = mode === "tool";
      const url = isTool ? APIs.EXECUTE_CODE : APIs.INLINE_MCP_RUN;
      const payload = isTool
        ? { code, inputs: buildArguments(), handle_default: true }
        : { code, tool_name: selectedTool, arguments: buildArguments(), timeout_sec: 5, debug: false, handle_default: true };

      const response = await postData(url, payload);
      processResponse(response);
    } catch (err) {
      setExecutionResult({ type: "error", data: err?.message || "Execution error" });
    } finally {
      setRunLoading(false);
      onRunComplete();
    }
  };

  // -------- Auto execute (dry-run / introspection) --------
  useEffect(() => {
    if (!autoExecute || !code) return;
    const key = `${mode}-${executeTrigger}`;
    if (executedTriggersRef.current.has(key)) return;
    executedTriggersRef.current.add(key);

    (async () => {
      onRunStart();
      setRunLoading(true);
      try {
        const isTool = mode === "tool";
        const url = isTool ? APIs.EXECUTE_CODE : APIs.INLINE_MCP_RUN;
        // handle_default false to elicit required inputs
        const payload = { code, handle_default: false };
        const response = await postData(url, payload);
        processResponse(response);
      } catch (err) {
        addMessage("Error executing code", "error");
      } finally {
        setRunLoading(false);
        // Always signal completion so parent loaders clear
        onRunComplete();
      }
    })();
  }, [autoExecute, executeTrigger, code, mode, postData, addMessage, onRunStart, onRunComplete]);

  // -------- Sync params when server selected tool changes --------
  useEffect(() => {
    if (mode !== "server") return;
    const tool = serverTools.find((t) => t.name === selectedTool);
    if (tool) setActiveParams(tool.params || []);
    else setActiveParams([]);
  }, [selectedTool, mode, serverTools]);

  // -------- Scroll result into view when updated --------
  useEffect(() => {
    if (!executionResult) return;
    const container = containerRef.current;
    const resultEl = executionResultRef.current;
    if (!resultEl) return;

    const doScroll = () => {
      if (container) {
        const cRect = container.getBoundingClientRect();
        const rRect = resultEl.getBoundingClientRect();
        const delta = rRect.top - cRect.top;
        const target = container.scrollTop + delta - 12;
        const outOfView = delta < 0 || delta + rRect.height > cRect.height;
        if (outOfView) container.scrollTo({ top: target, behavior: "smooth" });

        const pageRect = container.getBoundingClientRect();
        const vh = window.innerHeight || document.documentElement.clientHeight;
        if (pageRect.top < 0 || pageRect.bottom > vh) {
          try {
            container.scrollIntoView({ behavior: "smooth", block: "nearest" });
          } catch (_) {}
        }
      } else {
        try {
          resultEl.scrollIntoView({ behavior: "smooth", block: "nearest" });
        } catch (_) {}
      }
    };
    requestAnimationFrame(() => setTimeout(doScroll, 0));
  }, [executionResult]);

  const hasParams = inputsMeta.length > 0;
  // const headerText = mode === "server" ? "Server Parameters" : "Required Inputs";
  const headerText = "Required Inputs";

  return (
    <div ref={containerRef} className={style.executorContainer}>
      {runLoading && (
        <div className={style.loadingOverlay} aria-label="Executing">
          <Loader />
        </div>
      )}
      <div className={style.executorHeaderWrapper}>
        <h3 className={style.executorPanelHeader}>Executor Panel</h3>
        <button
          className={`closeBtn ${style.closeBtnPosition}`}
          onClick={() => {
            setInputsMeta([]);
            setServerTools([]);
            setInputValues({});
            setParamErrors({});
            setExecutionResult(null);
            onClose();
          }}
          type="button"
          title="Close Executorpanel">
          ×
        </button>
      </div>
      <div className={style.sectionWrapper}>
        {mode === "server" && serverTools.length > 0 && (
          <div className={style.formBlock}>
            <NewCommonDropdown
              options={serverTools.map((t) => t.name)}
              selected={selectedTool}
              onSelect={(name) => setSelectedTool(name)}
              placeholder="Search tool..."
              width={240}
              classNameOverride="executorPanelToolsDropdown"
            />
          </div>
        )}

        {hasParams && (
          <form onSubmit={handleRun} className="form">
            <div className={style.executionHeader}>
              <p className={style.headerText}>{headerText}</p>
            </div>
            <div className="formSection">
              <div className="formSection">
                {inputsMeta.map((p) => {
                  const errorId = `${p.name}-error`;
                  const hasError = Boolean(paramErrors[p.name]);
                  const isRequired = isMandatoryParam(p);
                  const placeholder = getPlaceholder(p);

                  const inputId = `param-input-${p.name}`;

                  return (
                    <div key={p.name} className="formGroup">
                      <label htmlFor={inputId} className="label-desc">
                        {/* <span> */}
                        {mode === "server" ? p.name : toTitleCase(p.name)}
                        {isRequired && <span className="required">*</span>}
                        {/* </span> */}
                      </label>
                      <input
                        type="text"
                        id={inputId}
                        name={p.name}
                        value={inputValues[p.name] || ""}
                        onChange={(e) => handleParamChange(p.name, e.target.value)}
                        className={`input ${hasError ? style.inputError : ""}`}
                        aria-label={p.name}
                        placeholder={placeholder}
                        {...(hasError ? { "aria-describedby": errorId } : {})}
                        {...(isRequired ? { "aria-required": "true" } : {})}
                      />
                      {hasError && (
                        <span id={errorId} className={style.subtleErrorMessage} role="alert">
                          {paramErrors[p.name]}
                        </span>
                      )}
                    </div>
                  );
                })}
                <div className={style.runButtonRight}>
                  <IAFButton type="primary" onClick={handleRun} disabled={runLoading} loading={runLoading}>
                    Run
                  </IAFButton>
                </div>
              </div>
            </div>
          </form>
        )}
      </div>

      {executionResult && (
        <div className={style.sectionWrapper}>
          <div className={style.executionHeader}>
            <span className={style.executionTitle}>Output</span>
            <span className={style.checkIcon} aria-label="Success">
              <SVGIcons icon="circle-check-big" width={20} height={20} color="var(--header-color)" />
            </span>
          </div>
          <div ref={executionResultRef} className={style.executionOutputPanel}>
            <div className={style.executionOutputTextBlock}>
              {/* <div className={style.executionStep}>Execution started...</div>
              <div className={style.executionStep}>
                Processing {typeof code === "string" && code.match(/def\s+(\w+)/) ? code.match(/def\s+(\w+)/)[1] : selectedTool || "TOOL"}...
              </div> */}
              <div className={style.executionStep}>Execution completed successfully!</div>
              <div className={style.executionResultText}>Result: {renderValidationContent(executionResult.data)}</div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default ExecutorPanel;
