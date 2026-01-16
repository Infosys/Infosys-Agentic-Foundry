import React, { useState, useCallback, useEffect, useRef } from "react";
import SVGIcons from "../../Icons/SVGIcons";
import style from "../../css_modules/ToolOnboarding.module.css";
import { useMessage } from "../../Hooks/MessageContext";
import useFetch from "../../Hooks/useAxios.js";
import NewCommonDropdown from "./NewCommonDropdown";
import { APIs } from "../../constant";
import Loader from "./Loader.jsx";

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

const ExecutorPanel = ({
  code = "",
  mode = "tool",
  autoExecute = false,
  executeTrigger = 0,
  onClose = () => {},
  onRunStart = () => {},
  onRunComplete = () => {},
  style: panelStyle,
}) => {
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
  const [validationResult, setValidationResult] = useState(null);
  const validationResultRef = useRef(null);
  const containerRef = useRef(null);
  const executedTriggersRef = useRef(new Set());

  // -------- Rendering helpers --------
  const renderValidationContent = useCallback((data) => {
    if (data === null || data === undefined) return null;
    if (typeof data === "string" || typeof data === "number") return <pre className={style.success_error_content}>{String(data)}</pre>;
    if (Array.isArray(data))
      return (
        <ul className={`${style.success_error_list} ${style.success_error_content}`}>
          {data.map((item, i) => (
            <li key={i}>{typeof item === "object" ? <pre style={{ margin: 0 }}>{JSON.stringify(item, null, JSON_INDENT)}</pre> : String(item)}</li>
          ))}
        </ul>
      );
    if (typeof data === "object") return <pre className={style.success_error_content}>{JSON.stringify(data, null, JSON_INDENT)}</pre>;
    if (typeof data === "boolean") return <pre className={style.success_error_content}>{toTitleCase(data.toString())}</pre>;
    return null;
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
      setValidationResult(null);
      return;
    }
    // Tool mode required inputs (flat param list)
    else if (mode === "tool" && Array.isArray(response?.inputs_required) && response.inputs_required.length && !response.success && response.error === "") {
      setActiveParams(response.inputs_required);
      setValidationResult(null);
      return;
    }
    // If error and no required inputs, clear form and show error only
    else if (!response?.success && response?.error && Array.isArray(response?.inputs_required) && response.inputs_required.length === 0) {
      setActiveParams([]);
      setValidationResult({ type: "error", data: response.error });
      return;
    }
    // On clicking of Run button it is success
    else if (response?.success && response?.output !== "") {
      setValidationResult({ type: "success", data: response.output });
      return;
    }
    // On clicking of Run button it is error
    else if (!response?.success && response?.error) {
      setValidationResult({ type: "error", data: response.error });
    }
    // Dry-run / introspection error
    else {
      setValidationResult({ type: "error", data: response?.message || "Unknown response" });
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
      setValidationResult({ type: "error", data: err?.message || "Execution error" });
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
    if (!validationResult) return;
    const container = containerRef.current;
    const resultEl = validationResultRef.current;
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
  }, [validationResult]);

  const hasParams = inputsMeta.length > 0;
  // const headerText = mode === "server" ? "Server Parameters" : "Required Inputs";
  const headerText = "Required Inputs";

  return (
    <div ref={containerRef} className={style.executorContainer} style={{ overflowY: "auto", maxHeight: "80vh", ...panelStyle }}>
      {runLoading && (
        <div
          style={{
            position: "absolute",
            inset: 0,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            background: "rgba(255,255,255,0.55)",
            zIndex: 1200,
          }}
          aria-label="Executing">
          <Loader />
        </div>
      )}

      <span
        onClick={() => {
          setInputsMeta([]);
          setServerTools([]);
          setInputValues({});
          setParamErrors({});
          setValidationResult(null);
          onClose();
        }}
        title="Close executor"
        className={style.closeButton}>
        <SVGIcons icon="close-icon" color="#dc3545" width={18} height={18} />
      </span>

      {mode === "server" && serverTools.length > 0 && (
        <div className={style.formBlock} style={{ position: "relative", top: "20px", left: "20px" }}>
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
        <form onSubmit={handleRun} className={style.validationPanel}>
          <div className={style.validatorHeader}>
            <p className={style.headerText}>{headerText}</p>
          </div>
          <div className={style.ValidationInputWrapper}>
            {inputsMeta.map((p) => {
              const errorId = `${p.name}-error`;
              const hasError = !!paramErrors[p.name];
              const isRequired = isMandatoryParam(p);
              const placeholder = getPlaceholder(p);

              return (
                <label key={p.name} className={style.inputFieldLabel}>
                  <span>
                    {mode === "server" ? p.name : toTitleCase(p.name)}
                    {isRequired && <span style={{ color: "#dc3545" }}>*</span>}:
                  </span>
                  <input
                    type="text"
                    name={p.name}
                    value={inputValues[p.name] || ""}
                    onChange={(e) => handleParamChange(p.name, e.target.value)}
                    className={`${style.validationInput} ${hasError ? style.inputError : ""}`}
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
                </label>
              );
            })}
            <div className={style.ValidationButtonWrapper}>
              <button type="submit" className={style.addButton} disabled={runLoading}>
                {runLoading ? "Running..." : "Run"}
              </button>
            </div>
          </div>
        </form>
      )}

      {validationResult && (
        <div ref={validationResultRef} className={`${style.success_error_section} ${style[validationResult.type]}`}>
          <div className={`${style.success_error_header} ${style[validationResult.type]}`}>{validationResult.type === "success" ? "Success" : "Error"}</div>
          {validationResult.type === "success" && <p className={style.outputLabel}>Output is:</p>}
          <div className={`${style.success_error_content} ${style[validationResult.type]}`}>{renderValidationContent(validationResult.data)}</div>
        </div>
      )}
    </div>
  );
};

export default ExecutorPanel;
