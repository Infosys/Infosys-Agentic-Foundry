/**
 * Workflow Utility Functions
 * 
 * Helper functions for Workflow components
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
 * Get node count from workflow definition
 * Handles both full workflow_definition (when readAccess is true)
 * and direct node_count/nodes_count fields (when readAccess is false)
 * @param {Object} workflow - Workflow object
 * @returns {number} - Number of nodes
 */
export const getNodeCount = (workflow) => {
  try {
    const definition = workflow?.workflow_definition;

    // When readAccess is true, workflow_definition contains full nodes array
    if (definition?.nodes) {
      return definition.nodes.length;
    }

    // When readAccess is false, workflow_definition contains node_count directly
    if (typeof definition?.node_count === "number") {
      return definition.node_count;
    }

    // Also check nodes_count (with 's') inside workflow_definition
    if (typeof definition?.nodes_count === "number") {
      return definition.nodes_count;
    }

    // Check top-level node_count / nodes_count on the workflow object itself
    if (typeof workflow?.node_count === "number") {
      return workflow.node_count;
    }
    if (typeof workflow?.nodes_count === "number") {
      return workflow.nodes_count;
    }

    // Fallback: check if workflow_definition is a number (some APIs return count directly)
    if (typeof definition === "number") {
      return definition;
    }

    return 0;
  } catch {
    return 0;
  }
};

export default {
  getAgentTypeAbbreviation,
  formatDate,
  getNodeCount,
};
