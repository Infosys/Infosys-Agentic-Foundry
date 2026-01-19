/**
 * Pipeline Utility Functions
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


export default {
  getAgentTypeAbbreviation,
};
