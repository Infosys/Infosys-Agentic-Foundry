/**
 * Normalize tool-call details from executor messages.
 * Async inference responses may return additional_details as string reprs
 * instead of structured objects — fall back to tools_used or interrupt_metadata.
 */

export const hasStructuredToolCallDetails = (additionalDetails) =>
  Array.isArray(additionalDetails) &&
  additionalDetails.length > 0 &&
  typeof additionalDetails[0] === "object" &&
  additionalDetails[0] !== null &&
  additionalDetails[0].additional_kwargs &&
  Object.keys(additionalDetails[0].additional_kwargs).length > 0 &&
  Array.isArray(additionalDetails[0].additional_kwargs.tool_calls) &&
  additionalDetails[0].additional_kwargs.tool_calls.length > 0;

export const synthesizeAdditionalDetailsFromToolsUsed = (toolsUsed) => {
  if (!toolsUsed || typeof toolsUsed !== "object") return null;

  try {
    const toolCalls = Object.entries(toolsUsed).map(([callId, tu]) => {
      const argsObj = tu?.arguments ?? tu?.args ?? {};
      const serializedArgs = typeof argsObj === "string" ? argsObj : JSON.stringify(argsObj || {});
      return {
        id: callId,
        type: tu?.type || "function",
        function: {
          name: tu?.name || tu?.tool_name || callId,
          arguments: serializedArgs,
        },
        output: tu?.output ?? tu?.tool_output ?? null,
      };
    });

    if (toolCalls.length === 0) return null;
    return [{ additional_kwargs: { tool_calls: toolCalls } }];
  } catch {
    return null;
  }
};

export const synthesizeAdditionalDetailsFromInterruptMetadata = (interruptMetadata) => {
  if (!interruptMetadata || interruptMetadata.interrupt_type !== "tool_interrupt") return null;

  const toolName = interruptMetadata.tool_name;
  if (!toolName) return null;

  const callId = interruptMetadata.tool_call_id || "interrupt_tool_call";
  const args = interruptMetadata.tool_args ?? {};

  return [
    {
      additional_kwargs: {
        tool_calls: [
          {
            id: callId,
            type: "function",
            function: {
              name: toolName,
              arguments: typeof args === "string" ? args : JSON.stringify(args || {}),
            },
          },
        ],
      },
    },
  ];
};

export const resolveToolCallAdditionalDetails = (executorItem, chatHistory = {}) => {
  if (hasStructuredToolCallDetails(executorItem?.additional_details)) {
    return executorItem.additional_details;
  }

  const fromToolsUsed = synthesizeAdditionalDetailsFromToolsUsed(executorItem?.tools_used);
  if (fromToolsUsed) return fromToolsUsed;

  return synthesizeAdditionalDetailsFromInterruptMetadata(chatHistory?.interrupt_metadata);
};

export const hasToolCallDetailsInMessage = (message) => {
  if (hasStructuredToolCallDetails(message?.toolcallData?.additional_details)) return true;
  if (synthesizeAdditionalDetailsFromToolsUsed(message?.toolcallData?.tools_used)) return true;
  return Boolean(synthesizeAdditionalDetailsFromInterruptMetadata(message?.interrupt_metadata));
};
