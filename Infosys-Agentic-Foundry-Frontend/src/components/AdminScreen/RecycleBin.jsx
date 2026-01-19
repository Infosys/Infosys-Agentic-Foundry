import React, { useState, useEffect } from "react";
import styles from "./RecycleBin.module.css";
import Cookies from "js-cookie";
import AgentCard from "../ListOfAgents/AgentCard";
import style from "../../css_modules/ListOfAgents.module.css";
import { APIs, REACT_AGENT } from "../../constant";
import style2 from "../../css_modules/AvailableTools.module.css";
import serverStyles from "../../css_modules/AvailableServers.module.css";
import ToolsCard from "../AvailableTools/ToolsCard";
import UpdateAgent from "../ListOfAgents/UpdateAgent.jsx";
import ToolOnBoarding from "../AvailableTools/ToolOnBoarding.jsx";
import AddServer from "../AgentOnboard/AddServer.jsx";
import useFetch from "../../Hooks/useAxios.js";
import Loader from "../commonComponents/Loader.jsx";
import { useMessage } from "../../Hooks/MessageContext";

const RecycleBin = ({ initialType = "agents" }) => {
  const [selectedType, setSelectedType] = useState(initialType); // for data fetching
  const [activeTab, setActiveTab] = useState(initialType); // for tab highlight
  const [lastTab, setLastTab] = useState(initialType); // to restore tab highlight after modal
  const [data, setData] = useState([]);
  const [error, setError] = useState(null);
  const { fetchData, postData, deleteData } = useFetch();
  const [editAgentData, setEditAgentData] = useState("");
  const [showForm, setShowForm] = useState(false);
  const [isAddTool, setIsAddTool] = useState(true);
  const [editTool, setEditTool] = useState({});
  const [restoreData, setRestoreData] = useState();
  const { addMessage } = useMessage();
  const [loader, setLoader] = useState(false);
  const [selectedServer, setSelectedServer] = useState(null);
  const [showServerForm, setShowServerForm] = useState(false);
  const onAgentEdit = (data) => {
    setEditAgentData(data);
  };
  const handleUpdateAgentClose = () => {
    setEditAgentData(null);
  };
  const RestoreAgent = async (e) => {
    setLoader(true);
    let url = "";
    if (selectedType === "agents") {
      url = `${APIs.RESTORE_AGENTS}${editAgentData?.agentic_application_id}?user_email_id=${encodeURIComponent(Cookies?.get("email"))}`;
    }
    const response = await postData(url);
    if (response?.is_restored) {
      setLoader(false);
      addMessage(response?.message, "success");
      setEditAgentData(false);
      setRestoreData(response);
    } else {
      setLoader(false);
      setEditAgentData(false);
      addMessage(response.message, "error");
    }
  };
  const deleteAgent = async (e) => {
    setLoader(true);
    let url = "";
    if (selectedType === "agents") {
      url = `${APIs.DELETE_AGENTS_PERMANENTLY}${editAgentData?.agentic_application_id}?user_email_id=${encodeURIComponent(Cookies?.get("email"))}`;
    } else if (selectedType === "tools") {
      url = `${APIs.DELETE_TOOLS_PERMANENTLY}${editAgentData?.tool_id}?user_email_id=${encodeURIComponent(Cookies?.get("email"))}`;
    } else if (selectedType === "servers") {
      url = `${APIs.MCP_DELETE_SERVERS_PERMANENTLY}${editAgentData?.tool_id}?user_email_id=${encodeURIComponent(Cookies?.get("email"))}`;
    }
    const response = await deleteData(url);
    if (response?.is_delete) {
      setLoader(false);
      addMessage(response.message, "success");
      setEditAgentData(false);
      setRestoreData(response);
    } else {
      setLoader(false);
      setEditAgentData(false);
      addMessage(response.message, "error");
    }
  };

  // Helper to get server type display
  const getServerType = (server) => {
    const raw = server || {};
    const hasCode = Boolean(raw?.mcp_config?.args?.[1] || raw?.mcp_file?.code_content || raw?.code_content || raw?.code || raw?.script);
    const hasUrl = Boolean(raw?.mcp_config?.url || raw?.mcp_url || raw?.endpoint || raw?.mcp_config?.mcp_url || raw?.mcp_config?.endpoint);
    
    if (raw.mcp_type === "module") return "EXTERNAL";
    if (hasCode) return "LOCAL";
    if (hasUrl) return "REMOTE";
    return ((raw.mcp_type || raw.type || "") + "").toUpperCase() || "UNKNOWN";
  };

  useEffect(() => {
    if (!selectedType) return;
    const fetchRecycleData = async () => {
      setLoader(true);
      setError(null);
      try {
        let url = "";
        if (selectedType === "agents") {
          url = `${APIs.AGENTS_RECYCLE_BIN}?user_email_id=${encodeURIComponent(Cookies?.get("email"))}`;
        } else if (selectedType === "tools") {
          url = `${APIs.TOOLS_RECYCLE_BIN}?user_email_id=${encodeURIComponent(Cookies?.get("email"))}`;
        } else if (selectedType === "servers") {
          url = `${APIs.MCP_SERVERS_RECYCLE_BIN}?user_email_id=${encodeURIComponent(Cookies?.get("email"))}`;
        }
        const json = await fetchData(url);
        setData(json);
      } catch (err) {
        setError(err.response.data.detail);
        setData([]);
      } finally {
        setLoader(false);
      }
    };
    fetchRecycleData();
  }, [selectedType, restoreData]);

  return (
    <>
      {showForm && (
        <ToolOnBoarding
          setShowForm={(show) => {
            if (!show) setActiveTab(lastTab);
            setShowForm(show);
          }}
          isAddTool={isAddTool}
          editTool={editTool}
          setIsAddTool={setIsAddTool}
          tags={""}
          fetchPaginatedTools={""}
          recycle={true}
          selectedType={selectedType}
          setRestoreData={setRestoreData}
        />
      )}
      {loader && (
        <div className={styles.loaderOverlay}>
          <Loader contained />
        </div>
      )}
      <div className={style.containerCss}>
        {/* <div className={styles.recycleBinContainer}> */}
        {!initialType && (
          <div className={styles.toggleWrapper}>
            <button
              type="button"
              className={`iafTabsBtn ${activeTab === "agents" ? " active" : ""}`}
              onClick={() => {
                setActiveTab("agents");
                setSelectedType("agents");
              }}>
              Agents
            </button>
            <button
              type="button"
              className={`iafTabsBtn ${activeTab === "tools" ? " active" : ""}`}
              onClick={() => {
                setActiveTab("tools");
                setSelectedType("tools");
              }}>
              Tools
            </button>
          </div>
        )}

        <div className={styles.listArea}>
          {error && <p className={styles.error}>{error}</p>}
          {!loader && !error && selectedType === "agents" && (
            <>
              <div className={styles.visibleAgentsContainer}>
                {!data.length > 0 ? (
                  <>
                    <div className={style.agentsList}>
                      <div className={styles.cardNoData}>
                        <div className={styles.discriptionNoData}>{"No Deleted Agents To Display"}</div>
                      </div>
                    </div>
                  </>
                ) : (
                  <>
                    <div className={style.agentsList}>
                      {data.length > 0 &&
                        data?.map((data1) => (
                          <AgentCard
                            recycle={"recycle"}
                            key={`agent-${data1.agentic_application_id}`}
                            styles={style}
                            data={data1}
                            onAgentEdit={(agent) => {
                              setLastTab(activeTab);
                              setActiveTab("");
                              onAgentEdit(agent);
                            }}
                            deleteAgent={""}
                            fetchAgents={""}
                          />
                        ))}
                    </div>
                  </>
                )}
              </div>
            </>
          )}
          {!loader && !error && selectedType === "tools" && (
            <>
              {!data.length > 0 ? (
                <>
                  <div className={style.agentsList}>
                    <div className={styles.cardNoData}>
                      <div className={styles.discriptionNoData}>{"No Deleted Tools To Display"}</div>
                    </div>
                  </div>
                </>
              ) : (
                <>
                  <div className={style2.toolsList}>
                    {data.length > 0 &&
                      data?.map((item, index) => (
                        <ToolsCard
                          tool={item}
                          setShowForm={(show) => {
                            if (show) setLastTab("tools");
                            if (!show) setActiveTab(lastTab);
                            setShowForm(show);
                          }}
                          isAddTool={isAddTool}
                          setIsAddTool={setIsAddTool}
                          key={`tool-card-${item.tool_id}`}
                          style={style2}
                          setEditTool={setEditTool}
                          loading={loader}
                          fetchPaginatedTools={""}
                          recycle={true}
                        />
                      ))}
                  </div>
                </>
              )}
            </>
          )}
          {/* Servers Section */}
          {!loader && !error && selectedType === "servers" && (
            <>
              {!data.length > 0 ? (
                <>
                  <div className={style.agentsList}>
                    <div className={styles.cardNoData}>
                      <div className={styles.discriptionNoData}>{"No Deleted Servers To Display"}</div>
                    </div>
                  </div>
                </>
              ) : (
                <>
                  <div className={serverStyles.serverGrid}>
                    {data.length > 0 &&
                      data?.map((server) => (
                        <div
                          key={`server-${server.tool_id || server.id}`}
                          className={serverStyles.serverCard}
                          style={{
                            width: "200px",
                            minHeight: "140px",
                            height: "140px",
                            maxHeight: "160px",
                            padding: "11px",
                            color: "white",
                            position: "relative",
                            backgroundColor: "#3d4359",
                            boxShadow: "5px 15px 6px #00000029",
                            borderRadius: "4px",
                            cursor: "pointer",
                            display: "flex",
                            flexDirection: "column",
                            justifyContent: "space-between",
                            fontFamily: "Segoe UI",
                            transition: "transform 0.2s ease, box-shadow 0.2s ease",
                          }}
                          onMouseOver={(e) => {
                            e.currentTarget.style.transform = "translateY(-3px)";
                            e.currentTarget.style.boxShadow = "5px 18px 10px #00000029";
                          }}
                          onMouseOut={(e) => {
                            e.currentTarget.style.transform = "translateY(0)";
                            e.currentTarget.style.boxShadow = "5px 15px 6px #00000029";
                          }}
                          onClick={() => {
                            setSelectedServer(server);
                            setShowServerForm(true);
                          }}
                        >
                          <div style={{ flex: 1 }}>
                            <span
                              style={{
                                fontSize: "16px",
                                lineHeight: "14px",
                                fontWeight: 600,
                                letterSpacing: "-0.8px",
                                wordBreak: "break-word",
                                textTransform: "uppercase",
                                marginBottom: "4px",
                                maxHeight: "35px",
                                color: "#fff",
                              }}>
                              {server.tool_name || server.name}
                            </span>
                            <div style={{ width: "28px", height: "2px", backgroundColor: "#0071b3", marginTop: "5px" }} />
                            <div style={{ marginTop: "5px" }}>
                              <div
                                title={server.tool_description || server.description || "No description"}
                                style={{
                                  font: "normal normal 400 12px/16px Segoe UI",
                                  letterSpacing: "-0.24px",
                                  color: "#ffffff",
                                  wordBreak: "break-word",
                                  whiteSpace: "pre-line",
                                  maxHeight: "32px",
                                  marginBottom: "30px",
                                  overflow: "hidden",
                                  textOverflow: "ellipsis",
                                  display: "-webkit-box",
                                  WebkitLineClamp: 2,
                                  WebkitBoxOrient: "vertical",
                                }}>
                                {server.tool_description || server.description || "No description"}
                              </div>
                            </div>
                          </div>
                          <div style={{ position: "absolute", left: "2px", bottom: "10px", display: "flex", alignItems: "center", gap: "8px" }}>
                            <span style={{ fontSize: "12px", padding: "4px 10px", background: "#6b7280", color: "#fff", borderRadius: "8px" }}>
                              {getServerType(server)}
                            </span>
                          </div>
                        </div>
                      ))}
                  </div>
                </>
              )}
            </>
          )}
        </div>

        {editAgentData && (
          <div className={styles.fullPageEditContainer}>
            <UpdateAgent
              onClose={() => {
                setActiveTab(lastTab);
                handleUpdateAgentClose();
              }}
              agentData={editAgentData}
              setEditAgentData={setEditAgentData}
              tags={""}
              agentsListData={data?.filter((agent) => agent?.agentic_application_type === REACT_AGENT)}
              styles={style}
              fetchAgents={""}
              searchTerm={""}
              selectedType={selectedType}
              recycleBin={true}
              setRestoreData={setRestoreData}
              RestoreAgent={RestoreAgent}
              deleteAgent={deleteAgent}
            />
          </div>
        )}

        {/* Server Form for Restore/Delete - uses AddServer component */}
        {showServerForm && selectedServer && (
          <AddServer
            editMode={true}
            serverData={selectedServer}
            onClose={() => {
              setShowServerForm(false);
              setSelectedServer(null);
            }}
            recycle={true}
            setRestoreData={setRestoreData}
            selectedType={selectedType}
          />
        )}
      </div>
    </>
  );
};

export default RecycleBin;
