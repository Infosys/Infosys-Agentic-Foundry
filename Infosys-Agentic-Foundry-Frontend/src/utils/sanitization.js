/**
 * Sanitization utilities to prevent XSS attacks
 * These functions validate and sanitize user input before processing
 */

/**
 * Sanitizes user input to prevent XSS attacks
 * @param {string} input - The input string to sanitize
 * @param {string} type - The type of sanitization ('text', 'html', 'attribute', 'code')
 * @returns {string} - Sanitized string
 */
export const sanitizeInput = (input, type = "text") => {
  if (typeof input !== "string") {
    return String(input);
  }

  switch (type) {
    case "text":
      // Remove all HTML tags and dangerous characters
      return input
        .replace(/[<>]/g, "")
        .replace(/javascript:/gi, "")
        .replace(/on\w+\s*=/gi, "");

    case "html":
      // More aggressive sanitization for HTML contexts
      return input.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#x27;").replace(/\//g, "&#x2F;");

    case "attribute":
      // For use in HTML attributes
      return input.replace(/"/g, "&quot;").replace(/'/g, "&#x27;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

    case "code":
      // For code snippets, allow more characters but still sanitize dangerous patterns
      return input
        .replace(/<script\b[^<]*(?:(?!<\/script>)<[^<]*)*<\/script>/gi, "")
        .replace(/javascript:/gi, "")
        .replace(/on\w+\s*=/gi, "");

    default:
      return input.replace(/[<>]/g, "");
  }
};

/**
 * Validates and sanitizes form field values based on field name
 * @param {string} name - Field name
 * @param {string} value - Field value
 * @returns {string} - Sanitized value
 */
export const sanitizeFormField = (name, value) => {
  // Convert value to string if it isn't already
  const stringValue = typeof value === "string" ? value : String(value);

  const allowedFields = {
    // Agent fields
    agent_name: { pattern: /^[a-zA-Z0-9_\s\-().{}\[\]]*$/, type: "text" },
    agentic_application_name: { pattern: /^[a-zA-Z0-9_\s\-().{}\[\]]*$/, type: "text" },
    agent_goal: { type: "text" },
    workflow_description: { type: "text" },
    agentic_application_description: { type: "text" },
    agentic_application_workflow_description: { type: "text" },
    model_name: { type: "text" },
    system_prompt: { type: "text" },

    // Tool fields
    description: { type: "text" },
    code: { type: "code" },
    code_snippet: { type: "code" },
    name: { pattern: /^[a-zA-Z0-9_\s\-().{}\[\]]*$/, type: "text" },

    // Common fields
    subdirectory: { pattern: /^[a-zA-Z0-9_\-\/]*$/, type: "text" },
    search: { type: "text" },
    knowledgeBaseName: { pattern: /^[a-zA-Z0-9_\s\-]*$/, type: "text" },
    email_id: { pattern: /^[a-zA-Z0-9@._\-]*$/, type: "text" },
    userEmail: { pattern: /^[a-zA-Z0-9@._\-]*$/, type: "text" },
    createdBy: { pattern: /^[a-zA-Z0-9@._\-]*$/, type: "text" },
    created_by: { pattern: /^[a-zA-Z0-9@._\-]*$/, type: "text" },

    // Server fields
    server_name: { pattern: /^[a-zA-Z0-9_\s\-().{}\[\]]*$/, type: "text" },
    server_url: { type: "text" },
    api_key: { type: "text" },

    // Agent type
    agent_type: { type: "text" },
  };

  // Check if field is allowed
  if (!allowedFields[name]) {
    console.warn(`Field "${name}" is not in the allowlist. Applying default sanitization.`);
    return sanitizeInput(stringValue, "text");
  }

  const rule = allowedFields[name];

  // If pattern is defined, validate and clean
  if (rule.pattern) {
    // Remove characters that don't match the pattern
    const cleaned = stringValue
      .split("")
      .filter((char) => {
        // Test single character against the pattern
        const testStr = char;
        // Extract the character class from the pattern
        const patternStr = rule.pattern.source.replace(/^\^|\$$/g, "");
        const testPattern = new RegExp(patternStr);
        return testPattern.test(testStr);
      })
      .join("");

    // Still apply basic sanitization
    return sanitizeInput(cleaned, rule.type);
  }

  // Apply sanitization based on type
  return sanitizeInput(stringValue, rule.type);
};

/**
 * Validates event object structure before processing
 * @param {object} event - Event object to validate
 * @returns {boolean} - True if event is valid
 */
export const isValidEvent = (event) => {
  return event && event.target && typeof event.target.name === "string" && event.target.value !== undefined;
};
