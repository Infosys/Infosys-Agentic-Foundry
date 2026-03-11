import React, { useState, useEffect, useMemo } from "react";
import styles from "./RecycleBin.module.css";
import Cookies from "js-cookie";
import DisplayCard1 from "../../iafComponents/GlobalComponents/DisplayCard/DisplayCard1.jsx";
import { APIs, REACT_AGENT } from "../../constant";
import UpdateAgent from "../AvailableAgents/UpdateAgent.jsx";
import ToolOnBoarding from "../AvailableTools/ToolOnBoarding.jsx";
import AddServer from "../AgentOnboard/AddServer.jsx";
import useFetch from "../../Hooks/useAxios.js";
import Loader from "../commonComponents/Loader.jsx";
import { useMessage } from "../../Hooks/MessageContext";
import SummaryLine from "../../iafComponents/GlobalComponents/SummaryLine.jsx";
import EmptyState from "../commonComponents/EmptyState.jsx";
import { getServerType } from "../../utils/serverUtils.js";

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
    } else if (selectedType === "tools") {
      url = `${APIs.RESTORE_TOOLS}${editAgentData?.tool_id}?user_email_id=${encodeURIComponent(Cookies?.get("email"))}`;
    } else if (selectedType === "servers") {
      const serverId = editAgentData?.tool_id || editAgentData?.id;
      url = `${APIs.RESTORE_SERVERS}${serverId}?user_email_id=${encodeURIComponent(Cookies?.get("email"))}`;
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
      const serverId = editAgentData?.tool_id || editAgentData?.id;
      url = `${APIs.DELETE_SERVERS_PERMANENTLY}${serverId}?user_email_id=${encodeURIComponent(Cookies?.get("email"))}`;
    }
    const response = await deleteData(url);
    if (response?.is_delete || response?.is_deleted) {
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
          url = `${APIs.SERVERS_RECYCLE_BIN}?user_email_id=${encodeURIComponent(Cookies?.get("email"))}`;
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
          // Normalize tool data to include category for filtering
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
    </>
  );
};

export default RecycleBin;
