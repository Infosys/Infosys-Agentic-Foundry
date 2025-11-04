import React, { useState, useEffect, useCallback } from "react";
import Cookies from "js-cookie";
import styles from "./Unused.module.css";
import style from "../../css_modules/ListOfAgents.module.css";
import { APIs } from "../../constant";
import style2 from "../../css_modules/AvailableTools.module.css";
import AgentCard from "../ListOfAgents/AgentCard";
import ToolsCard from "../AvailableTools/ToolsCard";
import UpdateAgent from "../ListOfAgents/UpdateAgent.jsx";
import useFetch from "../../Hooks/useAxios.js";
import Loader from "../commonComponents/Loader.jsx";
import { useMessage } from "../../Hooks/MessageContext";

const Unused = () => {
  const [selectedType, setSelectedType] = useState("agents"); // for data fetching
  const [activeTab, setActiveTab] = useState("agents"); // for tab highlight
  const [data, setData] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [editAgentData, setEditAgentData] = useState(null);
  const { fetchData, deleteData } = useFetch();
  const { addMessage } = useMessage();
  
  const deleteItem = async (id, email, isAdmin) => {
    try {
      const endpoint = selectedType === "agents" ? APIs.DELETE_AGENTS : APIs.DELETE_TOOLS;
      const response = await deleteData(`${endpoint}${id}`, {
        user_email_id: email,
        is_admin: isAdmin,
      });
      
      if (response?.is_delete) {
        addMessage(response?.status_message || "Item deleted successfully", "success");
        // Refresh the list
        const userEmail = Cookies.get("email");
        const url = selectedType === "agents" 
          ? `${APIs.AGENTS_UNUSED}?threshold_days=15`
          : `${APIs.TOOLS_UNUSED}?threshold_days=15`;
        const newData = await fetchData(url);
        setData(newData?.unused_agents?.details || newData?.unused_tools?.details || []);
        return true;
      } else {
        const errorMsg = response?.detail || response?.status_message || response?.message || "Failed to delete item";
        addMessage(errorMsg, "error");
        return false;
      }
    } catch (error) {
      const errorMsg = error?.response?.data?.detail || error?.response?.data?.message || error?.message || "Error deleting item";
      addMessage(errorMsg, "error");
      return false;
    }
  };

  const onAgentEdit = (data) => {
    setEditAgentData(data);
  };

  const fetchUnusedData = useCallback(async () => {
    setLoading(true);
    setError(null);
    
    try {
      const userEmail = Cookies.get("email");
      if (!userEmail) {
        throw new Error("User email not found");
      }

      const url = selectedType === "agents" 
        ? `${APIs.AGENTS_UNUSED}?threshold_days=15`
        : `${APIs.TOOLS_UNUSED}?threshold_days=15`;

      const response = await fetchData(url);
      if (!response || typeof response !== 'object') {
        throw new Error('Invalid response received');
      }

      // Extract the data based on the type
      let itemsList = [];
      if (selectedType === 'agents') {
        if (response.unused_agents?.details) {
          itemsList = response.unused_agents.details;
        } else if (response.details || response.agents) {
          itemsList = response.details || response.agents;
        }
      } else {
        const normalizeToolData = (item) => {
          // Ensure we have a valid ID
          const id = item.id || item.tool_id;
          if (!id) {
            console.error('Tool missing ID:', item);
          }
          
          return {
            ...item,
            id: id,
            tool_id: id,
            name: item.name || item.tool_name || 'Unnamed Tool',
            tool_name: item.name || item.tool_name || 'Unnamed Tool',
            description: item.description || item.tool_description || '',
            tool_description: item.description || item.tool_description || '',
            created_by: item.created_by || '',
            created_on: item.created_on || '',
            last_used: item.last_used || ''
          };
        };

        if (response.unused_tools?.details) {
          itemsList = response.unused_tools.details.map(normalizeToolData);
        } else if (response.details || response.tools) {
          itemsList = (response.details || response.tools).map(normalizeToolData);
        }
      }

      if (!Array.isArray(itemsList)) {
        throw new Error(`No ${selectedType} data found`);
      }

      setData(itemsList);
    } catch (e) {
      setError(e.message);
      addMessage(e.message, "error");
    } finally {
      setLoading(false);
    }
  }, [selectedType, fetchData, addMessage]);

  useEffect(() => {
    if (!selectedType) return;
    fetchUnusedData();
  }, [selectedType, fetchUnusedData]);

  const handleTabClick = (tabType) => {
    setSelectedType(tabType);
    setActiveTab(tabType);
  };

  if (!style || !styles || !style2) {
    return <div>Loading styles...</div>;
  }

  return (
    <>
      <div className={style.containerCss}>
        <div className={styles.toggleWrapper}>
          <button
            type="button"
            className={`iafTabsBtn ${activeTab === "agents" ? " active" : ""}`}
            onClick={() => handleTabClick("agents")}
          >
            Agents
          </button>
          <button
            type="button"
            className={`iafTabsBtn ${activeTab === "tools" ? " active" : ""}`}
            onClick={() => handleTabClick("tools")}
          >
            Tools
          </button>
        </div>

        <div className={styles.listArea}>
          {loading && <Loader />}
          {error && <div className={styles.error}>{error}</div>}

          {!loading && !error && (
            <>
              <div className={styles.visibleAgentsContainer}>
                {!data || data.length === 0 ? (
                  <div className={styles.noItemsWrapper}>
                    <div className={styles.noItemsText}>
                      {selectedType === "agents" 
                        ? "No unused agents found"
                        : "No unused tools found"}
                    </div>
                  </div>
                ) : (
                  <>
                    {selectedType === "agents" ? (
                      <div className={style.agentsList}>
                        {data
                          .filter(agent => agent && typeof agent === 'object')
                          .map((item, index) => (
                            <div key={`agents-card-${index}`}>
                              <AgentCard
                                data={item}
                                styles={style}
                                isUnusedSection={true}
                                onAgentEdit={onAgentEdit}
                                showDescription={true}
                                isRecycleBin={false}
                                tags=""
                                setAgentTags={() => {}}
                                createdBy={item.created_by}
                                createdOn={item.created_on}
                                lastUsed={item.last_used}
                                deleteAgent={deleteItem}
                                fetchAgents={fetchUnusedData}
                              />
                            </div>
                          ))}
                      </div>
                    ) : (
                      <div className={style2.toolsList}>
                        {data
                          .filter(item => item && typeof item === 'object')
                          .map((item, index) => (
                            <div key={`tools-card-${index}`}>
                              <ToolsCard
                                tool={item}
                                style={style2}
                                isUnusedSection={true}
                                loading={loading}
                                setSelectedTool={() => {}}
                                createdBy={item.created_by}
                                lastUsed={item.last_used}
                                fetchPaginatedTools={fetchUnusedData}
                              />
                            </div>
                          ))}
                      </div>
                    )}
                  </>
                )}
              </div>
            </>
          )}
        </div>

        {editAgentData && (
          <div className={style.EditAgentContainer}>
            <UpdateAgent
              onClose={() => setEditAgentData(null)}
              agentData={editAgentData}
              setEditAgentData={setEditAgentData}
              tags=""
              agentsListData={data}
              styles={style}
              fetchAgents={() => {}}
              searchTerm=""
              selectedType={selectedType}
              recycleBin={false}
              unused={true}
            />
          </div>
        )}
      </div>
    </>
  );
};

export default Unused;