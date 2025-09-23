import React, { useEffect, useState } from "react";
import Register from "../Register/Index";
import Loader from "../commonComponents/Loader";
import { useMessage } from "../../Hooks/MessageContext";
import {APIs} from "../../constant";
import AgentList from "./AgentsList";
import ResponsesList from "./ResponseList";
import ResponseDetail from "./ResponseDetail";
import styles from "./AdminScreen.module.css";
// import AgentsEvaluator from "../AgentsEvaluator";
// import EvaluationScore from "../AdminScreen/EvaluationScore.js";
import UpdatePassword from "./UpdatePassword.jsx";
import RecycleBin from "./RecycleBin.jsx";
import useFetch from "../../Hooks/useAxios.js";

const AdminScreen = () => {
  const [agents, setAgents] = useState([]);
  const [responses, setResponses] = useState([]);
  const [selectedAgentId, setSelectedAgentId] = useState(null);
  const [responseDetail, setResponseDetail] = useState(null);
  const [form, setForm] = useState({});// form state for response details
  const [loadingAgents, setLoadingAgents] = useState(false);//loader state for agents
  const [activeTab, setActiveTab] = useState("register"); // State for active tab
  const { addMessage, setShowPopup} = useMessage(); // Message context for notifications
  
  const [selectedAgentName, setSelectedAgentName] = useState(null);
  const{ fetchData, putData } = useFetch();

  useEffect(() => {
    if (!loadingAgents) {
      setShowPopup(true);
    } else {
      setShowPopup(false);
    }
  }, [loadingAgents, setShowPopup]);

  // Fetch all agents
  const loadAgents = async () => {
    setLoadingAgents(true);
    try {
      setAgents([]); // Clear agents before loading new data
      const agentsData = await fetchData(APIs.GET_APPROVALS_LIST);
      setAgents(agentsData);
    } catch (err) {
      addMessage("Failed to load agents", "error");
    } finally {
      setLoadingAgents(false);
    }
  };
  // Fetch agents on mount and clear response states when switching tabs
  useEffect(() => {
    if(activeTab === "learning"){
      // Reset states when switching to learning tab
      setResponseDetail(null);
      setSelectedAgentId(null);
      loadAgents();
    }
  }, [activeTab]); // Only load agents when learning tab is active
  // Fetch responses for a selected agent
  const loadResponses = async (agentId, agentName) => {
    setSelectedAgentId(agentId);
    setSelectedAgentName(agentName);
    try {
      const responsesData = await fetchData(`${APIs.GET_APPROVALS_BY_ID}${agentId}`);
      setResponses(responsesData);
      // Switch to learning tab when an agent is selected
      setActiveTab("learning");
    } catch (err) {
      addMessage("Failed to load responses", "error");
    }
  };

  // Fetch details for a selected response
  const loadResponseDetail = async (responseId) => {
    try {
      const data = await fetchData(`${APIs.GET_RESPONSES_DATA}${responseId}`);
      const response = data[0] || {};
      setResponseDetail(response);
      setForm({
        response_id: response.response_id || "",
        query: response.query || "",
        old_final_response: response.old_final_response || "",
        old_steps: response.old_steps || "",
        old_response: response.old_response || "",
        feedback: response.feedback || "",
        new_final_response: response.new_final_response || "",
        new_steps: response.new_steps || "",
        approved: response.approved === 1,
      });
    } catch (err) {
      addMessage("Failed to load response details", "error");
    }
  };

  // Handle form field changes
  const handleFormChange = (e) => {
    const { name, value, type, checked } = e.target;
    setForm((prevForm) => ({ ...prevForm, [name]: type === "checkbox" ? checked : value }));
  };
  // Handle form submission
  const handleFormSubmit = async (e) => {
    setLoadingAgents(true);
    e.preventDefault();
    const payload = { ...form };
    try {
      const response = await putData(APIs.UPDATE_APPROVAL_RESPONSE,payload)
      setLoadingAgents(false); // Hide loader before showing toast
      if (response.is_update) {
        addMessage("Updated successfully!", "success");
        // After successful update, return to the responses list
        setResponseDetail(null);
        loadResponses(selectedAgentId);
      } else {
        addMessage("Update failed!", "error");
      }
    } catch (err) {
      setLoadingAgents(false); // Hide loader before showing toast
      addMessage("Update failed!", "error");
    }
  };

  return (
    <div style={{ fontFamily: "Arial, sans-serif", marginLeft: 20,marginTop:20, maxHeight: '80vh', overflowY: 'auto' }}>
      {loadingAgents && <Loader />}
      
      {/* Tabs Header */}      <div className={styles.tabHeader}>
        {/* <button 
          className={activeTab === "register" ? styles.activeTab : styles.tab} 
          onClick={() => {
            setActiveTab("register");
            // Clear response states when switching to Register tab
            setResponseDetail(null);
            setSelectedAgentId(null);
          }}
        >
          Register
        </button> */}
        <button 
          className={activeTab === "learning" ? styles.activeTab : styles.tab} 
          onClick={() => setActiveTab("learning")}
        >
          Learning
        </button>
        {/* Commented out - moved to separate Evaluation page
        <button 
          className={activeTab === "metrics" ? styles.activeTab : styles.tab} 
          onClick={() => {
            // window.history.replaceState(null, '', '/admin-evaluator');
            setActiveTab("metrics");
            setResponseDetail(null);
            setSelectedAgentId(null);
          }}
        >
          Metrics
        </button>
        <button 
          className={activeTab === "evaluation" ? styles.activeTab : styles.tab} 
          onClick={() => {
            setActiveTab("evaluation");
            setResponseDetail(null);
            setSelectedAgentId(null);
          }}
        >
          Evaluations
        </button>
        */}
         {/* <button 
          className={activeTab === "Update User" ? styles.activeTab : styles.tab} 
          onClick={() => {
            setActiveTab("Update User");
            setResponseDetail(null);
            setSelectedAgentId(null);
          }}
        >
         Update User
        </button> */}
      {/* <button 
  className={activeTab === "Recycle Bin" ? styles.activeTab : styles.tab} 
  onClick={() => {
    setActiveTab("Recycle Bin"); 
    setResponseDetail(null);
    setSelectedAgentId(null);
  }}
>
  RecycleBin
</button> */}
       
      </div>

      {/* Tab Content */}
      <div className={styles.tabContent}>
        {/* Register Tab */}
        {/* {activeTab === "register" && (
          <div className={styles.registrationForm}>
            <Register isAdminScreen={true} />
          </div>
        )} */}
        {/* Learning Tab */}
        {activeTab === "learning" && (
          <div>
            {!selectedAgentId ? (
              /* If no agent is selected, show the agent list */
              <div>
                <AgentList agents={agents} onSelect={loadResponses} />
              </div>
            ) : responseDetail ? (
              /* If response detail exists, show the response detail */
              <div>
                <ResponseDetail
                  form={form}
                  onChange={handleFormChange}
                  onSubmit={handleFormSubmit}
                  onBack={() => {
                    setResponseDetail(null); // Clear response detail
                  }}
                />
              </div>
            ) : (
              /* If agent is selected but no response detail, show responses list */
              <div>
                <ResponsesList
                  responses={responses}
                  onSelect={loadResponseDetail}
                  onBack={() => {
                    setSelectedAgentId(null); // Clear selected agent
                    setSelectedAgentName(null); // Clear agent name as well
                    loadAgents(); // Reload agents list
                  }}
                  agentName={selectedAgentName}
                />
              </div>
            )}
          </div>
        )}
        {/* Commented out - moved to separate Evaluation page
        {/* Metrics Tab */}
        {/* {activeTab === "metrics" && (
          <div className={styles.evaluateMetrics}>
            <AgentsEvaluator />
          </div>
        )} */}
        {/* Evaluations Tab */}
        {/* {activeTab === "evaluation" && (
          <div className={styles.evaluateMetrics}>
            <EvaluationScore />
          </div>
        )} */}
        {/* End of commented evaluation sections */}
         
        
      </div>
    </div>
  );
};

export default AdminScreen;