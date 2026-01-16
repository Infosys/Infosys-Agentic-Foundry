import { useEffect } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import toolCallCSS from "./ToolCallFinalResponse.module.css";

const ToolCallFinalResponse = (props) => {
  // Handler to reset values and exit edit mode
  const handleCancelEdit = () => {
    // Reset argument values to default from messageData
    try {
      const argObj = props?.messageData?.toolcallData?.additional_details?.[0]?.additional_kwargs?.tool_calls?.[0]?.function?.arguments;
      const parsed = JSON.parse(argObj || "{}");
      props.setParsedValues(parsed);
    } catch {
      props.setParsedValues({});
    }

    // Need to return back to default state of the tool interrupt
    props.setLikeIcon(false);
    props.setIsEditable(false);

    // If parent controls isEditable, call callback if provided
    if (props.onCancelEdit) props.onCancelEdit();
  };

  useEffect(() => {
    const jsonString = props?.rawData;

    try {
      
      const obj = jsonString? JSON.parse(jsonString) : "{}";
      props.setParsedValues(obj);
    } catch (error) {
      console.error("Error parsing JSON:", error);
    }
  }, [props?.rawData]);

  useEffect(() => {}, [props?.messageData]);

  // Extract tool call data safely
  const toolCallFunction = props?.messageData?.toolcallData?.additional_details?.[0]?.additional_kwargs?.tool_calls?.[0]?.function;
  const toolName = toolCallFunction?.name || "";
  const toolArguments = toolCallFunction?.arguments || "{}";
  const hasToolCallData = Boolean(toolName);

  return (
    <>
      <div className={toolCallCSS.toolCallWrapper}>
        {/* Only render Tool Call Box if we have tool call data */}
        {hasToolCallData && (
          <div className={toolCallCSS.toolcallBox}>
            <div className={toolCallCSS.toolcallHeader}>
              <span className={toolCallCSS.toolcallHeaderTitle}>Tool Calls</span>
            </div>
            <div className={toolCallCSS.toolcallContent}>
              <div className={toolCallCSS.toolcallRow}>
                <span className={toolCallCSS.toolcallLabel}>Tool Name:</span>
                <span className={toolCallCSS.toolcallValue}>
                  <ReactMarkdown rehypePlugins={[remarkGfm]}>
                    {toolName}
                  </ReactMarkdown>
                </span>
              </div>
              <div className={toolCallCSS.toolcallRow + " " + toolCallCSS.toolcallArguments}>
                <span className={toolCallCSS.toolcallLabel}>Arguments:</span>
                <span className={toolCallCSS.toolcallValue}>
                  {(() => {
                    const argsEmpty = toolArguments === "{}";
                    if (argsEmpty) {
                      return <span className={toolCallCSS.toolcallNoArgs}>No arguments to show</span>;
                    }
                    // Always render inputs, control editability with readOnly
                    let argEntries = [];
                    if (props.isEditable) {
                      argEntries = Object.entries(props?.parsedValues || {});
                    } else {
                      try {
                        argEntries = Object.entries(JSON.parse(toolArguments || "{}"));
                      } catch {
                        argEntries = [];
                      }
                    }
                    return (
                      <div className={toolCallCSS.toolcallArgsList}>
                        {argEntries.map(([key, val]) => {
                          const value = typeof val === "object" ? JSON.stringify(val) : val;
                          const isLong = typeof val === "object" || (typeof val === "string" && val.length > 10);
                          return (
                            <div className={toolCallCSS.toolcallArgItem} key={key}>
                              <span className={toolCallCSS.toolcallArgKey}>{key}:</span>
                              {isLong ? (
                                <textarea
                                  className={toolCallCSS.toolcallArgInput}
                                  value={value}
                                  disabled={!props.isEditable}
                                  row={4}
                                  onChange={props.isEditable ? (e) => props.handleEditChange(key, e.target.value, val) : undefined}
                                />
                              ) : (
                                <input
                                  className={toolCallCSS.toolcallArgInput}
                                  type="text"
                                  value={value}
                                  disabled={!props.isEditable}
                                  onChange={props.isEditable ? (e) => props.handleEditChange(key, e.target.value, val) : undefined}
                                  autoFocus={props.isEditable}
                                />
                              )}
                            </div>
                          );
                        })}
                      </div>
                    );
                  })()}
                </span>
              </div>
              {props?.isEditable && (!props?.generating || !props?.fetching) && props?.sendIconShow && (
                <div className={toolCallCSS.toolcallActions}>
                  <button className={toolCallCSS.toolcallUpdateBtn} onClick={() => props?.sendArgumentEditData(props?.messageData)} title="Update">
                    Update
                  </button>
                  <button
                    className={toolCallCSS.toolcallCancelBtn}
                    onClick={handleCancelEdit}
                    title="Cancel"
                    style={{
                      marginLeft: 8,
                      background: "#f3f4f6",
                      color: "#374151",
                      border: "1px solid #e5e7eb",
                    }}>
                    Cancel
                  </button>
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </>
  );
};

export default ToolCallFinalResponse;
