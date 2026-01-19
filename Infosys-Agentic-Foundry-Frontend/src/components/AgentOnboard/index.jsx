import React, { useEffect, useState, useCallback, useRef } from "react";
import SVGIcons from "../../Icons/SVGIcons";
import styles from "../../css_modules/AgentOnboard.module.css";
import ToolCard from "./ToolCard";
import AgentForm from "./AgentForm";
import useFetch from "../../Hooks/useAxios";
import Loader from "../commonComponents/Loader";
import DropDown from "../commonComponents/DropDowns/DropDown";
import { agentTypesDropdown, MULTI_AGENT, REACT_AGENT, META_AGENT, PLANNER_META_AGENT, HYBRID_AGENT, APIs, PLANNER_EXECUTOR_AGENT, REACT_CRITIC_AGENT, PIPELINE_AGENT } from "../../constant";
import { useMessage } from "../../Hooks/MessageContext";
import { useToolsAgentsService } from "../../services/toolService";
import SearchInputToolsAgents from "../commonComponents/SearchInputTools";
import { debounce } from "lodash";
import { useMcpServerService } from "../../services/serverService";
import FilterModal from "../commonComponents/FilterModal";
import { useErrorHandler } from "../../Hooks/useErrorHandler";
import { usePermissions } from "../../context/PermissionsContext";
// Note: Centralized error handling integrated (handleError) replacing scattered console.error occurrences

const AgentOnboard = (props) => {
  const { onClose, tags, setNewAgentData, fetchAgents } = props;

  const [selectedTool, setSelectedTool] = useState([]);
  const [selectedAgents, setSelectedAgents] = useState([]);
  const [selectedAgent, setSelectedAgent] = useState("react_agent");
  const [visibleData, setVisibleData] = useState([]);
  const [searchTerm, setSearchTerm] = useState("");
  const [loading, setLoading] = useState(false);
  const [totalCount, setTotalCount] = useState(0);
  const [loader, setLoaderState] = useState(false);
  const isLoadingRef = React.useRef(false);
  const [activeTab, setActiveTab] = useState("tools");
  const [servers, setServers] = useState([]);
  const [selectedServers, setSelectedServers] = useState([]);
  const [unmappedServers, setUnmappedServers] = useState([]);
  // Tag filtering state
  const [selectedTags, setSelectedTags] = useState([]);
  const [selectedServerTags, setSelectedServerTags] = useState([]);
  const [filterModal, setFilterModal] = useState(false);

  const { addMessage } = useMessage();
  const { postData, fetchData } = useFetch();
  const { getToolsSearchByPageLimit, getAgentsSearchByPageLimit, calculateDivs,getValidatorTools } = useToolsAgentsService();
  const { getServersSearchByPageLimit } = useMcpServerService();

  const containerRef = useRef(null);
  const pageRef = useRef(1);
  const hasLoadedOnce = useRef(false);

  const { handleError } = useErrorHandler();
  const { hasPermission, permissions } = usePermissions();
  const filteredAgentTypesDropdown = agentTypesDropdown.filter(type => type.value !== PIPELINE_AGENT);

  const fetchPaginatedData = useCallback(
    async (pageNumber, divsCount, tagParams = null) => {
      setLoading(true);
      try {
        const tagsToUse = tagParams !== null ? tagParams : selectedTags;
        if (selectedAgent === META_AGENT || selectedAgent === PLANNER_META_AGENT) {
          const response = await getAgentsSearchByPageLimit({ page: pageNumber, limit: divsCount, search: searchTerm, tags: tagsToUse });
          const allDetails = typeof response?.details === "object" && Array.isArray(response.details) ? response.details : [];
          const filtered = allDetails.filter((agent) => agent.agentic_application_type === REACT_AGENT || agent.agentic_application_type === MULTI_AGENT || agent.agentic_application_type === REACT_CRITIC_AGENT || agent.agentic_application_type === PLANNER_EXECUTOR_AGENT);
          setVisibleData((prev) => (pageNumber === 1 ? filtered : [...prev, ...filtered]));
          setTotalCount(response?.total_count || allDetails?.length || 0);
        } else {
          const response = await getToolsSearchByPageLimit({ page: pageNumber, limit: divsCount, search: searchTerm, tags: tagsToUse });
          const toolsData = typeof response?.details === "object" && Array.isArray(response.details) ? response.details : [];
          setVisibleData((prev) => (pageNumber === 1 ? toolsData : [...prev, ...toolsData]));
          setTotalCount(response?.total_count || toolsData?.length || 0);
        }
      } catch (e) {
        handleError(e, { customMessage: "Failed to fetch list" });
      } finally {
        setLoading(false);
      }
    },
    [searchTerm, selectedAgent, selectedTags]
  );

  // Helper to map server data for ToolCard (include raw + derived LOCAL/REMOTE)
  const mapServerData = (server) => {
    const raw = server || {};
    const hasCode = Boolean(raw?.mcp_config?.args?.[1] || raw?.mcp_file?.code_content || raw?.code_content || raw?.code || raw?.script || raw?.code_snippet);
    const hasUrl = Boolean(raw?.mcp_config?.url || raw?.mcp_url || raw?.endpoint || raw?.mcp_config?.mcp_url || raw?.mcp_config?.endpoint);
    const derivedType = hasCode ? "LOCAL" : hasUrl ? "REMOTE" : String(raw.mcp_type || raw.type || "").toUpperCase() || "UNKNOWN";
    return {
      tool_id: raw.tool_id || raw.id || raw._id || crypto.randomUUID(), // Always unique!
      name: raw.tool_name || raw.name,
      status: raw.status || "approved",
      type: derivedType,
      team_id: raw.team_id || "Public",
      description: raw.tool_description || raw.description,
      tags: Array.isArray(raw.tag_ids)
        ? raw.tag_ids.map((t) => (typeof t === "object" ? t.tag_name : t))
        : Array.isArray(raw.tags)
        ? raw.tags.map((t) => (typeof t === "object" ? t.tag_name : t))
        : [],
      endpoint: raw.mcp_url || raw.endpoint || "",
      tools: raw.tools || [],
      raw, // preserve full object for code snippet extraction
    };
  };

  useEffect(() => {
    if (activeTab === "servers") {
      setLoading(true);
      Promise.all([
        selectedServerTags?.length > 0
          ? getServersSearchByPageLimit({
              page: 1,
              limit: calculateDivs(containerRef, 149, 57, 26),
              search: searchTerm,
              tags: selectedServerTags,
            })
          : getServersSearchByPageLimit({
              page: 1,
              limit: calculateDivs(containerRef, 149, 57, 26),
              search: searchTerm,
              tags: selectedServerTags,
            }),
        ,
        fetchData(APIs.GET_AGENTS_BY_DETAILS),
      ])
        .then(([serverResponse, allAgents]) => {
          // Handle server response format - check for details property or use response directly
          const allServers = serverResponse?.details || serverResponse || [];

          // Collect all mapped server IDs from all agents
          const mappedServerIds = new Set();
          (allAgents || []).forEach((agent) => {
            if (Array.isArray(agent.tools_id)) {
              agent.tools_id.forEach((id) => mappedServerIds.add(id));
            } else if (typeof agent.tools_id === "string") {
              try {
                JSON.parse(agent.tools_id).forEach((id) => mappedServerIds.add(id));
              } catch {}
            }
          });
          // Only show servers not mapped to any agent
          const unmapped = (Array.isArray(allServers) ? allServers : []).filter((s) => !mappedServerIds.has(s.tool_id || s.id));
          setUnmappedServers(unmapped.map(mapServerData));
          setServers(unmapped.map(mapServerData)); // Use unmapped for display
          setLoading(false);
        })
        .catch((e) => {
          setServers([]);
          setUnmappedServers([]);
          setLoading(false);
          handleError(e, { customMessage: "Failed to load servers" });
        });
    }
  }, [activeTab, selectedServerTags, searchTerm]);

  useEffect(() => {
    if (!hasLoadedOnce.current && activeTab === "tools") {
      hasLoadedOnce.current = true;
      const divsCount = calculateDivs(containerRef, 149, 57, 26);
      pageRef.current = 1;
      setVisibleData([]);
      fetchPaginatedData(1, divsCount);
    }
  }, [selectedAgent, activeTab, fetchPaginatedData]);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    // Extract the check logic into a separate function
    const checkAndLoadMore = () => {
      if (
        container.scrollTop + container.clientHeight >= container.scrollHeight - 40 &&
        !loading &&
        !isLoadingRef.current // Prevent if already loading
      ) {
        handleScrollLoadMore();
      }
    };

    const debouncedCheckAndLoad = debounce(checkAndLoadMore, 200); // 200ms debounce

    const handleResize = () => {
      debouncedCheckAndLoad();
    };

    window.addEventListener("resize", handleResize);
    container.addEventListener("scroll", debouncedCheckAndLoad);

    return () => {
      window.removeEventListener("resize", handleResize);
      debouncedCheckAndLoad.cancel && debouncedCheckAndLoad.cancel();
      container.removeEventListener("scroll", debouncedCheckAndLoad);
    };
  }, [visibleData.length, totalCount, searchTerm]); // handleScrollLoadMore, loading  - also might be included in the dependency

  const handleScrollLoadMore = async () => {
    if (loader || isLoadingRef.current) return; // Prevent multiple calls
    isLoadingRef.current = true;
    const nextPage = pageRef.current + 1;
    const divsCount = calculateDivs(containerRef, 149, 57, 26);

    try {
      setLoaderState(true);
      setLoading && setLoading(true);
      let newData = [];
      if (searchTerm.trim()) {
        // Only call search API if searchTerm is present
        if (selectedAgent === META_AGENT || selectedAgent === PLANNER_META_AGENT) {
          const res = await getAgentsSearchByPageLimit({
            page: nextPage,
            limit: divsCount,
            search: searchTerm,
            tags: selectedTags,
          });
          newData = (res?.details || []).filter((a) => a.agentic_application_type === REACT_AGENT || a.agentic_application_type === MULTI_AGENT || a.agentic_application_type === REACT_CRITIC_AGENT || a.agentic_application_type === PLANNER_EXECUTOR_AGENT);
        } else {
          const res = await getToolsSearchByPageLimit({
            page: nextPage,
            limit: divsCount,
            search: searchTerm,
            tags: selectedTags,
          });
          newData = res?.details || [];
        }
        if (typeof newData === "object" && Array.isArray(newData)) {
          setVisibleData((prev) => [...prev, ...newData]);
          pageRef.current = nextPage;
        }
      } else {
        // Only call fetchToolsData if no searchTerm
        await fetchPaginatedData(nextPage, divsCount);
        pageRef.current = nextPage;
      }
    } catch (err) {
      handleError(err, { customMessage: "Load more failed" });
    } finally {
      setLoaderState(false);
      setLoading && setLoading(false);
      isLoadingRef.current = false;
    }
  };

  const clearSearch = async () => {
    setSearchTerm("");
    setVisibleData([]);
    pageRef.current = 1;
    if (activeTab === "servers") {
      setLoading(true);
      try {
        // Fetch all agents to get mapped server IDs
        const allAgents = await fetchData(APIs.GET_AGENTS_BY_DETAILS);
        const mappedServerIds = new Set();
        (allAgents || []).forEach((agent) => {
          if (Array.isArray(agent.tools_id)) {
            agent.tools_id.forEach((id) => mappedServerIds.add(id));
          } else if (typeof agent.tools_id === "string") {
            try {
              JSON.parse(agent.tools_id).forEach((id) => mappedServerIds.add(id));
            } catch {}
          }
        });

        // Use filtered or unfiltered servers based on selected tags
        let serverResponse;
        if (selectedServerTags?.length > 0) {
          serverResponse = await getServersSearchByPageLimit({
            page: 1,
            limit: calculateDivs(containerRef, 149, 57, 26),
            search: "",
            tags: selectedServerTags,
          });
        } else {
          serverResponse = await getServersSearchByPageLimit({
            page: 1,
            limit: calculateDivs(containerRef, 149, 57, 26),
            search: searchTerm,
            tags: selectedServerTags,
          });
        }

        const allServers = serverResponse?.details || serverResponse || [];
        const unmapped = (Array.isArray(allServers) ? allServers : []).filter((s) => !mappedServerIds.has(s.tool_id || s.id));
        setUnmappedServers(unmapped.map(mapServerData));
        setServers(unmapped.map(mapServerData));
      } catch (err) {
        setUnmappedServers([]);
        setServers([]);
        handleError(err, { customMessage: "Failed to clear search" });
      } finally {
        setLoading(false);
      }
      return;
    }
    if (activeTab === "tools") {
      setLoading(true);
      try {
        let data = [];
        const divsCount = calculateDivs(containerRef, 149, 57, 26);

        if (selectedAgent === META_AGENT || selectedAgent === PLANNER_META_AGENT) {
          const response = await getAgentsSearchByPageLimit({
            page: 1,
            limit: divsCount,
            search: "",
            tags: selectedTags,
          });
          data = response?.details || [];
          data = data.filter((a) => a.agentic_application_type === REACT_AGENT || a.agentic_application_type === MULTI_AGENT || a.agentic_application_type === REACT_CRITIC_AGENT || a.agentic_application_type === PLANNER_EXECUTOR_AGENT);
        } else {
          const response = await getToolsSearchByPageLimit({
            page: 1,
            limit: divsCount,
            search: "",
            tags: selectedTags,
          });
          data = typeof response?.details === "object" && Array.isArray(response?.details) ? response?.details : [];
        }
        setVisibleData(data);
        setTotalCount(data.length);
      } catch (err) {
        setVisibleData([]);
        setTotalCount(0);
        handleError(err, { customMessage: "Failed to reset list" });
      } finally {
        setLoading(false);
      }
      return;
    }
    // ...existing code for agents clear...
    const divsCount = calculateDivs(containerRef, 149, 57, 26);
    fetchPaginatedData(1, divsCount);
  };

  const handleSearch = async (searchValue) => {
    setSearchTerm(searchValue);
    setVisibleData([]);
    pageRef.current = 1;
    if (activeTab === "servers") {
      setLoading(true);
      try {
        const divsCount = calculateDivs(containerRef, 149, 57, 26);
        // Fetch all agents to get mapped server IDs
        const allAgents = await fetchData(APIs.GET_AGENTS_BY_DETAILS);
        const mappedServerIds = new Set();
        (allAgents || []).forEach((agent) => {
          if (Array.isArray(agent.tools_id)) {
            agent.tools_id.forEach((id) => mappedServerIds.add(id));
          } else if (typeof agent.tools_id === "string") {
            try {
              JSON.parse(agent.tools_id).forEach((id) => mappedServerIds.add(id));
            } catch {}
          }
        });
        // Call backend search for servers with tags
        const response = await getServersSearchByPageLimit({
          page: 1,
          limit: divsCount,
          search: searchValue,
          tags: selectedServerTags?.length > 0 ? selectedServerTags : undefined,
        });
        let data = response?.details || response || [];
        if (!Array.isArray(data)) data = [];
        // Only show unmapped servers
        const unmapped = data.filter((s) => !mappedServerIds.has(s.tool_id || s.id));
        setUnmappedServers(unmapped.map(mapServerData));
        setServers(unmapped.map(mapServerData));
      } catch (err) {
        setUnmappedServers([]);
        setServers([]);
        handleError(err, { customMessage: "Server search failed" });
      } finally {
        setLoading(false);
      }
      return;
    }
    // ...existing code for tools/agents search...
    if (searchValue.trim()) {
      try {
        setLoading(true);
        let data = [];
        const divsCount = calculateDivs(containerRef, 149, 57, 26);
        if (selectedAgent === META_AGENT || selectedAgent === PLANNER_META_AGENT) {
          const response = await getAgentsSearchByPageLimit({
            page: 1,
            limit: divsCount,
            search: searchValue,
            tags: selectedTags,
          });
          data = response?.details || [];
          data = data.filter((a) => a.agentic_application_type === REACT_AGENT || a.agentic_application_type === MULTI_AGENT || a.agentic_application_type === REACT_CRITIC_AGENT || a.agentic_application_type === PLANNER_EXECUTOR_AGENT);
        } else {
          const response = await getToolsSearchByPageLimit({
            page: 1,
            limit: divsCount,
            search: searchValue,
            tags: selectedTags,
          });
          data = typeof response?.details === "object" && Array.isArray(response?.details) ? response?.details : [];
        }
        setVisibleData(data);
        setTotalCount(data.length);
      } catch (err) {
        setVisibleData([]);
        handleError(err, { customMessage: "Search failed" });
      } finally {
        setLoading(false);
      }
    } else {
      const divsCount = calculateDivs(containerRef, 149, 57, 26);
      setVisibleData([]);
      pageRef.current = 1;
      fetchPaginatedData(1, divsCount);
    }
  };

  const handleTabSwitch = (tab) => {
    // Block switching to servers for meta agent types
    if ((selectedAgent === META_AGENT || selectedAgent === PLANNER_META_AGENT) && tab === "servers") return;
    setActiveTab(tab);
    setVisibleData([]);
    setSearchTerm("");
    pageRef.current = 1;
    hasLoadedOnce.current = false;
    if (tab === "tools") {
      // Clear server tag filters when switching to tools tab
      setSelectedServerTags([]);
      clearSearch();
      fetchPaginatedData(1, calculateDivs(containerRef, 149, 57, 26));
    } else if (tab === "servers") {
      // Clear tool tag filters when switching to servers tab
      setSelectedServerTags([]);
      setSelectedTags([]);
      clearSearch();
      // Fetch servers if needed
    }
  };

  // Ensure activeTab is tools when switching to a meta agent type
  useEffect(() => {
    if ((selectedAgent === META_AGENT || selectedAgent === PLANNER_META_AGENT) && activeTab === "servers") {
      setActiveTab("tools");
    }
  }, [selectedAgent, activeTab]);

  // Tag filtering functions
  const getToolsDataWithTags = useCallback(
    (tagsToApply) => {
      setVisibleData([]);
      pageRef.current = 1;
      const divsCount = calculateDivs(containerRef, 149, 57, 26);
      fetchPaginatedData(1, divsCount, tagsToApply);
    },
    [fetchPaginatedData]
  );

  const getAgentsDataWithTags = useCallback(
    (tagsToApply) => {
      setVisibleData([]);
      pageRef.current = 1;
      const divsCount = calculateDivs(containerRef, 149, 57, 26);
      fetchPaginatedData(1, divsCount, tagsToApply);
    },
    [fetchPaginatedData]
  );

  const handleFilter = useCallback(
    (newSelectedTags) => {
      setSelectedTags(newSelectedTags);

      if (selectedAgent === META_AGENT || selectedAgent === PLANNER_META_AGENT) {
        getAgentsDataWithTags(newSelectedTags);
      } else {
        getToolsDataWithTags(newSelectedTags);
      }
    },
    [selectedAgent, getAgentsDataWithTags, getToolsDataWithTags]
  );

  const getServersDataWithTags = useCallback(
    async (tagsToApply) => {
      setLoading(true);
      try {
        const divsCount = calculateDivs(containerRef, 149, 57, 26);
        // Fetch all agents to get mapped server IDs
        const allAgents = await fetchData(APIs.GET_AGENTS_BY_DETAILS);
        const mappedServerIds = new Set();
        (allAgents || []).forEach((agent) => {
          if (Array.isArray(agent.tools_id)) {
            agent.tools_id.forEach((id) => mappedServerIds.add(id));
          } else if (typeof agent.tools_id === "string") {
            try {
              JSON.parse(agent.tools_id).forEach((id) => mappedServerIds.add(id));
            } catch {}
          }
        });

        // Call backend search for servers with tags
        const response = await getServersSearchByPageLimit({
          page: 1,
          limit: divsCount,
          search: searchTerm,
          tags: tagsToApply?.length > 0 ? tagsToApply : undefined,
        });
        let data = response?.details || response || [];
        if (!Array.isArray(data)) data = [];

        // Only show unmapped servers
        const unmapped = data.filter((s) => !mappedServerIds.has(s.tool_id || s.id));
        setUnmappedServers(unmapped.map(mapServerData));
        setServers(unmapped.map(mapServerData));
      } catch (err) {
        console.error(err);
        setUnmappedServers([]);
        setServers([]);
      } finally {
        setLoading(false);
      }
    },
    [searchTerm, fetchData, getServersSearchByPageLimit, mapServerData, calculateDivs]
  );

  const handleServerFilter = useCallback(
    (newSelectedServerTags) => {
      setSelectedServerTags(newSelectedServerTags);
      getServersDataWithTags(newSelectedServerTags);
    },
    [getServersDataWithTags]
  );

  const submitForm = async (value, callBack) => {
    // Frontend defensive permission check: ensure user can add agents
    const canAddAgents = typeof hasPermission === "function" ? hasPermission("add_access.agents") : !(permissions && permissions.add_access && permissions.add_access.agents === false);
    if (!canAddAgents) {
      // show a friendly message and abort
      try {
        addMessage("You do not have permission to add agents.", "error");
      } catch (e) {}
      return;
    }
    setLoading(true);
    const payload = { ...value };
    // Fix: Always send both selected tool and server IDs in payload.tools_id
    const toolIds =
      selectedAgent === META_AGENT || selectedAgent === PLANNER_META_AGENT
        ? selectedAgents?.map((agent) => agent?.agentic_application_id)
        : selectedTool?.map((tool) => tool?.tool_id);
    const serverIds = selectedServers?.map((server) => server.tool_id);
    payload.tools_id = [...(toolIds || []), ...(serverIds || [])];

    try {
      const url = APIs.ONBOARD_AGENTS;
      const response = await postData(url, payload);
      if (response?.result?.is_created) {
        setNewAgentData(response.result);
        addMessage("Agent has been added successfully!", "success");
        setSelectedTool([]);
        setSelectedAgents([]);
        setSelectedServers([]);
        await fetchAgents();
        callBack(response);
      } else {
        addMessage(response?.result?.message || "Unknown error", "error");
      }
    } catch (e) {
      handleError(e, { showToast: false }); // Added showToast so it shows default error message from response . Previously had '{ customMessage: "Submit failed" }' as option
    } finally {
      setLoading(false);
    }
  };

  const handleClose = () => {
    onClose();
  };

  return (
    <div className={styles.container}>
      <div className={styles.header}>
        <h6>ONBOARD AGENT</h6>
        <button onClick={handleClose}>
          <SVGIcons icon="close-icon" color="#7F7F7F" width={28} height={28} />
        </button>
      </div>
      <div className={styles.dashboardContainer}>
        <div className={styles.agentToolsContainer} ref={containerRef}>
          {/* Agent Type moved to top above tabs */}
          <div className={styles.selectContainer} style={{ marginBottom: "14px" }}>
            <label htmlFor="agent_type_select">Agent Type</label>
            <DropDown
              id="agent_type_select"
              options={filteredAgentTypesDropdown}
              value={selectedAgent}
              onChange={(e) => {
                hasLoadedOnce.current = false;
                const newType = e?.target?.value;
                setSelectedAgent(newType);
                // Reset selections & listing when agent type changes
                setSelectedTool([]);
                setSelectedAgents([]);
                setSelectedServers([]);
                setVisibleData([]);
                pageRef.current = 1;
                if ((newType === META_AGENT || newType === PLANNER_META_AGENT || newType === HYBRID_AGENT) && activeTab === "servers") {
                  setActiveTab("tools");
                }
              }}
            />
          </div>
          <div className={styles.tabRow} style={{ display: "flex", marginBottom: "18px", alignItems: "center" }}>
            <button
              className={`iafTabsBtn ${activeTab === "tools" ? " active" : ""}`}
              onClick={() => handleTabSwitch("tools")}
              aria-label={selectedAgent === META_AGENT || selectedAgent === PLANNER_META_AGENT ? "Agents" : "Tools"}
              type="button"
              style={{
                marginRight: selectedAgent === META_AGENT || selectedAgent === PLANNER_META_AGENT ? 0 : "0",
                boxShadow: activeTab === "tools" ? "0 2px 8px rgba(16,24,40,0.08)" : "none",
              }}>
              {selectedAgent === META_AGENT || selectedAgent === PLANNER_META_AGENT ? "AGENTS" : "TOOLS"}
            </button>
            {/* Enable Servers tab for HYBRID_AGENT and non-meta agents */}
            {selectedAgent !== META_AGENT && selectedAgent !== PLANNER_META_AGENT && (
              <button
                className={`iafTabsBtn ${activeTab === "servers" ? " active" : ""}`}
                onClick={() => handleTabSwitch("servers")}
                aria-label="Servers list"
                type="button"
                style={{
                  boxShadow: activeTab === "servers" ? "0 2px 8px rgba(16,24,40,0.08)" : "none",
                }}>
                SERVERS
              </button>
            )}
          </div>
          <div className={styles.subHeader}>
            {/* <p>{`SELECT ${activeTab === "servers" ? "SERVER" : selectedAgent === META_AGENT || selectedAgent === PLANNER_META_AGENT ? "AGENT" : "TOOL"} TO ADD AGENT`}</p> */}
            <SearchInputToolsAgents
              inputProps={{
                placeholder: activeTab === "servers" ? "Search Servers" : selectedAgent === META_AGENT || selectedAgent === PLANNER_META_AGENT ? "Search Agents" : "Search Tools",
              }}
              handleSearch={handleSearch}
              clearSearch={clearSearch}
            />
            {activeTab === "tools" && (
              <button
                type="button"
                onClick={() => setFilterModal(true)}
                title={`Filter ${selectedAgent === META_AGENT || selectedAgent === PLANNER_META_AGENT ? "agents" : "tools"} by tags`}
                style={{
                  width: "40px",
                  height: "30px",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  cursor: "pointer",
                  backgroundColor: selectedTags.length > 0 ? "#007acc" : "transparent",
                  border: "none",
                  borderRadius: "4px",
                  marginLeft: "10px",
                  position: "relative",
                }}
                aria-label="Open filter modal">
                {selectedTags?.length > 0 && (
                  <span
                    style={{
                      position: "absolute",
                      top: "-5px",
                      right: "-5px",
                      backgroundColor: "#007cc3",
                      color: "white",
                      fontSize: "10px",
                      borderRadius: "50%",
                      width: "16px",
                      height: "16px",
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                    }}>
                    {selectedTags.length}
                  </span>
                )}
                <SVGIcons icon="slider-rect" width={20} height={18} fill="#C3C1CF" />
              </button>
            )}
            {activeTab === "servers" && (
              <button
                type="button"
                onClick={() => setFilterModal(true)}
                title="Filter servers by tags"
                style={{
                  width: "40px",
                  height: "30px",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  cursor: "pointer",
                  backgroundColor: selectedServerTags.length > 0 ? "#007acc" : "transparent",
                  border: "none",
                  borderRadius: "4px",
                  marginLeft: "10px",
                  position: "relative",
                }}
                aria-label="Open server filter modal">
                {selectedServerTags?.length > 0 && (
                  <span
                    style={{
                      position: "absolute",
                      top: "-5px",
                      right: "-5px",
                      backgroundColor: "#007cc3",
                      color: "white",
                      fontSize: "10px",
                      borderRadius: "50%",
                      width: "16px",
                      height: "16px",
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                    }}>
                    {selectedServerTags.length}
                  </span>
                )}
                <SVGIcons icon="slider-rect" width={20} height={18} fill="#C3C1CF" />
              </button>
            )}
          </div>
          <div className={styles.toolsCards}>
            {activeTab === "tools" &&
              selectedAgent !== META_AGENT &&
              selectedAgent !== PLANNER_META_AGENT &&
              visibleData?.map((tool) => (
                <ToolCard
                  key={tool?.tool_id}
                  tool={tool}
                  tool_id={tool?.tool_id}
                  styles={styles}
                  setSelectedTool={setSelectedTool}
                  selectedTool={selectedTool}
                  selectedAgents={selectedAgents}
                />
              ))}
            {activeTab === "tools" &&
              (selectedAgent === META_AGENT || selectedAgent === PLANNER_META_AGENT) &&
              visibleData?.map((agent) => (
                <ToolCard
                  key={agent?.agentic_application_id}
                  agent={agent}
                  agent_id={agent?.agentic_application_id}
                  styles={styles}
                  setSelectedAgents={setSelectedAgents}
                  selectedTool={selectedTool}
                  selectedAgents={selectedAgents}
                />
              ))}
            {activeTab === "servers" &&
              unmappedServers?.map((server) => (
                <ToolCard
                  key={server.tool_id}
                  server={server}
                  tool_id={server.tool_id} // Pass unique tool_id
                  styles={styles}
                  setSelectedServers={setSelectedServers}
                  selectedServers={selectedServers}
                />
              ))}
          </div>
        </div>
        <div className={styles.agentDetailContainer}>
          <AgentForm
            styles={styles}
            handleClose={handleClose}
            submitForm={submitForm}
            isMetaAgent={selectedAgent === META_AGENT || selectedAgent === PLANNER_META_AGENT}
            selectedAgent={selectedAgent}
            loading={loading}
            tags={tags}
            setSelectedAgents={setSelectedAgents}
            setSelectedTool={setSelectedTool}
            setSelectedServers={setSelectedServers}
          />
        </div>
      </div>
      {loading && <Loader />}
      {filterModal && (
        <FilterModal
          show={filterModal}
          onClose={() => setFilterModal(false)}
          tags={tags}
          selectedTags={activeTab === "servers" ? selectedServerTags : selectedTags}
          handleFilter={activeTab === "servers" ? handleServerFilter : handleFilter}
          showfilterHeader={
            activeTab === "servers" ? "Filter Servers by Tags" : `Filter ${selectedAgent === META_AGENT || selectedAgent === PLANNER_META_AGENT ? "Agents" : "Tools"} by Tags`
          }
          filterTypes={activeTab === "servers" ? "servers" : undefined}
        />
      )}
    </div>
  );
};

export default AgentOnboard;
