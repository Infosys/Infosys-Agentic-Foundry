import React, { useState, useEffect, useMemo } from "react";
import ReactDOM from "react-dom";
import styles from "./RecycleBin.module.css";
import DisplayCard1 from "../../iafComponents/GlobalComponents/DisplayCard/DisplayCard1.jsx";
import { APIs, REACT_AGENT } from "../../constant";
import { getEmailFromToken } from "../../utils/jwtUtils";
import UpdateAgent from "../AvailableAgents/UpdateAgent.jsx";
import ToolOnBoarding from "../AvailableTools/ToolOnBoarding.jsx";
import AddServer from "../AgentOnboard/AddServer.jsx";
import useFetch from "../../Hooks/useAxios.js";
import Loader from "../commonComponents/Loader.jsx";
import { useMessage } from "../../Hooks/MessageContext";
import SummaryLine from "../../iafComponents/GlobalComponents/SummaryLine.jsx";
import EmptyState from "../commonComponents/EmptyState.jsx";
import { getServerType } from "../../utils/serverUtils.js";
import IAFButton from "../../iafComponents/GlobalComponents/Buttons/Button";

const RecycleBin = ({ initialType = "agents", heading, externalSearchTerm, selectedAgentTypes = [], selectedServerTypes = [], selectedToolTypes = [] }) => {
  const [selectedType, setSelectedType] = useState(initialType); // for data fetching
  const [activeTab, setActiveTab] = useState(initialType); // for tab highlight
  const [lastTab, setLastTab] = useState(initialType); // to restore tab highlight after modal
  const [data, setData] = useState([]);
  const [internalSearchTerm, setInternalSearchTerm] = useState("");

  // Use external search term if provided, otherwise use internal
  const searchTerm = externalSearchTerm !== undefined ? externalSearchTerm : internalSearchTerm;
  const [error, setError] = useState(null);
  const { fetchData, postData, deleteData } = useFetch();
  const [editAgentData, setEditAgentData] = useState("");
  const [showForm, setShowForm] = useState(false);
  const [isAddTool, setIsAddTool] = useState(true);
  const [editTool, setEditTool] = useState({});
  const [selectedServer, setSelectedServer] = useState(null);
  const [showServerForm, setShowServerForm] = useState(false);
  const [restoreData, setRestoreData] = useState();
  const { addMessage } = useMessage();
  const [loader, setLoader] = useState(false);
  const [restoreConflict, setRestoreConflict] = useState(null);
  const [restoreNewName, setRestoreNewName] = useState("");

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
      url = `${APIs.RESTORE_AGENTS}${editAgentData?.agentic_application_id}?user_email_id=${encodeURIComponent(getEmailFromToken())}`;
    } else if (selectedType === "tools") {
      url = `${APIs.RESTORE_TOOLS}${editAgentData?.tool_id}?user_email_id=${encodeURIComponent(getEmailFromToken())}`;
    } else if (selectedType === "servers") {
      const serverId = editAgentData?.tool_id || editAgentData?.id;
      url = `${APIs.RESTORE_SERVERS}${serverId}?user_email_id=${encodeURIComponent(getEmailFromToken())}`;
    }
    if (restoreNewName.trim()) url += `&new_name=${encodeURIComponent(restoreNewName.trim())}`;
    try {
      const response = await postData(url, undefined, { silent: true });
      setLoader(false);
      setRestoreNewName("");
      if (response?.is_restored) {
        addMessage(response?.message, "success");
        setEditAgentData(false);
        setRestoreData(response);
      } else {
        addMessage(response?.message || "Restore failed", "error");
        setEditAgentData(false);
      }
    } catch (err) {
      setLoader(false);
      const detail = err?.response?.data?.detail;
      if (detail?.name_conflict) {
        setRestoreConflict(detail);
      } else {
        const errMsg = typeof detail === "string" ? detail : detail?.message || err?.message || "Restore failed";
        addMessage(errMsg, "error");
        setEditAgentData(false);
      }
    }
  };
  const deleteAgent = async (e) => {
    setLoader(true);
    let url = "";
    if (selectedType === "agents") {
      url = `${APIs.DELETE_AGENTS_PERMANENTLY}${editAgentData?.agentic_application_id}?user_email_id=${encodeURIComponent(getEmailFromToken())}`;
    } else if (selectedType === "tools") {
      url = `${APIs.DELETE_TOOLS_PERMANENTLY}${editAgentData?.tool_id}?user_email_id=${encodeURIComponent(getEmailFromToken())}`;
    } else if (selectedType === "servers") {
      const serverId = editAgentData?.tool_id || editAgentData?.id;
      url = `${APIs.DELETE_SERVERS_PERMANENTLY}${serverId}?user_email_id=${encodeURIComponent(getEmailFromToken())}`;
    }
    const response = await deleteData(url);
    const statusMsg = response?.status_message || response?.message;
    if (response?.is_delete) {
      setLoader(false);
      if (statusMsg) addMessage(statusMsg, "success");
      setEditAgentData(false);
      setRestoreData(response);
    } else {
      setLoader(false);
      setEditAgentData(false);
      if (statusMsg) addMessage(statusMsg, "error");
    }
  };
  useEffect(() => {
    if (!selectedType) return;
    const fetchRecycleData = async () => {
      setLoader(true);
      setError(null);
      try {
        let url = "";
        if (selectedType === "agents") {
          url = `${APIs.AGENTS_RECYCLE_BIN}?user_email_id=${encodeURIComponent(getEmailFromToken())}`;
        } else if (selectedType === "tools") {
          url = `${APIs.TOOLS_RECYCLE_BIN}?user_email_id=${encodeURIComponent(getEmailFromToken())}`;
        } else if (selectedType === "servers") {
          url = `${APIs.SERVERS_RECYCLE_BIN}?user_email_id=${encodeURIComponent(getEmailFromToken())}`;
        }
        const json = await fetchData(url);

        // Normalize server data to include correct type and consistent field names
        if (selectedType === "servers" && Array.isArray(json)) {
          const normalizedServers = json.map(item => {
            const serverType = getServerType(item);
            return {
              ...item,
              // Ensure both name and tool_name fields exist for search compatibility
              name: item.name || item.tool_name || "Unnamed Server",
              tool_name: item.name || item.tool_name || "Unnamed Server",
              description: item.description || item.tool_description || "",
              tool_description: item.description || item.tool_description || "",
              type: serverType,
              category: serverType,
              tool_type: serverType,
            };
          });
          setData(normalizedServers);
        } else if (selectedType === "tools" && Array.isArray(json)) {
          // Normalize tools — backend returns both fully-deleted tools (tool_status: "deleted")
          // and version-deleted entries (tool_status: "active") in the same endpoint
          const normalizedTools = json.map(item => {
            const id = item.id || item.tool_id;
            const isValidator = item.is_validator === true || item.is_validator === "true" || (id && String(id).startsWith("_validator"));
            return {
              ...item,
              name: item.name || item.tool_name || "Unnamed Tool",
              tool_name: item.name || item.tool_name || "Unnamed Tool",
              description: item.description || item.tool_description || "",
              tool_description: item.description || item.tool_description || "",
              category: isValidator ? "validator" : "tool",
              tool_status: item.tool_status || "deleted",
            };
          });

          setData(normalizedTools);
        } else if (Array.isArray(json)) {
          setData(json);
        } else {
          // Handle case where response is not an array (empty or error response)
          setData([]);
        }
        setError(null);
      } catch (err) {
        // Treat only specific "not found" errors as empty data, not actual errors
        const errorMessage = err?.response?.data?.detail || err?.message || "";
        const isNotFoundError =
          err?.response?.status === 404 ||
          errorMessage === "No agents found" ||
          errorMessage === "No tools found" ||
          errorMessage === "No servers found" ||
          errorMessage.toLowerCase().includes("not found");

        if (isNotFoundError) {
          setData([]);
          setError(null);
        } else {
          setError(errorMessage || "Failed to fetch data");
          setData([]);
        }
      } finally {
        setLoader(false);
      }
    };
    fetchRecycleData();
  }, [selectedType, restoreData, fetchData]);

  // Filter data based on search term and agent type filter
  const filteredData = useMemo(() => {
    let result = data;

    // Apply agent type filter (only for agents)
    if (selectedType === "agents" && selectedAgentTypes && selectedAgentTypes.length > 0) {
      result = result.filter((item) => selectedAgentTypes.includes(item?.agentic_application_type));
    }

    // Apply tool type filter (only for tools)
    if (selectedType === "tools" && selectedToolTypes && selectedToolTypes.length > 0) {
      result = result.filter((item) => {
        const toolType = (item?.category || item?.tool_type || item?.type || "").toLowerCase();
        return selectedToolTypes.some((filterType) => filterType.toLowerCase() === toolType);
      });
    }

    // Apply server type filter (only for servers)
    if (selectedType === "servers" && selectedServerTypes && selectedServerTypes.length > 0) {
      result = result.filter((item) => {
        const serverType = (item?.type || item?.category || item?.tool_type || "").toLowerCase();
        return selectedServerTypes.some((filterType) => filterType.toLowerCase() === serverType);
      });
    }

    // Apply search term filter
    if (searchTerm.trim()) {
      const term = searchTerm.toLowerCase();
      result = result.filter((item) => {
        let name = "";
        if (selectedType === "agents") {
          name = item?.agentic_application_name || "";
        } else if (selectedType === "servers") {
          // Check both name and tool_name fields for servers
          name = item?.name || item?.tool_name || "";
        } else {
          name = item?.tool_name || "";
        }
        const createdBy = item?.created_by || "";
        return (name && name.toLowerCase().includes(term)) || (createdBy && createdBy.toLowerCase().includes(term));
      });
    }

    return result;
  }, [data, searchTerm, selectedType, selectedAgentTypes, selectedServerTypes, selectedToolTypes]);

  return (
    <>
      <>
        {!initialType && (
          <div className={styles.toggleWrapper}>
            <button
              type="button"
              className={`iafTabsBtn ${activeTab === "agents" ? " active" : ""}`}
              onClick={() => {
                setActiveTab("agents");
                setSelectedType("agents");
                setInternalSearchTerm("");
              }}>
              Agents
            </button>
            <button
              type="button"
              className={`iafTabsBtn ${activeTab === "tools" ? " active" : ""}`}
              onClick={() => {
                setActiveTab("tools");
                setSelectedType("tools");
                setInternalSearchTerm("");
              }}>
              Tools
            </button>
          </div>
        )}

        <SummaryLine visibleCount={filteredData.length} />
        <div className="listWrapper">
          {loader && <Loader />}
          {error && <p className={styles.error}>{error}</p>}
          {!loader && !error && selectedType === "agents" && (
            <>
              {filteredData.length === 0 && searchTerm.trim() ? (
                <EmptyState
                  filters={[`Search: ${searchTerm}`]}
                  onClearFilters={() => setInternalSearchTerm("")}
                  message="No deleted agents found"
                  showCreateButton={false}
                />
              ) : filteredData.length === 0 && !searchTerm.trim() ? (
                <EmptyState
                  message="No deleted agents found"
                  subMessage="Deleted agents will appear here"
                  showClearFilter={false}
                  showCreateButton={false}
                />
              ) : (
                <DisplayCard1
                  data={filteredData}
                  onCardClick={null}
                  onEditClick={(item) => {
                    setLastTab(activeTab);
                    setActiveTab("");
                    onAgentEdit(item);
                  }}
                  showDeleteButton={false}
                  isRecycleMode={true}
                  showCreateCard={false}
                  cardNameKey="agentic_application_name"
                  cardDescriptionKey="agentic_application_description"
                  cardOwnerKey="created_by"
                  cardCategoryKey="agentic_application_type"
                  emptyMessage="No Deleted Agents To Display"
                  contextType="agent"
                  footerButtonsConfig={[]}
                />
              )}
            </>
          )}
          {!loader && !error && selectedType === "tools" && (
            <>
              {filteredData.length === 0 && searchTerm.trim() ? (
                <EmptyState
                  filters={[`Search: ${searchTerm}`]}
                  onClearFilters={() => setInternalSearchTerm("")}
                  message="No deleted tools found"
                  showCreateButton={false}
                />
              ) : filteredData.length === 0 && !searchTerm.trim() ? (
                <EmptyState
                  message="No deleted tools found"
                  subMessage="Deleted tools will appear here"
                  showClearFilter={false}
                  showCreateButton={false}
                />
              ) : (
                <DisplayCard1
                  data={filteredData}
                  onCardClick={null}
                  onEditClick={(item) => {
                    setLastTab("tools");
                    setActiveTab("");
                    setEditTool(item);
                    setIsAddTool(false);
                    setShowForm(true);
                  }}
                  showDeleteButton={false}
                  isRecycleMode={true}
                  showCreateCard={false}
                  cardNameKey="tool_name"
                  cardDescriptionKey="tool_description"
                  cardOwnerKey="created_by"
                  cardCategoryKey="category"
                  emptyMessage="No Deleted Tools To Display"
                  contextType="tool"
                  footerButtonsConfig={[]}
                />
              )}
            </>
          )}
          {!loader && !error && selectedType === "servers" && (
            <>
              {filteredData.length === 0 && searchTerm.trim() ? (
                <EmptyState
                  filters={[`Search: ${searchTerm}`]}
                  onClearFilters={() => setInternalSearchTerm("")}
                  message="No deleted servers found"
                  showCreateButton={false}
                />
              ) : filteredData.length === 0 && !searchTerm.trim() ? (
                <EmptyState
                  message="No deleted servers found"
                  subMessage="Deleted servers will appear here"
                  showClearFilter={false}
                  showCreateButton={false}
                />
              ) : (
                <DisplayCard1
                  data={filteredData}
                  onCardClick={null}
                  onEditClick={(item) => {
                    setLastTab(activeTab);
                    setActiveTab("");
                    setSelectedServer(item);
                    setShowServerForm(true);
                  }}
                  showDeleteButton={false}
                  isRecycleMode={true}
                  showCreateCard={false}
                  cardNameKey="name"
                  cardDescriptionKey="description"
                  cardOwnerKey="created_by"
                  cardCategoryKey="type"
                  emptyMessage="No Deleted Servers To Display"
                  contextType="server"
                  footerButtonsConfig={[]}
                />
              )}
            </>
          )}
        </div>

        {editAgentData && (
          // <div className={styles.EditAgentContainer}>
          <UpdateAgent
            onClose={() => {
              setActiveTab(lastTab);
              handleUpdateAgentClose();
            }}
            agentData={editAgentData}
            setEditAgentData={setEditAgentData}
            tags={""}
            agentsListData={data?.filter((agent) => agent?.agentic_application_type === REACT_AGENT)}
            styles={styles}
            fetchAgents={""}
            searchTerm={""}
            selectedType={selectedType}
            recycleBin={true}
            setRestoreData={setRestoreData}
            RestoreAgent={RestoreAgent}
            deleteAgent={deleteAgent}
          />
          // </div>
        )}

        {showForm && editTool && (
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
          />
        )}
      </>

      {restoreConflict && ReactDOM.createPortal(
        <div className={styles.renameOverlay}
          onClick={() => { setRestoreConflict(null); setRestoreNewName(""); }}>
          <div className={styles.renameDialog} onClick={(e) => e.stopPropagation()}>
            <h3 className={styles.renameTitle}>Name Already In Use</h3>
            <p className={styles.renameMessage}>{restoreConflict.message}</p>
            {restoreConflict.conflicting_resource && (
              <p className={styles.renameConflictInfo}>
                Active {selectedType === "agents" ? "agent" : "item"}: <strong>{restoreConflict.conflicting_resource.agentic_application_name || restoreConflict.conflicting_resource.tool_name}</strong>
                {restoreConflict.conflicting_resource.created_by && <> &mdash; created by <strong>{restoreConflict.conflicting_resource.created_by}</strong></>}
              </p>
            )}
            <div className={styles.renameFieldGroup}>
              <label className="label-desc">New name</label>
              <input
                className="input"
                type="text"
                placeholder={restoreConflict.suggested_name || ""}
                value={restoreNewName}
                onChange={(e) => setRestoreNewName(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter" && restoreNewName.trim()) { setRestoreConflict(null); RestoreAgent(); } }}
                autoFocus
              />
            </div>
            <div className={styles.renameActions}>
              <IAFButton type="secondary" onClick={() => { setRestoreConflict(null); setRestoreNewName(""); }}>Cancel</IAFButton>
              <IAFButton type="primary" disabled={loader || !restoreNewName.trim()} onClick={() => { setRestoreConflict(null); RestoreAgent(); }}>Restore</IAFButton>
            </div>
          </div>
        </div>,
        document.body
      )}
    </>
  );
};

export default RecycleBin;
