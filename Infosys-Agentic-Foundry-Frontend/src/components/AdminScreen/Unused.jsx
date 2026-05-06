import React, { useState, useEffect, useMemo } from "react";
import { getRoleFromToken, getEmailFromToken } from "../../utils/jwtUtils";
import styles from "./Unused.module.css";
import style from "../../css_modules/AvailableAgents.module.css";
import { APIs } from "../../constant";
import DisplayCard1 from "../../iafComponents/GlobalComponents/DisplayCard/DisplayCard1.jsx";
import useFetch from "../../Hooks/useAxios.js";
import Loader from "../commonComponents/Loader.jsx";
import { useMessage } from "../../Hooks/MessageContext";
import SummaryLine from "../../iafComponents/GlobalComponents/SummaryLine.jsx";
import EmptyState from "../commonComponents/EmptyState.jsx";
import useMultiSelect from "../../Hooks/useMultiSelect";
import ConfirmationModal from "../commonComponents/ToastMessages/ConfirmationPopup";
import CheckBox from "../../iafComponents/GlobalComponents/CheckBox/CheckBox";
import IAFButton from "../../iafComponents/GlobalComponents/Buttons/Button";
import SVGIcons from "../../Icons/SVGIcons";
import subHeaderStyles from "../commonComponents/SubHeader.module.css";
import { getServerType } from "../../utils/serverUtils.js";
import { usePermissions } from "../../context/PermissionsContext.jsx";

const Unused = ({ initialType = "agents", heading, externalSearchTerm, selectedAgentTypes = [], selectedServerTypes = [], selectedToolTypes = [] }) => {
  const { hasPermission } = usePermissions();
  const canDeleteAgents = typeof hasPermission === "function" ? hasPermission("delete_access.agents") : false;
  const canDeleteServers = typeof hasPermission === "function" ? hasPermission("delete_access.mcp_servers") : false;
  const canDeleteTools = typeof hasPermission === "function" ? hasPermission("delete_access.tools") : false;

  const [selectedType, setSelectedType] = useState(initialType); // for data fetching
  const [activeTab, setActiveTab] = useState(initialType); // for tab highlight
  const [data, setData] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [internalSearchTerm, setInternalSearchTerm] = useState("");
  const [refreshCounter, setRefreshCounter] = useState(0); // Used to trigger re-fetch
  const [showBulkDeleteModal, setShowBulkDeleteModal] = useState(false);
  const [bulkDeleteLoading, setBulkDeleteLoading] = useState(false);

  // Use external search term if provided, otherwise use internal
  const searchTerm = externalSearchTerm !== undefined ? externalSearchTerm : internalSearchTerm;
  const { fetchData, deleteData } = useFetch();
  const { addMessage } = useMessage();

  const deleteItem = async (id, email, isAdmin) => {
    try {
      let endpoint, idKey;
      if (selectedType === "agents") {
        endpoint = APIs.DELETE_AGENTS;
        idKey = "agent_ids";
      } else if (selectedType === "tools" || selectedType === "servers") {
        endpoint = selectedType === "tools" ? APIs.DELETE_TOOLS : APIs.MCP_DELETE_TOOLS;
        idKey = "tool_ids";
      }
      const payload = {
        user_email_id: email,
        is_admin: isAdmin,
      };
      payload[idKey] = [id];
      const response = await deleteData(endpoint, payload);

      if (response && typeof response !== "string") {
        const statusMsg = response.status_message || response.message;
        const hasAnyFailure = Array.isArray(response.results) && response.results.some((r) => r.is_delete === false);
        if (statusMsg) {
          addMessage(statusMsg, hasAnyFailure ? "error" : "success");
        }
        if (!hasAnyFailure) setRefreshCounter((prev) => prev + 1);
        return !hasAnyFailure;
      } else {
        return false;
      }
    } catch (error) {
      return false;
    }
  };

  // Fetch data when selectedType or refreshCounter changes
  useEffect(() => {
    if (!selectedType) return;

    const fetchUnusedData = async () => {
      setLoading(true);
      setError(null);

      try {
        const userEmail = getEmailFromToken();
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
        if (!response || typeof response !== "object") {
          throw new Error("Invalid response received");
        }

        // Extract the data based on the type
        let itemsList = [];
        if (selectedType === "agents") {
          if (response.unused_agents?.details) {
            itemsList = response.unused_agents.details;
          } else if (response.details || response.agents) {
            itemsList = response.details || response.agents;
          }
        } else if (selectedType === "tools") {
          const normalizeToolData = (item) => {
            // Ensure we have a valid ID
            const id = item.id || item.tool_id;
            if (!id) {
              console.error("Tool missing ID:", item);
            }

            // Determine tool category (tool vs validator)
            const isValidator = item.is_validator === true || item.is_validator === "true" || (id && String(id).startsWith("_validator"));

            return {
              ...item,
              id: id,
              tool_id: id,
              name: item.name || item.tool_name || "Unnamed Tool",
              tool_name: item.name || item.tool_name || "Unnamed Tool",
              description: item.description || item.tool_description || "",
              tool_description: item.description || item.tool_description || "",
              created_by: item.created_by || "",
              created_on: item.created_on || "",
              last_used: item.last_used || "",
              category: isValidator ? "validator" : "tool",
            };
          };

          if (response.unused_tools?.details) {
            itemsList = response.unused_tools.details.map(normalizeToolData);
          } else if (response.details || response.tools) {
            itemsList = (response.details || response.tools).map(normalizeToolData);
          }
        } else if (selectedType === "servers") {
          const normalizeServerData = (item) => {
            const id = item.id || item.tool_id;
            const serverType = getServerType(item);
            return {
              ...item,
              id: id,
              tool_id: id,
              name: item.name || item.tool_name || "Unnamed Server",
              tool_name: item.name || item.tool_name || "Unnamed Server",
              description: item.description || item.tool_description || "",
              tool_description: item.description || item.tool_description || "",
              created_by: item.created_by || "",
              created_on: item.created_on || "",
              updated_on: item.updated_on || "",
              // Backend doesn't provide last_used for servers, use updated_on as fallback
              last_used: item.last_used || item.updated_on || "",
              mcp_type: item.mcp_type || "",
              mcp_config: item.mcp_config || {},
              type: serverType,
              category: serverType,
              tool_type: serverType,
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
          // Treat as empty data, not error
          itemsList = [];
        }

        setData(itemsList);
        setError(null);
      } catch (e) {
        // Treat only specific "not found" errors as empty data, not actual errors
        const errorMessage = e?.message || "";
        const isNotFoundError =
          e?.response?.status === 404 ||
          errorMessage === "No agents found" ||
          errorMessage === "No tools found" ||
          errorMessage === "No servers found" ||
          errorMessage.toLowerCase().includes("not found");

        if (isNotFoundError) {
          setData([]);
          setError(null);
        } else {
          setError(errorMessage || "Failed to fetch data");
          addMessage(errorMessage, "error");
        }
      } finally {
        setLoading(false);
      }
    };

    fetchUnusedData();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedType, refreshCounter]);

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
      const searchLower = searchTerm.toLowerCase();
      result = result.filter((item) => {
        const name = selectedType === "agents" ? item?.agentic_application_name || "" : selectedType === "servers" ? item?.name || "" : item?.tool_name || item?.name || "";
        const description = item?.description || item?.tool_description || "";
        const createdBy = item?.created_by || "";
        return name.toLowerCase().includes(searchLower) || description.toLowerCase().includes(searchLower) || createdBy.toLowerCase().includes(searchLower);
      });
    }

    return result;
  }, [data, searchTerm, selectedType, selectedAgentTypes, selectedServerTypes, selectedToolTypes]);

  const handleTabClick = (tabType) => {
    setSelectedType(tabType);
    setActiveTab(tabType);
    clearMultiSelection();
  };

  // Dynamic idKey based on selectedType
  const unusedIdKey = selectedType === "agents" ? "agentic_application_id" : selectedType === "servers" ? "id" : "tool_id";

  // Multi-select state
  const {
    selectedIds: multiSelectIds,
    selectedCount: multiSelectCount,
    isAllSelected,
    isPartiallySelected,
    handleSelectionChange: handleMultiSelectChange,
    handleSelectAll,
    clearSelection: clearMultiSelection,
  } = useMultiSelect({ data: filteredData, idKey: unusedIdKey });

  // Bulk delete handler — calls API directly to avoid per-item toasts from deleteItem
  const handleBulkDeleteUnused = async () => {
    if (multiSelectIds.length === 0) return;
    setBulkDeleteLoading(true);
    const email = getEmailFromToken();
    const isAdmin = getRoleFromToken().toLowerCase() === "admin";

    // Determine endpoint and idKey based on current tab type
    let endpoint, idKey;
    if (selectedType === "agents") {
      endpoint = APIs.DELETE_AGENTS;
      idKey = "agent_ids";
    } else if (selectedType === "tools" || selectedType === "servers") {
      endpoint = selectedType === "tools" ? APIs.DELETE_TOOLS : APIs.MCP_DELETE_TOOLS;
      idKey = "tool_ids";
    }

    const payload = {
      user_email_id: email,
      is_admin: isAdmin,
    };
    payload[idKey] = multiSelectIds;
    try {
      const response = await deleteData(endpoint, payload);
      if (response && typeof response !== "string") {
        const statusMsg = response.status_message || response.message;
        if (statusMsg) {
          const hasAnyFailure = Array.isArray(response.results) && response.results.some((r) => r.is_delete === false);
          addMessage(statusMsg, hasAnyFailure ? "error" : "success");
        }
      }
    } catch (error) {
      // silent catch
    }
    clearMultiSelection();
    setShowBulkDeleteModal(false);
    setBulkDeleteLoading(false);
    setRefreshCounter((prev) => prev + 1);
  };

  if (!style || !styles) {
    return <div>Loading styles...</div>;
  }

  return (
    <>
      {!initialType && (
        <div className={styles.toggleWrapper}>
          <button type="button" className={`iafTabsBtn ${activeTab === "agents" ? " active" : ""}`} onClick={() => handleTabClick("agents")}>
            Agents
          </button>
          <button type="button" className={`iafTabsBtn ${activeTab === "tools" ? " active" : ""}`} onClick={() => handleTabClick("tools")}>
            Tools
          </button>
          <button type="button" className={`iafTabsBtn ${activeTab === "servers" ? " active" : ""}`} onClick={() => handleTabClick("servers")}>
            Servers
          </button>
        </div>
      )}

      {/* Summary + Delete button row */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "0 4px" }}>
        <SummaryLine visibleCount={filteredData.length} />
        {multiSelectCount > 0 && (selectedType === "agents" ? canDeleteAgents : selectedType === "servers" ? canDeleteServers : canDeleteTools) && (
          <IAFButton
            type="primary"
            className={subHeaderStyles.deleteSelectedBtn}
            onClick={() => setShowBulkDeleteModal(true)}
            icon={<SVGIcons icon="trash" width={14} height={14} color="#fff" />}
          >
            Delete ({multiSelectCount})
          </IAFButton>
        )}
      </div>
      {/* Select All row - above cards */}
      {filteredData.length > 1 && (selectedType === "agents" ? canDeleteAgents : selectedType === "servers" ? canDeleteServers : canDeleteTools) && <div className={subHeaderStyles.selectAllRow}>
        <label className={subHeaderStyles.selectAllWrapper}>
          <CheckBox
            checked={isAllSelected}
            indeterminate={isPartiallySelected}
            onChange={handleSelectAll}
          />
          <span className={subHeaderStyles.selectAllLabel}>Select All</span>
        </label>
      </div>}
      <div className="listWrapper">
        {loading && <Loader />}
        {error && <div className={styles.error}>{error}</div>}

        {!loading && !error && (
          <div className={styles.visibleAgentsContainer}>
            {!filteredData || filteredData.length === 0 ? (
              searchTerm.trim() ? (
                <EmptyState
                  filters={[`Search: ${searchTerm}`]}
                  onClearFilters={() => setInternalSearchTerm("")}
                  message={selectedType === "agents" ? "No unused agents found" : selectedType === "servers" ? "No unused servers found" : "No unused tools found"}
                  showCreateButton={false}
                />
              ) : (
                <EmptyState
                  message={selectedType === "agents" ? "No unused agents found" : selectedType === "servers" ? "No unused servers found" : "No unused tools found"}
                  subMessage={
                    selectedType === "agents"
                      ? "Agents unused for more than 15 days will appear here"
                      : selectedType === "servers"
                        ? "Servers unused for more than 15 days will appear here"
                        : "Tools unused for more than 15 days will appear here"
                  }
                  showClearFilter={false}
                  showCreateButton={false}
                />
              )
            ) : (
              <>
                {selectedType === "agents" ? (
                  <DisplayCard1
                    data={filteredData.filter((agent) => agent && typeof agent === "object")}
                    showDeleteButton={canDeleteAgents}
                    isUnusedSection={true}
                    showCheckbox={canDeleteAgents}
                    onSelectionChange={handleMultiSelectChange}
                    selectedIds={multiSelectIds}
                    idKey="agentic_application_id"
                    onDeleteClick={(name, item) => {
                      const id = item?.agentic_application_id;
                      const email = getEmailFromToken();
                      const isAdmin = getRoleFromToken().toLowerCase() === "admin";
                      if (id) deleteItem(id, email, isAdmin);
                    }}
                    cardNameKey="agentic_application_name"
                    cardOwnerKey="created_by"
                    cardCategoryKey="agentic_application_type"
                    emptyMessage="No unused agents found"
                    showCreateCard={false}
                    contextType="agent"
                  />
                ) : selectedType === "servers" ? (
                  <DisplayCard1
                    data={filteredData.filter((item) => item && typeof item === "object")}
                    showDeleteButton={canDeleteServers}
                    isUnusedSection={true}
                    showCheckbox={canDeleteServers}
                    onSelectionChange={handleMultiSelectChange}
                    selectedIds={multiSelectIds}
                    idKey="id"
                    onDeleteClick={(name, item) => {
                      const id = item?.id || item?.server_id;
                      const email = getEmailFromToken();
                      const isAdmin = getRoleFromToken().toLowerCase() === "admin";
                      if (id) deleteItem(id, email, isAdmin);
                    }}
                    cardNameKey="name"
                    cardOwnerKey="created_by"
                    cardCategoryKey="type"
                    emptyMessage="No unused servers found"
                    showCreateCard={false}
                    contextType="server"
                  />
                ) : (
                  <DisplayCard1
                    data={filteredData.filter((item) => item && typeof item === "object")}
                    showDeleteButton={canDeleteTools}
                    isUnusedSection={true}
                    showCheckbox={canDeleteTools}
                    onSelectionChange={handleMultiSelectChange}
                    selectedIds={multiSelectIds}
                    idKey="tool_id"
                    onDeleteClick={(name, item) => {
                      const id = item?.tool_id || item?.id;
                      const email = getEmailFromToken();
                      const isAdmin = getRoleFromToken().toLowerCase() === "admin";
                      if (id) deleteItem(id, email, isAdmin);
                    }}
                    cardNameKey="tool_name"
                    cardOwnerKey="created_by"
                    cardCategoryKey="category"
                    emptyMessage="No unused tools found"
                    showCreateCard={false}
                    contextType="tool"
                  />
                )}
              </>
            )}
          </div>
        )}
      </div>

      {showBulkDeleteModal && (
        <ConfirmationModal
          message={`Are you sure you want to delete ${multiSelectCount} selected ${selectedType === "agents" ? "agent" : selectedType === "servers" ? "server" : "tool"}(s)? This action cannot be undone.`}
          onConfirm={handleBulkDeleteUnused}
          setShowConfirmation={setShowBulkDeleteModal}
        />
      )}
    </>
  );
};

export default Unused;
