import { useEffect, useState } from "react";
import toolCallCSS from "./ToolCallFinalResponse.module.css";
import SVGIcons from "../../Icons/SVGIcons";
import { META_AGENT, PLANNER_META_AGENT } from "../../constant";

const ToolCallFinalResponse = (props) => {
  // Local state to track if user clicked "Request Changes" to enable editing mode
  const [isRequestingChanges, setIsRequestingChanges] = useState(false);

  useEffect(() => {
    const jsonString = props?.rawData;

    try {
      const obj = jsonString ? JSON.parse(jsonString) : {};
      // Ensure obj is always an object, not a string
      if (typeof obj === "object" && obj !== null && !Array.isArray(obj)) {
        props.setParsedValues(obj);
      } else {
        props.setParsedValues({});
      }
    } catch (error) {
      console.error("Error parsing JSON:", error);
      props.setParsedValues({});
    }
  }, [props?.rawData]);

  useEffect(() => { }, [props?.messageData]);

  // Reset request changes mode when messageData changes (new tool call)
  useEffect(() => {
    setIsRequestingChanges(false);
  }, [props?.messageData?.toolcallData]);

  // Extract tool call data safely
  const toolCallFunction = props?.messageData?.toolcallData?.additional_details?.[0]?.additional_kwargs?.tool_calls?.[0]?.function;
  const toolName = toolCallFunction?.name || "";

  // Get raw arguments from toolCallFunction.arguments (this is the correct source)
  const toolArgumentsRaw = toolCallFunction?.arguments || "{}";
  const hasToolCallData = Boolean(toolName);

  // Parse tool arguments - handle string, object, or nested string scenarios
  const getToolArguments = () => {
    const args = toolArgumentsRaw;

    // If empty string or "{}", return empty object
    if (!args || args === "" || args === "{}") {
      return {};
    }

    // If it's already an object, return it
    if (typeof args === "object" && args !== null && !Array.isArray(args)) {
      return args;
    }

    // If it's a string, try to parse it
    if (typeof args === "string") {
      try {
        const parsed = JSON.parse(args);
        // If parsed is an object, return it
        if (typeof parsed === "object" && parsed !== null && !Array.isArray(parsed)) {
          return parsed;
        }
        // If parsed result is still a string, try parsing again (double-stringified)
        if (typeof parsed === "string") {
          try {
            const doubleParsed = JSON.parse(parsed);
            if (typeof doubleParsed === "object" && doubleParsed !== null) {
              return doubleParsed;
            }
          } catch {
            // ignore
          }
        }
      } catch (e) {
        console.error("Failed to parse toolArguments:", e, args);
        return {};
      }
    }

    return {};
  };

  const toolArguments = getToolArguments();

  const isAgentCall = props.agentType === PLANNER_META_AGENT || props.agentType === META_AGENT;
  const entityLabel = isAgentCall ? "Agent" : "Tool";
  const headerTitle = isAgentCall ? "Agent Call Request – Awaiting Approval" : "Tool Call Request – Awaiting Approval";

  // Handle Request Changes click - enable editing mode
  const handleRequestChanges = () => {
    // Initialize parsedValues with current tool arguments so all fields are available for editing
    props.setParsedValues({ ...toolArguments });
    setIsRequestingChanges(true);
  };

  // Handle Cancel - exit editing mode without submitting
  const handleCancelChanges = () => {
    setIsRequestingChanges(false);
    // Reset parsed values to original arguments
    try {
      const obj = props?.rawData ? JSON.parse(props.rawData) : {};
      props.setParsedValues(obj);
    } catch {
      props.setParsedValues({});
    }
  };

  // Handle Submit Changes - send edited arguments
  const handleSubmitChanges = () => {
    setIsRequestingChanges(false);
    props?.sendArgumentEditData?.(props?.messageData);
  };

  return (
    <>
      <div className={toolCallCSS.toolCallWrapper}>
        {/* Only render Tool Call Box if we have tool call data */}
        {hasToolCallData && (
          <div className={toolCallCSS.toolcallBox}>
            {/* Header */}
            <div className={toolCallCSS.toolcallHeader}>
              <SVGIcons icon="activity-pulse" width={19} height={19} stroke="#0073CF" />
              <span className={toolCallCSS.toolcallHeaderTitle}>{headerTitle}</span>
            </div>

            {/* Tool Calls Content */}
            <div className={toolCallCSS.toolcallContent}>
              {/* Tool Name Row */}
              <div className={toolCallCSS.toolcallRow}>
                <span className={toolCallCSS.toolcallLabel}>
                  {props?.agentType === META_AGENT || props?.agentType === PLANNER_META_AGENT ? "Agent Name:" : "Tool Name:"}
                </span>
                <span className={toolCallCSS.toolcallValue}>{toolName}</span>
              </div>

              <div className={toolCallCSS.toolcallRow}>
                <span className={toolCallCSS.toolcallLabel}>Arguments:</span>
              </div>

              {/* Arguments List */}
              {(() => {
                // Always prefer parsedValues if they exist (contains user edits after submission)
                // Fall back to toolArguments only if parsedValues is empty
                // Ensure displayValues is always a plain object
                let displayValues = toolArguments;
                if (props?.parsedValues && typeof props.parsedValues === "object" && !Array.isArray(props.parsedValues) && Object.keys(props.parsedValues).length > 0) {
                  displayValues = props.parsedValues;
                }
                const argEntries = Object.entries(displayValues);

                if (argEntries.length === 0) {
                  return <span className={toolCallCSS.toolcallNoargs}>No arguments to show</span>;
                }

                return (
                  <div className={toolCallCSS.toolcallArgsList}>
                    {argEntries.map(([key, currentVal]) => {
                      // Display the current value directly - parsedValues when editing, toolArguments otherwise
                      const value = typeof currentVal === "object" ? JSON.stringify(currentVal, null, 2) : String(currentVal ?? "");
                      return (
                        <div className={toolCallCSS.toolcallArgItem} key={key}>
                          <span className={toolCallCSS.toolcallArgKey}>{key}:</span>
                          <textarea
                            className={toolCallCSS.toolcallArgInput}
                            value={value}
                            disabled={!isRequestingChanges}
                            rows={2}
                            onChange={isRequestingChanges ? (e) => props.handleEditChange(key, e.target.value, currentVal) : undefined}
                          />
                        </div>
                      );
                    })}
                  </div>
                );
              })()}
            </div>

            {/* Action buttons - only show when execution access is allowed */}
            {props?.canExecute !== false && props?.isEditable && (!props?.generating || !props?.fetching) && props?.sendIconShow && (
              <div className={toolCallCSS.toolcallActions}>
                {!isRequestingChanges ? (
                  // Initial state: Show Approve and Request Changes buttons
                  <>
                    <button className={toolCallCSS.toolcallUpdateBtn} onClick={() => props?.submitFeedbackYes?.(props?.messageData)} title="Approve">
                      <SVGIcons icon="thumbs-up" width={15} height={15} stroke="white" />
                      <span className={toolCallCSS.toolcallBtnLabel}>Approve</span>
                    </button>
                    <button className={toolCallCSS.toolcallCancelBtn} onClick={handleRequestChanges} title="Request Changes">
                      <SVGIcons icon="thumbs-down" width={15} height={15} stroke="#1A1A1A" />
                      <span className={toolCallCSS.toolcallBtnLabel}>Request Changes</span>
                    </button>
                  </>
                ) : (
                  // Editing state: Show Submit and Cancel buttons
                  <>
                    <button className={toolCallCSS.toolcallUpdateBtn} onClick={handleSubmitChanges} title="Submit Changes">
                      <SVGIcons icon="send" width={16} height={16} />
                      <span className={toolCallCSS.toolcallBtnLabel}>Submit Changes</span>
                    </button>
                    <button className={toolCallCSS.toolcallCancelBtn} onClick={handleCancelChanges} title="Cancel">
                      <SVGIcons icon="close" width={16} height={16} />
                      <span className={toolCallCSS.toolcallBtnLabel}>Cancel</span>
                    </button>
                  </>
                )}
              </div>
            )}
          </div>
        )}
      </div>
    </>
  );
};

export default ToolCallFinalResponse;
