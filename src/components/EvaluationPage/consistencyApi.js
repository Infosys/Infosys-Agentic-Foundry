// consistencyApi.js
// API helper for ConsistencyTab, matching GroundTruth style
import { APIs } from "../../constant";
import useFetch from "../../Hooks/useAxios";

export const useConsistencyApi = () => {
  const { postData } = useFetch();

  // Executes the consistency evaluation API
  const executeConsistencyEvaluation = async (formData, agentListDropdown) => {
    const selectedAgent = agentListDropdown.find((agent) => agent.agentic_application_name === formData.agent_name);
    const agent_id = selectedAgent ? selectedAgent.agentic_application_id : "";
    const agent_name = selectedAgent ? selectedAgent.agentic_application_name : formData.agent_name;
    const formDataToSend = new FormData();

    // Handle file upload OR manual queries
    if (formData.uploaded_file) {
      formDataToSend.append("file", formData.uploaded_file, formData.uploaded_file.name);
    } else if (formData.queries && formData.queries.length > 0) {
      // Send queries as JSON string or individual fields depending on backend API
      formDataToSend.append("queries", JSON.stringify(formData.queries));
    }

    formDataToSend.append("agent_id", agent_id);
    formDataToSend.append("agent_name", agent_name);
    formDataToSend.append("agent_type", formData.agent_type);
    formDataToSend.append("model_name", formData.model_name);
    formDataToSend.append("session_id", "test_consistency");
    // Use postData helper for consistency
    return await postData(APIs.CONSISTENCY_PREVIEW_RESPONSES, formDataToSend);
  };

  return { executeConsistencyEvaluation };
};
