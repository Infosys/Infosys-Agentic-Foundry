/**
 * Pipeline Utility Functions
 * 
 * Helper functions for Pipeline components
 */

/**
 * Get agent type abbreviation for display
 * Uses the same abbreviations as shown in agent cards
 * @param {string} agentType - The agent type string
 * @returns {string} - Abbreviated agent type
 */
export const getAgentTypeAbbreviation = (agentType) => {
  if (!agentType || typeof agentType !== "string") return "";

  // Map specific agent types to their abbreviations (same as AgentCard)
  const abbreviationMap = {
    react_agent: { title: "RA", description: "React Agent" },
    react_critic_agent: { title: "RC", description: "React Critic" },
    planner_executor_agent: { title: "PE", description: "Planner Executor" },
    multi_agent: { title: "PC", description: "Planner Critic" },
    meta_agent: { title: "MA", description: "Meta Agent" },
    planner_meta_agent: { title: "MP", description: "Meta Planner" },
    hybrid_agent: { title: "HA", description: "Hybrid Agent" },
  };

  const mapping = abbreviationMap[agentType];

  // Return the mapped abbreviation or fallback to first two letters
  return mapping?.title || (agentType.length >= 2 ? agentType.substring(0, 2).toUpperCase() : agentType.toUpperCase()) || "";
};

/**
 * Generate unique ID for nodes/edges
 * @param {string} prefix - Prefix for the ID
 * @returns {string} - Unique ID
 */
export const generateId = (prefix = "node") => {
  return `${prefix}_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
};

/**
 * Format date for display
 * @param {string} dateString - ISO date string
 * @returns {string} - Formatted date
 */
export const formatDate = (dateString) => {
  if (!dateString) return "N/A";
  try {
    const date = new Date(dateString);
    return date.toLocaleDateString("en-US", {
      month: "short",
      day: "numeric",
      year: "numeric",
    });
  } catch {
    return "N/A";
  }
};

/**
 * Get node count from pipeline definition
 * @param {Object} pipeline - Pipeline object
 * @returns {number} - Number of nodes
 */
export const getNodeCount = (pipeline) => {
  try {
    const definition = pipeline?.pipeline_definition;
    if (definition?.nodes) {
      return definition.nodes.length;
    }
    return 0;
  } catch {
    return 0;
  }
};

export default {
  getAgentTypeAbbreviation,
  generateId,
  formatDate,
  getNodeCount,
};
