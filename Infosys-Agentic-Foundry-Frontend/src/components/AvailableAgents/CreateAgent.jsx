import React from "react";
import AgentForm from "./AgentForm";

/**
 * CreateAgent - Wrapper component for creating a new agent
 * Uses the unified AgentForm component in "create" mode
 *
 * @param {Object} props
 * @param {Function} props.onClose - Callback to close the modal
 * @param {Function} props.fetchAgents - Callback to refresh agents list
 * @param {Array} props.tags - Available tags
 */
const CreateAgent = ({ onClose, fetchAgents, tags }) => {
  return <AgentForm mode="create" onClose={onClose} fetchAgents={fetchAgents} tags={tags} />;
};

export default CreateAgent;
