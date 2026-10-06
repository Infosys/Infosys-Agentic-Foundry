const STRUCTURED_PARSE_FALLBACK_PREFIX =
  /^I couldn't format the response correctly, but here is the raw answer:\s*/i;

/**
 * Strips the backend fallback wrapper emitted when structured LLM parsing fails.
 * @param {string} content
 * @returns {string}
 */
export const unwrapStructuredParseFallback = (content) => {
  if (typeof content !== "string" || !content.trim()) return content || "";
  return content.replace(STRUCTURED_PARSE_FALLBACK_PREFIX, "").trim();
};

/**
 * Returns true when parts carry metadata indicating structured parse failure.
 * @param {Array} parts
 * @returns {boolean}
 */
export const hasStructuredParseError = (parts) => {
  if (!Array.isArray(parts)) return false;
  return parts.some((part) =>
    /Failed to parse structured response/i.test(String(part?.metadata?.error || "")),
  );
};

/**
 * Sanitize parts array by unwrapping fallback text content.
 * @param {Array} parts
 * @returns {Array}
 */
export const sanitizeResponseParts = (parts) => {
  if (!Array.isArray(parts)) return [];
  return parts.map((part) => {
    if (part?.type === "text" && typeof part?.data?.content === "string") {
      return {
        ...part,
        data: {
          ...part.data,
          content: unwrapStructuredParseFallback(part.data.content),
        },
      };
    }
    if (typeof part?.text === "string") {
      return { ...part, text: unwrapStructuredParseFallback(part.text) };
    }
    if (typeof part?.content === "string") {
      return { ...part, content: unwrapStructuredParseFallback(part.content) };
    }
    return part;
  });
};

/**
 * Resolve the best bot message text from an executor_message, preferring canonical
 * fields over parts and stripping structured-parse fallback wrappers.
 * @param {object} item
 * @param {object} [chatHistory]
 * @returns {string}
 */
export const resolveBotMessageText = (item, chatHistory = null) => {
  const canonical =
    safeStringifyMessage(item?.final_response) ||
    safeStringifyMessage(item?.response) ||
    safeStringifyMessage(item?.message) ||
    safeStringifyMessage(item?.content) ||
    safeStringifyMessage(chatHistory?.response) ||
    "";

  if (canonical.trim()) {
    return unwrapStructuredParseFallback(canonical);
  }

  const rawParts = item?.parts?.length ? item.parts : chatHistory?.parts;
  if (Array.isArray(rawParts) && rawParts.length > 0) {
    const partsText = rawParts
      .map(
        (p) =>
          safeStringifyMessage(p?.data?.content) ||
          safeStringifyMessage(p?.text) ||
          safeStringifyMessage(p?.content),
      )
      .filter(Boolean)
      .join("\n\n");
    if (partsText.trim()) {
      return unwrapStructuredParseFallback(partsText);
    }
  }

  return "";
};

/**
 * Resolve parts for display, falling back to chat-level parts on the last message.
 * @param {object} item
 * @param {object} chatHistory
 * @param {boolean} isLastMessage
 * @returns {Array}
 */
export const resolveResponseParts = (item, chatHistory, isLastMessage = false) => {
  const sourceParts =
    (Array.isArray(item?.parts) && item.parts.length > 0
      ? item.parts
      : isLastMessage && Array.isArray(chatHistory?.parts)
        ? chatHistory.parts
        : []) || [];
  return sanitizeResponseParts(sourceParts);
};

/**
 * Human-readable label from snake_case / camelCase keys.
 * @param {string} key
 * @returns {string}
 */
const toDisplayLabel = (key) =>
  String(key)
    .replace(/_/g, " ")
    .replace(/([a-z])([A-Z])/g, "$1 $2")
    .replace(/\b\w/g, (c) => c.toUpperCase());

/**
 * Recursively format any structured value for display.
 * Role-agnostic — handles lists, dicts, and nested payloads from any execution step.
 * @param {*} value
 * @param {number} [depth]
 * @returns {string}
 */
const formatStructuredValue = (value, depth = 0) => {
  if (value === null || value === undefined) return "";
  if (typeof value === "string") return value.trim();
  if (typeof value === "number" || typeof value === "boolean") return String(value);

  if (Array.isArray(value)) {
    if (value.length === 0) return "";

    if (value.every((item) => typeof item === "string")) {
      const items = value.map((s) => s.trim()).filter(Boolean);
      if (depth === 0) return items.join("\n\n");
      return items.map((s) => `- ${s}`).join("\n");
    }

    if (value.every((item) => item === null || typeof item !== "object")) {
      return value
        .filter((item) => item !== null && item !== undefined)
        .map((item) => `- ${formatStructuredValue(item, depth + 1)}`)
        .join("\n");
    }

    return value
      .map((item) => formatStructuredValue(item, depth + 1))
      .filter(Boolean)
      .join("\n\n");
  }

  if (typeof value === "object") {
    const entries = Object.entries(value).filter(
      ([, v]) => v !== null && v !== undefined && v !== "",
    );
    if (entries.length === 0) return "";

    return entries
      .map(([key, val]) => {
        const label = toDisplayLabel(key);
        const formatted = formatStructuredValue(val, depth + 1);
        if (!formatted) return "";

        const isNested =
          Array.isArray(val) || (typeof val === "object" && val !== null && formatted.includes("\n"));

        return isNested ? `**${label}:**\n${formatted}` : `**${label}:** ${formatted}`;
      })
      .filter(Boolean)
      .join("\n\n");
  }

  return String(value).trim();
};

/**
 * Safely converts a bot-message value to a plain string.
 *
 * Handles all shapes returned across agent types:
 *  - string  → trimmed as-is
 *  - { response: "..." }  → unwrap (hybrid agent)
 *  - { message: "..." }   → unwrap
 *  - { answer:  "..." }   → unwrap
 *  - { content: "..." }   → unwrap
 *  - array / object → formatStructuredValue (role-agnostic)
 *  - null/undefined → ""
 *
 * @param {*} value
 * @returns {string}
 */
export const safeStringifyMessage = (value) => {
  if (value === null || value === undefined) {
    return "";
  }
  if (typeof value === "string") {
    return formatStringContent(value);
  }
  if (typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  if (Array.isArray(value)) {
    return formatStructuredValue(value);
  }
  if (typeof value === "object") {
    // Unwrap common single-key wrapper objects returned by various agent backends.
    if (typeof value.response === "string" && value.response.trim()) {
      return formatStringContent(value.response);
    }
    if (typeof value.message === "string" && value.message.trim()) {
      return formatStringContent(value.message);
    }
    if (typeof value.answer === "string" && value.answer.trim()) {
      return formatStringContent(value.answer);
    }
    if (typeof value.content === "string" && value.content.trim()) {
      return formatStringContent(value.content);
    }
    return formatStructuredValue(value);
  }
  return String(value).trim();
};


/**
 * Extract a balanced [...] or {...} literal from a Python repr string.
 * @param {string} str
 * @param {number} startIndex
 * @returns {string|null}
 */
const extractBalancedLiteral = (str, startIndex) => {
  const open = str[startIndex];
  if (open !== "[" && open !== "{") return null;
  const close = open === "[" ? "]" : "}";

  let depth = 0;
  let inString = false;
  let stringQuote = null;

  for (let i = startIndex; i < str.length; i += 1) {
    const ch = str[i];
    if (inString) {
      if (ch === "\\" && i + 1 < str.length) {
        i += 1;
        continue;
      }
      if (ch === stringQuote) inString = false;
      continue;
    }
    if (ch === "'" || ch === '"') {
      inString = true;
      stringQuote = ch;
      continue;
    }
    if (ch === open) depth += 1;
    else if (ch === close) {
      depth -= 1;
      if (depth === 0) return str.slice(startIndex, i + 1);
    }
  }

  return null;
};

/**
 * Decode a Python/JSON-style escape sequence inside a repr quoted string.
 * @param {string} str
 * @param {number} index - index of the backslash
 * @returns {{ value: string, advance: number }}
 */
const decodeReprEscape = (str, index) => {
  const escapeChar = str[index + 1];
  switch (escapeChar) {
    case "n":
      return { value: "\n", advance: 2 };
    case "t":
      return { value: "\t", advance: 2 };
    case "r":
      return { value: "\r", advance: 2 };
    case "\\":
      return { value: "\\", advance: 2 };
    case "'":
      return { value: "'", advance: 2 };
    case '"':
      return { value: '"', advance: 2 };
    default:
      return { value: escapeChar ?? "", advance: escapeChar ? 2 : 1 };
  }
};

/**
 * Extract a single- or double-quoted repr field value from a Python __repr__ string.
 * Also supports bracket/brace literals (lists/dicts) for any structured payload.
 * @param {string} str
 * @param {string} fieldName
 * @returns {string|null}
 */
const extractReprField = (str, fieldName) => {
  const marker = `${fieldName}=`;
  const idx = str.indexOf(marker);
  if (idx === -1) return null;

  let i = idx + marker.length;
  if (i >= str.length) return null;

  const quote = str[i];
  if (quote === "'" || quote === '"') {
    i += 1;
    let result = "";
    while (i < str.length) {
      const ch = str[i];
      if (ch === "\\" && i + 1 < str.length) {
        const decoded = decodeReprEscape(str, i);
        result += decoded.value;
        i += decoded.advance;
        continue;
      }
      if (ch === quote) break;
      result += ch;
      i += 1;
    }
    return formatStringContent(result);
  }

  if (quote === "[" || quote === "{") {
    const literal = extractBalancedLiteral(str, i);
    if (!literal) return null;
    const parsed = pythonLiteralToJson(literal);
    if (parsed != null) {
      return formatStructuredValue(parsed);
    }
    return literal;
  }

  return null;
};

/**
 * Convert a Python literal string to JSON text, preserving double-quoted
 * string values that contain apostrophes (common in validator feedback).
 * @param {string} input
 * @returns {string}
 */
const convertPythonLiteralToJson = (input) => {
  let out = "";
  let i = 0;

  const appendEscape = (str, index) => {
    const next = str[index + 1];
    switch (next) {
      case "n":
        return { value: "\\n", advance: 2 };
      case "t":
        return { value: "\\t", advance: 2 };
      case "r":
        return { value: "\\r", advance: 2 };
      case "\\":
        return { value: "\\\\", advance: 2 };
      case "'":
        return { value: "'", advance: 2 };
      case '"':
        return { value: '\\"', advance: 2 };
      default:
        return { value: next ?? "", advance: next ? 2 : 1 };
    }
  };

  while (i < input.length) {
    const ch = input[i];

    if (ch === "'") {
      out += '"';
      i += 1;
      while (i < input.length) {
        const c = input[i];
        if (c === "\\" && i + 1 < input.length) {
          const decoded = appendEscape(input, i);
          out += decoded.value;
          i += decoded.advance;
          continue;
        }
        if (c === "'") {
          out += '"';
          i += 1;
          break;
        }
        if (c === '"') {
          out += '\\"';
          i += 1;
          continue;
        }
        if (c === "\n") {
          out += "\\n";
          i += 1;
          continue;
        }
        out += c;
        i += 1;
      }
      continue;
    }

    if (ch === '"') {
      out += '"';
      i += 1;
      while (i < input.length) {
        const c = input[i];
        if (c === "\\" && i + 1 < input.length) {
          const decoded = appendEscape(input, i);
          out += decoded.value;
          i += decoded.advance;
          continue;
        }
        if (c === '"') {
          out += '"';
          i += 1;
          break;
        }
        out += c;
        i += 1;
      }
      continue;
    }

    if (input.slice(i, i + 4) === "None" && !/\w/.test(input[i + 4] || "")) {
      out += "null";
      i += 4;
      continue;
    }
    if (input.slice(i, i + 4) === "True" && !/\w/.test(input[i + 4] || "")) {
      out += "true";
      i += 4;
      continue;
    }
    if (input.slice(i, i + 5) === "False" && !/\w/.test(input[i + 5] || "")) {
      out += "false";
      i += 5;
      continue;
    }

    out += ch;
    i += 1;
  }

  return out;
};

/**
 * Convert a Python literal fragment (dict/list with single quotes) to a JS value.
 * @param {string} literal
 * @returns {*|null}
 */
const pythonLiteralToJson = (literal) => {
  try {
    return JSON.parse(convertPythonLiteralToJson(literal));
  } catch {
    return null;
  }
};

/**
 * Parse a string that is entirely a JSON or Python dict/list literal.
 * @param {string} str
 * @returns {*|null}
 */
const tryParseStructuredLiteral = (str) => {
  const trimmed = str.trim();
  if (!trimmed || (trimmed[0] !== "{" && trimmed[0] !== "[")) return null;

  try {
    return JSON.parse(trimmed);
  } catch {
    return pythonLiteralToJson(trimmed);
  }
};

/**
 * Format string content for display — converts raw JSON/Python literals and
 * embedded {...} / [...] blocks into readable markdown while preserving prose.
 * @param {string} content
 * @returns {string}
 */
const formatStringContent = (content) => {
  if (typeof content !== "string") return "";
  const trimmed = content.trim();
  if (!trimmed) return "";

  const whole = tryParseStructuredLiteral(trimmed);
  if (whole != null) {
    return formatStructuredValue(whole);
  }

  const parts = [];
  let textBuffer = "";
  let i = 0;

  while (i < trimmed.length) {
    const ch = trimmed[i];
    if (ch === "{" || ch === "[") {
      const literal = extractBalancedLiteral(trimmed, i);
      if (literal) {
        const parsed = tryParseStructuredLiteral(literal);
        if (parsed != null) {
          if (textBuffer.trim()) {
            parts.push(textBuffer.trim());
            textBuffer = "";
          }
          parts.push(formatStructuredValue(parsed));
          i += literal.length;
          continue;
        }
      }
    }
    textBuffer += ch;
    i += 1;
  }

  if (textBuffer.trim()) {
    parts.push(textBuffer.trim());
  }

  if (parts.length > 1) {
    return parts.join("\n\n");
  }

  return parts[0] ?? trimmed;
};

/**
 * Extract tool_calls=[...] from a Python __repr__ string.
 * @param {string} str
 * @returns {Array|null}
 */
const extractToolCallsFromRepr = (str) => {
  const marker = "tool_calls=[";
  const idx = str.indexOf(marker);
  if (idx === -1) return null;

  const start = idx + "tool_calls=".length;
  let depth = 0;
  for (let i = start; i < str.length; i += 1) {
    if (str[i] === "[") depth += 1;
    else if (str[i] === "]") {
      depth -= 1;
      if (depth === 0) {
        const arrayStr = str.slice(start, i + 1);
        const parsed = pythonLiteralToJson(arrayStr);
        if (!Array.isArray(parsed) || parsed.length === 0) return null;
        return parsed
          .map((tc) => ({
            id: tc.id,
            name: tc.name,
            args: tc.args ?? tc.arguments ?? {},
          }))
          .filter((tc) => tc.id && tc.name);
      }
    }
  }
  return null;
};

/**
 * Parse tool call arguments that may be JSON string or object.
 * @param {*} args
 * @returns {object}
 */
const parseToolArgs = (args) => {
  if (args && typeof args === "object") return args;
  if (typeof args === "string") {
    try {
      return JSON.parse(args);
    } catch {
      return {};
    }
  }
  return {};
};

/**
 * Normalize a tool call entry from sync or async backend shapes.
 * @param {object} tc
 * @returns {object|null}
 */
const normalizeToolCallEntry = (tc) => {
  if (!tc) return null;
  const name = tc.name || tc.function?.name || tc.tool_name || "";
  const id = tc.id || tc.tool_call_id || "";
  if (!name || !id) return null;
  return {
    id,
    name,
    args: parseToolArgs(tc.args ?? tc.arguments ?? tc.function?.arguments),
  };
};

/**
 * Parse one additional_details entry — structured object (sync) or Python repr string (async).
 * @param {string|object} detail
 * @returns {object|null}
 */
const parseDetailRepr = (detail) => {
  if (!detail) return null;

  if (typeof detail === "object" && !Array.isArray(detail)) {
    if (detail.role) {
      return {
        ...detail,
        content: safeStringifyMessage(detail.content),
      };
    }
    if (Array.isArray(detail.tool_calls) && detail.tool_calls.length > 0) {
      return detail;
    }
    if (detail.type === "tool" || (detail.tool_call_id && detail.name)) {
      return {
        type: "tool",
        tool_call_id: detail.tool_call_id,
        content: safeStringifyMessage(detail.content),
        name: detail.name,
      };
    }
    if (Array.isArray(detail.tool_calls) && detail.tool_calls.length > 0) {
      const toolCalls = detail.tool_calls.map(normalizeToolCallEntry).filter(Boolean);
      return toolCalls.length > 0 ? { tool_calls: toolCalls } : null;
    }
    if (detail.additional_kwargs?.tool_calls?.length) {
      const toolCalls = detail.additional_kwargs.tool_calls
        .map(normalizeToolCallEntry)
        .filter(Boolean);
      return toolCalls.length > 0 ? { tool_calls: toolCalls } : null;
    }
    if (detail.role || detail.content !== undefined) {
      return {
        ...(detail.role ? { role: detail.role } : {}),
        content: safeStringifyMessage(detail.content),
        ...(detail.type ? { type: detail.type } : {}),
        ...(detail.tool_call_id ? { tool_call_id: detail.tool_call_id } : {}),
        ...(detail.name ? { name: detail.name } : {}),
      };
    }
    return detail;
  }

  if (typeof detail !== "string") return null;

  const trimmed = detail.trim();
  if (!trimmed.includes("content=") && !trimmed.includes("tool_calls=") && !trimmed.includes("tool_call_id=")) {
    return null;
  }

  const content = extractReprField(trimmed, "content") ?? "";
  const role = extractReprField(trimmed, "role");
  const name = extractReprField(trimmed, "name");
  const toolCallId = extractReprField(trimmed, "tool_call_id");
  const toolCalls = extractToolCallsFromRepr(trimmed);

  if (name && toolCallId) {
    return { type: "tool", tool_call_id: toolCallId, content, name };
  }

  if (toolCalls && toolCalls.length > 0) {
    return { tool_calls: toolCalls };
  }

  if (role) {
    return { role, content: formatStringContent(content) };
  }

  if (content.trim()) {
    if (trimmed.includes("tool_calls=[]") || trimmed.includes("invalid_tool_calls=[]")) {
      return {
        role: "assistant",
        content: unwrapStructuredParseFallback(formatStringContent(content)),
      };
    }
    return { content: formatStringContent(content), type: "message" };
  }

  return null;
};

/**
 * Normalize additional_details to structured execution steps (sync + async parity).
 * @param {Array} details
 * @returns {Array<object>}
 */
export const normalizeAdditionalDetails = (details) => {
  if (!Array.isArray(details) || details.length === 0) return [];
  return details.map((detail) => parseDetailRepr(detail)).filter(Boolean);
};

/**
 * Ensure execution-step items have display-ready content (handles raw repr strings
 * and mixed Python/JSON literals that may slip through on some code paths).
 * @param {Array} steps
 * @returns {Array<object>}
 */
export const normalizeDebugExecutorSteps = (steps) => {
  if (!Array.isArray(steps)) return [];
  return steps
    .map((item) => {
      if (typeof item === "string") {
        return parseDetailRepr(item);
      }
      if (typeof item === "object" && item !== null && !Array.isArray(item)) {
        return {
          ...item,
          ...(item.content !== undefined
            ? { content: safeStringifyMessage(item.content) }
            : {}),
        };
      }
      return item;
    })
    .filter(Boolean);
};

/**
 * Count execution steps that will be rendered in the accordion (excludes nested tool outputs).
 * @param {Array} debugExecutor
 * @returns {number}
 */
export const countExecutionSteps = (debugExecutor) => {
  if (!Array.isArray(debugExecutor)) return 0;
  return debugExecutor.filter(
    (item) =>
      item?.role ||
      (Array.isArray(item?.tool_calls) && item.tool_calls.length > 0) ||
      (item?.content && item?.type !== "tool"),
  ).length;
};

/**
 * Normalize inference/chat response so async and sync payloads render identically.
 * @param {object} result
 * @returns {object}
 */
export const normalizeInferenceResult = (result) => {
  if (!result || typeof result !== "object") return result;

  const payload =
    result.result &&
    !Array.isArray(result.executor_messages) &&
    Array.isArray(result.result?.executor_messages)
      ? { ...result, ...result.result }
      : result;

  if (!Array.isArray(payload.executor_messages)) return payload;

  return {
    ...payload,
    executor_messages: payload.executor_messages.map((em) => ({
      ...em,
      additional_details: normalizeAdditionalDetails(em.additional_details),
    })),
  };
};

/**
 * Build a structured `debugExecutor` array (Execution Steps) for a single
 * executor_message. Prefers the backend-provided `additional_details` when
 * it is already structured. Falls back to synthesizing steps from the
 * canonical fields `user_query`, `tools_used`, and `final_response`.
 *
 * Output shape (consumed by AccordionPlanSteps):
 *   [
 *     { role: "user_query", content: "..." },
 *     { tool_calls: [{ id, name, args }] },
 *     { type: "tool", tool_call_id, content: "<output>" },
 *     { role: "assistant", content: "<final_response>" },
 *   ]
 *
 * @param {object} item - A single executor_messages[] entry
 * @returns {Array<object>} structured debug steps (never null)
 */
export const buildDebugExecutor = (item, chatHistory = null) => {
  if (!item || typeof item !== "object") return [];

  let steps = normalizeAdditionalDetails(item.additional_details);

  if (steps.length === 0) {
    steps = [];

    // 2. Tool calls + tool responses (from `tools_used` map)
    const toolsUsed =
      item.tools_used && typeof item.tools_used === "object" && !Array.isArray(item.tools_used)
        ? item.tools_used
        : null;

    if (toolsUsed) {
      const toolEntries = Object.entries(toolsUsed);
      const toolCalls = toolEntries
        .map(([callId, tu]) => {
          const name = tu?.name || tu?.tool_name || "";
          if (!name) return null;
          return {
            id: tu?.id || callId,
            name,
            args: tu?.args ?? tu?.arguments ?? {},
          };
        })
        .filter(Boolean);

      if (toolCalls.length > 0) {
        steps.push({ tool_calls: toolCalls });

        toolCalls.forEach((tc) => {
          const raw = toolsUsed[tc.id] || toolEntries.find(([, t]) => (t?.name || t?.tool_name) === tc.name)?.[1];
          const output = raw?.output ?? raw?.tool_output ?? "";
          steps.push({
            type: "tool",
            tool_call_id: tc.id,
            content: typeof output === "string" ? output : JSON.stringify(output, null, 2),
          });
        });
      }
    }
  }
  const hasEvaluatorStep = steps.some(
    (s) => s.role === "evaluator-response" || s.role === "evaluator-feedback",
  );
  const hasValidatorStep = steps.some(
    (s) => s.role === "validator-response" || s.role === "validator-feedback",
  );

  if (chatHistory?.evaluation_feedback && !hasEvaluatorStep) {
    steps.push({ role: "evaluator-feedback", content: chatHistory.evaluation_feedback });
  }
  if (chatHistory?.validation_feedback && !hasValidatorStep) {
    steps.push({ role: "validator-feedback", content: chatHistory.validation_feedback });
  }

  return steps;
};
