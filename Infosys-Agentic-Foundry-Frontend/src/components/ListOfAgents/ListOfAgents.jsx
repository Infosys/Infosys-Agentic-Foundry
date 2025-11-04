import React, { useEffect, useState, useCallback, useRef } from "react";
import styles from "../../css_modules/ListOfAgents.module.css";
import AgentCard from "./AgentCard";
import { APIs, REACT_AGENT, agentTypesDropdown } from "../../constant";
import SubHeader from "../commonComponents/SubHeader";
import AgentOnboard from "../AgentOnboard";
import UpdateAgent from "./UpdateAgent.jsx";
import ExportFilesModal from "./ExportFilesModal.jsx";
import useFetch from "../../Hooks/useAxios.js";
import Loader from "../commonComponents/Loader.jsx";
import { useMessage } from "../../Hooks/MessageContext";
import FilterModal from "../commonComponents/FilterModal.jsx";
import { useToolsAgentsService } from "../../services/toolService.js";
import { debounce } from "lodash";
import Cookies from "js-cookie";
import { useActiveNavClick } from "../../events/navigationEvents";
import { useErrorHandler } from "../../Hooks/useErrorHandler";

const ListOfAgents = () => {
  const [plusBtnClicked, setPlusBtnClicked] = useState(false);
  const [editAgentData, setEditAgentData] = useState("");
  const [agentsListData, setAgentsListData] = useState([]);
  const [visibleData, setVisibleData] = useState([]);
  const [page, setPage] = useState(1);
  const [searchTerm, setSearchTerm] = useState("");
  const [agentsList, setAgentsList] = useState([]);
  const [filterModal, setFilterModal] = useState(false);
  const [tags, setTags] = useState([]);
  const [selectedTags, setSelectedTags] = useState([]);
  const [selectedAgentType, setSelectedAgentType] = useState("");
  const selectedAgentTypeRef = useRef("");
  const [selectedAgentIds, setSelectedAgentIds] = useState([]);
  const visibleAgentsContainerRef = useRef(null);
  const [totalAgentCount, setTotalAgentCount] = useState(0);
  const [loading, setLoading] = useState(false);
  const [exportLoading, setExportLoading] = useState(false);
  const [showExportModal, setShowExportModal] = useState(false);
  const { addMessage, setShowPopup } = useMessage();
  const isLoadingRef = React.useRef(false);
  const [loader, setLoaderState] = useState(false);
  const [hasMore, setHasMore] = useState(true); // track if more pages are available
  const handleAddMessage = (message, type) => {
    addMessage(message, type);
  };

  const { fetchData, deleteData } = useFetch();
  const { getAgentsSearchByPageLimit, exportAgents, calculateDivs } = useToolsAgentsService();
  const pageRef = useRef(1);
  const { handleError } = useErrorHandler();

  const getTags = async () => {
    try {
      const data = await fetchData(APIs.GET_TAGS);
      setTags(data);
    } catch (e) {
      handleError(e, { customMessage: "Failed to load tags" });
    }
  };
  // Use a ref to ensure tags are fetched only once
  const hasLoadedTagsOnce = useRef(false);

  useEffect(() => {
    if (hasLoadedTagsOnce.current) return;
    hasLoadedTagsOnce.current = true;
    getTags();
  }, [plusBtnClicked, editAgentData]);

  useEffect(() => {
    if (!loading) {
      setShowPopup(true);
    } else {
      setShowPopup(false);
    }
  }, [loading]);

  const getAgentsData = async (pageNumber, divsCount) => {
    return getAgentsDataWithTags(pageNumber, divsCount, selectedTags, selectedAgentTypeRef.current);
  };

  const getAgentsDataWithTags = async (pageNumber, divsCount, tagsToUse, agentTypeToUse) => {
    setLoading(true);
    try {
      const tagsParam = tagsToUse?.length > 0 ? tagsToUse : undefined;

      const response = await getAgentsSearchByPageLimit({
        page: pageNumber,
        limit: divsCount,
        search: "",
        agentic_application_type: agentTypeToUse !== "all" && agentTypeToUse ? agentTypeToUse : undefined,
        tags: tagsParam,
      });
      const data = sanitizeAgentsResponse(response?.details);

      if (pageNumber === 1) {
        setAgentsList(data); // Save the initial list of agents
        setVisibleData(data); // Ensure initial load is rendered
      } else {
        if (data.length > 0) {
          setVisibleData((prev) => [...prev, ...data]);
        }
      }

      // Use total_count from response if available, otherwise use current data length
      setTotalAgentCount(response.total_count || data?.length || 0);
      // If fewer items than requested were returned, we've reached the end
      if (data.length < divsCount) {
        setHasMore(false);
      } else if (pageNumber === 1) {
        // Reset hasMore on fresh load only when page is full
        setHasMore(true);
      }
    } catch (e) {
      // return data; // return fetched data for caller decisions

      handleError(e, { customMessage: "Failed to load agents" });
      console.error("Error fetching tools");
      if (pageNumber === 1) {
        setAgentsList([]);
        setVisibleData([]);
        setTotalAgentCount(0);
      }
      setHasMore(false);
      return [];
    } finally {
      setLoading(false);
    }
  };

  const fetchAgents = async () => {
    try {
      const divsCount = calculateDivs(visibleAgentsContainerRef, 200, 128, 40);

      pageRef.current = 1;
      setPage(1);

      getAgentsData(1, divsCount);
    } catch (e) {
      handleError(e, { customMessage: "Failed to fetch agents" });
    }
  };

  const deleteAgent = async (id, email, isAdmin = false) => {
    try {
      await deleteData(APIs.DELETE_AGENTS + id, {
        user_email_id: email,
        is_admin: isAdmin,
      });
      handleAddMessage("AGENT HAS BEEN DELETED SUCCESSFULLY !", "success");
      return true;
    } catch (error) {
      handleError(error);
      return false;
    }
  };

  const handleSearch = async (searchValue, divsCount, pageNumber, tagsToUse = null) => {
    setSearchTerm(searchValue || "");
    setPage(1);
    pageRef.current = 1;
    setVisibleData([]);
    setHasMore(true);
    if (searchValue.trim()) {
      try {
        setLoading(true);
        // Use provided tagsToUse or fall back to selectedTags state
        const tagsForSearch = tagsToUse !== null ? tagsToUse : selectedTags;
        const tagsParam = tagsForSearch?.length > 0 ? tagsForSearch : undefined;

        // Use the new API endpoint for search with tag filtering
        const response = await getAgentsSearchByPageLimit({
          page: pageNumber,
          limit: divsCount,
          search: searchValue,
          agentic_application_type: selectedAgentTypeRef.current !== "all" && selectedAgentTypeRef.current ? selectedAgentTypeRef.current : undefined,
          tags: tagsParam,
        });
        let dataToSearch = sanitizeAgentsResponse(response?.details);
        if (tagsForSearch?.length > 0) {
          dataToSearch = dataToSearch.filter((item) => item.tags && item.tags.some((tag) => tagsForSearch.includes(tag?.tag_name)));
        }

        // Setting the total count
        setTotalAgentCount(response.total_count || 0);

        // Update visibleData with the API filtered data (no client-side filtering needed)
        setVisibleData(dataToSearch);
        // If returned less than requested, no more pages
        setHasMore(dataToSearch.length >= divsCount);
      } catch (error) {
        handleError(error, { customMessage: "Search failed" });
        setVisibleData([]); // Clear visibleData on error
        setTotalAgentCount(0);
        setHasMore(false);
      } finally {
        setLoading(false); // Hide loader
      }
    } else {
      // If search term is empty, reset to default data
      setVisibleData(agentsList); // Reset to the initial list of tools
      setHasMore(true);
    }
  };

  const clearSearch = () => {
    setSearchTerm("");
    setSelectedTags([]); // Clear tags when clearing search
    setVisibleData([]);
    setHasMore(true);
    const divsCount = calculateDivs(visibleAgentsContainerRef, 200, 128, 40);
    setPage(1);
    pageRef.current = 1;
    // Call getAgentsData with explicitly empty tags and current agent type
    getAgentsDataWithTags(1, divsCount, [], selectedAgentTypeRef.current);
  };

  const hasLoadedOnce = useRef(false);

  useEffect(() => {
    const container = visibleAgentsContainerRef?.current;
    if (!container) return;

    // Extract the check logic into a separate function
    const checkAndLoadMore = () => {
      if (
        container.scrollTop + container.clientHeight >= container.scrollHeight - 10 &&
        !loading &&
        !isLoadingRef.current &&
        hasMore // Prevent if no more pages
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
  }, [visibleAgentsContainerRef, hasMore, loading]);

  const handleScrollLoadMore = async () => {
    if (loader || isLoadingRef.current || !hasMore) return; // Prevent multiple calls or if no more data
    isLoadingRef.current = true;
    const nextPage = pageRef.current + 1;
    const divsCount = calculateDivs(visibleAgentsContainerRef, 200, 128, 40);
    try {
      setLoaderState(true);
      setLoading && setLoading(true);
      let newData = [];
      const res = await getAgentsSearchByPageLimit({
        page: nextPage,
        limit: divsCount,
        search: searchTerm,
        agentic_application_type: selectedAgentTypeRef.current !== "all" && selectedAgentTypeRef.current ? selectedAgentTypeRef.current : undefined,
        tags: selectedTags?.length > 0 ? selectedTags : undefined,
      });
      newData = sanitizeAgentsResponse(res?.details);
      if (selectedTags?.length > 0) {
        newData = newData.filter((item) => item.tags && item.tags.some((tag) => selectedTags.includes(tag?.tag_name)));
      }
      if (newData.length > 0) {
        setVisibleData((prev) => [...prev, ...newData]);
        setPage(nextPage);
        pageRef.current = nextPage;
      }
      // If fewer items than requested were returned, we've reached the end
      if (newData.length < divsCount) setHasMore(false);
    } catch (err) {
      handleError(err, { customMessage: "Failed to load more agents" });
      setHasMore(false);
    } finally {
      setLoaderState(false);
      setLoading && setLoading(false);
      isLoadingRef.current = false;
    }
  };

  useEffect(() => {
    if (hasLoadedOnce.current) return; // prevent duplicate initial load
    hasLoadedOnce.current = true;
    fetchAgents();
  }, []);

  const handleRefresh = () => {
    setSearchTerm("");
    setSelectedTags([]);
    setSelectedAgentType("");
    selectedAgentTypeRef.current = "";
    setVisibleData([]);
    setHasMore(true);
    setPage(1);
    pageRef.current = 1;
    const divsCount = calculateDivs(visibleAgentsContainerRef, 200, 128, 40);
    // Call getAgentsData with explicitly empty tags and empty agent type
    getAgentsDataWithTags(1, divsCount, [], "");
  };

  const onSettingClick = () => {
    setFilterModal(true);
  };

  const onPlusClick = () => {
    setPlusBtnClicked(true);
  };

  const onOnboardClose = () => {
    setPlusBtnClicked(false);
  };

  // Normalize API responses to always return a clean array of agent objects
  const sanitizeAgentsResponse = (response) => {
    if (!response) return [];
    // Handle new response format with details array
    const dataArray = response.details || response;
    // If backend sometimes returns an object instead of array
    if (!Array.isArray(dataArray)) return [];
    // If array contains a single message/detail object with no agent fields, treat as empty
    if (
      dataArray.length === 1 &&
      dataArray[0] &&
      typeof dataArray[0] === "object" &&
      ("detail" in dataArray[0] || "message" in dataArray[0]) &&
      !("agentic_application_id" in dataArray[0])
    ) {
      return [];
    }
    return dataArray.filter((item) => item && typeof item === "object" && ("agentic_application_id" in item || "agentic_application_name" in item));
  };

  const onAgentEdit = (data) => {
    setEditAgentData(data);
    setPlusBtnClicked(false);
  };

  const handleUpdateAgentClose = () => {
    setPlusBtnClicked(false);
    setEditAgentData(null);
  };

  const handleFilter = async (selectedTagsParam) => {
    setSelectedTags(selectedTagsParam);
    setPage(1);
    pageRef.current = 1;
    setVisibleData([]);
    setHasMore(true);

    // Trigger new API call with selected tags
    const divsCount = calculateDivs(visibleAgentsContainerRef, 200, 128, 40);
    if (searchTerm.trim()) {
      // If there's a search term, use handleSearch with current search and new tags
      await handleSearch(searchTerm, divsCount, 1, selectedTagsParam);
    } else {
      // If no search term, fetch data with tag filter - use selectedTagsParam directly
      await getAgentsDataWithTags(1, divsCount, selectedTagsParam, selectedAgentTypeRef.current);
    }
  };

  const handleAgentTypeChange = async (e) => {
    const type = e.target.value;
    setSelectedAgentType(type);
    selectedAgentTypeRef.current = type;
    setSearchTerm("");
    setPage(1);
    pageRef.current = 1;
    setVisibleData([]);
    setHasMore(true);
    const divsCount = calculateDivs(visibleAgentsContainerRef, 200, 128, 40);
    setLoading(true);
    try {
      const response = await getAgentsSearchByPageLimit({
        page: 1,
        limit: divsCount,
        agentic_application_type: type !== "all" && type ? type : undefined,
        tags: selectedTags?.length > 0 ? selectedTags : undefined,
      });
      const sanitized = sanitizeAgentsResponse(response?.details);
      setVisibleData(sanitized);
      setTotalAgentCount(response.total_count || 0);
      setHasMore(sanitized.length >= divsCount);
    } catch (error) {
      setVisibleData([]);
      setTotalAgentCount(0);
      setHasMore(false);
    } finally {
      setLoading(false);
    }
  };
  const handleAgentSelect = (agentId, checked) => {
    setSelectedAgentIds((prev) => (checked ? [...prev, agentId] : prev.filter((id) => id !== agentId)));
  };

  const handleExportSelected = () => {
    if (selectedAgentIds.length === 0) return;
    setShowExportModal(true);
  };

  const handleExportWithFiles = async (selectedFiles, configData, exportAndDeploy) => {
    setExportLoading(true);
    setShowExportModal(false);
    try {
      const userEmail = Cookies.get("email");
      // You can extend the exportAgents function to accept selectedFiles parameter
      // For now, we'll use the existing function and note that file selection could be added to the API
      // Accept exportAndDeploy as a separate argument
      const blob = await exportAgents(selectedAgentIds, userEmail, selectedFiles, configData, exportAndDeploy);
      if (!blob) throw new Error("Failed to export agents");
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;

      // Dynamic filename and message based on whether files are selected
      const filename = selectedFiles.length > 0 ? `agents_export_with_${selectedFiles.length}_files.zip` : `agents_export.zip`;
      const successMessage =
        selectedFiles.length > 0 ? `Agents exported successfully with ${selectedFiles.length} file${selectedFiles.length !== 1 ? "s" : ""}!` : "Agents exported successfully!";

      a.download = filename;
      document.body.appendChild(a);
      a.click();
      a.remove();
      window.URL.revokeObjectURL(url);
      handleAddMessage(successMessage, "success");
      setSelectedAgentIds([]); // Clear selection after successful export
    } catch (err) {
      handleError(err, { customMessage: "Export failed" });
    } finally {
      setExportLoading(false);
    }
  };

  const handleCloseExportModal = () => {
    setShowExportModal(false);
  };

  useActiveNavClick("/agent", () => {
    setPlusBtnClicked((open) => (open ? false : open));
    setEditAgentData(null);
  });

  return (
    <div className={styles.container}>
      {(loading || exportLoading) && <Loader />}
      {/* Show end-of-list message when no more pages */}
      {/* {!hasMore && visibleData.length > 0 && (
        <div className={styles.endOfListMsg}>
          <p>No more agents to load.</p>
        </div>
      )} */}
      <div className={styles.subHeaderContainer}>
        <SubHeader
          onSearch={(value) => {
            handleSearch(value, calculateDivs(visibleAgentsContainerRef, 200, 128, 40), 1);
          }}
          onSettingClick={onSettingClick}
          onPlusClick={onPlusClick}
          selectedTags={selectedTags}
          heading={"AGENTS"}
          handleRefresh={handleRefresh}
          searchValue={searchTerm}
          clearSearch={clearSearch}
          showAgentTypeDropdown={true}
          agentTypes={agentTypesDropdown}
          selectedAgentType={selectedAgentType}
          handleAgentTypeChange={handleAgentTypeChange}
        />
        <button className={styles.exportSelectedBtn} onClick={handleExportSelected} disabled={selectedAgentIds.length === 0}>
          Export
        </button>
      </div>

      <div style={{ display: "flex", gap: "12px", width: "100%", overflow: "hidden" }}>
        {/* Display searched tool text if searchTerm exists and results are found */}
        {searchTerm.trim() && visibleData.length > 0 && (
          <div className={styles.searchedToolText}>
            <p>
              Search term:{" "}
              <span className={`boldText ${styles.filterOrSearchText}`} title={searchTerm}>
                {searchTerm}
              </span>
            </p>
          </div>
        )}

        {/* Display filtered tools text if filters are applied */}
        {selectedTags.length > 0 && visibleData.length > 0 && (
          <div className={styles.filteredToolText}>
            <p>
              Selected tags:{" "}
              <span className={`boldText ${styles.filterOrSearchText}`} title={selectedTags.join(", ")}>
                {selectedTags.join(", ")}
              </span>
            </p>
          </div>
        )}
      </div>

      {/* Display total count summary */}
      {visibleData.length > 0 && (
        <div className={styles.summaryLine}>
          <strong>{visibleData.length}</strong> agents (of {totalAgentCount} total)
        </div>
      )}

      <div className={styles.visibleAgentsContainer} ref={visibleAgentsContainerRef}>
        {/* Display "No Agents Found" if no results are found after filtering */}
        {selectedTags.length > 0 && visibleData.length === 0 && (
          <div className={styles.searchedToolText}>
            <p>
              No agents found for:{" "}
              <span className={`boldText ${styles.filterOrSearchText}`} title={selectedTags.join(", ")}>
                {selectedTags.join(", ")}
              </span>
            </p>
          </div>
        )}

        {/* Display "No Agents Found" if no results are found after searching */}
        {searchTerm.trim() && visibleData.length === 0 && (
          <div className={styles.filteredToolText}>
            <p>
              No agents found for:{" "}
              <span className={`boldText ${styles.filterOrSearchText}`} title={searchTerm}>
                {searchTerm}
              </span>
            </p>
          </div>
        )}

        {/* Display "No Agents found" if no results are found after selecting agent type */}
        {selectedAgentType && !searchTerm.trim() && selectedTags.length === 0 && visibleData.length === 0 && (
          <div className={styles.filteredToolText}>
            <p>No agents found</p>
          </div>
        )}
        <div className={styles.agentsList}>
          {visibleData?.map((data) => (
            <AgentCard
              key={data?.agentic_application_id}
              styles={styles}
              data={data}
              onAgentEdit={onAgentEdit}
              deleteAgent={deleteAgent}
              fetchAgents={fetchAgents}
              isSelected={selectedAgentIds.includes(data.agentic_application_id)}
              onSelect={handleAgentSelect}
            />
          ))}
        </div>
      </div>

      {plusBtnClicked && (
        <div className={styles.agentOnboardContainer}>
          <AgentOnboard
            onClose={onOnboardClose}
            tags={tags}
            fetchAgents={fetchAgents}
            setNewAgentData={setEditAgentData}
            agentsListData={agentsListData?.filter((agent) => agent?.agentic_application_type === REACT_AGENT)}
          />
        </div>
      )}
      {editAgentData && (
        <div className={styles.updateAgentContainer}>
          <UpdateAgent
            onClose={handleUpdateAgentClose}
            agentData={editAgentData}
            tags={tags}
            agentsListData={agentsListData?.filter((agent) => agent?.agentic_application_type === REACT_AGENT)}
            fetchAgents={fetchAgents}
            searchTerm={searchTerm}
          />
        </div>
      )}

      <FilterModal
        show={filterModal}
        onClose={() => setFilterModal(false)}
        tags={tags}
        handleFilter={handleFilter}
        selectedTags={selectedTags}
        showfilterHeader={"Filter agents by Tags"}
      />

      {showExportModal && <ExportFilesModal onClose={handleCloseExportModal} selectedAgentIds={selectedAgentIds} onExport={handleExportWithFiles} />}
    </div>
  );
};

export default ListOfAgents;
