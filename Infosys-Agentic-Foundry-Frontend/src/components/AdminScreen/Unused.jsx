import React, { useState, useEffect, useCallback } from "react";
import Cookies from "js-cookie";
import styles from "./Unused.module.css";
import style from "../../css_modules/ListOfAgents.module.css";
import { APIs } from "../../constant";
import style2 from "../../css_modules/AvailableTools.module.css";
import AgentCard from "../ListOfAgents/AgentCard";
import ToolsCard from "../AvailableTools/ToolsCard";
import UpdateAgent from "../ListOfAgents/UpdateAgent.jsx";
import AddServer from "../AgentOnboard/AddServer.jsx";
import useFetch from "../../Hooks/useAxios.js";
import Loader from "../commonComponents/Loader.jsx";
import { useMessage } from "../../Hooks/MessageContext";
import SVGIcons from "../../Icons/SVGIcons";

const Unused = ({ initialType = "agents" }) => {
  const [selectedType, setSelectedType] = useState(initialType); // for data fetching
  const [activeTab, setActiveTab] = useState(initialType); // for tab highlight
  const [data, setData] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [editAgentData, setEditAgentData] = useState(null);
  const [selectedServer, setSelectedServer] = useState(null);
  const [showServerForm, setShowServerForm] = useState(false);
  const [deleteServerCardId, setDeleteServerCardId] = useState(null); // Track which server card is in delete mode
  const { fetchData, deleteData } = useFetch();
  const { addMessage } = useMessage();

  // Helper to determine server type - matches main servers logic
  const getServerType = (server) => {
    const raw = server || {};
    const hasCode = Boolean(raw?.mcp_config?.args?.[1] || raw?.mcp_file?.code_content || raw?.code_content || raw?.code || raw?.script);
    const hasUrl = Boolean(raw?.mcp_config?.url || raw?.mcp_url || raw?.endpoint || raw?.mcp_config?.mcp_url || raw?.mcp_config?.endpoint);

    if (raw.mcp_type === "module") return "EXTERNAL";
    if (hasCode) return "LOCAL";
    if (hasUrl) return "REMOTE";
    return ((raw.mcp_type || raw.type || "") + "").toUpperCase() || "UNKNOWN";
  };
  
  const deleteItem = async (id, email, isAdmin) => {
    try {
      let endpoint;
      if (selectedType === "agents") {
        endpoint = APIs.DELETE_AGENTS;
      } else if (selectedType === "tools") {
        endpoint = APIs.DELETE_TOOLS;
      } else if (selectedType === "servers") {
        endpoint = APIs.MCP_DELETE_TOOLS;
      }
      const response = await deleteData(`${endpoint}${id}`, {
        user_email_id: email,
        is_admin: isAdmin,
      });
      
      if (response?.is_delete || response?.is_deleted) {
        addMessage(response?.message || "Deleted successfully", "success");
        // Refresh the list
        fetchUnusedData();
        return true;
      } else {
        const errorMsg = response?.detail || response?.message || "Failed to delete";
        addMessage(errorMsg, "error");
        return false;
      }
    } catch (error) {
      const errorMsg = error?.response?.data?.detail || error?.message || "Failed to delete";
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

      let url;
      if (selectedType === "agents") {
        url = `${APIs.AGENTS_UNUSED}?threshold_days=15`;
      } else if (selectedType === "tools") {
        url = `${APIs.TOOLS_UNUSED}?threshold_days=15`;
      } else if (selectedType === "servers") {
        url = `${APIs.MCP_SERVERS_UNUSED}?threshold_days=15`;
      }

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
      } else if (selectedType === 'tools') {
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
      } else if (selectedType === 'servers') {
        const normalizeServerData = (item) => {
          const id = item.id || item.tool_id;
          return {
            ...item,
            id: id,
            tool_id: id,
            name: item.name || item.tool_name || 'Unnamed Server',
            tool_name: item.name || item.tool_name || 'Unnamed Server',
            description: item.description || item.tool_description || '',
            tool_description: item.description || item.tool_description || '',
            created_by: item.created_by || '',
            created_on: item.created_on || '',
            updated_on: item.updated_on || '',
            last_used: item.last_used || '',
            mcp_type: item.mcp_type || '',
            mcp_config: item.mcp_config || {}
          };
        };

        if (response.unused_mcp_tools?.details) {
          itemsList = response.unused_mcp_tools.details.map(normalizeServerData);
        } else if (response.unused_servers?.details) {
          itemsList = response.unused_servers.details.map(normalizeServerData);
        } else if (response.details || response.servers) {
          itemsList = (response.details || response.servers).map(normalizeServerData);
        } else if (Array.isArray(response)) {
          itemsList = response.map(normalizeServerData);
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
      {loading && (
        <div className={styles.loaderOverlay}>
          <Loader contained />
        </div>
      )}
      <div className={style.containerCss}>
        {!initialType && (
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
        )}

        <div className={styles.listArea}>
          {error && <div className={styles.error}>{error}</div>}

          {!loading && !error && (
            <>
              <div className={styles.visibleAgentsContainer}>
                {!data || data.length === 0 ? (
                  <div className={styles.noItemsWrapper}>
                    <div className={styles.noItemsText}>
                      {selectedType === "agents" 
                        ? "No unused agents found"
                        : selectedType === "tools"
                        ? "No unused tools found"
                        : "No unused servers found"}
                    </div>
                  </div>
                ) : (
                  <>
                    {selectedType === "agents" && (
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
                    )}
                    {selectedType === "tools" && (
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
                    {selectedType === "servers" && (
                      <div className={style2.toolsList}>
                        {data
                          .filter(item => item && typeof item === 'object')
                          .map((server, index) => {
                            const serverId = server.tool_id || server.id;
                            const isDeleteMode = deleteServerCardId === serverId;
                            return (
                              <div
                                key={`server-card-${serverId || index}`}
                                className={`${isDeleteMode ? style2["delete-card"] : ""} ${style2["card-unused"]}`}
                              >
                                {!isDeleteMode ? (
                                  <div>
                                    <p className={style2["card-title"]}>{server.tool_name || server.name || "Unnamed Server"}</p>
                                    <div className={style2["dash"]}></div>
                                    <div
                                      style={{
                                        position: "absolute",
                                        left: "2px",
                                        bottom: "10px",
                                        display: "flex",
                                        alignItems: "center",
                                        gap: "8px",
                                        pointerEvents: "none",
                                      }}>
                                      <span
                                        style={{
                                          fontSize: "12px",
                                          padding: "4px 10px",
                                          background: "#6b7280",
                                          color: "#fff",
                                          borderRadius: "8px",
                                          textTransform: "uppercase",
                                          letterSpacing: "0.5px",
                                        }}>
                                        {getServerType(server)}
                                      </span>
                                    </div>
                                    <div className={style2["card-info"]}>
                                      <div className={style2["info-item"]}>
                                        <div className={style2["info-label"]}>Created by:</div>
                                        <div className={style2["info-value"]}>{server.created_by || "-"}</div>
                                      </div>
                                      <div className={style2["info-item"]}>
                                        <div className={style2["info-label"]}>Created on:</div>
                                        <div className={style2["info-value"]}>{server.created_on || "-"}</div>
                                      </div>
                                      <div className={style2["info-item"]}>
                                        <div className={style2["info-label"]}>Last used:</div>
                                        <div className={style2["info-value"]}>{server.updated_on || server.last_used || "-"}</div>
                                      </div>
                                    </div>
                                    <div className={style2["btn-grp"]}>
                                      <button
                                        onClick={() => setDeleteServerCardId(serverId)}
                                        title="Delete"
                                        className={style2["deleteBtn"]}>
                                        <SVGIcons icon="recycle-bin" width={20} height={16} />
                                      </button>
                                    </div>
                                  </div>
                                ) : (
                                  <>
                                    <button className={style2["cancel-btn"]} onClick={() => setDeleteServerCardId(null)}>
                                      <SVGIcons icon="fa-xmark" fill="#3D4359" />
                                    </button>
                                    <input className={style2["email-id-input"]} type="text" value={server.created_by || "-"} disabled />
                                    <div className={style2["action-info"]}>
                                      <span className={style2.warningIcon}>
                                        <SVGIcons icon="warnings" width={16} height={16} fill="#B8860B" />
                                      </span>
                                      creator / admin can perform this action
                                    </div>
                                    <div className={style2["delete-btn-container"]}>
                                      <button
                                        onClick={() => {
                                          deleteItem(serverId, Cookies.get("email"), Cookies.get("role")?.toUpperCase() === "ADMIN");
                                          setDeleteServerCardId(null);
                                        }}>
                                        DELETE <SVGIcons icon="fa-circle-xmark" width={16} height={16} />
                                      </button>
                                    </div>
                                  </>
                                )}
                              </div>
                            );
                          })}
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

        {showServerForm && selectedServer && (
          <div className={style.EditAgentContainer}>
            <AddServer
              onClose={() => {
                setShowServerForm(false);
                setSelectedServer(null);
              }}
              setRestoreData={setSelectedServer}
              selectedType={getServerType(selectedServer)}
              setRefreshPaginated={fetchUnusedData}
              recycle={false}
              unused={true}
              serverData={selectedServer}
            />
          </div>
        )}
      </div>
    </>
  );
};

export default Unused;