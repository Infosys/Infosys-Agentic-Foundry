/**
 * Server utility functions for MCP server type detection and management
 */

/**
 * Determines the server type based on server configuration
 * @param {Object} server - The server object containing mcp_config and other properties
 * @returns {string} Server type: "LOCAL", "REMOTE", "EXTERNAL", or "UNKNOWN"
 */
export const getServerType = (server) => {
  const raw = server || {};
  const hasCode = Boolean(
    raw?.mcp_config?.args?.[1] ||
    raw?.mcp_file?.code_content ||
    raw?.code_content ||
    raw?.code ||
    raw?.script
  );
  const hasUrl = Boolean(
    raw?.mcp_config?.url ||
    raw?.mcp_url ||
    raw?.endpoint ||
    raw?.mcp_config?.mcp_url ||
    raw?.mcp_config?.endpoint
  );

  if (raw.mcp_type === "module") return "EXTERNAL";
  if (hasCode) return "LOCAL";
  if (hasUrl) return "REMOTE";
  return String(raw.mcp_type || raw.type || "").toUpperCase() || "UNKNOWN";
};
