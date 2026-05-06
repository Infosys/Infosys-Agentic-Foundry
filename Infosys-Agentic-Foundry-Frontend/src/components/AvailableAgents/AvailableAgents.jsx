import React, { useEffect, useState, useRef } from "react";
import { usePermissions } from "../../context/PermissionsContext";
import styles from "../../css_modules/AvailableAgents.module.css";
import DisplayCard1 from "../../iafComponents/GlobalComponents/DisplayCard/DisplayCard1.jsx";
import { APIs, REACT_AGENT, agentTypesDropdown } from "../../constant";
import SubHeader from "../commonComponents/SubHeader";
import CreateAgent from "./CreateAgent";
import UpdateAgent from "./UpdateAgent.jsx";
import ExportFilesModal from "./ExportFilesModal.jsx";
import useFetch from "../../Hooks/useAxios.js";
import Loader from "../commonComponents/Loader.jsx";
import { useMessage } from "../../Hooks/MessageContext";
import FilterModal from "../commonComponents/FilterModal.jsx";
import { useToolsAgentsService } from "../../services/toolService.js";
import { debounce } from "lodash";
import { getRoleFromToken, getEmailFromToken, getUserNameFromToken } from "../../utils/jwtUtils";
import { useActiveNavClick } from "../../events/navigationEvents";
import { useErrorHandler } from "../../Hooks/useErrorHandler";
import SVGIcons from "../../Icons/SVGIcons";
import EmptyState from "../commonComponents/EmptyState.jsx";
import ShareModal from "../commonComponents/ShareModal/ShareModal.jsx";
import SummaryLine from "../../iafComponents/GlobalComponents/SummaryLine.jsx";
import useMultiSelect from "../../Hooks/useMultiSelect.js";
import ConfirmationModal from "../commonComponents/ToastMessages/ConfirmationPopup";

const AvailableAgents = () => {
  const { loading: permissionsLoading, hasPermission } = usePermissions();

  // Permission checks for CRUD operations - default to false when permissions not loaded
  const canReadAgents = typeof hasPermission === "function" ? hasPermission("read_access.agents") : false;
  const canAddAgents = typeof hasPermission === "function" ? hasPermission("add_access.agents") : false;
  const canDeleteAgents = typeof hasPermission === "function" ? hasPermission("delete_access.agents") : false;
  const canExportAgents = typeof hasPermission === "function" ? hasPermission("export_agents_access") : false;

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
  const [selectedAgentType, setSelectedAgentType] = useState([]);
  const selectedAgentTypeRef = useRef([]);
  const [selectedAgentIds, setSelectedAgentIds] = useState([]);
  const visibleAgentsContainerRef = useRef(null);
  const [totalAgentCount, setTotalAgentCount] = useState(0);
  const [loading, setLoading] = useState(false);
  const [isLoadingMore, setIsLoadingMore] = useState(false);
  const [exportLoading, setExportLoading] = useState(false);
  const [showExportModal, setShowExportModal] = useState(false);

  // Share modal state
  const [shareModalData, setShareModalData] = useState(null);
  const [showShareModal, setShowShareModal] = useState(false);
  const { addMessage, setShowPopup } = useMessage();
  const isLoadingRef = React.useRef(false);
  const [loader, setLoaderState] = useState(false);
  const [hasMore, setHasMore] = useState(true); // track if more pages are available
  const [createdBy, setCreatedBy] = useState("All"); // Created By filter state

  // Multi-select delete state
  const {
    selectedIds: multiSelectIds,
    selectedCount: multiSelectCount,
    isAllSelected,
    isPartiallySelected,
    handleSelectionChange: handleMultiSelectChange,
    handleSelectAll,
    clearSelection: clearMultiSelection,
  } = useMultiSelect({ data: visibleData, idKey: "agentic_application_id" });
  const [showBulkDeleteModal, setShowBulkDeleteModal] = useState(false);
  const [bulkDeleteLoading, setBulkDeleteLoading] = useState(false);
  const handleAddMessage = (message, type) => {
    addMessage(message, type);
  };

  // Get user info from cookies for Created By filter
  const loggedInUserEmail = getEmailFromToken();
  const userName = getUserNameFromToken();
  const role = getRoleFromToken();
  const isAdmin = role?.toLowerCase() === "admin";

  const { fetchData, deleteData } = useFetch();
  const { getAgentsSearchByPageLimit, exportAgents, calculateDivs, deleteAgent: deleteAgentService } = useToolsAgentsService();
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

  const getAgentsDataWithTags = async (pageNumber, divsCount, tagsToUse, agentTypeToUse, createdByToUse = null) => {
    setLoading(true);
    try {
      const tagsParam = tagsToUse?.length > 0 ? tagsToUse : undefined;

      // Determine if we should use server-side type filtering (single type selected)
      const agentTypes = agentTypeToUse || [];
      const singleTypeFilter = agentTypes.length === 1 ? agentTypes[0] : undefined;

      // Use createdByToUse if provided, otherwise fall back to state
      const createdByValue = createdByToUse !== null ? createdByToUse : createdBy;
      const createdByEmail = createdByValue === "Me" ? loggedInUserEmail : createdByValue === "System" ? "system" : undefined;

      const response = await getAgentsSearchByPageLimit({
        page: pageNumber,
        limit: divsCount,
        search: "",
        agentic_application_type: singleTypeFilter, // Pass single type to API if applicable
        tags: tagsParam,
        created_by: createdByEmail,
      });
      let data = sanitizeAgentsResponse(response?.details);

      // Client-side filter for multiple types (API only supports single type)
      if (agentTypes.length > 1) {
        data = data.filter((agent) => agentTypes.includes(agent.agentic_application_type));
      }

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

  // Use the service-layer deleteAgent, which always uses array payload and bulk endpoint
  const deleteAgent = async (id, email, isAdmin = false) => {
    try {
      const payload = { user_email_id: email, is_admin: isAdmin };
      // Always use array, even for single delete
      const response = await deleteAgentService(payload, [id]);
      if (response && typeof response !== "string") {
        const statusMsg = response.status_message || response.message;
        if (statusMsg) {
          const hasAnyFailure = Array.isArray(response.results) && response.results.some((r) => r.is_delete === false);
          handleAddMessage(statusMsg, hasAnyFailure ? "error" : "success");
        }
      }
      return true;
    } catch (error) {
      handleError(error);
      return false;
    }
  };

  const handleSearch = async (searchValue, divsCount, pageNumber, tagsToUse = null, createdByToUse = null) => {
    setSearchTerm(searchValue || "");
    setPage(1);
    pageRef.current = 1;
    setVisibleData([]);
    setHasMore(true);
    setLoading(true);

    try {
      // Use provided tagsToUse or fall back to selectedTags state
      const tagsForSearch = tagsToUse !== null ? tagsToUse : selectedTags;
      const tagsParam = tagsForSearch?.length > 0 ? tagsForSearch : undefined;

      // Determine if we should use server-side type filtering (single type selected)
      const selectedTypes = selectedAgentTypeRef.current || [];
      const singleTypeFilter = selectedTypes.length === 1 ? selectedTypes[0] : undefined;

      // Use createdByToUse if provided, otherwise fall back to state
      const createdByValue = createdByToUse !== null ? createdByToUse : createdBy;
      const createdByEmail = createdByValue === "Me" ? loggedInUserEmail : createdByValue === "System" ? "system" : undefined;

      // Use the API endpoint for search with tag and type filtering
      const response = await getAgentsSearchByPageLimit({
        page: pageNumber,
        limit: divsCount,
        search: searchValue ? searchValue : "",
        agentic_application_type: singleTypeFilter, // Pass single type to API if applicable
        tags: tagsParam,
        created_by: createdByEmail,
      });
      let dataToSearch = sanitizeAgentsResponse(response?.details);

      // Client-side filter for multiple types (API only supports single type)
      if (selectedTypes.length > 1) {
        dataToSearch = dataToSearch.filter((agent) => selectedTypes.includes(agent.agentic_application_type));
      }

      // Setting the total count
      setTotalAgentCount(response.total_count || dataToSearch.length);

      // Update visibleData with the filtered data
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
  };

  const clearSearch = () => {
    setSearchTerm("");
    setSelectedTags([]);
    setSelectedAgentType([]);
    selectedAgentTypeRef.current = [];
    setCreatedBy("All");
    setVisibleData([]);
    setHasMore(true);
    const divsCount = calculateDivs(visibleAgentsContainerRef, 200, 128, 40);
    setPage(1);
    pageRef.current = 1;
    // Call getAgentsData with explicitly empty tags and empty agent type (matches handleRefresh)
    getAgentsDataWithTags(1, divsCount, [], []);
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
        !isLoadingMore &&
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
  }, [visibleAgentsContainerRef, hasMore, loading, isLoadingMore]);

  const handleScrollLoadMore = async () => {
    if (loader || isLoadingRef.current || !hasMore) return; // Prevent multiple calls or if no more data
    isLoadingRef.current = true;
    const nextPage = pageRef.current + 1;
    const divsCount = calculateDivs(visibleAgentsContainerRef, 200, 128, 40);
    try {
      setLoaderState(true);
      setIsLoadingMore(true);
      let newData = [];

      // Determine if we should use server-side type filtering (single type selected)
      const selectedTypes = selectedAgentTypeRef.current || [];
      const singleTypeFilter = selectedTypes.length === 1 ? selectedTypes[0] : undefined;

      // Pass created_by value based on filter selection
      const createdByEmail = createdBy === "Me" ? loggedInUserEmail : createdBy === "System" ? "system" : undefined;

      const res = await getAgentsSearchByPageLimit({
        page: nextPage,
        limit: divsCount,
        search: searchTerm,
        agentic_application_type: singleTypeFilter, // Pass single type to API if applicable
        tags: selectedTags?.length > 0 ? selectedTags : undefined,
        created_by: createdByEmail,
      });
      newData = sanitizeAgentsResponse(res?.details);

      // Client-side filter for multiple types (API only supports single type)
      if (selectedTypes.length > 1) {
        newData = newData.filter((item) => selectedTypes.includes(item.agentic_application_type));
      }

      if (newData.length > 0) {
        setVisibleData((prev) => {
          const updated = [...prev, ...newData];
          if (updated.length >= totalAgentCount) setHasMore(false);
          return updated;
        });
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
      setIsLoadingMore(false);
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
    setSelectedAgentType([]);
    selectedAgentTypeRef.current = [];
    setCreatedBy("All");
    setVisibleData([]);
    setHasMore(true);
    setPage(1);
    pageRef.current = 1;
    const divsCount = calculateDivs(visibleAgentsContainerRef, 200, 128, 40);
    // Call getAgentsData with explicitly empty tags and empty agent type
    getAgentsDataWithTags(1, divsCount, [], []);
  };

  const onPlusClick = () => {
    // only allow opening onboard when user has add permission for agents
    if (!canAddAgents) return;
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

  const handleFilter = async (selectedTagsParam, typesParam = null, createdByParam = null) => {
    setSelectedTags(selectedTagsParam);
    // If types parameter is provided, use it; otherwise use current ref value
    const typesToUse = typesParam !== null ? typesParam : selectedAgentTypeRef.current;
    if (typesParam !== null) {
      setSelectedAgentType(typesParam);
      selectedAgentTypeRef.current = typesParam;
    }
    // If createdBy parameter is provided, update state
    const createdByToUse = createdByParam !== null ? createdByParam : createdBy;
    if (createdByParam !== null) {
      setCreatedBy(createdByParam);
    }
    setPage(1);
    pageRef.current = 1;
    setVisibleData([]);
    setHasMore(true);

    // Trigger new API call with all filters
    const divsCount = calculateDivs(visibleAgentsContainerRef, 200, 128, 40);
    if (searchTerm.trim()) {
      // If there's a search term, use handleSearch with current search and filters
      await handleSearch(searchTerm, divsCount, 1, selectedTagsParam, createdByToUse);
    } else {
      // If no search term, fetch data with all filters
      await getAgentsDataWithTags(1, divsCount, selectedTagsParam, typesToUse, createdByToUse);
    }
  };

  const handleTypeFilter = async (e) => {
    const types = e.target.value; // Array of selected agent types
    setSelectedAgentType(types);
    selectedAgentTypeRef.current = types;
    setPage(1);
    pageRef.current = 1;
    setVisibleData([]);
    setHasMore(true);
    const divsCount = calculateDivs(visibleAgentsContainerRef, 200, 128, 40);

    // If no types selected, fetch normally with pagination (no type filter)
    if (!types || types.length === 0) {
      await getAgentsDataWithTags(1, divsCount, selectedTags, []);
      return;
    }

    setLoading(true);
    try {
      // If only one type is selected, use server-side filtering via API
      if (types.length === 1) {
        // Pass created_by value based on filter selection
        const createdByEmail = createdBy === "Me" ? loggedInUserEmail : createdBy === "System" ? "system" : undefined;
        const response = await getAgentsSearchByPageLimit({
          page: 1,
          limit: divsCount,
          search: searchTerm || "",
          agentic_application_type: types[0], // Pass single type to API
          tags: selectedTags?.length > 0 ? selectedTags : undefined,
          created_by: createdByEmail,
        });
        const sanitized = sanitizeAgentsResponse(response?.details);

        setAgentsList(sanitized);
        setVisibleData(sanitized);
        setTotalAgentCount(response.total_count || sanitized.length);
        // Check if more pages available
        setHasMore(sanitized.length >= divsCount);
      } else {
        // Multiple types selected - fetch larger dataset and filter client-side
        // API only supports single type, so we need to fetch all and filter
        // Pass created_by value based on filter selection
        const createdByEmail = createdBy === "Me" ? loggedInUserEmail : createdBy === "System" ? "system" : undefined;
        const response = await getAgentsSearchByPageLimit({
          page: 1,
          limit: 1000, // Fetch more to ensure we get all matching agents
          search: searchTerm || "",
          agentic_application_type: undefined,
          tags: selectedTags?.length > 0 ? selectedTags : undefined,
          created_by: createdByEmail,
        });
        let sanitized = sanitizeAgentsResponse(response?.details);

        // Filter by selected types client-side
        sanitized = sanitized.filter((agent) => types.includes(agent.agentic_application_type));

        setAgentsList(sanitized);
        setVisibleData(sanitized);
        setTotalAgentCount(sanitized.length);
        // Disable pagination when multi-type filter is active
        setHasMore(false);
      }
    } catch (error) {
      handleError(error, { customMessage: "Failed to filter agents by type" });
      setVisibleData([]);
      setTotalAgentCount(0);
      setHasMore(false);
    } finally {
      setLoading(false);
    }
  };
  // Handler for Created By dropdown - only updates state
  // API call is triggered by handleFilter via onTagsChange/onApply
  const handleCreatedByChange = (value) => {
    setCreatedBy(value);
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
      const userEmail = getEmailFromToken();
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

  // Bulk delete handler for multi-select
  const handleBulkDeleteAgents = async () => {
    if (multiSelectIds.length === 0) return;
    // Filter out items created by the current user (creator cannot delete own items)
    const currentEmail = (loggedInUserEmail || "").trim().toLowerCase();
    const ownItems = visibleData.filter((item) => multiSelectIds.includes(item.agentic_application_id) && (item.created_by || "").trim().toLowerCase() === currentEmail);
    const deletableIds = multiSelectIds.filter((id) => {
      const item = visibleData.find((d) => d.agentic_application_id === id);
      return !item || (item.created_by || "").trim().toLowerCase() !== currentEmail;
    });
    if (ownItems.length > 0) {
      addMessage(`${ownItems.length} agent(s) created by you were skipped. You cannot delete your own agents.`, "error");
    }
    if (deletableIds.length === 0) {
      clearMultiSelection();
      setShowBulkDeleteModal(false);
      return;
    }
    setBulkDeleteLoading(true);
    const userEmail = getEmailFromToken();
    const userRole = getRoleFromToken();
    const isAdmin = userRole?.toLowerCase() === "admin";
    try {
      const payload = {
        user_email_id: userEmail,
        is_admin: isAdmin,
        agent_ids: deletableIds,
      };
      const response = await deleteData(APIs.DELETE_AGENTS, payload);
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
    fetchAgents();
  };

  if (permissionsLoading) {
    return <Loader />;
  }

  return (
    <div className={"pageContainer"}>
      {(loading || exportLoading) && <Loader />}
      <SubHeader
        onSearch={(value) => {
          // Use named constants for magic numbers
          const AGENT_CARD_WIDTH = 200;
          const AGENT_CARD_HEIGHT = 128;
          const AGENT_CARD_MARGIN = 40;
          handleSearch(value, calculateDivs(visibleAgentsContainerRef, AGENT_CARD_WIDTH, AGENT_CARD_HEIGHT, AGENT_CARD_MARGIN), 1);
        }}
        onPlusClick={canAddAgents ? onPlusClick : null}
        showPlusButton={canAddAgents}
        selectedTags={selectedTags}
        heading={"Agents"}
        handleRefresh={handleRefresh}
        searchValue={searchTerm}
        clearSearch={clearSearch}
        showAgentTypeDropdown={true}
        agentTypes={agentTypesDropdown}
        selectedAgentType={selectedAgentType}
        handleTypeFilter={handleTypeFilter}
        showTypeDropdown={true}
        showTagsDropdown={true}
        availableTags={tags.map((tag) => tag.tag_name || tag)}
        selectedTagsForDropdown={selectedTags}
        onTagsChange={handleFilter}
        showCreatedByDropdown={true}
        createdBy={createdBy}
        onCreatedByChange={handleCreatedByChange}
        onSecondaryButtonClick={canExportAgents ? handleExportSelected : null}
        secondaryButtonLabel={canExportAgents ? "Export" : null}
        secondaryButtonDisabled={selectedAgentIds.length === 0}
        showSelectAll={canDeleteAgents && isAdmin && visibleData.length > 1}
        isAllSelected={isAllSelected}
        isPartiallySelected={isPartiallySelected}
        onSelectAll={handleSelectAll}
        selectedCount={multiSelectCount}
        onDeleteSelected={canDeleteAgents && isAdmin ? () => setShowBulkDeleteModal(true) : null}
      />

      {/* Display total count summary */}
      <SummaryLine visibleCount={visibleData.length} totalCount={totalAgentCount} />

      <div className="listWrapper" ref={visibleAgentsContainerRef}>
        {/* Only show DisplayCard1 when there's data to display */}
        {visibleData?.length > 0 && (
          <DisplayCard1
            data={visibleData}
            onCardClick={canReadAgents ? (name, item) => setEditAgentData(item) : null}
            showDeleteButton={false}
            showCheckbox={canDeleteAgents || canAddAgents || canExportAgents}
            onSelectionChange={(name, checked) => {
              handleMultiSelectChange(name, checked);
              if (canAddAgents || canExportAgents) {
                const agent = visibleData.find((a) => a.agentic_application_name === name);
                if (agent) handleAgentSelect(agent.agentic_application_id, checked);
              }
            }}
            cardNameKey="agentic_application_name"
            cardDescriptionKey="agentic_application_description"
            cardOwnerKey="created_by"
            cardCategoryKey="agentic_application_type"
            showButton={false}
            buttonIcon={<SVGIcons icon="message-square" width={20} height={16} color="var(--content-color)" />}
            className={styles.agentsList}
            contextType="agent"
            selectedIds={multiSelectIds}
            idKey="agentic_application_id"
            onCreateClick={canAddAgents ? onPlusClick : null}
            showCreateCard={false}
            hideActions={!canReadAgents}
            onShareClick={(item) => {
              setShareModalData(item);
              setShowShareModal(true);
            }}
          />
        )}
        {/* Display EmptyState when filters are active but no results */}
        {(searchTerm.trim() || selectedTags.length > 0 || selectedAgentType?.length > 0 || (createdBy && createdBy !== "All")) && visibleData.length === 0 && !loading && (
          <EmptyState
            filters={[
              ...selectedTags,
              ...(selectedAgentType || []).map((type) => {
                const agentTypeObj = agentTypesDropdown.find((a) => a.value === type);
                return agentTypeObj ? agentTypeObj.label : type;
              }),
              ...(createdBy === "Me" ? ["Created By: Me"] : []),
              ...(searchTerm.trim() ? [`Search: ${searchTerm}`] : []),
            ]}
            onClearFilters={clearSearch}
            onCreateClick={canAddAgents ? onPlusClick : null}
            createButtonLabel={canAddAgents ? "New Agent" : null}
          />
        )}
        {/* Display EmptyState when no data exists from backend (no filters applied) */}
        {!searchTerm.trim() && selectedTags.length === 0 && (!selectedAgentType || selectedAgentType.length === 0) && createdBy === "All" && visibleData.length === 0 && !loading && (
          <EmptyState
            message="No agents found"
            subMessage={canAddAgents ? "Get started by creating your first agent" : "No agents available"}
            onCreateClick={canAddAgents ? onPlusClick : null}
            createButtonLabel={canAddAgents ? "New Agent" : null}
            showClearFilter={false}
          />
        )}
        {/* Loading more indicator for pagination */}
        {isLoadingMore && <div className={styles.loadingMore}>Loading more...</div>}
      </div>

      {plusBtnClicked && <CreateAgent onClose={onOnboardClose} tags={tags} fetchAgents={fetchAgents} />}
      {editAgentData && (
        <div className={styles.updateAgentContainer}>
          <UpdateAgent
            onClose={handleUpdateAgentClose}
            agentData={editAgentData}
            tags={tags}
            agentsListData={agentsListData?.filter((agent) => agent?.agentic_application_type === REACT_AGENT)}
            fetchAgents={fetchAgents}
            searchTerm={searchTerm}
            readOnly={!hasPermission("update_access.agents")}
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

      <ShareModal
        show={showShareModal}
        onClose={() => setShowShareModal(false)}
        itemData={shareModalData}
        entityType="agent"
      />

      {showBulkDeleteModal && (
        <ConfirmationModal
          message={`Are you sure you want to delete ${multiSelectCount} selected agent(s)? This action cannot be undone.`}
          onConfirm={handleBulkDeleteAgents}
          setShowConfirmation={setShowBulkDeleteModal}
        />
      )}
    </div>
  );
};

export default AvailableAgents;
