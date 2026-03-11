import React from "react";
import AgentForm from "../AgentForm";

/**
 * UpdateAgent - Thin wrapper component for updating existing agents
 *
 * Uses the unified AgentForm component with mode="update"
 * All business logic is handled in AgentForm.jsx
 */
const UpdateAgent = (props) => {
  const { agentData, onClose, tags, fetchAgents, RestoreAgent, deleteAgent, recycleBin, readOnly } = props;

  return (
    <AgentForm
      mode="update"
      agentData={agentData}
      onClose={onClose}
      fetchAgents={fetchAgents}
      tags={tags}
      recycleBin={recycleBin}
      onRestore={RestoreAgent}
      onDelete={deleteAgent}
      readOnly={readOnly}
    />
  );
};

export default UpdateAgent;
