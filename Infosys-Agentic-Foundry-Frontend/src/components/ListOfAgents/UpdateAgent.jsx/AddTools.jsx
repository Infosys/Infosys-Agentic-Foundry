import React, { useState, useEffect } from "react";
import SVGIcons from "../../../Icons/SVGIcons";
import Toggle from "../../commonComponents/Toggle";
import { META_AGENT, MULTI_AGENT, PLANNER_META_AGENT, REACT_AGENT } from "../../../constant";
import ToolCard from "./ToolCard";
import SearchInput from "../../commonComponents/SearchInputTools";

import style from "./AddTools.module.css";
import FilterModal from "../../commonComponents/FilterModal";
import { useToolsAgentsService } from "../../../services/toolService";
import { useMcpServerService } from "../../../services/serverService";
import { debounce } from "lodash";
import Loader from "../../commonComponents/Loader";

const AddTools = (props) => {
  const {
    styles,
    addOrRemoveTool,
    selectedTools,
    remainingTools,
    addedToolsId,
    setAddedToolsId,
    removedToolsId,
    setremovedToolsId,
    selectedAgents,
    remainingAgents,
    agentType,
    setAddedAgentsId,
    addedAgentsId,
    removedAgentsId,
    setRemovedAgentsId,
    tags,
    setSelectedTags,
    setToggleSelected,
    toggleSelected,
    selectedTags,
    agentData,
    tagsList,
    setShowForm,
    setEditTool,
    toolListContainerRef,
    fetchToolsData,
    setVisibleData,
    setLoader,
    pageRef,
    setPage,
    visibleData,
    remainingServers,
  } = props;

  const [searchTerm, setSearchTerm] = useState("");
  const [filterModalOpen, setFilterModalOpen] = useState(false);
  const [updateTagsModalOpen, setUpdateTagsModalOpen] = useState(false);
  const [filterTags, setFilterTags] = useState([]); // For filtering unmapped list
  const [loader, setLoaderState] = useState(false);
  const isLoadingRef = React.useRef(false);
  const [activeTab, setActiveTab] = useState("tools"); // 'tools' or 'servers'

  // Normalize toggleSelected into a strict boolean so that string/number values
  // passed from parent (e.g. 'true'/'false' or 1/0) don't break conditional rendering.
  const normalizedToggleSelected = React.useMemo(() => {
    if (typeof toggleSelected === "boolean") return toggleSelected;
    if (typeof toggleSelected === "string") return toggleSelected.toLowerCase() === "true";
    if (typeof toggleSelected === "number") return toggleSelected === 1;
    return Boolean(toggleSelected);
  }, [toggleSelected]);
  const { getToolsSearchByPageLimit, getAgentsSearchByPageLimit, calculateDivs } = useToolsAgentsService();
  const { getServersSearchByPageLimit } = useMcpServerService();

  // Normalize API responses to always return a clean array
  const sanitizeToolsResponse = (response) => {
    if (!response) return [];
    if (!Array.isArray(response)) return [];
    if (response.length === 1 && response[0] && typeof response[0] === "object" && "message" in response[0] && !("tool_id" in response[0])) {
      return [];
    }
    return response.filter((item) => item && typeof item === "object" && ("tool_id" in item || "tool_name" in item));
  };

  const sanitizeAgentsResponse = (response) => {
    if (!response) return [];
    if (!Array.isArray(response)) return [];
    if (response.length === 1 && response[0] && typeof response[0] === "object" && "message" in response[0] && !("agentic_application_id" in response[0])) {
      return [];
    }
    return response.filter((item) => item && typeof item === "object" && ("agentic_application_id" in item || "agentic_application_name" in item));
  };

  const sanitizeServersResponse = (response) => {
    if (!response) return [];
    if (!Array.isArray(response)) return [];
    return response.filter((item) => item && typeof item === "object");
  };

  useEffect(() => {
    if (agentData?.tags) {
      const defaultTags = agentData.tags.map((tag) => tag.tag_id);
      setSelectedTags(defaultTags);
    }
  }, [agentData, setSelectedTags]);

  const onChange = (e) => {
    // Ensure parent still gets a boolean, but normalize locally for safety.
    const checked = Boolean(e.target.checked);
    setToggleSelected(checked);
    // If user turns ON the remove-mapped toggle, ensure they land on the Tools mapped list
    // since the action is typically removing mapped tools. If needed we can refine
    // this to only switch when there are mapped tools present.
    if (checked) {
      setActiveTab("tools");
    }
    setSearchTerm("");
    setVisibleData([]);
    setPage(1);
    pageRef.current = 1;
  };

  const handleSearch = async (searchValue, divsCount, pageNumber) => {
    setSearchTerm(searchValue);
    setPage(1);
    pageRef.current = 1;
    if (!normalizedToggleSelected) {
      if (searchValue?.trim()) {
        setVisibleData([]);
        try {
          setLoaderState(true);
          setLoader && setLoader(true);
          let data = [];
          if (activeTab === "servers") {
            // Use servers search API for servers tab
            const res = await getServersSearchByPageLimit({
              page: pageNumber,
              limit: divsCount,
              search: searchValue,
              tags: filterTags?.length > 0 ? filterTags : undefined,
            });
            const serverData = sanitizeServersResponse(res?.details || []);
            data = Array.isArray(serverData) ? serverData : [];
          } else if (agentType === META_AGENT || agentType === PLANNER_META_AGENT) {
            const res = await getAgentsSearchByPageLimit({
              page: pageNumber,
              limit: divsCount,
              search: searchValue,
              tags: filterTags?.length > 0 ? filterTags : undefined,
            });
            const agentData = sanitizeAgentsResponse(res?.details || []);
            data =
              agentData?.filter(
                (a) =>
                  (a.agentic_application_type === REACT_AGENT || a.agentic_application_type === MULTI_AGENT) &&
                  !selectedAgents.some((mapped) => mapped.agentic_application_id === a.agentic_application_id)
              ) || [];
          } else {
            const tagsToPass = filterTags?.length > 0 ? filterTags : undefined;
            const res = await getToolsSearchByPageLimit({
              page: pageNumber,
              limit: divsCount,
              search: searchValue,
              tags: tagsToPass,
            });
            const toolData = sanitizeToolsResponse(res?.details || []);
            data = toolData.filter((tool) => !selectedTools.some((mapped) => mapped.tool_id === tool.tool_id));
          }
          setVisibleData(data);
        } catch (err) {
          console.error(err);
          setVisibleData([]);
        } finally {
          setLoaderState(false);
          setLoader && setLoader(false);
        }
      } else {
        const divsCount = calculateDivs(toolListContainerRef, 231, 70, 26);
        setVisibleData([]);
        fetchInitialData(1, divsCount);
      }
    } else {
      // If toggleSelected is on, use dropdown search approach (filter mapped list)
      let filtered = [];
      if (agentType === META_AGENT || agentType === PLANNER_META_AGENT) {
        filtered = selectedAgents.filter((agent) => agent.agentic_application_name?.toLowerCase().includes(searchValue.toLowerCase()));
      } else {
        filtered = selectedTools.filter((tool) => tool.tool_name?.toLowerCase().includes(searchValue.toLowerCase()));
      }
      setVisibleData(filtered);
    }
  };

  const handleSearchWithTags = async (searchValue, divsCount, pageNumber, tags = filterTags) => {
    if (searchValue && searchValue.trim().length > 0) {
      if (!normalizedToggleSelected) {
        try {
          setLoaderState(true);
          setLoader && setLoader(true);
          let data = [];
          if (activeTab === "servers") {
            // Use servers search API for servers tab
            const res = await getServersSearchByPageLimit({
              page: pageNumber,
              limit: divsCount,
              search: searchValue,
              tags: tags?.length > 0 ? tags : undefined,
            });
            const serverData = sanitizeServersResponse(res?.details || []);
            data = Array.isArray(serverData) ? serverData : [];
          } else if (agentType === META_AGENT || agentType === PLANNER_META_AGENT) {
            const res = await getAgentsSearchByPageLimit({
              page: pageNumber,
              limit: divsCount,
              search: searchValue,
              tags: tags?.length > 0 ? tags : undefined,
            });
            const agentData = sanitizeAgentsResponse(res?.details || []);
            data =
              agentData?.filter(
                (a) =>
                  (a.agentic_application_type === REACT_AGENT || a.agentic_application_type === MULTI_AGENT) &&
                  !selectedAgents.some((mapped) => mapped.agentic_application_id === a.agentic_application_id)
              ) || [];
          } else {
            const tagsToPass = tags?.length > 0 ? tags : undefined;
            const res = await getToolsSearchByPageLimit({
              page: pageNumber,
              limit: divsCount,
              search: searchValue,
              tags: tagsToPass,
            });
            const toolData = sanitizeToolsResponse(res?.details || []);
            data = toolData.filter((tool) => !selectedTools.some((mapped) => mapped.tool_id === tool.tool_id));
          }
          setVisibleData(data);
        } catch (err) {
          console.error(err);
          setVisibleData([]);
        } finally {
          setLoaderState(false);
          setLoader && setLoader(false);
        }
      } else {
        const divsCount = calculateDivs(toolListContainerRef, 231, 70, 26);
        setVisibleData([]);
        fetchInitialData(1, divsCount);
      }
    } else {
      // If toggleSelected is on, use dropdown search approach (filter mapped list)
      let filtered = [];
      if (agentType === META_AGENT || agentType === PLANNER_META_AGENT) {
        filtered = selectedAgents.filter((agent) => agent.agentic_application_name?.toLowerCase().includes(searchValue.toLowerCase()));
      } else {
        filtered = selectedTools.filter((tool) => tool.tool_name?.toLowerCase().includes(searchValue.toLowerCase()));
      }
      setVisibleData(filtered);
    }
  };

  const clearSearch = () => {
    setSearchTerm("");
    setPage(1);
    pageRef.current = 1;
    if (!normalizedToggleSelected) {
      setVisibleData([]);
      // Trigger fetchInitialData with no search term (reset to first page)
      const divsCount = calculateDivs(toolListContainerRef, 231, 70, 26);
      fetchInitialData(1, divsCount);
    } else {
      // If toggleSelected is on, reset visibleData to mapped list
      let mappedList = [];
      if (agentType === META_AGENT || agentType === PLANNER_META_AGENT) {
        mappedList = selectedAgents;
      } else {
        mappedList = selectedTools;
      }
      setVisibleData(mappedList);
    }
  };

  const handleFilter = (selectedTags) => {
    setSelectedTags(selectedTags); // Update selected tags for agent
  };

  // Internal data fetching function that handles the new response format
  const fetchInitialData = async (pageNumber, divsCount) => {
    return fetchInitialDataWithTags(pageNumber, divsCount, filterTags);
  };

  const fetchInitialDataWithTags = async (pageNumber, divsCount, tags = filterTags) => {
    if (normalizedToggleSelected) return; // Don't fetch for mapped mode

    try {
      setLoaderState(true);
      setLoader && setLoader(true);
      let data = [];

      if (activeTab === "servers") {
        const res = await getServersSearchByPageLimit({
          page: pageNumber,
          limit: divsCount,
          search: "",
          tags: tags?.length > 0 ? tags : undefined,
        });
        data = sanitizeServersResponse(res?.details || []);
      } else if (agentType === META_AGENT || agentType === PLANNER_META_AGENT) {
        const res = await getAgentsSearchByPageLimit({
          page: pageNumber,
          limit: divsCount,
          search: "",
          tags: tags?.length > 0 ? tags : undefined,
        });
        const agentData = sanitizeAgentsResponse(res?.details || []);
        data =
          agentData?.filter(
            (a) =>
              (a.agentic_application_type === REACT_AGENT || a.agentic_application_type === MULTI_AGENT) &&
              !selectedAgents.some((mapped) => mapped.agentic_application_id === a.agentic_application_id)
          ) || [];
      } else {
        const res = await getToolsSearchByPageLimit({
          page: pageNumber,
          limit: divsCount,
          search: "",
          tags: tags?.length > 0 ? tags : undefined,
        });
        const toolData = sanitizeToolsResponse(res?.details || []);
        data = toolData.filter((tool) => !selectedTools.some((mapped) => mapped.tool_id === tool.tool_id));
      }

      setVisibleData(data);
    } catch (err) {
      console.error("fetchInitialDataWithTags error:", err);
      setVisibleData([]);
    } finally {
      setLoaderState(false);
      setLoader && setLoader(false);
    }
  };

  // Internal data fetching function for pagination that returns data
  const fetchInitialDataForPagination = async (pageNumber, divsCount) => {
    if (normalizedToggleSelected) return []; // Don't fetch for mapped mode

    try {
      let data = [];

      if (activeTab === "servers") {
        const res = await getServersSearchByPageLimit({
          page: pageNumber,
          limit: divsCount,
          search: "",
          tags: filterTags?.length > 0 ? filterTags : undefined,
        });
        data = sanitizeServersResponse(res?.details || []);
      } else if (agentType === META_AGENT || agentType === PLANNER_META_AGENT) {
        const res = await getAgentsSearchByPageLimit({
          page: pageNumber,
          limit: divsCount,
          search: "",
          tags: filterTags?.length > 0 ? filterTags : undefined,
        });
        const agentData = sanitizeAgentsResponse(res?.details || []);
        data =
          agentData?.filter(
            (a) =>
              (a.agentic_application_type === REACT_AGENT || a.agentic_application_type === MULTI_AGENT) &&
              !selectedAgents.some((mapped) => mapped.agentic_application_id === a.agentic_application_id)
          ) || [];
      } else {
        const res = await getToolsSearchByPageLimit({
          page: pageNumber,
          limit: divsCount,
          search: "",
          tags: filterTags?.length > 0 ? filterTags : undefined,
        });
        const toolData = sanitizeToolsResponse(res?.details || []);
        data = toolData.filter((tool) => !selectedTools.some((mapped) => mapped.tool_id === tool.tool_id));
      }

      return data;
    } catch (err) {
      console.error("fetchInitialDataForPagination error:", err);
      return [];
    }
  };

  const handleFilterTools = async (selectedFilterTags) => {
    setFilterTags(selectedFilterTags); // Update filter tags for unmapped list
    setPage(1);
    pageRef.current = 1;
    setVisibleData([]);

    // Immediately trigger API call with the new filter tags (don't wait for state update)
    if (!normalizedToggleSelected) {
      const divsCount = calculateDivs(toolListContainerRef, 231, 70, 26);
      if (searchTerm.trim()) {
        // If there's a search term, use search with new tags
        await handleSearchWithTags(searchTerm, divsCount, 1, selectedFilterTags);
      } else {
        // If no search term, fetch initial data with new tags
        await fetchInitialDataWithTags(1, divsCount, selectedFilterTags);
      }
    }
  };

  // Trigger search when filter tags change
  useEffect(() => {
    if (!normalizedToggleSelected && !searchTerm.trim()) {
      const divsCount = calculateDivs(toolListContainerRef, 231, 70, 26);
      setVisibleData([]);
      fetchInitialData(1, divsCount);
    } else if (!normalizedToggleSelected && searchTerm.trim()) {
      const divsCount = calculateDivs(toolListContainerRef, 231, 70, 26);
      handleSearch(searchTerm, divsCount, 1);
    }
  }, [filterTags]);

  // Initial load when component mounts or tab changes
  useEffect(() => {
    if (!normalizedToggleSelected && !searchTerm.trim()) {
      const divsCount = calculateDivs(toolListContainerRef, 231, 70, 26);
      setVisibleData([]);
      fetchInitialData(1, divsCount);
    }
  }, [activeTab, normalizedToggleSelected]);

  const isMetaAgent = agentType === META_AGENT || agentType === PLANNER_META_AGENT;
  const shouldHideServers = isMetaAgent;

  // If agent doesn't support servers, ensure we stay on the 'tools' tab
  useEffect(() => {
    if (shouldHideServers && activeTab === "servers") {
      setActiveTab("tools");
    }
  }, [shouldHideServers, activeTab]);

  const displayData = searchTerm.trim()
    ? visibleData || []
    : (toggleSelected ? (isMetaAgent ? selectedAgents : selectedTools) : isMetaAgent ? remainingAgents : remainingTools)?.filter((item) => {
        return isMetaAgent ? item.agentic_application_name?.toLowerCase().includes(searchTerm?.toLowerCase()) : item.tool_name?.toLowerCase()?.includes(searchTerm?.toLowerCase());
      }) || [];

  const handleScrollLoadMore = React.useCallback(async () => {
    if (loader || isLoadingRef.current) return; // Prevent multiple calls
    isLoadingRef.current = true;
    const nextPage = pageRef.current + 1;
    const divsCount = calculateDivs(toolListContainerRef, 231, 70, 26);
    if (!normalizedToggleSelected) {
      try {
        setLoaderState(true);
        setLoader && setLoader(true);
        let newData = [];
        if (searchTerm?.trim()) {
          // Only call search API if searchTerm is present
          if (agentType === META_AGENT || agentType === PLANNER_META_AGENT) {
            const res = await getAgentsSearchByPageLimit({
              page: nextPage,
              limit: divsCount,
              search: searchTerm,
              tags: filterTags?.length > 0 ? filterTags : undefined,
            });
            const agentData = sanitizeAgentsResponse(res?.details || []);
            newData = agentData.filter(
              (a) =>
                (a.agentic_application_type === REACT_AGENT || a.agentic_application_type === MULTI_AGENT) &&
                !selectedAgents.some((mapped) => mapped.agentic_application_id === a.agentic_application_id)
            );
          } else {
            const res = await getToolsSearchByPageLimit({
              page: nextPage,
              limit: divsCount,
              search: searchTerm,
              tags: filterTags?.length > 0 ? filterTags : undefined,
            });
            const toolData = sanitizeToolsResponse(res?.details || []);
            newData = toolData.filter((tool) => !selectedTools.some((mapped) => mapped.tool_id === tool.tool_id));
          }
          setVisibleData((prev) => [...prev, ...newData]);
        } else {
          // Only call fetchInitialData if no searchTerm
          const res = searchTerm?.trim() ? null : await fetchInitialDataForPagination(nextPage, divsCount);
          if (res && res.length > 0) {
            setVisibleData((prev) => [...prev, ...res]);
          }
        }
        setPage(nextPage);
        pageRef.current = nextPage;
      } catch (err) {
        console.error(err);
      } finally {
        setLoaderState(false);
        setLoader && setLoader(false);
        isLoadingRef.current = false;
      }
    } else {
      isLoadingRef.current = false;
    }
  }, [
    loader,
    normalizedToggleSelected,
    agentType,
    searchTerm,
    selectedAgents,
    selectedTools,
    setLoader,
    setLoaderState,
    setVisibleData,
    fetchToolsData,
    setPage,
    pageRef,
    toolListContainerRef,
  ]);

  useEffect(() => {
    if (normalizedToggleSelected) return; // Don't attach scroll for mapped list
    const container = toolListContainerRef?.current;
    if (!container) return;
    const debouncedHandleScroll = debounce(() => {
      if (
        container.scrollTop + container.clientHeight >= container.scrollHeight - 10 &&
        !loader &&
        !isLoadingRef.current // Prevent if already loading
      ) {
        handleScrollLoadMore();
      }
    }, 200); // 200ms debounce
    container.addEventListener("scroll", debouncedHandleScroll);
    return () => container.removeEventListener("scroll", debouncedHandleScroll);
  }, [toolListContainerRef, normalizedToggleSelected, loader, handleScrollLoadMore]);

  // const tabDisplayData = searchTerm.trim()
  //   ? visibleData || []
  //   : normalizedToggleSelected
  //   ? activeTab === "tools"
  //     ? selectedTools
  //     : selectedAgents.filter((agent) => agent.agentic_application_type === REACT_AGENT)
  //   : activeTab === "tools"
  //   ? remainingTools
  //       : remainingServers;

  let tabDisplayData;
  if (!normalizedToggleSelected) {
    // When toggle is OFF (showing unmapped items), always use visibleData from API calls
    tabDisplayData = visibleData || [];
  } else {
    // When toggle is ON (showing mapped items), use the mapped lists
    if (searchTerm.trim()) {
      // When searching in mapped mode, use visibleData (filtered mapped items)
      tabDisplayData = visibleData || [];
    } else {
      // No search in mapped mode, show all mapped items
      if (activeTab === "tools") {
        if (isMetaAgent) {
          tabDisplayData = selectedAgents || [];
        } else {
          tabDisplayData = selectedTools || [];
        }
      } else if (activeTab === "servers") {
        tabDisplayData = remainingServers || []; // Servers don't have a mapped state yet
      } else {
        tabDisplayData = [];
      }
    }
  }

  const filteredTabDisplayData = searchTerm.trim()
    ? tabDisplayData.filter(
        (item) => item.tool_name?.toLowerCase().includes(searchTerm.toLowerCase()) || item.agentic_application_name?.toLowerCase().includes(searchTerm.toLowerCase())
      )
    : tabDisplayData;

  return (
    <>
      {props?.recycleBin ? (
        <>
          <div className={styles.addToolContainer}>
            <div
              className={`${tabDisplayData?.length > 0 ? styles.toolsContainer : ""} ${props?.recycleBin ? styles.disabledButton : ""}`}
              style={{ maxHeight: "none", overflow: "visible" }}>
              {filteredTabDisplayData.map((tool) => (
                <ToolCard
                  key={tool.id || tool.tool_id || tool.agentic_application_id}
                  tool={tool}
                  styles={styles}
                  isMappedTool={normalizedToggleSelected}
                  addOrRemoveTool={addOrRemoveTool}
                  addedToolsId={addedToolsId}
                  addedAgentsId={addedAgentsId}
                  setAddedToolsId={setAddedToolsId}
                  setAddedAgentsId={setAddedAgentsId}
                  removedToolsId={removedToolsId}
                  removedAgentsId={removedAgentsId}
                  setremovedToolsId={setremovedToolsId}
                  setRemovedAgentsId={setRemovedAgentsId}
                  agentType={agentType}
                  tagsList={tagsList}
                  setShowForm={setShowForm}
                  setEditTool={setEditTool}
                  server={tool.mcp_config ? { ...tool, type: tool.mcp_config?.args?.[1] ? "LOCAL" : tool.mcp_config?.url ? "REMOTE" : "UNKNOWN" } : undefined}
                />
              ))}
            </div>
          </div>
        </>
      ) : (
        <>
          <div className={styles.addToolContainer}>
            {/* Show tabs only when remove-mapped toggle is OFF */}
            {normalizedToggleSelected !== true && (
              <div>
                <button
                  className={activeTab === "tools" ? `iafTabsBtn active` : "iafTabsBtn"}
                  onClick={() => {
                    setActiveTab("tools");
                    setFilterTags([]); // Clear filters when switching to tools
                    setSearchTerm("");
                    setVisibleData([]);
                    setPage(1);
                    pageRef.current = 1;
                  }}
                  aria-selected={activeTab === "tools"}
                  aria-controls="tools-panel"
                  role="tab"
                  tabIndex={activeTab === "tools" ? 0 : -1}>
                  {isMetaAgent ? "Agents" : "Tools"}
                </button>
                {!shouldHideServers && (
                  <button
                    className={activeTab === "servers" ? "iafTabsBtn active" : "iafTabsBtn"}
                    onClick={() => {
                      setActiveTab("servers");
                      setFilterTags([]); // Clear filters when switching to servers.
                      setSearchTerm("");
                      setVisibleData([]);
                      setPage(1);
                      pageRef.current = 1;
                    }}
                    aria-selected={activeTab === "servers"}
                    aria-controls="servers-panel"
                    role="tab"
                    tabIndex={activeTab === "servers" ? 0 : -1}>
                    Servers
                  </button>
                )}
              </div>
            )}
            <div className={styles.addTools} data-selected={normalizedToggleSelected}>
              <div className={style.topSection}>
                <p className={styles.addNewTool}>
                  <SVGIcons icon="fa-plus" width={12} height={12} fill="#007AC0" />
                  ADD
                </p>
                <Toggle onChange={onChange} value={toggleSelected} />
                <p className={styles.removeTool}>
                  <SVGIcons icon="fa-xmark" fill="#a1a1a1" width={12} height={16} /> REMOVE
                </p>
              </div>
              {/* Search bar */}
              <div className={styles.searchBar}>
                <SearchInput
                  key={`${normalizedToggleSelected}-${activeTab}`}
                  inputProps={{
                    placeholder: activeTab === "tools" ? (isMetaAgent ? "Search Agents" : "Search Tools") : "Search Servers",
                  }}
                  handleSearch={(value) => handleSearch(value, calculateDivs(toolListContainerRef, 231, 70, 26), 1)}
                  clearSearch={clearSearch}
                />
              </div>
              {normalizedToggleSelected !== true && (
                <div className={style.filterContainer}>
                  <button
                    type="button"
                    onClick={(e) => {
                      e.preventDefault();
                      setFilterModalOpen(true);
                    }}
                    className={style.filterIcon}
                    title="Filter by tags">
                    {filterTags?.length > 0 && <span className={style.filterIconBadge}>{filterTags?.length}</span>}
                    <SVGIcons icon="slider-rect" width={20} height={18} fill="#C3C1CF" />
                  </button>
                </div>
              )}
            </div>
            {searchTerm.trim() && !loader && visibleData.length === 0 ? (
              <div className={styles.noResultsFound}>
                <p>No results found.</p>
              </div>
            ) : (
              <div className={styles.toolsContainer} ref={toolListContainerRef}>
                {filteredTabDisplayData.map((tool) => (
                  <ToolCard
                    key={tool.id || tool.tool_id || tool.agentic_application_id}
                    tool={tool}
                    styles={styles}
                    isMappedTool={normalizedToggleSelected}
                    addOrRemoveTool={addOrRemoveTool}
                    addedToolsId={addedToolsId}
                    addedAgentsId={addedAgentsId}
                    setAddedToolsId={setAddedToolsId}
                    setAddedAgentsId={setAddedAgentsId}
                    removedToolsId={removedToolsId}
                    removedAgentsId={removedAgentsId}
                    setremovedToolsId={setremovedToolsId}
                    setRemovedAgentsId={setRemovedAgentsId}
                    agentType={agentType}
                    tagsList={tagsList}
                    setShowForm={setShowForm}
                    setEditTool={setEditTool}
                    server={tool.mcp_config ? { ...tool, type: tool.mcp_config?.args?.[1] ? "LOCAL" : tool.mcp_config?.url ? "REMOTE" : "UNKNOWN" } : undefined}
                  />
                ))}
              </div>
            )}
            {!normalizedToggleSelected && (
              <>
                <FilterModal
                  show={filterModalOpen}
                  onClose={() => setFilterModalOpen(false)}
                  tags={tags}
                  handleFilter={handleFilterTools}
                  selectedTags={filterTags}
                  filterTypes={activeTab}
                  showfilterHeader={
                    activeTab === "servers"
                      ? "Filter Servers by Tags"
                      : agentType === META_AGENT || agentType === PLANNER_META_AGENT
                      ? "Filter Agents by Tags"
                      : "Filter Tools by Tags"
                  }
                />
              </>
            )}
          </div>
        </>
      )}
    </>
  );
};

export default AddTools;
